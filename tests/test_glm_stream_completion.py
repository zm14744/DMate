"""An early native GLM SSE EOF must not certify a valid JSON prefix."""
import io
import json
import time
from unittest.mock import Mock

import pytest
import requests

from graph_agent_runtime import AgentBudget
from graph_semantic_pipeline import SemanticRunner
from vision_provider import GLM_5V_TURBO_MODEL, VisionError, VisionProvider


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setenv('ZHIPU_API_KEY', 'offline-test-key')
    monkeypatch.setattr(requests.sessions.Session, 'send',
                        lambda *args, **kwargs: pytest.fail('No network is allowed'))


def response(content, *, finish=None, done=False):
    event = {'model': GLM_5V_TURBO_MODEL, 'choices': [
        {'delta': {'content': content}, 'finish_reason': finish}]}
    raw = 'data: ' + json.dumps(event, ensure_ascii=False) + '\n\n'
    if done:
        raw += 'data: [DONE]\n\n'
    value = requests.Response()
    value.status_code = 200
    value.headers['Content-Type'] = 'text/event-stream'
    value.raw = io.BytesIO(raw.encode('utf-8'))
    value.close = Mock(wraps=value.close)
    return value


class Budget:
    def __init__(self):
        self.deadline = time.monotonic() + 30
        self.metrics = []
        self.calls = 0

    def take(self):
        self.calls += 1
        return 10


@pytest.mark.parametrize('content', ['{"graphs":[]}', '{"graphs":['])
def test_eof_without_terminal_never_accepts_or_classifies_prefix_as_format_failure(monkeypatch, content):
    value = response(content)
    monkeypatch.setattr(requests, 'post', lambda *args, **kwargs: value)
    ledger = Budget()
    provider = VisionProvider('glm', model=GLM_5V_TURBO_MODEL, retries=0)
    with pytest.raises(VisionError, match='^transport_failed$'):
        provider('Read the complete page as JSON.', [], ledger)
    assert ledger.calls == 1 and len(ledger.metrics) == 1
    metric = ledger.metrics[0]
    assert metric['status'] == 'transport_failed'
    assert metric['transport_failure_kind'] == 'incomplete_stream'
    assert metric['confirmed_timeout'] is False
    assert metric['partial_stream'] is True and metric['stream_done_received'] is False
    assert metric['finish_reason'] is None and metric['http_status'] == 200
    assert metric['content_chars'] == len(content)
    assert 'output_error' not in metric and 'json_error' not in metric
    value.close.assert_called_once()


@pytest.mark.parametrize('finish,done', [('stop', False), (None, True), ('stop', True)])
def test_either_terminal_finish_or_done_accepts_completed_json(monkeypatch, finish, done):
    value = response('{"graphs":[]}', finish=finish, done=done)
    monkeypatch.setattr(requests, 'post', lambda *args, **kwargs: value)
    ledger = Budget()
    assert VisionProvider('glm', model=GLM_5V_TURBO_MODEL)(
        'Read the complete page as JSON.', [], ledger) == {'graphs': []}
    assert ledger.calls == 1 and ledger.metrics[0]['status'] == 200
    value.close.assert_called_once()


@pytest.mark.parametrize('finish,kind', [('length', 'truncated_output'),
                                      ('network_error', 'upstream_network_error')])
def test_terminal_provider_failure_still_cannot_certify_valid_json(monkeypatch, finish, kind):
    monkeypatch.setattr(requests, 'post', lambda *args, **kwargs:
                        response('{"graphs":[]}', finish=finish))
    ledger = Budget()
    with pytest.raises(VisionError, match='^' + kind + '$'):
        VisionProvider('glm', model=GLM_5V_TURBO_MODEL)(
            'Read the complete page as JSON.', [], ledger)
    assert ledger.calls == 1 and ledger.metrics[0]['status'] == kind


def test_native_incomplete_stream_uses_network_allowance_and_preserves_shared_budget(monkeypatch):
    sent = []
    def post(*args, **kwargs):
        sent.append(True)
        return response('{"graphs":[]}', finish='stop' if len(sent) == 2 else None)
    monkeypatch.setattr(requests, 'post', post)
    ledger = AgentBudget(seconds=30, calls=5, call_seconds=10,
                         task_id='offline-glm-eof', source_sha256='a' * 64)
    before_deadline = ledger.deadline
    provider = VisionProvider('glm', model=GLM_5V_TURBO_MODEL, retries=0)
    result = SemanticRunner(ledger, provider={'semantic_specialist': provider}).call(
        'semantic_specialist', 'Read the complete page as JSON.', {}, [], response_identity=False)
    assert result == {'graphs': []} and len(sent) == 2
    assert ledger.remaining == 3 and ledger.deadline == before_deadline
    assert ledger.network_recoveries == 1 and ledger.json_format_recoveries == 0
    assert [item['status'] for item in ledger.metrics] == ['transport_failed', 200]
    assert [item['agent_attempt_kind'] for item in ledger.metrics] == ['initial', 'network_recovery']
    assert not any(item['status'] == 'json_format_recovery' for item in ledger.events)
