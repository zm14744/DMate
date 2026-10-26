"""GLM-5V request/response contracts; fixtures do not certify image accuracy."""
import base64
import hashlib
import json
from unittest.mock import Mock

import pytest

from graph_staged import Budget
from vision_provider import (
    GLM_MODEL, GLM_PAID_MODEL, GLM_53_FLASH_MODEL, GLM_5V_TURBO_MODEL,
    GLM_URL, QWEN_MODEL, VisionError, VisionProvider,
)


IMAGES=['data:image/png;base64,'+base64.b64encode(f'image fixture {i}'.encode()).decode()
        for i in range(6)]


def response(*,model=GLM_5V_TURBO_MODEL,content='{"graphs":[]}',finish='stop'):
    return 200,'',{'model':model,'usage':{'prompt_tokens':11,'completion_tokens':9,'total_tokens':20},
        'choices':[{'message':{'content':content},'finish_reason':finish}]}


@pytest.mark.parametrize('thinking',[False,True])
def test_glm5v_native_payload_has_explicit_thinking_and_original_image_bytes(thinking):
    provider=VisionProvider('glm',model=GLM_5V_TURBO_MODEL,thinking=thinking)
    payload=provider.payload('Return one JSON object.',IMAGES,max_images=5)
    assert payload['model']=='glm-5v-turbo'
    assert payload['thinking']=={'type':'enabled' if thinking else 'disabled'}
    assert payload['do_sample'] is False and payload['stream'] is True
    assert not {'response_format','reasoning_effort','thinking_budget','enable_thinking',
                'temperature','top_p','stream_options'} & payload.keys()
    content=payload['messages'][0]['content']
    assert content[0]=={'type':'text','text':'Return one JSON object.'}
    assert [item['image_url'] for item in content[1:]]==[
        {'url':url.split(',',1)[1]} for url in IMAGES[:5]]


@pytest.mark.parametrize('kwargs',[{'reasoning_effort':'low'},{'thinking_budget':1024}])
def test_unverified_reasoning_parameters_cannot_be_sent(kwargs):
    with pytest.raises(ValueError):
        VisionProvider('glm',model=GLM_5V_TURBO_MODEL,thinking=True,**kwargs)


def test_missing_key_is_unavailable_without_spending_budget_or_transport(monkeypatch):
    monkeypatch.delenv('ZHIPU_API_KEY',raising=False)
    transport=Mock()
    provider=VisionProvider('glm',model=GLM_5V_TURBO_MODEL,transport=transport)
    budget=Budget(calls=2)
    assert not provider.available()
    with pytest.raises(VisionError,match='missing_key'):
        provider('JSON',IMAGES[:1],budget)
    assert budget.remaining==2 and budget.metrics==[] and provider.logical_calls==0
    transport.assert_not_called()


def test_glm5v_uses_shared_call_budget_and_records_actual_provider_images_and_output_cap(monkeypatch):
    monkeypatch.setenv('ZHIPU_API_KEY','fixture-only-not-a-credential')
    transport=Mock(return_value=response())
    provider=VisionProvider('glm',model=GLM_5V_TURBO_MODEL,thinking=True,transport=transport)
    budget=Budget(calls=2);budget.max_images=5;budget.output_tokens=4096;budget.connect_seconds=3
    assert provider('JSON',IMAGES,budget)=={'graphs':[]}
    assert budget.remaining==1 and transport.call_count==1
    payload=transport.call_args.args[0]
    assert payload['max_tokens']==4096 and len(payload['messages'][0]['content'])==6
    metric=budget.metrics[0]
    assert metric['provider']=='glm' and metric['model']==GLM_5V_TURBO_MODEL
    assert metric['returned_model']==GLM_5V_TURBO_MODEL and metric['status']==200
    assert metric['max_images']==5 and metric['image_count']==5
    assert metric['max_output_tokens']==4096 and metric['usage']['total_tokens']==20
    assert metric['image_sha256']==[hashlib.sha256(base64.b64decode(url.split(',',1)[1])).hexdigest()
                                    for url in IMAGES[:5]]
    assert 'fixture-only-not-a-credential' not in json.dumps(metric)


@pytest.mark.parametrize('output_tokens',[True,1023,16385,4096.0])
def test_invalid_output_budget_cannot_send_a_request(output_tokens,monkeypatch):
    monkeypatch.setenv('ZHIPU_API_KEY','fixture-only')
    transport=Mock();budget=Budget();budget.output_tokens=output_tokens
    provider=VisionProvider('glm',model=GLM_5V_TURBO_MODEL,transport=transport)
    with pytest.raises(ValueError,match='invalid_bounded_output_budget'):
        provider('JSON',IMAGES[:1],budget)
    transport.assert_not_called()
    assert budget.remaining==7 and budget.metrics==[]


@pytest.mark.parametrize('returned,valid',[
    ('glm-5v-turbo',True),('glm-5v-turbo-20260402',True),
    ('glm-5-turbo',False),('glm-4.6v',False),('qwen3-vl-plus',False),(None,False),
])
def test_glm5v_never_accepts_an_unidentified_or_substituted_model(returned,valid,monkeypatch):
    monkeypatch.setenv('ZHIPU_API_KEY','fixture-only')
    provider=VisionProvider('glm',model=GLM_5V_TURBO_MODEL,
                            transport=Mock(return_value=response(model=returned)))
    budget=Budget()
    if valid:
        assert provider('JSON',IMAGES[:1],budget)=={'graphs':[]}
    else:
        expected='model_identity_unverified' if returned is None else 'model_mismatch'
        with pytest.raises(VisionError,match=expected):provider('JSON',IMAGES[:1],budget)
        assert budget.metrics[0]['status']==expected


@pytest.mark.parametrize('content,finish,kind',[
    ('{"graphs":[]}','length','truncated_output'),
    ('{"graphs":[]}','network_error','upstream_network_error'),
    ('answer: {"graphs":[]}','stop','invalid_output'),
    ('{"graphs":[],"score":NaN}','stop','invalid_output'),
    ('[]','stop','invalid_output'),
])
def test_json_prompt_does_not_relax_complete_response_validation(content,finish,kind,monkeypatch):
    monkeypatch.setenv('ZHIPU_API_KEY','fixture-only')
    transport=Mock(return_value=response(content=content,finish=finish))
    provider=VisionProvider('glm',model=GLM_5V_TURBO_MODEL,transport=transport)
    budget=Budget()
    with pytest.raises(VisionError,match=kind):provider('JSON',IMAGES[:1],budget)
    assert transport.call_count==1 and budget.metrics[0]['status']==kind


def test_china_sse_transport_keeps_unicode_and_one_actual_glm_attempt(monkeypatch):
    monkeypatch.setenv('ZHIPU_API_KEY','fixture-only')
    class Response:
        status_code=200;headers={'Content-Type':'text/event-stream'};closed=False
        def iter_lines(self,**kwargs):
            assert self.encoding=='utf-8' and kwargs=={'decode_unicode':True}
            chunks=[{'model':GLM_5V_TURBO_MODEL,'choices':[{'delta':{'reasoning_content':'独立检查'}}]},
                {'model':GLM_5V_TURBO_MODEL,'choices':[{'delta':{'content':'{"text":"边名 e₂"}'},
                                                      'finish_reason':'stop'}],
                 'usage':{'total_tokens':20}}]
            for chunk in chunks:yield 'data: '+json.dumps(chunk,ensure_ascii=False)
            yield 'data: [DONE]'
        def close(self):self.closed=True
    streamed=Response();post=Mock(return_value=streamed)
    monkeypatch.setattr('vision_provider.requests.post',post)
    provider=VisionProvider('glm',model=GLM_5V_TURBO_MODEL,thinking=True)
    budget=Budget()
    assert provider('JSON',IMAGES[:2],budget)=={'text':'边名 e₂'}
    assert post.call_args.args==(GLM_URL,)
    assert GLM_URL=='https://open.bigmodel.cn/api/paas/v4/chat/completions'
    assert post.call_args.kwargs['stream'] is True and streamed.closed
    assert len(budget.metrics)==1 and budget.metrics[0]['provider']=='glm'
    assert budget.metrics[0]['reasoning_chars']==4


def test_glm5v_opt_in_does_not_change_qwen_or_legacy_glm_contracts():
    assert VisionProvider().model==QWEN_MODEL
    assert VisionProvider('glm').model==GLM_MODEL
    for model in (GLM_MODEL,GLM_PAID_MODEL):
        off=VisionProvider('glm',model=model).payload('JSON',IMAGES[:1])
        on=VisionProvider('glm',model=model,thinking=True).payload('JSON',IMAGES[:1])
        assert off['response_format']=={'type':'json_object'} and 'response_format' not in on
        assert off['max_tokens']==on['max_tokens']==6500
    previous=VisionProvider('glm',model=GLM_53_FLASH_MODEL,thinking=True).payload('JSON',IMAGES[:1])
    assert previous['reasoning_effort']=='low'
    assert previous['response_format']=={'type':'json_object'}
    qwen=VisionProvider().payload('JSON',IMAGES[:1])
    assert qwen['model']==QWEN_MODEL and qwen['temperature']==0
    assert qwen['response_format']=={'type':'json_object'} and 'thinking' not in qwen
