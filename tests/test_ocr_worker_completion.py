"""Real subprocess completion receipts; no model, image, network or cache download.

The principal regression publishes a full result, marks the output phase
complete, then hangs forever in a simulated native runtime teardown.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

import ocr_runtime
from ocr_worker_audit import audit_path,read_audit


ROOT=Path(__file__).resolve().parents[1]
LAYOUT={'model':'PP-DocLayoutV3','status':'ok','regions':[]}
TEXT={'text':'测试题干 x₅','front_text':'测试题干 x₅','text_evidence':{
    'body':[],'graph_labels':[],'noise':[],'uncertain':[],
    'image_size':[20,20],'coordinate_space':'canonical_image_pixels'}}

WORKER=r'''
import hashlib,json,os,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from ocr_runtime import WORKER_RUN_ENV,write_worker_result
from ocr_worker_audit import WorkerAudit
path,mode,stage=Path(sys.argv[2]),sys.argv[3],sys.argv[4]
if mode=='stale_exit':
    raise SystemExit(0)
audit=WorkerAudit(path,stage)
if mode=='never_complete':
    with audit.phase('output'):
        path.write_text('{"regions":',encoding='utf-8')
    time.sleep(30)
    raise SystemExit(0)
result=({'model':'PP-DocLayoutV3','status':'ok','regions':[]} if stage=='layout' else
        {'text':'测试题干 x₅','front_text':'测试题干 x₅','text_evidence':{
         'body':[],'graph_labels':[],'noise':[],'uncertain':[],
         'image_size':[20,20],'coordinate_space':'canonical_image_pixels'}})
if mode=='wrong_payload_stage':result={'text':'wrong stage','text_evidence':{}}
with audit.phase('output'):
    if mode=='reuse_stale_file':
        raw=path.read_bytes()
        receipt={'run_id':os.environ[WORKER_RUN_ENV],'pid':os.getpid(),'stage':stage,
                 'output_bytes':len(raw),'output_sha256':hashlib.sha256(raw).hexdigest(),
                 'finished_monotonic':time.monotonic()}
    else:
        receipt=write_worker_result(stage,path,result)
if mode=='wrong_run':receipt['run_id']='previous-invocation'
if mode=='wrong_pid':receipt['pid']=os.getpid()+1
if mode=='wrong_stage':receipt['stage']='text'
if mode=='wrong_audit_stage':audit.data['stage']='text'
if mode=='wrong_digest':receipt['output_sha256']='0'*64
if mode=='wrong_size':receipt['output_bytes']+=1
if mode=='late_completion':receipt['finished_monotonic']=time.monotonic()+60
if mode=='old_completion':receipt['finished_monotonic']=time.monotonic()-60
if mode=='partial':
    raw=b'{"regions":'
    path.write_bytes(raw)
    receipt.update(output_bytes=len(raw),output_sha256=hashlib.sha256(raw).hexdigest())
if mode=='worker_error':
    raw=b'{"worker_error":"RuntimeError"}'
    path.write_bytes(raw)
    receipt.update(output_bytes=len(raw),output_sha256=hashlib.sha256(raw).hexdigest())
if mode=='output_phase_failed':audit.data['events'][-1]['status']='failed'
if mode!='missing_receipt':audit.data['completion']=receipt
audit.set_phase('output' if mode=='wrong_phase' else 'complete')
if mode=='native_failure':os._exit(7)
if mode in ('hang_after_complete','partial','wrong_digest'):
    time.sleep(30)
'''


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch,tmp_path):
    monkeypatch.setenv('DMATE_MODEL_CACHE_DIR',str(tmp_path/'cache'))
    monkeypatch.delenv('PADDLE_PDX_CACHE_HOME',raising=False)
    monkeypatch.setattr(ocr_runtime,'cgroup_memory',lambda:None)
    spawned=[]
    original=subprocess.Popen
    def capture(*args,**kwargs):
        proc=original(*args,**kwargs)
        spawned.append(proc)
        return proc
    monkeypatch.setattr(ocr_runtime.subprocess,'Popen',capture)
    yield spawned
    for proc in spawned:
        if proc.poll() is None:
            os.killpg(proc.pid,signal.SIGKILL)
        proc.wait(timeout=3)


def run(tmp_path,mode,*,stage='layout',timeout=.8):
    output=tmp_path/'result.json'
    return ocr_runtime.run_worker(stage,'unused-image',output,timeout=timeout,
        command=[sys.executable,'-c',WORKER,str(ROOT),str(output),mode,stage])


@pytest.mark.parametrize('stage,expected',[('layout',LAYOUT),('text',TEXT)])
def test_complete_result_is_received_before_hanging_native_cleanup(tmp_path,isolated_runtime,stage,expected):
    result,metric=run(tmp_path,'hang_after_complete',stage=stage,timeout=2.)
    assert result==expected and metric['status']=='ok'
    assert metric['completion_validated'] is True and metric['result_complete'] is True
    assert metric['result_received_before_exit'] is True
    assert 0<metric['result_completion_seconds']<metric['seconds']<1.
    assert metric['cleanup_status']=='terminated_and_reaped'
    assert metric['process_reaped'] is True and metric['process_returncode']==-signal.SIGKILL
    assert isolated_runtime[-1].poll()==-signal.SIGKILL
    receipt=metric['audit']['completion']
    assert receipt['pid']==isolated_runtime[-1].pid and receipt['stage']==stage
    assert hashlib.sha256((tmp_path/'result.json').read_bytes()).hexdigest()==receipt['output_sha256']
    assert '测试题干' not in json.dumps(metric,ensure_ascii=False)


def test_normal_clean_exit_uses_same_bound_receipt(tmp_path,monkeypatch,isolated_runtime):
    capture=ocr_runtime.subprocess.Popen
    def already_exited(*args,**kwargs):
        proc=capture(*args,**kwargs)
        proc.wait(timeout=3)
        return proc
    monkeypatch.setattr(ocr_runtime.subprocess,'Popen',already_exited)
    result,metric=run(tmp_path,'normal',timeout=2.)
    assert result==LAYOUT and metric['status']=='ok'
    assert metric['result_received_before_exit'] is False
    assert metric['process_returncode']==0 and metric['cleanup_status']=='already_exited'


@pytest.mark.parametrize('mode,reason',[
    ('wrong_run','worker_completion_identity_mismatch'),
    ('wrong_pid','worker_completion_identity_mismatch'),
    ('wrong_stage','worker_completion_identity_mismatch'),
    ('wrong_audit_stage','worker_completion_not_confirmed'),
    ('wrong_phase','worker_completion_not_confirmed'),
    ('missing_receipt','worker_completion_receipt_missing'),
    ('wrong_digest','worker_result_digest_mismatch'),
    ('wrong_size','worker_result_digest_mismatch'),
    ('partial','worker_result_invalid_json'),
    ('late_completion','worker_completion_after_deadline'),
    ('old_completion','worker_completion_time_invalid'),
    ('output_phase_failed','worker_output_phase_not_finished'),
    ('worker_error','worker_result_invalid_json'),
    ('wrong_payload_stage','worker_result_stage_mismatch'),
])
def test_incomplete_or_unbound_results_are_never_accepted(tmp_path,mode,reason):
    result,metric=run(tmp_path,mode,timeout=.45)
    assert result is None and metric['status'] in ('worker_failed','timeout')
    assert metric['result_validation_error']==reason
    assert metric['process_reaped'] is True
    assert not metric.get('completion_validated')


def test_stale_complete_result_from_prior_invocation_cannot_pass_clean_exit(tmp_path):
    output=tmp_path/'result.json'
    output.write_text(json.dumps(LAYOUT))
    audit_path(output).write_text(json.dumps({'schema_version':1,'stage':'layout',
        'current':{'phase':'complete'},'events':[{'phase':'output','status':'ok'}],
        'completion':{'run_id':'old-run','pid':123,'stage':'layout','output_bytes':output.stat().st_size,
          'output_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'finished_monotonic':time.monotonic()}}))
    result,metric=run(tmp_path,'stale_exit')
    assert result is None and metric['status']=='worker_failed'
    assert metric['result_validation_error']=='worker_completion_identity_mismatch'


def test_relabelled_but_unwritten_old_file_is_rejected_even_with_current_nonce(tmp_path):
    output=tmp_path/'result.json'
    output.write_text(json.dumps(LAYOUT))
    before=ocr_runtime._result_file_identity(output)
    result,metric=run(tmp_path,'reuse_stale_file')
    assert result is None and metric['result_validation_error']=='worker_result_missing_or_stale'
    assert ocr_runtime._result_file_identity(output)==before


def test_partial_output_without_complete_retains_original_timeout(tmp_path):
    result,metric=run(tmp_path,'never_complete',timeout=.2)
    assert result is None and metric['status']=='timeout'
    assert metric['limit_reason']=='wall_time' and metric['seconds']<1.
    assert metric['process_reaped'] is True


def test_native_error_after_publishing_is_not_hidden_as_our_cleanup(tmp_path,monkeypatch):
    capture=ocr_runtime.subprocess.Popen
    def already_exited(*args,**kwargs):
        proc=capture(*args,**kwargs);proc.wait(timeout=3);return proc
    monkeypatch.setattr(ocr_runtime.subprocess,'Popen',already_exited)
    result,metric=run(tmp_path,'native_failure')
    assert result is None and metric['status']=='worker_failed'
    assert metric['process_returncode']==7


def _wait_for_completion_before_observing(monkeypatch):
    capture=ocr_runtime.subprocess.Popen
    def ready(*args,**kwargs):
        proc=capture(*args,**kwargs)
        path=Path(args[0][4])
        end=time.monotonic()+2
        while time.monotonic()<end:
            audit=read_audit(audit_path(path))
            if audit and audit.get('current',{}).get('phase')=='complete':return proc
            time.sleep(.005)
        raise AssertionError('synthetic worker did not publish')
    monkeypatch.setattr(ocr_runtime.subprocess,'Popen',ready)


@pytest.mark.parametrize('limit',['rss','cgroup'])
def test_resource_limit_keeps_priority_over_a_complete_result(tmp_path,monkeypatch,limit):
    _wait_for_completion_before_observing(monkeypatch)
    if limit=='rss':monkeypatch.setattr(ocr_runtime,'child_rss',lambda pid:ocr_runtime.MAX_RSS+1)
    else:
        observations=iter([None,(4*1024**3,4*1024**3)])
        monkeypatch.setattr(ocr_runtime,'cgroup_memory',lambda:next(observations))
    result,metric=run(tmp_path,'hang_after_complete',timeout=2.)
    assert result is None and metric['status']=='memory_limit'
    assert metric['limit_reason']==('worker_rss' if limit=='rss' else 'cgroup_headroom')
    assert metric['process_reaped'] is True and not metric.get('completion_validated')


def test_cancellation_propagates_even_when_result_was_just_written(tmp_path,monkeypatch,isolated_runtime):
    class Cancelled(RuntimeError):pass
    _wait_for_completion_before_observing(monkeypatch)
    def cancel(pid):raise Cancelled('synthetic cancellation')
    monkeypatch.setattr(ocr_runtime,'child_rss',cancel)
    with pytest.raises(Cancelled):run(tmp_path,'hang_after_complete',timeout=2.)
    assert isolated_runtime[-1].poll()==-signal.SIGKILL


def test_atomic_writer_does_not_replace_valid_file_with_unserializable_result(tmp_path,monkeypatch):
    output=tmp_path/'result.json';output.write_bytes(b'old-result')
    monkeypatch.setenv(ocr_runtime.WORKER_RUN_ENV,'run-test')
    with pytest.raises(ValueError):ocr_runtime.write_worker_result('layout',output,{'value':float('nan')})
    assert output.read_bytes()==b'old-result'
    assert not list(tmp_path.glob('result.json.*.tmp'))
