"""Real queue/lock behavior with isolated synthetic local tool boundaries."""
import fcntl
import hashlib
import multiprocessing
from pathlib import Path
import threading
import time

import pytest

from graph_agent_runtime import AgentBudget
import graph_local_scheduler as scheduler


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler.tempfile, 'gettempdir', lambda: str(tmp_path))
    # A separate queue keeps test ordering independent of other unit fixtures.
    instance = scheduler._LocalExecutor()
    monkeypatch.setattr(scheduler, '_executor', lambda: instance)
    return tmp_path


def budget(raw, seconds=5):
    return AgentBudget(seconds=seconds, source_sha256=hashlib.sha256(raw).hexdigest())


def text_result(label):
    return {'text_hints': [{'text': label}], 'diagnostics': {'model_executed_this_call': True},
            'resource_metrics': [{'stage': 'text', 'status': 'ok', 'worker_started': True}],
            'tool_audit': [{'tool': 'image.semantic_text', 'status': 'success'}]}


def test_four_images_serialize_actual_local_stages_without_serializing_callers(monkeypatch, isolated):
    import graph_semantic_text
    release, started = threading.Event(), threading.Event()
    lock = threading.Lock()
    active, peak = 0, 0
    execution = []

    def recognize(raw, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        with scheduler.local_model_lock() as nested:
            assert nested, 'The actual adapter must reuse this thread’s acquired resource lease'
        started.set()
        assert release.wait(2)
        execution.append(raw)
        with lock:
            active -= 1
        return text_result(raw.decode())

    monkeypatch.setattr(graph_semantic_text, 'prepare_semantic_text', recognize)
    raw = [f'image-{i}'.encode() for i in range(4)]
    handles = [scheduler.submit_local_bundle(x, budget=budget(x)) for x in raw]
    assert started.wait(1)
    assert all(not handle.done() for handle in handles)
    assert all(handle.snapshot()['status'] == 'running' for handle in handles)
    # All callers have returned immediately; they can launch four independent
    # vision requests while the shared local resource is still occupied.
    release.set()
    results = [handle.result(timeout=2) for handle in handles]
    assert peak == 1 and execution == raw
    assert [value['text']['text_hints'][0]['text'] for value in results] == [x.decode() for x in raw]
    assert all(value['status'] == 'completed' for value in results)
    assert all(value['scheduler']['stages'][0]['worker_started'] for value in results)


def test_queued_small_ocr_precedes_optional_layout_of_an_earlier_image(monkeypatch, isolated):
    import graph_semantic_text
    import graph_semantic_layout
    started, release = threading.Event(), threading.Event()
    order = []

    def text(raw, **kwargs):
        order.append(('text', raw))
        if raw == b'first':
            started.set()
            assert release.wait(2)
        return text_result(raw.decode())

    def layout(raw, **kwargs):
        order.append(('layout', raw))
        return {'layout': {'status': 'ok'}, 'resource_metrics': [{'worker_started': True}]}

    monkeypatch.setattr(graph_semantic_text, 'prepare_semantic_text', text)
    monkeypatch.setattr(graph_semantic_layout, 'prepare_semantic_layout', layout)
    first = scheduler.submit_local_bundle(b'first', budget=budget(b'first'), policy={'layout': True})
    assert started.wait(1)
    others = [scheduler.submit_local_bundle(x, budget=budget(x)) for x in (b'second', b'third', b'fourth')]
    release.set()
    for handle in [first, *others]:
        handle.result(timeout=2)
    assert order == [('text', b'first'), ('text', b'second'), ('text', b'third'),
                     ('text', b'fourth'), ('layout', b'first')]


def test_cancel_optional_queue_work_does_not_cancel_required_text_or_start_layout(monkeypatch, isolated):
    import graph_semantic_text
    import graph_semantic_layout
    started, release = threading.Event(), threading.Event()

    def text(raw, **kwargs):
        started.set()
        assert release.wait(2)
        return text_result('actual')

    monkeypatch.setattr(graph_semantic_text, 'prepare_semantic_text', text)
    monkeypatch.setattr(graph_semantic_layout, 'prepare_semantic_layout', lambda *a, **k: pytest.fail('Cancelled layout started'))
    handle = scheduler.submit_local_bundle(b'image', budget=budget(b'image'), policy={'layout': True})
    assert started.wait(1)
    assert handle.cancel_pending() == 1
    release.set()
    result = handle.result(timeout=2)
    stages = {row['stage']: row for row in result['scheduler']['stages']}
    assert result['status'] == 'completed'
    assert stages['text']['status'] == 'ok' and stages['text']['stage_started']
    assert stages['layout']['status'] == 'not_needed' and not stages['layout']['worker_started']


def test_request_close_cancels_a_stage_waiting_for_another_process_lock(monkeypatch, isolated):
    import graph_semantic_text
    monkeypatch.setattr(graph_semantic_text, 'prepare_semantic_text', lambda *a, **k: pytest.fail('Request already closed'))
    with (isolated/'dmate-local-model.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle = scheduler.submit_local_bundle(b'blocked', budget=budget(b'blocked'))
        deadline = time.monotonic()+1
        while handle.audit()['stages'][0]['status'] == 'queued' and time.monotonic() < deadline:
            time.sleep(.005)
        assert handle.audit()['stages'][0]['status'] == 'waiting_for_resource'
        result = handle.close()
        assert result['status'] == 'degraded' and not result['scheduler']['stages'][0]['stage_started']
        assert result['scheduler']['stages'][0]['status'] == 'cancelled'
        fcntl.flock(lock, fcntl.LOCK_UN)


def test_queued_deadline_is_reported_and_never_starts_a_worker(monkeypatch, isolated):
    import graph_semantic_text
    monkeypatch.setattr(graph_semantic_text, 'prepare_semantic_text', lambda *a, **k: pytest.fail('Expired task started'))
    result = scheduler.submit_local_bundle(b'expired', budget=budget(b'expired', seconds=1)).result(timeout=1)
    assert result['status'] == 'degraded'
    assert result['scheduler']['stages'][0]['status'] == 'deadline_exceeded'
    assert not result['scheduler']['stages'][0]['worker_started']


def test_one_image_tool_failure_does_not_fail_the_next_image(monkeypatch, isolated):
    import graph_semantic_text

    def text(raw, **kwargs):
        if raw == b'bad':
            raise RuntimeError('Private input must not escape in diagnostics')
        return text_result('good')

    monkeypatch.setattr(graph_semantic_text, 'prepare_semantic_text', text)
    bad = scheduler.submit_local_bundle(b'bad', budget=budget(b'bad'))
    good = scheduler.submit_local_bundle(b'good', budget=budget(b'good'))
    assert bad.result(timeout=2)['status'] == 'degraded'
    assert 'Private' not in str(bad.audit())
    assert good.result(timeout=2)['text']['text_hints'] == [{'text': 'good'}]


def test_policy_can_disable_text_and_select_paths_without_sknw(monkeypatch, isolated):
    import graph_semantic_text
    import graph_semantic_geometry
    calls = []
    monkeypatch.setattr(graph_semantic_text, 'prepare_semantic_text', lambda *a, **k: pytest.fail('Text disabled'))

    def geometry(raw, **kwargs):
        calls.append(kwargs)
        return {'graphs': [], 'tool_audit': [{'tool': 'image.semantic_opencv', 'executed': True, 'status': 'success'}]}

    monkeypatch.setattr(graph_semantic_geometry, 'prepare_semantic_geometry', geometry)
    draft = {'graphs': []}
    handle = scheduler.submit_local_bundle(b'paths', budget=budget(b'paths'), draft=draft,
                                           policy={'text': False, 'paths': True})
    result = handle.result(timeout=2)
    assert result['status'] == 'completed' and result['text'] == {}
    assert len(calls) == 1 and calls[0]['run_sknw'] is False and calls[0]['draft'] == draft


def _try_process_lock(path, conn):
    with Path(path).open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            conn.send('blocked')
        else:
            conn.send('acquired')
            fcntl.flock(lock, fcntl.LOCK_UN)
    conn.close()


def test_resource_lease_excludes_another_process_and_is_released(isolated):
    context = multiprocessing.get_context('fork')
    with scheduler.local_model_lock() as acquired:
        assert acquired
        parent, child = context.Pipe()
        proc = context.Process(target=_try_process_lock, args=(str(isolated/'dmate-local-model.lock'), child))
        proc.start()
        assert parent.poll(2) and parent.recv() == 'blocked'
        proc.join(2)
        assert proc.exitcode == 0
    with scheduler.local_model_lock() as acquired:
        assert acquired


@pytest.mark.parametrize('policy', [{'bogus': True}, {'text': 1}, {'sknw': True}])
def test_invalid_policy_is_not_silently_accepted(policy, isolated):
    with pytest.raises(ValueError):
        scheduler.submit_local_bundle(b'x', budget=budget(b'x'), policy=policy)


def test_source_binding_rejects_another_images_candidates(isolated):
    with pytest.raises(ValueError, match='candidate_source'):
        scheduler.submit_local_bundle(b'x', budget=budget(b'x'), initial_geometry={'source_sha256': '0'*64})


def test_geometry_diagnostic_list_keeps_its_top_level_source_binding(isolated):
    raw = b'x'
    source = hashlib.sha256(raw).hexdigest()
    handle = scheduler.submit_local_bundle(raw, budget=budget(raw), policy={'text': False},
        initial_geometry={'source_sha256': source, 'diagnostics': [{'work_size': [16, 16]}]})
    assert handle.result()['status'] == 'not_requested'


def test_real_registered_text_adapter_reuses_scheduler_lease(monkeypatch, isolated):
    import graph_semantic_text
    from test_graph_semantic_text import png, picture, evidence, worker_metric
    seen = []

    def run_worker(stage, *args, **kwargs):
        seen.append(stage)
        # Another descriptor cannot acquire the process-wide resource while
        # the actual registered tool is invoking its bounded worker.
        with (isolated/'dmate-local-model.lock').open('a') as other:
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return evidence(), worker_metric()

    monkeypatch.setattr(graph_semantic_text, '_cache_readiness', lambda: {'status': 'ready'})
    monkeypatch.setattr('ocr_runtime.run_worker', run_worker)
    raw = png(picture())
    result = scheduler.submit_local_bundle(raw, budget=budget(raw)).result(timeout=3)
    assert seen == ['text'] and result['status'] == 'completed'
    assert result['tool_audit'][0]['tool'] == 'image.semantic_text'
    assert result['text']['diagnostics']['model_executed_this_call'] is True
    assert result['scheduler']['stages'][0]['worker_started'] is True


def test_partial_path_tool_failure_is_retained_even_when_another_tool_executed(monkeypatch, isolated):
    import graph_semantic_geometry
    monkeypatch.setattr(graph_semantic_geometry, 'prepare_semantic_geometry', lambda *a, **k: {
        'graphs': [{'id': 'G', 'candidates': [{'from': 'a', 'to': 'b'}]}],
        'tool_audit': [{'tool': 'image.semantic_opencv', 'status': 'success', 'executed': True},
                       {'tool': 'image.semantic_sknw', 'status': 'failed', 'executed': False}]})
    result = scheduler.submit_local_bundle(b'paths', budget=budget(b'paths'), draft={'graphs': []},
        policy={'text': False, 'paths': True, 'sknw': True}).result(timeout=2)
    assert result['status'] == 'degraded'
    assert result['geometry']['graphs'][0]['candidates']
    assert result['scheduler']['stages'][0]['status'] == 'partial'
