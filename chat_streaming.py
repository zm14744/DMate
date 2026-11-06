"""Opt-in SSE delivery for the existing, synchronously validated chat handler.

Only the final validated payload is a completed answer. Deltas are temporary
presentation data; disconnecting closes this request's cooperative work scope.
"""

import json
import queue
import threading
import time

from flask import copy_current_request_context, current_app, jsonify, request
from server_i18n import request_language, localize_error_payload


class ChatStreamCancelled(BaseException):
    """Leave model/fallback work without broad application error handlers."""


_QUEUE_SIZE = 64
_HEARTBEAT_SECONDS = 1.0
_DELTA_CHARS = 4096
# Socket read timeouts do not expire while an upstream keeps sending heartbeat
# comments. Give the complete streamed request a wall-clock budget as well.
_MAX_STREAM_SECONDS = 300.0
# A disconnected buffered request may still be inside an upstream read until
# its ordinary timeout. Bound those workers across HTTP connection lifetimes.
_STREAM_SLOTS = threading.BoundedSemaphore(4)


def _event(name, payload):
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return f"event: {name}\ndata: {data}\n\n"


def stream_chat_response(handler):
    """Run ``handler(on_delta, cancelled)`` in its copied Flask request context.

    The handler keeps ownership of input validation, access checks and final
    answer correction. It returns its ordinary Flask response/response tuple.
    Non-stream callers should invoke that handler directly instead.
    """
    app = current_app._get_current_object()
    language = request_language(request)
    slots = _STREAM_SLOTS
    if not slots.acquire(blocking=False):
        response = jsonify({
            "error": "当前回答请求较多，请稍后再试。",
            "code": "chat_stream_busy",
        })
        response.status_code = 429
        response.headers["Retry-After"] = "2"
        response.headers["Cache-Control"] = "no-store"
        return response
    events = queue.Queue(maxsize=_QUEUE_SIZE)
    cancelled = threading.Event()
    finished = threading.Event()
    lifecycle_lock = threading.Lock()
    worker_started = False
    slot_released = False

    def release_slot():
        nonlocal slot_released
        with lifecycle_lock:
            if not slot_released:
                slot_released = True
                slots.release()

    def close():
        nonlocal slot_released
        cancelled.set()
        with lifecycle_lock:
            if not worker_started and not slot_released:
                slot_released = True
                slots.release()

    def put(name, payload):
        # Encode before enqueueing so malformed values cannot terminate the
        # response generator after it has already claimed final completion.
        encoded = _event(name, localize_error_payload(payload, language) if name == "error" else payload)
        while not cancelled.is_set():
            try:
                events.put((name, encoded), timeout=0.1)
                return
            except queue.Full:
                continue
        raise ChatStreamCancelled()

    def on_delta(text):
        if not isinstance(text, str) or not text:
            return
        for offset in range(0, len(text), _DELTA_CHARS):
            put("delta", {"text": text[offset:offset + _DELTA_CHARS]})

    @copy_current_request_context
    def invoke():
        if cancelled.is_set():
            raise ChatStreamCancelled()
        response = app.make_response(handler(on_delta, cancelled.is_set))
        try:
            payload = response.get_json(silent=True)
            status = response.status_code
        finally:
            response.close()
        if cancelled.is_set():
            raise ChatStreamCancelled()
        if not isinstance(payload, dict):
            raise ValueError("chat_response_not_json_object")
        if 200 <= status < 300 and not payload.get("error") and payload.get("ok") is not False:
            if not isinstance(payload.get("reply"), str) or not payload["reply"].strip():
                raise ValueError("chat_response_missing_reply")
            put("final", payload)
        else:
            failure = dict(payload)
            failure["status"] = status if status >= 400 else 502
            failure.setdefault("error", "本次回答未能完成，请稍后重试。")
            put("error", failure)

    def worker():
        try:
            invoke()
        except ChatStreamCancelled:
            cancelled.set()
        except Exception as exc:
            # Never serialize exception messages, upstream bodies or secrets.
            app.logger.warning("Chat stream worker failed (%s)", type(exc).__name__)
            if not cancelled.is_set():
                try:
                    put("error", {
                        "error": "本次回答未能完成，请稍后重试。",
                        "code": "chat_stream_failed",
                        "status": 500,
                    })
                except ChatStreamCancelled:
                    pass
        finally:
            finished.set()
            release_slot()

    def generate():
        nonlocal worker_started
        deadline = time.monotonic() + _MAX_STREAM_SECONDS
        try:
            with lifecycle_lock:
                if cancelled.is_set():
                    return
                worker_started = True
            try:
                threading.Thread(target=worker, name="dmate-chat-stream", daemon=True).start()
            except Exception:
                release_slot()
                raise
            yield ": connected\n\n"
            while not cancelled.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    cancelled.set()
                    yield _event("error", localize_error_payload({
                        "error": "回答等待时间过长，已停止本次请求，请稍后重试。",
                        "code": "chat_stream_timeout",
                        "status": 504,
                    }, language))
                    break
                try:
                    name, encoded = events.get(timeout=min(_HEARTBEAT_SECONDS, remaining))
                except queue.Empty:
                    if finished.is_set():
                        break
                    # Frequent small writes both defeat proxy idle buffering
                    # and expose a disconnected client to the WSGI server.
                    yield ": keepalive\n\n"
                    continue
                yield encoded
                if name in ("final", "error"):
                    break
        finally:
            close()

    response = app.response_class(generate(), content_type="text/event-stream; charset=utf-8")
    response.headers["Cache-Control"] = "no-store, no-transform"
    response.headers["X-Accel-Buffering"] = "no"
    response.call_on_close(close)
    return response
