import copy

import pytest

from dmate_math_tools import register_math_tools
from dmate_tool_registry import ToolContext, ToolRegistry


SHA = 'c'*64


def edge(eid, a, b, directed=False, **extra):
    return {'id': eid, 'from': a, 'to': b,
            'direction': 'forward' if directed else 'undirected',
            'status': 'accepted', 'multiplicity': 1, **extra}


def graph(edges=None, *, directed=False, multigraph=True, vertices=('a', 'b'), **extra):
    return {'id': 'G1', 'vertices': [{'id': x, 'label': x} for x in vertices],
            'edges': edges if edges is not None else [edge('e1', 'a', 'b', directed)],
            'directed': directed, 'multigraph': multigraph, 'weighted': False,
            'complete': True, 'uncertain_edges': [], **extra}


@pytest.fixture
def registry():
    return register_math_tools(ToolRegistry())


def ctx(record=None, *, draft=False, math_inputs=None):
    data = {'draft_graphs' if draft else 'confirmed_graphs': {'G1': record or graph()}}
    if math_inputs is not None:
        data['confirmed_math_inputs'] = math_inputs
    return ToolContext(source_sha256=SHA, data=data)


def call(registry, name, arguments=None, *, context=None, role='solver'):
    return registry.call(name, arguments or {'graph_id': 'G1'}, role=role, context=context or ctx())


def test_draft_audit_is_useful_before_confirmation_and_never_changes_ocr(registry):
    record = graph(complete=False)
    record['edges'][0]['status'] = 'pending'
    before = copy.deepcopy(record)
    context = ctx(record, draft=True)
    result = call(registry, 'graph.structure_audit', context=context, role='structure_review')
    assert result['ok']
    assert result['result']['consistent'] is True
    assert result['result']['input_confirmed'] is False
    assert result['result']['advisory_only'] and not result['result']['may_confirm_ocr']
    assert result['result']['pending_edge_count'] == 1
    assert record == before and record['complete'] is False
    denied = call(registry, 'graph.adjacency_matrix', context=context)
    assert denied['error']['code'] == 'unknown_graph'


@pytest.mark.parametrize('change', [
    {'complete': False}, {'uncertain_edges': ['unresolved_arrow']},
    {'edges': [edge('e1', 'a', 'b', status='pending')]},
])
def test_solver_requires_confirmed_graph_even_if_model_requests_calculation(registry, change):
    result = call(registry, 'graph.walk_count', {'graph_id': 'G1', 'source': 'a', 'target': 'b', 'length': 1},
                  context=ctx(graph(**change)))
    assert result['error']['code'] == 'unconfirmed_graph'


def test_model_arguments_cannot_supply_an_alternate_graph(registry):
    result = call(registry, 'graph.adjacency_matrix', {'graph_id': 'G1', 'graph': graph()})
    assert result['error']['code'] == 'invalid_arguments'


def test_parallel_edges_loops_adjacency_walks_and_euler_preserve_instances(registry):
    record = graph([edge('ab1', 'a', 'b'), edge('ab2', 'a', 'b'), edge('loop', 'a', 'a')])
    before = copy.deepcopy(record)
    context = ctx(record)
    matrix = call(registry, 'graph.adjacency_matrix', context=context)
    assert matrix['result']['matrix'] == [[1, 2], [2, 0]]
    assert matrix['result']['diagonal_convention'] == 'one_per_loop'
    walks = call(registry, 'graph.walk_count', {'graph_id': 'G1', 'source': 'a', 'target': 'a', 'length': 2}, context=context)
    assert walks['result']['count'] == 5
    zero = call(registry, 'graph.walk_count', {'graph_id': 'G1', 'source': 'a', 'target': 'a', 'length': 0}, context=context)
    assert zero['result']['count'] == 1
    audit = call(registry, 'graph.structure_audit', context=context, role='structure_review')['result']
    assert audit['degrees'][0]['degree'] == 4
    euler = call(registry, 'graph.euler', context=context)['result']
    assert euler['has_eulerian_circuit'] and len(euler['trail']) == 3
    assert {e['edge_id'] for e in euler['trail']} == {'ab1', 'ab2', 'loop'}
    assert before == record


def test_reciprocal_arcs_are_not_parallel_and_direction_is_preserved(registry):
    record = graph([edge('ab', 'a', 'b', True), edge('ba', 'b', 'a', True)], directed=True, multigraph=False)
    context = ctx(record)
    audit = call(registry, 'graph.structure_audit', context=context, role='structure_review')
    assert audit['result']['consistent'] and not audit['result']['issues']
    assert call(registry, 'graph.adjacency_matrix', context=context)['result']['matrix'] == [[0, 1], [1, 0]]
    euler = call(registry, 'graph.euler', context=context)['result']
    assert euler['has_eulerian_circuit']
    assert {(x['from'], x['to'], x['edge_id']) for x in euler['trail']} == {('a', 'b', 'ab'), ('b', 'a', 'ba')}


def test_structural_audit_reports_invalid_endpoint_duplicate_ids_and_flags(registry):
    record = graph([edge('e1', 'a', 'b'), edge('e1', 'b', 'z')], multigraph=False, complete=False)
    result = call(registry, 'graph.structure_audit', context=ctx(record, draft=True), role='structure_review')
    assert result['ok'] and not result['result']['consistent']
    codes = {x['code'] for x in result['result']['issues']}
    assert {'duplicate_edge_id', 'unknown_endpoint'} <= codes
    assert result['result']['degrees'] is None
    simple = graph([edge('e1', 'a', 'b'), edge('e2', 'a', 'b')], multigraph=False)
    result = call(registry, 'graph.structure_audit', context=ctx(simple), role='structure_review')
    assert 'parallel_edges_in_simple_graph' in {x['code'] for x in result['result']['issues']}


def test_unknown_direction_and_aggregated_multiplicity_are_not_solved(registry):
    for item in (edge('e1', 'a', 'b', direction='unknown'), edge('e1', 'a', 'b', multiplicity=2)):
        result = call(registry, 'graph.adjacency_matrix', context=ctx(graph([item])))
        assert result['error']['code'] == 'inconsistent_graph'


def test_euler_isolate_convention_is_explicit_and_wrong_start_rejected(registry):
    context = ctx(graph([edge('e1', 'a', 'b')], vertices=('a', 'b', 'c')))
    strict = call(registry, 'graph.euler', context=context)['result']
    assert not strict['has_eulerian_trail']
    relaxed = call(registry, 'graph.euler', {'graph_id': 'G1', 'ignore_isolated': True}, context=context)['result']
    assert relaxed['has_eulerian_trail'] and relaxed['isolated_vertices'] == ['c']
    directed = ctx(graph([edge('ab', 'a', 'b', True)], directed=True))
    invalid = call(registry, 'graph.euler', {'graph_id': 'G1', 'start_vertex': 'b'}, context=directed)
    assert invalid['error']['code'] == 'invalid_start_vertex'


def test_graph_and_walk_limits_are_enforced(registry):
    large = graph([], vertices=tuple(str(i) for i in range(101)))
    result = call(registry, 'graph.adjacency_matrix', context=ctx(large))
    assert result['error']['code'] == 'graph_capacity_or_shape'
    result = call(registry, 'graph.walk_count', {'graph_id': 'G1', 'source': 'a', 'target': 'b', 'length': 65})
    assert result['error']['code'] == 'invalid_arguments'


def test_integral_json_numbers_follow_the_integer_schema_contract(registry):
    walks = call(registry, 'graph.walk_count', {'graph_id': 'G1', 'source': 'a', 'target': 'a', 'length': 2.0})
    assert walks['ok'] and walks['result']['count'] == 1 and type(walks['result']['length']) is int
    power = call(registry, 'math.matrix', {'input_id': 'M', 'operation': 'power', 'exponent': 2.0},
                 context=ctx(math_inputs=matrix_input([[2]])))
    assert power['ok'] and power['result']['matrix'] == [[4]]


def matrix_input(matrix, **extra):
    return {'M': {'confirmed': True, 'kind': 'matrix', 'matrix': matrix, **extra}}


def test_exact_matrix_inverse_decimal_multiplication_and_rank(registry):
    record = matrix_input([[1, 2], [3, 4]])
    before = copy.deepcopy(record)
    context = ctx(math_inputs=record)
    det = call(registry, 'math.matrix', {'input_id': 'M', 'operation': 'determinant'}, context=context)
    assert det['result']['scalar'] == -2
    inv = call(registry, 'math.matrix', {'input_id': 'M', 'operation': 'inverse'}, context=context)
    assert inv['result']['matrix'] == [[-2, 1], [{'numerator': 3, 'denominator': 2}, {'numerator': -1, 'denominator': 2}]]
    rank = call(registry, 'math.matrix', {'input_id': 'M', 'operation': 'rank'}, context=context)
    assert rank['result']['rank'] == 2
    assert before == record
    decimal = ctx(math_inputs=matrix_input([[0.1]], other=[[3]]))
    product = call(registry, 'math.matrix', {'input_id': 'M', 'operation': 'multiply'}, context=decimal)
    assert product['result']['matrix'] == [[{'numerator': 3, 'denominator': 10}]]


def test_rref_power_and_singular_matrix(registry):
    context = ctx(math_inputs=matrix_input([[1, 2], [2, 4]]))
    reduced = call(registry, 'math.matrix', {'input_id': 'M', 'operation': 'rref'}, context=context)
    assert reduced['result']['matrix'] == [[1, 2], [0, 0]]
    assert reduced['result']['pivot_columns'] == [0]
    invalid = call(registry, 'math.matrix', {'input_id': 'M', 'operation': 'inverse'}, context=context)
    assert invalid['error']['code'] == 'singular_matrix'
    power = call(registry, 'math.matrix', {'input_id': 'M', 'operation': 'power', 'exponent': 0}, context=context)
    assert power['result']['matrix'] == [[1, 0], [0, 1]]


@pytest.mark.parametrize('cell', [
    '__import__("os").system("echo MUST_NOT_RUN")', '1/2', True,
    float('nan'), float('inf'), {'numerator': 1, 'denominator': 0}, 1_000_001,
])
def test_matrix_rejects_strings_code_nonfinite_and_unbounded_numbers(registry, cell, monkeypatch):
    import os
    monkeypatch.setattr(os, 'system', lambda *_: pytest.fail('code execution is forbidden'))
    result = call(registry, 'math.matrix', {'input_id': 'M', 'operation': 'determinant'},
                  context=ctx(math_inputs=matrix_input([[cell]])))
    assert not result['ok'] and result['error']['code'] == 'invalid_matrix_number'


def test_matrix_capacity_shape_and_unconfirmed_inputs(registry):
    context = ctx(math_inputs=matrix_input([[1]*9 for _ in range(9)]))
    assert call(registry, 'math.matrix', {'input_id': 'M', 'operation': 'inverse'}, context=context)['error']['code'] == 'exact_matrix_capacity'
    context = ctx(math_inputs=matrix_input([[1, 2], [3]]))
    assert call(registry, 'math.matrix', {'input_id': 'M', 'operation': 'rank'}, context=context)['error']['code'] == 'matrix_capacity_or_shape'
    context = ctx(math_inputs={'M': {'kind': 'matrix', 'confirmed': False, 'matrix': [[1]]}})
    assert call(registry, 'math.matrix', {'input_id': 'M', 'operation': 'rank'}, context=context)['error']['code'] == 'unconfirmed_math_input'
    assert call(registry, 'math.matrix', {'input_id': 'M', 'operation': 'rank', 'matrix': [[1]]}, context=context)['error']['code'] == 'invalid_arguments'


P = {'op': 'symbol', 'name': 'p'}
Q = {'op': 'symbol', 'name': 'q'}


def logic_context(ast):
    return ctx(math_inputs={'L': {'kind': 'logic', 'confirmed': True, 'ast': ast}})


def test_boolean_ast_tautology_contradiction_and_truth_table(registry):
    tautology = {'op': 'or', 'args': [P, {'op': 'not', 'arg': P}]}
    result = call(registry, 'math.logic', {'input_id': 'L', 'operation': 'classify'}, context=logic_context(tautology))
    assert result['result']['tautology'] and result['result']['satisfiable']
    contradiction = {'op': 'and', 'args': [P, {'op': 'not', 'arg': P}]}
    result = call(registry, 'math.logic', {'input_id': 'L', 'operation': 'classify'}, context=logic_context(contradiction))
    assert result['result']['contradiction'] and not result['result']['satisfiable']
    implication = {'op': 'implies', 'left': P, 'right': Q}
    result = call(registry, 'math.logic', {'input_id': 'L', 'operation': 'truth_table'}, context=logic_context(implication))
    rows = result['result']['rows']
    assert len(rows) == 4
    assert [r['value'] for r in rows] == [True, True, False, True]
    evaluated = call(registry, 'math.logic', {'input_id': 'L', 'operation': 'evaluate', 'assignment': {'p': True, 'q': False}}, context=logic_context(implication))
    assert evaluated['result']['value'] is False


@pytest.mark.parametrize('ast', [
    '__import__("os").system("MUST_NOT_RUN")',
    {'op': 'eval', 'value': '1+1'},
    {'op': 'symbol', 'name': '__import__("os")'},
    {'op': 'const', 'value': 'False'},
    {'op': 'not', 'arg': P, 'code': 'unexpected'},
])
def test_logic_rejects_expression_strings_unknown_operators_and_extra_fields(registry, ast):
    result = call(registry, 'math.logic', {'input_id': 'L', 'operation': 'classify'}, context=logic_context(ast))
    assert not result['ok'] and result['result'] is None


def test_logic_variable_limit_and_exact_assignment_schema(registry):
    many = {'op': 'and', 'args': [
        {'op': 'or', 'args': [{'op': 'symbol', 'name': f'p{i}'} for i in range(8)]},
        {'op': 'symbol', 'name': 'p8'},
    ]}
    result = call(registry, 'math.logic', {'input_id': 'L', 'operation': 'classify'}, context=logic_context(many))
    assert result['error']['code'] == 'logic_variable_limit'
    missing = call(registry, 'math.logic', {'input_id': 'L', 'operation': 'evaluate', 'assignment': {}}, context=logic_context(P))
    assert missing['error']['code'] == 'incomplete_logic_assignment'
    wrong = call(registry, 'math.logic', {'input_id': 'L', 'operation': 'evaluate', 'assignment': {'p': 'false'}}, context=logic_context(P))
    assert wrong['error']['code'] == 'invalid_arguments'
