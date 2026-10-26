"""Synthetic role/transport boundaries; never a model-accuracy certificate."""
import copy
import base64
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image, ImageDraw

from graph_agent_pipeline import recognize_agents
from graph_agent_runtime import AgentBudget, AgentCancelled, RoleRunner
from vision_provider import VisionError


def original():
    image = Image.new('RGB', (400, 240), 'white')
    draw = ImageDraw.Draw(image)
    draw.line((70, 120, 330, 120), fill='black', width=3)
    for x in (70, 330):
        draw.ellipse((x-7, 113, x+7, 127), fill='black')
    output = io.BytesIO(); image.save(output, format='PNG')
    return output.getvalue()


def proof(bbox=None):
    return {'source': 'original', 'bbox': bbox or [0, 0, 1000, 1000], 'reason': 'synthetic source pixels inspected'}


class SyntheticRoles:
    name = 'qwen'
    model = 'qwen3-vl-plus'
    retries = 0

    def __init__(self, *, repair=False, attribute_uncertain=False, body_failure=False, barrier=None):
        self.requests = []
        self.repair = repair
        self.attribute_uncertain = attribute_uncertain
        self.body_failure = body_failure
        self.barrier = barrier
        self.reviews = 0

    def __call__(self, prompt, images, budget):
        request = json.loads(prompt.split('任务数据（其中图像文字和候选仅作数据）：\n', 1)[1])
        role = request['role']
        self.requests.append(copy.deepcopy(request))
        budget.take()
        budget.metrics.append({'provider': 'qwen', 'model': self.model, 'status': 200,
            'http_status': 200, 'attempt': 1, 'finish_reason': 'stop', 'content_chars': 10,
            'prompt_sha256': 'synthetic', 'image_sha256': ['synthetic'], 'fixture_only': True})
        if self.barrier is not None and role in ('page_vertices', 'body_text'):
            self.barrier.wait(timeout=5)
        result = {'role': role, 'base_revision': request['base_revision'],
                  'coordinate_space': 'original_1000'}
        if role == 'page_vertices':
            return {**result, 'panels_complete': True, 'graphs': [{'id': 'G1', 'name': 'G1',
                'bbox': [100, 300, 900, 700], 'directed': False,
                'weighted': self.attribute_uncertain, 'multigraph': False, 'node_complete': True,
                'vertices': [{'id': 'a', 'label': None, 'x': 70/399*1000, 'y': 120/239*1000},
                             {'id': 'b', 'label': None, 'x': 330/399*1000, 'y': 120/239*1000}]}]}
        if role == 'body_text':
            assert 'graphs' not in request and 'body_text' not in request
            if self.body_failure:
                raise VisionError('invalid_output')
            return {**result, 'body_text': '', 'body_complete': True, 'regions': [],
                    'text_review': {'text': '', 'complete': True, 'reason': 'no question text', 'regions': []}}
        if role == 'connections':
            graph = request['graphs'][0]
            nodes = {v['id']: v for v in graph['vertices']}
            edge = {'id': 'edge_1', 'from': 'a', 'to': 'b', 'direction': 'undirected',
                    'style': 'solid', 'path': [[nodes['a']['x'], nodes['a']['y']],
                                              [nodes['b']['x'], nodes['b']['y']]]}
            if self.attribute_uncertain:
                edge['weight'] = '7'
            candidates = graph['candidates']
            if candidates:
                edge['candidate_id'] = candidates[0]['id']
            return {**result, 'panels_complete': True, 'graphs': [{'id': 'G1',
                'node_inventory_confirmed': True, 'inventory_complete': True, 'edges': [edge],
                'reads': [{'vertex': v, 'complete': True, 'edge_ids': ['edge_1']} for v in ('a', 'b')],
                'candidate_verdicts': [[c['id'], i == 0] for i, c in enumerate(candidates)],
                'retired_edges': []}], 'issues': []}
        if role == 'attributes':
            return {**result, 'graphs': [{'id': 'G1', 'edges': [{'id': 'edge_1',
                'verdict': 'uncertain' if self.attribute_uncertain else 'confirmed',
                'attributes': {}, 'evidence': proof([100, 300, 900, 700])}]}], 'issues': []}
        if role == 'structure_review':
            self.reviews += 1
            issues = []
            if self.repair and self.reviews == 1:
                issues = [{'id': 'connection_check', 'kind': 'endpoint_uncertain',
                    'target_role': 'connections', 'graph_id': 'G1', 'vertex_ids': [],
                    'edge_ids': ['edge_1'], 'hint_ids': [], 'reason': 'synthetic focused review',
                    'evidence': proof([100, 300, 900, 700])}]
            position_ids = {g['graph_id']: set(g['vertex_ids'])
                            for g in request.get('marker_position_checks', [])}
            return {**result, 'verdict': 'needs_review' if issues else 'accept',
                'page_coverage': {'complete': True, 'graph_ids': ['G1'], 'evidence': proof()},
                'graphs': [{'id': g['id'], 'vertex_ids': [v['id'] for v in g['vertices']],
                    'edge_ids': [e['id'] for e in g['edges']], 'verdict': 'accept', 'evidence': proof(g['bbox']),
                    'vertex_position_review': [{'id': v['id'], 'position': [v['x'], v['y']],
                        'verdict': 'confirmed', 'evidence': proof([v['x']-15, v['y']-15, v['x']+15, v['y']+15])}
                        for v in g['vertices'] if v['id'] in position_ids.get(g['id'], set())]}
                    for g in request['graphs']],
                'body_coverage': {'complete': True, 'region_ids': [], 'evidence': proof()},
                'text_review': {'text': '', 'complete': True, 'reason': 'no question text', 'regions': []},
                'issues': issues}
        raise AssertionError(role)


@pytest.fixture
def bounded_tools(monkeypatch):
    # The sknw plugin has independent process tests. Do not start JIT processes
    # repeatedly in orchestration tests, and record the tool as injected.
    monkeypatch.setattr('graph_sknw_plugin.suggest_candidates',
                        lambda document, graphs, **kw: ({g['id']: [] for g in graphs},
                                                       [{'code': 'synthetic_plugin_boundary'}]))
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '0')


def test_real_langgraph_parallel_roles_and_registered_tools_complete_one_task(bounded_tools):
    provider = SyntheticRoles(barrier=threading.Barrier(2))
    budget = AgentBudget(seconds=25, calls=10)
    result = recognize_agents(original(), provider=provider, budget=budget, text_result={})
    workflow = result['agent_workflow']
    assert workflow['engine'] == 'langgraph' and workflow['provider_source'] == 'injected'
    assert workflow['complete'], workflow['remaining_conflicts']
    # The independent attribute read is now mandatory even for monochrome,
    # apparently unweighted edges with no upstream label reported.
    assert workflow['actual_remote_sends'] == 5
    assert set(workflow['role_sends']) == {'page_vertices', 'body_text', 'connections', 'attributes', 'structure_review'}
    assert len({m['task_id'] for m in result['remote_metrics']}) == 1
    assert all(m['source_sha256'] == workflow['source_sha256'] for m in result['remote_metrics'])
    page_request = next(r for r in provider.requests if r['role'] == 'page_vertices')
    assert page_request['original_image_size'] == [400, 240]
    markers = page_request['marker_proposals']
    assert markers['source_sha256'] == workflow['source_sha256']
    assert markers['coordinate_space'] == 'original_1000' and markers['proposal_only'] is True
    for x in (70, 330):
        assert any(abs(row['x']/1000*399-x) < 2 and abs(row['y']/1000*239-120) < 2
                   for row in markers['candidates']), 'Non-square source axes must have independent scales.'
    assert result['graphs'][0]['complete'] is True
    assert len(result['graphs'][0]['edges']) == 1
    assert {'image.marker_grounding', 'image.trace_candidates', 'image.sknw_candidates',
            'graph.stroke_validation', 'graph.structure_audit', 'text.visual_reconciliation'} <= {
                x['tool'] for x in workflow['tools']}


def test_first_connections_really_start_before_the_initial_body_returns(bounded_tools):
    overlap = threading.Barrier(2)
    body_returned = threading.Event()
    observed = []

    class BodyStillRunning(SyntheticRoles):
        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'body_text':
                overlap.wait(timeout=5)
                body_returned.set()
            elif response['role'] == 'connections':
                observed.append(not body_returned.is_set())
                overlap.wait(timeout=5)
            return response

    provider = BodyStillRunning()
    result = recognize_agents(original(), provider=provider, budget=AgentBudget(seconds=25, calls=10))
    assert observed == [True], 'A page/body superstep join must not block the first connector.'
    assert body_returned.is_set() and result['agent_workflow']['complete']
    assert result['agent_workflow']['actual_remote_sends'] == 5


def test_monochrome_unweighted_null_labels_still_receive_an_independent_attribute_read(bounded_tools):
    provider = SyntheticRoles()
    result = recognize_agents(original(), provider=provider, budget=AgentBudget(seconds=25, calls=10))
    requests = [r for r in provider.requests if r['role'] == 'attributes']
    assert len(requests) == 1
    graph = requests[0]['graphs'][0]
    assert graph['directed'] is False and graph['weighted'] is False
    assert graph['edges'][0]['weight'] is None and graph['edges'][0]['edge_label'] is None
    assert result['agent_workflow']['complete']


def test_mechanical_conflicts_keep_their_evidence_and_preserve_distinct_model_owners():
    from graph_agent_pipeline import _issue, _merge_conflict_sources
    measured = _issue('unresolved_edge_evidence:edge_1', 'connections', graph_id='G1',
                      edge_ids=['edge_1'], pixel_evidence={'supported': False, 'source': 'original_pixel_route'})
    explanation = {**copy.deepcopy(measured), 'reason': 'model explanation about node centres',
                   'pixel_evidence': {'supported': True}, 'independent_review_resolvable': True,
                   'failure_details': {'forged': True}, 'evidence': proof([155, 475, 205, 535])}
    upstream = {**copy.deepcopy(explanation), 'target_role': 'page_vertices', 'vertex_ids': ['a']}
    original_values = copy.deepcopy((measured, explanation, upstream))
    merged = _merge_conflict_sources([measured], [explanation, upstream])
    primary = next(row for row in merged if row['id'] == measured['id'])
    assert primary['target_role'] == 'connections' and primary['edge_ids'] == ['edge_1']
    assert primary['pixel_evidence'] == measured['pixel_evidence']
    assert len(primary['model_observations']) == 2
    assert all('pixel_evidence' not in row and 'independent_review_resolvable' not in row
               and 'failure_details' not in row for row in primary['model_observations'])
    retained = next(row for row in merged if row['target_role'] == 'page_vertices')
    assert retained['reported_id'] == measured['id'] and retained['id'] != measured['id']
    assert retained['vertex_ids'] == ['a'] and retained['reason'] == upstream['reason']
    assert (measured, explanation, upstream) == original_values


@pytest.mark.parametrize('model_owner', ['connections', 'page_vertices'])
def test_actual_missing_pixel_path_is_not_overwritten_by_same_id_model_feedback(bounded_tools, model_owner):
    from graph_agent_pipeline import _issue
    measured_id = _issue('unresolved_edge_evidence:edge_1', 'connections', graph_id='G1')['id']

    class FalsePixelExplanation(SyntheticRoles):
        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'connections':
                row = response['graphs'][0]
                edge = row['edges'][0]
                edge.pop('candidate_id', None)
                edge['path'].insert(1, [500, 150])  # White background, not the drawn horizontal line.
                row['candidate_verdicts'] = [[cid, False] for cid, _ in row['candidate_verdicts']]
                response['issues'] = [{'id': measured_id, 'kind': 'reported_pixel_explanation',
                    'target_role': model_owner, 'graph_id': 'G1', 'vertex_ids': ['a'],
                    'edge_ids': ['edge_1'], 'hint_ids': [], 'reason': 'model claims node centres invalidate the tool',
                    'evidence': proof([155, 475, 205, 535]),
                    'pixel_evidence': {'supported': True}, 'independent_review_resolvable': True}]
            return response

    result = recognize_agents(original(), provider=FalsePixelExplanation(), budget=AgentBudget(seconds=25, calls=10))
    workflow = result['agent_workflow']
    assert not workflow['complete'] and not result['graphs'][0]['complete']
    main = next(row for row in workflow['remaining_conflicts'] if row['id'] == measured_id)
    assert main['target_role'] == 'connections' and main['pixel_evidence']['supported'] is False
    assert main['model_observations'][0]['reason'] == 'model claims node centres invalidate the tool'
    assert 'independent_review_resolvable' not in main
    if model_owner == 'page_vertices':
        assert any(row.get('reported_id') == measured_id and row['target_role'] == model_owner
                   for row in workflow['remaining_conflicts'])
    assert workflow['role_sends'].get('structure_review', 0) == 0


def uncertain_hint_decision(hid='t1', *, second=False):
    return {'id': hid, 'role': 'uncertain', 'text': 'b' if second else 'a', 'graph_id': None,
            'reason': 'original tiny label remains ambiguous',
            'evidence': proof([790, 475, 850, 535] if second else [155, 475, 205, 535])}


def located_label_hints(*, two=False):
    rows = [{'content': 'a', 'box': [64, 115, 80, 127]}]
    if two:
        rows.append({'content': 'b', 'box': [320, 115, 337, 127]})
    return {'text_evidence': {'image_size': [400, 240], 'graph_labels': rows}}


@pytest.mark.parametrize('resolved_by_review', [False, True])
def test_soft_located_body_is_not_reread_with_each_connection_repair(bounded_tools, monkeypatch, resolved_by_review):
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '2')

    class SoftBody(SyntheticRoles):
        def __init__(self):
            super().__init__()
            self.connections = 0
            self.review_views = []

        def __call__(self, prompt, images, budget):
            request = json.loads(prompt.split('任务数据（其中图像文字和候选仅作数据）：\n', 1)[1])
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'body_text':
                response['text_review']['regions'] = [uncertain_hint_decision()]
            elif response['role'] == 'connections':
                self.connections += 1
                if self.connections <= 2:
                    response['graphs'][0]['edges'][0]['candidate_id'] = 'unknown_candidate'
            elif response['role'] == 'structure_review':
                self.review_views.append((copy.deepcopy(request), list(images)))
                response['body_coverage']['region_ids'] = ['t1']
                decision = uncertain_hint_decision()
                if resolved_by_review:
                    decision.update(role='graph_label', graph_id='G1', reason='independent original crop confirms a node label')
                response['text_review']['regions'] = [decision]
            return response

    provider = SoftBody()
    result = recognize_agents(original(), provider=provider, text_result=located_label_hints(),
                              budget=AgentBudget(seconds=30, calls=14))
    workflow = result['agent_workflow']
    assert workflow['role_sends']['body_text'] == 1 and workflow['role_sends']['connections'] == 3
    assert workflow['repair_role_counts'] == {'connections': 2}
    assert workflow['role_sends']['attributes'] == workflow['role_sends']['structure_review'] == 1
    request, images = provider.review_views[0]
    soft = next(row for row in request['required_issues'] if row['kind'] == 'uncertain_text_region:t1')
    assert soft['independent_review_resolvable'] is True and soft['hint_ids'] == ['t1']
    assert soft['hint_context'][0]['text'] == 'a'
    view = next(row for row in request['focused_views'] if 't1' in row['hint_ids'])
    assert 3 <= view['image_number'] <= len(images) <= 5
    decoded = Image.open(io.BytesIO(base64.b64decode(images[view['image_number']-1].split(',', 1)[1]))).convert('RGB')
    source = Image.open(io.BytesIO(original())).convert('RGB')
    expected = source.crop(view['original_pixel_bbox']).resize(tuple(view['output_size']), Image.Resampling.LANCZOS)
    assert decoded.size == tuple(view['output_size']) and decoded.tobytes() == expected.tobytes()
    assert workflow['complete'] is resolved_by_review and result['body_complete'] is resolved_by_review
    if not resolved_by_review:
        assert any(row['target_role'] == 'body_text' for row in workflow['remaining_conflicts'])


def test_resolved_old_body_rejection_does_not_supply_wrong_hint_to_new_soft_issue(bounded_tools, monkeypatch):
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '1')
    confirmed = uncertain_hint_decision()
    confirmed.update(role='graph_label', graph_id='G1', reason='original node label confirmed')

    class RepairedWithDifferentUncertainty(SyntheticRoles):
        def __init__(self):
            super().__init__()
            self.bodies = 0

        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'body_text':
                self.bodies += 1
                first = copy.deepcopy(confirmed)
                if self.bodies == 1:
                    first.update(role='body', text='a', graph_id=None)  # Not present in the empty body text.
                response['text_review']['regions'] = [first, uncertain_hint_decision('t2', second=True)]
            elif response['role'] == 'structure_review':
                response['body_coverage']['region_ids'] = ['t1', 't2']
                response['text_review']['regions'] = [copy.deepcopy(confirmed), uncertain_hint_decision('t2', second=True)]
            return response

    provider = RepairedWithDifferentUncertainty()
    result = recognize_agents(original(), provider=provider, text_result=located_label_hints(two=True),
                              budget=AgentBudget(seconds=30, calls=12))
    workflow = result['agent_workflow']
    assert provider.bodies == 2 and not workflow['complete']
    prior = workflow['proposal_rejections']['body_text']
    assert prior['resolved'] is True and prior['details']['hint_id'] == 't1'
    review = next(row for row in provider.requests if row['role'] == 'structure_review')
    current = next(row for row in review['required_issues'] if row['kind'] == 'uncertain_text_region:t2')
    assert current['hint_ids'] == ['t2'] and current['hint_context'][0]['id'] == 't2'
    assert 'failure_details' not in current
    assert {hid for crop in review['focused_views'] for hid in crop['hint_ids']} == {'t2'}


@pytest.mark.parametrize('invalid_body_coverage', [False, True])
def test_independent_review_same_id_keeps_mechanical_body_failure_and_other_owner(bounded_tools, monkeypatch, invalid_body_coverage):
    from graph_agent_pipeline import _issue, _merge_conflict_sources
    measured_id = _issue('uncertain_text_region:t1', 'body_text')['id']
    merged_raw_review = []

    def observed_merge(measured, model):
        if any(row.get('reason') == 'independent-review-owner-echo' and 'reported_id' not in row for row in model):
            merged_raw_review.append(1)
        return _merge_conflict_sources(measured, model)

    monkeypatch.setattr('graph_agent_pipeline._merge_conflict_sources', observed_merge)

    class IndependentEcho(SyntheticRoles):
        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'body_text':
                response['text_review']['regions'] = [uncertain_hint_decision()]
            elif response['role'] == 'structure_review':
                response['body_coverage']['region_ids'] = ['not_a_hint'] if invalid_body_coverage else ['t1']
                response['text_review']['regions'] = [uncertain_hint_decision()]
                response['issues'] = [{'id': measured_id, 'kind': 'located_position_concern',
                    'target_role': 'page_vertices', 'graph_id': 'G1', 'vertex_ids': ['a'], 'edge_ids': [],
                    'hint_ids': [], 'reason': 'independent-review-owner-echo',
                    'evidence': proof([155, 475, 205, 535]), 'independent_review_resolvable': True,
                    'pixel_evidence': {'supported': True}}]
            return response

    result = recognize_agents(original(), provider=IndependentEcho(), text_result=located_label_hints(),
                              budget=AgentBudget(seconds=25, calls=10))
    workflow = result['agent_workflow']
    assert not workflow['complete'] and not result['body_complete']
    mechanical = next(row for row in workflow['remaining_conflicts']
                      if row['id'] == measured_id and row['target_role'] == 'body_text')
    assert mechanical['hint_ids'] == ['t1']
    if invalid_body_coverage:
        assert merged_raw_review == []
        assert workflow['proposal_rejections']['structure_review']['resolved'] is False
    else:
        assert merged_raw_review
        upstream = next(row for row in workflow['remaining_conflicts'] if row.get('reported_id') == measured_id)
        assert upstream['target_role'] == 'page_vertices' and upstream['vertex_ids'] == ['a']
        assert 'independent_review_resolvable' not in upstream and 'pixel_evidence' not in upstream


def test_concrete_review_conflict_routes_back_with_fixed_edge_ids(bounded_tools, monkeypatch):
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '1')
    provider = SyntheticRoles(repair=True)
    result = recognize_agents(original(), provider=provider, budget=AgentBudget(seconds=30, calls=10))
    workflow = result['agent_workflow']
    assert workflow['complete'], workflow['remaining_conflicts']
    assert workflow['repair_rounds'] == 1 and workflow['actual_remote_sends'] == 8
    connections = [r for r in provider.requests if r['role'] == 'connections']
    assert len(connections) == 2
    assert connections[1]['focus_issues'][0]['id'] == 'connection_check'
    assert connections[1]['previous_graphs'][0]['edges'][0]['id'] == 'edge_1'
    assert connections[1]['base_revision'] > connections[0]['base_revision']
    reviews = [r for r in provider.requests if r['role'] == 'structure_review']
    assert all('focus_issues' not in r for r in reviews), 'A completed connection repair must not retarget the judge.'
    attributes = [r for r in provider.requests if r['role'] == 'attributes']
    assert len(attributes) == 2, 'A connection repair invalidates the previous attribute read.'
    assert attributes[1]['base_revision'] > attributes[0]['base_revision']


def test_tool_failure_before_a_new_role_call_cannot_reject_a_committed_proposal(bounded_tools, monkeypatch):
    from dmate_tool_registry import ToolRegistry
    original_call = ToolRegistry.call
    views = []
    def failing_view(self, name, arguments, *, role, context):
        if name == 'image.review_views' and role == 'connections':
            views.append(1)
            if len(views) == 2:
                return {'ok': False, 'error': {'code': 'synthetic_view_failure'}}
        return original_call(self, name, arguments, role=role, context=context)
    monkeypatch.setattr(ToolRegistry, 'call', failing_view)
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '1')
    provider = SyntheticRoles(repair=True)
    result = recognize_agents(original(), provider=provider, budget=AgentBudget(seconds=30, calls=10))
    workflow = result['agent_workflow']
    assert len(views) == 2 and workflow['role_sends']['connections'] == 1
    assert len(result['graphs'][0]['edges']) == 1, 'Keep the previously committed graph.'
    assert 'connections' not in workflow['proposal_rejections']
    assert any(e['role'] == 'connections' and e.get('error_kind') == 'tool_failed'
               for e in workflow['events'])
    assert not workflow['complete']


def test_rejected_connection_returns_actionable_proposal_to_its_owner(bounded_tools, monkeypatch):
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '1')
    class Corrected(SyntheticRoles):
        def __init__(self):
            super().__init__()
            self.connections = 0

        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'connections':
                self.connections += 1
                if self.connections == 1:
                    response['graphs'][0]['edges'][0]['candidate_id'] = 'unknown_candidate'
                    response['unrequested_metadata'] = 'never part of the diagnostic snapshot'
            return response

    provider = Corrected()
    result = recognize_agents(original(), provider=provider, budget=AgentBudget(seconds=30, calls=10))
    assert result['agent_workflow']['complete'], result['agent_workflow']['remaining_conflicts']
    calls = [r for r in provider.requests if r['role'] == 'connections']
    feedback = calls[1]['previous_rejection']
    assert feedback['rejected_proposal']['graphs'][0]['edges'][0]['candidate_id'] == 'unknown_candidate'
    assert feedback['source_sha256'] == result['agent_workflow']['source_sha256']
    assert feedback['resolved'] is False
    assert 'unrequested_metadata' not in feedback['rejected_proposal']
    assert calls[1]['retirable_edge_ids'] == {}, 'Rejected IDs are not committed graph IDs.'
    assert result['agent_workflow']['proposal_rejections']['connections']['resolved'] is True


def test_persistent_connection_failure_cannot_starve_independent_body_repair(bounded_tools, monkeypatch):
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '2')
    class TwoFailures(SyntheticRoles):
        def __init__(self):
            super().__init__()
            self.body_calls = 0

        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'connections':
                response['graphs'][0]['edges'][0]['candidate_id'] = 'unknown_candidate'
            if response['role'] == 'body_text':
                self.body_calls += 1
                if self.body_calls == 1:
                    response['text_review']['regions'] = [{'id': 'nonexistent_hint', 'role': 'noise',
                        'text': 'x', 'reason': 'synthetic invalid hint', 'evidence': proof()}]
            return response

    provider = TwoFailures()
    result = recognize_agents(original(), provider=provider, budget=AgentBudget(seconds=30, calls=12))
    workflow = result['agent_workflow']
    repairs = [event['target_role'] for event in workflow['events'] if event['status'] == 'targeted_review']
    assert repairs == ['body_text', 'connections', 'connections']
    assert workflow['repair_role_counts'] == {'body_text': 1, 'connections': 2}
    assert provider.body_calls == 2 and workflow['role_sends']['connections'] == 3
    body_repair = [r for r in provider.requests if r['role'] == 'body_text'][1]
    connection_repair = [r for r in provider.requests if r['role'] == 'connections'][1]
    assert body_repair['base_revision'] == connection_repair['base_revision'], 'Independent body repair is not starved.'
    assert not workflow['complete'], 'Unresolved edges must remain unaccepted.'
    assert not any(issue['target_role'] == 'body_text' for issue in workflow['remaining_conflicts'])
    assert workflow['role_sends'].get('structure_review', 0) == 0, 'Known hard failures cannot be accepted by a judge.'


def test_invalid_initial_body_repairs_in_parallel_with_first_attributes(bounded_tools, monkeypatch):
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '1')
    overlap = threading.Barrier(2)
    class ParallelRepair(SyntheticRoles):
        def __init__(self):
            super().__init__()
            self.body_calls = 0

        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'body_text':
                self.body_calls += 1
                if self.body_calls == 1:
                    response['regions'] = 'malformed'
                else:
                    overlap.wait(timeout=5)
            elif response['role'] == 'attributes':
                overlap.wait(timeout=5)
            return response

    provider = ParallelRepair()
    result = recognize_agents(original(), provider=provider, budget=AgentBudget(seconds=30, calls=10))
    workflow = result['agent_workflow']
    assert workflow['complete'], workflow['remaining_conflicts']
    assert workflow['repair_role_counts'] == {'body_text': 1}
    body_repair = [r for r in provider.requests if r['role'] == 'body_text'][1]
    connection = next(r for r in provider.requests if r['role'] == 'connections')
    attributes = next(r for r in provider.requests if r['role'] == 'attributes')
    assert body_repair['base_revision'] == attributes['base_revision'] > connection['base_revision']
    assert 'previous_rejection' in body_repair and 'focus_issues' not in connection


def test_newer_failed_body_repair_is_not_replaced_by_the_old_rejected_draft(bounded_tools, monkeypatch):
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '2')
    class TwoRejectedBodies(SyntheticRoles):
        def __init__(self):
            super().__init__()
            self.body_calls = 0
            self.connection_calls = 0

        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'body_text':
                self.body_calls += 1
                if self.body_calls == 1:
                    response['regions'] = 'first_bad_draft'
                elif self.body_calls == 2:
                    response['regions'] = [{'id': 'b1', 'role': 'body', 'text': '',
                                             'bbox': [0, 0, 1000, 1000], 'source': 'original'}]
            elif response['role'] == 'connections':
                self.connection_calls += 1
                if self.connection_calls == 1:
                    response['graphs'][0]['edges'][0]['candidate_id'] = 'unknown_candidate'
            return response

    provider = TwoRejectedBodies()
    result = recognize_agents(original(), provider=provider, budget=AgentBudget(seconds=30, calls=12))
    workflow = result['agent_workflow']
    assert workflow['complete'], workflow['remaining_conflicts']
    calls = [r for r in provider.requests if r['role'] == 'body_text']
    assert len(calls) == 3 and 'previous_transcription' not in calls[2]
    latest = calls[2]['previous_rejection']
    assert latest['error_kind'] == 'empty_body_region'
    assert latest['base_revision'] == calls[1]['base_revision']
    assert latest['rejected_proposal']['regions'][0]['id'] == 'b1'
    assert workflow['repair_role_counts'] == {'body_text': 2, 'connections': 1}
    assert workflow['role_sends']['structure_review'] == 1


def test_old_valid_body_invalidated_by_new_panel_cannot_replace_newer_rejection(bounded_tools, monkeypatch):
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '2')
    decision = {'id': 't1', 'role': 'graph_label', 'text': 'a', 'graph_id': 'G1',
                'reason': 'synthetic label located in the original panel',
                'evidence': proof([155, 475, 205, 535])}
    class ChangedPanel(SyntheticRoles):
        def __init__(self):
            super().__init__(repair=True)
            self.pages = self.bodies = 0

        def __call__(self, prompt, images, budget):
            request = json.loads(prompt.split('任务数据（其中图像文字和候选仅作数据）：\n', 1)[1])
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'page_vertices':
                self.pages += 1
                if self.pages > 1:
                    response['graphs'][0]['id'] = 'G2'
            elif response['role'] == 'connections':
                response['graphs'][0]['id'] = request['graphs'][0]['id']
            elif response['role'] == 'body_text':
                self.bodies += 1
                response['text_review']['regions'] = [copy.deepcopy(decision)]
                if self.bodies > 1:
                    response['regions'] = [{'id': 'new_empty', 'role': 'body', 'text': '',
                                             'bbox': [0, 0, 1000, 1000], 'source': 'original'}]
            elif response['role'] == 'structure_review':
                response['body_coverage']['region_ids'] = ['t1']
                response['text_review']['regions'] = [copy.deepcopy(decision)]
                if self.reviews == 1:
                    response['issues'][0].update(target_role='page_vertices',
                        kind='panel_inventory_uncertain', edge_ids=[], vertex_ids=['a'])
            return response

    provider = ChangedPanel()
    local_text = {'text_evidence': {'image_size': [400, 240], 'graph_labels': [
        {'content': 'a', 'box': [64, 115, 80, 127]}]}}
    result = recognize_agents(original(), provider=provider, text_result=local_text,
                              budget=AgentBudget(seconds=30, calls=12))
    workflow = result['agent_workflow']
    assert not workflow['complete'] and provider.pages == provider.bodies == 2
    bodies = [r for r in provider.requests if r['role'] == 'body_text']
    assert 'previous_transcription' in bodies[1], 'The old body was genuinely validated before the panel changed.'
    rejected = workflow['proposal_rejections']['body_text']
    assert rejected['base_revision'] == bodies[1]['base_revision']
    assert rejected['error_kind'] == 'empty_body_region'
    assert rejected['rejected_proposal']['regions'][0]['id'] == 'new_empty'


def test_unknown_graph_type_is_repaired_before_attribute_or_judge_calls(bounded_tools, monkeypatch):
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '1')
    class UnknownType(SyntheticRoles):
        def __init__(self):
            super().__init__()
            self.connections = 0

        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'page_vertices':
                response['graphs'][0]['weighted'] = 'unknown'
            elif response['role'] == 'connections':
                self.connections += 1
                if self.connections == 2:
                    response['graphs'][0].update(weighted=False, type_evidence=proof([100, 300, 900, 700]))
            return response

    provider = UnknownType()
    result = recognize_agents(original(), provider=provider, budget=AgentBudget(seconds=30, calls=10))
    workflow = result['agent_workflow']
    assert workflow['complete'], workflow['remaining_conflicts']
    assert workflow['role_sends']['connections'] == 2
    assert workflow['role_sends']['attributes'] == 1
    assert workflow['role_sends']['structure_review'] == 1
    connection = [r for r in provider.requests if r['role'] == 'connections'][1]
    assert any('unknown_weighted' in x['kind'] for x in connection['focus_issues'])
    order = [r['role'] for r in provider.requests]
    second_connection = [i for i, role in enumerate(order) if role == 'connections'][1]
    assert second_connection < order.index('attributes') < order.index('structure_review')


def test_rejected_connections_still_route_located_vertex_issues_upstream(bounded_tools, monkeypatch):
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '1')
    class VertexFeedback(SyntheticRoles):
        def __init__(self):
            super().__init__()
            self.connections = 0

        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'connections':
                self.connections += 1
                if self.connections == 1:
                    response['graphs'][0]['edges'][0]['candidate_id'] = 'unknown_candidate'
                    response['issues'] = [{'id': 'check_vertex_a', 'kind': 'missing_vertex_evidence',
                        'target_role': 'page_vertices', 'graph_id': 'G1', 'vertex_ids': ['a'],
                        'edge_ids': [], 'hint_ids': [], 'reason': 'synthetic located position check',
                        'evidence': proof([160, 480, 190, 530])}]
            return response

    provider = VertexFeedback()
    result = recognize_agents(original(), provider=provider, budget=AgentBudget(seconds=30, calls=10))
    workflow = result['agent_workflow']
    assert workflow['complete'], workflow['remaining_conflicts']
    assert workflow['repair_role_counts'] == {'page_vertices': 1}
    pages = [r for r in provider.requests if r['role'] == 'page_vertices']
    assert len(pages) == 2
    feedback = next(x for x in pages[1]['focus_issues'] if x['id'] == 'check_vertex_a')
    assert feedback['scheduling_only'] is True and feedback['source_role'] == 'connections'
    assert feedback['source_revision'] < pages[1]['base_revision']
    connections = [r for r in provider.requests if r['role'] == 'connections']
    assert connections[1]['previous_graphs'] == [], 'The failed edge draft was never committed.'
    assert workflow['role_sends']['structure_review'] == 1


def test_connection_attribute_issue_is_resolved_only_by_its_owner_before_review(bounded_tools):
    class AttributeFeedback(SyntheticRoles):
        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'connections':
                response['issues'] = [{'id': 'check_color', 'kind': 'color_uncertain',
                    'target_role': 'attributes', 'graph_id': 'G1', 'vertex_ids': [],
                    'edge_ids': ['edge_1'], 'hint_ids': [], 'reason': 'synthetic color check',
                    'evidence': proof([400, 480, 600, 530])}]
            elif response['role'] == 'attributes':
                response['graphs'][0]['edges'][0].update(
                    attributes={'color': 'black'}, evidence=proof([400, 480, 600, 530]))
            return response

    provider = AttributeFeedback()
    result = recognize_agents(original(), provider=provider, budget=AgentBudget(seconds=30, calls=10))
    workflow = result['agent_workflow']
    assert workflow['complete'], workflow['remaining_conflicts']
    assert workflow['role_sends']['attributes'] == 1 and workflow['repair_rounds'] == 0
    assert result['graphs'][0]['edges'][0]['color'] == 'black'


def test_blocked_attribute_owner_cannot_spend_the_last_repair_round(bounded_tools, monkeypatch):
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '2')
    class DependentRepair(SyntheticRoles):
        def __init__(self):
            super().__init__(repair=True)
            self.connections = 0

        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'connections':
                self.connections += 1
                if self.connections == 2:
                    response['graphs'][0]['edges'][0]['candidate_id'] = 'unknown_candidate'
                    response['issues'] = [{'id': 'attribute_waits_for_path', 'kind': 'color_uncertain',
                        'target_role': 'attributes', 'graph_id': 'G1', 'vertex_ids': [],
                        'edge_ids': ['edge_1'], 'hint_ids': [], 'reason': 'synthetic dependent attribute',
                        'evidence': proof([400, 480, 600, 530])}]
            return response

    provider = DependentRepair()
    result = recognize_agents(original(), provider=provider, budget=AgentBudget(seconds=30, calls=12))
    workflow = result['agent_workflow']
    assert workflow['complete'], workflow['remaining_conflicts']
    assert workflow['repair_role_counts'] == {'connections': 2}
    assert workflow['role_sends']['connections'] == 3
    assert workflow['role_sends']['attributes'] == 2
    order = [r['role'] for r in provider.requests]
    connector_calls = [i for i, role in enumerate(order) if role == 'connections']
    attribute_calls = [i for i, role in enumerate(order) if role == 'attributes']
    assert attribute_calls[0] < connector_calls[1] < connector_calls[2] < attribute_calls[1]


def test_rejected_body_draft_does_not_become_transcription_history(bounded_tools, monkeypatch):
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '1')
    class MalformedFirstBody(SyntheticRoles):
        def __init__(self):
            super().__init__()
            self.body_calls = 0

        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'body_text':
                self.body_calls += 1
                if self.body_calls == 1:
                    response.pop('body_text')
                    response['regions'] = 'invalid_body_region_list'
            return response
    provider = MalformedFirstBody()
    result = recognize_agents(original(), provider=provider, budget=AgentBudget(seconds=30, calls=10))
    workflow = result['agent_workflow']
    assert workflow['complete'], workflow['remaining_conflicts']
    calls = [r for r in provider.requests if r['role'] == 'body_text']
    assert len(calls) == 2 and 'previous_transcription' not in calls[1]
    assert calls[1]['previous_rejection']['rejected_proposal']['regions'] == 'invalid_body_region_list'
    assert workflow['proposal_rejections']['body_text']['resolved'] is True


def test_unresolved_marker_position_is_reviewed_before_any_connection_call(bounded_tools, monkeypatch):
    from graph_marker_grounding import ground_nodes
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '1')
    attempts = []
    def positional_review(document, graphs, proposals=None):
        grounded = ground_nodes(document, graphs, proposals=proposals)
        attempts.append(1)
        if len(attempts) == 1:
            grounded[0]['marker_grounding'].update(review_required=True,
                position_gate={'hard_blocking': True, 'hard_conflicts': ['synthetic position conflict']},
                untrusted_vertices=[{'vertex': 'a', 'reason': 'synthetic position conflict'}])
        return grounded
    monkeypatch.setattr('graph_marker_grounding.ground_nodes', positional_review)
    provider = SyntheticRoles()
    result = recognize_agents(original(), provider=provider, budget=AgentBudget(seconds=30, calls=10))
    assert result['agent_workflow']['complete'], result['agent_workflow']['remaining_conflicts']
    order = [request['role'] for request in provider.requests]
    pages = [i for i, role in enumerate(order) if role == 'page_vertices']
    assert len(pages) == 2 and order.index('connections') > pages[-1]
    assert provider.requests[pages[-1]]['marker_review_context'][0]['vertex_ids'] == ['a']


def test_unobserved_cpu_marker_needs_located_review_without_blocking_connections(bounded_tools, monkeypatch):
    from graph_marker_grounding import ground_nodes
    def unobserved_marker(document, graphs, proposals=None):
        grounded = ground_nodes(document, graphs, proposals=proposals)
        grounded[0]['marker_grounding'].update(review_required=True,
            position_gate={'hard_blocking': False, 'visual_review_required': True},
            untrusted_vertices=[{'vertex': 'a', 'reason': 'no_reliable_local_marker',
                                 'classification': 'pixel_unobserved', 'blocks_connections': False}])
        grounded[0]['node_position_evidence'] = [
            row for row in grounded[0]['node_position_evidence'] if row['vertex'] != 'a']
        return grounded
    monkeypatch.setattr('graph_marker_grounding.ground_nodes', unobserved_marker)
    provider = SyntheticRoles()
    result = recognize_agents(original(), provider=provider, budget=AgentBudget(seconds=30, calls=10))
    workflow = result['agent_workflow']
    assert workflow['complete'], workflow['remaining_conflicts']
    assert workflow['role_sends']['page_vertices'] == 1
    connection = next(r for r in provider.requests if r['role'] == 'connections')
    assert connection['vertex_position_observations'][0]['graph_id'] == 'G1'
    review = next(r for r in provider.requests if r['role'] == 'structure_review')
    assert review['marker_position_checks'] == [{'graph_id': 'G1', 'vertex_ids': ['a']}]
    assert len(result['graphs'][0]['edges']) == 1


def test_pixel_support_and_accepting_judge_cannot_erase_attribute_uncertainty(bounded_tools):
    result = recognize_agents(original(), provider=SyntheticRoles(attribute_uncertain=True),
                              budget=AgentBudget(seconds=30, calls=10))
    assert result['graphs'][0]['edges'], 'Known pixel-supported lines must survive.'
    assert result['graphs'][0]['complete'] is False
    assert not result['agent_workflow']['complete']
    assert any(i['target_role'] == 'attributes' for i in result['agent_workflow']['remaining_conflicts'])


def test_color_review_survives_the_second_pixel_validation(bounded_tools):
    image = Image.open(io.BytesIO(original())).convert('RGB')
    ImageDraw.Draw(image).line((79, 120, 321, 120), fill='red', width=3)
    output = io.BytesIO(); image.save(output, format='PNG')
    class ColorRoles(SyntheticRoles):
        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'attributes':
                response['graphs'][0]['edges'][0].update(
                    attributes={'color': 'red'}, evidence=proof([400, 480, 600, 530]))
            return response
    provider = ColorRoles()
    result = recognize_agents(output.getvalue(), provider=provider, budget=AgentBudget(seconds=30, calls=10))
    workflow = result['agent_workflow']
    assert workflow['complete'], workflow['remaining_conflicts']
    assert workflow['role_sends']['attributes'] == 1
    assert result['graphs'][0]['edges'][0]['color'] == 'red'
    reviewed = next(r for r in provider.requests if r['role'] == 'structure_review')
    assert reviewed['graphs'][0]['edges'][0]['color'] == 'red'


def test_explicit_attribute_repair_cannot_be_skipped_by_initial_heuristics(bounded_tools, monkeypatch):
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '1')
    class AttributeRepair(SyntheticRoles):
        def __init__(self):
            super().__init__(repair=True)

        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'structure_review' and self.reviews == 1:
                response['issues'][0].update(kind='color_uncertain', target_role='attributes')
            if response['role'] == 'attributes':
                response['graphs'][0]['edges'][0].update(
                    attributes={'color': 'black'}, evidence=proof([400, 480, 600, 530]))
            return response
    provider = AttributeRepair()
    result = recognize_agents(original(), provider=provider, budget=AgentBudget(seconds=30, calls=10))
    workflow = result['agent_workflow']
    assert workflow['complete'], workflow['remaining_conflicts']
    assert workflow['role_sends']['attributes'] == 2
    attribute_calls = [r for r in provider.requests if r['role'] == 'attributes']
    assert 'focus_issues' not in attribute_calls[0]
    assert any(issue['target_role'] == 'attributes' for issue in attribute_calls[1]['focus_issues'])
    assert result['graphs'][0]['edges'][0]['color'] == 'black'


def test_body_failure_keeps_independent_graph_results(bounded_tools):
    result = recognize_agents(original(), provider=SyntheticRoles(body_failure=True),
                              budget=AgentBudget(seconds=30, calls=10))
    assert len(result['graphs'][0]['edges']) == 1
    assert not result['body_complete'] and not result['agent_workflow']['complete']
    assert result['agent_workflow']['role_sends']['body_text'] == 1
    assert any(x['target_role'] == 'body_text' for x in result['agent_workflow']['remaining_conflicts'])


def test_cancellation_is_checked_before_any_model_or_pixel_tool(monkeypatch):
    provider = SyntheticRoles()
    with pytest.raises(AgentCancelled):
        recognize_agents(original(), provider=provider, cancelled=lambda: True)
    assert not provider.requests


def test_shared_budget_cannot_be_overspent_by_parallel_roles():
    budget = AgentBudget(seconds=10, calls=3)
    def attempt(_):
        try:
            budget.take('connections')
            return True
        except TimeoutError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(attempt, range(30)))
    assert sum(values) == 3 and budget.remaining == 0
    assert budget.role_counts == {'connections': 3}


def test_network_recovery_preserves_failed_send_and_one_upload_identity():
    counts = []
    def remote(prompt, images, budget):
        budget.take(); counts.append(1)
        budget.metrics.append({'status': 'transport_failed' if len(counts) == 1 else 200})
        if len(counts) == 1:
            raise VisionError('transport_failed')
        return {'role': 'page_vertices', 'base_revision': 7, 'coordinate_space': 'original_1000'}
    ledger = AgentBudget(seconds=15, calls=4, source_sha256='a'*64)
    result = RoleRunner(ledger, provider=remote).call('page_vertices', 'JSON', {}, [], revision=7)
    assert result['base_revision'] == 7 and ledger.remaining == 2
    assert len(ledger.metrics) == 2 and ledger.metrics[0]['status'] == 'transport_failed'
    assert ledger.network_recoveries == 1 and len({m['task_id'] for m in ledger.metrics}) == 1


def test_stale_role_response_is_rejected_before_state_commit():
    def remote(prompt, images, budget):
        budget.take()
        return {'role': 'connections', 'base_revision': 1, 'coordinate_space': 'original_1000'}
    with pytest.raises(ValueError, match='agent_response_identity_mismatch'):
        RoleRunner(AgentBudget(), provider=remote).call('connections', 'JSON', {}, [], revision=2)


def test_cancellation_after_last_visual_send_does_not_start_deepseek(monkeypatch):
    import ocr_nextgen
    from graph_schema import canonical_graph
    cancelled = [False]
    def engine(*args, **kwargs):
        cancelled[0] = True
        return {'graphs': [canonical_graph({'id': 'G1', 'name': 'G1', 'directed': False,
            'weighted': False, 'multigraph': False, 'complete': True,
            'vertices': [{'id': 'a', 'label': None, 'x': .5, 'y': .5, 'isolated_confirmed': True}],
            'edges': []})], 'diagnostics': [], 'body_text': '求度数。', 'body_complete': True,
            'agent_workflow': {}, 'remote_metrics': []}
    monkeypatch.setattr('graph_agent_pipeline.recognize_agents', engine)
    monkeypatch.setattr(ocr_nextgen, 'correct_text', lambda *a, **k: pytest.fail('cancelled task sent text request'))
    result = ocr_nextgen.recognize_graph_document(b'original', {}, graph_pipeline='agent-tools',
                                                  cancelled=lambda: cancelled[0])
    assert result['recognition_status'] == 'failed'
    assert result['diagnostics']['failure_kind'] == 'AgentCancelled'


def test_whole_upload_deadline_reserves_cleanup_after_local_ocr(monkeypatch):
    import time
    import ocr_nextgen
    limit = time.monotonic()+40
    def engine(*args, **kwargs):
        assert kwargs['budget'].deadline <= limit-28
        raise TimeoutError('synthetic stop before any request')
    monkeypatch.setattr('graph_agent_pipeline.recognize_agents', engine)
    result = ocr_nextgen.recognize_graph_document(b'original', {}, graph_pipeline='agent-tools',
                                                  request_deadline=limit)
    assert result['recognition_status'] == 'failed'
    assert result['diagnostics']['remote_metrics'] == []
