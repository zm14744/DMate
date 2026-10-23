"""Failure evidence checks, never real-image accuracy claims."""
import base64,json
import pytest
import requests
from graph_staged import Budget
from vision_provider import GLM_53_FLASH_MODEL,VisionError,VisionProvider

URL='data:image/png;base64,'+base64.b64encode(b'image fixture').decode()


@pytest.mark.parametrize('content',['','{"graphs":[]}'])
def test_network_finish_is_failure_even_if_partial_content_is_valid_json(content,monkeypatch):
    monkeypatch.setenv('ZHIPU_API_KEY','test-only')
    result={'model':GLM_53_FLASH_MODEL,'choices':[{'message':{'content':content},'finish_reason':'network_error'}]}
    provider=VisionProvider('glm',model=GLM_53_FLASH_MODEL,thinking=True,capture=True,
                            transport=lambda *a,**kw:(200,'',result))
    with pytest.raises(VisionError,match='upstream_network_error'):provider('JSON',[URL],Budget())
    observed=provider.observations[0]
    assert observed['http_status']==200 and observed['status']=='upstream_network_error'
    assert observed['raw_content']==content


def test_timed_out_sse_keeps_partial_evidence_but_never_scores_it(monkeypatch):
    monkeypatch.setenv('ZHIPU_API_KEY','test-only')
    class Response:
        status_code=200;headers={'Content-Type':'text/event-stream'};closed=False
        def iter_lines(self,**kwargs):
            yield 'data: '+json.dumps({'model':GLM_53_FLASH_MODEL,'choices':[{'delta':{
                'content':'{"graphs":[','reasoning_content':'partial thought'}}]})
            raise requests.ReadTimeout('simulated stream interruption')
        def close(self):self.closed=True
    response=Response();monkeypatch.setattr('vision_provider.requests.post',lambda *a,**kw:response)
    provider=VisionProvider('glm',model=GLM_53_FLASH_MODEL,thinking=True,capture=True)
    with pytest.raises(VisionError,match='transport_failed'):provider('JSON',[URL],Budget())
    metric=provider.observations[0]
    assert metric['status']=='transport_failed' and metric['confirmed_timeout'] is True
    assert metric['http_status']==200 and metric['partial_stream'] is True
    assert metric['raw_content']=='{"graphs":[' and metric['reasoning_chars']==15
    assert metric['usage']=={} and response.closed
