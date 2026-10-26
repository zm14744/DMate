import copy

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
