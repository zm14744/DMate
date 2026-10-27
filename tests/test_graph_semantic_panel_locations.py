"""Prevent a reused local coordinate template from cropping another panel."""
import copy

from graph_semantic_panel_context import panel_context, separate_location_hints


def graph(gid, points, *, label_prefix=''):
    return {'id': gid, 'name': gid, 'vertices': [
        {'id': f'v{i}', 'label': label_prefix+str(i), 'x': x, 'y': y,
         'position': 'printed vertex'} for i, (x, y) in enumerate(points)],
        'edges': [{'from': 'v0', 'to': 'v1', 'weight': 5, 'style': 'dashed'}]}


def test_lower_panel_cannot_reuse_upper_panel_coordinates_to_choose_its_crop():
    left = [(250, 100), (120, 180), (120, 340), (380, 340), (380, 180)]
    right = [(620, 100), (500, 340), (740, 340), (740, 180)]
    original = [graph('G1', left), graph('G2', right), graph('G3', left),
                graph('G4', right+[(500, 180)])]
    before = copy.deepcopy(original)
    layout = {'panels': [
        {'id': 'upper-left', 'bbox': [90, 20, 430, 420]},
        {'id': 'upper-right', 'bbox': [445, 60, 810, 440]},
        {'id': 'lower-left', 'bbox': [90, 500, 430, 930]},
        {'id': 'lower-right', 'bbox': [445, 500, 810, 950]}]}
    # Reproduce the old wrong crop before checking the correction.
    assert panel_context(original[2], layout)['audit']['layout_panel_ids'] == ['upper-left']
    prepared, audit = separate_location_hints(original)
    assert audit['withdrawn_graph_ids'] == ['G1', 'G2', 'G3', 'G4']
    assert len(prepared) == 4 and original == before
    for old, new in zip(original, prepared):
        assert [(v['id'], v['label']) for v in new['vertices']] == [
            (v['id'], v['label']) for v in old['vertices']]
        assert new['edges'] == old['edges'] and new['name'] == old['name']
        contextual = panel_context(new, layout)
        assert not contextual['audit']['layout_panel_ids']
        assert contextual['audit']['reading_bbox'] is None
        assert contextual['audit']['original_overview_required']


def test_similar_shapes_in_different_page_locations_retain_their_coordinates():
    points = [(100, 100), (200, 100), (200, 300), (100, 300)]
    graphs = [graph('G1', points), graph('G2', [(x, y+500) for x, y in points])]
    prepared, audit = separate_location_hints(graphs)
    assert prepared == graphs and prepared is not graphs
    assert audit['status'] == 'unchanged'


def test_independent_panel_box_and_literal_labels_survive_reused_points():
    points = [(100, 100), (200, 100), (200, 300)]
    graphs = [graph('G1', points, label_prefix='a'), graph('G2', points, label_prefix='B')]
    graphs[1]['bbox'] = [500, 500, 800, 800]
    graphs[1]['layout_panel_ids'] = ['lower']
    prepared, audit = separate_location_hints(graphs)
    assert audit['withdrawn_graph_ids'] == ['G1', 'G2']
    assert prepared[1]['bbox'] == graphs[1]['bbox']
    assert prepared[1]['layout_panel_ids'] == ['lower']
    assert [v['label'] for v in prepared[1]['vertices']] == ['B0', 'B1', 'B2']
    assert all(v['position'] == 'printed vertex' for v in prepared[1]['vertices'])


def test_numeric_position_lists_are_also_withdrawn_without_guessing_new_positions():
    graphs = [graph('G1', [(10, 20), (30, 40)]), graph('G2', [(10, 20), (30, 40)])]
    for g in graphs:
        for v in g['vertices']:
            v['position'] = [v.pop('x'), v.pop('y')]
    prepared, audit = separate_location_hints(graphs)
    assert len(audit['withdrawn_graph_ids']) == 2
    assert all('position' not in v for g in prepared for v in g['vertices'])


def test_partial_or_invalid_points_do_not_create_an_inferred_conflict():
    graphs = [graph('G1', [(10, 20), (30, 40)]), graph('G2', [(10, 20), (30, 40)])]
    graphs[1]['vertices'][1]['x'] = None
    prepared, audit = separate_location_hints(graphs)
    assert prepared == graphs and audit['status'] == 'unchanged'
