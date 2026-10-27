"""Deterministic V6 scope and question-required attribute guards."""
import copy

from graph_semantic_pipeline import (
    _geometry_identity,
    _literal_required_edge_attributes,
    _required_visual_attribute_issues,
)


def graph(gid, *, color=None, style=None, weight=None, edge_label=None):
    edge = {
        'id': gid + '-e1',
        'from': 'a',
        'to': 'b',
        'direction': 'undirected',
    }
    if color is not None:
        edge['color'] = color
    if style is not None:
        edge['style'] = style
    if weight is not None:
        edge['weight'] = weight
    if edge_label is not None:
        edge['edge_label'] = edge_label
    return {
        'id': gid,
        'name': gid,
        'bbox': [10, 20, 400, 450],
        'layout_panel_ids': ['panel-b', 'panel-a'],
        'vertices': [
            {'id': 'a', 'label': 'a', 'x': 100, 'y': 120},
            {'id': 'b', 'label': 'b', 'x': 300, 'y': 320},
        ],
        'edges': [edge],
    }


def test_geometry_identity_ignores_graph_vertex_and_panel_id_list_order_only():
    first = {
        'body_text': 'compare',
        'graphs': [graph('G2'), graph('G1')],
        'uncertainties': [],
    }
    second = copy.deepcopy(first)
    second['graphs'].reverse()
    for row in second['graphs']:
        row['vertices'].reverse()
        row['layout_panel_ids'].reverse()
    assert _geometry_identity(first) == _geometry_identity(second)


def test_geometry_identity_changes_for_actual_panel_node_or_label_edits():
    base = {'body_text': '', 'graphs': [graph('G1')], 'uncertainties': []}
    original = _geometry_identity(base)
    edits = []
    for mutate in (
        lambda doc: doc['graphs'][0].__setitem__('bbox', [11, 20, 400, 450]),
        lambda doc: doc['graphs'][0]['vertices'][0].__setitem__('x', 101),
        lambda doc: doc['graphs'][0]['vertices'][0].__setitem__('label', 'A'),
        lambda doc: doc['graphs'][0].__setitem__('layout_panel_ids', ['panel-a']),
    ):
        doc = copy.deepcopy(base)
        mutate(doc)
        edits.append(_geometry_identity(doc))
    assert all(value != original for value in edits)


def test_literal_green_edges_and_black_dashed_chords_require_color_and_style():
    doc = {
        'body_text': '图中绿边为一棵生成树 T，黑色虚线为 T 的弦。',
        'graphs': [graph('G1')],
        'uncertainties': [],
    }
    assert _literal_required_edge_attributes(doc) == {'G1': {'color', 'style'}}
    issues = _required_visual_attribute_issues(doc)
    assert {(row['field'], tuple(row['edge_ids'])) for row in issues} == {
        ('color', ('G1-e1',)), ('style', ('G1-e1',))
    }
    assert all(row['scope'] == 'graph' and row['graph_id'] == 'G1' for row in issues)


def test_question_required_attributes_do_not_invent_values_and_clear_only_after_real_fields_exist():
    doc = {
        'body_text': '图中绿边为树边，黑色虚线为弦。',
        'graphs': [graph('G1', color='green', style='dashed')],
        'uncertainties': [],
    }
    assert _required_visual_attribute_issues(doc) == []
    # The requirement detector only says which fields matter.  It never
    # writes green/dashed into an unread edge.
    unread = {'body_text': doc['body_text'], 'graphs': [graph('G1')], 'uncertainties': []}
    before = copy.deepcopy(unread)
    _required_visual_attribute_issues(unread)
    assert unread == before


def test_ordinary_topology_question_does_not_make_cosmetic_color_or_style_mandatory():
    doc = {
        'body_text': '判断下图是否为树，并求各顶点的度数。',
        'graphs': [graph('G1')],
        'uncertainties': [],
    }
    assert _literal_required_edge_attributes(doc) == {'G1': set()}
    assert _required_visual_attribute_issues(doc) == []


def test_located_legend_scopes_attribute_requirement_to_its_graph():
    doc = {
        'body_text': '回答下列问题。',
        'graphs': [graph('G1'), graph('G2')],
        'text_context': {
            'legends': [{
                'text': '绿色边表示选中的边，黑色虚线表示其余边。',
                'graph_ids': ['G2'],
            }]
        },
        'uncertainties': [],
    }
    required = _literal_required_edge_attributes(doc)
    assert required == {'G1': set(), 'G2': {'color', 'style'}}
    issues = _required_visual_attribute_issues(doc)
    assert {row['graph_id'] for row in issues} == {'G2'}


def test_weight_and_edge_label_are_required_only_when_literal_question_requests_them():
    doc = {
        'body_text': '请按边编号给出结果，并计算加权图中各边权值对应的总权重。',
        'graphs': [graph('G1')],
        'uncertainties': [],
    }
    assert _literal_required_edge_attributes(doc)['G1'] == {'weight', 'edge_label'}
    assert {row['field'] for row in _required_visual_attribute_issues(doc)} == {
        'weight', 'edge_label'
    }


def test_scoped_legend_duplicated_in_body_does_not_expand_to_other_graphs():
    legend = '绿色边表示树边，黑色虚线表示其余边。'
    doc = {
        'body_text': '观察两幅图。' + legend + '回答问题。',
        'graphs': [graph('G1'), graph('G2')],
        'text_context': {'legends': [{'text': legend, 'graph_ids': ['G2']}]},
        'uncertainties': [],
    }
    assert _literal_required_edge_attributes(doc) == {
        'G1': set(), 'G2': {'color', 'style'}
    }
