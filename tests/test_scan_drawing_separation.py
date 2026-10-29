"""Actual production render, handlers and editor, with zero external requests."""
import base64
import io
import os
import re
import shutil
from pathlib import Path

import pytest
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'templates/index.html').read_text()
SCRIPT=(ROOT/'static/script.js').read_text()


@pytest.fixture(params=[(1440,900),(390,844)])
def scan_page(request):
    chromium=os.environ.get('DMATE_BROWSER_EXECUTABLE') or shutil.which('chromium')
    if not chromium:pytest.skip('Chromium unavailable')
    pw=pytest.importorskip('playwright.sync_api')
    fragment='<div id="ocrUploadStage"'+HTML.split('<div id="ocrUploadStage"',1)[1].split('\n<div class="right">',1)[0]
    dialog='<dialog id="graphEditorDialog"'+HTML.split('<dialog id="graphEditorDialog"',1)[1].split('</dialog>',1)[0]+'</dialog>'
    menu=re.search(r'<button id="graphDrawingBtn"[^>]*>.*?</button>',HTML).group()
    styles='\n'.join(re.findall(r'<style[^>]*>([\s\S]*?)</style>',HTML))
    code=SCRIPT[SCRIPT.index('const OCR_MAX_CONCURRENT'):SCRIPT.index('\nfunction isClearlyNonQuestionWrongBookText')]
    with Image.new('RGB',(600,400),'white') as im:
        buf=io.BytesIO();im.save(buf,format='PNG')
    image='data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()
    sample={'body_text':'求下图从 A 到 B 的最短路径。','graphs':[{
        'id':'G1','name':'图一','directed':True,'weighted':True,
        'vertices':[{'id':'a','label':'A','x':.2,'y':.3},{'id':'b','label':'B','x':.8,'y':.6}],
        'edges':[{'id':'ab','from':'a','to':'b','direction':'forward','weight':0},
                 {'id':'ab2','from':'b','to':'a','direction':'forward','weight':3},
                 {'id':'loop','from':'a','to':'a','direction':'unknown','weight':2}]}]}
    with pw.sync_playwright() as engine:
        browser=engine.chromium.launch(executable_path=chromium,headless=True)
        page=browser.new_page(viewport={'width':request.param[0],'height':request.param[1]})
        page.route('**/*',lambda route:route.fulfill(body='<html><body></body></html>',content_type='text/html'))
        page.goto('https://dmate.test/')
        page.set_content('<div class="center" style="height:90dvh">'+fragment+'<aside class="right">'+menu+'</aside>'+dialog)
        page.add_style_tag(content=styles)
        page.add_style_tag(content=(ROOT/'static/graph-editor.css').read_text())
        for name in ['graph-editor-model.js','graph-editor-format.js','graph-editor-overlay.js','graph-editor.js']:
            page.add_script_tag(content=(ROOT/'static'/name).read_text())
        page.add_script_tag(content='''window.ocrRequestInFlight=false;window.ocrReviewInProgress=false;
          window.refreshInputAvailability=()=>{};window.queueChatJumpControlsUpdate=()=>{};
          window.closeMobileShellDrawers=()=>document.body.classList.remove('mobile-tools-open');window.showCurrentError=e=>{window.lastError=e};
          window.posts=[];window.parseResponseJson=r=>r.json();window.fetch=async(url,options)=>{
            if(url==='/graph/confirm'){const payload=JSON.parse(options.body);posts.push(payload);
              return {ok:true,json:async()=>({document:payload.document,drawing_document:payload.document,
                confirmation_token:'fixture',revision:1,semantic_context:{}})}};
            return {ok:true,json:async()=>({})};};
        '''+code)
        page.evaluate('''a=>{window.sample=a.sample;ocrTasks.set('scan',{id:'scan',file:{name:'测试图片.png'},
          state:'ready',draft:structuredClone(a.sample),initialDocument:structuredClone(a.sample),
          originalUrl:a.image,userRequest:'',sourceSha256:'a'.repeat(64),
          confirmation:null,dirty:false,confirming:false,sending:false,notice:'',
          startedAt:0,finishedAt:1});initializeOcrTaskPanel();renderOcrTasks();}''',{'sample':sample,'image':image})
        yield page
        browser.close()


def test_scan_shows_source_text_rendered_graph_and_optional_request(scan_page):
    p=scan_page;card=p.locator('.ocr-task-card')
    assert p.locator('.ocr-task-text').input_value()=='求下图从 A 到 B 的最短路径。'
    assert p.locator('.ocr-task-graph-preview svg').count()==1
    assert p.locator('.dge-visual-edge').count()==3
    assert p.locator('.dge-visual-node').count()==2
    assert p.locator('.dge-visual-edge[role=button]').count()==0
    assert p.locator('[marker-end]').count()==2
    assert p.locator('.dge-edge-stroke[stroke-dasharray="4 5"]').count()==1
    assert '0' in p.locator('.ocr-task-graph-preview').inner_text()
    assert card.get_by_role('button',name='添加顶点').count()==0
    assert p.locator('.ocr-task-request').is_visible()
    left=p.locator('.ocr-task-thumbnail').bounding_box();right=p.locator('.ocr-task-text').bounding_box()
    if p.viewport_size['width']>760:assert left['x']+left['width']<right['x']
    else:assert left['y']+left['height']<=right['y']
    assert card.evaluate('e=>e.scrollWidth<=e.clientWidth+2')


def test_editing_text_invalidates_confirmation_and_reconfirmation_uses_latest_text(scan_page):
    p=scan_page;p.get_by_role('button',name='确认识别结果').click()
    p.wait_for_function('ocrTasks.get("scan").confirmation!==null')
    p.locator('.ocr-task-text').fill('用户修正后的题干，求最短路径。')
    assert p.evaluate('ocrTasks.get("scan").confirmation') is None
    assert p.get_by_role('button',name='解题',exact=True).count()==0
    p.locator('.ocr-task-request').fill('只解第一问')
    p.get_by_role('button',name='确认识别结果').click()
    p.wait_for_function('posts.length===2')
    assert p.evaluate('posts[1].document.body_text')=='用户修正后的题干，求最短路径。'
    assert p.evaluate('ocrTasks.get("scan").userRequest')=='只解第一问'
    assert p.evaluate('posts[1].document.graphs[0].edges.length')==3


def test_structure_edit_has_forms_without_drawing_controls(scan_page):
    p=scan_page;p.get_by_role('button',name='修改结构').click()
    assert p.locator('#graphEditorDialog').is_visible()
    assert p.locator('.dge-overlay-svg').count()==0
    assert p.get_by_role('button',name='添加顶点',exact=True).count()==0
    p.get_by_label('边 1 权重',exact=True).fill('9')
    assert p.evaluate('ocrTasks.get("scan").draft.graphs[0].edges[0].weight')==9
    p.get_by_role('button',name='关闭图形识别编辑器').click()
    p.wait_for_function('document.querySelector(".ocr-task-graph-preview").textContent.includes("9")')


def test_standalone_drawing_saves_reopens_and_never_changes_scan(scan_page):
    p=scan_page;p.evaluate('document.body.classList.add("mobile-tools-open")')
    p.get_by_role('button',name='绘图',exact=True).click()
    p.wait_for_function('document.querySelector(".dge-overlay-image").naturalWidth===1000')
    assert p.locator('#graphEditorTitle').inner_text()=='绘图'
    assert p.get_by_role('tab',name='文字识别').count()==0
    p.get_by_role('button',name='添加顶点',exact=True).click()
    svg=p.locator('.dge-overlay-svg').bounding_box()
    p.mouse.click(svg['x']+svg['width']*.4,svg['y']+svg['height']*.4)
    assert p.locator('.dge-overlay-node').count()==1
    p.get_by_role('button',name='保存绘图',exact=True).click()
    p.wait_for_function('!document.getElementById("graphEditorDialog").open')
    assert p.evaluate('JSON.parse(localStorage.getItem(DRAWING_STORAGE_KEY)).graphs[0].vertices.length')==1
    assert p.evaluate('ocrTasks.get("scan").draft.graphs[0].vertices.length')==2
    assert p.evaluate('posts.length')==0
    p.evaluate('document.body.classList.add("mobile-tools-open")')
    p.get_by_role('button',name='绘图',exact=True).click()
    p.wait_for_selector('.dge-overlay-node')
    assert p.locator('.dge-overlay-node').count()==1


def test_empty_scan_can_be_supplemented_as_structure_without_drawing(scan_page):
    p=scan_page
    p.evaluate('ocrTasks.get("scan").draft={body_text:"人工补充题干",graphs:[]};renderOcrTasks()')
    p.get_by_role('button',name='修改结构').click()
    p.get_by_role('button',name='添加图形结构').click()
    p.get_by_label('新节点标签',exact=True).fill('X')
    p.get_by_role('button',name='添加节点',exact=True).click()
    assert p.evaluate('ocrTasks.get("scan").draft.graphs[0].vertices[0].label')=='X'
    assert p.locator('.dge-overlay-svg').count()==0
