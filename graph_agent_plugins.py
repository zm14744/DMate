"""Registered, source-bound image tools used by DMate's role workflow."""
from __future__ import annotations

import copy
import hashlib
import io
import time

from dmate_tool_registry import ToolContext, ToolRegistry, ToolSpec


_OBJECT = {'type': 'object'}
_EMPTY = {'type': 'object', 'properties': {}, 'additionalProperties': False}
_GRAPHS = {'type': 'object', 'required': ['graphs'], 'additionalProperties': False,
           'properties': {'graphs': {'type': 'array', 'maxItems': 48,
                                    'items': {'type': 'object'}}}}
_ROLES = ('page_vertices', 'body_text', 'connections', 'attributes', 'structure_review')


def build_image_tools(document, text_result, layout, budget):
    """The context holds pixels; JSON tools expose only measured results/refs."""
    from graph_evidence_pipeline import apply_topology, collect_candidates
    from graph_marker_grounding import ground_nodes
    from graph_panel_context import layout_hints
    from graph_review_views import build_review_sheet
    from graph_text_evidence import reconcile_text, text_hints

    context = ToolContext(source_sha256=budget.source_sha256,
                          data={'document': document, 'text_result': text_result or {},
                                'layout': layout or [], 'images': {}},
                          deadline_monotonic=budget.deadline)
    registry = ToolRegistry()

    def register(name, description, schema, roles, handler, *, timeout=15):
        registry.register(ToolSpec(name=name, version='2026-10-26-v1',
            description=description, input_schema=schema, output_schema=_OBJECT,
            allowed_roles=tuple(roles), source_required=True, timeout_seconds=timeout), handler)

    def local_evidence(args, *, context):
        return {'layout_hints': layout_hints(context.data['layout']),
                'text_hints': text_hints(context.data['text_result']),
                'quality': copy.deepcopy(document.quality),
                'diagnostics': list(document.diagnostics)}

    register('image.local_evidence', 'Read the existing local OCR and layout evidence, without reloading models.',
             _EMPTY, _ROLES, local_evidence)

    def markers(args, *, context):
        graphs = ground_nodes(document, copy.deepcopy(args['graphs']))
        return {'graphs': graphs, 'proposal_only': True}

    register('image.marker_grounding', 'Attach existing vertex identities to unique original-pixel markers.',
             _GRAPHS, ('page_vertices',), markers)

    def trace(args, *, context):
        graphs = copy.deepcopy(args['graphs'])
        candidates, diagnostics = collect_candidates(document, graphs)
        return {'graphs': graphs, 'candidates': candidates, 'diagnostics': diagnostics,
                'proposal_only': True}

    register('image.trace_candidates', 'Trace original-source paths; candidates require later visual and pixel review.',
             _GRAPHS, ('connections',), trace, timeout=30)

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
        # One page-only text sheet plus the latest graph sheet are sufficient.
        if len(context.data['images']) > 6:
            oldest = next(iter(context.data['images']))
            if oldest != reference:
                del context.data['images'][oldest]
        return {'image_ref': reference, 'coordinate_space': 'original_1000',
                'review_tiles': tiles, 'text_review_tiles': text_tiles,
                'diagnostics': notes, 'source_pixels_only': True}

    register('image.review_views', 'Build original-pixel graph/text crops with explicit full-image coordinates.',
             _GRAPHS, _ROLES, views)

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
        body, complete, audit = reconcile_text(args['first'], args['reviewed'],
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
