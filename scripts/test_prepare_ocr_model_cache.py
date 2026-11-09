#!/usr/bin/env python3
"""Offline regression checks for bounded, resumable official model downloads."""
from contextlib import redirect_stderr
import hashlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    'prepare_ocr_model_cache', Path(__file__).with_name('prepare_ocr_model_cache.py'))
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)


class RequestException(Exception):
    pass


class HTTPError(RequestException):
    response = None


class Response:
    def __init__(self, chunks, *, status=200, content_range=None, delay=0):
        self.status_code = status
        self.headers = {'Content-Range': content_range} if content_range else {}
        self.chunks = chunks
        self.delay = delay

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, size):
        for chunk in self.chunks:
            if self.delay:
                time.sleep(self.delay)
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk


class HTTP:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.ranges = []

    def get(self, url, **kwargs):
        self.ranges.append(kwargs['headers']['Range'])
        assert kwargs['params']['Revision'] == 'a' * 40
        assert kwargs['timeout'] == (8, 30)
        return next(self.responses)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.destination = Path(self.temporary.name) / 'inference.pdiparams'
        self.requests = patch.dict(sys.modules, {
            'requests': SimpleNamespace(RequestException=RequestException, HTTPError=HTTPError)})
        self.requests.start()
        self.addCleanup(self.requests.stop)
        self.logs = io.StringIO()
        self.stderr = redirect_stderr(self.logs)
        self.stderr.__enter__()
        self.addCleanup(self.stderr.__exit__, None, None, None)

    def download(self, http, expected=b'abcdef', timeout=1):
        record = {'size': len(expected), 'sha256': hashlib.sha256(expected).hexdigest(),
                  'revision': 'a' * 40}
        cache._download_modelscope_file(http, cache.MODEL_NAMES[0],
                                       'inference.pdiparams', record, self.destination, timeout)

    def test_interruption_resumes_the_exact_immutable_file(self):
        http = HTTP([Response([b'abc', cache._DownloadDeadline('interrupted')]),
                     Response([b'def'], status=206, content_range='bytes 3-5/6')])
        self.download(http)
        self.assertEqual(http.ranges, ['bytes=0-', 'bytes=3-'])
        self.assertEqual(self.destination.read_bytes(), b'abcdef')
        self.assertIn('3/6 partial bytes retained, awaiting full SHA256', self.logs.getvalue())

    def test_server_ignoring_range_replaces_partial_bytes(self):
        http = HTTP([Response([b'abc', RequestException('disconnected')]),
                     Response([b'abcdef'])])
        self.download(http)
        self.assertEqual(http.ranges, ['bytes=0-', 'bytes=3-'])
        self.assertEqual(self.destination.read_bytes(), b'abcdef')
        self.assertIn('server ignored Range', self.logs.getvalue())

    def test_malformed_range_is_never_appended(self):
        self.destination.write_bytes(b'abc')
        http = HTTP([Response([b'def'], status=206, content_range='bytes 2-5/6')
                     for _ in range(cache.DOWNLOAD_ATTEMPTS)])
        with self.assertRaises(cache.CachePreparationError):
            self.download(http)
        self.assertEqual(self.destination.read_bytes(), b'abc')

    def test_hash_mismatch_is_rejected_and_removed(self):
        http = HTTP([Response([b'abcdeg']) for _ in range(cache.DOWNLOAD_ATTEMPTS)])
        with self.assertRaises(cache.CachePreparationError):
            self.download(http)
        self.assertFalse(self.destination.exists())

    def test_oversized_response_is_rejected(self):
        http = HTTP([Response([b'abcdefg']) for _ in range(cache.DOWNLOAD_ATTEMPTS)])
        with self.assertRaises(cache.CachePreparationError):
            self.download(http)
        self.assertEqual(self.destination.read_bytes(), b'')

    def test_healthy_progress_outlives_original_attempt_deadline(self):
        http = HTTP([Response([b'ab', b'cd', b'ef'], delay=0.12)])
        with patch.object(cache, 'DOWNLOAD_PROGRESS_INTERVAL', 0):
            self.download(http, timeout=0.3)
        self.assertEqual(len(http.ranges), 1)
        self.assertEqual(self.destination.read_bytes(), b'abcdef')
        self.assertIn('100.0%', self.logs.getvalue())

    def test_progress_cannot_extend_shared_hard_budget(self):
        http = HTTP([Response([b'a'] * 20, delay=0.12)])
        with self.assertRaises(cache.CachePreparationError):
            self.download(http, expected=b'a' * 20, timeout=0.3)
        self.assertEqual(len(http.ranges), 1)
        self.assertLess(self.destination.stat().st_size, 20)
        self.assertIn('0 retries and 0s total download budget remaining', self.logs.getvalue())

    def test_paddlex_source_deadline_still_rearms_for_fallback(self):
        attempted = []
        with cache._download_deadline(0.05):
            for source in ('preferred', 'fallback'):
                try:
                    time.sleep(0.1)
                except cache._DownloadDeadline:
                    attempted.append(source)
        self.assertEqual(attempted, ['preferred', 'fallback'])


if __name__ == '__main__':
    unittest.main()
