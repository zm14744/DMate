"""Associate coarse reading hints with local layout windows, never with truth.

Every resulting window is used alongside the full original. Panel candidates
do not determine graph count, node identity, connectivity, or completeness.
"""
from __future__ import annotations

import copy
import math


def _box(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 4
            or any(type(x) not in (int, float) or not math.isfinite(x) for x in value)):
        return None
    a, b, c, d = value
    return list(value) if 0 <= a < c <= 1000 and 0 <= b < d <= 1000 else None


def _union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _overlap(a, b):
    return max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))


def _area(box):
    return max(1., (box[2]-box[0])*(box[3]-box[1]))


def _point(vertex):
    if not isinstance(vertex, dict):
        return None
    # Match the geometry adapter: an invalid optional position does not hide
    # usable x/y coordinates. Every consumer must reject the same collisions.
    for value in (vertex.get('position'), [vertex.get('x'), vertex.get('y')]):
        if (isinstance(value, (list, tuple)) and len(value) == 2
                and all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1000
                        for v in value)):
            return tuple(value)
    return None


def separate_location_hints(graphs):
    """Withdraw reused page coordinates without changing any graph content.

    Readers sometimes copy panel-local coordinates to other panels as though
    they were page coordinates. Using that same point cloud to select crops
    then directs both source readers and local tracers to the first panel.
    A complete, repeated cloud is therefore an ambiguous hint. This check
    never matches labels, infers a different location, merges graphs or adds
    a semantic uncertainty: every original graph still needs to be read.
    """
    result = copy.deepcopy(graphs)
    if not isinstance(graphs, list) or len(graphs) > 64:
        return result, {'status': 'skipped', 'reason': 'invalid_inventory',
                        'candidate_only': True, 'withdrawn_graph_ids': []}
    clouds = []
    for index, graph in enumerate(graphs):
        if not isinstance(graph, dict):
            continue
        vertices = graph.get('vertices')
        if not isinstance(vertices, list) or not 2 <= len(vertices) <= 100:
            continue
        points = []
        for vertex in vertices:
            point = _point(vertex)
            if point is None:
                break
            points.append(point)
        if len(points) == len(vertices) and len(set(points)) == len(points):
            clouds.append((index, set(points)))
    conflicted, pairs = set(), []
    for offset, (left, a) in enumerate(clouds):
        for right, b in clouds[offset+1:]:
            # Require exact reused coordinates, not nearby or similar shapes.
            # The small allowed difference handles an otherwise identical
            # template with one additional visible vertex in another panel.
            shared = len(a & b)
            if shared != min(len(a), len(b)) or shared / max(len(a), len(b)) < .8:
                continue
            conflicted.update((left, right))
            if len(pairs) < 64:
                pairs.append([left, right])
    for index in conflicted:
        for vertex in result[index]['vertices']:
            vertex.pop('x', None)
            vertex.pop('y', None)
            if isinstance(vertex.get('position'), (list, tuple)):
                vertex.pop('position', None)
        # A separate bbox or explicit layout reference may still identify
        # the right panel. Only the repeated vertex coordinates are withdrawn.
    return result, {'status': 'ambiguous_locations_withdrawn' if conflicted else 'unchanged',
        'candidate_only': True, 'original_overview_required': True,
        'withdrawn_graph_ids': [str(graphs[i].get('id', '')) for i in sorted(conflicted)],
        'conflicting_panel_indices': pairs, 'graph_content_changed': False}


def panel_context(graph, layout):
    """Return a copy of the graph with an optional enlarged reading bbox.

    Explicit window references are hints from the inventory, not a requirement.
    Otherwise a strong overlap/vertex-location match may enlarge a model hint
    to include the full measured ink component and outside arcs. Ambiguity
    leaves the original coarse hint or all-page views available to the reader.
    """
    result = copy.deepcopy(graph)
    candidates = [r for r in (layout or {}).get('panels', [])
                  if isinstance(r, dict) and _box(r.get('bbox')) is not None]
    model_box = _box(graph.get('bbox'))
    explicit = graph.get('layout_panel_ids', [])
    explicit = {str(x) for x in explicit[:24]} if isinstance(explicit, list) else set()
    selected = [r for r in candidates if str(r.get('id')) in explicit]
    association = 'inventory_window_reference' if selected else 'none'
    points = []
    for vertex in graph.get('vertices', []) if isinstance(graph.get('vertices'), list) else []:
        point = _point(vertex)
        if point is not None:
            points.append(point)
    if not selected:
        ranked = []
        for row in candidates:
            box = row['bbox']
            inside = sum(box[0] <= x <= box[2] and box[1] <= y <= box[3] for x, y in points)
            coverage = inside/len(points) if points else 0.
            shared = _overlap(box, model_box) if model_box else 0.
            iou = shared/(_area(box)+_area(model_box)-shared) if model_box else 0.
            # A broad full-page box overlapping every graph is not a useful
            # substitute for an existing per-graph window.
            not_broad = not model_box or _area(box) <= _area(model_box)*2.8
            if not_broad and (iou >= .32 or len(points) >= 2 and coverage >= .8):
                ranked.append((max(iou, coverage*.8), row))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        if ranked and (len(ranked) == 1 or ranked[0][0]-ranked[1][0] >= .12):
            selected = [ranked[0][1]]
            association = 'coarse_spatial_match'
    if selected:
        boxes = [r['bbox'] for r in selected]
        if model_box:
            boxes.append(model_box)
        # Include indicated vertices even when coarse model and tool boxes
        # disagree; the consumer adds another margin and keeps the full page.
        if points:
            xs, ys = zip(*points)
            boxes.append([max(0, min(xs)-20), max(0, min(ys)-20),
                          min(1000, max(xs)+20), min(1000, max(ys)+20)])
        result['bbox'] = _union(boxes)
    audit = {'association': association, 'candidate_only': True,
             'layout_panel_ids': [str(r.get('id')) for r in selected],
             'model_bbox': model_box, 'reading_bbox': _box(result.get('bbox')),
             'original_overview_required': True, 'geometry_required': False}
    return {'graph': result, 'audit': audit}


__all__ = ['panel_context', 'separate_location_hints']
