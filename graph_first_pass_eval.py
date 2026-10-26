"""Independent, evaluation-only graph comparison. Never import into OCR.

No recognition, answer lookup, or topology repair takes place here. References
must be explicitly supplied by the private benchmark caller. Counts alone never
constitute a pass; correspondence uses visible labels and original coordinates.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata


@dataclass(frozen=True)
class EvaluationConfig:
    minimum_panel_iou: float = 0.30
    # Distance in units of the full original image diagonal, aspect corrected.
    maximum_vertex_distance: float = 0.035


STRUCTURE_DIMENSIONS = (
    'panels', 'vertices', 'endpoints', 'directions', 'multiplicity', 'self_loops',
    'weights', 'edge_labels', 'styles', 'edge_instances', 'graph_types',
)
CURRENT_PIPELINE_VERSION = '2026-10-26-evidence-two-pass-v2'
FRONTEND_CHECKS = (
    'public_projection', 'panels', 'vertex_labels', 'graph_types', 'edge_instances',
    'edge_endpoints', 'directions', 'multiplicity', 'self_loops', 'weights',
    'edge_labels', 'styles', 'status', 'text', 'original_preview',
    'response_immutable', 'readonly', 'no_markup_injection',
    'source_unchanged', 'network_isolation',
)


def normalized_text(value):
    """Normalize canonical Unicode and whitespace without collapsing math.

    NFKC would equate x² with x2 and turn distinct mathematical labels into the
    same text. NFC preserves superscripts, subscripts and mathematical symbols.
    """
    if value is None:
        return None
    return re.sub(r'\s+', '', unicodedata.normalize('NFC', str(value)))


def prediction_digest(prediction):
    """Bind browser observations to one exact response, never a similar fixture."""
    if not isinstance(prediction, dict):
        return None
    try:
        encoded = json.dumps(prediction, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def _point(node):
    if not isinstance(node, dict):
        return None
    values = [node.get('x'), node.get('y')]
    if any(isinstance(x, bool) or not isinstance(x, (int, float))
           or not math.isfinite(x) or not 0 <= x <= 1 for x in values):
        return None
    return values


def _box(value):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    if _point({'x': value[0], 'y': value[1]}) is None or _point({'x': value[2], 'y': value[3]}) is None:
        return None
    return list(value) if value[0] < value[2] and value[1] < value[3] else None


def box_iou(first, second):
    a, b = _box(first), _box(second)
    if a is None or b is None:
        return 0.0
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
    return intersection/union if union else 0.0


def _assignment(costs, columns):
    """Rectangular minimum-cost bijection, Hungarian algorithm, stdlib only."""
    rows = len(costs)
    size = max(rows, columns)
    if not rows or not columns:
        return []
    matrix = [[costs[i][j] if i < rows and j < columns else 10000.0
               for j in range(size)] for i in range(size)]
    u, v, p, way = [0.]*(size+1), [0.]*(size+1), [0]*(size+1), [0]*(size+1)
    for i in range(1, size+1):
        p[0] = i
        j0 = 0
        minimum, used = [math.inf]*(size+1), [False]*(size+1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], math.inf, 0
            for j in range(1, size+1):
                if not used[j]:
                    current = matrix[i0-1][j-1]-u[i0]-v[j]
                    if current < minimum[j]:
                        minimum[j], way[j] = current, j0
                    if minimum[j] < delta:
                        delta, j1 = minimum[j], j
            for j in range(size+1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minimum[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    return sorted((p[j]-1, j-1) for j in range(1, size+1)
                  if p[j] and p[j] <= rows and j <= columns)


def _nodes(graph):
    return graph.get('vertices', graph.get('nodes')) if isinstance(graph, dict) else None


def _name(graph):
    return graph.get('name', graph.get('title'))


def _label(edge):
    return edge.get('edge_label', edge.get('label'))


def _number(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return ('invalid', str(value))
    text = normalized_text(value)
    try:
        number = Decimal(text)
        if number.is_finite():
            return ('number', str(number.normalize()))
    except (InvalidOperation, ValueError, TypeError):
        pass
    return ('text', text)


def _is_complete_reference(graph):
    if graph.get('annotation_complete') is False or graph.get('topology_complete') is False:
        return False
    return graph.get('annotation_complete') is True or graph.get('topology_complete') is True


def reference_issues(reference):
    """Missing/uncertain reference evidence cannot certify a prediction."""
    if not isinstance(reference, dict):
        return ['missing_reference']
    issues = []
    if reference.get('annotation_complete') is False:
        issues.append('image_annotation_incomplete')
    if reference.get('issues') or reference.get('uncertainties'):
        issues.append('image_annotation_uncertain')
    if not isinstance(reference.get('sha256'), str) or not re.fullmatch(r'[0-9a-fA-F]{64}', reference['sha256']):
        issues.append('missing_reference_image_digest')
    graphs = reference.get('graphs')
    if not isinstance(graphs, list):
        return issues + ['missing_reference_graphs']
    graph_kind = reference.get('is_graph_theory_image')
    if graph_kind is None:
        graph_kind = True if reference.get('kind') == 'graph_diagram' else False if reference.get('kind') in ('non_graph', 'text_only', 'non_graph_chart') else None
    if not graphs and graph_kind is not False:
        issues.append('empty_reference_inventory_not_explicitly_non_graph')
    if not graphs and reference.get('annotation_complete') is not True:
        issues.append('non_graph_reference_not_certified')
    for i, graph in enumerate(graphs):
        prefix = f'graph[{i}]'
        if not isinstance(graph, dict):
            issues.append(prefix+':invalid_graph')
            continue
        if not _is_complete_reference(graph) or graph.get('issues') or graph.get('uncertainties') or graph.get('labels_complete') is False:
            issues.append(prefix+':annotation_incomplete_or_uncertain')
        if _box(graph.get('bbox')) is None:
            issues.append(prefix+':missing_bbox')
        for field in ('directed', 'weighted'):
            if type(graph.get(field)) is not bool:
                issues.append(prefix+':unknown_'+field)
        vertices, edges = _nodes(graph), graph.get('edges')
        if not isinstance(vertices, list) or not vertices or not isinstance(edges, list):
            issues.append(prefix+':missing_vertex_or_edge_inventory')
            continue
        identifiers = [n.get('id') for n in vertices if isinstance(n, dict)]
        if any(not isinstance(x, str) or not x for x in identifiers) or len(set(identifiers)) != len(vertices):
            issues.append(prefix+':invalid_vertex_ids')
        seen = set()
        for node in vertices:
            if not isinstance(node, dict) or 'label' not in node or _point(node) is None:
                issues.append(prefix+':missing_vertex_evidence')
                continue
            signature = (normalized_text(node['label']), *node_point(node))
            if signature in seen:
                issues.append(prefix+':ambiguous_identical_vertices')
            seen.add(signature)
        for edge in edges:
            if not isinstance(edge, dict):
                issues.append(prefix+':invalid_edge')
                continue
            if (edge.get('from') not in identifiers or edge.get('to') not in identifiers
                    or edge.get('direction') not in ('forward', 'reverse', 'undirected')
                    or edge.get('style') not in ('solid', 'dashed', 'dotted')
                    or 'weight' not in edge or not ('edge_label' in edge or 'label' in edge)
                    or type(edge.get('multiplicity', 1)) is not int or edge.get('multiplicity', 1) < 1
                    or edge.get('issues') or edge.get('uncertainties')):
                issues.append(prefix+':uncertain_or_missing_edge_evidence')
            if graph.get('weighted') is True and edge.get('weight') is None:
                issues.append(prefix+':unknown_edge_weight')
            if graph.get('weighted') is False and edge.get('weight') is not None:
                issues.append(prefix+':inconsistent_weighted_reference')
    return sorted(set(issues))


def reference_text_issues(reference):
    """A cropped/missing transcription is independent of graph readiness."""
    if not isinstance(reference, dict):
        return ['missing_reference_text']
    field = 'question_text' if 'question_text' in reference else 'transcribed_text'
    if not isinstance(reference.get(field), str):
        return ['missing_reference_text']
    complete = reference.get('question_text_complete', reference.get('annotation_complete'))
    return [] if complete is True else ['reference_text_completeness_unknown_or_cropped']


def node_point(node):
    # Used only after validation; never guesses a position.
    return node['x'], node['y']


def annotation_records(document):
    if isinstance(document, list):
        return document
    if isinstance(document, dict):
        for key in ('images', 'records', 'annotations', 'cases'):
            if isinstance(document.get(key), list):
                return document[key]
    raise ValueError('No supported annotation record collection')


def load_annotations(paths):
    records = {}
    for path in paths:
        for record in annotation_records(json.loads(Path(path).read_text(encoding='utf-8'))):
            identifier = record.get('id', record.get('image_id')) if isinstance(record, dict) else None
            if not isinstance(identifier, str) or not identifier:
                raise ValueError('Annotation record has no image ID')
            if identifier in records:
                raise ValueError('Duplicate annotation image ID: '+identifier)
            records[identifier] = record
    return records


def _distance(a, b, reference):
    p, q = _point(a), _point(b)
    if p is None or q is None:
        return math.inf
    size = reference.get('image_size', [reference.get('width', 1), reference.get('height', 1)])
    try:
        w, h = float(size[0]), float(size[1])
        if w <= 0 or h <= 0:
            raise ValueError
    except (TypeError, ValueError, IndexError):
        w, h = 1., 1.
    return math.hypot((p[0]-q[0])*w, (p[1]-q[1])*h)/math.hypot(w, h)


def _counter_rows(counter):
    return [{'signature': key, 'count': count} for key, count in sorted(counter.items(), key=lambda item: repr(item[0]))]


def _edge_counters(edges, mapping, *, gold=False):
    counters = {key: Counter() for key in STRUCTURE_DIMENSIONS if key not in ('panels', 'vertices', 'graph_types')}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        a, b = mapping.get(edge.get('from')), mapping.get(edge.get('to'))
        if a is None or b is None:
            # Unknown endpoints remain observable and can never match a reference.
            a = a if a is not None else '<unmapped:'+str(edge.get('from'))+'>'
            b = b if b is not None else '<unmapped:'+str(edge.get('to'))+'>'
        direction = edge.get('direction', '<missing>')
        if direction == 'reverse':
            a, b, direction = b, a, 'forward'
        pair = tuple(sorted((a, b)))
        oriented = pair if direction == 'undirected' else (a, b)
        core = (*oriented, direction)
        weight, label, style = _number(edge.get('weight')), normalized_text(_label(edge)), edge.get('style', '<missing>')
        count = edge.get('multiplicity', 1)
        count = count if type(count) is int and 1 <= count <= 300 else 1
        counters['endpoints'][pair] += count
        counters['directions'][core] += count
        counters['multiplicity'][pair] += count
        if a == b:
            counters['self_loops'][(a, direction)] += count
        counters['weights'][(*core, weight)] += count
        counters['edge_labels'][(*core, label)] += count
        counters['styles'][(*core, style)] += count
        counters['edge_instances'][(*core, weight, label, style)] += count
    return counters


def _predicted_graph_issues(graph):
    issues = []
    if graph.get('schema_version') != 'dmate.graph/1':
        issues.append('missing_or_unsupported_graph_schema')
    vertices, edges = _nodes(graph), graph.get('edges')
    if not isinstance(vertices, list) or not isinstance(edges, list):
        return ['missing_vertex_or_edge_inventory']
    ids = [v.get('id') for v in vertices if isinstance(v, dict)]
    if any(not isinstance(v, str) or not v for v in ids) or len(set(ids)) != len(vertices):
        issues.append('invalid_or_duplicate_vertex_ids')
    if any(not isinstance(v, dict) or 'label' not in v or _point(v) is None for v in vertices):
        issues.append('missing_vertex_label_or_position')
    valid_points = [tuple(_point(v)) for v in vertices if _point(v) is not None]
    if len(valid_points) != len(set(valid_points)):
        issues.append('distinct_vertices_collapsed_to_identical_position')
    box = _box(graph.get('bbox'))
    if box and any(not (box[0]-.01 <= x <= box[2]+.01 and box[1]-.01 <= y <= box[3]+.01) for x, y in valid_points):
        issues.append('vertex_outside_graph_bbox')
    edge_ids = []
    for edge in edges:
        if not isinstance(edge, dict):
            issues.append('invalid_edge')
            continue
        edge_ids.append(edge.get('id'))
        if any(k not in edge for k in ('from', 'to', 'direction', 'weight', 'edge_label', 'style', 'multiplicity', 'status')):
            issues.append('missing_critical_edge_field')
        if edge.get('from') not in ids or edge.get('to') not in ids:
            issues.append('invalid_or_cross_graph_endpoint')
        if edge.get('direction') not in ('forward', 'undirected') or edge.get('style') not in ('solid', 'dashed', 'dotted'):
            issues.append('unknown_or_noncanonical_direction_or_style')
        # The public canonical/card contract represents every physical edge
        # independently. A scalar count would hide distinct rendered instances.
        if type(edge.get('multiplicity')) is not int or edge.get('multiplicity') != 1:
            issues.append('non_atomic_or_invalid_multiplicity')
        if edge.get('status') != 'accepted':
            issues.append('pending_or_unconfirmed_edge')
    if any(not isinstance(e, str) or not e for e in edge_ids) or len(set(edge_ids)) != len(edge_ids):
        issues.append('invalid_or_duplicate_edge_ids')
    if graph.get('complete') is not True:
        issues.append('graph_not_complete')
    if graph.get('uncertain_edges') or graph.get('node_complete') is False or graph.get('inventory_reviewed') is False:
        issues.append('unresolved_graph_evidence')
    if any(type(graph.get(field)) is not bool for field in ('directed', 'weighted', 'multigraph')):
        issues.append('unknown_graph_type')
    if _box(graph.get('bbox')) is None:
        issues.append('missing_or_invalid_bbox')
    if issues and graph.get('complete') is True:
        issues.append('complete_claim_with_invalid_or_unresolved_fields')
    return sorted(set(issues))


def _run_evidence(evidence, reference, prediction=None):
    if not isinstance(evidence, dict):
        return {'status': 'not_certified', 'issues': ['missing_live_run_evidence']}
    issues, missing = [], []
    if evidence.get('document_requests') != 1:
        issues.append('document_not_executed_exactly_once')
    if evidence.get('is_live') is not True:
        missing.append('not_a_verified_live_run')
    if evidence.get('source_unchanged') is False:
        issues.append('source_changed_during_request')
    elif evidence.get('source_unchanged') is not True:
        missing.append('source_snapshot_not_verified')
    if evidence.get('image_sha256') != reference.get('sha256'):
        issues.append('original_image_digest_mismatch')
    if not evidence.get('request_started_at'):
        missing.append('request_start_time_missing')
    started = finished = None
    try:
        date = datetime.fromisoformat(evidence['request_started_at'])
        if date.tzinfo is None:
            raise ValueError('Timezone missing')
        started = date.timestamp()
        end = datetime.fromisoformat(evidence['request_finished_at'])
        if end.tzinfo is None:
            raise ValueError('Timezone missing')
        finished = end.timestamp()
        if finished < started:
            issues.append('request_finished_before_start')
    except (KeyError, TypeError, ValueError, OverflowError):
        missing.append('request_time_not_verifiable')
    snapshot = evidence.get('source_snapshot') or {}
    if not snapshot.get('git_sha') or type(snapshot.get('dirty')) is not bool or not snapshot.get('source_tree_sha256'):
        missing.append('git_and_source_snapshot_missing')
    if evidence.get('mode') == 'http' and evidence.get('server_source_verified') is not True:
        missing.append('http_server_source_identity_unverified')
    if evidence.get('pipeline_contract') != 'evidence-two-pass':
        missing.append('two_pass_execution_contract_missing')
    if not isinstance(prediction, dict) or prediction.get('graph_display_version') != CURRENT_PIPELINE_VERSION:
        missing.append('current_pipeline_version_not_verified')
    execution_id = evidence.get('execution_id')
    if not isinstance(execution_id, str) or not execution_id:
        missing.append('execution_identity_missing')
    metrics = evidence.get('model_attempts')
    text_metrics = evidence.get('text_model_attempts')
    transports = evidence.get('transport_attempts')
    if not isinstance(metrics, list) or not metrics:
        missing.append('model_attempt_evidence_missing')
        metrics = []
    if not isinstance(text_metrics, list):
        missing.append('separate_text_model_ledger_missing')
        text_metrics = []
    if not isinstance(transports, list) or not transports:
        missing.append('actual_transport_evidence_missing')
        transports = []

    def check_time(record):
        timestamp = record.get('started_at_unix')
        if type(timestamp) not in (int, float) or not math.isfinite(timestamp):
            missing.append('attempt_start_missing')
        elif started is not None and finished is not None and not started-1 <= timestamp <= finished+1:
            issues.append('model_attempt_not_from_this_request')
        if not execution_id or record.get('execution_id') != execution_id:
            missing.append('attempt_execution_identity_unverified')

    sends = {}
    send_identities = set()
    for sent in transports:
        if not isinstance(sent, dict):
            missing.append('invalid_transport_record')
            continue
        check_time(sent)
        tid = sent.get('transport_id')
        if not isinstance(tid, str) or not tid:
            missing.append('transport_identity_missing')
        elif tid in sends:
            issues.append('repeated_transport_identity')
        else:
            sends[tid] = sent
        identity = (sent.get('provider'), sent.get('logical_call'), sent.get('attempt'))
        if identity in send_identities:
            issues.append('repeated_transport_for_logical_attempt')
        send_identities.add(identity)
        if sent.get('provider') not in ('qwen', 'text'):
            issues.append('unscoped_model_transport')
        if type(sent.get('attempt')) is not int or sent['attempt'] != 1:
            issues.append('model_retry_or_unidentified_attempt')
        if sent.get('method') != 'POST' or not sent.get('host'):
            missing.append('transport_target_unverified')
        if not re.fullmatch(r'[0-9a-f]{64}', str(sent.get('request_body_sha256') or '')):
            missing.append('transport_payload_digest_missing')
        if sent.get('http_status') != 200 or sent.get('exception_type'):
            issues.append('model_transport_not_successful')

    qwen_sends = [s for s in transports if isinstance(s, dict) and s.get('provider') == 'qwen']
    text_sends = [s for s in transports if isinstance(s, dict) and s.get('provider') == 'text']
    qwen_metrics = [m for m in metrics if isinstance(m, dict) and m.get('provider') == 'qwen']
    complete_claim = not isinstance(prediction, dict) or prediction.get('recognition_status') in ('complete', 'not_graph')
    if len(qwen_sends) > 2 or len(qwen_metrics) > 2:
        issues.append('qwen_two_send_budget_exceeded')
    if reference.get('graphs'):
        if (metrics and len(qwen_metrics) != 2) or (transports and len(qwen_sends) != 2):
            (issues if complete_claim else missing).append('two_successful_qwen_sends_not_completed')
        if not qwen_metrics:
            missing.append('vision_model_attempt_missing')
    if len(text_metrics) > 1 or len(text_sends) > 1:
        issues.append('text_correction_single_send_budget_exceeded')
    if qwen_sends and len(qwen_sends) == 2:
        if [s.get('logical_call') for s in qwen_sends] != [1, 2]:
            issues.append('qwen_stage_send_order_invalid')

    used_sends, calls = set(), set()
    for group, records in (('qwen', metrics), ('text', text_metrics)):
        for metric in records:
            if not isinstance(metric, dict):
                missing.append('invalid_attempt_evidence')
                continue
            check_time(metric)
            if metric.get('provider') != group:
                issues.append('model_metric_in_wrong_ledger')
            if type(metric.get('attempt')) is not int or metric['attempt'] != 1:
                issues.append('model_retry_or_unidentified_attempt')
            identity = (group, metric.get('logical_call'))
            if type(metric.get('logical_call')) is not int or metric['logical_call'] < 1:
                missing.append('attempt_identity_missing')
            elif identity in calls:
                issues.append('repeated_model_logical_call')
            calls.add(identity)
            model = metric.get('model')
            if group == 'qwen' and model != 'qwen3-vl-plus':
                issues.append('unexpected_vision_model')
            elif group == 'text' and (not isinstance(model, str) or not model.startswith('deepseek-')):
                issues.append('unexpected_text_correction_model')
            if metric.get('http_status') != 200 or metric.get('status') != 200 or metric.get('error') or metric.get('exception_type'):
                issues.append('model_metric_not_successful')
            if group == 'qwen':
                if metric.get('finish_reason') != 'stop':
                    issues.append('vision_response_not_complete')
                returned = metric.get('returned_model')
                if not isinstance(returned, str) or not (returned == 'qwen3-vl-plus' or returned.startswith('qwen3-vl-plus-')):
                    missing.append('returned_vision_model_unverified')
            elif metric.get('finish_reason') in ('length', 'network_error'):
                issues.append('text_response_not_complete')
            tid = metric.get('transport_id')
            sent = sends.get(tid) if isinstance(tid, str) else None
            if sent is None:
                missing.append('model_metric_has_no_observed_send')
                continue
            if tid in used_sends:
                issues.append('multiple_metrics_for_one_transport')
            used_sends.add(tid)
            for field in ('provider', 'logical_call', 'attempt', 'model', 'http_status', 'execution_id'):
                if metric.get(field) != sent.get(field):
                    issues.append('provider_transport_mismatch:'+field)
            if group == 'qwen':
                prompt = metric.get('prompt_sha256')
                images = metric.get('image_sha256')
                if (not re.fullmatch(r'[0-9a-f]{64}', str(prompt or ''))
                        or not isinstance(images, list) or not images
                        or not all(re.fullmatch(r'[0-9a-f]{64}', str(value)) for value in images)):
                    missing.append('vision_input_identity_missing')
                elif prompt != sent.get('prompt_sha256') or images != sent.get('image_sha256'):
                    issues.append('provider_transport_input_mismatch')
            when, sent_at = metric.get('started_at_unix'), sent.get('started_at_unix')
            if type(when) in (int, float) and type(sent_at) in (int, float):
                duration = metric.get('seconds')
                if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
                    missing.append('model_attempt_duration_missing')
                elif not when-.1 <= sent_at <= when+duration+.1:
                    issues.append('transport_outside_provider_call')
    if set(sends)-used_sends:
        missing.append('observed_send_has_no_provider_metric')
    if isinstance(prediction, dict):
        diag = prediction.get('diagnostics')
        correction = diag.get('correction') if isinstance(diag, dict) else None
        correction = correction if isinstance(correction, dict) else {}
        if correction.get('status') == 'ok' and str(prediction.get('text') or '').strip() and len(text_metrics) != 1:
            missing.append('claimed_text_correction_has_no_observed_call')
    return {'status': 'fail' if issues else 'not_certified' if missing else 'pass',
            'issues': sorted(set(issues)), 'missing_evidence': sorted(set(missing)),
            'qwen_sends': len(qwen_sends), 'text_sends': len(text_sends),
            'pipeline_contract': evidence.get('pipeline_contract')}


def _frontend_evidence(evidence, reference, prediction, run_evidence):
    if not isinstance(evidence, dict) or evidence.get('status') == 'not_run':
        return {'status': 'not_run', 'issues': ['actual_browser_render_not_checked']}
    if evidence.get('status') == 'fail':
        return {'status': 'fail', 'issues': ['actual_browser_render_failed']}
    if evidence.get('kind') != 'original_response' or evidence.get('fixture_only') is True:
        return {'status': 'not_certified', 'issues': ['fixture_or_unbound_browser_run_cannot_certify_original']}
    required = ('image_sha256', 'prediction_sha256', 'source_tree_sha256', 'execution_id')
    missing = [name for name in required if not evidence.get(name)]
    artifacts = evidence.get('artifact_paths')
    if (evidence.get('status') != 'pass' or evidence.get('actual_browser') is not True
            or evidence.get('exact_edge_projection_checked') is not True
            or evidence.get('contract') != 'original_preview_and_text_cards'
            or not isinstance(artifacts, list) or not artifacts
            or not all(isinstance(path, str) and path for path in artifacts)):
        missing.append('frontend_evidence_incomplete')
    checks = evidence.get('checks')
    if (evidence.get('schema_version') != 2 or not isinstance(checks, list)
            or {c.get('name') for c in checks if isinstance(c, dict)} != set(FRONTEND_CHECKS)
            or len(checks) != len(FRONTEND_CHECKS)):
        missing.append('frontend_itemized_checks_missing')
    elif any(c.get('status') != 'pass' for c in checks):
        return {'status': 'fail', 'issues': ['frontend_itemized_check_failed']}
    views = evidence.get('views')
    per_view = set(FRONTEND_CHECKS)-{'source_unchanged', 'network_isolation'}
    if (not isinstance(views, list) or len(views) != 2
            or {v.get('mode') for v in views if isinstance(v, dict)} != {'desktop', 'mobile'}):
        missing.append('frontend_viewport_checks_missing')
    else:
        for view in views:
            observed = view.get('checks')
            if (not isinstance(observed, list)
                    or {c.get('name') for c in observed if isinstance(c, dict)} != per_view
                    or len(observed) != len(per_view)):
                missing.append('frontend_viewport_itemized_checks_missing')
            elif any(c.get('status') != 'pass' for c in observed):
                return {'status': 'fail', 'issues': ['frontend_viewport_check_failed']}
    if (evidence.get('source_unchanged') is not True
            or not isinstance(evidence.get('source_snapshot'), dict)
            or any(type(evidence.get(key)) is not int or evidence[key] != 0
                   for key in ('ocr_requests', 'external_network_requests', 'external_requests_blocked'))):
        missing.append('frontend_replay_isolation_evidence_missing')
    if evidence.get('source_unchanged') is False:
        return {'status': 'fail', 'issues': ['source_changed_during_frontend_replay']}
    if any(isinstance(evidence.get(key), (int, float)) and evidence[key] > 0
           for key in ('ocr_requests', 'external_network_requests', 'external_requests_blocked')):
        return {'status': 'fail', 'issues': ['frontend_replay_attempted_ocr_or_external_network']}
    artifact_digests = evidence.get('artifact_sha256')
    if (not isinstance(artifact_digests, dict) or not isinstance(artifacts, list)
            or any(not isinstance(artifact_digests.get(path), str)
                   or not re.fullmatch(r'[a-f0-9]{64}', artifact_digests[path]) for path in artifacts)
            or not isinstance(evidence.get('first_response_file_sha256'), str)
            or not re.fullmatch(r'[a-f0-9]{64}', evidence['first_response_file_sha256'])):
        missing.append('frontend_artifact_integrity_binding_missing')
    if missing:
        return {'status': 'not_certified', 'issues': missing}
    issues = []
    if evidence['image_sha256'] != reference.get('sha256'):
        issues.append('browser_original_image_mismatch')
    if evidence['prediction_sha256'] != prediction_digest(prediction):
        issues.append('browser_response_mismatch')
    run = run_evidence if isinstance(run_evidence, dict) else {}
    snapshot = run.get('source_snapshot') or {}
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    if evidence['source_tree_sha256'] != snapshot.get('source_tree_sha256'):
        issues.append('browser_source_snapshot_mismatch')
    if evidence['execution_id'] != run.get('execution_id'):
        issues.append('browser_execution_id_mismatch')
    browser_source = evidence['source_snapshot']
    if any(browser_source.get(key) != snapshot.get(key)
           for key in ('git_sha', 'dirty', 'source_tree_sha256')):
        issues.append('browser_full_source_snapshot_mismatch')
    return {'status': 'fail' if issues else 'pass', 'issues': issues,
            'contract': 'original_preview_and_text_cards', 'artifact_paths': artifacts}


def evaluate_prediction(reference, prediction, *, run_evidence=None, frontend_evidence=None, config=None):
    """Strict first-result evaluation with separately visible evidence gates.

    A structure pass is never a full certification: original text, completeness,
    source/attempt evidence, and actual frontend rendering must also pass.
    """
    config = config or EvaluationConfig()
    if not 0 < config.minimum_panel_iou <= 1 or not 0 < config.maximum_vertex_distance < 1:
        raise ValueError('Invalid evaluation tolerances')
    ref_issues = reference_issues(reference)
    dims = {name: {'status': 'pass', 'issues': []} for name in STRUCTURE_DIMENSIONS+('schema', 'completeness')}
    result = {'schema_version': 1, 'image_id': (reference or {}).get('id', (reference or {}).get('image_id')),
              'config': asdict(config), 'reference': {'status': 'not_certified' if ref_issues else 'ready',
                  'scope': 'graph_structure', 'issues': ref_issues,
                  'text_status': 'not_certified' if reference_text_issues(reference) else 'ready',
                  'text_issues': reference_text_issues(reference)},
              'dimensions': dims, 'graph_matches': []}
    def fail(name, issue, **details):
        dims[name]['status'] = 'fail'
        dims[name]['issues'].append({'code': issue, **details})
    if ref_issues:
        for dimension in dims.values():
            dimension.update(status='not_certified', issues=[{'code': 'reference_not_certified'}])
        dims['text'] = {'status': 'not_certified', 'issues': ['reference_not_certified']}
    elif not isinstance(prediction, dict) or not isinstance(prediction.get('graph_structures'), list):
        fail('schema', 'missing_graph_structures')
        for name in STRUCTURE_DIMENSIONS:
            dims[name] = {'status': 'fail', 'issues': [{'code': 'missing_graph_structures'}]}
        fail('completeness', 'missing_recognition_result')
        dims['text'] = {'status': 'fail', 'issues': ['missing_prediction_text']}
    else:
        gold, observed = reference['graphs'], prediction['graph_structures']
        if any(not isinstance(g, dict) for g in observed):
            fail('schema', 'invalid_graph_object')
            observed = [g for g in observed if isinstance(g, dict)]
        if len(gold) != len(observed):
            fail('panels', 'subgraph_count_mismatch', expected=len(gold), actual=len(observed))
        costs = [[1-box_iou(g.get('bbox'), p.get('bbox'))
                  + (0.2 if _name(g) is not None and normalized_text(_name(g)) != normalized_text(_name(p)) else 0)
                  for p in observed] for g in gold]
        assignments = _assignment(costs, len(observed))
        for number, (gi, pi) in enumerate(assignments):
            for gj, pj in assignments[number+1:]:
                if box_iou(gold[gi].get('bbox'), gold[gj].get('bbox')) < .1 and box_iou(observed[pi].get('bbox'), observed[pj].get('bbox')) > .9:
                    fail('panels', 'distinct_panels_collapsed_to_same_bbox', predicted_graphs=[pi, pj])
        for gi, pi in assignments:
            g, p = gold[gi], observed[pi]
            prefix = {'reference_graph': gi, 'predicted_graph': pi}
            overlap = box_iou(g.get('bbox'), p.get('bbox'))
            match = {**prefix, 'bbox_iou': round(overlap, 6), 'vertex_matches': []}
            result['graph_matches'].append(match)
            if overlap < config.minimum_panel_iou:
                fail('panels', 'subgraph_bbox_mismatch', **prefix, iou=overlap)
            # Titles assist assignment; exact printed titles remain auditable,
            # without confusing arbitrary generated graph IDs with printed text.
            if _name(g) is not None and normalized_text(_name(g)) != normalized_text(_name(p)):
                fail('panels', 'printed_graph_name_mismatch', **prefix, expected=_name(g), actual=_name(p))
            issues = _predicted_graph_issues(p)
            if issues:
                fail('schema', 'invalid_prediction_fields', **prefix, details=issues)
                fail('completeness', 'unresolved_or_invalid_graph', **prefix, details=issues)
            gn, pn = _nodes(g), _nodes(p)
            pn = pn if isinstance(pn, list) else []
            pn = [n for n in pn if isinstance(n, dict)]
            if len(gn) != len(pn):
                fail('vertices', 'vertex_count_mismatch', **prefix, expected=len(gn), actual=len(pn))
            node_costs = []
            for a in gn:
                row = []
                for b in pn:
                    distance = _distance(a, b, reference)
                    row.append((distance if math.isfinite(distance) else 1000.)
                               + (10. if normalized_text(a['label']) != normalized_text(b.get('label')) else 0.)
                               + (100. if distance > config.maximum_vertex_distance else 0.))
                node_costs.append(row)
            mapping = {}
            for ni, nj in _assignment(node_costs, len(pn)):
                a, b = gn[ni], pn[nj]
                distance = _distance(a, b, reference)
                mapping[b.get('id')] = a['id']
                match['vertex_matches'].append({'reference_id': a['id'], 'predicted_id': b.get('id'),
                                                'distance': round(distance, 6) if math.isfinite(distance) else None})
                if distance > config.maximum_vertex_distance:
                    fail('vertices', 'vertex_position_mismatch', **prefix, reference_vertex=a['id'], predicted_vertex=b.get('id'), distance=distance if math.isfinite(distance) else None)
                if normalized_text(a['label']) != normalized_text(b.get('label')):
                    fail('vertices', 'vertex_label_mismatch', **prefix, expected=a['label'], actual=b.get('label'))
            ge, pe = g['edges'], p.get('edges')
            pe = pe if isinstance(pe, list) else []
            expected = _edge_counters(ge, {v['id']: v['id'] for v in gn}, gold=True)
            actual = _edge_counters(pe, mapping)
            for dimension in expected:
                missing, extra = expected[dimension]-actual[dimension], actual[dimension]-expected[dimension]
                if missing or extra:
                    fail(dimension, 'edge_evidence_mismatch', **prefix,
                         missing=_counter_rows(missing), extra=_counter_rows(extra))
            # Opposite directed edges are different ordered pairs. They can
            # coexist in a simple digraph and do not imply parallel edges.
            multi = any(n > 1 for n in expected['directions'].values()) or bool(expected['self_loops'])
            for field, target in [('directed', g['directed']), ('weighted', g['weighted']), ('multigraph', g.get('multigraph', multi))]:
                if type(p.get(field)) is not bool or p[field] != target:
                    fail('graph_types', 'graph_type_mismatch', **prefix, field=field, expected=target, actual=p.get(field))
        if prediction.get('recognition_status') not in ('complete', 'not_graph'):
            fail('completeness', 'document_not_complete', actual=prediction.get('recognition_status'))
        if gold and prediction.get('recognition_status') == 'not_graph':
            fail('completeness', 'graph_document_reported_as_non_graph')
        review = prediction.get('review')
        if not isinstance(review, dict) or type(review.get('required')) is not bool:
            fail('schema', 'missing_or_invalid_review_envelope')
            fail('completeness', 'review_status_not_explicit')
        if prediction.get('error') or prediction.get('cancelled') or (isinstance(review, dict) and review.get('required') is True):
            fail('completeness', 'document_reports_failure_or_review')
        text_field = 'question_text' if 'question_text' in reference else 'transcribed_text'
        text_ref_issues = reference_text_issues(reference)
        if text_ref_issues:
            dims['text'] = {'status': 'not_certified', 'issues': text_ref_issues}
        elif 'text' not in prediction or not isinstance(prediction['text'], str):
            dims['text'] = {'status': 'fail', 'issues': ['missing_prediction_text']}
        else:
            wanted, received = normalized_text(reference[text_field]), normalized_text(prediction['text'])
            dims['text'] = {'status': 'pass' if wanted == received else 'fail',
                            'issues': [] if wanted == received else ['text_mismatch'],
                            'expected_sha256': hashlib.sha256((wanted or '').encode()).hexdigest(),
                            'actual_sha256': hashlib.sha256(received.encode()).hexdigest()}
        diagnostics = prediction.get('diagnostics')
        text_evidence = diagnostics.get('text_evidence') if isinstance(diagnostics, dict) else None
        text_evidence_issues = []
        if not isinstance(text_evidence, dict) or type(text_evidence.get('complete')) is not bool:
            text_evidence_issues.append('missing_or_unknown_text_completeness')
            fail('schema', 'missing_or_unknown_text_completeness')
        elif text_evidence['complete'] is not True:
            text_evidence_issues.append('prediction_text_incomplete')
        if isinstance(text_evidence, dict):
            if text_evidence.get('visual_body_complete') is False:
                text_evidence_issues.append('visual_body_transcription_incomplete')
            if (text_evidence.get('source') == 'original_visual_transcription'
                    and text_evidence.get('visual_body_complete') is not True):
                text_evidence_issues.append('visual_body_completeness_not_explicit')
            if prediction.get('graph_display_version') == CURRENT_PIPELINE_VERSION:
                if text_evidence.get('second_pass_reviewed') is not True:
                    text_evidence_issues.append('second_pass_text_review_not_explicit')
                reconciliation = text_evidence.get('reconciliation')
                if not isinstance(reconciliation, dict) or not isinstance(reconciliation.get('issues'), list):
                    text_evidence_issues.append('text_reconciliation_evidence_missing')
                elif reconciliation['issues']:
                    text_evidence_issues.append('unresolved_text_reconciliation_issues')
                elif reconciliation.get('second_pass_reviewed') is False:
                    text_evidence_issues.append('text_reconciliation_review_conflict')
                correction = diagnostics.get('correction')
                if str(prediction.get('text') or '').strip() and (
                        not isinstance(correction, dict) or correction.get('status') != 'ok'):
                    text_evidence_issues.append('text_correction_not_verified')
        for field in ('body_complete', 'text_complete'):
            if field in prediction and prediction[field] is not True:
                text_evidence_issues.append(field+'_not_true')
        if text_evidence_issues:
            fail('completeness', 'text_not_certified_by_recognizer', details=text_evidence_issues)
            if dims['text']['status'] != 'not_certified':
                dims['text']['status'] = 'fail'
            dims['text']['issues'].extend(text_evidence_issues)
    dims['run_evidence'] = _run_evidence(run_evidence, reference or {}, prediction)
    dims['frontend'] = _frontend_evidence(frontend_evidence, reference or {}, prediction, run_evidence)
    structure = [dims[k]['status'] for k in STRUCTURE_DIMENSIONS+('schema',)]
    result['structure_status'] = 'not_certified' if ref_issues else 'fail' if 'fail' in structure else 'pass'
    statuses = [d['status'] for d in dims.values()]
    result['status'] = ('not_certified' if ref_issues else 'fail' if 'fail' in statuses
                        else 'pass' if all(s == 'pass' for s in statuses) else 'not_certified')
    return result
