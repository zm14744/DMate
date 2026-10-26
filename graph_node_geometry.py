"""Bounded original-pixel node footprints, separate from labels and graph IDs.

The input inventory supplies a location, never a shape or a reference edge.
Ellipse hypotheses tolerate small localisation errors and broken raster rims.
They are accepted only with distributed boundary and exterior evidence. A
returned footprint describes pixels; it does not certify a mathematical node.
"""
from __future__ import annotations

import math
import cv2
import numpy as np

MAX_CONTOUR_PROPOSALS = 64
MAX_RADIAL_SEEDS = 24


def contains_points(points, geometry, margin=0.):
    points = np.asarray(points, np.float64)
    centre = np.asarray(geometry['center_pixels'], np.float64)
    axes = np.maximum(.5, np.asarray(geometry['semiaxes_pixels'], np.float64)+margin)
    angle = math.radians(geometry.get('angle_degrees', 0.))
    cosine, sine = math.cos(angle), math.sin(angle)
    delta = points-centre
    x = delta[..., 0]*cosine+delta[..., 1]*sine
    y = -delta[..., 0]*sine+delta[..., 1]*cosine
    return (x/axes[0])**2+(y/axes[1])**2 <= 1.


def boundary_distance(points, geometry):
    """Signed radial distance to the ellipse; negative values are inside."""
    points = np.asarray(points, np.float64)
    centre = np.asarray(geometry['center_pixels'], np.float64)
    axes = np.maximum(.5, np.asarray(geometry['semiaxes_pixels'], np.float64))
    angle = math.radians(geometry.get('angle_degrees', 0.))
    cosine, sine = math.cos(angle), math.sin(angle)
    delta = points-centre
    x = delta[..., 0]*cosine+delta[..., 1]*sine
    y = -delta[..., 0]*sine+delta[..., 1]*cosine
    length = np.linalg.norm(delta, axis=-1)
    norm = np.sqrt((x/axes[0])**2+(y/axes[1])**2)
    radius = np.divide(length, norm, out=np.full_like(length, min(axes)), where=norm>1e-8)
    return length-radius


def scaled_geometry(geometry, scale, *, offset=(0., 0.)):
    result = dict(geometry)
    result['center_pixels'] = [float(geometry['center_pixels'][i])*scale-offset[i] for i in range(2)]
    result['semiaxes_pixels'] = [float(value)*scale for value in geometry['semiaxes_pixels']]
    result['radius_pixels'] = float(geometry['radius_pixels'])*scale
    return result


def circle_geometry(centre, radius, *, confidence=0., source='fallback'):
    return {'center_pixels': [float(x) for x in centre],
            'semiaxes_pixels': [float(radius), float(radius)], 'angle_degrees': 0.,
            'radius_pixels': float(radius), 'kind': 'uncertain_disk',
            'confidence': float(confidence), 'boundary_support': 0., 'source': source}


def ray_entry(point, direction, geometry, *, margin=0.):
    """First forward intersection of a ray with a footprint, or None."""
    point = np.asarray(point, np.float64)
    direction = np.asarray(direction, np.float64)
    if contains_points(point, geometry, margin=margin):
        return point.copy()
    centre = np.asarray(geometry['center_pixels'], np.float64)
    axes = np.maximum(.5, np.asarray(geometry['semiaxes_pixels'], np.float64)+margin)
    angle = math.radians(geometry.get('angle_degrees', 0.))
    rotation = np.asarray([[math.cos(angle), math.sin(angle)],
                           [-math.sin(angle), math.cos(angle)]])
    q = rotation@(point-centre)/axes
    t = rotation@direction/axes
    a, b, c = float(t@t), float(2*q@t), float(q@q-1)
    discriminant = b*b-4*a*c
    if a < 1e-10 or discriminant < 0:
        return None
    roots = [x for x in ((-b-math.sqrt(discriminant))/(2*a),
                          (-b+math.sqrt(discriminant))/(2*a)) if x >= 0]
    return point+min(roots)*direction if roots else None


def _sample(distance, points, *, outside_value=1000.):
    xy = np.rint(points).astype(int)
    valid = ((xy[..., 0] >= 0) & (xy[..., 0] < distance.shape[1]) &
             (xy[..., 1] >= 0) & (xy[..., 1] < distance.shape[0]))
    x = np.clip(xy[..., 0], 0, distance.shape[1]-1)
    y = np.clip(xy[..., 1], 0, distance.shape[0]-1)
    return np.where(valid, distance[y, x], outside_value)


def _compact_component_fraction(ink, geometry, enclosing):
    """Does a small filled fit describe a whole ink blob, or a glyph junction?

    A dense patch inside a numeral can satisfy all radial disk tests. Look at
    the same connected ink immediately around that patch, excluding unrelated
    lettering and the larger ring. A genuine compact dot may have thin ports,
    but cannot leave most of its local connected component outside its fit.
    The bounded patch is not used to declare missing image pixels invisible.
    """
    centre = np.asarray(geometry['center_pixels'], np.float64)
    radius = max(geometry['semiaxes_pixels'])
    gap = min(enclosing['semiaxes_pixels'])-np.linalg.norm(
        centre-np.asarray(enclosing['center_pixels']))
    reach = min(2.2*radius, .72*gap)
    if reach < radius+1.:
        return 0.
    lo = np.maximum(0, np.floor(centre-reach).astype(int))
    hi = np.minimum([ink.shape[1], ink.shape[0]], np.ceil(centre+reach+1).astype(int))
    region = np.uint8(ink[lo[1]:hi[1], lo[0]:hi[0]] != 0)
    if not region.size:
        return 0.
    _, labels = cv2.connectedComponents(region, connectivity=8)
    yy, xx = np.mgrid[lo[1]:hi[1], lo[0]:hi[0]]
    points = np.stack([xx, yy], axis=-1)
    inside = contains_points(points, geometry, margin=.5)
    ids = labels[inside & (region != 0)]
    if not len(ids):
        return 0.
    component = int(np.argmax(np.bincount(ids)))
    local = ((labels == component) &
             (np.linalg.norm(points-centre, axis=-1) <= reach))
    return float(np.count_nonzero(local & inside)/max(1, np.count_nonzero(local)))


def estimate_marker_geometry(ink, distance, vertex, vertices, size):
    """Estimate an outer disk/ellipse with bounded ROI and hypothesis count.

    Closed contour fits are supplemented by radial-band fits, which tolerate
    gaps and slight eccentricity without lowering every circular-ring threshold.
    The largest credible enclosing outline beats a smaller internal glyph.
    Only the actual image boundary can hide a fitted arc, never the node ROI.
    Clipped fits require at least 60% visible circumference and distributed
    support throughout those visible sectors; unseen pixels provide no votes.
    """
    w, h = size
    centre = np.asarray([vertex['x']*(w-1), vertex['y']*(h-1)], np.float64)
    nearest = min((math.hypot((v['x']-vertex['x'])*(w-1), (v['y']-vertex['y'])*(h-1))
                   for v in vertices if v['id'] != vertex['id']), default=280.)
    upper = max(3, min(128, int(nearest*.45)))
    angles = np.linspace(0., 2*math.pi, 96, endpoint=False)
    directions = np.stack([np.cos(angles), np.sin(angles)], axis=1)
    proposals = []
    reach = upper+5
    lo = np.maximum(0, np.floor(centre-reach).astype(int))
    hi = np.minimum([w, h], np.ceil(centre+reach+1).astype(int))
    roi = ink[lo[1]:hi[1], lo[0]:hi[0]]
    contours, _ = cv2.findContours(roi, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    contour_count = len(contours)
    contours = sorted(contours, key=lambda row: abs(cv2.contourArea(row)), reverse=True)[:MAX_CONTOUR_PROPOSALS]
    limits = {'contours_seen': contour_count, 'contour_cap': MAX_CONTOUR_PROPOSALS,
              'contour_cap_reached': contour_count > MAX_CONTOUR_PROPOSALS,
              'radial_seed_cap': MAX_RADIAL_SEEDS}
    for contour in contours:
        if len(contour) < 12:
            continue
        area = abs(cv2.contourArea(contour))
        if area < 10:
            continue
        ellipse = cv2.fitEllipse(contour)
        (cx, cy), (da, db), angle = ellipse
        if min(da, db) < 4 or max(da, db) > 2*upper+2:
            continue
        # Long joined edge components and glyph outlines are not complete
        # elliptical boundaries merely because fitEllipse returns a result.
        if not .80 <= area/max(1., math.pi*da*db/4) <= 1.15:
            continue
        proposals.append((np.asarray([cx, cy])+lo, np.asarray([da, db])/2,
                          angle, 'closed_contour'))
    radii = np.arange(1, upper+8, dtype=np.float64)
    polar = centre+directions[None, :, :]*radii[:, None, None]
    distances = _sample(distance, polar)
    seeds = []
    for r in range(3, upper+1):
        band = min(9, max(2, round(r*.18)))
        low, high = max(1, r-band), min(len(radii), r+band+1)
        near = distances[low-1:high]
        visible = np.isfinite(_sample(distance, polar[r-1], outside_value=np.nan))
        if float(np.mean(visible)) < .60:
            continue
        support = float(np.mean((np.min(near, axis=0) <= 1.2)[visible]))
        # This only proposes a fit. Its final ellipse must independently pass
        # the stricter distributed boundary test below.
        if support >= .72:
            seeds.append((r, support, low, high, visible))
    # Spread seeds over scale; bound work even on a textured photograph.
    selected = []
    for row in sorted(seeds, key=lambda item: (-item[1], -item[0])):
        if any(abs(row[0]-old[0]) < max(2, row[0]*.06) for old in selected):
            continue
        selected.append(row)
        if len(selected) == MAX_RADIAL_SEEDS:
            break
    limits['radial_seed_cap_reached'] = len(selected) == MAX_RADIAL_SEEDS
    for r, _, low, high, visible in selected:
        near = distances[low-1:high]
        values = near+.12*np.abs(radii[low-1:high, None]-r)
        indexes = np.argmin(values, axis=0)+low-1
        points = polar[indexes, np.arange(len(angles))]
        valid = visible & (distances[indexes, np.arange(len(angles))] <= 1.2)
        if np.count_nonzero(valid) < 30:
            continue
        fit = cv2.fitEllipse(points[valid].astype(np.float32).reshape(-1, 1, 2))
        (cx, cy), (da, db), angle = fit
        proposals.append((np.asarray([cx, cy]), np.asarray([da, db])/2,
                          angle, 'distributed_radial_fit'))
    accepted = []
    for fitted_centre, axes, angle, source in proposals:
        if not np.isfinite(np.r_[fitted_centre, axes, angle]).all():
            continue
        small, large = float(min(axes)), float(max(axes))
        offset = float(np.linalg.norm(fitted_centre-centre))
        if (small < 2 or large > upper+1 or large/small > 1.8 or
                offset > max(2.8, min(12., large*.23))):
            continue
        radians = math.radians(float(angle))
        rotation = np.asarray([[math.cos(radians), -math.sin(radians)],
                               [math.sin(radians), math.cos(radians)]])
        rim = (directions*axes)@rotation.T+fitted_centre
        rim_distance = _sample(distance, rim, outside_value=np.nan)
        visible = np.isfinite(rim_distance)
        visible_fraction = float(np.mean(visible))
        if visible_fraction < .60:
            continue
        hit = rim_distance <= 1.7
        support = float(np.mean(hit[visible]))
        # Distributed evidence is necessary; one curved edge cannot stand
        # in for a node ring even when its overall fitted shape is plausible.
        sectors = [float(part[seen].mean())
                   for part, seen in zip(np.array_split(hit, 8), np.array_split(visible, 8))
                   if np.count_nonzero(seen) >= 3]
        if len(sectors) < 5 or support < .78 or min(sectors) < .42:
            continue
        # A blurred inner contour can sit several pixels inside the outer
        # wall. Look beyond a scale-bounded wall thickness, not on that wall.
        exterior_offset = max(4., min(10., large*.22))
        outside = (directions*(axes+exterior_offset))@rotation.T+fitted_centre
        outside_distance = _sample(distance, outside, outside_value=np.nan)
        outside_visible = np.isfinite(outside_distance)
        if float(np.mean(outside_visible)) < .50:
            continue
        exterior = float(np.mean(outside_distance[outside_visible] > 1.7))
        if exterior < .60:
            continue
        # Fit samples may be on the inner wall. Find a bounded outward wall
        # offset that remains supported, preserving the actual white interior.
        expansion = 0.
        for amount in (.75, 1.5, 2.25):
            test = (directions*(axes+amount))@rotation.T+fitted_centre
            test_distance = _sample(distance, test, outside_value=np.nan)
            test_visible = np.isfinite(test_distance)
            if (float(np.mean(test_visible)) >= .60 and
                    float(np.mean(test_distance[test_visible] <= .9)) >= max(.65, support-.16)):
                expansion = amount
        final_axes = axes+expansion
        inner = (directions*(axes*.55))@rotation.T+fitted_centre
        core = float(np.mean(_sample(distance, inner) <= .9))
        yy,xx=np.mgrid[-.8:.81:.16,-.8:.81:.16]
        unit=np.column_stack([xx.ravel(),yy.ravel()])
        unit=unit[np.linalg.norm(unit,axis=1)<=.8]
        core_points=(unit*axes)@rotation.T+fitted_centre
        interior_ink=float(np.mean(_sample(distance,core_points)<=.45))
        confidence = min(.99, .55*support+.30*exterior+.15*min(sectors))*(.75+.25*visible_fraction)
        geometry = {
            'center_pixels': [round(float(x), 3) for x in fitted_centre],
            'semiaxes_pixels': [round(float(x), 3) for x in final_axes],
            'angle_degrees': round(float(angle), 3),
            'radius_pixels': round(float(max(final_axes)+offset), 3),
            'kind': 'filled_marker' if core > .80 and interior_ink > .88 else 'hollow_marker',
            'interior_ink_fraction': round(interior_ink,4),
            'confidence': round(confidence, 4), 'boundary_support': round(support, 4),
            'boundary_visible_fraction': round(visible_fraction, 4),
            'boundary_clipped_by_image': bool(not np.all(visible)),
            'direct_boundary_ink_fraction': round(float(np.mean(rim_distance[visible]<=.45)),4),
            'exterior_clear_fraction': round(exterior, 4),
            'exterior_visible_fraction': round(float(np.mean(outside_visible)), 4),
            'center_offset_pixels': round(offset, 3), 'source': source,
        }
        accepted.append(geometry)
    if accepted:
        # Size only orders hypotheses that independently passed every
        # boundary/exterior gate. It is not a page-wide equal-radius prior.
        accepted.sort(key=lambda row: (max(row['semiaxes_pixels']), row['confidence']), reverse=True)
        best = accepted[0]
        # An enclosing circular stroke can be a loop or decoration around a
        # genuine central dot. Keep the small marker and expose ambiguity;
        # never erase a concentric external ring merely because it is larger.
        possible_nested = [row for row in accepted[1:]
                  if row['kind'] == 'filled_marker' and row['confidence'] >= .78
                  and row['interior_ink_fraction'] >= .92
                  and row['boundary_visible_fraction'] >= .95
                  # A closed glyph contour is not automatically a filled
                  # ellipse: its fitted rim must itself fall on real ink.
                  and row['direct_boundary_ink_fraction'] >=
                      (.70 if row['source']=='closed_contour' else .85)
                  and max(row['semiaxes_pixels'])/min(row['semiaxes_pixels']) <= 1.4
                  and max(best['semiaxes_pixels']) > max(7., 1.8*max(row['semiaxes_pixels']))
                  and np.linalg.norm(np.asarray(row['center_pixels'])-best['center_pixels'])
                      <= max(3., min(row['semiaxes_pixels'])*.5)]
        nested = []
        for row in possible_nested:
            compact = _compact_component_fraction(ink, row, best)
            row['local_component_retained_fraction'] = round(compact, 4)
            if compact >= .72:
                nested.append(row)
        limits['noncompact_inner_fits_rejected'] = len(possible_nested)-len(nested)
        if nested:
            inner = max(nested, key=lambda row: row['confidence'])
            inner = dict(inner)
            inner['kind'] = 'nested_outline_ambiguous'
            inner['confidence'] = min(inner['confidence'], .5)
            inner['uncertain_reason'] = 'outer_ring_may_be_connector_or_decoration'
            inner['outer_alternative'] = {key:best[key] for key in ('center_pixels','semiaxes_pixels','angle_degrees','boundary_support')}
            best = inner
        best['hypothesis_count'] = len(accepted)
        best['limits'] = limits
        return best
    # Preserve tiny dot and open-endpoint behaviour; the explicit confidence
    # prevents a fallback radius from masquerading as a measured outer rim.
    legacy = []
    for r in range(2, min(upper, 13)+1):
        if float(np.mean(_sample(distance, centre+directions*r) <= 1.2)) >= .72:
            legacy.append(r)
    radius = float(max(legacy)) if legacy else 3.
    result = circle_geometry(centre, radius, confidence=.25 if legacy else 0.,
                             source='local_ink_fallback')
    result['limits'] = limits
    return result
