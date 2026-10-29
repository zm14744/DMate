"""Standalone drawing pages use production UI, persisted docs and real PNG export."""
import json
import os
import re
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=[(1440, 900), (390, 844)])
def drawing_page(request):
    executable = os.environ.get('DMATE_BROWSER_EXECUTABLE') or shutil.which('chromium')
    if not executable:
        pytest.skip('Chromium unavailable')
    pw = pytest.importorskip('playwright.sync_api')
    with pw.sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=executable, headless=True)
        page = browser.new_page(viewport={'width': request.param[0], 'height': request.param[1]}, accept_downloads=True)
        page.route('**/*', lambda route: route.fulfill(body='<html><body></body></html>', content_type='text/html'))
        page.goto('https://dmate.test/')
        page.set_content('<style>html,body{margin:0;height:100%;font-family:sans-serif}#mount{height:95dvh;padding:8px;box-sizing:border-box}</style><div id="mount"></div>')
        for name in ['graph-editor.css', 'drawing-workspace.css', 'modal-chrome.css']:
            page.add_style_tag(content=(ROOT / 'static' / name).read_text())
        for name in ['graph-editor-model.js', 'graph-editor-format.js', 'graph-editor-overlay.js', 'graph-editor.js', 'drawing-export.js', 'delete-confirm.js', 'drawing-workspace.js']:
            page.add_script_tag(content=(ROOT / 'static' / name).read_text())
        page.evaluate('''()=>{
          window.sample={body_text:'',graphs:[{id:'G1',name:'原来的图',directed:true,weighted:true,
            vertices:[{id:'a',label:'A',x:.2,y:.3},{id:'b',label:'B',x:1.2,y:.7}],
            edges:[{id:'ab',from:'a',to:'b',direction:'forward',weight:12,path:[[.2,.3],[.7,.2],[1.2,.7]]}]}]};
          window.uploads=[];window.closeCount=0;window.aiRequests=[];
          window.fetch=async(url,options)=>{aiRequests.push(JSON.parse(options.body));
            if(window.deferAi)return new Promise(resolve=>{window.resolveAi=()=>resolve({ok:true,json:async()=>({ok:true,answer:'旧图回答'})});options.signal.addEventListener('abort',()=>window.aiAborted=true);});
            return {ok:true,json:async()=>({ok:true,answer:'先画 A、B，再从 A 向 B 连一条权值为 12 的有向边。'})};};
          window.drawingMount=document.getElementById('mount');
          window.openDrawing=(storageKey='drawings:user1',legacy=sample,extra={})=>{
            window.workspace=DMateDrawingWorkspace.mount(drawingMount,{
              storageKey,legacyDocument:legacy,
              onUpload:async(blob,metadata)=>{if(window.uploadFailure)throw new Error(window.uploadFailure);uploads.push({type:blob.type,size:blob.size,metadata});},
              onClose:()=>closeCount++,...extra});};openDrawing();
        }''')
        page.wait_for_function('document.querySelector(".dge-overlay").dataset.geometryReady==="true"')
        yield page
        browser.close()


def use_real_dialog_and_template_styles(page, theme):
    html = (ROOT / 'templates/index.html').read_text()
    page.evaluate('document.querySelectorAll("style,link[rel=stylesheet]").forEach(node=>node.remove())')
    for match in re.finditer(r'<style\b[^>]*>([\s\S]*?)</style>|<link\b[^>]*rel="stylesheet"[^>]*>', html):
        if match.group(1) is not None:
            page.add_style_tag(content=match.group(1))
        else:
            source = re.search(r'/static/([^?"\s]+)', match.group(0))
            assert source, match.group(0)
            page.add_style_tag(content=(ROOT / 'static' / source.group(1)).read_text())
    dialog = '<dialog id="graphEditorDialog"' + html.split('<dialog id="graphEditorDialog"', 1)[1].split('</dialog>', 1)[0] + '</dialog>'
    page.evaluate('''({markup,theme})=>{workspace.destroy();document.body.innerHTML=markup;
      document.body.dataset.appearanceTheme=theme;document.documentElement.dataset.appearanceTheme=theme;
      document.body.style.setProperty('--panel-alpha','.55');drawingMount=document.getElementById('graphEditorMount');
      document.getElementById('graphEditorTitle').textContent='绘图';openDrawing('drawings:real-template',sample);
      document.getElementById('graphEditorDialog').showModal();}''', {'markup': dialog, 'theme': theme})
    page.wait_for_function('document.querySelector(".dge-overlay").dataset.geometryReady==="true"')


def test_legacy_saved_pages_new_page_and_account_scope(drawing_page):
    page = drawing_page
    assert page.locator('.ddw-name').input_value() == '我的图形'
    page.locator('.ddw-name').fill('带权图')
    assert page.evaluate('workspace.getDocument().graphs[0].name') == '带权图'
    page.get_by_role('button', name='新建空白页', exact=True).click()
    assert page.evaluate('workspace.getDocument().graphs[0].vertices.length') == 0
    assert page.evaluate('workspace.getDocument().graphs[0].name') == page.locator('.ddw-name').input_value()
    new_name = page.locator('.ddw-name').input_value()
    page.get_by_role('button', name='历史绘图', exact=True).click()
    page.get_by_role('button', name='带权图', exact=True).click()
    assert page.evaluate('workspace.getDocument().graphs[0].edges[0].weight') == 12
    page.evaluate("workspace.destroy();openDrawing('drawings:user1',null)")
    assert page.locator('.ddw-name').input_value() == '带权图'
    assert page.evaluate('workspace.getPages().length') == 2
    assert page.evaluate('(name)=>workspace.getPages().find(p=>p.name===name).document.graphs[0].name', new_name) == new_name
    page.evaluate("workspace.destroy();openDrawing('drawings:user2',null)")
    assert page.evaluate('workspace.getDocument().graphs') == []
    assert page.evaluate('workspace.getPages()') == []
    assert page.locator('.ddw-name').input_value() == ''
    assert page.evaluate("JSON.parse(localStorage.getItem('drawings:user1')).pages.length") == 2


def test_guidance_uses_snapshot_and_does_not_modify_drawing(drawing_page):
    page = drawing_page
    page.get_by_role('button', name='AI指导', exact=True).click()
    page.get_by_label('绘图指导要求（可选）').fill('说明有向边怎么画')
    page.get_by_role('button', name='请求 AI 指导', exact=True).click()
    page.wait_for_function('document.querySelector(".ddw-ai-answer").textContent.includes("从 A 向 B")')
    assert page.evaluate('aiRequests.length') == 1
    assert page.evaluate('aiRequests[0].requirement') == '说明有向边怎么画'
    assert page.evaluate('aiRequests[0].document.graphs[0].edges[0].direction') == 'forward'
    assert page.evaluate('workspace.getDocument().graphs[0].edges[0].weight') == 12
    # Editing the requirement clears a completed answer without disrupting typing.
    page.get_by_label('绘图指导要求（可选）').fill('重新解释')
    assert '从 A 向 B' not in page.locator('.ddw-ai-answer').inner_text()
    assert page.get_by_label('绘图指导要求（可选）').input_value() == '重新解释'
    page.evaluate('window.deferAi=true')
    page.get_by_role('button', name='请求 AI 指导', exact=True).click()
    assert page.get_by_role('button', name='请求 AI 指导', exact=True).is_disabled()
    assert page.get_by_role('button', name='请求 AI 指导', exact=True).get_attribute('aria-busy') == 'true'
    page.get_by_role('button', name='新建空白页', exact=True).click()
    assert page.evaluate('window.aiAborted')
    page.evaluate('resolveAi()')
    page.wait_for_timeout(50)
    assert page.locator('.ddw-ai-answer').count() == 0
    page.get_by_role('button', name='AI指导', exact=True).click()
    assert page.locator('.ddw-ai-answer').inner_text() == ''
    assert page.get_by_role('button', name='请求 AI 指导', exact=True).is_enabled()
    assert page.get_by_role('button', name='请求 AI 指导', exact=True).get_attribute('aria-busy') == 'false'


def test_old_multiple_graphs_become_individual_accessible_pages(drawing_page):
    page = drawing_page
    page.evaluate('''()=>{workspace.destroy();const legacy=structuredClone(sample);
      legacy.graphs.push({...structuredClone(sample.graphs[0]),id:'G2',name:'原来的第二张图'});
      openDrawing('drawings:legacy-multiple',legacy);}''')
    assert page.evaluate('workspace.getPages().length') == 2
    assert page.evaluate('workspace.getPages().every(p=>p.document.graphs.length===1)')
    page.get_by_role('button', name='历史绘图', exact=True).click()
    page.get_by_role('button', name='原来的第二张图', exact=True).click()
    assert page.evaluate('workspace.getDocument().graphs[0].id') == 'G2'


def test_export_png_and_upload_only_enqueue_result(drawing_page, tmp_path):
    from PIL import Image
    page = drawing_page
    # Actual production SVG is converted by a browser canvas and downloaded.
    mobile = page.viewport_size['width'] < 760
    if mobile:
        page.get_by_role('button', name='导出图片', exact=True).click()
        preview = page.get_by_role('dialog', name='导出绘图', exact=True)
        assert preview.locator('img').get_attribute('src').startswith('blob:')
        assert page.get_by_role('button', name='新建空白页', exact=True).is_disabled()
        with page.expect_download() as download:
            preview.get_by_role('link', name='下载图片', exact=True).click()
        preview.get_by_role('button', name='关闭图片预览', exact=True).click()
        assert preview.count() == 0
    else:
        with page.expect_download() as download:
            page.get_by_role('button', name='导出图片', exact=True).click()
    path = tmp_path / 'drawing.png'
    download.value.save_as(path)
    with Image.open(path) as image:
        assert image.format == 'PNG'
        assert image.width > 100 and image.height > 50
        assert image.convert('RGB').getextrema()[0][0] < 100
    page.get_by_role('button', name='上传', exact=True).click()
    page.wait_for_function('uploads.length===1')
    upload = page.evaluate('uploads[0]')
    assert upload['type'] == 'image/png' and upload['size'] > 100
    assert upload['metadata']['document']['graphs'][0]['edges'][0]['weight'] == 12
    # Upload coordinates refer to the exported tight PNG, including a node
    # drawn beyond the original blank page, not the original source viewport.
    assert all(0 <= v['x'] <= 1 and 0 <= v['y'] <= 1
               for v in upload['metadata']['document']['graphs'][0]['vertices'])
    assert upload['metadata']['document']['graphs'][0]['vertices'][1]['x'] != 1.2
    assert upload['metadata']['document']['graphs'][0]['bbox'] == [0, 0, 1, 1]
    assert page.evaluate('closeCount') == 1
    assert page.evaluate('aiRequests.length') == 0


def test_guide_requirement_matches_backend_limit(drawing_page):
    page = drawing_page
    page.get_by_role('button', name='AI指导', exact=True).click()
    assert page.get_by_label('绘图指导要求（可选）').get_attribute('maxlength') == '2000'
    page.get_by_label('绘图指导要求（可选）').fill('画' * 2000)
    page.get_by_role('button', name='请求 AI 指导', exact=True).click()
    page.wait_for_function('aiRequests.length===1')
    assert len(page.evaluate('aiRequests[0].requirement')) == 2000


def test_drawing_upload_is_literal_text_and_guidance_uses_the_chat_send_arrow(drawing_page):
    page = drawing_page
    button = page.get_by_role('button', name='上传', exact=True)
    assert button.inner_text() == '上传'
    assert button.get_attribute('title') == '上传'
    box = button.bounding_box()
    assert button.evaluate('e=>getComputedStyle(e).borderRadius') != '50%'
    assert button.evaluate('e=>getComputedStyle(e,"::before").content') == 'none'
    assert page.locator('.ddw-page-actions').bounding_box()['x'] <= box['x']
    page.get_by_role('button', name='AI指导', exact=True).click()
    assert page.locator('.ddw-panel-header h3').inner_text() == 'AI指导'
    guide = page.get_by_role('button', name='请求 AI 指导', exact=True)
    assert guide.inner_text() == ''
    assert guide.get_attribute('title') == '请求 AI 指导'
    assert guide.get_attribute('aria-busy') == 'false'
    page.add_style_tag(content=(ROOT / 'static/chat-composer.css').read_text())
    page.evaluate('''()=>{document.body.dataset.appearanceTheme='light';const reference=document.createElement('div');
      reference.className='center';reference.style.cssText='position:fixed;left:-2000px;bottom:0;width:500px';
      reference.innerHTML='<div class="input-wrap"><div class="input"><button id="sendBtn" type="button">发送</button></div></div>';
      document.body.append(reference);}''')
    chat_send = page.locator('#sendBtn')
    icon = guide.locator('svg')
    assert icon.get_attribute('aria-hidden') == 'true'
    assert icon.get_attribute('viewBox') == '0 0 24 24'
    assert icon.locator('path').get_attribute('d') == 'M12 20V4m-7 7 7-7 7 7'
    assert icon.locator('path').get_attribute('stroke-width') == '2.4'
    assert guide.evaluate('e=>getComputedStyle(e).borderRadius') == '50%'
    assert guide.bounding_box()['width'] == guide.bounding_box()['height'] == 38
    for color in ('#3b82f6', '#14b8a6', '#8b5cf6'):
        page.evaluate('color=>document.body.style.setProperty("--accent",color)', color)
        expected = page.evaluate('color=>{const node=document.createElement("i");node.style.color=color;document.body.append(node);const rgb=getComputedStyle(node).color;node.remove();return rgb;}', color)
        assert button.evaluate('e=>getComputedStyle(e).backgroundColor') == expected
        assert guide.evaluate('e=>getComputedStyle(e).backgroundColor') == chat_send.evaluate('e=>getComputedStyle(e).backgroundColor') == expected
        assert icon.locator('path').evaluate('e=>getComputedStyle(e).stroke') == 'rgb(255, 255, 255)'
        assert 'M12 20V4m-7 7 7-7 7 7' in chat_send.evaluate('e=>decodeURIComponent(getComputedStyle(e,"::before").maskImage)')
    assert page.evaluate('aiRequests.length') == page.evaluate('uploads.length') == 0


def test_empty_page_export_and_storage_failure_are_honest(drawing_page):
    page = drawing_page
    page.get_by_role('button', name='新建空白页', exact=True).click()
    page.get_by_role('button', name='导出图片', exact=True).click()
    assert '请先' in page.locator('.ddw-status').inner_text()
    page.evaluate("()=>{Storage.prototype.setItem=function(){throw new DOMException('quota','QuotaExceededError')};}")
    page.locator('.ddw-name').fill('仍在内存中')
    page.wait_for_function('document.querySelector(".ddw-status").textContent.includes("存储不足")')
    assert page.locator('.ddw-status').evaluate("e=>e.classList.contains('is-error')")
    assert page.locator('.ddw-name').input_value() == '仍在内存中'
    assert page.evaluate('workspace.getPages().some(p=>p.name==="仍在内存中")')


@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_drawing_panels_share_compact_popovers_and_horizontal_accessible_triggers(drawing_page, theme):
    page = drawing_page
    colors = {'--surface-1': '#ffffff', '--surface-2': '#f8fafc', '--border-strong': '#cbd5e1', '--text-primary': '#172033'} if theme == 'light' else {'--surface-1': '#1e293b', '--surface-2': '#0f172a', '--border-strong': '#475569', '--text-primary': '#f8fafc'}
    page.evaluate('colors=>{for(const [key,value] of Object.entries(colors))document.body.style.setProperty(key,value)}', colors)
    rail = page.get_by_role('toolbar', name='绘图面板', exact=True)
    controls = rail.get_by_role('button')
    assert controls.count() == 3
    boxes = [controls.nth(i).bounding_box() for i in range(3)]
    assert all(box is not None for box in boxes)
    for index, box in enumerate(boxes):
        assert box['y'] == pytest.approx(boxes[0]['y'], abs=1)
        for other in boxes[index + 1:]:
            assert box['x'] + box['width'] <= other['x']
    tools = page.locator('.dge-tool-palette > summary')
    tool_box = tools.bounding_box()
    assert tool_box['x'] + tool_box['width'] <= boxes[0]['x']
    assert tools.get_attribute('aria-expanded') == 'false'
    assert page.locator('.dge-floating-actions > details > summary').evaluate_all(
        'nodes=>nodes.every(n=>getComputedStyle(n).display==="none")')
    page.evaluate('''()=>{const probe=document.createElement('aside');probe.className='dgs-source-picker';
      probe.style.visibility='hidden';probe.dataset.styleProbe='true';document.querySelector('.ddw-editor').append(probe);}''')
    appearance = '''e=>{const s=getComputedStyle(e);return {background:s.backgroundColor,border:s.border,padding:s.padding,radius:s.borderRadius,shadow:s.boxShadow}}'''
    expected = page.locator('[data-style-probe]').evaluate(appearance)
    for label, selector in [('绘图工具', '.dge-tool-palette > .dge-overlay-tools'), ('绘图设置', '[data-panel-key="graphs"] > .dge-float-content'),
                            ('图形信息', '[data-panel-key="results"] > .dge-float-content'), ('历史绘图', '.ddw-side-panel'), ('AI指导', '.ddw-side-panel')]:
        trigger = tools if label == '绘图工具' else page.get_by_role('button', name=label, exact=True)
        trigger.click()
        content = page.locator(selector)
        assert content.is_visible()
        assert trigger.is_visible() and trigger.get_attribute('aria-expanded') == 'true'
        assert rail.is_visible()
        assert content.evaluate(appearance) == expected
        assert page.locator('.ddw-panel-header button,.ddw-editor-panel-header button').count() == 0
        bounds = content.bounding_box()
        anchor = trigger.bounding_box()
        assert bounds['y'] == pytest.approx(anchor['y'] + anchor['height'] + 8, abs=1)
        assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= page.viewport_size['width']
        assert content.evaluate('e=>e.scrollWidth<=e.clientWidth')
        if label == '绘图工具':
            assert page.locator('.dge-tool-palette .dge-overlay-status').is_hidden()
        if label in ('绘图工具', '历史绘图'):
            page.screenshot(path='/tmp/dmate-drawing-'+('tools' if label == '绘图工具' else 'history')+'-'+theme+'-'+('mobile' if page.viewport_size['width'] < 760 else 'desktop')+'.png')
        # Clicking content leaves it open; its own visible trigger folds it.
        content.click(position={'x': 4, 'y': 4})
        assert trigger.get_attribute('aria-expanded') == 'true'
        trigger.click()
        assert trigger.get_attribute('aria-expanded') == 'false'
        trigger.click()
        page.locator('.ddw-name').click()
        assert trigger.get_attribute('aria-expanded') == 'false'
        trigger.click()
        trigger.press('Escape')
        assert trigger.get_attribute('aria-expanded') == 'false'
        assert trigger.evaluate('e=>e===document.activeElement')
        assert trigger.evaluate('e=>getComputedStyle(e).outlineStyle') == 'none'
    page.locator('[data-style-probe]').evaluate('e=>e.remove()')
    assert '绘图保存在此设备' not in page.locator('.dmate-drawing-workspace').inner_text()
    assert 'AI 会根据当前绘图' not in page.locator('.dmate-drawing-workspace').inner_text()
    assert page.locator('.ddw-status').is_hidden()
    page.screenshot(path='/tmp/dmate-drawing-popovers-'+theme+'-'+('mobile' if page.viewport_size['width'] < 760 else 'desktop')+'.png')


def test_history_is_next_to_new_page_in_top_actions_and_opens_above_canvas(drawing_page):
    page = drawing_page
    actions = page.locator('.ddw-page-actions')
    assert actions.get_by_role('button').all_text_contents() == ['新建空白页', '历史绘图', '导出图片', '上传']
    assert actions.get_by_role('button', name='上传', exact=True).count() == 1
    new = actions.get_by_role('button', name='新建空白页', exact=True).bounding_box()
    history = actions.get_by_role('button', name='历史绘图', exact=True)
    box = history.bounding_box()
    assert box['y'] == pytest.approx(new['y'], abs=1)
    assert box['x'] >= new['x'] + new['width'] + 4
    assert page.get_by_role('toolbar', name='绘图面板').get_by_role('button', name='历史绘图', exact=True).count() == 0
    for button in actions.get_by_role('button').all():
        bounds = button.bounding_box()
        assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= page.viewport_size['width']
        assert button.evaluate('e=>e.scrollWidth<=e.clientWidth')
    assert page.evaluate('document.documentElement.scrollWidth') <= page.viewport_size['width']
    history.click()
    assert history.get_attribute('aria-expanded') == 'true'
    assert history.is_visible()
    assert page.locator('.ddw-history-list').is_visible()
    history.click()
    assert history.get_attribute('aria-expanded') == 'false'
    assert page.locator('.ddw-side-panel').is_hidden()
    history.click()
    history.press('Escape')
    assert history.is_visible() and history.get_attribute('aria-expanded') == 'false'


def test_drawing_settings_remain_open_across_editor_redraw(drawing_page):
    page = drawing_page
    page.get_by_role('button', name='绘图设置', exact=True).click()
    page.get_by_label('绘图方向', exact=True).select_option('no')
    page.get_by_label('绘图权值', exact=True).select_option('no')
    page.get_by_role('button', name='绘图设置', exact=True).click()
    assert page.get_by_role('toolbar', name='绘图面板').is_visible()
    assert page.evaluate('workspace.getDocument().graphs[0].directed') is False
    assert page.evaluate('workspace.getDocument().graphs[0].weighted') is False


def test_top_name_is_the_only_drawing_name_and_refreshes_graph_information(drawing_page):
    page = drawing_page
    before = page.locator('.dge-overlay-image').bounding_box()
    page.locator('.ddw-name').fill('画页甲')
    assert page.evaluate('workspace.getDocument().graphs[0].name') == '画页甲'
    page.get_by_role('button', name='绘图设置', exact=True).click()
    assert page.get_by_label('画页名称', exact=True).count() == 0
    assert page.locator('.ddw-name').input_value() == '画页甲'
    page.get_by_role('button', name='绘图设置', exact=True).click()
    page.get_by_role('button', name='图形信息', exact=True).click()
    assert page.locator('.dge-review-content .dgs-counts').inner_text() == '2 个顶点 · 1 条边'
    assert page.evaluate('workspace.getDocument().graphs[0].name') == '画页甲'
    assert page.locator('.dge-overlay-image').bounding_box() == pytest.approx(before, abs=1)
    page.get_by_role('button', name='图形信息', exact=True).click()
    page.get_by_role('button', name='撤销', exact=True).click()
    assert page.locator('.ddw-name').input_value() == page.evaluate('workspace.getDocument().graphs[0].name')
    page.get_by_role('button', name='重做', exact=True).click()
    assert page.locator('.ddw-name').input_value() == '画页甲'


def test_drawing_answer_uses_shared_renderer_and_invalidates_on_edit(drawing_page):
    page = drawing_page
    page.evaluate('''()=>{window.richRenderCalls=[];window.DMateAIAnswer={render:(target,text,options)=>{
      richRenderCalls.push(text);if(!options.isCurrent())throw new Error('stale answer');
      target.classList.add('wrong-answer-inner');const p=document.createElement('p');p.textContent=text;target.replaceChildren(p);
      return Promise.resolve(true);}};}''')
    page.get_by_role('button', name='AI指导', exact=True).click()
    assert page.locator('.ddw-ai-answer').text_content() == ''
    page.get_by_role('button', name='请求 AI 指导', exact=True).click()
    page.wait_for_function('richRenderCalls.length===1')
    assert page.locator('.ddw-ai-answer.wrong-answer-inner p').count() == 1
    page.get_by_label('绘图指导要求（可选）').fill('换一种画法')
    assert page.locator('.ddw-ai-answer').text_content() == ''


def test_opening_another_popover_only_changes_that_trigger_and_closes_the_previous(drawing_page):
    page = drawing_page
    tools = page.locator('.dge-tool-palette > summary')
    tools.click()
    settings = page.get_by_role('button', name='绘图设置', exact=True)
    settings.click()
    assert tools.get_attribute('aria-expanded') == 'false'
    assert settings.get_attribute('aria-expanded') == 'true'
    ai = page.get_by_role('button', name='AI指导', exact=True)
    ai.click()
    assert settings.get_attribute('aria-expanded') == 'false'
    assert ai.get_attribute('aria-expanded') == 'true'
    history = page.get_by_role('button', name='历史绘图', exact=True)
    history.click()
    assert ai.get_attribute('aria-expanded') == 'false'
    assert history.get_attribute('aria-expanded') == 'true'
    tools.click()
    assert tools.get_attribute('aria-expanded') == 'true'
    assert history.get_attribute('aria-expanded') == 'false'
    assert page.locator('.ddw-side-panel').is_hidden()


def test_history_red_delete_circle_removes_its_page_and_keeps_current_drawing(drawing_page):
    page = drawing_page
    page.get_by_role('button', name='新建空白页', exact=True).click()
    active_name = page.locator('.ddw-name').input_value()
    page.get_by_role('button', name='历史绘图', exact=True).click()
    row = page.locator('.ddw-history-item', has=page.get_by_role('button', name='我的图形', exact=True))
    remove = row.get_by_role('button', name='删除绘图：我的图形', exact=False)
    assert remove.inner_text() == ''
    assert remove.evaluate('e=>getComputedStyle(e).backgroundColor') == 'rgb(239, 68, 68)'
    assert remove.evaluate('e=>getComputedStyle(e).borderRadius') == '50%'
    bounds = remove.bounding_box()
    assert bounds['width'] == bounds['height'] and bounds['width'] >= 20
    assert remove.get_attribute('aria-label').endswith('）')
    remove.click()
    assert page.evaluate('workspace.getPages().length') == 2
    page.get_by_role('button', name='删除绘图', exact=True).click()
    assert page.evaluate('workspace.getPages().length') == 1
    assert page.locator('.ddw-name').input_value() == active_name
    assert page.evaluate('workspace.getDocument().graphs[0].vertices.length') == 0
    assert page.locator('.ddw-history-item').count() == 1
    assert page.locator('.ddw-history-meta').count() == 0
    assert page.locator('.ddw-status').is_hidden()
    page.locator('.ddw-history-delete').click()
    page.get_by_role('button', name='删除绘图', exact=True).click()
    assert page.evaluate('workspace.getPages()') == []
    assert page.evaluate('workspace.getDocument().graphs') == []
    assert page.locator('.ddw-name').input_value() == ''
    assert page.locator('.dge-overlay-node,.dge-overlay-edge').count() == 0
    page.locator('.ddw-side-panel').wait_for(state='visible')
    assert page.locator('.ddw-history-list').text_content() == '无'
    assert page.evaluate("JSON.parse(localStorage.getItem('drawings:user1'))") == {'version': 2, 'activeId': '', 'pages': []}
    page.evaluate('workspace.destroy();openDrawing()')
    assert page.evaluate('workspace.getPages()') == []
    assert page.evaluate('workspace.getDocument().graphs') == []
    assert page.locator('.ddw-name').input_value() == ''
    assert page.locator('.ddw-name').is_disabled()
    page.get_by_role('button', name='历史绘图', exact=True).click()
    page.locator('.ddw-side-panel').wait_for(state='visible')
    assert page.locator('.ddw-history-list').text_content() == '无'
    page.get_by_role('button', name='新建空白页', exact=True).click()
    assert page.evaluate('workspace.getPages().length') == 1
    assert page.locator('.ddw-name').input_value() == '绘图 1'


def test_upload_callback_failure_is_visible_and_the_same_button_can_retry(drawing_page):
    page = drawing_page
    upload = page.get_by_role('button', name='上传', exact=True)
    page.evaluate('window.uploadFailure="绘图上传失败，请重试。"')
    upload.click()
    page.wait_for_function('document.querySelector(".ddw-status").textContent==="绘图上传失败，请重试。"')
    assert page.locator('.ddw-status.is-error').is_visible()
    assert upload.is_enabled()
    assert page.evaluate('uploads.length===0 && closeCount===0')
    page.evaluate('window.uploadFailure=""')
    upload.click()
    page.wait_for_function('uploads.length===1 && closeCount===1')
    assert page.locator('.ddw-status').is_hidden()


def test_history_delete_cancel_keeps_saved_pages_and_returns_focus(drawing_page):
    page = drawing_page
    page.get_by_role('button', name='历史绘图', exact=True).click()
    before = page.evaluate("localStorage.getItem('drawings:user1')")
    identifier = page.evaluate('workspace.getPages()[0].id')
    trigger = page.locator('.ddw-history-delete')
    for cancel in ['button', 'escape', 'outside']:
        trigger.click()
        prompt = page.get_by_role('dialog', name='删除这个绘图？', exact=True)
        prompt.wait_for(state='visible')
        assert prompt.get_by_role('button', name='取消', exact=True).count() == 0
        assert page.evaluate('workspace.getPages()[0].id') == identifier
        if cancel == 'button':
            prompt.get_by_role('button', name='取消删除', exact=True).click()
        elif cancel == 'escape':
            page.keyboard.press('Escape')
        else:
            page.mouse.click(1, 1)
        prompt.wait_for(state='detached')
        assert page.locator('.ddw-history-list').is_visible()
        assert trigger.is_enabled()
        page.wait_for_function('document.activeElement.classList.contains("ddw-history-delete")')
        assert page.evaluate("localStorage.getItem('drawings:user1')") == before
        assert page.evaluate('workspace.getPages()[0].id') == identifier


def test_history_delete_does_not_remove_a_page_changed_while_confirming(drawing_page):
    page = drawing_page
    page.get_by_role('button', name='历史绘图', exact=True).click()
    identifier = page.evaluate('workspace.getPages()[0].id')
    page.locator('.ddw-history-delete').click()
    page.evaluate('''()=>{const input=document.querySelector('.ddw-name');
      input.value='确认期间更新的绘图';input.dispatchEvent(new Event('input',{bubbles:true}));}''')
    page.get_by_role('button', name='删除绘图', exact=True).click()
    assert page.evaluate('workspace.getPages().length') == 1
    assert page.evaluate('workspace.getPages()[0].id') == identifier
    assert page.locator('.ddw-name').input_value() == '确认期间更新的绘图'
    page.wait_for_function("JSON.parse(localStorage.getItem('drawings:user1')).pages[0].name==='确认期间更新的绘图'")
    page.locator('.ddw-history-delete').click()
    page.get_by_role('button', name='删除绘图', exact=True).click()
    assert page.evaluate('workspace.getPages()') == []


def test_history_delete_prompt_closes_on_workspace_destroy_and_cannot_affect_another_owner(drawing_page):
    page = drawing_page
    page.get_by_role('button', name='历史绘图', exact=True).click()
    page.locator('.ddw-history-delete').click()
    page.get_by_role('dialog', name='删除这个绘图？', exact=True).wait_for(state='visible')
    page.evaluate("workspace.destroy();openDrawing('drawings:other-owner',sample)")
    assert page.locator('.dmate-delete-confirm').count() == 0
    assert page.evaluate("JSON.parse(localStorage.getItem('drawings:user1')).pages.length") == 1
    assert page.evaluate('workspace.getPages().length') == 1
    assert page.evaluate("JSON.parse(localStorage.getItem('drawings:other-owner')).pages.length") == 1


def test_delayed_external_history_confirmation_cannot_delete_after_destroy(drawing_page):
    page = drawing_page
    page.evaluate("workspace.destroy();openDrawing('drawings:cancelled',sample,{confirmDelete:()=>false})")
    page.get_by_role('button', name='历史绘图', exact=True).click()
    page.locator('.ddw-history-delete').click()
    assert page.evaluate('workspace.getPages().length') == 1
    assert page.locator('.ddw-status').is_hidden()
    page.evaluate('''()=>{workspace.destroy();openDrawing('drawings:delayed',sample,{
      confirmDelete:settings=>{window.deleteSettings=settings;return new Promise(resolve=>window.finishDelete=resolve);}});}''')
    page.get_by_role('button', name='历史绘图', exact=True).click()
    page.locator('.ddw-history-delete').click()
    assert page.evaluate('deleteSettings.confirmText') == '删除绘图'
    assert page.evaluate('workspace.getPages().length') == 1
    page.evaluate("workspace.destroy();openDrawing('drawings:next',sample);finishDelete(true)")
    assert page.evaluate("JSON.parse(localStorage.getItem('drawings:delayed')).pages.length") == 1
    assert page.evaluate("JSON.parse(localStorage.getItem('drawings:next')).pages.length") == 1
    assert page.evaluate('workspace.getPages().length') == 1


def test_reopened_numbered_pages_migrate_only_the_old_generic_graph_title(drawing_page):
    page = drawing_page
    page.evaluate('''()=>{workspace.destroy();window.oldGeneric=structuredClone(sample);oldGeneric.graphs[0].name='我的图形';
      localStorage.setItem('drawings:old-generic',JSON.stringify({version:1,activeId:'old-page',pages:[
        {id:'old-page',name:'绘图 5',document:oldGeneric,requirement:'',createdAt:1,updatedAt:2},
        {id:'real-title',name:'绘图 6',document:sample,requirement:'',createdAt:3,updatedAt:4}
      ]}));openDrawing('drawings:old-generic',null);}''')
    assert page.locator('.ddw-name').input_value() == '绘图 5'
    assert page.evaluate('workspace.getDocument().graphs[0].name') == '绘图 5'
    saved = page.evaluate('JSON.parse(localStorage.getItem("drawings:old-generic")).pages')
    expected = page.evaluate('structuredClone(oldGeneric)')
    expected['graphs'][0]['name'] = '绘图 5'
    assert saved[0]['document'] == expected
    assert saved[1]['document'] == page.evaluate('sample')
    page.evaluate("workspace.destroy();openDrawing('drawings:old-generic',null)")
    assert page.locator('.ddw-name').input_value() == '绘图 5'
    page.get_by_role('button', name='图形信息', exact=True).click()
    assert page.locator('.dge-review-content .dgs-counts').inner_text() == '2 个顶点 · 1 条边'
    assert page.evaluate('workspace.getDocument().graphs[0].name') == '绘图 5'
    assert page.evaluate('workspace.getPages().find(p=>p.id==="real-title").document.graphs[0].name') == '原来的图'


def test_empty_first_use_does_not_import_a_placeholder_but_preserves_named_legacy(drawing_page):
    page = drawing_page
    placeholder = page.evaluate('DMateDrawingWorkspace.blankDocument()')
    for key, legacy in [('new-empty', None), ('blank-placeholder', placeholder)]:
        page.evaluate('(values)=>{workspace.destroy();openDrawing(values.key,values.legacy);}', {'key': key, 'legacy': legacy})
        assert page.evaluate('workspace.getPages()') == []
        assert page.evaluate('workspace.getDocument()') == {'body_text': '', 'graphs': []}
        assert page.locator('.ddw-name').input_value() == ''
        assert page.locator('.dge-overlay-node,.dge-overlay-edge').count() == 0
        assert page.get_by_role('button', name='新建空白页', exact=True).is_enabled()
        page.get_by_role('button', name='历史绘图', exact=True).click()
        assert page.locator('.ddw-history-list').inner_text() == '无'
        assert page.evaluate('(key)=>JSON.parse(localStorage.getItem(key))', key) == {'version': 2, 'activeId': '', 'pages': []}
    page.evaluate("workspace.destroy();openDrawing('named-legacy',DMateDrawingWorkspace.blankDocument('保留的空图'))")
    assert page.evaluate('workspace.getPages().length') == 1
    assert page.evaluate('workspace.getDocument().graphs[0].name') == '保留的空图'
    page.evaluate("workspace.destroy();localStorage.setItem('old-empty',JSON.stringify({version:1,activeId:'',pages:[]}));openDrawing('old-empty',sample)")
    assert page.evaluate('workspace.getPages()') == []
    assert page.evaluate("JSON.parse(localStorage.getItem('old-empty')).version") == 2


def test_last_geometry_name_and_requirements_are_saved_immediately_on_close(drawing_page):
    page = drawing_page
    node = page.locator('[data-vertex-id="a"] .dge-overlay-node-hit').bounding_box()
    page.mouse.move(node['x'] + node['width'] / 2, node['y'] + node['height'] / 2)
    page.mouse.down()
    page.mouse.move(node['x'] + node['width'] / 2 + 18, node['y'] + node['height'] / 2 + 20, steps=5)
    page.mouse.up()
    point = page.evaluate('workspace.getDocument().graphs[0].vertices.find(v=>v.id==="a")')
    assert point['x'] != .2 or point['y'] != .3
    page.locator('.ddw-name').fill('关闭前的最后一次编辑')
    page.get_by_role('button', name='AI指导', exact=True).click()
    requirement = '关闭前刚输入的要求'
    page.get_by_label('绘图指导要求（可选）').fill(requirement)
    assert page.evaluate("JSON.parse(localStorage.getItem('drawings:user1')).pages[0].requirement") != requirement
    page.evaluate("workspace.destroy();openDrawing('drawings:user1',null)")
    assert page.locator('.ddw-name').input_value() == '关闭前的最后一次编辑'
    assert page.evaluate('workspace.getDocument().graphs[0].vertices.find(v=>v.id==="a")') == point
    page.get_by_role('button', name='AI指导', exact=True).click()
    assert page.get_by_label('绘图指导要求（可选）').input_value() == requirement
    assert page.evaluate('aiRequests') == []


def test_popovers_are_anchored_on_the_first_visible_frame_and_reclamp_on_resize(drawing_page):
    page = drawing_page
    for label, selector in [('历史绘图', '.ddw-side-panel'), ('绘图设置', '[data-panel-key="graphs"] > .dge-float-content'),
                            ('图形信息', '[data-panel-key="results"] > .dge-float-content')]:
        trigger = page.get_by_role('button', name=label, exact=True)
        trigger.evaluate('''(button,selector)=>{window.firstPopoverFrame=null;button.addEventListener('click',()=>requestAnimationFrame(()=>{
          const content=document.querySelector(selector),box=content.getBoundingClientRect(),anchor=button.getBoundingClientRect();
          window.firstPopoverFrame={visible:getComputedStyle(content).visibility,top:box.top,bottom:box.bottom,left:box.left,right:box.right,anchorBottom:anchor.bottom};
        }),{once:true});}''', selector)
        trigger.click()
        page.wait_for_function('window.firstPopoverFrame!==null')
        frame = page.evaluate('firstPopoverFrame')
        assert frame['visible'] == 'visible'
        assert frame['top'] == pytest.approx(frame['anchorBottom'] + 8, abs=1)
        assert frame['left'] >= 8 and frame['right'] <= page.viewport_size['width'] - 8
        assert frame['bottom'] <= page.viewport_size['height'] - 8
        trigger.click()
    page.get_by_role('button', name='历史绘图', exact=True).click()
    page.set_viewport_size({'width': 340, 'height': 580})
    page.wait_for_function('''()=>{const box=document.querySelector('.ddw-side-panel').getBoundingClientRect();
      return box.left>=7.5&&box.right<=innerWidth-7.5&&box.top>=7.5&&box.bottom<=innerHeight-7.5;}''')
    history = page.get_by_role('button', name='历史绘图', exact=True).bounding_box()
    popup = page.locator('.ddw-side-panel').bounding_box()
    assert popup['y'] == pytest.approx(history['y'] + history['height'] + 8, abs=1)


@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_real_template_tools_have_one_surface_and_open_on_every_click_even_when_gallery_empty(drawing_page, theme):
    page = drawing_page
    use_real_dialog_and_template_styles(page, theme)
    for empty in (False, True):
        if empty:
            page.evaluate("workspace.destroy();openDrawing('drawings:real-template-empty',null)")
            assert page.evaluate('workspace.getPages()') == []
            assert page.locator('.ddw-name').input_value() == ''
        palette = page.locator('.dge-tool-palette')
        trigger = palette.locator(':scope > summary')
        surface = palette.evaluate('''node=>{const style=getComputedStyle(node),box=node.getBoundingClientRect(),trigger=node.querySelector(':scope > summary').getBoundingClientRect();
          return {background:style.backgroundColor,image:style.backgroundImage,shadow:style.boxShadow,border:style.borderWidth,padding:style.padding,width:box.width,height:box.height,triggerWidth:trigger.width,triggerHeight:trigger.height};}''')
        size = 'mobile' if page.viewport_size['width'] < 760 else 'desktop'
        page.screenshot(path='/tmp/dmate-tools-before-'+theme+'-'+size+('-empty' if empty else '')+'.png')
        assert surface['background'] == 'rgba(0, 0, 0, 0)', surface
        assert surface['image'] == 'none' and surface['shadow'] == 'none', surface
        assert surface['border'] == '0px' and surface['padding'] == '0px', surface
        assert surface['width'] == pytest.approx(surface['triggerWidth'], abs=1), surface
        assert surface['height'] == pytest.approx(surface['triggerHeight'], abs=1), surface
        for index in range(6):
            trigger.click(timeout=3000)
            expanded = index % 2 == 0
            assert trigger.get_attribute('aria-expanded') == str(expanded).lower()
            assert palette.evaluate('node=>node.open') is expanded
            if expanded:
                assert page.get_by_role('button', name='添加顶点', exact=True).is_visible()
                assert page.locator('.dge-overlay-tools').evaluate('node=>getComputedStyle(node).visibility') == 'visible'
                bounds = palette.evaluate('''node=>{
                  const rect=element=>{const {x,y,width,height}=element.getBoundingClientRect();return {x,y,width,height};};
                  return {palette:rect(node),trigger:rect(node.querySelector(':scope > summary'))};
                }''')
                assert bounds['palette'] == pytest.approx(bounds['trigger'], abs=1)
                assert palette.evaluate('node=>getComputedStyle(node).backgroundColor') == 'rgba(0, 0, 0, 0)'
                assert page.locator('[data-overlay-tool="vertex"]').evaluate('''node=>{const box=node.getBoundingClientRect();
                  return document.elementFromPoint(box.x+box.width/2,box.y+box.height/2)?.closest('[data-overlay-tool="vertex"]')===node;}''')
            else:
                assert page.get_by_role('button', name='添加顶点', exact=True).count() == 0
            assert page.evaluate('workspace.getPages().length') == 1
        trigger.click()
        page.get_by_role('button', name='添加顶点', exact=True).click()
        assert page.locator('[data-overlay-tool="vertex"]').get_attribute('aria-pressed') == 'true'
        page.screenshot(path='/tmp/dmate-tools-expanded-'+theme+'-'+size+('-empty' if empty else '')+'.png')
        before = page.evaluate('workspace.getDocument().graphs[0].vertices.length')
        canvas = page.locator('.dge-overlay-viewport').bounding_box()
        page.mouse.click(canvas['x'] + canvas['width'] * .55, canvas['y'] + canvas['height'] * .7)
        assert page.evaluate('workspace.getDocument().graphs[0].vertices.length') == before + 1
        storage_key = 'drawings:real-template-empty' if empty else 'drawings:real-template'
        page.wait_for_function('''({key,count})=>JSON.parse(localStorage.getItem(key)).pages[0].document.graphs[0].vertices.length===count''', arg={'key': storage_key, 'count': before + 1})
        page.screenshot(path='/tmp/dmate-tools-working-'+theme+'-'+size+('-empty' if empty else '')+'.png')


@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_real_template_controls_keep_clearance_with_long_names_zoom_and_scrollbars(drawing_page, theme):
    page = drawing_page
    use_real_dialog_and_template_styles(page, theme)
    page.locator('.ddw-name').fill('用于检查界面留白的很长绘图名称' * 4 + '.png')
    page.add_style_tag(content='''.dge-overlay-viewport{scrollbar-gutter:stable both-edges;scrollbar-width:auto}
      .dge-overlay-viewport::-webkit-scrollbar{width:14px;height:14px}''')

    def assert_clearance():
        page.wait_for_function('''()=>{const viewport=document.querySelector('.dge-overlay-viewport'),view=document.querySelector('.dge-view-controls').getBoundingClientRect();
          const canvas=viewport.getBoundingClientRect(),rail=document.querySelector('.ddw-side-actions').getBoundingClientRect(),tools=document.querySelector('.dge-tool-palette>summary').getBoundingClientRect();
          return rail.top>=view.bottom+17.5&&canvas.left+viewport.clientLeft+viewport.clientWidth-rail.right>=17.5&&tools.left-canvas.left-viewport.clientLeft>=17.5;}''')
        header = page.locator('.graph-editor-dialog-head').bounding_box()
        actions = page.locator('.ddw-header').bounding_box()
        undo = page.locator('.dge-topline').bounding_box()
        assert actions['y'] - header['y'] - header['height'] >= 11.5
        assert undo['y'] - actions['y'] - actions['height'] >= 11.5
        tools = page.locator('.dge-tool-palette > summary').bounding_box()
        rail = page.locator('.ddw-side-actions').bounding_box()
        assert rail['x'] >= tools['x'] + tools['width'] + 11.5 or rail['y'] >= tools['y'] + tools['height'] + 11.5
        buttons = page.locator('.ddw-side-actions > button').all()
        boxes = [button.bounding_box() for button in buttons]
        assert all(box['y'] == pytest.approx(boxes[0]['y'], abs=1) for box in boxes)
        assert all(left['x'] + left['width'] < right['x'] for left, right in zip(boxes, boxes[1:]))
        assert page.locator('#graphEditorDialog').evaluate('n=>n.scrollWidth<=n.clientWidth')
        assert page.locator('.ddw-header').evaluate('n=>n.scrollWidth<=n.clientWidth')
        # The canvas has its own rounded clip, separate from the view toolbar.
        # Verify the white stage cannot paint or receive clicks in a cut corner.
        assert page.locator('.dge-overlay-viewport').evaluate('''node=>{
          const r=node.getBoundingClientRect(),s=getComputedStyle(node);
          const corner=document.elementFromPoint(r.left+.5,r.top+.5);
          const bar=document.querySelector('.dge-view-controls').getBoundingClientRect();
          return ['borderTopLeftRadius','borderTopRightRadius','borderBottomLeftRadius','borderBottomRightRadius'].every(k=>parseFloat(s[k])>=12)
            &&r.top-bar.bottom>=7.5&&!corner?.closest('.dge-overlay-stage');
        }''')
        ai = page.get_by_role('button', name='AI指导', exact=True)
        assert ai.evaluate('''node=>{const box=node.getBoundingClientRect();return document.elementFromPoint(box.x+box.width/2,box.y+box.height/2)?.closest('button')===node;}''')

    assert_clearance()
    for _ in range(4):
        page.get_by_role('button', name='放大原图', exact=True).click()
    page.locator('.dge-overlay-viewport').evaluate('node=>{node.scrollTop=node.scrollHeight;node.scrollLeft=node.scrollWidth;}')
    assert_clearance()
    page.get_by_role('button', name='AI指导', exact=True).click()
    send = page.get_by_role('button', name='请求 AI 指导', exact=True)
    assert send.locator('svg path').get_attribute('d') == 'M12 20V4m-7 7 7-7 7 7'
    assert send.evaluate('n=>getComputedStyle(n).backgroundColor') == 'rgb(59, 130, 246)'
    assert send.locator('svg path').evaluate('n=>getComputedStyle(n).stroke') == 'rgb(255, 255, 255)'
    size = 'mobile' if page.viewport_size['width'] < 760 else 'desktop'
    page.screenshot(path='/tmp/dmate-drawing-safe-spacing-'+theme+'-'+size+'.png')
    page.get_by_role('button', name='AI指导', exact=True).click()
    page.set_viewport_size({'width': 320, 'height': 720})
    assert_clearance()
    page.screenshot(path='/tmp/dmate-drawing-safe-spacing-'+theme+'-'+size+'-narrow.png')
