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

from graph_pipeline_version import AGENT_PIPELINE_VERSION, EVIDENCE_PIPELINE_VERSION


@dataclass(frozen=True)
class EvaluationConfig:
    minimum_panel_iou: float = 0.30
    # Distance in units of the full original image diagonal, aspect corrected.
    maximum_vertex_distance: float = 0.035


STRUCTURE_DIMENSIONS = (
    'panels', 'vertices', 'endpoints', 'directions', 'multiplicity', 'self_loops',
    'weights', 'edge_labels', 'styles', 'edge_instances', 'graph_types',
)
# Keep this public name for the existing two-pass benchmark fixtures/callers.
# Agent execution has a separate contract; it must never inherit a two-send
# certificate by changing only a display version string.
CURRENT_PIPELINE_VERSION = EVIDENCE_PIPELINE_VERSION
EXECUTION_MODES = {'local': 'local_pipeline', 'http': 'http_ocr_response'}
FRONTEND_CHECKS = (
    'public_projection', 'panels', 'vertex_labels', 'graph_types', 'edge_instances',
    'edge_endpoints', 'directions', 'multiplicity', 'self_loops', 'weights',
    'edge_labels', 'styles', 'status', 'text', 'original_preview',
    'response_immutable', 'readonly', 'no_markup_injection',
    'source_unchanged', 'network_isolation',
)


def evaluation_scope(mode, *, http_status=None):
    """These tools certify components, never the actual application workflow.

    Even HTTP mode plus direct dialog replay does not exercise the browser's
    upload handler or certify /ocr dispatch, readiness and HTTP error behavior.
    Application evidence is intentionally unsupported until a separate real
    application harness exists; caller-supplied claims cannot enable it. A
    recorded HTTP response remains visible as observed but not app-certified.
    """
    known = isinstance(mode, str) and mode in EXECUTION_MODES
    scope = EXECUTION_MODES[mode] if known else 'unverified_execution'
    observed_http = mode == 'http' and type(http_status) is int and 100 <= http_status <= 599
    return {'execution_mode': mode if known else 'unknown', 'execution_scope': scope,
            'frontend_scope': 'response_dialog_replay',
            'certification_scope': scope+'_and_ui_replay',
            'application_status': 'not_certified' if observed_http else 'not_run',
            'application_certified_passes': 0,
            'http_response_observed': observed_http,
            'http_status': http_status if observed_http else None}


def _assessment_status(statuses):
    if not statuses:
        return 'not_run'
    return 'fail' if 'fail' in statuses else 'pass' if all(s == 'pass' for s in statuses) else 'not_certified'


def summarize_assessments(results, mode):
    """Keep scoped pass counts without promoting them to application passes."""
    http_responses = [r['http_status'] for r in results if r.get('http_response_observed') is True
                      and type(r.get('http_status')) is int]
    return {**evaluation_scope(mode),
            'application_status': 'not_certified' if http_responses else 'not_run',
            'http_response_observed': bool(http_responses),
            'http_response_count': len(http_responses),
            'http_status_counts': dict(Counter(str(status) for status in http_responses)),
            'status': 'fail' if any(r.get('status') == 'fail' for r in results) else 'not_certified',
            'status_counts': dict(Counter(r.get('status', 'not_certified') for r in results)),
            'certified_passes': 0,
            'pipeline_status': _assessment_status([r.get('pipeline_status', 'not_certified') for r in results]),
            'frontend_status': _assessment_status([r.get('frontend_status', 'not_run') for r in results]),
            'pipeline_ui_status': _assessment_status([r.get('pipeline_ui_status', 'not_certified') for r in results]),
            'pipeline_passes': sum(r.get('pipeline_status') == 'pass' for r in results),
            'frontend_passes': sum(r.get('frontend_status') == 'pass' for r in results),
            'pipeline_ui_passes': sum(r.get('pipeline_ui_status') == 'pass' for r in results),
            'structure_passes': sum(r.get('structure_status') == 'pass' for r in results)}


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


def _run_evidence_two_pass(evidence, reference, prediction=None):
    if not isinstance(evidence, dict):
        return {'status': 'not_certified', 'issues': ['missing_live_run_evidence']}
    issues, missing = [], []
    mode = evidence.get('mode')
    if not isinstance(mode, str) or mode not in EXECUTION_MODES:
        issues.append('unsupported_or_missing_execution_mode')
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
            'execution_scope': evaluation_scope(mode)['execution_scope'],
            'pipeline_contract': evidence.get('pipeline_contract')}


_AGENT_ROLES = frozenset(('page_vertices', 'body_text', 'body_review', 'connections', 'attributes', 'structure_review'))
_AGENT_REQUIRED_ROLES = frozenset(('page_vertices', 'body_text', 'connections', 'structure_review'))
_AGENT_TOOL_ROLES = {
    'image.local_evidence': _AGENT_ROLES-{'body_review'},
    'image.marker_proposals': {'page_vertices'},
    'image.marker_grounding': {'page_vertices'},
    'image.trace_candidates': {'connections'},
    'image.sknw_candidates': {'connections'},
    'image.review_views': _AGENT_ROLES,
    'image.focused_views': {'page_vertices', 'body_text', 'body_review', 'connections', 'structure_review'},
    'graph.stroke_validation': {'connections', 'attributes', 'structure_review'},
    'text.visual_reconciliation': {'body_text', 'structure_review'},
    'graph.structure_audit': {'structure_review'},
    'graph.adjacency_matrix': {'structure_review', 'solver'},
    'graph.walk_count': {'solver'}, 'graph.euler': {'solver'},
    'math.logic': {'solver'}, 'math.matrix': {'solver'},
}


def _sha256_string(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _agent_attempt_key(record):
    if (not isinstance(record, dict) or not isinstance(record.get('agent_role'), str)
            or record['agent_role'] not in _AGENT_ROLES):
        return None
    numbers = [record.get(k) for k in ('role_invocation', 'logical_call', 'attempt')]
    if any(type(value) is not int or value < 1 for value in numbers):
        return None
    return (record['agent_role'], *numbers)


def _agent_event_evidence(workflow, metrics, issues, missing):
    """Bind role sends to task history, including two owners of one repair round.

    Body repair is independent of graph repair. Two adjacent coordinator
    announcements can therefore authorize one body+connections/attributes
    round, not two rounds. Their actual owner calls must use the same revision.
    Optional body-only reads additionally bind their dependency digest. A
    cached scope can reuse a recorded outcome, never manufacture a new send.
    """
    events = workflow.get('events')
    if not isinstance(events, list) or not events:
        missing.append('agent_event_ledger_missing')
        return {}, {}, []
    starts, outcomes, recoveries = {}, {}, Counter()
    active, repair_groups = {}, []
    owner_counts = Counter()
    seen_invocations = Counter()
    body_scope_pending = None
    body_scopes, body_scope_digests, body_reviews = {}, set(), set()
    downstream = {
        'page_vertices': _AGENT_ROLES-{'body_text'},
        'body_text': {'body_text', 'body_review', 'structure_review'},
        'connections': {'connections', 'attributes', 'structure_review'},
        'attributes': {'attributes', 'structure_review'},
        'structure_review': {'structure_review'},
    }
    for position, event in enumerate(events, 1):
        if not isinstance(event, dict):
            issues.append('invalid_agent_event')
            continue
        if type(event.get('sequence')) is not int or event['sequence'] != position:
            issues.append('agent_event_sequence_invalid')
        role, status = event.get('role'), event.get('status')
        if not isinstance(role, str):
            issues.append('invalid_agent_event_role')
            continue
        if body_scope_pending is not None and role == 'body_review' and status not in ('scope_checked', 'started'):
            issues.append('body_review_scope_not_followed_by_start')
        if status == 'scope_checked':
            digest, revision = event.get('body_input_digest'), event.get('revision')
            if role != 'body_review':
                issues.append('body_review_scope_role_invalid')
                continue
            if body_scope_pending is not None:
                issues.append('body_review_scope_not_consumed')
            if not _sha256_string(digest) or type(revision) is not int or revision < 0:
                issues.append('body_review_scope_identity_invalid')
            elif digest in body_scope_digests:
                issues.append('body_review_repeated_input_digest')
            else:
                body_scope_digests.add(digest)
            body_scope_pending = {**event, '_position': position}
        elif status == 'scope_reused':
            prior = next(((key, scope) for key, scope in body_scopes.items()
                          if scope.get('body_input_digest') == event.get('body_input_digest')), None)
            if (role != 'body_review' or not _sha256_string(event.get('body_input_digest'))
                    or type(event.get('revision')) is not int
                    or type(event.get('source_request_revision')) is not int or prior is None):
                issues.append('body_review_reused_scope_unverified')
            elif (event['source_request_revision'] != prior[1]['revision']
                  or event['revision'] < prior[1]['revision']
                  or (prior[0] not in body_reviews
                      and outcomes.get(prior[0]) not in ('failed', 'proposal_rejected'))):
                issues.append('body_review_reused_scope_unverified')
        if status == 'targeted_review':
            owner, number, conflict_ids = event.get('target_role'), event.get('repair_round'), event.get('conflict_ids')
            if (role != 'coordinator' or not isinstance(event.get('target_role'), str)
                    or event['target_role'] not in downstream or
                    not isinstance(conflict_ids, list) or not conflict_ids
                    or any(not isinstance(x, str) or not x for x in conflict_ids)
                    or (isinstance(conflict_ids, list) and all(isinstance(x, str) for x in conflict_ids)
                        and len(set(conflict_ids)) != len(conflict_ids))):
                issues.append('unscoped_agent_repair')
            if type(number) is not int or number < 1 or number > 3:
                issues.append('agent_repair_sequence_invalid')
                continue
            if not repair_groups or number != repair_groups[-1]['number']:
                if number != len(repair_groups)+1:
                    issues.append('agent_repair_sequence_invalid')
                repair_groups.append({'number': number, 'owners': set(), 'starts': {},
                    'owner_revisions': {}, 'last_announcement': position,
                    'previous_revision': max((x['revision'] for x in starts.values()), default=-1)})
            else:
                if repair_groups[-1]['last_announcement'] != position-1:
                    issues.append('agent_repair_announced_after_work_started')
                repair_groups[-1]['last_announcement'] = position
            group = repair_groups[-1]
            if isinstance(owner, str) and owner in downstream:
                if owner in group['owners']:
                    issues.append('agent_repair_owner_repeated')
                group['owners'].add(owner)
                owner_counts[owner] += 1
                if len(group['owners']) > 1 and group['owners'] not in (
                        {'body_text', 'connections'}, {'body_text', 'attributes'}):
                    issues.append('agent_repair_owner_pair_invalid')
        if status == 'started':
            invocation, revision = event.get('invocation'), event.get('revision')
            if (role not in _AGENT_ROLES or type(invocation) is not int or invocation < 1 or
                    type(revision) is not int or revision < 0):
                issues.append('invalid_agent_invocation_event')
                continue
            key = (role, invocation)
            if role == 'body_review':
                if body_scope_pending is None:
                    missing.append('body_review_scope_missing')
                else:
                    if revision != body_scope_pending.get('revision'):
                        issues.append('body_review_scope_revision_mismatch')
                    body_scopes[key] = body_scope_pending
                    body_scope_pending = None
            group = repair_groups[-1] if repair_groups else None
            repair_round = group['number'] if group else 0
            seen_invocations[role] += 1
            if key in starts or invocation != seen_invocations[role]:
                issues.append('repeated_or_skipped_agent_invocation')
            if invocation > len(repair_groups)+1:
                issues.append('agent_invocation_without_targeted_review')
            if invocation > 1:
                previous = starts.get((role, invocation-1))
                if previous and revision <= previous.get('revision', revision):
                    issues.append('agent_rerun_without_new_revision')
                if group is None or previous is None or previous['_repair_round'] >= repair_round:
                    issues.append('agent_invocation_without_targeted_review')
            if group is not None:
                scope = set().union(*(downstream[owner] for owner in group['owners']))
                # A hard initial body repair can accompany the FIRST normal
                # attribute read; that read is not an attribute-owner retry.
                if group['owners'] == {'body_text'} and role == 'attributes' and invocation == 1:
                    scope.add('attributes')
                if role not in scope:
                    issues.append('agent_rerun_outside_targeted_scope')
                if role in group['starts']:
                    issues.append('agent_role_repeated_within_repair_round')
                group['starts'][role] = {'revision': revision, 'position': position}
                if revision <= group['previous_revision']:
                    issues.append('agent_repair_uses_stale_revision')
                if role in group['owners']:
                    group['owner_revisions'][role] = revision
            if not _sha256_string(event.get('request_digest')):
                missing.append('agent_role_request_digest_missing')
            starts[key] = {**event, '_position': position, '_repair_round': repair_round}
            active[role] = key
        elif status == 'reviewed' and role == 'body_review':
            key = active.get(role)
            scope = body_scopes.get(key)
            if key is None or scope is None or outcomes.get(key) != 'responded':
                issues.append('body_review_result_without_response')
            elif (type(event.get('revision')) is not int or event['revision'] != starts[key]['revision']
                  or event.get('body_input_digest') != scope.get('body_input_digest')):
                issues.append('body_review_result_scope_mismatch')
            if key in body_reviews:
                issues.append('body_review_result_repeated')
            if (type(event.get('body_complete')) is not bool
                    or type(event.get('conflict_count')) is not int or event['conflict_count'] < 0):
                issues.append('body_review_result_invalid')
            body_reviews.add(key)
        elif status in ('responded', 'network_recovery', 'failed', 'proposal_rejected'):
            key = active.get(role)
            if status in ('responded', 'network_recovery', 'failed'):
                explicit = (role, event.get('invocation'))
                if explicit != key:
                    issues.append('agent_response_invocation_mismatch')
            if key is None:
                issues.append('agent_event_without_started_role')
                continue
            if status == 'network_recovery':
                recoveries[key] += 1
            else:
                outcomes[key] = status
            if status == 'responded':
                if event.get('revision') != starts[key].get('revision'):
                    issues.append('agent_response_revision_mismatch')
                if not _sha256_string(event.get('response_digest')):
                    missing.append('agent_role_response_digest_missing')
    if body_scope_pending is not None:
        missing.append('body_review_scope_without_invocation')
    rounds = workflow.get('repair_rounds')
    if type(rounds) is not int or not 0 <= rounds <= 3 or rounds != len(repair_groups):
        issues.append('agent_repair_ledger_mismatch')
    recorded_owners = workflow.get('repair_role_counts')
    if (not isinstance(recorded_owners, dict)
            or any(type(value) is not int or not 1 <= value <= 3 for value in recorded_owners.values())
            or recorded_owners != dict(owner_counts)):
        issues.append('agent_repair_owner_count_mismatch')
    for group in repair_groups:
        for owner in group['owners']-set(group['starts']):
            missing.append('targeted_agent_owner_not_started:'+owner)
        revisions = set(group['owner_revisions'].values())
        if len(revisions) > 1:
            issues.append('agent_paired_owners_revision_mismatch')
        if revisions and any(x['revision'] < min(revisions) for x in group['starts'].values()):
            issues.append('agent_repair_downstream_revision_mismatch')
    count = workflow.get('network_recoveries')
    if (type(count) is not int or not 0 <= count <= 2 or count != sum(recoveries.values())
            or any(value > 1 for value in recoveries.values())):
        issues.append('agent_network_recovery_ledger_mismatch')
    groups = {}
    for metric in metrics:
        key = _agent_attempt_key(metric)
        if key:
            groups.setdefault(key[:2], []).append(metric)
    if set(starts) != set(groups):
        missing.append('agent_invocations_not_bound_to_actual_sends')
    latest = {role: max(key[1] for key in groups if key[0] == role) for role in {k[0] for k in groups}}
    for key, rows in groups.items():
        rows.sort(key=lambda row: row['logical_call'])
        if [row['logical_call'] for row in rows] != list(range(1, len(rows)+1)) or len(rows) > 2:
            issues.append('agent_hidden_or_reordered_retry')
        if len(rows)-1 != recoveries[key]:
            issues.append('agent_retry_without_recovery_event')
        start = starts.get(key)
        for row in rows:
            if start and row.get('state_revision') != start.get('revision'):
                issues.append('agent_metric_event_revision_mismatch')
        for row in rows[:-1]:
            retryable = row.get('status') == 'transport_failed' or row.get('http_status') in (429, 500, 502, 503, 504)
            if not retryable:
                issues.append('agent_retry_after_non_transport_result')
        last = rows[-1]
        successful = (last.get('http_status') == 200 and last.get('status') == 200
                      and last.get('finish_reason') == 'stop' and not last.get('partial_stream')
                      and not last.get('error') and not last.get('exception_type'))
        if key[0] == 'body_review':
            # This read-only role is optional. A disclosed failure can be
            # resolved by the mandatory final structure_review; it never
            # substitutes for that final accepted review. All sends/scopes
            # still require their ordinary independent transport evidence.
            if successful and outcomes.get(key) == 'responded':
                if key not in body_reviews:
                    missing.append('body_review_decoder_result_missing')
            elif outcomes.get(key) not in ('failed', 'proposal_rejected'):
                issues.append('agent_failed_invocation_not_disclosed')
            continue
        if key[1] == latest[key[0]]:
            if not successful or outcomes.get(key) != 'responded':
                issues.append('agent_final_role_response_not_successful')
        elif not successful and outcomes.get(key) not in ('failed', 'proposal_rejected'):
            issues.append('agent_failed_invocation_not_disclosed')
    return starts, outcomes, events


def _agent_tool_evidence(workflow, source_sha, issues, missing):
    records = workflow.get('tools')
    if not isinstance(records, list) or not records:
        missing.append('agent_tool_audit_missing')
        return
    seen, successes = set(), Counter()
    allowed_fields = {'call_id', 'tool', 'tool_version', 'role', 'source_sha256',
                      'input_digest', 'result_digest', 'elapsed_seconds', 'status',
                      'error_code', 'timeout_mode', 'handler_started', 'handler_finished'}
    for row in records:
        if not isinstance(row, dict):
            issues.append('invalid_agent_tool_audit')
            continue
        if set(row)-allowed_fields:
            issues.append('agent_tool_audit_has_unscoped_fields')
        cid, name, role = row.get('call_id'), row.get('tool'), row.get('role')
        if not isinstance(cid, str) or not cid or cid in seen:
            issues.append('agent_tool_call_identity_invalid')
        else:
            seen.add(cid)
        if (not isinstance(name, str) or name not in _AGENT_TOOL_ROLES
                or not isinstance(role, str) or role not in _AGENT_TOOL_ROLES[name]):
            issues.append('agent_tool_role_not_allowed')
        if row.get('source_sha256') != source_sha:
            issues.append('agent_tool_source_mismatch')
        if not isinstance(row.get('tool_version'), str) or not row['tool_version']:
            missing.append('agent_tool_version_missing')
        seconds = row.get('elapsed_seconds')
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
            missing.append('agent_tool_elapsed_time_missing')
        if row.get('timeout_mode') != 'cooperative':
            missing.append('agent_tool_deadline_contract_missing')
        if row.get('status') == 'success':
            if (not _sha256_string(row.get('input_digest')) or not _sha256_string(row.get('result_digest'))
                    or row.get('handler_started') is not True or row.get('handler_finished') is not True
                    or row.get('error_code') is not None):
                missing.append('agent_tool_success_not_bound_to_result')
            if isinstance(name, str) and isinstance(role, str):
                successes[(name, role)] += 1
        elif row.get('status') not in ('failed', 'timeout', 'denied') or not row.get('error_code'):
            issues.append('agent_tool_status_invalid')
    required = [('image.local_evidence', 'page_vertices'), ('image.marker_grounding', 'page_vertices'),
                ('image.trace_candidates', 'connections'), ('graph.stroke_validation', 'connections'),
                ('image.review_views', 'body_text'), ('image.review_views', 'structure_review'),
                ('text.visual_reconciliation', 'structure_review'), ('graph.structure_audit', 'structure_review')]
    for name, role in required:
        if not successes[(name, role)]:
            missing.append('required_agent_tool_not_successful:'+name+':'+role)


def _agent_attributes_needed(graphs):
    if not isinstance(graphs, list):
        return True
    for graph in graphs:
        if not isinstance(graph, dict) or not isinstance(graph.get('edges'), list):
            return True
        if graph['edges']:
            return True
    return False


def _run_evidence_agent(evidence, reference, prediction):
    """A role workflow needs observed sends; self-reported counters are insufficient."""
    if not isinstance(evidence, dict):
        return {'status': 'not_certified', 'issues': ['missing_live_run_evidence']}
    issues, missing = [], []
    mode = evidence.get('mode')
    if not isinstance(mode, str) or mode not in EXECUTION_MODES:
        issues.append('unsupported_or_missing_execution_mode')
    if type(evidence.get('document_requests')) is not int or evidence['document_requests'] != 1:
        issues.append('document_not_executed_exactly_once')
    if evidence.get('is_live') is not True:
        missing.append('not_a_verified_live_run')
    if any(evidence.get(k) is True for k in ('fixture_only', 'synthetic', 'mocked')):
        issues.append('synthetic_run_cannot_certify_live_agents')
    if evidence.get('source_unchanged') is False:
        issues.append('source_changed_during_request')
    elif evidence.get('source_unchanged') is not True:
        missing.append('source_snapshot_not_verified')
    source_sha = reference.get('sha256')
    if not _sha256_string(source_sha) or evidence.get('image_sha256') != source_sha:
        issues.append('original_image_digest_mismatch')
    snapshot = evidence.get('source_snapshot')
    if (not isinstance(snapshot, dict) or not snapshot.get('git_sha') or
            type(snapshot.get('dirty')) is not bool or not _sha256_string(snapshot.get('source_tree_sha256'))):
        missing.append('git_and_source_snapshot_missing')
    if mode == 'http' and evidence.get('server_source_verified') is not True:
        missing.append('http_server_source_identity_unverified')
    if evidence.get('pipeline_contract') != 'agent-tools':
        missing.append('agent_tools_execution_contract_missing')
    prediction = prediction if isinstance(prediction, dict) else {}
    if prediction.get('graph_display_version') != AGENT_PIPELINE_VERSION:
        missing.append('current_agent_pipeline_version_not_verified')
    diagnostics = prediction.get('diagnostics')
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    workflow = diagnostics.get('agent_workflow')
    workflow = workflow if isinstance(workflow, dict) else {}
    if workflow.get('engine') != 'langgraph' or workflow.get('version') != AGENT_PIPELINE_VERSION:
        missing.append('agent_workflow_identity_missing')
    task_id = workflow.get('task_id')
    if not isinstance(task_id, str) or not task_id or len(task_id) > 128:
        missing.append('agent_task_identity_missing')
    if workflow.get('source_sha256') != source_sha:
        issues.append('agent_workflow_source_mismatch')
    if workflow.get('provider_source') == 'injected':
        issues.append('injected_model_provider_cannot_certify_live_agents')
    elif workflow.get('provider_source') != 'configured_live':
        missing.append('configured_live_agent_provider_not_verified')
    conflicts = workflow.get('remaining_conflicts')
    if not isinstance(conflicts, list):
        missing.append('agent_remaining_conflicts_not_explicit')
    elif conflicts:
        issues.append('agent_has_remaining_conflicts')
    if workflow.get('complete') is not True:
        missing.append('agent_workflow_not_complete')
        if prediction.get('recognition_status') == 'complete':
            issues.append('complete_prediction_with_incomplete_agent_workflow')
    execution_id = evidence.get('execution_id')
    if not isinstance(execution_id, str) or not execution_id:
        missing.append('execution_identity_missing')
    started = finished = None
    try:
        first = datetime.fromisoformat(evidence['request_started_at'])
        last = datetime.fromisoformat(evidence['request_finished_at'])
        if first.tzinfo is None or last.tzinfo is None:
            raise ValueError('timezone_missing')
        started, finished = first.timestamp(), last.timestamp()
        if finished < started:
            issues.append('request_finished_before_start')
    except (KeyError, TypeError, ValueError, OverflowError):
        missing.append('request_time_not_verifiable')

    def check_time(row):
        stamp = row.get('started_at_unix')
        if type(stamp) not in (int, float) or not math.isfinite(stamp):
            missing.append('attempt_start_missing')
        elif started is not None and finished is not None and not started-1 <= stamp <= finished+1:
            issues.append('model_attempt_not_from_this_request')
        if row.get('execution_id') != execution_id or not execution_id:
            missing.append('attempt_execution_identity_unverified')

    metrics, text_metrics, transports, remote = [], [], [], []
    for field, destination in (('model_attempts', metrics), ('text_model_attempts', text_metrics),
                               ('transport_attempts', transports)):
        value = evidence.get(field)
        if not isinstance(value, list) or (field != 'text_model_attempts' and not value):
            missing.append(field+'_missing')
        elif any(not isinstance(row, dict) for row in value):
            issues.append('invalid_'+field)
        else:
            destination.extend(value)
    value = diagnostics.get('remote_metrics')
    if not isinstance(value, list) or not value:
        missing.append('agent_remote_metrics_missing')
    elif any(not isinstance(row, dict) for row in value):
        issues.append('invalid_agent_remote_metrics')
    else:
        remote = value
    sends, used, attempt_keys = {}, set(), set()
    for sent in transports:
        check_time(sent)
        tid = sent.get('transport_id')
        if not isinstance(tid, str) or not tid or tid in sends:
            issues.append('repeated_or_invalid_transport_identity')
        else:
            sends[tid] = sent
        if sent.get('provider') not in ('qwen', 'text'):
            issues.append('unscoped_model_transport')
        if type(sent.get('attempt')) is not int or sent['attempt'] != 1:
            issues.append('model_retry_or_unidentified_attempt')
        if sent.get('method') != 'POST' or not sent.get('host'):
            missing.append('transport_target_unverified')
        if not _sha256_string(sent.get('request_body_sha256')):
            missing.append('transport_payload_digest_missing')
    for group, rows in (('qwen', metrics), ('text', text_metrics)):
        for metric in rows:
            check_time(metric)
            if metric.get('provider') != group:
                issues.append('model_metric_in_wrong_ledger')
            if type(metric.get('attempt')) is not int or metric['attempt'] != 1:
                issues.append('model_retry_or_unidentified_attempt')
            if group == 'qwen':
                key = _agent_attempt_key(metric)
                if key is None or key in attempt_keys:
                    issues.append('agent_attempt_identity_invalid_or_repeated')
                else:
                    attempt_keys.add(key)
                if metric.get('task_id') != task_id or metric.get('source_sha256') != source_sha:
                    issues.append('agent_metric_task_or_source_mismatch')
                if metric.get('model') != 'qwen3-vl-plus':
                    issues.append('unexpected_vision_model')
                if metric.get('status') == 200:
                    returned = metric.get('returned_model')
                    if not isinstance(returned, str) or not (returned == 'qwen3-vl-plus' or returned.startswith('qwen3-vl-plus-')):
                        missing.append('returned_vision_model_unverified')
            else:
                model = metric.get('model')
                if not isinstance(model, str) or not model.startswith('deepseek-'):
                    issues.append('unexpected_text_correction_model')
                if type(metric.get('logical_call')) is not int or metric['logical_call'] != 1:
                    issues.append('text_correction_single_send_budget_exceeded')
            tid = metric.get('transport_id')
            sent = sends.get(tid) if isinstance(tid, str) else None
            if sent is None:
                missing.append('model_metric_has_no_observed_send')
                continue
            if tid in used:
                issues.append('multiple_metrics_for_one_transport')
            used.add(tid)
            if metric.get('status') == 200 and (sent.get('http_status') != 200 or sent.get('exception_type')):
                issues.append('successful_metric_has_failed_transport')
            fields = ('provider', 'logical_call', 'attempt', 'model', 'http_status', 'execution_id')
            if group == 'qwen':
                fields += ('agent_role', 'role_invocation', 'state_revision', 'task_id', 'source_sha256')
            for field in fields:
                if metric.get(field) != sent.get(field):
                    issues.append('provider_transport_mismatch:'+field)
            if group == 'qwen':
                images = metric.get('image_sha256')
                if (not _sha256_string(metric.get('prompt_sha256')) or not isinstance(images, list)
                        or not images or not all(_sha256_string(x) for x in images)):
                    missing.append('vision_input_identity_missing')
                elif metric['prompt_sha256'] != sent.get('prompt_sha256') or images != sent.get('image_sha256'):
                    issues.append('provider_transport_input_mismatch')
                if isinstance(images, list) and len(images) > 5:
                    issues.append('agent_vision_image_budget_exceeded')
            stamp, sent_at, duration = metric.get('started_at_unix'), sent.get('started_at_unix'), metric.get('seconds')
            if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
                missing.append('model_attempt_duration_missing')
            elif type(stamp) in (int, float) and type(sent_at) in (int, float) and not stamp-.1 <= sent_at <= stamp+duration+.1:
                issues.append('transport_outside_provider_call')
    if set(sends)-used:
        missing.append('observed_send_has_no_provider_metric')
    qwen_sends = [x for x in transports if x.get('provider') == 'qwen']
    text_sends = [x for x in transports if x.get('provider') == 'text']
    count, maximum = workflow.get('actual_remote_sends'), workflow.get('max_remote_calls')
    if (type(count) is not int or count != len(metrics) or count != len(remote) or count != len(qwen_sends)):
        issues.append('agent_actual_send_count_mismatch')
    if type(maximum) is not int or not 4 <= maximum <= 24 or (type(count) is int and count > maximum):
        issues.append('agent_remote_send_budget_invalid')
    if len(text_metrics) > 1 or len(text_sends) > 1:
        issues.append('text_correction_single_send_budget_exceeded')
    role_counts = Counter(x.get('agent_role') for x in metrics if isinstance(x.get('agent_role'), str))
    recorded_counts = workflow.get('role_sends')
    if (not isinstance(recorded_counts, dict) or any(type(v) is not int or v <= 0 for v in recorded_counts.values())
            or recorded_counts != dict(role_counts)):
        issues.append('agent_role_send_count_mismatch')
    if [row.get('send_sequence') for row in remote] != list(range(1, len(remote)+1)):
        issues.append('agent_remote_sequence_invalid')
    by_key = {_agent_attempt_key(row): row for row in metrics if _agent_attempt_key(row) is not None}
    compare_fields = ('provider', 'model', 'logical_call', 'attempt', 'agent_role', 'role_invocation',
                      'state_revision', 'task_id', 'source_sha256', 'send_sequence', 'http_status', 'status',
                      'finish_reason', 'prompt_sha256', 'image_sha256', 'started_at_unix', 'seconds',
                      'returned_model', 'partial_stream')
    for row in remote:
        other = by_key.get(_agent_attempt_key(row))
        if other is None or any(row.get(key) != other.get(key) for key in compare_fields):
            issues.append('agent_response_remote_ledger_mismatch')
    revision = workflow.get('state_revision')
    if (type(revision) is not int or revision < 0 or any(
            type(row.get('state_revision')) is not int or not 0 <= row['state_revision'] <= revision
            for row in remote)):
        issues.append('agent_state_revision_invalid')
    starts, outcomes, events = _agent_event_evidence(workflow, metrics, issues, missing)
    required_roles = set(_AGENT_REQUIRED_ROLES)
    attributes_needed = _agent_attributes_needed(prediction.get('graph_structures'))
    if attributes_needed:
        required_roles.add('attributes')
        connection_starts = [value for (role, _), value in starts.items() if role == 'connections']
        attribute_starts = [value for (role, _), value in starts.items() if role == 'attributes']
        if connection_starts and attribute_starts:
            connection, attribute = connection_starts[-1], attribute_starts[-1]
            if (attribute['_position'] <= connection['_position']
                    or attribute['revision'] <= connection['revision']):
                issues.append('agent_attributes_not_current_after_connections')
    elif not role_counts['attributes'] and not any(
            event.get('role') == 'attributes' and event.get('status') == 'skipped'
            and event.get('reason') == 'no_edges_to_read' for event in events if isinstance(event, dict)):
        missing.append('optional_attribute_role_skip_not_explained')
    for role in required_roles:
        if not role_counts[role]:
            missing.append('required_agent_role_not_executed:'+role)
    reviews = [e for e in events if isinstance(e, dict) and e.get('role') == 'structure_review' and e.get('status') == 'reviewed']
    if (not reviews or reviews[-1].get('verdict') != 'accept'
            or type(reviews[-1].get('conflict_count')) is not int or reviews[-1]['conflict_count'] != 0):
        missing.append('independent_agent_review_not_accepted')
    elif reviews[-1].get('revision') != revision:
        issues.append('agent_final_review_is_stale')
    _agent_tool_evidence(workflow, source_sha, issues, missing)
    correction = diagnostics.get('correction')
    correction = correction if isinstance(correction, dict) else {}
    if correction.get('status') == 'ok' and str(prediction.get('text') or '').strip():
        if len(text_metrics) != 1 or len(text_sends) != 1:
            missing.append('claimed_text_correction_has_no_observed_call')
        elif (text_metrics[0].get('status') != 200 or text_metrics[0].get('http_status') != 200
              or text_metrics[0].get('finish_reason') != 'stop' or text_sends[0].get('exception_type')):
            issues.append('claimed_text_correction_not_successful')
    elif str(prediction.get('text') or '').strip() and prediction.get('text') != prediction.get('raw_ocr_text'):
        issues.append('unverified_agent_text_changed_after_visual_review')
    return {'status': 'fail' if issues else 'not_certified' if missing else 'pass',
            'issues': sorted(set(issues)), 'missing_evidence': sorted(set(missing)),
            'qwen_sends': len(qwen_sends), 'text_sends': len(text_sends),
            'task_id': task_id, 'execution_scope': evaluation_scope(mode)['execution_scope'],
            'pipeline_contract': evidence.get('pipeline_contract')}


def _run_evidence(evidence, reference, prediction=None):
    diagnostics = prediction.get('diagnostics') if isinstance(prediction, dict) else None
    agent_response = (isinstance(prediction, dict) and prediction.get('graph_display_version') == AGENT_PIPELINE_VERSION)
    agent_response = agent_response or isinstance(diagnostics, dict) and 'agent_workflow' in diagnostics
    if agent_response or isinstance(evidence, dict) and evidence.get('pipeline_contract') == 'agent-tools':
        return _run_evidence_agent(evidence, reference, prediction)
    return _run_evidence_two_pass(evidence, reference, prediction)


def _frontend_evidence(evidence, reference, prediction, run_evidence):
    if not isinstance(evidence, dict) or evidence.get('status') == 'not_run':
        return {'status': 'not_run', 'issues': ['actual_browser_render_not_checked']}
    if evidence.get('status') == 'fail':
        return {'status': 'fail', 'issues': ['actual_browser_render_failed']}
    if evidence.get('kind') != 'original_response' or evidence.get('fixture_only') is True:
        return {'status': 'not_certified', 'issues': ['fixture_or_unbound_browser_run_cannot_certify_original']}
    if evidence.get('frontend_scope') != 'response_dialog_replay':
        return {'status': 'not_certified', 'issues': ['frontend_replay_scope_missing']}
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
    expected_scope = evaluation_scope(run.get('mode'))
    if any(evidence.get(key) != expected_scope[key]
           for key in ('execution_mode', 'execution_scope', 'certification_scope')):
        issues.append('browser_execution_scope_mismatch')
    browser_source = evidence['source_snapshot']
    if any(browser_source.get(key) != snapshot.get(key)
           for key in ('git_sha', 'dirty', 'source_tree_sha256')):
        issues.append('browser_full_source_snapshot_mismatch')
    return {'status': 'fail' if issues else 'pass', 'issues': issues,
            'contract': 'original_preview_and_text_cards', 'artifact_paths': artifacts}


def evaluate_prediction(reference, prediction, *, run_evidence=None, frontend_evidence=None, config=None):
    """Strict first-result evaluation with separately visible evidence gates.

    A pipeline/UI pass checks original text, completeness, source/attempts and
    actual dialog rendering. This harness does not certify actual /ocr routing,
    upload handling, HTTP status or readiness. Local application_status stays
    not_run; observed HTTP responses remain not_certified for full application.
    """
    config = config or EvaluationConfig()
    if not 0 < config.minimum_panel_iou <= 1 or not 0 < config.maximum_vertex_distance < 1:
        raise ValueError('Invalid evaluation tolerances')
    ref_issues = reference_issues(reference)
    dims = {name: {'status': 'pass', 'issues': []} for name in STRUCTURE_DIMENSIONS+('schema', 'completeness')}
    mode = run_evidence.get('mode') if isinstance(run_evidence, dict) else None
    http_status = run_evidence.get('http_status') if isinstance(run_evidence, dict) else None
    result = {'schema_version': 2, **evaluation_scope(mode, http_status=http_status),
              'status': 'not_certified', 'pipeline_status': 'not_certified',
              'frontend_status': 'not_run', 'pipeline_ui_status': 'not_certified',
              'image_id': (reference or {}).get('id', (reference or {}).get('image_id')),
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
            if prediction.get('graph_display_version') in (EVIDENCE_PIPELINE_VERSION, AGENT_PIPELINE_VERSION):
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
                if (prediction.get('graph_display_version') == EVIDENCE_PIPELINE_VERSION
                        and str(prediction.get('text') or '').strip() and (
                        not isinstance(correction, dict) or correction.get('status') != 'ok')):
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
    result['pipeline_status'] = ('not_certified' if ref_issues else
                                 _assessment_status([d['status'] for key, d in dims.items() if key != 'frontend']))
    result['frontend_status'] = dims['frontend']['status']
    result['pipeline_ui_status'] = ('not_certified' if ref_issues else
                                    _assessment_status([d['status'] for d in dims.values()]))
    # Do not turn a component certificate into an unqualified application pass.
    result['status'] = 'fail' if result['pipeline_ui_status'] == 'fail' else 'not_certified'
    return result
