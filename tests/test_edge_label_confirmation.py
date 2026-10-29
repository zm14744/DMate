"""An independently printed numeric edge name survives signed confirmation."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from graph_confirmation import COOKIE_NAME, register_recognition
from test_ocr_application_contract import application
from test_semantic_chat_snapshot_frontend import run_js

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('explicit', [False, True])
def test_weight_and_name_remain_separate_through_confirm_browser_and_solver(application, monkeypatch, tmp_path, explicit):
    module, client, _ = application
    monkeypatch.setenv('DMATE_GRAPH_CONFIRMATION_DB', str(tmp_path / 'edge-names.sqlite3'))
    client.get('/graph/session')
    owner = hashlib.sha256((client.get_cookie(COOKIE_NAME).value + ':guest').encode()).hexdigest()
    register_recognition(owner, 'weighted-picture', 'a' * 64)
    edge = {'id': 'e1', 'from': 'a', 'to': 'b', 'direction': 'undirected',
            'weight': 200, 'edge_label': '200', 'edge_label_is_explicit': explicit}
    document = {'body_text': '列出边及权值。', 'graphs': [{'id': 'G1', 'name': '带权无向图',
        'directed': False, 'weighted': True, 'vertices': [{'id': 'a', 'label': 'A'}, {'id': 'b', 'label': 'B'}], 'edges': [edge]}]}
    response = client.post('/graph/confirm', json={'confirmed': True, 'request_id': 'weighted-picture',
        'source_sha256': 'a' * 64, 'document': document})
    assert response.status_code == 200, response.get_json()
    saved = response.get_json()
    result = saved['document']['graphs'][0]['edges'][0]
    assert (result['from'], result['to'], result['weight']) == ('a', 'b', 200)
    assert result['edge_label'] == ('200' if explicit else None)
    assert result['edge_label_is_explicit'] is explicit
    context = run_js({'operation': 'sanitize', 'context': saved['semantic_context']})
    assert context['document'] == saved['document']
    captured = []
    def answer(messages, **options):
        captured.append(options['teaching_context']['semantic_math']['document'])
        return {'ok': True, 'reply': 'A与B之间边的权值为200。'}
    monkeypatch.setattr(module, 'ask_ai', answer)
    result = client.post('/chat', json={'messages': [{'role': 'user', 'content': context['question_text']}],
        'semantic_context': context, 'request_kind': 'solution'})
    assert result.status_code == 200, result.get_json()
    assert captured[0]['graphs'][0]['edges'][0]['edge_label'] == ('200' if explicit else None)
    assert captured[0]['graphs'][0]['edges'][0]['edge_label_is_explicit'] is explicit


def test_user_entering_a_numeric_name_records_its_explicit_origin():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node unavailable')
    program = '''const assert=require('node:assert/strict'),api=require('./static/graph-editor-model.js');
const model=api.createModel({body_text:'',graphs:[{id:'G1',directed:false,weighted:true,
vertices:[{id:'a',label:'A'},{id:'b',label:'B'}],edges:[{id:'e',from:'a',to:'b',direction:'undirected',weight:200,edge_label:null}]}]});
model.updateEdges('G1',['e'],'edge_label','200');
const result=api.importDocument(model.getDocument());
assert.equal(result.graphs[0].edges[0].edge_label,'200');assert.equal(result.graphs[0].edges[0].edge_label_is_explicit,true);
model.updateEdges('G1',['e'],'edge_label','');assert.equal(model.getDocument().graphs[0].edges[0].edge_label_is_explicit,false);'''
    subprocess.run([node, '-e', program], cwd=ROOT, check=True, text=True, capture_output=True)
