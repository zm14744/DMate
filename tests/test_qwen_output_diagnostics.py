"""Offline protocol failures: retain usage without accepting partial graphs."""
import base64
import json

import pytest

from graph_staged import Budget
from vision_provider import VisionError, VisionProvider


URL='data:image/png;base64,'+base64.b64encode(b'offline image fixture').decode()


@pytest.mark.parametrize('raw,reason,root_type',[
    ('[{"vertices":[]}]','root_not_object','list'),
    ('null','root_not_object','NoneType'),
    ('"private fixture"','root_not_object','str'),
    ('{"graphs":[','json_syntax',None),
    ('{"graphs":[]} {"graphs":[]}','json_syntax',None),
    ('{"weight":NaN}','non_finite_json_number',None),
    ('{"weight":Infinity}','non_finite_json_number',None),
    (['private fixture'],'content_not_string',None),
])
def test_failure_reason_preserves_usage_and_never_retries_or_salvages(raw,reason,root_type,monkeypatch):
    monkeypatch.setattr('ai.API_KEY','offline-test-key')
    monkeypatch.setattr('ai.VISION_ENABLED',True)
    calls=[]
    def request(*args,**kwargs):
        calls.append(1)
        return 200,'',{'model':'qwen3-vl-plus','usage':{'total_tokens':37},
            'choices':[{'message':{'content':raw},'finish_reason':'stop'}]}
    provider=VisionProvider('qwen',transport=request)
    budget=Budget(calls=2)
    with pytest.raises(VisionError,match='^invalid_output$'):
        provider('Return a JSON object.',[URL],budget)
    assert len(calls)==1 and budget.remaining==1 and len(budget.metrics)==1
    metric=budget.metrics[0]
    assert metric['status']=='invalid_output' and metric['http_status']==200
    assert metric['output_error']==reason and metric['usage']=={'total_tokens':37}
    assert metric.get('json_root_type')==root_type
    if reason=='json_syntax':
        assert set(metric['json_error'])=={'line','column','position','kind'}
        assert metric['json_error']['line']>=1 and metric['json_error']['position']>=0
        assert metric['json_error']['kind']==('invalid_value' if raw=='{"graphs":[' else 'extra_data')
    assert not provider.observations  # Raw response capture stays opt-in.
    assert 'private fixture' not in json.dumps(metric)
    assert 'offline-test-key' not in json.dumps(metric)


def test_valid_object_keeps_the_existing_formatting_contract(monkeypatch):
    monkeypatch.setattr('ai.API_KEY','offline-test-key')
    monkeypatch.setattr('ai.VISION_ENABLED',True)
    provider=VisionProvider('qwen',transport=lambda *a,**k:(200,'',{
        'model':'qwen3-vl-plus','choices':[{'message':{
            'content':'```json\n{"graphs":[]}\n```'},'finish_reason':'stop'}]}))
    budget=Budget()
    assert provider('JSON object.',[URL],budget)=={'graphs':[]}
    assert budget.metrics[0]['status']==200 and 'output_error' not in budget.metrics[0]
