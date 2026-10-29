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
    p.get_by_role('checkbox', name='图形框1', exact=True).check()
    p.keyboard.press('Escape')
    p.wait_for_function('graphCalls.length===1 && document.querySelector(".dgs-appearance")?.textContent.includes("四个顶点")')
    assert p.locator('.dgs-vertex-position').filter(has_text='1：外圈左上方').count() == 1
    p.get_by_role('button', name='保存').click()
    p.wait_for_function('posts.length===1')
    submitted = p.evaluate('posts[0].document.graphs[0]')
    assert submitted['id'] == 'g1_1'
    assert submitted['visual_description'] == anonymous_graph()['visual_description']
    assert {v['id']: v.get('display_label') for v in submitted['vertices']}['v1'] == '1'


def equivalent_documents():
    first = anonymous_graph()
    first['name'] = '无向无权图'
    first['visual_description'] = '外圈与中心顶点，以线段相连。'
    second = {
        'id': 'G2', 'name': '带权有向图', 'directed': True, 'weighted': True,
        'vertices': [{'id': 'x', 'label': 'X', 'x': .2, 'y': .2, 'position_description': '左上'},
                     {'id': 'y', 'label': None, 'display_label': '⑤', 'x': .8, 'y': .8}],
        'edges': [
            {'id': 'zero', 'from': 'x', 'to': 'y', 'direction': 'forward', 'weight': 0, 'edge_label': '0'},
            {'id': 'fraction', 'from': 'y', 'to': 'x', 'direction': 'forward', 'weight': '1/2', 'edge_label': '路线甲'},
            {'id': 'missing', 'from': 'x', 'to': 'x', 'direction': 'unknown', 'weight': None,
             'edge_label': '7', 'edge_label_is_explicit': True},
        ],
    }
    hostile = anonymous_graph()
    hostile['name'] = '<b>图名</b>'
    hostile['visual_description'] = '<img src=x onerror=alert(1)> 原样文字'
    hostile['vertices'][0]['position_description'] = '<script>未执行</script>'
    hostile['vertices'][1]['label'] = '<svg/onload=alert(1)>'
    return [
        {'body_text': '', 'graphs': [first, second]},
        {'body_text': '', 'graphs': [{'id': 'G1', 'name': '空白页', 'directed': False,
                                    'weighted': False, 'vertices': [], 'edges': []}]},
        {'body_text': '', 'graphs': []},
        {'body_text': '', 'graphs': [hostile]},
    ]


@pytest.mark.parametrize('document', equivalent_documents(), ids=['types_names_weights_anonymous', 'empty_graph', 'empty_document', 'literal_text'])
def test_drawing_and_scan_use_identical_readonly_graph_information_dom_and_styles(scan_page, document):
    page = scan_page
    page.evaluate('''documentValue=>{
      document.documentElement.style.setProperty('--font-scale','1.2');
      // Both views receive exactly the same canonical model data; this test
      // compares display paths rather than their independent import rules.
      const labeled=DMateGraphEditorModel.ensureAnonymousLabels(DMateGraphEditorModel.importDocument(documentValue));
      const normalized=DMateGraphEditorModel.createModel(labeled,undefined,{drawingOnly:true}).getDocument();
      const task=ocrTasks.get('scan');task.initialDocument=normalized;task.draft=structuredClone(normalized);
      window.originalGraphData=JSON.stringify(normalized);window.renderPaths=[];
      const original=DMateGraphFormat.renderGraphInformation;
      DMateGraphFormat.renderGraphInformation=function(host,value,options){
        renderPaths.push(host.className);return original(host,value,options);
      };
    }''', document)
    open_scan(page)
    result = page.evaluate('''()=>{
      const task=ocrTasks.get('scan'),source=document.querySelector('.dgs-graphs .dmate-graph-information');
      const host=document.createElement('div');document.getElementById('graphEditorDialog').append(host);
      window.comparisonDrawing=DMateGraphEditor.mount(host,{drawingOnly:true,
        originalUrl:document.querySelector('.dgs-source .dge-overlay-image').src,
        document:structuredClone(task.scanState.nativeDocument)});
      host.querySelector('.dge-float-results').open=true;
      const drawing=host.querySelector('.dge-review-content.dmate-graph-information');
      const styleRows=container=>[...container.querySelectorAll('h4,h5,p')].map(node=>{
        const style=getComputedStyle(node);return {tag:node.tagName,text:node.textContent,
          font:style.fontFamily,size:style.fontSize,weight:style.fontWeight,lineHeight:style.lineHeight,
          top:style.marginTop,bottom:style.marginBottom,left:style.paddingLeft,color:style.color};
      });
      const readonly=container=>container.querySelectorAll('button,input,select,textarea,svg,[contenteditable=true]').length;
      return {source:source.innerHTML,drawing:drawing.innerHTML,sourceText:source.textContent,drawingText:drawing.textContent,
        sourceStyles:styleRows(source),drawingStyles:styleRows(drawing),sourceReadonly:readonly(source),drawingReadonly:readonly(drawing),
        sourceData:JSON.stringify(task.scanState.nativeDocument),drawingData:JSON.stringify(comparisonDrawing.getDocument()),
        baseFont:getComputedStyle(document.body).fontSize,sourceFont:getComputedStyle(source).fontSize,drawingFont:getComputedStyle(drawing).fontSize,
        renderPaths,footer:host.querySelectorAll('.dge-footer').length,
        badHtml:source.querySelectorAll('script,img,svg,b').length+drawing.querySelectorAll('script,img,svg,b').length};
    }''')
    assert result['source'] == result['drawing']
    assert result['sourceText'] == result['drawingText']
    assert result['sourceStyles'] == result['drawingStyles']
    assert result['sourceFont'] == result['drawingFont'] == result['baseFont']
    assert result['sourceReadonly'] == result['drawingReadonly'] == 0
    assert result['badHtml'] == result['footer'] == 0
    assert result['sourceData'] == page.evaluate('originalGraphData')
    assert json.loads(result['sourceData']) == json.loads(result['drawingData'])
    assert any('dgs-graph-information' in name for name in result['renderPaths'])
    assert any('dge-review-content' in name for name in result['renderPaths'])
    if not document['graphs']:
        assert result['sourceText'] == '暂无图形信息。'
    elif len(document['graphs']) == 2:
        assert '0 个顶点' not in result['sourceText']
        assert '图形外观：由 2 个顶点、3 条边组成。' in result['sourceText']
        assert '路线甲：5→X（权值：1/2）' in result['sourceText']
        assert '0：X' not in result['sourceText']  # A numeric edge name equal to its weight is redundant.
        assert '7：X？X' in result['sourceText']
