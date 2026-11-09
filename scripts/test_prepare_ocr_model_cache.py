#!/usr/bin/env python3
"""Offline regression checks for bounded, resumable official model downloads."""
from contextlib import redirect_stderr
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
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
        self.urls = []
        self.parameters = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, **kwargs):
        self.ranges.append(kwargs['headers']['Range'])
        self.urls.append(url)
        self.parameters.append(kwargs['params'])
        if kwargs['params'] is not None:
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

    def sources(self):
        return [{'label': 'ModelScope', 'url': f'{cache.MODELSCOPE_API}/{cache.MODEL_NAMES[0]}/repo',
                 'params': {'Revision': 'a' * 40, 'FilePath': 'inference.pdiparams'}}]

    def download(self, http, expected=b'abcdef', timeout=1, sources=None):
        record = {'size': len(expected), 'sha256': hashlib.sha256(expected).hexdigest(),
                  'revision': 'a' * 40}
        cache._download_official_file(http, cache.MODEL_NAMES[0], 'inference.pdiparams',
                                      record, self.destination, timeout,
                                      sources=self.sources() if sources is None else sources)

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

    def test_official_source_failure_resumes_the_same_bytes_on_next_source(self):
        sources = self.sources() + [
            {'label': 'HuggingFace', 'url': 'https://huggingface.co/PaddlePaddle/model/resolve/'
             + 'b' * 40 + '/inference.pdiparams', 'params': None}]
        http = HTTP([Response([b'abc', RequestException('source disconnected')]),
                     Response([b'def'], status=206, content_range='bytes 3-5/6')])
        self.download(http, sources=sources)
        self.assertEqual(http.urls, [source['url'] for source in sources])
        self.assertEqual(http.ranges, ['bytes=0-', 'bytes=3-'])
        self.assertEqual(http.parameters, [sources[0]['params'], None])
        self.assertEqual(self.destination.read_bytes(), b'abcdef')

    def test_slow_source_rotates_before_consuming_the_total_budget(self):
        sources = self.sources() + [
            {'label': 'HuggingFace', 'url': 'https://huggingface.co/PaddlePaddle/model/resolve/'
             + 'b' * 40 + '/inference.pdiparams', 'params': None}]
        http = HTTP([Response([b'a', b'a'], delay=0.12),
                     Response([b'a' * 99], status=206, content_range='bytes 1-99/100')])
        with patch.object(cache, 'DOWNLOAD_RATE_WINDOW', 0.05):
            self.download(http, expected=b'a' * 100, sources=sources)
        self.assertEqual(http.urls, [source['url'] for source in sources])
        self.assertEqual(http.ranges, ['bytes=0-', 'bytes=1-'])
        self.assertEqual(self.destination.read_bytes(), b'a' * 100)

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
        with patch.object(cache, 'DOWNLOAD_PROGRESS_INTERVAL', 0), \
                patch.object(cache, 'DOWNLOAD_PROGRESS_TIMEOUT', 0.3):
            self.download(http, timeout=1)
        self.assertEqual(len(http.ranges), 1)
        self.assertEqual(self.destination.read_bytes(), b'abcdef')
        self.assertIn('100.0%', self.logs.getvalue())

    def test_progress_cannot_extend_shared_hard_budget(self):
        http = HTTP([Response([b'a'] * 20, delay=0.12)])
        started = time.monotonic()
        with self.assertRaises(cache.CachePreparationError):
            self.download(http, expected=b'a' * 20, timeout=0.3)
        self.assertLess(time.monotonic() - started, 0.8)
        self.assertEqual(len(http.ranges), 1)
        self.assertLess(self.destination.stat().st_size, 20)
        self.assertIn('0 retries and 0s total download budget remaining', self.logs.getvalue())

    def test_source_rotation_cannot_restart_the_total_budget(self):
        sources = self.sources() + [
            {'label': 'HuggingFace', 'url': 'https://huggingface.co/PaddlePaddle/model/resolve/'
             + 'b' * 40 + '/inference.pdiparams', 'params': None}]
        http = HTTP([Response([b'a', RequestException('disconnected')], delay=0.2),
                     Response([b'a'] * 20, status=206,
                              content_range='bytes 1-19/20', delay=0.2)])
        started = time.monotonic()
        with self.assertRaises(cache.CachePreparationError):
            self.download(http, expected=b'a' * 20, timeout=0.6, sources=sources)
        self.assertLess(time.monotonic() - started, 0.9)
        self.assertEqual(http.urls, [source['url'] for source in sources])
        self.assertEqual(http.ranges, ['bytes=0-', 'bytes=1-'])

    def test_packaged_lock_contains_all_required_models_and_immutable_sources(self):
        for name in cache.MODEL_NAMES:
            with self.subTest(model=name):
                spec = cache._official_model_spec(name)
                self.assertEqual(set(spec['files']), set(cache.REQUIRED_FILES))
                self.assertEqual(len(spec['huggingface_revision']), 40)
                for filename, record in spec['files'].items():
                    self.assertGreater(record['size'], 0)
                    self.assertEqual(len(record['sha256']), 64)
                    sources = cache._official_file_sources(name, filename, record)
                    self.assertIn('/resolve/' + spec['huggingface_revision'] + '/', sources[0]['url'])
                    self.assertEqual(sources[1]['params']['Revision'], record['revision'])

    def test_malformed_pinned_hash_and_revision_are_rejected(self):
        original = json.loads(cache.MODEL_LOCK_PATH.read_text(encoding='utf-8'))
        name = cache.MODEL_NAMES[0]
        path = Path(self.temporary.name) / 'invalid-model-lock.json'
        for field, value in (('sha256', 'unverified'), ('revision', 'master'), ('size', True)):
            with self.subTest(field=field):
                malformed = deepcopy(original)
                malformed[name]['files']['inference.pdiparams'][field] = value
                path.write_text(json.dumps(malformed), encoding='utf-8')
                with patch.object(cache, 'MODEL_LOCK_PATH', path):
                    with self.assertRaises(cache.CachePreparationError):
                        cache._official_model_spec(name)

    def exercise_persistent_resume(self, *, change_spec=False):
        name = cache.MODEL_NAMES[0]
        cache_home = Path(self.temporary.name) / 'paddlex'
        bodies = dict(zip(cache.REQUIRED_FILES, (b'{"program":true}', b'abcdef', b'Global: model')))

        def spec_for(contents):
            return {'huggingface_revision': 'b' * 40, 'files': {
                filename: {'size': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
                           'revision': 'a' * 40}
                for filename, body in contents.items()}}

        first_spec = spec_for(bodies)
        first_http = HTTP([Response([bodies['inference.json']]),
                           Response([b'abc', RequestException('interrupted')]),
                           Response([RequestException('offline')], status=206,
                                    content_range='bytes 3-5/6'),
                           Response([RequestException('offline')], status=206,
                                    content_range='bytes 3-5/6')])
        second_bodies = dict(bodies)
        if change_spec:
            second_bodies['inference.pdiparams'] = b'uvwxyz'
            second_responses = [Response([second_bodies[filename]]) for filename in cache.REQUIRED_FILES]
        else:
            second_responses = [Response([b'def'], status=206, content_range='bytes 3-5/6'),
                                Response([bodies['inference.yml']])]
        second_spec = spec_for(second_bodies)
        second_http = HTTP(second_responses)

        def sources(model, filename, record):
            return [{'label': 'ModelScope', 'url': f'https://modelscope.cn/{model}/{filename}',
                     'params': {'Revision': record['revision'], 'FilePath': filename}}]

        def inspect(staging_home, model):
            self.assertEqual(model, name)
            for filename, body in second_bodies.items():
                self.assertEqual((Path(staging_home) / 'official_models' / model / filename).read_bytes(), body)

        requests_stub = sys.modules['requests']
        with patch.object(requests_stub, 'Session', create=True, side_effect=[first_http, second_http]), \
                patch.object(cache, '_official_model_spec', side_effect=[first_spec, second_spec]), \
                patch.object(cache, '_official_file_sources', side_effect=sources), \
                patch.object(cache, 'inspect_model', side_effect=inspect) as inspector:
            with self.assertRaises(cache.CachePreparationError):
                cache._download_official_model(cache_home, name, 1)
            partial_home = cache_home / '.downloads' / name
            self.assertTrue((partial_home / 'source.json').exists())
            self.assertFalse((cache_home / 'official_models' / name).exists())
            inspector.assert_not_called()
            published = cache._download_official_model(cache_home, name, 1)
            inspector.assert_called_once()
        self.assertFalse((cache_home / '.downloads' / name).exists())
        for filename, body in second_bodies.items():
            self.assertEqual((published / filename).read_bytes(), body)
        return second_http

    def test_failed_preparation_retains_staging_and_next_run_resumes(self):
        http = self.exercise_persistent_resume()
        self.assertEqual(http.ranges, ['bytes=3-', 'bytes=0-'])
        self.assertEqual([params['FilePath'] for params in http.parameters],
                         ['inference.pdiparams', 'inference.yml'])

    def test_changed_pinned_spec_discards_old_partial_staging(self):
        http = self.exercise_persistent_resume(change_spec=True)
        self.assertEqual(http.ranges, ['bytes=0-'] * len(cache.REQUIRED_FILES))
        self.assertEqual([params['FilePath'] for params in http.parameters], list(cache.REQUIRED_FILES))

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
