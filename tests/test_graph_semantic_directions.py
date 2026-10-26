"""Direction-instance contracts, without private diagrams or model execution."""
import copy

import pytest

from graph_semantic_directions import build_direction_task, apply_direction_reading


def document():
    return {'body_text': '求顶点v₅的出度。', 'uncertainties': [], 'graphs': [{
        'id': 'G', 'name': '(a)', 'directed': True, 'weighted': True,
        'vertices': [{'id': 'a', 'label': 'v₁', 'position': '左上'},
                     {'id': 'b', 'label': 'V₂'}, {'id': 'c', 'label': None}],
        'edges': [{'id': 'e1', 'from': 'a', 'to': 'b', 'direction': 'forward',
                   'weight': 0, 'edge_label': 'e₁', 'color': 'blue', 'style': 'dashed',
                   'path': [[.1, .2], [.8, .3]], 'evidence': ['kept']},
                  {'id': 'e2', 'from': 'a', 'to': 'b', 'direction': 'forward', 'edge_label': 'e₂'},
                  {'id': 'e3', 'from': 'b', 'to': 'a', 'direction': 'forward', 'weight': -2},
                  {'id': 'loop', 'from': 'a', 'to': 'a', 'direction': 'forward'}]},
        {'id': 'U', 'directed': False, 'vertices': [{'id': 'x', 'label': 'x'}, {'id': 'y', 'label': 'y'}],
         'edges': [{'id': 'u1', 'from': 'x', 'to': 'y', 'direction': 'undirected'}]}]}


def reading(draft):
    return {'graphs': [{'id': 'G', 'edges': [
        {key: edge[key] for key in ('id', 'from', 'to', 'direction')}
        for edge in draft['graphs'][0]['edges']]}], 'uncertainties': []}


def test_task_hides_current_direction_without_merging_parallel_arcs_or_loops():
    draft = document()
    before = copy.deepcopy(draft)
    task = build_direction_task(draft)
    assert draft == before
    assert [g['id'] for g in task['graphs']] == ['G']
    graph = task['graphs'][0]
    assert set(graph) == {'id', 'name', 'vertices', 'edges'}
    assert graph['vertices'][0] == {'id': 'a', 'label': 'v₁', 'position': '左上'}
    assert [edge['id'] for edge in graph['edges']] == ['e1', 'e2', 'e3', 'loop']
    assert [edge['endpoints'] for edge in graph['edges']] == [['a', 'b']] * 3 + [['a', 'a']]
    assert all(not {'from', 'to', 'direction', 'path', 'evidence'} & set(edge) for edge in graph['edges'])
    reversed_draft = copy.deepcopy(draft)
    for edge in reversed_draft['graphs'][0]['edges']:
        edge['from'], edge['to'] = edge['to'], edge['from']
    assert build_direction_task(reversed_draft) == task


def test_two_same_direction_arcs_opposite_arc_and_loop_remain_distinct_instances():
    draft = document()
    response = reading(draft)
    for edge in response['graphs'][0]['edges'][:3]:
        edge['from'], edge['to'] = edge['to'], edge['from']
    result = apply_direction_reading(draft, response)
    assert result['issues'] == [] and result['audit']['all_requested_edges_confirmed']
    assert len(result['audit']['changes']) == 3
    edges = result['document']['graphs'][0]['edges']
    assert [(e['from'], e['to']) for e in edges] == [('b', 'a'), ('b', 'a'), ('a', 'b'), ('a', 'a')]
    for old, new in zip(draft['graphs'][0]['edges'], edges):
        assert {k: v for k, v in old.items() if k not in ('from', 'to', 'direction')} == {
            k: v for k, v in new.items() if k not in ('from', 'to', 'direction')}
    assert result['document']['body_text'] == draft['body_text']
    assert result['document']['graphs'][0]['vertices'] == draft['graphs'][0]['vertices']
    assert result['document']['graphs'][1] == draft['graphs'][1]
    assert draft == document()


def test_missing_ids_are_stable_and_do_not_collide_with_explicit_instance_ids():
    draft = document()
    del draft['graphs'][0]['edges'][0]['id']
    draft['graphs'][0]['edges'][1]['id'] = 'direction_edge_1'
    task = build_direction_task(draft)
    assert task == build_direction_task(draft)
    ids = [e['id'] for e in task['graphs'][0]['edges']]
    assert ids[:2] == ['direction_edge_1_1', 'direction_edge_1']
    response = {'graphs': [{'id': 'G', 'edges': [{
        'id': edge['id'], 'from': edge['endpoints'][0], 'to': edge['endpoints'][1], 'direction': 'forward'}
        for edge in task['graphs'][0]['edges']]}]}
    result = apply_direction_reading(draft, response)
    assert [e['id'] for e in result['document']['graphs'][0]['edges']] == ids
    assert len(result['audit']['generated_edge_ids']) == 1
    assert 'id' not in draft['graphs'][0]['edges'][0]


@pytest.mark.parametrize('response', [None, [], 'bad', {}, {'graphs': None}, {'graphs': [None]}, {'graphs': []}])
def test_bad_or_empty_response_cannot_erase_existing_document(response):
    draft = document()
    result = apply_direction_reading(draft, response)
    assert result['document'] == draft
    assert result['issues'] and not result['audit']['all_requested_edges_confirmed']


@pytest.mark.parametrize('mutation,kind', [
    ('missing', 'missing_direction_edges'), ('extra', 'unexpected_direction_edge'),
    ('duplicate', 'duplicate_direction_edge'), ('pair', 'direction_endpoints_mismatch'),
    ('loop_pair', 'direction_endpoints_mismatch'), ('value', 'invalid_direction_value'),
    ('unknown', 'direction_uncertain'), ('unknown_half_pair', 'direction_endpoints_mismatch'),
    ('duplicate_graph', 'duplicate_direction_graph'), ('extra_graph', 'unexpected_direction_graph'),
])
def test_incomplete_or_ambiguous_instances_keep_their_known_data(mutation, kind):
    draft = document()
    response = reading(draft)
    edges = response['graphs'][0]['edges']
    if mutation == 'missing':
        edges.pop(0)
    elif mutation == 'extra':
        edges.append({'id': 'ghost', 'from': 'a', 'to': 'b', 'direction': 'forward'})
    elif mutation == 'duplicate':
        edges.append({**edges[0], 'from': 'b', 'to': 'a'})
    elif mutation == 'pair':
        edges[0]['to'] = 'c'
    elif mutation == 'loop_pair':
        edges[-1].update({'from': 'b', 'to': 'b'})
    elif mutation == 'value':
        edges[0]['direction'] = 'undirected'
    elif mutation == 'unknown':
        edges[0] = {'id': 'e1', 'direction': 'unknown'}
    elif mutation == 'unknown_half_pair':
        edges[0] = {'id': 'e1', 'direction': 'unknown', 'from': 'a'}
    elif mutation == 'duplicate_graph':
        response['graphs'].append(copy.deepcopy(response['graphs'][0]))
    elif mutation == 'extra_graph':
        response['graphs'].append({'id': 'phantom', 'edges': []})
    result = apply_direction_reading(draft, response)
    assert result['document'] == draft
    assert kind in {issue['kind'] for issue in result['issues']}
    assert not result['audit']['all_requested_edges_confirmed']
    assert all(issue['scope'] == 'graph' and issue.get('graph_id') for issue in result['issues'])


def test_model_text_node_and_attribute_rewrites_are_ignored():
    draft = document()
    response = reading(draft)
    response['body_text'] = 'changed question'
    response['graphs'][0].update(vertices=[], name='renamed', directed=False)
    response['graphs'][0]['edges'][0].update(weight=999, edge_label='wrong', color='red', style='solid')
    result = apply_direction_reading(draft, response)
    assert result['document'] == draft and result['issues'] == []
    assert result['audit']['ignored_response_fields']


def test_only_unknown_edges_and_directed_graph_edges_are_selected():
    draft = document()
    draft['graphs'][0]['directed'] = False
    draft['graphs'][0]['edges'][0]['direction'] = 'unknown'
    draft['graphs'][0]['edges'][1]['direction'] = 'undirected'
    assert [e['id'] for e in build_direction_task(draft)['graphs'][0]['edges']] == ['e1', 'e3', 'loop']


def test_stale_directed_graph_flag_cannot_promote_known_undirected_edge_to_arrow_task():
    draft = document()
    draft['graphs'][0]['edges'][1]['direction'] = 'undirected'
    assert draft['graphs'][0]['directed'] is True
    assert [e['id'] for e in build_direction_task(draft)['graphs'][0]['edges']] == ['e1', 'e3', 'loop']


def test_unknown_uncertainty_scope_does_not_create_edges_or_hide_unresolved_status():
    draft = document()
    response = reading(draft)
    response['uncertainties'] = [{'graph_id': 'G', 'edge_ids': ['ghost'], 'message': 'uncertain'}]
    result = apply_direction_reading(draft, response)
    assert result['document'] == draft
    assert result['issues'][0]['kind'] == 'invalid_direction_uncertainty_scope'


def test_duplicate_original_edge_ids_do_not_select_one_instance_as_authoritative():
    draft = document()
    draft['graphs'][0]['edges'][1]['id'] = 'e1'
    result = apply_direction_reading(draft, {'graphs': []})
    assert result['document'] == draft
    assert 'duplicate_original_direction_edge_id' in {issue['kind'] for issue in result['issues']}
