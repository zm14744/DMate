"""Fast editable orchestration contracts; synthetic responses are not accuracy evidence."""
import base64
import copy
import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image

import graph_fast_pipeline as fast
from graph_agent_runtime import AgentCancelled
from vision_provider import GLM_5V_TURBO_MODEL, VisionError


def document():
    return {'body_text': '求两图中各顶点的度数；虚线表示可选边。', 'graphs': [
        {'id': 'G1', 'name': '(a)', 'directed': False,
         'vertices': [{'id': 'a', 'label': 'a'}, {'id': 'b', 'label': 'b'}, {'id': 'z', 'label': None}],
         'edges': [{'id': 'e1', 'from': 'a', 'to': 'b', 'direction': 'undirected', 'weight': 0, 'style': 'dashed'},
                   {'id': 'e2', 'from': 'a', 'to': 'b', 'direction': 'undirected', 'weight': 7, 'style': 'solid'},
                   {'id': 'e3', 'from': 'a', 'to': 'a', 'direction': 'undirected', 'style': 'solid'}]},
        {'id': 'G2', 'name': '(b)', 'directed': True,
         'vertices': [{'id': 'a', 'label': 'a'}, {'id': 'b', 'label': 'b'}],
         'edges': [{'id': 'arrow', 'from': 'b', 'to': 'a', 'direction': 'forward', 'weight': -3, 'style': 'solid'}]}],
        'uncertainties': []}


class Provider:
    name, model, retries = 'qwen', 'qwen3-vl-plus', 0

    def __init__(self, output, *, available=True):
        self.output, self.is_available, self.requests = output, available, []

    def available(self):
        return self.is_available

    def __call__(self, prompt, images, budget):
        budget.take()
        request = json.loads(prompt.rsplit('\n', 1)[1])
        self.requests.append(request)
        assert images and images[0].startswith('data:image/png;base64,')
        budget.metrics.append({'provider': self.name, 'status': 200, 'fixture_only': True})
        if isinstance(self.output, Exception):
            raise self.output
        return copy.deepcopy(self.output(request) if callable(self.output) else self.output)


class Specialist(Provider):
    name, model = 'glm', GLM_5V_TURBO_MODEL


class Handle:
    def __init__(self, policy, raw):
        self.policy, self.raw, self.closed, self.joined = policy, raw, False, False

    def done(self):
        return self.joined

    def snapshot(self):
        return {'text': {}, 'layout': {}, 'geometry': {}, 'status': 'running',
                'resource_metrics': [], 'tool_audit': []}

    def result(self):
        self.joined = True
        return {**self.snapshot(), 'status': 'completed',
            'text': {'text': '', 'text_hints': [], 'text_evidence': {},
                     'diagnostics': {'model_executed_this_call': True}},
            'geometry': {'graphs': [], 'document': object()} if self.policy.get('paths') else {}}

    def close(self):
        self.closed = True
        return self.result()

    def audit(self):
        stages = [key for key in ('text', 'layout') if self.policy.get(key)]
        if self.policy.get('paths'):
            stages.append('geometry')
        return {'stages': [{'stage': key, 'status': 'ok'} for key in stages],
                'source_sha256': hashlib.sha256(self.raw).hexdigest()}


@pytest.fixture
def prepared(monkeypatch):
    stream = io.BytesIO()
    Image.new('RGB', (24, 20), 'white').save(stream, 'PNG')
    raw = stream.getvalue()
    encoded = 'data:image/png;base64,'+base64.b64encode(raw).decode()
    quick = {'images': [encoded], 'view_descriptions': ['完整原图'], 'panels': [], 'body_regions': [],
        'layout': {'status': 'not_requested', 'regions': []}, 'resource_metrics': [], 'tool_audit': [],
        'diagnostics': {'original_size': [24, 20], 'cv_executed': True}}
    import graph_semantic_layout, graph_semantic_geometry, graph_semantic_question_reference, graph_visual_inventory
    monkeypatch.setattr(graph_semantic_layout, 'prepare_semantic_layout', lambda *a, **kw: copy.deepcopy(quick))
    monkeypatch.setattr(graph_semantic_geometry, 'prepare_semantic_geometry', lambda *a, **kw: {
        'marker_candidates': [], 'diagnostics': [], 'tool_audit': []})
    monkeypatch.setattr(graph_visual_inventory, 'measure_visual_inventory', lambda *a, **kw: {
        'status': 'measured', 'panels': [], 'diagnostics': [], 'proposal_only': True,
        'tool_audit': [{'tool': 'image.visual_marker_inventory', 'status': 'success', 'executed': True}]})
    monkeypatch.setattr(graph_semantic_question_reference, 'start_question_reference',
                        lambda *a, **kw: pytest.fail('Recognition must not call DeepSeek'))
    import requests
    monkeypatch.setattr(requests.sessions.Session, 'send', lambda *a, **kw: pytest.fail('No live network in contracts'))
    handles = []

    def submit(raw, **kwargs):
        handle = Handle(kwargs['policy'], raw)
        handles.append(handle)
        return handle

    def run(main=None, specialist=None, **kwargs):
        ordinary = main if isinstance(main, Provider) else Provider(main or document())
        provider = {'fast_main': ordinary,
                    'fast_local_review': specialist or Specialist({}, available=False)}
        return fast.recognize_fast(raw, provider=provider, local_submit=submit, **kwargs), ordinary

    return raw, run, handles


def test_clean_upload_is_one_main_call_with_actual_final_program_validation(prepared):
    _, run, handles = prepared
    specialist = Specialist(AssertionError('Unneeded specialist call'))
    result, main = run(specialist=specialist)
    assert [row['role'] for row in main.requests] == ['fast_main']
    assert specialist.requests == []
    assert result['complete'] is True and result['confirmation_required'] is True
    workflow = result['semantic_workflow']
    assert workflow['role_counts'] == {'fast_main': 1}
    assert workflow['question_reference']['remote_calls'] == 0
    assert workflow['local_review']['status'] == 'not_needed'
    assert workflow['final_validation']['phase'] == 'final'
    assert workflow['final_validation']['schema_valid'] is True
    assert any(row.get('library') == 'networkx' and row.get('executed') for row in workflow['final_validation']['tool_audit'])
    assert result['body_audit']['second_pass_reviewed'] is False
    assert handles[0].closed and handles[0].policy == {'text': True, 'layout': False, 'paths': False, 'sknw': False}
    assert len(result['graphs'][0]['edges']) == 3
    assert result['graphs'][0]['vertices'][-1]['isolated_confirmed'] is True
    assert [edge['weight'] for edge in result['graphs'][0]['edges'][:2]] == [0, 7]
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(('field', 'legend'), [
    ('color', '绿色边表示树边，黑色边表示其余边。'),
    ('style', '虚线表示可选边，实线表示其余边。'),
])
@pytest.mark.parametrize('review_available', [False, True])
def test_required_visual_attributes_stay_pending_until_actually_read(prepared, field, legend, review_available):
    _, run, handles = prepared
    initial = document()
    initial['body_text'] = '观察两幅图。' + legend + '回答问题。'
    initial['text_context'] = {'legends': [{'text': legend, 'graph_ids': ['G2']}]}
    initial['graphs'][1]['edges'][0].pop(field, None)
    glm = Specialist({'graphs': [copy.deepcopy(initial['graphs'][1])], 'uncertainties': []},
                     available=review_available)
    result, main = run(Provider(initial), glm)
    assert len(main.requests) == 1 and len(glm.requests) == int(review_available)
    assert result['complete'] is False and result['graphs'][0]['complete'] is True
    assert result['graphs'][1]['complete'] is False and result['body_complete'] is True
    expected = 'required_' + field + '_unresolved'
    issues = [row for row in result['semantic_issues'] if row['kind'] == expected]
    assert len(issues) == 1 and issues[0]['graph_id'] == 'G2' and issues[0]['edge_ids'] == ['arrow']
    assert result['graphs'][1]['edges'][0][field] == 'unknown'
    workflow = result['semantic_workflow']
    assert workflow['final_validation']['status'] == 'completed'
    assert workflow['performance']['completed'] is False
    assert workflow['performance']['within_target'] is False
    assert any(row['kind'] == expected for row in workflow['final_validation']['issues'])
    assert workflow['local_review']['targets']['graph_ids'] == ['G2']
    if review_available:
        assert any(row['kind'] == expected for row in glm.requests[0]['issues'])
    assert len(handles) == 1  # Required color/style does not schedule topology tracing.


def test_required_attributes_can_clear_in_same_review_with_advisory_marker_candidates(prepared, monkeypatch):
    _, run, handles = prepared
    import graph_semantic_geometry
    markers = [{'id': f'circle-{i}', 'position': [100+i*100, 500],
                'radius_x': 18, 'radius_y': 18, 'confidence': .97, 'proposal_only': True}
               for i in range(6)] + [
                {'id': 'glyph', 'position': [50, 30], 'radius_x': 3,
                 'radius_y': 3, 'confidence': .8, 'proposal_only': True}]
    monkeypatch.setattr(graph_semantic_geometry, 'prepare_semantic_geometry', lambda *a, **kw: {
        'marker_candidates': copy.deepcopy(markers), 'diagnostics': [], 'tool_audit': []})
    initial = document()
    legend = '绿边表示树边，黑色虚线表示其余边。'
    initial['body_text'] = '观察两幅图。' + legend
    initial['text_context'] = {'legends': [{'text': legend, 'graph_ids': ['G2']}]}
    initial['graphs'][1]['edges'][0].pop('style')
    corrected = copy.deepcopy(initial['graphs'][1])
    corrected['edges'][0].update(color='green', style='solid')
    glm = Specialist({'graphs': [corrected], 'uncertainties': []})
    result, main = run(Provider(initial), glm)
    assert len(main.requests) == len(glm.requests) == 1
    assert glm.requests[0]['local_marker_candidates'] == markers
    assert glm.requests[0]['targets']['graph_ids'] == ['G2']
    assert result['complete'] is True and result['semantic_issues'] == []
    # Candidates guide visual checking; their count never overwrites the read.
    assert len(result['graphs'][1]['vertices']) == 2
    assert result['graphs'][1]['edges'][0]['color'] == 'green'
    assert result['graphs'][1]['edges'][0]['style'] == 'solid'
    assert len(handles) == 1


def test_unmentioned_cosmetic_attributes_do_not_trigger_review(prepared):
    _, run, _ = prepared
    initial = document()
    initial['body_text'] = '判断下图是否为树，并求各顶点的度数。'
    for graph in initial['graphs']:
        for edge in graph['edges']:
            edge.pop('style', None)
            edge.pop('color', None)
    glm = Specialist(AssertionError('Cosmetic attributes must not trigger review'))
    result, main = run(Provider(initial), glm)
    assert len(main.requests) == 1 and glm.requests == []
    assert result['complete'] is True


def test_uncertain_graph_gets_one_scoped_glm_read_without_overwriting_other_graph_or_body(prepared):
    _, run, handles = prepared
    initial = document()
    initial['uncertainties'] = [{'scope': 'graph', 'graph_id': 'G1', 'field': 'weight', 'message': 'e2权重看不清'}]
    corrected = copy.deepcopy(initial['graphs'][0])
    corrected['edges'][1]['weight'] = 9
    bad_other = {'id': 'G2', 'vertices': [], 'edges': []}
    glm = Specialist({'graphs': [corrected, bad_other], 'body_text': '无关改写', 'uncertainties': []})
    result, main = run(Provider(initial), glm)
    assert len(main.requests) == len(glm.requests) == 1
    assert glm.requests[0]['targets']['graph_ids'] == ['G1']
    assert glm.requests[0]['targets']['body'] is False
    assert result['body_text'] == initial['body_text']
    assert result['graphs'][0]['edges'][1]['weight'] == 9
    assert result['graphs'][1]['vertices'][0]['label'] == 'a'
    assert result['graphs'][1]['edges'][0]['from'] == 'b'
    assert result['complete'] is True
    assert len(handles) == 1  # A scalar-weight doubt does not request heavy tracing.


def test_missing_glm_keeps_specific_unknown_and_runs_final_validation(prepared):
    _, run, _ = prepared
    initial = document()
    initial['graphs'][1]['edges'][0]['direction'] = 'unknown'
    result, main = run(Provider(initial))
    assert len(main.requests) == 1 and result['complete'] is False
    assert result['graphs'][0]['complete'] is True
    assert result['graphs'][1]['edges'][0]['direction'] == 'unknown'
    assert result['semantic_workflow']['local_review']['reason'] == 'glm_not_configured'
    assert result['semantic_workflow']['final_validation']['status'] == 'completed'


@pytest.mark.parametrize('mixed', [False, True])
def test_missing_direction_does_not_become_an_accepted_default_arrow(prepared, mixed):
    _, run, _ = prepared
    initial = document()
    graph = initial['graphs'][0 if mixed else 1]
    edge = graph['edges'][1 if mixed else 0]
    edge.pop('direction')
    if mixed:
        graph['edges'][0]['direction'] = 'forward'
    result, _ = run(Provider(initial))
    rendered = result['graphs'][0 if mixed else 1]['edges'][1 if mixed else 0]
    assert rendered['direction'] == 'unknown' and rendered['status'] == 'pending'
    assert result['complete'] is False
    assert any(issue['kind'] == 'unknown_direction' for issue in result['semantic_issues'])


@pytest.mark.parametrize(('weight', 'declared_weighted', 'body'), [
    ('unknown', False, ''), ('?', False, ''), ('未知', False, ''),
    (None, True, ''), (None, False, '计算加权图的最短路径。'),
])
def test_unknown_and_required_missing_weights_remain_pending(prepared, weight, declared_weighted, body):
    _, run, _ = prepared
    initial = document()
    initial['graphs'][1]['edges'][0]['weight'] = weight
    initial['graphs'][1]['weighted'] = declared_weighted
    if body:
        initial['body_text'] = body
        initial['text_context'] = {'legends': [{'text': body, 'graph_ids': ['G2']}]}
    result, _ = run(Provider(initial))
    assert result['complete'] is False
    assert result['graphs'][1]['edges'][0]['status'] == 'pending'
    assert any(issue.get('field') == 'weight' and issue.get('graph_id') == 'G2'
               for issue in result['semantic_issues'])


@pytest.mark.parametrize('body', ['比较加权图和无权图的定义。', '下图是非加权图。', 'This graph is not weighted.'])
def test_weight_concepts_and_negative_legends_do_not_make_unweighted_edges_missing(prepared, body):
    _, run, _ = prepared
    initial = document()
    initial['body_text'] = body
    initial['text_context'] = {'legends': [{'text': body, 'graph_ids': ['G2']}]}
    for graph in initial['graphs']:
        for edge in graph['edges']:
            edge['weight'] = None
    result, _ = run(Provider(initial))
    assert result['complete'] is True


def test_symbolic_weights_and_unweighted_nulls_remain_valid_and_read_weight_can_clear(prepared):
    _, run, handles = prepared
    initial = document()
    initial['graphs'][0]['edges'][0]['weight'] = 'π'
    initial['graphs'][0]['edges'][1]['weight'] = 'x'
    result, _ = run(Provider(initial))
    assert result['complete'] is True
    assert [edge['weight'] for edge in result['graphs'][0]['edges']] == ['π', 'x', None]
    initial['graphs'][1]['edges'][0]['weight'] = 'unknown'
    corrected = copy.deepcopy(initial['graphs'][1])
    corrected['edges'][0]['weight'] = 0
    glm = Specialist({'graphs': [corrected], 'uncertainties': []})
    result, main = run(Provider(initial), glm)
    assert len(main.requests) == len(glm.requests) == 1
    assert result['complete'] is True and result['graphs'][1]['edges'][0]['weight'] == 0
    assert len(handles) == 2  # One Small bundle per upload, no extra topology tracing.


@pytest.mark.parametrize('status', ['memory_admission_rejected', 'partial', 'unavailable', None])
def test_unfinished_selected_tools_preserve_editable_result_but_fail_performance(prepared, monkeypatch, status):
    _, run, _ = prepared
    original = Handle.audit
    def failed_audit(self):
        result = original(self)
        if status is None:
            result['stages'] = []
        else:
            result['stages'][0]['status'] = status
        return result
    monkeypatch.setattr(Handle, 'audit', failed_audit)
    result, _ = run()
    assert result['complete'] is True and result['graphs'][0]['edges']
    assert result['local_tools_complete'] is False and result['selected_tools_complete'] is False
    assert result['service_warnings']
    performance = result['semantic_workflow']['performance']
    assert performance['local_tools_complete'] is False
    assert performance['selected_tools_complete'] is False
    assert performance['completed'] is False and performance['within_target'] is False


def test_selected_path_tool_failure_also_excludes_performance_after_visual_correction(prepared, monkeypatch):
    _, run, _ = prepared
    original = Handle.audit
    def failed_paths(self):
        result = original(self)
        for stage in result['stages']:
            if stage['stage'] == 'geometry':
                stage['status'] = 'partial'
        return result
    monkeypatch.setattr(Handle, 'audit', failed_paths)
    initial = document()
    initial['uncertainties'] = [{'scope': 'graph', 'graph_id': 'G1', 'field': 'edges', 'message': '边未确定'}]
    glm = Specialist({'graphs': [copy.deepcopy(initial['graphs'][0])], 'uncertainties': []})
    result, _ = run(Provider(initial), glm)
    assert result['complete'] is True and result['selected_tools_complete'] is False
    assert result['semantic_workflow']['performance']['within_target'] is False


def test_visual_stroke_inventory_preserves_loop_parallel_instances_and_needs_no_coordinates(prepared):
    _, run, _ = prepared
    initial = document()
    for graph in initial['graphs']:
        graph['stroke_inventory'] = [{'id': edge['id'], 'position': '原图中的独立笔画'} for edge in graph['edges']]
    glm = Specialist(AssertionError('A matching inventory is not a review trigger'))
    result, main = run(Provider(initial), glm)
    assert len(main.requests) == 1 and glm.requests == [] and result['complete'] is True
    assert len(result['graphs'][0]['edges']) == 3
    assert result['semantic_workflow']['image_accuracy_certified'] is False


@pytest.mark.parametrize('mismatch', ['unmapped_stroke', 'unlisted_edge', 'duplicate_stroke', 'missing_edge_id'])
def test_stroke_inventory_conflicts_do_not_fill_or_delete_edges(prepared, mismatch):
    _, run, _ = prepared
    initial = document()
    graph = initial['graphs'][0]
    graph['stroke_inventory'] = [{'id': edge['id']} for edge in graph['edges']]
    if mismatch == 'unmapped_stroke':
        graph['stroke_inventory'].append({'id': 's4', 'position': '右侧弧线'})
    elif mismatch == 'unlisted_edge':
        graph['stroke_inventory'].pop()
    elif mismatch == 'duplicate_stroke':
        graph['stroke_inventory'][1]['id'] = graph['stroke_inventory'][0]['id']
    else:
        graph['edges'][0].pop('id')
    result, main = run(Provider(initial))
    assert len(main.requests) == 1 and result['complete'] is False
    assert len(result['graphs'][0]['edges']) == 3 and len(result['graphs'][0]['vertices']) == 3
    assert result['graphs'][1]['complete'] is True
    assert any(issue['kind'] == 'stroke_inventory_mismatch' for issue in result['semantic_issues'])


@pytest.mark.parametrize('corrected_inventory', [False, True])
def test_same_review_must_resolve_stroke_mismatch_without_dropping_checklist(prepared, corrected_inventory):
    _, run, handles = prepared
    initial = document()
    initial['graphs'][0]['stroke_inventory'] = [{'id': 'extra-stroke'}]
    corrected = copy.deepcopy(initial['graphs'][0])
    if corrected_inventory:
        corrected['stroke_inventory'] = [{'id': edge['id']} for edge in corrected['edges']]
    else:
        corrected.pop('stroke_inventory')
    glm = Specialist({'graphs': [corrected], 'uncertainties': []})
    result, main = run(Provider(initial), glm)
    assert len(main.requests) == len(glm.requests) == 1
    assert result['complete'] is corrected_inventory
    assert len(result['graphs'][0]['edges']) == 3
    assert len(handles) == 1  # Checklist issues need a visual recount, not path tracing.


@pytest.mark.parametrize('corrected_vertices', [False, True])
def test_independent_marker_conflict_triggers_one_review_and_is_rechecked_afterwards(
        prepared, monkeypatch, corrected_vertices):
    _, run, handles = prepared
    import graph_visual_inventory
    evidence = {'status': 'measured', 'panels': [{'region_id': 'panel_1', 'bbox': [0, 0, 1000, 1000],
        'candidate_count': 4, 'comparison_eligible': True,
        'markers': [{'id': f'm{i}', 'position': [100+i*200, 500]} for i in range(4)]}],
        'diagnostics': [], 'proposal_only': True,
        'tool_audit': [{'tool': 'image.visual_marker_inventory', 'status': 'success', 'executed': True}]}
    calls = []
    def measure(*args, **kwargs):
        calls.append(True)
        return copy.deepcopy(evidence)
    monkeypatch.setattr(graph_visual_inventory, 'measure_visual_inventory', measure)
    initial = document()
    initial['graphs'] = initial['graphs'][:1]
    corrected = copy.deepcopy(initial['graphs'][0])
    if corrected_vertices:
        corrected['vertices'].append({'id': 'visible-isolated', 'label': None})
    glm = Specialist({'graphs': [corrected], 'uncertainties': []})
    result, main = run(Provider(initial), glm)
    assert len(calls) == 1 and len(main.requests) == len(glm.requests) == 1
    assert main.requests[0]['local_visual_inventory'] == fast._compact_visual_inventory(evidence)
    assert glm.requests[0]['local_visual_inventory'] == evidence
    assert any(issue['kind'] == 'visual_marker_count_conflict' for issue in glm.requests[0]['issues'])
    assert result['complete'] is corrected_vertices
    assert len(result['graphs'][0]['vertices']) == (4 if corrected_vertices else 3)
    assert result['selected_tools_complete'] is True
    if not corrected_vertices:
        assert any(issue['kind'] == 'visual_marker_count_conflict' for issue in result['semantic_issues'])
        assert result['semantic_workflow']['performance']['within_target'] is False
    assert len(handles) == 1  # Counting real markers does not schedule edge tracing.


def test_marker_measurement_failure_preserves_visual_result_but_is_not_performance_success(prepared, monkeypatch):
    _, run, _ = prepared
    import graph_visual_inventory
    def broken_measure(*args, **kwargs):
        raise ValueError('local pixel measurement failed')
    monkeypatch.setattr(graph_visual_inventory, 'measure_visual_inventory', broken_measure)
    result, main = run()
    assert len(main.requests) == 1 and result['complete'] is True
    assert result['selected_tools_complete'] is False and result['service_warnings']
    assert result['semantic_workflow']['local_tools']['visual_inventory']['status'] == 'failed'
    assert result['semantic_workflow']['performance']['within_target'] is False


def test_missing_marker_execution_audit_is_warned_and_not_a_performance_success(prepared, monkeypatch):
    _, run, _ = prepared
    import graph_visual_inventory
    monkeypatch.setattr(graph_visual_inventory, 'measure_visual_inventory', lambda *a, **kw: {
        'status': 'measured', 'panels': [], 'diagnostics': [], 'tool_audit': []})
    result, _ = run()
    assert result['complete'] is True and result['graphs'][0]['edges']
    assert result['local_tools_complete'] is False and result['selected_tools_complete'] is False
    assert result['service_warnings'][0]['kind'] == 'local_tools_degraded'
    assert result['semantic_workflow']['performance']['within_target'] is False


def test_main_inventory_projection_only_sends_eligible_pixel_supported_groups():
    evidence = {'status': 'measured', 'diagnostics': ['internal'], 'tool_audit': [{'internal': True}],
        'panels': [{'region_id': 'panel_1', 'bbox': [0, 0, 500, 1000], 'candidate_count': 3,
                    'comparison_eligible': True, 'markers': [{
                        'id': 'm1', 'position': [100, 200], 'radius_pixels': 18, 'color_hue': 120,
                        'proof': {'source': 'original_colour_component', 'convex_hull_roundness': .94,
                                  'component_fill': .98, 'component_pixels': 900, 'internal': 'omit'}}]},
                   {'region_id': 'weak', 'candidate_count': 15, 'comparison_eligible': False,
                    'markers': [{'id': 'glyph'}]}]}
    before = copy.deepcopy(evidence)
    compact = fast._compact_visual_inventory(evidence)
    assert compact['proposal_only'] is True and compact['image_accuracy_certified'] is False
    assert [row['region_id'] for row in compact['panels']] == ['panel_1']
    assert compact['panels'][0]['candidate_count'] == 3
    marker = compact['panels'][0]['markers'][0]
    assert marker['position'] == [100, 200] and marker['radius_pixels'] == 18
    assert marker['pixel_support']['source'] == 'original_colour_component'
    assert 'internal' not in marker['pixel_support'] and 'tool_audit' not in compact
    assert evidence == before


def test_specialist_network_failure_retains_editable_data_and_unaffected_panel(prepared):
    _, run, handles = prepared
    initial = document()
    initial['uncertainties'] = [{'scope': 'graph', 'graph_id': 'G1', 'field': 'edges', 'message': '平行弧存疑'}]
    result, _ = run(Provider(initial), Specialist(VisionError('transport_failed')))
    assert result['complete'] is False and len(result['graphs'][0]['edges']) == 3
    assert result['graphs'][1]['complete'] is True and result['body_complete'] is True
    assert result['semantic_workflow']['local_review']['status'] == 'failed'
    assert result['semantic_workflow']['final_validation']['status'] == 'completed'
    assert len(handles) == 2 and handles[1].policy['paths'] and handles[1].policy['sknw']
    assert all(handle.closed for handle in handles)
    json.dumps(result, allow_nan=False)  # No scheduler PIL/document objects leak.


def test_schema_invalid_endpoint_cannot_be_certified_by_networkx_cleanup(prepared):
    _, run, _ = prepared
    initial = document()
    initial['graphs'][0]['edges'][0]['to'] = ['not', 'an', 'endpoint']
    result, _ = run(Provider(initial))
    assert result['complete'] is False
    assert any(issue['kind'] == 'json_schema_invalid' for issue in result['semantic_issues'])
    assert result['graphs'][0]['unresolved_edges']


@pytest.mark.parametrize('value', ['unknown', None, 1])
def test_provided_weighted_flag_must_be_boolean(prepared, value):
    _, run, _ = prepared
    initial = document()
    initial['graphs'][0]['weighted'] = value
    result, _ = run(Provider(initial))
    assert result['complete'] is False
    assert any(issue['kind'] == 'json_schema_invalid' and issue.get('field') == 'weighted'
               for issue in result['semantic_issues'])


@pytest.mark.parametrize('explicit_correction', [False, True])
def test_review_omitted_graph_flags_cannot_clear_unknown_direction_or_weight(prepared, explicit_correction):
    _, run, _ = prepared
    initial = document()
    initial['graphs'][1]['weighted'] = True
    initial['graphs'][1]['edges'][0]['weight'] = None
    corrected = copy.deepcopy(initial['graphs'][1])
    corrected.pop('directed')
    corrected.pop('weighted')
    corrected['edges'][0].pop('direction')
    if explicit_correction:
        corrected.update(directed=False, weighted=False)
        corrected['edges'][0]['direction'] = 'undirected'
    glm = Specialist({'graphs': [corrected], 'uncertainties': []})
    result, main = run(Provider(initial), glm)
    assert len(main.requests) == len(glm.requests) == 1
    edge = result['graphs'][1]['edges'][0]
    assert edge['weight'] is None  # No value is invented to satisfy a flag.
    assert result['complete'] is explicit_correction
    if explicit_correction:
        assert edge['direction'] == 'undirected'
        assert result['graphs'][1]['directed'] is False and result['graphs'][1]['weighted'] is False
    else:
        assert edge['direction'] == 'unknown' and edge['status'] == 'pending'
        assert {'unknown_direction', 'unknown_weight'}.issubset(
            {issue['kind'] for issue in result['semantic_issues']})


def test_main_model_failure_closes_running_tools_and_does_not_start_another_visual_role(prepared):
    _, run, handles = prepared
    main = Provider(VisionError('transport_failed'))
    glm = Specialist(document())
    with pytest.raises(VisionError, match='transport_failed'):
        run(main, glm)
    assert len(main.requests) == 1 and glm.requests == []
    assert handles[0].closed


def test_four_uploads_have_independent_identity_results_and_budget(prepared):
    raw, run, handles = prepared
    def one(index):
        source = document()
        source['body_text'] = f'独立题目 {index}'
        return run(Provider(source), task_id=f'task-{index}')[0]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(one, range(4)))
    assert [row['body_text'] for row in results] == [f'独立题目 {i}' for i in range(4)]
    assert {row['semantic_workflow']['task_id'] for row in results} == {f'task-{i}' for i in range(4)}
    assert all(row['semantic_workflow']['role_counts'] == {'fast_main': 1} for row in results)
    assert all(handle.closed for handle in handles)


def test_whole_document_dispute_can_correct_panel_inventory_without_old_graph_id_requirements():
    initial = document()
    initial['uncertainties'] = [{'scope': 'document', 'message': '分图边界存疑'}]
    corrected = {'body_text': initial['body_text'], 'graphs': [
        {**copy.deepcopy(initial['graphs'][0]), 'id': 'Corrected'}], 'uncertainties': []}
    targets = fast._targets(initial, initial['uncertainties'])
    patched, pending = fast._merge_local_review(initial, corrected, targets)
    assert patched['graphs'] == corrected['graphs'] and patched['uncertainties'] == []
    assert pending == []


def test_normal_multifigure_page_does_not_always_select_layout_model():
    quick = {'panels': [{'bbox': [x, y, x+200, y+200]} for y in (0, 500) for x in (0, 300, 600)]}
    assert fast._complex_layout_needed(quick, {'marker_candidates': [{}]*30}) is False
    ambiguous = {'panels': [{'bbox': [0, 0, 500, 500]}, {'bbox': [10, 10, 510, 510]}]}
    assert fast._complex_layout_needed(ambiguous, {}) is True


def test_main_views_reuse_only_panel_metadata_and_keep_overview_without_duplicates():
    quick = {'images': ['overview', 'body', 'panel', 'duplicate-panel', 'panel', 'unlocated'],
             'view_descriptions': ['完整原图'],
             'panels': [{'id': 'panel_1'}, {'id': 'panel_2'}],
             'body_regions': [{'id': 'body_region_1'}],
             'view_metadata': [{}, {'region_id': 'body_region_1'}, {'region_id': 'panel_1'},
                               {'region_id': 'panel_1'}, {'region_id': 'panel_2'}]}
    before = copy.deepcopy(quick)
    views = fast._main_panel_views(quick)
    assert views['images'] == ['overview', 'panel']
    assert len(views['view_descriptions']) == 2
    assert '同一原图' in views['view_descriptions'][1] and '不是新增子图' in views['view_descriptions'][1]
    assert quick == before


def test_main_views_allow_four_panel_crops_and_fall_back_to_overview_without_metadata():
    quick = {'images': ['overview'] + [f'crop-{i}' for i in range(6)],
             'view_descriptions': ['完整原图'],
             'panels': [{'id': f'panel_{i}'} for i in range(6)],
             'view_metadata': [{}] + [{'region_id': f'panel_{i}'} for i in range(6)]}
    assert fast._main_panel_views(quick)['images'] == ['overview', 'crop-0', 'crop-1', 'crop-2', 'crop-3']
    quick.pop('view_metadata')
    assert fast._main_panel_views(quick) == {'images': ['overview'], 'view_descriptions': ['完整原图']}


def test_only_main_call_receives_existing_panel_crops_and_never_body_fragments(prepared, monkeypatch):
    _, run, handles = prepared
    import graph_semantic_layout, graph_semantic_arrow_views
    prepare = graph_semantic_layout.prepare_semantic_layout
    def with_crops(*args, **kwargs):
        quick = prepare(*args, **kwargs)
        quick.update(images=quick['images'] + ['synthetic-panel', 'synthetic-body'],
                     panels=[{'id': 'panel_1'}], body_regions=[{'id': 'body_region_1'}],
                     view_metadata=[{}, {'region_id': 'panel_1'}, {'region_id': 'body_region_1'}])
        return quick
    monkeypatch.setattr(graph_semantic_layout, 'prepare_semantic_layout', with_crops)
    monkeypatch.setattr(graph_semantic_arrow_views, 'prepare_panel_views',
                        lambda raw, **kwargs: copy.deepcopy(kwargs['overview_views']))
    class CaptureImages(Provider):
        def __call__(self, prompt, images, budget):
            self.received_images = list(images)
            return super().__call__(prompt, images, budget)
    initial = document()
    initial['uncertainties'] = [{'scope': 'graph', 'graph_id': 'G1', 'field': 'weight', 'message': '权重存疑'}]
    main = CaptureImages(initial)
    glm = CaptureImages({'graphs': [copy.deepcopy(initial['graphs'][0])], 'uncertainties': []})
    glm.name, glm.model = 'glm', GLM_5V_TURBO_MODEL
    result, _ = run(main, glm)
    assert main.received_images[1:] == ['synthetic-panel']
    assert len(glm.received_images) == 1 and glm.received_images[0] == main.received_images[0]
    assert len(main.requests) == len(glm.requests) == 1 and result['complete'] is True
    assert len(main.requests[0]['image_views']) == 2 and len(glm.requests[0]['image_views']) == 1
    assert len(handles) == 1


def test_budget_is_explicit_with_one_preheader_qwen_recovery_but_no_json_retries():
    budget = fast.configured_fast_budget()
    assert budget.initial_calls == 3
    assert budget.max_network_recoveries == 1
    assert budget.max_json_format_recoveries == 0
    assert budget.deadline-budget.started == pytest.approx(200)


def test_default_main_uses_json_mode_without_changing_explicit_injected_provider():
    from vision_provider import VisionProvider
    budget = fast.configured_fast_budget()
    runner = fast.FastRunner(budget)
    ordinary = runner._provider_for('fast_main')
    payload = ordinary.payload('Only JSON', [])
    assert ordinary.name == 'qwen' and ordinary.model == 'qwen3-vl-plus'
    assert ordinary.retries == 0 and ordinary.thinking_budget is None
    assert payload['enable_thinking'] is False and 'thinking_budget' not in payload
    assert payload['response_format'] == {'type': 'json_object'}
    injected = VisionProvider('qwen', thinking=True, thinking_budget=1024, retries=0)
    assert fast.FastRunner(budget, provider=injected)._provider_for('fast_main') is injected
    assert fast.FastRunner(budget, provider={'fast_main': injected})._provider_for('fast_main') is injected
    assert fast.FastRunner(budget)._provider_for('fast_local_review').thinking is False


def test_public_tool_result_preserves_actual_readiness_metrics_without_worker_objects():
    metric = {'stage': 'text', 'status': 'ok', 'worker_started': True,
              'model_inference_completed': True}
    original = {'text': {'resource_metrics': [metric], 'document': object()},
                'layout': {'resource_metrics': [{'stage': 'layout', 'status': 'ok'}], 'images': ['private']}}
    projected = fast._public_local_result(original)
    assert projected['text']['resource_metrics'] == [metric]
    assert 'document' not in projected['text'] and 'images' not in projected['layout']
    projected['text']['resource_metrics'][0]['status'] = 'changed'
    assert original['text']['resource_metrics'][0]['status'] == 'ok'
    json.dumps(projected, allow_nan=False)


def test_small_ocr_can_flag_a_located_missing_subquestion_without_copying_it_into_body():
    draft = document()
    text = {'text_hints': [
        {'id': 'question', 'text': '（2）求从a到b的最短路径。', 'bbox': [10, 10, 700, 80],
         'coordinate_space': 'original_1000', 'role_hint': 'body', 'confidence': .98},
        {'id': 'label', 'text': 'v1 e2 e3', 'bbox': [10, 400, 200, 450],
         'coordinate_space': 'original_1000', 'role_hint': 'body', 'confidence': .99}]}
    before = copy.deepcopy(draft)
    issues = fast._text_candidate_issues(draft, text, {})
    assert draft == before and len(issues) == 1
    assert issues[0]['candidate_text'] == '（2）求从a到b的最短路径。'
    draft['body_text'] += '\n(2) 求从 a 到 b 的最短路径。'
    assert fast._text_candidate_issues(draft, text, {}) == []
    draft['body_text'] = ''
    text['text_hints'][0]['confidence'] = .5
    assert fast._text_candidate_issues(draft, text, {}) == []


def test_fast_dispatch_preserves_user_confirmation_and_measures_rendering(prepared, monkeypatch):
    raw, run, _ = prepared
    result, _ = run()
    monkeypatch.setattr(fast, 'recognize_fast', lambda *a, **kw: copy.deepcopy(result))
    import ocr_nextgen
    monkeypatch.setattr(ocr_nextgen, 'correct_text', lambda *a, **kw: pytest.fail('No DeepSeek during recognition'))
    rendered = ocr_nextgen.recognize_graph_document(raw, {}, graph_pipeline='agent-tools')
    assert rendered['recognition_status'] == 'complete'
    assert rendered['confirmation_required'] is True
    assert rendered['recognition_profile'] == 'fast-editable'
    assert rendered['recognition_timing']['scope'] == 'recognition_and_response_rendering'
    assert rendered['recognition_timing']['target_seconds'] == 120
    assert rendered['diagnostics']['correction']['status'] == 'not_run'


def test_late_success_is_reported_as_a_performance_miss_not_an_artificial_timeout(prepared, monkeypatch):
    raw, run, _ = prepared
    result, _ = run()
    monkeypatch.setattr(fast, 'recognize_fast', lambda *a, **kw: copy.deepcopy(result))
    real_budget = fast.configured_fast_budget
    def late(**kwargs):
        budget = real_budget(**kwargs)
        budget.started -= 130
        return budget
    monkeypatch.setattr(fast, 'configured_fast_budget', late)
    import ocr_nextgen
    rendered = ocr_nextgen.recognize_graph_document(raw, {}, graph_pipeline='agent-tools')
    assert rendered['recognition_status'] == 'complete'
    assert rendered['recognition_timing']['seconds'] >= 130
    assert rendered['recognition_timing']['within_target'] is False
