"""Stable frame IDs do not override a user's explicit reading order."""
import io
import json
from pathlib import Path

import pytest

from graph_region import RegionError, validate_text_regions
from test_ocr_application_contract import application
from test_text_region_batch import image_bytes, regions, register


def ordered():
    return [{**row, 'order': index} for index, row in enumerate(regions())]


def test_order_is_preserved_across_route_and_worker_validation_without_renumbering():
    value = ordered()
    result = validate_text_regions(value)
    assert [row['id'] for row in result] == [2, 1]
    assert validate_text_regions(result) == result
    assert value == ordered()


@pytest.mark.parametrize('mutation', ['partial', 'duplicate', 'negative', 'boolean', 'float'])
def test_invalid_explicit_order_is_not_silently_replaced_with_id_order(mutation):
    value = ordered()
    if mutation == 'partial':
        value[1].pop('order')
    else:
        value[1]['order'] = {'duplicate': 0, 'negative': -1, 'boolean': True, 'float': .5}[mutation]
    with pytest.raises(RegionError):
        validate_text_regions(value)


def test_one_small_ocr_worker_processes_crops_in_the_selected_order(monkeypatch):
    import ocr_runtime
    calls = []
    def worker(stage, input_path, output_path, *, layout_path, timeout):
        plan = json.loads(Path(layout_path).read_text())
        calls.append(plan['text_region_files'])
        assert [row['id'] for row in calls[0]] == [2, 1]
        return {'text': '先读第二框\n\n再读第一框', 'regions': [
            {'id': 2, 'text': '先读第二框'}, {'id': 1, 'text': '再读第一框'}]}, {'status': 'ok'}
    monkeypatch.setattr(ocr_runtime, 'run_worker', worker)
    result = ocr_runtime.recognize_text_regions(image_bytes(), ordered())
    assert len(calls) == 1
    assert [row['id'] for row in result['regions']] == [2, 1]
    assert result['text'] == '先读第二框\n\n再读第一框'


def test_actual_endpoint_retains_explicit_order_and_rejects_ambiguous_order(application, monkeypatch):
    import ocr_runtime
    _, client, _ = application
    raw = image_bytes()
    register(client, raw)
    calls = []
    def read(data, items):
        calls.append(items)
        return {'regions': [{'id': row['id'], 'text': str(row['id'])} for row in items], 'text': '2\n\n1'}
    monkeypatch.setattr(ocr_runtime, 'recognize_text_regions', read)
    def post(items):
        return client.post('/graph/text-region', data={'image': (io.BytesIO(raw), 'original.png'),
            'request_id': 'batch-text-test', 'regions': json.dumps(items)})
    result = post(ordered())
    assert result.status_code == 200, result.get_json()
    assert [row['id'] for row in calls[0]] == [2, 1]
    assert result.get_json()['text'] == '2\n\n1'
    invalid = ordered()
    invalid[1]['order'] = 0
    assert post(invalid).status_code == 400 and len(calls) == 1
