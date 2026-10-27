"""Real Flask concurrency and isolation with an explicit synthetic model boundary."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import threading

from PIL import Image

from test_ocr_application_contract import application, graph_result


def original(index):
    buffer = io.BytesIO()
    Image.new('RGB', (8, 8), (index * 30, 80, 160)).save(buffer, 'PNG')
    return buffer.getvalue()


def post(client, request_id, raw):
    return client.post('/ocr', data={'request_id': request_id,
        'image': (io.BytesIO(raw), 'synthetic.png')}, content_type='multipart/form-data')


def test_four_real_upload_routes_enter_models_concurrently_and_failure_is_isolated(application, monkeypatch, tmp_path):
    module, _, _ = application
    monkeypatch.delenv('DMATE_GRAPH_PIPELINE', raising=False)
    monkeypatch.setenv('DMATE_GRAPH_CONFIRMATION_DB', str(tmp_path/'confirmations.db'))
    entered, release = threading.Barrier(5), threading.Event()
    sends = []
    lock = threading.Lock()

    def recognize(raw, local, **kwargs):
        with lock:
            sends.append((kwargs['task_id'], hashlib.sha256(raw).hexdigest()))
        entered.wait(timeout=10)
        assert release.wait(timeout=10)
        if kwargs['task_id'] == 'image-1':
            raise RuntimeError('synthetic remote failure')
        return graph_result()

    monkeypatch.setattr('ocr_nextgen.recognize_graph_document', recognize)

    def request(index):
        client = module.app.test_client()
        assert client.get('/graph/session').status_code == 200
        return post(client, f'image-{index}', original(index))

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(request, index) for index in range(4)]
        try:
            entered.wait(timeout=10)
            client = module.app.test_client()
            response = post(client, 'fifth', original(4))
            assert response.status_code == 429
            assert response.get_json()['error_code'] == 'recognition_capacity'
            assert len(sends) == 4
        finally:
            release.set()
        responses = [future.result(timeout=10) for future in futures]
    for index, response in enumerate(responses):
        result = response.get_json()
        assert response.status_code == (503 if index == 1 else 200)
        assert result['request_id'] == f'image-{index}'
        assert result['source_sha256'] == hashlib.sha256(original(index)).hexdigest()
        assert result['recognition_status'] == ('failed' if index == 1 else 'complete')
        assert result['server_elapsed_seconds'] >= 0


def test_cancelling_same_named_task_does_not_cancel_another_browser(application, monkeypatch, tmp_path):
    module, client, _ = application
    monkeypatch.delenv('DMATE_GRAPH_PIPELINE', raising=False)
    monkeypatch.setenv('DMATE_GRAPH_CONFIRMATION_DB', str(tmp_path/'confirmations.db'))
    sends = []
    monkeypatch.setattr('ocr_nextgen.recognize_graph_document',
        lambda *args, **kwargs: sends.append(kwargs['task_id']) or graph_result())
    other = module.app.test_client()
    assert client.get('/graph/session').status_code == other.get('/graph/session').status_code == 200
    assert client.post('/ocr/cancel', json={'request_id': 'same-name'}).status_code == 200
    assert post(other, 'same-name', original(0)).get_json()['recognition_status'] == 'complete'
    assert post(client, 'same-name', original(0)).get_json() == {'cancelled': True}
    assert sends == ['same-name']


def test_cancellation_callback_keeps_owner_identity_in_model_threads(application, monkeypatch, tmp_path):
    module, client, _ = application
    monkeypatch.delenv('DMATE_GRAPH_PIPELINE', raising=False)
    monkeypatch.setenv('DMATE_GRAPH_CONFIRMATION_DB', str(tmp_path/'confirmations.db'))
    client.get('/graph/session')

    def recognize(*args, **kwargs):
        module._mark_ocr_cancelled(kwargs['task_id'])
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(kwargs['cancelled']).result(timeout=5) is True
        return graph_result()

    monkeypatch.setattr('ocr_nextgen.recognize_graph_document', recognize)
    assert post(client, 'cancel-current', original(0)).get_json() == {'cancelled': True}
