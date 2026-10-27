"""Scoped reread identity checks; no image, model or private reference needed."""
import copy

import pytest

from graph_semantic_repair_identity import remap_repair_edges


def readings():
    previous = {'id': 'G1', 'name': '(a)', 'vertices': [
        {'id': 'v1', 'label': 'A', 'x': 10},
        {'id': 'v2', 'label': 'B', 'x': 90},
        {'id': 'v3', 'label': 'C', 'x': 50},
        {'id': 'v4', 'label': 'D', 'position': 'isolated'}],
        'edges': [{'id': 'old', 'from': 'v1', 'to': 'v2', 'weight': 2}]}
    proposed = {'id': 'G1', 'name': '(a)', 'vertices': [
        {'id': 'C', 'label': 'C'}, {'id': 'A', 'label': 'A'},
        {'id': 'D', 'label': 'D'}, {'id': 'B', 'label': 'B'}],
        'edges': [
            {'id': 'read1', 'from': 'A', 'to': 'B', 'direction': 'undirected', 'weight': 2},
            {'id': 'read2', 'from': 'A', 'to': 'C', 'direction': 'undirected', 'weight': 5}]}
    return previous, proposed


def test_valid_label_bijection_accepts_reread_edge_without_replacing_vertices():
    previous, proposed = readings()
    before, raw = copy.deepcopy(previous), copy.deepcopy(proposed)
    edges, audit = remap_repair_edges(previous, proposed)
    assert edges == [
        {'id': 'read1', 'from': 'v1', 'to': 'v2', 'direction': 'undirected', 'weight': 2},
        {'id': 'read2', 'from': 'v1', 'to': 'v3', 'direction': 'undirected', 'weight': 5}]
    assert audit['status'] == 'mapped'
    assert audit['vertex_id_map'] == {'C': 'v3', 'A': 'v1', 'D': 'v4', 'B': 'v2'}
    assert audit['image_accuracy_certified'] is False
    assert previous == before and proposed == raw
    edges[0]['weight'] = 999
    assert proposed == raw


def test_parallel_instances_loop_attributes_and_edge_order_are_not_inferred_or_changed():
    previous, proposed = readings()
    proposed['edges'] = [
        {'id': 'same', 'from': 'B', 'to': 'A', 'direction': 'forward', 'weight': 0,
         'color': 'blue', 'style': 'dashed', 'edge_label': 'e₂', 'path': [[3, 7], [9, 2]]},
        {'id': 'same', 'from': 'B', 'to': 'A', 'direction': 'forward', 'weight': 0,
         'color': 'red', 'style': 'solid', 'edge_label': 'e₃'},
        {'from': 'C', 'to': 'C', 'direction': 'backward', 'multiplicity': 2}]
    expected = copy.deepcopy(proposed['edges'])
    for edge in expected:
        edge['from'] = {'A': 'v1', 'B': 'v2', 'C': 'v3'}[edge['from']]
        edge['to'] = {'A': 'v1', 'B': 'v2', 'C': 'v3'}[edge['to']]
    edges, audit = remap_repair_edges(previous, proposed)
    assert edges == expected
    assert len(edges) == 3 and audit['edge_instances_preserved'] == 3
    # Duplicate edge IDs, direction values and paths belong to the downstream
    # validator. This helper must neither certify nor silently "fix" them.
    assert audit['topology_used'] is False and audit['geometry_used'] is False


def test_internal_id_collision_uses_simultaneous_exact_label_mapping():
    previous = {'id': 'G1', 'vertices': [{'id': 'a', 'label': '左'}, {'id': 'b', 'label': '右'}]}
    proposed = {'id': 'G1', 'vertices': [{'id': 'b', 'label': '左'}, {'id': 'a', 'label': '右'}],
                'edges': [{'from': 'b', 'to': 'a', 'direction': 'forward'}]}
    edges, audit = remap_repair_edges(previous, proposed)
    assert edges == [{'from': 'a', 'to': 'b', 'direction': 'forward'}]
    assert audit['vertex_id_map'] == {'b': 'a', 'a': 'b'}


@pytest.mark.parametrize('side', ['previous', 'proposed'])
@pytest.mark.parametrize('label', [None, '', ' ', 1, True])
def test_any_anonymous_or_nonliteral_label_prevents_whole_mapping(side, label):
    previous, proposed = readings()
    target = previous if side == 'previous' else proposed
    target['vertices'][0]['label'] = label
    edges, audit = remap_repair_edges(previous, proposed)
    assert edges is None and audit['reason'] == side + '_missing_printed_label'


@pytest.mark.parametrize('side', ['previous', 'proposed'])
@pytest.mark.parametrize('field,reason', [('id', 'duplicate_vertex_id'), ('label', 'duplicate_printed_label')])
def test_duplicate_ids_or_labels_cannot_be_disambiguated_by_position_or_topology(side, field, reason):
    previous, proposed = readings()
    target = previous if side == 'previous' else proposed
    target['vertices'][1][field] = target['vertices'][0][field]
    target['vertices'][1].update(x=100, y=200, position='distinct corner')
    edges, audit = remap_repair_edges(previous, proposed)
    assert edges is None and audit['reason'] == side + '_' + reason


@pytest.mark.parametrize('old_label,new_label', [('A', 'a'), ('A', ' A'), ('v₁', 'v1'), ('é', 'e\u0301')])
def test_printed_labels_are_not_casefolded_trimmed_or_unicode_normalized(old_label, new_label):
    previous, proposed = readings()
    previous['vertices'][0]['label'] = old_label
    proposed['vertices'][1]['label'] = new_label
    edges, audit = remap_repair_edges(previous, proposed)
    assert edges is None and audit['reason'] == 'printed_labels_changed'


@pytest.mark.parametrize('change', ['add_isolated', 'remove_isolated', 'rename_isolated'])
def test_even_an_isolated_vertex_inventory_change_cannot_be_hidden(change):
    previous, proposed = readings()
    if change == 'add_isolated':
        proposed['vertices'].append({'id': 'E', 'label': 'E'})
    elif change == 'remove_isolated':
        proposed['vertices'] = [v for v in proposed['vertices'] if v['id'] != 'D']
    else:
        next(v for v in proposed['vertices'] if v['id'] == 'D')['label'] = 'E'
    edges, audit = remap_repair_edges(previous, proposed)
    assert edges is None
    assert audit['reason'] == ('printed_labels_changed' if change == 'rename_isolated' else 'vertex_count_changed')


@pytest.mark.parametrize('graph_id', ['G2', '', None, 1, ' G1'])
def test_matching_labels_never_cross_panel_identity(graph_id):
    previous, proposed = readings()
    proposed['id'] = graph_id
    edges, audit = remap_repair_edges(previous, proposed)
    assert edges is None and audit['reason'] == 'graph_identity_mismatch'


@pytest.mark.parametrize('endpoint', ['v1', 'absent', None, 1, ' A', ['A']])
def test_every_proposed_endpoint_must_belong_to_proposed_inventory(endpoint):
    previous, proposed = readings()
    proposed['edges'].append({'from': endpoint, 'to': 'B'})
    edges, audit = remap_repair_edges(previous, proposed)
    assert edges is None and audit['reason'] == 'unknown_proposed_endpoint'


@pytest.mark.parametrize('field,value,reason', [
    ('vertices', [], 'proposed_vertex_inventory_missing'),
    ('vertices', None, 'proposed_vertex_inventory_missing'),
    ('vertices', [{'id': 'x', 'label': 'x'}] * 101, 'proposed_vertex_capacity_exceeded'),
    ('edges', None, 'edge_inventory_missing'),
    ('edges', [None], 'invalid_edge'),
    ('edges', [{'from': 'A', 'to': 'B'}] * 301, 'edge_capacity_exceeded')])
def test_invalid_or_oversized_records_are_not_silently_truncated(field, value, reason):
    previous, proposed = readings()
    proposed[field] = value
    edges, audit = remap_repair_edges(previous, proposed)
    assert edges is None and audit['reason'] == reason


def test_empty_reread_edges_are_preserved_without_fabricating_expected_structure():
    previous, proposed = readings()
    proposed['edges'] = []
    edges, audit = remap_repair_edges(previous, proposed)
    assert edges == [] and audit['status'] == 'mapped'
    assert audit['mapped_vertex_count'] == 4
    assert audit['changed_endpoint_count'] == 0


def test_scoped_repair_accepts_rebound_edge_and_preserves_body_other_panel_and_original_inventory():
    from graph_semantic_pipeline import _scope_repair

    previous_graph, proposed_graph = readings()
    other = {'id': 'G2', 'name': '(b)', 'vertices': [{'id': 'v1', 'label': 'A'}],
             'edges': []}
    previous = {'body_text': '保留原题干与全部小问。',
                'text_context': {'legend': '原图图例'},
                'graphs': [previous_graph, other],
                'uncertainties': [{'scope': 'body', 'message': '原有题干疑点'}]}
    proposed = {'body_text': '不允许的题干替换', 'text_context': {},
                'graphs': [proposed_graph, {'id': 'G2', 'vertices': [], 'edges': []},
                           {'id': 'G3', 'vertices': [], 'edges': []}],
                'uncertainties': []}
    proposed_graph['name'] = '不允许的图名替换'
    before, raw = copy.deepcopy(previous), copy.deepcopy(proposed)
    result, audit = _scope_repair(previous, proposed, [
        {'scope': 'graph', 'graph_id': 'G1', 'field': 'edges'}])
    assert result['graphs'][0]['edges'] == [
        {'id': 'read1', 'from': 'v1', 'to': 'v2', 'direction': 'undirected', 'weight': 2},
        {'id': 'read2', 'from': 'v1', 'to': 'v3', 'direction': 'undirected', 'weight': 5}]
    assert result['graphs'][0]['vertices'] == previous_graph['vertices']
    assert result['graphs'][0]['name'] == previous_graph['name']
    assert result['graphs'][1:] == [other]
    assert result['body_text'] == previous['body_text']
    assert result['text_context'] == previous['text_context']
    assert result['uncertainties'] == previous['uncertainties']
    assert audit['body_allowed'] is False
    assert audit['field_permissions'][0]['vertex_identity_remap']['status'] == 'mapped'
    assert previous == before and proposed == raw


@pytest.mark.parametrize('case,reason', [
    ('duplicate_label', 'proposed_duplicate_printed_label'),
    ('missing_isolated', 'vertex_count_changed'),
    ('anonymous', 'proposed_missing_printed_label')])
def test_scoped_repair_keeps_original_edges_and_unresolved_issue_for_ambiguous_identity(case, reason):
    from graph_semantic_pipeline import _scope_repair

    previous_graph, proposed_graph = readings()
    if case == 'duplicate_label':
        proposed_graph['vertices'][0]['label'] = proposed_graph['vertices'][1]['label']
    elif case == 'missing_isolated':
        proposed_graph['vertices'] = [v for v in proposed_graph['vertices'] if v['id'] != 'D']
    else:
        proposed_graph['vertices'][0]['label'] = None
    previous = {'body_text': '未改题干', 'graphs': [previous_graph], 'uncertainties': []}
    proposed = {'body_text': '不能采用', 'graphs': [proposed_graph], 'uncertainties': []}
    result, audit = _scope_repair(previous, proposed, [
        {'scope': 'graph', 'graph_id': 'G1', 'field': 'edges'}])
    assert result['graphs'] == previous['graphs']
    assert result['body_text'] == previous['body_text']
    assert result['uncertainties'][0]['kind'] == 'scoped_attribute_unresolved'
    permission = audit['field_permissions'][0]
    assert permission['unresolved_graph'] is True
    assert permission['reason'] == 'edge_repair_changed_node_inventory'
    assert permission['vertex_identity_remap']['reason'] == reason


def test_direction_only_scope_does_not_gain_edge_replacement_or_id_rebinding_permission():
    from graph_semantic_pipeline import _scope_repair

    previous_graph, proposed_graph = readings()
    proposed_graph['edges'][0]['id'] = previous_graph['edges'][0]['id']
    proposed_graph['edges'][0].update(direction='forward', weight=77)
    previous = {'body_text': '', 'graphs': [previous_graph], 'uncertainties': []}
    proposed = {'body_text': '不能采用', 'graphs': [proposed_graph], 'uncertainties': []}
    result, audit = _scope_repair(previous, proposed, [
        {'scope': 'graph', 'graph_id': 'G1', 'field': 'direction', 'edge_ids': ['old']}])
    assert result['graphs'] == previous['graphs']
    permission = audit['field_permissions'][0]
    assert permission['mode'] == 'edge_fields'
    assert permission['unresolved_edge_ids'] == ['old']
    assert 'vertex_identity_remap' not in permission


def test_scoped_repair_does_not_borrow_exact_labels_from_a_different_panel():
    from graph_semantic_pipeline import _scope_repair

    previous_graph, proposed_graph = readings()
    proposed_graph['id'] = 'G2'
    previous = {'body_text': '', 'graphs': [previous_graph], 'uncertainties': []}
    proposed = {'body_text': '', 'graphs': [proposed_graph], 'uncertainties': []}
    result, audit = _scope_repair(previous, proposed, [
        {'scope': 'graph', 'graph_id': 'G1', 'field': 'edges'}])
    assert result['graphs'] == previous['graphs']
    assert audit['missing_graph_ids'] == ['G1']
    assert result['uncertainties'] and audit['field_permissions'] == []
