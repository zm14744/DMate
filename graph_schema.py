"""Bounded canonical graph records. Edge identity is never an endpoint pair."""
from __future__ import annotations
import copy
import math
from collections import Counter

SCHEMA_VERSION = 'dmate.graph/1'


def parallel_key(edge):
    """Parallel arcs share direction; reciprocal arcs are distinct classes."""
    a, b = edge['from'], edge['to']
    direction = edge.get('direction', 'unknown')
    return (direction, a, b) if direction == 'forward' else (direction, *sorted((a, b)))


def unit(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) and 0 <= value <= 1 else None
    except (TypeError, ValueError, OverflowError):
        return None


def path_points(value):
    if not isinstance(value, list) or not 2 <= len(value) <= 128:
        return []
    result = []
    for p in value:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            return []
        x, y = unit(p[0]), unit(p[1])
        if x is None or y is None:
            return []
        result.append([x, y])
    return result


def canonical_graph(source, index=1):
    """Preserve labels, separate weights, direction, route and uncertainty.

    Invalid endpoints are recorded as uncertainty, never auto-created vertices.
    No inference of topology from connectivity, degrees, or common templates.
    """
    if not isinstance(source, dict):
        raise ValueError('graph must be an object')
    graph = {'schema_version': SCHEMA_VERSION,
             'id': str(source.get('id') or f'G{index}')[:48],
             'name': str(source.get('name') or source.get('id') or f'G{index}')[:80],
             'vertices': [], 'edges': [], 'uncertain_edges': [],
             'complete': source.get('complete') is True}
    for k in ('directed', 'weighted', 'multigraph'):
        v = source.get(k)
        graph[k] = v if isinstance(v, bool) else 'unknown'
    for key in ('bbox', 'node_complete', 'inventory_reviewed', 'node_position_evidence', 'node_review',
                'panel_revision_audit', 'node_geometry_evidence', 'candidate_trace_diagnostics'):
        if key in source:
            graph[key] = copy.deepcopy(source[key])
    for key, limit in (('visual_description', 800),):
        if isinstance(source.get(key), str) and len(source[key]) <= limit:
            graph[key] = source[key]
    if type(source.get('anon_next')) is int and 1 <= source['anon_next'] <= 10000:
        graph['anon_next'] = source['anon_next']
    if isinstance(source.get('qwen_review_audit'), list):
        graph['qwen_review_audit']=copy.deepcopy(source['qwen_review_audit'][:24])
    raw_nodes = source.get('vertices')
    raw_edges = source.get('edges', [])
    if not isinstance(raw_nodes, list) or not 1 <= len(raw_nodes) <= 100:
        raise ValueError('invalid vertex inventory')
    if not isinstance(raw_edges, list) or len(raw_edges) > 300:
        raise ValueError('edge budget exceeded')
    used = set()
    for n, item in enumerate(raw_nodes, 1):
        if isinstance(item, str):
            item = {'id': item, 'label': item}
        if not isinstance(item, dict):
            raise ValueError('invalid vertex')
        identifier = str(item.get('id') or f'v{n}')[:64]
        if identifier in used:
            raise ValueError('duplicate vertex ID')
        used.add(identifier)
        label = item.get('label')
        graph['vertices'].append({'id': identifier,
            'label': str(label)[:64] if label is not None and str(label).strip() else None,
            'x': unit(item.get('x')), 'y': unit(item.get('y')),
            'isolated_confirmed': item.get('isolated_confirmed') is True})
        for key, limit in (('display_label', 16), ('position_description', 160)):
            if isinstance(item.get(key), str) and 0 < len(item[key]) <= limit:
                graph['vertices'][-1][key] = item[key]
    edge_ids = set()
    for n, item in enumerate(raw_edges, 1):
        if not isinstance(item, dict):
            graph['uncertain_edges'].append('invalid_edge'); continue
        a, b = str(item.get('from', '')), str(item.get('to', ''))
        if a not in used or b not in used:
            graph['uncertain_edges'].append('invalid_endpoint'); continue
        eid = str(item.get('id') or f'e{n}')[:64]
        if eid in edge_ids:
            graph['uncertain_edges'].append('duplicate_edge_id')
            eid = f'e{n}_{len(edge_ids)}'
        edge_ids.add(eid)
        direction = item.get('direction')
        if direction not in ('forward', 'undirected', 'unknown'):
            direction = 'undirected' if graph['directed'] is False else 'unknown'
        weight = item.get('weight')
        if isinstance(weight, bool) or not isinstance(weight, (str, int, float)):
            weight = None
        elif isinstance(weight, float) and not math.isfinite(weight):
            weight = None
        elif isinstance(weight, str):
            weight = weight.strip()[:80] or None
        label = item.get('edge_label')
        # Never silently move numeric labels: the visual binding must decide.
        edge = {'id': eid, 'from': a, 'to': b, 'direction': direction,
                'edge_label': str(label)[:64] if label is not None else None,
                'weight': weight, 'multiplicity': 1,
                'path': path_points(item.get('path')),
                'style': item.get('style') if item.get('style') in ('solid', 'dashed', 'dotted') else 'unknown',
                'color': str(item.get('color') or 'unknown')[:32],
                'status': item.get('status') if item.get('status') in ('accepted', 'pending') else 'pending'}
        evidence = item.get('evidence')
        edge['evidence'] = copy.deepcopy(evidence[:12]) if isinstance(evidence, list) else []
        if ((graph['directed'] is False and direction == 'forward')
                or (graph['directed'] is True and direction == 'undirected')):
            edge['evidence'].append({'source':'graph_direction_conflict',
                                     'observed_direction':direction,'graph_directed':graph['directed']})
            edge['direction']='unknown'
            edge['status']='pending'
        graph['edges'].append(edge)
    pair_counts = Counter(parallel_key(e) for e in graph['edges'])
    for e in graph['edges']:
        e['parallel_count'] = pair_counts[parallel_key(e)]
    graph['uncertain_edges'] += [str(x)[:240] for x in (source.get('uncertain_edges') or [])[:80]]
    if (graph['uncertain_edges'] or any(e['direction'] == 'unknown' or e['status'] != 'accepted' for e in graph['edges'])
            or any(graph[k] == 'unknown' for k in ('directed', 'weighted', 'multigraph'))):
        graph['complete'] = False
    from graph_presentation import prepare_graph_presentation
    return prepare_graph_presentation(graph)


def display_graph(graph):
    """Public display fields only; pixels/model diagnostics stay server-side."""
    fields = ('schema_version', 'id', 'name', 'directed', 'direction_mode', 'weighted', 'multigraph', 'complete', 'visual_description', 'anon_next')
    out = {k: graph[k] for k in fields if k in graph}
    out['vertices'] = [{k: v[k] for k in ('id', 'label', 'display_label', 'position_description', 'isolated_confirmed') if k in v}
                       for v in graph['vertices']]
    out['edges'] = [{k: e[k] for k in ('id', 'from', 'to', 'direction', 'edge_label', 'weight',
                                      'multiplicity', 'parallel_count', 'style', 'color', 'status') if k in e}
                    for e in graph['edges']]
    return out


def describe_graphs(graphs):
    """Describe the SAME edge records as the cards; never infer graph names.

    This is solver input, so incomplete evidence keeps the existing guard
    marker. The UI renders display_graph instead of these internal markers.
    """
    lines = []
    for graph in graphs:
        labels = {v['id']: v.get('label') or v.get('display_label') or v['id'] for v in graph['vertices']}
        edges = []
        incident = set()
        for edge in graph['edges']:
            incident.update((edge['from'], edge['to']))
            connector = {'forward': '→', 'undirected': '—'}.get(edge['direction'], '?')
            attrs = []
            if edge['from'] == edge['to']: attrs.append('自环')
            if edge.get('edge_label') is not None: attrs.append('边名 '+str(edge['edge_label']))
            if edge.get('weight') is not None: attrs.append('权值 '+str(edge['weight']))
            if edge.get('style') in ('solid', 'dashed', 'dotted'):
                attrs.append({'solid': '实线', 'dashed': '虚线', 'dotted': '点线'}[edge['style']])
            color = edge.get('color')
            if isinstance(color, str) and color.strip() and color.strip().lower() != 'unknown':
                attrs.append('颜色 '+color.strip())
            if edge['direction'] == 'unknown': attrs.append('方向未确定')
            if edge['status'] != 'accepted': attrs.append('待确认')
            suffix = '（'+'，'.join(attrs)+'）' if attrs else ''
            edges.append(f"{edge['id']}: {labels[edge['from']]}{connector}{labels[edge['to']]}{suffix}")
        isolated = [labels[v['id']] for v in graph['vertices'] if v['id'] not in incident
                    and (graph['complete'] or v.get('isolated_confirmed'))]
        kind = ('混合图' if graph.get('direction_mode') == 'mixed' else
                '有向图' if graph['directed'] is True else '无向图' if graph['directed'] is False else '方向未确定')
        line = f"{graph['name']}：{kind}。顶点："+'、'.join(labels.values())+'。'
        if isolated: line += '孤立顶点：'+'、'.join(isolated)+'。'
        line += f"边（{'共' if graph['complete'] else '暂录'}{len(edges)}条）："+'；'.join(edges)+'。'
        from graph_presentation import reference_notes
        notes = reference_notes(graph)
        if notes:
            line += '\n' + notes
        lines.append(line)
    text = '\n\n'.join(lines)
    return ('【图形结构待核对】\n'+text) if any(not g['complete'] for g in graphs) else text
