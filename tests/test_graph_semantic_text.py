"""Small-worker contract tests; synthetic OCR items are never image accuracy."""
import copy
import fcntl
import hashlib
import io
import json
from pathlib import Path
import time
from unittest.mock import Mock

from PIL import Image, ImageDraw
import pytest
import requests

import graph_semantic_text as module
from graph_semantic_text import prepare_semantic_text
from image_evidence import analyze_document, decode_document_image


REAL_CACHE_READINESS = module._cache_readiness


class Budget:
    def __init__(self, seconds=30):
        self.deadline = time.monotonic()+seconds
        self.source_sha256 = None

    def check(self):
        if time.monotonic() >= self.deadline:
            raise TimeoutError('fixture_deadline')


def png(image):
    stream = io.BytesIO(); image.save(stream, format='PNG'); return stream.getvalue()


def picture():
    image = Image.new('RGBA', (300, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.text((25, 15), 'READ ORIGINAL PIXELS', fill='black')
    draw.ellipse((70, 75, 95, 100), outline='red', width=3)
    return image


def evidence(size=(300, 200)):
    return {'text': '第三问 v₅', 'formula_count': 0, 'text_evidence': {
        'body': [{'content': '第三问 v₅', 'box': [10, 10, 150, 30], 'score': .89,
                  'ocr_provenance': {'pass_index': 1, 'pass_kind': 'original', 'item_index': 0}}],
        'graph_labels': [{'content': 'e₇', 'box': [80, 80, 100, 100], 'score': .81,
                          'region_ids': ['r1']},
                         {'content': '−5', 'box': [115, 90, 135, 110], 'score': .72}],
        'uncertain': [{'content': 'v₃', 'box': [10, 10, 150, 30], 'score': .67,
                       'ocr_provenance': {'pass_index': 2, 'pass_kind': 'enhanced', 'item_index': 1}}],
        'noise': [{'content': '(a)', 'box': [120, 160, 150, 180], 'score': .9}],
        'coordinate_space': 'canonical_image_pixels', 'image_size': list(size)}}


def worker_metric(size=(300, 200)):
    return {'stage': 'text', 'status': 'ok', 'seconds': .02,
            'audit': {'schema_version': 1, 'stage': 'text', 'current': {'phase': 'complete'},
                      'input_size': list(size), 'events': [],
                      'passes': [{'pass_index': 1, 'kind': 'original'}]}}


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(requests.sessions.Session, 'send', lambda *a, **k: pytest.fail('network forbidden'))
    monkeypatch.setattr('subprocess.Popen', lambda *a, **k: pytest.fail('unmocked model worker'))
    monkeypatch.setattr(module.tempfile, 'gettempdir', lambda: str(tmp_path))
    monkeypatch.setattr(module, '_cache_readiness', lambda: {
        'status': 'ready', 'missing_models': [], 'model_cache': {'status': 'ready', 'source': 'fixture'}})


def completed_worker(monkeypatch, result=None):
    result = evidence() if result is None else result
    worker = Mock(return_value=(copy.deepcopy(result), worker_metric()))
    monkeypatch.setattr('ocr_runtime.run_worker', worker)
    return worker


def test_text_only_native_rgb_source_and_budget_are_preserved(monkeypatch):
    raw = png(picture()); expected = decode_document_image(raw)
    seen = {}

    def run(stage, image_path, output_path, **kwargs):
        seen.update(stage=stage, kwargs=kwargs)
        with Image.open(image_path) as image:
            assert image.mode == 'RGB' and image.size == expected.size
            assert image.tobytes() == expected.tobytes()
            assert image.getpixel((299, 199)) == (255, 255, 255)
        assert json.loads(Path(kwargs['layout_path']).read_text())['regions'] == []
        return evidence(), worker_metric()

    monkeypatch.setattr('ocr_runtime.run_worker', run)
    result = prepare_semantic_text(raw, budget=Budget())
    assert seen['stage'] == 'text' and 0 < seen['kwargs']['timeout'] < 18
    assert not result['images']
    assert result['diagnostics']['model_executed_this_call']
    assert result['resource_metrics'][0]['formula_enabled'] is False
    assert result['resource_metrics'][0]['worker_started']
    assert result['tool_audit'][0]['tool'] == 'image.semantic_text'
    assert result['tool_audit'][0]['status'] == 'success'
    assert result['tool_audit'][0]['source_sha256'] == hashlib.sha256(raw).hexdigest()
    assert '第三问' not in json.dumps(result['tool_audit'], ensure_ascii=False)


def test_keeps_body_label_weight_and_enhanced_alternative_without_certifying(monkeypatch):
    completed_worker(monkeypatch)
    result = prepare_semantic_text(png(picture()), budget=Budget())
    hints = result['text_hints']
    assert [h['text'] for h in hints] == ['第三问 v₅', 'e₇', '−5', 'v₃', '(a)']
    assert [h['role_hint'] for h in hints] == ['body', 'graph_label', 'graph_label', 'uncertain', 'noise_or_caption']
    assert all(h['status'] == 'candidate' and h['authoritative'] is False for h in hints)
    assert hints[0]['bbox'] == [33.33333, 50., 500., 150.]
    assert hints[3]['ocr_provenance']['pass_kind'] == 'enhanced'
    assert result['text_evidence']['body'][0]['box'] == [10., 10., 150., 30.]
    assert result['text_evidence']['coordinate_space'] == 'canonical_image_pixels'
    assert result['diagnostics']['ocr_is_not_transcription_or_topology_truth']
    json.dumps(result, allow_nan=False)


def test_passes_only_verified_layout_predictions_and_keeps_all_text_partitions(monkeypatch):
    layout = {'layout': {'status': 'ok', 'model': 'PP-DocLayoutV3', 'regions': [
        {'id': 'r1', 'bbox': [.2, .3, .9, .8], 'role': 'figure', 'score': .95},
        {'id': 'bad', 'bbox': [0, 0, 1000, 1000], 'role': 'figure', 'score': .95}]}}
    saved = copy.deepcopy(layout)
    seen = {}
    def run(*args, **kwargs):
        seen.update(json.loads(Path(kwargs['layout_path']).read_text()))
        return evidence(), worker_metric()
    monkeypatch.setattr('ocr_runtime.run_worker', run)
    result = prepare_semantic_text(png(picture()), budget=Budget(), layout=layout)
    assert layout == saved and [r['id'] for r in seen['regions']] == ['r1']
    assert result['diagnostics']['layout_regions_used'] == 1
    assert len(result['text_hints']) == 5


def test_reuses_completed_same_source_result_without_claiming_execution(monkeypatch):
    raw = png(picture()); previous = evidence()
    previous.update(source_sha256=hashlib.sha256(raw).hexdigest(), resource_metrics=[worker_metric()])
    saved = copy.deepcopy(previous)
    worker = completed_worker(monkeypatch)
    result = prepare_semantic_text(raw, budget=Budget(), text_result=previous)
    worker.assert_not_called()
    assert previous == saved
    assert result['diagnostics']['previous_result_reused']
    assert not result['diagnostics']['model_executed_this_call']
    assert result['diagnostics']['reuse_source_binding'] == 'source_sha256'
    assert not result['resource_metrics'][0]['worker_started']


def test_legacy_reuse_explicitly_reports_caller_owned_dimensions_binding(monkeypatch):
    previous = evidence(); previous['resource_metrics'] = [worker_metric()]
    worker = completed_worker(monkeypatch)
    result = prepare_semantic_text(png(picture()), budget=Budget(), text_result=previous)
    worker.assert_not_called()
    assert result['diagnostics']['reuse_source_binding'] == 'caller_owned_same_dimensions'


@pytest.mark.parametrize('problem', ['no_audit', 'source_mismatch', 'wrong_size', 'incomplete'])
def test_unproved_or_wrong_image_received_text_does_not_skip_real_worker(monkeypatch, problem):
    previous = evidence(); previous['resource_metrics'] = [worker_metric()]
    if problem == 'no_audit': previous['resource_metrics'] = []
    if problem == 'source_mismatch': previous['source_sha256'] = '0'*64
    if problem == 'wrong_size': previous['text_evidence']['image_size'] = [600, 400]
    if problem == 'incomplete': previous['resource_metrics'][0]['audit']['current']['phase'] = 'text_rec'
    worker = completed_worker(monkeypatch)
    result = prepare_semantic_text(png(picture()), budget=Budget(), text_result=previous)
    assert worker.call_count == 1 and result['diagnostics']['model_executed_this_call']
    assert not result['diagnostics']['previous_result_reused']


@pytest.mark.parametrize('status,started', [('memory_admission_rejected', False), ('cache_unavailable', False),
                                         ('timeout', True), ('memory_limit', True), ('worker_failed', True)])
def test_worker_failure_keeps_audit_and_original_reading_fallback(monkeypatch, status, started):
    metric = {'stage': 'text', 'status': status}
    if started: metric['phase_peaks'] = [{'phase': 'text_init', 'samples': 1}]
    monkeypatch.setattr('ocr_runtime.run_worker', lambda *a, **k: (None, metric))
    result = prepare_semantic_text(png(picture()), budget=Budget())
    assert not result['text_hints'] and result['diagnostics']['fallback'] == 'original_image'
    assert result['diagnostics']['reason'] == status
    assert result['resource_metrics'][0]['worker_started'] is started
    assert not result['diagnostics']['model_executed_this_call']


def test_missing_models_never_start_download_or_worker(monkeypatch):
    monkeypatch.setattr(module, '_cache_readiness', lambda: {
        'status': 'model_cache_missing', 'missing_models': ['PP-OCRv6_small_rec'], 'worker_started': False})
    worker = completed_worker(monkeypatch)
    result = prepare_semantic_text(png(picture()), budget=Budget())
    worker.assert_not_called()
    assert result['diagnostics']['reason'] == 'model_cache_missing'
    assert result['resource_metrics'][0]['missing_models'] == ['PP-OCRv6_small_rec']


def test_cache_preflight_uses_existing_files_without_environment_mutation(monkeypatch, tmp_path):
    env_before = dict(module.os.environ)
    monkeypatch.setattr(module.importlib.util, 'find_spec', lambda name: object())
    def cache(env):
        env['PADDLE_PDX_CACHE_HOME'] = str(tmp_path/'cache')
        return {'status': 'ready', 'source': 'fixture'}
    monkeypatch.setattr('ocr_runtime.configure_model_cache', cache)
    first = REAL_CACHE_READINESS()
    assert first['status'] == 'model_cache_missing' and len(first['missing_models']) == 2
    for name in module.MODEL_NAMES:
        root = tmp_path/'cache'/'official_models'/name; root.mkdir(parents=True)
        for suffix in ('json', 'pdiparams', 'yml'): (root/f'inference.{suffix}').write_bytes(b'x')
    assert REAL_CACHE_READINESS()['status'] == 'ready'
    assert dict(module.os.environ) == env_before


def test_busy_shared_lock_is_nonblocking(monkeypatch, tmp_path):
    worker = completed_worker(monkeypatch)
    with (tmp_path/'dmate-local-model.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = prepare_semantic_text(png(picture()), budget=Budget())
    worker.assert_not_called()
    assert result['diagnostics']['reason'] == 'busy'
    assert not result['resource_metrics'][0]['worker_started']


def test_short_shared_budget_reserves_following_work(monkeypatch):
    worker = completed_worker(monkeypatch)
    result = prepare_semantic_text(png(picture()), budget=Budget(seconds=2.5))
    worker.assert_not_called()
    assert result['diagnostics']['reason'] == 'deadline_reserved'


def test_invalid_worker_coordinates_do_not_become_original_1000(monkeypatch):
    bad = evidence(); bad['text_evidence']['image_size'] = [600, 400]
    completed_worker(monkeypatch, bad)
    result = prepare_semantic_text(png(picture()), budget=Budget())
    assert result['diagnostics']['reason'] == 'invalid_worker_output'
    assert result['text_hints'] == [] and not result['diagnostics']['model_executed_this_call']


def test_bad_auxiliary_boxes_and_scores_remain_unlocated_text_suggestions(monkeypatch):
    items = evidence()
    items['text_evidence']['body'][0]['box'] = [0, 0, float('nan'), 2]
    items['text_evidence']['body'][0]['score'] = float('inf')
    completed_worker(monkeypatch, items)
    result = prepare_semantic_text(png(picture()), budget=Budget())
    assert result['text_hints'][0]['text'] == '第三问 v₅'
    assert result['text_hints'][0]['bbox'] is None and result['text_hints'][0]['confidence'] is None
    assert len(result['regions']) == 4
    assert result['diagnostics']['limits']['unlocated_items'] == 1
    json.dumps(result, allow_nan=False)


def test_hint_capacity_is_visible_not_silent_complete(monkeypatch):
    items = evidence(); items['text_evidence']['body'] *= 300
    completed_worker(monkeypatch, items)
    result = prepare_semantic_text(png(picture()), budget=Budget())
    assert len(result['text_hints']) == 256
    assert result['diagnostics']['limits']['capacity_omitted_items'] == 48
    assert 'complete' not in result


def test_document_reuse_does_not_decode_again_or_mutate_source(monkeypatch):
    raw = png(picture()); document = analyze_document(raw)
    before = document.original.tobytes()
    completed_worker(monkeypatch)
    monkeypatch.setattr(module, 'decode_document_image', lambda raw: pytest.fail('unnecessary decode'))
    result = prepare_semantic_text(raw, budget=Budget(), document=document)
    assert document.original.tobytes() == before and result['diagnostics']['document_reused']


def test_cancellation_after_worker_propagates_and_releases_lock(monkeypatch, tmp_path):
    class Cancelled(Exception): pass
    budget = Budget(); cancelled = [False]
    def check():
        if cancelled[0]: raise Cancelled()
    budget.check = check
    def worker(*a, **k):
        cancelled[0] = True
        return evidence(), worker_metric()
    monkeypatch.setattr('ocr_runtime.run_worker', worker)
    with pytest.raises(Cancelled): prepare_semantic_text(png(picture()), budget=budget)
    with (tmp_path/'dmate-local-model.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_source_mismatch_rejected_before_local_worker(monkeypatch):
    worker = completed_worker(monkeypatch)
    budget = Budget(); budget.source_sha256 = '0'*64
    with pytest.raises(ValueError, match='text_source_identity_mismatch'):
        prepare_semantic_text(png(picture()), budget=budget)
    worker.assert_not_called()
