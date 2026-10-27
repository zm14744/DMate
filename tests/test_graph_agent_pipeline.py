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
        if role == 'body_review':
            return {**result,
                'body_coverage': {'complete': True,
                    'region_ids': [r['id'] for r in request['text_hints']],
                    'observed_region_ids': [r['id'] for r in request['body_regions']], 'evidence': proof()},
                'body_region_review': [{**{k: r[k] for k in ('id', 'role', 'text', 'graph_id') if k in r},
                    'reason': 'synthetic independent body observation', 'evidence': proof(r['bbox'])}
                    for r in request['body_regions']],
                'text_review': copy.deepcopy(request['body_proposal']), 'issues': []}
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


class SyntheticLocatedBody(SyntheticRoles):
    """A deliberately wrong first digit and a separate, located visual read."""
    def __init__(self, *, reject_connections=False, reject_body_review=False, overlap=None, **kwargs):
        super().__init__(**kwargs)
        self.reject_connections = reject_connections
        self.reject_body_review = reject_body_review
        self.overlap = overlap
        self.body_images = []

    def __call__(self, prompt, images, budget):
        request = json.loads(prompt.split('任务数据（其中图像文字和候选仅作数据）：\n', 1)[1])
        response = super().__call__(prompt, images, budget)
        role = response['role']
        bounds = [90, 100, 450, 230]
        if role == 'body_text':
            response.update(body_text='Count r9.', regions=[{'id': 'line_1', 'role': 'body',
                'text': 'Count r9.', 'bbox': bounds, 'source': 'original'}],
                text_review={'text': 'Count r9.', 'complete': True,
                             'reason': 'synthetic first read', 'regions': []})
        elif role == 'connections':
            if self.overlap:
                self.overlap.wait(timeout=5)
            if self.reject_connections:
                response['graphs'][0]['reads'][0]['complete'] = False
        elif role == 'body_review':
            self.body_images.append((copy.deepcopy(request), list(images)))
            if self.overlap:
                self.overlap.wait(timeout=5)
            response['body_region_review'][0].update(text='Count r7.', evidence=proof(bounds))
            response['text_review'].update(text='Count r7.',
                reason='independent same-position synthetic digit observation', evidence=proof(bounds))
            if self.reject_body_review:
                response['body_coverage']['observed_region_ids'] = []
        elif role == 'structure_review':
            response['body_coverage']['observed_region_ids'] = ['line_1']
            response['body_region_review'] = [{'id': 'line_1', 'role': 'body', 'text': 'Count r7.',
                'reason': 'final separate synthetic original read', 'evidence': proof(bounds)}]
            response['text_review'].update(text='Count r7.',
                reason='final same-position synthetic digit observation', evidence=proof(bounds))
        return response


def original_with_body(text='Count r7.'):
    source = Image.open(io.BytesIO(original())).convert('RGB')
    ImageDraw.Draw(source).text((40, 35), text, fill='black')
    output = io.BytesIO(); source.save(output, format='PNG')
    return output.getvalue()


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


def test_independent_body_reads_source_pixels_while_connections_are_still_pending(bounded_tools):
    provider = SyntheticLocatedBody(reject_connections=True, overlap=threading.Barrier(2))
    raw = original_with_body()
    result = recognize_agents(raw, provider=provider, budget=AgentBudget(seconds=30, calls=12))
    workflow = result['agent_workflow']
    assert not workflow['complete'] and not result['body_complete']
    assert result['body_text'] == 'Count r7.'
    assert result['graphs'][0]['edges'] == []
    assert workflow['role_sends'] == {'page_vertices': 1, 'body_text': 1,
                                     'connections': 1, 'body_review': 1}
    assert workflow['body_review']['status'] == 'reviewed'
    assert workflow['body_review']['result']['raw_response']['role'] == 'body_review'
    request, images = provider.body_images[0]
    assert request['body_text'] == 'Count r9.'
    view = next(v for v in request['focused_views'] if 'line_1' in v['body_region_ids'])
    crop = Image.open(io.BytesIO(base64.b64decode(images[view['image_number']-1].split(',', 1)[1]))).convert('RGB')
    expected = Image.open(io.BytesIO(raw)).convert('RGB').crop(view['original_pixel_bbox'])
    expected = expected.resize(tuple(view['output_size']), Image.Resampling.LANCZOS)
    assert crop.tobytes() == expected.tobytes()
    assert len(images) == 3 and not any(e['role'] == 'structure_review' and e['status'] == 'started'
                                      for e in workflow['events'])


def test_body_review_result_survives_unrelated_connector_repair_and_reaches_final_judge(bounded_tools, monkeypatch):
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '1')
    provider = SyntheticLocatedBody(repair=True)
    result = recognize_agents(original_with_body(), provider=provider, budget=AgentBudget(seconds=35, calls=14))
    workflow = result['agent_workflow']
    assert workflow['complete'], workflow['remaining_conflicts']
    assert result['body_text'] == 'Count r7.' and result['body_complete']
    assert workflow['role_sends']['body_review'] == 1
    assert workflow['role_sends']['connections'] == 2
    judges = [r for r in provider.requests if r['role'] == 'structure_review']
    assert len(judges) == 2 and all(r['body_text'] == 'Count r7.' for r in judges)
    assert all(r['body_regions'][0]['text'] == 'Count r7.' for r in judges)
    scopes = [e for e in workflow['events'] if e['role'] == 'body_review' and e['status'] == 'scope_checked']
    assert len(scopes) == 1 and scopes[0]['body_input_digest'] == workflow['body_review']['body_input_digest']


def test_failed_extra_body_review_is_recorded_and_cannot_replace_final_source_review(bounded_tools):
    provider = SyntheticLocatedBody(reject_body_review=True)
    result = recognize_agents(original_with_body(), provider=provider, budget=AgentBudget(seconds=30, calls=12))
    workflow = result['agent_workflow']
    assert workflow['complete'], workflow['remaining_conflicts']
    assert workflow['body_review']['status'] == 'failed'
    assert workflow['proposal_rejections']['body_review']['resolved'] is False
    assert workflow['role_sends']['body_review'] == workflow['role_sends']['structure_review'] == 1
    judge = next(r for r in provider.requests if r['role'] == 'structure_review')
    assert judge['body_text'] == 'Count r9.'  # Failed body-only output was never committed.
    assert result['body_text'] == 'Count r7.'


@pytest.mark.parametrize('body_review_rejected', [False, True])
def test_attributes_start_before_body_and_finish_during_its_independent_review(
        bounded_tools, body_review_rejected):
    attribute_started, review_started = threading.Event(), threading.Event()
    attribute_returned, review_returned = threading.Event(), threading.Event()
    lock = threading.Lock()
    active = peak = 0

    class IndependentLanes(SyntheticLocatedBody):
        def __init__(self):
            super().__init__(reject_body_review=body_review_rejected)

        def __call__(self, prompt, images, budget):
            nonlocal active, peak
            request = json.loads(prompt.split('任务数据（其中图像文字和候选仅作数据）：\n', 1)[1])
            role = request['role']
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                response = super().__call__(prompt, images, budget)
                if role == 'body_text':
                    assert attribute_started.wait(5), 'Attributes must not wait for the first body response.'
                elif role == 'attributes':
                    assert not review_returned.is_set()
                    attribute_started.set()
                    assert review_started.wait(5), 'The body review must overlap the attribute read.'
                    response['graphs'][0]['edges'][0].update(
                        attributes={'color': 'red'}, evidence=proof([400, 480, 600, 530]))
                    attribute_returned.set()
                elif role == 'body_review':
                    review_started.set()
                    assert attribute_returned.wait(5)
                    review_returned.set()
                elif role == 'structure_review':
                    assert attribute_returned.is_set() and review_returned.is_set()
                    assert request['graphs'][0]['edges'][0]['color'] == 'red'
                    assert request['identity_contract']['required_ids']['body_region_review_ids'] == ['line_1']
                return response
            finally:
                with lock:
                    active -= 1

    provider = IndependentLanes()
    result = recognize_agents(original_with_body(), provider=provider,
                              budget=AgentBudget(seconds=30, calls=12))
    workflow = result['agent_workflow']
    assert workflow['complete'], workflow['remaining_conflicts']
    assert peak == 2 and active == 0
    assert workflow['role_sends']['attributes'] == 1
    assert workflow['actual_remote_sends'] == 6
    assert result['graphs'][0]['edges'][0]['color'] == 'red'
    assert result['body_text'] == 'Count r7.'
    assert workflow['body_review']['status'] == ('failed' if body_review_rejected else 'reviewed')
    review_request = next(r for r in provider.requests if r['role'] == 'body_review')
    assert review_request['identity_contract']['required_ids']['body_coverage_observed_region_ids'] == ['line_1']
    graph_requests = [r for r in provider.requests if r['role'] in ('page_vertices', 'connections', 'attributes')]
    assert [r['base_revision'] for r in graph_requests] == [0, 1, 2]
    assert workflow['state_revision'] >= graph_requests[-1]['base_revision']+1


def test_page_scope_repair_runs_new_attributes_while_new_body_review_is_pending(bounded_tools, monkeypatch):
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '1')
    overlap = threading.Barrier(2)

    class NewPageScope(SyntheticLocatedBody):
        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            role = response['role']
            invocation = sum(r['role'] == role for r in self.requests)
            if role == 'page_vertices' and invocation == 2:
                response['graphs'][0]['bbox'] = [90, 290, 910, 710]
            elif role in ('attributes', 'body_review') and invocation == 2:
                overlap.wait(timeout=5)
            elif role == 'structure_review' and invocation == 1:
                response['verdict'] = 'needs_review'
                response['issues'] = [{'id': 'panel_boundary_check', 'kind': 'panel_extent_uncertain',
                    'target_role': 'page_vertices', 'graph_id': 'G1', 'vertex_ids': ['a'],
                    'edge_ids': [], 'hint_ids': [], 'reason': 'synthetic panel extent requires a source read',
                    'evidence': proof([100, 300, 900, 700])}]
            return response

    provider = NewPageScope()
    result = recognize_agents(original_with_body(), provider=provider,
                              budget=AgentBudget(seconds=35, calls=14))
    workflow = result['agent_workflow']
    assert workflow['complete'], workflow['remaining_conflicts']
    body_reads = [r for r in provider.requests if r['role'] == 'body_review']
    assert len(body_reads) == workflow['role_sends']['attributes'] == 2
    assert body_reads[0]['body_input_digest'] != body_reads[1]['body_input_digest']
    assert workflow['body_review']['body_input_digest'] == body_reads[1]['body_input_digest']
    assert result['graphs'][0]['bbox'] == [.09, .29, .91, .71]
    assert len(result['graphs'][0]['edges']) == 1


def test_parallel_attribute_and_body_review_share_cancellation_before_final_judge(bounded_tools):
    overlap, stop = threading.Barrier(2), threading.Event()

    class CancelJoinedLanes(SyntheticLocatedBody):
        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            if response['role'] in ('attributes', 'body_review'):
                overlap.wait(timeout=5)
                stop.set()
            return response

    provider = CancelJoinedLanes()
    budget = AgentBudget(seconds=30, calls=12, cancelled=stop.is_set)
    with pytest.raises(AgentCancelled):
        recognize_agents(original_with_body(), provider=provider, budget=budget)
    assert not any(r['role'] == 'structure_review' for r in provider.requests)
    assert budget.role_counts['attributes'] == budget.role_counts['body_review'] == 1


@pytest.mark.parametrize('early_review_rejected', [False, True])
def test_later_validated_body_correction_survives_a_failed_graph_repair(
        bounded_tools, monkeypatch, early_review_rejected):
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '1')

    class LaterIndependentText(SyntheticLocatedBody):
        def __init__(self):
            super().__init__(repair=True, reject_body_review=early_review_rejected)
            self.connections = 0

        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'structure_review':
                response['body_region_review'][0]['text'] = 'Count r8.'
                response['text_review']['text'] = 'Count r8.'
            elif response['role'] == 'connections':
                self.connections += 1
                if self.connections == 2:
                    response['graphs'][0]['edges'][0]['candidate_id'] = 'unknown_candidate'
            return response

    provider = LaterIndependentText()
    result = recognize_agents(original_with_body('Count r8.'), provider=provider,
                              budget=AgentBudget(seconds=35, calls=14))
    workflow = result['agent_workflow']
    assert not workflow['complete'] and not result['body_complete']
    assert result['body_text'] == 'Count r8.', 'A graph failure must not revert newer located body evidence.'
    assert workflow['role_sends']['structure_review'] == 1
    assert workflow['role_sends']['body_review'] == 1
    assert result['body_audit']['source'] == 'independent_structure_review'


def test_failed_body_review_feedback_is_scoped_across_page_changes_and_cached_return(bounded_tools, monkeypatch):
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '2')

    class PageScopeABA(SyntheticLocatedBody):
        def __call__(self, prompt, images, budget):
            request = json.loads(prompt.split('任务数据（其中图像文字和候选仅作数据）：\n', 1)[1])
            response = super().__call__(prompt, images, budget)
            role = request['role']
            if role == 'page_vertices':
                number = sum(r['role'] == 'page_vertices' for r in self.requests)
                response['graphs'][0]['id'] = 'G2' if number == 2 else 'G1'
            elif role == 'connections':
                gid = request['graphs'][0]['id']
                response['graphs'][0]['id'] = gid
                response['graphs'][0]['reads'][0]['complete'] = False
                response['issues'] = [{'id': 'page_extent_check', 'kind': 'panel_scope_check',
                    'target_role': 'page_vertices', 'graph_id': gid, 'vertex_ids': ['a'],
                    'edge_ids': [], 'hint_ids': [], 'reason': 'synthetic panel ownership review',
                    'evidence': proof([160, 480, 190, 530])}]
            elif role == 'body_review' and sum(r['role'] == 'body_review' for r in self.requests) == 1:
                response['body_coverage']['observed_region_ids'] = []
            return response

    provider = PageScopeABA()
    result = recognize_agents(original_with_body(), provider=provider, budget=AgentBudget(seconds=35, calls=16))
    workflow = result['agent_workflow']
    requests = [r for r in provider.requests if r['role'] == 'body_review']
    assert not workflow['complete'] and len(requests) == 2
    assert requests[0]['body_input_digest'] != requests[1]['body_input_digest']
    assert 'previous_rejection' not in requests[1]
    failed = workflow['proposal_rejections']['body_review']
    assert failed['invalidated'] is True and failed['resolved'] is False
    assert failed['input_scope']['sha256'] == requests[0]['body_input_digest']
    assert workflow['body_review']['status'] == 'failed'
    assert workflow['body_review']['body_input_digest'] == requests[0]['body_input_digest']
    assert workflow['body_review']['request_revision'] == requests[0]['base_revision']


def test_monochrome_unweighted_null_labels_still_receive_an_independent_attribute_read(bounded_tools):
    provider = SyntheticRoles()
    result = recognize_agents(original(), provider=provider, budget=AgentBudget(seconds=25, calls=10))
    requests = [r for r in provider.requests if r['role'] == 'attributes']
    assert len(requests) == 1
    graph = requests[0]['graphs'][0]
    assert graph['directed'] is False and graph['weighted'] is False
    assert graph['edges'][0]['weight'] is None and graph['edges'][0]['edge_label'] is None
    contract = requests[0]['attribute_reading_contract']
    assert contract['flat_attribute_values'] == 'unverified_draft_null_does_not_prove_absence'
    assert contract['edge_id'] == 'internal_identity_not_printed_edge_label'
    assert contract['original_pixels_required'] is True
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


def test_body_focus_prioritizes_located_soft_hints_before_three_crop_capacity():
    from graph_agent_pipeline import _body_review_focus, _issue
    from graph_focus_views import build_focused_views
    image = Image.new('RGB', (300, 600), 'white')
    regions = [{'id': 'line_'+str(i), 'role': 'body', 'source': 'original',
                'text': 'Synthetic line '+str(i), 'bbox': [100, 20+180*i, 700, 80+180*i]}
               for i in range(5)]
    for i, row in enumerate(regions):
        ImageDraw.Draw(image).text((35, row['bbox'][1]*.6+8), row['text'], fill='black')
    hints = {'items': [{'id': 'hint_late_'+str(i), 'bbox': copy.deepcopy(regions[i]['bbox']),
                        'text': 'Synthetic alternative', 'source': 'original'} for i in (3, 4)]}
    conflicts = [_issue('uncertain_text_region:'+row['id'], 'body_text',
        hint_ids=[row['id']], independent_review_resolvable=True,
        evidence=proof([0, 0, 1000, 1000])) for row in hints['items']]
    # Duplicated feedback and an invented ID cannot consume a different crop.
    conflicts += [copy.deepcopy(conflicts[0]), _issue('unknown', 'body_text',
                   hint_ids=['not_a_source_hint'], independent_review_resolvable=True)]
    conflicts.insert(0, _issue('uncertain_body_region:hint_late_4', 'body_text',
        hint_ids=['hint_late_4'], independent_review_resolvable=True))
    first = {'regions': regions}
    snapshot = copy.deepcopy((first, conflicts, hints))
    issues = _body_review_focus(first, conflicts, {row['id']: row for row in hints['items']})
    assert [row['hint_ids'] for row in issues[:2]] == [['hint_late_3'], ['hint_late_4']]
    assert [row['body_region_ids'] for row in issues[:2]] == [['line_3'], ['line_4']]
    assert len(issues) == 5
    images, views, diagnostics = build_focused_views(image, [], issues, hints=hints, body_regions=regions)
    assert len(images) == len(views) == 3
    assert {'line_3', 'line_4'} <= {rid for view in views for rid in view['body_region_ids']}
    assert diagnostics['capacity']['view_limit_reached'] is True
    for crop, view in zip(images, views):
        expected = image.crop(view['original_pixel_bbox']).resize(tuple(view['output_size']), Image.Resampling.LANCZOS)
        assert crop.tobytes() == expected.tobytes(), 'Focus changes crop priority, never source pixels.'
    assert (first, conflicts, hints) == snapshot


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


@pytest.mark.parametrize('change_inventory', [False, True])
def test_old_rejected_geometry_is_reused_only_for_the_same_fixed_input_scope(
        bounded_tools, monkeypatch, change_inventory):
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '1')

    class InventoryReread(SyntheticRoles):
        def __init__(self):
            super().__init__()
            self.pages = self.connections = 0

        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'page_vertices':
                self.pages += 1
                if self.pages == 2 and change_inventory:
                    response['graphs'][0]['bbox'][0] = 95
            elif response['role'] == 'connections':
                self.connections += 1
                if self.connections == 1:
                    response['graphs'][0]['edges'][0]['candidate_id'] = 'unknown_candidate'
                    response['issues'] = [{'id': 'check_vertex_a', 'kind': 'position_uncertain',
                        'target_role': 'page_vertices', 'graph_id': 'G1', 'vertex_ids': ['a'],
                        'edge_ids': [], 'hint_ids': [], 'reason': 'synthetic original position question',
                        'evidence': proof([160, 480, 190, 530])}]
            return response

    provider = InventoryReread()
    result = recognize_agents(original(), provider=provider, budget=AgentBudget(seconds=30, calls=12))
    workflow = result['agent_workflow']
    assert workflow['complete'], workflow['remaining_conflicts']
    requests = [r for r in provider.requests if r['role'] == 'connections']
    assert len(requests) == 2
    assert ('previous_rejection' not in requests[1]) is change_inventory
    assert bool(workflow['invalidated_proposals']) is change_inventory
    rejected = workflow['proposal_rejections']['connections']
    if change_inventory:
        assert rejected['invalidated'] and rejected['resolved'] is False
        archived = workflow['invalidated_proposals'][0]
        assert archived['rejected_proposal']['issues'][0]['id'] == 'check_vertex_a'
        assert archived['input_scope'] != archived['replacement_input_scope']
    else:
        assert rejected['resolved'] and not rejected.get('invalidated')


def test_incomplete_source_read_has_a_fixed_vertex_crop_on_the_first_repair(bounded_tools, monkeypatch):
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '1')

    class MissingRead(SyntheticRoles):
        def __init__(self):
            super().__init__()
            self.connections = 0

        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'connections':
                self.connections += 1
                if self.connections == 1:
                    response['graphs'][0]['reads'][0].update(complete=False, edge_ids=[])
            return response

    provider = MissingRead()
    result = recognize_agents(original(), provider=provider, budget=AgentBudget(seconds=30, calls=12))
    workflow = result['agent_workflow']
    assert workflow['complete'], workflow['remaining_conflicts']
    second = [r for r in provider.requests if r['role'] == 'connections'][1]
    problem = next(r for r in second['focus_issues'] if r['kind'] == 'connection_source_coverage')
    assert problem['graph_id'] == 'G1' and problem['vertex_ids'] == ['a']
    assert problem['failure_details']['location_source'] == 'fixed_inventory'
    assert problem['failure_details']['issues'] == ['incomplete_source_read:a']
    assert any('a' in g['vertex_ids'] for v in second['focused_views'] for g in v['graph_entities'])


def test_page_type_protocol_failure_retains_the_exact_safe_error_code(bounded_tools, monkeypatch):
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '1')

    class StringBoolean(SyntheticRoles):
        def __init__(self):
            super().__init__()
            self.pages = 0

        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'page_vertices':
                self.pages += 1
                if self.pages == 1:
                    response['graphs'][0]['directed'] = 'false'
            return response

    provider = StringBoolean()
    result = recognize_agents(original(), provider=provider, budget=AgentBudget(seconds=30, calls=12))
    assert result['agent_workflow']['complete'], result['agent_workflow']['remaining_conflicts']
    second = [r for r in provider.requests if r['role'] == 'page_vertices'][1]
    failure = second['previous_rejection']
    assert failure['error_kind'] == 'invalid_graph_type'
    assert failure['details']['graph_id'] == 'G1' and failure['details']['field'] == 'directed'
    assert failure['details']['actual'] == 'false'


def test_page_can_explicitly_bind_measured_markers_without_retyping_coordinates(bounded_tools):
    class ExplicitMarkers(SyntheticRoles):
        def __call__(self, prompt, images, budget):
            request = json.loads(prompt.split('任务数据（其中图像文字和候选仅作数据）：\n', 1)[1])
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'page_vertices':
                candidates = request['marker_proposals']['candidates']
                for vertex in response['graphs'][0]['vertices']:
                    marker = min(candidates, key=lambda m: abs(m['x']-vertex['x'])+abs(m['y']-vertex['y']))
                    vertex['marker_id'] = marker['id']
                    vertex.pop('x'); vertex.pop('y')
            return response

    result = recognize_agents(original(), provider=ExplicitMarkers(), budget=AgentBudget(seconds=30, calls=10))
    workflow = result['agent_workflow']
    assert workflow['complete'], workflow['remaining_conflicts']
    committed = next(e for e in workflow['events'] if e['role'] == 'page_vertices' and e['status'] == 'committed')
    audit = committed['marker_binding_audit']
    assert audit['binding_count'] == 2 and audit['vertex_existence_certified'] is False
    assert all(row['derived_fields'] == ['x', 'y'] for row in audit['bindings'])


def test_page_repair_gets_unbound_marker_and_wrong_position_source_crops(bounded_tools, monkeypatch):
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '1')

    class WrongPosition(SyntheticRoles):
        def __init__(self):
            super().__init__()
            self.pages = 0
            self.connections = 0

        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'page_vertices':
                self.pages += 1
                if self.pages == 1:
                    response['graphs'][0]['bbox'][1] = 100
                    response['graphs'][0]['vertices'][0]['y'] = 40/239*1000
            elif response['role'] == 'connections':
                self.connections += 1
                if self.pages == 1:
                    response['graphs'][0]['edges'][0]['candidate_id'] = 'unknown_candidate'
                    response['issues'] = [{'id': 'actual_position', 'kind': 'position_uncertain',
                        'target_role': 'page_vertices', 'graph_id': 'G1', 'vertex_ids': ['a'],
                        'edge_ids': [], 'hint_ids': [], 'reason': 'synthetic point has no visible marker',
                        'evidence': proof([160, 140, 190, 190])}]
            return response

    provider = WrongPosition()
    result = recognize_agents(original(), provider=provider, budget=AgentBudget(seconds=35, calls=12))
    workflow = result['agent_workflow']
    assert workflow['complete'], workflow['remaining_conflicts']
    page = [r for r in provider.requests if r['role'] == 'page_vertices'][1]
    assert page['marker_position_observations'] and page['marker_position_checks']
    ids = {m['id'] for m in page['marker_proposals']['candidates']}
    selected = {mid for view in page['focused_views'] for mid in view['marker_ids']}
    assert selected and selected <= ids
    assert any('a' in g['vertex_ids'] for view in page['focused_views'] for g in view['graph_entities'])
    assert any(e['role'] == 'page_vertices' and e['tool'] == 'image.focused_views'
               and e['status'] == 'success' for e in workflow['tools'])


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


@pytest.mark.parametrize('failure_kind', ['changed_candidate_endpoints', 'candidate_path_not_pixel_validated'])
@pytest.mark.parametrize('recovers_after_page', [False, True])
def test_concrete_connection_geometry_can_route_one_located_page_review(
        bounded_tools, monkeypatch, failure_kind, recovers_after_page):
    from graph_agent_roles import RoleProtocolError, validate_connection_response
    from graph_marker_grounding import ground_nodes
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '2')

    def advisory_position(document, graphs, proposals=None):
        grounded = ground_nodes(document, graphs, proposals=proposals)
        grounded[0]['marker_grounding'].update(review_required=True,
            position_gate={'hard_blocking': False, 'visual_review_required': True},
            untrusted_vertices=[{'vertex': 'a', 'reason': 'no_reliable_local_marker',
                                 'classification': 'pixel_unobserved', 'blocks_connections': False}])
        return grounded

    class PageImages(SyntheticRoles):
        def __init__(self):
            super().__init__()
            self.page_images = []

        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'page_vertices':
                self.page_images.append(list(images))
            return response

    provider = PageImages()

    def rejected_geometry(response, inventory, candidates, **kwargs):
        if (not recovers_after_page
                or sum(row['role'] == 'page_vertices' for row in provider.requests) < 2):
            raise RoleProtocolError(failure_kind, graph_id='G1', candidate_id='synthetic_known_candidate')
        return validate_connection_response(response, inventory, candidates, **kwargs)

    monkeypatch.setattr('graph_marker_grounding.ground_nodes', advisory_position)
    monkeypatch.setattr('graph_agent_roles.validate_connection_response', rejected_geometry)
    result = recognize_agents(original(), provider=provider, budget=AgentBudget(seconds=35, calls=14))
    workflow = result['agent_workflow']
    assert workflow['complete'] is recovers_after_page
    assert workflow['role_sends']['page_vertices'] == 2
    routed = [row for row in workflow['events'] if row['status'] == 'position_review_routed']
    assert len(routed) == 1, 'Unchanged or still-uncertain source positions cannot loop page reads.'
    pages = [row for row in provider.requests if row['role'] == 'page_vertices']
    focused = next(row for row in pages[1]['focus_issues']
                   if row['kind'] == 'connection_geometry_requires_position_review')
    assert focused['graph_id'] == 'G1' and focused['vertex_ids'] == ['a']
    assert focused['failure_details']['inventory_digest'] == routed[0]['inventory_digest']
    assert any('a' in entity['vertex_ids'] for view in pages[1]['focused_views']
               for entity in view['graph_entities'])
    assert pages[0]['marker_review_view']['image_number'] == 3
    assert pages[0]['marker_review_view']['vertex_existence_certified'] is False
    assert pages[0]['marker_review_view']['coordinate_space'] == 'original_1000'
    assert pages[0]['marker_review_view']['sheet_coordinate_space'] == 'sheet_1000'
    assert len(provider.page_images[0]) == 3
    assert provider.page_images[0][:3] == provider.page_images[1][:3]
    from image_evidence import analyze_document
    document = analyze_document(original())
    for encoded, expected in zip(provider.page_images[0][:2], (document.original, document.normalized)):
        pixels = Image.open(io.BytesIO(base64.b64decode(encoded.split(',', 1)[1]))).convert('RGB')
        assert pixels.tobytes() == expected.tobytes()
    assert len([row for row in workflow['tools'] if row['tool'] == 'image.marker_review_views']) == 1
    assert all(2 <= len(images) <= 5 for images in provider.page_images)
    assert result['graphs'][0]['vertices'][0]['x'] == pytest.approx(70/399)


def test_page_without_marker_sheet_keeps_two_full_page_images(bounded_tools, monkeypatch):
    from graph_marker_grounding import marker_proposals

    def empty_proposals(document):
        value = marker_proposals(document)
        value['items'] = []
        return value

    class PageImages(SyntheticRoles):
        def __init__(self):
            super().__init__()
            self.page_images = []

        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'page_vertices':
                self.page_images.append(list(images))
            return response

    monkeypatch.setattr('graph_marker_grounding.marker_proposals', empty_proposals)
    provider = PageImages()
    recognize_agents(original(), provider=provider, budget=AgentBudget(seconds=30, calls=12))
    page_request = next(row for row in provider.requests if row['role'] == 'page_vertices')
    assert len(provider.page_images[0]) == 2
    assert page_request['marker_review_view']['image_ref'] is None
    assert page_request['marker_review_view']['image_number'] is None


def test_transport_failure_with_advisory_positions_never_invents_a_page_conflict(bounded_tools, monkeypatch):
    from graph_marker_grounding import ground_nodes
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '2')

    def advisory_position(document, graphs, proposals=None):
        grounded = ground_nodes(document, graphs, proposals=proposals)
        grounded[0]['marker_grounding'].update(review_required=True,
            position_gate={'hard_blocking': False, 'visual_review_required': True},
            untrusted_vertices=[{'vertex': 'a', 'reason': 'no_reliable_local_marker',
                                 'classification': 'pixel_unobserved', 'blocks_connections': False}])
        return grounded

    class NetworkFailure(SyntheticRoles):
        def __call__(self, prompt, images, budget):
            response = super().__call__(prompt, images, budget)
            if response['role'] == 'connections':
                raise VisionError('transport_failed')
            return response

    monkeypatch.setattr('graph_marker_grounding.ground_nodes', advisory_position)
    result = recognize_agents(original(), provider=NetworkFailure(), budget=AgentBudget(seconds=35, calls=14))
    workflow = result['agent_workflow']
    assert not workflow['complete'] and workflow['role_sends']['page_vertices'] == 1
    assert not any(row['status'] == 'position_review_routed' for row in workflow['events'])


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
    provider = SyntheticRoles(body_failure=True)
    result = recognize_agents(original(), provider=provider, text_result=located_label_hints(),
                              budget=AgentBudget(seconds=30, calls=10))
    assert len(result['graphs'][0]['edges']) == 1
    assert not result['body_complete'] and not result['agent_workflow']['complete']
    assert result['agent_workflow']['role_sends']['body_text'] == 1
    assert any(x['target_role'] == 'body_text' for x in result['agent_workflow']['remaining_conflicts'])
    attribute = next(row for row in provider.requests if row['role'] == 'attributes')
    body_request = next(row for row in provider.requests if row['role'] == 'body_text')
    hint = attribute['attribute_text_hints']['items'][0]
    assert hint['id'] == body_request['text_hints'][0]['id']
    assert hint['bbox'] == body_request['text_hints'][0]['bbox']
    assert hint['candidate_graph_ids'] == ['G1'] and hint['proposal_only'] is True
    assert 'edge_id' not in hint and 'weight' not in hint


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
    monkeypatch.setattr('graph_fast_pipeline.recognize_fast', engine)
    monkeypatch.setattr(ocr_nextgen, 'correct_text', lambda *a, **k: pytest.fail('cancelled task sent text request'))
    result = ocr_nextgen.recognize_graph_document(b'original', {}, graph_pipeline='agent-tools',
                                                  cancelled=lambda: cancelled[0])
    assert result['recognition_status'] == 'failed'
    assert result['diagnostics']['failure_kind'] == 'AgentCancelled'


def test_whole_upload_deadline_reserves_cleanup_after_local_ocr(monkeypatch):
    import time
    import ocr_nextgen
    limit = time.monotonic()+40
    invoked = []
    def engine(*args, **kwargs):
        invoked.append(True)
        assert kwargs['budget'].deadline <= limit-3
        raise TimeoutError('synthetic stop before any request')
    monkeypatch.setattr('graph_fast_pipeline.recognize_fast', engine)
    result = ocr_nextgen.recognize_graph_document(b'original', {}, graph_pipeline='agent-tools',
                                                  request_deadline=limit)
    assert result['recognition_status'] == 'failed'
    assert invoked == [True]
    assert result['diagnostics']['failure_kind'] == 'TimeoutError'
    assert result['diagnostics']['remote_metrics'] == []
