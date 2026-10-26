"""Small, source-only image views for semantic extraction and visual review.

The first view always shows the complete, correctly oriented RGB source. The
source bytes remain untouched; only bounded sending copies are resized. Local
preprocessing and OCR hints are assistance, never graph or acceptance gates.
"""
from __future__ import annotations

import base64
import hashlib
import io
import math

from PIL import Image

from dmate_tool_registry import ToolContext, ToolRegistry, ToolSpec
from image_evidence import analyze_document, decode_document_image


MAX_VIEW_SIDE = 1600
MAX_VIEW_PIXELS = 2_600_000
MAX_IMAGES = 5
MAX_HINT_CHARACTERS = 3000
LARGE_IMAGE_SIDE = 1800
_OVERLAP_PERCENT = 12
_SEMANTIC_ROLES = frozenset({'semantic_extract', 'semantic_review', 'semantic_repair'})
_OVERVIEW_DESCRIPTION = '完整原图总览；所有局部图均来自此图，颜色和分图数量以此图为准。'
_HINT_PREFIX = '以下本地 OCR 可能漏字或错字，仅供对照原图，不是已确认正文：\n'
_EMPTY = {'type': 'object', 'properties': {}, 'additionalProperties': False}


def _bounded_view(image):
    width, height = image.size
    scale = min(1., MAX_VIEW_SIDE / max(width, height),
                math.sqrt(MAX_VIEW_PIXELS / (width * height)))
    size = (max(1, math.floor(width * scale)), max(1, math.floor(height * scale)))
    if size != image.size:
        return image.resize(size, Image.Resampling.LANCZOS)
    return image.copy()


def _encode_view(image):
    # Lossless PNG keeps small lettering and colour differences. Large base64
    # strings stay outside the registry's bounded JSON metadata envelope.
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    encoded = stream.getvalue()
    return hashlib.sha256(encoded).hexdigest(), (
        'data:image/png;base64,' + base64.b64encode(encoded).decode('ascii'))


def _quadrants(size):
    width, height = size
    upper, lower = 100 + _OVERLAP_PERCENT, 100 - _OVERLAP_PERCENT
    # Integer arithmetic avoids a floating-point ceil adding a spurious row.
    left_end, right_start = (width * upper + 199) // 200, width * lower // 200
    top_end, bottom_start = (height * upper + 199) // 200, height * lower // 200
    rows = [('左上', (0, 0, left_end, top_end)),
            ('右上', (right_start, 0, width, top_end)),
            ('左下', (0, bottom_start, left_end, height)),
            ('右下', (right_start, bottom_start, width, height))]
    seen = set()
    for label, box in rows:
        # One-pixel-wide/tall images need no repeated identical half-page crop.
        if box not in seen:
            seen.add(box)
            yield label, box


def _checkpoint(context):
    budget = context.data['budget']
    try:
        budget.check()
    except Exception as exc:
        # ToolRegistry intentionally converts handler failures to safe codes.
        # Preserve task cancellation/deadline exceptions privately so the
        # wrapper never turns them into an apparently usable fallback result.
        context.data['state']['control_error'] = exc
        raise
    context.check_deadline()


def _semantic_views(arguments, *, context):
    _checkpoint(context)
    document = analyze_document(context.data['raw'], max_work_side=MAX_VIEW_SIDE)
    _checkpoint(context)
    original = context.data['original']
    refs = [context.data['overview_ref']]
    descriptions = [_OVERVIEW_DESCRIPTION]
    cache = context.data['state']['images']
    large = max(original.size) > LARGE_IMAGE_SIDE or original.width * original.height > MAX_VIEW_PIXELS

    def append(image, description):
        _checkpoint(context)
        reference, data_url = _encode_view(_bounded_view(image))
        _checkpoint(context)
        cache[reference] = data_url
        refs.append(reference)
        descriptions.append(description)

    if large:
        for label, box in _quadrants(original.size):
            append(original.crop(box), f'同一原图的{label}重叠局部，保留原始颜色；仅帮助看清，不能作为新增子图。')
    elif document.quality.get('background_normalized'):
        append(document.normalized, '同一原图的光照归一化辅助；不新增子图，颜色和实际笔画仍以第一张原图为准。')

    quality = {
        **context.data['base_quality'],
        'preprocessing_status': 'ok',
        'large_image': large,
        'view_count': len(refs),
        'possible_blur': bool(document.quality.get('possible_blur')),
        'low_contrast_only': bool(document.quality.get('low_contrast_only')),
        'background_normalized': bool(document.quality.get('background_normalized')),
        'normalization_view_included': not large and len(refs) > 1,
        'exif_transposed': bool(document.quality.get('exif_transposed')),
        'transparency_present': bool(document.quality.get('transparency_present')),
    }
    return {'image_refs': refs, 'view_descriptions': descriptions, 'image_quality': quality}


def _build_registry():
    schema = {
        'type': 'object', 'additionalProperties': False,
        'required': ['image_refs', 'view_descriptions', 'image_quality'],
        'properties': {
            'image_refs': {'type': 'array', 'minItems': 1, 'maxItems': MAX_IMAGES,
                           'items': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}},
            'view_descriptions': {'type': 'array', 'minItems': 1, 'maxItems': MAX_IMAGES,
                                  'items': {'type': 'string', 'maxLength': 160}},
            'image_quality': {'type': 'object'},
        },
    }
    return ToolRegistry().register(ToolSpec(
        name='image.semantic_views', version='2026-10-26-semantic-v1',
        description='提供同一原图的彩色总览及有界原像素局部，必要时提供光照归一化辅助。',
        input_schema=_EMPTY, output_schema=schema, allowed_roles=_SEMANTIC_ROLES,
        source_required=True, timeout_seconds=15,
    ), _semantic_views)


def _local_text_hint(text_result):
    """A bounded, untrusted text suggestion with no IDs or coverage contract."""
    result = text_result if isinstance(text_result, dict) else {}
    evidence = result.get('text_evidence')
    evidence = evidence if isinstance(evidence, dict) else {}
    parts, seen = [], set()
    remaining = MAX_HINT_CHARACTERS - len(_HINT_PREFIX)

    def add(value):
        nonlocal remaining
        if not isinstance(value, str) or remaining <= 0:
            return
        value = value[:MAX_HINT_CHARACTERS].strip()
        if not value or value in seen:
            return
        seen.add(value)
        separator = 1 if parts else 0
        if remaining <= separator:
            return
        part = value[:remaining-separator]
        parts.append(part)
        remaining -= len(part) + separator

    add(text_result if isinstance(text_result, str) else result.get('text'))
    for role in ('body', 'graph_labels', 'uncertain', 'noise'):
        rows = evidence.get(role)
        if isinstance(rows, list):
            for row in rows[:128]:
                if isinstance(row, dict):
                    add(row.get('content'))
                if remaining <= 0:
                    break
    return _HINT_PREFIX + '\n'.join(parts) if parts else ''


def prepare_semantic_images(raw, *, budget, text_result=None, layout=None):
    """Prepare at most five images without graph geometry or remote inference.

    ``budget`` provides ``check()`` and the shared monotonic ``deadline``. Source
    decoding and task cancellation/deadline failures propagate. A failed local
    tool returns only the already prepared full-source view, with a safe audit.
    ``layout`` is accepted for callers reusing local OCR; it does not determine
    graph counts, crop identities, or any acceptance requirement.
    """
    budget.check()
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise TypeError('expected image bytes')
    raw = bytes(raw)
    source_sha256 = hashlib.sha256(raw).hexdigest()
    original = decode_document_image(raw)
    budget.check()
    overview = _bounded_view(original)
    overview_ref, overview_url = _encode_view(overview)
    budget.check()
    base_quality = {'source_sha256': source_sha256, 'original_size': list(original.size),
                    'overview_size': list(overview.size)}
    state = {'images': {overview_ref: overview_url}, 'control_error': None}
    context = ToolContext(source_sha256=source_sha256, deadline_monotonic=budget.deadline,
                          data={'raw': raw, 'original': original, 'budget': budget,
                                'overview_ref': overview_ref, 'base_quality': base_quality,
                                'state': state})
    envelope = _build_registry().call('image.semantic_views', {}, role='semantic_extract', context=context)
    if state['control_error'] is not None:
        raise state['control_error']
    budget.check()
    if envelope['ok']:
        prepared = envelope['result']
        images = [state['images'][reference] for reference in prepared['image_refs']]
        descriptions, quality = prepared['view_descriptions'], prepared['image_quality']
    else:
        images, descriptions = [overview_url], [_OVERVIEW_DESCRIPTION]
        quality = {**base_quality, 'preprocessing_status': 'fallback_original', 'view_count': 1,
                   'fallback_reason': envelope['error']['code']}
    return {'images': images, 'view_descriptions': descriptions, 'image_quality': quality,
            'tool_audit': list(context.audit), 'local_text_hint': _local_text_hint(text_result)}


__all__ = ['prepare_semantic_images']
