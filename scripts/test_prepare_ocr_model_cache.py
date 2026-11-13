#!/usr/bin/env python3
"""Offline regression checks for bounded, resumable official model downloads."""
from contextlib import contextmanager, redirect_stderr
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
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
        assert size == 16 * 1024
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
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.destination = Path(self.temporary.name) / 'inference.pdiparams'
        self.requests = patch.dict(sys.modules, {
            'requests': SimpleNamespace(RequestException=RequestException, HTTPError=HTTPError)})
        self.requests.start()
        self.addCleanup(self.requests.stop)
        backoff = patch.object(cache, 'DOWNLOAD_RETRY_BACKOFF', 0)
        backoff.start()
        self.addCleanup(backoff.stop)
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

    def test_slow_source_is_resumable_after_alternative_is_forbidden(self):
        sources = self.sources() + [{'label': 'fallback', 'url': 'https://fallback.invalid/model',
                                     'params': None}]
        forbidden = HTTPError('forbidden')
        forbidden.response = SimpleNamespace(status_code=403)
        http = HTTP([Response([b'a'], delay=0.06), forbidden,
                     Response([b'a' * 99], status=206, content_range='bytes 1-99/100')])
        with patch.object(cache, 'DOWNLOAD_RATE_WINDOW', 0.05):
            self.download(http, expected=b'a' * 100, sources=sources)
        self.assertEqual(http.urls, [sources[0]['url'], sources[1]['url'], sources[0]['url']])
        self.assertEqual(http.ranges, ['bytes=0-', 'bytes=1-', 'bytes=1-'])
        self.assertEqual(self.destination.read_bytes(), b'a' * 100)

    def test_two_slow_sources_are_deprioritized_but_not_both_disabled(self):
        sources = self.sources() + [{'label': 'fallback', 'url': 'https://fallback.invalid/model',
                                     'params': None}]
        http = HTTP([Response([b'a'], delay=0.06),
                     Response([b'a'], status=206, content_range='bytes 1-99/100', delay=0.06),
                     Response([b'a' * 98], status=206, content_range='bytes 2-99/100')])
        with patch.object(cache, 'DOWNLOAD_RATE_WINDOW', 0.05):
            self.download(http, expected=b'a' * 100, sources=sources)
        self.assertEqual(http.ranges, ['bytes=0-', 'bytes=1-', 'bytes=2-'])
        self.assertEqual(self.destination.read_bytes(), b'a' * 100)

    def test_slow_source_is_not_starved_by_an_alternative_timing_out(self):
        sources = self.sources() + [{'label': 'fallback', 'url': 'https://fallback.invalid/model',
                                     'params': None}]
        http = HTTP([Response([b'a'], delay=0.06),
                     RequestException('timed out'),
                     Response([b'a' * 99], status=206, content_range='bytes 1-99/100')])
        with patch.object(cache, 'DOWNLOAD_RATE_WINDOW', 0.05):
            self.download(http, expected=b'a' * 100, sources=sources)
        self.assertEqual(http.urls, [sources[0]['url'], sources[1]['url'], sources[0]['url']])
        self.assertEqual(self.destination.read_bytes(), b'a' * 100)

    def test_every_source_continuously_failing_exhausts_finite_retries(self):
        sources = self.sources() + [{'label': 'fallback', 'url': 'https://fallback.invalid/model',
                                     'params': None}]
        http = HTTP([Response([RequestException('disconnected')])
                     for _ in range(cache.DOWNLOAD_ATTEMPTS)])
        with self.assertRaisesRegex(cache.CachePreparationError, 'official_file_download_failed'):
            self.download(http, sources=sources)
        self.assertEqual(len(http.urls), 6)
        self.assertEqual(set(http.urls), {source['url'] for source in sources})
        self.assertIn('0 retries', self.logs.getvalue())

    def test_retry_backoff_cannot_outlive_shared_hard_budget(self):
        http = HTTP([Response([RequestException('disconnected')])])
        started = time.monotonic()
        with patch.object(cache, 'DOWNLOAD_RETRY_BACKOFF', 1):
            with self.assertRaises(cache.CachePreparationError):
                self.download(http, timeout=0.1)
        self.assertLess(time.monotonic() - started, 0.4)
        self.assertEqual(len(http.ranges), 1)

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

    def test_default_budget_covers_reported_layout_transfer_and_cli_uses_it(self):
        layout_bytes = cache._official_model_spec('PP-DocLayoutV3')['files']['inference.pdiparams']['size']
        # The failed deployment transferred about 65 KiB/s, including healthy
        # partial progress. This file cannot fit the previous 300/600 s limit.
        self.assertGreater(cache.DEFAULT_DOWNLOAD_TIMEOUT, layout_bytes / (65 * 1024) + 60)
        with patch.object(cache, 'prepare_model_cache', return_value={}) as prepare, \
                patch('sys.stdout', new=io.StringIO()):
            self.assertEqual(cache.main([]), 0)
        self.assertEqual(prepare.call_args.kwargs['timeout_seconds'], 3600)

    def test_longer_download_budget_does_not_extend_conversion_deadline(self):
        home = Path(self.temporary.name) / 'paddlex'
        home.mkdir()
        with patch.object(cache, 'configure_build_cache', return_value=(home, {})), \
                patch.object(cache, '_download_official_model'), \
                patch.object(cache, 'inspect_model', side_effect=lambda _, name: {'name': name}), \
                patch.object(cache, '_export_onnx_model', return_value=({}, True)) as export, \
                patch.object(cache, 'verify_manifest'), \
                patch.object(cache.metadata, 'version', return_value='test'):
            cache.prepare_model_cache(home, timeout_seconds=7200)
        self.assertEqual(len(export.call_args_list), 2)
        self.assertEqual([call.args[2] for call in export.call_args_list], [300, 300])
        for invalid in (0, -1, 7201, float('inf'), float('nan'), True):
            with self.subTest(timeout=invalid), self.assertRaisesRegex(
                    cache.CachePreparationError, 'invalid_download_deadline'):
                cache.prepare_model_cache(home, timeout_seconds=invalid)

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
                           *[Response([RequestException('offline')], status=206,
                                      content_range='bytes 3-5/6')
                             for _ in range(cache.DOWNLOAD_ATTEMPTS - 1)]])
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


class LocalHTTPTests(unittest.TestCase):
    """Real requests streaming against a small controlled loopback server."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.destination = Path(self.temporary.name) / 'inference.pdiparams'
        self.body = bytes(range(256)) * 384  # 96 KiB, never an external model.
        self.logs = io.StringIO()
        stderr = redirect_stderr(self.logs)
        stderr.__enter__()
        self.addCleanup(stderr.__exit__, None, None, None)
        backoff = patch.object(cache, 'DOWNLOAD_RETRY_BACKOFF', 0)
        backoff.start()
        self.addCleanup(backoff.stop)

    @contextmanager
    def server(self, mode):
        body, ranges = self.body, []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                offset = int(self.headers.get('Range', 'bytes=0-')[6:-1])
                ranges.append(offset)
                self.send_response(206 if offset else 200)
                self.send_header('Content-Length', str(len(body) - offset))
                if offset:
                    self.send_header('Content-Range', f'bytes {offset}-{len(body) - 1}/{len(body)}')
                self.end_headers()
                try:
                    if mode == 'stall':
                        time.sleep(0.4)
                        return
                    end = offset + 2 * 16 * 1024 if mode == 'interrupt' and len(ranges) == 1 else len(body)
                    for start in range(offset, end, 16 * 1024):
                        if mode == 'slow':
                            time.sleep(0.06)
                        self.wfile.write(body[start:min(start + 16 * 1024, end)])
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass  # The client intentionally aborts a stalled response.
                finally:
                    self.close_connection = True

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}/model', ranges
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

    def download(self, url, timeout):
        import requests
        record = {'size': len(self.body), 'sha256': hashlib.sha256(self.body).hexdigest()}
        with requests.Session() as http:
            # This test talks exclusively to its own loopback server.
            http.trust_env = False
            cache._download_official_file(http, cache.MODEL_NAMES[0], 'inference.pdiparams',
                                          record, self.destination, timeout,
                                          sources=[{'label': 'loopback', 'url': url, 'params': None}])

    def test_real_disconnection_resumes_at_written_range_and_verifies_hash(self):
        with self.server('interrupt') as (url, ranges):
            self.download(url, 2)
        self.assertEqual(ranges, [0, 2 * 16 * 1024])
        self.assertEqual(self.destination.read_bytes(), self.body)
        self.assertIn('ChunkedEncodingError', self.logs.getvalue())
        self.assertIn('and SHA256', self.logs.getvalue())

    def test_real_slow_progress_refreshes_idle_timer_before_full_64k_buffer(self):
        with self.server('slow') as (url, ranges), \
                patch.object(cache, 'DOWNLOAD_PROGRESS_TIMEOUT', 0.2):
            self.download(url, 2)
        self.assertEqual(ranges, [0])
        self.assertEqual(self.destination.read_bytes(), self.body)

    def test_real_stalled_stream_exhausts_hard_budget_and_never_succeeds(self):
        with self.server('stall') as (url, ranges), \
                patch.object(cache, 'DOWNLOAD_PROGRESS_TIMEOUT', 0.08):
            started = time.monotonic()
            with self.assertRaisesRegex(cache.CachePreparationError, 'official_file_download_failed'):
                self.download(url, 0.25)
            self.assertLess(time.monotonic() - started, 0.7)
        self.assertGreaterEqual(len(ranges), 1)
        self.assertLessEqual(len(ranges), cache.DOWNLOAD_ATTEMPTS)
        self.assertNotEqual(self.destination.read_bytes(), self.body)
        self.assertNotIn('and SHA256', self.logs.getvalue())


if __name__ == '__main__':
    unittest.main()
