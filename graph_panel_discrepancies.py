"""Find possible repeated image windows without changing the graph inventory.

Identical graph content alone is not duplication: an exercise can deliberately
show several isomorphic graphs. A reread target additionally needs overlapping
original-image locations, or missing locations and fewer usable CV crop
suggestions. Crop counts are never treated as the mathematical graph count.
"""
from __future__ import annotations

from collections import Counter
import json
import math
import re
import time
import unicodedata

import networkx as nx

VERSION = '2026-10-27-panel-discrepancies-v1'
MAX_GRAPHS = 16
MAX_VERTICES = 64
MAX_EDGES = 160
MAX_COMPARE_SECONDS = .08


def _box(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 4
            or not all(type(v) in (int, float) and math.isfinite(v) for v in value)
            or not (0 <= value[0] < value[2] <= 1000 and 0 <= value[1] < value[3] <= 1000)):
        return None
    # The common whole-page placeholder supplies no independent position.
    if value[0] <= 5 and value[1] <= 5 and value[2] >= 995 and value[3] >= 995:
        return None
    return tuple(float(v) for v in value)


def _text(value):
    return unicodedata.normalize('NFKC', str(value)).strip() if value is not None else None


def _caption(graph):
    explicit = _text(graph.get('visible_caption'))
    if explicit:
        return explicit
    name = _text(graph.get('name'))
    if not name or name == _text(graph.get('id')):
        return None
    if re.fullmatch(r'(?i)(?:G\s*\d+|graph\s*\d+|图\s*\d+)', name):
        return None
    if name in ('原图图注', '原图图注或G1', '未命名', '图'):
        return None
    return name


def _iou(first, second):
    overlap = max(0., min(first[2], second[2])-max(first[0], second[0])) * max(
        0., min(first[3], second[3])-max(first[1], second[1]))
    first_area = (first[2]-first[0])*(first[3]-first[1])
    second_area = (second[2]-second[0])*(second[3]-second[1])
    return overlap/max(first_area+second_area-overlap, 1.), overlap


def _usable_panels(layout):
    rows = layout.get('panels', []) if isinstance(layout, dict) else []
    if not isinstance(rows, list):
        return []
    result = []
    for row in rows[:64]:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str):
            continue
        raw = row.get('bbox')
        box = _box(raw)
        # A single whole-page CV crop is still one usable crop suggestion;
        # unlike a model's default bbox, it is not location proof for a pair.
        if box is None and raw == [0, 0, 1000, 1000]:
            box = tuple(raw)
        if box is not None:
            result.append({'id': row['id'], 'bbox': box})
    return result


def _declared_distinct_panels(first, second, panels):
    known = {row['id']: row['bbox'] for row in panels}
    one, two = first.get('layout_panel_ids'), second.get('layout_panel_ids')
    if not (isinstance(one, list) and isinstance(two, list) and one and two
            and all(isinstance(v, str) and v in known for v in one+two)):
        return False
    return not (set(one) & set(two)) and all(_iou(known[a], known[b])[1] == 0 for a in one for b in two)


def _location_reason(first, second, panels, graph_count):
    first_caption, second_caption = _caption(first), _caption(second)
    if first_caption and second_caption and first_caption != second_caption:
        return None
    if _declared_distinct_panels(first, second, panels):
        return None
    first_box, second_box = _box(first.get('bbox')), _box(second.get('bbox'))
    if first_box is not None and second_box is not None:
        overlap, area = _iou(first_box, second_box)
        if area == 0:
            return None
        return 'overlapping_original_locations' if overlap >= .65 else None
    if 0 < len(panels) < graph_count:
        return 'same_content_missing_locations_and_fewer_crop_candidates'
    return None


def _scalar(value):
    if value is None or type(value) in (bool, int, float, str):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    raise ValueError('non_scalar_graph_attribute')


def _semantic_graph(graph):
    vertices, edges = graph.get('vertices'), graph.get('edges')
    if (not isinstance(vertices, list) or not isinstance(edges, list)
            or not 1 <= len(vertices) <= MAX_VERTICES or len(edges) > MAX_EDGES):
        return None
    result = nx.MultiDiGraph()
    for vertex in vertices:
        if not isinstance(vertex, dict) or not isinstance(vertex.get('id'), (str, int)):
            return None
        identifier = str(vertex['id'])
        if identifier in result:
            return None
        result.add_node(identifier, label=_text(vertex.get('label')))
    count = 0
    try:
        for edge in edges:
            if not isinstance(edge, dict):
                return None
            source, target = str(edge.get('from')), str(edge.get('to'))
            if source not in result or target not in result:
                return None
            direction = edge.get('direction', 'forward' if graph.get('directed') is True else 'undirected')
            if direction not in ('forward', 'undirected', 'unknown'):
                return None
            multiplicity = edge.get('multiplicity', 1)
            if type(multiplicity) is not int or not 1 <= multiplicity <= MAX_EDGES:
                return None
            count += multiplicity
            if count > MAX_EDGES:
                return None
            signature = (direction, _scalar(edge.get('weight')), _text(edge.get('edge_label')),
                         _text(edge.get('style', 'solid')), _text(edge.get('color')))
            for _ in range(multiplicity):
                result.add_edge(source, target, signature=signature)
                if direction != 'forward' and source != target:
                    result.add_edge(target, source, signature=signature)
    except (ValueError, TypeError, OverflowError):
        return None
    result.graph['instance_count'] = count
    return result


class _ComparisonLimit(Exception):
    pass


class _BoundedMatcher(nx.algorithms.isomorphism.MultiDiGraphMatcher):
    def __init__(self, *args, deadline, **kwargs):
        self.deadline = deadline
        super().__init__(*args, **kwargs)

    def semantic_feasibility(self, first, second):
        if time.monotonic() >= self.deadline:
            raise _ComparisonLimit
        return super().semantic_feasibility(first, second)


def _same_semantics(first, second, *, deadline):
    if (first is None or second is None or len(first) != len(second)
            or first.graph['instance_count'] != second.graph['instance_count']
            or Counter(data['label'] for _, data in first.nodes(data=True))
                != Counter(data['label'] for _, data in second.nodes(data=True))
            or sorted(first.degree(v) for v in first) != sorted(second.degree(v) for v in second)):
        return False
    def edge_match(one, two):
        return Counter(row['signature'] for row in one.values()) == Counter(row['signature'] for row in two.values())
    matcher = _BoundedMatcher(first, second, deadline=deadline,
        node_match=lambda one, two: one['label'] == two['label'], edge_match=edge_match)
    return matcher.is_isomorphic()


def compare_panel_discrepancies(draft, layout):
    """Return document reread targets; never delete, merge or rewrite graphs."""
    started = time.monotonic()
    output = {'issues': [], 'evidence': {'version': VERSION, 'suspected_pairs': [],
        'proposal_only': True, 'graph_count_certified': False}, 'tool_audit': []}
    graphs = draft.get('graphs') if isinstance(draft, dict) else None
    if not isinstance(graphs, list) or len(graphs) < 2 or len(graphs) > MAX_GRAPHS:
        return output
    if any(not isinstance(graph, dict) or graph.get('id') is None for graph in graphs):
        return output
    panels = _usable_panels(layout)
    cached = {}
    deadline = started + MAX_COMPARE_SECONDS
    try:
        for index, first in enumerate(graphs):
            for other_index, second in enumerate(graphs[index+1:], index+1):
                if time.monotonic() >= deadline:
                    raise _ComparisonLimit
                reason = _location_reason(first, second, panels, len(graphs))
                if reason is None:
                    continue
                for position, graph in ((index, first), (other_index, second)):
                    if position not in cached:
                        cached[position] = _semantic_graph(graph)
                if _same_semantics(cached[index], cached[other_index], deadline=deadline):
                    output['evidence']['suspected_pairs'].append({
                        'graph_ids': [str(first['id']), str(second['id'])], 'reason': reason,
                        'same_labels_and_connections': True})
    except _ComparisonLimit:
        output['evidence']['comparison_limit_reached'] = True
    pairs = output['evidence']['suspected_pairs']
    if pairs:
        ids = list(dict.fromkeys(identifier for pair in pairs for identifier in pair['graph_ids']))
        output['issues'].append({'scope': 'document', 'field': 'graphs',
            'kind': 'possible_duplicate_panel', 'graph_ids': ids,
            'message': '部分子图的节点标签、连接及属性相同，位置证据也未能区分它们，可能把同一原图及放大窗口重复计图。'
                '请只对照完整原图重新核对独立数学图清单；真实独立同构图仍须分别保留，不能按工具裁图数量删除或合并。',
            'suspected_pairs': pairs, 'reported_graph_count': len(graphs),
            'crop_candidate_count': len(panels), 'proposal_only': True,
            'image_accuracy_certified': False})
    output['evidence']['seconds'] = round(time.monotonic()-started, 6)
    return output
