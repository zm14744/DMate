"""Bounded, short-lived machine OCR results, separated by browser/account.

No images, user edits, confirmation tokens, task IDs or worker receipts are
stored. A hit still requires the route's current source and selection checks.
"""
from collections import OrderedDict
import hashlib
import importlib.util
import json
from pathlib import Path
import threading
import time

CACHE_VERSION = '2026-10-31-text-result-v1'
_PAYLOAD_FIELDS = ('regions', 'text', 'text_count', 'recognition_status',
                   'review_count', 'review_reasons', 'warning',
                   'selection_mode', 'text_regions')


def reader_cache_tag(reader):
    kind = type(reader)
    return (f"{getattr(reader, '__module__', kind.__module__)}:"
            f"{getattr(reader, '__qualname__', kind.__qualname__)}:{id(reader)}")


def result_cache_key(owner, source_sha256, selection, *, reader_tag):
    """Disable reuse when the selected runtime/cache cannot be verified ready."""
    from ocr_runtime import ModelCacheError
    try:
        from ocr_text_engine import text_model_options
        from ocr_text_preprocess import PREPROCESS_VERSION
        options = text_model_options()
        runtime = 'onnxruntime' if options['engine'] == 'onnxruntime' else 'paddle'
        if any(importlib.util.find_spec(name) is None for name in (runtime, 'paddleocr')):
            return None
        detector = Path(options['text_detection_model_dir'])
        cache_home = detector.parent.parent
        manifest_path = cache_home/'dmate-model-manifest.json'
        if not 0 < manifest_path.stat().st_size <= 64*1024:
            return None
        encoded_manifest = manifest_path.read_bytes()
        manifest = json.loads(encoded_manifest)
        if (not isinstance(manifest, dict) or manifest.get('schema_version') not in (1, 2)
                or not isinstance(manifest.get('models'), list)
                or (runtime == 'onnxruntime' and not isinstance(manifest.get('onnx_models'), list))):
            return None
        filenames = (('inference.onnx', 'inference.yml') if runtime == 'onnxruntime'
                     else ('inference.json', 'inference.pdiparams', 'inference.yml'))
        # Stat every active file so a removed/replaced/truncated model cannot
        # be hidden behind an existing result. Full hashes are checked at build.
        model_stats = []
        for field in ('text_detection_model_dir', 'text_recognition_model_dir'):
            directory = Path(options[field])
            for filename in filenames:
                info = (directory/filename).stat()
                model_stats.append([directory.name, filename, info.st_size,
                                    info.st_mtime_ns, info.st_ctime_ns, info.st_ino])
        value = [CACHE_VERSION, PREPROCESS_VERSION, owner, source_sha256,
                 selection, reader_tag, options['engine'],
                 hashlib.sha256(encoded_manifest).hexdigest(), model_stats]
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                        allow_nan=False).encode()).hexdigest()
    except (OSError, ValueError, TypeError, ImportError, RuntimeError, ModelCacheError):
        return None


def _complete_nonempty(value):
    if not isinstance(value, dict):
        return False
    if (value.get('recognition_status') != 'complete'
            or not str(value.get('text') or '').strip()
            or value.get('error') or value.get('warning')
            or value.get('review_count') or value.get('review_reasons')):
        return False
    review = value.get('review')
    if isinstance(review, dict) and (review.get('required') or review.get('reasons')):
        return False
    return True


class TextResultCache:
    def __init__(self, *, ttl_seconds=600, capacity=64, max_bytes=8*1024**2,
                 clock=time.monotonic):
        self.ttl_seconds = ttl_seconds
        self.capacity = capacity
        self.max_bytes = max_bytes
        self._clock = clock
        self._lock = threading.Lock()
        self._entries = OrderedDict()
        self._bytes = 0

    def _remove(self, key):
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._bytes -= len(entry[1])

    def _expire(self, now):
        for key, (expiry, _) in list(self._entries.items()):
            if expiry <= now:
                self._remove(key)

    def get(self, key):
        if key is None:
            return None
        with self._lock:
            self._expire(self._clock())
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key)
            encoded = entry[1]
        return json.loads(encoded)

    def discard(self, key):
        if key is not None:
            with self._lock:
                self._remove(key)

    def put(self, key, result):
        if key is None or not _complete_nonempty(result):
            return False
        if 'regions' in result and (not isinstance(result['regions'], list)
                                   or not result['regions']
                                   or not all(_complete_nonempty(row) for row in result['regions'])):
            return False
        metrics = result.get('resource_metrics') or []
        if not isinstance(metrics, list) or any(not isinstance(row, dict)
                or (row.get('stage') == 'text' and row.get('status') != 'ok') for row in metrics):
            return False
        payload = {field: result[field] for field in _PAYLOAD_FIELDS if field in result}
        if 'regions' in payload:
            row_fields = ('id', 'text', 'text_count', 'recognition_status',
                          'review_count', 'review_reasons', 'warning')
            payload['regions'] = [{field: row[field] for field in row_fields if field in row}
                                  for row in payload['regions']]
        try:
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False,
                                 separators=(',', ':')).encode()
        except (ValueError, TypeError):
            return False
        if len(encoded) > self.max_bytes or self.capacity <= 0:
            return False
        with self._lock:
            now = self._clock()
            self._expire(now)
            self._remove(key)
            while self._entries and (len(self._entries) >= self.capacity
                                     or self._bytes + len(encoded) > self.max_bytes):
                self._remove(next(iter(self._entries)))
            self._entries[key] = (now+self.ttl_seconds, encoded)
            self._bytes += len(encoded)
        return True


TEXT_RESULT_CACHE = TextResultCache()
