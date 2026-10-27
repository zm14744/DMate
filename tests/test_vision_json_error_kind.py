"""Strict parsing stays strict; JSON diagnostics never include private text."""
import json
import time

import pytest
import requests

from vision_provider import GLM_5V_TURBO_MODEL, VisionError, VisionProvider


class Budget:
    def __init__(self):
        self.deadline = time.monotonic() + 30
        self.metrics = []
        self.calls = 0

    def take(self):
        self.calls += 1
        return 10


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setenv('ZHIPU_API_KEY', 'offline-test-key')
    monkeypatch.setattr(requests.sessions.Session, 'send',
                        lambda *args, **kwargs: pytest.fail('No network is allowed'))


@pytest.mark.parametrize('content,kind', [
    ('{"private":"secret-value"} trailing', 'extra_data'),
    ('{"private":"secret-value" "x":1}', 'missing_delimiter'),
    ('{"private" "secret-value"}', 'missing_delimiter'),
    ('{"private": }', 'invalid_value'),
    ('{"private":"secret-value",}', 'invalid_value'),
    ('{"private":"secret-value', 'unterminated_string'),
    ('{"private":"secret-value\\q"}', 'other'),
])
def test_invalid_json_has_bounded_error_kind_and_is_never_accepted(content, kind):
    calls = []
    def transport(*args, **kwargs):
        calls.append(True)
        return 200, '', {'model': GLM_5V_TURBO_MODEL, 'choices': [
            {'message': {'content': content}, 'finish_reason': 'stop'}]}
    provider = VisionProvider('glm', model=GLM_5V_TURBO_MODEL, retries=0, transport=transport)
    budget = Budget()
    with pytest.raises(VisionError, match='^invalid_output$'):
        provider('Return the original task as JSON.', [], budget)
    assert len(calls) == budget.calls == 1
    assert len(budget.metrics) == 1
    metric = budget.metrics[0]
    assert metric['status'] == 'invalid_output' and metric['output_error'] == 'json_syntax'
    assert set(metric['json_error']) == {'line', 'column', 'position', 'kind'}
    assert metric['json_error']['kind'] == kind
    assert all(type(metric['json_error'][k]) is int for k in ('line', 'column', 'position'))
    encoded = json.dumps(metric, allow_nan=False)
    assert 'private' not in encoded and 'secret-value' not in encoded
    assert 'msg' not in metric['json_error'] and not provider.observations


@pytest.mark.parametrize('content,error_kind', [
    ('{"private": NaN}', 'non_finite_json_number'),
    ('[]', 'root_not_object'),
])
def test_non_syntax_invalid_outputs_are_not_reclassified_as_json_syntax(content, error_kind):
    provider = VisionProvider('glm', model=GLM_5V_TURBO_MODEL, retries=0,
        transport=lambda *args, **kwargs: (200, '', {'model': GLM_5V_TURBO_MODEL,
            'choices': [{'message': {'content': content}, 'finish_reason': 'stop'}]}))
    budget = Budget()
    with pytest.raises(VisionError, match='^invalid_output$'):
        provider('JSON', [], budget)
    assert budget.metrics[0]['output_error'] == error_kind
    assert 'json_error' not in budget.metrics[0]
