"""Synthetic role/transport boundaries; never a model-accuracy certificate."""
import copy
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
            return {**result, 'verdict': 'needs_review' if issues else 'accept',
                'page_coverage': {'complete': True, 'graph_ids': ['G1'], 'evidence': proof()},
                'graphs': [{'id': g['id'], 'vertex_ids': [v['id'] for v in g['vertices']],
                    'edge_ids': [e['id'] for e in g['edges']], 'verdict': 'accept', 'evidence': proof(g['bbox'])}
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
    assert workflow['actual_remote_sends'] == 4
    assert set(workflow['role_sends']) == {'page_vertices', 'body_text', 'connections', 'structure_review'}
    assert len({m['task_id'] for m in result['remote_metrics']}) == 1
    assert all(m['source_sha256'] == workflow['source_sha256'] for m in result['remote_metrics'])
    assert result['graphs'][0]['complete'] is True
    assert len(result['graphs'][0]['edges']) == 1
    assert {'image.marker_grounding', 'image.trace_candidates', 'image.sknw_candidates',
            'graph.stroke_validation', 'graph.structure_audit', 'text.visual_reconciliation'} <= {
                x['tool'] for x in workflow['tools']}


def test_concrete_review_conflict_routes_back_with_fixed_edge_ids(bounded_tools, monkeypatch):
    monkeypatch.setenv('DMATE_AGENT_REVIEW_ROUNDS', '1')
    provider = SyntheticRoles(repair=True)
    result = recognize_agents(original(), provider=provider, budget=AgentBudget(seconds=30, calls=10))
    workflow = result['agent_workflow']
    assert workflow['complete'], workflow['remaining_conflicts']
    assert workflow['repair_rounds'] == 1 and workflow['actual_remote_sends'] == 6
    connections = [r for r in provider.requests if r['role'] == 'connections']
    assert len(connections) == 2
    assert connections[1]['focus_issues'][0]['id'] == 'connection_check'
    assert connections[1]['previous_graphs'][0]['edges'][0]['id'] == 'edge_1'
    assert connections[1]['base_revision'] > connections[0]['base_revision']


def test_pixel_support_and_accepting_judge_cannot_erase_attribute_uncertainty(bounded_tools):
    result = recognize_agents(original(), provider=SyntheticRoles(attribute_uncertain=True),
                              budget=AgentBudget(seconds=30, calls=10))
    assert result['graphs'][0]['edges'], 'Known pixel-supported lines must survive.'
    assert result['graphs'][0]['complete'] is False
    assert not result['agent_workflow']['complete']
    assert any(i['target_role'] == 'attributes' for i in result['agent_workflow']['remaining_conflicts'])


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
