"""Default deployment selects semantic OCR without eagerly loading models."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_agent_upload_route import install_reader, semantic_application, upload
from test_ocr_application_contract import application


@pytest.mark.parametrize('flag,enabled', [(None, True), ('1', True), ('0', False)])
def test_fresh_application_uses_one_gate_for_import_warmup_and_health(flag, enabled):
    # A fresh interpreter checks import-time selection; mutating an already
    # imported Flask module would miss accidental eager legacy model loading.
    program = r'''
import json, sys, threading, types
import requests
import ocr_runtime

def forbidden(*args, **kwargs):
    raise AssertionError('No network or model execution in startup contract')

requests.sessions.Session.send = forbidden
ocr_runtime.load_models = forbidden
ocr_runtime.recognize_image = forbidden
legacy = types.ModuleType('ocr')
legacy.OCRError = ocr_runtime.OCRError
legacy.load_models = forbidden
legacy.recognize_image = lambda raw: None
sys.modules['ocr'] = legacy
started = []
threading.Thread.start = lambda thread: started.append(thread._target.__name__)
import app
client = app.app.test_client()
print(json.dumps({
    'runtime_imported': app.recognize_image is ocr_runtime.recognize_image,
    'warmup_started': '_warm_ocr_models' in started,
    'semantic_selected': app._semantic_ocr_selected(),
    'health': client.get('/health').get_json()['graph_nextgen_enabled'],
    'ready': client.get('/ready').get_json()['graph_nextgen_enabled'],
}))
'''
    environment = {'PATH': os.environ.get('PATH', ''), 'LANG': 'C.UTF-8',
                   'PYTHONDONTWRITEBYTECODE': '1', 'OMP_NUM_THREADS': '1',
                   'OPENBLAS_NUM_THREADS': '1'}
    if flag is not None:
        environment['DMATE_GRAPH_NEXTGEN'] = flag
    result = subprocess.run([sys.executable, '-c', program],
        cwd=Path(__file__).resolve().parents[1], env=environment,
        text=True, capture_output=True, timeout=30, check=True)
    import json
    observed = json.loads(result.stdout.splitlines()[-1])
    assert observed == {'runtime_imported': enabled, 'warmup_started': not enabled,
                        'semantic_selected': enabled, 'health': enabled, 'ready': enabled}


def test_unset_deployment_flag_upload_runs_semantic_roles(semantic_application, monkeypatch):
    module, client, guards = semantic_application
    monkeypatch.delenv('DMATE_GRAPH_NEXTGEN', raising=False)
    reader = install_reader(monkeypatch)
    response = upload(client, task_id='default-semantic-upload')
    assert response.status_code == 200
    body = response.get_json()
    assert body['recognition_status'] == 'complete'
    assert module._semantic_ocr_selected()
    assert body['diagnostics']['semantic_workflow']['role_counts']['semantic_extract'] == 1
    assert body['diagnostics']['semantic_workflow']['role_counts']['semantic_edges'] == 1
    assert len(body['graph_structures'][0]['edges']) == 1
    assert [row['stage'] for row in guards['worker_events'] if row['kind'] == 'injected_worker'] == ['layout', 'text']
    assert reader.requests and guards['network'] == 0

