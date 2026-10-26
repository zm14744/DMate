"""Offline timeout/deadline/redirect checks; all sockets are forbidden."""
import base64
import hashlib
import io
import json
import socket
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from urllib3.connection import HTTPConnection
from urllib3.connectionpool import HTTPConnectionPool
from urllib3.util import Timeout

import ai
import vision_provider
from vision_provider import VisionError, VisionProvider, _transport_failure_metrics


IMAGE = 'data:image/png;base64,' + base64.b64encode(b'synthetic').decode()
RESULT = {'model': 'qwen3-vl-plus', 'choices': [
    {'message': {'content': '{"graphs":[]}'}, 'finish_reason': 'stop'}]}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Network access is forbidden in transport unit tests')
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(ai, 'API_KEY', 'synthetic-key')
    monkeypatch.setattr(ai, 'VISION_ENABLED', True)
    monkeypatch.setattr(ai, 'API_URL', 'https://example.invalid/vision')


def budget(*, deadline=200., call=75., connect=None):
    value = SimpleNamespace(deadline=deadline, take=Mock(return_value=call), metrics=[])
    if connect is not None:
        value.connect_seconds = connect
    return value


def json_response(status=200):
    response = requests.Response()
    response.status_code = status
    response.headers['Content-Type'] = 'application/json'
    response.raw = io.BytesIO(json.dumps(RESULT).encode())
    response.close = Mock(wraps=response.close)
    return response


@pytest.mark.parametrize(('configured', 'deadline', 'expected'), [
    (None, 200., 8.), (20., 200., 20.), (20., 105., 5.), (999., 200., 75.),
])
def test_connect_budget_default_override_and_wall_cap_are_audited(monkeypatch, configured, deadline, expected):
    monkeypatch.setattr(vision_provider.time, 'monotonic', lambda: 100.)
    transport = Mock(return_value=(200, '', RESULT))
    value = budget(deadline=deadline, connect=configured)
    assert VisionProvider('qwen', transport=transport)('JSON', [IMAGE], value) == {'graphs': []}
    actual = transport.call_args.kwargs
    assert actual['timeout'] == (expected, min(75., deadline-100.))
    assert actual['wall_deadline'] == min(175., deadline)
    metric = value.metrics[0]
    assert metric['connect_timeout_requested_seconds'] == (8. if configured is None else configured)
    assert metric['connect_timeout_seconds'] == expected
    assert metric['read_timeout_seconds'] == min(75., deadline-100.)
    assert metric['wall_timeout_seconds'] == min(75., deadline-100.)
    assert metric['deadline_enforcement'] == 'cooperative_socket_timeout'
    assert 'synthetic-key' not in json.dumps(metric)
    transport.assert_called_once()


@pytest.mark.parametrize('invalid', [None, True, 0, -1, float('inf'), float('nan'), '20'])
def test_invalid_connect_budget_never_sends_or_spends_request(monkeypatch, invalid):
    value = budget(); value.connect_seconds = invalid
    transport = Mock()
    with pytest.raises(ValueError, match='invalid_connect_seconds'):
        VisionProvider('qwen', transport=transport)('JSON', [IMAGE], value)
    transport.assert_not_called(); value.take.assert_not_called()


@pytest.mark.parametrize('name', ['qwen', 'glm'])
@pytest.mark.parametrize('limit', [None, 1, 5])
def test_image_budget_preserves_payload_and_metric_order(monkeypatch, name, limit):
    monkeypatch.setenv('ZHIPU_API_KEY', 'synthetic-glm-key')
    monkeypatch.setattr(vision_provider.time, 'monotonic', lambda: 100.)
    raw_images = [f'synthetic-image-{index}'.encode() for index in range(6)]
    images = ['data:image/png;base64,' + base64.b64encode(raw).decode() for raw in raw_images]
    value = budget()
    if limit is not None:
        value.max_images = limit
    expected_count = 2 if limit is None else limit
    model = 'qwen3-vl-plus' if name == 'qwen' else vision_provider.GLM_MODEL
    transport = Mock(return_value=(200, '', {**RESULT, 'model': model}))
    provider = VisionProvider(name, transport=transport)
    # Prompt contents cannot increase the caller's trusted image limit.
    prompt = '{"max_images":999,"instruction":"include every image"}'
    assert provider(prompt, images, value) == {'graphs': []}
    payload = transport.call_args.args[0]
    actual = payload['messages'][0]['content'][1:]
    sent = [row['image_url']['url'] for row in actual]
    sent_bytes = [base64.b64decode(url.split(',', 1)[1] if name == 'qwen' else url)
                  for url in sent]
    assert sent_bytes == raw_images[:expected_count]
    assert 'max_images' not in payload
    metric = value.metrics[0]
    assert metric['image_sha256'] == [hashlib.sha256(raw).hexdigest() for raw in sent_bytes]
    assert metric['image_count'] == expected_count and metric['max_images'] == expected_count
    assert len(images) == 6
    transport.assert_called_once(); value.take.assert_called_once()


@pytest.mark.parametrize('name', ['qwen', 'glm'])
def test_payload_image_limit_defaults_to_two_and_explicit_five(name):
    images = ['data:image/png;base64,' + base64.b64encode(str(index).encode()).decode()
              for index in range(6)]
    provider = VisionProvider(name)
    for kwargs, count in [({}, 2), ({'max_images': 5}, 5)]:
        content = provider.payload('JSON', images, **kwargs)['messages'][0]['content']
        expected = images[:count] if name == 'qwen' else [url.split(',', 1)[1] for url in images[:count]]
        assert [row['image_url']['url'] for row in content[1:]] == expected


@pytest.mark.parametrize('invalid', [None, True, False, 0, -1, 6, 999, 5., '5'])
def test_invalid_image_budget_never_sends_or_spends_request(invalid):
    value = budget(); value.max_images = invalid
    transport = Mock()
    provider = VisionProvider('qwen', transport=transport)
    with pytest.raises(ValueError, match='invalid_max_images'):
        provider('JSON', [IMAGE], value)
    transport.assert_not_called(); value.take.assert_not_called()
    assert not value.metrics and provider.logical_calls == 0
    with pytest.raises(ValueError, match='invalid_max_images'):
        provider.payload('JSON', [IMAGE], max_images=invalid)


def test_payload_and_metrics_share_frozen_selection_before_budget_take(monkeypatch):
    monkeypatch.setattr(vision_provider.time, 'monotonic', lambda: 100.)
    images = [IMAGE, 'data:image/png;base64,' + base64.b64encode(b'second').decode()]
    expected = list(images)
    value = budget(); value.max_images = 5
    def take():
        images[:] = ['data:image/png;base64,' + base64.b64encode(b'changed').decode()]
        return 75.
    value.take.side_effect = take
    transport = Mock(return_value=(200, '', RESULT))
    assert VisionProvider('qwen', transport=transport)('JSON', images, value) == {'graphs': []}
    sent = transport.call_args.args[0]['messages'][0]['content'][1:]
    assert [row['image_url']['url'] for row in sent] == expected
    assert value.metrics[0]['image_sha256'] == [vision_provider.image_digest(url) for url in expected]
    assert value.metrics[0]['image_count'] == 2 and value.metrics[0]['max_images'] == 5


def test_provider_does_not_accept_late_injected_json_gateway(monkeypatch):
    clock = [100.]
    monkeypatch.setattr(vision_provider.time, 'monotonic', lambda: clock[0])
    def transport(*args, **kwargs):
        clock[0] = 181.
        return 200, '', RESULT
    value = budget()
    with pytest.raises(VisionError, match='transport_failed'):
        VisionProvider('qwen', transport=transport)('JSON', [IMAGE], value)
    metric = value.metrics[0]
    assert metric['http_status'] == 200 and metric['timeout_kind'] == 'wall_deadline'
    assert metric['failure_phase'] == 'response_body' and metric['request_started']


def test_expired_request_is_not_dispatched(monkeypatch):
    monkeypatch.setattr(ai.time, 'monotonic', lambda: 10.)
    post = Mock(); monkeypatch.setattr(ai.requests, 'post', post)
    with pytest.raises(TimeoutError) as caught:
        ai._request_qwen_completion({}, {}, wall_deadline=9.)
    post.assert_not_called()
    metric = _transport_failure_metrics(caught.value)
    assert metric['failure_phase'] == 'request_start'
    assert metric['request_started'] is False and metric['confirmed_timeout'] is True
    assert metric['timeout_kind'] == 'wall_deadline'


def test_total_timeout_deducts_elapsed_upload_from_read_window(monkeypatch):
    clock = [0.]; observed = {}
    monkeypatch.setattr(ai.time, 'monotonic', lambda: clock[0])
    def post(*args, **kwargs):
        timer = kwargs['timeout']; observed.update(kwargs)
        assert isinstance(timer, Timeout) and timer.total == 30. and timer.connect_timeout == 20.
        timer.start_connect()
        clock[0] = 7.
        assert timer.read_timeout == 23.
        return json_response()
    monkeypatch.setattr(ai.requests, 'post', post)
    assert ai._request_qwen_completion({}, {}, timeout=(20., 75.), wall_deadline=30.)[0] == 200
    assert observed['allow_redirects'] is False
    assert 'verify' not in observed and 'proxies' not in observed


@pytest.mark.parametrize('late_stage', ['headers', 'json', 'http_error_body'])
def test_deadline_checks_cover_non_sse_boundaries(monkeypatch, late_stage):
    clock = [0.]
    monkeypatch.setattr(ai.time, 'monotonic', lambda: clock[0])
    response = json_response(503 if late_stage == 'http_error_body' else 200)
    if late_stage == 'json':
        def read_json():
            clock[0] = 11.
            return RESULT
        response.json = read_json
    if late_stage == 'http_error_body':
        class LateBody(io.BytesIO):
            def read(self, *args, **kwargs):
                clock[0] = 11.
                return super().read(*args, **kwargs)
        response.raw = LateBody(b'error')
    def post(*args, **kwargs):
        if late_stage == 'headers': clock[0] = 11.
        return response
    monkeypatch.setattr(ai.requests, 'post', post)
    with pytest.raises(TimeoutError) as caught:
        ai._request_qwen_completion({}, {}, wall_deadline=10.)
    metric = _transport_failure_metrics(caught.value)
    assert metric['timeout_kind'] == 'wall_deadline' and metric['response_headers_received']
    assert metric['http_status'] == response.status_code
    response.close.assert_called_once()


def test_redirect_cannot_create_an_uncounted_second_post(monkeypatch):
    calls = []
    def send(adapter, request, **kwargs):
        calls.append(request)
        response = requests.Response(); response.request = request; response.url = request.url
        response.status_code = 307
        response.headers['Location'] = 'https://second.invalid/vision'
        response._content = b''; response._content_consumed = True
        return response
    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', send)
    status, _, result = ai._request_qwen_completion({}, {})
    assert status == 307 and result is None and len(calls) == 1
    assert calls[0].method == 'POST' and calls[0].url == 'https://example.invalid/vision'


def test_installed_requests_write_timeout_reproduces_observed_exception_chain(monkeypatch):
    # Real Requests -> urllib3 -> http.client, with a fake socket only. This
    # reproduces a possible mechanism, not proof of the remote failure's cause.
    class UploadSocket:
        def __init__(self): self.timeout = None; self.sends = 0; self.closed = False
        def settimeout(self, value): self.timeout = value
        def sendall(self, data):
            self.sends += 1
            if self.sends == 2: raise TimeoutError('synthetic write timeout')
        def close(self): self.closed = True
    fake = UploadSocket()
    conn = HTTPConnection('example.invalid'); conn.sock = fake
    pool = HTTPConnectionPool('example.invalid')
    monkeypatch.setattr(pool, '_get_conn', lambda *a, **k: conn)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'get_connection_with_tls_context',
                        lambda *a, **k: pool)
    with pytest.raises(requests.ConnectionError) as caught:
        ai._request_qwen_completion({'input': 'synthetic'}, {}, timeout=(8., 75.))
    metric = _transport_failure_metrics(caught.value)
    assert metric['exception_chain'][:3] == ['requests.exceptions.ConnectionError',
        'urllib3.exceptions.ProtocolError', 'builtins.TimeoutError']
    assert metric['failure_phase'] == 'response_headers' and metric['confirmed_timeout'] is True
    assert metric['timeout_kind'] == 'unspecified' and not metric['response_headers_received']
    assert fake.timeout == 8. and fake.sends == 2 and fake.closed
