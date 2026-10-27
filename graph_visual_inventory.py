"""Pixel-supported marker discrepancies for a scoped visual reread.

This deliberately measures a narrow, useful case: compact coloured circular
markers whose colour separates them from their incident strokes. It neither
declares a complete vertex inventory nor changes a graph. Black-and-white,
mixed-style, clipped and weakly supported cases remain advisory. In particular,
the raw marker proposal count (which includes glyphs and arrowheads) is never
compared with the model's vertex count.
"""
from __future__ import annotations

import copy
import math
import time

import cv2
import numpy as np

VERSION = '2026-10-27-colour-marker-discrepancies-v1'
MAX_MARKERS = 160
MAX_PANELS = 32


def _box(value):
    if (isinstance(value, (list, tuple)) and len(value) == 4
            and all(type(v) in (int, float) and math.isfinite(v) for v in value)
            and 0 <= value[0] < value[2] <= 1000 and 0 <= value[1] < value[3] <= 1000):
        return list(map(float, value))
    return None


def _hue_distance(first, second):
    delta = np.abs(np.asarray(first, dtype=float) - second)
    return np.minimum(delta, 180 - delta)


def _compact_colour_component(hsv, marker):
    """Recheck a seed in original colour pixels, without morphology/repair."""
    height, width = hsv.shape[:2]
    radius = marker.get('radius_pixels', 0)
    if not (4 <= radius <= 90 and marker.get('confidence', 0) >= .85
            and not marker.get('advisory_only')):
        return None
    center = np.array([marker['x'] * (width - 1), marker['y'] * (height - 1)])
    reach = int(math.ceil(radius * 2.7 + 4))
    x, y = np.rint(center).astype(int)
    if x - reach < 0 or y - reach < 0 or x + reach >= width or y + reach >= height:
        return None
    roi = hsv[y-reach:y+reach+1, x-reach:x+reach+1]
    yy, xx = np.indices(roi.shape[:2])
    seed = roi[((xx-reach)**2 + (yy-reach)**2 <= (radius*.95)**2)
               & (roi[:, :, 1] >= 45) & (roi[:, :, 2] >= 35)]
    if len(seed) < max(12, radius*radius*.2):
        return None
    # Up to two independent colours allow a real point partly overdrawn by a
    # differently coloured incident stroke; neither colour is hard-coded.
    histogram = np.bincount(seed[:, 0], minlength=180)
    smooth = sum(np.roll(histogram, shift) for shift in range(-5, 6))
    hues = []
    for _ in range(2):
        hue = int(np.argmax(smooth))
        if smooth[hue] < max(12, len(seed)*.12):
            break
        hues.append(hue)
        smooth[_hue_distance(np.arange(180), hue) <= 18] = 0
    accepted = []
    for hue in hues:
        mask = ((_hue_distance(roi[:, :, 0], hue) <= 9)
                & (roi[:, :, 1] >= 35) & (roi[:, :, 2] >= 35)).astype(np.uint8)
        count, labels, stats, centers = cv2.connectedComponentsWithStats(mask, 8)
        for index in range(1, count):
            left, top, rw, rh, area = map(int, stats[index])
            if (min(left, top) <= 0 or left+rw >= roi.shape[1]-1 or top+rh >= roi.shape[0]-1
                    or area < radius*radius*.65 or min(rw, rh)/max(rw, rh) < .72
                    or np.linalg.norm(centers[index] - [reach, reach]) > radius*.65):
                continue
            contours = cv2.findContours(np.uint8(labels == index), cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_NONE)[0]
            if len(contours) != 1:
                continue
            hull = cv2.convexHull(contours[0])
            hull_area = float(cv2.contourArea(hull))
            perimeter = float(cv2.arcLength(hull, True))
            if hull_area <= 0 or perimeter <= 0:
                continue
            roundness = 4*math.pi*hull_area/(perimeter*perimeter)
            (cx, cy), measured_radius = cv2.minEnclosingCircle(hull)
            fill = min(1., area/hull_area)
            if (roundness < .82 or fill < .70
                    or not .70*radius <= measured_radius <= 1.25*radius
                    or math.dist((cx, cy), (reach, reach)) > radius*.35):
                continue
            accepted.append({'id': marker['id'],
                'work_center': [float(x-reach+cx), float(y-reach+cy)],
                'radius_pixels': round(float(measured_radius), 3),
                'color_hue': hue,
                'connected_stroke': bool(marker.get('connected_stroke')),
                'proof': {'source': 'original_colour_component',
                    'convex_hull_roundness': round(roundness, 4),
                    'component_fill': round(fill, 4), 'component_pixels': area,
                    'component_clipped': False, 'morphology_used': False}})
    return max(accepted, key=lambda row: row['proof']['convex_hull_roundness'], default=None)


def measure_visual_inventory(geometry, layout, *, budget):
    """Reuse the geometry document and return JSON-only bounded evidence."""
    started = time.monotonic()
    budget.check()
    source = geometry.get('source_sha256') if isinstance(geometry, dict) else None
    result = {'version': VERSION, 'source_sha256': source, 'status': 'unavailable',
              'panels': [], 'diagnostics': [], 'tool_audit': [], 'proposal_only': True}
    document = geometry.get('document') if isinstance(geometry, dict) else None
    cache = getattr(document, '_semantic_geometry_cache', {})
    if not source or cache.get('source_sha256') != source:
        result['diagnostics'].append('source_bound_geometry_unavailable')
        return result
    pool = cache.get('pool', {})
    limited = any(v is True for k, v in pool.get('limits', {}).items()
                  if k.endswith('_limit_reached') or k.endswith('_cap_reached'))
    candidates = pool.get('items', [])
    if len(candidates) > MAX_MARKERS:
        limited = True
    rgb = np.asarray(document.working)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    observed, measured_centers = [], []
    clipped_context = False
    for marker in candidates[:MAX_MARKERS]:
        budget.check()
        radius = marker.get('radius_pixels', 0)
        if marker.get('confidence', 0) >= .85 and 4 <= radius <= 90:
            mx, my = marker['x']*(hsv.shape[1]-1), marker['y']*(hsv.shape[0]-1)
            reach = math.ceil(radius*2.7+4)
            if min(mx, my, hsv.shape[1]-1-mx, hsv.shape[0]-1-my) <= reach:
                clipped_context = True
        measured = _compact_colour_component(hsv, marker)
        if measured is None:
            continue
        if any(math.dist(measured['work_center'], center)
               <= min(measured['radius_pixels'], radius) for center, radius in measured_centers):
            continue
        measured_centers.append((measured['work_center'], measured['radius_pixels']))
        point = [((measured['work_center'][i]+.5)/document.scale_xy[i]-.5)
                 / max(document.original.size[i]-1, 1)*1000 for i in (0, 1)]
        measured['position'] = [round(float(v), 3) for v in point]
        measured.pop('work_center')
        observed.append(measured)
    panels = layout.get('panels', []) if isinstance(layout, dict) else []
    for panel in panels[:MAX_PANELS]:
        if not isinstance(panel, dict) or not isinstance(panel.get('id'), str):
            continue
        box = _box(panel.get('bbox'))
        if box is None:
            continue
        members = [row for row in observed if box[0] <= row['position'][0] <= box[2]
                   and box[1] <= row['position'][1] <= box[3]]
        radii = [row['radius_pixels'] for row in members]
        # Require the whole measured set to agree; never select whichever
        # size cluster happens to match a requested vertex count.
        radius_consistent = bool(radii) and max(radii) <= min(radii)*1.35
        same_colour = bool(members) and max(float(_hue_distance(row['color_hue'], members[0]['color_hue']))
                                           for row in members) <= 12
        extent = np.ptp([row['position'] for row in members], axis=0) if members else [0, 0]
        spread = bool(members) and all(extent[i]*document.original.size[i]/1000
                                       > max(radii)*3 for i in (0, 1))
        eligible = (not limited and not clipped_context and len(members) >= 3 and radius_consistent and same_colour
                    and spread and sum(row['connected_stroke'] for row in members) >= 2)
        result['panels'].append({'region_id': panel['id'], 'bbox': box,
            'markers': copy.deepcopy(members), 'candidate_count': len(members),
            'comparison_eligible': eligible, 'proposal_only': True,
            'complete_vertex_inventory_certified': False})
    result['status'] = 'measured'
    if limited:
        result['diagnostics'].append('candidate_capacity_or_measurement_limit')
    if clipped_context:
        result['diagnostics'].append('candidate_context_clipped_count_comparison_disabled')
    result['tool_audit'].append({'tool': 'image.visual_marker_inventory', 'version': VERSION,
        'source_sha256': source, 'status': 'success', 'executed': True, 'proposal_only': True,
        'seconds': round(time.monotonic()-started, 6), 'measured_markers': len(observed)})
    return result


def _panel_match(graph, graphs, panels):
    if len(graphs) == len(panels) == 1:
        return panels[0]
    box = _box(graph.get('bbox'))
    if box is None:
        return None
    # A whole-page placeholder cannot assign one of several independent crops.
    matches = []
    for panel in panels:
        other = panel['bbox']
        overlap = max(0, min(box[2], other[2])-max(box[0], other[0])) * max(
            0, min(box[3], other[3])-max(box[1], other[1]))
        area = (box[2]-box[0])*(box[3]-box[1])
        other_area = (other[2]-other[0])*(other[3]-other[1])
        if overlap/max(area+other_area-overlap, 1.) >= .65:
            matches.append(panel)
    return matches[0] if len(matches) == 1 else None


def compare_visual_inventory(draft, evidence):
    """Produce reread targets, never replacement vertices or a certified count."""
    result = {'issues': [], 'evidence': copy.deepcopy(evidence), 'tool_audit': []}
    if not isinstance(draft, dict) or not isinstance(evidence, dict):
        return result
    graphs = draft.get('graphs', [])
    panels = evidence.get('panels', [])
    if not isinstance(graphs, list) or not isinstance(panels, list):
        return result
    assigned = {}
    for graph in graphs:
        if not isinstance(graph, dict) or not isinstance(graph.get('vertices'), list):
            continue
        panel = _panel_match(graph, graphs, panels)
        if panel is not None:
            assigned.setdefault(panel['region_id'], []).append((graph, panel))
    for matches in assigned.values():
        if len(matches) != 1:
            continue
        graph, panel = matches[0]
        observed, reported = panel['candidate_count'], len(graph['vertices'])
        if not panel.get('comparison_eligible') or observed == reported:
            continue
        result['issues'].append({'scope': 'graph', 'graph_id': str(graph.get('id', '')),
            'kind': 'visual_marker_count_conflict', 'field': 'vertices',
            'message': f'该子图有 {observed} 个经原像素支持的同类彩色圆点候选，但当前列出 {reported} 个顶点。'
                '请逐点核对圆点、邻近边名及交叉处，检查多列或漏列；候选数不是顶点真值，不能为了数量一致补删节点。',
            'candidate_count': observed, 'reported_count': reported,
            'marker_ids': [row['id'] for row in panel['markers']],
            'region_id': panel['region_id'], 'proposal_only': True,
            'image_accuracy_certified': False})
    return result
