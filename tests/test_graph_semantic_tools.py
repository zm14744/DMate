"""Real NetworkX calculations over synthetic semantics, with no image/model."""
import copy
import time

import networkx as nx
import pytest

import graph_semantic_tools as semantic_tools
from dmate_tool_registry import ToolContext, ToolRegistry
from graph_semantic_tools import inspect_semantic_graphs, prepare_semantic_math


def edge(eid, start, end, direction='undirected', **attrs):
    return {'id': eid, 'from': start, 'to': end, 'direction': direction, **attrs}


def document(edges=None, nodes=('a', 'b', 'c'), **extra):
    graph = {'id': 'G', 'name': 'G₁', 'vertices': [{'id': n, 'label': n} for n in nodes],
             'edges': edges or [], 'complete': True, **extra}
    return {'body_text': 'Keep v₁ and V₁ distinct', 'graphs': [graph], 'complete': True, 'reviewed': True}


def summary(doc):
    result = inspect_semantic_graphs(doc)
    assert not result['issues'], result['issues']
    assert result['tool_audit'][0]['executed'] is True
    assert result['tool_audit'][0]['library'] == 'networkx'
    return result['summaries'][0]


def compute(doc, operation, **arguments):
    return prepare_semantic_math(doc, {'operation': operation, 'graph_id': 'G', **arguments})


def test_actual_multigraph_preserves_loops_parallel_isolates_and_attributes(monkeypatch):
    calls = []
    real = nx.MultiGraph.add_edge
    def observed(self, *args, **kwargs):
        calls.append(copy.deepcopy(kwargs))
        return real(self, *args, **kwargs)
    monkeypatch.setattr(nx.MultiGraph, 'add_edge', observed)
    doc = document([edge('red', 'a', 'b', color='red', edge_label='e₁', weight=0, style='dashed'),
                    edge('blue', 'a', 'b', color='blue', edge_label='e₂', weight='x'),
                    edge('loop', 'a', 'a')], multigraph=False)
    before = copy.deepcopy(doc)
    result = summary(doc)
    assert doc == before
    assert len(calls) == 3 and len({c['key'] for c in calls}) == 3
    assert calls[0]['color'] == 'red' and calls[0]['style'] == 'dashed' and calls[0]['weight'] == 0
    assert result['degrees'] == [{'vertex_id': 'a', 'degree': 4}, {'vertex_id': 'b', 'degree': 2}, {'vertex_id': 'c', 'degree': 0}]
    assert result['self_loop_edge_ids'] == ['loop']
    assert result['parallel_groups'][0]['edge_ids'] == ['red', 'blue']
    assert result['isolated_vertices'] == ['c']
    assert result['invariants'] == {'edge_instances_preserved': True, 'degree_sum': 6, 'expected_degree_sum': 6}
    assert result['image_fidelity_certified'] is False


def test_reverse_arcs_are_not_same_direction_parallel_and_loop_in_out_are_one_each():
    result = summary(document([edge('ab', 'a', 'b', 'forward'), edge('ba', 'b', 'a', 'forward'),
                               edge('aa', 'a', 'a', 'forward')]))
    assert result['parallel_groups'] == []
    assert result['directed_degrees'] == [
        {'vertex_id': 'a', 'in_degree': 2, 'out_degree': 2},
        {'vertex_id': 'b', 'in_degree': 1, 'out_degree': 1},
        {'vertex_id': 'c', 'in_degree': 0, 'out_degree': 0}]
    assert result['invariants']['in_degree_sum'] == result['invariants']['out_degree_sum'] == 3


def test_mixed_unknown_and_partial_weight_do_not_poison_other_facts():
    doc = document([edge('ab', 'a', 'b', 'forward', weight='θ'),
                    edge('bc', 'b', 'c', 'undirected', weight=None),
                    edge('ac', 'a', 'c', 'unknown', weight=2)], weighted=True, directed=True)
    result = summary(doc)
    assert result['direction_mode'] == 'unknown' and result['directed_degrees'] is None
    assert result['underlying_components'] == [['a', 'b', 'c']]
    assert result['weight_coverage'] == {'numeric': 1, 'missing': 1, 'symbolic_or_non_numeric': 1}
    assert compute(doc, 'degrees')['status'] == 'computed'
    answer = compute(doc, 'shortest_path', source='a', target='c')
    assert answer['status'] == 'not_applicable'
    assert answer['issues'][0]['code'] == 'mixed_or_unknown_direction_not_supported'


@pytest.mark.parametrize('mutation,code', [
    (lambda g: g['vertices'].append({'id': 'a'}), 'duplicate_vertex_id'),
    (lambda g: g['edges'].append(edge('ab', 'b', 'c')), 'duplicate_edge_id'),
    (lambda g: g['edges'][0].update(to='A'), 'unknown_endpoint'),
    (lambda g: g['edges'][0].update(direction={}), 'invalid_edge_direction'),
    (lambda g: g['edges'][0].update(weight=float('inf')), 'invalid_weight'),
    (lambda g: g['edges'][0].update(weight=True), 'invalid_weight'),
    (lambda g: g['edges'][0].update(multiplicity=2), 'aggregated_multiplicity_requires_instances'),
    (lambda g: g.update(vertex_count=18), 'declared_count_mismatch'),
    (lambda g: g.update(directed='false'), 'invalid_graph_type'),
])
def test_real_input_errors_are_local_and_never_repaired(mutation, code):
    doc = document([edge('ab', 'a', 'b')])
    mutation(doc['graphs'][0])
    good = copy.deepcopy(document([edge('ok', 'x', 'y')], nodes=('x', 'y'))['graphs'][0])
    good['id'] = 'other'
    doc['graphs'].append(good)
    before = copy.deepcopy(doc)
    result = inspect_semantic_graphs(doc)
    assert any(i['code'] == code for i in result['issues'])
    assert all(i.get('message') for i in result['issues'])
    assert result['summaries'][0]['degrees'] is None
    assert result['summaries'][1]['structural_valid'] and result['summaries'][1]['edge_count'] == 1
    assert doc == before


def test_case_subscript_labels_and_unknown_null_direction_are_preserved():
    doc = document([edge('r', 'a', 'A', None)], nodes=('a', 'A'), directed=True)
    doc['graphs'][0]['vertices'][0]['label'] = 'v₁'
    doc['graphs'][0]['vertices'][1]['label'] = 'V₁'
    result = summary(doc)
    assert result['vertex_labels'] == [{'id': 'a', 'label': 'v₁'}, {'id': 'A', 'label': 'V₁'}]
    assert result['direction_mode'] == 'unknown' and result['directed_degrees'] is None


def test_no_math_request_does_not_even_call_networkx(monkeypatch):
    monkeypatch.setattr(nx, 'MultiGraph', lambda *a, **kw: pytest.fail('unsolicited calculation'))
    result = prepare_semantic_math(document())
    assert result['status'] == 'not_requested' and result['tool_audit'] == []


def test_explicit_bipartite_and_components_dont_delete_legal_loops_or_isolates():
    doc = document([edge('loop', 'a', 'a')])
    before = copy.deepcopy(doc)
    result = compute(doc, 'bipartite')
    assert result['status'] == 'computed' and result['facts']['is_bipartite'] is False
    assert compute(doc, 'components')['facts']['isolated_vertices'] == ['b', 'c']
    assert doc == before


def test_weighted_shortest_path_returns_the_specific_parallel_instance():
    doc = document([edge('slow', 'a', 'b', 'forward', weight=9, color='red'),
                    edge('fast', 'a', 'b', 'forward', weight='0.1', color='blue'),
                    edge('end', 'b', 'c', 'forward', weight='0.2')])
    before = copy.deepcopy(doc)
    result = compute(doc, 'shortest_path', source='a', target='c', weighted=True)
    assert result['status'] == 'computed'
    assert result['facts']['edge_ids'] == ['fast', 'end']
    assert result['facts']['distance'] == '0.3'
    assert doc == before
    reverse = compute(doc, 'shortest_path', source='c', target='a', weighted=True)
    assert reverse['facts']['path_exists'] is False


def test_unweighted_path_keeps_zero_weight_and_edge_label_out_of_cost_inference():
    doc = document([edge('one', 'a', 'b', weight=0, edge_label='999'), edge('two', 'b', 'c', weight='x')])
    result = compute(doc, 'shortest_path', source='a', target='c', weighted=False)
    assert result['facts']['distance'] == 2
    assert compute(doc, 'shortest_path', source='a', target='c', weighted=True)['status'] == 'not_applicable'
    omitted = compute(doc, 'shortest_path', source='a', target='c')
    assert omitted['status'] == 'not_applicable'
    assert omitted['issues'][0]['code'] == 'path_weight_mode_required'


def test_mst_preserves_parallel_instances_without_rewriting_the_input():
    doc = document([edge('heavy', 'a', 'b', weight=10), edge('light', 'a', 'b', weight=1),
                    edge('end', 'b', 'c', weight=2), edge('long', 'a', 'c', weight=9),
                    edge('loop', 'a', 'a', weight=-10)])
    before = copy.deepcopy(doc)
    result = compute(doc, 'minimum_spanning_tree')
    assert result['status'] == 'computed' and result['facts']['total_weight'] == 3
    assert set(result['facts']['edge_ids']) == {'light', 'end'}
    assert doc == before


@pytest.mark.parametrize('doc,code', [
    (document([edge('ab', 'a', 'b', 'forward', weight=1)]), 'mst_requires_undirected_graph'),
    (document([edge('ab', 'a', 'b', weight='z')]), 'complete_numeric_weights_required'),
    (document([edge('ab', 'a', 'b', weight=1)]), 'connected_nonempty_graph_required_for_mst'),
    (document([edge('ab', 'a', 'b', weight=1)], complete=False), 'incomplete_semantic_snapshot'),
])
def test_inapplicable_mst_abstains_with_specific_reason(doc, code):
    result = compute(doc, 'minimum_spanning_tree')
    assert result['status'] == 'not_applicable' and result['issues'][0]['code'] == code
    assert next(a for a in result['tool_audit'] if a.get('library') and a['tool'] == 'graph.semantic_math')['executed'] is False


def test_negative_cycle_is_not_returned_as_finite_shortest_path():
    doc = document([edge('ab', 'a', 'b', 'forward', weight=-2),
                    edge('ba', 'b', 'a', 'forward', weight=1), edge('bc', 'b', 'c', 'forward', weight=1)])
    result = compute(doc, 'shortest_path', source='a', target='c', weighted=True)
    assert result['status'] == 'not_applicable' and result['issues'][0]['code'] == 'reachable_negative_cycle'
    assert next(a for a in result['tool_audit'] if a.get('library') and a['tool'] == 'graph.semantic_math')['executed'] is True


def test_unknown_operation_and_injected_graph_or_code_are_rejected():
    for request in ({'operation': 'eval', 'graph_id': 'G'},
                    {'operation': 'degrees', 'graph_id': 'G', 'graph': {}},
                    {'operation': 'shortest_path', 'graph_id': 'G', 'weighted': 'yes'}):
        result = prepare_semantic_math(document(), request)
        assert result['status'] == 'not_applicable'
        assert result['tool_audit'][-1]['error_code'] == 'invalid_arguments'
        assert not result['tool_audit'][-1]['handler_started']


def test_cancellation_is_not_converted_to_an_invariant_success():
    error = RuntimeError('cancelled')
    class Budget:
        def check(self):
            raise error
    for call in (lambda: inspect_semantic_graphs(document(), budget=Budget()),
                 lambda: prepare_semantic_math(document(), {'operation': 'degrees', 'graph_id': 'G'}, budget=Budget())):
        with pytest.raises(RuntimeError) as caught:
            call()
        assert caught.value is error


def test_public_apis_really_call_registry_with_roles_schema_and_private_document(monkeypatch):
    observed = []
    original = ToolRegistry.call
    def spy(self, name, arguments, *, role, context=None):
        observed.append((name, copy.deepcopy(arguments), role, context))
        return original(self, name, arguments, role=role, context=context)
    monkeypatch.setattr(ToolRegistry, 'call', spy)
    doc = document([edge('ab', 'a', 'b')])
    inspected = inspect_semantic_graphs(doc)
    calculated = compute(doc, 'degrees')
    assert [(row[0], row[2]) for row in observed] == [
        ('graph.semantic_inspect', 'semantic_review'), ('graph.semantic_math', 'solver')]
    assert observed[0][1] == {} and observed[1][1] == {'operation': 'degrees', 'graph_id': 'G'}
    assert all(row[3].data['document'] is doc for row in observed)
    for result in (inspected, calculated):
        event = result['tool_audit'][-1]
        assert event['call_id'] and event['input_digest'] and event['result_digest']
        assert event['handler_started'] and event['handler_finished'] and event['status'] == 'success'
        assert event['timeout_mode'] == 'cooperative'
    count = len(observed)
    assert prepare_semantic_math(doc)['status'] == 'not_requested'
    assert len(observed) == count


def test_registry_roles_and_request_schema_reject_bypasses():
    registry = semantic_tools._build_registry()
    context = ToolContext(data={'document': document(), 'budget': None, 'control': {'error': None}})
    denied = registry.call('graph.semantic_math', {'operation': 'degrees', 'graph_id': 'G'},
                           role='semantic_review', context=context)
    assert denied['error']['code'] == 'role_not_allowed' and not denied['audit']['handler_started']
    invalid = registry.call('graph.semantic_inspect', {'graphs': []}, role='semantic_review', context=context)
    assert invalid['error']['code'] == 'invalid_arguments'
    assert registry.describe(role='semantic_review')[0]['timeout_seconds'] == 5.


def test_cancellation_inside_registered_handler_is_rethrown_unchanged():
    error = RuntimeError('one-shot cancellation')
    class Budget:
        deadline = time.monotonic() + 60
        calls = 0
        def check(self):
            self.calls += 1
            if self.calls == 3:
                raise error
    with pytest.raises(RuntimeError) as caught:
        inspect_semantic_graphs(document([edge('ab', 'a', 'b')]), budget=Budget())
    assert caught.value is error


def test_local_registry_timeout_is_explicit_and_never_image_success(monkeypatch):
    original = ToolRegistry.call
    def expired(self, name, arguments, *, role, context=None):
        from dataclasses import replace
        return original(self, name, arguments, role=role,
                        context=replace(context, deadline_monotonic=time.monotonic() - 1))
    monkeypatch.setattr(ToolRegistry, 'call', expired)
    result = inspect_semantic_graphs(document())
    assert result['summaries'] == [] and result['issues']
    assert result['tool_audit'][-1]['status'] == 'timeout'
    assert not result['tool_audit'][-1]['handler_started']


def test_adjacency_counts_instances_and_each_mixed_edge_direction_without_type_conversion():
    doc = document([edge('u1', 'a', 'b'), edge('u2', 'a', 'b'),
                    edge('arc', 'a', 'b', 'forward'), edge('exit', 'b', 'c', 'forward'),
                    edge('loop', 'a', 'a', weight=99)], directed=False, weighted=True)
    before = copy.deepcopy(doc)
    result = compute(doc, 'adjacency_matrix')
    assert result['status'] == 'computed'
    assert result['facts']['vertex_order'] == ['a', 'b', 'c']
    assert result['facts']['matrix'] == [[1, 3, 0], [2, 0, 1], [0, 0, 0]]
    assert result['facts']['direction_mode'] == 'mixed'
    assert result['facts']['entry_meaning'] == 'edge_instance_count'
    assert result['facts']['weights_used'] is False
    assert doc == before


@pytest.mark.parametrize('source,target,length,count', [
    ('a', 'c', 2, 3), ('b', 'a', 1, 2), ('c', 'b', 1, 0),
    ('a', 'a', 2, 7), ('a', 'a', 0, 1), ('a', 'b', 0, 0),
])
def test_walk_count_is_edge_distinct_and_honours_loops_length_zero_and_mixed_direction(source, target, length, count):
    doc = document([edge('u1', 'a', 'b'), edge('u2', 'a', 'b'),
                    edge('arc', 'a', 'b', 'forward'), edge('exit', 'b', 'c', 'forward'),
                    edge('loop', 'a', 'a')])
    result = compute(doc, 'walk_count', source=source, target=target, length=length)
    assert result['status'] == 'computed' and result['facts']['count'] == count
    assert result['facts']['walk_definition'] == 'edge_distinct_walks_repetition_allowed'


@pytest.mark.parametrize('length', [-1, 65, True, '2', 2.5, 2.0])
def test_walk_length_is_an_explicit_bounded_integer(length):
    result = compute(document(), 'walk_count', source='a', target='b', length=length)
    assert result['status'] == 'not_applicable'
    assert result['issues'][0]['code'] == 'invalid_math_request'


@pytest.mark.parametrize('operation,arguments', [
    ('adjacency_matrix', {}), ('walk_count', {'source': 'a', 'target': 'b', 'length': 1}),
])
def test_transition_calculations_never_turn_unknown_direction_into_undirected(operation, arguments):
    result = compute(document([edge('u', 'a', 'b', 'unknown')], directed=False), operation, **arguments)
    assert result['status'] == 'not_applicable'
    assert result['issues'][0]['code'] == 'unknown_edge_direction_not_supported'


def test_euler_trail_returns_every_parallel_instance_and_loop_once():
    doc = document([edge('first', 'a', 'b'), edge('second', 'a', 'b'), edge('loop', 'a', 'a')], nodes=('a', 'b'))
    before = copy.deepcopy(doc)
    result = compute(doc, 'euler', start_vertex='a')
    assert result['status'] == 'computed' and result['facts']['has_eulerian_circuit']
    trail = result['facts']['trail']
    assert {item['edge_id'] for item in trail} == {'first', 'second', 'loop'} and len(trail) == 3
    assert trail[0]['from'] == trail[-1]['to'] == 'a'
    assert all(left['to'] == right['from'] for left, right in zip(trail, trail[1:]))
    assert doc == before


def test_euler_directed_start_and_opposite_arcs_are_not_collapsed():
    doc = document([edge('ab1', 'a', 'b', 'forward'), edge('ab2', 'a', 'b', 'forward'),
                    edge('ba', 'b', 'a', 'forward'), edge('bb', 'b', 'b', 'forward')], nodes=('a', 'b'))
    result = compute(doc, 'euler', start_vertex='a')
    assert result['status'] == 'computed'
    assert result['facts']['has_eulerian_trail'] and not result['facts']['has_eulerian_circuit']
    assert [item['edge_id'] for item in result['facts']['trail']].count('ba') == 1
    assert result['facts']['trail'][-1]['to'] == 'b'
    invalid = compute(doc, 'euler', start_vertex='b')
    assert invalid['status'] == 'not_applicable' and invalid['issues'][0]['code'] == 'invalid_euler_start'


def test_euler_isolated_vertices_have_an_explicit_convention_not_silent_deletion():
    doc = document([edge('ab1', 'a', 'b'), edge('ab2', 'a', 'b')])
    all_nodes = compute(doc, 'euler')['facts']
    ignored = compute(doc, 'euler', ignore_isolated=True)['facts']
    assert not all_nodes['has_eulerian_trail'] and all_nodes['vertex_convention'] == 'all_declared_vertices'
    assert ignored['has_eulerian_circuit'] and ignored['isolated_vertices'] == ['c']
    assert ignored['vertex_convention'] == 'ignore_isolated'
    disconnected = document([edge('ab', 'a', 'b'), edge('cd', 'c', 'd')], nodes=('a', 'b', 'c', 'd'))
    assert not compute(disconnected, 'euler')['facts']['has_eulerian_trail']


@pytest.mark.parametrize('direction', ['undirected', 'unknown'])
def test_euler_abstains_instead_of_forcing_mixed_or_unknown_graph_type(direction):
    doc = document([edge('ab', 'a', 'b', 'forward'), edge('ba', 'b', 'a', direction)], directed=True)
    result = compute(doc, 'euler')
    assert result['status'] == 'not_applicable'
    assert result['issues'][0]['code'] == 'mixed_or_unknown_direction_not_supported'


def test_precise_decimal_weights_keep_strict_path_order_and_exact_mst_sum():
    larger = '1.0000000000000000000000000001'
    tiny = '0.00000000000000000000000000001'
    doc = document([edge('direct', 'a', 'b', 'forward', weight=larger),
                    edge('via', 'a', 'c', 'forward', weight='1'),
                    edge('end', 'c', 'b', 'forward', weight=tiny)])
    result = compute(doc, 'shortest_path', source='a', target='b', weighted=True)
    assert result['facts']['edge_ids'] == ['via', 'end']
    assert result['facts']['distance'] == '1.00000000000000000000000000001'
    assert result['facts']['arithmetic'] == 'exact_rational'
    for item in doc['graphs'][0]['edges']:
        item['direction'] = 'undirected'
    tree = compute(doc, 'minimum_spanning_tree')['facts']
    assert set(tree['edge_ids']) == {'via', 'end'}
    assert tree['total_weight'] == '1.00000000000000000000000000001'


def test_weight_bound_is_exact_and_missing_declared_weights_never_default_to_one():
    doc = document([edge('ab', 'a', 'b', weight='1000000000000.0000000000000000001')], nodes=('a', 'b'))
    assert compute(doc, 'shortest_path', source='a', target='b', weighted=True)['status'] == 'not_applicable'
    doc['graphs'][0].update(weighted=True)
    doc['graphs'][0]['edges'][0]['weight'] = None
    assert compute(doc, 'shortest_path', source='a', target='b')['issues'][0]['code'] == 'path_weight_mode_required'
    assert compute(doc, 'shortest_path', source='a', target='b', weighted=True)['issues'][0]['code'] == 'complete_numeric_weights_required'


@pytest.mark.parametrize('pending', ['unresolved_edges', 'unresolved_vertices', 'uncertain_edges', 'edge_status'])
def test_pending_content_blocks_full_graph_calculation_and_changes_audit_digest(pending):
    doc = document([edge('ab', 'a', 'b', weight=1)], nodes=('a', 'b'))
    before_digest = inspect_semantic_graphs(doc)['tool_audit'][0]['input_digest']
    if pending == 'edge_status':
        doc['graphs'][0]['edges'][0]['status'] = 'uncertain'
    else:
        doc['graphs'][0][pending] = [{'reason': 'not yet resolved'}]
    for operation, args in [('shortest_path', {'source': 'a', 'target': 'b', 'weighted': True}),
                            ('adjacency_matrix', {}), ('walk_count', {'source': 'a', 'target': 'b', 'length': 1}),
                            ('euler', {})]:
        result = compute(doc, operation, **args)
        assert result['issues'][0]['code'] == 'incomplete_semantic_snapshot'
        assert result['input_complete'] is False
        assert result['tool_audit'][0]['input_digest'] != before_digest
    assert compute(doc, 'degrees')['facts']['degrees'][0]['degree'] == 1
