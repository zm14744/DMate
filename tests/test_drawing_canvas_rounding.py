"""All four painted canvas corners stay round beside real native scrollbars."""
import io
import os
from pathlib import Path
import shutil

import pytest

from test_drawing_workspace import use_real_dialog_and_template_styles

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=[(1440, 900), (390, 844)])
def canvas_page(request):
    executable = os.environ.get('DMATE_BROWSER_EXECUTABLE') or shutil.which('chromium')
    if not executable:
        pytest.skip('Chromium unavailable')
    browser_api = pytest.importorskip('playwright.sync_api')
    with browser_api.sync_playwright() as runtime:
        # Playwright normally hides native scrollbars. Keeping them visible is
        # essential: the white content corners are inside their two gutters.
        browser = runtime.chromium.launch(executable_path=executable, headless=True,
                                          ignore_default_args=['--hide-scrollbars'])
        page = browser.new_page(viewport={'width': request.param[0], 'height': request.param[1]})
        page.route('**/*', lambda route: route.fulfill(body='<html></html>', content_type='text/html'))
        page.goto('https://dmate.test/')
        page.set_content('<div id="mount" style="height:95dvh"></div>')
        for name in ['graph-editor.css', 'drawing-workspace.css']:
            page.add_style_tag(content=(ROOT / 'static' / name).read_text())
        for name in ['graph-editor-model.js', 'graph-editor-format.js', 'graph-editor-overlay.js',
                     'graph-editor.js', 'drawing-export.js', 'drawing-workspace.js']:
            page.add_script_tag(content=(ROOT / 'static' / name).read_text())
        page.evaluate('''()=>{
          window.sample={body_text:'',graphs:[{id:'G1',name:'圆角画板',directed:false,weighted:false,
            vertices:[{id:'a',label:'A',x:.3,y:.3},{id:'b',label:'B',x:.7,y:.7}],
            edges:[{id:'ab',from:'a',to:'b',direction:'undirected',path:[[.3,.3],[.7,.7]]}]}]};
          window.drawingMount=document.getElementById('mount');
          window.openDrawing=(storageKey='rounding',legacy=sample)=>{
            window.workspace=DMateDrawingWorkspace.mount(drawingMount,{storageKey,legacyDocument:legacy,
              onExport:async blob=>{window.exportedRoundImage={type:blob.type,size:blob.size};}});
          };openDrawing();
        }''')
        page.wait_for_selector('.dge-overlay[data-geometry-ready="true"]')
        yield page
        browser.close()


def assert_four_visible_corners(page, *, gutters):
    page.wait_for_function('''()=>{
      const v=document.querySelector('.dge-overlay-viewport'),s=v.querySelector('.dge-overlay-stage');
      return getComputedStyle(s).clipPath!=='none';
    }''')
    result = page.locator('.dge-overlay-viewport').evaluate('''v=>{
      const r=v.getBoundingClientRect(),x=r.left+v.clientLeft,y=r.top+v.clientTop,
        w=v.clientWidth,h=v.clientHeight;
      const points=[[x+1,y+1],[x+w-2,y+1],[x+1,y+h-2],[x+w-2,y+h-2]];
      return {x,y,w,h,points,gutters:[v.offsetWidth-v.clientWidth,v.offsetHeight-v.clientHeight],
        hits:points.map(([a,b])=>!!document.elementFromPoint(a,b)?.closest('.dge-overlay-stage'))};
    }''')
    assert result['hits'] == [False] * 4, result
    if gutters:
        assert min(result['gutters']) >= 14, result
    image_module = pytest.importorskip('PIL.Image')
    image = image_module.open(io.BytesIO(page.screenshot()))
    # Paint, not just CSS radii or hit testing: the four cut corners must reveal
    # the darkened dialog, while the white stage remains visible along its edge.
    for x, y in result['points']:
        pixel = image.getpixel((round(x), round(y)))[:3]
        assert max(abs(channel - 255) for channel in pixel) >= 35, (result, pixel)
    white = image.getpixel((round(result['x'] + result['w'] / 2), round(result['y'] + 3)))[:3]
    assert min(white) >= 245, (result, white)


@pytest.mark.parametrize('theme', ['light', 'dark', 'navy'])
def test_native_gutters_keep_all_client_corners_round_while_zooming_and_scrolling(canvas_page, theme):
    page = canvas_page
    use_real_dialog_and_template_styles(page, theme)
    page.add_style_tag(content='''.ddw-editor .dge-overlay-viewport{
      overflow:scroll!important;scrollbar-width:auto!important;scrollbar-gutter:stable both-edges!important}
      .ddw-editor .dge-overlay-viewport::-webkit-scrollbar{display:block!important;width:16px!important;height:16px!important}''')
    page.wait_for_function('getComputedStyle(document.querySelector(".dge-overlay-stage")).clipPath!=="none"')
    document = page.evaluate('workspace.getDocument()')
    for position in ['initial', 'middle', 'end']:
        if position != 'initial':
            for _ in range(2):
                page.get_by_role('button', name='放大原图', exact=True).click()
            page.locator('.dge-overlay-viewport').evaluate('''(v,position)=>{
              v.scrollTop=position==='end'?v.scrollHeight:v.scrollHeight/3;
              v.scrollLeft=position==='end'?v.scrollWidth:v.scrollWidth/3;
            }''', position)
        page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        assert_four_visible_corners(page, gutters=True)
        assert page.evaluate('workspace.getDocument()') == document
    if theme == 'dark':
        # Some platforms place a native vertical scrollbar on the left in RTL.
        # clientLeft includes that gutter; the visible canvas still has four cuts.
        page.locator('.dge-overlay-viewport').evaluate('''v=>{
          v.style.direction='rtl';v.scrollLeft=-v.scrollWidth/3;v.scrollTop=v.scrollHeight/3;
        }''')
        page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        assert_four_visible_corners(page, gutters=True)
    page.screenshot(path=f'/tmp/dmate-four-rounded-corners-{theme}-{page.viewport_size["width"]}.png')


def test_overlay_scrollbars_resize_and_export_keep_the_same_document(canvas_page):
    page = canvas_page
    use_real_dialog_and_template_styles(page, 'dark')
    page.add_style_tag(content='''.ddw-editor .dge-overlay-viewport{scrollbar-width:none!important;scrollbar-gutter:auto!important}
      .ddw-editor .dge-overlay-viewport::-webkit-scrollbar{display:none!important}''')
    document = page.evaluate('workspace.getDocument()')
    before = page.locator('.dge-overlay-stage').bounding_box()['width']
    for _ in range(4):
        page.get_by_role('button', name='放大原图', exact=True).click()
    page.locator('.dge-overlay-viewport').evaluate('v=>{v.scrollTop=v.scrollHeight;v.scrollLeft=v.scrollWidth}')
    page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
    assert_four_visible_corners(page, gutters=False)
    size = page.viewport_size
    page.set_viewport_size({'width': max(320, size['width'] - 50), 'height': size['height'] - 50})
    page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
    assert_four_visible_corners(page, gutters=False)
    assert page.evaluate('workspace.getDocument()') == document
    assert page.locator('.dge-overlay-stage').bounding_box()['width'] > before * 1.5
    # Inspect the real SVG passed to PNG export. The viewport's display clip
    # must not enter it, even when the camera is panned away from the drawing.
    page.evaluate('''()=>{
      const png=DMateDrawingExport.pngBlob;
      DMateDrawingExport.pngBlob=svg=>{window.exportedRoundSvg=svg.outerHTML;return png(svg);};
    }''')
    page.get_by_role('button', name='导出图片', exact=True).click()
    page.wait_for_function('typeof exportedRoundSvg==="string"&&!!window.exportedRoundImage')
    assert page.evaluate('exportedRoundImage.type') == 'image/png'
    assert page.evaluate('exportedRoundImage.size') > 100
    assert page.evaluate('''()=>{
      const output=new DOMParser().parseFromString(exportedRoundSvg,'image/svg+xml').documentElement;
      return !output.hasAttribute('clip-path')&&!output.style.clipPath&&output.querySelectorAll('.dge-overlay-node').length===2;
    }''')
