"""Bounded, isolated PaddleOCR Small text suggestions for semantic readers.

No recognised word, score, layout category, or OCR box is an acceptance gate.
The existing text-only worker retains original and auxiliary-pass provenance;
this adapter retains graph labels and uncertain/noise items as suggestions too.
It never downloads a missing model or starts layout/formula recognition.
"""
from __future__ import annotations

import copy
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import tempfile
import time

from dmate_tool_registry import ToolContext, ToolRegistry, ToolSpec
from image_evidence import DocumentEvidence, decode_document_image


VERSION = '2026-10-26-semantic-text-v1'
MODEL_NAMES = ('PP-OCRv6_small_det', 'PP-OCRv6_small_rec')
STAGE_SECONDS = 18.0
MAX_HINTS = 256
MAX_HINT_CHARACTERS = 512
MAX_TOTAL_CHARACTERS = 24_000
MAX_LAYOUT_REGIONS = 128
_PARTITIONS = ('body', 'graph_labels', 'uncertain', 'noise')
_ROLE_HINTS = {'body': 'body', 'graph_labels': 'graph_label',
               'uncertain': 'uncertain', 'noise': 'noise_or_caption'}


def _check(context):
    try:
        context.data['budget'].check()
    except Exception as exc:
        context.data['state']['control_error'] = exc
        raise
    context.check_deadline()


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _box(value, size):
    if not isinstance(value, (tuple, list)) or len(value) != 4 or not all(_number(x) for x in value):
        return None
    a, b, c, d = map(float, value)
    if 0 <= a < c <= size[0] and 0 <= b < d <= size[1]:
        return [a, b, c, d]
    return None


def _layout_input(value):
    # Only an actual, completed named layout result supplies partition hints.
    # OpenCV windows remain valuable elsewhere, but are not text truth here.
    value = value if isinstance(value, dict) else {}
    if isinstance(value.get('layout'), dict):
        value = value['layout']
    rows = value.get('regions')
    if value.get('model') != 'PP-DocLayoutV3' or value.get('status') != 'ok' or not isinstance(rows, list):
        return {'regions': [], 'status': 'unavailable'}
    regions = []
    for row in rows[:MAX_LAYOUT_REGIONS]:
        if not isinstance(row, dict) or _box(row.get('bbox'), (1, 1)) is None:
            continue
        if row.get('role') not in ('figure', 'text', 'formula', 'caption', 'noise'):
            continue
        score = row.get('score')
        regions.append({'id': str(row.get('id') or f'r{len(regions)+1}')[:64],
                        'bbox': _box(row['bbox'], (1, 1)), 'role': row['role'],
                        'score': float(score) if _number(score) and 0 <= score <= 1 else 0.})
    return {'regions': regions, 'status': 'ok', 'model': 'PP-DocLayoutV3'}


def _cache_readiness():
    """Inspect the existing configured cache without importing Paddle."""
    from ocr_runtime import configure_model_cache, ModelCacheError
    if any(importlib.util.find_spec(name) is None for name in ('paddle', 'paddleocr')):
        return {'status': 'dependency_unavailable', 'worker_started': False}
    env = dict(os.environ)
    try:
        cache = configure_model_cache(env)
    except ModelCacheError:
        return {'status': 'cache_unavailable', 'worker_started': False}
    root = Path(env['PADDLE_PDX_CACHE_HOME'])/'official_models'
    missing = []
    for name in MODEL_NAMES:
        folder = root/name
        try:
            ready = all((folder/file).is_file() and (folder/file).stat().st_size > 0
                        for file in ('inference.json', 'inference.pdiparams', 'inference.yml'))
        except OSError:
            ready = False
        if not ready:
            missing.append(name)
    return {'status': 'model_cache_missing' if missing else 'ready',
            'model_cache': cache, 'missing_models': missing, 'worker_started': False}


def _evidence_valid(result, size):
    if not isinstance(result, dict) or not isinstance(result.get('text_evidence'), dict):
        return False
    evidence = result['text_evidence']
    return (evidence.get('coordinate_space') == 'canonical_image_pixels'
            and evidence.get('image_size') == list(size)
            and all(isinstance(evidence.get(key), list) for key in _PARTITIONS))


def _reusable(result, size, source_sha256):
    """Reuse caller-owned completed workers, never a model's text claim.

    Old local OCR records predate source hashes. Their same-size binding is
    explicitly caller-owned; we do not claim a cryptographic binding for them.
    """
    if not _evidence_valid(result, size):
        return None, 'not_a_completed_text_result'
    diagnostics = result.get('diagnostics') if isinstance(result.get('diagnostics'), dict) else {}
    previous_sha = result.get('source_sha256') or diagnostics.get('source_sha256')
    if previous_sha is not None and previous_sha != source_sha256:
        return None, 'received_source_mismatch'
    metrics = result.get('resource_metrics')
    for metric in metrics[:16] if isinstance(metrics, list) else []:
        if not isinstance(metric, dict) or metric.get('stage') != 'text' or metric.get('status') != 'ok':
            continue
        audit = metric.get('audit') if isinstance(metric.get('audit'), dict) else {}
        current = audit.get('current') if isinstance(audit.get('current'), dict) else {}
        if (audit.get('stage') == 'text' and current.get('phase') == 'complete'
                and audit.get('input_size') == list(size)):
            return metric, ('source_sha256' if previous_sha else 'caller_owned_same_dimensions')
    return None, 'missing_completed_text_worker_audit'


def _run_text(original, layout, context):
    from ocr_runtime import run_worker
    started = time.monotonic()
    metric = {'stage': 'text', 'status': 'not_run', 'worker_started': False,
              'models': list(MODEL_NAMES), 'formula_enabled': False,
              'stage_timeout_seconds': STAGE_SECONDS, 'model_inference_completed': False}
    if context.deadline_monotonic-time.monotonic() < 1.:
        return None, {**metric, 'status': 'deadline_reserved'}
    _check(context)
    from graph_local_scheduler import local_model_lock
    with local_model_lock() as acquired:
        if not acquired:
            return None, {**metric, 'status': 'busy', 'seconds': 0.}
        readiness = _cache_readiness()
        metric.update(readiness)
        if readiness['status'] != 'ready':
            return None, metric
        _check(context)
        with tempfile.TemporaryDirectory(prefix='dmate-semantic-text-') as folder:
            root = Path(folder)
            # Native recognition crops keep all original pixels. The
            # existing BoundedTextModel limits only the detector to 1600.
            original.save(root/'original.png', compress_level=1)
            (root/'layout.json').write_text(json.dumps(layout, ensure_ascii=False), encoding='utf-8')
            _check(context)
            remaining = context.deadline_monotonic-time.monotonic()-.25
            if remaining < 1.:
                return None, {**metric, 'status': 'deadline_reserved'}
            result, measured = run_worker('text', root/'original.png', root/'text.json',
                layout_path=root/'layout.json', timeout=remaining)
            metric.update(measured)
            metric['worker_timeout_seconds'] = remaining
            metric['worker_started'] = bool(measured.get('phase_peaks') or measured.get('audit')
                                            or measured.get('rss_observed') or measured.get('status') == 'ok')
            completed = measured.get('status') == 'ok' and _evidence_valid(result, original.size)
            metric['model_inference_completed'] = completed
            metric['seconds_including_preparation'] = round(time.monotonic()-started, 6)
            if measured.get('status') == 'ok' and not completed:
                metric['status'] = 'invalid_worker_output'
            return result if completed else None, metric


def _normalise(result, size, context):
    evidence = result['text_evidence']
    hints, regions, partitions = [], [], {key: [] for key in _PARTITIONS}
    counts = {'input_items': sum(len(evidence[key]) for key in _PARTITIONS),
              'invalid_items': 0, 'unlocated_items': 0, 'truncated_items': 0,
              'capacity_omitted_items': 0, 'invalid_confidences': 0}
    characters = 0
    for category in _PARTITIONS:
        for index, row in enumerate(evidence[category][:MAX_HINTS+1]):
            _check(context)
            if len(hints) >= MAX_HINTS or characters >= MAX_TOTAL_CHARACTERS:
                break
            if not isinstance(row, dict) or not isinstance(row.get('content'), str) or not row['content'].strip():
                counts['invalid_items'] += 1
                continue
            text = row['content'][:min(MAX_HINT_CHARACTERS, MAX_TOTAL_CHARACTERS-characters)]
            if len(text) < len(row['content']):
                counts['truncated_items'] += 1
            characters += len(text)
            pixel_box = _box(row.get('box'), size)
            bbox = [round(value*1000/size[i % 2], 5) for i, value in enumerate(pixel_box)] if pixel_box else None
            if bbox is None:
                counts['unlocated_items'] += 1
            score = row.get('score')
            confidence = float(score) if _number(score) and 0 <= score <= 1 else None
            if confidence is None:
                counts['invalid_confidences'] += 1
            provenance = row.get('ocr_provenance')
            provenance = provenance if isinstance(provenance, dict) else {}
            clean_provenance = {key: value for key, value in provenance.items()
                if ((key in ('pass_index', 'item_index') and type(value) is int and 0 <= value <= 100_000)
                    or (key == 'pass_kind' and value in ('original', 'enhanced')))}
            hint_id = f'text_{len(hints)+1}'
            hint = {'id': hint_id, 'text': text, 'bbox': bbox, 'coordinate_space': 'original_1000',
                    'role_hint': _ROLE_HINTS[category], 'confidence': confidence,
                    'status': 'candidate', 'authoritative': False, 'source': 'paddleocr_small_text',
                    'ocr_provenance': clean_provenance}
            if isinstance(row.get('region_ids'), list):
                hint['layout_region_ids'] = [x[:64] for x in row['region_ids'][:16] if isinstance(x, str)]
            hints.append(hint)
            # Preserve the established evidence shape for existing callers;
            # pixel coordinates here are explicitly separate from hint boxes.
            item = {'type': 'text', 'content': text, 'box': pixel_box, 'score': confidence,
                    'ocr_provenance': copy.deepcopy(clean_provenance), 'hint_id': hint_id}
            partitions[category].append(item)
            if bbox is not None:
                regions.append({key: copy.deepcopy(hint[key]) for key in
                    ('id', 'bbox', 'coordinate_space', 'role_hint', 'confidence', 'status', 'source')})
    counts['capacity_omitted_items'] = max(0, counts['input_items']-len(hints)-counts['invalid_items'])
    partitions.update(image_size=list(size), coordinate_space='canonical_image_pixels')
    body_text = result.get('text')
    body_text = body_text[:MAX_TOTAL_CHARACTERS] if isinstance(body_text, str) else ''
    return hints, regions, partitions, body_text, counts


def _text_tool(arguments, context):
    state, original = context.data['state'], context.data['original']
    supplied = context.data.get('text_result')
    reusable, binding = _reusable(supplied, original.size, context.source_sha256)
    if reusable is not None:
        result = supplied
        metric = {'stage': 'text', 'status': 'reused', 'worker_started': False,
                  'model_inference_completed': False, 'previous_model_result_reused': True,
                  'models': list(MODEL_NAMES), 'formula_enabled': False,
                  'source_binding': binding, 'previous_worker_audit': copy.deepcopy(reusable.get('audit'))}
    else:
        result, metric = _run_text(original, context.data['layout'], context)
    state['resource_metrics'].append(metric)
    _check(context)
    if result is None:
        return {'text_hints': [], 'regions': [], 'text': '', 'text_evidence': {},
                'resource_metrics': state['resource_metrics'], 'diagnostics': {
                    'version': VERSION, 'source_sha256': context.source_sha256,
                    'status': 'unavailable', 'reason': metric.get('status'),
                    'original_size': list(original.size), 'fallback': 'original_image',
                    'model_executed_this_call': False, 'previous_result_reused': False,
                    'received_result_reason': binding if supplied is not None else None}}
    hints, regions, evidence, text, counts = _normalise(result, original.size, context)
    return {'text_hints': hints, 'regions': regions, 'text': text, 'text_evidence': evidence,
            'resource_metrics': state['resource_metrics'], 'diagnostics': {
                'version': VERSION, 'source_sha256': context.source_sha256,
                'status': 'candidates' if hints else 'empty_result', 'models': list(MODEL_NAMES),
                'coordinate_space': 'original_1000', 'original_size': list(original.size),
                'document_reused': context.data.get('document') is not None,
                'model_executed_this_call': metric.get('model_inference_completed') is True,
                'previous_result_reused': reusable is not None,
                'reuse_source_binding': binding if reusable is not None else None,
                'received_result_reason': binding if supplied is not None and reusable is None else None,
                'layout_regions_used': len(context.data['layout']['regions']),
                'ocr_is_not_transcription_or_topology_truth': True,
                'formula_executed': False, 'limits': counts}}


def _registry():
    return ToolRegistry().register(ToolSpec(
        name='image.semantic_text', version=VERSION,
        description='隔离执行现有PaddleOCR Small文字模型，保留题干、图标签及不确定项作为候选。',
        input_schema={'type': 'object', 'additionalProperties': False},
        output_schema={'type': 'object', 'required': ['text_hints', 'regions', 'text', 'text_evidence',
            'resource_metrics', 'diagnostics'], 'properties': {
                'text_hints': {'type': 'array', 'maxItems': MAX_HINTS},
                'regions': {'type': 'array', 'maxItems': MAX_HINTS}, 'text': {'type': 'string'}}},
        allowed_roles=frozenset({'semantic_extract'}), source_required=True,
        timeout_seconds=STAGE_SECONDS), _text_tool)


def prepare_semantic_text(raw, *, budget, layout=None, document=None, text_result=None):
    """Prepare bounded Small OCR suggestions; original-image reading is fallback.

    ``layout`` may be a completed PP result or prepare_semantic_layout output.
    Optional ``document`` and ``text_result`` are trusted application-owned
    material for these same image bytes, never values returned by a model.
    No new images are generated: callers retain their original overview.
    The 18s stage shares AgentBudget and includes the nonblocking shared lock.
    """
    started = time.monotonic()
    budget.check()
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise TypeError('expected image bytes')
    if document is not None and not isinstance(document, DocumentEvidence):
        raise TypeError('expected DocumentEvidence')
    raw = bytes(raw)
    source_sha256 = hashlib.sha256(raw).hexdigest()
    if getattr(budget, 'source_sha256', None) not in (None, source_sha256):
        raise ValueError('text_source_identity_mismatch')
    original = document.original if document is not None else decode_document_image(raw)
    if original.mode != 'RGB' or original.width*original.height > 16_000_000:
        raise ValueError('invalid_document_source')
    budget.check()
    state = {'control_error': None, 'resource_metrics': []}
    context = ToolContext(source_sha256=source_sha256,
        deadline_monotonic=min(started+STAGE_SECONDS, budget.deadline-2.),
        data={'budget': budget, 'state': state, 'original': original, 'document': document,
              'layout': _layout_input(layout), 'text_result': text_result})
    envelope = _registry().call('image.semantic_text', {}, role='semantic_extract', context=context)
    if state['control_error'] is not None:
        raise state['control_error']
    budget.check()
    result = envelope.get('result') if envelope['ok'] else None
    if result is None:
        result = {'text_hints': [], 'regions': [], 'text': '', 'text_evidence': {},
            'resource_metrics': state['resource_metrics'], 'diagnostics': {
                'version': VERSION, 'source_sha256': source_sha256, 'status': 'unavailable',
                'reason': envelope['error']['code'], 'fallback': 'original_image',
                'model_executed_this_call': any(m.get('model_inference_completed') is True
                                               for m in state['resource_metrics']),
                'previous_result_reused': False}}
    result['diagnostics']['seconds'] = round(time.monotonic()-started, 6)
    return {**result, 'images': [], 'tool_audit': list(context.audit)}


__all__ = ['prepare_semantic_text']
