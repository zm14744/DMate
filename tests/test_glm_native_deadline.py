"""Exercise the native GLM SSE parser, without network or real credentials."""
import base64
import json
import types
from unittest.mock import Mock

import pytest
import requests

import vision_provider as vision
from graph_agent_runtime import AgentBudget
from graph_semantic_pipeline import SemanticRunner


IMAGE = 'data:image/png;base64,' + base64.b64encode(b'synthetic bytes').decode()
CONTENT = '{"sources":[]}'


class Clock:
    value = 100.

    def __call__(self):
        return self.value


class NativeResponse(requests.Response):
    """Real requests UTF-8/line decoding; only elapsed time/failure injected."""
    def __init__(self, *, clock=None, expire=False, error=None, finish=None):
        super().__init__()
        self.status_code = 200
        self.headers['Content-Type'] = 'text/event-stream'
        chunk = {'model': vision.GLM_5V_TURBO_MODEL, 'choices': [{'delta': {
            'content': CONTENT, 'reasoning_content': '原图检查'}, 'finish_reason': finish}],
            'usage': {'completion_tokens': 7}}
        lines = ['data: ' + json.dumps(chunk, ensure_ascii=False)]
        if not error:
            lines.append('data: [DONE]')
        self._content = ('\n'.join(lines)+'\n').encode('utf-8')
        self._content_consumed = True
        self.clock, self.expire, self.error = clock, expire, error
        self.closed = False

    def iter_lines(self, *args, **kwargs):
        for index, line in enumerate(super().iter_lines(*args, **kwargs)):
            if self.expire and index == 1:
                self.clock.value += 11.
            yield line
        if self.error:
            raise self.error

    def close(self):
        self.closed = True
        super().close()


@pytest.fixture(autouse=True)
def no_network_or_real_keys(monkeypatch):
    monkeypatch.setenv('ZHIPU_API_KEY', 'test-only-no-real-key')
    monkeypatch.setattr(requests.sessions.Session, 'send',
                        lambda *a, **kw: pytest.fail('network forbidden'))


def setup(monkeypatch, post):
    clock = Clock()
    monkeypatch.setattr(vision, 'time', types.SimpleNamespace(monotonic=clock, time=lambda: 1000.))
    monkeypatch.setattr(vision.requests, 'post', post(clock))
    ledger = AgentBudget(seconds=60, calls=8, call_seconds=10,
                         task_id='native_glm_test', source_sha256='c'*64)
    provider = vision.VisionProvider('glm', model=vision.GLM_5V_TURBO_MODEL,
                                     thinking=True, retries=0)
    return clock, ledger, provider


def invoke(ledger, provider):
    return SemanticRunner(ledger, provider={'semantic_edges_glm': provider}).call('semantic_edges_glm', 'JSON', {},
        [IMAGE], revision=3, response_identity=False)


def test_native_output_deadline_is_not_network_retried_even_with_valid_partial_json(monkeypatch):
    responses, sends = [], []
    def factory(clock):
        def post(*args, **kwargs):
            sends.append(kwargs)
            response = NativeResponse(clock=clock, expire=True)
            responses.append(response)
            return response
        return post
    _, ledger, provider = setup(monkeypatch, factory)
    with pytest.raises(vision.VisionError, match='output_deadline_exceeded') as caught:
        invoke(ledger, provider)
    assert len(sends) == 1 and ledger.network_recoveries == 0
    assert all(response.closed for response in responses)
    metric = ledger.metrics[0]
    assert metric['status'] == 'transport_failed'
    assert metric['timeout_kind'] == metric['transport_failure_kind'] == 'wall_deadline'
    assert metric['failure_phase'] == 'sse_stream' and metric['http_status'] == 200
    assert metric['request_started'] and metric['response_headers_received'] and metric['partial_stream']
    assert metric['stream_done_received'] is False
    assert metric['stream_lines_received'] == 2 and metric['sse_events_received'] == 1
    assert metric['content_chars'] == len(CONTENT) and metric['reasoning_chars'] == 4
    assert metric['usage'] == {'completion_tokens': 7}
    facts = caught.value.audit['failure_facts']
    assert facts['agent_role'] == 'semantic_edges_glm' and facts['state_revision'] == 3
    assert facts['role_invocation'] == 1 and facts['source_sha256'] == 'c'*64
    assert facts['task_id'] == ledger.task_id
    assert caught.value.audit['accepted'] is False


def test_exact_deadline_is_expired_and_unparsed_done_does_not_count(monkeypatch):
    response = NativeResponse()
    monkeypatch.setattr(vision.requests, 'post', Mock(return_value=response))
    monkeypatch.setattr(vision, 'time', types.SimpleNamespace(monotonic=lambda: 10.))
    with pytest.raises(TimeoutError) as caught:
        vision._glm_request({}, {}, (1., 10.), 10.)
    facts = vision._transport_failure_metrics(caught.value)
    assert facts['timeout_kind'] == 'wall_deadline'
    assert facts['stream_lines_received'] == 1 and facts['sse_events_received'] == 0
    assert facts['stream_done_received'] is False and response.closed
    assert caught.value.vision_partial_result['content'] == ''


@pytest.mark.parametrize('error', [requests.ReadTimeout('vision_wall_deadline'),
                                 requests.ConnectTimeout('vision_wall_deadline')])
def test_native_read_and_connect_faults_keep_bounded_recovery_despite_message(error, monkeypatch):
    sends = []
    def factory(clock):
        def post(*args, **kwargs):
            sends.append(True)
            if len(sends) == 1:
                if isinstance(error, requests.ConnectTimeout):
                    raise error
                return NativeResponse(error=error)
            return NativeResponse(finish='stop')
        return post
    _, ledger, provider = setup(monkeypatch, factory)
    assert invoke(ledger, provider) == {'sources': []}
    assert len(sends) == 2 and ledger.network_recoveries == 1
    metric = ledger.metrics[0]
    assert metric['timeout_kind'] == ('connect' if isinstance(error, requests.ConnectTimeout) else 'read')
    assert metric['transport_failure_kind'] != 'wall_deadline'
    if isinstance(error, requests.ReadTimeout):
        assert metric['partial_stream'] and metric['content_chars'] == len(CONTENT)
        assert metric['failure_phase'] == 'sse_stream'
    assert ledger.metrics[1]['status'] == 200


def test_native_utf8_completion_before_deadline_keeps_content_and_reasoning(monkeypatch):
    response = NativeResponse(finish='stop')
    _, ledger, provider = setup(monkeypatch, lambda clock: Mock(return_value=response))
    assert invoke(ledger, provider) == {'sources': []}
    assert len(ledger.metrics) == 1 and ledger.metrics[0]['reasoning_chars'] == 4
    assert ledger.metrics[0]['status'] == 200 and response.closed
