"""GLM 5.3 protocol checks. Only live benchmarks measure OCR accuracy."""
import base64
from unittest.mock import Mock
import pytest

from graph_staged import Budget
from vision_provider import GLM_53_FLASH_MODEL,VisionError,VisionProvider
from scripts.benchmark_graph_vision import adaptation_profile,main

URL='data:image/png;base64,'+base64.b64encode(b'image fixture').decode()


def test_always_thinking_is_explicit_and_cannot_silently_be_marked_off():
    request=Mock()
    with pytest.raises(ValueError,match='thinking cannot be disabled'):
        VisionProvider('glm',model=GLM_53_FLASH_MODEL,transport=request)
    request.assert_not_called()
    p=VisionProvider('glm',model=GLM_53_FLASH_MODEL,thinking=True)
    payload=p.payload('JSON only',[URL])
    assert payload['thinking']=={'type':'enabled'} and payload['reasoning_effort']=='low'
    assert payload['do_sample'] is False and payload['stream'] is True
    assert payload['messages'][0]['content'][1]['image_url']=={'url':URL.split(',',1)[1]}
    assert payload['response_format']=={'type':'json_object'}
    assert not {'enable_thinking','thinking_budget','stream_options','temperature'}&payload.keys()


@pytest.mark.parametrize('effort',['low','high','max'])
def test_supported_efforts_are_recorded_in_request(effort):
    p=VisionProvider('glm',model=GLM_53_FLASH_MODEL,thinking=True,reasoning_effort=effort)
    assert p.payload('JSON',[URL])['reasoning_effort']==effort


def test_old_models_do_not_receive_new_reasoning_fields():
    for name in ('glm','qwen'):
        p=VisionProvider(name)
        assert 'reasoning_effort' not in p.payload('JSON',[URL])
        with pytest.raises(ValueError):VisionProvider(name,reasoning_effort='low')
    with pytest.raises(ValueError):VisionProvider('glm',model=GLM_53_FLASH_MODEL,thinking=True,reasoning_effort='medium')


@pytest.mark.parametrize('returned,valid',[
    ('glm-5.3-flash',True),('glm-5.3-flash-20260814',True),
    ('glm-5.3-flashx',False),('glm-5.3',False),(None,False),
])
def test_no_substitution_with_flashx_paid_or_unidentified_model(returned,valid,monkeypatch):
    monkeypatch.setenv('ZHIPU_API_KEY','test-only')
    response={'model':returned,'reasoning_chars':43,'usage':{'prompt_tokens':8,'completion_tokens':9,'total_tokens':17,
                    'completion_tokens_details':{'reasoning_tokens':4}},
              'choices':[{'message':{'content':'{"graphs":[]}'},'finish_reason':'stop'}]}
    p=VisionProvider('glm',model=GLM_53_FLASH_MODEL,thinking=True,capture=True,
                     transport=lambda *a,**kw:(200,'',response))
    if valid:assert p('JSON',[URL],Budget())=={'graphs':[]}
    else:
        with pytest.raises(VisionError):p('JSON',[URL],Budget())
    assert p.observations[0]['thinking'] is True and p.observations[0]['reasoning_effort']=='low'
    assert p.observations[0]['reasoning_chars']==43
    assert p.observations[0]['usage']['completion_tokens_details']['reasoning_tokens']==4


def test_profile_keeps_stable_topology_contract_not_v6():
    assert adaptation_profile('glm','staged','native',GLM_53_FLASH_MODEL)=='glm53-native-v2'
    assert adaptation_profile('glm','raw','native',GLM_53_FLASH_MODEL)=='baseline'
    with pytest.raises(ValueError):adaptation_profile('glm','staged','experimental',GLM_53_FLASH_MODEL)


def test_benchmark_rejects_off_mode_before_loading_private_files_or_calling_api(monkeypatch,capsys):
    monkeypatch.setattr('sys.argv',['benchmark','--manifest','missing','--output','/tmp/not-created',
                                   '--glm-model',GLM_53_FLASH_MODEL,'--thinking','off'])
    with pytest.raises(SystemExit) as result:main()
    assert result.value.code==2 and 'always-thinking' in capsys.readouterr().err


def test_qwen_budget_is_explicit_and_does_not_change_off_or_glm_requests():
    p=VisionProvider('qwen',thinking=True,thinking_budget=1024)
    assert p.payload('JSON',[URL])['thinking_budget']==1024
    assert 'thinking_budget' not in VisionProvider('qwen').payload('JSON',[URL])
    with pytest.raises(ValueError):VisionProvider('qwen',thinking_budget=1024)
    with pytest.raises(ValueError):VisionProvider('glm',thinking=True,thinking_budget=1024)


@pytest.mark.parametrize('budget',[True,0,255,4097,1024.5])
def test_invalid_qwen_budgets_fail_before_api(budget):
    with pytest.raises(ValueError):VisionProvider('qwen',thinking=True,thinking_budget=budget)


def test_reasoning_only_is_not_parsed_as_an_answer(monkeypatch):
    monkeypatch.setenv('ZHIPU_API_KEY','test-only')
    response={'model':GLM_53_FLASH_MODEL,'reasoning_chars':100,
              'choices':[{'message':{'content':''},'finish_reason':'stop'}]}
    p=VisionProvider('glm',model=GLM_53_FLASH_MODEL,thinking=True,capture=True,
                     transport=lambda *a,**kw:(200,'',response))
    with pytest.raises(VisionError,match='reasoning_only_output'):p('JSON',[URL],Budget())
    assert p.observations[0]['status']=='reasoning_only_output'
