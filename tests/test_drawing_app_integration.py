"""Drawing shell is wired to the real app dialog and exact-structure upload stage."""
import os
import re
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=[(1440, 900), (390, 844)])
def drawing_app(request):
    executable = os.environ.get('DMATE_BROWSER_EXECUTABLE') or shutil.which('chromium')
    if not executable:
        pytest.skip('Chromium unavailable')
    pw = pytest.importorskip('playwright.sync_api')
    html = (ROOT / 'templates/index.html').read_text()
    script = (ROOT / 'static/script.js').read_text()
    stage = '<div id="ocrUploadStage"' + html.split('<div id="ocrUploadStage"', 1)[1].split('\n<div class="right">', 1)[0]
    dialog = '<dialog id="graphEditorDialog"' + html.split('<dialog id="graphEditorDialog"', 1)[1].split('</dialog>', 1)[0] + '</dialog>'
    menu = re.search(r'<button id="graphDrawingBtn"[^>]*>.*?</button>', html).group()
    styles = '\n'.join(re.findall(r'<style[^>]*>([\s\S]*?)</style>', html))
    code = script[script.index('const OCR_MAX_CONCURRENT'):script.index('\nfunction isClearlyNonQuestionWrongBookText')]
    with pw.sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=executable, headless=True)
        page = browser.new_page(viewport={'width': request.param[0], 'height': request.param[1]})
        page.route('**/*', lambda route: route.fulfill(body='<html><body></body></html>', content_type='text/html'))
        page.goto('https://dmate.test/')
        page.set_content('<body data-appearance-theme="light"><div class="center" style="height:90dvh">' + stage + '<aside class="right">' + menu + '</aside>' + dialog + '</body>')
        page.add_style_tag(content=styles)
        for name in ['voice-input.css', 'graph-editor.css', 'drawing-workspace.css']:
            page.add_style_tag(content=(ROOT / 'static' / name).read_text())
        for name in ['graph-editor-model.js', 'graph-editor-format.js', 'graph-editor-overlay.js',
                     'graph-editor.js', 'drawing-export.js', 'drawing-workspace.js', 'graph-scan-workspace.js']:
            page.add_script_tag(content=(ROOT / 'static' / name).read_text())
        page.add_script_tag(content='''
          window.accountState={authenticated:true,username:'alice'};
          window.currentId='chat1';window.sessions=[{id:'chat1',messages:[]}];
          window.getCurrent=()=>sessions.find(s=>s.id===currentId);
          window.newChat=()=>{currentId='created';sessions.push({id:currentId,messages:[]});};
          window.ocrRequestInFlight=false;window.ocrReviewInProgress=false;
          window.MAX_IMAGE_BYTES=20000000;
          window.refreshInputAvailability=()=>{};window.queueChatJumpControlsUpdate=()=>{};
          window.isCurrentSessionTyping=()=>false;window.isSessionBusy=()=>false;
          window.isSessionPendingAiStart=()=>false;
          window.closeMobileShellDrawers=()=>document.body.classList.remove('mobile-tools-open');window.showCurrentError=e=>{window.lastError=e;};
          window.makeOcrRequestId=()=>crypto.randomUUID();window.notifyOcrCancelled=()=>{};
          window.parseResponseJson=r=>r.json();window.requests=[];window.uploads=[];
          window.fetch=async(url,options={})=>{
            requests.push(url);
            if(url==='/graph/session')return {ok:true,json:async()=>({})};
            if(url==='/drawing/guide')return {ok:true,json:async()=>({ok:true,answer:('先保留 A、B 顶点，再从 A 向 B 画边。\\n').repeat(100)})};
            if(url==='/drawing/upload'){
              const document=JSON.parse(options.body.get('document'));
              const request_id=options.body.get('request_id'),file=options.body.get('image');
              uploads.push({document,request_id,type:file.type,size:file.size,name:file.name});
              const result={ok:true,json:async()=>({ok:true,request_id,source_sha256:'a'.repeat(64),document})};
              if(window.deferUpload)return new Promise(resolve=>window.resolveUpload=()=>resolve(result));
              return result;
            }
            throw new Error('Unexpected request: '+url);
          };
        ''' + code)
        page.evaluate('''()=>{
          window.sample={body_text:'',graphs:[{id:'G1',name:'原来的图',directed:true,weighted:true,
            vertices:[{id:'a',label:'A',x:.25,y:.35},{id:'b',label:'B',x:.75,y:.65}],
            edges:[{id:'ab',from:'a',to:'b',direction:'forward',weight:12,edge_label:null}]}]};
          localStorage.setItem(DRAWING_STORAGE_KEY,JSON.stringify(sample));
          initializeOcrTaskPanel();renderOcrTasks();
        }''')
        yield page
        browser.close()


def open_drawing(page):
    # The real phone menu slides in after the user opens the learning drawer.
    page.evaluate("document.body.classList.add('mobile-tools-open')")
    page.get_by_role('button', name='画图', exact=True).click()
    page.wait_for_function('document.querySelector(".dge-overlay-image")?.naturalWidth===1000')
    assert page.locator('.dmate-drawing-workspace').count() == 1


def test_red_close_stays_in_header_while_answer_scrolls(drawing_app):
    page = drawing_app
    open_drawing(page)
    before = page.locator('#graphEditorClose').bounding_box()
    dialog = page.locator('#graphEditorDialog').bounding_box()
    assert abs(before['x'] + before['width'] - (dialog['x'] + dialog['width'] - (13 if page.viewport_size['width'] <= 760 else 19))) <= 3
    assert before['y'] < dialog['y'] + 30
    page.get_by_role('button', name='AI 回答', exact=True).click()
    page.get_by_role('button', name='请求 AI 指导', exact=True).click()
    page.wait_for_function('document.querySelector(".ddw-ai-answer").textContent.includes("A、B")')
    page.locator('.ddw-side-panel').evaluate('e=>e.scrollTop=e.scrollHeight')
    assert page.locator('.ddw-side-panel').evaluate('e=>e.scrollTop') > 0
    after = page.locator('#graphEditorClose').bounding_box()
    assert abs(after['y'] - before['y']) < 1
    assert page.locator('#graphEditorDialog').evaluate('e=>e.scrollTop') == 0
    assert page.locator('#graphEditorDialog').evaluate('e=>getComputedStyle(e).overflowY') == 'hidden'
    page.get_by_role('button', name='关闭绘图', exact=True).click()
    page.wait_for_function('!document.getElementById("graphEditorDialog").open && ocrEditorTaskId===null')
    assert page.locator('.dmate-drawing-workspace').count() == 0


def test_uploaded_drawing_keeps_exact_structure_and_waits_for_user_send(drawing_app):
    page = drawing_app
    open_drawing(page)
    page.locator('.ddw-name').fill('已绘制的有向图')
    page.get_by_role('button', name='AI 回答', exact=True).click()
    page.get_by_label('绘图指导要求（可选）').fill('检查这条权值为 12 的边')
    page.evaluate('window.deferUpload=true')
    page.get_by_role('button', name='上传到对话', exact=True).click()
    page.wait_for_function('uploads.length===1')
    assert page.locator('#graphEditorDialog').evaluate('e=>e.open')
    assert page.evaluate('ocrTasks.size') == 0
    assert page.evaluate('sessions[0].messages.length') == 0
    sent = page.evaluate('uploads[0]')
    graph = sent['document']['graphs'][0]
    assert sent['type'] == 'image/png' and sent['size'] > 100
    assert sent['name'] == '已绘制的有向图.png'
    assert [v['id'] for v in graph['vertices']] == ['a', 'b']
    assert [(e['from'], e['to'], e['direction'], e['weight'], e.get('edge_label')) for e in graph['edges']] == [('a', 'b', 'forward', 12, None)]
    page.evaluate('resolveUpload()')
    page.wait_for_function('ocrTasks.size===1 && ocrEditorTaskId===null')
    task = page.evaluate('structuredClone([...ocrTasks.values()][0])')
    assert task['state'] == 'ready' and task['confirmation'] is None
    assert task['draft'] == sent['document'] == task['initialDocument']
    assert task['sourceSha256'] == 'a' * 64
    assert task['userRequest'] == '检查这条权值为 12 的边'
    assert page.evaluate('requests') == ['/graph/session', '/drawing/upload']
    assert page.evaluate('sessions[0].messages.length') == 0
    assert page.locator('#ocrUploadStage').is_visible()
    assert page.get_by_role('button', name='上传图片', exact=True).is_visible()
    assert page.get_by_role('button', name='发送', exact=True).is_visible()
    assert page.locator('#sendBtn').evaluate('e=>e.parentElement.id') == 'ocrUploadActions'


def test_saved_drawing_gallery_reopens_and_is_scoped_to_account(drawing_app):
    page = drawing_app
    open_drawing(page)
    page.locator('.ddw-name').fill('Alice 的图')
    page.get_by_role('button', name='新建空白页', exact=True).click()
    page.get_by_role('button', name='历史绘图', exact=True).click()
    page.get_by_role('button', name='Alice 的图', exact=True).click()
    assert page.evaluate('ocrEditorController.getDocument().graphs[0].vertices.length') == 2
    page.get_by_role('button', name='关闭绘图', exact=True).click()
    page.wait_for_function('ocrEditorTaskId===null')
    open_drawing(page)
    assert page.locator('.ddw-name').input_value() == 'Alice 的图'
    page.get_by_role('button', name='历史绘图', exact=True).click()
    assert page.locator('.ddw-history-item').count() == 2
    page.get_by_role('button', name='关闭绘图', exact=True).click()
    page.wait_for_function('ocrEditorTaskId===null')
    page.evaluate("accountState.username='bob'")
    open_drawing(page)
    assert page.evaluate('ocrEditorController.getDocument().graphs[0].vertices.length') == 0
    page.get_by_role('button', name='历史绘图', exact=True).click()
    assert page.locator('.ddw-history-item').count() == 1
    assert page.get_by_role('button', name='Alice 的图', exact=True).count() == 0


def test_closing_drawing_during_upload_does_not_enqueue_a_late_result(drawing_app):
    page = drawing_app
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    open_drawing(page)
    page.evaluate('window.deferUpload=true')
    page.get_by_role('button', name='上传到对话', exact=True).click()
    page.wait_for_function('uploads.length===1')
    page.get_by_role('button', name='关闭绘图', exact=True).click()
    page.wait_for_function('ocrEditorTaskId===null')
    page.evaluate('resolveUpload()')
    page.wait_for_timeout(100)
    assert page.evaluate('ocrTasks.size') == 0
    assert page.evaluate('sessions[0].messages.length') == 0
    assert page.locator('#graphEditorDialog').evaluate('e=>!e.open')
    assert not errors


def test_confirmed_graph_information_is_complete_without_collapsed_state(drawing_app):
    page = drawing_app
    page.evaluate('''()=>{
      const document=structuredClone(sample);
      document.graphs[0].edges=Array.from({length:35},(_,i)=>({id:'e'+i,from:'a',to:'b',direction:'forward',weight:i,edge_label:null}));
      ocrTasks.set('confirmed',{id:'confirmed',file:{name:'图.png'},sessionId:'chat1',
        originalUrl:'data:image/png;base64,iVBORw0KGgo=',state:'ready',startedAt:0,finishedAt:1,
        draft:document,initialDocument:document,confirmation:{document},userRequest:'',error:''});
      renderOcrTasks();
    }''')
    panel = page.locator('.ocr-task-structure')
    assert panel.evaluate('e=>e.tagName') == 'SECTION'
    assert panel.locator('summary').count() == 0
    assert panel.locator('.ocr-task-relations p').count() == 35
    assert panel.locator('.ocr-task-relations').evaluate('e=>e.scrollHeight<=e.clientHeight+1')
    assert '34' in panel.locator('.ocr-task-relations p').last.inner_text()
