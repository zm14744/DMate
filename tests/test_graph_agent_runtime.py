"""Per-attempt deadline classification; offline providers and synthetic bytes."""
import base64
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
import requests

from graph_agent_runtime import AgentBudget, RoleRunner
from vision_provider import VisionError, VisionProvider


def budget():
    return AgentBudget(seconds=60, calls=8, call_seconds=10,
                       task_id='test_task', source_sha256='a'*64)


def answer(role='connections', revision=3):
    return {'role': role, 'base_revision': revision, 'coordinate_space': 'original_1000'}


def failure(**changes):
    return {'status': 'transport_failed', 'http_status': 200, 'failure_phase': 'sse_stream',
            'transport_failure_kind': 'wall_deadline', 'timeout_kind': 'wall_deadline',
            'partial_stream': True, 'response_headers_received': True,
            'stream_done_received': False, 'content_chars': 1234,
            'wall_timeout_seconds': 10., 'seconds': 10.001, **changes}


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    monkeypatch.setattr(requests.sessions.Session, 'send',
                        lambda *a, **k: pytest.fail('No network is allowed'))


def test_local_output_wall_deadline_is_not_retried_and_preserves_bound_failure_history():
    ledger = budget(); calls = []
    def remote(prompt, images, attempt):
        attempt.take(); calls.append(True); attempt.metrics.append(failure())
        raise VisionError('transport_failed')
    with pytest.raises(VisionError) as caught:
        RoleRunner(ledger, provider=remote).call('connections', 'JSON', {}, [], revision=3)
    error = caught.value
    assert error.kind == 'output_deadline_exceeded' and error.status == 200
    assert isinstance(error.__cause__, VisionError) and error.__cause__.kind == 'transport_failed'
    assert len(calls) == 1 and ledger.remaining == 7 and ledger.network_recoveries == 0
    assert len(ledger.metrics) == 1 and ledger.metrics[0]['status'] == 'transport_failed'
    assert ledger.events[-1]['status'] == 'failed'
    assert ledger.events[-1]['error_kind'] == 'output_deadline_exceeded'
    assert error.audit['accepted'] is False and not error.audit['same_request_recovery_allowed']
    facts = error.audit['failure_facts']
    assert {k: facts[k] for k in ('agent_role', 'state_revision', 'role_invocation', 'task_id', 'source_sha256')} == {
        'agent_role': 'connections', 'state_revision': 3, 'role_invocation': 1,
        'task_id': ledger.task_id, 'source_sha256': ledger.source_sha256}
    assert facts['content_chars'] == 1234 and facts['stream_done_received'] is False


@pytest.mark.parametrize('field', ['timeout_kind', 'transport_failure_kind'])
def test_either_explicit_local_wall_deadline_fact_is_sufficient(field):
    ledger = budget()
    def remote(prompt, images, attempt):
        attempt.take(); attempt.metrics.append({'status': 'transport_failed', field: 'wall_deadline'})
        raise VisionError('transport_failed')
    with pytest.raises(VisionError, match='output_deadline_exceeded'):
        RoleRunner(ledger, provider=remote).call('connections', 'JSON', {}, [], revision=3)
    assert ledger.network_recoveries == 0


@pytest.mark.parametrize('phase,kind,timeout_kind,partial', [
    ('response_headers', 'timeout', 'unspecified', False),
    ('request_start', 'connect_timeout', 'connect', False),
    ('sse_stream', 'read_timeout', 'read', True),
])
def test_non_wall_transient_timeouts_keep_bounded_recovery(phase, kind, timeout_kind, partial):
    ledger = budget(); calls = []
    def remote(prompt, images, attempt):
        attempt.take(); calls.append(True)
        if len(calls) == 1:
            attempt.metrics.append(failure(failure_phase=phase, transport_failure_kind=kind,
                timeout_kind=timeout_kind, partial_stream=partial, http_status=None,
                response_headers_received=partial))
            raise VisionError('transport_failed')
        attempt.metrics.append({'status': 200}); return answer()
    assert RoleRunner(ledger, provider=remote).call('connections', 'JSON', {}, [], revision=3) == answer()
    assert len(calls) == 2 and ledger.network_recoveries == 1
    assert [m['status'] for m in ledger.metrics] == ['transport_failed', 200]
    recovery = next(e for e in ledger.events if e['status'] == 'network_recovery')
    assert recovery['error_kind'] == 'transport_failed'
    assert recovery['failure_facts']['timeout_kind'] == timeout_kind


def test_header_failure_then_output_deadline_keeps_both_sends_without_third_attempt():
    ledger = budget(); calls = []
    def remote(prompt, images, attempt):
        attempt.take(); calls.append(True)
        attempt.metrics.append(failure() if len(calls) == 2 else
            failure(failure_phase='response_headers', timeout_kind='unspecified',
                    transport_failure_kind='timeout', partial_stream=False, http_status=None))
        raise VisionError('transport_failed')
    with pytest.raises(VisionError, match='output_deadline_exceeded') as caught:
        RoleRunner(ledger, provider=remote).call('connections', 'JSON', {}, [], revision=3)
    assert len(calls) == 2 and ledger.network_recoveries == 1
    assert caught.value.audit['failure_facts']['send_sequence'] == 2
    assert len(ledger.metrics) == 2


def test_success_or_foreign_shared_metric_cannot_be_reused_as_this_attempt_failure():
    ledger = budget(); calls = []
    def remote(prompt, images, attempt):
        attempt.take(); calls.append(True)
        if len(calls) == 1:
            ledger.metrics.append({**failure(), 'agent_role': 'body_text', 'state_revision': 99,
                                   'task_id': 'other_task', 'source_sha256': 'b'*64})
            raise VisionError('transport_failed')  # No metric in this attempt's own sink.
        attempt.metrics.append({'status': 200}); return answer()
    assert RoleRunner(ledger, provider=remote).call('connections', 'JSON', {}, [], revision=3) == answer()
    assert len(calls) == 2 and ledger.network_recoveries == 1


def test_previous_same_role_invocation_failure_is_not_current_attempt_evidence():
    ledger = budget(); calls = []
    def remote(prompt, images, attempt):
        attempt.take(); calls.append(True)
        if len(calls) == 1:
            attempt.metrics.append(failure()); raise VisionError('transport_failed')
        if len(calls) == 2:
            raise VisionError('transport_failed')
        attempt.metrics.append({'status': 200}); return answer()
    runner = RoleRunner(ledger, provider=remote)
    with pytest.raises(VisionError, match='output_deadline_exceeded'):
        runner.call('connections', 'JSON', {}, [], revision=3)
    assert runner.call('connections', 'JSON', {}, [], revision=3) == answer()
    assert len(calls) == 3 and ledger.network_recoveries == 1


def test_concurrent_role_metric_after_local_deadline_does_not_hide_this_failure():
    ledger = budget(); own_recorded, foreign_recorded = Event(), Event()
    def connections(prompt, images, attempt):
        attempt.take(); attempt.metrics.append(failure()); own_recorded.set()
        assert foreign_recorded.wait(2)
        raise VisionError('transport_failed')
    def body(prompt, images, attempt):
        attempt.take(); assert own_recorded.wait(2)
        attempt.metrics.append({'status': 200}); foreign_recorded.set()
        return answer('body_text', 9)
    runner = RoleRunner(ledger, provider={'connections': connections, 'body_text': body})
    with ThreadPoolExecutor(max_workers=2) as pool:
        edge_result = pool.submit(runner.call, 'connections', 'JSON', {}, [], revision=3)
        body_result = pool.submit(runner.call, 'body_text', 'JSON', {}, [], revision=9)
        assert body_result.result(timeout=3) == answer('body_text', 9)
        with pytest.raises(VisionError, match='output_deadline_exceeded') as caught:
            edge_result.result(timeout=3)
    assert ledger.metrics[-1]['agent_role'] == 'body_text'
    assert caught.value.audit['failure_facts']['agent_role'] == 'connections'
    assert caught.value.audit['failure_facts']['state_revision'] == 3
    assert ledger.network_recoveries == 0 and len(ledger.metrics) == 2


def test_metric_snapshot_is_detached_and_failure_audit_is_fixed_type_and_secret_free():
    ledger = budget(); secret = 'not-a-real-secret'
    def remote(prompt, images, attempt):
        attempt.take()
        metric = failure(raw_content=secret, error_message=secret, headers={'Authorization': secret},
                         url=secret, stream_lines_received='123', sse_events_received=True,
                         seconds=float('nan'))
        attempt.metrics.append(metric)
        metric.update(timeout_kind='connect', transport_failure_kind='connect_timeout')
        ledger.metrics[-1]['timeout_kind'] = 'connect'
        raise VisionError('transport_failed')
    with pytest.raises(VisionError, match='output_deadline_exceeded') as caught:
        RoleRunner(ledger, provider=remote).call('connections', 'JSON', {}, [], revision=3)
    audit = caught.value.audit; encoded = json.dumps(audit, allow_nan=False)
    assert secret not in encoded
    assert not {'raw_content', 'error_message', 'headers', 'url', 'seconds',
                'stream_lines_received', 'sse_events_received'} & set(audit['failure_facts'])
    assert audit['failure_facts']['timeout_kind'] == 'wall_deadline'


def test_real_provider_partial_stream_is_never_accepted_even_if_partial_content_is_valid_json(monkeypatch):
    import ai
    monkeypatch.setattr(ai, 'API_KEY', 'offline-test-key')
    monkeypatch.setattr(ai, 'VISION_ENABLED', True)
    calls = []
    def transport(payload, headers, timeout, wall_deadline):
        calls.append(True)
        error = TimeoutError('offline_wall_deadline')
        error.vision_failure_context = {'failure_phase': 'sse_stream', 'http_status': 200,
            'request_started': True, 'response_headers_received': True,
            'partial_stream': True, 'wall_deadline_exceeded': True, 'stream_done_received': False}
        error.vision_partial_result = {'partial_stream': True, 'http_status': 200,
            'content': json.dumps(answer()), 'model': 'qwen3-vl-plus', 'finish_reason': None}
        raise error
    provider = VisionProvider('qwen', retries=0, transport=transport)
    ledger = budget(); before_deadline = ledger.deadline
    image = 'data:image/png;base64,' + base64.b64encode(b'offline image bytes').decode()
    with pytest.raises(VisionError, match='output_deadline_exceeded') as caught:
        RoleRunner(ledger, provider=provider).call('connections', 'JSON', {}, [image], revision=3)
    assert len(calls) == 1 and ledger.network_recoveries == 0
    assert ledger.metrics[0]['partial_stream'] and ledger.metrics[0]['http_status'] == 200
    assert ledger.metrics[0]['content_chars'] > 0
    assert caught.value.audit['failure_facts']['stream_done_received'] is False
    assert ledger.deadline == before_deadline


def test_existing_call_and_deadline_limits_remain_enforced():
    ledger = budget(); ledger.remaining = 1; calls = []
    def remote(prompt, images, attempt):
        attempt.take(); calls.append(True)
        attempt.metrics.append(failure(failure_phase='response_headers', timeout_kind='connect',
                                       transport_failure_kind='connect_timeout'))
        raise VisionError('transport_failed')
    with pytest.raises(VisionError, match='^transport_failed$'):
        RoleRunner(ledger, provider=remote).call('connections', 'JSON', {}, [], revision=3)
    assert len(calls) == 1 and ledger.remaining == 0 and ledger.network_recoveries == 0


def test_source_call_reserves_review_time_without_changing_shared_upload_deadline():
    ledger = AgentBudget(seconds=20, calls=4, call_seconds=75)
    original_deadline = ledger.deadline
    seen = []
    def remote(prompt, images, attempt):
        timeout = attempt.take()
        seen.append((attempt.deadline, timeout))
        assert attempt.deadline == original_deadline - 8
        assert 10 < timeout <= 12
        return {'sources': []}
    result = RoleRunner(ledger, provider=remote).call('semantic_edges', 'JSON', {}, [],
        response_identity=False, reserve_seconds=8)
    assert result == {'sources': []} and len(seen) == 1
    assert ledger.deadline == original_deadline and ledger.remaining == 3
    # The subsequent final reader gets the original, unshortened deadline.
    def reviewer(prompt, images, attempt):
        assert attempt.deadline == original_deadline
        assert attempt.take() > 18
        return {'body_text': '', 'graphs': []}
    RoleRunner(ledger, provider=reviewer).call('semantic_review', 'JSON', {}, [], response_identity=False)
    assert ledger.remaining == 2


def test_exhausted_source_window_does_not_spend_final_review_call():
    ledger = AgentBudget(seconds=10, calls=3)
    sent = []
    def remote(*args):
        sent.append(True)
        return {}
    with pytest.raises(TimeoutError, match='agent_task_deadline'):
        RoleRunner(ledger, provider=remote).call('semantic_edges', 'JSON', {}, [], reserve_seconds=8)
    assert not sent and ledger.remaining == 3


@pytest.mark.parametrize('reserve', [True, -1, float('nan'), float('inf'), '8'])
def test_invalid_time_reserve_is_rejected_before_provider_dispatch(reserve):
    ledger = budget()
    with pytest.raises(ValueError, match='invalid_role_time_reserve'):
        RoleRunner(ledger, provider=lambda *args: pytest.fail('must not dispatch')).call(
            'semantic_edges', 'JSON', {}, [], reserve_seconds=reserve)
    assert ledger.remaining == 8 and not ledger.events
