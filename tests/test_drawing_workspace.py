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
        page.wait_for_function('document.querySelector(".dge-overlay-image").naturalWidth===1000')
        yield page
        browser.close()


def test_legacy_saved_pages_new_page_and_account_scope(drawing_page):
    page = drawing_page
    assert page.locator('.ddw-name').input_value() == '我的图形'
    page.locator('.ddw-name').fill('带权图')
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
