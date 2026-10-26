"""Run inside docker --cpus=2 --memory=4g --memory-swap=4g; never an accuracy test."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ocr_runtime import recognize_image


def measured_cgroup_limits(root=Path('/sys/fs/cgroup')):
    """Read the hard container limits, never the application's capped budget."""
    try:
        memory=(root/'memory.max').read_text().strip()
        quota,period=(root/'cpu.max').read_text().split()
        memory_limit=None if memory=='max' else int(memory)
        cpu_limit=None if quota=='max' else int(quota)/int(period)
    except (OSError,ValueError,ZeroDivisionError):
        return {'valid':False,'memory_limit_bytes':None,'cpu_limit':None}
    return {'valid':memory_limit==4*1024**3 and cpu_limit==2,
            'memory_limit_bytes':memory_limit,'cpu_limit':cpu_limit}


def health_succeeded(observations):
    return bool(observations) and all(row.get('ok') is True for row in observations)


def native_synthetic_document():
    """A reproducible 12MP stress input; no private image or reference answer."""
    from PIL import Image,ImageDraw,ImageFont
    image=Image.new('RGB',(4096,3072),'white')
    draw=ImageDraw.Draw(image)
    for left in range(0,image.width,32):
        shade=170+round(85*left/(image.width-1))
        draw.rectangle((left,0,left+31,image.height),fill=(shade,shade,shade))
    try:font=ImageFont.truetype('DejaVuSans.ttf',36)
    except OSError:font=ImageFont.load_default()
    draw.text((180,120),'SYNTHETIC RESOURCE TEST: vertices and weighted edges',fill='black',font=font)
    for column in range(2):
        offset=240+column*1900
        points=[(offset+200,900),(offset+1200,900),(offset+200,1900),(offset+1200,1900)]
        for a,b in ((0,1),(0,2),(0,3),(1,2),(1,3),(2,3)):
            draw.line((*points[a],*points[b]),fill=(25,45,120),width=5)
            x=(points[a][0]+points[b][0])//2;y=(points[a][1]+points[b][1])//2
            draw.text((x+15,y+15),str(a+b+1),fill='black',font=font)
        for index,(x,y) in enumerate(points):
            draw.ellipse((x-24,y-24,x+24,y+24),fill='white',outline='black',width=4)
            draw.text((x+32,y-48),chr(97+index),fill='black',font=font)
    output=io.BytesIO();image.save(output,format='PNG');image.close()
    return output.getvalue()


def model_stages_succeeded(metrics):
    return (isinstance(metrics,list) and {m.get('stage') for m in metrics}=={'layout','text'}
            and all(m.get('status')=='ok' and m.get('rss_observed') is True for m in metrics))


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--output',default='/results/resources.json')
    args=parser.parse_args()
    limits=measured_cgroup_limits()
    if not limits['valid']: raise SystemExit('Run in a real 2 CPU / 4 GiB Linux cgroup')
    os.environ['DMATE_GRAPH_NEXTGEN']='1'
    # Import the actual application to include its baseline memory. Probe a real
    # health request concurrently with each serial local-model inference.
    from app import app
    stop=threading.Event(); health=[]
    def probe():
        while not stop.is_set():
            begin=time.monotonic()
            try:
                with app.test_client() as client: response=client.get('/health')
                health.append({'ok':response.status_code==200,'seconds':time.monotonic()-begin})
            except Exception as exc:
                health.append({'ok':False,'seconds':time.monotonic()-begin,'error_type':type(exc).__name__})
            stop.wait(.25)
    thread=threading.Thread(target=probe,daemon=True);thread.start()
    rows=[]; preparation=None
    try:
        images=sorted(Path('tests/fixtures/original_ouc_20261021').glob('*.png'))
        if not images:raise RuntimeError('public_resource_fixtures_missing')
        cases=[(path.name,path.read_bytes(),'existing_public_fixture') for path in images]
        cases.append(('synthetic_native_12mp.png',native_synthetic_document(),'generated_resource_only'))
        # Explicit maintenance-only cache preparation; never hidden in HTTP
        # timing and never concurrent with another local-model worker.
        prepare_start=time.monotonic()
        prepared=recognize_image(images[0].read_bytes(),prepare_cache=True)
        preparation={'seconds':time.monotonic()-prepare_start,'stages':prepared['resource_metrics']}
        for iteration in range(2):
            for name,raw,source in cases:
                start=time.monotonic()
                result=recognize_image(raw)
                metrics=result['resource_metrics']
                rows.append({'image':name,'source':source,'sha256':hashlib.sha256(raw).hexdigest(),'iteration':iteration,
                             'seconds':time.monotonic()-start,'stages':metrics,
                             'models_succeeded':model_stages_succeeded(metrics),
                             'safe_return':True})
    finally:
        stop.set();thread.join(timeout=2)
        peak_path=Path('/sys/fs/cgroup/memory.peak')
        report={'kind':'resource_measurement_not_accuracy','cpu_limit':limits['cpu_limit'],
                'memory_limit_bytes':limits['memory_limit_bytes'],'hard_limits_observed':True,
                'loading':'sequential_fresh_processes','co_resident_tested':False,'cache_preparation':preparation,
                'container_peak_bytes':int(peak_path.read_text()) if peak_path.exists() else None,
                'requests':rows,'model_success_rate':sum(r['models_succeeded'] for r in rows)/max(1,len(rows)),
                'health_probe_count':len(health),'health_success':health_succeeded(health),
                'health_max_seconds':max((h['seconds'] for h in health),default=None)}
        out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))
    # A successful fallback is not successful model inference.
    if not preparation or not model_stages_succeeded(preparation['stages']): return 2
    if not rows or not all(r['models_succeeded'] for r in rows) or not report['health_success']: return 2
    return 0


if __name__=='__main__': raise SystemExit(main())
