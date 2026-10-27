"""User-editable semantic structure, exercised in Node and actual Chromium."""
import copy
import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')


def document():
    return {'body_text': '（1）求 A 的度数。\n（2）求最短路径。', 'graphs': [
        {'id': 'G1', 'name': '(a)', 'vertices': [
            {'id': 'a', 'label': 'A'}, {'id': 'b', 'label': 'B'}, {'id': 'c', 'label': None}],
         'edges': [{'id': 'e1', 'from': 'a', 'to': 'b', 'direction': 'forward', 'weight': 2,
                    'edge_label': 'e₁', 'style': 'dashed', 'color': 'blue'}]},
        {'id': 'G2', 'name': '(b)', 'vertices': [{'id': 'a', 'label': 'X'}], 'edges': []}],
        'text_context': {'legends': [{'text': '虚线为候选边。', 'graph_ids': ['G1']}], 'captions': []}}


def run_model(code, data=None):
    if not NODE:
        pytest.skip('Node is required to execute the actual editor model')
    program = """
const fs=require('node:fs');
const editor=require('./static/graph-editor.js');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const model=editor.createModel(input);
""" + code
    result = subprocess.run([NODE, '-e', program], cwd=ROOT,
                            input=json.dumps(document() if data is None else data), text=True,
                            capture_output=True, check=True, timeout=15)
    return json.loads(result.stdout)


def test_weight_zero_direction_multiplicity_and_isolated_vertex_survive_snapshot():
    value = run_model("""
model.updateEdges('G1',['e1'],'weight',0);
model.updateEdges('G1',['e1'],'direction','undirected');
model.setEdgeCount('G1',['e1'],3);
model.renameVertex('G1','a','A′');
model.setBody('（1）求 A′ 的度数。\\n（2）求最短路径。');
console.log(JSON.stringify({document:model.getDocument(),issues:model.validate()}));
""")
    graph = value['document']['graphs'][0]
    assert value['issues'] == []
    assert len(graph['edges']) == 3 and len({edge['id'] for edge in graph['edges']}) == 3
    assert all(edge['weight'] == 0 and edge['direction'] == 'undirected' for edge in graph['edges'])
    assert all(edge['style'] == 'dashed' and edge['edge_label'] == 'e₁' for edge in graph['edges'])
    assert graph['vertices'][-1] == {'id': 'c', 'label': None}
    assert value['document']['body_text'].startswith('（1）求 A′')


def test_moving_only_one_endpoint_is_atomic_and_rejected_then_component_moves_with_unique_ids():
    value = run_model("""
const before=model.getDocument(); let problem;
try{model.moveVertices('G1','G2',['a']);}catch(error){problem=error.message;}
const unchanged=JSON.stringify(before)===JSON.stringify(model.getDocument());
model.moveVertices('G1','G2',['a','b']);
console.log(JSON.stringify({problem,unchanged,document:model.getDocument(),issues:model.validate()}));
""")
    assert value['unchanged'] and '相连' in value['problem']
    first, target = value['document']['graphs']
    assert first['vertices'] == [{'id': 'c', 'label': None}] and first['edges'] == []
    assert {vertex['label'] for vertex in target['vertices']} == {'X', 'A', 'B'}
    assert len({vertex['id'] for vertex in target['vertices']}) == 3
    labels = {vertex['id']: vertex['label'] for vertex in target['vertices']}
    assert labels[target['edges'][0]['from']] == 'A' and labels[target['edges'][0]['to']] == 'B'
    assert value['issues'] == []


def test_merge_and_undo_restore_all_graph_content_and_legend_association():
    value = run_model("""
model.mergeGraph('G1','G2'); const merged=model.getDocument();
model.undo(); const undone=model.getDocument();
model.setBody('edited'); model.reset();
console.log(JSON.stringify({merged,undone,reset:model.getDocument()}));
""")
    assert len(value['merged']['graphs']) == 1
    assert len(value['merged']['graphs'][0]['vertices']) == 4
    assert value['merged']['text_context']['legends'][0]['graph_ids'] == ['G2']
    assert value['undone'] == document()
    assert value['reset'] == document()


def test_edge_reassignment_requires_real_target_endpoints_and_preserves_source_isolated_nodes():
    value = run_model("""
let rejected=false;try{model.moveEdges('G1','G2',['e1'],'missing','a');}catch(_error){rejected=true;}
model.moveEdges('G1','G2',['e1'],'a','a');
console.log(JSON.stringify({rejected,document:model.getDocument(),issues:model.validate()}));
""")
    assert value['rejected'] and value['issues'] == []
    first, second = value['document']['graphs']
    assert len(first['vertices']) == 3 and first['edges'] == []
    assert second['edges'][0]['from'] == second['edges'][0]['to'] == 'a'
    assert second['edges'][0]['weight'] == 2


@pytest.mark.parametrize('mutation,phrase', [
    ("model.updateEdges('G1',['e1'],'direction','unknown');", '方向尚未确认'),
    ("model.updateEdges('G1',['e1'],'to','missing');", '有效的两个端点'),
    ("model.updateEdges('G1',['e1'],'weight','unknown');", '权重尚未确认'),
])
def test_unresolved_core_semantics_block_confirmation(mutation, phrase):
    issues = run_model(mutation + 'console.log(JSON.stringify(model.validate()));')
    assert any(phrase in issue for issue in issues)


def test_parallel_groups_preserve_different_labels_weights_and_directions():
    value = run_model("""
model.setEdgeCount('G1',['e1'],3);
const edges=model.getDocument().graphs[0].edges;
model.updateEdges('G1',[edges[1].id],'weight',7);
model.updateEdges('G1',[edges[2].id],'direction','undirected');
console.log(JSON.stringify(editor.groupEdges(model.getDocument().graphs[0],false).map(group=>group.length)));
""")
    assert value == [1, 1, 1]


def test_duplicate_imported_vertex_ids_never_attach_ambiguous_edge_to_first_node():
    value = document()
    value['graphs'][0]['vertices'][1]['id'] = 'a'
    result = run_model('console.log(JSON.stringify({document:model.getDocument(),issues:model.validate()}));', value)
    graph = result['document']['graphs'][0]
    assert len({vertex['id'] for vertex in graph['vertices']}) == 3
    assert graph['edges'][0]['from'] == '' and result['issues']


def test_deleting_a_graph_does_not_silently_reassign_its_legend_to_the_whole_question():
    value = run_model("""
model.deleteGraph('G1'); const issues=model.validate();
model.setContext('legends',0,{text:'虚线为候选边。',graph_ids:['G2']});
console.log(JSON.stringify({issues,document:model.getDocument(),finalIssues:model.validate()}));
""")
    assert any('关联了不存在的子图' in issue for issue in value['issues'])
    assert value['finalIssues'] == []


def test_malformed_weight_and_dangling_merge_endpoint_cannot_become_valid_by_omission():
    data = document()
    data['graphs'][0]['edges'][0]['weight'] = {'unreadable': True}
    data['graphs'][0]['edges'][0]['from'] = 'ghost'
    value = run_model("""
model.addVertex('G2','ghost');
model.mergeGraph('G1','G2');
console.log(JSON.stringify({document:model.getDocument(),issues:model.validate()}));
""", data)
    assert value['document']['graphs'][0]['edges'][0]['weight'] == 'unknown'
    assert value['document']['graphs'][0]['edges'][0]['from'] == ''
    assert len(value['issues']) == 2


@pytest.fixture
def browser_editor():
    executable = shutil.which('chromium')
    if not executable:
        pytest.skip('Chromium is required for actual editor interaction')
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(executable_path=executable, headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 1000})
        external = []
        page.route('**/*', lambda route: (external.append(route.request.url), route.abort()))
        page.set_content('<main id="editor"></main>')
        page.add_style_tag(content=(ROOT/'static/graph-editor.css').read_text())
        page.add_script_tag(content=(ROOT/'static/graph-editor-model.js').read_text())
        page.add_script_tag(content=(ROOT/'static/graph-editor.js').read_text())
        page.evaluate("""value => {
            window.changes=[];window.confirmations=[];window.cancelled=0;window.failSave=false;
            window.instance=DMateGraphEditor.mount(document.getElementById('editor'),{
                document:value,onChange:doc=>changes.push(doc),onCancel:()=>cancelled++,
                onConfirm:async doc=>{if(failSave)throw Error('保存失败，请重试');confirmations.push(doc);}
            });
        }""", document())
        yield page
        assert external == [], 'Editor must not invoke recognition, solving, or external services'
        browser.close()


def test_real_browser_edits_and_confirms_the_same_user_visible_document(browser_editor, tmp_path):
    page = browser_editor
    label = '<img src=x onerror="window.INJECTED=true">'
    page.get_by_label('节点 1 标签', exact=True).fill(label)
    page.get_by_label('题干、全部小问与公式', exact=True).fill('（1）求修改后的度数。\n（2）列出全部边。')
    page.get_by_label('边 1 权重', exact=True).fill('0')
    page.get_by_label('边 1 方向', exact=True).select_option('undirected')
    page.get_by_label('边 1 相同边数量', exact=True).fill('3')
    page.get_by_role('button', name='应用数量', exact=True).click()
    page.get_by_label('逐条编辑重边', exact=True).check()
    page.get_by_label('边 2 权重', exact=True).fill('7')
    page.get_by_label('我已对照原图核对题干与各子图', exact=True).check()
    page.get_by_role('button', name='保存并确认', exact=True).click()
    page.wait_for_function('confirmations.length===1')
    confirmed = page.evaluate('confirmations[0]')
    assert confirmed == page.evaluate('instance.getDocument()')
    assert confirmed['body_text'].startswith('（1）求修改后的度数。')
    assert confirmed['graphs'][0]['vertices'][0]['label'] == label
    assert [edge['weight'] for edge in confirmed['graphs'][0]['edges']] == [0, 7, 0]
    assert page.evaluate('window.INJECTED === undefined')
    assert page.locator('#editor img').count() == 0
    page.screenshot(path=str(tmp_path/'editor-desktop.png'), full_page=True)
    page.get_by_label('节点 1 标签', exact=True).fill('A′')
    assert not page.get_by_label('我已对照原图核对题干与各子图', exact=True).is_checked()
    assert page.evaluate('changes.at(-1).graphs[0].vertices[0].label') == 'A′'


def test_real_browser_adds_nodes_and_moves_edges_without_losing_select_values(browser_editor):
    page = browser_editor
    page.get_by_label('新节点标签', exact=True).fill('Z')
    page.get_by_role('button', name='添加节点', exact=True).click()
    assert page.get_by_label('节点 4 标签', exact=True).input_value() == 'Z'
    page.get_by_role('button', name='边 1', exact=True).click()
    page.get_by_text('调整所选边的子图归属', exact=True).click()
    page.get_by_label('边移动目标', exact=True).select_option('G2')
    page.get_by_label('移动后起点', exact=True).select_option('a')
    page.get_by_label('移动后终点', exact=True).select_option('a')
    page.get_by_role('button', name='移动这条边', exact=True).click()
    result = page.evaluate('instance.getDocument()')
    assert result['graphs'][0]['edges'] == [] and len(result['graphs'][0]['vertices']) == 4
    assert result['graphs'][1]['edges'][0]['from'] == result['graphs'][1]['edges'][0]['to'] == 'a'


def test_real_browser_unknown_direction_and_failed_save_keep_editable_draft(browser_editor):
    page = browser_editor
    page.get_by_label('边 1 方向', exact=True).select_option('unknown')
    page.get_by_label('我已对照原图核对题干与各子图', exact=True).check()
    page.get_by_role('button', name='保存并确认', exact=True).click()
    assert page.evaluate('confirmations.length') == 0
    assert page.get_by_text('请先处理上方标出的结构问题。', exact=True).is_visible()
    page.get_by_label('边 1 方向', exact=True).select_option('forward')
    page.evaluate('window.failSave=true')
    page.get_by_label('我已对照原图核对题干与各子图', exact=True).check()
    page.get_by_role('button', name='保存并确认', exact=True).click()
    page.get_by_text('保存失败，请重试', exact=True).wait_for()
    assert page.get_by_label('边 1 权重', exact=True).input_value() == '2'
    assert page.evaluate('instance.getDocument().graphs[0].edges[0].direction') == 'forward'


def test_real_browser_mobile_layout_and_two_step_delete(browser_editor):
    page = browser_editor
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
    page.get_by_label('选中节点 A', exact=True).check()
    page.get_by_role('button', name='删除所选节点', exact=True).click()
    assert page.evaluate('instance.getDocument().graphs[0].vertices.length') == 3
    page.get_by_role('button', name='删除所选节点', exact=True).click()
    assert page.evaluate('instance.getDocument().graphs[0].vertices.length') == 2
    assert page.evaluate('instance.getDocument().graphs[0].edges.length') == 0
    page.get_by_role('button', name='撤销', exact=True).click()
    assert page.evaluate('instance.getDocument().graphs[0].vertices.length') == 3
    assert page.evaluate('instance.getDocument().graphs[0].edges.length') == 1


def test_svg_editor_and_data_model_share_the_same_operations():
    if not NODE:
        pytest.skip('Node is required to verify graph editor exports')
    script = """
const model = require('./static/graph-editor-model.js');
const editor = require('./static/graph-editor.js');
if (editor.createModel !== model.createModel ||
    editor.validateDocument !== model.validateDocument ||
    editor.groupEdges !== model.groupEdges) process.exit(3);
const doc = {body_text:'check', graphs:[{
    id:'G1', vertices:[{id:'a',label:null},{id:'b',label:'B'}],
    edges:[{id:'e1',from:'a',to:'b',direction:'forward',weight:0}]
}]};
const state = editor.createModel(doc);
state.addEdge('G1', {from:'b',to:'a',direction:'forward'});
if (state.validate().length || state.getDocument().graphs[0].edges.length !== 2) process.exit(4);
state.undo();
if (state.getDocument().graphs[0].edges.length !== 1) process.exit(5);
"""
    process = subprocess.run([NODE, '-e', script], cwd=ROOT, capture_output=True,
                             text=True, timeout=15)
    assert process.returncode == 0, process.stderr or process.stdout
