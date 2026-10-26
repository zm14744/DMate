"""Bounded original-colour views for a final, direction-only visual reader.

No graph, label, answer or proposed direction is accepted by this module. The
overview and overlapping quadrants all come from the same decoded source.
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


__all__ = ['prepare_arrow_views', 'prepare_panel_views']
