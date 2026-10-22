"""Run inside docker --cpus=2 --memory=4g --memory-swap=4g; never an accuracy test."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['DMATE_GRAPH_NEXTGEN']='1'
from ocr_runtime import recognize_image,cgroup_memory


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--output',default='/results/resources.json')
    args=parser.parse_args()
    state=cgroup_memory()
    quota=Path('/sys/fs/cgroup/cpu.max').read_text().split() if Path('/sys/fs/cgroup/cpu.max').exists() else []
    constrained=bool(state and state[1]<=4*1024**3 and quota and quota[0]!='max' and int(quota[0])/int(quota[1])<=2)
    if not constrained: raise SystemExit('Run in a real 2 CPU / 4 GiB Linux cgroup')
    # Import the actual application to include its baseline memory. Probe a real
    # health request concurrently with each serial local-model inference.
    from app import app
    stop=threading.Event(); health=[]
    def probe():
        while not stop.is_set():
            begin=time.monotonic()
            with app.test_client() as client: response=client.get('/health')
            health.append({'ok':response.status_code==200,'seconds':time.monotonic()-begin})
            stop.wait(.25)
    thread=threading.Thread(target=probe,daemon=True);thread.start()
    rows=[]; preparation=None
    try:
        images=sorted(Path('tests/fixtures/original_ouc_20261021').glob('*.png'))
        # Explicit maintenance-only cache preparation; never hidden in HTTP
        # timing and never concurrent with another local-model worker.
        prepare_start=time.monotonic()
        prepared=recognize_image(images[0].read_bytes(),prepare_cache=True)
        preparation={'seconds':time.monotonic()-prepare_start,'stages':prepared['resource_metrics']}
        for iteration in range(2):
            for path in images:
                raw=path.read_bytes(); start=time.monotonic()
                result=recognize_image(raw)
                metrics=result['resource_metrics']
                rows.append({'image':path.name,'sha256':hashlib.sha256(raw).hexdigest(),'iteration':iteration,
                             'seconds':time.monotonic()-start,'stages':metrics,
                             'models_succeeded':all(m['status']=='ok' for m in metrics),
                             'safe_return':True})
    finally:
        stop.set();thread.join(timeout=2)
        peak_path=Path('/sys/fs/cgroup/memory.peak')
        report={'kind':'resource_measurement_not_accuracy','cpu_limit':2,'memory_limit_bytes':4*1024**3,
                'loading':'sequential_fresh_processes','co_resident_tested':False,'cache_preparation':preparation,
                'container_peak_bytes':int(peak_path.read_text()) if peak_path.exists() else None,
                'requests':rows,'model_success_rate':sum(r['models_succeeded'] for r in rows)/max(1,len(rows)),
                'health_probe_count':len(health),'health_success':all(h['ok'] for h in health),
                'health_max_seconds':max((h['seconds'] for h in health),default=None)}
        out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))
    # A successful fallback is not successful model inference.
    if not preparation or not all(m['status']=='ok' for m in preparation['stages']): return 2
    if not rows or not all(r['models_succeeded'] for r in rows) or not report['health_success']: return 2
    return 0


if __name__=='__main__': raise SystemExit(main())
