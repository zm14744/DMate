"""Offline transport boundaries using Requests' real SSE exception wrapping."""
import base64
import io
import json
import socket
import ssl
from unittest.mock import Mock

import pytest
import requests
from urllib3 import exceptions as urllib3_errors

import ai
from graph_staged import Budget
from vision_provider import VisionError, VisionProvider, _transport_failure_metrics


IMAGE = 'data:image/png;base64,' + base64.b64encode(b'offline image').decode()
SECRET = 'private-api-key-and-message'
PRIVATE_URL = 'https://user:password@example.invalid/vision?api_key=' + SECRET
CONTENT = '{"body_text":"私有图片正文","graphs":[]}'


class InterruptedRaw:
    def __init__(self, chunks, error=None):
        self.chunks = chunks
        self.error = error
        self.closed = False
        self.released = False

    def stream(self, *args, **kwargs):
        yield from self.chunks
        if self.error is not None:
            raise self.error

    def close(self):
        self.closed = True

    def release_conn(self):
        self.released = True


def event(content=CONTENT, finish=None):
    chunk = {'model': 'qwen3-vl-plus', 'usage': {'total_tokens': 19},
             'choices': [{'delta': {'content': content, 'reasoning_content': SECRET},
                          'finish_reason': finish}]}
    return ('data: ' + json.dumps(chunk, ensure_ascii=False) + '\n\n').encode('utf-8')


def response(chunks, error=None, *, status=200, content_type='text/event-stream'):
    value = requests.Response()
    value.status_code = status
    value.headers['Content-Type'] = content_type
    value.encoding = requests.utils.get_encoding_from_headers(value.headers)
    value.raw = InterruptedRaw(chunks, error)
    value.close = Mock(wraps=value.close)
    return value


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    monkeypatch.setattr(requests.sessions.Session, 'send',
                        lambda *a, **k: pytest.fail('External requests are forbidden'))
    monkeypatch.setattr(ai, 'API_KEY', SECRET)
    monkeypatch.setattr(ai, 'VISION_ENABLED', True)


def invoke_failure(monkeypatch, *, value=None, error=None, capture=False, budget=None):
    post = Mock(return_value=value, side_effect=error)
    monkeypatch.setattr(ai.requests, 'post', post)
    provider = VisionProvider('qwen', capture=capture)
    budget = budget or Budget(calls=2)
    with pytest.raises(VisionError, match='^transport_failed$'):
        provider('Return JSON.', [IMAGE], budget)
    assert post.call_count == 1
    metric = budget.metrics[-1]
    assert metric['status'] == 'transport_failed' and metric['attempt'] == 1
    serialized = json.dumps(metric, ensure_ascii=False)
    for private in (SECRET, PRIVATE_URL, 'user:password', '私有图片正文', 'Authorization'):
        assert private not in serialized
    if value is not None:
        value.close.assert_called_once()
        assert value.raw.released
        if not value._content_consumed:
            assert value.raw.closed
    return metric, provider, budget, post


@pytest.mark.parametrize('capture', [False, True])
@pytest.mark.parametrize('finish', [None, 'stop'])
def test_wrapped_read_timeout_keeps_status_counts_and_audit_only_raw(monkeypatch, capture, finish):
    # Real Response.iter_content converts this to requests.ConnectionError.
    value = response([event(finish=finish)],
                     urllib3_errors.ReadTimeoutError(None, PRIVATE_URL, SECRET))
    metric, provider, budget, _ = invoke_failure(monkeypatch, value=value, capture=capture)

    assert budget.remaining == 1
    assert metric['exception_type'] == 'ConnectionError'
    assert 'urllib3.exceptions.ReadTimeoutError' in metric['exception_chain']
    assert metric['confirmed_timeout'] is True and metric['timeout_kind'] == 'read'
    assert metric['failure_phase'] == 'sse_stream'
    assert metric['transport_failure_kind'] == 'read_timeout'
    assert metric['response_headers_received'] is True and metric['http_status'] == 200
    assert metric['partial_stream'] is True and metric['stream_done_received'] is False
    assert metric['content_chars'] == len(CONTENT) and metric['sse_events_received'] == 1
    assert metric['reasoning_chars'] == len(SECRET) and metric['usage'] == {'total_tokens': 19}
    assert metric['finish_reason'] == finish
    if capture:
        assert provider.observations[0]['raw_content'] == CONTENT
        assert SECRET not in json.dumps(provider.observations, ensure_ascii=False)
    else:
        assert provider.observations == []


def test_disconnect_after_headers_but_before_first_event_is_observable(monkeypatch):
    value = response([], urllib3_errors.ProtocolError(SECRET, ConnectionResetError(104, SECRET)))
    metric, _, budget, _ = invoke_failure(monkeypatch, value=value)
    assert metric['failure_phase'] == 'sse_stream' and metric['http_status'] == 200
    assert metric['exception_type'] == 'ChunkedEncodingError'
    assert 'builtins.ConnectionResetError' in metric['exception_chain']
    assert metric['confirmed_timeout'] is False
    assert metric['transport_failure_kind'] == 'protocol'
    assert metric['sse_events_received'] == metric['content_chars'] == 0
    assert metric['partial_stream'] is True and budget.remaining == 1


def header_failure(kind):
    if kind == 'connect_timeout':
        return requests.ConnectTimeout(PRIVATE_URL), 'connect_timeout', True, 'connect'
    if kind == 'read_timeout':
        return requests.ReadTimeout(PRIVATE_URL), 'read_timeout', True, 'read'
    if kind == 'tls':
        cert = ssl.SSLCertVerificationError(1, PRIVATE_URL)
        inner = urllib3_errors.SSLError(cert)
        return requests.exceptions.SSLError(urllib3_errors.MaxRetryError(
            None, PRIVATE_URL, inner)), 'tls', False, None
    if kind == 'new_connection':
        inner = urllib3_errors.NewConnectionError(None, PRIVATE_URL)
        return requests.ConnectionError(urllib3_errors.MaxRetryError(
            None, PRIVATE_URL, inner)), 'connection', None, None
    if kind == 'dns':
        inner = urllib3_errors.NewConnectionError(None, PRIVATE_URL)
        inner.__cause__ = socket.gaierror(-2, SECRET)
        return requests.ConnectionError(urllib3_errors.MaxRetryError(
            None, PRIVATE_URL, inner)), 'dns', False, None
    return requests.ConnectionError(PRIVATE_URL), 'connection', None, None


@pytest.mark.parametrize('kind', ['connect_timeout', 'read_timeout', 'tls',
                                 'new_connection', 'dns', 'unknown_connection'])
def test_failure_before_response_headers_has_typed_bounded_evidence(monkeypatch, kind):
    error, expected_kind, timeout, timeout_kind = header_failure(kind)
    metric, provider, budget, _ = invoke_failure(monkeypatch, error=error)
    assert metric['failure_phase'] == 'response_headers'
    assert metric['transport_failure_kind'] == expected_kind
    assert metric['confirmed_timeout'] is timeout and metric['timeout_kind'] == timeout_kind
    assert metric['response_headers_received'] is False and 'http_status' not in metric
    assert metric['partial_stream'] is False and metric['content_chars'] == 0
    assert metric['exception_chain_truncated'] is False
    assert 1 <= len(metric['exception_chain']) <= 16
    assert budget.remaining == 1 and not provider.observations
    if kind == 'tls':
        assert 'ssl.SSLCertVerificationError' in metric['exception_chain']
    if kind == 'new_connection':
        # NewConnectionError's superclass is NOT proof of a connect timeout.
        assert 'urllib3.exceptions.NewConnectionError' in metric['exception_chain']


def test_known_http_error_is_kept_when_error_body_read_times_out(monkeypatch):
    value = response([b'{"error":"' + SECRET.encode()],
                     urllib3_errors.ReadTimeoutError(None, PRIVATE_URL, SECRET),
                     status=503, content_type='application/json')
    metric, _, _, _ = invoke_failure(monkeypatch, value=value)
    assert metric['http_status'] == 503 and metric['response_headers_received'] is True
    assert metric['failure_phase'] == 'response_body' and metric['partial_stream'] is False
    assert metric['confirmed_timeout'] is True and metric['content_chars'] == 0


def test_clean_eof_without_terminal_event_never_accepts_valid_json_prefix(monkeypatch):
    value = response([event()])  # Syntactically valid content, missing stop/DONE.
    metric, provider, budget, _ = invoke_failure(monkeypatch, value=value, capture=True)
    assert metric['transport_failure_kind'] == 'incomplete_stream'
    assert metric['confirmed_timeout'] is False and metric['stream_done_received'] is False
    assert metric['content_chars'] == len(CONTENT) and provider.observations[0]['raw_content'] == CONTENT
    assert budget.remaining == 1


def test_wall_deadline_has_its_own_timeout_kind(monkeypatch):
    value = response([event()])
    monkeypatch.setattr(ai.requests, 'post', Mock(return_value=value))
    with pytest.raises(TimeoutError) as caught:
        ai._request_qwen_completion({}, {}, wall_deadline=-1)
    metric = _transport_failure_metrics(caught.value)
    assert metric['failure_phase'] == 'sse_stream' and metric['http_status'] == 200
    assert metric['confirmed_timeout'] is True and metric['timeout_kind'] == 'wall_deadline'
    assert metric['transport_failure_kind'] == 'wall_deadline'
    assert metric['sse_events_received'] == 0
    value.close.assert_called_once()


def test_transport_failures_cannot_spend_more_than_two_total_requests(monkeypatch):
    post = Mock(side_effect=requests.ConnectionError(PRIVATE_URL))
    monkeypatch.setattr(ai.requests, 'post', post)
    provider = VisionProvider('qwen')
    budget = Budget(calls=2)
    for _ in range(2):
        with pytest.raises(VisionError, match='^transport_failed$'):
            provider('JSON.', [IMAGE], budget)
    with pytest.raises(TimeoutError, match='vision_budget'):
        provider('JSON.', [IMAGE], budget)
    assert post.call_count == 2 and budget.remaining == 0 and len(budget.metrics) == 2
    assert all(metric['attempt'] == 1 for metric in budget.metrics)


def test_exception_chain_is_bounded_and_never_serializes_messages():
    error = requests.ConnectionError(PRIVATE_URL)
    current = error
    for _ in range(30):
        current.__cause__ = RuntimeError(SECRET)
        current = current.__cause__
    current.__cause__ = error
    metric = _transport_failure_metrics(error)
    assert len(metric['exception_chain']) == 16 and metric['exception_chain_truncated'] is True
    assert metric['confirmed_timeout'] is None
    assert PRIVATE_URL not in json.dumps(metric) and SECRET not in json.dumps(metric)


def test_json_gateway_success_keeps_existing_result_contract(monkeypatch):
    result = {'model': 'qwen3-vl-plus', 'choices': [{'message': {'content': '{"graphs":[]}'},
                                                 'finish_reason': 'stop'}]}
    value = response([], content_type='application/json')
    value.raw = io.BytesIO(json.dumps(result).encode())
    monkeypatch.setattr(ai.requests, 'post', Mock(return_value=value))
    budget = Budget(calls=2)
    assert VisionProvider('qwen')('JSON.', [IMAGE], budget) == {'graphs': []}
    assert budget.remaining == 1 and budget.metrics[0]['status'] == 200
    value.close.assert_called_once()


def test_json_decode_error_is_not_misclassified_as_transport_failure(monkeypatch):
    # requests.JSONDecodeError inherits BOTH ValueError and RequestException.
    value = response([b'{not valid json'], content_type='application/json')
    monkeypatch.setattr(ai.requests, 'post', Mock(return_value=value))
    budget = Budget(calls=2)
    with pytest.raises(VisionError, match='^http_error_http_200$'):
        VisionProvider('qwen')('JSON.', [IMAGE], budget)
    metric = budget.metrics[0]
    assert metric['http_status'] == 200 and metric['status'] == 'http_error'
    assert 'failure_phase' not in metric and 'confirmed_timeout' not in metric
    assert budget.remaining == 1
    value.close.assert_called_once()
