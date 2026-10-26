"""Synthetic source crops, real CV, isolated worker contract; never accuracy gold."""
import base64
import copy
import fcntl
import hashlib
import io
import json
from pathlib import Path
import time
from unittest.mock import Mock

import numpy as np
from PIL import Image, ImageDraw
import pytest
import requests

import graph_semantic_layout as module
from graph_semantic_layout import prepare_semantic_layout
from image_evidence import analyze_document, decode_document_image


class Budget:
    def __init__(self, seconds=30):
        self.deadline = time.monotonic()+seconds
        self.source_sha256 = None

    def check(self):
        if time.monotonic() >= self.deadline:
            raise TimeoutError('fixture_deadline')


def png(image):
    stream = io.BytesIO(); image.save(stream, format='PNG'); return stream.getvalue()


def picture(*, alpha=False):
    image = Image.new('RGBA' if alpha else 'RGB', (600, 400), (0, 0, 0, 0) if alpha else 'white')
    draw = ImageDraw.Draw(image)
    for box, color in [((40, 90, 230, 300), 'red'), ((360, 90, 550, 300), 'blue')]:
        draw.rectangle(box, outline=color, width=4)
        draw.line((box[0], box[1], box[2], box[3]), fill=color, width=4)
    draw.text((40, 25), 'READ THE ORIGINAL QUESTION', fill='black')
    return image


def model_layout():
    return {'model': 'PP-DocLayoutV3', 'status': 'ok', 'regions': [
        {'id': 'r1', 'bbox': [.04, .17, .42, .82], 'role': 'figure', 'label': 'image', 'score': .9},
        {'id': 'r2', 'bbox': [.56, .17, .96, .82], 'role': 'figure', 'label': 'image', 'score': .9},
        {'id': 'r3', 'bbox': [.04, .02, .70, .12], 'role': 'text', 'label': 'text', 'score': .8}]}


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(requests.sessions.Session, 'send', lambda *a, **k: pytest.fail('network forbidden'))
    monkeypatch.setattr('subprocess.Popen', lambda *a, **k: pytest.fail('unmocked model worker'))
    monkeypatch.setattr(module.tempfile, 'gettempdir', lambda: str(tmp_path))


def test_real_cv_runs_and_does_not_impersonate_layout_model(monkeypatch):
    raw = png(picture())
    connected = Mock(wraps=module.cv2.connectedComponentsWithStats)
    monkeypatch.setattr(module.cv2, 'connectedComponentsWithStats', connected)
    result = prepare_semantic_layout(raw, budget=Budget())
    assert connected.call_count >= 2 and result['diagnostics']['cv_executed']
    assert len(result['panels']) >= 2
    assert all(p['status'] == 'candidate' and p['coordinate_space'] == 'original_1000' for p in result['panels'])
    assert all(p['segmentation_is_not_graph_inventory'] for p in result['panels'])
    assert result['layout']['status'] == 'not_run'
    assert not result['diagnostics']['layout_model_executed_this_call']
    event = result['tool_audit'][0]
    assert event['tool'] == 'image.semantic_layout' and event['status'] == 'success'
    assert event['source_sha256'] == hashlib.sha256(raw).hexdigest()
    assert 'base64' not in json.dumps(event)


def test_all_crops_are_original_rgb_pixels_and_source_is_unchanged():
    raw = png(picture(alpha=True)); before = bytes(raw)
    original = decode_document_image(raw)
    result = prepare_semantic_layout(raw, budget=Budget())
    assert raw == before and 1 <= len(result['images']) <= 5
    assert result['view_metadata'][0]['original_pixel_bbox'] == [0, 0, 600, 400]
    for url, meta in zip(result['images'], result['view_metadata']):
        crop = original.crop(meta['original_pixel_bbox'])
        assert hashlib.sha256(crop.tobytes()).hexdigest() == meta['source_crop_pixel_sha256']
        image = Image.open(io.BytesIO(base64.b64decode(url.split(',', 1)[1]))).convert('RGB')
        expected = crop if image.size == crop.size else crop.resize(image.size,
            Image.Resampling.NEAREST if meta['resampling'] == 'nearest' else Image.Resampling.LANCZOS)
        assert np.array_equal(image, expected)
    assert original.getpixel((0, 0)) == (255, 255, 255)
    assert result['diagnostics']['output_pixels'] <= module.MAX_OUTPUT_PIXELS


def test_reuses_only_identified_completed_layout_and_still_executes_cv(monkeypatch):
    import ocr_runtime
    worker = Mock(); monkeypatch.setattr(ocr_runtime, 'run_worker', worker)
    layout = model_layout(); saved = copy.deepcopy(layout)
    result = prepare_semantic_layout(png(picture()), budget=Budget(), layout=layout, run_layout=True)
    worker.assert_not_called()
    assert layout == saved and result['layout']['source'] == 'reused_layout_result'
    assert result['diagnostics']['cv_executed'] and result['diagnostics']['layout_model_result_reused']
    assert not result['diagnostics']['layout_model_executed_this_call']
    assert result['body_regions']


def test_executes_only_layout_stage_with_bounded_worker_and_original_input(monkeypatch):
    import ocr_runtime
    calls = []
    def worker(stage, image_path, output_path, **kwargs):
        calls.append((stage, kwargs))
        with Image.open(image_path) as image:
            assert image.mode == 'RGB' and max(image.size) <= module.MAX_WORK_SIDE
        return model_layout(), {'stage': stage, 'status': 'ok', 'seconds': .01,
                                'peak_rss_bytes': 123, 'rss_observed': True}
    monkeypatch.setattr(ocr_runtime, 'run_worker', worker)
    result = prepare_semantic_layout(png(picture()), budget=Budget(), run_layout=True, layout_timeout=18)
    assert len(calls) == 1 and calls[0][0] == 'layout' and 0 < calls[0][1]['timeout'] <= 18
    assert 'layout_path' not in calls[0][1]
    assert result['layout']['status'] == 'ok'
    assert result['layout']['coordinate_space'] == 'original_normalized_0_1'
    assert result['diagnostics']['layout_model_executed_this_call']
    assert result['resource_metrics'][-1]['worker_started']


@pytest.mark.parametrize('status,started', [('cache_unavailable', False), ('memory_admission_rejected', False),
                                          ('timeout', True), ('memory_limit', True)])
def test_model_failure_keeps_cv_candidates_without_claiming_model_success(status, started, monkeypatch):
    import ocr_runtime
    metric = {'stage': 'layout', 'status': status, 'seconds': .01}
    if started:
        metric['phase_peaks'] = [{'phase': 'layout_init'}]
    monkeypatch.setattr(ocr_runtime, 'run_worker', lambda *a, **k: (None, metric))
    result = prepare_semantic_layout(png(picture()), budget=Budget(), run_layout=True)
    assert result['panels'] and result['diagnostics']['cv_executed']
    assert result['layout']['status'] == 'unavailable'
    assert not result['diagnostics']['layout_model_executed_this_call']
    assert result['resource_metrics'][-1]['worker_started'] is started


def test_nonblocking_shared_lock_does_not_boot_another_worker(monkeypatch, tmp_path):
    import ocr_runtime
    worker = Mock(); monkeypatch.setattr(ocr_runtime, 'run_worker', worker)
    with (tmp_path/'dmate-local-model.lock').open('a') as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = prepare_semantic_layout(png(picture()), budget=Budget(), run_layout=True)
    worker.assert_not_called()
    assert result['layout']['status'] == 'busy'
    assert result['resource_metrics'][-1]['worker_started'] is False
    assert result['panels']


def test_short_remaining_budget_skips_model_without_spending_final_read_time(monkeypatch):
    import ocr_runtime
    worker = Mock(); monkeypatch.setattr(ocr_runtime, 'run_worker', worker)
    result = prepare_semantic_layout(png(picture()), budget=Budget(seconds=2.5), run_layout=True)
    worker.assert_not_called()
    assert result['resource_metrics'][-1]['status'] == 'deadline_reserved'
    assert result['images'] and result['panels']


def test_invalid_layout_identity_is_not_reused_as_completed_model(monkeypatch):
    import ocr_runtime
    worker = Mock(return_value=(None, {'status': 'cache_unavailable'}))
    monkeypatch.setattr(ocr_runtime, 'run_worker', worker)
    invalid = model_layout(); invalid.pop('model')
    result = prepare_semantic_layout(png(picture()), budget=Budget(), layout=invalid, run_layout=True)
    assert worker.call_count == 1 and not result['diagnostics']['layout_model_result_reused']


def test_invalid_or_out_of_bounds_region_is_not_used_for_crop():
    layout = model_layout()
    layout['regions'] = [{'id': 'bad', 'bbox': [0, 0, 1000, 1000], 'role': 'figure'},
                         {'id': 'nan', 'bbox': [0, 0, float('nan'), 1], 'role': 'text'}]
    result = prepare_semantic_layout(png(picture()), budget=Budget(), layout=layout)
    assert not result['layout']['regions']
    assert not any('bad' in row.get('layout_region_ids', []) for row in result['panels'])


def test_single_connected_graph_keeps_isolated_marker_in_local_context():
    image = Image.new('RGB', (600, 400), 'white'); draw = ImageDraw.Draw(image)
    draw.rectangle((30, 60, 300, 340), outline='black', width=4)
    draw.ellipse((510, 180, 530, 200), fill='black')
    result = prepare_semantic_layout(png(image), budget=Budget())
    assert len(result['panels']) == 1
    assert result['panels'][0]['bbox'][0] == 0 and result['panels'][0]['bbox'][2] == 1000
    assert 'graphs' not in result and not result['diagnostics']['geometry_required']


def test_blank_or_unsegmented_page_retains_full_original():
    result = prepare_semantic_layout(png(Image.new('RGB', (300, 200), 'white')), budget=Budget())
    assert result['panels'] == [] and len(result['images']) == 1
    assert result['diagnostics']['status'] == 'fallback_original'
    assert result['diagnostics']['cv_executed'] and result['view_metadata'][0]['original_pixel_bbox'] == [0, 0, 300, 200]


def test_capacity_is_explicit_and_crops_do_not_exceed_five_views():
    image = Image.new('RGB', (1200, 900), 'white'); draw = ImageDraw.Draw(image)
    for row in range(3):
        for col in range(4):
            draw.rectangle((col*300+30, row*300+30, col*300+240, row*300+240), outline='black', width=4)
    result = prepare_semantic_layout(png(image), budget=Budget())
    assert len(result['panels']) > 4 and len(result['images']) == 5
    assert result['diagnostics']['omitted']['view_region_ids']
    assert result['diagnostics']['output_pixels'] <= module.MAX_OUTPUT_PIXELS


def test_wide_heading_band_does_not_displace_figure_crops():
    image = picture(); draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 599, 34), outline='black', width=3)
    result = prepare_semantic_layout(png(image), budget=Budget())
    assert len(result['panels']) == 2
    assert all(panel['bbox'][1] > 100 for panel in result['panels'])
    assert result['resource_metrics'][0]['wide_bands_deferred_to_text_candidates'] >= 1


def test_one_coarse_cv_envelope_does_not_swallow_distinct_layout_regions():
    panels = [{'bbox': [0, 0, 1000, 1000], 'source': 'opencv_projection_components',
               'status': 'candidate', 'segmentation_is_not_graph_inventory': True}]
    fused, _, omitted = module._fuse(panels, [], model_layout())
    assert len(fused) == 2 and all(p['source'] == 'pp_doclayout_v3_prediction' for p in fused)
    assert omitted['cv_container_boxes'] == [[0, 0, 1000, 1000]]


def test_document_reuse_avoids_reanalysis_and_does_not_mutate_layers(monkeypatch):
    raw = png(picture()); document = analyze_document(raw, max_work_side=800)
    before = document.ink_mask.copy(), document.original.tobytes()
    monkeypatch.setattr(module, 'analyze_document', lambda *a, **k: pytest.fail('no reanalysis'))
    result = prepare_semantic_layout(raw, budget=Budget(), document=document)
    assert result['diagnostics']['document_reused']
    assert np.array_equal(document.ink_mask, before[0]) and document.original.tobytes() == before[1]


def test_caller_cancellation_propagates_instead_of_being_a_successful_fallback():
    class Cancelled(RuntimeError):
        pass
    class CancelBudget(Budget):
        def check(self):
            raise Cancelled()
    with pytest.raises(Cancelled):
        prepare_semantic_layout(png(picture()), budget=CancelBudget())


def test_source_identity_mismatch_prevents_any_tool_or_model():
    budget = Budget(); budget.source_sha256 = '0'*64
    with pytest.raises(ValueError, match='source_identity'):
        prepare_semantic_layout(png(picture()), budget=budget, run_layout=True)
