"""Bounded canonical graph records. Edge identity is never an endpoint pair."""
from __future__ import annotations
import copy
import math
from collections import Counter

SCHEMA_VERSION = 'dmate.graph/1'


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
    for key in ('bbox', 'node_complete', 'inventory_reviewed'):
        if key in source:
            graph[key] = copy.deepcopy(source[key])
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
            direction = 'forward' if graph['directed'] is True else (
                'undirected' if graph['directed'] is False else 'unknown')
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
        graph['edges'].append(edge)
    pair_counts = Counter(tuple(sorted((e['from'], e['to']))) for e in graph['edges'])
    for e in graph['edges']:
        e['parallel_count'] = pair_counts[tuple(sorted((e['from'], e['to'])))]
    graph['uncertain_edges'] += [str(x)[:240] for x in (source.get('uncertain_edges') or [])[:80]]
    if (graph['uncertain_edges'] or any(e['direction'] == 'unknown' or e['status'] != 'accepted' for e in graph['edges'])
            or any(graph[k] == 'unknown' for k in ('directed', 'weighted', 'multigraph'))):
        graph['complete'] = False
    return graph


def display_graph(graph):
    """Public display fields only; pixels/model diagnostics stay server-side."""
    fields = ('schema_version', 'id', 'name', 'directed', 'weighted', 'multigraph', 'complete')
    out = {k: graph[k] for k in fields if k in graph}
    out['vertices'] = [{k: v[k] for k in ('id', 'label', 'isolated_confirmed') if k in v}
                       for v in graph['vertices']]
    out['edges'] = [{k: e[k] for k in ('id', 'from', 'to', 'direction', 'edge_label', 'weight',
                                      'multiplicity', 'parallel_count', 'style', 'color', 'status') if k in e}
                    for e in graph['edges']]
    return out
