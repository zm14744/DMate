"""Trusted local measurements must cross the strict JSON tool boundary."""
import copy
import hashlib
import math
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from PIL import Image

from dmate_tool_registry import MAX_JSON_BYTES, _json_bytes
from graph_agent_plugins import build_image_tools
from graph_evidence_pipeline import _proposal_json, collect_candidates
from image_evidence import analyze_document


def graph_inventory():
    return {'id': 'G1', 'name': 'G1', 'bbox': [0., 0., 1., 1.],
            'vertices': [{'id': 'a', 'label': 'a', 'x': .2, 'y': .5},
                         {'id': 'b', 'label': 'b', 'x': .8, 'y': .5}],
            'edges': [], 'directed': False, 'weighted': False, 'multigraph': True,
            'node_complete': True}


def registry_for(document):
    budget = SimpleNamespace(source_sha256=hashlib.sha256(document.original.tobytes()).hexdigest(),
                             deadline=time.monotonic()+30)
    return build_image_tools(document, {}, [], budget)


def traced_row(value):
    return {'id': 'px_1', 'from': 'a', 'to': 'b', 'style': 'solid',
            'path': [[.2, .5], [.4, .2], [.6, .2], [.8, .5]],
            'connector_evidence': {'kind': 'stroke_chain', 'curve_fit': {
                'initial_bend_pixels': value, 'fitted_bend_pixels': -51.,
                'ridge_coverage': .8, 'fit_cost': .1, 'trial_cap': 9}},
            'pixel_evidence': {'coverage': .7797, 'supported': False,
                               'reasons': ['insufficient_original_stroke_support']}}


def invoke_stub(monkeypatch, row):
    document = analyze_document(Image.new('RGB', (120, 80), 'white'))
    candidates = {'G1': [row]}
    monkeypatch.setattr('graph_evidence_pipeline.collect_candidates',
                        lambda document, graphs: (candidates, []))
    registry, context = registry_for(document)
    result = registry.call('image.trace_candidates', {'graphs': [graph_inventory()]},
                           role='connections', context=context)
    return result, context


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.float64])
def test_trace_normalizes_finite_fit_scalar_without_changing_path_or_support(monkeypatch, dtype):
    row = traced_row(dtype(-50.724))
    snapshot = copy.deepcopy(row)
    with pytest.raises(ValueError, match='non_json_value'):
        _json_bytes({'G1': [row]})
    result, context = invoke_stub(monkeypatch, row)
    assert result['ok'], result
    candidate = result['result']['candidates']['G1'][0]
    value = candidate['connector_evidence']['curve_fit']['initial_bend_pixels']
    assert type(value) is float and value == float(snapshot['connector_evidence']['curve_fit']['initial_bend_pixels'])
    assert candidate['path'] == snapshot['path']
    assert candidate['pixel_evidence'] == snapshot['pixel_evidence']
    assert candidate['pixel_evidence']['supported'] is False
    assert row == snapshot and type(row['connector_evidence']['curve_fit']['initial_bend_pixels']) is dtype
    assert result['audit']['status'] == 'success' and result['audit']['result_digest']
    assert result['audit']['source_sha256'] == context.source_sha256
    assert result['version'] == '2026-10-26-v3'


@pytest.mark.parametrize('value', [np.float64('nan'), np.float64('inf'), np.float64('-inf'),
                                 np.asarray([-50.724]), object()])
def test_trace_does_not_serialize_nonfinite_arrays_or_arbitrary_objects(monkeypatch, value):
    result, _ = invoke_stub(monkeypatch, traced_row(value))
    assert not result['ok'] and result['error']['code'] == 'invalid_output'
    assert result['result'] is None and result['audit']['result_digest'] is None


def test_trace_keeps_unknown_numeric_fields_subject_to_strict_registry(monkeypatch):
    row = traced_row(np.float64(-50.724))
    row['pixel_evidence']['coverage'] = np.float64(.7797)
    result, _ = invoke_stub(monkeypatch, row)
    assert not result['ok'] and result['error']['code'] == 'invalid_output'


def test_trace_normalization_cannot_bypass_result_capacity(monkeypatch):
    row = traced_row(np.float64(-50.724))
    row['extra'] = 'x'*(MAX_JSON_BYTES+1)
    result, _ = invoke_stub(monkeypatch, row)
    assert not result['ok'] and result['error']['code'] == 'result_capacity_exceeded'


def test_real_curved_parallel_paths_reach_model_proposal_through_registry():
    # Two distinct thin arcs, deliberately between the coarse amplitude grid.
    # Pixels and vertex inventory are synthetic; no model or private gold data.
    image = np.full((440, 620, 3), 255, np.uint8)
    axis = np.asarray([math.cos(math.radians(27)), math.sin(math.radians(27))])
    normal = np.asarray([-axis[1], axis[0]])
    centre = np.asarray([310., 220.])
    a, b = centre-axis*190, centre+axis*190
    t = np.linspace(0, 1, 401)
    amplitude = .045*380+5*7+3.2
    for sign in (-1, 1):
        points = a+t[:, None]*(b-a)+normal[None, :]*sign*amplitude*(4*t*(1-t))[:, None]
        cv2.polylines(image, [np.rint(points).astype(np.int32)], False, (0, 0, 0), 1, cv2.LINE_AA)
    for point in (a, b):
        cv2.circle(image, tuple(np.rint(point).astype(int)), 7, (0, 0, 0), -1)
    document = analyze_document(Image.fromarray(image))
    graph = graph_inventory()
    graph['vertices'] = [{'id': name, 'label': name, 'x': float(point[0]/619), 'y': float(point[1]/439)}
                         for name, point in (('a', a), ('b', b))]
    raw, _ = collect_candidates(document, [copy.deepcopy(graph)])
    raw_arcs = [row for row in raw['G1'] if row.get('connector_evidence', {}).get('curve_fit')]
    assert len(raw_arcs) == 2, 'Both independent ink corridors must survive.'
    with pytest.raises(ValueError, match='non_json_value'):
        _json_bytes(raw)
    registry, context = registry_for(document)
    result = registry.call('image.trace_candidates', {'graphs': [graph]},
                           role='connections', context=context)
    assert result['ok'], result
    rows = result['result']['candidates']['G1']
    for original in raw_arcs:
        returned = next(row for row in rows if row['id'] == original['id'])
        assert returned['path'] == original['path']
        assert returned['pixel_evidence'] == original['pixel_evidence']
    proposal = _proposal_json(result['result']['graphs'][0], rows)
    prompt_arcs = [row for row in proposal['candidates'] if row['id'] in {r['id'] for r in raw_arcs}]
    assert len(prompt_arcs) == 2 and all(len(row['path']) > 2 for row in prompt_arcs)
    assert prompt_arcs[0]['path'] != prompt_arcs[1]['path']
    _json_bytes(proposal)


@pytest.mark.parametrize('role', ['body_text', 'connections', 'structure_review'])
def test_focused_tool_uses_context_hints_and_preserves_existing_image_refs(role):
    document = analyze_document(Image.new('RGB', (300, 180), 'white'))
    registry, context = registry_for(document)
    context.data['hints'] = {'items': [{'id': 't1', 'bbox': [100, 600, 900, 700]}]}
    previous = {f'active_ref_{i}': Image.new('RGB', (2, 2), (i, 0, 0)) for i in range(8)}
    context.data['images'].update(previous)
    arguments = {'graphs': [], 'issues': [{'id': 'i1', 'hint_ids': ['t1']}]}
    result = registry.call('image.focused_views', arguments, role=role, context=context)
    assert result['ok'], result
    value = result['result']
    assert len(value['image_refs']) == 1 and value['focused_views'][0]['hint_ids'] == ['t1']
    assert value['source_sha256'] == context.source_sha256 and value['source_pixels_only'] is True
    assert value['image_refs'][0] in context.data['images']
    assert value['focused_views'][0]['image_ref'] == value['image_refs'][0]
    assert result['version'] == '2026-10-26-v4' and result['audit']['result_digest']
    for ref, image in previous.items():
        assert context.data['images'][ref] is image
    # The existing review sheet must also leave concurrent body/focus refs alive.
    reviewed = registry.call('image.review_views', {'graphs': []}, role=role, context=context)
    assert reviewed['ok'], reviewed
    for ref, image in previous.items():
        assert context.data['images'][ref] is image
    assert value['image_refs'][0] in context.data['images']


@pytest.mark.parametrize('role', ['page_vertices', 'attributes', 'solver'])
def test_focused_tool_denies_roles_without_crop_authority(role):
    registry, context = registry_for(analyze_document(Image.new('RGB', (80, 60), 'white')))
    result = registry.call('image.focused_views', {'graphs': [], 'issues': []}, role=role, context=context)
    assert not result['ok'] and result['error']['code'] == 'role_not_allowed'
    assert not context.data['images']


def test_focused_tool_cannot_accept_caller_supplied_hint_boxes():
    registry, context = registry_for(analyze_document(Image.new('RGB', (80, 60), 'white')))
    result = registry.call('image.focused_views', {'graphs': [], 'issues': [],
        'hints': {'items': [{'id': 'forged', 'bbox': [0, 0, 1000, 1000]}]}},
        role='connections', context=context)
    assert not result['ok'] and result['error']['code'] == 'invalid_arguments'
    assert not context.data['images']


def test_focused_tool_reports_no_views_for_unlocated_issue():
    registry, context = registry_for(analyze_document(Image.new('RGB', (80, 60), 'white')))
    result = registry.call('image.focused_views', {'graphs': [], 'issues': [
        {'id': 'i1', 'hint_ids': ['missing'], 'evidence': {'bbox': [0, 0, 1000, 1000]}}]},
        role='body_text', context=context)
    assert result['ok'], result
    assert result['result']['image_refs'] == [] and result['result']['focused_views'] == []
    assert result['result']['diagnostics']['omitted_count'] == 1


def test_focused_tool_rejects_issue_capacity_before_generating_images():
    registry, context = registry_for(analyze_document(Image.new('RGB', (80, 60), 'white')))
    result = registry.call('image.focused_views', {'graphs': [], 'issues': [
        {'id': f'i{i}', 'hint_ids': []} for i in range(129)]}, role='body_text', context=context)
    assert not result['ok'] and result['error']['code'] == 'invalid_arguments'
    assert not context.data['images']
