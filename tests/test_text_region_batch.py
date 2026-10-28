"""Ordered masked text batches, one worker, truthful operational failures."""
import io
import json
from pathlib import Path

import pytest
from PIL import Image
from graph_region import RegionError, validate_text_regions
from test_ocr_application_contract import application


def image_bytes():
    image=Image.new('RGB',(180,120),'black');out=io.BytesIO();image.save(out,'PNG');return out.getvalue()


def regions():
    return [{'id':2,'polygon':[[.5,.1],[.9,.1],[.9,.4],[.5,.4]]},
            {'id':1,'polygon':[[.1,.6],[.4,.6],[.4,.9],[.1,.9]]}]


def test_batch_sorts_by_number_and_has_no_fixed_frame_count_limit():
    many=[{'id':i,'polygon':[[0,0],[1,0],[1,1],[0,1]]} for i in range(120,0,-1)]
    assert [r['id'] for r in validate_text_regions(many)]==list(range(1,121))
    with pytest.raises(RegionError): validate_text_regions([regions()[0],regions()[0]])
    with pytest.raises(RegionError): validate_text_regions([{'id':True,'polygon':regions()[0]['polygon']}])


def test_all_selected_crops_use_one_worker_and_its_original_pixel_details(monkeypatch):
    import ocr_runtime
    calls=[]
    def worker(stage,input_path,output_path,*,layout_path,timeout):
        plan=json.loads(Path(layout_path).read_text())
        files=plan['text_region_files'];calls.append(files)
        assert stage=='text' and timeout>45
        assert [f['id'] for f in files]==[1,2]
        for row in files:
            photo=Image.open(row['path']).convert('RGB')
            assert photo.width<180 and photo.height<120
            # The padded bounding box lies outside the polygon and is white.
            assert photo.getpixel((0,0))==(255,255,255)
            assert photo.getpixel((photo.width//2,photo.height//2))==(0,0,0)
        return {'text':'第一段\n\n第二段','regions':[{'id':1,'text':'第一段'}, {'id':2,'text':'第二段'}]}, {'status':'ok'}
    monkeypatch.setattr(ocr_runtime,'run_worker',worker)
    result=ocr_runtime.recognize_text_regions(image_bytes(),regions())
    assert len(calls)==1 and result['text']=='第一段\n\n第二段'


@pytest.mark.parametrize('status',['timeout','worker_failed','memory_limit','memory_admission_rejected','cache_unavailable'])
def test_failed_worker_never_returns_successful_blank_text(monkeypatch,status):
    import ocr_runtime
    monkeypatch.setattr(ocr_runtime,'run_worker',lambda *a,**k:(None,{'status':status}))
    with pytest.raises(ocr_runtime.OCRError): ocr_runtime.recognize_text_regions(image_bytes(),regions())


def register(client,raw):
    assert client.get('/graph/session').status_code==200
    response=client.post('/ocr',data={'image':(io.BytesIO(raw),'source.png'),
        'request_id':'batch-text-test','workflow':'manual_graph'})
    assert response.status_code==200


def test_batch_endpoint_preserves_order_source_identity_and_failures(application,monkeypatch):
    module,client,_=application;raw=image_bytes();register(client,raw)
    import ocr_runtime
    calls=[]
    def reader(data,items):
        calls.append(items)
        return {'regions':[{'id':1,'text':'第一问'}, {'id':2,'text':'第二问'}], 'text':'第一问\n\n第二问'}
    monkeypatch.setattr(ocr_runtime,'recognize_text_regions',reader)
    def post(data=raw):
        return client.post('/graph/text-region',data={'image':(io.BytesIO(data),'source.png'),
            'request_id':'batch-text-test','regions':json.dumps(regions())})
    response=post();assert response.status_code==200
    assert [r['id'] for r in calls[0]]==[1,2]
    assert response.get_json()['text']=='第一问\n\n第二问'
    assert response.get_json()['recognition_status']=='complete'
    assert post(b'wrong image').status_code==409 and len(calls)==1
    def timeout(*a): raise ocr_runtime.OCRError('文字识别超时，请重试。')
    monkeypatch.setattr(ocr_runtime,'recognize_text_regions',timeout)
    response=post();assert response.status_code==503
    assert response.get_json()['recognition_status']=='failed'
    assert '超时' in response.get_json()['error']


def test_legacy_polygon_timeout_is_reported_as_failure_instead_of_no_text(application,monkeypatch):
    module,client,_=application;raw=image_bytes();register(client,raw)
    def reader(data,*,text_only,timeout_seconds):
        assert text_only and timeout_seconds==45
        return {'text':'','resource_metrics':[{'stage':'text','status':'timeout'}]}
    monkeypatch.setattr(module,'recognize_image',reader)
    response=client.post('/graph/text-region',data={'image':(io.BytesIO(raw),'source.png'),
        'request_id':'batch-text-test','polygon':json.dumps(regions()[0]['polygon'])})
    assert response.status_code==503 and '超时' in response.get_json()['error']


def test_batch_worker_loads_model_once_and_keeps_audit_bounded_for_many_frames(tmp_path,monkeypatch):
    import sys
    from types import SimpleNamespace
    import numpy as np
    import ocr_runtime,ocr_worker,ocr_worker_audit
    loads=[];reads=[]
    monkeypatch.setattr(ocr_worker,'_limit_resources',lambda:None)
    monkeypatch.setattr(ocr_runtime,'configure_model_cache',lambda env:{})
    monkeypatch.setattr(ocr_worker_audit,'BoundedTextModel',lambda model,audit:model)
    monkeypatch.setitem(sys.modules,'ocr',SimpleNamespace(load_models=lambda:loads.append(1),_text_ocr=object()))
    monkeypatch.setitem(sys.modules,'cv2',SimpleNamespace(setNumThreads=lambda n:None,imread=lambda path:np.zeros((30,40,3))))
    def read(image,ocr,audit,regions):
        reads.append(1)
        return {'text':'段落 '+str(len(reads)),'text_count':1}
    monkeypatch.setattr(ocr_worker,'recognize_text_crop',read)
    plan=tmp_path/'regions.json';output=tmp_path/'result.json'
    plan.write_text(json.dumps({'text_region_files':[{'id':i,'path':'crop.png'} for i in range(1,101)]}))
    monkeypatch.setattr(sys,'argv',['ocr_worker.py','text','crop.png',str(output),str(plan)])
    ocr_worker.main()
    result=json.loads(output.read_text())
    assert loads==[1] and len(reads)==100
    assert result['regions'][0]['id']==1 and result['regions'][-1]['id']==100
    audit=ocr_worker_audit.read_audit(ocr_worker_audit.audit_path(output))
    assert audit['completed_regions']==100 and audit['current']['phase']=='complete'
    assert len(audit['events'])<48
