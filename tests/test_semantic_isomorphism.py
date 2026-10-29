"""Scoped, bounded NetworkX checks for confirmed unnamed graph pairs."""
import copy
from collections import Counter

import pytest

import graph_semantic_tools as tools


def graph(gid, pairs, *, size=6, directed=False):
    return {'id': gid, 'name': gid, 'directed': directed, 'weighted': False, 'complete': True,
            'vertices': [{'id': f'{gid}_v{i}', 'label': None,
                          'display_label': chr(0x2460 + i), 'x': (i + 1) / (size + 1), 'y': .2}
                         for i in range(size)],
            'edges': [{'id': f'e{i}', 'from': f'{gid}_v{a}', 'to': f'{gid}_v{b}',
                       'direction': 'forward' if directed else 'undirected', 'weight': None,
                       'status': 'accepted'} for i, (a, b) in enumerate(pairs)]}


def compare(left, right, **request):
    return tools.prepare_semantic_math({'body_text': '判断两图是否同构', 'graphs': [left, right]},
        {'operation': 'isomorphism', 'graph_id': left['id'], 'other_graph_id': right['id'], **request})


def verify_mapping(left, right, result):
    assert result['status'] == 'computed', result
    facts = result['facts']
    assert facts['isomorphic'] is True
    mapping = {item['from']: item['to'] for item in facts['mapping']}
    assert set(mapping) == {v['id'] for v in left['vertices']}
    assert set(mapping.values()) == {v['id'] for v in right['vertices']}
    directed = left['directed']
    normalize = lambda a, b: (a, b) if directed else tuple(sorted((a, b)))
    assert Counter(normalize(mapping[e['from']], mapping[e['to']]) for e in left['edges']) == Counter(
        normalize(e['from'], e['to']) for e in right['edges'])


def test_unnamed_different_drawings_get_scoped_bijection_without_label_matching():
    left = graph('left', [(i, (i + 1) % 6) for i in range(6)])
    right = graph('right', [(0, 2), (2, 4), (4, 1), (1, 3), (3, 5), (5, 0)])
    for i, vertex in enumerate(right['vertices']):
        vertex.update(display_label=f'临时{i + 1}', x=.8 - i / 10, y=.7)
    before = copy.deepcopy((left, right))
    result = compare(left, right)
    verify_mapping(left, right, result)
    assert (left, right) == before
    assert result['facts']['left_graph_id'] == 'left'
    assert result['facts']['right_graph_id'] == 'right'
    assert result['facts']['labels_used'] is False
    assert result['facts']['weights_used'] is False
    assert any(row['tool'] == 'graph.semantic_math' and row.get('library') == 'networkx'
               for row in result['tool_audit'])


def test_equal_vertex_edge_and_degree_counts_are_not_enough_for_isomorphism():
    cycle = graph('cycle', [(i, (i + 1) % 6) for i in range(6)])
    triangles = graph('triangles', [(0, 1), (1, 2), (2, 0), (3, 4), (4, 5), (5, 3)])
    result = compare(cycle, triangles)
    assert result['status'] == 'computed'
    assert result['facts']['isomorphic'] is False
    assert result['facts']['mapping'] == []


def test_parallel_edges_self_loops_and_isolates_are_preserved():
    left = graph('left', [(0, 1), (0, 1), (0, 0)], size=3)
    right = graph('right', [(2, 0), (2, 0), (2, 2)], size=3)
    verify_mapping(left, right, compare(left, right))
    right['edges'][-1].update(to='right_v0')
    result = compare(left, right)
    assert result['status'] == 'computed' and result['facts']['isomorphic'] is False


def test_directed_isomorphism_keeps_arrow_directions():
    outward = graph('left', [(0, 1), (0, 2)], size=3, directed=True)
    renamed = graph('right', [(2, 0), (2, 1)], size=3, directed=True)
    verify_mapping(outward, renamed, compare(outward, renamed))
    inward = graph('right', [(1, 0), (2, 0)], size=3, directed=True)
    result = compare(outward, inward)
    assert result['status'] == 'computed' and result['facts']['isomorphic'] is False


@pytest.mark.parametrize('mutation,code', [
    (lambda g: g.update(complete=False), 'incomplete_semantic_snapshot'),
    (lambda g: g['edges'][0].update(direction='unknown'), 'mixed_or_unknown_direction_not_supported'),
    (lambda g: g['edges'][0].update(direction='forward'), 'mixed_or_unknown_direction_not_supported'),
    (lambda g: g['edges'][0].update(weight=0), 'isomorphism_weights_not_supported'),
    (lambda g: g['edges'][0].update(weight='x'), 'isomorphism_weights_not_supported'),
    (lambda g: g.update(weighted=True), 'isomorphism_weights_not_supported'),
])
@pytest.mark.parametrize('side', [0, 1])
def test_uncertainty_and_weights_never_become_a_nonisomorphic_verdict(mutation, code, side):
    pair = [graph('left', [(0, 1), (1, 2)], size=3), graph('right', [(0, 1), (1, 2)], size=3)]
    mutation(pair[side])
    result = compare(*pair)
    assert result['status'] == 'not_applicable'
    assert result['facts'] is None
    assert result['issues'][0]['code'] == code


@pytest.mark.parametrize('limit,value', [('MAX_ISOMORPHISM_STATES', 0), ('ISOMORPHISM_SECONDS', 0.)])
def test_search_budget_exhaustion_is_unknown_not_false(monkeypatch, limit, value):
    monkeypatch.setattr(tools, limit, value)
    result = compare(graph('left', [(0, 1)], size=2), graph('right', [(0, 1)], size=2))
    assert result['status'] == 'not_applicable' and result['facts'] is None
    assert result['issues'][0]['code'] == 'isomorphism_search_limit'


@pytest.mark.parametrize('size,pairs', [(33, [(0, 1)]), (2, [(0, 1)] * 129)])
def test_capacity_limits_do_not_produce_false(size, pairs):
    result = compare(graph('left', pairs, size=size), graph('right', pairs, size=size))
    assert result['status'] == 'not_applicable' and result['facts'] is None
    assert result['issues'][0]['code'] == 'isomorphism_capacity'


def test_registry_schema_requires_explicit_distinct_graph_pair():
    pair = [graph('left', [(0, 1)], size=2), graph('right', [(0, 1)], size=2)]
    for request in ({'other_graph_id': None}, {'other_graph_id': 'missing'},
                    {'other_graph_id': 'left'}, {'weighted': True}):
        result = compare(*pair, **request)
        assert result['status'] == 'not_applicable' and result['facts'] is None


def test_caller_cancellation_is_not_hidden_by_registry():
    class Cancelled(Exception):
        pass

    class Budget:
        def check(self):
            raise Cancelled('stop')

    with pytest.raises(Cancelled):
        tools.prepare_semantic_math({'body_text': '', 'graphs': []},
            {'operation': 'isomorphism', 'graph_id': 'left', 'other_graph_id': 'right'}, budget=Budget())
