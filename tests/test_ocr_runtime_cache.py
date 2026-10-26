"""Exercise cache failures and worker contracts without downloading models."""
import builtins
import io
import json
import os
from pathlib import Path
import sys
import types
from unittest.mock import patch

from PIL import Image
import pytest

import ocr_runtime
import ocr_worker
from ocr_worker_audit import BoundedTextModel,WorkerAudit,audit_path,read_audit


def test_writable_explicit_cache_is_reused_without_changing_home(tmp_path):
    existing=tmp_path/'existing'
    existing.mkdir()
    marker=existing/'downloaded-model.bin'; marker.write_bytes(b'model')
    env={'PADDLE_PDX_CACHE_HOME':str(existing),'HOME':'/readonly-home',
         'CODEX_HOME':'/other-private-directory','PADDLE_PDX_MODEL_SOURCE':'modelscope'}
    before=dict(env)
    info=ocr_runtime.configure_model_cache(env)
    assert info=={'source':'paddlex_configured','fallback':False,'status':'ready'}
    assert env==before and marker.read_bytes()==b'model'
    assert not list(existing.rglob('.dmate-probe-*'))


def test_bad_explicit_cache_uses_app_cache_and_reports_no_path(tmp_path):
    invalid=tmp_path/'cannot-be-directory';invalid.write_text('preserve')
    app=tmp_path/'models'
    env={'PADDLE_PDX_CACHE_HOME':str(invalid),'DMATE_MODEL_CACHE_DIR':str(app)}
    info=ocr_runtime.configure_model_cache(env)
    assert env['PADDLE_PDX_CACHE_HOME']==str(app/'paddlex')
    assert info['fallback'] and info['source']=='dmate_configured'
    assert str(tmp_path) not in json.dumps(info)
    assert invalid.read_text()=='preserve'


def test_unwritable_paddlex_subdirectory_does_not_pass_base_probe(tmp_path):
    bad=tmp_path/'partial-cache';bad.mkdir();(bad/'locks').write_text('not a directory')
    env={'PADDLE_PDX_CACHE_HOME':str(bad),'DMATE_MODEL_CACHE_DIR':str(tmp_path/'fallback')}
    assert ocr_runtime.configure_model_cache(env)['fallback']
    assert env['PADDLE_PDX_CACHE_HOME'].endswith('/fallback/paddlex')


def test_temp_fallback_is_user_specific_without_home_reassignment(tmp_path):
    env={'HOME':'/unwritable','CODEX_HOME':'/still-unchanged'}
    with patch('ocr_runtime.tempfile.gettempdir',return_value=str(tmp_path)):
        info=ocr_runtime.configure_model_cache(env)
    uid=str(os.getuid()) if hasattr(os,'getuid') else 'current-user'
    assert Path(env['PADDLE_PDX_CACHE_HOME'])==tmp_path/f'dmate-model-cache-{uid}'/'paddlex'
    assert env['HOME']=='/unwritable' and env['CODEX_HOME']=='/still-unchanged'
    assert info['source']=='temporary'


def test_failed_cache_preflight_does_not_spawn_worker(tmp_path):
    with patch('ocr_runtime.cgroup_memory',return_value=None), \
         patch('ocr_runtime._probe_cache_directory',side_effect=PermissionError('private-path-and-token')), \
         patch('ocr_runtime.subprocess.Popen') as spawn:
        result,metric=ocr_runtime.run_worker('layout','unused',tmp_path/'out.json')
    assert result is None and metric['status']=='cache_unavailable'
    assert metric['error_kind']=='model_cache_unavailable'
    assert 'private-path' not in json.dumps(metric)
    spawn.assert_not_called()


def test_worker_cache_precedes_paddle_import(tmp_path,monkeypatch):
    cache=tmp_path/'cache'
    monkeypatch.setenv('DMATE_MODEL_CACHE_DIR',str(cache))
    monkeypatch.delenv('PADDLE_PDX_CACHE_HOME',raising=False)
    monkeypatch.setattr(ocr_worker,'_limit_resources',lambda:None)
    src=tmp_path/'normalized.png';Image.new('RGB',(20,15),'white').save(src)
    output=tmp_path/'layout.json'
    monkeypatch.setattr(sys,'argv',['ocr_worker.py','layout',str(src),str(output)])
    observed=[]
    class FakeLayout:
        def __init__(self,**kwargs):
            observed.append(kwargs)
            assert os.environ['PADDLE_PDX_CACHE_HOME']==str(cache/'paddlex')
            assert os.environ['DMATE_FORMULA_ENABLED']=='0'
        def predict(self,*args,**kwargs):return []
    real_import=builtins.__import__
    def guarded_import(name,*args,**kwargs):
        if name=='paddleocr':
            assert os.environ['PADDLE_PDX_CACHE_HOME']==str(cache/'paddlex')
            return types.SimpleNamespace(LayoutDetection=FakeLayout)
        return real_import(name,*args,**kwargs)
    with patch('builtins.__import__',side_effect=guarded_import):
        ocr_worker.main()
    assert observed[0]['model_name']=='PP-DocLayoutV3'
    assert observed[0]['cpu_threads']==2
    assert json.loads(output.read_text())['status']=='ok'


def test_worker_failure_record_is_structured_and_redacts_exception_message(monkeypatch):
    monkeypatch.setattr(ocr_worker,'WORKER_PHASE','layout_init')
    failure=ocr_worker.failure_payload(PermissionError('/private/model-cache api_key=secret'))
    assert failure=={'worker_error':'PermissionError','error_kind':'filesystem_permission_denied',
                     'phase':'layout_init'}
    assert 'secret' not in json.dumps(failure)


@pytest.mark.skipif(sys.platform!='linux',reason='Linux native-worker allocation guard')
def test_layout_resource_guard_allows_library_address_reservations():
    import resource
    with patch('resource.setrlimit') as limit,patch.object(Path,'write_text',return_value=3):
        ocr_worker._limit_resources()
    limit.assert_called_once_with(resource.RLIMIT_DATA,(3*1024**3,3*1024**3))


def test_runtime_keeps_safe_failure_kind_from_subprocess(tmp_path,monkeypatch):
    monkeypatch.setenv('DMATE_MODEL_CACHE_DIR',str(tmp_path/'cache'))
    output=tmp_path/'result.json'
    payload={'worker_error':'PermissionError','error_kind':'filesystem_permission_denied',
             'phase':'layout_init','message':'should never be surfaced'}
    code='import json,sys;open(sys.argv[1],"w").write(json.dumps('+repr(payload)+'));sys.exit(2)'
    with patch('ocr_runtime.cgroup_memory',return_value=None):
        result,metric=ocr_runtime.run_worker('layout','unused',output,
            command=[sys.executable,'-c',code,str(output)])
    assert result is None and metric['error_type']=='PermissionError'
    assert metric['error_kind']=='filesystem_permission_denied'
    assert metric['phase']=='layout_init' and 'message' not in metric


def test_cgroup_ignores_reclaimable_download_cache_but_keeps_four_gb_budget():
    files={'/sys/fs/cgroup/memory.current':str(3*1024**3),
           '/sys/fs/cgroup/memory.max':str(8*1024**3),
           '/sys/fs/cgroup/memory.stat':f'anon {1024**3}\ninactive_file {2*1024**3}\n'}
    with patch.object(Path,'read_text',lambda p,**kw:files[str(p)]):
        assert ocr_runtime.cgroup_memory()==(1024**3,4*1024**3)


def test_active_clean_unmapped_cache_is_allowed_but_protected_types_stay_charged():
    stats={'file':4200,'shmem':100,'file_mapped':300,'file_dirty':200,'file_writeback':100,
           'inactive_file':10,'active_file':4190,'anon':500,'slab_reclaimable':50}
    assert ocr_runtime._reclaimable_file_bytes(stats,'inactive_file')==3500
    # 5000 total - 3500 cache: all protected file classes plus non-file memory
    # remain charged. Large active_file or slab does not change the allowance.
    files={'/sys/fs/cgroup/memory.current':'5000','/sys/fs/cgroup/memory.max':str(8*1024**3),
           '/sys/fs/cgroup/memory.stat':'\n'.join(f'{k} {v}' for k,v in stats.items())}
    with patch.object(Path,'read_text',lambda p,**kw:files[str(p)]):
        assert ocr_runtime.cgroup_memory()==(1500,4*1024**3)


@pytest.mark.parametrize('missing',['file','shmem','file_mapped','file_dirty','file_writeback'])
def test_missing_type_counter_retains_inactive_fallback(missing):
    stats={'file':4200,'shmem':100,'file_mapped':300,'file_dirty':200,'file_writeback':100,
           'inactive_file':700}
    stats.pop(missing)
    assert ocr_runtime._reclaimable_file_bytes(stats,'inactive_file')==700


@pytest.mark.parametrize('negative',['file','shmem','file_mapped','file_dirty','file_writeback'])
def test_negative_type_counter_is_not_treated_as_free_memory(negative):
    stats={'file':4200,'shmem':100,'file_mapped':300,'file_dirty':200,'file_writeback':100,
           'inactive_file':700}
    stats[negative]=-100
    assert ocr_runtime._reclaimable_file_bytes(stats,'inactive_file')==700


@pytest.mark.parametrize('stats',[{}, {'inactive_file':-900}, {'inactive_file':'invalid'}])
def test_missing_or_invalid_inactive_counter_discounts_nothing(stats):
    assert ocr_runtime._reclaimable_file_bytes(stats,'inactive_file')==0


def test_overlapping_protected_counters_never_create_negative_cache_credit():
    stats={'file':1000,'shmem':800,'file_mapped':800,'file_dirty':500,'file_writeback':200,
           'inactive_file':900}
    assert ocr_runtime._reclaimable_file_bytes(stats,'inactive_file')==0


def test_parent_uses_shared_decode_and_keeps_layout_text_serial(tmp_path,monkeypatch):
    # Use a private lock namespace; a real OCR job may be active concurrently.
    monkeypatch.setattr(ocr_runtime.tempfile,'gettempdir',lambda:str(tmp_path))
    image=Image.new('RGBA',(6,4),(0,0,0,0));image.putpixel((2,1),(20,30,40,255))
    raw=io.BytesIO();image.save(raw,format='PNG')
    stages=[]
    def worker(stage,image_path,output_path,**kwargs):
        decoded=Image.open(image_path)
        assert decoded.mode=='RGB' and decoded.getpixel((0,0))==(255,255,255)
        assert decoded.getpixel((2,1))==(20,30,40)
        stages.append(stage)
        if stage=='layout':return {'status':'ok','regions':[]},{'stage':stage,'status':'ok'}
        assert stages==['layout','text'] and Path(kwargs['layout_path']).is_file()
        return {'text':'','text_count':0,'formula_count':0},{'stage':stage,'status':'ok'}
    with patch('ocr_runtime.run_worker',side_effect=worker):
        result=ocr_runtime.recognize_image(raw.getvalue())
    assert stages==['layout','text']
    assert result['formula_count']==0


def test_layout_thumbnail_does_not_replace_native_text_source(tmp_path,monkeypatch):
    monkeypatch.setattr(ocr_runtime.tempfile,'gettempdir',lambda:str(tmp_path))
    source=Image.new('RGB',(2600,1300),'white')
    source.putpixel((2501,113),(17,29,41))
    raw=io.BytesIO();source.save(raw,format='PNG')
    paths=[]
    def worker(stage,image_path,output_path,**kwargs):
        paths.append(image_path)
        with Image.open(image_path) as image:
            if stage=='layout': assert image.size==(2200,1100)
            else:
                assert image.size==(2600,1300)
                assert image.getpixel((2501,113))==(17,29,41)
        result={'status':'ok','regions':[]} if stage=='layout' else {'text':'','formula_count':0}
        return result,{'stage':stage,'status':'ok'}
    with patch('ocr_runtime.run_worker',side_effect=worker):
        result=ocr_runtime.recognize_image(raw.getvalue())
    assert paths[0]!=paths[1]
    assert result['image_views']['canonical_size']==[2600,1300]
    assert result['image_views']['text_size']==[2600,1300]
    assert result['image_views']['layout_to_canonical_scale']==[2600/2200,1300/1100]


def test_detector_budget_and_audit_preserve_lazy_results_without_text_logs(tmp_path):
    import numpy as np
    image=np.zeros((320,512,3),dtype=np.uint8)
    payload={'rec_text':'private-question-token','rec_score':.9}
    calls=[]
    def det(inputs,**kwargs):
        calls.append(('det',inputs[0],kwargs))
        yield {'dt_polys':[[[10,10],[20,10],[20,20],[10,20]]]}
    def rec(inputs,**kwargs):
        calls.append(('rec',inputs[0],kwargs))
        yield payload
    pipeline=types.SimpleNamespace(text_det_model=det,text_rec_model=rec)
    class Model:
        paddlex_pipeline=types.SimpleNamespace(_pipeline=pipeline)
        def predict(self,value,**kwargs):
            assert value is image
            assert kwargs['text_det_limit_side_len']==1600 and kwargs['text_det_limit_type']=='max'
            list(pipeline.text_det_model([value],limit_side_len=kwargs['text_det_limit_side_len'],
                                         limit_type=kwargs['text_det_limit_type']))
            yield from pipeline.text_rec_model([value[10:20,10:20]])
    audit=WorkerAudit(tmp_path/'result.json','text')
    audit.start_pass('original',image)
    model=BoundedTextModel(Model(),audit)
    result=list(model.predict(image,text_rec_score_thresh=.45))
    assert result[0] is payload and calls[0][1] is image
    assert calls[1][1].shape==(10,10,3)
    data=read_audit(audit.path)
    assert [event['phase'] for event in data['events']]==['text_det','text_rec']
    assert data['events'][0]['postprocess_detection_boxes']==1
    assert data['events'][1]['result_count']==1
    assert 'private-question-token' not in audit.path.read_text()


def test_predictor_failure_keeps_precise_phase_and_safe_error(tmp_path,monkeypatch):
    import numpy as np
    def det(*args,**kwargs):
        raise MemoryError('secret-token and private image path')
        yield
    pipeline=types.SimpleNamespace(text_det_model=det,text_rec_model=lambda *a,**kw:iter(()))
    target=types.SimpleNamespace(paddlex_pipeline=types.SimpleNamespace(_pipeline=pipeline))
    audit=WorkerAudit(tmp_path/'out.json','text',on_phase=ocr_worker._set_phase)
    monkeypatch.setattr(ocr_worker,'WORKER_PHASE','startup')
    audit.start_pass('original',np.zeros((16,16,3),dtype=np.uint8))
    BoundedTextModel(target,audit)
    with pytest.raises(MemoryError): list(pipeline.text_det_model([]))
    data=read_audit(audit.path)
    assert data['current']['phase']=='text_det'
    assert data['events'][0]['status']=='failed'
    failure=ocr_worker.failure_payload(MemoryError('secret-token'))
    assert failure['phase']=='text_det' and failure['error_kind']=='memory_allocation_failed'
    assert 'secret-token' not in audit.path.read_text()+json.dumps(failure)


def test_memory_guard_attributes_original_detector_without_raising_limit(tmp_path,monkeypatch):
    import numpy as np
    output=tmp_path/'result.json'
    audit=WorkerAudit(output,'text')
    audit.start_pass('original',np.zeros((16,16,3),dtype=np.uint8))
    audit.set_phase('text_det')
    class Process:
        pid=321;returncode=None
        def poll(self):return self.returncode
        def wait(self,**kwargs):self.returncode=-9;return self.returncode
    process=Process()
    monkeypatch.setenv('DMATE_MODEL_CACHE_DIR',str(tmp_path/'cache'))
    monkeypatch.setattr(ocr_runtime,'cgroup_memory',lambda:(100*1024**2,4*1024**3))
    monkeypatch.setattr(ocr_runtime,'child_rss',lambda pid:1600*1024**2+4096)
    with patch('ocr_runtime.subprocess.Popen',return_value=process),patch('ocr_runtime.os.killpg') as kill:
        result,metric=ocr_runtime.run_worker('text','unused',output)
    assert result is None and metric['status']=='memory_limit'
    assert metric['limit_reason']=='worker_rss' and metric['phase']=='text_det' and metric['pass_index']==1
    assert metric['phase_peaks'][0]['rss_observed'] is True
    assert metric['audit']['passes'][0]['kind']=='original'
    assert ocr_runtime.MAX_RSS==1600*1024**2 and ocr_runtime.CGROUP_RESERVE==768*1024**2
    kill.assert_called_once()


def test_text_worker_has_only_one_native_enhanced_pass_and_keeps_coordinate_contract(tmp_path,monkeypatch):
    source=tmp_path/'canonical.png'; Image.new('RGB',(160,100),'white').save(source)
    output=tmp_path/'text.json';layout=tmp_path/'layout.json'
    layout.write_text(json.dumps({'regions':[{'id':'r1','bbox':[.5,0,1,1],'role':'figure','score':.9}]}))
    monkeypatch.setattr(ocr_worker,'_limit_resources',lambda:None)
    monkeypatch.setenv('DMATE_MODEL_CACHE_DIR',str(tmp_path/'cache'))
    monkeypatch.setattr(sys,'argv',['ocr_worker.py','text',str(source),str(output),str(layout)])
    calls=[]
    def det(inputs,**kwargs):
        assert inputs[0].shape==(100,160,3)
        assert kwargs['limit_side_len']==1600 and kwargs['limit_type']=='max'
        yield {'dt_polys':[[[90,10],[110,10],[110,30],[90,30]]]}
    def rec(inputs,**kwargs):yield {'rec_text':'sensitive-label','rec_score':.9}
    pipeline=types.SimpleNamespace(text_det_model=det,text_rec_model=rec)
    class Model:
        paddlex_pipeline=types.SimpleNamespace(_pipeline=pipeline)
        def predict(self,image,**kwargs):
            calls.append(image.shape)
            list(pipeline.text_det_model([image],limit_side_len=kwargs['text_det_limit_side_len'],limit_type=kwargs['text_det_limit_type']))
            yield from pipeline.text_rec_model([image[10:30,90:110]])
    fake=types.SimpleNamespace(_text_ocr=Model(),load_models=lambda:None,
        _ocr_text_strength=lambda items:0,_math_line_risk=lambda items:False,
        _enhance_faded_photo=lambda image:image.copy(),_merge_text_ocr_passes=lambda first,second:first,
        _front_side_text_items=lambda items,image:items,
        _compose_markdown=lambda items,width:'\n'.join(item['content'] for item in items),
        _review_regions=lambda items,width,height:[])
    def extract(image):
        list(fake._text_ocr.predict(image,text_rec_score_thresh=.45))
        return [{'type':'text','content':'sensitive-label' if len(calls)==1 else '7',
                 'box':[90.,10.,110.,30.],'score':.9}]
    fake._extract_text_items=extract
    monkeypatch.setitem(sys.modules,'ocr',fake)
    ocr_worker.main()
    result=json.loads(output.read_text());data=read_audit(audit_path(output))
    assert calls==[(100,160,3),(100,160,3)]
    assert [row['kind'] for row in data['passes']]==['original','enhanced']
    assert result['text_evidence']['image_size']==[160,100]
    assert result['text_evidence']['graph_labels'][0]['box']==[90.,10.,110.,30.]
    assert result['text_evidence']['graph_labels'][0]['ocr_provenance']['pass_kind']=='original'
    assert result['text_evidence']['body']==[]
    assert result['text_evidence']['uncertain'][0]['content']=='7'
    assert result['text_evidence']['uncertain'][0]['ocr_provenance']['pass_kind']=='enhanced'
    assert result['text_evidence']['uncertain'][0]['review_reason']=='enhanced_candidate_unconfirmed'
    assert 'sensitive-label' not in audit_path(output).read_text()


def test_unconfirmed_enhancement_retains_numeric_conflict_and_new_region():
    original=[{'content':'3','box':[10,10,20,20],'score':.8}]
    provenance={'pass_index':2,'pass_kind':'enhanced','item_index':0}
    candidates=[{'content':'5','box':[10,10,20,20],'score':.95,'ocr_provenance':provenance},
                {'content':'3','box':[11,10,21,20],'score':.95},
                {'content':'3','box':[100,100,110,110],'score':.9},
                {'content':'bad','box':[0,0,0,1],'score':1}]
    retained=ocr_worker._unconfirmed_enhanced(original,candidates)
    assert [item['content'] for item in retained]==['5','3']
    assert retained[0]['ocr_provenance'] is provenance
    assert original==[{'content':'3','box':[10,10,20,20],'score':.8}]
