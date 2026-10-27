import copy

import pytest

from graph_semantic_panel_context import panel_context


def layout():
    return {'panels': [
        {'id': 'p1', 'bbox': [20, 20, 300, 400]},
        {'id': 'p2', 'bbox': [600, 20, 950, 400]},
        {'id': 'p5', 'bbox': [600, 600, 950, 950]}]}


def test_fifth_panel_can_get_own_context_despite_page_view_limit():
    graph = {'id': 'G5', 'bbox': [650, 650, 900, 900], 'vertices': [], 'edges': []}
    before = copy.deepcopy(graph)
    prepared = panel_context(graph, layout())
    assert prepared['graph']['bbox'] == [600, 600, 950, 950]
    assert prepared['audit']['layout_panel_ids'] == ['p5']
    assert graph == before


def test_explicit_hint_unions_disconnected_windows_without_creating_graphs():
    graph = {'id': 'G1', 'layout_panel_ids': ['p1', 'p2'], 'vertices': [{'id': 'z'}], 'edges': []}
    result = panel_context(graph, layout())
    assert result['graph']['bbox'] == [20, 20, 950, 400]
    assert result['graph']['vertices'] == graph['vertices']
    assert result['audit']['candidate_only']


def test_ambiguous_positions_dont_assign_by_graph_index_or_name():
    graph = {'id': 'G5', 'name': '(e)', 'vertices': [], 'edges': []}
    result = panel_context(graph, layout())
    assert result['graph'] == graph
    assert result['audit']['association'] == 'none'


def test_vertex_hints_can_select_window_without_mandatory_model_box():
    graph = {'vertices': [{'id': 'a', 'x': 700, 'y': 150},
                          {'id': 'b', 'position': [800, 250]}], 'edges': []}
    result = panel_context(graph, layout())
    assert result['audit']['layout_panel_ids'] == ['p2']
    assert result['graph']['bbox'] == [600, 20, 950, 400]


def test_full_page_candidate_does_not_dilute_per_graph_zoom():
    graph = {'bbox': [600, 600, 950, 950], 'vertices': []}
    result = panel_context(graph, {'panels': [{'id': 'all', 'bbox': [0, 0, 1000, 1000]}]})
    assert result['graph'] == graph
    assert not result['audit']['layout_panel_ids']


def test_invalid_geometry_is_an_ordinary_no_hint():
    graph = {'bbox': [2, float('nan'), 4, 8], 'vertices': [{'x': True, 'y': 40}]}
    result = panel_context(graph, layout())
    assert result['audit']['reading_bbox'] is None
    assert result['audit']['geometry_required'] is False


@pytest.mark.parametrize('position,expected', [('左上角', 'p1'), ('上排右侧', 'p2'),
                                              ('右下方', 'p5')])
def test_unique_spatial_locator_selects_candidate_without_vertex_coordinates(position, expected):
    graph = {'id': 'misleading_order_99', 'position': position,
             'vertices': [{'id': 'a'}, {'id': 'b'}], 'edges': []}
    result = panel_context(graph, layout())
    assert result['audit']['association'] == 'unique_spatial_locator'
    assert result['audit']['layout_panel_ids'] == [expected]
    assert result['graph']['vertices'] == graph['vertices']


@pytest.mark.parametrize('position', ['上排', '左右两边', '图中上方那条边有向', '(5)', '欧拉图'])
def test_ambiguous_or_semantic_text_is_not_a_panel_locator(position):
    graph = {'id': 'G5', 'position': position, 'vertices': [], 'edges': []}
    result = panel_context(graph, layout())
    assert result['graph'] == graph
    assert result['audit']['association'] == 'none'


def shifted_six_panel_case():
    """Observed 011 coarse hints; no expected edges or semantic answers."""
    boxes = [[66, 183, 307, 513], [377, 241, 559, 500], [696, 181, 955, 514],
             [62, 649, 244, 908], [361, 649, 542, 908], [693, 649, 874, 908]]
    windows = {'panels': [{'id': f'p{i}', 'bbox': box} for i, box in enumerate(boxes, 1)]}
    graphs = []
    for row in range(2):
        for column in range(3):
            left, top = 100+column*300, 150+row*400
            points = [(left, top), (left, top+150), (left+150, top+150), (left+150, top)]
            graphs.append({'id': f'arbitrary_{9-len(graphs)}', 'vertices': [
                {'id': f'v{i}', 'label': None, 'x': x, 'y': y} for i, (x, y) in enumerate(points)],
                'edges': []})
    graphs[0]['vertices'].append({'id': 'extra', 'label': 'e5', 'x': 320, 'y': 150})
    return graphs, windows


def test_rough_shifted_clouds_get_distinct_nearby_windows_without_precise_coordinates():
    graphs, windows = shifted_six_panel_case()
    for index, graph in enumerate(graphs, 1):
        before = copy.deepcopy(graph)
        result = panel_context(graph, windows)
        assert result['audit']['layout_panel_ids'] == [f'p{index}']
        assert result['audit']['association'] == 'nearby_layout_candidate'
        assert result['graph']['bbox'] == windows['panels'][index-1]['bbox']
        assert result['audit']['original_overview_required']
        assert result['graph']['vertices'] == graph['vertices'] and graph == before


def test_nearby_matching_rejects_equidistant_or_far_away_cloud():
    windows = {'panels': [{'id': 'left', 'bbox': [100, 500, 300, 800]},
                          {'id': 'right', 'bbox': [700, 500, 900, 800]}]}
    for points in [[(450, 600), (550, 700)], [(100, 0), (200, 50)]]:
        graph = {'vertices': [{'x': x, 'y': y} for x, y in points]}
        assert panel_context(graph, windows)['audit']['association'] == 'none'
