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
        page.add_style_tag(content=(ROOT/'static/voice-input.css').read_text())
        page.add_style_tag(content=(ROOT/'static/graph-editor.css').read_text())
        for name in ['graph-editor-model.js','graph-editor-format.js','graph-editor-overlay.js','graph-editor.js','graph-scan-workspace.js']:
            page.add_script_tag(content=(ROOT/'static'/name).read_text())
        page.add_script_tag(content='''window.ocrRequestInFlight=false;window.ocrReviewInProgress=false;
          window.refreshInputAvailability=()=>{};window.queueChatJumpControlsUpdate=()=>{};
          window.closeMobileShellDrawers=()=>document.body.classList.remove('mobile-tools-open');window.showCurrentError=e=>{window.lastError=e};
          window.makeOcrRequestId=()=>crypto.randomUUID();window.notifyOcrCancelled=()=>{};window.graphCalls=[];window.textCalls=[];window.posts=[];window.parseResponseJson=r=>r.json();window.fetch=async(url,options)=>{
            if(url==='/graph/confirm'){const payload=JSON.parse(options.body);posts.push(payload);
              return {ok:true,json:async()=>({document:payload.document,drawing_document:payload.document,
                confirmation_token:'fixture',revision:1,semantic_context:{}})}};
            if(url==='/graph/recognize-region'){
              const polygon=JSON.parse(options.body.get('polygon'));graphCalls.push(polygon);
              if(window.deferGraph)return new Promise(resolve=>window.resolveGraph=()=>resolve({ok:true,json:async()=>({request_id:'scan',operation_id:options.body.get('operation_id'),source_sha256:'a'.repeat(64),document:{graphs:sample.graphs},recognition_status:'complete'})}));
              return {ok:true,json:async()=>({request_id:'scan',operation_id:options.body.get('operation_id'),source_sha256:'a'.repeat(64),document:{graphs:sample.graphs},recognition_status:'complete'})};
            }
            if(url==='/graph/text-region'){
              const regions=JSON.parse(options.body.get('regions'));textCalls.push(regions);
              return {ok:true,json:async()=>({request_id:'scan',source_sha256:'a'.repeat(64),regions:regions.map(r=>({id:r.id,text:'文字区域 '+r.id}))})};
            }
            return {ok:true,json:async()=>({})};};
        '''+code)
        page.evaluate('''a=>{window.sample=a.sample;ocrTasks.set('scan',{id:'scan',file:{name:'测试图片.png'},
          state:'ready',draft:structuredClone(a.sample),initialDocument:structuredClone(a.sample),
          originalUrl:a.image,userRequest:'',sourceSha256:'a'.repeat(64),
          confirmation:null,dirty:false,confirming:false,sending:false,notice:'',
          startedAt:0,finishedAt:1});initializeOcrTaskPanel();renderOcrTasks();}''',{'sample':sample,'image':image})
        yield page
        browser.close()


def open_scan(p):
    p.get_by_role('button',name='编辑核对',exact=True).click()
    p.wait_for_function('document.querySelector(".dgs-source .dge-overlay-image").naturalWidth===600')


def drag(p, points):
    b=p.locator('.dgs-source .dge-overlay-image').bounding_box()
    p.mouse.move(b['x']+b['width']*points[0][0],b['y']+b['height']*points[0][1]);p.mouse.down()
    for x,y in points[1:]:p.mouse.move(b['x']+b['width']*x,b['y']+b['height']*y,steps=5)
    p.mouse.up()


def test_outer_upload_is_restored_and_only_editor_has_readonly_information(scan_page):
    p=scan_page
    assert p.locator('.ocr-task-text,.ocr-task-graph-preview').count()==0
    assert p.locator('.ocr-task-thumbnail').bounding_box()['width']==64
    open_scan(p)
    assert p.locator('.dgs-body').inner_text()=='求下图从 A 到 B 的最短路径。'
    assert p.locator('.dgs-information svg,.dgs-information input,.dgs-information textarea,.dgs-information select,[contenteditable=true]').count()==0
    assert p.locator('.dgs-information').get_by_text('图形信息',exact=True).count()==1
    assert p.locator('.dgs-information').get_by_text('顶点：A、B').count()==1
    assert p.get_by_label('要求（可选）',exact=True).is_visible()
    assert p.get_by_role('button',name='添加顶点',exact=True).count()==0
    assert p.get_by_role('button',name='隐藏描绘',exact=True).count()==0
    assert p.get_by_label('原图透明度',exact=True).count()==0
    assert p.get_by_role('button',name='适应',exact=True).is_visible()
    left=p.locator('.dgs-source').bounding_box();right=p.locator('.dgs-information').bounding_box()
    if p.viewport_size['width']>760:assert left['x']+left['width']<right['x']
    else:assert left['y']+left['height']<=right['y']


def test_rectangles_and_freehand_of_both_types_recognize_without_moving_view(scan_page):
    p=scan_page;open_scan(p)
    before=p.locator('.dge-overlay-image').bounding_box()
    p.get_by_role('button',name='图形框选',exact=True).click()
    drag(p,[(.12,.12),(.35,.35)])
    p.wait_for_function('graphCalls.length===1')
    p.get_by_label('选区方式').select_option('irregular')
    # Start on an existing border: drawing mode must not steal this as resize.
    drag(p,[(.12,.12),(.45,.12),(.48,.4),(.18,.45),(.12,.12)])
    p.wait_for_function('graphCalls.length===2')
    assert p.locator('.dge-overlay-polygon').count()==1
    p.get_by_role('button',name='文字框选',exact=True).click()
    drag(p,[(.55,.15),(.85,.18),(.8,.4),(.55,.4),(.55,.15)])
    p.wait_for_function('textCalls.length===1')
    p.get_by_label('选区方式').select_option('')
    drag(p,[(.58,.5),(.9,.8)])
    p.wait_for_function('textCalls.length===2')
    p.wait_for_function('ocrTasks.get("scan").scanState.textRegions.every(r=>r.status==="complete")')
    after=p.locator('.dge-overlay-image').bounding_box()
    assert all(abs(before[k]-after[k])<2 for k in ['x','y','width','height'])
    # Explicit source selection below the mobile canvas scrolls to those
    # controls normally; measure framing stability before that user action.
    p.get_by_role('checkbox',name='文字框1',exact=True).check()
    p.get_by_role('checkbox',name='文字框2',exact=True).check()
    p.keyboard.press('Escape')
    assert p.locator('.dge-overlay-text-region').count()==2
    assert p.locator('.dgs-body').inner_text()=='文字区域 1\n\n文字区域 2'
    assert p.locator('.dge-overlay-node,.dge-overlay-edge').count()==0
    assert p.locator('.dge-overlay-bbox').first.evaluate('e=>getComputedStyle(e).strokeWidth')=='1px'


def test_pending_scans_block_confirmation_and_deleted_frames_ignore_late_results(scan_page):
    p=scan_page;open_scan(p);p.evaluate('window.deferGraph=true')
    p.get_by_role('button',name='图形框选',exact=True).click()
    drag(p,[(.2,.2),(.6,.6)])
    p.wait_for_function('graphCalls.length===1')
    assert p.get_by_role('button',name='保存').is_disabled()
    p.get_by_role('button',name='删除图形框1',exact=True).click()
    p.evaluate('resolveGraph()')
    p.wait_for_timeout(100)
    assert p.evaluate('ocrTasks.get("scan").draft.graphs.length')==0
    assert p.locator('.dge-overlay-bbox').count()==0


def test_requirements_confirm_with_current_readonly_structure(scan_page):
    p=scan_page;open_scan(p)
    p.get_by_label('要求（可选）',exact=True).fill('只解第二问')
    p.get_by_role('button',name='保存').click()
    p.wait_for_function('posts.length===1')
    assert p.evaluate('posts[0].document.body_text')=='求下图从 A 到 B 的最短路径。'
    assert p.evaluate('posts[0].document.graphs[0].edges.length')==3
    assert p.evaluate('ocrTasks.get("scan").userRequest')=='只解第二问'


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
