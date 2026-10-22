"""Serial short-lived model workers: native crashes/OOM stay outside Flask.

No Paddle import in this module. DocLayoutV3 and Small NEVER coexist in a worker.
Persistent loading is deliberately unsupported until a real container benchmark
justifies it. Uses stdlib + existing Pillow; no new production dependency.
"""
from __future__ import annotations
import fcntl
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from PIL import Image, ImageOps

MAX_RSS=1600*1024*1024
CGROUP_RESERVE=768*1024*1024
MAX_PIXELS=16_000_000


class OCRError(Exception): pass


def load_models():
    # Do not preload a model in the web process (or claim readiness).
    return {'text_ready':False,'formula_ready':False,'lazy':True}


def cgroup_memory():
    for used,limit in (('/sys/fs/cgroup/memory.current','/sys/fs/cgroup/memory.max'),
                       ('/sys/fs/cgroup/memory/memory.usage_in_bytes','/sys/fs/cgroup/memory/memory.limit_in_bytes')):
        try:
            a,b=Path(used).read_text().strip(),Path(limit).read_text().strip()
            return int(a),min(int(b),4*1024**3) if b!='max' else 4*1024**3
        except (OSError,ValueError): pass
    return None


def child_rss(pid):
    try:
        for line in Path(f'/proc/{pid}/status').read_text().splitlines():
            if line.startswith('VmRSS:'): return int(line.split()[1])*1024
    except OSError: pass
    if sys.platform=='darwin':
        try: return int(subprocess.check_output(['ps','-o','rss=','-p',str(pid)],timeout=1).strip())*1024
        except (OSError,ValueError,subprocess.SubprocessError): pass
    return 0


def run_worker(stage,image_path,output_path,*,layout_path=None,timeout=55,command=None):
    """Poll RSS/cgroup headroom, kill entire process group on timeout/pressure."""
    metric={'stage':stage,'peak_rss_bytes':0,'seconds':0.,'status':'failed'}
    start=time.monotonic(); proc=None
    state=cgroup_memory()
    if state and state[1]-state[0]<CGROUP_RESERVE+MAX_RSS:
        metric['status']='memory_admission_rejected'; return None,metric
    env={k:v for k,v in os.environ.items() if not k.endswith('API_KEY')}
    for key in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS'):
        env[key]='1'
    env['DMATE_FORMULA_ENABLED']='0'
    cmd=command or [sys.executable,str(Path(__file__).with_name('ocr_worker.py')),stage,str(image_path),str(output_path)]
    if layout_path and command is None: cmd.append(str(layout_path))
    try:
        proc=subprocess.Popen(cmd,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        while proc.poll() is None:
            rss=child_rss(proc.pid); metric['peak_rss_bytes']=max(rss,metric['peak_rss_bytes'])
            state=cgroup_memory()
            if rss>MAX_RSS or (state and state[0]>state[1]-CGROUP_RESERVE):
                metric['status']='memory_limit'; break
            if time.monotonic()-start>timeout:
                metric['status']='timeout'; break
            time.sleep(.05)
        if proc.poll() is None:
            os.killpg(proc.pid,signal.SIGKILL); proc.wait(timeout=3)
        elif proc.returncode==0 and Path(output_path).exists() and Path(output_path).stat().st_size<4*1024**2:
            result=json.loads(Path(output_path).read_text())
            metric['status']='ok'; return result,metric
        else:
            metric['status']='worker_failed'
            if Path(output_path).is_file() and Path(output_path).stat().st_size < 1024:
                try:
                    metric['error_type']=str(json.loads(Path(output_path).read_text()).get('worker_error',''))[:80]
                except (OSError,ValueError): pass
    except (OSError,ValueError,subprocess.SubprocessError): metric['status']='worker_failed'
    finally:
        if proc is not None and proc.poll() is None:
            os.killpg(proc.pid,signal.SIGKILL); proc.wait()
        metric['seconds']=round(time.monotonic()-start,3)
    return None,metric


def recognize_image(raw, *, prepare_cache=False):
    metrics=[]
    # File lock is shared by all gunicorn processes, unlike threading.Lock.
    lock_path=Path(tempfile.gettempdir())/'dmate-local-model.lock'
    with lock_path.open('a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise OCRError('图片识别繁忙，请稍后重试。') from None
        try:
            with tempfile.TemporaryDirectory(prefix='dmate-ocr-') as folder:
                root=Path(folder); image_path=root/'image.png'
                with Image.open(io.BytesIO(raw)) as original:
                    if original.width*original.height>MAX_PIXELS: raise OCRError('图片分辨率过大，请裁剪题目后重试。')
                    image=ImageOps.exif_transpose(original).convert('RGB'); image.thumbnail((2200,2200)); image.save(image_path)
                layout,lm=run_worker('layout',image_path,root/'layout.json',timeout=180 if prepare_cache else 45); metrics.append(lm)
                if layout is None: layout={'regions':[],'status':'unavailable'}
                (root/'layout.json').write_text(json.dumps(layout))
                text,tm=run_worker('text',image_path,root/'text.json',layout_path=root/'layout.json',timeout=180 if prepare_cache else 65); metrics.append(tm)
                if text is None:
                    text={'text':'','front_text':'','text_count':0,'formula_count':0,'review_regions':[],'warning':'题目文字未能完整识别'}
                text['layout']=layout; text['resource_metrics']=metrics
                if layout.get('status')!='ok': text['layout_degraded']=True
                return text
        finally: fcntl.flock(lock,fcntl.LOCK_UN)
