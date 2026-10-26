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
        if not isinstance(vertex, dict):
            continue
        point = vertex.get('position')
        if not isinstance(point, (tuple, list)) or len(point) != 2:
            point = [vertex.get('x'), vertex.get('y')]
        if all(type(x) in (int, float) and math.isfinite(x) and 0 <= x <= 1000 for x in point):
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


__all__ = ['panel_context']
