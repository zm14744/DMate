"""Bounded original-colour views for a final, direction-only visual reader.

The optional pair views use only unordered endpoint identities and source-bound
local routes to choose crops. No proposed direction, answer or drawn overlay is
used; the existing overview/quadrant reader remains the fallback.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import math

from PIL import Image

from dmate_tool_registry import ToolContext, ToolRegistry, ToolSpec
from image_evidence import decode_document_image


MAX_IMAGES = 5
OVERVIEW_SIDE = 1600
CROP_SIDE = 1280
MAX_UPSCALE = 6
MAX_TOTAL_PIXELS = OVERVIEW_SIDE ** 2 + 4 * CROP_SIDE ** 2
_EMPTY = {'type': 'object', 'properties': {}, 'additionalProperties': False}
_OVERVIEW = '完整原图彩色总览；后续四个重叠局部均来自此图，不是新增子图，只帮助看清箭头。'


def _encode(image):
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    raw = stream.getvalue()
    return hashlib.sha256(raw).hexdigest(), 'data:image/png;base64,' + base64.b64encode(raw).decode('ascii')


def _resize(image, side, *, enlarge):
    scale = min(MAX_UPSCALE if enlarge else 1., side / max(image.size))
    size = tuple(max(1, math.floor(value * scale)) for value in image.size)
    if size == image.size:
        return image.copy(), 'identity'
    resampling = Image.Resampling.NEAREST if scale > 1 else Image.Resampling.LANCZOS
    return image.resize(size, resampling), 'nearest' if scale > 1 else 'lanczos'


def _quadrants(size):
    width, height = size
    # Twelve percent overlap, with integer bounds in the oriented source.
    left, right = (width * 112 + 199) // 200, width * 88 // 200
    top, bottom = (height * 112 + 199) // 200, height * 88 // 200
    seen = set()
    for label, box in (('左上', (0, 0, left, top)), ('右上', (right, 0, width, top)),
                       ('左下', (0, bottom, left, height)), ('右下', (right, bottom, width, height))):
        if box not in seen:
            seen.add(box)
            yield label, box


def _metadata(source, box, output, reference, resampling):
    return {'source_box': list(box), 'source_pixel_sha256': hashlib.sha256(source.tobytes()).hexdigest(),
            'output_size': list(output.size), 'output_png_sha256': reference, 'resampling': resampling}


def _checkpoint(context):
    try:
        context.data['budget'].check()
    except Exception as exc:
        context.data['state']['control_error'] = exc
        raise
    context.check_deadline()


def _arrow_views(arguments, *, context):
    state, original = context.data['state'], context.data['original']
    refs, descriptions = [context.data['overview_ref']], [_OVERVIEW]
    metadata = [context.data['overview_metadata']]
    pixels = math.prod(metadata[0]['output_size'])
    for label, box in _quadrants(original.size):
        _checkpoint(context)
        crop = original.crop(box)
        output, resampling = _resize(crop, CROP_SIDE, enlarge=True)
        pixels += output.width * output.height
        if len(refs) >= MAX_IMAGES or pixels > MAX_TOTAL_PIXELS:
            raise ValueError('arrow_view_capacity')
        _checkpoint(context)
        reference, encoded = _encode(output)
        _checkpoint(context)
        state['images'][reference] = encoded
        refs.append(reference)
        descriptions.append(f'同一原图的{label}重叠局部，保留原始颜色；仅裁切和非生成重采样放大，不是新增子图。')
        metadata.append(_metadata(crop, box, output, reference, resampling))
    return {'image_refs': refs, 'view_descriptions': descriptions, 'view_metadata': metadata,
            'output_pixels': pixels}


def _build_registry():
    schema = {'type': 'object', 'additionalProperties': False,
        'required': ['image_refs', 'view_descriptions', 'view_metadata', 'output_pixels'],
        'properties': {
            'image_refs': {'type': 'array', 'minItems': 1, 'maxItems': MAX_IMAGES,
                           'items': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}},
            'view_descriptions': {'type': 'array', 'minItems': 1, 'maxItems': MAX_IMAGES,
                                  'items': {'type': 'string', 'maxLength': 160}},
            'view_metadata': {'type': 'array', 'minItems': 1, 'maxItems': MAX_IMAGES,
                              'items': {'type': 'object'}},
            'output_pixels': {'type': 'integer', 'minimum': 1, 'maximum': MAX_TOTAL_PIXELS}}}
    return ToolRegistry().register(ToolSpec(
        name='image.arrow_views', version='2026-10-26-arrow-views-v1',
        description='提供完整彩色原图和四个重叠放大局部，仅用于独立核对箭头方向，不生成图或答案。',
        input_schema=_EMPTY, output_schema=schema,
        allowed_roles=frozenset({'semantic_review', 'semantic_repair'}),
        source_required=True, timeout_seconds=15), _arrow_views)


def prepare_arrow_views(raw, *, budget):
    """Return <=5 images, descriptions and a small source-bound tool audit.

    Source decoding, cancellation and request deadline failures propagate. A
    local crop/encoding failure returns the full source with explicit failed
    audit and ``preprocessing_status=fallback_original`` for caller fallback.
    Pixel coordinates here describe image views; they are not graph gates.
    """
    budget.check()
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise TypeError('expected image bytes')
    raw = bytes(raw)
    source_sha256 = hashlib.sha256(raw).hexdigest()
    if getattr(budget, 'source_sha256', None) not in (None, source_sha256):
        raise ValueError('arrow_source_identity_mismatch')
    original = decode_document_image(raw)
    budget.check()
    overview, resampling = _resize(original, OVERVIEW_SIDE, enlarge=False)
    reference, encoded = _encode(overview)
    budget.check()
    metadata = _metadata(original, (0, 0, *original.size), overview, reference, resampling)
    state = {'images': {reference: encoded}, 'control_error': None}
    context = ToolContext(source_sha256=source_sha256, deadline_monotonic=budget.deadline,
        data={'original': original, 'budget': budget, 'state': state,
              'overview_ref': reference, 'overview_metadata': metadata})
    envelope = _build_registry().call('image.arrow_views', {}, role='semantic_review', context=context)
    if state['control_error'] is not None:
        raise state['control_error']
    budget.check()
    quality = {'source_sha256': source_sha256, 'original_size': list(original.size),
               'preprocessing_status': 'ok' if envelope['ok'] else 'fallback_original',
               'source_only': True, 'geometry_required': False}
    if envelope['ok']:
        result = envelope['result']
        images = [state['images'][ref] for ref in result['image_refs']]
        descriptions, metadata = result['view_descriptions'], result['view_metadata']
        quality['output_pixels'] = result['output_pixels']
    else:
        images, descriptions, metadata = [encoded], [_OVERVIEW], [metadata]
        quality.update(fallback_reason=envelope['error']['code'],
                       output_pixels=overview.width * overview.height)
    quality['view_count'] = len(images)
    return {'images': images, 'view_descriptions': descriptions, 'view_metadata': metadata,
            'image_quality': quality, 'tool_audit': list(context.audit)}


def _panel_box(graph):
    box = graph.get('bbox') if isinstance(graph, dict) else None
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in box):
        return None
    left, top, right, bottom = box
    return list(box) if 0 <= left < right <= 1000 and 0 <= top < bottom <= 1000 else None


def _panel_pixels(box, size):
    left, top, right, bottom = box
    dx, dy = (right-left) * .12, (bottom-top) * .12
    width, height = size
    return (max(0, math.floor((left-dx) * width/1000)),
            max(0, math.floor((top-dy) * height/1000)),
            min(width, math.ceil((right+dx) * width/1000)),
            min(height, math.ceil((bottom+dy) * height/1000)))


def _panel_views(arguments, *, context):
    _checkpoint(context)
    original = decode_document_image(context.data['raw'])
    _checkpoint(context)
    box = _panel_pixels(context.data['box'], original.size)
    refs, descriptions, metadata = [], [
        '完整原图彩色总览；后一张只是本次目标图的大致原图局部，不能作为新增子图或确定边的依据。',
        '同一原图中目标图的粗略范围，已扩大边距并放大；若框不准、缺点或邻图混入，仍以完整原图为准。'], []
    for source, source_box, enlarge in ((original, (0, 0, *original.size), False),
                                        (original.crop(box), box, True)):
        _checkpoint(context)
        output, resampling = _resize(source, OVERVIEW_SIDE, enlarge=enlarge)
        _checkpoint(context)
        reference, encoded = _encode(output)
        _checkpoint(context)
        context.data['state']['images'][reference] = encoded
        refs.append(reference)
        metadata.append(_metadata(source, source_box, output, reference, resampling))
    return {'image_refs': refs, 'view_descriptions': descriptions, 'view_metadata': metadata,
            'original_size': list(original.size),
            'output_pixels': sum(math.prod(row['output_size']) for row in metadata)}


def _build_panel_registry():
    schema = {'type': 'object', 'additionalProperties': False,
        'required': ['image_refs', 'view_descriptions', 'view_metadata', 'original_size', 'output_pixels'],
        'properties': {
            'image_refs': {'type': 'array', 'minItems': 2, 'maxItems': 2,
                           'items': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}},
            'view_descriptions': {'type': 'array', 'minItems': 2, 'maxItems': 2,
                                  'items': {'type': 'string', 'maxLength': 160}},
            'view_metadata': {'type': 'array', 'minItems': 2, 'maxItems': 2, 'items': {'type': 'object'}},
            'original_size': {'type': 'array', 'minItems': 2, 'maxItems': 2,
                              'items': {'type': 'integer', 'minimum': 1}},
            'output_pixels': {'type': 'integer', 'minimum': 1, 'maximum': 2 * OVERVIEW_SIDE ** 2}}}
    return ToolRegistry().register(ToolSpec(
        name='image.panel_views', version='2026-10-26-panel-views-v1',
        description='原图总览与目标图粗范围局部；框仅提示阅读范围，不确认节点、边或子图边界。',
        input_schema=_EMPTY, output_schema=schema,
        allowed_roles=frozenset({'semantic_extract', 'semantic_review', 'semantic_repair'}),
        source_required=True, timeout_seconds=15), _panel_views)


def prepare_panel_views(raw, *, graph, overview_views, budget):
    """Use a coarse original_1000 panel hint, or keep every existing view.

    Missing/invalid hints are ordinary ``no_panel_hint`` results. A valid hint
    never hides the full source; each graph is independently cropped from that
    source, with 12% padding per side. No node or edge geometry is consulted.
    """
    budget.check()
    if (not isinstance(overview_views, dict) or not isinstance(overview_views.get('images'), list)
            or not 1 <= len(overview_views['images']) <= MAX_IMAGES
            or len(overview_views.get('view_descriptions', [])) != len(overview_views['images'])):
        raise ValueError('invalid_overview_views')
    result = copy.deepcopy(overview_views)
    quality = result.setdefault('image_quality', {})
    box = _panel_box(graph)
    if box is None:
        quality.update(panel_view_status='no_panel_hint',
                       panel_hint_reason='missing_or_invalid_bbox', geometry_required=False)
        return result
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise TypeError('expected image bytes')
    raw = bytes(raw)
    source_sha256 = hashlib.sha256(raw).hexdigest()
    if getattr(budget, 'source_sha256', None) not in (None, source_sha256):
        raise ValueError('panel_source_identity_mismatch')
    state = {'images': {}, 'control_error': None}
    context = ToolContext(source_sha256=source_sha256, deadline_monotonic=budget.deadline,
        data={'raw': raw, 'box': box, 'budget': budget, 'state': state})
    envelope = _build_panel_registry().call('image.panel_views', {}, role='semantic_extract', context=context)
    if state['control_error'] is not None:
        raise state['control_error']
    budget.check()
    result['tool_audit'] = result.get('tool_audit', []) + list(context.audit)
    if not envelope['ok']:
        quality.update(panel_view_status='fallback_original', panel_hint_reason=envelope['error']['code'])
        return result
    prepared = envelope['result']
    result.update(images=[state['images'][ref] for ref in prepared['image_refs']],
                  view_descriptions=prepared['view_descriptions'], view_metadata=prepared['view_metadata'])
    quality.update(source_sha256=source_sha256, original_size=prepared['original_size'],
                   panel_view_status='cropped', panel_padding_fraction=.12, view_count=2,
                   output_pixels=prepared['output_pixels'], geometry_required=False)
    return result


MAX_PAIR_CROPS = 3
MAX_PAIR_CANDIDATES = 160
PAIR_MARGIN_FRACTION = .24
PAIR_MIN_MARGIN_PIXELS = 24


def _identifier(value):
    return isinstance(value, str) and 0 < len(value) <= 128


def _source_point(value):
    if (isinstance(value, (list, tuple)) and len(value) == 2
            and all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1000 for v in value)):
        return tuple(float(v) for v in value)
    return None


def _parallel_pairs(draft):
    """Read edge-instance endpoints only; direction/labels/weights are ignored."""
    graphs = draft.get('graphs') if isinstance(draft, dict) else None
    if not isinstance(graphs, list) or len(graphs) > 64:
        return [], 'invalid_graph_inventory'
    seen, pairs = set(), []
    for graph in graphs:
        if not isinstance(graph, dict):
            return [], 'invalid_graph_inventory'
        gid = graph.get('id')
        if not _identifier(gid) or gid in seen:
            return [], 'ambiguous_graph_identity'
        seen.add(gid)
        vertices, edges = graph.get('vertices'), graph.get('edges')
        if (not isinstance(vertices, list) or len(vertices) > 100
                or not isinstance(edges, list) or len(edges) > 300):
            return [], 'graph_inventory_capacity'
        ids = [v.get('id') if isinstance(v, dict) else None for v in vertices]
        if any(not _identifier(v) for v in ids) or len(set(ids)) != len(ids):
            return [], 'ambiguous_vertex_identity'
        groups = {}
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            left, right = edge.get('from'), edge.get('to')
            if not _identifier(left) or not _identifier(right) or left not in ids or right not in ids:
                continue
            key = tuple(sorted((left, right)))
            groups.setdefault(key, []).append(edge.get('id'))
        for pair, edge_ids in groups.items():
            if len(edge_ids) >= 2:
                pairs.append({'graph_id': gid, 'vertex_ids': list(pair),
                              'edge_ids': [eid for eid in edge_ids if _identifier(eid)],
                              'semantic_edge_instances': len(edge_ids)})
    return pairs, None if pairs else 'no_parallel_endpoint_pairs'


def _pair_source_box(pair, candidates, size):
    """Union every associated local route; never choose an arrow orientation."""
    wanted = tuple(pair['vertex_ids'])
    selected = [row for row in candidates if isinstance(row, dict)
                and _identifier(row.get('from')) and _identifier(row.get('to'))
                and tuple(sorted((row['from'], row['to']))) == wanted]
    if not selected:
        return None, 'no_associated_routes'
    positions, marker_ids, marker_owners, points, instances = {}, {}, {}, [], []
    width, height = size
    def distance(a, b):
        return math.hypot((a[0]-b[0])*(width-1)/1000, (a[1]-b[1])*(height-1)/1000)
    for row in selected:
        if (row.get('coordinate_space') != 'original_1000' or row.get('unmapped') is not False
                or not _identifier(row.get('instance_id'))):
            return None, 'ambiguous_route_identity'
        endpoints = row.get('endpoints')
        if not isinstance(endpoints, list) or len(endpoints) != 2:
            return None, 'missing_unique_endpoint_positions'
        local = {}
        for endpoint in endpoints:
            if not isinstance(endpoint, dict):
                return None, 'missing_unique_endpoint_positions'
            vid, point, mid = endpoint.get('vertex_id'), _source_point(endpoint.get('position')), endpoint.get('marker_id')
            if (vid not in wanted or point is None or endpoint.get('association') != 'unique_close_marker'
                    or not _identifier(mid)):
                return None, 'missing_unique_endpoint_positions'
            if vid in positions and (marker_ids[vid] != mid or distance(positions[vid], point) > 1):
                return None, 'ambiguous_endpoint_positions'
            if mid in marker_owners and marker_owners[mid] != vid:
                return None, 'ambiguous_endpoint_positions'
            positions[vid], marker_ids[vid], local[vid] = point, mid, point
            marker_owners[mid] = vid
            points.append(point)
        if set(local) != set(wanted):
            return None, 'ambiguous_route_endpoints'
        path = row.get('path_hint')
        if not isinstance(path, list) or not 2 <= len(path) <= 128:
            return None, 'invalid_route_geometry'
        route = [_source_point(p) for p in path]
        if any(p is None for p in route):
            return None, 'invalid_route_geometry'
        a, b = (local[v] for v in wanted)
        if wanted[0] != wanted[1] and distance(a, b) <= 1:
            return None, 'ambiguous_endpoint_positions'
        if not (max(distance(route[0], a), distance(route[-1], b)) <= 2
                or max(distance(route[0], b), distance(route[-1], a)) <= 2):
            return None, 'route_endpoint_position_mismatch'
        if row['instance_id'] in instances:
            return None, 'ambiguous_route_identity'
        instances.append(row['instance_id'])
        points.extend(route)
    xs, ys = [p[0]*(width-1)/1000 for p in points], [p[1]*(height-1)/1000 for p in points]
    span = max(max(xs)-min(xs), max(ys)-min(ys))
    margin = max(PAIR_MIN_MARGIN_PIXELS, span*PAIR_MARGIN_FRACTION)
    box = (max(0, math.floor(min(xs)-margin)), max(0, math.floor(min(ys)-margin)),
           min(width, math.ceil(max(xs)+margin)+1), min(height, math.ceil(max(ys)+margin)+1))
    return {**pair, 'source_box': list(box), 'candidate_ids': sorted(instances),
            'candidate_count': len(selected), 'margin_pixels': round(margin, 4)}, None


def _direction_pair_views(arguments, *, context):
    _checkpoint(context)
    geometry = context.data['geometry']
    empty = {'image_refs': [], 'view_descriptions': [], 'view_metadata': [],
             'pair_groups': 0, 'omitted': [], 'omitted_count': 0, 'output_pixels': 0}
    if not isinstance(geometry, dict) or geometry.get('source_sha256') != context.source_sha256:
        return {**empty, 'reason': 'geometry_source_unverified'}
    pairs, reason = _parallel_pairs(context.data['draft'])
    if not pairs:
        return {**empty, 'reason': reason}
    geometry_graphs = geometry.get('graphs')
    if not isinstance(geometry_graphs, list) or len(geometry_graphs) > 64:
        return {**empty, 'reason': 'invalid_geometry_inventory'}
    index, total = {}, 0
    for graph in geometry_graphs:
        _checkpoint(context)
        if not isinstance(graph, dict) or not _identifier(graph.get('graph_id')):
            return {**empty, 'reason': 'ambiguous_geometry_graph'}
        gid, rows = graph['graph_id'], graph.get('candidates')
        if gid in index or not isinstance(rows, list):
            return {**empty, 'reason': 'ambiguous_geometry_graph'}
        total += len(rows)
        if total > MAX_PAIR_CANDIDATES:
            return {**empty, 'reason': 'geometry_candidate_capacity'}
        index[gid] = rows
    _checkpoint(context)
    original = decode_document_image(context.data['raw'])
    _checkpoint(context)
    result = {**empty, 'pair_groups': len(pairs), 'reason': 'no_unambiguous_pair_routes'}
    for pair in pairs:
        _checkpoint(context)
        location, omitted = _pair_source_box(pair, index.get(pair['graph_id'], []), original.size)
        if location is not None and len(result['image_refs']) >= MAX_PAIR_CROPS:
            omitted = 'pair_crop_capacity'
        if omitted:
            result['omitted_count'] += 1
            if len(result['omitted']) < 64:
                result['omitted'].append({'graph_id': pair['graph_id'], 'vertex_ids': pair['vertex_ids'],
                                          'reason': omitted})
            continue
        crop = original.crop(location['source_box'])
        output, resampling = _resize(crop, CROP_SIDE, enlarge=True)
        _checkpoint(context)
        reference, encoded = _encode(output)
        _checkpoint(context)
        context.data['state']['images'][reference] = encoded
        result['image_refs'].append(reference)
        result['view_descriptions'].append(
            '同一原图中一对端点及其多条路线的联合局部，含两端与周边印刷文字；'
            '仅裁切放大，不是新增子图，候选路线顺序不表示箭头方向。')
        result['view_metadata'].append({**_metadata(crop, location['source_box'], output, reference, resampling),
            **location, 'view_kind': 'endpoint_pair', 'coordinate_space': 'original_pixels',
            'original_bbox': [round(location['source_box'][i]*1000/original.size[i % 2], 6)
                              for i in range(4)],
            'original_bbox_space': 'original_1000', 'directions_used': False,
            'route_coverage_certified': False})
        result['output_pixels'] += output.width*output.height
    if result['image_refs']:
        result['reason'] = 'cropped'
    return result


def _build_direction_registry():
    schema = {'type': 'object', 'additionalProperties': False,
        'required': ['image_refs', 'view_descriptions', 'view_metadata', 'pair_groups',
                     'omitted', 'omitted_count', 'output_pixels', 'reason'],
        'properties': {
            'image_refs': {'type': 'array', 'maxItems': MAX_PAIR_CROPS,
                           'items': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}},
            'view_descriptions': {'type': 'array', 'maxItems': MAX_PAIR_CROPS,
                                  'items': {'type': 'string', 'maxLength': 160}},
            'view_metadata': {'type': 'array', 'maxItems': MAX_PAIR_CROPS, 'items': {'type': 'object'}},
            'pair_groups': {'type': 'integer', 'minimum': 0, 'maximum': 9600},
            'omitted': {'type': 'array', 'maxItems': 64, 'items': {'type': 'object'}},
            'omitted_count': {'type': 'integer', 'minimum': 0, 'maximum': 9600},
            'output_pixels': {'type': 'integer', 'minimum': 0, 'maximum': MAX_PAIR_CROPS*CROP_SIDE**2},
            'reason': {'type': 'string', 'maxLength': 80}}}
    return ToolRegistry().register(ToolSpec(
        name='image.direction_pair_views', version='2026-10-27-direction-pair-views-v1',
        description='以同源局部路线联合裁出同端点多边，仅提供原像素，不采用或绘制预测方向。',
        input_schema=_EMPTY, output_schema=schema,
        allowed_roles=frozenset({'semantic_review', 'semantic_repair'}),
        source_required=True, timeout_seconds=15), _direction_pair_views)


def prepare_direction_views(raw, *, draft, geometry, overview_views, budget):
    """Replace <=3 quadrants with source-only, unordered endpoint-pair crops.

    The full source is always first. Unknown/ambiguous local associations leave
    the existing overview/quadrants intact; they never reject graph content.
    The caller must invalidate geometry when the graph inventory changes.
    """
    budget.check()
    if (not isinstance(overview_views, dict) or not isinstance(overview_views.get('images'), list)
            or not 1 <= len(overview_views['images']) <= MAX_IMAGES
            or len(overview_views.get('view_descriptions', [])) != len(overview_views['images'])
            or len(overview_views.get('view_metadata', [])) != len(overview_views['images'])):
        raise ValueError('invalid_overview_views')
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise TypeError('expected image bytes')
    raw = bytes(raw)
    source_sha256 = hashlib.sha256(raw).hexdigest()
    if getattr(budget, 'source_sha256', None) not in (None, source_sha256):
        raise ValueError('arrow_source_identity_mismatch')
    if overview_views.get('image_quality', {}).get('source_sha256') != source_sha256:
        # Do not return a different image merely because its geometry cannot
        # be used. Rebuild the standard source-only fallback from these bytes.
        result = prepare_arrow_views(raw, budget=budget)
        result['image_quality'].update(direction_pair_status='fallback_overviews',
                                       direction_pair_reason='overview_source_mismatch')
        return result
    result = copy.deepcopy(overview_views)
    state = {'images': {}, 'control_error': None}
    context = ToolContext(source_sha256=source_sha256, deadline_monotonic=budget.deadline,
        data={'raw': raw, 'draft': draft, 'geometry': geometry, 'budget': budget, 'state': state})
    envelope = _build_direction_registry().call('image.direction_pair_views', {},
                                                role='semantic_review', context=context)
    if state['control_error'] is not None:
        raise state['control_error']
    budget.check()
    result['tool_audit'] = result.get('tool_audit', []) + list(context.audit)
    quality = result.setdefault('image_quality', {})
    quality.update(direction_pair_status='fallback_overviews', geometry_required=False)
    if not envelope['ok']:
        quality['direction_pair_reason'] = envelope['error']['code']
        return result
    prepared = envelope['result']
    quality.update(direction_pair_reason=prepared['reason'], direction_pair_groups=prepared['pair_groups'],
                   direction_pair_crops=len(prepared['image_refs']),
                   direction_pair_omissions=prepared['omitted'],
                   direction_pair_omitted_count=prepared['omitted_count'])
    if not prepared['image_refs']:
        return result
    keep = max(0, MAX_IMAGES-1-len(prepared['image_refs']))
    images = [overview_views['images'][0]] + [state['images'][ref] for ref in prepared['image_refs']]
    descriptions = ['完整彩色原图；后续局部均来自此图，不是新增子图，箭头方向必须从原像素读取。']
    descriptions += prepared['view_descriptions']
    metadata = [copy.deepcopy(overview_views['view_metadata'][0])] + prepared['view_metadata']
    images += overview_views['images'][1:1+keep]
    descriptions += overview_views['view_descriptions'][1:1+keep]
    metadata += copy.deepcopy(overview_views['view_metadata'][1:1+keep])
    pixels = sum(math.prod(row['output_size']) for row in metadata)
    if pixels > MAX_TOTAL_PIXELS:
        quality.update(direction_pair_reason='direction_view_pixel_capacity', direction_pair_crops=0)
        return result
    for number, row in enumerate(metadata, 1):
        row['image_number'] = number
    result.update(images=images, view_descriptions=descriptions, view_metadata=metadata)
    quality.update(direction_pair_status='cropped', output_pixels=pixels, view_count=len(images))
    return result


__all__ = ['prepare_arrow_views', 'prepare_panel_views', 'prepare_direction_views']
