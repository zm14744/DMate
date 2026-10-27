"""Shared scheduling for optional local image tools, independent of vision calls.

One priority queue per server process and the existing inter-process file lock
bound Paddle and tracing memory. Small OCR gets priority over optional layout
and path work. Queue time belongs to the upload, not a tool's inference window.
No model or image work is started by importing this module.
"""
from __future__ import annotations

import copy
import fcntl
import hashlib
import itertools
import os
from pathlib import Path
import queue
import tempfile
import threading
import time
from concurrent.futures import CancelledError, Future
from contextlib import contextmanager


VERSION = '2026-10-27-shared-local-tools-v1'
_LEASE = threading.local()
_EXECUTOR = None
_EXECUTOR_LOCK = threading.Lock()
_PRIORITY = {'text': 0, 'layout': 10, 'geometry': 20}


@contextmanager
def local_model_lock(*, wait=False, budget=None, cancelled=None):
    """Reuse this thread's lease, or take the legacy shared local-tool lock.

    Legacy direct callers remain nonblocking. The scheduler waits outside each
    tool's bounded inference window and checks cancellation while queued.
    """
    path = Path(tempfile.gettempdir()) / 'dmate-local-model.lock'
    owner = (os.getpid(), threading.get_ident(), str(path))
    if getattr(_LEASE, 'owner', None) == owner:
        yield True
        return
    with path.open('a') as handle:
        acquired = False
        try:
            while True:
                if cancelled is not None and cancelled():
                    raise CancelledError()
                if budget is not None:
                    budget.check(minimum=2.)
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except BlockingIOError:
                    if not wait:
                        yield False
                        return
                    time.sleep(.025)
            _LEASE.owner = owner
            yield True
        finally:
            if acquired:
                _LEASE.owner = None
                fcntl.flock(handle, fcntl.LOCK_UN)


class _LocalExecutor:
    """One bounded worker; queued OCR precedes queued optional heavy tools."""

    def __init__(self, capacity=32):
        self.pid = os.getpid()
        self._queue = queue.PriorityQueue(maxsize=capacity)
        self._sequence = itertools.count()
        self._thread = threading.Thread(target=self._run, name='dmate-local-tools', daemon=True)
        self._thread.start()

    def submit(self, stage, function):
        future = Future()
        self._queue.put_nowait((_PRIORITY[stage], next(self._sequence), future, function))
        return future

    def _run(self):
        while True:
            _, _, future, function = self._queue.get()
            try:
                if future.set_running_or_notify_cancel():
                    try:
                        future.set_result(function())
                    except BaseException as exc:
                        future.set_exception(exc)
            finally:
                self._queue.task_done()


def _executor():
    global _EXECUTOR
    with _EXECUTOR_LOCK:
        # A forked Gunicorn process cannot reuse its parent's vanished thread.
        if _EXECUTOR is None or _EXECUTOR.pid != os.getpid():
            _EXECUTOR = _LocalExecutor()
        return _EXECUTOR


def _policy(value):
    result = {'text': True, 'layout': False, 'paths': False, 'sknw': False}
    if value is not None:
        if (not isinstance(value, dict) or set(value) - result.keys()
                or any(type(flag) is not bool for flag in value.values())):
            raise ValueError('invalid_local_tool_policy')
        result.update(value)
    if result['sknw'] and not result['paths']:
        raise ValueError('sknw_requires_path_request')
    return result


def _stage_status(stage, value):
    if not isinstance(value, dict):
        return 'unavailable'
    if stage == 'text':
        diagnostic = value.get('diagnostics', {})
        return ('ok' if diagnostic.get('model_executed_this_call')
                    or diagnostic.get('previous_result_reused') else 'unavailable')
    if stage == 'layout':
        return 'ok' if value.get('layout', {}).get('status') == 'ok' else 'unavailable'
    audits = [row for row in value.get('tool_audit', [])
              if row.get('tool') in ('image.semantic_opencv', 'image.semantic_sknw')]
    executed = any(row.get('executed') is True for row in audits)
    failed = any(row.get('status') in ('failed', 'partial') for row in audits)
    return 'partial' if executed and failed else 'ok' if executed else 'unavailable'


class LocalBundle:
    """Source-bound futures with explicit cancellation and actual tool results."""

    def __init__(self, source_sha256, policy):
        self.source_sha256 = source_sha256
        self.policy = policy
        self.started = time.monotonic()
        self._lock = threading.RLock()
        self._stages = {}

    def _submit(self, stage, operation, budget, *, optional):
        record = {'stage': stage, 'status': 'queued', 'optional': optional,
                  'stage_started': False, 'worker_started': False, 'queued_at': time.monotonic(),
                  'stop': threading.Event(), 'result': None}
        with self._lock:
            self._stages[stage] = record

        def execute():
            try:
                with self._lock:
                    if record['stop'].is_set():
                        raise CancelledError()
                    record['status'] = 'waiting_for_resource'
                with local_model_lock(wait=True, budget=budget, cancelled=record['stop'].is_set):
                    with self._lock:
                        if record['stop'].is_set():
                            raise CancelledError()
                        record.update(status='running', stage_started=True,
                                      acquired_at=time.monotonic())
                    value = operation()
                    with self._lock:
                        record['result'] = value
                        record['status'] = _stage_status(stage, value)
                        record['worker_started'] = any(
                            row.get('worker_started') is True for row in value.get('resource_metrics', []))
                        if stage == 'geometry':
                            record['worker_started'] = any(
                                row.get('executed') is True and row.get('tool') in
                                ('image.semantic_opencv', 'image.semantic_sknw')
                                for row in value.get('tool_audit', []))
                    return value
            except CancelledError:
                with self._lock:
                    record['status'] = record.get('cancel_status', 'cancelled')
                return None
            except Exception as exc:
                # Record operational kinds, never exception text or image data.
                with self._lock:
                    record.update(status=('deadline_exceeded' if isinstance(exc, TimeoutError) else
                                          'cancelled' if type(exc).__name__ == 'AgentCancelled' else 'failed'),
                                  error_kind=type(exc).__name__)
                return None
            finally:
                with self._lock:
                    record['finished_at'] = time.monotonic()

        try:
            future = _executor().submit(stage, execute)
        except queue.Full:
            future = Future()
            future.set_result(None)
            record.update(status='queue_full', finished_at=time.monotonic())
        with self._lock:
            record['future'] = future

    def done(self):
        with self._lock:
            return all(row['future'].done() for row in self._stages.values())

    def cancel_pending(self, optional_only=True):
        """Cancel queued work; running tool subprocesses must finish normally."""
        changed = 0
        with self._lock:
            for row in self._stages.values():
                if row['stage_started'] or row['future'].done() or optional_only and not row['optional']:
                    continue
                row['cancel_status'] = 'not_needed' if optional_only else 'cancelled'
                row['stop'].set()
                if row['future'].cancel():
                    row.update(status=row['cancel_status'], finished_at=time.monotonic())
                changed += 1
        return changed

    def audit(self):
        now = time.monotonic()
        with self._lock:
            stages = []
            for row in self._stages.values():
                acquired = row.get('acquired_at')
                finished = row.get('finished_at', now)
                stages.append({key: copy.deepcopy(value) for key, value in {
                    'stage': row['stage'], 'status': row['status'], 'optional': row['optional'],
                    'stage_started': row['stage_started'], 'worker_started': row['worker_started'],
                    'error_kind': row.get('error_kind'),
                    'queue_seconds': round((acquired or finished)-row['queued_at'], 6),
                    'execution_seconds': round(finished-acquired, 6) if acquired else 0.,
                }.items() if value is not None})
        return {'version': VERSION, 'source_sha256': self.source_sha256,
                'shared_local_parallelism': 1, 'queue_policy': 'small_ocr_before_optional_heavy_tools',
                'elapsed_seconds': round(now-self.started, 6), 'stages': stages}

    def snapshot(self):
        with self._lock:
            results = {name: row['result'] for name, row in self._stages.items()
                       if row['result'] is not None}
            statuses = [row['status'] for row in self._stages.values()]
        # DocumentEvidence/PIL views are caller-owned runtime objects. Keep
        # those references for reuse; candidate dictionaries are not mutated.
        data = {'text': results.get('text', {}), 'layout': results.get('layout', {}),
                'geometry': results.get('geometry', {}), 'resource_metrics': [], 'tool_audit': []}
        for value in results.values():
            data['resource_metrics'].extend(copy.deepcopy(value.get('resource_metrics', [])))
            data['tool_audit'].extend(copy.deepcopy(value.get('tool_audit', [])))
        data['status'] = ('not_requested' if not statuses else
            'running' if any(x in ('queued', 'waiting_for_resource', 'running') for x in statuses) else
            'completed' if all(x in ('ok', 'not_needed') for x in statuses) else 'degraded')
        data['scheduler'] = self.audit()
        data['source_sha256'] = self.source_sha256
        return data

    def result(self, timeout=None):
        until = None if timeout is None else time.monotonic()+max(0., timeout)
        with self._lock:
            futures = [row['future'] for row in self._stages.values()]
        for future in futures:
            try:
                future.result(timeout=None if until is None else max(0., until-time.monotonic()))
            except CancelledError:
                pass
        return self.snapshot()

    def close(self):
        """Request cleanup: no queued stage may start after the request exits."""
        self.cancel_pending(optional_only=False)
        return self.result()


def submit_local_bundle(raw, *, budget, quick_layout=None, initial_geometry=None,
                        draft=None, policy=None):
    """Schedule text and explicitly selected layout/path tools for one upload.

    ``snapshot`` is nonblocking, ``result`` waits for real completion, and
    ``close`` cancels queued work then joins already-running bounded tools.
    Call ``close`` in the request's finally block, including failure paths.
    """
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise TypeError('expected_image_bytes')
    raw = bytes(raw)
    source = hashlib.sha256(raw).hexdigest()
    if getattr(budget, 'source_sha256', None) not in (None, source):
        raise ValueError('local_bundle_source_mismatch')
    selected = _policy(policy)
    if selected['paths'] and not isinstance(draft, dict):
        raise ValueError('path_bundle_requires_draft')
    for value in (quick_layout, initial_geometry):
        if value is None:
            continue
        if not isinstance(value, dict):
            raise ValueError('local_bundle_candidate_source_mismatch')
        diagnostic = value.get('diagnostics')
        bound_source = value.get('source_sha256')
        if bound_source is None and isinstance(diagnostic, dict):
            bound_source = diagnostic.get('source_sha256')
        if bound_source not in (None, source):
            raise ValueError('local_bundle_candidate_source_mismatch')
    handle = LocalBundle(source, selected)
    document = (initial_geometry or {}).get('document') or (quick_layout or {}).get('document')
    if selected['text']:
        def text_operation():
            from graph_semantic_text import prepare_semantic_text
            return prepare_semantic_text(raw, budget=budget, layout=quick_layout, document=document)
        handle._submit('text', text_operation, budget, optional=False)
    if selected['layout']:
        def layout_operation():
            from graph_semantic_layout import prepare_semantic_layout
            return prepare_semantic_layout(raw, budget=budget, run_layout=True, document=document)
        handle._submit('layout', layout_operation, budget, optional=True)
    if selected['paths']:
        stable_draft = copy.deepcopy(draft)
        def geometry_operation():
            from graph_semantic_geometry import prepare_semantic_geometry
            return prepare_semantic_geometry(raw, budget=budget, draft=stable_draft,
                document=document, layout=quick_layout, run_sknw=selected['sknw'])
        handle._submit('geometry', geometry_operation, budget, optional=True)
    return handle
