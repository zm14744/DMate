"""Bound active original-image requests without serializing visual inference."""
from contextlib import contextmanager
import threading


class UploadAdmissionError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class UploadTasks:
    def __init__(self, capacity=4):
        self.capacity = capacity
        self._active = set()
        self._lock = threading.Lock()

    @contextmanager
    def admit(self, owner, request_id):
        key = (owner, request_id)
        with self._lock:
            if key in self._active:
                raise UploadAdmissionError('duplicate_active_task')
            if len(self._active) >= self.capacity:
                raise UploadAdmissionError('recognition_capacity')
            self._active.add(key)
        try:
            yield
        finally:
            with self._lock:
                self._active.discard(key)

    def active_count(self):
        with self._lock:
            return len(self._active)


UPLOAD_TASKS = UploadTasks()
