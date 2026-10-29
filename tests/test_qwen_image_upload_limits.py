"""Large originals reach Qwen without a preview-sized or invalid sending copy."""
import base64
import hashlib
import io
import json

import numpy as np
from PIL import Image
import pytest

from image_upload_limits import (MAX_IMAGE_BYTES, MAX_IMAGE_PIXELS,
                                 MAX_QWEN_IMAGE_DATA_URI_BYTES, encode_qwen_image)
from test_ocr_application_contract import application, graph_result


def padded_png(length):
    stream = io.BytesIO()
    Image.new('RGB', (24, 24), 'white').save(stream, 'PNG')
    raw = stream.getvalue()
    return raw + b'\0' * (length - len(raw))


def upload(client, raw, workflow='auto_graph'):
    return client.post('/ocr', data={'request_id': 'large-original',
        'workflow': workflow, 'image': (io.BytesIO(raw), 'original.png')})


@pytest.mark.parametrize('length', [8 * 1024 * 1024 + 1, MAX_IMAGE_BYTES])
def test_real_upload_admits_large_original_unchanged(application, monkeypatch, tmp_path, length):
    _, client, _ = application
    monkeypatch.setenv('DMATE_GRAPH_CONFIRMATION_DB', str(tmp_path / 'confirmations.sqlite3'))
    client.get('/graph/session')
    seen = []
    def recognize(raw, **_):
        seen.append((len(raw), hashlib.sha256(raw).hexdigest()))
        return graph_result()
    monkeypatch.setattr('graph_qwen_targeted.recognize_qwen_targeted', recognize)
    raw = padded_png(length)
    response = upload(client, raw)
    assert response.status_code == 200, response.get_json()
    assert seen == [(length, hashlib.sha256(raw).hexdigest())]


def test_all_source_routes_reject_oversize_before_any_model(application, monkeypatch):
    _, client, _ = application
    calls = []
    monkeypatch.setattr('graph_qwen_targeted.recognize_qwen_targeted', lambda *_a, **_k: calls.append(1))
    raw = padded_png(MAX_IMAGE_BYTES + 1)
    for route in ('/ocr', '/graph/text-region', '/graph/recognize-region', '/graph/figure-type'):
        response = client.post(route, data={'request_id': 'large-original',
            'image': (io.BytesIO(raw), 'original.png')})
        assert response.status_code == 413, (route, response.get_json())
        assert '20MB' in response.get_json()['error']
    assert not calls


def test_original_and_framed_graph_text_share_the_larger_source_limit(application, monkeypatch):
    _, client, _ = application
    client.get('/graph/session')
    raw = padded_png(9_000_000)
    assert upload(client, raw, 'manual_graph').status_code == 200
    seen = []
    def text(source, regions):
        seen.append(('text', hashlib.sha256(source).hexdigest()))
        return {'regions': [{'id': 1, 'text': 'large original'}], 'text': 'large original'}
    def graph(source, _polygon, **_):
        seen.append(('graph', hashlib.sha256(source).hexdigest()))
        return graph_result()
    monkeypatch.setattr('ocr_runtime.recognize_text_regions', text)
    monkeypatch.setattr('graph_region_recognition.recognize_graph_region', graph)
    polygon = [[0, 0], [1, 0], [1, 1], [0, 1]]
    for route, extra in (
        ('/graph/text-region', {'regions': json.dumps([{'id': 1, 'polygon': polygon}])}),
        ('/graph/recognize-region', {'polygon': json.dumps(polygon)}),
    ):
        response = client.post(route, data={'request_id': 'large-original',
            'image': (io.BytesIO(raw), 'original.png'), **extra})
        assert response.status_code == 200, response.get_json()
    digest = hashlib.sha256(raw).hexdigest()
    assert seen == [('text', digest), ('graph', digest)]


def test_small_model_copy_is_lossless_png():
    with Image.new('RGB', (127, 53), (23, 88, 195)) as original:
        url = encode_qwen_image(original)
        assert url.startswith('data:image/png;base64,')
        with Image.open(io.BytesIO(base64.b64decode(url.split(',', 1)[1]))) as decoded:
            assert decoded.size == original.size
            assert decoded.tobytes() == original.tobytes()


def test_large_model_copy_fits_data_uri_and_preserves_full_dimensions():
    # A valid <20MB PNG whose Base64 form is >20MB. Never send that PNG URI.
    rng = np.random.default_rng(148)
    pixels = rng.integers(0, 256, size=(2400, 2400, 3), dtype=np.uint8)
    with Image.fromarray(pixels) as original:
        url = encode_qwen_image(original)
        assert url.startswith('data:image/jpeg;base64,')
        assert len(url.encode('ascii')) <= MAX_QWEN_IMAGE_DATA_URI_BYTES
        with Image.open(io.BytesIO(base64.b64decode(url.split(',', 1)[1]))) as decoded:
            assert decoded.size == (2400, 2400)
        from vision_provider import VisionProvider
        payload = VisionProvider('qwen').payload('读取这张原图', [url])
        assert payload['messages'][0]['content'][1]['image_url']['url'] == url
        assert len(json.dumps(payload).encode()) < 64_000_000


def test_high_resolution_source_remains_readable_for_region_selection():
    from graph_region import crop_region
    from image_evidence import decode_document_image
    import ocr_runtime
    assert ocr_runtime.MAX_PIXELS == MAX_IMAGE_PIXELS == 7680 * 4320
    stream = io.BytesIO()
    with Image.new('RGB', (7500, 3600), 'white') as original:
        original.save(stream, 'PNG')
    raw = stream.getvalue()
    with decode_document_image(raw) as source:
        assert source.size == (7500, 3600)
        crop = crop_region(raw, [[0, 0], [.1, 0], [.1, .1], [0, .1]], _photo=source)
    with Image.open(io.BytesIO(crop)) as region:
        assert region.size == (752, 362)
