"""Appearance and anonymous-point references remain consistent with saved data."""
import json
import shutil
import subprocess

import pytest

from test_scan_drawing_separation import ROOT, scan_page, open_scan, drag


def anonymous_graph():
    return {
        'id': 'G1', 'name': '左图', 'directed': False, 'weighted': False,
        'visual_description': '四个顶点分布在外圈，另一个顶点位于中心。',
        'vertices': [
            {'id': 'v2', 'label': None, 'x': .8, 'y': .2, 'position_description': '外圈右上方'},
            {'id': 'v1', 'label': None, 'x': .2, 'y': .2, 'position_description': '外圈左上方'},
            {'id': 'v3', 'label': '①', 'x': .5, 'y': .5, 'position_description': '中心'},
        ],
        'edges': [{'id': 'e1', 'from': 'v1', 'to': 'v2', 'direction': 'undirected'}],
    }


def test_plain_and_markdown_export_include_appearance_and_collision_free_point_map():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node unavailable')
    script = """
const assert=require('node:assert/strict'),fs=require('node:fs');
const model=require('./static/graph-editor-model.js'),format=require('./static/graph-editor-format.js');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const original=JSON.stringify(input);
const normalized=model.ensureAnonymousLabels(input);
const graph=normalized.graphs[0],byId=Object.fromEntries(graph.vertices.map(v=>[v.id,v]));
assert.equal(byId.v1.label,null);assert.equal(byId.v1.display_label,'1');
assert.equal(byId.v2.display_label,'2');assert.equal(byId.v3.label,'①');
assert.deepEqual([...format.graphLabels(input.graphs[0])],[...format.graphLabels(graph)]);
assert.equal(JSON.stringify(input),original);
const reversed=model.ensureAnonymousLabels({...input,graphs:[{...input.graphs[0],vertices:input.graphs[0].vertices.toReversed()}]});
for(const v of reversed.graphs[0].vertices)assert.equal(v.display_label,byId[v.id].display_label);
const existing={graphs:[{id:'G2',anon_next:6,vertices:[{id:'z',label:null},{id:'a',label:null,display_label:'⑤'}],edges:[]}]};
const continued=model.ensureAnonymousLabels(existing).graphs[0];
assert.equal(continued.vertices[0].display_label,'6');assert.equal(continued.vertices[1].display_label,'5');
assert.deepEqual([...format.graphLabels(existing.graphs[0])],[...format.graphLabels(continued)]);
const collisions={graphs:[{id:'G3',vertices:[{id:'zero',label:0},
 {id:'a',label:null,display_label:'0'},{id:'b',label:null,display_label:'②'},
 {id:'c',label:null,display_label:'②'},{id:'d',label:''}],edges:[{id:'e',from:'zero',to:'a',direction:'undirected'}]}]};
const repaired=model.ensureAnonymousLabels(collisions).graphs[0],repairedById=Object.fromEntries(repaired.vertices.map(v=>[v.id,v]));
assert.equal(repairedById.zero.label,0);assert.equal(repairedById.zero.display_label,undefined);
assert.equal(repairedById.b.display_label,'2');assert.equal(repairedById.a.display_label,'3');
assert.equal(repairedById.c.display_label,'4');assert.equal(repairedById.d.display_label,'5');
assert.deepEqual([...format.graphLabels(collisions.graphs[0])],[...format.graphLabels(repaired)]);
const zeroRow=format.graphRows(repaired,0);assert(zeroRow.vertices.includes('0'));
assert(!zeroRow.anonymousNote.includes('0'));assert.equal(zeroRow.relations[0].txt,'0—3');
const imported=model.importDocument(normalized).graphs[0];
assert.equal(imported.visual_description,graph.visual_description);
assert.equal(imported.vertices[0].position_description,'外圈右上方');
for(const text of [format.toPlain([graph]),format.toMarkdown([graph])]){
 assert(text.includes('四个顶点分布在外圈'));assert(text.includes('1：外圈左上方'));
 assert(text.includes('2：外圈右上方'));assert(text.includes('1—2'));
 assert(!text.includes('临时编号'));
}
const hostile={...graph,visual_description:'<img onerror=alert(1)>',vertices:graph.vertices.map(v=>({...v,position_description:'<script>x</script>'}))};
const markdown=format.toMarkdown([hostile]);assert(!markdown.includes('<img'));assert(!markdown.includes('<script>'));
console.log(JSON.stringify(normalized));
"""
    process = subprocess.run([node, '-e', script], cwd=ROOT,
                             input=json.dumps({'body_text': '', 'graphs': [anonymous_graph()]}),
                             capture_output=True, text=True, timeout=15)
    assert process.returncode == 0, process.stderr


def test_readonly_scan_maps_anonymous_points_and_confirms_the_same_references(scan_page):
    p = scan_page
    graph = anonymous_graph()
    p.evaluate("g=>{const task=ocrTasks.get('scan');task.initialDocument={body_text:'判断左右两图是否同构。',graphs:[g]};task.draft=structuredClone(task.initialDocument);}", graph)
    open_scan(p)
    panel = p.locator('.dgs-information')
    assert panel.get_by_text('图形外观：'+graph['visual_description'], exact=True).count() == 1
    assert panel.get_by_text('1：外圈左上方', exact=True).count() == 1
    assert panel.get_by_text('2：外圈右上方', exact=True).count() == 1
    assert panel.get_by_text('1—2', exact=True).count() == 1
    assert '临时编号' not in panel.inner_text()
    assert panel.locator('svg,input,select,textarea,[contenteditable=true]').count() == 0
    p.get_by_role('button', name='保存').click()
    p.wait_for_function('posts.length===1')
    submitted = p.evaluate('posts[0].document.graphs[0]')
    assert submitted['visual_description'] == graph['visual_description']
    assert {v['id']: v.get('display_label') for v in submitted['vertices']} == {
        'v1': '1', 'v2': '2', 'v3': None}
    assert all(v['label'] is None for v in submitted['vertices'] if v['id'] != 'v3')


def test_region_results_persist_numbering_and_descriptions_before_confirmation(scan_page):
    p = scan_page
    p.evaluate('g=>{sample.graphs=[g];}', anonymous_graph())
    open_scan(p)
    p.get_by_role('button', name='图形框选', exact=True).click()
    drag(p, [(.1, .1), (.8, .8)])
    p.wait_for_function('graphCalls.length===1 && ocrTasks.get("scan").scanState.graphRegions[0].status==="complete"')
    p.get_by_role('checkbox', name='放入图形框 1', exact=True).check()
    p.get_by_role('button', name='放入所选图形信息', exact=True).click()
    p.wait_for_function('graphCalls.length===1 && document.querySelector(".dgs-appearance")?.textContent.includes("四个顶点")')
    assert p.locator('.dgs-vertex-position').filter(has_text='1：外圈左上方').count() == 1
    p.get_by_role('button', name='保存').click()
    p.wait_for_function('posts.length===1')
    submitted = p.evaluate('posts[0].document.graphs[0]')
    assert submitted['id'] == 'g1_1'
    assert submitted['visual_description'] == anonymous_graph()['visual_description']
    assert {v['id']: v.get('display_label') for v in submitted['vertices']}['v1'] == '1'
