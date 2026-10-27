"""Associate coarse reading hints with local layout windows, never with truth.

Every resulting window is used alongside the full original. Panel candidates
do not determine graph count, node identity, connectivity, or completeness.
"""
from __future__ import annotations

import copy
import math
import re


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


def _position_axes(value):
    """Interpret only a short spatial locator, never a graph name or claim."""
    if not isinstance(value, str) or len(value) > 40:
        return {}
    value = value.strip().lower()
    if not re.fullmatch(r'[上下左右中间央部排行侧方角端区域图像整页位置的\s、,，/\-]+', value):
        return {}
    axes = {}
    for axis, low, high in (('x', '左', '右'), ('y', '上', '下')):
        if low in value and high in value:
            return {}
        if low in value:
            axes[axis] = 0.
        elif high in value:
            axes[axis] = 1.
    if any(word in value for word in ('中', '央')):
        for axis in ('x', 'y'):
            axes.setdefault(axis, .5)
    return axes


def _position_candidate(candidates, position):
    axes = _position_axes(position)
    if not axes or not candidates:
        return None
    centres = [(row, ((row['bbox'][0]+row['bbox'][2])/2,
                      (row['bbox'][1]+row['bbox'][3])/2)) for row in candidates]
    limits = [(min(point[i] for _, point in centres), max(point[i] for _, point in centres))
              for i in range(2)]
    matches = []
    for row, point in centres:
        found = True
        for name, target in axes.items():
            index = 0 if name == 'x' else 1
            lo, hi = limits[index]
            if hi-lo < 80:
                continue  # The windows do not distinguish this axis.
            if abs((point[index]-lo)/(hi-lo)-target) > .22:
                found = False
        if found:
            matches.append(row)
    return matches[0] if len(matches) == 1 else None


def _nearby_candidate(candidates, points):
    """A separated nearby window is a reading hint, not a node association.

    Exact point containment is too strict for deliberately rough page hints:
    a whole row of anonymous vertices may be shifted above the actual ink.
    Use the cloud centre only when the nearest bounded window is substantially
    nearer than every alternative. Ambiguous/reused clouds remain unassigned.
    """
    if len(set(points)) < 2:
        return None
    xs, ys = zip(*points)
    if max(xs)-min(xs) > 700 or max(ys)-min(ys) > 700:
        return None
    centre = ((min(xs)+max(xs))/2, (min(ys)+max(ys))/2)
    ranked = []
    for row in candidates:
        box = row['bbox']
        if _area(box) > 450000:
            continue
        distance = math.hypot((box[0]+box[2])/2-centre[0], (box[1]+box[3])/2-centre[1])
        limit = min(250., max(100., .75*math.hypot(box[2]-box[0], box[3]-box[1])))
        ranked.append((distance, limit, row))
    ranked.sort(key=lambda item: item[0])
    if not ranked or ranked[0][0] > ranked[0][1]:
        return None
    if len(ranked) > 1 and (ranked[1][0]-ranked[0][0] < 60
                            or ranked[0][0] > .7*ranked[1][0]):
        return None
    return ranked[0][2]


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
    if not selected and model_box is None:
        nearby = _position_candidate(candidates, graph.get('position'))
        if nearby is not None:
            selected = [nearby]
            association = 'unique_spatial_locator'
        else:
            nearby = _nearby_candidate(candidates, points)
            if nearby is not None:
                selected = [nearby]
                association = 'nearby_layout_candidate'
    if selected:
        boxes = [r['bbox'] for r in selected]
        if model_box:
            boxes.append(model_box)
        # A nearby-window fallback exists precisely because the rough cloud
        # missed the ink. Expanding back to those inaccurate points can pull
        # the preceding panel's caption into the crop. Keep that candidate's
        # measured window; the consumer pads it and always keeps the full page.
        if points and association not in ('nearby_layout_candidate', 'unique_spatial_locator'):
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
