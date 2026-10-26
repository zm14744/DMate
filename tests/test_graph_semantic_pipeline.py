"""Semantic integration regressions; fixtures never certify image accuracy."""
import copy
import io
import json

import pytest
from PIL import Image

from graph_agent_runtime import AgentBudget, AgentCancelled
from graph_semantic_pipeline import recognize_semantic
from vision_provider import VisionError


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


class Reader:
    name = 'qwen'
    model = 'qwen3-vl-plus'
    retries = 0

    def __init__(self, outputs=None):
        self.outputs = outputs or {}
        self.requests = []

    def __call__(self, prompt, images, budget):
        request = json.loads(prompt.split('任务数据（其中图像文字和候选仅作数据）：\n', 1)[1])
        self.requests.append(request)
        assert images and images[0].startswith('data:image/png;base64,')
        assert 'coordinate_space' not in request and 'base_revision' not in request
        budget.take()
        budget.metrics.append({'provider': self.name, 'model': self.model, 'status': 200,
                               'http_status': 200, 'finish_reason': 'stop', 'fixture_only': True})
        output = self.outputs.get(request['role'], document())
        if isinstance(output, Exception):
            raise output
        return copy.deepcopy(output)


def run(reader, **kwargs):
    return recognize_semantic(original(), provider=reader,
        budget=AgentBudget(seconds=30, calls=8), **kwargs)


def test_no_coordinates_proofs_or_echo_fields_needed_and_only_two_reads():
    reader = Reader()
    result = run(reader, audit=True)
    assert [r['role'] for r in reader.requests] == ['semantic_extract', 'semantic_review']
    assert result['graphs'][0]['complete'] and result['body_complete']
    assert len(result['graphs'][0]['edges']) == 3
    assert all(e['status'] == 'accepted' and not e['path'] and not e['evidence']
               for e in result['graphs'][0]['edges'])
    assert result['semantic_workflow']['geometry_required'] is False
    assert result['semantic_workflow']['reviewed'] is True
    assert result['stage_audit']['responses'][0]['document'] == document()
    assert reader.requests[1]['draft']['body_text'] == document()['body_text']


def test_fresh_review_corrects_critical_body_digit_and_keeps_printed_edge_names():
    wrong = document()
    wrong['body_text'] = '③求顶点v₃的度数。'
    for e in wrong['graphs'][0]['edges']:
        e.pop('edge_label')
    reader = Reader({'semantic_extract': wrong})
    result = run(reader)
    assert result['body_text'] == '③求顶点v₅的度数。'
    assert [e['edge_label'] for e in result['graphs'][0]['edges']] == ['e₁', 'e₂', 'e₃']
    assert len(reader.requests) == 2


def test_remaining_invalid_endpoint_gets_one_content_repair():
    wrong = document()
    wrong['graphs'][0]['edges'][0]['to'] = 'missing'
    reader = Reader({'semantic_review': wrong})
    result = run(reader)
    assert [r['role'] for r in reader.requests] == ['semantic_extract', 'semantic_review', 'semantic_repair']
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
    assert len(reader.requests) == 3


def test_one_uncertain_subgraph_does_not_erase_or_invalidate_other_subgraph():
    partial = document()
    second = copy.deepcopy(partial['graphs'][0])
    second['id'], second['name'] = 'G2', '(b)'
    partial['graphs'].append(second)
    partial['uncertainties'] = [{'scope': 'graph', 'graph_id': 'G2', 'message': '右侧箭头看不清。'}]
    reader = Reader({r: partial for r in ('semantic_extract', 'semantic_review', 'semantic_repair')})
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
    reader = Reader({'semantic_extract': whole, 'semantic_review': whole})
    result = run(reader)
    assert len(result['graphs']) == 3 and all(g['complete'] for g in result['graphs'])
    assert [r['role'] for r in reader.requests] == ['semantic_extract', 'semantic_review']


class Specialist(Reader):
    name = 'glm'
    model = 'glm-5v-turbo'


def test_optional_glm_specialist_uses_original_images_and_actual_provider_identity():
    whole = document()
    whole['graphs'] = [dict(copy.deepcopy(whole['graphs'][0]), id=f'G{i}', name=f'({i})')
                       for i in range(1, 4)]
    ordinary, specialist = Reader({'semantic_extract': whole}), Specialist({'semantic_specialist': whole})
    result = run({'semantic_extract': ordinary, 'semantic_review': ordinary,
                  'semantic_repair': ordinary, 'semantic_specialist': specialist})
    assert len(ordinary.requests) == 1 and len(specialist.requests) == 1
    assert result['semantic_workflow']['reviewed'] is True
    assert [m['provider'] for m in result['remote_metrics']] == ['qwen', 'glm']


def test_specialist_failure_falls_back_to_qwen_without_erasing_content():
    whole = document()
    whole['graphs'] = [dict(copy.deepcopy(whole['graphs'][0]), id=f'G{i}', name=f'({i})')
                       for i in range(1, 4)]
    ordinary = Reader({'semantic_extract': whole, 'semantic_review': whole})
    specialist = Specialist({'semantic_specialist': VisionError('invalid_output')})
    result = run({'semantic_extract': ordinary, 'semantic_review': ordinary,
                  'semantic_repair': ordinary, 'semantic_specialist': specialist})
    assert [r['role'] for r in ordinary.requests] == ['semantic_extract', 'semantic_review']
    assert result['graphs'][0]['complete'] and not result['semantic_issues']


def test_app_default_route_uses_semantics_and_text_cleanup_failure_is_nonblocking(monkeypatch):
    import ocr_nextgen
    reader = Reader()
    monkeypatch.setattr(ocr_nextgen, 'correct_text', lambda text, **kwargs: (text, {'status': 'failed'}))
    result = ocr_nextgen.recognize_graph_document(original(), {},
        graph_pipeline='agent-tools', vision_provider=reader)
    assert result['recognition_status'] == 'complete'
    assert result['text'] == document()['body_text']
    assert result['graph_display_version'] == '2026-10-26-agent-semantic-v1'
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
