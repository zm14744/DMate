"""Semantic integration regressions; fixtures never certify image accuracy."""
import copy
import io
import json
import threading
import time

import pytest
from PIL import Image

from graph_agent_runtime import AgentBudget, AgentCancelled
from graph_semantic_pipeline import SemanticRunner, _review_changes, recognize_semantic
from vision_provider import VisionError, VisionProvider


SOURCE_ROLES = ('semantic_edges', 'semantic_edges_glm', 'semantic_edges_glm_fast')
BODY_ROLES = ('semantic_body', 'semantic_body_glm')
DIRECTION_ROLES = ('semantic_directions', 'semantic_directions_glm')


def install_semantic_worker_fixtures(monkeypatch, events=None, *, lock_root=None):
    """Keep real adapters/registry/CV preparation; inject only heavy workers.

    These observations certify test wiring only. No Paddle or sknw inference,
    provider request, or original-image accuracy is claimed by this fixture.
    The browser child reuses the same boundaries in its isolated process.
    """
    import graph_semantic_geometry
    import graph_semantic_layout
    import graph_semantic_text
    import graph_sknw_plugin
    import ocr_runtime
    events = [] if events is None else events
    if lock_root is not None:
        import tempfile
        from types import SimpleNamespace
        # Keep test workers independent of another process's actual model lock.
        isolated_tempfile = SimpleNamespace(gettempdir=lambda: str(lock_root),
                                            TemporaryDirectory=tempfile.TemporaryDirectory)
        monkeypatch.setattr(graph_semantic_layout, 'tempfile', isolated_tempfile)
        monkeypatch.setattr(graph_semantic_text, 'tempfile', isolated_tempfile)

    def worker(stage, image_path, output_path, **kwargs):
        with Image.open(image_path) as image:
            width, height = image.size
        events.append({'kind': 'injected_worker', 'stage': stage,
                       'image_size': [width, height], 'fixture_only': True})
        metric = {'stage': stage, 'status': 'ok', 'seconds': 0,
                  'peak_rss_bytes': None, 'rss_observed': False, 'fixture_only': True}
        if stage == 'layout':
            return {'status': 'ok', 'model': 'PP-DocLayoutV3', 'regions': [
                {'id': 'fixture_body', 'bbox': [.02, .02, .98, .2],
                 'label': 'text', 'role': 'text', 'score': .9},
                {'id': 'fixture_figure', 'bbox': [.02, .25, .98, .98],
                 'label': 'image', 'role': 'figure', 'score': .9}]}, metric
        if stage == 'text':
            hint = '本地文字候选，须对照原图。'
            return {'text': hint, 'front_text': hint, 'text_count': 1,
                'formula_count': 0, 'review_regions': [], 'text_evidence': {
                    'image_size': [width, height], 'coordinate_space': 'canonical_image_pixels',
                    'body': [{'content': hint,
                        'box': [1, 1, max(2, width-1), max(2, height//5)], 'score': .9}],
                    'graph_labels': [], 'uncertain': [], 'noise': []}}, metric
        raise AssertionError('Unexpected heavy worker stage: '+stage)

    def trace(name):
        def run(document, graphs, **kwargs):
            budget = kwargs.get('budget')
            if budget is not None:
                budget.check()
            events.append({'kind': 'injected_geometry_worker', 'tool': name,
                           'graph_ids': [g['id'] for g in graphs], 'fixture_only': True})
            inventory, diagnostics = {}, []
            for graph in graphs:
                nodes = graph['vertices']
                rows = []
                if len(nodes) >= 2:
                    a, b = nodes[:2]
                    rows.append({'id': 'fixture_'+name, 'from': a['id'], 'to': b['id'],
                        'path': [[a['x'], a['y']], [b['x'], b['y']]], 'style': 'solid'})
                inventory[graph['id']] = rows
                diagnostics.append({'code': 'roi_traced', 'status': 'ok',
                                    'graph_id': graph['id'], 'fixture_only': True})
            return inventory, diagnostics
        return run

    monkeypatch.setattr(ocr_runtime, 'run_worker', worker)
    monkeypatch.setattr(graph_semantic_text, '_cache_readiness', lambda: {
        'status': 'ready', 'worker_started': False, 'fixture_only': True})
    monkeypatch.setattr(graph_semantic_geometry, '_trace_opencv', trace('opencv'))
    monkeypatch.setattr(graph_sknw_plugin, 'suggest_candidates', trace('sknw'))
    return events


@pytest.fixture(autouse=True)
def local_worker_boundaries(monkeypatch, tmp_path):
    return install_semantic_worker_fixtures(monkeypatch, lock_root=tmp_path)


def original():
    output = io.BytesIO()
    Image.new('RGB', (180, 120), 'white').save(output, format='PNG')
    return output.getvalue()


def document():
    return {'body_text': '③求顶点v₅的度数。', 'graphs': [{
        'id': 'G1', 'name': '(a)', 'directed': True,
        'vertices': [{'id': 'a', 'label': 'v₁'}, {'id': 'b', 'label': 'v₅'},
                     {'id': 'c', 'label': '孤立点'}],
        'edges': [{'from': 'a', 'to': 'b', 'direction': 'forward', 'edge_label': 'e₁',
                   'weight': 0, 'color': 'blue', 'style': 'dashed'},
                  {'from': 'a', 'to': 'b', 'direction': 'forward', 'edge_label': 'e₂', 'weight': 3},
                  {'from': 'a', 'to': 'a', 'direction': 'forward', 'edge_label': 'e₃', 'weight': 2}]}],
        'uncertainties': []}


@pytest.fixture(autouse=True)
def no_implicit_live_provider(monkeypatch):
    # Explicit fake readers exercise orchestration; a missing role in a mapping
    # must never consult usable production credentials or make an API request.
    monkeypatch.setattr(VisionProvider, 'available', lambda self: False)


def source_response(task, whole):
    graph = next(g for g in whole['graphs'] if g['id'] == task['graph_id'])
    sources = []
    for sid in task['source_ids']:
        edges = []
        for edge in graph['edges']:
            target = None
            if edge['from'] == sid:
                target = edge['to']
            elif edge.get('direction') == 'undirected' and edge['to'] == sid:
                target = edge['from']
            if target is not None:
                edges.append({'to': target, **{k: copy.deepcopy(v) for k, v in edge.items()
                    if k in ('direction', 'weight', 'edge_label', 'color', 'style')}})
        sources.append({'id': sid, 'edges': edges})
    return {'sources': sources}


def direction_response(task, whole):
    """Return the request's exact graph/edge identities and unordered pairs."""
    rows = []
    for requested in task['graphs']:
        known = next((g for g in whole['graphs'] if g['id'] == requested['id']), {})
        edges = []
        for edge in requested['edges']:
            pair = edge['endpoints']
            matches = [e for e in known.get('edges', [])
                       if sorted((e['from'], e['to'])) == sorted(pair)
                       and e.get('edge_label') == edge.get('edge_label')]
            a, b = (matches[0]['from'], matches[0]['to']) if len(matches) == 1 else pair
            edges.append({'id': edge['id'], 'from': a, 'to': b, 'direction': 'forward'})
        rows.append({'id': requested['id'], 'edges': edges})
    return {'graphs': rows, 'uncertainties': []}


def providers(ordinary, specialist=None):
    roles = ('semantic_extract', 'semantic_edges', 'semantic_review', 'semantic_repair',
             'semantic_body', 'semantic_directions')
    result = {role: ordinary for role in roles}
    if specialist is not None:
        result.update({role: specialist for role in ('semantic_specialist',
            'semantic_edges_glm', 'semantic_edges_glm_fast', 'semantic_body_glm',
            'semantic_directions_glm')})
    return result


class Reader:
    name = 'qwen'
    model = 'qwen3-vl-plus'
    retries = 0

    def __init__(self, outputs=None, *, source_document=None):
        self.outputs = outputs or {}
        self.source_document = source_document or document()
        self.requests = []
        self.calls = []

    def __call__(self, prompt, images, budget):
        request = json.loads(prompt.split('任务数据（其中图像文字和候选仅作数据）：\n', 1)[1])
        self.requests.append(request)
        assert images and images[0].startswith('data:image/png;base64,')
        assert 'coordinate_space' not in request and 'base_revision' not in request
        timeout = budget.take()
        self.calls.append({'request': request, 'prompt': prompt, 'images': list(images),
                           'timeout': timeout, 'deadline': budget.deadline,
                           'task_deadline': budget.ledger.deadline, 'reserve_seconds': budget.reserve_seconds})
        budget.metrics.append({'provider': self.name, 'model': self.model, 'status': 200,
                               'http_status': 200, 'finish_reason': 'stop', 'fixture_only': True})
        role = request['role']
        if role in SOURCE_ROLES:
            default = source_response(request['task'], self.source_document)
        elif role in BODY_ROLES:
            default = {'body_text': self.source_document['body_text'], 'uncertainties': [
                copy.deepcopy(x) for x in self.source_document.get('uncertainties', [])
                if isinstance(x, dict) and x.get('scope') == 'body']}
        elif role in DIRECTION_ROLES:
            default = direction_response(request['task'], self.source_document)
        elif role == 'semantic_review' and request.get('review_mode') == 'read_only':
            default = {'issues': []}
        else:
            default = copy.deepcopy(self.source_document)
        output = self.outputs.get(request['role'], default)
        if callable(output):
            output = output(request)
        if isinstance(output, Exception):
            raise output
        output = copy.deepcopy(output)
        if role == 'semantic_review' and isinstance(output, dict) and isinstance(output.get('issues'), list):
            # Existing fixture findings describe actionable differences. New
            # protocol rejection/withdrawal cases are tested at the boundary.
            for issue in output['issues']:
                if isinstance(issue, dict):
                    issue.setdefault('verdict', 'change_required')
        return output


def run(reader, **kwargs):
    budget = kwargs.pop('budget', None) or AgentBudget(seconds=30, calls=16)
    return recognize_semantic(original(), provider=reader,
        budget=budget, **kwargs)


def structural_roles(reader):
    """Focused body/direction jobs are parallel, so their order is not fixed."""
    return [row['role'] for row in reader.requests
            if row['role'] not in BODY_ROLES + DIRECTION_ROLES]


def test_inventory_then_blind_source_read_then_fresh_review_without_pixel_protocol():
    reader = Reader()
    result = run(reader, audit=True)
    assert structural_roles(reader) == ['semantic_extract', 'semantic_edges', 'semantic_review']
    assert {r['role'] for r in reader.requests[3:]} == {'semantic_body', 'semantic_directions'}
    assert result['graphs'][0]['complete'] and result['body_complete']
    assert len(result['graphs'][0]['edges']) == 3
    assert all(e['status'] == 'accepted' and not e['path'] and not e['evidence']
               for e in result['graphs'][0]['edges'])
    assert result['semantic_workflow']['geometry_required'] is False
    assert result['semantic_workflow']['reviewed'] is True
    assert result['stage_audit']['responses'][0]['document'] == document()
    assert 'draft' not in reader.requests[1]
    assert 'edges' not in reader.requests[1]['task']
    assert reader.requests[2]['draft']['body_text'] == document()['body_text']
    assert reader.requests[2]['review_mode'] == 'read_only'
    assert result['semantic_workflow']['literal_body_checked'] is True
    assert result['semantic_workflow']['direction_audit']['all_requested_edges_confirmed'] is True
    assert result['semantic_workflow']['edge_strategy'] == 'node_inventory_then_source_conditioned_edges'
    assert len(result['semantic_workflow']['source_audit']['graphs']) == 1


def test_literal_body_reader_corrects_critical_digit_and_source_reader_keeps_edge_names():
    wrong = document()
    wrong['body_text'] = '③求顶点v₃的度数。'
    for e in wrong['graphs'][0]['edges']:
        e.pop('edge_label')
    reader = Reader({'semantic_extract': wrong})
    result = run(reader)
    assert result['body_text'] == '③求顶点v₅的度数。'
    assert [e['edge_label'] for e in result['graphs'][0]['edges']] == ['e₁', 'e₂', 'e₃']
    assert structural_roles(reader) == ['semantic_extract', 'semantic_edges', 'semantic_review']
    assert result['semantic_workflow']['literal_body_checked'] is True
    assert any(r['role'] == 'semantic_body' for r in reader.requests)


def test_full_document_is_invalid_for_readonly_review_and_gets_one_content_repair():
    wrong = document()
    wrong['graphs'][0]['edges'][0]['to'] = 'missing'
    reader = Reader({'semantic_review': wrong})
    result = run(reader)
    assert structural_roles(reader) == ['semantic_extract', 'semantic_edges', 'semantic_review', 'semantic_repair']
    assert next(r for r in reader.requests if r['role'] == 'semantic_repair')['remaining_issues']
    assert result['graphs'][0]['complete'] and not result['semantic_issues']


def test_review_failure_retains_initial_content_without_claiming_complete():
    reader = Reader({'semantic_review': VisionError('invalid_output'),
                     'semantic_repair': VisionError('invalid_output')})
    result = run(reader)
    assert len(result['graphs'][0]['edges']) == 3
    assert result['body_text'] == document()['body_text']
    assert not result['graphs'][0]['complete'] and not result['body_complete']
    assert result['semantic_issues']
    assert result['semantic_workflow']['reviewed'] is False


def test_failed_first_read_requires_another_review_after_recovery():
    reader = Reader({'semantic_extract': VisionError('invalid_output')})
    result = run(reader)
    assert structural_roles(reader) == ['semantic_extract', 'semantic_review', 'semantic_repair']
    assert reader.requests[1].get('review_mode') != 'read_only'
    assert result['semantic_workflow']['reviewed'] is True
    assert result['graphs'][0]['complete']


@pytest.mark.parametrize('bad', [{}, {'body_text': 12, 'graphs': []},
                                {'body_text': '', 'graphs': {}},
                                {'body_text': '', 'graphs': [{}]},
                                {'body_text': '', 'graphs': [None]},
                                {'body_text': '', 'graphs': []}])
def test_mechanically_bad_or_empty_review_does_not_erase_previous_content(bad):
    reader = Reader({'semantic_review': bad, 'semantic_repair': VisionError('invalid_output')})
    result = run(reader)
    assert result['body_text'] == document()['body_text']
    assert len(result['graphs'][0]['edges']) == 3
    assert not result['semantic_workflow']['reviewed']
    assert result['semantic_issues']


@pytest.mark.parametrize('bad', [{}, {'body_text': '', 'graphs': []},
                                {'body_text': '', 'graphs': [{}]},
                                {'body_text': '', 'graphs': [None]}])
def test_bad_or_blank_initial_payload_is_not_counted_as_review_of_recovered_content(bad):
    reader = Reader({'semantic_extract': bad})
    result = run(reader)
    assert structural_roles(reader) == ['semantic_extract', 'semantic_review', 'semantic_repair']
    assert result['graphs'][0]['complete']


def test_body_only_document_is_valid_and_independently_reviewed():
    text = {'body_text': '写出握手定理。', 'graphs': [], 'uncertainties': []}
    reader = Reader(source_document=text)
    result = run(reader)
    assert result['graphs'] == [] and result['body_complete']
    assert not result['semantic_issues']
    assert structural_roles(reader) == ['semantic_extract', 'semantic_review']
    assert any(r['role'] == 'semantic_body' for r in reader.requests)
    assert not any(r['role'] in SOURCE_ROLES + DIRECTION_ROLES for r in reader.requests)


def test_body_uncertainty_preserves_valid_graph_and_does_not_loop():
    partial = document()
    partial['uncertainties'] = [{'scope': 'body', 'message': '顶部题干在原图中裁切。'}]
    reader = Reader(source_document=partial)
    result = run(reader)
    assert result['graphs'][0]['complete']
    assert not result['body_complete']
    assert structural_roles(reader) == ['semantic_extract', 'semantic_edges', 'semantic_review', 'semantic_repair']
    assert sum(r['role'] == 'semantic_body' for r in reader.requests) == 1


def test_one_uncertain_subgraph_does_not_erase_or_invalidate_other_subgraph():
    partial = document()
    second = copy.deepcopy(partial['graphs'][0])
    second['id'], second['name'] = 'G2', '(b)'
    partial['graphs'].append(second)
    partial['uncertainties'] = [{'scope': 'graph', 'graph_id': 'G2', 'message': '右侧箭头看不清。'}]
    reader = Reader(source_document=partial)
    result = run(reader)
    assert result['graphs'][0]['complete']
    assert not result['graphs'][1]['complete']
    assert all(len(g['edges']) == 3 for g in result['graphs'])


def test_cancelled_upload_never_sends_a_model_request():
    reader = Reader()
    with pytest.raises(AgentCancelled):
        run(reader, cancelled=lambda: True)
    assert reader.requests == []


def test_three_completed_subgraphs_do_not_require_a_configured_specialist(monkeypatch):
    from graph_semantic_pipeline import SemanticRunner
    monkeypatch.setattr(SemanticRunner, 'specialist_available', lambda self: False)
    whole = document()
    whole['graphs'] = [dict(copy.deepcopy(whole['graphs'][0]), id=f'G{i}', name=f'({i})')
                       for i in range(1, 4)]
    reader = Reader(source_document=whole)
    result = run(reader)
    assert len(result['graphs']) == 3 and all(g['complete'] for g in result['graphs'])
    assert [r['role'] for r in reader.requests].count('semantic_edges') == 3
    assert structural_roles(reader)[0] == 'semantic_extract'
    assert structural_roles(reader)[-1] == 'semantic_review'


class Specialist(Reader):
    name = 'glm'
    model = 'glm-5v-turbo'


def test_optional_glm_reads_source_groups_and_qwen_independently_reviews_all_graphs():
    whole = document()
    whole['graphs'] = [dict(copy.deepcopy(whole['graphs'][0]), id=f'G{i}', name=f'({i})')
                       for i in range(1, 4)]
    ordinary = Reader(source_document=whole)
    specialist = Specialist(source_document=whole)
    result = run(providers(ordinary, specialist))
    assert [r['role'] for r in ordinary.requests] == ['semantic_extract', 'semantic_review']
    source_reads = [r for r in specialist.requests if r['role'] in SOURCE_ROLES]
    assert len(source_reads) == 3 and all(r['role'] == 'semantic_edges_glm_fast' for r in source_reads)
    assert {r['role'] for r in specialist.requests} == {
        'semantic_edges_glm_fast', 'semantic_body_glm', 'semantic_directions_glm'}
    assert result['semantic_workflow']['reviewed'] is True
    assert sum(m['provider'] == 'qwen' for m in result['remote_metrics']) == 2
    assert sum(m['provider'] == 'glm' for m in result['remote_metrics']) == 5
    assert all(c['images'][0] == ordinary.calls[0]['images'][0] for c in specialist.calls)


def test_source_specialist_failure_falls_back_to_qwen_without_erasing_content():
    whole = document()
    whole['graphs'] = [dict(copy.deepcopy(whole['graphs'][0]), id=f'G{i}', name=f'({i})')
                       for i in range(1, 4)]
    ordinary = Reader(source_document=whole)
    specialist = Specialist({'semantic_edges_glm_fast': VisionError('invalid_output')}, source_document=whole)
    result = run(providers(ordinary, specialist))
    assert [r['role'] for r in ordinary.requests].count('semantic_edges') == 3
    assert structural_roles(ordinary)[-1] == 'semantic_review'
    assert result['graphs'][0]['complete'] and not result['semantic_issues']


def test_app_default_route_preserves_literal_text_without_another_model_editor(monkeypatch):
    import ocr_nextgen
    reader = Reader()
    calls = []
    def redundant_editor(text, **kwargs):
        calls.append(text)
        return 'unexpected text edit', {'status': 'ok'}
    monkeypatch.setattr(ocr_nextgen, 'correct_text', redundant_editor)
    result = ocr_nextgen.recognize_graph_document(original(), {},
        graph_pipeline='agent-tools', vision_provider=reader)
    assert result['recognition_status'] == 'complete'
    assert result['text'] == document()['body_text']
    assert calls == []
    assert result['diagnostics']['correction']['reason'] == 'literal_semantic_text_preserved'
    from graph_pipeline_version import AGENT_PIPELINE_VERSION
    assert result['graph_display_version'] == AGENT_PIPELINE_VERSION
    assert '颜色 blue' in result['visual_text'] and '虚线' in result['visual_text']
    assert 'semantic_workflow' in result['diagnostics']


def test_app_allows_text_only_and_marks_remaining_body_issue_partial(monkeypatch):
    import ocr_nextgen
    text = {'body_text': '求图的……', 'graphs': [],
            'uncertainties': [{'scope': 'body', 'message': '原图末尾裁切。'}]}
    reader = Reader(source_document=text)
    monkeypatch.setattr(ocr_nextgen, 'correct_text', lambda text, **kwargs: (text, {'status': 'ok'}))
    result = ocr_nextgen.recognize_graph_document(original(), {},
        graph_pipeline='agent-tools', vision_provider=reader)
    assert result['recognition_status'] == 'partial'
    assert result['text'] == text['body_text'] and result['graph_display_data'] == []
    assert result['review']['required']


def test_accidental_inventory_edges_are_cleared_before_source_inputs_and_merge():
    initial = document()
    initial['graphs'][0]['edges'] = [{'from': 'a', 'to': 'missing', 'edge_label': 'DO_NOT_LEAK'}]
    reader = Reader({'semantic_extract': initial})
    result = run(reader, audit=False)
    task = next(r for r in reader.requests if r['role'] == 'semantic_edges')['task']
    assert 'DO_NOT_LEAK' not in json.dumps(task) and 'edges' not in json.dumps(task)
    review = next(r for r in reader.requests if r['role'] == 'semantic_review')
    assert len(review['draft']['graphs'][0]['edges']) == 3
    assert 'DO_NOT_LEAK' not in json.dumps(review['draft'])
    assert result['graphs'][0]['complete']
    assert 'stage_audit' not in result
    assert {r['role'] for r in result['semantic_workflow']['readings']} == {
        'semantic_extract', 'semantic_edges', 'semantic_review', 'semantic_body', 'semantic_directions'}
    assert result['semantic_workflow']['readings'][1]['sources'][0]['edges'][0]['to'] == 'b'


def test_source_batches_are_max_six_and_exactly_two_can_execute_concurrently():
    whole = document()
    whole['graphs'][0].update(vertices=[{'id': f'n{i}', 'label': None, 'position': f'位置{i}'}
                                        for i in range(8)], edges=[])
    barrier, lock = threading.Barrier(2), threading.Lock()
    active = {'now': 0, 'maximum': 0}

    class ConcurrentReader(Reader):
        def __call__(self, prompt, images, budget):
            if budget.role != 'semantic_edges':
                return super().__call__(prompt, images, budget)
            with lock:
                active['now'] += 1
                active['maximum'] = max(active['maximum'], active['now'])
            try:
                barrier.wait(timeout=3)
                return super().__call__(prompt, images, budget)
            finally:
                with lock:
                    active['now'] -= 1

    reader = ConcurrentReader(source_document=whole)
    result = run(reader)
    tasks = [r['task'] for r in reader.requests if r['role'] == 'semantic_edges']
    assert active['maximum'] == 2 and len(tasks) == 2
    assert sorted(len(t['source_ids']) for t in tasks) == [2, 6]
    assert all(len(t['vertices']) == 8 for t in tasks)
    assert sorted(s for t in tasks for s in t['source_ids']) == [f'n{i}' for i in range(8)]
    assert result['graphs'][0]['complete']


@pytest.mark.parametrize('failed', [VisionError('invalid_output'), {'sources': []}])
def test_failed_or_empty_source_stage_requires_another_review_after_first_full_read(failed):
    reader = Reader({'semantic_edges': failed})
    result = run(reader)
    assert structural_roles(reader) == ['semantic_extract', 'semantic_edges', 'semantic_review', 'semantic_repair']
    assert next(r for r in reader.requests if r['role'] == 'semantic_review').get('review_mode') != 'read_only'
    assert result['semantic_workflow']['reviewed'] and result['graphs'][0]['complete']
    audit = result['semantic_workflow']['source_audit']['graphs'][0]
    assert audit['missing_source_ids'] == ['a', 'b', 'c']


def test_source_time_reserve_reaches_provider_deadline_and_does_not_shorten_review():
    reader = Reader()
    run(reader)
    source = next(c for c in reader.calls if c['request']['role'] == 'semantic_edges')
    review = next(c for c in reader.calls if c['request']['role'] == 'semantic_review')
    assert source['reserve_seconds'] > 0
    assert source['deadline'] == pytest.approx(source['task_deadline'] - source['reserve_seconds'])
    assert 0 < source['timeout'] < review['timeout']
    assert review['reserve_seconds'] == 0 and review['deadline'] == review['task_deadline']


def test_call_budget_limits_groups_and_missing_sources_remain_explicit_after_recovery():
    whole = document()
    whole['graphs'] = [dict(copy.deepcopy(whole['graphs'][0]), id=f'G{i}') for i in range(1, 5)]
    reader = Reader(source_document=whole)
    result = run(reader, budget=AgentBudget(seconds=30, calls=8))
    assert sum(r['role'] == 'semantic_edges' for r in reader.requests) == 3
    assert structural_roles(reader)[-1] == 'semantic_repair'
    assert result['semantic_workflow']['source_audit']['graphs'][3]['missing_source_ids'] == ['a', 'b', 'c']
    assert all(g['complete'] for g in result['graphs'])


def test_changed_edge_endpoint_gets_one_visual_confirmation_without_automatic_reversal():
    corrected = document()
    corrected['graphs'][0]['edges'][0]['to'] = 'c'
    reader = Reader({'semantic_review': {'issues': [{'scope': 'graph', 'graph_id': 'G1',
        'field': 'edges', 'source_ids': ['a'], 'message': '请核对从该节点出发的连线。'}]},
        'semantic_repair': corrected})
    result = run(reader)
    assert structural_roles(reader)[-1] == 'semantic_repair'
    repair_request = next(r for r in reader.requests if r['role'] == 'semantic_repair')
    assert any(issue.get('field') == 'edges' for issue in repair_request['remaining_issues'])
    assert result['graphs'][0]['edges'][0]['to'] == 'c'
    assert result['graphs'][0]['complete'] and not result['semantic_issues']


def test_glm_specialist_runs_at_most_once_after_qwen_review_failure():
    changed = document()
    changed['graphs'][0]['edges'][0]['weight'] = 1
    ordinary = Reader({'semantic_review': VisionError('invalid_output')})
    specialist = Specialist({'semantic_specialist': changed})
    result = run(providers(ordinary, specialist))
    assert structural_roles(specialist) == ['semantic_edges_glm_fast', 'semantic_specialist']
    assert result['graphs'][0]['edges'][0]['weight'] == 1
    assert result['graphs'][0]['complete']


def test_default_glm_source_provider_enables_thinking_without_hidden_retries():
    runner = SemanticRunner(AgentBudget(seconds=30, calls=8))
    remote = runner._provider_for('semantic_edges_glm')
    assert remote.name == 'glm' and remote.model == 'glm-5v-turbo'
    assert remote.thinking is True and remote.retries == 0
    fast = runner._provider_for('semantic_edges_glm_fast')
    assert fast.name == 'glm' and fast.thinking is False and fast.retries == 0


def test_visible_node_label_and_caption_changes_are_semantic_but_coordinates_are_not():
    before = document()
    changed = copy.deepcopy(before)
    changed['graphs'][0]['vertices'][1]['label'] = 'v₃'
    assert _review_changes(before, changed)[0]['scope'] == 'graph'
    changed = copy.deepcopy(before)
    changed['graphs'][0]['name'] = '(b)'
    assert _review_changes(before, changed)[0]['scope'] == 'graph'
    changed = copy.deepcopy(before)
    changed['graphs'][0]['vertices'][0].update(x=-100, y=50000, position='另一粗略位置')
    assert _review_changes(before, changed) == []


def test_explicit_unknown_style_is_not_the_same_as_declared_ordinary_default():
    before = document()
    before['graphs'][0]['edges'][0]['style'] = 'unknown'
    changed = copy.deepcopy(before)
    changed['graphs'][0]['edges'][0]['style'] = 'solid'
    assert _review_changes(before, changed)
    del before['graphs'][0]['edges'][0]['style']
    assert _review_changes(before, changed) == []


def test_unresolved_body_issue_at_budget_end_does_not_invalidate_correct_graphs():
    initial = document()
    initial['body_text'] = '③求顶点v₃的度数。'
    budget = AgentBudget(seconds=30, calls=8)

    def finish_review(request):
        budget.deadline = time.monotonic() + 10
        return {'issues': [{'scope': 'body', 'message': '正文关键数字仍需核实。'}]}

    reader = Reader({'semantic_extract': initial, 'semantic_review': finish_review,
                     'semantic_body': VisionError('invalid_output')})
    result = run(reader, budget=budget)
    assert structural_roles(reader) == ['semantic_extract', 'semantic_edges', 'semantic_review']
    assert result['body_complete'] is False and result['graphs'][0]['complete'] is True
    assert any(issue['scope'] == 'body' for issue in result['semantic_issues'])
    assert result['complete'] is False


def test_readonly_review_cannot_replace_source_edges_even_with_extra_document_fields():
    bad = document()
    bad['body_text'] = '未经许可重写的文字'
    bad['graphs'][0]['vertices'] = []
    bad['graphs'][0]['edges'] = []
    reader = Reader({'semantic_review': {'issues': [], **bad}})
    result = run(reader)
    assert structural_roles(reader) == ['semantic_extract', 'semantic_edges', 'semantic_review']
    assert result['body_text'] == document()['body_text']
    assert [v['id'] for v in result['graphs'][0]['vertices']] == ['a', 'b', 'c']
    assert [e['edge_label'] for e in result['graphs'][0]['edges']] == ['e₁', 'e₂', 'e₃']
    assert result['complete'] is True


def test_whole_workflow_attribute_repair_preserves_other_edges_panels_and_body():
    whole = document()
    whole['graphs'].append(dict(copy.deepcopy(whole['graphs'][0]), id='G2', name='(b)'))

    def conflict(request):
        eid = request['draft']['graphs'][0]['edges'][0]['id']
        return {'issues': [{'scope': 'graph', 'graph_id': 'G1', 'field': 'weight',
                            'edge_ids': [eid], 'message': '仅此边的权值需要核实。'}]}

    def repair(request):
        value = copy.deepcopy(request['draft'])
        value['body_text'] = '不允许顺手改写的题干'
        value['graphs'][0]['edges'][0].update(weight=7, color='red', **{'to': 'c'})
        value['graphs'][0]['edges'][1]['weight'] = 99
        value['graphs'][0]['vertices'][0]['label'] = 'FAKE'
        value['graphs'][1]['edges'] = []
        return value

    reader = Reader({'semantic_review': conflict, 'semantic_repair': repair}, source_document=whole)
    result = run(reader)
    first, second = result['graphs']
    assert first['edges'][0]['weight'] == 7
    assert first['edges'][0]['to'] == 'b' and first['edges'][0]['color'] == 'blue'
    assert first['edges'][1]['weight'] == 3
    assert first['vertices'][0]['label'] == 'v₁'
    assert len(second['edges']) == 3 and [e['weight'] for e in second['edges']] == [0, 3, 2]
    assert result['body_text'] == whole['body_text']
    audit = result['semantic_workflow']['repair_scope']
    assert audit['retained_graph_ids'] == ['G2']
    assert audit['field_permissions'][0]['mode'] == 'edge_fields'
    # Direction readers run after repair, so this also observes the scoped
    # intermediate state rather than relying on their eventual output.
    task = next(r['task'] for r in reader.requests if r['role'] == 'semantic_directions')
    assert [e['weight'] for e in task['graphs'][0]['edges']] == [7, 3, 2]
    assert [e['weight'] for e in task['graphs'][1]['edges']] == [0, 3, 2]


def test_body_and_direction_readers_cannot_modify_each_others_or_attribute_fields():
    def directions(request):
        result = direction_response(request['task'], document())
        result['body_text'] = '不能由方向角色修改的正文'
        graph = result['graphs'][0]
        graph['vertices'] = [{'id': 'fake', 'label': '假点'}]
        first = graph['edges'][0]
        first['from'], first['to'] = first['to'], first['from']
        first.update(weight=999, edge_label='假边名', color='red', style='dotted')
        return result

    body = {'body_text': '逐字核对后的新题干。', 'uncertainties': [],
            'graphs': [{'id': 'G1', 'vertices': [], 'edges': []}]}
    reader = Reader({'semantic_body': body, 'semantic_directions': directions})
    result = run(reader)
    assert result['body_text'] == body['body_text']
    graph = result['graphs'][0]
    assert [v['id'] for v in graph['vertices']] == ['a', 'b', 'c']
    assert len(graph['edges']) == 3
    edge = graph['edges'][0]
    assert (edge['from'], edge['to'], edge['direction']) == ('b', 'a', 'forward')
    assert (edge['weight'], edge['edge_label'], edge['color'], edge['style']) == (0, 'e₁', 'blue', 'dashed')
    assert result['semantic_workflow']['direction_audit']['ignored_response_fields']


def test_actual_tool_adapters_supply_candidate_measurements_to_the_visual_roles(local_worker_boundaries):
    from test_graph_semantic_geometry import picture
    raw, whole = picture()
    whole['graphs'][0]['edges'][0]['direction'] = 'forward'
    whole['graphs'][0]['directed'] = True
    reader = Reader(source_document=whole)
    result = recognize_semantic(raw, provider=reader, budget=AgentBudget(seconds=30, calls=16))
    events = local_worker_boundaries
    assert [row['stage'] for row in events if row['kind'] == 'injected_worker'] == ['layout', 'text']
    assert {row['tool'] for row in events if row['kind'] == 'injected_geometry_worker'} == {'opencv', 'sknw'}
    extract = next(r for r in reader.requests if r['role'] == 'semantic_extract')
    assert extract['local_layout_candidates']['panels']
    assert extract['local_marker_candidates']
    assert extract['local_ocr_candidates'][0]['text'] == '本地文字候选，须对照原图。'
    assert extract['local_ocr_candidates'][0]['authoritative'] is False
    source = next(r for r in reader.requests if r['role'] == 'semantic_edges')
    measured = source['local_connection_candidates']['candidates']
    assert {row['source'] for row in measured} == {'opencv', 'sknw'}
    assert all(row['proposal_only'] is True for row in measured)
    assert all(row['path_hint'] for row in measured)
    review = next(r for r in reader.requests if r['role'] == 'semantic_review')
    assert review['local_connection_candidates'][0]['candidates'] == measured
    directions = next(r for r in reader.requests if r['role'] == 'semantic_directions')
    assert directions['local_geometry_candidates'][0]['candidates'] == measured
    tool_rows = result['semantic_workflow']['tool_audit']
    assert {'image.semantic_text', 'image.semantic_layout', 'image.semantic_opencv',
            'image.semantic_sknw'} <= {row['tool'] for row in tool_rows}
    assert result['semantic_workflow']['geometry_required'] is False
    assert all(row['fixture_only'] for row in events)


def test_missing_small_dependency_is_explicit_but_not_a_content_acceptance_gate(monkeypatch, local_worker_boundaries):
    import graph_semantic_text
    monkeypatch.setattr(graph_semantic_text, '_cache_readiness', lambda: {
        'status': 'dependency_unavailable', 'worker_started': False})
    reader = Reader()
    result = run(reader)
    metrics = result['semantic_workflow']['local_tools']['text']['resource_metrics']
    assert metrics[-1]['status'] == 'dependency_unavailable'
    assert metrics[-1]['worker_started'] is False
    assert metrics[-1]['model_inference_completed'] is False
    assert not any(row.get('stage') == 'text' for row in local_worker_boundaries)
    assert reader.requests[0]['local_ocr_candidates'] == []
    assert result['complete'] is True and result['semantic_issues'] == []
