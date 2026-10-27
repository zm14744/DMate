"""DMate's application-owned LangGraph specialists and registered image tools.

Each role receives original pixels and a narrow schema. Only validated proposals
enter state. Independent review routes concrete conflicts back to their owner;
all work, including bounded transport recovery, remains one upload task.
"""
from __future__ import annotations

import copy
import hashlib
import json
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
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
    page_issues: list
    marker_observations: list
    position_checks: list
    body_proposal: dict
    body_previous: dict
    body_error: str
    body_review: dict
    reviewed_body: dict
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
    repair_counts: dict
    repair_roles: list
    initial_route: str
    attributes_pending: bool
    result: dict


class ImageToolFailure(RuntimeError):
    def __init__(self, name, code):
        self.tool_name, self.code = name, code
        super().__init__('registered_tool_failed')


def _error_kind(exc):
    # These are application-owned pure decoder codes. Preserve their precise
    # protocol feedback without serializing arbitrary exception messages.
    known = {'node_coordinate_contract', 'node_panel_inventory', 'invalid_graph_record',
             'duplicate_graph_identity', 'invalid_node_inventory', 'duplicate_or_excessive_nodes',
             'invalid_vertex_record', 'invalid_graph_type', 'invalid_qwen_coordinate',
             'invalid_qwen_point', 'invalid_qwen_box', 'invalid_qwen_id', 'invalid_qwen_attribute'}
    if type(exc) is ValueError and str(exc) in known:
        return str(exc)
    return str(getattr(exc, 'kind', None) or getattr(exc, 'code', None) or type(exc).__name__)[:80]


def _issue(code, role, *, graph_id=None, evidence=None, **details):
    result = {'id': 'local_'+hashlib.sha256((role+':'+str(graph_id)+':'+code).encode()).hexdigest()[:16],
              'kind': code, 'target_role': role, 'reason': code,
              'graph_id': graph_id, 'vertex_ids': [], 'edge_ids': [], 'hint_ids': []}
    if evidence:
        result['evidence'] = copy.deepcopy(evidence)
    result.update(copy.deepcopy(details))
    return result


def _bounded_json(value, limit):
    """Keep model-owned JSON evidence, never requests, headers or credentials."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError):
        return {'omitted': True, 'reason': 'not_json'}
    if len(encoded) > limit:
        return {'omitted': True, 'reason': 'diagnostic_capacity',
                'bytes': len(encoded), 'sha256': hashlib.sha256(encoded).hexdigest()}
    return copy.deepcopy(value)


def _role_snapshot(response):
    allowed = ('role', 'base_revision', 'coordinate_space', 'panels_complete',
               'graphs', 'body_text', 'body_complete', 'regions', 'text_review',
               'verdict', 'page_coverage', 'body_coverage', 'body_region_review', 'issues')
    return _bounded_json({key: response[key] for key in allowed if key in response}, 96_000)


def _merge_conflict_sources(measured, model_issues):
    """Keep local failures authoritative when a model echoes their IDs.

    A model explanation may be useful feedback, but cannot replace the tool's
    actual pixel result, the owner, or the affected identities. An additional
    upstream request is retained under a separate application-generated ID.
    """
    result = {}
    for issue in measured:
        result.setdefault(issue['id'], copy.deepcopy(issue))
    for issue in model_issues:
        # Role protocols validate these identities and located observations.
        # Extra model fields cannot assert local measurement or soft routing.
        fields = ('id', 'kind', 'target_role', 'graph_id', 'vertex_ids', 'edge_ids',
                  'hint_ids', 'body_region_ids', 'reason', 'evidence', 'source_role', 'source_revision',
                  'scheduling_only')
        item = {key: copy.deepcopy(issue[key]) for key in fields if key in issue}
        existing = result.get(item['id'])
        if existing is None:
            result[item['id']] = item
            continue
        if item == existing:
            continue
        observations = existing.setdefault('model_observations', [])
        observation = _bounded_json(item, 6000)
        if observation not in observations and len(observations) < 3:
            observations.append(observation)
        if (item.get('target_role'), item.get('graph_id')) != (
                existing.get('target_role'), existing.get('graph_id')):
            item['reported_id'] = item['id']
            item['id'] = 'model_' + json_digest(item)[:16]
            result.setdefault(item['id'], item)
    return list(result.values())


def _marker_review_observation(grounding):
    """Model-facing positions share the same full-image 0..1000 contract."""
    untrusted = copy.deepcopy(grounding.get('untrusted_vertices', []))
    for row in untrusted:
        point = row.get('position')
        if isinstance(point, list) and len(point) == 2 and all(isinstance(v, (int, float)) for v in point):
            row['position'] = [round(v*1000, 3) for v in point]
        marker = row.get('nearest_strong_marker')
        if isinstance(marker, dict):
            for key in ('x', 'y'):
                if isinstance(marker.get(key), (int, float)):
                    marker[key] = round(marker[key]*1000, 3)
    unbound = []
    for marker in grounding.get('unbound_strong_markers', []):
        if not marker.get('review_relevant'):
            continue
        marker = copy.deepcopy(marker)
        marker.pop('work_point', None)
        for key in ('x', 'y'):
            if isinstance(marker.get(key), (int, float)):
                marker[key] = round(marker[key]*1000, 3)
        unbound.append(marker)
    return _bounded_json({'coordinate_space': 'original_1000',
        'untrusted_vertices': untrusted, 'unbound_strong_markers': unbound,
        'assignment_summary': grounding.get('assignment_summary', {}),
        'position_gate': grounding.get('position_gate', {})}, 24_000)


def _issue_role(code):
    if any(x in code for x in ('unknown_directed', 'unknown_weighted', 'unknown_multigraph')):
        return 'connections'  # Graph types belong to the connection protocol, not edge attributes.
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
                                               'edge_label', 'style', 'color')},
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
            for key in ('from', 'to', 'direction', 'style', 'weight', 'edge_label', 'color'):
                old[key] = copy.deepcopy(edge.get(key))
            old['path'] = [[round(x*1000, 5), round(y*1000, 5)] for x, y in edge['path']]
    return result


def _body_review_focus(first_body, conflicts, hint_by_id):
    """Spend the bounded extra crops on located disagreements before context.

    Coordinates come only from the fixed hint/body inventories. Issue-owned
    rectangles and text content cannot invent a crop or change an answer.
    """
    regions = [row for row in first_body.get('regions', [])
               if row.get('role') == 'body' and isinstance(row.get('id'), str)]

    def box(row):
        value = row.get('bbox')
        if (not isinstance(value, list) or len(value) != 4
                or not all(type(v) in (int, float) and 0 <= v <= 1000 for v in value)
                or value[2] <= value[0] or value[3] <= value[1]):
            return None
        return value

    ordered, groups, covered, seen_hints = [], {}, set(), set()
    for issue in conflicts:
        if (issue.get('target_role') != 'body_text'
                or issue.get('independent_review_resolvable') is not True
                or not str(issue.get('kind', '')).startswith(
                    ('uncertain_text_region:', 'text_graph_ownership_unresolved:'))):
            continue
        for hid in issue.get('hint_ids', []):
            hint = hint_by_id.get(hid)
            bounds = box(hint) if isinstance(hint, dict) else None
            if hid in seen_hints or bounds is None:
                continue
            seen_hints.add(hid)
            x, y = (bounds[0]+bounds[2])/2, (bounds[1]+bounds[3])/2
            matches = [(row, box(row)) for row in regions]
            matches = [(row, rect) for row, rect in matches if rect is not None
                       and rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]]
            # A hint can sit in nested text boxes. Use the smallest known
            # body fragment containing it, not an adjacent or whole-page box.
            located = min(matches, key=lambda item: (item[1][2]-item[1][0])
                          *(item[1][3]-item[1][1]))[0] if matches else None
            key = ('body', located['id']) if located else ('hint_box', *bounds)
            if key not in groups:
                row = _issue('independent_body_hint:'+hid, 'body_review', hint_ids=[],
                             body_region_ids=[located['id']] if located else [])
                groups[key] = row
                ordered.append(row)
            groups[key]['hint_ids'].append(hid)
            if located:
                covered.add(located['id'])

    fallback_boxes = {}
    for region in regions:
        if region['id'] in covered:
            continue
        bounds = box(region)
        key = tuple(bounds) if bounds else ('id', region['id'])
        if key in fallback_boxes:
            fallback_boxes[key]['body_region_ids'].append(region['id'])
            continue
        row = _issue('independent_body_region:'+region['id'], 'body_review',
                     body_region_ids=[region['id']])
        fallback_boxes[key] = row
        ordered.append(row)
    return ordered


def recognize_agents(raw, *, layout=None, provider=None, budget=None, audit=False,
                     text_result=None, cancelled=None, task_id=None):
    """Run independent vision roles with local tools and fail-visible review."""
    from langgraph.graph import START, END, StateGraph
    from langsmith import tracing_context
    from graph_agent_plugins import build_image_tools, combine_candidates
    from graph_agent_roles import (
        PAGE_VERTICES_PROMPT, BODY_PROMPT, CONNECTION_PROMPT, ATTRIBUTE_PROMPT,
        REVIEW_PROMPT, TARGETED_REVIEW_PROMPT, decode_page_response, merge_body_response,
        validate_connection_response, merge_attribute_response, decode_review_response,
        extract_rejected_role_issues, connection_graph_view, attribute_input_view)
    from graph_agent_body_review import (BODY_REVIEW_PROMPT, body_review_input_digest,
                                        decode_body_review_response, build_body_identity_contract,
                                        BODY_IDENTITY_INSTRUCTIONS)
    from graph_evidence_pipeline import _url
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
    proposal_rejections = {}
    invalidated_proposals = []
    role_call_scopes = {}
    body_review_attempts = {}
    validated_body_digests = set()
    position_repair_scopes = set()
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
    marker_hints = tool('image.marker_proposals', {}, 'page_vertices', optional=True)
    hints = evidence['text_hints']
    hint_by_id = {row['id']: row for row in hints['items']}
    context.data['hints'] = hints
    body_view = tool('image.review_views', {'graphs': []}, 'body_text')
    body_images = [overview, _url(context.data['images'][body_view['image_ref']])]

    def record(role, response):
        if audit:
            history.append({'role': role, 'response': copy.deepcopy(response)})

    def committed(role, response=None):
        with ledger._lock:
            if role in proposal_rejections and not proposal_rejections[role].get('invalidated'):
                rejected = proposal_rejections[role]
                if (response is not None and
                        response.get('base_revision', -1) < rejected.get('base_revision', -1)):
                    return  # Revalidating an older fallback cannot resolve a newer failed edit.
                proposal_rejections[role]['resolved'] = True

    def call(role, prompt, request, images, state, *, tokens=12000):
        # A rejected connector draft names the inventory and measured
        # candidates of that invocation. Page edits or new candidate scopes
        # must not reintroduce its old coordinates into a fresh request.
        scope = None
        if role == 'body_review':
            scope = {'kind': 'body_visual_inputs', 'sha256': request['body_input_digest']}
        elif role in ('connections', 'attributes', 'structure_review'):
            keys = (('graphs', 'previous_graphs') if role == 'connections' else
                    ('graphs',) if role == 'attributes' else
                    ('graphs', 'body_text', 'body_proposal', 'body_regions'))
            scope = {'kind': 'fixed_role_inputs',
                     'sha256': json_digest({key: request.get(key) for key in keys})}
        with ledger._lock:
            role_call_scopes[role] = scope
            prior = proposal_rejections.get(role)
            if (scope is not None and prior and not prior.get('resolved')
                    and not prior.get('invalidated') and prior.get('input_scope') != scope):
                prior.update(invalidated=True, invalidation_reason='role_input_scope_changed',
                             invalidated_at_revision=state.get('revision', 0),
                             replacement_input_scope=copy.deepcopy(scope))
                if len(invalidated_proposals) < 8:
                    invalidated_proposals.append(copy.deepcopy(prior))
                ledger.event(role, 'rejection_scope_invalidated', revision=state.get('revision', 0),
                    previous_scope=copy.deepcopy(prior.get('input_scope')), input_scope=copy.deepcopy(scope),
                    error_kind=prior.get('error_kind'))
        focus = [x for x in state.get('focus_issues') or []
                 if isinstance(x, dict) and x.get('target_role') == role]
        if focus:
            prompt = TARGETED_REVIEW_PROMPT + '\n本轮仍必须遵守以下角色完整协议：\n' + prompt
            request = {**request, 'focus_issues': focus,
                       'repair_round': state.get('repair_round', 0)}
        crop_issues = (request.get('required_issues', []) + focus
                       if role in ('page_vertices', 'structure_review', 'body_review') else focus)
        if crop_issues and role in ('page_vertices', 'body_text', 'body_review', 'connections', 'structure_review'):
            crop_issues = list({x['id']: x for x in crop_issues if isinstance(x, dict)
                               and isinstance(x.get('id'), str)}.values())[:128]
            focus_args = {'graphs': state.get('graphs') or state.get('inventory') or [],
                          'issues': crop_issues}
            if isinstance(request.get('body_regions'), list):
                focus_args['body_regions'] = request['body_regions']
            focused = tool('image.focused_views', focus_args, role, optional=True)
            if focused is not None:
                images = list(images)
                mappings = []
                for mapping in focused['focused_views']:
                    if len(images) >= 5:
                        break
                    images.append(_url(context.data['images'][mapping['image_ref']]))
                    mappings.append({**mapping, 'image_number': len(images)})
                request = {**request, 'focused_views': mappings,
                           'focused_view_diagnostics': focused['diagnostics']}
                if mappings:
                    prompt += ('\nfocused_views 的 image_number 是本次图片从1开始的序号；'
                               '追加图片只放大原始像素。必须按 original_bbox 映射回完整原图'
                               '0..1000坐标，不把裁片局部坐标当原图坐标，也不把裁片视为正确性结论。')
        with ledger._lock:
            rejected = copy.deepcopy(proposal_rejections.get(role))
        if rejected and not rejected.get('resolved') and not rejected.get('invalidated'):
            request = {**request, 'previous_rejection': rejected}
            prompt += ('\nprevious_rejection 是未提交的提案与明确校验错误，'
                       '请修正对应字段；它不是已确认结构，不能从中创造可退役边。')
        response = runner.call(role, prompt, request, images,
                               revision=state.get('revision', 0), output_tokens=tokens)
        record(role, response)
        return response

    def failed(role, exc, response=None):
        if isinstance(exc, AgentCancelled):
            raise exc
        kind = _error_kind(exc)
        details = _bounded_json(getattr(exc, 'audit', {}), 24_000)
        if kind == 'invalid_graph_type' and role == 'page_vertices' and isinstance(response, dict):
            for graph in response.get('graphs', []) if isinstance(response.get('graphs'), list) else []:
                if not isinstance(graph, dict):
                    continue
                bad = next((key for key in ('directed', 'weighted', 'multigraph')
                            if key in graph and type(graph[key]) is not bool and graph[key] != 'unknown'), None)
                if bad:
                    details = _bounded_json({'issue': kind, 'graph_id': graph.get('id'), 'field': bad,
                        'expected': 'JSON boolean true/false or the string unknown', 'actual': graph[bad]}, 6000)
                    break
        with ledger._lock:
            if isinstance(response, dict):
                previous_revision = proposal_rejections.get(role, {}).get('base_revision', -1)
                revision = response.get('base_revision', -1)
                if revision >= previous_revision:
                    proposal_rejections[role] = {'role': role, 'error_kind': kind,
                        'base_revision': revision,
                        'details': details, 'rejected_proposal': _role_snapshot(response),
                        'input_scope': copy.deepcopy(role_call_scopes.get(role)),
                        'resolved': False, 'source_sha256': source_sha,
                        'task_id': ledger.task_id}
        ledger.event(role, 'proposal_rejected' if isinstance(response, dict) else 'stage_failed',
                     error_kind=kind, details=details)
        return kind

    def page(state):
        response = None
        try:
            marker_cache = context.data['marker_cache']
            if 'page_review_sheet' not in marker_cache:
                marker_cache['page_review_sheet'] = tool('image.marker_review_views', {},
                                                         'page_vertices', optional=True)
            marker_view = marker_cache['page_review_sheet']
            page_images = [overview, _url(document.normalized)]
            page_prompt = PAGE_VERTICES_PROMPT + ('\n图片1是完整原图；图片2是同页归一化辅助视图，'
                '仅帮助查看阴影/透印等内容，增强效果不证明任何顶点、边或文字事实。'
                '所有输出坐标仍按完整原图 original_1000，必须回到原图核对。')
            marker_request = {}
            if marker_view is not None:
                marker_request = copy.deepcopy(marker_view)
                image_ref = marker_view.get('image_ref')
                marker_request['image_number'] = 3 if image_ref else None
                if image_ref:
                    page_images.append(_url(context.data['images'][image_ref]))
                page_prompt += ('\nmarker_review_view 是原像素候选接触拼图；image_number 指定图片，'
                    'sheet_bbox/拼图坐标绝不是完整原图坐标。只能依据 original_bbox/original_center '
                    '映射回 original_1000，或用实际 marker_id 绑定原位置。候选可能是噪声，也可能漏点；'
                    'tile_number 按从左到右、从上到下对应格位，ID只在metadata，不是图片上的标注；'
                    'original_center 不等于 sheet 中心。必须另看完整原图逐图核对，'
                    '不以候选个数或候选存在/缺失证明顶点存在/不存在。')
            marker_focus = []
            known_markers = {m['id'] for m in (marker_hints or {}).get('candidates', [])}
            for entry in state.get('marker_observations') or []:
                observation = entry.get('observations') or {}
                missing = [m['marker_id'] for m in observation.get('unbound_strong_markers', [])
                           if isinstance(m, dict) and m.get('marker_id') in known_markers]
                if missing:
                    marker_focus.append(_issue('unbound_marker_visual_check', 'page_vertices',
                        graph_id=entry.get('graph_id'), marker_ids=missing))
            for entry in state.get('position_checks') or []:
                marker_focus.append(_issue('unobserved_position_visual_check', 'page_vertices',
                    graph_id=entry.get('graph_id'), vertex_ids=entry.get('vertex_ids') or []))
            response = call('page_vertices', page_prompt,
                            {'layout_hints': evidence['layout_hints'], 'text_hints': hints['items'],
                             'original_image_size': list(document.original.size),
                             'marker_proposals': marker_hints,
                             'marker_review_view': marker_request,
                             'previous_inventory': _review_graphs(state.get('inventory') or []),
                             'marker_review_context': state.get('page_issues') or [],
                             'marker_position_observations': state.get('marker_observations') or [],
                             'marker_position_checks': state.get('position_checks') or [],
                             'required_issues': marker_focus + (state.get('page_issues') or [])},
                            page_images, state, tokens=10000)
            decoded = decode_page_response(response, marker_hints, revision=state.get('revision', 0))
            graphs = decoded['graphs']
            for graph in graphs:
                bindings = [row for row in decoded['audit']['bindings'] if row['graph_id'] == graph['id']]
                binding_audit = {**copy.deepcopy(decoded['audit']),
                                 'bindings': copy.deepcopy(bindings), 'binding_count': len(bindings)}
                graph['node_review'] = {'source': 'page_vertices',
                    'source_sha256': source_sha, 'observed_vertices': copy.deepcopy(graph['vertices']),
                    'marker_binding_audit': binding_audit}
            grounded = tool('image.marker_grounding', {'graphs': graphs}, 'page_vertices', optional=True)
            graphs = grounded['graphs'] if grounded is not None else graphs
            position_issues, observations, position_checks = [], [], []
            for graph in graphs:
                grounding = graph.get('marker_grounding') or {}
                if grounding.get('review_required'):
                    gate = grounding.get('position_gate') or {}
                    observations.append({'graph_id': graph['id'],
                        'observations': _marker_review_observation(grounding)})
                    vids = [v['vertex'] for v in grounding.get('untrusted_vertices', [])]
                    if vids:
                        position_checks.append({'graph_id': graph['id'], 'vertex_ids': vids})
                    # Failure to detect a marker is not evidence that a node
                    # is absent. Only a measured identity/position conflict
                    # blocks connectors; unsupported positions require an
                    # independent, located visual check on this revision.
                    if not gate.get('hard_blocking'):
                        continue
                    position_issues.append(_issue('vertex_position_review_required', 'page_vertices',
                        graph_id=graph['id'], vertex_ids=vids,
                        marker_observations=copy.deepcopy(observations[-1]['observations'])))
            committed('page_vertices')
            ledger.event('page_vertices', 'committed', revision=state.get('revision', 0)+1,
                         inventory_digest=json_digest(graphs), marker_binding_audit=copy.deepcopy(decoded['audit']))
            # Any inventory edit invalidates ALL old paths and edge evidence.
            return {'initial': response, 'inventory': graphs, 'graphs': [], 'candidates': {},
                    'connection_response': {}, 'page_error': '',
                    'page_issues': position_issues,
                    'marker_observations': observations, 'position_checks': position_checks,
                    'connection_error': '', 'connection_issues': [], 'attribute_error': '', 'attribute_issues': [],
                    'attributes_pending': True,
                    'revision': state.get('revision', 0)+1}
        except Exception as exc:
            return {'page_error': failed('page_vertices', exc, response)}

    def body(state):
        response = None
        try:
            request = {'text_hints': hints['items'], 'text_review_tiles': body_view['text_review_tiles'],
                       'local_text_status': hints['local_status']}
            previous = state.get('body_proposal')
            if previous and json_digest(previous) not in validated_body_digests:
                previous = None  # A rejected draft is feedback, not committed transcription history.
            if previous:
                request['previous_transcription'] = copy.deepcopy(previous)
                request['body_regions'] = copy.deepcopy(previous.get('regions', []))
            response = call('body_text', BODY_PROMPT,
                            request, body_images, state, tokens=8500)
            if state.get('inventory'):
                merge_body_response(response, hints, state.get('graphs') or state['inventory'],
                                    previous=previous, revision=state.get('revision', 0))
                validated_body_digests.add(json_digest(response))
                committed('body_text', response)
            # Panel ownership is reconciled only after the parallel page role
            # has completed; this role never guesses another role's new IDs.
            return {'body_proposal': response, 'body_previous': previous or {}, 'body_error': ''}
        except Exception as exc:
            return {'body_error': failed('body_text', exc, response)}

    def text_proposal(state, *, reviewed=True):
        proposal = state.get('body_proposal')
        if not proposal or (state.get('body_error') and json_digest(proposal) not in validated_body_digests):
            # A newer failed repair must not be overwritten by decoding the
            # stale rejected draft which stayed in state as a fallback.
            return {'body_text': '', 'body_complete': False, 'role_valid': False,
                    'issues': [state.get('body_error') or 'body_role_missing'],
                    'text_review': {'text': '', 'complete': False, 'regions': []}}
        try:
            value = merge_body_response(proposal, hints, state.get('graphs') or state.get('inventory') or [],
                        previous=state.get('body_previous') or None,
                        revision=proposal.get('base_revision', 0))
            validated_body_digests.add(json_digest(proposal))
            committed('body_text', proposal)
            dependency = (body_review_input_digest(value, hints,
                state.get('graphs') or state.get('inventory') or []) if reviewed else None)
            latest = state.get('reviewed_body') or {}
            if reviewed and latest.get('body_input_digest') == dependency:
                return {**copy.deepcopy(latest['result']), 'role_valid': True}
            independent = state.get('body_review') or {}
            if (reviewed and independent.get('status') == 'reviewed'
                    and independent.get('body_input_digest') == dependency):
                return {**copy.deepcopy(independent['result']), 'role_valid': True}
            return {**value, 'role_valid': True}
        except Exception as exc:
            error = failed('body_text', exc, proposal)
            return {'body_text': '', 'body_complete': False, 'role_valid': False,
                    'issues': [error], 'text_review': {'text': '', 'complete': False, 'regions': []}}

    def independent_body(state):
        """Read located body pixels without waiting for a valid edge graph.

        This is an additional, separately recorded visual reader. It neither
        certifies graphs nor replaces the mandatory final whole-page judge.
        Its scope follows body/panel evidence, not unrelated edge revisions.
        """
        first = text_proposal(state, reviewed=False)
        graphs = state.get('graphs') or state.get('inventory') or []
        if not first.get('role_valid') or not graphs:
            ledger.event('body_review', 'deferred', reason='body_or_panel_inventory_unavailable')
            return {}
        regions = [r for r in first.get('regions', []) if r.get('role') == 'body']
        if not regions:
            ledger.event('body_review', 'skipped', reason='no_located_body_to_review')
            return {}
        digest = body_review_input_digest(first, hints, graphs)
        if (state.get('body_review') or {}).get('body_input_digest') == digest:
            return {}  # Same pixels/input: a graph repair is not a body reread.
        if digest in body_review_attempts:
            cached = copy.deepcopy(body_review_attempts[digest])
            ledger.event('body_review', 'scope_reused', revision=state.get('revision', 0),
                         body_input_digest=digest, source_request_revision=cached['request_revision'])
            return {'body_review': cached}
        if ledger.remaining < 2 or ledger.deadline-time.monotonic() < 15:
            ledger.event('body_review', 'deferred', reason='reserved_final_review_budget')
            return {}
        response = None
        revision = state.get('revision', 0)
        ledger.event('body_review', 'scope_checked', revision=revision, body_input_digest=digest)
        try:
            focused = _body_review_focus(first, local_conflicts(state, [], first), hint_by_id)
            request = {'body_text': first['body_text'], 'body_proposal': first.get('text_review'),
                       'body_regions': first.get('regions', []), 'text_hints': hints['items'],
                       'text_review_tiles': body_view['text_review_tiles'],
                       'graphs': [{'id': g['id'], 'bbox': [round(v*1000, 3) for v in g['bbox']]}
                                  for g in graphs],
                       'body_input_digest': digest, 'required_issues': focused}
            request['identity_contract'] = build_body_identity_contract(first, hints)
            response = call('body_review', BODY_REVIEW_PROMPT, request, body_images, state, tokens=10000)
            result = decode_body_review_response(response, first, hints=hints, graphs=graphs,
                                                 revision=revision)
            if result['body_input_digest'] != digest:
                raise ValueError('body_review_input_changed')
            committed('body_review', response)
            ledger.event('body_review', 'reviewed', revision=revision, body_input_digest=digest,
                         body_complete=result['body_complete'], conflict_count=len(result['issues']))
            value = {'status': 'reviewed', 'body_input_digest': digest,
                     'request_revision': revision, 'result': result}
            body_review_attempts[digest] = copy.deepcopy(value)
            return {'body_review': value}
        except Exception as exc:
            error = failed('body_review', exc, response)
            value = {'status': 'failed', 'body_input_digest': digest,
                     'request_revision': revision, 'error_kind': error}
            body_review_attempts[digest] = copy.deepcopy(value)
            return {'body_review': value}

    def review_view(graphs, role):
        view = tool('image.review_views', {'graphs': graphs}, role)
        return view, [overview, _url(context.data['images'][view['image_ref']])]

    def validate_topology(response, state, role):
        context.data.update(inventory=state['inventory'], candidates=state['candidates'],
                            panels_complete=state.get('initial', {}).get('panels_complete') is True)
        return tool('graph.stroke_validation', {'response': response}, role)

    def rejected_issues(role, response, state):
        # Diagnose against the invocation's fixed IDs, never IDs invented in
        # a rejected proposal. A later page commit clears these diagnostics.
        fixed = copy.deepcopy(state.get('inventory') or [])
        committed_graphs = {g['id']: g for g in state.get('graphs') or []}
        for graph in fixed:
            graph['edges'] = copy.deepcopy(committed_graphs.get(graph['id'], {}).get('edges', []))
        return extract_rejected_role_issues(response, fixed, role=role,
                                           revision=state.get('revision', 0), hints=hints)

    def connections(state):
        if not state.get('inventory'):
            return {'connection_error': 'page_inventory_missing'}
        if state.get('page_issues'):
            return {'connection_error': 'unresolved_vertex_positions'}
        response = None
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
            request = {'graphs': [connection_graph_view(g, candidates.get(g['id'], [])) for g in inventory],
                       'review_tiles': view['review_tiles'], 'candidate_generation_diagnostics': notes,
                       'vertex_position_observations': state.get('marker_observations') or [],
                       'previous_graphs': _review_graphs(state.get('graphs') or []),
                       'retirable_edge_ids': {g['id']: [e['id'] for e in g.get('edges', [])]
                                              for g in state.get('graphs') or []}}
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
            committed('connections')
            ledger.event('connections', 'committed', revision=state.get('revision', 0)+1,
                         graph_digest=json_digest(checked['graphs']))
            return {'inventory': inventory, 'candidates': candidates, 'graphs': checked['graphs'],
                    'connection_response': response, 'connection_error': '',
                    'connection_issues': copy.deepcopy(response.get('issues', [])),
                    'attribute_error': '', 'attribute_issues': [],
                    'attributes_pending': True,
                    'candidate_diagnostics': notes, 'revision': state.get('revision', 0)+1}
        except Exception as exc:
            # A failed proposal cannot replace the last validated graph state.
            feedback = rejected_issues('connections', response, state)
            return {'connection_error': failed('connections', exc, response),
                    **({'connection_issues': feedback} if feedback else {})}

    def attributes(state):
        graphs = state.get('graphs') or []
        # Text has its own independent lane. Only page/connection evidence
        # can invalidate the fixed graph that this role is allowed to edit.
        blockers = [x for x in local_conflicts(state, graphs, {})
                    if x.get('target_role') in ('page_vertices', 'connections')]
        if not graphs or blockers:
            # Attribute edits cannot fix node positions, missing paths or a
            # rejected topology. Keep the time for their owners first.
            ledger.event('attributes', 'deferred', reason='prerequisite_conflicts',
                         conflict_ids=[x['id'] for x in blockers][:64])
            return {'attributes_pending': True}
        if state.get('attributes_pending') is False and state.get('target_role') != 'attributes':
            return {}  # A joined lane must not read the same attributes twice.
        # Missing labels/weights are exactly what this independent role must
        # detect. An upstream null or "unweighted" guess cannot skip its read.
        needed = any(g.get('edges') for g in graphs)
        if not needed:
            ledger.event('attributes', 'skipped', reason='no_edges_to_read')
            return {'attribute_error': '', 'attribute_issues': [], 'attributes_pending': False}
        response = None
        try:
            view, images = review_view(graphs, 'attributes')
            response = call('attributes', ATTRIBUTE_PROMPT,
                            {**attribute_input_view(graphs, hints), 'review_tiles': view['review_tiles']},
                            images, state, tokens=10000)
            proposed, merge_audit = merge_attribute_response(graphs, response,
                                                             revision=state.get('revision', 0))
            updated_raw = _attribute_topology(state['connection_response'], proposed)
            checked = validate_topology(updated_raw, state, 'attributes')
            committed('attributes')
            ledger.event('attributes', 'committed', revision=state.get('revision', 0)+1,
                         change_audit=merge_audit, graph_digest=json_digest(checked['graphs']))
            return {'graphs': checked['graphs'], 'connection_response': updated_raw,
                    'attribute_error': '', 'attribute_issues': copy.deepcopy(merge_audit.get('issues', [])),
                    'connection_issues': [copy.deepcopy(x) for x in state.get('connection_issues') or []
                                          if not isinstance(x, dict) or x.get('target_role') != 'attributes'],
                    'attributes_pending': False,
                    'revision': state.get('revision', 0)+1}
        except Exception as exc:
            feedback = rejected_issues('attributes', response, state)
            return {'attribute_error': failed('attributes', exc, response), 'attributes_pending': False,
                    **({'attribute_issues': feedback} if feedback else {})}

    def local_conflicts(state, graphs, body_value):
        conflicts = copy.deepcopy(state.get('page_issues') or [])

        def body_issue(code, *, soft=False):
            rejected = proposal_rejections.get('body_text') or {}
            current_failure = (not rejected.get('resolved') and rejected.get('error_kind') == code)
            details = copy.deepcopy(rejected.get('details') or {}) if current_failure else {}
            hid = str(code).rsplit(':', 1)[-1]
            if hid not in hint_by_id:
                hid = details.get('hint_id')
            known = [hid] if hid in hint_by_id else []
            issue = _issue(str(code), 'body_text', hint_ids=known,
                independent_review_resolvable=bool(soft),
                hint_context=[copy.deepcopy(hint_by_id[identity]) for identity in known])
            if details:
                issue['failure_details'] = details
            return issue

        for role, key in (('page_vertices', 'page_error'), ('body_text', 'body_error'),
                          ('connections', 'connection_error'), ('attributes', 'attribute_error')):
            if state.get(key):
                if role == 'body_text':
                    conflicts.append(body_issue(state[key]))
                    continue
                rejected = proposal_rejections.get(role) or {}
                details = (rejected.get('details') or {}) if (not rejected.get('resolved')
                            and not rejected.get('invalidated')
                            and rejected.get('error_kind') == state[key]) else {}
                fixed = {g['id']: g for g in state.get('inventory') or []}
                gid = details.get('graph_id')
                gid = gid if isinstance(gid, str) and gid in fixed else None
                known = {v['id'] for v in fixed[gid]['vertices']} if gid else set()
                vids = [v for v in details.get('vertex_ids', [])
                        if isinstance(v, str) and v in known] if isinstance(details.get('vertex_ids'), list) else []
                conflicts.append(_issue(state[key], role, graph_id=gid,
                    vertex_ids=list(dict.fromkeys(vids)), failure_details=copy.deepcopy(details)))
        for graph in graphs:
            for field in ('directed', 'weighted', 'multigraph'):
                if type(graph.get(field)) is not bool:
                    conflicts.append(_issue('unknown_'+field, 'connections', graph_id=graph['id']))
            for code in graph.get('uncertain_edges', []):
                code = str(code)
                role, details = _issue_role(code), {}
                if code.startswith('unresolved_edge_evidence:'):
                    eid = code.split(':', 1)[1]
                    edge = next((e for e in graph['edges'] if e['id'] == eid), {})
                    proofs = [e for e in edge.get('evidence', []) if isinstance(e, dict)
                              and e.get('source') in ('original_pixel_route', 'original_pixel_connector_boundaries')]
                    proof = proofs[-1] if proofs else {}
                    if proof.get('supported') is True:
                        role = 'attributes'  # The path is supported; direction/style remain editable here.
                    details = {'edge_ids': [eid], 'pixel_evidence': _bounded_json(proof, 6000)}
                conflicts.append(_issue(code, role, graph_id=graph['id'], **details))
        for code in body_value.get('issues', []):
            conflicts.append(body_issue(str(code), soft=body_value.get('role_valid') is True
                                        and not state.get('body_error')))
        model_issues = []
        model_issues.extend(copy.deepcopy(body_value.get('model_issues') or []))
        for code in state.get('connection_issues', []):
            model_issues.append(copy.deepcopy(code) if isinstance(code, dict) else _issue(str(code), 'connections'))
        for code in state.get('attribute_issues', []):
            model_issues.append(copy.deepcopy(code) if isinstance(code, dict) else _issue(str(code), 'attributes'))
        return _merge_conflict_sources(conflicts, model_issues)

    def deferred_review(first_body, conflicts, reason):
        ledger.event('structure_review', 'deferred', reason=reason,
                     conflict_ids=[x['id'] for x in conflicts][:64])
        return {'review': {'verdict': 'needs_review'}, 'review_error': '',
                'conflicts': conflicts[:160], 'body_text': first_body['body_text'],
                'body_complete': False, 'body_audit': first_body.get('audit', {})}

    def review_blocked(state, first_body, conflicts):
        return any(x.get('target_role') != 'body_text' or not first_body.get('role_valid')
                   or state.get('body_error') for x in conflicts)

    def review(state):
        graphs = copy.deepcopy(state.get('graphs') or [])
        first_body = text_proposal(state)
        conflicts = local_conflicts(state, graphs, first_body)
        if not graphs:
            if not conflicts:
                conflicts.append(_issue('graph_inventory_missing', 'page_vertices'))
            return deferred_review(first_body, conflicts, 'graph_inventory_missing')
        if review_blocked(state, first_body, conflicts):
            # A judge cannot override these required failures. Do not spend a
            # whole remote turn discovering an already known rejection again.
            return deferred_review(first_body, conflicts, 'owner_repair_required')
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
        if review_blocked(state, first_body, conflicts):
            return deferred_review(first_body, conflicts, 'local_audit_requires_repair')
        response = None
        try:
            view, images = review_view(graphs, 'structure_review')
            response = call('structure_review', REVIEW_PROMPT+'\n'+BODY_IDENTITY_INSTRUCTIONS,
                            {'graphs': _review_graphs(graphs), 'body_text': first_body['body_text'],
                             'body_proposal': first_body.get('text_review'),
                             'body_regions': first_body.get('regions', []),
                             'identity_contract': build_body_identity_contract(first_body, hints),
                             'text_hints': hints['items'], 'review_tiles': view['review_tiles'],
                             'text_review_tiles': view['text_review_tiles'],
                             'marker_position_checks': state.get('position_checks') or [],
                             'marker_observations': state.get('marker_observations') or [],
                             'required_issues': conflicts}, images, state, tokens=16384)
            text_value = tool('text.visual_reconciliation', {'first': first_body, 'reviewed': response},
                              'structure_review')
            final_conflicts = local_conflicts(state, graphs, {'issues': text_value['body_audit'].get('issues', [])})
            # The independent source review may resolve a body transcription
            # disagreement. Programmatic graph failures remain unresolved.
            final_conflicts.extend(x for x in conflicts
                                   if (x.get('target_role') != 'body_text' or not first_body.get('role_valid'))
                                   and x['id'] not in {c['id'] for c in final_conflicts})
            reviewed = decode_review_response(response, graphs, body_complete=text_value['body_complete'],
                revision=state.get('revision', 0), required_issues=final_conflicts, hints=hints,
                body_regions=first_body.get('regions', []),
                position_checks=state.get('position_checks') or [])
            committed('structure_review')
            seen = {x['id'] for x in final_conflicts}
            final_conflicts = _merge_conflict_sources(final_conflicts,
                [x for x in reviewed.get('issues', []) if x.get('id') not in seen])
            # The decoder has validated every raw model issue, but its own
            # required-ID deduplication can hide an additional upstream owner.
            # Keep the deterministic failure and retain that located request.
            final_conflicts = _merge_conflict_sources(final_conflicts, response.get('issues', []))
            if reviewed.get('verdict') != 'accept' and not final_conflicts:
                final_conflicts.append(_issue('independent_review_incomplete', 'connections'))
            body_update = {}
            # A valid whole-page reader can correct body text while asking
            # for an unrelated edge repair. Keep that newer located text;
            # a later deferred graph review must not resurrect an older read.
            if (text_value['body_complete'] is True
                    and not any(x.get('target_role') == 'body_text' for x in final_conflicts)):
                decisions = {r['id']: r for r in reviewed.get('body_region_review', [])}
                regions = []
                for old in first_body.get('regions', []):
                    decision = decisions[old['id']]
                    region = {**copy.deepcopy(old), 'role': decision['role'],
                              'text': decision.get('text', old['text'])}
                    region.pop('graph_id', None)
                    if decision['role'] == 'graph_label':
                        region['graph_id'] = decision.get('graph_id')
                    regions.append(region)
                dependency = body_review_input_digest(text_proposal(state, reviewed=False), hints, graphs)
                body_result = {'role': 'structure_review', 'base_revision': state.get('revision', 0),
                    'body_text': text_value['body_text'], 'body_complete': True, 'regions': regions,
                    'text_review': copy.deepcopy(reviewed['text_review']), 'issues': [], 'model_issues': [],
                    'audit': {'source': 'independent_structure_review', 'scope': 'body_only',
                              'source_sha256': source_sha, 'base_revision': state.get('revision', 0),
                              'reconciliation': copy.deepcopy(text_value['body_audit'])}}
                body_update['reviewed_body'] = {'body_input_digest': dependency, 'result': body_result}
                ledger.event('structure_review', 'body_committed', revision=state.get('revision', 0),
                             body_input_digest=dependency, content_digest=json_digest(body_result))
            ledger.event('structure_review', 'reviewed', revision=state.get('revision', 0),
                         verdict=reviewed.get('verdict'), conflict_count=len(final_conflicts))
            return {'review': reviewed, 'review_error': '', 'conflicts': final_conflicts[:160],
                    **text_value, **body_update}
        except Exception as exc:
            error = failed('structure_review', exc, response)
            conflicts.extend(rejected_issues('structure_review', response, state))
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
        # Valid located text with uncertain OCR alternatives can be settled
        # by the independent visual reviewer. Do not reread it wholesale
        # alongside every unrelated connector repair.
        owner_issues = [row for row in issues if isinstance(row, dict)
                        and not (row.get('target_role') == 'body_text'
                                 and row.get('independent_review_resolvable') is True)]
        # A geometry rejection can make the final judge unreachable while
        # advisory node positions wait for that same judge. Break this cycle
        # once with a located page read; lack of a CV marker alone is not a
        # reason to reject or move a node, and transport failures never qualify.
        geometry_errors = {'changed_candidate_endpoints', 'candidate_path_not_pixel_validated'}
        measured_geometry = [row for row in owner_issues if row.get('target_role') == 'connections'
            and (row.get('kind') in geometry_errors
                 or (str(row.get('kind', '')).startswith('unresolved_edge_evidence:')
                     and (row.get('pixel_evidence') or {}).get('supported') is False
                     and (row.get('pixel_evidence') or {}).get('source') in
                         ('original_pixel_route', 'original_pixel_connector_boundaries')))]
        inventory = {graph['id']: graph for graph in state.get('inventory') or []}
        scope = json_digest([{'id': graph['id'], 'bbox': graph['bbox'],
            'vertices': [{key: vertex.get(key) for key in ('id', 'label', 'x', 'y')}
                         for vertex in graph['vertices']]} for graph in inventory.values()])
        located = []
        if measured_geometry and scope not in position_repair_scopes:
            known_markers = {row['id'] for row in (marker_hints or {}).get('candidates', [])}
            affected_graphs = {row['graph_id'] for row in measured_geometry if row.get('graph_id') in inventory}
            observations = {row.get('graph_id'): row.get('observations') or {}
                            for row in state.get('marker_observations') or []}
            for check in state.get('position_checks') or []:
                gid = check.get('graph_id')
                if gid not in inventory or (affected_graphs and gid not in affected_graphs):
                    continue
                known_vertices = {vertex['id'] for vertex in inventory[gid]['vertices']}
                vertices = [vid for vid in check.get('vertex_ids') or [] if vid in known_vertices]
                if not vertices:
                    continue
                markers = [row['marker_id'] for row in observations.get(gid, {}).get('unbound_strong_markers', [])
                           if isinstance(row, dict) and row.get('marker_id') in known_markers]
                located.append(_issue('connection_geometry_requires_position_review', 'page_vertices',
                    graph_id=gid, vertex_ids=list(dict.fromkeys(vertices)), marker_ids=list(dict.fromkeys(markers)),
                    failure_details={'inventory_digest': scope,
                        'geometry_conflict_ids': [row['id'] for row in measured_geometry]},
                    reason='A concrete connection geometry rejection leaves current positions unreviewed; '
                           'inspect these original pixels, without assuming a missing marker means a missing node.'))
        if located:
            position_repair_scopes.add(scope)
            located_ids = {row['id'] for row in located}
            owner_issues = [row for row in owner_issues if row['id'] not in located_ids] + located
            ledger.event('coordinator', 'position_review_routed', inventory_digest=scope,
                         conflict_ids=[row['id'] for row in measured_geometry],
                         graph_ids=[row['graph_id'] for row in located])
        targets = {row.get('target_role') for row in owner_issues}
        priority = ('page_vertices', 'connections', 'attributes', 'body_text', 'structure_review')
        counts = dict(state.get('repair_counts') or {})
        choices = [r for r in priority if r in targets]
        if state.get('page_error') or state.get('page_issues') or not state.get('inventory'):
            choices = [r for r in choices if r in ('page_vertices', 'body_text')]
        elif 'connections' in targets:
            # Attribute work would be deferred or invalidated by a pending
            # topology repair; such a non-runnable role must not spend a round.
            choices = [r for r in choices if r != 'attributes']
        # An unresolved connection must not consume every repair opportunity
        # while an independent body proposal remains invalid and unvisited.
        # A located upstream conflict invalidates dependent work regardless
        # of how often another owner has already been retried.
        target = ('page_vertices' if 'page_vertices' in choices else
                  min(choices, key=lambda r: (counts.get(r, 0), priority.index(r)))
                  if choices else 'structure_review')
        roles = [target]
        if target in ('connections', 'attributes') and 'body_text' in choices:
            roles.append('body_text')
        elif target == 'body_text':
            partner = next((r for r in ('connections', 'attributes') if r in choices), None)
            if partner:
                roles.append(partner)
        focus = [copy.deepcopy(x) for x in owner_issues if x.get('target_role') in roles][:128]
        for role in roles:
            counts[role] = counts.get(role, 0)+1
            ledger.event('coordinator', 'targeted_review', target_role=role,
                         repair_round=state.get('repair_round', 0)+1,
                         conflict_ids=[x.get('id') for x in focus if x.get('target_role') == role])
        route = target if target in ('page_vertices', 'structure_review') else 'role_repairs'
        return {'target_role': route, 'focus_issues': focus, 'repair_roles': roles,
                'repair_counts': counts,
                'repair_round': state.get('repair_round', 0)+1,
                'revision': state.get('revision', 0)+1}

    def initial_roles(state):
        # A LangGraph superstep would join the two branches between every
        # stage. Coordinate their actual dependencies here instead: page ->
        # connections -> attributes and body -> independent body review.
        # Only this coordinator merges state; workers receive snapshots.
        current, changed = copy.deepcopy(state), set()
        body_keys = {'body_proposal', 'body_previous', 'body_error', 'body_review'}
        pending, sequence = {}, 0
        page_done, first_connection_done, body_repair_planned = False, False, False
        graph_stage, body_stage = 'page', 'initial'

        def merge(value, lane):
            if ((lane == 'body' and not set(value) <= body_keys)
                    or (lane == 'graph' and set(value) & body_keys)):
                raise ValueError('initial_role_state_collision')
            value = copy.deepcopy(value)
            if 'revision' in value:
                # A body repair may have reserved a later request revision
                # while an older, independent attribute request was running.
                value['revision'] = max(current.get('revision', 0), value['revision'])
            current.update(value)
            changed.update(value)

        with ThreadPoolExecutor(max_workers=2) as pool:
            def submit(role, function, lane, *, targeted=False):
                nonlocal sequence
                snapshot = copy.deepcopy(current)
                if targeted:
                    snapshot['target_role'] = role
                future = pool.submit(function, snapshot)
                pending[future] = (sequence, role, lane)
                sequence += 1

            submit('page_vertices', page, 'graph')
            submit('body_text', body, 'body')
            while pending:
                completed, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in sorted(completed, key=lambda f: pending[f][0]):
                    _, role, lane = pending.pop(future)
                    merge(future.result(), lane)
                    if role == 'page_vertices':
                        page_done, graph_stage = True, 'needs_connections'
                    elif role == 'connections':
                        first_connection_done, graph_stage = True, 'needs_attributes'
                    elif role == 'attributes':
                        graph_stage = 'done'
                    elif role == 'body_text':
                        body_stage = 'validate'
                    else:
                        body_stage = 'done'

                if graph_stage == 'needs_connections':
                    submit('connections', connections, 'graph')
                    graph_stage = 'connecting'

                if page_done and body_stage == 'validate':
                    first = text_proposal(current, reviewed=False)
                    if first.get('role_valid'):
                        submit('body_review', independent_body, 'body')
                        body_stage = 'reviewing'
                    elif body_repair_planned:
                        body_stage = 'done'  # The normal fair repair loop owns any next attempt.
                    elif first_connection_done:
                        # Preserve the existing first hard-body repair round.
                        # It may share an already running attribute lane, or
                        # repair a rejected first connection in parallel.
                        plan = prepare_initial(current)
                        merge({k: v for k, v in plan.items() if k != 'body_error'}, 'control')
                        if 'body_error' in plan:
                            merge({'body_error': plan['body_error']}, 'body')
                        if plan['initial_route'] == 'role_repairs':
                            body_repair_planned, body_stage = True, 'repairing'
                            submit('body_text', body, 'body', targeted=True)
                            if 'connections' in plan['repair_roles']:
                                submit('connections', connections, 'graph', targeted=True)
                                graph_stage = 'connecting'
                            elif ('attributes' in plan['repair_roles']
                                  and graph_stage != 'attributing'):
                                submit('attributes', attributes, 'graph', targeted=True)
                                graph_stage = 'attributing'
                        else:
                            body_stage = 'done'

                if graph_stage == 'needs_attributes':
                    submit('attributes', attributes, 'graph')
                    graph_stage = 'attributing'

        if graph_stage != 'done' or body_stage != 'done':
            raise ValueError('initial_role_dependency_incomplete')
        return {key: current[key] for key in changed}

    def connections_with_attributes(state):
        updates = connections(state)
        return {**updates, **attributes({**state, **updates})}

    def connections_and_body_review(state):
        # After a page repair, independently review newly located body scope
        # while tracing the new inventory. A prior unchanged body scope is a
        # no-op, regardless of how many connector revisions have occurred.
        with ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(connections_with_attributes, copy.deepcopy(state))
            body_updates = independent_body(state)
            updates = future.result()
        if set(updates) & set(body_updates):
            raise ValueError('page_repair_state_collision')
        return {**updates, **body_updates}

    def prepare_initial(state):
        first_body = text_proposal(state)
        conflicts = local_conflicts(state, state.get('graphs') or [], first_body)
        if (first_body.get('role_valid') or not state.get('inventory')
                or any(x.get('target_role') == 'page_vertices' for x in conflicts)):
            return {'initial_route': 'attributes'}
        error = state.get('body_error') or first_body.get('issues', ['body_role_missing'])[0]
        if max_repairs < 1 or ledger.remaining < 3 or ledger.deadline-time.monotonic() < 15:
            return {'initial_route': 'attributes', 'body_error': error}
        # The first connector has already run. Repair its actual failures in
        # parallel with hard body failures; otherwise read edge attributes
        # while the body owner repairs its independent protocol.
        partner = ('connections' if any(x.get('target_role') == 'connections' for x in conflicts)
                   else 'attributes' if (state.get('attributes_pending') is not False
                        or any(x.get('target_role') == 'attributes' for x in conflicts)) else None)
        roles = ['body_text'] + ([partner] if partner else [])
        focus = [x for x in conflicts if x.get('target_role') in roles][:128]
        counts = {'body_text': 1}
        if partner == 'connections':
            counts[partner] = 1
        elif partner == 'attributes' and state.get('attributes_pending') is False:
            counts[partner] = 1  # An earlier completed attribute attempt actually needs repair.
        for role in counts:
            ledger.event('coordinator', 'targeted_review', target_role=role,
                         repair_round=1, conflict_ids=[x['id'] for x in focus if x.get('target_role') == role])
        return {'initial_route': 'role_repairs', 'body_error': error,
                'repair_roles': roles, 'target_role': 'role_repairs',
                'focus_issues': focus, 'repair_counts': counts,
                'repair_round': 1, 'revision': state.get('revision', 0)+1}

    def role_repairs(state):
        roles = state.get('repair_roles') or []
        def body_with_review(snapshot):
            updates = body(snapshot)
            return {**updates, **independent_body({**snapshot, **updates})}

        functions = {'body_text': body_with_review, 'connections': connections_with_attributes,
                     'attributes': attributes}
        # Only body+connections or body+attributes can run together. One owns
        # text, the other graph state; both share the exact inventory revision.
        if not roles or len(roles) > 2 or (len(roles) == 2 and 'body_text' not in roles):
            raise ValueError('invalid_parallel_repair_roles')
        def invoke(role):
            return functions[role]({**state, 'target_role': role})
        if roles == ['connections']:
            return connections_and_body_review(state)
        if len(roles) == 1:
            values = [invoke(roles[0])]
        else:
            with ThreadPoolExecutor(max_workers=2) as pool:
                values = list(pool.map(invoke, roles))
        updates = {}
        for value in values:
            if set(updates) & set(value):
                raise ValueError('parallel_repair_state_collision')
            updates.update(value)
        if 'body_text' not in roles:
            updates.update(independent_body({**state, **updates}))
        return updates

    def after_repairs(state):
        roles = state.get('repair_roles') or []
        return ('attributes' if 'connections' in roles
                or ('attributes' not in roles and state.get('attributes_pending')) else 'structure_review')

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
                    'repair_role_counts': dict(state.get('repair_counts') or {}),
                    'state_revision': state.get('revision', 0),
                    'events': copy.deepcopy(ledger.events), 'tools': copy.deepcopy(context.audit),
                    'remaining_conflicts': copy.deepcopy(conflicts),
                    'proposal_rejections': copy.deepcopy(proposal_rejections),
                    'invalidated_proposals': copy.deepcopy(invalidated_proposals),
                    'body_review': _bounded_json(state.get('body_review') or {}, 96_000),
                    'body_review_history': [{'status': value['status'], 'body_input_digest': digest,
                        'request_revision': value['request_revision'], 'error_kind': value.get('error_kind'),
                        'result_digest': json_digest(value['result']) if value.get('result') else None}
                        for digest, value in body_review_attempts.items()],
                    'position_review': {'required': copy.deepcopy(state.get('position_checks') or []),
                        'verdict': state.get('review', {}).get('verdict'),
                        'graphs': _bounded_json([{'id': graph.get('id'),
                            'vertex_position_review': graph.get('vertex_position_review', [])}
                            for graph in state.get('review', {}).get('graphs', [])], 24_000)},
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
    for name, node in [('initial_roles', initial_roles), ('connections', connections_and_body_review),
                       ('attributes', attributes), ('structure_review', review), ('plan_repair', plan_repair),
                       ('role_repairs', role_repairs),
                       ('page_repair', page), ('finish', finish)]:
        builder.add_node(name, node)
    builder.add_edge(START, 'initial_roles')
    builder.add_edge('initial_roles', 'structure_review')
    builder.add_edge('connections', 'attributes')
    builder.add_edge('attributes', 'structure_review')
    builder.add_conditional_edges('structure_review', after_review,
                                  {'finish': 'finish', 'plan_repair': 'plan_repair'})
    builder.add_conditional_edges('plan_repair', lambda s: s['target_role'],
        {'page_vertices': 'page_repair', 'role_repairs': 'role_repairs', 'structure_review': 'structure_review'})
    builder.add_edge('page_repair', 'connections')
    builder.add_conditional_edges('role_repairs', after_repairs,
                                  {'attributes': 'attributes', 'structure_review': 'structure_review'})
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
