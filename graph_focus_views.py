"""Bounded, source-only crops addressed by existing text/graph/marker identities.

Issue evidence boxes and prose never choose pixels. Text locations come from
the caller's existing OCR hints; graph locations come from the current fixed
inventory and complete stored paths. A crop is another observation, not proof
that a proposed label, endpoint or route is correct. CPU marker identities
select measured source locations; they never grant mathematical vertex status.
"""
from __future__ import annotations

import math
from collections import Counter

from PIL import Image

from image_evidence import decode_document_image


VERSION = '2026-10-26-focused-original-views-v1'
MAX_VIEWS = 3
MAX_VIEW_PIXELS = 1_000_000
MAX_TOTAL_PIXELS = 2_000_000
MAX_SIDE = 1600
MAX_SCALE = 6.
MAX_GRAPHS = 48
MAX_ISSUES = 128
MAX_HINTS = 128
MAX_BODY_REGIONS = 128
MAX_MARKERS = 256
MAX_ENTITIES = 512
MAX_REFERENCES = 128
MAX_TARGETS = 256
MAX_OMISSIONS = 128


def _identifier(value):
    return type(value) is str and 0 < len(value) <= 128


def _bounds(value, scale=1.):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in value):
        return None
    a, b, c, d = [v/scale for v in value]
    return (a, b, c, d) if 0 <= a < c <= 1 and 0 <= b < d <= 1 else None


def _point(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    return value if all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1
                        for v in value) else None


def _area(rect):
    return (rect[2]-rect[0])*(rect[3]-rect[1])


def _intersection(a, b):
    return max(0, min(a[2], b[2])-max(a[0], b[0]))*max(
        0, min(a[3], b[3])-max(a[1], b[1]))


def _padded_rect(bounds, size, *, text=False):
    width, height = size
    left, top, right, bottom = bounds
    if text:
        px = py = max(4., (bottom-top)*.4)
    else:
        # Include nearby labels/node outlines without guessing their text.
        context = max(12., min(64., max(size)*.06))
        px, py = max(context, (right-left)*.08), max(context, (bottom-top)*.08)
    return (max(0, math.floor(left-px)), max(0, math.floor(top-py)),
            min(width, math.ceil(right+px)), min(height, math.ceil(bottom+py)))


def _merge_into(left, right):
    a, b = left['rect'], right['rect']
    left['rect'] = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
    left['hint_ids'].update(right['hint_ids'])
    left['body_region_ids'].update(right['body_region_ids'])
    left['marker_ids'].update(right['marker_ids'])
    left['issue_ids'].update(right['issue_ids'])
    left['targets'].extend(right['targets'])
    for gid, entities in right['graph_entities'].items():
        group = left['graph_entities'].setdefault(gid, {'edge_ids': set(), 'vertex_ids': set()})
        for key in group:
            group[key].update(entities[key])


def build_focused_views(original, graphs, issues, *, hints=None, body_regions=None,
                        markers=None, check_deadline=None):
    """Return ``images, coordinate_maps, diagnostics`` without changing inputs.

    ``graphs`` use the application's internal 0..1 coordinates. Hint bboxes
    and caller-validated body region bboxes use original_1000. Body region
    identities are a separate namespace from OCR hints and require an explicit
    original source. Returned pixel rectangles are half-open crop bounds;
    returned original_bbox values divide those bounds by the full image size.
    Optional ``markers`` are a caller-owned list of CPU measurements with
    id/x/y/radius_x/radius_y in original_1000. Their independent marker_ids
    namespace does not create, attach, move or confirm any graph vertex.
    Only caller-owned IDs can select pixels. No issue-supplied bbox is read.
    """
    if not isinstance(original, Image.Image):
        raise ValueError('focused_views_requires_original_image')
    source = decode_document_image(original)
    width, height = source.size
    capacity = {}
    omissions, omission_count = [], 0
    malformed = Counter()

    def check():
        if check_deadline is not None:
            check_deadline()

    def omit(issue_id, reason, *, kind=None, identity=None, graph_id=None):
        nonlocal omission_count
        omission_count += 1
        if len(omissions) < MAX_OMISSIONS:
            row = {'issue_id': issue_id, 'reason': reason}
            if kind is not None:
                row['entity_type'] = kind
            if identity is not None and _identifier(identity):
                row['entity_id'] = identity
            if graph_id is not None and _identifier(graph_id):
                row['graph_id'] = graph_id
            omissions.append(row)

    def index(rows, limit, kind):
        if not isinstance(rows, list):
            malformed['invalid_'+kind+'_list'] += 1
            return {}
        if len(rows) > limit:
            capacity[kind+'_limit_reached'] = True
        selected = rows[:limit]
        malformed['invalid_'+kind+'_records'] += sum(
            not isinstance(row, dict) or not _identifier(row.get('id')) for row in selected)
        counts = Counter(row['id'] for row in selected
                         if isinstance(row, dict) and _identifier(row.get('id')))
        malformed['ambiguous_'+kind+'_ids'] += sum(n > 1 for n in counts.values())
        return {row['id']: row for row in selected if isinstance(row, dict)
                and _identifier(row.get('id')) and counts[row['id']] == 1}

    check()
    by_graph = index(graphs, MAX_GRAPHS, 'graph')
    by_hint = index((hints or {}).get('items', []) if isinstance(hints, dict) else [],
                    MAX_HINTS, 'hint')
    if isinstance(body_regions, list) and len(body_regions) > MAX_BODY_REGIONS:
        # Do not accept a prefix whose identity could be duplicated beyond the
        # cap. The caller must supply a bounded, unambiguous region inventory.
        capacity['body_region_limit_reached'] = True
        by_body_region = {}
    else:
        by_body_region = index(body_regions, MAX_BODY_REGIONS, 'body_region') \
            if body_regions is not None else {}
    if isinstance(markers, list) and len(markers) > MAX_MARKERS:
        # A duplicate beyond a truncated prefix cannot establish identity.
        capacity['marker_limit_reached'] = True
        by_marker = {}
    else:
        by_marker = index(markers, MAX_MARKERS, 'marker') if markers is not None else {}
    by_issue = index(issues, MAX_ISSUES, 'issue')
    graph_indexes = {}
    for gid, graph in by_graph.items():
        check()
        if _bounds(graph.get('bbox')) is None:
            malformed['invalid_graph_bounds'] += 1
            continue
        graph_indexes[gid] = (
            index(graph.get('vertices', []), MAX_ENTITIES, 'vertex'),
            index(graph.get('edges', []), MAX_ENTITIES, 'edge'))
    targets = []

    def references(issue, field, *, report_duplicates=False):
        values = issue.get(field, [])
        if not isinstance(values, list):
            omit(issue['id'], 'invalid_reference_list', kind=field)
            return []
        if len(values) > MAX_REFERENCES:
            capacity['reference_limit_reached'] = True
            omit(issue['id'], 'reference_capacity_reached', kind=field)
        seen, result = set(), []
        for value in values[:MAX_REFERENCES]:
            if not _identifier(value):
                omit(issue['id'], 'invalid_reference_id', kind=field)
            elif value not in seen:
                seen.add(value)
                result.append(value)
            elif report_duplicates:
                omit(issue['id'], 'duplicate_reference_id', kind=field, identity=value)
        return result

    def add(rect, issue_id, *, hint_id=None, body_region_id=None, marker_id=None,
            gid=None, edge_ids=(), vertex_ids=()):
        if len(targets) >= MAX_TARGETS:
            capacity['target_limit_reached'] = True
            omit(issue_id, 'target_capacity_reached',
                 kind='marker' if marker_id else 'body_region' if body_region_id else None,
                 identity=marker_id or body_region_id or hint_id, graph_id=gid)
            return
        entities = {gid: {'edge_ids': set(edge_ids), 'vertex_ids': set(vertex_ids)}} if gid else {}
        targets.append({'rect': rect, 'issue_ids': {issue_id},
                        'hint_ids': {hint_id} if hint_id else set(),
                        'body_region_ids': {body_region_id} if body_region_id else set(),
                        'marker_ids': {marker_id} if marker_id else set(),
                        'graph_entities': entities,
                        'targets': [{'issue_id': issue_id, 'hint_id': hint_id, 'graph_id': gid,
                                     'body_region_id': body_region_id,
                                     'marker_id': marker_id,
                                     'edge_ids': list(edge_ids), 'vertex_ids': list(vertex_ids)}]})

    def vertex_points(vertex, graph):
        point = _point([vertex.get('x'), vertex.get('y')])
        if point is None:
            return None
        points = [(point[0]*(width-1), point[1]*(height-1))]
        geometries = graph.get('node_geometry_evidence')
        footprint = geometries.get(vertex['id'], {}) if isinstance(geometries, dict) else {}
        outline = footprint.get('footprint_outline') if isinstance(footprint, dict) else None
        if (isinstance(outline, list) and 3 <= len(outline) <= 32 and
                all(isinstance(p, (list, tuple)) and len(p) == 2 and
                    all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1000 for v in p)
                    for p in outline)):
            points.extend((x/1000*(width-1), y/1000*(height-1)) for x, y in outline)
        return points

    def point_rect(points):
        xs, ys = zip(*points)
        return _padded_rect((min(xs), min(ys), max(xs), max(ys)), source.size)

    for iid, issue in by_issue.items():
        check()
        before = len(targets)
        hint_ids = references(issue, 'hint_ids')
        body_region_ids = references(issue, 'body_region_ids', report_duplicates=True)
        marker_ids = references(issue, 'marker_ids', report_duplicates=True)
        edge_ids = references(issue, 'edge_ids')
        vertex_ids = references(issue, 'vertex_ids')
        for hid in hint_ids:
            hint = by_hint.get(hid)
            box = _bounds(hint.get('bbox'), 1000.) if hint else None
            if box is None:
                omit(iid, 'unknown_ambiguous_or_unlocated_hint', kind='hint', identity=hid)
                continue
            a, b, c, d = box
            add(_padded_rect((a*width, b*height, c*width, d*height), source.size, text=True), iid,
                hint_id=hid)
        for rid in body_region_ids:
            region = by_body_region.get(rid)
            if region is None:
                reason = ('body_region_inventory_capacity_reached'
                          if capacity.get('body_region_limit_reached') else 'unknown_or_ambiguous_body_region')
                omit(iid, reason, kind='body_region', identity=rid)
                continue
            if region.get('source') != 'original':
                omit(iid, 'body_region_source_not_original', kind='body_region', identity=rid)
                continue
            box = _bounds(region.get('bbox'), 1000.)
            if box is None:
                omit(iid, 'invalid_body_region_bounds', kind='body_region', identity=rid)
                continue
            a, b, c, d = box
            add(_padded_rect((a*width, b*height, c*width, d*height), source.size, text=True), iid,
                body_region_id=rid)
        for mid in marker_ids:
            marker = by_marker.get(mid)
            if marker is None:
                reason = ('marker_inventory_capacity_reached' if capacity.get('marker_limit_reached')
                          else 'unknown_or_ambiguous_marker')
                omit(iid, reason, kind='marker', identity=mid)
                continue
            values = [marker.get(key) for key in ('x', 'y', 'radius_x', 'radius_y')]
            if (any(type(v) not in (int, float) or not math.isfinite(v) for v in values)
                    or not all(0 <= v <= 1000 for v in values[:2])
                    or not all(0 < v <= 1000 for v in values[2:])):
                omit(iid, 'invalid_marker_geometry', kind='marker', identity=mid)
                continue
            x, y, rx, ry = values
            # CPU locations describe point centers, using the same W-1/H-1
            # axes as fixed vertices; x/y radii are independently normalized.
            cx, cy = x/1000*(width-1), y/1000*(height-1)
            rx, ry = rx/1000*(width-1), ry/1000*(height-1)
            add(_padded_rect((cx-rx, cy-ry, cx+rx, cy+ry), source.size), iid, marker_id=mid)
        gid = issue.get('graph_id')
        if edge_ids or vertex_ids:
            if not _identifier(gid) or gid not in graph_indexes:
                omit(iid, 'unknown_ambiguous_or_unlocated_graph', graph_id=gid)
            else:
                graph = by_graph[gid]
                nodes, edges = graph_indexes[gid]
                for eid in edge_ids:
                    edge = edges.get(eid)
                    path = edge.get('path') if edge else None
                    if (not isinstance(path, list) or not 2 <= len(path) <= 128 or
                            any(_point(point) is None for point in path)):
                        omit(iid, 'unknown_ambiguous_or_invalid_edge_path', kind='edge', identity=eid, graph_id=gid)
                        continue
                    endpoints = [edge.get('from'), edge.get('to')]
                    if any(not _identifier(v) or v not in nodes or
                           vertex_points(nodes[v], graph) is None for v in endpoints):
                        omit(iid, 'edge_endpoint_not_in_fixed_inventory', kind='edge', identity=eid, graph_id=gid)
                        continue
                    related = set(endpoints)
                    proofs = ([edge['pixel_evidence']] if isinstance(edge.get('pixel_evidence'), dict) else [])
                    if isinstance(edge.get('evidence'), list):
                        proofs += edge['evidence'][:32]
                    for proof in proofs:
                        if not isinstance(proof, dict) or proof.get('source') not in (
                                'original_pixel_route', 'original_pixel_connector_boundaries'):
                            continue
                        reasons = proof.get('reasons', [])
                        if not isinstance(reasons, list):
                            continue
                        for reason in reasons[:32]:
                            prefix = 'path_crosses_mathematical_vertex:'
                            if isinstance(reason, str) and reason.startswith(prefix):
                                vid = reason[len(prefix):]
                                if vid in nodes and vertex_points(nodes[vid], graph) is not None:
                                    related.add(vid)
                    points = [(x*(width-1), y*(height-1)) for x, y in path]
                    for vid in sorted(related):
                        points.extend(vertex_points(nodes[vid], graph))
                    add(point_rect(points), iid, gid=gid, edge_ids=[eid], vertex_ids=sorted(related))
                for vid in vertex_ids:
                    points = vertex_points(nodes[vid], graph) if vid in nodes else None
                    if points is None:
                        omit(iid, 'unknown_ambiguous_or_unlocated_vertex', kind='vertex', identity=vid, graph_id=gid)
                    else:
                        add(point_rect(points), iid, gid=gid, vertex_ids=[vid])
        if (len(targets) == before and not hint_ids and not body_region_ids
                and not marker_ids and not edge_ids and not vertex_ids):
            omit(iid, 'issue_has_no_locatable_ids')

    # Collapse genuinely overlapping crops, including a vertex crop already
    # enclosed in an edge crop. Merely sharing graph endpoints is insufficient.
    regions = []
    for target in targets:
        regions.append(target)
    changed = True
    while changed:
        check()
        changed = False
        for i, left in enumerate(regions):
            for j in range(i+1, len(regions)):
                right = regions[j]
                if _intersection(left['rect'], right['rect']) >= .65*min(_area(left['rect']), _area(right['rect'])):
                    _merge_into(left, right)
                    regions.pop(j)
                    changed = True
                    break
            if changed:
                break
    merged_count = len(regions)
    if len(regions) > MAX_VIEWS:
        capacity['view_limit_reached'] = True
        for region in regions[MAX_VIEWS:]:
            for target in region['targets']:
                omit(target['issue_id'], 'view_capacity_reached',
                     kind='marker' if target['marker_id'] else 'body_region' if target['body_region_id'] else None,
                     identity=target['marker_id'] or target['body_region_id'] or target['hint_id'],
                     graph_id=target['graph_id'])
    selected = regions[:MAX_VIEWS]
    images, views = [], []
    remaining_pixels = MAX_TOTAL_PIXELS
    for index_, region in enumerate(selected):
        check()
        a, b, c, d = region['rect']
        w, h = c-a, d-b
        quota = min(MAX_VIEW_PIXELS, remaining_pixels//(len(selected)-index_))
        factor = min(MAX_SCALE, MAX_SIDE/w, MAX_SIDE/h, math.sqrt(quota/(w*h)))
        output_size = (max(1, math.floor(w*factor)), max(1, math.floor(h*factor)))
        pixels = output_size[0]*output_size[1]
        if factor < MAX_SCALE:
            capacity['resampling_size_limited'] = True
        crop = source.crop(region['rect'])
        if crop.size != output_size:
            crop = crop.resize(output_size, Image.Resampling.LANCZOS)
        images.append(crop)
        remaining_pixels -= pixels
        views.append({'crop_number': index_+1, 'coordinate_space': 'original_1000',
            'original_bbox': [round(a/width*1000, 4), round(b/height*1000, 4),
                              round(c/width*1000, 4), round(d/height*1000, 4)],
            'original_pixel_bbox': [a, b, c, d], 'pixel_bbox_convention': 'half_open',
            'original_size': [width, height], 'output_size': list(output_size),
            'scale_xy': [output_size[0]/w, output_size[1]/h],
            'hint_ids': sorted(region['hint_ids']), 'issue_ids': sorted(region['issue_ids']),
            'graph_entities': [{'graph_id': gid, 'edge_ids': sorted(value['edge_ids']),
                                'vertex_ids': sorted(value['vertex_ids'])}
                               for gid, value in sorted(region['graph_entities'].items())],
            'source_pixels_only': True})
        if body_regions is not None:
            views[-1]['body_region_ids'] = sorted(region['body_region_ids'])
        if markers is not None:
            views[-1]['marker_ids'] = sorted(region['marker_ids'])
        if body_regions is not None or markers is not None:
            mapped_targets = []
            for target in region['targets']:
                mapped = {'issue_id': target['issue_id']}
                if target['marker_id'] is not None:
                    mapped.update(entity_type='marker', marker_id=target['marker_id'])
                elif target['body_region_id'] is not None:
                    mapped.update(entity_type='body_region', body_region_id=target['body_region_id'])
                elif target['hint_id'] is not None:
                    mapped.update(entity_type='hint', hint_id=target['hint_id'])
                else:
                    mapped.update(entity_type='edge' if target['edge_ids'] else 'vertex',
                                  graph_id=target['graph_id'], edge_ids=target['edge_ids'],
                                  vertex_ids=target['vertex_ids'])
                mapped_targets.append(mapped)
            views[-1]['targets'] = mapped_targets
    diagnostics = {'version': VERSION, 'requested_issue_count': len(issues) if isinstance(issues, list) else 0,
        'resolved_target_count': len(targets), 'merged_region_count': merged_count,
        'produced_view_count': len(views), 'output_pixels': MAX_TOTAL_PIXELS-remaining_pixels,
        'capacity': capacity, 'omitted': omissions, 'omitted_count': omission_count,
        'omitted_records_truncated': omission_count > len(omissions),
        'invalid_records': {key: value for key, value in malformed.items() if value},
        'limits': {'max_views': MAX_VIEWS, 'max_view_pixels': MAX_VIEW_PIXELS,
                   'max_total_pixels': MAX_TOTAL_PIXELS, 'max_side': MAX_SIDE, 'max_scale': MAX_SCALE,
                   'max_targets': MAX_TARGETS, 'max_issues': MAX_ISSUES, 'max_graphs': MAX_GRAPHS}}
    if body_regions is not None:
        diagnostics['requested_body_region_count'] = len(body_regions) if isinstance(body_regions, list) else 0
        diagnostics['limits']['max_body_regions'] = MAX_BODY_REGIONS
    if markers is not None:
        diagnostics['requested_marker_count'] = len(markers) if isinstance(markers, list) else 0
        diagnostics['limits']['max_markers'] = MAX_MARKERS
    return images, views, diagnostics
