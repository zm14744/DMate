"""Offline candidate contracts/fault injection; no real-image accuracy claims."""
import base64
import copy
import io
import json
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw

from graph_qwen_coordinates import (crop_bounds, decode_inventory, encode_point,
                                    point, scalar)
from graph_qwen_simple import decode_review, recognize_simple, review_job, select_crop
from graph_relation import recover_relations
from graph_staged import Budget
from vision_provider import VisionProvider


def inventory():
    return {'coordinate_space': 'original_1000', 'graphs': [{
        'id': 'G', 'name': 'G', 'bbox': [0, 0, 1000, 1000], 'node_complete': True,
        'directed': False, 'weighted': False, 'multigraph': True,
        'vertices': [{'id': 'a', 'label': 'a', 'x': 200, 'y': 500},
                     {'id': 'b', 'label': 'b', 'x': 800, 'y': 500}],
        'edges': [{'id': 'upper', 'from': 'a', 'to': 'b', 'direction': 'undirected',
                   'path': [[200, 500], [500, 200], [800, 500]], 'style': 'solid'},
                  {'id': 'lower', 'from': 'a', 'to': 'b', 'direction': 'undirected',
                   'path': [[200, 500], [500, 800], [800, 500]], 'style': 'solid'}]}]}


def picture(size=(400, 250)):
    image = Image.new('RGB', size, 'white')
    draw = ImageDraw.Draw(image)
    for y in (.2, .8):
        draw.line([(round(x*(size[0]-1)), round(v*(size[1]-1))) for x, v in
                   ((.2, .5), (.5, y), (.8, .5))], fill='black', width=3)
    out = io.BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


def test_inventory_retains_instance_ids_without_fake_reciprocal_evidence():
    source = inventory()
    saved = copy.deepcopy(source)
    g = decode_inventory(source)[0]
    assert source == saved
    assert [e['id'] for e in g['edges']] == ['upper', 'lower']
    assert g['vertices'][0]['x'] == .2 and g['edges'][0]['path'][1] == [.5, .2]
    assert all(e['parallel_count'] == 2 for e in g['edges'])
    assert all(len(e['evidence']) == 1 and e['evidence'][0]['source'] == 'qwen_image_read' for e in g['edges'])
    assert g['node_review']['observed_vertices'][0]['x'] == .2
    assert g['edges'][0]['evidence'][0]['observed_path'] == g['edges'][0]['path']


@pytest.mark.parametrize('bad', [True, -1, 1001, 10**500, float('nan'), float('inf'), '250', None])
def test_invalid_coordinates_are_rejected_without_clipping(bad):
    with pytest.raises(ValueError):
        scalar(bad)


@pytest.mark.parametrize('change', ['missing_space', 'array_root', 'duplicate_edge', 'invalid_endpoint'])
def test_bad_inventory_is_rejected_instead_of_repaired(change):
    value = inventory()
    if change == 'missing_space':
        value.pop('coordinate_space')
    elif change == 'array_root':
        value = value['graphs']
    elif change == 'duplicate_edge':
        value['graphs'][0]['edges'][1]['id'] = 'upper'
    else:
        value['graphs'][0]['edges'][0]['to'] = 'ghost'
    with pytest.raises(ValueError):
        decode_inventory(value)


def test_crop_coordinates_round_trip_including_exclusive_last_pixel():
    bounds = crop_bounds((123, 77, 635, 589), (2048, 1000))
    for p in (bounds[:2], bounds[2:], [.2, .3]):
        local = encode_point(p, bounds)
        restored = point(local, bounds)
        assert restored == pytest.approx(p, abs=1e-7)
    assert encode_point(bounds[2:], bounds) == [1000, 1000]
    with pytest.raises(ValueError):
        encode_point([.9, .9], bounds)


def test_weight_window_cannot_delete_or_reorient_a_partially_visible_edge():
    g = decode_inventory(inventory())[0]
    g['weighted'] = True
    g['edges'][0]['evidence'].append({'source': 'qwen_attribute_region', 'field': 'weight',
                                    'bbox': [.49, .49, .51, .51]})
    job = review_job(g, g['edges'], (400, 400, 600, 600), (1001, 1001))
    assert len(job['candidates']) == 1
    assert job['candidates'][0]['allowed_fields'] == ['weight', 'edge_label']
    assert len(job['candidates'][0]['weight_bbox']) == 4
    assert not job['full_inventory_in_crop']
    response = {'coordinate_space': 'crop_1000', 'graph_id': 'G',
                'decisions': [{'id': 'upper', 'visible': False}], 'additional_edges': []}
    with pytest.raises(ValueError, match='scope_violation'):
        decode_review(response, job, crop_bounds((400, 400, 600, 600), (1001, 1001)))
    response['decisions'] = [{'id': 'upper', 'weight': 7}]
    decisions, _, complete = decode_review(response, job, crop_bounds((400, 400, 600, 600), (1001, 1001)))
    assert decisions['upper']['weight'] == 7 and not complete


def test_located_weight_uses_native_local_window_instead_of_resizing_whole_panel():
    g = decode_inventory(inventory())[0]
    g['weighted'] = True
    g['edges'][0]['evidence'].append({'source': 'qwen_attribute_region', 'field': 'weight',
                                    'bbox': [.49, .49, .51, .51]})
    related = recover_relations(g, [])
    plan = select_crop((2400, 800), [g], [related])
    assert plan['target_id'] == 'upper' and plan['reason'] == 'weight'
    left, top, right, bottom = plan['rect']
    assert right-left == bottom-top == 512
    assert left < .5*2399 < right and top < .5*799 < bottom


def test_model_panel_box_does_not_certify_missing_outside_ink():
    g = decode_inventory(inventory())[0]
    g['bbox'] = [.1, .1, .9, .9]
    job = review_job(g, g['edges'], (100, 100, 901, 901), (1001, 1001))
    assert len(job['candidates']) == 2 and not job['full_inventory_in_crop']


def test_missing_weight_focus_cannot_rewrite_other_edges_or_remove_a_stroke():
    g=decode_inventory(inventory())[0]
    g['weighted']=True;g['edges'][1]['weight']=4
    job=review_job(g,g['edges'],(0,0,400,250),(400,250),focus_id='upper')
    assert job['review_mode']=='missing_weight' and len(job['candidates'])==1
    assert job['candidates'][0]['allowed_fields']==['weight','edge_label']
    assert not job['full_inventory_in_crop']
    response={'coordinate_space':'crop_1000','graph_id':'G',
              'decisions':[{'id':'upper','weight':2}], 'additional_edges':[]}
    decisions,_,complete=decode_review(response,job,[0,0,1,1])
    assert decisions['upper']['weight']==2 and not complete
    response['decisions'][0]['visible']=False
    with pytest.raises(ValueError,match='scope_violation'):
        decode_review(response,job,[0,0,1,1])


def test_two_call_candidate_keeps_parallel_identity_and_original_crop_pixels():
    seen = []
    raw = picture()
    def ask(prompt, images, budget):
        budget.take()
        seen.append(prompt)
        if len(seen) == 1:
            assert '"coordinate_space":"original_1000"' in prompt
            return inventory()
        crop = Image.open(io.BytesIO(base64.b64decode(images[1].split(',')[1])))
        assert crop.size == (400, 250)
        assert crop.tobytes() == Image.open(io.BytesIO(raw)).tobytes()
        job = json.loads(prompt[prompt.index('{"requests":'):])['requests'][0]
        assert job['full_inventory_in_crop']
        return {'coordinate_space': 'crop_1000', 'graph_id': 'G',
                'decisions': [{'id': e['id'], 'visible': True, 'direction': 'undirected',
                               'path': e['path']} for e in job['candidates']],
                'additional_edges': [], 'inventory_complete': True}
    with patch('graph_qwen_simple.refine_node_positions', side_effect=lambda im, g, **kw: g), patch(
            'graph_line_tracer.attach_line_evidence', return_value={}):
        result = recognize_simple(raw, provider=ask, budget=Budget(calls=7), audit=True)
    g = result['graphs'][0]
    assert len(seen) == 2 and result['calls_remaining'] == 0
    assert [e['id'] for e in g['edges']] == ['upper', 'lower']
    assert g['complete'] and all(e['status'] == 'accepted' for e in g['edges'])
    assert all(any(p['source'] == 'qwen_image_read' for p in e['evidence']) for e in g['edges'])
    assert all(not any(p['source'] == 'node_read' for p in e['evidence']) for e in g['edges'])


def test_single_call_failure_never_retries_and_optional_audit_survives():
    calls = []
    def fail(prompt, images, budget):
        calls.append(1)
        budget.take()
        raise RuntimeError('transport_failed')
    with pytest.raises(RuntimeError) as raised:
        recognize_simple(picture(), provider=fail, audit=True)
    assert len(calls) == 1
    assert raised.value.graph_stage_audit[0]['stage'] == 'INVENTORY.failed'


def test_local_failure_preserves_initial_edges_and_never_uses_a_third_call():
    calls = []
    def ask(prompt, images, budget):
        budget.take()
        calls.append(1)
        if len(calls) == 1:
            return inventory()
        return {'coordinate_space': 'original_1000'}  # Wrong local frame.
    with patch('graph_qwen_simple.refine_node_positions', side_effect=lambda im, g, **kw: g), patch(
            'graph_line_tracer.attach_line_evidence', return_value={}):
        result = recognize_simple(picture(), provider=ask)
    assert len(calls) == 2
    assert [e['id'] for e in result['graphs'][0]['edges']] == ['upper', 'lower']
    assert not result['graphs'][0]['complete']
    assert result['diagnostics'] == ['single_review_failed:ValueError']


def test_other_provider_or_retries_are_rejected_before_any_request():
    with pytest.raises(ValueError, match='fixed_provider'):
        recognize_simple(picture(), provider=VisionProvider('glm'))
    with pytest.raises(ValueError, match='fixed_provider'):
        recognize_simple(picture(), provider=VisionProvider('qwen', retries=1))


def test_one_remaining_slot_does_not_make_a_second_request():
    calls = []
    def ask(prompt, images, budget):
        budget.take()
        calls.append(1)
        return inventory()
    with patch('graph_qwen_simple.refine_node_positions', side_effect=lambda im, g, **kw: g), patch(
            'graph_line_tracer.attach_line_evidence', return_value={}):
        result = recognize_simple(picture(), provider=ask, budget=Budget(calls=1))
    assert len(calls) == 1 and result['calls_remaining'] == 0
    assert not result['graphs'][0]['complete']


def test_nearby_fake_node_is_flagged_without_deleting_or_relabelling():
    value = inventory()
    value['graphs'][0]['vertices'].append({'id': 'ghost', 'label': 'v10', 'x': 201, 'y': 500})
    calls = []
    def ask(prompt, images, budget):
        budget.take()
        calls.append(1)
        if len(calls) == 1:
            return value
        return {'coordinate_space': 'crop_1000', 'graph_id': 'G', 'decisions': [],
                'additional_edges': [], 'inventory_complete': True}
    with patch('graph_qwen_simple.refine_node_positions', side_effect=lambda im, g, **kw: g), patch(
            'graph_line_tracer.attach_line_evidence', return_value={}):
        result = recognize_simple(picture(), provider=ask)
    g = result['graphs'][0]
    assert len(g['vertices']) == 3 and g['vertices'][-1]['label'] == 'v10'
    assert not g['node_complete'] and not g['complete']
    assert 'nearby_vertex_markers:a:ghost' in result['diagnostics']


def test_direction_correction_changes_only_the_named_edge_instance():
    value = inventory()
    value['graphs'][0].update(directed=True, weighted=True)
    for e in value['graphs'][0]['edges']:
        e.update(direction='forward', weight=4)
    calls = []
    def ask(prompt, images, budget):
        budget.take()
        calls.append(1)
        if len(calls) == 1:
            return value
        return {'coordinate_space': 'crop_1000', 'graph_id': 'G', 'decisions': [
            {'id': 'upper', 'visible': True, 'direction': 'reverse', 'weight': 7},
            {'id': 'lower', 'visible': True, 'direction': 'forward', 'weight': 4}],
            'additional_edges': [], 'inventory_complete': True}
    with patch('graph_qwen_simple.refine_node_positions', side_effect=lambda im, g, **kw: g), patch(
            'graph_line_tracer.attach_line_evidence', return_value={}):
        result = recognize_simple(picture(), provider=ask)
    edges = result['graphs'][0]['edges']
    assert [(e['id'], e['from'], e['to'], e['weight']) for e in edges] == [
        ('upper', 'b', 'a', 7), ('lower', 'a', 'b', 4)]
    assert edges[0]['evidence'][0]['observed_from'] == 'a'


def test_actual_adapter_failure_retains_raw_audit_and_token_metrics_without_fallback(monkeypatch):
    from ocr_nextgen import recognize_graph_document
    monkeypatch.setattr('ai.API_KEY', 'offline-test-key')
    monkeypatch.setattr('ai.VISION_ENABLED', True)
    monkeypatch.setenv('DMATE_GRAPH_STAGE_AUDIT', '1')
    requests = []
    def transport(*args, **kwargs):
        requests.append(1)
        return 200, '', {'model': 'qwen3-vl-plus', 'usage': {'total_tokens': 7},
            'choices': [{'message': {'content': '[]'}, 'finish_reason': 'stop'}]}
    provider = VisionProvider('qwen', capture=True, transport=transport)
    with patch('ocr_nextgen.correct_text') as text, patch('ocr_nextgen.recognize_staged') as staged:
        result = recognize_graph_document(picture(), {}, vision_provider=provider,
                                          graph_pipeline='qwen-simple-candidate')
    assert len(requests) == 1 and result['error']
    text.assert_not_called()
    staged.assert_not_called()
    metric = result['diagnostics']['remote_metrics'][0]
    assert metric['output_error'] == 'root_not_object' and metric['usage']['total_tokens'] == 7
    observed = result['diagnostics']['stage_audit'][0]['observations'][0]
    assert observed['raw_content'] == '[]'
    assert 'offline-test-key' not in json.dumps(result)


def test_default_orchestration_does_not_select_candidate():
    from ocr_nextgen import recognize_graph_document
    with patch('ocr_nextgen.recognize_staged', side_effect=RuntimeError('offline')) as staged, patch(
            'graph_qwen_simple.recognize_simple') as candidate:
        result = recognize_graph_document(picture(), {})
    assert result['error'] and staged.call_count == 1
    candidate.assert_not_called()


def test_explicit_candidate_uses_unified_display_and_existing_text_correction():
    from ocr_nextgen import recognize_graph_document
    g = decode_inventory(inventory())[0]
    with patch('graph_qwen_simple.recognize_simple', return_value={
            'graphs': [g], 'diagnostics': [], 'remote_metrics': []}) as candidate, patch(
            'ocr_nextgen.recognize_staged') as staged, patch(
            'ocr_nextgen.correct_text', return_value=('unchanged text', {})) as text:
        result = recognize_graph_document(picture(), {'text': 'source'}, graph_pipeline='qwen-simple-candidate')
    assert candidate.call_count == 1
    staged.assert_not_called()
    text.assert_called_once_with('source')
    assert result['graph_display_version'] == 'qwen-simple-candidate-v4'
    assert [e['id'] for e in result['graph_display_data'][0]['edges']] == ['upper', 'lower']
    assert result['text'] == 'unchanged text'
