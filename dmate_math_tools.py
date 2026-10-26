"""Bounded, read-only graph and symbolic tools for DMate's role workflow.

Graph calculations consume application-confirmed snapshots, never graph tables
from model tool arguments. Structure review may inspect a draft but is advisory
and cannot promote OCR completeness. SymPy inputs are confirmed numerical arrays
or an explicit Boolean AST: no expression parser, eval, or string sympification.
"""
from __future__ import annotations

import copy
import itertools
import math
import re
from collections import Counter
from decimal import Decimal

from dmate_tool_registry import ToolFailure, ToolSpec


VERSION = '1.0.0'
MAX_VERTICES = 100
MAX_EDGES = 400
MAX_WALK_LENGTH = 64
MAX_MATRIX_SIDE = 12
MAX_EXACT_MATRIX_SIDE = 8
MAX_LOGIC_VARIABLES = 8
MAX_LOGIC_NODES = 96
_IDENTIFIER = {'type': 'string', 'minLength': 1, 'maxLength': 64}
_INTEGER = {'type': 'integer', 'minimum': 0}
_BOOL = {'type': 'boolean'}
_ID_LIST = {'type': 'array', 'items': _IDENTIFIER, 'maxItems': MAX_VERTICES}


def _object(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required),
            'additionalProperties': False}


def _nx():
    try:
        import networkx
    except ImportError:
        raise ToolFailure('missing_dependency') from None
    return networkx


def _sympy():
    try:
        import sympy
    except ImportError:
        raise ToolFailure('missing_dependency') from None
    return sympy


def _record(context, graph_id, *, draft=False):
    context.check_deadline()
    store = context.data.get('draft_graphs' if draft else 'confirmed_graphs', {})
    if draft and not store:
        store = context.data.get('confirmed_graphs', {})
    if isinstance(store, dict):
        value = store.get(graph_id)
    elif isinstance(store, (list, tuple)):
        matches = [item for item in store if isinstance(item, dict) and item.get('id') == graph_id]
        if len(matches) > 1:
            raise ToolFailure('ambiguous_graph_id')
        value = matches[0] if matches else None
    else:
        value = None
    if not isinstance(value, dict) or value.get('id') != graph_id:
        raise ToolFailure('unknown_graph')
    vertices, edges = value.get('vertices'), value.get('edges')
    if (not isinstance(vertices, list) or not 1 <= len(vertices) <= MAX_VERTICES or
            not isinstance(edges, list) or len(edges) > MAX_EDGES):
        raise ToolFailure('graph_capacity_or_shape')
    # Derive separate NetworkX objects and analysis arrays. Never write back to
    # this snapshot, its complete flag, edge table, status, or source geometry.
    fields = ('id', 'vertices', 'edges', 'directed', 'multigraph', 'weighted', 'complete',
              'uncertain_edges', 'vertex_count', 'confirmed_edge_count')
    return copy.deepcopy({key: value[key] for key in fields if key in value})


def _graph_issues(graph, context):
    vertices, edges = graph.get('vertices'), graph.get('edges')
    if (not isinstance(vertices, list) or not 1 <= len(vertices) <= MAX_VERTICES or
            not isinstance(edges, list) or len(edges) > MAX_EDGES):
        raise ToolFailure('graph_capacity_or_shape')
    issues = []
    ids, edge_ids = [], set()
    for vertex in vertices:
        context.check_deadline()
        vid = vertex.get('id') if isinstance(vertex, dict) else None
        if not isinstance(vid, str) or not 1 <= len(vid) <= 64:
            issues.append({'code': 'invalid_vertex_id'})
        elif vid in ids:
            issues.append({'code': 'duplicate_vertex_id', 'vertex_id': vid})
        else:
            ids.append(vid)
    for field in ('directed', 'multigraph', 'weighted'):
        if type(graph.get(field)) is not bool:
            issues.append({'code': 'unknown_'+field})
    pairs = Counter()
    for edge in edges:
        context.check_deadline()
        if not isinstance(edge, dict):
            issues.append({'code': 'invalid_edge_record'})
            continue
        eid = edge.get('id')
        if not isinstance(eid, str) or not 1 <= len(eid) <= 64:
            issues.append({'code': 'invalid_edge_id'})
            eid = None
        elif eid in edge_ids:
            issues.append({'code': 'duplicate_edge_id', 'edge_id': eid})
        else:
            edge_ids.add(eid)
        where = {'edge_id': eid} if eid else {}
        u, v = edge.get('from'), edge.get('to')
        if not isinstance(u, str) or not isinstance(v, str) or u not in ids or v not in ids:
            issues.append({'code': 'unknown_endpoint', **where})
            continue
        direction = edge.get('direction')
        if direction not in ('forward', 'undirected'):
            issues.append({'code': 'unknown_edge_direction', **where})
        elif ((graph.get('directed') is True and direction != 'forward') or
              (graph.get('directed') is False and direction != 'undirected')):
            issues.append({'code': 'direction_conflict', **where})
        if edge.get('multiplicity', 1) != 1 or type(edge.get('multiplicity', 1)) is not int:
            issues.append({'code': 'aggregated_edge_not_supported', **where})
        pair = (u, v) if direction == 'forward' else tuple(sorted((u, v)))
        pairs[pair] += 1
        if graph.get('multigraph') is False and u == v:
            issues.append({'code': 'self_loop_in_simple_graph', **where})
        has_weight = edge.get('weight') is not None and str(edge.get('weight')).strip() != ''
        if graph.get('weighted') is False and has_weight:
            issues.append({'code': 'weight_in_unweighted_graph', **where})
        if graph.get('weighted') is True and not has_weight:
            issues.append({'code': 'missing_weight', **where})
    if graph.get('multigraph') is False and any(n > 1 for n in pairs.values()):
        issues.append({'code': 'parallel_edges_in_simple_graph'})
    for field, expected in (('vertex_count', len(vertices)), ('confirmed_edge_count', len(edges))):
        if field in graph and (type(graph[field]) is not int or graph[field] != expected):
            issues.append({'code': field+'_mismatch'})
    return ids, edges, issues


def _build_graph(graph, ids, edges, context):
    nx = _nx()
    # Preserve edge instances even when a draft declares the wrong graph type.
    result = nx.MultiDiGraph() if graph['directed'] else nx.MultiGraph()
    result.add_nodes_from(ids)
    for edge in edges:
        context.check_deadline()
        result.add_edge(edge['from'], edge['to'], key=edge['id'], edge_id=edge['id'])
    return result


def _confirmed(arguments, context):
    graph = _record(context, arguments['graph_id'])
    if (graph.get('complete') is not True or graph.get('uncertain_edges') or
            not isinstance(graph.get('edges'), list) or
            any(not isinstance(edge, dict) or edge.get('status') != 'accepted'
                for edge in graph.get('edges', []))):
        raise ToolFailure('unconfirmed_graph')
    ids, edges, issues = _graph_issues(graph, context)
    if issues:
        raise ToolFailure('inconsistent_graph')
    return graph, ids, edges, _build_graph(graph, ids, edges, context)


def graph_structure_audit(arguments, *, context):
    """Inspect drafts without creating, deleting, confirming or correcting edges."""
    graph = _record(context, arguments['graph_id'], draft=True)
    ids, edges, issues = _graph_issues(graph, context)
    confirmed = (graph.get('complete') is True and not graph.get('uncertain_edges') and
                 all(isinstance(e, dict) and e.get('status') == 'accepted' for e in edges))
    result = {'graph_id': graph['id'], 'advisory_only': True, 'may_confirm_ocr': False,
              'input_confirmed': confirmed, 'consistent': not issues,
              'vertex_count': len(graph['vertices']), 'edge_count': len(edges),
              'issues': issues[:100], 'issues_truncated': len(issues) > 100,
              'pending_edge_count': sum(not isinstance(e, dict) or e.get('status') != 'accepted' for e in edges),
              'degrees': None, 'isolated_vertices': None,
              'weak_components': None, 'strong_components': None}
    if not issues:
        nx = _nx()
        actual = _build_graph(graph, ids, edges, context)
        result['degrees'] = [dict(vertex_id=vid, degree=int(actual.degree(vid)),
            in_degree=int(actual.in_degree(vid)) if actual.is_directed() else None,
            out_degree=int(actual.out_degree(vid)) if actual.is_directed() else None) for vid in ids]
        result['isolated_vertices'] = list(nx.isolates(actual))
        result['weak_components'] = (nx.number_weakly_connected_components(actual)
                                     if actual.is_directed() else nx.number_connected_components(actual))
        if actual.is_directed():
            result['strong_components'] = nx.number_strongly_connected_components(actual)
    return result


def _adjacency(ids, edges, directed, context):
    indices = {vid: i for i, vid in enumerate(ids)}
    matrix = [[0]*len(ids) for _ in ids]
    for edge in edges:
        context.check_deadline()
        u, v = indices[edge['from']], indices[edge['to']]
        matrix[u][v] += 1
        if not directed and u != v:
            matrix[v][u] += 1
    return matrix


def graph_adjacency_matrix(arguments, *, context):
    graph, ids, edges, _ = _confirmed(arguments, context)
    return {'graph_id': graph['id'], 'vertex_order': ids,
            'matrix': _adjacency(ids, edges, graph['directed'], context),
            'entry_meaning': 'edge_instance_count', 'diagonal_convention': 'one_per_loop'}


def graph_walk_count(arguments, *, context):
    graph, ids, edges, _ = _confirmed(arguments, context)
    # JSON Schema accepts integral JSON numbers such as 2.0 as integers.
    source, target, length = arguments['source'], arguments['target'], int(arguments['length'])
    if source not in ids or target not in ids:
        raise ToolFailure('unknown_vertex')
    counts = {vid: int(vid == source) for vid in ids}
    for _ in range(length):
        context.check_deadline()
        after = dict.fromkeys(ids, 0)
        for edge in edges:
            context.check_deadline()
            u, v = edge['from'], edge['to']
            after[v] += counts[u]
            if not graph['directed'] and u != v:
                after[u] += counts[v]
        counts = after
    return {'graph_id': graph['id'], 'source': source, 'target': target,
            'length': length, 'count': counts[target],
            'walk_definition': 'edge_distinct_walks_repetition_allowed',
            'loop_step_convention': 'one_per_loop'}


def graph_euler(arguments, *, context):
    nx = _nx()
    graph, ids, edges, actual = _confirmed(arguments, context)
    isolated = list(nx.isolates(actual))
    ignore = arguments.get('ignore_isolated', False)
    analysed = actual.subgraph([v for v in ids if v not in isolated]).copy() if ignore else actual
    start = arguments.get('start_vertex')
    if start is not None and start not in ids:
        raise ToolFailure('unknown_vertex')
    context.check_deadline()
    if analysed.number_of_nodes() == 0:
        circuit = path = True  # Explicit empty-edge convention after ignoring isolates.
        trail = []
    else:
        circuit = bool(nx.is_eulerian(analysed))
        path = bool(nx.has_eulerian_path(analysed))
        trail = []
        if start is not None and (start not in analysed or not nx.has_eulerian_path(analysed, source=start)):
            raise ToolFailure('invalid_start_vertex')
        if path and edges:
            for u, v, key in nx.eulerian_path(analysed, source=start, keys=True):
                context.check_deadline()
                trail.append({'edge_id': key, 'from': u, 'to': v})
    return {'graph_id': graph['id'], 'has_eulerian_circuit': circuit,
            'has_eulerian_trail': path, 'trail': trail, 'isolated_vertices': isolated,
            'vertex_convention': 'ignore_isolated' if ignore else 'all_declared_vertices'}


def _math_input(context, input_id, kind):
    context.check_deadline()
    store = context.data.get('confirmed_math_inputs', {})
    record = store.get(input_id) if isinstance(store, dict) else None
    if not isinstance(record, dict) or record.get('confirmed') is not True:
        raise ToolFailure('unconfirmed_math_input')
    if record.get('kind') != kind:
        raise ToolFailure('math_input_kind_mismatch')
    return record


def _logic_expression(node, sp, state, context, depth=0):
    context.check_deadline()
    state['nodes'] += 1
    if state['nodes'] > MAX_LOGIC_NODES or depth > 12 or type(node) is not dict:
        raise ToolFailure('logic_capacity_or_shape')
    op = node.get('op')
    if op == 'symbol':
        if set(node) != {'op', 'name'} or not isinstance(node.get('name'), str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,15}', node['name']):
            raise ToolFailure('invalid_logic_symbol')
        name = node['name']
        if name not in state['symbols']:
            state['symbols'][name] = sp.Symbol(name)
        if len(state['symbols']) > MAX_LOGIC_VARIABLES:
            raise ToolFailure('logic_variable_limit')
        return state['symbols'][name]
    if op == 'const':
        if set(node) != {'op', 'value'} or type(node.get('value')) is not bool:
            raise ToolFailure('invalid_logic_constant')
        return sp.true if node['value'] else sp.false
    if op == 'not':
        if set(node) != {'op', 'arg'}:
            raise ToolFailure('invalid_logic_ast')
        return sp.Not(_logic_expression(node['arg'], sp, state, context, depth+1), evaluate=False)
    if op in ('and', 'or', 'xor'):
        if set(node) != {'op', 'args'} or type(node.get('args')) is not list or not 2 <= len(node['args']) <= 8:
            raise ToolFailure('invalid_logic_ast')
        values = [_logic_expression(n, sp, state, context, depth+1) for n in node['args']]
        return {'and': sp.And, 'or': sp.Or, 'xor': sp.Xor}[op](*values, evaluate=False)
    if op in ('implies', 'iff'):
        if set(node) != {'op', 'left', 'right'}:
            raise ToolFailure('invalid_logic_ast')
        left = _logic_expression(node['left'], sp, state, context, depth+1)
        right = _logic_expression(node['right'], sp, state, context, depth+1)
        return (sp.Implies if op == 'implies' else sp.Equivalent)(left, right, evaluate=False)
    raise ToolFailure('unsupported_logic_operator')


def math_logic(arguments, *, context):
    record = _math_input(context, arguments['input_id'], 'logic')
    sp = _sympy()
    state = {'nodes': 0, 'symbols': {}}
    expression = _logic_expression(record.get('ast'), sp, state, context)
    variables = sorted(state['symbols'])
    operation = arguments['operation']
    if operation == 'evaluate':
        assignment = arguments.get('assignment')
        if not isinstance(assignment, dict) or set(assignment) != set(variables):
            raise ToolFailure('incomplete_logic_assignment')
        context.check_deadline()
        value = bool(expression.xreplace({state['symbols'][k]: sp.true if v else sp.false
                                          for k, v in assignment.items()}))
        return {'input_id': arguments['input_id'], 'operation': operation,
                'variables': variables, 'value': value}
    if 'assignment' in arguments:
        raise ToolFailure('unexpected_logic_assignment')
    rows = []
    for values in itertools.product((False, True), repeat=len(variables)):
        context.check_deadline()
        assignment = dict(zip(variables, values))
        value = bool(expression.xreplace({state['symbols'][k]: sp.true if v else sp.false
                                          for k, v in assignment.items()}))
        rows.append({'assignment': assignment, 'value': value})
    result = {'input_id': arguments['input_id'], 'operation': operation, 'variables': variables,
              'satisfiable': any(r['value'] for r in rows),
              'tautology': all(r['value'] for r in rows),
              'contradiction': not any(r['value'] for r in rows)}
    if operation == 'truth_table':
        result['rows'] = rows
    return result


def _number(value, sp):
    if type(value) is int and abs(value) <= 1_000_000:
        return sp.Integer(value)
    if type(value) is float and math.isfinite(value) and abs(value) <= 1_000_000:
        numerator, denominator = Decimal(str(value)).as_integer_ratio()
        if max(abs(numerator).bit_length(), denominator.bit_length()) <= 64:
            return sp.Rational(numerator, denominator)
    if type(value) is dict and set(value) == {'numerator', 'denominator'}:
        n, d = value['numerator'], value['denominator']
        if type(n) is int and type(d) is int and abs(n) <= 1_000_000 and 1 <= abs(d) <= 1_000_000:
            return sp.Rational(n, d)
    raise ToolFailure('invalid_matrix_number')


def _matrix(value, sp, context):
    if type(value) is not list or not 1 <= len(value) <= MAX_MATRIX_SIDE:
        raise ToolFailure('matrix_capacity_or_shape')
    if type(value[0]) is not list or not 1 <= len(value[0]) <= MAX_MATRIX_SIDE:
        raise ToolFailure('matrix_capacity_or_shape')
    width = len(value[0])
    rows = []
    for row in value:
        context.check_deadline()
        if type(row) is not list or len(row) != width:
            raise ToolFailure('matrix_capacity_or_shape')
        rows.append([_number(cell, sp) for cell in row])
    return sp.Matrix(rows)


def _scalar(value):
    if value.is_Rational is not True:
        raise ToolFailure('non_rational_matrix_result')
    n, d = int(value.p), int(value.q)
    if max(abs(n).bit_length(), d.bit_length()) > 4096:
        raise ToolFailure('matrix_result_capacity')
    return n if d == 1 else {'numerator': n, 'denominator': d}


def _matrix_result(matrix, context):
    rows = []
    for i in range(matrix.rows):
        context.check_deadline()
        rows.append([_scalar(matrix[i, j]) for j in range(matrix.cols)])
    return rows


def math_matrix(arguments, *, context):
    record = _math_input(context, arguments['input_id'], 'matrix')
    sp = _sympy()
    matrix = _matrix(record.get('matrix'), sp, context)
    operation = arguments['operation']
    if operation not in ('transpose', 'multiply') and max(matrix.shape) > MAX_EXACT_MATRIX_SIDE:
        raise ToolFailure('exact_matrix_capacity')
    if operation != 'power' and 'exponent' in arguments:
        raise ToolFailure('unexpected_matrix_exponent')
    if operation in ('determinant', 'inverse', 'power') and matrix.rows != matrix.cols:
        raise ToolFailure('square_matrix_required')
    context.check_deadline()
    result = {'input_id': arguments['input_id'], 'operation': operation,
              'input_shape': [matrix.rows, matrix.cols], 'arithmetic': 'exact_rational'}
    try:
        if operation == 'determinant':
            result['scalar'] = _scalar(matrix.det())
        elif operation == 'rank':
            result['rank'] = int(matrix.rank())
        elif operation == 'inverse':
            result['matrix'] = _matrix_result(matrix.inv(), context)
        elif operation == 'rref':
            reduced, pivots = matrix.rref()
            result['matrix'] = _matrix_result(reduced, context)
            result['pivot_columns'] = list(pivots)
        elif operation == 'multiply':
            other = _matrix(record.get('other'), sp, context)
            if matrix.cols != other.rows:
                raise ToolFailure('matrix_shape_mismatch')
            result['matrix'] = _matrix_result(matrix*other, context)
        elif operation == 'transpose':
            result['matrix'] = _matrix_result(matrix.T, context)
        elif operation == 'power':
            if 'exponent' not in arguments:
                raise ToolFailure('matrix_exponent_required')
            result['matrix'] = _matrix_result(matrix**int(arguments['exponent']), context)
        else:
            raise ToolFailure('unsupported_matrix_operation')
    except sp.matrices.exceptions.NonInvertibleMatrixError:
        raise ToolFailure('singular_matrix') from None
    context.check_deadline()
    return result


_ISSUE = _object({'code': _IDENTIFIER, 'vertex_id': _IDENTIFIER, 'edge_id': _IDENTIFIER}, ('code',))
_DEGREE = _object({'vertex_id': _IDENTIFIER, 'degree': _INTEGER,
                   'in_degree': {'type': ['integer', 'null'], 'minimum': 0},
                   'out_degree': {'type': ['integer', 'null'], 'minimum': 0}},
                  ('vertex_id', 'degree', 'in_degree', 'out_degree'))
_COUNT_MATRIX = {'type': 'array', 'maxItems': MAX_VERTICES,
                 'items': {'type': 'array', 'maxItems': MAX_VERTICES, 'items': _INTEGER}}
_RATIONAL = {'oneOf': [
    {'type': 'integer'},
    _object({'numerator': {'type': 'integer'}, 'denominator': {'type': 'integer', 'minimum': 1}},
            ('numerator', 'denominator')),
]}
_RATIONAL_MATRIX = {'type': 'array', 'maxItems': MAX_MATRIX_SIDE,
                    'items': {'type': 'array', 'maxItems': MAX_MATRIX_SIDE, 'items': _RATIONAL}}
_ASSIGNMENT = {'type': 'object', 'maxProperties': MAX_LOGIC_VARIABLES,
               'propertyNames': {'pattern': '^[A-Za-z][A-Za-z0-9_]{0,15}$'},
               'additionalProperties': _BOOL}


def register_math_tools(registry):
    """Register six local tools; return the same registry for composition."""
    audit_output = _object({
        'graph_id': _IDENTIFIER, 'advisory_only': {'const': True}, 'may_confirm_ocr': {'const': False},
        'input_confirmed': _BOOL, 'consistent': _BOOL, 'vertex_count': _INTEGER, 'edge_count': _INTEGER,
        'issues': {'type': 'array', 'items': _ISSUE, 'maxItems': 100}, 'issues_truncated': _BOOL,
        'pending_edge_count': _INTEGER,
        'degrees': {'anyOf': [{'type': 'null'}, {'type': 'array', 'items': _DEGREE, 'maxItems': MAX_VERTICES}]},
        'isolated_vertices': {'anyOf': [{'type': 'null'}, _ID_LIST]},
        'weak_components': {'type': ['integer', 'null'], 'minimum': 0},
        'strong_components': {'type': ['integer', 'null'], 'minimum': 0},
    }, ('graph_id', 'advisory_only', 'may_confirm_ocr', 'input_confirmed', 'consistent',
        'vertex_count', 'edge_count', 'issues', 'issues_truncated', 'pending_edge_count',
        'degrees', 'isolated_vertices', 'weak_components', 'strong_components'))
    graph_args = _object({'graph_id': _IDENTIFIER}, ('graph_id',))
    specs = [
        ('graph.structure_audit', graph_structure_audit, graph_args, audit_output,
         ('structure_review',), 'Advisory consistency review of a private draft; never confirms OCR.'),
        ('graph.adjacency_matrix', graph_adjacency_matrix, graph_args,
         _object({'graph_id': _IDENTIFIER, 'vertex_order': _ID_LIST, 'matrix': _COUNT_MATRIX,
                  'entry_meaning': {'const': 'edge_instance_count'}, 'diagonal_convention': {'const': 'one_per_loop'}},
                 ('graph_id', 'vertex_order', 'matrix', 'entry_meaning', 'diagonal_convention')),
         ('structure_review', 'solver'), 'Exact adjacency counts of confirmed edge instances; ignores edge weights.'),
        ('graph.walk_count', graph_walk_count,
         _object({'graph_id': _IDENTIFIER, 'source': _IDENTIFIER, 'target': _IDENTIFIER,
                  'length': {'type': 'integer', 'minimum': 0, 'maximum': MAX_WALK_LENGTH}},
                 ('graph_id', 'source', 'target', 'length')),
         _object({'graph_id': _IDENTIFIER, 'source': _IDENTIFIER, 'target': _IDENTIFIER,
                  'length': _INTEGER, 'count': _INTEGER,
                  'walk_definition': {'const': 'edge_distinct_walks_repetition_allowed'},
                  'loop_step_convention': {'const': 'one_per_loop'}},
                 ('graph_id', 'source', 'target', 'length', 'count', 'walk_definition', 'loop_step_convention')),
         ('solver',), 'Counts fixed-length walks, allowing repeated vertices and edges; parallel edges are distinct.'),
        ('graph.euler', graph_euler,
         _object({'graph_id': _IDENTIFIER, 'ignore_isolated': _BOOL, 'start_vertex': _IDENTIFIER}, ('graph_id',)),
         _object({'graph_id': _IDENTIFIER, 'has_eulerian_circuit': _BOOL, 'has_eulerian_trail': _BOOL,
                  'trail': {'type': 'array', 'maxItems': MAX_EDGES,
                            'items': _object({'edge_id': _IDENTIFIER, 'from': _IDENTIFIER, 'to': _IDENTIFIER},
                                             ('edge_id', 'from', 'to'))},
                  'isolated_vertices': _ID_LIST,
                  'vertex_convention': {'enum': ['ignore_isolated', 'all_declared_vertices']}},
                 ('graph_id', 'has_eulerian_circuit', 'has_eulerian_trail', 'trail', 'isolated_vertices', 'vertex_convention')),
         ('solver',), 'Euler trail/circuit analysis of confirmed directed or undirected multigraphs; preserves edge IDs.'),
        ('math.logic', math_logic,
         _object({'input_id': _IDENTIFIER, 'operation': {'enum': ['classify', 'truth_table', 'evaluate']},
                  'assignment': _ASSIGNMENT}, ('input_id', 'operation')),
         _object({'input_id': _IDENTIFIER, 'operation': {'enum': ['classify', 'truth_table', 'evaluate']},
                  'variables': {'type': 'array', 'items': _IDENTIFIER, 'maxItems': MAX_LOGIC_VARIABLES},
                  'value': _BOOL, 'satisfiable': _BOOL, 'tautology': _BOOL, 'contradiction': _BOOL,
                  'rows': {'type': 'array', 'maxItems': 2**MAX_LOGIC_VARIABLES,
                           'items': _object({'assignment': _ASSIGNMENT, 'value': _BOOL}, ('assignment', 'value'))}},
                 ('input_id', 'operation', 'variables')),
         ('solver',), 'Boolean evaluation/truth tables from a confirmed structured AST, at most 8 variables; no text parser.'),
        ('math.matrix', math_matrix,
         _object({'input_id': _IDENTIFIER,
                  'operation': {'enum': ['determinant', 'rank', 'inverse', 'rref', 'multiply', 'transpose', 'power']},
                  'exponent': {'type': 'integer', 'minimum': -16, 'maximum': 16}}, ('input_id', 'operation')),
         _object({'input_id': _IDENTIFIER, 'operation': _IDENTIFIER,
                  'input_shape': {'type': 'array', 'minItems': 2, 'maxItems': 2, 'items': _INTEGER},
                  'arithmetic': {'const': 'exact_rational'}, 'scalar': _RATIONAL, 'matrix': _RATIONAL_MATRIX,
                  'rank': _INTEGER, 'pivot_columns': {'type': 'array', 'maxItems': MAX_MATRIX_SIDE, 'items': _INTEGER}},
                 ('input_id', 'operation', 'input_shape', 'arithmetic')),
         ('solver',), 'Exact rational matrix operations on confirmed arrays; bounded dimensions/numbers, no expressions.'),
    ]
    for name, handler, input_schema, output_schema, roles, description in specs:
        registry.register(ToolSpec(name=name, version=VERSION, description=description,
            input_schema=input_schema, output_schema=output_schema, allowed_roles=frozenset(roles),
            source_required=True, timeout_seconds=5.0), handler)
    return registry


__all__ = ['register_math_tools']
