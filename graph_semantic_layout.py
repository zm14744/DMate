"""Bounded local layout assistance, never a graph inventory or answer.

OpenCV always runs. PP-DocLayoutV3 may run in the existing isolated layout
worker; its execution is reported separately from CV and reused predictions.
Every displayed crop comes from the original oriented, white-composited RGB.
Disconnected ink components and layout boxes are proposals, not new graphs.
"""
from __future__ import annotations

import base64
import copy
import fcntl
import hashlib
import io
import math
import os
from pathlib import Path
import tempfile
import time

import cv2
import numpy as np
from PIL import Image

from dmate_tool_registry import ToolContext, ToolRegistry, ToolSpec
from image_evidence import DocumentEvidence, analyze_document, decode_document_image


VERSION = '2026-10-26-semantic-layout-v1'
MAX_WORK_SIDE = 1400
MAX_COMPONENT_PROPOSALS = 128
MAX_PANELS = 24
MAX_BODY_REGIONS = 16
MAX_LAYOUT_REGIONS = 128
MAX_IMAGES = 5
MAX_CROP_PIXELS = 900_000
MAX_OVERVIEW_PIXELS = 1_800_000
MAX_OUTPUT_PIXELS = MAX_OVERVIEW_PIXELS + 4 * MAX_CROP_PIXELS
MODEL_NAME = 'PP-DocLayoutV3'
DEFAULT_LAYOUT_SECONDS = 30.
MAX_LAYOUT_SECONDS = 35.


def configured_layout_timeout():
    """Bound cold model startup and inference within the upload's deadline."""
    try:
        seconds = float(os.environ.get('DMATE_LAYOUT_SECONDS', DEFAULT_LAYOUT_SECONDS))
    except (TypeError, ValueError):
        seconds = DEFAULT_LAYOUT_SECONDS
    if not math.isfinite(seconds):
        seconds = DEFAULT_LAYOUT_SECONDS
    return min(MAX_LAYOUT_SECONDS, max(1., seconds))


def _check(context):
    try:
        context.data['budget'].check()
    except Exception as exc:
        context.data['state']['control_error'] = exc
        raise
    context.check_deadline()


def _box(value, limit=1000.):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in value):
        return None
    a, b, c, d = value
    return list(map(float, value)) if 0 <= a < c <= limit and 0 <= b < d <= limit else None


def _union(a, b):
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _intersection_fraction(a, b):
    area = max(0., min(a[2], b[2])-max(a[0], b[0])) * max(0., min(a[3], b[3])-max(a[1], b[1]))
    return area / max(1., min((a[2]-a[0])*(a[3]-a[1]), (b[2]-b[0])*(b[3]-b[1])))


def _pad(box, width, height, fraction=.08):
    x = max(6., (box[2]-box[0])*fraction)
    y = max(6., (box[3]-box[1])*fraction)
    return [max(0., box[0]-x), max(0., box[1]-y), min(float(width), box[2]+x), min(float(height), box[3]+y)]


def _normalized(box, size):
    return [round(float(v)*1000/size[i % 2], 4) for i, v in enumerate(box)]


def _merge_components(boxes, width, height):
    """Group nearby/overlapping geometry; never equate components with graphs."""
    groups = []
    for box in boxes:
        again = True
        while again:
            again = False
            for i, other in enumerate(groups):
                gap_x = max(0., box[0]-other[2], other[0]-box[2])
                gap_y = max(0., box[1]-other[3], other[1]-box[3])
                overlap_x = min(box[2], other[2])-max(box[0], other[0])
                overlap_y = min(box[3], other[3])-max(box[1], other[1])
                near = (gap_x < width*.025 and overlap_y > min(box[3]-box[1], other[3]-other[1])*.25
                        or gap_y < height*.025 and overlap_x > min(box[2]-box[0], other[2]-other[0])*.25)
                if _intersection_fraction(box, other) > .08 or near:
                    box = _union(box, groups.pop(i)); again = True; break
        groups.append(box)
    return groups


def _whitespace_split(mask, box, depth=0):
    """Large projection gutters suggest local reading windows, not graph IDs."""
    if depth >= 3:
        return [box]
    a, b, c, d = map(int, box)
    crop = mask[b:d, a:c]
    if crop.size == 0:
        return []
    choices = []
    for axis, length, global_size in ((0, c-a, mask.shape[1]), (1, d-b, mask.shape[0])):
        counts = np.count_nonzero(crop, axis=axis)
        blank = counts <= max(1, (crop.shape[0] if axis == 0 else crop.shape[1])*.002)
        padded = np.pad(blank.astype(np.int8), (1, 1))
        starts = np.flatnonzero(np.diff(padded) == 1)
        ends = np.flatnonzero(np.diff(padded) == -1)
        for start, end in zip(starts, ends):
            if (end-start >= max(16, global_size*.035)
                    and start >= max(24, global_size*.10)
                    and length-end >= max(24, global_size*.10)):
                choices.append((float(end-start)/global_size, axis, int((start+end)//2)))
    if not choices:
        return [box]
    _, axis, split = max(choices)
    children = ([a, b, a+split, d], [a+split, b, c, d]) if axis == 0 else (
        [a, b, c, b+split], [a, b+split, c, d])
    return [part for child in children for part in _whitespace_split(mask, child, depth+1)]


def _cv_regions(document, context):
    started = time.monotonic()
    _check(context)
    mask = document.ink_mask
    if max(mask.shape) > MAX_WORK_SIDE:
        scale = MAX_WORK_SIDE/max(mask.shape)
        mask = cv2.resize(mask, (max(1, round(mask.shape[1]*scale)), max(1, round(mask.shape[0]*scale))),
                          interpolation=cv2.INTER_NEAREST)
    height, width = mask.shape
    # A small close bridges rasterization gaps only. Text/line distinction is
    # intentionally coarse; no thin stroke is erased from the source image.
    joined = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)
    _check(context)
    measured = stats[1:]
    keep = ((measured[:, 2] >= max(24, width*.07)) & (measured[:, 3] >= max(24, height*.07))
            & (np.maximum(measured[:, 2]/width, measured[:, 3]/height) >= .17) & (measured[:, 4] >= 40))
    # A wide, shallow header/banner is an ambiguous text band, not a good
    # default figure zoom. Keep its pixels for text proposals and overview.
    wide_bands = keep & (measured[:, 2] > measured[:, 3]*6) & (measured[:, 3] < height*.18)
    keep &= ~wide_bands
    candidates = [[int(x), int(y), int(x+w), int(y+h)] for x, y, w, h, _ in measured[keep]]
    candidates.sort(key=lambda box: -(box[2]-box[0])*(box[3]-box[1]))
    component_omitted = max(0, len(candidates)-MAX_COMPONENT_PROPOSALS)
    candidates = candidates[:MAX_COMPONENT_PROPOSALS]
    grouped = _merge_components(candidates, width, height)
    boxes = [part for box in grouped for part in _whitespace_split(joined, box)]
    if len(boxes) == 1:
        # An isolated marked vertex may be disconnected from the main graph.
        # Keep its entire horizontal context, rather than treating it as a new
        # graph or silently excluding it from the single figure view.
        boxes[0][0], boxes[0][2] = 0, width
    boxes = sorted(boxes, key=lambda q: (q[1], q[0]))
    panels = [{'bbox': _normalized(_pad(box, width, height), (width, height)),
               'source': 'opencv_projection_components', 'status': 'candidate',
               'segmentation_is_not_graph_inventory': True} for box in boxes[:MAX_PANELS]]

    # Text-like rows are merely potential reading regions. PP-DocLayout's
    # text/caption predictions, when available, are recorded separately.
    text_mask = mask.copy()
    for box in boxes:
        a, b, c, d = map(int, box)
        text_mask[max(0, b):min(height, d), max(0, a):min(width, c)] = 0
    rows = cv2.dilate(text_mask, np.ones((3, max(5, int(width*.014))), np.uint8))
    _, _, text_stats, _ = cv2.connectedComponentsWithStats(rows, connectivity=8)
    measured = text_stats[1:]
    keep = ((measured[:, 2] >= max(24, width*.05)) & (measured[:, 3] >= 3)
            & (measured[:, 3] <= height*.14) & (measured[:, 2] >= measured[:, 3]*1.8)
            & (measured[:, 4] >= 20))
    text_boxes = [[int(x), int(y), int(x+w), int(y+h)] for x, y, w, h, _ in measured[keep]]
    text_boxes.sort(key=lambda box: (box[1], box[0]))
    body = [{'bbox': _normalized(_pad(box, width, height, .04), (width, height)),
             'source': 'opencv_text_projection', 'status': 'text_or_caption_candidate'}
            for box in text_boxes[:MAX_BODY_REGIONS]]
    _check(context)
    return panels, body, {'stage': 'semantic_layout_cv', 'status': 'ok', 'worker_started': False,
        'executed': True, 'algorithm': 'local_contrast_mask_components_whitespace_projection',
        'seconds': round(time.monotonic()-started, 6), 'work_size': [width, height],
        'components_observed': int(count-1), 'component_proposals_omitted': component_omitted,
        'wide_bands_deferred_to_text_candidates': int(np.count_nonzero(wide_bands)),
        'panels_omitted': max(0, len(boxes)-MAX_PANELS),
        'body_regions_omitted': max(0, len(text_boxes)-MAX_BODY_REGIONS),
        'model_executed': False}


def _valid_regions(layout):
    if not isinstance(layout, dict) or layout.get('status') != 'ok' or layout.get('model') != MODEL_NAME:
        return None
    if not isinstance(layout.get('regions'), list):
        return None
    regions = []
    for row in layout['regions'][:MAX_LAYOUT_REGIONS]:
        if not isinstance(row, dict) or _box(row.get('bbox'), 1.) is None:
            continue
        role = row.get('role')
        if role not in ('figure', 'formula', 'text', 'caption', 'noise'):
            continue
        regions.append({'id': str(row.get('id') or f'r{len(regions)+1}')[:64],
                        'bbox': _box(row['bbox'], 1.), 'role': role,
                        'label': str(row.get('label', 'unknown'))[:64],
                        'score': float(row.get('score', 0.)) if type(row.get('score')) in (int, float)
                                 and math.isfinite(row['score']) else 0.})
    return regions


def _run_layout(original, context, timeout):
    from ocr_runtime import run_worker
    started = time.monotonic()
    deadline = min(started+timeout, context.deadline_monotonic-2.)
    metric = {'stage': 'layout', 'status': 'not_run', 'worker_started': False,
              'model': MODEL_NAME, 'timeout_seconds': timeout, 'model_inference_completed': False}
    _check(context)
    from graph_local_scheduler import local_model_lock
    with local_model_lock() as acquired:
        if not acquired:
            return {'status': 'busy', 'regions': [], 'model': MODEL_NAME}, {**metric, 'status': 'busy', 'seconds': 0.}
        if deadline-time.monotonic() < 1.:
            return {'status': 'not_run', 'regions': [], 'model': MODEL_NAME}, {**metric, 'status': 'deadline_reserved'}
        with tempfile.TemporaryDirectory(prefix='dmate-semantic-layout-') as folder:
            path = Path(folder)
            view = original.copy()
            view.thumbnail((MAX_WORK_SIDE, MAX_WORK_SIDE))
            view.save(path/'layout.png', compress_level=2)
            _check(context)
            remaining = deadline-time.monotonic()
            if remaining < 1.:
                return {'status': 'not_run', 'regions': [], 'model': MODEL_NAME}, {**metric, 'status': 'deadline_reserved'}
            result, measured = run_worker('layout', path/'layout.png', path/'layout.json', timeout=remaining)
            metric.update(measured)
            metric['worker_started'] = bool(measured.get('phase_peaks') or measured.get('audit')
                                            or measured.get('rss_observed') or measured.get('status') == 'ok')
            regions = _valid_regions(result)
            completed = regions is not None and measured.get('status') == 'ok'
            metric['model_inference_completed'] = completed
            metric['seconds_including_preparation'] = round(time.monotonic()-started, 6)
            if completed:
                return {'status': 'ok', 'model': MODEL_NAME, 'regions': regions,
                        'coordinate_space': 'original_normalized_0_1', 'source': 'executed_layout_worker'}, metric
            return {'status': 'unavailable', 'model': MODEL_NAME, 'regions': [],
                    'reason': str(metric.get('status', 'worker_failed'))}, metric


def _fuse(panels, body, layout):
    panels, body = copy.deepcopy(panels), copy.deepcopy(body)
    broad_layout_regions, broad_cv_regions = [], []
    figures = [[x*1000 for x in row['bbox']] for row in layout.get('regions', []) if row['role'] == 'figure']
    retained = []
    for panel in panels:
        a = panel['bbox']
        covered = [b for b in figures if a[0] <= b[0]+10 and a[1] <= b[1]+10
                   and a[2] >= b[2]-10 and a[3] >= b[3]-10]
        if any(_intersection_fraction(x, y) < .2 for i, x in enumerate(covered) for y in covered[i+1:]):
            # A coarse CV envelope must not swallow two separate model
            # reading windows. The full source remains visible either way.
            broad_cv_regions.append(panel['bbox'])
        else:
            retained.append(panel)
    panels = retained
    for region in layout.get('regions', []):
        box = [x*1000 for x in region['bbox']]
        if region['role'] == 'figure':
            matches = [p for p in panels if _intersection_fraction(p['bbox'], box) >= .55]
            if len(matches) > 1:
                broad_layout_regions.append(region['id'])
                for panel in matches:
                    panel.setdefault('layout_region_ids', []).append(region['id'])
                continue
            if matches:
                matches[0]['bbox'] = _union(matches[0]['bbox'], box)
                matches[0]['source'] = 'opencv_and_layout_prediction'
                matches[0]['layout_region_ids'] = [region['id']]
            else:
                panels.append({'bbox': box, 'source': 'pp_doclayout_v3_prediction', 'status': 'candidate',
                               'layout_region_ids': [region['id']], 'segmentation_is_not_graph_inventory': True})
        elif region['role'] in ('text', 'formula'):
            if not any(_intersection_fraction(row['bbox'], box) >= .75 for row in body):
                body.append({'bbox': box, 'source': 'pp_doclayout_v3_prediction',
                             'status': 'body_or_formula_candidate', 'layout_region_ids': [region['id']]})
    rows = []
    for panel in sorted(panels, key=lambda row: (row['bbox'][1], row['bbox'][0])):
        box = panel['bbox']
        row = next((r for r in rows if min(r[0]['bbox'][3], box[3])-max(r[0]['bbox'][1], box[1])
                    > min(r[0]['bbox'][3]-r[0]['bbox'][1], box[3]-box[1])*.5), None)
        if row is None:
            rows.append([panel])
        else:
            row.append(panel)
    panels = [panel for row in rows for panel in sorted(row, key=lambda item: item['bbox'][0])]
    body.sort(key=lambda row: (row['bbox'][1], row['bbox'][0]))
    omitted = {'panels': max(0, len(panels)-MAX_PANELS), 'body_regions': max(0, len(body)-MAX_BODY_REGIONS),
               'layout_container_regions': broad_layout_regions, 'cv_container_boxes': broad_cv_regions}
    panels, body = panels[:MAX_PANELS], body[:MAX_BODY_REGIONS]
    for i, panel in enumerate(panels, 1):
        panel.update(id=f'panel_{i}', coordinate_space='original_1000')
    for i, row in enumerate(body, 1):
        row.update(id=f'body_region_{i}', coordinate_space='original_1000')
    return panels, body, omitted


def _pixels(box, size):
    width, height = size
    a, b, c, d = box
    dx, dy = (c-a)*.08, (d-b)*.08
    return (max(0, math.floor((a-dx)*width/1000)), max(0, math.floor((b-dy)*height/1000)),
            min(width, math.ceil((c+dx)*width/1000)), min(height, math.ceil((d+dy)*height/1000)))


def _encode(original, box, *, overview=False):
    source = original.crop(box)
    max_pixels, side = (MAX_OVERVIEW_PIXELS, 1600) if overview else (MAX_CROP_PIXELS, 1280)
    factor = min(1. if overview else 4., side/max(source.size), math.sqrt(max_pixels/(source.width*source.height)))
    size = tuple(max(1, math.floor(v*factor)) for v in source.size)
    resampling = 'identity' if size == source.size else 'nearest' if factor > 1 else 'lanczos'
    output = source if size == source.size else source.resize(size,
        Image.Resampling.NEAREST if factor > 1 else Image.Resampling.LANCZOS)
    stream = io.BytesIO(); output.save(stream, format='PNG', compress_level=3)
    raw = stream.getvalue(); digest = hashlib.sha256(raw).hexdigest()
    return digest, 'data:image/png;base64,'+base64.b64encode(raw).decode('ascii'), {
        'original_pixel_bbox': list(box), 'original_bbox': _normalized(box, original.size),
        'coordinate_space': 'original_1000', 'original_size': list(original.size),
        'source_crop_pixel_sha256': hashlib.sha256(source.tobytes()).hexdigest(),
        'output_png_sha256': digest, 'output_size': list(size), 'resampling': resampling}


def _layout_tool(arguments, *, context):
    _check(context)
    state, original = context.data['state'], context.data['original']
    document = context.data.get('document')
    if document is None:
        document = analyze_document(original, max_work_side=MAX_WORK_SIDE)
    _check(context)
    panels, body, cv_metric = _cv_regions(document, context)
    state['resource_metrics'].append(cv_metric)
    received = context.data.get('layout')
    regions = _valid_regions(received)
    if regions is not None:
        layout = {'status': 'ok', 'model': MODEL_NAME, 'regions': regions,
                  'coordinate_space': 'original_normalized_0_1', 'source': 'reused_layout_result'}
        lm = {'stage': 'layout', 'status': 'reused', 'worker_started': False,
              'model_inference_completed': False, 'previous_model_result_reused': True, 'model': MODEL_NAME}
    elif arguments['run_layout']:
        layout, lm = _run_layout(original, context, arguments['layout_timeout'])
    else:
        layout, lm = ({'status': 'not_run', 'model': MODEL_NAME, 'regions': []},
                      {'stage': 'layout', 'status': 'not_run', 'worker_started': False,
                       'model_inference_completed': False, 'model': MODEL_NAME})
    state['resource_metrics'].append(lm)
    _check(context)
    panels, body, omitted = _fuse(panels, body, layout)
    refs, descriptions, metadata = [state['overview_ref']], [
        '完整原图总览；局部窗口是OpenCV/版面预测的宽松阅读建议，不代表子图数量或答案。'], [state['overview_metadata']]
    selected = (panels+body)[:MAX_IMAGES-1]
    used = {tuple(state['overview_metadata']['original_pixel_bbox'])}
    for region in selected:
        _check(context)
        box = _pixels(region['bbox'], original.size)
        if box in used:
            continue
        used.add(box)
        ref, url, meta = _encode(original, box)
        state['images'][ref] = url
        refs.append(ref); metadata.append({**meta, 'region_id': region['id'], 'source': region['source']})
        descriptions.append(f"同一原图的宽松局部 {region['id']}，来源 {region['source']}；只裁取原RGB，不是新增子图。")
    shown = {m.get('region_id') for m in metadata}
    omitted['view_region_ids'] = [r['id'] for r in panels+body if r['id'] not in shown]
    _check(context)
    return {'panels': panels, 'body_regions': body, 'layout': layout, 'image_refs': refs,
        'view_descriptions': descriptions, 'view_metadata': metadata,
        'resource_metrics': state['resource_metrics'],
        'diagnostics': {'version': VERSION, 'source_sha256': context.source_sha256,
            'coordinate_space': 'original_1000', 'cv_executed': True,
            'layout_model_executed_this_call': lm.get('model_inference_completed') is True,
            'layout_model_result_reused': lm.get('previous_model_result_reused') is True,
            'document_reused': context.data.get('document') is not None,
            'segmentation_is_not_graph_inventory': True, 'geometry_required': False,
            'omitted': omitted, 'image_evidence': copy.deepcopy(document.diagnostics),
            'output_pixels': sum(math.prod(m['output_size']) for m in metadata),
            'status': 'candidates' if panels else 'fallback_original',
            'original_size': list(original.size)}}


def _registry():
    return ToolRegistry().register(ToolSpec(name='image.semantic_layout', version=VERSION,
        description='真实OpenCV留白/墨迹分组及可选隔离PP-DocLayoutV3版面预测，提供原RGB宽松局部。',
        input_schema={'type': 'object', 'required': ['run_layout', 'layout_timeout'],
                      'additionalProperties': False, 'properties': {
                          'run_layout': {'type': 'boolean'}, 'layout_timeout': {'type': 'number', 'minimum': 1, 'maximum': MAX_LAYOUT_SECONDS}}},
        output_schema={'type': 'object', 'required': ['panels', 'body_regions', 'layout', 'image_refs',
            'view_descriptions', 'view_metadata', 'resource_metrics', 'diagnostics'],
            'properties': {'image_refs': {'type': 'array', 'minItems': 1, 'maxItems': 5, 'items': {'type': 'string'}},
                           'panels': {'type': 'array', 'maxItems': MAX_PANELS},
                           'body_regions': {'type': 'array', 'maxItems': MAX_BODY_REGIONS}}},
        allowed_roles=frozenset({'semantic_extract'}), source_required=True,
        timeout_seconds=MAX_LAYOUT_SECONDS+10), _layout_tool)


def prepare_semantic_layout(raw, *, budget, layout=None, run_layout=False,
                            layout_timeout=None, document=None):
    """Return local candidates, original views, and actual execution audits.

    ``document`` is an optional caller-owned analysis of these same bytes;
    it must never come from model output. Only a completed, explicitly named
    PP-DocLayoutV3 result can skip a requested worker. No text/formula worker
    is started. The nonblocking shared lock, image preparation, cold model
    initialization and inference share a bounded worker allowance, clipped to
    the remaining upload deadline. DMATE_LAYOUT_SECONDS defaults to 30 and
    cannot exceed 35; an explicit argument may choose a shorter allowance.
    """
    budget.check()
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise TypeError('expected image bytes')
    if layout_timeout is None:
        layout_timeout = configured_layout_timeout()
    if (type(run_layout) is not bool or type(layout_timeout) not in (int, float)
            or not math.isfinite(layout_timeout) or not 1 <= layout_timeout <= MAX_LAYOUT_SECONDS):
        raise ValueError('invalid_layout_budget')
    if document is not None and not isinstance(document, DocumentEvidence):
        raise TypeError('expected DocumentEvidence')
    raw = bytes(raw); source_sha256 = hashlib.sha256(raw).hexdigest()
    if getattr(budget, 'source_sha256', None) not in (None, source_sha256):
        raise ValueError('layout_source_identity_mismatch')
    original = document.original if document is not None else decode_document_image(raw)
    if original.mode != 'RGB' or original.width*original.height > 16_000_000:
        raise ValueError('invalid_document_source')
    if cv2.getNumThreads() > 2:
        cv2.setNumThreads(2)
    budget.check()
    ref, overview, meta = _encode(original, (0, 0, *original.size), overview=True)
    state = {'images': {ref: overview}, 'overview_ref': ref, 'overview_metadata': meta,
             'control_error': None, 'resource_metrics': []}
    context = ToolContext(source_sha256=source_sha256, deadline_monotonic=budget.deadline,
        data={'original': original, 'document': document, 'budget': budget, 'state': state, 'layout': layout})
    envelope = _registry().call('image.semantic_layout', {'run_layout': run_layout, 'layout_timeout': layout_timeout},
                                role='semantic_extract', context=context)
    if state['control_error'] is not None:
        raise state['control_error']
    budget.check()
    if envelope['ok']:
        result = envelope['result']
    else:
        result = {'panels': [], 'body_regions': [], 'layout': {'status': 'unavailable', 'regions': []},
            'image_refs': [ref], 'view_descriptions': ['完整原RGB总览；本地分图未完成，仍按原图读取。'],
            'view_metadata': [meta], 'resource_metrics': state['resource_metrics'],
            'diagnostics': {'version': VERSION, 'source_sha256': source_sha256,
                'status': 'fallback_original', 'reason': envelope['error']['code'],
                'cv_executed': any(m.get('stage') == 'semantic_layout_cv' for m in state['resource_metrics']),
                'layout_model_executed_this_call': False, 'geometry_required': False}}
    return {**result, 'images': [state['images'][r] for r in result['image_refs']], 'tool_audit': list(context.audit)}


__all__ = ['prepare_semantic_layout', 'configured_layout_timeout']
