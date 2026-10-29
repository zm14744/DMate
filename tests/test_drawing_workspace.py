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
            if(window.deferAi)return new Promise(resolve=>window.resolveAi=()=>resolve({ok:true,json:async()=>({ok:true,answer:'旧图回答'})}));
            return {ok:true,json:async()=>({ok:true,answer:'先画 A、B，再从 A 向 B 连一条权值为 12 的有向边。'})};};
          window.openDrawing=(storageKey='drawings:user1',legacy=sample)=>{
            window.workspace=DMateDrawingWorkspace.mount(document.getElementById('mount'),{
              storageKey,legacyDocument:legacy,
              onUpload:async(blob,metadata)=>{uploads.push({type:blob.type,size:blob.size,metadata});},
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
    page.get_by_role('button', name='历史绘图', exact=True).click()
    page.get_by_role('button', name='带权图', exact=True).click()
    assert page.evaluate('workspace.getDocument().graphs[0].edges[0].weight') == 12
    page.evaluate("workspace.destroy();openDrawing('drawings:user1',null)")
    assert page.locator('.ddw-name').input_value() == '带权图'
    assert page.evaluate('workspace.getPages().length') == 2
    page.evaluate("workspace.destroy();openDrawing('drawings:user2',null)")
    assert page.evaluate('workspace.getDocument().graphs[0].vertices.length') == 0
    assert page.evaluate('workspace.getPages().length') == 1
    assert page.evaluate("JSON.parse(localStorage.getItem('drawings:user1')).pages.length") == 2


def test_guidance_uses_snapshot_and_does_not_modify_drawing(drawing_page):
    page = drawing_page
    page.get_by_role('button', name='AI 回答', exact=True).click()
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
    page.get_by_role('button', name='新建空白页', exact=True).click()
    page.evaluate('resolveAi()')
    page.wait_for_timeout(50)
    assert '旧图回答' not in page.locator('.ddw-ai-answer').inner_text()
    assert page.get_by_role('button', name='请求 AI 指导', exact=True).is_enabled()


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
    page.get_by_role('button', name='上传到对话', exact=True).click()
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
    page.get_by_role('button', name='AI 回答', exact=True).click()
    assert page.get_by_label('绘图指导要求（可选）').get_attribute('maxlength') == '2000'
    page.get_by_label('绘图指导要求（可选）').fill('画' * 2000)
    page.get_by_role('button', name='请求 AI 指导', exact=True).click()
    page.wait_for_function('aiRequests.length===1')
    assert len(page.evaluate('aiRequests[0].requirement')) == 2000


def test_drawing_upload_is_an_accessible_plus_with_live_theme_color(drawing_page):
    page = drawing_page
    button = page.get_by_role('button', name='上传到对话', exact=True)
    assert button.inner_text() == ''
    assert button.get_attribute('title') == '上传到对话'
    box = button.bounding_box()
    assert box['width'] == pytest.approx(box['height'], abs=1)
    assert page.locator('.ddw-page-actions').bounding_box()['x'] <= box['x']
    for color in ('#3b82f6', '#14b8a6', '#8b5cf6'):
        page.evaluate('color=>document.body.style.setProperty("--accent",color)', color)
        expected = page.evaluate('color=>{const node=document.createElement("i");node.style.color=color;document.body.append(node);const rgb=getComputedStyle(node).color;node.remove();return rgb;}', color)
        assert button.evaluate('e=>getComputedStyle(e).backgroundColor') == expected
        assert button.evaluate('e=>getComputedStyle(e,"::before").backgroundColor') == 'rgb(255, 255, 255)'
        assert button.evaluate('e=>getComputedStyle(e,"::before").maskImage') != 'none'
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


def test_drawing_panels_use_one_nonoverlapping_toolbar_and_red_closes(drawing_page):
    page = drawing_page
    rail = page.get_by_role('toolbar', name='绘图面板', exact=True)
    controls = rail.get_by_role('button')
    assert controls.count() == 3
    boxes = [controls.nth(i).bounding_box() for i in range(3)]
    assert all(box is not None for box in boxes)
    for index, box in enumerate(boxes):
        for other in boxes[index + 1:]:
            assert box['y'] + box['height'] <= other['y'] or other['y'] + other['height'] <= box['y']
    assert page.locator('.dge-floating-actions > details > summary').evaluate_all(
        'nodes=>nodes.every(n=>getComputedStyle(n).display==="none")')
    for label, close in [('绘图设置', '关闭绘图设置'), ('图形信息', '关闭图形信息'),
                         ('历史绘图', '关闭历史绘图'), ('AI 回答', '关闭 AI 回答')]:
        page.get_by_role('button', name=label, exact=True).click()
        button = page.get_by_role('button', name=close, exact=True)
        assert button.is_visible()
        assert rail.is_hidden()
        button.focus()
        style = button.evaluate('e=>{const s=getComputedStyle(e);return {background:s.backgroundColor,radius:s.borderRadius,width:s.width,height:s.height,outline:s.outlineStyle,shadow:s.boxShadow}}')
        assert style['background'] == 'rgb(239, 68, 68)'
        assert style['radius'] == '50%' and style['width'] == style['height']
        assert style['outline'] == 'none' and style['shadow'] == 'none'
        if label == '历史绘图':
            assert '绘图保存在此设备' not in page.locator('.ddw-side-panel').inner_text()
        if label == 'AI 回答':
            assert 'AI 会根据当前绘图' not in page.locator('.ddw-side-panel').inner_text()
        button.click()
        assert rail.is_visible()
    assert '绘图保存在此设备' not in page.locator('.dmate-drawing-workspace').inner_text()
    assert 'AI 会根据当前绘图' not in page.locator('.dmate-drawing-workspace').inner_text()
    page.screenshot(path='/tmp/dmate-drawing-unified-rail-'+('mobile' if page.viewport_size['width'] < 760 else 'desktop')+'.png')


def test_history_is_next_to_new_page_in_top_actions_and_opens_above_canvas(drawing_page):
    page = drawing_page
    actions = page.locator('.ddw-page-actions')
    assert actions.get_by_role('button').all_text_contents() == ['新建空白页', '历史绘图', '导出图片', '']
    assert actions.get_by_role('button', name='上传到对话', exact=True).count() == 1
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
    page.get_by_role('button', name='关闭历史绘图', exact=True).click()
    assert history.is_visible() and history.get_attribute('aria-expanded') == 'false'


def test_drawing_settings_remain_open_across_editor_redraw(drawing_page):
    page = drawing_page
    page.get_by_role('button', name='绘图设置', exact=True).click()
    page.get_by_label('绘图方向', exact=True).select_option('no')
    page.get_by_label('绘图权值', exact=True).select_option('no')
    page.get_by_role('button', name='关闭绘图设置', exact=True).click()
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
    page.get_by_role('button', name='关闭绘图设置', exact=True).click()
    page.get_by_role('button', name='图形信息', exact=True).click()
    assert '画页甲' in page.locator('.dge-review-type').inner_text()
    assert page.locator('.dge-overlay-image').bounding_box() == pytest.approx(before, abs=1)
    page.get_by_role('button', name='关闭图形信息', exact=True).click()
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
    page.get_by_role('button', name='AI 回答', exact=True).click()
    assert page.locator('.ddw-ai-answer').text_content() == ''
    page.get_by_role('button', name='请求 AI 指导', exact=True).click()
    page.wait_for_function('richRenderCalls.length===1')
    assert page.locator('.ddw-ai-answer.wrong-answer-inner p').count() == 1
    page.get_by_label('绘图指导要求（可选）').fill('换一种画法')
    assert page.locator('.ddw-ai-answer').text_content() == ''
