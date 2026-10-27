"""Fast OCR only retries Qwen when there were ZERO HTTP response bytes.

All model outputs here are synthetic and no network or paid call is made.
"""
import copy

import pytest

from graph_agent_runtime import AgentBudget
from graph_fast_pipeline import FastRunner, configured_fast_budget
from test_graph_fast_pipeline import Provider, Specialist, document, prepared
from vision_provider import VisionError


NO_HEADERS = {
    'status': 'transport_failed', 'failure_phase': 'response_headers',
    'transport_failure_kind': 'timeout', 'timeout_kind': 'unspecified',
    'response_headers_received': False, 'request_started': True,
    'partial_stream': False, 'confirmed_timeout': True,
    'content_chars': 0
}


class PreheaderProvider(Provider):
    def __init__(self, *, failure=None, fail_count=1):
        super().__init__(document())
        self.failure = NO_HEADERS if failure is None else failure
        self.fail_count = fail_count
        self.attempts = 0

    def __call__(self, prompt, images, budget):
        self.attempts += 1
        if self.attempts <= self.fail_count:
            budget.take()
            budget.metrics.append(copy.deepcopy(self.failure))
            raise VisionError('transport_failed')
        return super().__call__(prompt, images, budget)


def test_verified_no_header_qwen_timeout_recovers_once_without_skipping_validation(prepared):
    _, run, handles = prepared
    qwen = PreheaderProvider()
    review = Specialist(AssertionError('No review for completely specified graph'))
    result, _ = run(qwen, review)
    assert qwen.attempts == 2
    assert len(qwen.requests) == 1
    assert review.requests == []
    assert result['complete'] is True
    workflow = result['semantic_workflow']
    assert workflow['role_counts'] == {'fast_main': 2}
    assert any(row['status'] == 'network_recovery' and row['role'] == 'fast_main'
               for row in workflow['roles'])
    assert [row['status'] for row in result['remote_metrics']] == ['transport_failed', 200]
    assert workflow['final_validation']['status'] == 'completed'
    assert all(h.closed for h in handles)


@pytest.mark.parametrize('change', [
    {'failure_phase': 'sse_stream', 'response_headers_received': True,
     'partial_stream': True, 'content_chars': 177, 'transport_failure_kind': 'read_timeout'},
    {'failure_phase': 'response_headers', 'response_headers_received': True},
    {'failure_phase': 'response_headers', 'content_chars': 11},
    {'failure_phase': 'response_headers', 'confirmed_timeout': False,
     'transport_failure_kind': 'tls'},
    {'failure_phase': 'response_headers', 'request_started': False},
    {'failure_phase': 'response_headers', 'transport_failure_kind': 'wall_deadline',
     'timeout_kind': 'wall_deadline'},
])
def test_incomplete_stream_tls_identity_or_wall_deadline_never_spends_retry(prepared, change):
    _, run, _ = prepared
    qwen = PreheaderProvider(failure={**NO_HEADERS, **change})
    with pytest.raises(VisionError):
        run(qwen)
    assert qwen.attempts == 1


def test_second_preheader_timeout_does_not_create_third_attempt(prepared):
    _, run, _ = prepared
    qwen = PreheaderProvider(fail_count=5)
    with pytest.raises(VisionError, match='transport_failed'):
        run(qwen)
    assert qwen.attempts == 2


def test_glm_local_review_preheader_timeout_is_not_replayed(prepared):
    _, run, _ = prepared
    initial = document()
    initial['graphs'][0]['edges'][0]['direction'] = 'unknown'
    qwen = Provider(initial)
    specialist = PreheaderProvider()
    specialist.name = 'glm'
    from vision_provider import GLM_5V_TURBO_MODEL
    specialist.model = GLM_5V_TURBO_MODEL
    result, _ = run(qwen, specialist)
    assert specialist.attempts == 1
    assert len(qwen.requests) == 1
    assert result['complete'] is False
    assert result['semantic_workflow']['local_review']['status'] == 'failed'


def test_fast_budget_has_no_network_recovery_for_unverified_failures():
    budget = configured_fast_budget()
    runner = FastRunner(budget)
    assert budget.initial_calls == 3
    assert budget.max_network_recoveries == 1
    assert not runner._network_recovery_allowed(
        'fast_main', VisionError('transport_failed'),
        {'failure_phase': 'response_headers'})
    assert not runner._network_recovery_allowed(
        'fast_local_review', VisionError('transport_failed'), NO_HEADERS)
    assert runner._network_recovery_allowed(
        'fast_main', VisionError('transport_failed'), NO_HEADERS)
