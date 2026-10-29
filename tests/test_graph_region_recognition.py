import copy
import hashlib
import io
import json

import pytest
from PIL import Image

from graph_region_recognition import recognize_graph_region
from test_ocr_application_contract import application


def raw_image():
    out=io.BytesIO();Image.new('RGB',(100,80),'red').save(out,format='PNG');return out.getvalue()


def draft():
    return {'document':{'body_text':'不得混入图形框的文字栏','graphs':[{
        'id':'G1','directed':False,'weighted':False,'bbox':[0,0,1,1],
        'vertices':[{'id':'a','label':'a','x':0,'y':0},{'id':'b','label':'b','x':1,'y':1}],
        'edges':[{'id':'e','from':'a','to':'b','direction':'undirected','path':[[0,0],[1,1]]}]}]},
        'recognition_status':'complete','review':{'required':False}}


def test_only_polygon_pixels_are_read_and_geometry_returns_to_original_frame():
    seen=[]
    def reader(raw,**options):
        im=Image.open(io.BytesIO(raw)).convert('RGB');seen.append(im)
        assert im.size==(64,52)
        assert im.getpixel((63,51))==(255,255,255)
        assert im.getpixel((12,12))==(255,0,0)
        return draft()
    raw=raw_image();result=recognize_graph_region(raw,[[.2,.2],[.8,.2],[.2,.8]],recognizer=reader)
    graph=result['document']['graphs'][0]
    assert graph['vertices'][0]['x']==pytest.approx(18/99)
    assert graph['vertices'][1]['y']==pytest.approx(65/79)
    assert graph['edges'][0]['path'][1]==pytest.approx([81/99,65/79])
    assert graph['bbox']==pytest.approx([18/99,14/79,81/99,65/79])
    assert result['document']['body_text']==result['text']==''
    assert result['source_sha256']==hashlib.sha256(raw).hexdigest()
    assert result['selection']['original_sha256']!=result['selection']['crop_sha256']


def test_wrong_original_is_rejected_before_any_region_model(application,monkeypatch,tmp_path):
    import graph_region_recognition
    _,client,_=application
    monkeypatch.setenv('DMATE_GRAPH_CONFIRMATION_DB',str(tmp_path/'confirm.sqlite3'))
    monkeypatch.setattr(graph_region_recognition,'recognize_graph_region',lambda *a,**k:pytest.fail('unregistered source reached model'))
    client.get('/graph/session')
    response=client.post('/graph/recognize-region',data={'image':(io.BytesIO(raw_image()),'x.png'),
        'request_id':'missing','polygon':json.dumps([[0,0],[1,0],[1,1],[0,1]])})
    assert response.status_code in (400,409)


def test_registered_region_uses_independent_operation_and_original_source(application,monkeypatch,tmp_path):
    import graph_qwen_targeted
    from graph_upload_tasks import UPLOAD_TASKS
    _,client,_=application
    monkeypatch.setenv('DMATE_GRAPH_CONFIRMATION_DB',str(tmp_path/'confirm.sqlite3'))
    calls=[]
    monkeypatch.setattr(graph_qwen_targeted,'recognize_qwen_targeted',lambda raw,**options:calls.append((raw,options)) or draft())
    client.get('/graph/session');raw=raw_image()
    initial=client.post('/ocr',data={'image':(io.BytesIO(raw),'x.png'),'request_id':'parent','workflow':'manual_graph'})
    assert initial.status_code==200
    before=UPLOAD_TASKS.active_count()
    result=client.post('/graph/recognize-region',data={'image':(io.BytesIO(raw),'x.png'),
        'request_id':'parent','operation_id':'region1','polygon':json.dumps([[.2,.2],[.8,.2],[.2,.8]])})
    assert result.status_code==200,result.get_json()
    assert result.get_json()['request_id']=='parent'
    assert result.get_json()['operation_id']=='region1'
    assert result.get_json()['source_sha256']==hashlib.sha256(raw).hexdigest()
    assert len(calls)==1 and callable(calls[0][1]['cancelled'])
    assert UPLOAD_TASKS.active_count()==before
