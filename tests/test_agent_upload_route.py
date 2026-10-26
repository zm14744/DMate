"""Real Flask upload/agent wiring with explicit synthetic model boundaries."""
import hashlib
import io

from graph_pipeline_version import AGENT_PIPELINE_VERSION
from test_graph_agent_pipeline import original
from test_graph_semantic_pipeline import Reader
from test_ocr_application_contract import application, local_result


def test_upload_default_runs_langgraph_and_returns_same_source_identity(application, monkeypatch):
    module, client, guards = application
    monkeypatch.delenv('DMATE_GRAPH_PIPELINE', raising=False)
    monkeypatch.setattr(module, 'recognize_image', lambda raw: local_result())
    document = {'body_text': '', 'graphs': [{'id': 'G1', 'directed': False,
        'vertices': [{'id': 'a', 'label': None}, {'id': 'b', 'label': None}],
        'edges': [{'from': 'a', 'to': 'b', 'direction': 'undirected'}]}], 'uncertainties': []}
    model = Reader({'semantic_extract': document, 'semantic_review': document})
    monkeypatch.setattr('vision_provider.VisionProvider.available', lambda self: True)
    monkeypatch.setattr('vision_provider.VisionProvider.__call__',
                        lambda self, prompt, images, budget: model(prompt, images, budget))
    raw = original()
    task_id = 'agent-contract-upload-01'
    response = client.post('/ocr', data={'request_id': task_id,
        'image': (io.BytesIO(raw), 'synthetic.png')}, content_type='multipart/form-data')
    assert response.status_code == 200
    result = response.get_json()
    assert result['graph_display_version'] == AGENT_PIPELINE_VERSION
    assert result['recognition_status'] == 'complete', result.get('diagnostics')
    workflow = result['diagnostics']['semantic_workflow']
    assert workflow['task_id'] == task_id
    assert workflow['source_sha256'] == hashlib.sha256(raw).hexdigest()
    assert len(result['graph_structures'][0]['edges']) == 1
    assert workflow['role_counts'] == {'semantic_extract': 1, 'semantic_review': 1}
    assert workflow['reviewed'] is True and workflow['geometry_required'] is False
    assert all(metric.get('fixture_only') for metric in result['diagnostics']['remote_metrics'])
    assert guards['network'] == 0
    assert client.get('/health').get_json()['graph_nextgen_engine'] == 'agent-tools'
