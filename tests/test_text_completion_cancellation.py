"""Cancellation prevents each actual send; default text behavior stays intact."""
from unittest.mock import Mock

import pytest

import ai


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.setattr(ai, '_text_provider_configs', lambda *a: [
        {'id': 'deepseek', 'name': 'DeepSeek', 'model': 'deepseek-flash',
         'api_key': 'synthetic', 'url': 'https://example.invalid/text'}])
    session = Mock()
    success = Mock(status_code=200, ok=True)
    success.json.return_value = {'choices': [{'message': {'content': 'synthetic result'}}]}
    session.post.return_value = success
    monkeypatch.setattr(ai, '_text_http_session', lambda: session)
    monkeypatch.setattr(ai.time, 'sleep', lambda *a: None)
    return session


def test_cancelled_text_completion_never_posts(transport):
    result = ai._request_text_completion([], cancelled=lambda: True)
    assert result == {'ok': False, 'cancelled': True}
    transport.post.assert_not_called()


def test_cancelled_retry_does_not_send_after_first_failure(transport):
    transport.post.return_value = Mock(status_code=503)
    cancelled = Mock(side_effect=[False, True])
    result = ai._request_text_completion([], retries=2, cancelled=cancelled)
    assert result == {'ok': False, 'cancelled': True}
    assert transport.post.call_count == 1 and cancelled.call_count == 2


@pytest.mark.parametrize('callback', [None, lambda: False])
def test_default_or_not_cancelled_keeps_success_contract(transport, callback):
    result = ai._request_text_completion([], retries=0, cancelled=callback)
    assert result['ok'] and result['content'] == 'synthetic result'
    transport.post.assert_called_once()
