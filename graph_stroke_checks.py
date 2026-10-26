"""Original-pixel support for graph paths, independent of a model's vote.

Enhancement is useful for proposing routes. Only masks measured from the
unsharpened source image can support an accepted route. This module never
looks at filenames, reference answers, degrees or graph-family templates.
"""
from __future__ import annotations

import math
import cv2
import numpy as np

from graph_node_geometry import (boundary_distance, contains_points,
                                 estimate_marker_geometry)
from graph_connector_geometry import validate_outlined_arrow, same_outlined_instance


def sample_route(path, size, count=None):
    if not isinstance(path, list) or not 2 <= len(path) <= 128:
        return np.empty((0, 2), np.float32)
    try:
        points = np.asarray(path, np.float32)
    except (ValueError, TypeError):
        return np.empty((0, 2), np.float32)
    if points.shape != (len(path), 2) or not np.isfinite(points).all():
        return np.empty((0, 2), np.float32)
    if (points < 0).any() or (points > 1).any():
        return np.empty((0, 2), np.float32)
    points = points * np.asarray([size[0]-1, size[1]-1], np.float32)
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    cumulative = np.r_[0., np.cumsum(lengths)]
    if cumulative[-1] < 2:
        return np.empty((0, 2), np.float32)
    count = min(4096, max(24, int(count or math.ceil(cumulative[-1]/1.5))))
    samples = np.linspace(0, cumulative[-1], count)
    return np.stack([np.interp(samples, cumulative, points[:, i]) for i in range(2)], axis=1)


def _longest_false(values):
    best = current = 0
    for value in values:
        current = 0 if value else current+1
        best = max(best, current)
    return best / max(1, len(values))


class StrokeEvidence:
    """Reusable bounded distance fields; no per-edge image-sized allocation."""
    def __init__(self, document):
        self.size = document.work_size
        self.ink = document.ink_mask
        self.strong = document.strong_ink
        self.weak = document.uncertain_ink
        self.distance = cv2.distanceTransform(np.uint8(self.ink == 0), cv2.DIST_L2, 3)
        self.strong_distance = cv2.distanceTransform(np.uint8(self.strong == 0), cv2.DIST_L2, 3)
        all_ink = cv2.bitwise_or(self.ink, self.weak)
        self.all_distance = cv2.distanceTransform(np.uint8(all_ink == 0), cv2.DIST_L2, 3)
        self._radii = {}
        self._geometry = {}
        self._nearest_ink = None

    def vertex_supported(self, vertex, vertices):
        """Reject blank claimed vertices; ink alone does not prove a vertex.

        The two visual inventories still establish mathematical ownership.
        Filled markers, hollow rings and clearly inked endpoints can pass this
        local existence test without imposing a particular textbook style.
        """
        w, h = self.size
        x, y = round(vertex['x']*(w-1)), round(vertex['y']*(h-1))
        radius = self.marker_radius(vertex, vertices)
        reach = max(3, min(48, math.ceil(radius+2)))
        area = self.ink[max(0, y-reach):min(h, y+reach+1),
                        max(0, x-reach):min(w, x+reach+1)]
        return bool(np.count_nonzero(area) >= 3)

    def marker_radius(self, vertex, vertices):
        """Compatible bounding radius; precise consumers use marker_geometry."""
        return self.marker_geometry(vertex, vertices)['radius_pixels']

    def marker_geometry(self, vertex, vertices):
        w, h = self.size
        nearest = min((math.hypot((v['x']-vertex['x'])*(w-1), (v['y']-vertex['y'])*(h-1))
                       for v in vertices if v['id'] != vertex['id']), default=280.)
        key = (round(vertex['x'], 5), round(vertex['y'], 5), round(nearest, 2))
        if key not in self._geometry:
            self._geometry[key] = estimate_marker_geometry(
                self.ink, self.distance, vertex, vertices, self.size)
        return self._geometry[key]

    def inspect(self, edge, graph):
        path = edge.get('path') or []
        points = sample_route(path, self.size)
        proof = {'source': 'original_pixel_route', 'coverage': 0.,
                 'strong_coverage': 0., 'longest_gap_fraction': 1.,
                 'supported': False, 'reasons': []}
        if not len(points):
            proof['reasons'].append('empty_or_degenerate_route')
            return proof
        by_id = {v['id']: v for v in graph['vertices']}
        a, b = by_id[edge['from']], by_id[edge['to']]
        w, h = self.size
        endpoints = np.asarray([[v['x']*(w-1), v['y']*(h-1)] for v in (a, b)])
        geometries = [self.marker_geometry(v, graph['vertices']) for v in (a, b)]
        radii = [geometry['radius_pixels'] for geometry in geometries]
        error = min(max(np.linalg.norm(points[0]-endpoints[0]), np.linalg.norm(points[-1]-endpoints[1])),
                    max(np.linalg.norm(points[-1]-endpoints[0]), np.linalg.norm(points[0]-endpoints[1])))
        proof['endpoint_error_pixels'] = round(float(error), 2)
        if error > max(5., max(radii)+2):
            proof['reasons'].append('path_endpoint_mismatch')
        keep = np.ones(len(points), bool)
        for geometry in geometries:
            keep &= ~contains_points(points, geometry, margin=1.)
        interior = points[keep]
        if len(interior) < 6:
            proof['reasons'].append('no_independent_stroke_outside_nodes')
            return proof
        for v in graph['vertices']:
            if v['id'] in (a['id'], b['id']):
                continue
            geometry = self.marker_geometry(v, graph['vertices'])
            inset = min(2., min(geometry['semiaxes_pixels'])*.15)
            if np.any(contains_points(interior, geometry, margin=-inset)):
                proof['reasons'].append('path_crosses_mathematical_vertex:'+v['id'])
        index = np.rint(interior).astype(int)
        x, y = np.clip(index[:, 0], 0, w-1), np.clip(index[:, 1], 0, h-1)
        tolerance = max(1.5, min(3., min(w, h)/400))
        hit = self.distance[y, x] <= tolerance
        strong = self.strong_distance[y, x] <= tolerance
        weak = self.all_distance[y, x] <= tolerance
        coverage = float(np.mean(hit))
        strong_coverage = float(np.mean(strong))
        gap = _longest_false(hit)
        outline = edge.get('connector_evidence', {})
        if isinstance(outline, dict) and outline.get('kind') == 'outlined_arrow':
            instance = validate_outlined_arrow(outline, edge, self.size, self.distance,
                                               self.strong_distance,
                                               {a['id']:geometries[0],b['id']:geometries[1]},
                                               all_distance=self.all_distance)
            proof['connector_instance'] = instance
            proof['centreline_coverage'] = round(coverage,4)
            if instance['valid']:
                # The centre of an outlined arrow is intentionally white.
                # Its observed walls/head replace that inappropriate test;
                # no new pixels or geometric edge identity are manufactured.
                coverage = instance['coverage']
                strong_coverage = instance['strong_coverage']
                gap = instance['longest_gap_fraction']
                proof['source'] = 'original_pixel_connector_boundaries'
            else:
                proof['reasons'].extend(instance['reasons'] or ['invalid_outline_instance'])
        proof.update(coverage=round(coverage, 4), strong_coverage=round(strong_coverage, 4),
                     weak_coverage=round(float(np.mean(weak)), 4),
                     longest_gap_fraction=round(gap, 4))
        dashed = edge.get('style') in ('dashed', 'dotted')
        minimum = .36 if dashed else (.73 if proof.get('connector_instance', {}).get('valid') else .78)
        max_gap = .24 if dashed else (.20 if proof.get('connector_instance', {}).get('valid') else .18)
        if coverage < minimum or gap > max_gap:
            proof['reasons'].append('insufficient_original_stroke_support')
        # Faint ink is never deleted merely because it resembles bleed-through.
        # It stays pending until the original view resolves the ambiguity.
        if strong_coverage < (.15 if dashed else .38):
            proof['reasons'].append('weak_foreground_or_bleedthrough_ambiguity')
        if self._switches_at_crossing(points, endpoints, radii, geometries=geometries):
            proof['reasons'].append('route_switches_strokes_at_unmarked_crossing')
        oriented = points if np.linalg.norm(points[0]-endpoints[0]) <= np.linalg.norm(points[-1]-endpoints[0]) else points[::-1]
        ports = []
        for node, geometry, route in ((a, geometries[0], oriented), (b, geometries[1], oriented[::-1])):
            outside = np.flatnonzero(~contains_points(route, geometry, margin=1.))
            if not len(outside):
                continue
            start = int(outside[0])
            point = route[start]
            tangent = route[min(len(route)-1, start+4)]-point
            norm = float(np.linalg.norm(tangent))
            ports.append({'vertex': node['id'],
                          'point': [round(float(point[0]/max(1,w-1)), 6), round(float(point[1]/max(1,h-1)), 6)],
                          'outward_tangent': [round(float(x/max(norm, 1e-6)), 5) for x in tangent],
                          'footprint_confidence': geometry['confidence'],
                          'footprint_source': geometry['source']})
        proof['ports'] = ports
        if a['id'] == b['id']:
            excursion = float(np.max(np.linalg.norm(interior-endpoints[0], axis=1)))
            if excursion < max(8., radii[0]*1.8):
                proof['reasons'].append('node_rim_is_not_a_self_loop')
            hull = cv2.convexHull(interior.astype(np.float32))
            if cv2.contourArea(hull) < max(12., radii[0]**2):
                proof['reasons'].append('self_loop_has_no_enclosed_area')
            else:
                # Going out and returning on the same curve is one stroke,
                # not a closed edge. Compare non-neighbouring route sections.
                sample = interior[np.linspace(0, len(interior)-1, min(96, len(interior))).astype(int)]
                separation = np.abs(np.arange(len(sample))[:, None]-np.arange(len(sample))[None, :])
                dist = np.linalg.norm(sample[:, None, :]-sample[None, :, :], axis=2)
                dist[separation < max(5, len(sample)//8)] = np.inf
                if np.mean(np.min(dist, axis=1) < 2.) > .40:
                    proof['reasons'].append('self_loop_retraces_same_stroke')
        proof['supported'] = not proof['reasons']
        return proof

    def _switches_at_crossing(self, points, endpoints, radii, *, geometries=None):
        """A sharp turn at a four-arm ink crossing cannot silently swap lines.

        This is an ambiguity veto, not a topology repair. Marked mathematical
        vertices are handled separately; no new edge or vertex is invented.
        """
        if len(points) < 12:
            return False
        step = max(2, min(10, len(points)//12))
        angles = np.linspace(0, 2*np.pi, 96, endpoint=False)
        rays = np.stack([np.cos(angles), np.sin(angles)], axis=1)
        w, h = self.size
        for i in range(step, len(points)-step, max(1, step//2)):
            centre = points[i]
            # The whole 16px observation window plus raster tolerance must
            # be outside a node's footprint. A point outside its disk can
            # still inspect the dense fan of its legitimate outgoing edges.
            if (any(float(boundary_distance(centre, geometry)) <= 18. for geometry in geometries)
                    if geometries else any(np.linalg.norm(centre-p) < r+8 for p, r in zip(endpoints, radii))):
                continue
            before, after = centre-points[i-step], points[i+step]-centre
            den = np.linalg.norm(before)*np.linalg.norm(after)
            if den < 1 or np.dot(before, after)/den > .65:
                continue
            # At a crossing the four separated corridors persist at more
            # than one radius. A corner or arrowhead usually has 2/3 arms.
            counts = []
            for radius in (10, 16):
                ring = np.rint(centre+rays*radius).astype(int)
                ring[:, 0] = np.clip(ring[:, 0], 0, w-1)
                ring[:, 1] = np.clip(ring[:, 1], 0, h-1)
                hit = self.distance[ring[:, 1], ring[:, 0]] <= .95
                starts = np.count_nonzero(hit & ~np.roll(hit, 1))
                counts.append(starts)
            if all(4 <= count <= 6 for count in counts):
                return True
        return False

    def duplicate(self, edge, other, *, graph=None):
        """Duplicate ink, not just equal endpoints; preserve separate arcs."""
        if {edge['from'], edge['to']} != {other['from'], other['to']}:
            return False
        first_meta=edge.get('connector_evidence',{})
        second_meta=other.get('connector_evidence',{})
        if first_meta.get('kind')=='outlined_arrow' and second_meta.get('kind')=='outlined_arrow':
            return same_outlined_instance(first_meta,second_meta,self.ink,self.size)
        a, b = sample_route(edge.get('path'), self.size, 96), sample_route(other.get('path'), self.size, 96)
        if min(len(a), len(b)) < 20:
            return False
        if graph is not None:
            nodes = {node['id']: node for node in graph['vertices']}
            geometries = [self.marker_geometry(nodes[name], graph['vertices'])
                          for name in {edge['from'], edge['to']} if name in nodes]
            def exterior(route):
                keep = np.ones(len(route), bool)
                for geometry in geometries:
                    keep &= ~contains_points(route, geometry, margin=2.)
                return route[keep]
            a, b = exterior(a), exterior(b)
            if min(len(a), len(b)) < 6:
                return False
        else:
            a, b = a[8:-8], b[8:-8]
        a, b = self._project_to_ink(a), self._project_to_ink(b)
        distances = np.sqrt(np.sum((a[:, None, :]-b[None, :, :])**2, axis=2))
        # Exactly repeated approximate polylines are one observation even if
        # both sit on a neighbouring anti-aliasing/white pixel. A subpixel
        # threshold keeps genuinely separate one-pixel corridors distinct.
        if (np.mean(np.min(distances, axis=1) < .45) >= .96
                and np.mean(np.min(distances, axis=0) < .45) >= .96):
            return True
        # Test the original corridor between the routes as well as geometric
        # distance. Two offsets within one thick line are duplicate ink; two
        # real parallel lines separated by white space remain separate.
        def same_corridor(source, target, distances):
            nearest = target[np.argmin(distances, axis=1)]
            close = np.min(distances, axis=1) <= 12.
            bridges = source[:, None, :]+(nearest-source)[:, None, :]*np.linspace(0, 1, 13)[None, :, None]
            indexes = np.rint(bridges).astype(int)
            x = np.clip(indexes[:, :, 0], 0, self.size[0]-1)
            y = np.clip(indexes[:, :, 1], 0, self.size[1]-1)
            # A continuous white gap in the middle is independent evidence
            # even when two estimated centrelines are only a pixel apart.
            supported = np.mean(self.ink[y, x] > 0, axis=1) >= .90
            return np.mean(close & supported) >= .90
        return bool(same_corridor(a, b, distances) and same_corridor(b, a, distances.T))

    def _project_to_ink(self, points):
        """Resolve tiny model-coordinate offsets using nearest original ink.

        Exact pixels on two distinct thin strokes stay where they are. Points
        on either white neighbour of one thin stroke map to that same stroke.
        This projection is for identity comparisons only, never an edge repair.
        """
        if self._nearest_ink is None:
            _, labels = cv2.distanceTransformWithLabels(
                np.uint8(self.ink == 0), cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
            locations = np.column_stack(np.nonzero(self.ink)[::-1]).astype(np.float32)
            self._nearest_ink = (labels, locations)
        labels, locations = self._nearest_ink
        if not len(locations):
            return points
        index = np.rint(points).astype(int)
        x = np.clip(index[:, 0], 0, self.size[0]-1)
        y = np.clip(index[:, 1], 0, self.size[1]-1)
        nearest = locations[np.clip(labels[y, x]-1, 0, len(locations)-1)]
        tolerance = max(1.5, min(3., min(self.size)/400))
        supported = np.linalg.norm(nearest-points, axis=1) <= tolerance
        return np.where(supported[:, None], nearest, points)
