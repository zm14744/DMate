"""Offline Qwen SSE reception through real Requests.Response decoding.

Only the HTTP boundary is injected. No credentials or external requests are
needed; provider parsing, response closure and the no-retry budget stay real.
"""
import base64
import io
import json
from unittest.mock import Mock

import pytest
import requests

import ai
from graph_staged import Budget
from vision_provider import VisionError, VisionProvider


IMAGE = 'data:image/png;base64,' + base64.b64encode(b'offline fixture').decode()


def sse(*chunks):
    return (''.join('data: ' + json.dumps(chunk, ensure_ascii=False) + '\n\n'
                    for chunk in chunks) + 'data: [DONE]\n\n').encode('utf-8')


def response(raw, *, content_type='text/event-stream', status=200):
    value = requests.Response()
    value.status_code = status
    value.headers['Content-Type'] = content_type
    # This is how the real HTTP adapter sets Response.encoding. A plain
    # text/event-stream header triggers Requests' ISO-8859-1 fallback.
    value.encoding = requests.utils.get_encoding_from_headers(value.headers)
    value.raw = io.BytesIO(raw)
    value.close = Mock(wraps=value.close)
    return value


@pytest.fixture(autouse=True)
def forbid_external_requests(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail('This protocol test must never send an external request')
    monkeypatch.setattr(requests.sessions.Session, 'send', denied)


def inject_response(monkeypatch, value):
    post = Mock(return_value=value)
    monkeypatch.setattr(ai.requests, 'post', post)
    monkeypatch.setattr(ai, 'API_KEY', 'offline-test-key')
    monkeypatch.setattr(ai, 'VISION_ENABLED', True)
    return post


@pytest.mark.parametrize('content_type', [
    'text/event-stream',
    'text/event-stream; charset=utf-8',
    'text/event-stream; charset=iso-8859-1',
])
def test_sse_is_utf8_regardless_of_charset_header(content_type, monkeypatch):
    expected = {'body_text': '顶点甲与乙，𝒙∈ℝ。' * 80, 'graphs': []}
    content = json.dumps(expected, ensure_ascii=False)
    half = len(content) // 2
    value = response(sse(
        {'model': 'qwen3-vl-plus', 'choices': [{'delta': {
            'content': content[:half]}, 'finish_reason': None}]},
        {'model': 'qwen3-vl-plus', 'choices': [{'delta': {
            'content': content[half:]}, 'finish_reason': 'stop'}]},
        {'model': 'qwen3-vl-plus', 'choices': [], 'usage': {'total_tokens': 37}},
    ), content_type=content_type)
    post = inject_response(monkeypatch, value)
    budget = Budget(calls=2)

    result = VisionProvider('qwen')('Return JSON.', [IMAGE], budget)

    assert result == expected
    assert value.encoding == 'utf-8'
    assert post.call_count == 1 and budget.remaining == 1
    assert post.call_args.kwargs['json']['stream'] is True
    assert budget.metrics[0]['finish_reason'] == 'stop'
    assert budget.metrics[0]['usage'] == {'total_tokens': 37}
    value.close.assert_called_once()


def test_http_error_body_and_response_closure_are_unchanged(monkeypatch):
    body = json.dumps({'error': {'message': '限流，请稍后再试'}}, ensure_ascii=False)
    value = response(body.encode('utf-8'), content_type='application/json', status=429)
    post = inject_response(monkeypatch, value)

    status, error, parsed = ai._request_qwen_completion({}, {})

    assert status == 429 and error == body and parsed is None
    assert post.call_count == 1
    value.close.assert_called_once()


def test_midstream_timeout_never_returns_partial_graph_or_retries(monkeypatch):
    class InterruptedRaw:
        closed = False

        def stream(self, *args, **kwargs):
            yield sse({'model': 'qwen3-vl-plus', 'choices': [{'delta': {
                'content': '{"body_text":"未完成的题干'}, 'finish_reason': None}]}).split(
                    b'data: [DONE]')[0]
            raise requests.Timeout('offline interrupted stream')

        def close(self):
            self.closed = True

    value = response(b'')
    value.raw = InterruptedRaw()
    post = inject_response(monkeypatch, value)
    budget = Budget(calls=2)

    with pytest.raises(VisionError, match='^transport_failed$'):
        VisionProvider('qwen')('Return JSON.', [IMAGE], budget)

    assert post.call_count == 1 and budget.remaining == 1
    assert budget.metrics[0]['status'] == 'transport_failed'
    assert budget.metrics[0]['confirmed_timeout'] is True
    assert value.raw.closed
    value.close.assert_called_once()


@pytest.mark.parametrize('finish_reason,error', [
    ('length', 'truncated_output'),
    ('network_error', 'upstream_network_error'),
])
def test_upstream_failure_finish_is_not_accepted_even_with_valid_json(
        finish_reason, error, monkeypatch):
    value = response(sse({'model': 'qwen3-vl-plus', 'choices': [{'delta': {
        'content': '{"body_text":"题干","graphs":[]}'},
        'finish_reason': finish_reason}]}))
    post = inject_response(monkeypatch, value)
    budget = Budget(calls=2)

    with pytest.raises(VisionError, match='^' + error + '$'):
        VisionProvider('qwen')('Return JSON.', [IMAGE], budget)

    assert post.call_count == 1 and budget.remaining == 1
    assert budget.metrics[0]['status'] == error
    value.close.assert_called_once()
