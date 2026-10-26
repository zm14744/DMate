"""Read-only NetworkX checks/calculations over the shared semantic graph.

Neither graph invariants nor a successful calculation certify image reading.
The inspector does not solve a question.  Mathematical operations run only
through an explicit, bounded request over an application-held snapshot.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import time
from collections import Counter
from decimal import Decimal, InvalidOperation
from fractions import Fraction

from dmate_tool_registry import ToolContext, ToolRegistry, ToolSpec

VERSION = '2026-10-26-semantic-networkx-v2'
MAX_GRAPHS, MAX_VERTICES, MAX_EDGES = 64, 100, 300
MAX_WALK_LENGTH = 64
_EDGE_FIELDS = ('id', 'from', 'to', 'direction', 'weight', 'edge_label', 'color', 'style', 'multiplicity', 'status')
_OPERATIONS = frozenset(('degrees', 'components', 'bipartite', 'shortest_path', 'minimum_spanning_tree',
                         'adjacency_matrix', 'walk_count', 'euler'))
_DECIMAL = re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d{1,3})?\Z')
_MESSAGES = {
    'invalid_graph_inventory': '图结构必须提供顶点和边列表。',
    'invalid_or_duplicate_graph_id': '图的内部标识无效或重复。',
    'invalid_vertex_id': '顶点内部标识无效。',
    'duplicate_vertex_id': '同一图内的顶点内部标识重复。',
    'invalid_edge_id': '边的内部标识无效。',
    'duplicate_edge_id': '同一图内的边实例标识重复。',
    'unknown_endpoint': '边端点不能对应此图已列出的顶点。',
    'invalid_edge_record': '边记录必须是对象。',
    'invalid_edge_direction': '边方向字段不是支持的语义类型。',
    'invalid_graph_type': '图类型字段必须是布尔值或 unknown。',
    'invalid_weight': '权值必须是有限数值、文字或空值。',
    'invalid_edge_attribute': '边颜色与线型字段必须是文字或空值。',
    'invalid_edge_label': '印刷边名字段不是可读文本或数值。',
    'aggregated_multiplicity_requires_instances': '请保留每条重边的独立实例，不能用一个重数代替。',
    'declared_count_mismatch': '声明的数量与实际结构记录不一致。',
    'networkx_instance_invariant_failure': '程序内部的边实例数或度数总和不一致。',
    'networkx_unavailable': '本次 NetworkX 工具未能加载。',
    'graph_tool_capacity': '本次图工具输入超出有界计算容量。',
    'invalid_math_request': '本次数学计算请求不属于支持的明确操作。',
    'unknown_graph': '本次计算未找到唯一的图记录。',
    'incomplete_semantic_snapshot': '图结构尚未完整确认，暂不计算全图矩阵、通路、欧拉性质或生成树。',
    'mixed_or_unknown_direction_not_supported': '该算法需要明确且适用的全图方向类型。',
    'mst_requires_undirected_graph': '此最小生成树算法只适用于无向图。',
    'complete_numeric_weights_required': '本次带权计算需要每条边的有限数值权重。',
    'connected_nonempty_graph_required_for_mst': '此图为空或不连通，不存在覆盖全部顶点的生成树。',
    'unknown_path_endpoint': '路径起终点不能对应所选图的顶点。',
    'path_weight_mode_required': '图内含权值，请明确最短路按权值计算还是按边数计算。',
    'reachable_negative_cycle': '检测到可达负权环，不能给出有限最短距离。',
    'unknown_edge_direction_not_supported': '本次计算需要每条边的方向明确，不能将未知方向当无向边。',
    'invalid_euler_start': '指定起点不能作为该欧拉通路的起点。',
}


def _check(budget):
    if budget is not None:
        budget.check()


def _identifier(value):
    return isinstance(value, str) and 0 < len(value) <= 128 and bool(value.strip())


def _safe(value, depth=0):
    if value is None or type(value) in (bool, int):
        return value
    if isinstance(value, str):
        return value if len(value) <= 512 else {'text_prefix': value[:512],
            'sha256': hashlib.sha256(value.encode()).hexdigest(), 'length': len(value)}
    if isinstance(value, float):
        return value if math.isfinite(value) else {'invalid_number': str(value)}
    if depth > 4:
        return {'omitted': True}
    if isinstance(value, (list, tuple)):
        return [_safe(v, depth + 1) for v in value[:MAX_EDGES]]
    if isinstance(value, dict):
        return {str(k)[:128]: _safe(v, depth + 1) for k, v in list(value.items())[:24]}
    return {'invalid_type': type(value).__name__}


def _digest(graphs):
    rows = []
    for graph in graphs[:MAX_GRAPHS]:
        if not isinstance(graph, dict):
            rows.append(_safe(graph))
            continue
        row = {k: _safe(graph[k]) for k in ('id', 'name', 'directed', 'weighted', 'multigraph', 'complete',
                                         'unresolved_edges', 'unresolved_vertices', 'uncertain_edges')
               if k in graph}
        row['vertices'] = [_safe({k: n[k] for k in ('id', 'label') if k in n}) if isinstance(n, dict) else _safe(n)
                           for n in graph.get('vertices', [])[:MAX_VERTICES]] if isinstance(graph.get('vertices'), list) else None
        row['edges'] = [_safe({k: e[k] for k in _EDGE_FIELDS if k in e}) if isinstance(e, dict) else _safe(e)
                        for e in graph.get('edges', [])[:MAX_EDGES]] if isinstance(graph.get('edges'), list) else None
        rows.append(row)
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                     separators=(',', ':')).encode()).hexdigest()


def _issue(code, graph_id=None, **details):
    return {'scope': 'graph' if graph_id is not None else 'document', 'kind': code,
            'code': code, 'message': _MESSAGES.get(code, '程序结构检查需要核对该字段。'),
            **({'graph_id': graph_id} if graph_id is not None else {}),
            'may_confirm_ocr': False, **details}


def _numeric_weight(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    text = str(value).strip()
    if len(text) > 128 or not _DECIMAL.fullmatch(text):
        return None
    try:
        number = Decimal(text)
        if not number.is_finite():
            return None
        # Decimal construction is exact, but arithmetic/abs use the ambient
        # precision (normally 28 digits). Fraction preserves close weights and
        # path ordering rather than rounding distinct routes into a false tie.
        exact = Fraction(number)
        return exact if abs(exact) <= 10**12 else None
    except InvalidOperation:
        return None


def _direction(edge, graph):
    if 'direction' not in edge:
        return 'forward' if graph.get('directed') is True else 'undirected' if graph.get('directed') is False else 'unknown'
    return 'unknown' if edge['direction'] is None else edge['direction']


def _complete(source):
    return (source.get('complete') is True and not source.get('unresolved_edges')
            and not source.get('unresolved_vertices') and not source.get('uncertain_edges')
            and isinstance(source.get('edges'), list)
            and all(isinstance(e, dict) and e.get('status') in (None, 'accepted')
                    for e in source.get('edges', [])))


def _record(graph, graph_id, budget):
    issues, notes = [], []
    nodes, edges = graph.get('vertices'), graph.get('edges')
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return [], [], [_issue('invalid_graph_inventory', graph_id)], notes
    if len(nodes) > MAX_VERTICES or len(edges) > MAX_EDGES:
        return [], [], [_issue('graph_tool_capacity', graph_id, vertices=len(nodes), edges=len(edges))], notes
    ids, edge_ids = set(), set()
    for index, node in enumerate(nodes):
        _check(budget)
        vid = node.get('id') if isinstance(node, dict) else None
        if not _identifier(vid):
            issues.append(_issue('invalid_vertex_id', graph_id, source_index=index))
        elif vid in ids:
            issues.append(_issue('duplicate_vertex_id', graph_id, vertex_id=vid))
        else:
            ids.add(vid)
    for field in ('directed', 'weighted', 'multigraph'):
        value = graph.get(field)
        if value is not None and type(value) is not bool and value != 'unknown':
            issues.append(_issue('invalid_graph_type', graph_id, field=field))
    normalized = []
    for index, edge in enumerate(edges):
        _check(budget)
        if not isinstance(edge, dict):
            issues.append(_issue('invalid_edge_record', graph_id, source_index=index))
            continue
        eid = edge.get('id')
        if not _identifier(eid):
            issues.append(_issue('invalid_edge_id', graph_id, source_index=index))
        elif eid in edge_ids:
            issues.append(_issue('duplicate_edge_id', graph_id, edge_id=eid))
        else:
            edge_ids.add(eid)
        for endpoint in ('from', 'to'):
            value = edge.get(endpoint)
            if not _identifier(value) or value not in ids:
                issues.append(_issue('unknown_endpoint', graph_id, edge_id=eid,
                                     endpoint=endpoint, reference=_safe(value)))
        direction = _direction(edge, graph)
        if direction not in ('forward', 'undirected', 'unknown'):
            issues.append(_issue('invalid_edge_direction', graph_id, edge_id=eid))
        if type(edge.get('multiplicity', 1)) is not int or edge.get('multiplicity', 1) != 1:
            issues.append(_issue('aggregated_multiplicity_requires_instances', graph_id, edge_id=eid))
        weight = edge.get('weight')
        if (isinstance(weight, bool) or (weight is not None and not isinstance(weight, (str, int, float)))
                or isinstance(weight, float) and not math.isfinite(weight)):
            issues.append(_issue('invalid_weight', graph_id, edge_id=eid))
        for field in ('color', 'style'):
            if edge.get(field) is not None and not isinstance(edge[field], str):
                issues.append(_issue('invalid_edge_attribute', graph_id, edge_id=eid, field=field))
        label = edge.get('edge_label')
        if (isinstance(label, bool) or (label is not None and not isinstance(label, (str, int, float)))
                or isinstance(label, float) and not math.isfinite(label)):
            issues.append(_issue('invalid_edge_label', graph_id, edge_id=eid))
        normalized.append({**copy.deepcopy({k: edge[k] for k in _EDGE_FIELDS if k in edge}),
                           'direction': direction, '_instance': index})
    for field, expected in (('vertex_count', len(nodes)), ('confirmed_edge_count', len(edges))):
        if field in graph and (type(graph[field]) is not int or graph[field] != expected):
            issues.append(_issue('declared_count_mismatch', graph_id, field=field, expected=expected,
                                 actual=_safe(graph[field])))
    # Per-edge semantics are authoritative; a redundant global flag may be
    # stale. In particular a loop/parallel pair is never a mathematical error.
    kinds = {e['direction'] for e in normalized if isinstance(e['direction'], str)}
    if graph.get('directed') is True and 'undirected' in kinds or graph.get('directed') is False and 'forward' in kinds:
        notes.append({'kind': 'redundant_direction_flag_differs', 'authoritative': 'per_edge_direction'})
    if graph.get('weighted') is False and any(e.get('weight') is not None for e in normalized):
        notes.append({'kind': 'redundant_weight_flag_differs', 'authoritative': 'per_edge_weight'})
    return nodes, normalized, issues, notes


def _build(nx, nodes, edges, *, directed=False):
    graph = nx.MultiDiGraph() if directed else nx.MultiGraph()
    for node in nodes:
        graph.add_node(node['id'], label=copy.deepcopy(node.get('label')))
    for edge in edges:
        graph.add_edge(edge['from'], edge['to'], key=edge['_instance'], **copy.deepcopy(edge))
    return graph


def _inspect(document, budget):
    started = time.monotonic()
    _check(budget)
    issues, summaries, prepared = [], [], {}
    sources = document.get('graphs') if isinstance(document, dict) else None
    if not isinstance(sources, list):
        return {'issues': [_issue('invalid_graph_inventory')], 'summaries': [],
                'tool_audit': [{'tool': 'graph.semantic_inspect', 'version': VERSION,
                                'status': 'failed', 'executed': False}]}, prepared
    digest = _digest(sources)
    try:
        import networkx as nx
    except ImportError:
        return {'issues': [_issue('networkx_unavailable')], 'summaries': [],
                'tool_audit': [{'tool': 'graph.semantic_inspect', 'version': VERSION,
                                'status': 'failed', 'executed': False, 'input_digest': digest}]}, prepared
    if len(sources) > MAX_GRAPHS:
        issues.append(_issue('graph_tool_capacity', graph_count=len(sources), limit=MAX_GRAPHS))
    graph_ids = Counter(g.get('id') for g in sources[:MAX_GRAPHS]
                        if isinstance(g, dict) and _identifier(g.get('id')))
    executed = False
    for index, source in enumerate(sources[:MAX_GRAPHS]):
        _check(budget)
        gid = source.get('id') if isinstance(source, dict) else None
        if not _identifier(gid) or graph_ids.get(gid, 0) != 1:
            issues.append(_issue('invalid_or_duplicate_graph_id', source_index=index))
            continue
        nodes, edges, problems, notes = _record(source, gid, budget)
        issues.extend(problems)
        summary = {'graph_id': gid, 'structural_valid': not problems, 'image_fidelity_certified': False,
                   'input_complete': _complete(source),
                   'vertex_count': len(nodes), 'edge_count': len(edges), 'declaration_notes': notes,
                   'vertex_labels': [{'id': node.get('id'), 'label': _safe(node.get('label'))}
                                     for node in nodes if isinstance(node, dict)],
                   'degrees': None, 'directed_degrees': None, 'isolated_vertices': None,
                   'underlying_components': None, 'strong_components': None,
                   'invariants': None, 'calculation_scope': 'listed_edge_instances'}
        summaries.append(summary)
        if problems:
            continue
        actual = _build(nx, nodes, edges)
        executed = True
        counts = Counter(e['direction'] for e in edges)
        mode = ('directed' if not edges and source.get('directed') is True else 'empty' if not edges
                else 'directed' if counts['forward'] == len(edges)
                else 'undirected' if counts['undirected'] == len(edges)
                else 'unknown' if counts['unknown'] else 'mixed')
        directed = _build(nx, nodes, edges, directed=True) if mode == 'directed' else None
        groups = {}
        for e in edges:
            if e['direction'] == 'unknown':
                continue
            ends = (e['from'], e['to']) if e['direction'] == 'forward' else tuple(sorted((e['from'], e['to'])))
            groups.setdefault((e['direction'], *ends), []).append(e['id'])
        weights = [_numeric_weight(e.get('weight')) for e in edges]
        summary.update({'direction_mode': mode, 'direction_counts': dict(counts),
            'degrees': [{'vertex_id': v, 'degree': int(actual.degree(v))} for v in actual],
            'isolated_vertices': list(nx.isolates(actual)),
            'underlying_components': [sorted(c) for c in nx.connected_components(actual)],
            'self_loop_edge_ids': [e['id'] for e in edges if e['from'] == e['to']],
            'parallel_groups': [{'direction': key[0], 'endpoints': list(key[1:]), 'edge_ids': ids}
                                for key, ids in groups.items() if len(ids) > 1],
            'weight_coverage': {'numeric': sum(v is not None for v in weights),
                                'missing': sum(e.get('weight') is None for e in edges),
                                'symbolic_or_non_numeric': sum(e.get('weight') is not None and v is None
                                                              for e, v in zip(edges, weights))},
            'invariants': {'edge_instances_preserved': actual.number_of_edges() == len(edges),
                           'degree_sum': sum(dict(actual.degree()).values()),
                           'expected_degree_sum': 2 * len(edges)}})
        if directed is not None:
            summary['directed_degrees'] = [{'vertex_id': v, 'in_degree': int(directed.in_degree(v)),
                                           'out_degree': int(directed.out_degree(v))} for v in directed]
            summary['strong_components'] = [sorted(c) for c in nx.strongly_connected_components(directed)]
            summary['invariants'].update({'in_degree_sum': sum(dict(directed.in_degree()).values()),
                                           'out_degree_sum': sum(dict(directed.out_degree()).values())})
        inv = summary['invariants']
        if (not inv['edge_instances_preserved'] or inv['degree_sum'] != inv['expected_degree_sum']
                or directed is not None and (inv['in_degree_sum'] != len(edges) or inv['out_degree_sum'] != len(edges))):
            issues.append(_issue('networkx_instance_invariant_failure', gid))
            summary['structural_valid'] = False
        prepared[gid] = {'source': source, 'nodes': nodes, 'edges': edges,
                         'underlying': actual, 'directed': directed, 'summary': summary}
        _check(budget)
    audit = {'tool': 'graph.semantic_inspect', 'version': VERSION, 'library': 'networkx',
             'library_version': nx.__version__, 'status': 'partial' if issues else 'success',
             'executed': executed, 'input_digest': digest, 'graph_count': len(summaries),
             'seconds': round(time.monotonic() - started, 4), 'may_confirm_ocr': False}
    return {'issues': issues, 'summaries': summaries, 'tool_audit': [audit]}, prepared


def _decimal_output(value):
    """Serialize exact sums of bounded decimal weights without rounding."""
    number = Fraction(value)
    if number.denominator == 1:
        return number.numerator
    denominator, twos, fives = number.denominator, 0, 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        raise ValueError('non_terminating_weight_sum')
    scale = max(twos, fives)
    numerator = abs(number.numerator) * 2**(scale-twos) * 5**(scale-fives)
    digits = str(numerator).rjust(scale+1, '0')
    return ('-' if number < 0 else '') + digits[:-scale] + '.' + digits[-scale:].rstrip('0')


def _transition_counts(item, budget):
    """Count edge instances directly; do not coerce a mixed graph's type.

    As in the existing graph adjacency/walk tools, a self-loop permits one
    one-step traversal. An undirected non-loop permits either traversal; a
    directed edge permits only from -> to. A parallel edge contributes again.
    """
    ids = [node['id'] for node in item['nodes']]
    indices = {vid: index for index, vid in enumerate(ids)}
    matrix = [[0] * len(ids) for _ in ids]
    for edge in item['edges']:
        _check(budget)
        left, right = indices[edge['from']], indices[edge['to']]
        matrix[left][right] += 1
        if edge['direction'] == 'undirected' and left != right:
            matrix[right][left] += 1
    return ids, matrix


def _euler_facts(item, request, nx, budget):
    actual = item['directed'] if item['summary']['direction_mode'] == 'directed' else item['underlying']
    isolated = list(nx.isolates(actual))
    ignore = request.get('ignore_isolated', False)
    analysed = actual.subgraph([v for v in actual if v not in isolated]).copy() if ignore else actual
    start = request.get('start_vertex')
    if start is not None and (start not in actual or start not in analysed):
        return None, 'invalid_euler_start'
    _check(budget)
    if analysed.number_of_nodes() == 0:
        # Explicit legacy convention; not an inferred missing vertex.
        circuit = trail_exists = True
    else:
        circuit = bool(nx.is_eulerian(analysed))
        trail_exists = bool(nx.has_eulerian_path(analysed))
    if start is not None and trail_exists and not nx.has_eulerian_path(analysed, source=start):
        return None, 'invalid_euler_start'
    trail = []
    if trail_exists and analysed.number_of_edges():
        for left, right, key in nx.eulerian_path(analysed, source=start, keys=True):
            _check(budget)
            trail.append({'edge_id': analysed[left][right][key]['id'], 'from': left, 'to': right})
    return {'has_eulerian_circuit': circuit, 'has_eulerian_trail': trail_exists,
            'trail': trail, 'isolated_vertices': isolated,
            'vertex_convention': 'ignore_isolated' if ignore else 'all_declared_vertices',
            'empty_graph_convention': 'empty_edge_trail',
            'direction_mode': item['summary']['direction_mode'],
            'parallel_instances_preserved': True}, None


def _prepare_math(document, request=None, *, budget=None):
    """Run an explicitly selected operation; never infer one from OCR text.

    Caller supplies the application-held canonical snapshot after the user
    starts solving. ``None`` performs no calculation. Full-graph calculations
    require a complete semantic snapshot and applicable direction/weights.
    """
    _check(budget)
    result = {'status': 'not_requested', 'facts': None, 'issues': [], 'tool_audit': [],
              'image_fidelity_certified': False}
    if request is None:
        return result
    if (not isinstance(request, dict) or set(request) - {'operation', 'graph_id', 'source', 'target',
                                                         'weighted', 'length', 'start_vertex', 'ignore_isolated'}
            or request.get('operation') not in _OPERATIONS or not _identifier(request.get('graph_id'))):
        return {**result, 'status': 'not_applicable', 'issues': [_issue('invalid_math_request')]}
    op, gid = request['operation'], request['graph_id']
    operation_fields = {'shortest_path': {'source', 'target', 'weighted'},
                        'walk_count': {'source', 'target', 'length'},
                        'euler': {'start_vertex', 'ignore_isolated'}}
    permitted = {'operation', 'graph_id'} | operation_fields.get(op, set())
    if (set(request) - permitted or ('weighted' in request and type(request['weighted']) is not bool)
            or ('ignore_isolated' in request and type(request['ignore_isolated']) is not bool)
            or (op == 'walk_count' and (type(request.get('length')) is not int
                                      or not 0 <= request['length'] <= MAX_WALK_LENGTH))):
        return {**result, 'status': 'not_applicable', 'issues': [_issue('invalid_math_request')]}
    inspected, prepared = _inspect(document, budget)
    result['tool_audit'] = inspected['tool_audit']
    item = prepared.get(gid)
    if item is None or not item['summary']['structural_valid']:
        return {**result, 'status': 'not_applicable', 'issues': inspected['issues'] or [_issue('unknown_graph', gid)]}
    import networkx as nx
    started = time.monotonic()
    executed, failure, facts = False, None, None
    source, summary = item['source'], item['summary']
    actual = item['underlying']
    _check(budget)
    if op == 'degrees':
        facts = {'degrees': copy.deepcopy(summary['degrees']),
                 'directed_degrees': copy.deepcopy(summary['directed_degrees']),
                 'degree_convention': 'incidences; a loop contributes two',
                 'direction_mode': summary['direction_mode']}
        executed = True
    elif op == 'components':
        facts = {'underlying_components': copy.deepcopy(summary['underlying_components']),
                 'strong_components': copy.deepcopy(summary['strong_components']),
                 'isolated_vertices': copy.deepcopy(summary['isolated_vertices'])}
        executed = True
    elif op == 'bipartite':
        facts = {'is_bipartite': bool(nx.is_bipartite(actual)), 'direction_convention': 'underlying_graph'}
        executed = True
    elif not _complete(source):
        failure = 'incomplete_semantic_snapshot'
    elif op in ('adjacency_matrix', 'walk_count'):
        if summary['direction_mode'] == 'unknown':
            failure = 'unknown_edge_direction_not_supported'
        else:
            ids, matrix = _transition_counts(item, budget)
            common = {'vertex_order': ids, 'direction_mode': summary['direction_mode'],
                      'direction_convention': 'per_edge_traversal',
                      'diagonal_convention': 'one_per_loop', 'parallel_instances_preserved': True}
            if op == 'adjacency_matrix':
                facts = {**common, 'matrix': matrix, 'entry_meaning': 'edge_instance_count',
                         'weights_used': False}
                executed = True
            else:
                left, right = request.get('source'), request.get('target')
                if left not in ids or right not in ids:
                    failure = 'unknown_path_endpoint'
                else:
                    counts = [int(vid == left) for vid in ids]
                    for _ in range(request['length']):
                        _check(budget)
                        counts = [sum(counts[i] * matrix[i][j] for i in range(len(ids)))
                                  for j in range(len(ids))]
                    facts = {**common, 'source': left, 'target': right,
                             'length': request['length'], 'count': counts[ids.index(right)],
                             'walk_definition': 'edge_distinct_walks_repetition_allowed',
                             'weights_used': False}
                    executed = True
    elif summary['direction_mode'] not in ('directed', 'undirected', 'empty'):
        failure = 'mixed_or_unknown_direction_not_supported'
    elif op == 'euler':
        facts, failure = _euler_facts(item, request, nx, budget)
        executed = failure is None
    elif op == 'minimum_spanning_tree' and summary['direction_mode'] == 'directed':
        failure = 'mst_requires_undirected_graph'
    elif (op == 'shortest_path' and 'weighted' not in request
          and (source.get('weighted') is True or any(e.get('weight') is not None for e in item['edges']))):
        failure = 'path_weight_mode_required'
    else:
        actual = item['directed'] if summary['direction_mode'] == 'directed' else item['underlying']
        weighted = op == 'minimum_spanning_tree' or request.get('weighted', False)
        if weighted and any(_numeric_weight(e.get('weight')) is None for e in item['edges']):
            failure = 'complete_numeric_weights_required'
        else:
            actual = actual.copy()
            for _, _, key, data in actual.edges(keys=True, data=True):
                data['_cost'] = _numeric_weight(data.get('weight')) if weighted else Fraction(1)
            try:
                if op == 'minimum_spanning_tree':
                    if actual.number_of_nodes() == 0 or not nx.is_connected(actual):
                        failure = 'connected_nonempty_graph_required_for_mst'
                    else:
                        tree = list(nx.minimum_spanning_edges(actual, algorithm='kruskal', weight='_cost', keys=True, data=True))
                        facts = {'edge_ids': [data['id'] for _, _, _, data in tree],
                                 'total_weight': _decimal_output(sum((data['_cost'] for _, _, _, data in tree), Fraction(0))),
                                 'vertex_ids': list(actual), 'parallel_instances_preserved': True,
                                 'arithmetic': 'exact_rational'}
                        executed = True
                else:
                    a, b = request.get('source'), request.get('target')
                    if not _identifier(a) or not _identifier(b) or a not in actual or b not in actual:
                        failure = 'unknown_path_endpoint'
                    else:
                        negative = any(data['_cost'] < 0 for _, _, data in actual.edges(data=True))
                        method = nx.single_source_bellman_ford if negative else nx.single_source_dijkstra
                        executed = True
                        distance, path = method(actual, a, target=b, weight='_cost')
                        instances, ties = [], []
                        for u, v in zip(path, path[1:]):
                            options = sorted(actual[u][v].items(), key=lambda row: (row[1]['_cost'], row[0]))
                            chosen = options[0][1]
                            instances.append(chosen['id'])
                            ties.append([data['id'] for _, data in options if data['_cost'] == chosen['_cost']])
                        facts = {'vertex_ids': path, 'edge_ids': instances,
                                 'distance': _decimal_output(distance),
                                 'equal_cost_edge_choices': ties, 'weighted': weighted,
                                 'arithmetic': 'exact_rational' if weighted else 'edge_count',
                                 'algorithm': 'bellman_ford' if negative else 'dijkstra'}
                        executed = True
            except nx.NetworkXNoPath:
                facts, executed = {'path_exists': False, 'vertex_ids': [], 'edge_ids': []}, True
            except nx.NetworkXUnbounded:
                failure = 'reachable_negative_cycle'
    _check(budget)
    result.update({'status': 'computed' if failure is None else 'not_applicable',
                   'facts': facts, 'graph_id': gid, 'operation': op,
                   'input_complete': summary['input_complete'],
                   'calculation_scope': 'provided_semantic_snapshot'})
    if failure:
        result['issues'] = [_issue(failure, gid)]
    result['tool_audit'].append({'tool': 'graph.semantic_math', 'version': VERSION,
        'library': 'networkx', 'library_version': nx.__version__, 'operation': op, 'graph_id': gid,
        'status': result['status'], 'executed': executed, 'seconds': round(time.monotonic() - started, 4),
        'input_digest': inspected['tool_audit'][0].get('input_digest'), 'may_confirm_ocr': False})
    return result


class _PrivateBudget:
    """Preserve caller cancellation across the registry's failure envelope."""

    def __init__(self, context):
        self.context = context

    def check(self):
        budget = self.context.data['budget']
        if budget is not None:
            try:
                budget.check()
            except Exception as exc:
                self.context.data['control']['error'] = exc
                raise
        self.context.check_deadline()


def _inspect_tool(arguments, *, context):
    return _inspect(context.data['document'], _PrivateBudget(context))[0]


def _math_tool(arguments, *, context):
    return _prepare_math(context.data['document'], arguments, budget=_PrivateBudget(context))


def _build_registry():
    identifier = {'type': 'string', 'minLength': 1, 'maxLength': 128}
    ordinary = {'type': 'object', 'additionalProperties': False,
        'required': ['operation', 'graph_id'], 'properties': {
            'operation': {'enum': sorted(_OPERATIONS - {'shortest_path', 'walk_count', 'euler'})}, 'graph_id': identifier}}
    path = {'type': 'object', 'additionalProperties': False,
        'required': ['operation', 'graph_id'], 'properties': {
            'operation': {'const': 'shortest_path'}, 'graph_id': identifier,
            'source': identifier, 'target': identifier, 'weighted': {'type': 'boolean'}}}
    walk = {'type': 'object', 'additionalProperties': False,
        'required': ['operation', 'graph_id', 'source', 'target', 'length'], 'properties': {
            'operation': {'const': 'walk_count'}, 'graph_id': identifier,
            'source': identifier, 'target': identifier,
            'length': {'type': 'integer', 'minimum': 0, 'maximum': MAX_WALK_LENGTH}}}
    euler = {'type': 'object', 'additionalProperties': False,
        'required': ['operation', 'graph_id'], 'properties': {
            'operation': {'const': 'euler'}, 'graph_id': identifier,
            'start_vertex': identifier, 'ignore_isolated': {'type': 'boolean'}}}
    registry = ToolRegistry()
    registry.register(ToolSpec(name='graph.semantic_inspect', version=VERSION,
        description='Inspect the private semantic graph with NetworkX; never certify image reading.',
        input_schema={'type': 'object', 'additionalProperties': False},
        output_schema={'type': 'object', 'required': ['issues', 'summaries', 'tool_audit'],
                       'properties': {'issues': {'type': 'array'}, 'summaries': {'type': 'array'},
                                      'tool_audit': {'type': 'array'}}},
        allowed_roles=frozenset({'semantic_review'}), source_required=False, timeout_seconds=5.), _inspect_tool)
    registry.register(ToolSpec(name='graph.semantic_math', version=VERSION,
        description='Run one explicit bounded operation on the private semantic snapshot.',
        input_schema={'oneOf': [ordinary, path, walk, euler]},
        output_schema={'type': 'object', 'required': ['status', 'facts', 'issues', 'tool_audit'],
                       'properties': {'status': {'enum': ['not_requested', 'computed', 'not_applicable']},
                                      'issues': {'type': 'array'}, 'tool_audit': {'type': 'array'}}},
        allowed_roles=frozenset({'solver'}), source_required=False, timeout_seconds=5.), _math_tool)
    return registry


def _registered_call(name, arguments, *, document, budget, role):
    _check(budget)
    started = time.monotonic()
    control = {'error': None}
    deadline = min(started + 5., getattr(budget, 'deadline', started + 5.))
    context = ToolContext(source_sha256=getattr(budget, 'source_sha256', None),
        deadline_monotonic=deadline,
        data={'document': document, 'budget': budget, 'control': control})
    envelope = _build_registry().call(name, arguments, role=role, context=context)
    if control['error'] is not None:
        raise control['error']
    _check(budget)
    if envelope['ok']:
        result = envelope['result']
    elif name == 'graph.semantic_inspect':
        result = {'issues': [_issue('semantic_inspection_tool_unavailable',
                                   reason=envelope['error']['code'])], 'summaries': [], 'tool_audit': []}
    else:
        code = 'invalid_math_request' if envelope['error']['code'] == 'invalid_arguments' else 'semantic_math_tool_unavailable'
        result = {'status': 'not_applicable', 'facts': None, 'issues': [_issue(code,
                  reason=envelope['error']['code'])], 'tool_audit': [], 'image_fidelity_certified': False}
    # Preserve actual NetworkX measurements and append the independent host
    # invocation record: role/schema/deadline enforcement really happened.
    result['tool_audit'] = list(result.get('tool_audit', [])) + list(context.audit)
    return result


def inspect_semantic_graphs(document, *, budget=None):
    """Read-only NetworkX inspection through the semantic_review registry role."""
    return _registered_call('graph.semantic_inspect', {}, document=document, budget=budget,
                            role='semantic_review')


def prepare_semantic_math(document, request=None, *, budget=None):
    """An explicit solver request; None neither invokes tools nor solves."""
    if request is None:
        _check(budget)
        return {'status': 'not_requested', 'facts': None, 'issues': [], 'tool_audit': [],
                'image_fidelity_certified': False}
    return _registered_call('graph.semantic_math', request, document=document, budget=budget, role='solver')


__all__ = ['inspect_semantic_graphs', 'prepare_semantic_math']
