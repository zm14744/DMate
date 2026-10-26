"""Registered, source-bound image tools used by DMate's role workflow."""
from __future__ import annotations

import copy
import hashlib
import io
import math
import time

from dmate_tool_registry import ToolContext, ToolRegistry, ToolSpec


_OBJECT = {'type': 'object'}
_EMPTY = {'type': 'object', 'properties': {}, 'additionalProperties': False}
_GRAPHS = {'type': 'object', 'required': ['graphs'], 'additionalProperties': False,
           'properties': {'graphs': {'type': 'array', 'maxItems': 48,
                                    'items': {'type': 'object'}}}}
_ROLES = ('page_vertices', 'body_text', 'connections', 'attributes', 'structure_review')


def _native_trace_measurements(candidates):
    """Make the tracer's finite numeric fit diagnostics JSON-native.

    NumPy amplitude grids can leave numpy.floating scalars in curve_fit. Only
    these measured scalar fields are normalized; paths, support decisions and
    arbitrary objects still go through the registry's strict JSON/capacity
    checks. This is deliberately not a general-purpose object serializer.
    """
    import numpy as np

    result = copy.deepcopy(candidates)
    for rows in result.values():
        for row in rows:
            evidence = row.get('connector_evidence')
            fit = evidence.get('curve_fit') if isinstance(evidence, dict) else None
            if not isinstance(fit, dict):
                continue
            for field in ('initial_bend_pixels', 'fitted_bend_pixels',
                          'ridge_coverage', 'fit_cost'):
                value = fit.get(field)
                if isinstance(value, np.floating) and np.isfinite(value):
                    native = float(value)
                    if math.isfinite(native):
                        fit[field] = native
    return result


def build_image_tools(document, text_result, layout, budget):
    """The context holds pixels; JSON tools expose only measured results/refs."""
    from graph_evidence_pipeline import apply_topology, collect_candidates
    from graph_marker_grounding import ground_nodes, marker_proposals
    from graph_panel_context import layout_hints
    from graph_review_views import build_review_sheet
    from graph_focus_views import build_focused_views
    from graph_text_evidence import text_hints
    from graph_agent_roles import reconcile_role_text

    context = ToolContext(source_sha256=budget.source_sha256,
                          data={'document': document, 'text_result': text_result or {},
                                'layout': layout or [], 'images': {}, 'marker_cache': {}},
                          deadline_monotonic=budget.deadline)
    registry = ToolRegistry()

    def register(name, description, schema, roles, handler, *, timeout=15,
                 version='2026-10-26-v2'):
        registry.register(ToolSpec(name=name, version=version,
            description=description, input_schema=schema, output_schema=_OBJECT,
            allowed_roles=tuple(roles), source_required=True, timeout_seconds=timeout), handler)

    def local_evidence(args, *, context):
        return {'layout_hints': layout_hints(context.data['layout']),
                'text_hints': text_hints(context.data['text_result']),
                'quality': copy.deepcopy(document.quality),
                'diagnostics': list(document.diagnostics)}

    register('image.local_evidence', 'Read the existing local OCR and layout evidence, without reloading models.',
             _EMPTY, _ROLES, local_evidence)

    def marker_hints(args, *, context):
        proposals = marker_proposals(document)
        context.data['marker_cache']['proposals'] = proposals
        return {'version': proposals['version'], 'source_sha256': context.source_sha256,
                'coordinate_space': 'original_1000', 'proposal_only': True,
                'candidates': [{'id': row['id'], 'x': round(row['x']*1000, 3),
                                'y': round(row['y']*1000, 3), 'kind': row['kind'],
                                'radius_x': round(row['radius_pixels']/max(document.work_size[0]-1, 1)*1000, 3),
                                'radius_y': round(row['radius_pixels']/max(document.work_size[1]-1, 1)*1000, 3),
                                'confidence': round(row['confidence'], 4),
                                'evidence_source': row['evidence'].get('source'),
                                'advisory_only': row.get('advisory_only', False),
                                'advisory_reason': row.get('advisory_reason'),
                                'connected_stroke': row['connected_stroke']}
                               for row in proposals['items']],
                'limits': copy.deepcopy(proposals['limits'])}

    register('image.marker_proposals', 'Measure bounded original-pixel marker hypotheses before visual vertex inventory.',
             _EMPTY, ('page_vertices',), marker_hints)

    def markers(args, *, context):
        graphs = ground_nodes(document, copy.deepcopy(args['graphs']),
                              proposals=context.data['marker_cache'].get('proposals'))
        return {'graphs': graphs, 'proposal_only': True}

    register('image.marker_grounding', 'Attach existing vertex identities to unique original-pixel markers.',
             _GRAPHS, ('page_vertices',), markers)

    def trace(args, *, context):
        graphs = copy.deepcopy(args['graphs'])
        candidates, diagnostics = collect_candidates(document, graphs)
        return {'graphs': graphs, 'candidates': _native_trace_measurements(candidates),
                'diagnostics': diagnostics,
                'proposal_only': True}

    register('image.trace_candidates', 'Trace original-source paths; candidates require later visual and pixel review.',
             _GRAPHS, ('connections',), trace, timeout=30, version='2026-10-26-v3')

    def skeleton(args, *, context):
        from graph_sknw_plugin import suggest_candidates
        candidates, diagnostics = suggest_candidates(document, copy.deepcopy(args['graphs']),
                max_candidates=160, deadline=min(budget.deadline, time.monotonic()+18))
        return {'candidates': candidates, 'diagnostics': diagnostics, 'proposal_only': True}

    register('image.sknw_candidates', 'Use sknw MultiGraph skeleton chains as additional source-path proposals.',
             _GRAPHS, ('connections',), skeleton, timeout=20)

    def views(args, *, context):
        hints = text_hints(context.data['text_result'])
        sheet, tiles, text_tiles, notes = build_review_sheet(document.original, args['graphs'], hints=hints,
                                                            allow_empty=not args['graphs'])
        stream = io.BytesIO()
        sheet.save(stream, format='PNG')
        reference = hashlib.sha256(stream.getvalue()).hexdigest()
        context.data['images'][reference] = sheet
        # These refs can be consumed by concurrent roles. The bounded upload
        # owns the cache; release it with the context, never evict an active ref
        # because another role just produced additional focus crops.
        return {'image_ref': reference, 'coordinate_space': 'original_1000',
                'review_tiles': tiles, 'text_review_tiles': text_tiles,
                'diagnostics': notes, 'source_pixels_only': True}

    register('image.review_views', 'Build original-pixel graph/text crops with explicit full-image coordinates.',
             _GRAPHS, _ROLES, views)

    def focused(args, *, context):
        images, mappings, diagnostics = build_focused_views(
            document.original, args['graphs'], args['issues'],
            hints=context.data.get('hints'), check_deadline=context.check_deadline)
        references, output_maps = [], []
        for crop, mapping in zip(images, mappings):
            context.check_deadline()
            stream = io.BytesIO()
            crop.save(stream, format='PNG')
            reference = hashlib.sha256(stream.getvalue()).hexdigest()
            context.data['images'][reference] = crop
            references.append(reference)
            output_maps.append({**mapping, 'image_ref': reference})
        return {'image_refs': references, 'focused_views': output_maps,
                'coordinate_space': 'original_1000', 'source_sha256': context.source_sha256,
                'source_pixels_only': True, 'diagnostics': diagnostics}

    register('image.focused_views', 'Crop original pixels addressed by verified text/edge/vertex IDs; never render answers.',
             {'type': 'object', 'required': ['graphs', 'issues'], 'additionalProperties': False,
              'properties': {'graphs': _GRAPHS['properties']['graphs'],
                             'issues': {'type': 'array', 'maxItems': 128, 'items': _OBJECT}}},
             ('body_text', 'connections', 'structure_review'), focused,
             version='2026-10-26-v4')

    def validate(args, *, context):
        graphs, issues = apply_topology(args['response'], context.data['inventory'],
                    context.data['candidates'], document,
                    panels_complete=context.data.get('panels_complete') is True)
        return {'graphs': graphs, 'issues': issues}

    register('graph.stroke_validation', 'Recheck endpoint identity, original ink, multiplicity and source coverage.',
             {'type': 'object', 'properties': {'response': _OBJECT},
              'required': ['response'], 'additionalProperties': False},
             ('connections', 'attributes', 'structure_review'), validate, timeout=25)

    def reconcile(args, *, context):
        body, complete, audit = reconcile_role_text(args['first'], args['reviewed'],
                         context.data['hints'], context.data['draft_graphs'])
        return {'body_text': body, 'body_complete': complete, 'body_audit': audit}

    register('text.visual_reconciliation', 'Reconcile independent body transcription against located original-image review.',
             {'type': 'object', 'properties': {'first': _OBJECT, 'reviewed': _OBJECT},
              'required': ['first', 'reviewed'], 'additionalProperties': False},
             ('body_text', 'structure_review'), reconcile)

    from dmate_math_tools import register_math_tools
    register_math_tools(registry)
    return registry, context


def combine_candidates(document, graphs, primary, supplemental, *, limit=160):
    """Fuse measured routes, retaining independent parallel ink identities."""
    from graph_stroke_checks import StrokeEvidence
    inspector = StrokeEvidence(document)
    result, issues = copy.deepcopy(primary), []
    for graph in graphs:
        gid = graph['id']
        rows = result.setdefault(gid, [])
        ids = {row['id'] for row in rows}
        vertices = {v['id'] for v in graph['vertices']}
        for raw in supplemental.get(gid, []):
            if len(rows) >= limit:
                issues.append('combined_candidate_capacity_reached:'+gid)
                break
            candidate = copy.deepcopy(raw)
            if (candidate.get('from') not in vertices or candidate.get('to') not in vertices
                    or not isinstance(candidate.get('path'), list)):
                issues.append('sknw_invalid_endpoint_proposal:'+gid)
                continue
            if any(inspector.duplicate(candidate, old, graph=graph) for old in rows):
                continue
            proof = inspector.inspect(candidate, graph)
            if proof['coverage'] < .20 and proof.get('weak_coverage', 0) < .35:
                continue
            cid = candidate.get('id')
            if not isinstance(cid, str) or cid in ids:
                issues.append('sknw_duplicate_candidate_identity:'+gid)
                continue
            candidate['pixel_evidence'] = proof
            candidate.setdefault('style', 'unknown')
            candidate.setdefault('direction', 'undirected' if graph['directed'] is False else 'unknown')
            rows.append(candidate)
            ids.add(cid)
    return result, issues
