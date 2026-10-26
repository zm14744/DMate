"""DMate's application-owned LangGraph specialists and registered image tools.

Each role receives original pixels and a narrow schema. Only validated proposals
enter state. Independent review routes concrete conflicts back to their owner;
all work, including bounded transport recovery, remains one upload task.
"""
from __future__ import annotations

import copy
import hashlib
import time
from typing import TypedDict

from graph_agent_runtime import AgentBudget, AgentCancelled, RoleRunner, bounded_setting, json_digest
from graph_pipeline_version import AGENT_PIPELINE_VERSION


class AgentState(TypedDict, total=False):
    revision: int
    repair_round: int
    target_role: str
    focus_issues: list
    initial: dict
    inventory: list
    page_error: str
    body_proposal: dict
    body_previous: dict
    body_error: str
    graphs: list
    candidates: dict
    connection_response: dict
    connection_error: str
    connection_issues: list
    attribute_error: str
    attribute_issues: list
    candidate_diagnostics: list
    body_text: str
    body_complete: bool
    body_audit: dict
    review: dict
    review_error: str
    conflicts: list
    result: dict


class ImageToolFailure(RuntimeError):
    def __init__(self, name, code):
        self.tool_name, self.code = name, code
        super().__init__('registered_tool_failed')


def _error_kind(exc):
    return str(getattr(exc, 'kind', None) or getattr(exc, 'code', None) or type(exc).__name__)[:80]


def _issue(code, role, *, graph_id=None, evidence=None):
    result = {'id': 'local_'+hashlib.sha256((role+':'+str(graph_id)+':'+code).encode()).hexdigest()[:16],
              'kind': code, 'target_role': role, 'reason': code,
              'graph_id': graph_id, 'vertex_ids': [], 'edge_ids': [], 'hint_ids': []}
    if evidence:
        result['evidence'] = copy.deepcopy(evidence)
    return result


def _issue_role(code):
    if any(x in code for x in ('node_', 'vertex_', 'panel_', 'source_read')):
        return 'page_vertices' if any(x in code for x in ('node_', 'vertex_', 'panel_')) else 'connections'
    if any(x in code for x in ('weight', 'direction', 'style', 'attribute')):
        return 'attributes'
    return 'connections'


def _review_graphs(graphs):
    """A bounded draft with no CPU-invented confirmation labels for the judge."""
    rows = []
    for graph in graphs:
        rows.append({
            'id': graph['id'], 'name': graph.get('name'),
            'bbox': [round(v*1000, 3) for v in graph['bbox']],
            **{k: graph.get(k, 'unknown') for k in ('directed', 'weighted', 'multigraph')},
            'vertices': [{**{k: v.get(k) for k in ('id', 'label')},
                          'x': round(v['x']*1000, 3), 'y': round(v['y']*1000, 3)}
                         for v in graph['vertices']],
            'edges': [{**{k: e.get(k) for k in ('id', 'from', 'to', 'direction', 'weight',
                                               'edge_label', 'style')},
                       'path': [[round(x*1000, 3), round(y*1000, 3)]
                                for x, y in e.get('path', [])[::max(1, len(e.get('path', []))//16)]]}
                      for e in graph['edges']],
            'local_issues': list(graph.get('uncertain_edges', []))})
    return rows


def _attribute_topology(previous, graphs):
    """Revalidate attribute edits against the same inventory and candidate IDs."""
    result = copy.deepcopy(previous)
    by_id = {g['id']: g for g in graphs}
    for row in result.get('graphs', []):
        updated = by_id[row['id']]
        by_edge = {e['id']: e for e in updated['edges']}
        for old in row['edges']:
            edge = by_edge.get(old['id'])
            if edge is None:
                # Invalid/rejected original records are deliberately retained;
                # an attribute agent cannot silently erase topology conflicts.
                continue
            for key in ('from', 'to', 'direction', 'style', 'weight', 'edge_label'):
                old[key] = copy.deepcopy(edge.get(key))
            old['path'] = [[round(x*1000, 5), round(y*1000, 5)] for x, y in edge['path']]
    return result


def recognize_agents(raw, *, layout=None, provider=None, budget=None, audit=False,
                     text_result=None, cancelled=None, task_id=None):
    """Run independent vision roles with local tools and fail-visible review."""
    from langgraph.graph import START, END, StateGraph
    from langsmith import tracing_context
    from graph_agent_plugins import build_image_tools, combine_candidates
    from graph_agent_roles import (
        PAGE_VERTICES_PROMPT, BODY_PROMPT, CONNECTION_PROMPT, ATTRIBUTE_PROMPT,
        REVIEW_PROMPT, TARGETED_REVIEW_PROMPT, decode_nodes, merge_body_response,
        validate_connection_response, merge_attribute_response, decode_review_response)
    from graph_evidence_pipeline import _url, _proposal_json
    from graph_schema import canonical_graph
    from graph_validation import audit_graph_records
    from image_evidence import analyze_document

    source_sha = hashlib.sha256(raw).hexdigest()
    ledger = budget or AgentBudget.configured(source_sha256=source_sha, task_id=task_id, cancelled=cancelled)
    if not isinstance(ledger, AgentBudget):
        raise TypeError('agent_workflow_requires_shared_agent_budget')
    if ledger.source_sha256 not in (None, source_sha):
        raise ValueError('agent_source_identity_mismatch')
    ledger.source_sha256 = source_sha
    if cancelled is not None:
        ledger.cancelled = cancelled
    ledger.check()
    document = analyze_document(raw)
    registry, context = build_image_tools(document, text_result, layout, ledger)
    runner = RoleRunner(ledger, provider=provider, capture=audit)
    overview = _url(document.original)
    history = []
    max_repairs = bounded_setting('DMATE_AGENT_REVIEW_ROUNDS', 2, 0, 3)

    def tool(name, arguments, role, *, optional=False):
        ledger.check()
        reply = registry.call(name, arguments, role=role, context=context)
        if not reply.get('ok'):
            ledger.event(role, 'tool_failed', tool=name,
                         error_kind=str(reply.get('error', {}).get('code', 'tool_failed'))
                         if isinstance(reply.get('error'), dict) else 'tool_failed')
            if optional:
                return None
            raise ImageToolFailure(name, 'tool_failed')
        return reply['result']

    evidence = tool('image.local_evidence', {}, 'page_vertices')
    hints = evidence['text_hints']
    context.data['hints'] = hints
    body_view = tool('image.review_views', {'graphs': []}, 'body_text')
    body_images = [overview, _url(context.data['images'][body_view['image_ref']])]

    def record(role, response):
        if audit:
            history.append({'role': role, 'response': copy.deepcopy(response)})

    def call(role, prompt, request, images, state, *, tokens=12000):
        focus = state.get('focus_issues') or []
        if focus:
            prompt = TARGETED_REVIEW_PROMPT + '\n本轮仍必须遵守以下角色完整协议：\n' + prompt
            request = {**request, 'focus_issues': focus,
                       'repair_round': state.get('repair_round', 0)}
        response = runner.call(role, prompt, request, images,
                               revision=state.get('revision', 0), output_tokens=tokens)
        record(role, response)
        return response

    def failed(role, exc):
        if isinstance(exc, AgentCancelled):
            raise exc
        kind = _error_kind(exc)
        ledger.event(role, 'proposal_rejected', error_kind=kind)
        return kind

    def page(state):
        try:
            response = call('page_vertices', PAGE_VERTICES_PROMPT,
                            {'layout_hints': evidence['layout_hints'], 'text_hints': hints['items']},
                            [overview, _url(document.normalized)], state, tokens=10000)
            graphs = decode_nodes(response)
            for graph in graphs:
                graph['node_review'] = {'source': 'page_vertices',
                    'source_sha256': source_sha, 'observed_vertices': copy.deepcopy(graph['vertices'])}
            grounded = tool('image.marker_grounding', {'graphs': graphs}, 'page_vertices', optional=True)
            graphs = grounded['graphs'] if grounded is not None else graphs
            ledger.event('page_vertices', 'committed', revision=state.get('revision', 0)+1,
                         inventory_digest=json_digest(graphs))
            # Any inventory edit invalidates ALL old paths and edge evidence.
            return {'initial': response, 'inventory': graphs, 'graphs': [], 'candidates': {},
                    'connection_response': {}, 'page_error': '',
                    'connection_error': '', 'connection_issues': [], 'attribute_error': '', 'attribute_issues': [],
                    'revision': state.get('revision', 0)+1}
        except Exception as exc:
            return {'page_error': failed('page_vertices', exc)}

    def body(state):
        try:
            request = {'text_hints': hints['items'], 'text_review_tiles': body_view['text_review_tiles'],
                       'local_text_status': hints['local_status']}
            previous = state.get('body_proposal')
            if previous:
                request['previous_transcription'] = copy.deepcopy(previous)
            response = call('body_text', BODY_PROMPT,
                            request, body_images, state, tokens=8500)
            if previous:
                merge_body_response(response, hints, state.get('graphs') or state.get('inventory') or [],
                                    previous=previous, revision=state.get('revision', 0))
            # Panel ownership is reconciled only after the parallel page role
            # has completed; this role never guesses another role's new IDs.
            return {'body_proposal': response, 'body_previous': previous or {}, 'body_error': ''}
        except Exception as exc:
            return {'body_error': failed('body_text', exc)}

    def text_proposal(state):
        proposal = state.get('body_proposal')
        if not proposal:
            return {'body_text': '', 'body_complete': False,
                    'issues': ['body_role_missing'], 'text_review': {'text': '', 'complete': False, 'regions': []}}
        try:
            return merge_body_response(proposal, hints, state.get('graphs') or state.get('inventory') or [],
                        previous=state.get('body_previous') or None,
                        revision=proposal.get('base_revision', 0))
        except Exception as exc:
            failed('body_text', exc)
            return {'body_text': '', 'body_complete': False,
                    'issues': ['body_role_invalid'], 'text_review': {'text': '', 'complete': False, 'regions': []}}

    def review_view(graphs, role):
        view = tool('image.review_views', {'graphs': graphs}, role)
        return view, [overview, _url(context.data['images'][view['image_ref']])]

    def validate_topology(response, state, role):
        context.data.update(inventory=state['inventory'], candidates=state['candidates'],
                            panels_complete=state.get('initial', {}).get('panels_complete') is True)
        return tool('graph.stroke_validation', {'response': response}, role)

    def connections(state):
        if not state.get('inventory'):
            return {'connection_error': 'page_inventory_missing'}
        try:
            inventory = copy.deepcopy(state['inventory'])
            traced = tool('image.trace_candidates', {'graphs': inventory}, 'connections', optional=True)
            if traced is None:
                candidates = {g['id']: [] for g in inventory}
                notes = ['primary_trace_unavailable']
            else:
                inventory, candidates = traced['graphs'], traced['candidates']
                notes = list(traced.get('diagnostics', []))
            skeleton = tool('image.sknw_candidates', {'graphs': inventory}, 'connections', optional=True)
            if skeleton is not None:
                candidates, combined_notes = combine_candidates(document, inventory, candidates,
                                                                  skeleton['candidates'])
                notes.extend(combined_notes)
                notes.extend('sknw:'+str(d.get('code', d.get('status', 'observed')))
                             if isinstance(d, dict) else str(d) for d in skeleton.get('diagnostics', []))
            else:
                notes.append('sknw_tool_unavailable')
            view, images = review_view(inventory, 'connections')
            request = {'graphs': [_proposal_json(g, candidates.get(g['id'], [])) for g in inventory],
                       'review_tiles': view['review_tiles'], 'candidate_generation_diagnostics': notes,
                       'previous_graphs': _review_graphs(state.get('graphs') or [])}
            response = call('connections', CONNECTION_PROMPT, request, images, state, tokens=16384)
            decoder_inventory = copy.deepcopy(inventory)
            previous = {g['id']: g for g in state.get('graphs') or []}
            for graph in decoder_inventory:
                if graph['id'] in previous:
                    graph['edges'] = copy.deepcopy(previous[graph['id']]['edges'])
            response = validate_connection_response(response, decoder_inventory, candidates,
                                                     revision=state.get('revision', 0))
            local = {**state, 'inventory': inventory, 'candidates': candidates}
            checked = validate_topology(response, local, 'connections')
            ledger.event('connections', 'committed', revision=state.get('revision', 0)+1,
                         graph_digest=json_digest(checked['graphs']))
            return {'inventory': inventory, 'candidates': candidates, 'graphs': checked['graphs'],
                    'connection_response': response, 'connection_error': '',
                    'connection_issues': copy.deepcopy(response.get('issues', [])),
                    'attribute_error': '', 'attribute_issues': [],
                    'candidate_diagnostics': notes, 'revision': state.get('revision', 0)+1}
        except Exception as exc:
            # A failed proposal cannot replace the last validated graph state.
            return {'connection_error': failed('connections', exc)}

    def attributes(state):
        graphs = state.get('graphs') or []
        if not graphs or state.get('connection_error'):
            return {'attribute_error': '', 'attribute_issues': []}
        needed = any(g.get('directed') is not False or g.get('weighted') is not False
                     or g.get('multigraph') is True
                     or any(e.get('style') == 'unknown' or e.get('edge_label') is not None for e in g['edges'])
                     for g in graphs)
        if not needed:
            ledger.event('attributes', 'skipped', reason='no_attribute_conflict_or_annotated_edges')
            return {'attribute_error': '', 'attribute_issues': []}
        try:
            view, images = review_view(graphs, 'attributes')
            response = call('attributes', ATTRIBUTE_PROMPT,
                            {'graphs': _review_graphs(graphs), 'review_tiles': view['review_tiles']},
                            images, state, tokens=10000)
            proposed, merge_audit = merge_attribute_response(graphs, response,
                                                             revision=state.get('revision', 0))
            updated_raw = _attribute_topology(state['connection_response'], proposed)
            checked = validate_topology(updated_raw, state, 'attributes')
            ledger.event('attributes', 'committed', revision=state.get('revision', 0)+1,
                         change_audit=merge_audit, graph_digest=json_digest(checked['graphs']))
            return {'graphs': checked['graphs'], 'connection_response': updated_raw,
                    'attribute_error': '', 'attribute_issues': copy.deepcopy(merge_audit.get('issues', [])),
                    'revision': state.get('revision', 0)+1}
        except Exception as exc:
            return {'attribute_error': failed('attributes', exc)}

    def local_conflicts(state, graphs, body_value):
        conflicts = []
        for role, key in (('page_vertices', 'page_error'), ('body_text', 'body_error'),
                          ('connections', 'connection_error'), ('attributes', 'attribute_error')):
            if state.get(key):
                conflicts.append(_issue(state[key], role))
        for graph in graphs:
            for code in graph.get('uncertain_edges', []):
                conflicts.append(_issue(str(code), _issue_role(str(code)), graph_id=graph['id']))
        for code in body_value.get('issues', []):
            conflicts.append(_issue(str(code), 'body_text'))
        for code in state.get('connection_issues', []):
            conflicts.append(copy.deepcopy(code) if isinstance(code, dict) else _issue(str(code), 'connections'))
        for code in state.get('attribute_issues', []):
            conflicts.append(copy.deepcopy(code) if isinstance(code, dict) else _issue(str(code), 'attributes'))
        return conflicts

    def review(state):
        graphs = copy.deepcopy(state.get('graphs') or [])
        first_body = text_proposal(state)
        conflicts = local_conflicts(state, graphs, first_body)
        if not graphs:
            if not conflicts:
                conflicts.append(_issue('graph_inventory_missing', 'page_vertices'))
            return {'review': {'verdict': 'needs_review'}, 'conflicts': conflicts,
                    'body_text': first_body['body_text'], 'body_complete': False,
                    'review_error': 'graph_inventory_missing'}
        context.data['draft_graphs'] = copy.deepcopy(graphs)
        # Structural mathematics is an audit of a draft, never an edge source.
        try:
            ledger.check(minimum=3)
        except Exception as exc:
            error = failed('structure_review', exc)
            return {'review': {'verdict': 'needs_review'}, 'review_error': error,
                    'conflicts': conflicts+[_issue(error, 'structure_review')],
                    'body_text': first_body['body_text'], 'body_complete': False,
                    'body_audit': {'issues': [error]}}
        for graph in graphs:
            checked = tool('graph.structure_audit', {'graph_id': graph['id']}, 'structure_review', optional=True)
            if checked is None:
                conflicts.append(_issue('structure_tool_failed', 'connections', graph_id=graph['id']))
            else:
                for problem in checked.get('issues', []):
                    code = (str(problem.get('code', problem.get('kind', 'structure_issue')))
                            if isinstance(problem, dict) else str(problem))
                    conflicts.append(_issue(code, _issue_role(code), graph_id=graph['id']))
                if checked.get('issues_truncated'):
                    conflicts.append(_issue('structure_audit_capacity_reached', 'connections', graph_id=graph['id']))
        validation = audit_graph_records(graphs)
        conflicts.extend(_issue(str(code), _issue_role(str(code))) for code in validation)
        try:
            view, images = review_view(graphs, 'structure_review')
            response = call('structure_review', REVIEW_PROMPT,
                            {'graphs': _review_graphs(graphs), 'body_text': first_body['body_text'],
                             'body_proposal': first_body.get('text_review'),
                             'body_regions': first_body.get('regions', []),
                             'text_hints': hints['items'], 'review_tiles': view['review_tiles'],
                             'text_review_tiles': view['text_review_tiles'],
                             'required_issues': conflicts}, images, state, tokens=16384)
            text_value = tool('text.visual_reconciliation', {'first': first_body, 'reviewed': response},
                              'structure_review')
            final_conflicts = local_conflicts(state, graphs, {'issues': text_value['body_audit'].get('issues', [])})
            # The independent source review may resolve a body transcription
            # disagreement. Programmatic graph failures remain unresolved.
            final_conflicts.extend(x for x in conflicts if x.get('target_role') != 'body_text'
                                   and x['id'] not in {c['id'] for c in final_conflicts})
            reviewed = decode_review_response(response, graphs, body_complete=text_value['body_complete'],
                revision=state.get('revision', 0), required_issues=final_conflicts, hints=hints,
                body_regions=first_body.get('regions', []))
            model_issues = reviewed.get('issues', [])
            seen = {x['id'] for x in final_conflicts}
            for item in model_issues:
                if isinstance(item, dict) and item.get('id') not in seen:
                    final_conflicts.append(copy.deepcopy(item))
                    seen.add(item.get('id'))
            if reviewed.get('verdict') != 'accept' and not final_conflicts:
                final_conflicts.append(_issue('independent_review_incomplete', 'connections'))
            ledger.event('structure_review', 'reviewed', revision=state.get('revision', 0),
                         verdict=reviewed.get('verdict'), conflict_count=len(final_conflicts))
            return {'review': reviewed, 'review_error': '', 'conflicts': final_conflicts[:160], **text_value}
        except Exception as exc:
            error = failed('structure_review', exc)
            conflicts.append(_issue(error, 'structure_review'))
            return {'review': {'verdict': 'needs_review'}, 'review_error': error,
                    'conflicts': conflicts[:160], 'body_text': first_body['body_text'],
                    'body_complete': False, 'body_audit': {'issues': [error]}}

    def after_review(state):
        if (state.get('review', {}).get('verdict') == 'accept' and not state.get('conflicts')
                and state.get('body_complete') is True
                and all(g.get('complete') is True for g in state.get('graphs', []))):
            return 'finish'
        if (state.get('repair_round', 0) >= max_repairs or ledger.remaining < 2
                or ledger.deadline-time.monotonic() < 15):
            return 'finish'
        return 'plan_repair'

    def plan_repair(state):
        issues = state.get('conflicts') or []
        targets = {row.get('target_role') for row in issues if isinstance(row, dict)}
        target = next((r for r in ('page_vertices', 'connections', 'attributes', 'body_text', 'structure_review')
                       if r in targets), 'structure_review')
        focus = [copy.deepcopy(x) for x in issues if x.get('target_role') == target][:64]
        ledger.event('coordinator', 'targeted_review', target_role=target,
                     repair_round=state.get('repair_round', 0)+1,
                     conflict_ids=[x.get('id') for x in focus])
        return {'target_role': target, 'focus_issues': focus,
                'repair_round': state.get('repair_round', 0)+1,
                'revision': state.get('revision', 0)+1}

    def finish(state):
        graphs = copy.deepcopy(state.get('graphs') or state.get('inventory') or [])
        conflicts = state.get('conflicts') or []
        accepted = state.get('review', {}).get('verdict') == 'accept' and not conflicts
        for graph in graphs:
            graph.setdefault('edges', [])
            if not accepted or graph.get('complete') is not True:
                graph['complete'] = False
                graph['uncertain_edges'] = list(dict.fromkeys(graph.get('uncertain_edges', [])
                                                        + ['independent_review_incomplete']))
            graph['agent_review'] = {'task_id': ledger.task_id, 'revision': state.get('revision', 0),
                                     'accepted': accepted and graph.get('complete') is True}
        graphs = [canonical_graph(g) for g in graphs]
        workflow = {'engine': 'langgraph', 'version': AGENT_PIPELINE_VERSION,
                    'task_id': ledger.task_id, 'source_sha256': source_sha,
                    'provider_source': 'injected' if provider is not None else 'configured_live',
                    'max_remote_calls': ledger.initial_calls,
                    'actual_remote_sends': ledger.initial_calls-ledger.remaining,
                    'role_sends': dict(ledger.role_counts), 'network_recoveries': ledger.network_recoveries,
                    'repair_rounds': state.get('repair_round', 0),
                    'state_revision': state.get('revision', 0),
                    'events': copy.deepcopy(ledger.events), 'tools': copy.deepcopy(context.audit),
                    'remaining_conflicts': copy.deepcopy(conflicts),
                    'complete': bool(graphs) and accepted and state.get('body_complete') is True
                                and all(g.get('complete') is True for g in graphs),
                    'seconds': round(time.monotonic()-ledger.started, 3)}
        result = {'graphs': graphs, 'body_text': state.get('body_text', ''),
                  'body_complete': state.get('body_complete') is True and accepted,
                  'body_audit': state.get('body_audit', {}), 'image_quality': document.quality,
                  'diagnostics': list(document.diagnostics)+state.get('candidate_diagnostics', [])
                                 +[str(x.get('kind', 'agent_conflict')) for x in conflicts],
                  'calls_remaining': ledger.remaining, 'remote_metrics': copy.deepcopy(ledger.metrics),
                  'agent_workflow': workflow, 'pipeline_version': AGENT_PIPELINE_VERSION}
        if audit:
            result['stage_audit'] = history
        return {'result': result}

    builder = StateGraph(AgentState)
    for name, node in [('page_vertices', page), ('body_text', body), ('connections', connections),
                       ('attributes', attributes), ('structure_review', review), ('plan_repair', plan_repair),
                       ('page_repair', page), ('body_repair', body), ('finish', finish)]:
        builder.add_node(name, node)
    builder.add_edge(START, 'page_vertices')
    builder.add_edge(START, 'body_text')
    builder.add_edge(['page_vertices', 'body_text'], 'connections')
    builder.add_edge('connections', 'attributes')
    builder.add_edge('attributes', 'structure_review')
    builder.add_conditional_edges('structure_review', after_review,
                                  {'finish': 'finish', 'plan_repair': 'plan_repair'})
    builder.add_conditional_edges('plan_repair', lambda s: s['target_role'],
        {'page_vertices': 'page_repair', 'body_text': 'body_repair', 'connections': 'connections',
         'attributes': 'attributes', 'structure_review': 'structure_review'})
    builder.add_edge('page_repair', 'connections')
    builder.add_edge('body_repair', 'structure_review')
    builder.add_edge('finish', END)
    workflow = builder.compile()
    try:
        # No external tracing service is authorized for private student images.
        # Original image objects stay in the request context, outside graph state.
        with tracing_context(enabled=False):
            output = workflow.invoke({'revision': 0, 'repair_round': 0, 'focus_issues': []},
                config={'max_concurrency': 2, 'recursion_limit': 32,
                        'configurable': {'thread_id': ledger.task_id}})
        return output['result']
    except Exception as exc:
        if audit:
            exc.graph_stage_audit = history
        raise
