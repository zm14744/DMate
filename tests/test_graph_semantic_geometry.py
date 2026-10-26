"""Actual CPU-tool and advisory contracts; these are not model accuracy tests."""
import copy
import hashlib
import io
import json
import time

from PIL import Image, ImageDraw
import pytest

import graph_semantic_geometry as geometry


class Budget:
    def __init__(self, seconds=60):
        self.deadline = time.monotonic() + seconds
        self.error = None

    def check(self):
        if self.error is not None:
            error, self.error = self.error, None
            raise error
        if time.monotonic() >= self.deadline:
            raise TimeoutError('task_deadline')


def picture(*, parallel=False, loop=False, alpha=False):
    image = Image.new('RGBA' if alpha else 'RGB', (320, 220),
                      (255, 255, 255, 0) if alpha else 'white')
    draw = ImageDraw.Draw(image)
    draw.line((40, 110, 280, 110), fill='blue', width=3)
    if parallel:
        draw.line([(x, round(110 - .004 * (x - 40) * (280 - x))) for x in range(40, 281)],
                  fill='red', width=3)
    if loop:
        draw.ellipse((40, 110, 140, 200), outline='green', width=3)
    for x in (40, 280):
        draw.ellipse((x - 7, 103, x + 7, 117), fill='black')
    stream = io.BytesIO()
    image.save(stream, 'PNG')
    draft = {'body_text': 'Original body α', 'graphs': [{'id': 'g', 'name': 'G',
        'bbox': [0, 0, 1000, 1000], 'vertices': [
            {'id': 'a', 'label': 'a₁', 'position': [40 / 319 * 1000, 110 / 219 * 1000]},
            {'id': 'b', 'label': 'B', 'position': [280 / 319 * 1000, 110 / 219 * 1000]}],
        'edges': [{'id': 'already', 'from': 'a', 'to': 'b', 'direction': 'unknown',
                   'color': 'violet', 'weight': 0, 'edge_label': 'r₂', 'style': 'dashed'}]}]}
    return stream.getvalue(), draft


def public_json(result):
    return json.dumps({k: v for k, v in result.items() if k != 'document'}, allow_nan=False)


def test_before_inventory_really_measures_opencv_markers_without_inventing_graphs(monkeypatch):
    import cv2
    import graph_sknw_plugin
    calls = []
    real = cv2.connectedComponentsWithStats
    def observe(*args, **kwargs):
        calls.append(True)
        return real(*args, **kwargs)
    monkeypatch.setattr(cv2, 'connectedComponentsWithStats', observe)
    monkeypatch.setattr(graph_sknw_plugin, 'suggest_candidates', lambda *a, **k: pytest.fail('pre-inventory sknw'))
    raw, _ = picture(alpha=True)
    result = geometry.prepare_semantic_geometry(raw, budget=Budget())
    assert calls and len(result['marker_candidates']) >= 2
    assert result['graphs'] == []
    assert result['document'].original.getpixel((0, 0)) == (255, 255, 255)
    assert result['source_sha256'] == hashlib.sha256(raw).hexdigest()
    assert result['tool_audit'][0]['executed'] is True
    assert all(x['mathematical_panel_confirmed'] is False for x in result['region_candidates'])
    assert 'data:image' not in public_json(result)


def test_real_bounded_opencv_and_sknw_preserve_parallel_instances_and_source_colors():
    pytest.importorskip('sknw')
    raw, draft = picture(parallel=True)
    before = copy.deepcopy(draft)
    budget = Budget()
    first = geometry.prepare_semantic_geometry(raw, budget=budget)
    result = geometry.prepare_semantic_geometry(raw, draft=draft, document=first['document'], budget=budget)
    assert draft == before
    audits = {a['tool']: a for a in result['tool_audit']}
    for tool in ('image.semantic_opencv', 'image.semantic_sknw'):
        assert audits[tool]['executed'] is True, result['diagnostics']
        assert audits[tool]['candidate_count'] >= 2, result['diagnostics']
    rows = result['graphs'][0]['candidates']
    assert len({r['instance_id'] for r in rows}) == len(rows)
    sknw = [r for r in rows if r['source'] == 'sknw']
    assert len(sknw) >= 2
    assert all({r['from'], r['to']} == {'a', 'b'} for r in sknw)
    assert all('weight' not in r and 'direction' not in r for r in rows)
    colors = [c['rgb'] for r in rows for c in r['color_measurement'].get('colors', [])]
    assert any(b > r + 100 for r, g, b in colors)
    assert any(r > b + 100 for r, g, b in colors)
    assert all(len(r['path_hint']) <= 24 for r in rows)
    assert all(a['original_pixel_path'] for a in result['candidate_audit'])
    assert result['diagnostics'][-1]['mathematical_edges_certified'] is False
    public_json(result)


def test_no_coordinate_and_unlabelled_marker_never_creates_math_identity(monkeypatch):
    raw, draft = picture()
    for v in draft['graphs'][0]['vertices']:
        v.pop('position')
    first = geometry.prepare_semantic_geometry(raw, budget=Budget())
    tools, associations, issues = geometry._tool_graphs(draft, first['document']._semantic_geometry_cache['pool'],
                                                       first['document'], None)
    assert tools and all(v['id'].startswith('marker_') for v in tools[0]['vertices'])
    assert all(a['vertex_id'] is None for a in associations['g'].values())
    assert any(i['code'] == 'vertices_without_unique_marker_association' for i in issues)


def test_capacity_or_ambiguous_markers_never_supply_false_unique_mapping():
    raw, draft = picture()
    first = geometry.prepare_semantic_geometry(raw, budget=Budget())
    document = first['document']
    pool = copy.deepcopy(document._semantic_geometry_cache['pool'])
    pool['limits']['marker_limit_reached'] = True
    _, associations, issues = geometry._tool_graphs(draft, pool, document, None)
    assert all(a['vertex_id'] is None for a in associations['g'].values())
    assert any(i['code'] == 'marker_pool_incomplete_no_unique_association' for i in issues)
    pool['limits']['marker_limit_reached'] = False
    draft['graphs'][0]['vertices'].append({'id': 'c', 'position': draft['graphs'][0]['vertices'][0]['position']})
    _, associations, _ = geometry._tool_graphs(draft, pool, document, None)
    assert not any(a['vertex_id'] in ('a', 'c') for a in associations['g'].values())


def test_projection_retains_loop_parallel_and_per_instance_arrow_without_pair_dedup():
    raw, _ = picture()
    document = geometry.prepare_semantic_geometry(raw, budget=Budget())['document']
    a = {'vertex_id': 'a', 'marker_id': 'm1', 'position': [100, 500]}
    b = {'vertex_id': 'b', 'marker_id': 'm2', 'position': [900, 500]}
    rows = [{'id': 'one', 'from': 'm1', 'to': 'm2', 'path': [[.1, .5], [.5, .3], [.9, .5]],
             'arrow_hint': {'from': 'm1', 'to': 'm2', 'score': .8, 'method': 'measured'}},
            {'id': 'two', 'from': 'm1', 'to': 'm2', 'path': [[.1, .5], [.5, .7], [.9, .5]],
             'arrow_hint': {'from': 'm2', 'to': 'm1', 'score': .7, 'method': 'measured'}},
            {'id': 'loop', 'from': 'm1', 'to': 'm1', 'path': [[.1, .5], [.2, .3], [.3, .5], [.1, .5]]}]
    graphs, audit, count = geometry._project(document, [('opencv', {'g': rows})], {'g': {'m1': a, 'm2': b}})
    assert count == 3 and len(audit) == 3
    result = graphs[0]['candidates']
    assert result[0]['arrow_measurement']['from'] == 'a'
    assert result[1]['arrow_measurement']['from'] == 'b'
    assert result[2]['from'] == result[2]['to'] == 'a' and 'arrow_measurement' not in result[2]
    assert all('direction' not in r for r in result)


def test_tool_failure_is_explicit_and_keeps_draft_and_original(monkeypatch):
    import graph_sknw_plugin
    raw, draft = picture()
    before = copy.deepcopy(draft)
    first = geometry.prepare_semantic_geometry(raw, budget=Budget())
    def fail(*args, **kwargs):
        raise OSError('private_path_or_content')
    monkeypatch.setattr(geometry, '_trace_opencv', fail)
    monkeypatch.setattr(graph_sknw_plugin, 'suggest_candidates', lambda *a, **kw: (
        {}, [{'code': 'dependency_missing', 'status': 'failed'}]))
    result = geometry.prepare_semantic_geometry(raw, draft=draft, document=first['document'], budget=Budget())
    assert draft == before and result['document'] is first['document']
    assert all(not r['candidates'] for r in result['graphs'])
    assert all(a['status'] == 'failed' and not a['executed'] for a in result['tool_audit'][1:])
    assert 'private_path_or_content' not in public_json(result)


def test_cancel_before_start_and_during_worker_never_becomes_fallback(monkeypatch):
    raw, draft = picture()
    first = geometry.prepare_semantic_geometry(raw, budget=Budget())
    budget = Budget()
    error = RuntimeError('cancelled-once')
    budget.error = error
    with pytest.raises(RuntimeError) as caught:
        geometry.prepare_semantic_geometry(raw, budget=budget)
    assert caught.value is error
    def cancelled(*a, **kw):
        budget.error = error
        geometry._worker_checkpoint(budget)
    monkeypatch.setattr(geometry, '_trace_opencv', cancelled)
    with pytest.raises(RuntimeError) as caught:
        geometry.prepare_semantic_geometry(raw, draft=draft, document=first['document'], budget=budget)
    assert caught.value is error


def test_cached_document_cannot_be_borrowed_for_other_bytes():
    raw, _ = picture()
    document = geometry.prepare_semantic_geometry(raw, budget=Budget())['document']
    other, _ = picture(parallel=True)
    with pytest.raises(ValueError, match='source_mismatch'):
        geometry.prepare_semantic_geometry(other, budget=Budget(), document=document)
    budget = Budget()
    budget.source_sha256 = '0' * 64
    with pytest.raises(ValueError, match='source_identity'):
        geometry.prepare_semantic_geometry(raw, budget=budget)


def test_multi_panel_missing_boxes_never_traces_whole_page_as_each_graph():
    raw, draft = picture()
    first = geometry.prepare_semantic_geometry(raw, budget=Budget())
    draft['graphs'] = [{'id': 'g1', 'vertices': [{'id': 'a'}]}, {'id': 'g2', 'vertices': [{'id': 'a'}]}]
    tools, mappings, issues = geometry._tool_graphs(draft, first['document']._semantic_geometry_cache['pool'],
                                                  first['document'], None)
    assert tools == [] and mappings == {}
    assert {i['graph_id'] for i in issues} == {'g1', 'g2'}


def test_prose_position_with_explicit_numeric_xy_remains_a_coarse_hint():
    raw, draft = picture()
    first = geometry.prepare_semantic_geometry(raw, budget=Budget())
    for vertex in draft['graphs'][0]['vertices']:
        vertex['x'], vertex['y'] = vertex['position']
        vertex['position'] = 'a visible corner, not a coordinate'
    _, associations, _ = geometry._tool_graphs(draft, first['document']._semantic_geometry_cache['pool'],
                                              first['document'], None)
    assert {a['vertex_id'] for a in associations['g'].values()} == {'a', 'b'}


def test_local_layout_is_used_for_roi_but_not_as_a_final_panel_inventory():
    raw, draft = picture()
    first = geometry.prepare_semantic_geometry(raw, budget=Budget())
    draft['graphs'][0].pop('bbox')
    layout = {'panels': [{'bbox': [0, 250, 1000, 750]}]}
    tools, _, _ = geometry._tool_graphs(draft, first['document']._semantic_geometry_cache['pool'],
                                       first['document'], layout)
    assert tools[0]['bbox'] == [0., .25, 1., .75]
    assert tools[0]['crop_source'] == 'local_layout_crop_hint'


def test_shared_physical_marker_cannot_be_called_a_unique_math_vertex_in_two_panels():
    raw, draft = picture()
    first = geometry.prepare_semantic_geometry(raw, budget=Budget())
    other = copy.deepcopy(draft['graphs'][0])
    other['id'] = 'other'
    draft['graphs'].append(other)
    _, associations, issues = geometry._tool_graphs(draft, first['document']._semantic_geometry_cache['pool'],
                                                  first['document'], None)
    assert all(endpoint['vertex_id'] is None for mapping in associations.values() for endpoint in mapping.values())
    assert any(i['code'] == 'marker_assigned_to_multiple_panel_hints' for i in issues)


def test_actual_opencv_deadline_does_not_claim_tracing_or_leave_locked_worker():
    import fcntl
    import tempfile
    from pathlib import Path
    raw, draft = picture()
    first = geometry.prepare_semantic_geometry(raw, budget=Budget())
    document = first['document']
    graphs, _, _ = geometry._tool_graphs(draft, document._semantic_geometry_cache['pool'], document, None)
    _, diagnostics = geometry._trace_opencv(document, graphs, deadline=time.monotonic() + .10, budget=Budget())
    assert any(d.get('code') == 'deadline_exceeded' and not d.get('executed') for d in diagnostics)
    with (Path(tempfile.gettempdir()) / 'dmate-local-model.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(handle, fcntl.LOCK_UN)


def test_missing_sknw_does_not_erase_available_opencv_observations(monkeypatch):
    import graph_sknw_plugin
    raw, draft = picture()
    first = geometry.prepare_semantic_geometry(raw, budget=Budget())
    document = first['document']
    graphs, _, _ = geometry._tool_graphs(draft, document._semantic_geometry_cache['pool'], document, None)
    nodes = graphs[0]['vertices']
    row = {'id': 'measured', 'from': nodes[0]['id'], 'to': nodes[1]['id'],
           'path': [[v['x'], v['y']] for v in nodes]}
    monkeypatch.setattr(geometry, '_trace_opencv', lambda *a, **kw: (
        {'g': [row]}, [{'code': 'roi_traced', 'status': 'ok'}]))
    monkeypatch.setattr(graph_sknw_plugin, 'suggest_candidates', lambda *a, **kw: (
        {}, [{'code': 'dependency_missing', 'status': 'failed'}]))
    result = geometry.prepare_semantic_geometry(raw, draft=draft, budget=Budget(), document=document)
    assert len(result['graphs'][0]['candidates']) == 1
    assert result['graphs'][0]['candidates'][0]['source'] == 'opencv'
    assert result['tool_audit'][-1]['status'] == 'failed'
