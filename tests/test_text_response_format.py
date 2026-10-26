"""OCR's structured output option must not constrain ordinary chat replies."""
import json

import pytest
import requests

import ai


def test_ordinary_text_request_still_accepts_plain_text_without_json_mode(monkeypatch):
    monkeypatch.setattr(ai, 'DEEPSEEK_API_KEY', 'offline-test-key')
    sent = []

    def fake_network(session, prepared, **kwargs):
        payload = json.loads(prepared.body)
        sent.append(payload)
        response = requests.Response()
        response.status_code = 200
        response.encoding = 'utf-8'
        response._content = json.dumps({
            'model': payload['model'],
            'choices': [{'message': {'content': '这是一条普通回复。'}, 'finish_reason': 'stop'}],
        }, ensure_ascii=False).encode()
        response._content_consumed = True
        return response

    monkeypatch.setattr(requests.sessions.Session, 'send', fake_network)
    result = ai._request_text_completion([{'role': 'user', 'content': '离线测试'}], retries=0)

    assert len(sent) == 1
    assert 'response_format' not in sent[0]
    assert result['ok'] is True and result['content'] == '这是一条普通回复。'


def test_unsupported_output_contract_fails_before_any_send(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Invalid output contract must not start a network request')

    monkeypatch.setattr(requests.sessions.Session, 'send', forbidden)
    with pytest.raises(ValueError, match='Unsupported text response format'):
        ai._request_text_completion([], response_format={'type': 'json_schema'})
