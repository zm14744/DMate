"""Conservative grounding of an existing vertex inventory in original pixels.

Closed marker holes and compact filled silhouettes are position proposals,
never a node inventory or an edge answer. Small hollow markers do not require
Hough's larger radius threshold. A proposal can move a supplied vertex only
when its pixels, panel ownership and mutually unique local assignment agree.
Unmarked/ambiguous vertices are retained unchanged. No OCR, label lookup,
reference image, model call, graph-name rule or topology completion is used.
"""
from __future__ import annotations

import copy
import hashlib
import math

import cv2
import numpy as np

from image_evidence import DocumentEvidence, analyze_document
from graph_node_geometry import (circle_geometry, contains_points,
                                 estimate_marker_geometry, _compact_component_fraction)

VERSION = 'original-marker-grounding-v1'
MAX_MARKERS = 256
MAX_HOLES = 1024
MAX_FILLED_COMPONENTS = 1024
MAX_OUTLINE_HYPOTHESES = 512
MAX_VERTICES = 160
ANGLES = np.linspace(0., 2*math.pi, 64, endpoint=False)
DIRECTIONS = np.column_stack([np.cos(ANGLES), np.sin(ANGLES)])


def _document(image):
    return image if isinstance(image, DocumentEvidence) else analyze_document(image)


def _source(document):
    # Provenance only: never an image-hash answer cache or a lookup key.
    value = hashlib.sha256(document.working.tobytes()).hexdigest()
    return {'working_rgb_sha256': value, 'work_size': list(document.work_size),
            'original_size': list(document.original.size)}


def _sample(mask, points):
    xy = np.rint(points).astype(int)
    valid = ((xy[..., 0] >= 0) & (xy[..., 0] < mask.shape[1])
             & (xy[..., 1] >= 0) & (xy[..., 1] < mask.shape[0]))
    x = np.clip(xy[..., 0], 0, mask.shape[1]-1)
    y = np.clip(xy[..., 1], 0, mask.shape[0]-1)
    return mask[y, x] & valid, valid


def _radial_proof(ink, center, radius, *, hollow, signal=None):
    """Check a complete small rim/disk, clear exterior and circular extent.

    All samples come from the unsharpened original-contrast mask. Image-clipped
    circles are deliberately left to the existing footprint/visual review; a
    small ROI cannot make absent pixels count as an invisible circumference.
    """
    if not np.isfinite(np.r_[center, radius]).all() or not 1.5 <= radius <= 90:
        return None
    reach = min(140., max(7., radius*2.4+3))
    radii = np.arange(.5, reach+.1, .5)
    polar = np.asarray(center)+radii[:, None, None]*DIRECTIONS
    hits, valid = _sample(ink, polar)
    def rim_samples(points):
        # Bilinear sampling measures fractional coverage of original pixels.
        # It avoids missing a one-pixel diagonal solely through rounding; no
        # closing, dilation, sharpening or invented wall is used as evidence.
        values = cv2.remap(signal if signal is not None else np.uint8(ink)*255,
            points[..., 0].astype(np.float32), points[..., 1].astype(np.float32),
            cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        return values >= 51
    if not valid.all():
        return None
    if hollow:
        hits = rim_samples(polar)
        # First dark wall following the supplied enclosed white hole.
        starts = np.argmax(hits, axis=0)
        found = hits.any(axis=0)
        if np.mean(found) < .94:
            return None
        inner = radii[starts]
        if np.median(inner) < .7 or np.median(inner) > radius*1.5+1:
            return None
    else:
        starts = np.zeros(len(ANGLES), dtype=int)
        found = np.ones(len(ANGLES), dtype=bool)
    ends = []
    for column, start in enumerate(starts):
        if not found[column]:
            continue
        # Two consecutive half-pixel samples avoid treating one aliased pixel
        # as a wall exit. True connector ports may have no exit within reach.
        after = max(int(start)+2, int(radius*.5/.5))
        clear = np.flatnonzero(~hits[after:-1, column] & ~hits[after+1:, column])
        if len(clear):
            ends.append(radii[after+int(clear[0])])
    if len(ends) < 40:
        return None
    outer = float(np.median(ends))
    if not 2 <= outer <= 90:
        return None
    deviation = float(np.median(np.abs(np.asarray(ends)-outer))/outer)
    if deviation > .24:
        return None
    # Thin crossing lines and bold glyph joints do not fill a round disk.
    core, _ = _sample(ink, np.asarray(center)+DIRECTIONS*outer*.55)
    if not hollow and float(np.mean(core)) < .94:
        return None
    rim_radii = np.maximum(.5, outer-np.asarray([.75, 1.25, 1.75]))
    rim, _ = _sample(ink, np.asarray(center)+rim_radii[:, None, None]*DIRECTIONS)
    if hollow:
        rim = rim_samples(np.asarray(center)+rim_radii[:, None, None]*DIRECTIONS)
    distributed = np.any(rim, axis=0)
    coverage = float(np.mean(distributed))
    sectors = [float(x.mean()) for x in np.array_split(distributed, 8)]
    outside, _ = _sample(ink, np.asarray(center)+DIRECTIONS*(outer+max(2., outer*.30)))
    clear_fraction = float(np.mean(~outside))
    if coverage < .82 or min(sectors) < .50 or clear_fraction < .56:
        return None
    return {'radius_pixels': round(outer, 3), 'rim_support': round(coverage, 4),
            'minimum_sector_support': round(min(sectors), 4),
            'exterior_clear_fraction': round(clear_fraction, 4),
            'radial_median_deviation': round(deviation, 4),
            'core_ink_fraction': round(float(np.mean(core)), 4),
            'rim_sampling': 'original_bilinear_coverage' if hollow else 'original_nearest_pixel'}


def _contour_roundness(contour):
    area = abs(float(cv2.contourArea(contour)))
    perimeter = float(cv2.arcLength(contour, True))
    return area, 4*math.pi*area/max(perimeter*perimeter, 1.)


def _large_outlines(document):
    """Find independently supported enclosing rings, including numbered nodes.

    A printed numeral may break up the white-hole contour, while pink/grey
    node rims can remain visible in original colour gradients. Hough results
    are seeds only: distributed original gradient support and the existing
    original-ink ellipse validator must independently agree. No inventory or
    expected count is supplied to this search.
    """
    gray = cv2.cvtColor(np.asarray(document.working), cv2.COLOR_RGB2GRAY)
    seeds = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, 1, 12, param1=80,
                             param2=35, minRadius=12, maxRadius=90)
    seeds = [] if seeds is None else seeds[0]
    gradient = cv2.Canny(gray, 40, 80)
    distance = cv2.distanceTransform(255-gradient, cv2.DIST_L2, 5)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    ink_distance = cv2.distanceTransform(255-document.ink_mask, cv2.DIST_L2, 5)
    height, width = gray.shape
    found, refinement_limited = [], False
    for x, y, radius in seeds[:MAX_OUTLINE_HYPOTHESES]:
        rim = np.asarray([x, y])+radius*DIRECTIONS
        xy = np.rint(rim).astype(int)
        if (np.any(xy < 0) or np.any(xy[:, 0] >= width) or np.any(xy[:, 1] >= height)):
            continue
        hit = distance[xy[:, 1], xy[:, 0]] <= 2.5
        support = float(np.mean(hit))
        if support < .78 or min(float(v.mean()) for v in np.array_split(hit, 8)) < .50:
            continue
        # Dense body text puts some edge near almost any imaginary circle.
        # Its gradients do not consistently point along that circle's radial
        # normal. Require distributed orientation evidence in the original
        # pixels before asking the bounded ellipse refiner for a shape.
        band = np.asarray([x, y])+(radius+np.arange(-2., 2.1, .5))[:, None, None]*DIRECTIONS
        xs, ys = band[..., 0].astype(np.float32), band[..., 1].astype(np.float32)
        dx = cv2.remap(gx, xs, ys, cv2.INTER_LINEAR)
        dy = cv2.remap(gy, xs, ys, cv2.INTER_LINEAR)
        magnitude = np.hypot(dx, dy)
        normal = np.abs(dx*DIRECTIONS[None, :, 0]+dy*DIRECTIONS[None, :, 1])/np.maximum(magnitude, 1.)
        aligned = np.any((normal >= .92) & (magnitude >= 60), axis=0)
        aligned_support = float(np.mean(aligned))
        if aligned_support < .88 or min(float(v.mean()) for v in np.array_split(aligned, 8)) < .625:
            continue
        seed = {'id': 'unassigned_pixel_seed', 'x': float(x/max(width-1, 1)),
                'y': float(y/max(height-1, 1))}
        geometry = estimate_marker_geometry(document.ink_mask, ink_distance, seed, [seed], document.work_size)
        refinement_limited |= any(value is True for key, value in geometry.get('limits', {}).items()
                                  if key.endswith('_cap_reached'))
        if (geometry['confidence'] < .80 or not 12 <= geometry['radius_pixels'] <= 90
                or not .70*radius <= max(geometry['semiaxes_pixels']) <= 1.30*radius):
            continue
        found.append({'center': list(geometry['center_pixels']), 'radius': geometry['radius_pixels'],
            'kind': 'hollow', 'confidence': min(.98, .5*support+.5*geometry['confidence']),
            # A missing measured port never becomes a claim of an edge or an
            # isolated node. Its conservative attraction bound is the radius.
            'connected_stroke': False,
            'evidence': {'source': 'original_gradient_and_ink_outline',
                         'original_gradient_rim_support': round(support, 4),
                         'original_radial_gradient_support': round(aligned_support, 4),
                         'geometry': geometry}})
    return found, len(seeds), refinement_limited


def _pool(document):
    ink = document.ink_mask != 0
    height, width = ink.shape
    contours, hierarchy = cv2.findContours(np.uint8(ink)*255, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    candidates, holes = [], []
    for index, contour in enumerate(contours):
        parent = int(hierarchy[0, index, 3]) if hierarchy is not None else -1
        if parent < 0:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if not (3 <= min(w, h) <= max(w, h) <= 170 and .66 <= w/h <= 1.5):
            continue
        area, roundness = _contour_roundness(contour)
        if area < 3 or roundness < .72:
            continue
        moments = cv2.moments(contour)
        center = (moments['m10']/moments['m00'], moments['m01']/moments['m00'])
        box = cv2.boundingRect(contours[parent])
        holes.append((max(box[2:]), area, center, max(w, h)/2, parent, box, roundness))
    # Scan bounded hypotheses, preferring long connected ink over text holes;
    # ordering does not supply expected counts or a preferred graph structure.
    holes.sort(key=lambda item: (-item[0], -item[1], item[2]))
    for _, area, center, radius, parent, box, roundness in holes[:MAX_HOLES]:
        proof = _radial_proof(ink, center, radius, hollow=True, signal=document.ink_mask)
        if not proof:
            continue
        outer = proof['radius_pixels']
        connected = max(box[2:]) >= max(25., outer*7)
        parent_area, parent_roundness = _contour_roundness(contours[parent])
        isolated = (.70 <= box[2]/max(box[3], 1) <= 1.42
                    and parent_roundness >= .75 and .08 <= area/max(parent_area, 1) <= .85)
        if not connected and not isolated:
            continue
        confidence = min(.99, .50*proof['rim_support']+.25*proof['exterior_clear_fraction']
                         +.25*(1-proof['radial_median_deviation']))
        candidates.append({'center': list(center), 'radius': outer, 'kind': 'hollow',
            'confidence': confidence, 'connected_stroke': connected,
            'evidence': {**proof, 'source': 'closed_original_ink_hole',
                         'hole_area_pixels': round(area, 3), 'hole_roundness': round(roundness, 4),
                         'component_bbox_pixels': list(box), 'component': parent}})

    filled_seen = 0
    ink_depth = cv2.distanceTransform(np.uint8(ink), cv2.DIST_L2, 5)
    # Opening supplies seeds only; acceptance is rechecked in the ORIGINAL
    # ink mask. It never bridges a gap or changes the pixels used as evidence.
    for diameter in (3, 5, 9, 17):
        opened = cv2.morphologyEx(np.uint8(ink)*255, cv2.MORPH_OPEN,
                                 cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (diameter, diameter)))
        count, _, stats, centers = cv2.connectedComponentsWithStats(opened, 8)
        for index in range(1, count):
            x, y, w, h, area = (int(value) for value in stats[index])
            if not (4 <= min(w, h) <= max(w, h) <= 170 and .78 <= w/h <= 1.28
                    and .64 <= area/max(w*h, 1) <= .94):
                continue
            filled_seen += 1
            if filled_seen > MAX_FILLED_COMPONENTS:
                break
            center = centers[index].tolist()
            radius = (w+h)/4
            proof = _radial_proof(ink, center, radius, hollow=False)
            if not proof:
                continue
            # Connected support is measured outside the fitted disk, not from
            # opening's severed component. A single compact isolated dot is
            # retained as a candidate but cannot attract a distant label.
            ray = np.asarray(center)+np.arange(proof['radius_pixels']+1,
                proof['radius_pixels']+max(12., proof['radius_pixels']*4), 1.)[:, None, None]*DIRECTIONS
            samples, visible = _sample(ink, ray)
            ports = np.mean(samples & visible, axis=0) >= .82
            connected = bool(np.any(ports))
            # A rasterized bend/thick patch on a line can be locally round.
            # An attached disk must be visibly wider than its own outgoing
            # strokes; matching a nearby label cannot supply this evidence.
            port_halfwidth = 0.
            if connected:
                xy = np.rint(ray).astype(int)
                xs = np.clip(xy[..., 0], 0, width-1)
                ys = np.clip(xy[..., 1], 0, height-1)
                depths = ink_depth[ys, xs]
                port_halfwidth = max(float(np.median(depths[:, k][samples[:, k]]))
                                     for k in np.flatnonzero(ports))
            distinguished = not connected or proof['radius_pixels'] >= port_halfwidth*1.8+.5
            confidence = min(.98, .5*proof['rim_support']+.25*proof['exterior_clear_fraction']
                             +.25*(1-proof['radial_median_deviation']))
            candidates.append({'center': center, 'radius': proof['radius_pixels'], 'kind': 'filled',
                'confidence': confidence if distinguished else min(confidence, .65),
                'connected_stroke': connected,
                'evidence': {**proof, 'source': 'opened_seed_original_disk_validation',
                             'opening_diameter_pixels': diameter,
                             'outgoing_stroke_halfwidth_pixels': round(port_halfwidth, 3),
                             'distinct_from_stroke_thickness': distinguished}})
        if filled_seen > MAX_FILLED_COMPONENTS:
            break

    outlines, outline_seen, outline_refinement_limited = _large_outlines(document)
    # An internal numeral or a tiny joint on an enclosing node's rim must not
    # become a rival node centre. A genuinely compact small dot/ring inside a
    # larger loop survives this check, so the enclosing circle cannot swallow
    # such a node merely by being larger.
    retained = []
    for candidate in candidates:
        nested_glyph = False
        for outline in outlines:
            geometry = outline['evidence']['geometry']
            if (candidate['radius'] >= .40*min(geometry['semiaxes_pixels'])
                    or not contains_points(candidate['center'], geometry, margin=2.)):
                continue
            small = circle_geometry(candidate['center'], candidate['radius'])
            compact = _compact_component_fraction(document.ink_mask, small, geometry)
            if compact < .72:
                nested_glyph = True
                break
        if not nested_glyph:
            retained.append(candidate)
    candidates = retained+outlines

    # Multiple thresholds/openings of one physical mark remain one position.
    found = []
    for candidate in sorted(candidates, key=lambda item: (-item['confidence'], item['center'])):
        if any(max(candidate['radius'], other['radius']) <= 2*min(candidate['radius'], other['radius'])
               and math.dist(candidate['center'], other['center']) <= max(2., .55*min(candidate['radius'], other['radius']))
               for other in found):
            continue
        found.append(candidate)
        if len(found) >= MAX_MARKERS:
            break
    found.sort(key=lambda item: (item['center'][1], item['center'][0]))
    items = []
    for index, candidate in enumerate(found):
        x, y = candidate.pop('center')
        items.append({'id': f'marker_{index+1}', 'x': x/max(width-1, 1), 'y': y/max(height-1, 1),
                      'radius_pixels': candidate.pop('radius'), **candidate})
    return {'version': VERSION, 'source': _source(document), 'items': items,
            'limits': {'max_markers': MAX_MARKERS, 'hole_hypotheses_seen': len(holes),
                       'max_hole_hypotheses': MAX_HOLES, 'hole_limit_reached': len(holes) > MAX_HOLES,
                       'filled_hypotheses_seen': filled_seen,
                       'filled_limit_reached': filled_seen > MAX_FILLED_COMPONENTS,
                       'outline_hypotheses_seen': outline_seen,
                       'max_outline_hypotheses': MAX_OUTLINE_HYPOTHESES,
                       'outline_limit_reached': outline_seen > MAX_OUTLINE_HYPOTHESES,
                       'outline_refinement_limit_reached': outline_refinement_limited,
                       'marker_limit_reached': len(found) == MAX_MARKERS}}


def marker_proposals(image):
    """Return bounded CPU proposals plus source/size provenance; no vertex IDs."""
    return _pool(_document(image))


def _box(graph):
    try:
        a, b, c, d = graph['bbox']
        if all(type(x) in (int, float) and math.isfinite(x) for x in (a, b, c, d)) and 0 <= a < c <= 1 and 0 <= b < d <= 1:
            return a, b, c, d
    except (KeyError, TypeError, ValueError):
        pass
    return None


def _point(vertex, size):
    x, y = vertex.get('x'), vertex.get('y')
    if (type(x) not in (int, float) or type(y) not in (int, float)
            or not math.isfinite(x) or not math.isfinite(y) or not 0 <= x <= 1 or not 0 <= y <= 1):
        return None
    return [x*max(size[0]-1, 1), y*max(size[1]-1, 1)]


def ground_nodes(image, graphs, proposals=None):
    """Return a deep copy with only uniquely supported vertex positions moved.

    Use on the NODE inventory before connector generation. Optional proposals
    are a diagnostic reuse contract, not trusted model input: the current image
    is independently remeasured and a changed/foreign pool is rejected. Passing
    an existing DocumentEvidence avoids decoding/preprocessing a second time.
    Each graph gets marker_grounding and node_position_evidence. Unchanged
    nodes retain their original x/y values, labels, IDs and inventory flags.
    """
    output = copy.deepcopy(graphs)
    document = _document(image)
    pool = _pool(document)
    if proposals is not None and proposals != pool:
        raise ValueError('marker_proposals_do_not_match_original_pixels')
    size = document.work_size
    diagonal = math.hypot(*size)
    items = pool['items']
    nodes = [(gi, vi, vertex, _point(vertex, size)) for gi, graph in enumerate(output)
             for vi, vertex in enumerate(graph.get('vertices', []))]
    limited = any(value for key, value in pool['limits'].items() if key.endswith('_limit_reached'))
    if len(nodes) > MAX_VERTICES or limited:
        for graph in output:
            graph['marker_grounding'] = {'version': VERSION, 'status': 'not_applied',
                'reason': 'vertex_budget_exceeded' if len(nodes) > MAX_VERTICES else 'marker_candidate_budget_exceeded',
                'source': copy.deepcopy(pool['source']), 'limits': copy.deepcopy(pool['limits'])}
        return output
    bounds = [_box(graph) for graph in output]
    relations, reverse = {}, {}
    reasons = {}
    for ni, (gi, vi, vertex, point) in enumerate(nodes):
        if point is None:
            reasons[ni] = 'invalid_position'
            continue
        if bounds[gi] is None:
            reasons[ni] = 'panel_bounds_missing'
            continue
        nearest = min((math.dist(point, other[3]) for oi, other in enumerate(nodes)
                       if oi != ni and other[0] == gi and other[3] is not None), default=diagonal*.20)
        # A broad displacement bound only limits search. It is never evidence
        # of a marker and cannot override pixel/ambiguity/ownership checks.
        reach = min(diagonal*.10, max(8., nearest*.70))
        candidates = []
        for mi, marker in enumerate(items):
            if marker['confidence'] < .84:
                continue
            radius = marker['radius_pixels']
            mx, my = marker['x'], marker['y']
            owners = [index for index, box in enumerate(bounds) if box is not None
                      and box[0]-.012 <= mx <= box[2]+.012 and box[1]-.012 <= my <= box[3]+.012]
            if owners != [gi]:
                continue  # Overlapping panels do not get arbitrary ownership.
            distance = math.dist(point, [mx*(size[0]-1), my*(size[1]-1)])
            cap = reach if marker['connected_stroke'] else min(reach, max(3., radius*1.25))
            if distance <= cap and radius < max(4., nearest*.40):
                candidates.append((distance, mi))
                reverse.setdefault(mi, []).append((distance, ni))
        relations[ni] = sorted(candidates)
        if not candidates:
            reasons[ni] = 'no_reliable_local_marker'
    selected = {}
    for ni, candidates in relations.items():
        if not candidates:
            continue
        distance, mi = candidates[0]
        radius = items[mi]['radius_pixels']
        margin = max(3., 1.1*radius)
        competitors = sorted(reverse[mi])
        if ((len(candidates) > 1 and candidates[1][0]-distance <= margin)
                or competitors[0][1] != ni
                or (len(competitors) > 1 and competitors[1][0]-distance <= margin)):
            reasons[ni] = 'ambiguous_one_to_one_assignment'
            continue
        selected[ni] = (mi, distance)
    for gi, graph in enumerate(output):
        evidence, unresolved = [], []
        for ni, (group, vi, vertex, point) in enumerate(nodes):
            if group != gi:
                continue
            if ni not in selected:
                unresolved.append({'vertex': vertex.get('id'), 'reason': reasons.get(ni, 'assignment_not_unique')})
                continue
            mi, distance = selected[ni]
            marker = items[mi]
            before = [vertex['x'], vertex['y']]
            after = [marker['x'], marker['y']]
            evidence.append({'vertex': vertex.get('id'), 'source': VERSION,
                'marker_id': marker['id'], 'node_position': before, 'pixel_position': after,
                'shift_work_pixels': round(distance, 3), 'kind': marker['kind'],
                'confidence': round(marker['confidence'], 4), 'pixel_evidence': copy.deepcopy(marker['evidence'])})
            vertex['x'], vertex['y'] = after
        prior = graph.get('node_position_evidence')
        graph['node_position_evidence'] = (copy.deepcopy(prior) if isinstance(prior, list) else [])+evidence
        graph['marker_grounding'] = {'version': VERSION, 'status': 'grounded' if not unresolved else 'partial',
            'grounded_vertices': len(evidence), 'retained_vertices': unresolved,
            'source': copy.deepcopy(pool['source']), 'limits': copy.deepcopy(pool['limits']),
            'position_evidence_only': True}
    return output
