"""Current canvas layout is described locally, including in guidance snapshots."""
import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_node(program):
    executable = shutil.which('node')
    if not executable:
        pytest.skip('Node is required to execute the drawing model')
    return json.loads(subprocess.run(
        [executable, '-e', program], cwd=ROOT, text=True,
        capture_output=True, check=True, timeout=15).stdout)


def test_drawing_metadata_tracks_geometry_styles_and_undo_without_a_model_call():
    value = run_node('''
const modelApi=require('./static/graph-editor-model.js');
const format=require('./static/graph-editor-format.js');
const model=modelApi.createModel({body_text:'',graphs:[{id:'G1',name:'绘图',
  directed:false,weighted:false,visual_description:'旧外观',
  vertices:[{id:'a',label:'A',x:-.2,y:.2,position_description:'旧位置'},
    {id:'b',label:'B',x:1.2,y:.2},{id:'c',label:null,display_label:'1',x:.5,y:.9}],
  edges:[{id:'ab',from:'a',to:'b',direction:'undirected',style:'dashed',
    path:[[-.2,.2],[.5,.5],[1.2,.2]]}]}]},undefined,{drawingOnly:true});
const before=model.getDocument();
model.moveVertex('G1','a',1.4,1.2);
const moved=model.getDocument(),rows=format.graphRows(moved.graphs[0],0);
model.undo();const undone=model.getDocument();model.redo();
model.deleteVertices('G1',['c']);model.deleteVertices('G1',['b']);
console.log(JSON.stringify({before,moved,rows,undone,single:model.getDocument()}));
''')
    before = value['before']['graphs'][0]
    assert [v['position_description'] for v in before['vertices']] == [
        '图内左上方', '图内右上方', '图内下方']
    assert '1 条虚线边' in before['visual_description']
    assert '弯曲或折线路径' in before['visual_description']
    assert value['undone'] == value['before']
    moved = value['moved']['graphs'][0]
    assert moved['vertices'][0]['position_description'] == '图内右下方'
    assert moved['vertices'][0]['x'] == 1.4
    assert moved['visual_description'] != before['visual_description']
    assert len(value['rows']['positions']) == 3
    assert all('位置未记录' not in row['txt'] for row in value['rows']['positions'])
    single = value['single']['graphs'][0]
    assert single['vertices'][0]['position_description'] == '图内中部'
    assert '1 个顶点、0 条边' in single['visual_description']


def test_scan_observations_survive_and_coordinate_fallback_does_not_mutate_them():
    value = run_node('''
const modelApi=require('./static/graph-editor-model.js');
const format=require('./static/graph-editor-format.js');
const input={body_text:'',graphs:[{id:'G1',visual_description:'原图是交叉曲线',
  vertices:[{id:'a',label:'A',x:0,y:0,position_description:'原图左上角'},
    {id:'b',label:'B',x:1,y:1}],edges:[]}]};
const model=modelApi.createModel(input);
model.moveVertex('G1','a',.2,.3);
const snapshot=model.getDocument(),rows=format.graphRows(snapshot.graphs[0],0);
const fallback=structuredClone(snapshot.graphs[0]);delete fallback.visual_description;
console.log(JSON.stringify({snapshot,rows,fallback:format.graphRows(fallback,0),input}));
''')
    graph = value['snapshot']['graphs'][0]
    assert graph['visual_description'] == value['rows']['description'] == '原图是交叉曲线'
    assert graph['vertices'][0]['position_description'] == '原图左上角'
    assert value['rows']['positions'][1]['txt'] == 'B：图内右下方'
    assert 'position_description' not in graph['vertices'][1]
    assert '按当前画布位置' in value['fallback']['description']
    assert value['input']['graphs'][0]['vertices'][0]['x'] == 0


def test_guidance_preserves_current_canvas_metadata_in_mocked_context():
    import drawing_guidance

    payload = {'document': {'body_text': '', 'graphs': [{
        'id': 'G1', 'name': '绘图', 'directed': False, 'weighted': False,
        'visual_description': '由 2 个顶点、1 条边组成。按当前画布位置，顶点分布于图内左上方、图内右下方。',
        'vertices': [
            {'id': 'a', 'label': 'A', 'x': -.2, 'y': .2, 'position_description': '图内左上方'},
            {'id': 'b', 'label': 'B', 'x': 1.2, 'y': .8, 'position_description': '图内右下方'}],
        'edges': [{'id': 'ab', 'from': 'a', 'to': 'b', 'direction': 'undirected'}]}]}}
    completion = Mock(return_value={'ok': True, 'content': 'A 位于左上方，B 位于右下方。'})
    drawing_guidance.guide_drawing(payload, completion=completion)
    sent = json.loads(completion.call_args.args[0][1]['content'])['document']['graphs'][0]
    source = payload['document']['graphs'][0]
    assert sent['visual_description'] == source['visual_description']
    assert sent['vertices'] == source['vertices']
    assert completion.call_count == 1
