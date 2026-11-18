"""Recover source-bound OCR jobs across clients without repeating inference."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ocr_task_registry import OcrTaskCapacity, OcrTaskConflict, OcrTaskRegistry


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.now = 1000
        self.path = Path(self.directory.name) / 'jobs.sqlite3'
        self.jobs = OcrTaskRegistry(self.path, clock=lambda: self.now)

    def test_other_worker_can_read_running_and_completed_receipts(self):
        first = self.jobs.claim('owner-a', 'task-a', 'sha-a')
        other_worker = OcrTaskRegistry(self.path, clock=lambda: self.now)
        self.assertEqual(other_worker.claim('owner-a', 'task-a', 'sha-a')['status'], 'processing')
        result = {'document': {'body_text': 'Exact recognized text', 'graphs': []}, 'recognition_status': 'complete'}
        self.assertTrue(self.jobs.finish('owner-a', 'task-a', first['token'], result, 200))
        self.assertEqual(other_worker.get('owner-a', 'task-a', 'sha-a'), {
            'request_id': 'task-a', 'source_sha256': 'sha-a', 'status': 'completed', 'result': result, 'http_status': 200})
        self.assertEqual(other_worker.get('owner-b', 'task-a', 'sha-a')['status'], 'missing')
        with self.assertRaises(OcrTaskConflict):
            other_worker.get('owner-a', 'task-a', 'different-sha')
        with self.assertRaises(OcrTaskConflict):
            other_worker.claim('owner-a', 'task-a', 'different-sha')

    def test_expired_worker_cannot_overwrite_a_reclaimed_task(self):
        first = self.jobs.claim('owner', 'task', 'sha')
        self.now += self.jobs.lease_seconds + 1
        self.assertEqual(self.jobs.get('owner', 'task', 'sha')['status'], 'missing')
        second = self.jobs.claim('owner', 'task', 'sha')
        self.assertNotEqual(first['token'], second['token'])
        self.assertFalse(self.jobs.finish('owner', 'task', first['token'], {'text': 'Old result'}, 200))
        self.assertTrue(self.jobs.finish('owner', 'task', second['token'], {'text': 'Current result'}, 200))
        self.assertEqual(self.jobs.get('owner', 'task', 'sha')['result']['text'], 'Current result')

    def test_terminal_failure_and_cancellation_are_reused_without_claiming(self):
        for task, result, code, state in [('failure', {'error': 'Provider unavailable'}, 503, 'failed'),
                                          ('cancel', {'cancelled': True}, 200, 'cancelled')]:
            first = self.jobs.claim('owner', task, 'sha')
            self.jobs.finish('owner', task, first['token'], result, code)
            receipt = self.jobs.claim('owner', task, 'sha')
            self.assertEqual((receipt['status'], receipt['result'], receipt['http_status']), (state, result, code))

    def test_cache_bounds_never_evict_running_tasks(self):
        jobs = OcrTaskRegistry(self.path, clock=lambda: self.now, capacity=2, max_bytes=150)
        first = jobs.claim('owner', 'running', 'sha')
        second = jobs.claim('owner', 'complete-one', 'sha')
        with self.assertRaises(OcrTaskCapacity):
            jobs.claim('owner', 'overflow', 'sha')
        jobs.finish('owner', 'complete-one', second['token'], {'text': 'a' * 80}, 200)
        self.now += 1
        third = jobs.claim('owner', 'complete-two', 'sha')
        jobs.finish('owner', 'complete-two', third['token'], {'text': 'b' * 80}, 200)
        self.assertEqual(jobs.get('owner', 'running', 'sha')['status'], 'processing')
        self.assertEqual(jobs.get('owner', 'complete-one', 'sha')['status'], 'missing')
        self.assertEqual(jobs.get('owner', 'complete-two', 'sha')['status'], 'completed')
        with jobs.connection() as db:
            size = db.execute('SELECT COALESCE(SUM(LENGTH(CAST(result_json AS BLOB))),0) FROM ocr_tasks').fetchone()[0]
        self.assertLessEqual(size, jobs.max_bytes)
        jobs.abandon('owner', 'running', first['token'])
        self.assertEqual(jobs.claim('owner', 'running', 'sha')['status'], 'claimed')

    def test_stale_processing_leases_release_capacity_before_the_receipt_ttl(self):
        jobs = OcrTaskRegistry(self.path, clock=lambda: self.now, capacity=2)
        jobs.claim('owner', 'abandoned-one', 'sha')
        jobs.claim('owner', 'abandoned-two', 'sha')
        self.now += jobs.lease_seconds + 1
        self.assertEqual(jobs.claim('owner', 'new-task', 'sha')['status'], 'claimed')
        self.assertEqual(jobs.get('owner', 'abandoned-one', 'sha')['status'], 'missing')
        self.assertEqual(jobs.get('owner', 'abandoned-two', 'sha')['status'], 'missing')

    def test_simultaneous_worker_claims_start_only_one_task(self):
        barrier, results, errors = threading.Barrier(2), [], []
        def claim():
            try:
                barrier.wait(3)
                results.append(OcrTaskRegistry(self.path, clock=lambda: self.now).claim('owner', 'task', 'sha'))
            except Exception as error:
                errors.append(error)
        threads = [threading.Thread(target=claim) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(item['status'] for item in results), ['claimed', 'processing'])


class RecoveryRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch('requests.sessions.Session.request', side_effect=AssertionError('No network in OCR recovery tests')):
            import app as runtime
        cls.runtime = runtime

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.jobs = OcrTaskRegistry(Path(self.directory.name) / 'jobs.sqlite3')
        self.addCleanup(patch.stopall)
        patch('ocr_task_registry.OCR_TASKS', self.jobs).start()
        patch.dict('os.environ', {'DMATE_GRAPH_CONFIRMATION_DB': str(Path(self.directory.name) / 'sources.sqlite3')}).start()
        self.runtime.app.config.update(TESTING=True)
        patch.object(self.runtime, '_check_rate_limit', return_value=True).start()
        self.cookie = 'a' * 64
        self.image = b'Exact original source bytes'
        self.sha = hashlib.sha256(self.image).hexdigest()

    def client(self, cookie=None):
        client = self.runtime.app.test_client()
        client.set_cookie('dm_graph_owner', cookie or self.cookie)
        return client

    def upload(self, client, **kwargs):
        return client.post('/ocr', data={'image': (io.BytesIO(self.image), 'source.png'),
                                         'workflow': 'auto_graph', 'request_id': 'task-original',
                                         'source_sha256': self.sha}, **kwargs)

    def status(self, client, **kwargs):
        return client.get('/ocr/status', query_string={'request_id': 'task-original', 'source_sha256': self.sha}, **kwargs)

    def test_reopened_client_observes_original_inference_and_reuses_its_result(self):
        entered, release = threading.Event(), threading.Event()
        result = {'text': 'Finished after original page closed', 'document': {'body_text': 'Saved text', 'graphs': []}}
        answers = []

        def recognize(**kwargs):
            self.assertEqual(kwargs['raw'], self.image)
            entered.set()
            self.assertTrue(release.wait(5))
            return self.runtime.jsonify(result)

        with patch.object(self.runtime, '_ocr_uncached', side_effect=recognize) as model:
            thread = threading.Thread(target=lambda: answers.append(self.upload(self.client())))
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                reopened = self.client()
                self.assertEqual(self.status(reopened).get_json()['status'], 'processing')
                duplicate = self.upload(reopened)
                self.assertEqual((duplicate.status_code, duplicate.get_json()['status']), (202, 'processing'))
                self.assertEqual(self.status(self.client('b' * 64)).get_json()['status'], 'missing')
                self.assertEqual(model.call_count, 1)
            finally:
                release.set()
                thread.join(5)
            self.assertFalse(thread.is_alive())
            final = self.status(reopened).get_json()
            self.assertEqual((final['status'], final['result'], final['http_status']), ('completed', result, 200))
            with patch.object(self.runtime, '_check_rate_limit', return_value=False) as limiter:
                cached = self.upload(reopened)
                self.assertEqual((cached.status_code, cached.get_json()), (200, result))
                limiter.assert_not_called()
            self.assertEqual(model.call_count, 1)

    def test_capacity_rejection_can_later_continue_same_task(self):
        with patch.object(self.runtime, '_ocr_uncached', side_effect=lambda **_: (self.runtime.jsonify(
                error='Busy', error_code='recognition_capacity'), 429)):
            response = self.upload(self.client())
        self.assertEqual(response.status_code, 429)
        self.assertTrue(response.get_json()['retryable'])
        self.assertEqual(self.status(self.client()).get_json()['status'], 'missing')
        with patch.object(self.runtime, '_ocr_uncached', side_effect=lambda **_: self.runtime.jsonify(text='Now complete')) as model:
            self.assertEqual(self.upload(self.client()).get_json(), {'text': 'Now complete'})
            model.assert_called_once()

    def test_unexpected_worker_failure_is_terminal_and_does_not_repeat_inference(self):
        with patch.object(self.runtime, '_ocr_uncached', side_effect=RuntimeError('Fixture worker failure')) as model:
            first = self.upload(self.client())
            self.assertEqual(first.status_code, 500)
            receipt = self.status(self.client()).get_json()
            self.assertEqual((receipt['status'], receipt['http_status']), ('failed', 500))
            second = self.upload(self.client())
            self.assertEqual((second.status_code, second.get_json()), (500, first.get_json()))
            model.assert_called_once()

    def test_expired_or_wrong_account_cannot_resume_as_guest(self):
        with patch.object(self.runtime, '_current_auth_user', return_value=None), \
                patch.object(self.runtime, '_ocr_uncached') as model:
            headers = {'X-DMate-Draft-Owner': 'Expected account'}
            self.assertEqual(self.upload(self.client(), headers=headers).status_code, 401)
            self.assertEqual(self.status(self.client(), headers=headers).status_code, 401)
            source = self.client().post('/graph/source', headers=headers, data={})
            self.assertEqual(source.status_code, 401)
            model.assert_not_called()

    def test_encoded_chinese_account_name_is_checked_after_decoding(self):
        from urllib.parse import quote
        username = '图形学习者'
        with patch.object(self.runtime, '_current_auth_user', return_value={'username': username}):
            response = self.status(self.client(), headers={'X-DMate-Draft-Owner': quote(username, safe='')})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()['status'], 'missing')
            invalid = self.status(self.client(), headers={'X-DMate-Draft-Owner': '%FF'})
            self.assertEqual(invalid.status_code, 401)

    def test_rebind_original_source_without_recognition(self):
        from PIL import Image
        from graph_confirmation import confirmation_owner, require_recognition_source
        image = io.BytesIO()
        Image.new('RGB', (4, 3), 'white').save(image, 'PNG')
        raw = image.getvalue()
        sha = hashlib.sha256(raw).hexdigest()
        with patch.object(self.runtime, '_ocr_uncached') as model, \
                patch('requests.sessions.Session.request', side_effect=AssertionError('No model/network')):
            client = self.client()
            rebound = client.post('/graph/source', data={'request_id': 'saved-source', 'source_sha256': sha,
                'image': (io.BytesIO(raw), 'original.png')})
            self.assertEqual(rebound.status_code, 200)
            self.assertEqual(rebound.get_json(), {'ok': True, 'request_id': 'saved-source', 'source_sha256': sha})
            model.assert_not_called()
            with self.runtime.app.test_request_context(headers={'Cookie': 'dm_graph_owner=' + self.cookie}):
                owner = confirmation_owner()
                require_recognition_source(owner, 'saved-source', sha)
            self.assertEqual(self.jobs.get(owner, 'saved-source', sha)['status'], 'missing')
            wrong = client.post('/graph/source', data={'request_id': 'saved-source', 'source_sha256': 'b' * 64,
                'image': (io.BytesIO(raw), 'original.png')})
            self.assertEqual(wrong.status_code, 409)


if __name__ == '__main__':
    unittest.main()
