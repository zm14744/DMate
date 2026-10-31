"""Serial short-lived model workers: native crashes/OOM stay outside Flask.

No Paddle import in this module. DocLayoutV3 and Small NEVER coexist in a worker.
Persistent loading is deliberately unsupported until a real container benchmark
justifies it. Uses stdlib + existing Pillow; no new production dependency.
"""
from __future__ import annotations
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import uuid

MAX_RSS=1600*1024*1024
CGROUP_RESERVE=768*1024*1024
from image_upload_limits import MAX_IMAGE_PIXELS as MAX_PIXELS
MAX_RESULT_BYTES=4*1024**2
WORKER_RUN_ENV='DMATE_OCR_WORKER_RUN_ID'


class OCRError(Exception): pass


class ModelCacheError(OCRError):
    """No writable model cache; deliberately excludes local paths from errors."""


def normalize_text_result(result):
    """Preserve OCR text and uncertainty through single and batch readers.

    A nonempty string is not enough to certify an unambiguous read. Legacy
    readers can supply evidence, a warning or a review object without the new
    compact fields; retain that information instead of overwriting it.
    """
    value = dict(result) if isinstance(result, dict) else {}
    value['text'] = str(value.get('text') or '').strip()
    evidence = value.get('text_evidence')
    uncertain = evidence.get('uncertain') if isinstance(evidence, dict) else []
    count = value.get('review_count', 0)
    count = count if type(count) is int and count >= 0 else 0
    count = max(count, len(uncertain) if isinstance(uncertain, list) else 0)
    review = value.get('review') if isinstance(value.get('review'), dict) else {}
    reasons = []

    def add_reasons(items):
        if not isinstance(items, list):
            return
        for item in items:
            if isinstance(item, str) and item.strip():
                reason = item.strip()[:240]
                if reason not in reasons and len(reasons) < 4:
                    reasons.append(reason)

    add_reasons(value.get('review_reasons'))
    add_reasons(review.get('reasons'))
    rows = value.get('regions')
    incomplete_rows = False
    if isinstance(rows, list):
        rows = [normalize_text_result(row) for row in rows]
        value['regions'] = rows
        count = max(count, sum(row['review_count'] for row in rows))
        incomplete_rows = any(row['recognition_status'] != 'complete' for row in rows)
        for row in rows:
            add_reasons(row['review_reasons'])
    warning = value.get('warning')
    warning = warning.strip() if isinstance(warning, str) else ''
    empty_warning = '选区内未识别到文字，请调整范围后重试。'
    if warning and warning != empty_warning and warning != '；'.join(reasons):
        add_reasons([warning])
    needs_review = bool(count or reasons or review.get('required') is True
                        or value.get('recognition_status') in (
                            'partial', 'incomplete', 'uncertain', 'needs_review', 'review_required')
                        or incomplete_rows)
    if needs_review and not reasons:
        reasons.append('部分文字识别仍有未确认内容，请对照原图核对。')
    if value.get('recognition_status') in ('failed', 'error') or value.get('error'):
        status = 'failed'
    elif not value['text']:
        status = 'empty'
    else:
        status = 'partial' if needs_review else 'complete'
    value.update(review_count=count, review_reasons=reasons, recognition_status=status,
                 warning=('；'.join(reasons) if needs_review else
                          empty_warning if status == 'empty' else None))
    return value


def _probe_cache_directory(path):
    """Probe real writes, including PaddleX's independently mounted subdirs.

    os.access() alone is insufficient for read-only mounts and some container
    ACLs. These names follow paddlex/utils/cache.py and official_models.py.
    Only a newly created, empty probe file is removed.
    """
    for folder in (path, *(path/name for name in ('official_models','func_ret','locks','temp'))):
        folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        with tempfile.NamedTemporaryFile(prefix='.dmate-probe-',dir=folder) as probe:
            probe.write(b'1')
            probe.flush()


def configure_model_cache(env):
    """Choose a writable PaddleX cache before any Paddle/PaddleOCR import.

    PADDLE_PDX_CACHE_HOME is PaddleX's supported override. Preserve a usable
    explicit setting, then try DMate's own cache root and a user-specific temp
    cache. Neither HOME nor CODEX_HOME is modified. Return non-path diagnostics.
    """
    candidates=[]
    if env.get('PADDLE_PDX_CACHE_HOME'):
        candidates.append(('paddlex_configured',Path(env['PADDLE_PDX_CACHE_HOME']).expanduser()))
    if env.get('DMATE_MODEL_CACHE_DIR'):
        candidates.append(('dmate_configured',Path(env['DMATE_MODEL_CACHE_DIR']).expanduser()/'paddlex'))
    if env.get('XDG_CACHE_HOME'):
        candidates.append(('xdg_dmate',Path(env['XDG_CACHE_HOME']).expanduser()/'dmate'/'paddlex'))
    uid=str(os.getuid()) if hasattr(os,'getuid') else 'current-user'
    fallback=Path(tempfile.gettempdir())/f'dmate-model-cache-{uid}'
    candidates.append(('temporary',fallback/'paddlex'))
    failed=0; seen=set()
    for source,path in candidates:
        path=path.absolute()
        if str(path) in seen: continue
        seen.add(str(path))
        try:
            if source=='temporary':
                # Do not follow a shared /tmp name owned by another user.
                if fallback.is_symlink(): raise PermissionError('unsafe_cache_root')
                fallback.mkdir(parents=True,exist_ok=True,mode=0o700)
                if hasattr(os,'getuid') and fallback.stat().st_uid!=os.getuid():
                    raise PermissionError('unsafe_cache_owner')
            _probe_cache_directory(path)
        except (OSError,ValueError):
            failed+=1
            continue
        env['PADDLE_PDX_CACHE_HOME']=str(path)
        env.setdefault('PADDLE_PDX_MODEL_SOURCE','BOS')
        return {'source':source,'fallback':bool(failed),'status':'ready'}
    raise ModelCacheError('model_cache_unavailable')


def load_models():
    # Do not preload a model in the web process (or claim readiness).
    return {'text_ready':False,'formula_ready':False,'lazy':True}


def _reclaimable_file_bytes(values,inactive_key):
    """Conservative file-cache allowance from Linux memory.stat types.

    Kernel documentation distinguishes file (including shmem), file_mapped,
    file_dirty and file_writeback from the active/inactive LRU *list* counters:
    https://docs.kernel.org/admin-guide/cgroup-v2.html#memory-interface-files
    Subtract protected categories even when they overlap: that underestimates
    reclaimable cache rather than treating mapped/dirty/tmpfs pages as free.
    No slab or anonymous memory is discounted. On older/incomplete stats retain
    the former inactive-file fallback, with invalid/negative counters ignored.
    """
    fields=('file','shmem','file_mapped','file_dirty','file_writeback')
    try:
        counters=[int(values[key]) for key in fields]
        if all(value>=0 for value in counters):
            return max(0,counters[0]-sum(counters[1:]))
    except (KeyError,TypeError,ValueError):
        pass
    try:
        return max(0,int(values.get(inactive_key,0)))
    except (TypeError,ValueError):
        return 0


def cgroup_memory():
    for used,limit,stats,key in (('/sys/fs/cgroup/memory.current','/sys/fs/cgroup/memory.max',
                                  '/sys/fs/cgroup/memory.stat','inactive_file'),
                                 ('/sys/fs/cgroup/memory/memory.usage_in_bytes','/sys/fs/cgroup/memory/memory.limit_in_bytes',
                                  '/sys/fs/cgroup/memory/memory.stat','total_inactive_file')):
        try:
            a,b=Path(used).read_text().strip(),Path(limit).read_text().strip()
            current=int(a)
            try:
                values=dict(line.split() for line in Path(stats).read_text().splitlines())
                # Clean, unmapped cached model files remain reclaimable even
                # after repeated reads move them to active_file. Charging that
                # cache as live model memory eventually rejects every image.
                current=max(0,current-_reclaimable_file_bytes(values,key))
            except (OSError,ValueError):
                pass
            return current,min(int(b),4*1024**3) if b!='max' else 4*1024**3
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


def write_worker_result(stage,output_path,result):
    """Publish bytes atomically, then return this invocation's completion receipt.

    The worker places the receipt in its audit only after its output phase has
    succeeded. No model, input text, or credentials are placed in this receipt.
    """
    if not isinstance(result,dict) or 'worker_error' in result:
        raise ValueError('invalid_worker_result')
    payload=json.dumps(result,ensure_ascii=False,allow_nan=False).encode('utf-8')
    if not 0<len(payload)<MAX_RESULT_BYTES: raise ValueError('worker_result_capacity')
    path=Path(output_path); temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix=path.name+'.',suffix='.tmp',delete=False) as stream:
            temporary=Path(stream.name)
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if temporary is not None and temporary.exists(): temporary.unlink()
    return {'run_id':os.environ.get(WORKER_RUN_ENV),'pid':os.getpid(),'stage':stage,
            'output_bytes':len(payload),'output_sha256':hashlib.sha256(payload).hexdigest(),
            'finished_monotonic':time.monotonic()}


def _result_file_identity(path):
    try:
        info=Path(path).stat()
        return (info.st_dev,info.st_ino,info.st_mtime_ns,info.st_size)
    except OSError: return None


def _completed_worker_result(path,audit,*,stage,run_id,pid,started,deadline,previous_file):
    """Require a full current-process result; an old `complete` flag is insufficient."""
    if not audit or audit.get('stage')!=stage or audit.get('current',{}).get('phase')!='complete':
        raise ValueError('worker_completion_not_confirmed')
    receipt=audit.get('completion')
    if not isinstance(receipt,dict): raise ValueError('worker_completion_receipt_missing')
    if (receipt.get('run_id')!=run_id or type(receipt.get('pid')) is not int
            or receipt['pid']!=pid or receipt.get('stage')!=stage):
        raise ValueError('worker_completion_identity_mismatch')
    events=audit.get('events')
    if (not isinstance(events,list) or not events or events[-1].get('phase')!='output'
            or events[-1].get('status')!='ok'):
        raise ValueError('worker_output_phase_not_finished')
    finished=receipt.get('finished_monotonic')
    if type(finished) not in (int,float) or not math.isfinite(finished) or finished<started:
        raise ValueError('worker_completion_time_invalid')
    if finished>deadline: raise ValueError('worker_completion_after_deadline')
    identity=_result_file_identity(path)
    if identity is None or identity==previous_file: raise ValueError('worker_result_missing_or_stale')
    if type(receipt.get('output_bytes')) is not int or not 0<receipt['output_bytes']<MAX_RESULT_BYTES:
        raise ValueError('worker_result_capacity')
    with Path(path).open('rb') as stream: payload=stream.read(MAX_RESULT_BYTES)
    if (len(payload)!=receipt['output_bytes'] or hashlib.sha256(payload).hexdigest()!=receipt.get('output_sha256')):
        raise ValueError('worker_result_digest_mismatch')
    def invalid_constant(value): raise ValueError('worker_result_nonfinite')
    result=json.loads(payload.decode('utf-8'),parse_constant=invalid_constant)
    if not isinstance(result,dict) or 'worker_error' in result:
        raise ValueError('invalid_worker_result')
    if stage=='layout' and (result.get('model')!='PP-DocLayoutV3'
            or result.get('status')!='ok' or not isinstance(result.get('regions'),list)):
        raise ValueError('worker_result_stage_mismatch')
    if stage=='text' and (not isinstance(result.get('text'),str)
            or not isinstance(result.get('text_evidence'),dict)):
        raise ValueError('worker_result_stage_mismatch')
    return result,receipt


def _reap_worker(proc):
    """Bound cleanup by the existing reap allowance; never wait for native atexit."""
    started=time.monotonic(); signalled=False
    if proc.poll() is None:
        try:
            os.killpg(proc.pid,signal.SIGKILL); signalled=True
        except ProcessLookupError: pass
    code=proc.wait(timeout=3)
    return {'cleanup_status':'terminated_and_reaped' if signalled else 'already_exited',
            'cleanup_seconds':round(time.monotonic()-started,6),
            'cleanup_signal_sent':signalled,'process_reaped':True,'process_returncode':code}


def run_worker(stage,image_path,output_path,*,layout_path=None,timeout=55,command=None):
    """Poll RSS/cgroup headroom, kill entire process group on timeout/pressure."""
    from ocr_worker_audit import audit_path,read_audit
    metric={'stage':stage,'peak_rss_bytes':0,'rss_observed':False,'seconds':0.,'status':'failed'}
    start=time.monotonic(); proc=None; phase_peaks={}; accepted=None
    run_id=uuid.uuid4().hex; deadline=start+timeout
    previous_file=_result_file_identity(output_path)
    sidecar=audit_path(output_path)
    state=cgroup_memory()
    if state and state[1]-state[0]<CGROUP_RESERVE+MAX_RSS:
        metric.update(status='memory_admission_rejected',error_kind='memory_admission_rejected',
                      memory_admission={'working_set_bytes':state[0],'budget_bytes':state[1],
                                        'required_headroom_bytes':CGROUP_RESERVE+MAX_RSS})
        return None,metric
    env={k:v for k,v in os.environ.items() if not k.endswith('API_KEY')}
    for key in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS'):
        env[key]='1'
    env['DMATE_FORMULA_ENABLED']='0'
    env[WORKER_RUN_ENV]=run_id
    try:
        metric['model_cache']=configure_model_cache(env)
    except ModelCacheError:
        metric.update(status='cache_unavailable',error_type='ModelCacheError',error_kind='model_cache_unavailable')
        metric['seconds']=round(time.monotonic()-start,3)
        return None,metric
    cmd=command or [sys.executable,str(Path(__file__).with_name('ocr_worker.py')),stage,str(image_path),str(output_path)]
    if layout_path and command is None: cmd.append(str(layout_path))
    try:
        proc=subprocess.Popen(cmd,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        while proc.poll() is None:
            rss=child_rss(proc.pid); metric['peak_rss_bytes']=max(rss,metric['peak_rss_bytes'])
            metric['rss_observed']=metric['rss_observed'] or rss>0
            audit=read_audit(sidecar)
            current=(audit or {}).get('current',{'phase':'startup','pass_index':0})
            phase=current['phase']; pass_index=current.get('pass_index',0)
            key=(phase,pass_index)
            observed=phase_peaks.setdefault(key,{'phase':phase,'pass_index':pass_index,
                'pass_kind':current.get('pass_kind'),'peak_rss_bytes':0,'rss_observed':False,'samples':0})
            observed['peak_rss_bytes']=max(observed['peak_rss_bytes'],rss)
            observed['rss_observed']=observed['rss_observed'] or rss>0
            observed['samples']+=1
            state=cgroup_memory()
            if rss>MAX_RSS or (state and state[0]>state[1]-CGROUP_RESERVE):
                metric.update(status='memory_limit',phase=phase,pass_index=pass_index,
                              limit_reason='worker_rss' if rss>MAX_RSS else 'cgroup_headroom')
                if state: metric['memory_at_termination']={'working_set_bytes':state[0],'budget_bytes':state[1]}
                break
            # Result publication completes useful work. Third-party native
            # teardown can hang afterwards, so do not require process exit.
            # Resource checks retain priority, and the receipt must show that
            # output completed inside the original wall-clock allowance.
            if phase=='complete':
                try:
                    accepted,receipt=_completed_worker_result(output_path,audit,stage=stage,
                        run_id=run_id,pid=proc.pid,started=start,deadline=deadline,previous_file=previous_file)
                except (OSError,ValueError,TypeError,AttributeError) as exc:
                    metric['result_validation_error']=(str(exc) if isinstance(exc,ValueError)
                        and str(exc).startswith('worker_') else 'worker_result_invalid_json')
                else:
                    metric.update(result_complete=True,completion_validated=True,phase='complete',
                                  result_completion_seconds=round(receipt['finished_monotonic']-start,6),
                                  result_received_before_exit=proc.poll() is None)
                    break
            if time.monotonic()-start>timeout:
                metric.update(status='timeout',phase=phase,pass_index=pass_index,limit_reason='wall_time'); break
            time.sleep(.05)
        if accepted is not None:
            # A native failure observed before our cleanup is not converted
            # into success merely because a file exists.
            code=proc.poll()
            if code not in (None,0):
                accepted=None
                metric.update(status='worker_failed',error_kind='native_worker_failure')
            else:
                metric.update(_reap_worker(proc))
                if (metric['process_returncode']!=0
                        and not (metric['process_returncode']==-signal.SIGKILL
                                 and metric['cleanup_signal_sent'])):
                    accepted=None
                    metric.update(status='worker_failed',error_kind='native_worker_failure')
                else:
                    metric.pop('result_validation_error',None)
                    metric['status']='ok'; return accepted,metric
        elif proc.poll() is None:
            metric.update(_reap_worker(proc))
        elif proc.returncode==0:
            try:
                result,receipt=_completed_worker_result(output_path,read_audit(sidecar),stage=stage,
                    run_id=run_id,pid=proc.pid,started=start,deadline=deadline,previous_file=previous_file)
            except (OSError,ValueError,TypeError,AttributeError) as exc:
                metric.update(status='worker_failed',error_kind='worker_result_unconfirmed',
                              result_validation_error=(str(exc) if isinstance(exc,ValueError)
                              and str(exc).startswith('worker_') else 'worker_result_invalid_json'))
            else:
                metric.update(_reap_worker(proc),status='ok',result_complete=True,completion_validated=True,
                              phase='complete',result_received_before_exit=False,
                              result_completion_seconds=round(receipt['finished_monotonic']-start,6))
                return result,metric
        else:
            metric['status']='worker_failed'
            if Path(output_path).is_file() and Path(output_path).stat().st_size < 1024:
                try:
                    failure=json.loads(Path(output_path).read_text())
                    if isinstance(failure,dict):
                        for source,target in (('worker_error','error_type'),('error_kind','error_kind'),('phase','phase')):
                            value=failure.get(source)
                            if isinstance(value,str) and value.replace('_','').isalnum():
                                metric[target]=value[:80]
                except (OSError,ValueError): pass
            if 'error_kind' not in metric:
                metric['error_kind']='native_worker_failure' if proc.returncode and proc.returncode<0 else 'worker_failed'
    except (OSError,ValueError,subprocess.SubprocessError): metric['status']='worker_failed'
    finally:
        if proc is not None and proc.poll() is None:
            try: metric.update(_reap_worker(proc))
            except (OSError,subprocess.SubprocessError):
                metric.update(cleanup_status='reap_failed',process_reaped=False)
        if proc is not None and proc.poll() is not None:
            metric.setdefault('process_returncode',proc.returncode)
            metric.setdefault('process_reaped',True)
            metric.setdefault('cleanup_status','already_exited')
            metric.setdefault('cleanup_seconds',0.)
        metric['seconds']=round(time.monotonic()-start,3)
        metric['phase_peaks']=list(phase_peaks.values())
        audit=read_audit(sidecar)
        if audit is not None: metric['audit']=audit
    return None,metric


def recognize_image(raw, *, prepare_cache=False, text_only=False, timeout_seconds=None):
    """Use only the Small text worker for pure-text / lightweight panel uploads.

    The existing standard mode retains both layout and text worker stages.
    Skipping the 45-second layout worker must not affect other OCR callers.
    """
    metrics=[]
    # The fast upload path has a strict OCR budget; standard OCR is unchanged.
    deadline = (time.monotonic() + max(.1, float(timeout_seconds))
                if timeout_seconds is not None else None)
    def worker_seconds(default):
        if deadline is None:
            return default
        return max(.1, min(default, deadline - time.monotonic() - .12))
    # File lock is shared by all gunicorn processes, unlike threading.Lock.
    lock_path=Path(tempfile.gettempdir())/'dmate-local-model.lock'
    with lock_path.open('a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise OCRError('图片识别繁忙，请稍后重试。') from None
        try:
            with tempfile.TemporaryDirectory(prefix='dmate-ocr-') as folder:
                root=Path(folder); text_path=root/'canonical.png'; layout_image_path=root/'layout.png'
                from image_evidence import decode_document_image
                try:
                    image=decode_document_image(raw,max_pixels=MAX_PIXELS)
                except (ValueError,TypeError):
                    raise OCRError('图片无法读取或分辨率过大，请检查图片后重试') from None
                canonical_size=list(image.size)
                # The detector budgets its own intermediate tensor. Preserve
                # all canonical source pixels for recognition crops instead
                # of feeding both models the layout thumbnail.
                image.save(text_path)
                if text_only:
                    # Fast text-only scans must not resize/re-encode a second
                    # image for a layout model that is never invoked.
                    layout_size=canonical_size[:]
                else:
                    layout_image=image.copy(); layout_image.thumbnail((2200,2200))
                    layout_size=list(layout_image.size); layout_image.save(layout_image_path)
                    layout_image.close()
                image.close()
                if text_only:
                    # No PP-DocLayoutV3 inference and no extra image-reader.
                    # A genuinely empty region list tells the Small worker to
                    # retain the entire OCR text instead of partitioning it.
                    layout = {'regions': [], 'status': 'not_run', 'reason': 'text_only_fast_path'}
                    metrics.append({'stage': 'layout', 'status': 'skipped',
                                    'worker_started': False, 'seconds': 0.})
                else:
                    layout,lm=run_worker('layout',layout_image_path,root/'layout.json',
                                         timeout=worker_seconds(180 if prepare_cache else 45))
                    metrics.append(lm)
                    if layout is None: layout={'regions':[],'status':'unavailable'}
                (root/'layout.json').write_text(json.dumps(layout))
                if deadline is not None and deadline - time.monotonic() < .25:
                    text = None
                    tm = {'stage': 'text', 'status': 'timeout',
                          'seconds': 0., 'worker_started': False}
                else:
                    text,tm=run_worker('text',text_path,root/'text.json',
                                       layout_path=root/'layout.json',
                                       timeout=worker_seconds(180 if prepare_cache else 65))
                metrics.append(tm)
                if text is None:
                    text={'text':'','front_text':'','text_count':0,'formula_count':0,'review_regions':[],'warning':'题目文字未能完整识别'}
                text['layout']=layout; text['resource_metrics']=metrics
                text['image_views']={'canonical_size':canonical_size,'layout_size':layout_size,
                    'text_size':canonical_size,'layout_coordinate_space':'canonical_normalized_0_1',
                    'text_coordinate_space':'canonical_image_pixels',
                    'layout_to_canonical_scale':[canonical_size[0]/layout_size[0],canonical_size[1]/layout_size[1]],
                    'text_to_original_1000_scale':[1000/canonical_size[0],1000/canonical_size[1]]}
                if layout.get('status')!='ok' and not text_only:
                    text['layout_degraded']=True
                if text_only:
                    text['text_only_fast_path'] = True
                return normalize_text_result(text)
        finally: fcntl.flock(lock,fcntl.LOCK_UN)


def recognize_text_regions(raw, regions, *, timeout_seconds=90):
    """Recognize numbered, masked crops in order with ONE isolated Small worker.

    No fixed number-of-frames limit. Time, memory and output-size guards still
    apply; operational failures are errors, never successful empty OCR results.
    """
    from graph_region import crop_region, validate_text_regions
    regions = validate_text_regions(regions)
    deadline = time.monotonic() + timeout_seconds
    lock_path = Path(tempfile.gettempdir()) / 'dmate-local-model.lock'
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise OCRError('图片识别繁忙，请稍后重试。') from None
        try:
            with tempfile.TemporaryDirectory(prefix='dmate-text-regions-') as folder:
                root = Path(folder); files = []
                from image_evidence import decode_document_image
                with decode_document_image(raw, max_pixels=MAX_PIXELS).convert('RGB') as photo:
                    for region in regions:
                        if time.monotonic() >= deadline:
                            raise OCRError('文字选区处理超时，请重试。')
                        path = root / (str(region['id']) + '.png')
                        path.write_bytes(crop_region(raw, region['polygon'], _photo=photo))
                        files.append({'id': region['id'], 'path': str(path)})
                plan = root / 'regions.json'
                plan.write_text(json.dumps({'text_region_files': files}))
                result, metric = run_worker('text', files[0]['path'], root / 'text.json',
                                            layout_path=plan, timeout=max(.1, deadline-time.monotonic()))
                if result is None:
                    status = metric.get('status', 'worker_failed')
                    message = {'timeout': '文字识别超时，请重试。',
                               'memory_admission_rejected': '服务器识别资源繁忙，请稍后重试。',
                               'memory_limit': '文字识别内存不足，请缩小选区后重试。',
                               'cache_unavailable': '文字识别模型缓存不可用，请检查服务配置。'}
                    raise OCRError(message.get(status, '文字识别模型启动或运行失败，请稍后重试。'))
                if ([row.get('id') for row in result.get('regions', [])] !=
                        [row['id'] for row in regions]):
                    raise OCRError('文字识别返回的框编号不匹配，请重试。')
                result['resource_metrics'] = [metric]
                return normalize_text_result(result)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
