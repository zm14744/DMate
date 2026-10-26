"""Conservative colour correction from caller-owned, original RGB measurements.

This is not a graph detector or an acceptance gate.  It may change only the
``color`` of an existing, uniquely associated edge.  Missing or weak candidates
never imply a missing/incorrect edge.  The caller must discard geometry after
reassigning its graph/vertex identities; model-produced evidence is not an
input to this function.
"""
from __future__ import annotations

import colorsys
import copy
import math
from collections import Counter, defaultdict

from graph_semantic_geometry import MAX_CANDIDATES
from graph_semantic_schema import MAX_EDGES, MAX_GRAPHS, MAX_VERTICES, _identifier
from graph_semantic_sources import _attributes


VERSION = '2026-10-26-semantic-original-color-v1'
MIN_SAMPLES = 64
MIN_DOMINANT_FRACTION = .90
MAX_COMPETING_FRACTION = .02
MIN_SATURATION = .65
MIN_VALUE = .35
MIN_CHROMA = 80


def _check(budget):
    if budget is not None:
        budget.check()


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _pair(row):
    if not isinstance(row, dict):
        return None
    left, right = _identifier(row.get('from')), _identifier(row.get('to'))
    return tuple(sorted((left, right))) if left is not None and right is not None else None


def _rgb_name(rgb):
    """Narrow, saturated hue bands; grey, near-black and boundary hues abstain.

    Output names are a subset of the existing semantic source colour vocabulary.
    Cyan/magenta are deliberately not coerced to the nearest supported colour.
    """
    hue, saturation, value = colorsys.rgb_to_hsv(*(x / 255 for x in rgb))
    if saturation < MIN_SATURATION or value < MIN_VALUE or max(rgb) - min(rgb) < MIN_CHROMA:
        return None, False
    hue *= 360
    if hue <= 12 or hue >= 348:
        return 'red', True
    for lower, upper, name in ((22, 38, 'orange'), (48, 68, 'yellow'),
                               (88, 145, 'green'), (215, 255, 'blue'),
                               (268, 288, 'purple')):
        if lower <= hue <= upper:
            return name, True
    return None, True


def _measurement(value):
    if not isinstance(value, dict) or value.get('status') != 'measured':
        return None, 'unmeasured', {}
    if value.get('source') != 'unmodified_working_rgb':
        return None, 'not_original_rgb', {}
    samples = value.get('sample_count')
    if type(samples) is not int or not MIN_SAMPLES <= samples <= 2048:
        return None, 'insufficient_or_invalid_samples', {}
    rows = value.get('colors')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 3:
        return None, 'invalid_color_buckets', {}
    totals, saturated_unknown, total = defaultdict(float), 0., 0.
    for row in rows:
        if not isinstance(row, dict):
            return None, 'invalid_color_buckets', {}
        rgb, fraction = row.get('rgb'), row.get('fraction')
        if (not isinstance(rgb, (list, tuple)) or len(rgb) != 3
                or any(type(x) is not int or not 0 <= x <= 255 for x in rgb)
                or not _number(fraction) or not 0 <= fraction <= 1):
            return None, 'invalid_color_buckets', {}
        name, saturated = _rgb_name(rgb)
        total += fraction
        if name is not None:
            totals[name] += fraction
        elif saturated:
            saturated_unknown += fraction
    # Up to three fractions are independently rounded to four decimal places.
    if total > 1.0002:
        return None, 'invalid_fraction_total', {}
    measured = {'sample_count': samples, 'colors': copy.deepcopy(rows)}
    if not totals:
        return None, 'no_clear_saturated_color', measured
    name, fraction = max(totals.items(), key=lambda row: row[1])
    competing = sum(v for k, v in totals.items() if k != name) + saturated_unknown
    measured.update(color=name, dominant_fraction=round(fraction, 4),
                    competing_fraction=round(competing, 4))
    if competing > MAX_COMPETING_FRACTION + 1e-9:
        return None, 'mixed_or_ambiguous_hue', measured
    if fraction + 1e-9 < MIN_DOMINANT_FRACTION:
        return None, 'low_saturated_fraction', measured
    return name, None, measured


def _endpoint_problem(row, ids, marker_owners, vertex_markers, repeated_instances):
    if row.get('unmapped') is not False:
        return 'unmapped_endpoints'
    if row.get('source') not in ('opencv', 'sknw'):
        return 'unknown_local_measurement_source'
    instance = row.get('instance_id')
    if not isinstance(instance, str) or not instance or instance in repeated_instances:
        return 'missing_or_duplicate_candidate_identity'
    endpoints = row.get('endpoints')
    if not isinstance(endpoints, list) or len(endpoints) != 2:
        return 'missing_endpoint_associations'
    for key, endpoint in zip(('from', 'to'), endpoints):
        if not isinstance(endpoint, dict):
            return 'missing_endpoint_associations'
        vid, marker = _identifier(endpoint.get('vertex_id')), endpoint.get('marker_id')
        if (vid not in ids or vid != _identifier(row.get(key))
                or endpoint.get('association') != 'unique_close_marker'
                or not isinstance(marker, str) or not marker):
            return 'non_unique_endpoint_association'
        if len(marker_owners[marker]) != 1 or len(vertex_markers[vid]) != 1:
            return 'conflicting_marker_associations'
    route = row.get('path_hint')
    if (row.get('coordinate_space') != 'original_1000'
            or not isinstance(route, list) or not 2 <= len(route) <= 24
            or any(not isinstance(p, (list, tuple)) or len(p) != 2
                   or any(not _number(x) or not 0 <= x <= 1000 for x in p) for p in route)
            or all(tuple(p) == tuple(route[0]) for p in route)):
        return 'missing_or_invalid_measured_path'
    return None


def reconcile_edge_colors(document, geometry, *, budget=None):
    """Return ``(deep_copy_of_document, audit)``; change existing colours only.

    An edge ID is optional: audit entries always include graph/edge list indexes.
    Endpoint pairs match without direction, since RGB has no direction meaning.
    Parallel instances (including opposite arrows) remain unchanged unless a
    future implementation can prove their separate physical correspondence.
    Cancellation propagates; inadequate tool evidence merely causes abstention.
    """
    _check(budget)
    if not isinstance(document, dict):
        raise TypeError('expected_semantic_document')
    result = copy.deepcopy(document)
    audit = {'version': VERSION, 'status': 'unchanged', 'source_sha256': None,
             'changed_edges': 0, 'changes': [], 'decisions': [],
             'acceptance_required': False, 'graph_content_certified': False,
             'absence_is_not_negative_evidence': True,
             'thresholds': {'minimum_samples': MIN_SAMPLES,
                            'minimum_dominant_fraction': MIN_DOMINANT_FRACTION,
                            'maximum_competing_fraction': MAX_COMPETING_FRACTION}}

    def abstain(reason):
        audit['reason'] = reason
        return result, audit

    graphs = result.get('graphs')
    if not isinstance(graphs, list) or len(graphs) > MAX_GRAPHS:
        return abstain('invalid_document_inventory')
    if not isinstance(geometry, dict) or not isinstance(geometry.get('graphs'), list):
        return abstain('local_geometry_unavailable')
    source = geometry.get('source_sha256')
    audit['source_sha256'] = source if isinstance(source, str) and len(source) == 64 else None
    expected_sources = (getattr(budget, 'source_sha256', None), document.get('source_sha256'))
    if any(expected is not None and expected != source for expected in expected_sources):
        return abstain('source_identity_mismatch')
    local_graphs = geometry['graphs']
    if (len(local_graphs) > MAX_GRAPHS
            or any(not isinstance(g, dict) or not isinstance(g.get('candidates'), list)
                   for g in local_graphs)
            or sum(len(g['candidates']) for g in local_graphs) > MAX_CANDIDATES):
        return abstain('invalid_or_unbounded_geometry')
    local_issues = geometry.get('issues', [])
    if not isinstance(local_issues, list):
        return abstain('invalid_geometry_diagnostics')
    if any(isinstance(i, dict) and i.get('code') == 'geometry_candidate_capacity'
           for i in local_issues):
        return abstain('candidate_inventory_truncated')
    local_by_id = defaultdict(list)
    marker_owners = defaultdict(set)
    instance_counts = Counter()
    for group in local_graphs:
        _check(budget)
        gid = _identifier(group.get('graph_id'))
        local_by_id[gid].append(group)
        for row in group['candidates']:
            if not isinstance(row, dict):
                continue
            instance = row.get('instance_id')
            if isinstance(instance, str):
                instance_counts[instance] += 1
            for endpoint in row.get('endpoints', []) if isinstance(row.get('endpoints'), list) else []:
                if isinstance(endpoint, dict):
                    marker, vid = endpoint.get('marker_id'), _identifier(endpoint.get('vertex_id'))
                    if isinstance(marker, str) and marker and vid is not None:
                        marker_owners[marker].add((gid, vid))
    repeated = {key for key, count in instance_counts.items() if count > 1}
    graph_counts = Counter(_identifier(g.get('id')) for g in graphs if isinstance(g, dict))
    for graph_index, graph in enumerate(graphs):
        _check(budget)
        if not isinstance(graph, dict):
            continue
        gid = _identifier(graph.get('id'))
        vertices, edges = graph.get('vertices'), graph.get('edges')
        if (not isinstance(vertices, list) or len(vertices) > MAX_VERTICES
                or not isinstance(edges, list) or len(edges) > MAX_EDGES):
            continue
        ids = [_identifier(v.get('id')) if isinstance(v, dict) else None for v in vertices]
        graph_problem = None
        if gid is None or graph_counts[gid] != 1 or None in ids or len(set(ids)) != len(ids):
            graph_problem = 'ambiguous_document_identity'
        elif len(local_by_id.get(gid, [])) > 1:
            graph_problem = 'ambiguous_geometry_graph_identity'
        candidates = local_by_id[gid][0]['candidates'] if len(local_by_id.get(gid, [])) == 1 else []
        by_pair, vertex_markers = defaultdict(list), defaultdict(set)
        for row in candidates:
            pair = _pair(row)
            if pair is not None:
                by_pair[pair].append(row)
            if isinstance(row, dict) and isinstance(row.get('endpoints'), list):
                for endpoint in row['endpoints']:
                    if isinstance(endpoint, dict):
                        vid, marker = _identifier(endpoint.get('vertex_id')), endpoint.get('marker_id')
                        if vid is not None and isinstance(marker, str) and marker:
                            vertex_markers[vid].add(marker)
        pair_counts = Counter(_pair(e) for e in edges)
        for edge_index, edge in enumerate(edges):
            _check(budget)
            if not isinstance(edge, dict):
                continue
            pair = _pair(edge)
            decision = {'graph_id': gid, 'graph_index': graph_index, 'edge_index': edge_index,
                        'edge_id': _identifier(edge.get('id')), 'status': 'abstained'}
            audit['decisions'].append(decision)
            reason = graph_problem
            if not reason and (pair is None or not set(pair) <= set(ids)):
                reason = 'unknown_document_endpoints'
            rows = by_pair.get(pair, [])
            if not reason and not rows:
                reason = 'no_associated_path'
            if not reason and (pair_counts[pair] != 1 or edge.get('multiplicity', 1) != 1
                               or edge.get('parallel_count', 1) != 1):
                reason = 'parallel_instance_not_uniquely_bound'
            if reason:
                decision['reason'] = reason
                continue
            evidence, colors = [], []
            for row in rows:
                problem = _endpoint_problem(row, ids, marker_owners, vertex_markers, repeated)
                color, measurement_problem, measured = _measurement(row.get('color_measurement'))
                evidence.append({'instance_id': (row['instance_id'][:160]
                                     if isinstance(row.get('instance_id'), str) else None),
                                 'source': row.get('source') if row.get('source') in ('opencv', 'sknw') else None,
                                 'reason': problem or measurement_problem, **measured})
                if problem or measurement_problem:
                    reason = 'associated_path_not_conclusive'
                colors.append(color)
            decision['evidence'] = evidence
            if reason:
                decision['reason'] = reason
                continue
            if len(set(colors)) != 1:
                decision['reason'] = 'associated_paths_disagree'
                continue
            color = colors[0]
            normalized, _ = _attributes({'color': edge.get('color')})
            if normalized.get('color') == color:
                decision.update(status='consistent', color=color)
                continue
            before = copy.deepcopy(edge.get('color'))
            edge['color'] = color
            decision.update(status='corrected', before=before, after=color)
            audit['changes'].append(copy.deepcopy(decision))
            audit['changed_edges'] += 1
    _check(budget)
    if audit['changed_edges']:
        audit['status'] = 'corrected'
    return result, audit


__all__ = ['reconcile_edge_colors']
