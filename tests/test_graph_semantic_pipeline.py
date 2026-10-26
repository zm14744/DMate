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
        default = (source_response(request['task'], self.source_document)
                   if request['role'] in ('semantic_edges', 'semantic_edges_glm') else document())
        output = self.outputs.get(request['role'], default)
        if callable(output):
            output = output(request)
        if isinstance(output, Exception):
            raise output
        return copy.deepcopy(output)


def run(reader, **kwargs):
    budget = kwargs.pop('budget', None) or AgentBudget(seconds=30, calls=8)
    return recognize_semantic(original(), provider=reader,
        budget=budget, **kwargs)


def test_inventory_then_blind_source_read_then_fresh_review_without_pixel_protocol():
    reader = Reader()
    result = run(reader, audit=True)
    assert [r['role'] for r in reader.requests] == ['semantic_extract', 'semantic_edges', 'semantic_review']
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
    assert result['semantic_workflow']['edge_strategy'] == 'node_inventory_then_source_conditioned_edges'
    assert len(result['semantic_workflow']['source_audit']['graphs']) == 1


def test_fresh_review_corrects_critical_body_digit_and_keeps_printed_edge_names():
    wrong = document()
    wrong['body_text'] = '③求顶点v₃的度数。'
    for e in wrong['graphs'][0]['edges']:
        e.pop('edge_label')
    reader = Reader({'semantic_extract': wrong})
    result = run(reader)
    assert result['body_text'] == '③求顶点v₅的度数。'
    assert [e['edge_label'] for e in result['graphs'][0]['edges']] == ['e₁', 'e₂', 'e₃']
    assert len(reader.requests) == 4
    assert reader.requests[-1]['role'] == 'semantic_repair'
    assert any(issue['scope'] == 'body' for issue in reader.requests[-1]['remaining_issues'])


def test_remaining_invalid_endpoint_gets_one_content_repair():
    wrong = document()
    wrong['graphs'][0]['edges'][0]['to'] = 'missing'
    reader = Reader({'semantic_review': wrong})
    result = run(reader)
    assert [r['role'] for r in reader.requests] == ['semantic_extract', 'semantic_edges', 'semantic_review', 'semantic_repair']
    assert reader.requests[-1]['remaining_issues']
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
    assert [r['role'] for r in reader.requests] == ['semantic_extract', 'semantic_review', 'semantic_repair']
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
    assert [r['role'] for r in reader.requests] == ['semantic_extract', 'semantic_review', 'semantic_repair']
    assert result['graphs'][0]['complete']


def test_body_only_document_is_valid_and_independently_reviewed():
    text = {'body_text': '写出握手定理。', 'graphs': [], 'uncertainties': []}
    result = run(Reader({'semantic_extract': text, 'semantic_review': text}))
    assert result['graphs'] == [] and result['body_complete']
    assert not result['semantic_issues']


def test_body_uncertainty_preserves_valid_graph_and_does_not_loop():
    partial = document()
    partial['uncertainties'] = [{'scope': 'body', 'message': '顶部题干在原图中裁切。'}]
    reader = Reader({r: partial for r in ('semantic_extract', 'semantic_review', 'semantic_repair')})
    result = run(reader)
    assert result['graphs'][0]['complete']
    assert not result['body_complete']
    assert len(reader.requests) == 4


def test_one_uncertain_subgraph_does_not_erase_or_invalidate_other_subgraph():
    partial = document()
    second = copy.deepcopy(partial['graphs'][0])
    second['id'], second['name'] = 'G2', '(b)'
    partial['graphs'].append(second)
    partial['uncertainties'] = [{'scope': 'graph', 'graph_id': 'G2', 'message': '右侧箭头看不清。'}]
    reader = Reader({r: partial for r in ('semantic_extract', 'semantic_review', 'semantic_repair')}, source_document=partial)
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
    reader = Reader({'semantic_extract': whole, 'semantic_review': whole}, source_document=whole)
    result = run(reader)
    assert len(result['graphs']) == 3 and all(g['complete'] for g in result['graphs'])
    assert [r['role'] for r in reader.requests].count('semantic_edges') == 3
    assert reader.requests[0]['role'] == 'semantic_extract' and reader.requests[-1]['role'] == 'semantic_review'


class Specialist(Reader):
    name = 'glm'
    model = 'glm-5v-turbo'


def test_optional_glm_reads_source_groups_and_qwen_independently_reviews_all_graphs():
    whole = document()
    whole['graphs'] = [dict(copy.deepcopy(whole['graphs'][0]), id=f'G{i}', name=f'({i})')
                       for i in range(1, 4)]
    ordinary = Reader({'semantic_extract': whole, 'semantic_review': whole}, source_document=whole)
    specialist = Specialist(source_document=whole)
    result = run({'semantic_extract': ordinary, 'semantic_review': ordinary,
                  'semantic_repair': ordinary, 'semantic_edges_glm': specialist, 'semantic_specialist': specialist})
    assert [r['role'] for r in ordinary.requests] == ['semantic_extract', 'semantic_review']
    assert len(specialist.requests) == 3 and all(r['role'] == 'semantic_edges_glm' for r in specialist.requests)
    assert result['semantic_workflow']['reviewed'] is True
    assert [m['provider'] for m in result['remote_metrics']] == ['qwen', 'glm', 'glm', 'glm', 'qwen']
    assert all(c['images'][0] == ordinary.calls[0]['images'][0] for c in specialist.calls)


def test_source_specialist_failure_falls_back_to_qwen_without_erasing_content():
    whole = document()
    whole['graphs'] = [dict(copy.deepcopy(whole['graphs'][0]), id=f'G{i}', name=f'({i})')
                       for i in range(1, 4)]
    ordinary = Reader({'semantic_extract': whole, 'semantic_review': whole}, source_document=whole)
    specialist = Specialist({'semantic_edges_glm': VisionError('invalid_output')}, source_document=whole)
    result = run({'semantic_extract': ordinary, 'semantic_review': ordinary,
                  'semantic_repair': ordinary, 'semantic_edges': ordinary,
                  'semantic_edges_glm': specialist, 'semantic_specialist': specialist})
    assert [r['role'] for r in ordinary.requests].count('semantic_edges') == 3
    assert ordinary.requests[-1]['role'] == 'semantic_review'
    assert result['graphs'][0]['complete'] and not result['semantic_issues']


def test_app_default_route_uses_semantics_and_text_cleanup_failure_is_nonblocking(monkeypatch):
    import ocr_nextgen
    reader = Reader()
    monkeypatch.setattr(ocr_nextgen, 'correct_text', lambda text, **kwargs: (text, {'status': 'failed'}))
    result = ocr_nextgen.recognize_graph_document(original(), {},
        graph_pipeline='agent-tools', vision_provider=reader)
    assert result['recognition_status'] == 'complete'
    assert result['text'] == document()['body_text']
    assert result['graph_display_version'] == '2026-10-26-agent-semantic-v2'
    assert '颜色 blue' in result['visual_text'] and '虚线' in result['visual_text']
    assert 'semantic_workflow' in result['diagnostics']


def test_app_allows_text_only_and_marks_remaining_body_issue_partial(monkeypatch):
    import ocr_nextgen
    text = {'body_text': '求图的……', 'graphs': [],
            'uncertainties': [{'scope': 'body', 'message': '原图末尾裁切。'}]}
    reader = Reader({r: text for r in ('semantic_extract', 'semantic_review', 'semantic_repair')})
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
    assert len(result['semantic_workflow']['readings']) == 3
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

    reader = ConcurrentReader({'semantic_extract': whole, 'semantic_review': whole}, source_document=whole)
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
    assert [r['role'] for r in reader.requests] == ['semantic_extract', 'semantic_edges', 'semantic_review', 'semantic_repair']
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
    reader = Reader({role: whole for role in ('semantic_extract', 'semantic_review', 'semantic_repair')}, source_document=whole)
    result = run(reader)
    assert sum(r['role'] == 'semantic_edges' for r in reader.requests) == 3
    assert reader.requests[-1]['role'] == 'semantic_repair'
    assert result['semantic_workflow']['source_audit']['graphs'][3]['missing_source_ids'] == ['a', 'b', 'c']
    assert all(g['complete'] for g in result['graphs'])


def test_changed_edge_endpoint_gets_one_visual_confirmation_without_automatic_reversal():
    corrected = document()
    corrected['graphs'][0]['edges'][0]['to'] = 'c'
    reader = Reader({'semantic_review': corrected, 'semantic_repair': corrected})
    result = run(reader)
    assert reader.requests[-1]['role'] == 'semantic_repair'
    assert any(issue['kind'] == 'independent_reading_changed' for issue in reader.requests[-1]['remaining_issues'])
    assert result['graphs'][0]['edges'][0]['to'] == 'c'
    assert result['graphs'][0]['complete'] and not result['semantic_issues']


def test_glm_specialist_runs_at_most_once_after_qwen_review_failure():
    changed = document()
    changed['graphs'][0]['edges'][0]['weight'] = 1
    ordinary = Reader({'semantic_review': VisionError('invalid_output')})
    specialist = Specialist({'semantic_specialist': changed})
    result = run({'semantic_extract': ordinary, 'semantic_edges_glm': specialist,
                  'semantic_review': ordinary, 'semantic_repair': ordinary, 'semantic_specialist': specialist})
    assert [r['role'] for r in specialist.requests] == ['semantic_edges_glm', 'semantic_specialist']
    assert result['graphs'][0]['edges'][0]['weight'] == 1
    assert result['graphs'][0]['complete']


def test_default_glm_source_provider_enables_thinking_without_hidden_retries():
    runner = SemanticRunner(AgentBudget(seconds=30, calls=8))
    remote = runner._provider_for('semantic_edges_glm')
    assert remote.name == 'glm' and remote.model == 'glm-5v-turbo'
    assert remote.thinking is True and remote.retries == 0


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


def test_unconfirmed_body_change_at_budget_end_does_not_invalidate_correct_graphs():
    initial = document()
    initial['body_text'] = '③求顶点v₃的度数。'
    budget = AgentBudget(seconds=30, calls=8)

    def finish_review(request):
        budget.deadline = time.monotonic() + 10
        return document()

    reader = Reader({'semantic_extract': initial, 'semantic_review': finish_review})
    result = run(reader, budget=budget)
    assert [r['role'] for r in reader.requests] == ['semantic_extract', 'semantic_edges', 'semantic_review']
    assert result['body_complete'] is False and result['graphs'][0]['complete'] is True
    assert any(issue['scope'] == 'body' for issue in result['semantic_issues'])
    assert result['complete'] is False
