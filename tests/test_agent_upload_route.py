"""Real Flask upload/agent wiring with explicit synthetic model boundaries."""
import hashlib
import io
import copy
import json
from unittest.mock import Mock

import pytest

from graph_pipeline_version import AGENT_PIPELINE_VERSION
from test_graph_agent_pipeline import original
from test_graph_semantic_pipeline import Reader, install_semantic_worker_fixtures
from test_ocr_application_contract import application, local_result
from vision_provider import VisionError


@pytest.fixture
def semantic_application(application, monkeypatch, tmp_path):
    module, client, guards = application
    monkeypatch.delenv('DMATE_GRAPH_PIPELINE', raising=False)
    blocked = []
    worker_events = install_semantic_worker_fixtures(monkeypatch, lock_root=tmp_path)
    for owner, name in ((module, 'recognize_image'), (module, 'recognize_graphs')):
        handler = Mock(side_effect=AssertionError('Semantic upload must not call '+name))
        monkeypatch.setattr(owner, name, handler)
        blocked.append(handler)
    yield module, client, {**guards, 'worker_events': worker_events}
    for handler in blocked:
        handler.assert_not_called()


def visual_document():
    return {'body_text': '', 'graphs': [{'id': 'G1', 'directed': False,
        'vertices': [{'id': 'a', 'label': None}, {'id': 'b', 'label': None}],
        'edges': [{'from': 'a', 'to': 'b', 'direction': 'undirected'}]}], 'uncertainties': []}


def source_reply(document, task):
    """Render only the assigned synthetic outgoing/undirected source rows."""
    graph = next(g for g in document['graphs'] if g['id'] == task['graph_id'])
    ids = {v['id'] for v in graph['vertices']}
    assert set(task['source_ids']) <= ids
    assert {v['id'] for v in task['vertices']} == ids
    sources = []
    for source in task['source_ids']:
        edges = []
        for edge in graph['edges']:
            if edge['from'] == source:
                target = edge['to']
            elif edge['direction'] == 'undirected' and edge['to'] == source:
                target = edge['from']
            else:
                continue
            edges.append({'to': target, **{key: copy.deepcopy(edge[key]) for key in
                ('direction', 'weight', 'edge_label', 'color', 'style') if key in edge}})
        sources.append({'id': source, 'edges': edges})
    return {'sources': sources}


def install_reader(monkeypatch, outputs=None):
    document = visual_document()
    roles = {role: copy.deepcopy(value) for role, value in (outputs if outputs is not None else {
        'semantic_extract': document}).items()}
    full = copy.deepcopy(roles.get('semantic_extract', document))
    if not isinstance(full, dict):
        full = copy.deepcopy(document)
    if isinstance(roles.get('semantic_extract'), dict):
        for graph in roles['semantic_extract'].get('graphs', []):
            graph['edges'] = []
    model = Reader(roles, source_document=full)

    def read(self, prompt, images, budget):
        request = json.loads(prompt.rsplit('\n', 1)[1])
        if request['role'] == 'semantic_edges':
            model.outputs['semantic_edges'] = source_reply(full, request['task'])
        return model(prompt, images, budget)

    monkeypatch.setattr('vision_provider.VisionProvider.available', lambda self: self.name == 'qwen')
    monkeypatch.setattr('vision_provider.VisionProvider.__call__', read)
    return model


def upload(client, *, task_id='semantic-upload-contract', raw=None):
    return client.post('/ocr', data={'request_id': task_id,
        'image': (io.BytesIO(original() if raw is None else raw), 'synthetic.png')},
        content_type='multipart/form-data')


@pytest.mark.parametrize('local_available', [True, False])
def test_upload_default_runs_local_tool_adapters_and_returns_same_source_identity(
        semantic_application, monkeypatch, local_available):
    module, client, guards = semantic_application
    monkeypatch.setattr(module, 'OCR_AVAILABLE', local_available)
    model = install_reader(monkeypatch)
    import ocr_nextgen
    entry = Mock(wraps=ocr_nextgen.recognize_graph_document)
    monkeypatch.setattr(ocr_nextgen, 'recognize_graph_document', entry)
    initial = client.get('/ready').get_json()
    assert initial['recognition_mode'] == 'semantic_visual'
    assert initial['local_ocr_required'] is False and initial['recognition_ready'] is False
    raw = original()
    task_id = 'agent-contract-upload-01'
    response = upload(client, task_id=task_id, raw=raw)
    assert response.status_code == 200
    result = response.get_json()
    assert result['graph_display_version'] == AGENT_PIPELINE_VERSION
    assert result['recognition_status'] == 'complete', result.get('diagnostics')
    workflow = result['diagnostics']['semantic_workflow']
    assert workflow['task_id'] == task_id
    assert workflow['source_sha256'] == hashlib.sha256(raw).hexdigest()
    assert len(result['graph_structures'][0]['edges']) == 1
    assert workflow['role_counts'] == {'semantic_extract': 1, 'semantic_edges': 1,
                                      'semantic_review': 1, 'semantic_body': 1}
    assert workflow['reviewed'] is True and workflow['geometry_required'] is False
    assert entry.call_count == 1 and entry.call_args.kwargs['graph_pipeline'] == 'agent-tools'
    local_input = entry.call_args.args[1]
    assert local_input['text'] == '' and local_input['layout']['status'] == 'pending'
    assert {m['stage'] for m in local_input['resource_metrics']} == {'text', 'layout', 'formula'}
    assert {m['stage']: m['status'] for m in local_input['resource_metrics']} == {
        'layout': 'pending', 'text': 'pending', 'formula': 'skipped'}
    assert all(m['worker_started'] is False for m in local_input['resource_metrics'])
    local = result['diagnostics']['local_ocr']
    assert local['mode'] == 'semantic_with_local_tools'
    assert local['required'] is False and local['text_succeeded'] is True
    assert result['diagnostics']['text_evidence']['complete'] is True
    assert '本地文字候选，须对照原图。' in model.requests[0]['local_ocr_hint_may_be_wrong']
    assert '不是已确认正文' in model.requests[0]['local_ocr_hint_may_be_wrong']
    assert model.requests[0]['local_ocr_candidates'][0]['authoritative'] is False
    assert [e['stage'] for e in guards['worker_events'] if e['kind'] == 'injected_worker'] == ['layout', 'text']
    assert all(e['fixture_only'] for e in guards['worker_events'])
    assert workflow['tool_audit'], 'The actual CPU preparation and tool registry must still run'
    assert all(metric.get('fixture_only') for metric in result['diagnostics']['remote_metrics'])
    assert guards['network'] == 0
    assert client.get('/health').get_json()['graph_nextgen_engine'] == 'agent-tools'
    ready = client.get('/ready').get_json()
    assert ready['ocr_available'] is local_available and ready['ocr_ready'] is True
    assert ready['recognition_ready'] is True
    assert ready['ocr_stages']['semantic']['status'] == 'complete'
    assert ready['ocr_stages']['text']['status'] == 'ok'
    assert ready['ocr_stages']['text']['model_inference_completed'] is True
    assert ready['ocr_stages']['layout']['model_inference_completed'] is True
    assert ready['ocr_stages']['formula']['status'] == 'skipped'
    assert 'Small' in ready['ocr_status'] and '降级' not in ready['ocr_status']


def test_semantic_review_failure_keeps_first_read_partial_without_local_failure(
        semantic_application, monkeypatch):
    _, client, _ = semantic_application
    install_reader(monkeypatch, {'semantic_extract': visual_document(),
        'semantic_review': VisionError('invalid_output'),
        'semantic_repair': VisionError('invalid_output')})
    response = upload(client)
    body = response.get_json()
    assert response.status_code == 200 and body['recognition_status'] == 'partial'
    assert len(body['graph_structures'][0]['edges']) == 1
    assert body['review']['required'] is True
    assert body['diagnostics']['semantic_workflow']['reviewed'] is False
    assert body['diagnostics']['local_ocr']['stages']['text']['status'] == 'ok'
    assert client.get('/ready').get_json()['ocr_stages']['semantic']['status'] == 'partial'


def test_small_dependency_failure_is_visible_and_does_not_fake_worker_completion(
        semantic_application, monkeypatch):
    import graph_semantic_text
    _, client, guards = semantic_application
    monkeypatch.setattr(graph_semantic_text, '_cache_readiness', lambda: {
        'status': 'dependency_unavailable', 'worker_started': False})
    model = install_reader(monkeypatch)
    body = upload(client).get_json()
    local = body['diagnostics']['local_ocr']
    assert body['recognition_status'] == 'complete'
    assert local['text_succeeded'] is False and local['required'] is False
    assert local['stages']['text'] == {
        'status': 'dependency_unavailable', 'worker_started': False,
        'model_inference_completed': False}
    assert not any(row.get('stage') == 'text' for row in guards['worker_events'])
    assert model.requests[0]['local_ocr_candidates'] == []
    ready = client.get('/ready').get_json()
    assert ready['recognition_ready'] is True and ready['ocr_ready'] is False
    assert ready['ocr_stages']['text']['status'] == 'dependency_unavailable'


def test_all_visual_reads_fail_without_mistaking_local_tool_success_for_recognition(
        semantic_application, monkeypatch):
    _, client, _ = semantic_application
    model = install_reader(monkeypatch, {role: VisionError('invalid_output')
        for role in ('semantic_extract', 'semantic_review', 'semantic_repair')})
    response = upload(client)
    body = response.get_json()
    assert response.status_code == 200 and body['recognition_status'] == 'failed'
    assert body['review']['required'] is True and body.get('error')
    assert model.requests and body['diagnostics']['local_ocr']['text_succeeded'] is True
    ready = client.get('/ready').get_json()
    assert ready['recognition_ready'] is False and ready['ocr_ready'] is True
    assert ready['ocr_stages']['semantic']['status'] == 'failed'
    assert '公式' not in ready['ocr_status']


def test_missing_visual_key_does_not_turn_local_workers_into_recognition_success(
        semantic_application, monkeypatch):
    _, client, _ = semantic_application
    model = install_reader(monkeypatch)
    monkeypatch.setattr('vision_provider.VisionProvider.available', lambda self: False)
    response = upload(client)
    body = response.get_json()
    assert body['recognition_status'] == 'failed' and model.requests == []
    assert body['diagnostics']['remote_metrics'] == []
    assert client.get('/ready').get_json()['recognition_ready'] is False


def test_text_only_semantic_upload_has_no_graph_hint_or_local_worker_requirement(
        semantic_application, monkeypatch):
    _, client, _ = semantic_application
    document = {'body_text': '证明该等式。', 'graphs': [], 'uncertainties': []}
    model = install_reader(monkeypatch, {'semantic_extract': document})
    monkeypatch.setattr('ocr_nextgen.correct_text', lambda text, **kwargs: (text, {'status': 'unavailable'}))
    body = upload(client).get_json()
    assert body['recognition_status'] == 'complete' and body['text'] == document['body_text']
    assert body['graph_structures'] == []
    assert [r['role'] for r in model.requests] == ['semantic_extract', 'semantic_review', 'semantic_body']
    assert body['diagnostics']['text_evidence']['second_pass_reviewed'] is True


def test_semantic_upload_cancelled_before_start_sends_no_visual_request(
        semantic_application, monkeypatch):
    _, client, _ = semantic_application
    model = install_reader(monkeypatch)
    task_id = 'semantic-cancel-before-start'
    assert client.post('/ocr/cancel', json={'request_id': task_id}).get_json()['cancelled']
    assert upload(client, task_id=task_id).get_json() == {'cancelled': True}
    assert model.requests == []


def test_semantic_upload_cancelled_after_first_read_does_not_start_review_or_legacy(
        semantic_application, monkeypatch):
    module, client, _ = semantic_application
    task_id = 'semantic-cancel-after-read'
    model = install_reader(monkeypatch)

    def read_then_cancel(self, prompt, images, budget):
        result = model(prompt, images, budget)
        module._mark_ocr_cancelled(task_id)
        return result

    monkeypatch.setattr('vision_provider.VisionProvider.__call__', read_then_cancel)
    assert upload(client, task_id=task_id).get_json() == {'cancelled': True}
    assert [request['role'] for request in model.requests] == ['semantic_extract']
    ready = client.get('/ready').get_json()
    assert ready['recognition_ready'] is False and ready['ocr_stages']['semantic']['status'] == 'cancelled'


def test_evidence_route_still_requests_local_text_before_its_graph_engine(application, monkeypatch):
    module, client, _ = application
    import ocr_nextgen
    from test_ocr_application_contract import graph_result
    local = Mock(return_value=local_result())
    engine = Mock(return_value=graph_result())
    monkeypatch.setattr(module, 'recognize_image', local)
    monkeypatch.setattr(ocr_nextgen, 'recognize_graph_document', engine)
    response = upload(client)
    assert response.status_code == 200
    local.assert_called_once()
    assert engine.call_args.kwargs['graph_pipeline'] == 'evidence-two-pass'
    ready = client.get('/ready').get_json()
    assert ready['recognition_mode'] == 'local_ocr_then_vision'
    assert ready['local_ocr_required'] is True and ready['ocr_ready'] is True
