"""Standalone drawing pages use production UI, persisted docs and real PNG export."""
import json
import os
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
        for name in ['graph-editor.css', 'drawing-workspace.css']:
            page.add_style_tag(content=(ROOT / 'static' / name).read_text())
        for name in ['graph-editor-model.js', 'graph-editor-format.js', 'graph-editor-overlay.js', 'graph-editor.js', 'drawing-export.js', 'drawing-workspace.js']:
            page.add_script_tag(content=(ROOT / 'static' / name).read_text())
        page.evaluate('''()=>{
          window.sample={body_text:'',graphs:[{id:'G1',name:'原来的图',directed:true,weighted:true,
            vertices:[{id:'a',label:'A',x:.2,y:.3},{id:'b',label:'B',x:1.2,y:.7}],
            edges:[{id:'ab',from:'a',to:'b',direction:'forward',weight:12,path:[[.2,.3],[.7,.2],[1.2,.7]]}]}]};
          window.uploads=[];window.closeCount=0;window.aiRequests=[];
          window.fetch=async(url,options)=>{aiRequests.push(JSON.parse(options.body));
            if(window.deferAi)return new Promise(resolve=>{window.resolveAi=()=>resolve({ok:true,json:async()=>({ok:true,answer:'旧图回答'})});options.signal.addEventListener('abort',()=>window.aiAborted=true);});
            return {ok:true,json:async()=>({ok:true,answer:'先画 A、B，再从 A 向 B 连一条权值为 12 的有向边。'})};};
          window.openDrawing=(storageKey='drawings:user1',legacy=sample)=>{
            window.workspace=DMateDrawingWorkspace.mount(document.getElementById('mount'),{
              storageKey,legacyDocument:legacy,
              onUpload:async(blob,metadata)=>{if(window.uploadFailure)throw new Error(window.uploadFailure);uploads.push({type:blob.type,size:blob.size,metadata});},
              onClose:()=>closeCount++});};openDrawing();
        }''')
        page.wait_for_function('document.querySelector(".dge-overlay").dataset.geometryReady==="true"')
        yield page
        browser.close()


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


def test_drawing_upload_is_literal_text_and_guidance_uses_the_chat_plus_icon(drawing_page):
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
      reference.innerHTML='<div class="input-wrap"><div class="input"><div class="image-picker-wrap"><button id="imageBtn" type="button">上传图片</button></div></div></div>';
      document.body.append(reference);}''')
    chat_plus = page.locator('#imageBtn')
    for color in ('#3b82f6', '#14b8a6', '#8b5cf6'):
        page.evaluate('color=>document.body.style.setProperty("--accent",color)', color)
        expected = page.evaluate('color=>{const node=document.createElement("i");node.style.color=color;document.body.append(node);const rgb=getComputedStyle(node).color;node.remove();return rgb;}', color)
        assert button.evaluate('e=>getComputedStyle(e).backgroundColor') == expected
        assert guide.evaluate('e=>getComputedStyle(e).backgroundColor') == 'rgba(0, 0, 0, 0)'
        assert guide.evaluate('e=>getComputedStyle(e,"::before").maskImage') == chat_plus.evaluate('e=>getComputedStyle(e,"::before").maskImage')
        assert guide.evaluate('e=>getComputedStyle(e,"::before").backgroundColor') == chat_plus.evaluate('e=>getComputedStyle(e,"::before").backgroundColor')
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
    assert page.evaluate('workspace.getPages().length') == 1
    assert page.locator('.ddw-name').input_value() == active_name
    assert page.evaluate('workspace.getDocument().graphs[0].vertices.length') == 0
    assert page.locator('.ddw-history-item').count() == 1
    assert page.locator('.ddw-history-meta').count() == 0
    assert page.locator('.ddw-status').is_hidden()
    page.locator('.ddw-history-delete').click()
    assert page.evaluate('workspace.getPages()') == []
    assert page.evaluate('workspace.getDocument().graphs') == []
    assert page.locator('.ddw-name').input_value() == ''
    assert page.locator('.dge-overlay-node,.dge-overlay-edge').count() == 0
    assert page.locator('.ddw-history-list').inner_text() == '无'
    assert page.evaluate("JSON.parse(localStorage.getItem('drawings:user1'))") == {'version': 2, 'activeId': '', 'pages': []}
    page.evaluate('workspace.destroy();openDrawing()')
    assert page.evaluate('workspace.getPages()') == []
    assert page.evaluate('workspace.getDocument().graphs') == []
    assert page.locator('.ddw-name').input_value() == ''
    assert page.locator('.ddw-name').is_disabled()
    page.get_by_role('button', name='历史绘图', exact=True).click()
    assert page.locator('.ddw-history-list').inner_text() == '无'
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
