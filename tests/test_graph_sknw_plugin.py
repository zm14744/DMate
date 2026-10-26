"""Synthetic geometry and process-boundary tests, not OCR accuracy claims."""
import copy
import importlib.metadata
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw
import pytest

import graph_sknw_plugin as plugin
from image_evidence import analyze_document
from graph_line_tracer import prepare_skeleton_roi


def picture(points, *, size=(300, 200), hollow=False, radius=7, directed=False):
    image = Image.new('RGB', size, 'white')
    graph = {'id': 'panel', 'bbox': [0., 0., 1., 1.], 'directed': directed,
             'vertices': [{'id': name, 'label': name, 'x': x/(size[0]-1), 'y': y/(size[1]-1)}
                          for name, (x, y) in points.items()], 'edges': []}
    def markers():
        draw = ImageDraw.Draw(image)
        for x, y in points.values():
            draw.ellipse((x-radius, y-radius, x+radius, y+radius),
                         fill='white' if hollow else 'black', outline='black', width=3)
    return image, graph, markers


@pytest.fixture(scope='module')
def build_sknw():
    return pytest.importorskip('sknw').build_sknw


def execute(image, graphs, build_sknw, limit=160, side=1600):
    document = analyze_document(image, max_work_side=side)
    document.original_size = document.original.size
    snapshot = copy.deepcopy(graphs)
    result = plugin._process(document, graphs, limit, build_sknw, plugin.EXPECTED_VERSIONS)
    assert graphs == snapshot
    return result, document


def test_straight_path_uses_known_nodes_original_ink_and_no_weight(build_sknw):
    image, graph, markers = picture({'a': (30, 100), 'b': (270, 100)})
    ImageDraw.Draw(image).line((30, 100, 270, 100), fill='black', width=3)
    markers()
    calls = []
    def build(mask, **kwargs):
        calls.append(kwargs)
        return build_sknw(mask, **kwargs)
    result, _ = execute(image, [graph], build)
    rows = result['inventory']['panel']
    assert len(rows) == 1
    candidate = rows[0]
    assert {candidate['from'], candidate['to']} == {'a', 'b'}
    assert candidate['id'].startswith('sknw_')
    assert candidate['pixel_evidence']['supported'] is True
    assert candidate['direction'] == 'undirected'
    assert 'weight' not in candidate and 'weight' not in candidate['tool_evidence']
    assert candidate['tool_evidence']['proposal_only'] is True
    assert candidate['tool_evidence']['original_size'] == [300, 200]
    assert calls == [{'multi': True, 'iso': True, 'ring': True, 'full': False}]


def test_crossing_is_two_paths_not_a_new_mathematical_vertex(build_sknw):
    image, graph, markers = picture({'a': (35, 30), 'b': (265, 170),
                                     'c': (35, 170), 'd': (265, 30)})
    draw = ImageDraw.Draw(image)
    draw.line((35, 30, 265, 170), fill='black', width=3)
    draw.line((35, 170, 265, 30), fill='black', width=3)
    markers()
    result, _ = execute(image, [graph], build_sknw)
    rows = result['inventory']['panel']
    assert {frozenset((r['from'], r['to'])) for r in rows} == {frozenset('ab'), frozenset('cd')}
    assert all(row['pixel_evidence']['supported'] for row in rows)
    assert len(graph['vertices']) == 4


def test_three_parallel_strokes_remain_distinct(build_sknw):
    image, graph, markers = picture({'a': (40, 100), 'b': (260, 100)})
    draw = ImageDraw.Draw(image)
    for sign in (-1, 0, 1):
        draw.line([(x, round(100+sign*.0055*(x-40)*(260-x))) for x in range(40, 261)],
                  fill='black', width=3)
    markers()
    result, _ = execute(image, [graph], build_sknw)
    rows = result['inventory']['panel']
    assert len(rows) == 3
    assert len({row['id'] for row in rows}) == 3
    assert all(row['pixel_evidence']['supported'] for row in rows)


def test_hollow_node_rims_do_not_become_self_loops(build_sknw):
    image, graph, markers = picture({'a': (40, 100), 'b': (260, 100)}, hollow=True, radius=19)
    ImageDraw.Draw(image).line((40, 100, 260, 100), fill='black', width=3)
    markers()
    result, document = execute(image, [graph], build_sknw)
    rows = result['inventory']['panel']
    assert len(rows) == 1 and rows[0]['from'] != rows[0]['to']
    assert rows[0]['pixel_evidence']['supported'] is True
    roi = prepare_skeleton_roi(document, graph)
    assert roi['skeleton'][100, 40] == 0
    assert roi['skeleton'][100, 40+17] == 0


def test_unattached_ring_and_isolated_vertex_are_not_final_edges(build_sknw):
    image, graph, markers = picture({'a': (30, 100), 'b': (270, 100)})
    ImageDraw.Draw(image).ellipse((110, 60, 190, 140), outline='black', width=3)
    markers()
    result, _ = execute(image, [graph], build_sknw)
    assert result['inventory']['panel'] == []
    assert any(d.get('unattached_segments', 0) > 0 for d in result['diagnostics'])


def test_real_exterior_loop_can_be_proposed(build_sknw):
    image, graph, markers = picture({'a': (50, 100)})
    ImageDraw.Draw(image).ellipse((50, 30, 190, 170), outline='black', width=3)
    markers()
    result, _ = execute(image, [graph], build_sknw)
    rows = result['inventory']['panel']
    assert len(rows) == 1
    assert rows[0]['from'] == rows[0]['to'] == 'a'
    assert rows[0]['pixel_evidence']['supported'] is True


def test_arrow_direction_not_invented_from_skeleton_order(build_sknw):
    image, graph, markers = picture({'a': (30, 100), 'b': (270, 100)}, directed=True)
    ImageDraw.Draw(image).line((30, 100, 270, 100), fill='black', width=3)
    markers()
    result, _ = execute(image, [graph], build_sknw)
    assert result['inventory']['panel'][0]['direction'] == 'unknown'


def test_gap_not_implicitly_closed(build_sknw):
    image, graph, markers = picture({'a': (30, 100), 'b': (270, 100)})
    draw = ImageDraw.Draw(image)
    draw.line((30, 100, 120, 100), fill='black', width=3)
    draw.line((135, 100, 270, 100), fill='black', width=3)
    markers()
    result, _ = execute(image, [graph], build_sknw)
    assert result['inventory']['panel'] == []


def test_source_coordinate_mapping_uses_pixel_centres(build_sknw):
    image, graph, markers = picture({'a': (60, 200), 'b': (540, 200)}, size=(600, 400), radius=14)
    ImageDraw.Draw(image).line((60, 200, 540, 200), fill='black', width=6)
    markers()
    result, document = execute(image, [graph], build_sknw, side=300)
    candidate = result['inventory']['panel'][0]
    original = np.asarray(candidate['tool_evidence']['original_pixel_path'])
    normalized = np.asarray(candidate['path'][1:-1])
    work = normalized*np.asarray([299, 199])
    np.testing.assert_allclose(original, (work+.5)/.5-.5, atol=.001)
    assert document.original.size == (600, 400)


def test_candidate_capacity_is_explicit(build_sknw):
    image, graph, markers = picture({'a': (40, 100), 'b': (260, 100)})
    draw = ImageDraw.Draw(image)
    for sign in (-1, 1):
        draw.line([(x, round(100+sign*.0055*(x-40)*(260-x))) for x in range(40, 261)],
                  fill='black', width=3)
    markers()
    result, _ = execute(image, [graph], build_sknw, limit=1)
    assert len(result['inventory']['panel']) == 1
    assert any(d['code'] == 'candidate_capacity_reached' and d['status'] == 'partial'
               for d in result['diagnostics'])


def test_skeleton_buffer_capacity_precedes_third_party_call(monkeypatch):
    image, graph, markers = picture({'a': (30, 100), 'b': (270, 100)})
    ImageDraw.Draw(image).line((30, 100, 270, 100), fill='black', width=3)
    markers()
    monkeypatch.setattr(plugin, 'MAX_SKELETON_PIXELS', 3)
    def forbidden(*args, **kwargs):
        raise AssertionError('sknw must not see a buffer above the bound')
    result, _ = execute(image, [graph], forbidden)
    assert result['inventory']['panel'] == []
    assert result['diagnostics'][0]['code'] == 'skeleton_capacity_reached'


def test_tool_invented_path_on_blank_source_fails_independent_pixel_check():
    import networkx as nx
    image, graph, _ = picture({'a': (30, 100), 'b': (270, 100)})
    document = analyze_document(image)
    roi = prepare_skeleton_roi(document, graph)
    # This intentionally dishonest tool output joins the valid vertex ports.
    # It still must fail because none of the source pixels supports the path.
    a, b = [roi['local_geometry'][name] for name in ('a', 'b')]
    start = round(a['center_pixels'][0]+a['radius_pixels']+2)
    end = round(b['center_pixels'][0]-b['radius_pixels']-2)
    path = np.asarray([[100, x] for x in range(start, end+1)], dtype=np.int32)
    def fabricated(mask, **kwargs):
        result = nx.MultiGraph()
        result.add_node(0, pts=path[:1], o=path[0])
        result.add_node(1, pts=path[-1:], o=path[-1])
        result.add_edge(0, 1, pts=path, weight=12345)
        return result
    result, _ = execute(image, [graph], fabricated)
    assert result['inventory']['panel'] == []


def test_large_node_inventory_abstains_instead_of_truncating_nodes():
    image = Image.new('RGB', (300, 200), 'white')
    graph = {'id': 'g', 'vertices': [{'id': str(i), 'x': .1+i*.02, 'y': .5} for i in range(31)]}
    def forbidden(*args, **kwargs):
        raise AssertionError('invalid ROI must not reach sknw')
    result, _ = execute(image, [graph], forbidden)
    assert result['diagnostics'][0]['code'] == 'roi_unavailable'


def test_junction_bridge_cannot_cross_blank_pixels():
    assert plugin._junction_path([(0, 0), (2, 0)], (0, 0), (2, 0)) is None
    assert plugin._junction_path([(0, 0), (1, 0), (2, 0)], (0, 0), (2, 0)) == [(0, 0), (1, 0), (2, 0)]


@pytest.mark.parametrize('limit', [0, 161, True, 2.5])
def test_invalid_candidate_limits_fail_closed(limit):
    inventory, diagnostics = plugin.suggest_candidates(None, [], max_candidates=limit)
    assert inventory == {} and diagnostics[0]['status'] == 'failed'


def test_duplicate_node_ids_fail_before_execution():
    graph = {'id': 'g', 'vertices': [{'id': 'a', 'x': .2, 'y': .5}, {'id': 'a', 'x': .7, 'y': .5}]}
    inventory, diagnostics = plugin.suggest_candidates(None, [graph])
    assert inventory == {}
    assert diagnostics[0]['code'] == 'invalid_or_duplicate_vertex_id'


def test_past_deadline_does_not_spawn(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('already-expired calls must not start a worker')
    monkeypatch.setattr(plugin.subprocess, 'Popen', forbidden)
    _, diagnostics = plugin.suggest_candidates(None, [{'id': 'g', 'vertices': []}], deadline=time.monotonic()-1)
    assert diagnostics[0]['code'] == 'deadline_exceeded'


def test_worker_environment_does_not_copy_keys_or_database_config(monkeypatch, tmp_path):
    monkeypatch.setenv('QWEN_API_KEY', 'test-only-not-a-real-key')
    monkeypatch.setenv('DATABASE_URL', 'test-only-not-a-database')
    env = plugin._child_environment(tmp_path)
    assert 'QWEN_API_KEY' not in env and 'DATABASE_URL' not in env
    assert env['NUMBA_NUM_THREADS'] == env['OPENBLAS_NUM_THREADS'] == '1'
    assert 'HOME' not in env and 'CODEX_HOME' not in env


def test_shared_ocr_lock_prevents_parallel_cpu_worker():
    import fcntl
    import tempfile
    image, graph, markers = picture({'a': (30, 100), 'b': (270, 100)})
    markers()
    document = analyze_document(image)
    with (Path(tempfile.gettempdir())/'dmate-local-model.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            _, diagnostics = plugin.suggest_candidates(document, [graph])
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    assert diagnostics[0]['code'] == 'local_cpu_busy'


def test_timeout_kills_worker_and_cleans_private_inputs(monkeypatch):
    image, graph, markers = picture({'a': (30, 100), 'b': (270, 100)})
    markers()
    document = analyze_document(image)
    real_popen = subprocess.Popen
    calls = []
    def sleeping_worker(command, **kwargs):
        proc = real_popen([sys.executable, '-c', 'import time; time.sleep(60)'], **kwargs)
        calls.append((proc, Path(command[-1])))
        return proc
    monkeypatch.setattr(plugin.subprocess, 'Popen', sleeping_worker)
    started = time.monotonic()
    inventory, diagnostics = plugin.suggest_candidates(document, [graph], deadline=started+.6)
    assert time.monotonic()-started < 3
    assert inventory == {'panel': []}
    assert diagnostics[0]['code'] == 'deadline_exceeded'
    assert len(calls) == 1 and calls[0][0].poll() is not None
    assert not calls[0][1].exists()


def test_dependency_mismatch_is_explicit_no_model_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(plugin.importlib.metadata, 'version', lambda _: 'unexpected')
    plugin._worker(tmp_path)
    result = json.loads((tmp_path/'response.json').read_text())
    assert result['inventory'] == {}
    assert result['diagnostics'][0]['code'] == 'dependency_version_mismatch'
    assert result['diagnostics'][0]['status'] == 'failed'


def test_missing_dependency_is_explicit(monkeypatch, tmp_path):
    def missing(name):
        raise importlib.metadata.PackageNotFoundError(name)
    monkeypatch.setattr(plugin.importlib.metadata, 'version', missing)
    plugin._worker(tmp_path)
    result = json.loads((tmp_path/'response.json').read_text())
    assert result['diagnostics'][0]['code'] == 'dependency_missing'


def test_real_pinned_subprocess_works_without_model_calls(build_sknw):
    versions = {name: importlib.metadata.version(name) for name in plugin.EXPECTED_VERSIONS}
    if versions != plugin.EXPECTED_VERSIONS:
        pytest.skip('requires the production-constrained sknw dependency environment')
    image, graph, markers = picture({'a': (30, 100), 'b': (270, 100)})
    ImageDraw.Draw(image).line((30, 100, 270, 100), fill='black', width=3)
    markers()
    result, diagnostics = plugin.suggest_candidates(analyze_document(image), [graph])
    assert len(result['panel']) == 1
    assert result['panel'][0]['pixel_evidence']['supported'] is True
    assert not any(d['status'] == 'failed' for d in diagnostics)
    assert any(d.get('cpu_parallelism') == 1 for d in diagnostics)
