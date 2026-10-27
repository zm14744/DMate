"""Reused optional coordinates cannot steer later readers to another panel."""
import copy

import pytest
import requests

from graph_agent_runtime import AgentBudget
from graph_semantic_pipeline import recognize_semantic
from vision_provider import VisionProvider
from test_graph_semantic_pipeline import (
    Reader, SOURCE_ROLES, install_semantic_worker_fixtures, original,
)


@pytest.fixture(autouse=True)
def local_boundaries(monkeypatch, tmp_path):
    events = install_semantic_worker_fixtures(monkeypatch, lock_root=tmp_path)
    monkeypatch.setattr(VisionProvider, 'available', lambda self: False)
    monkeypatch.setattr(requests.sessions.Session, 'send',
                        lambda *args, **kwargs: pytest.fail('No network is allowed'))
    return events


def graph(gid, points):
    return {'id': gid, 'name': '(' + gid + ')', 'directed': False,
        'vertices': [{'id': letter, 'label': gid + '-' + letter,
                      'x': x, 'y': y, 'position': '原图中的印刷顶点'}
                     for letter, (x, y) in zip('abc', points)],
        'edges': [{'from': 'a', 'to': 'b', 'direction': 'undirected',
                   'weight': 5, 'style': 'dashed'},
                  {'from': 'b', 'to': 'c', 'direction': 'undirected',
                   'weight': 9, 'style': 'solid'}]}


def layout():
    return {'status': 'ok', 'model': 'PP-DocLayoutV3', 'regions': [
        {'id': 'upper', 'bbox': [.05, .05, .4, .4], 'role': 'figure',
         'label': 'image', 'score': .9},
        {'id': 'lower', 'bbox': [.55, .55, .95, .95], 'role': 'figure',
         'label': 'image', 'score': .9}]}


def observe(monkeypatch, graphs):
    """Spy on real preparation boundaries, without replacing their behavior."""
    import graph_semantic_arrow_views
    import graph_semantic_geometry
    geometry, panels = [], {}
    real_geometry = graph_semantic_geometry.prepare_semantic_geometry
    real_panel = graph_semantic_arrow_views.prepare_panel_views
    def geometry_call(*args, **kwargs):
        if kwargs.get('draft') is not None:
            geometry.append(copy.deepcopy(kwargs['draft']))
        return real_geometry(*args, **kwargs)
    def panel_call(*args, **kwargs):
        value = real_panel(*args, **kwargs)
        panels[kwargs['graph']['id']] = copy.deepcopy(value)
        return value
    monkeypatch.setattr(graph_semantic_geometry, 'prepare_semantic_geometry', geometry_call)
    monkeypatch.setattr(graph_semantic_arrow_views, 'prepare_panel_views', panel_call)
    doc = {'body_text': '分别核对两幅图的连接。', 'graphs': graphs, 'uncertainties': []}
    reader = Reader(source_document=doc)
    result = recognize_semantic(original(), layout=layout(), provider=reader,
        budget=AgentBudget(seconds=30, calls=16), audit=True)
    return result, reader, geometry, panels


def assert_semantics_preserved(result, graphs):
    assert result['complete'] and result['body_complete']
    assert not result['semantic_issues']
    assert [g['id'] for g in result['graphs']] == [g['id'] for g in graphs]
    for actual, expected in zip(result['graphs'], graphs):
        assert [(v['id'], v['label']) for v in actual['vertices']] == [
            (v['id'], v['label']) for v in expected['vertices']]
        assert [(e['from'], e['to'], e['weight'], e['style']) for e in actual['edges']] == [
            (e['from'], e['to'], e['weight'], e['style']) for e in expected['edges']]


@pytest.mark.parametrize('position_hint', ['原图中的印刷顶点', ['unknown', 'unknown']])
def test_reused_cloud_is_removed_before_real_geometry_and_source_requests(monkeypatch, local_boundaries, position_hint):
    points = [(100, 100), (200, 150), (300, 300)]
    graphs = [graph('G1', points), graph('G2', points)]
    for g in graphs:
        for v in g['vertices']:
            v['position'] = copy.deepcopy(position_hint)
    before = copy.deepcopy(graphs)
    result, reader, geometry, panels = observe(monkeypatch, graphs)
    assert_semantics_preserved(result, graphs)
    assert graphs == before
    assert len(geometry) == 1
    assert all('x' not in v and 'y' not in v
               for g in geometry[0]['graphs'] for v in g['vertices'])
    if isinstance(position_hint, str):
        assert all(v['position'] == position_hint
                   for g in geometry[0]['graphs'] for v in g['vertices'])
    else:
        assert all('position' not in v for g in geometry[0]['graphs'] for v in g['vertices'])
    assert not any(e['kind'] == 'injected_geometry_worker' for e in local_boundaries)
    assert not result['semantic_workflow']['local_tools']['connections']['graphs']
    overview = next(c['images'][0] for c in reader.calls if c['request']['role'] == 'semantic_extract')
    source_calls = [c for c in reader.calls if c['request']['role'] in SOURCE_ROLES]
    assert {c['request']['task']['graph_id'] for c in source_calls} == {'G1', 'G2'}
    for call in source_calls:
        assert call['images'] == [overview]
        assert not call['request']['local_connection_candidates']
        assert all('x' not in v and 'y' not in v for v in call['request']['task']['vertices'])
    assert all(p['image_quality']['panel_view_status'] == 'no_panel_hint' for p in panels.values())
    audit = next(a for a in result['semantic_workflow']['view_audit']
                 if a['phase'] == 'inventory_location_hints')
    assert audit['withdrawn_graph_ids'] == ['G1', 'G2'] and not audit['graph_content_changed']


def test_explicit_independent_windows_still_produce_distinct_real_crops(monkeypatch):
    points = [(100, 100), (200, 150), (300, 300)]
    graphs = [graph('G1', points), graph('G2', points)]
    graphs[0].update(bbox=[70, 70, 380, 380], layout_panel_ids=['panel_1'])
    graphs[1].update(bbox=[570, 570, 930, 930], layout_panel_ids=['panel_2'])
    result, reader, geometry, panels = observe(monkeypatch, graphs)
    assert_semantics_preserved(result, graphs)
    assert [g['layout_panel_ids'] for g in geometry[0]['graphs']] == [['panel_1'], ['panel_2']]
    assert all('x' not in v and 'y' not in v
               for g in geometry[0]['graphs'] for v in g['vertices'])
    assert all(p['image_quality']['panel_view_status'] == 'cropped' for p in panels.values())
    top = panels['G1']['view_metadata'][1]['source_box']
    bottom = panels['G2']['view_metadata'][1]['source_box']
    assert top[3] < bottom[1]
    for call in reader.calls:
        if call['request']['role'] in SOURCE_ROLES:
            assert len(call['images']) == 2
            assert call['images'][0] == panels[call['request']['task']['graph_id']]['images'][0]
    associations = [a for a in result['semantic_workflow']['view_audit']
                    if a['phase'] == 'layout_panel_association']
    assert all(a['association'] == 'inventory_window_reference' for a in associations)


def test_distinct_page_coordinates_continue_to_reach_tracers_and_source_readers(monkeypatch, local_boundaries):
    graphs = [graph('G1', [(100, 100), (200, 150), (300, 300)]),
              graph('G2', [(600, 600), (700, 650), (800, 800)])]
    result, reader, geometry, panels = observe(monkeypatch, graphs)
    assert_semantics_preserved(result, graphs)
    assert [[(v['x'], v['y']) for v in g['vertices']] for g in geometry[0]['graphs']] == [
        [(v['x'], v['y']) for v in g['vertices']] for g in graphs]
    traced = [e for e in local_boundaries if e['kind'] == 'injected_geometry_worker']
    assert {e['tool'] for e in traced} == {'opencv', 'sknw'}
    assert all(set(e['graph_ids']) == {'G1', 'G2'} for e in traced)
    for call in reader.calls:
        if call['request']['role'] in SOURCE_ROLES:
            assert all('x' in v and 'y' in v for v in call['request']['task']['vertices'])
            assert call['request']['local_connection_candidates']['candidates']
    assert all(p['image_quality']['panel_view_status'] == 'cropped' for p in panels.values())
