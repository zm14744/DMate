"""Standalone drawing fit uses painted graph bounds rather than its source page."""
import base64
import io
import os
from pathlib import Path
import shutil

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=[(1440, 900), (390, 844)])
def fit_page(request):
    executable = os.environ.get('DMATE_BROWSER_EXECUTABLE') or shutil.which('chromium')
    if not executable:
        pytest.skip('Chromium unavailable')
    playwright = pytest.importorskip('playwright.sync_api')
    with Image.new('RGB', (1000, 700), 'white') as image:
        stream = io.BytesIO()
        image.save(stream, format='PNG')
    url = 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()
    with playwright.sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=executable, headless=True)
        page = browser.new_page(viewport={'width': request.param[0], 'height': request.param[1]})
        page.set_default_timeout(7000)
        page.set_content('<main id="editor" style="max-width:1000px"></main>')
        page.add_style_tag(content=(ROOT / 'static/graph-editor.css').read_text())
        for name in ['graph-editor-model.js', 'graph-editor-format.js', 'graph-editor-overlay.js',
                     'graph-editor.js', 'drawing-export.js']:
            page.add_script_tag(content=(ROOT / 'static' / name).read_text())
        page.evaluate('''url=>{
          if(innerWidth<760)Object.defineProperty(navigator,'maxTouchPoints',{configurable:true,value:5});
          window.originalUrl=url;
          window.mountFit=graph=>{window.editor?.destroy?.();window.fitChanges=0;
            window.editor=DMateGraphEditor.mount(document.getElementById('editor'),{
              drawingOnly:true,originalUrl,document:{body_text:'',graphs:[graph]},onChange:()=>fitChanges++});
            window.fitOriginal=JSON.stringify(editor.getDocument());};
        }''', url)
        yield page
        browser.close()


def mount_graph(page, variant):
    if variant == 'empty':
        graph = {'id': 'G1', 'name': '空白页', 'directed': True, 'weighted': True,
                 'vertices': [], 'edges': []}
    else:
        a, b, apex, bend = ((.1, .15), (.25, .3), (.05, -.1), (.8, -.3)) if variant == 'asymmetric' else (
            (-2, 1.4), (-.5, 2.2), (-2.7, .4), (1.2, 3))
        graph = {'id': 'G1', 'name': '需要适应的绘图', 'directed': True, 'weighted': True,
                 'vertices': [
                     {'id': 'a', 'label': 'A long vertex label with all text visible', 'x': a[0], 'y': a[1]},
                     {'id': 'b', 'label': 'B another long vertex label', 'x': b[0], 'y': b[1]}],
                 'edges': [
                     {'id': 'loop', 'from': 'a', 'to': 'a', 'direction': 'forward', 'weight': 12345,
                      'edge_label': 'adjusted loop', 'path': [a, apex, a]},
                     {'id': 'curve1', 'from': 'a', 'to': 'b', 'direction': 'forward', 'weight': 7},
                     {'id': 'curve2', 'from': 'a', 'to': 'b', 'direction': 'forward', 'weight': 8},
                     {'id': 'bent', 'from': 'a', 'to': 'b', 'direction': 'forward', 'weight': 98765,
                      'edge_label': 'outer edge label', 'path': [a, bend, b]}]}
    page.evaluate('mountFit', graph)
    page.wait_for_function('document.querySelector(".dge-overlay").dataset.geometryReady==="true"')
    page.locator('.dge-tool-palette').evaluate('e=>e.open=false')


def painted_snapshot(page):
    return page.evaluate('''()=>{
      const viewport=document.querySelector('.dge-overlay-viewport'),vb=viewport.getBoundingClientRect(),boxes=[];
      const add=(x,y,width,height)=>boxes.push({x,y,width,height});
      for(const node of document.querySelectorAll('.dge-overlay-stroke,.dge-overlay-contrast-halo,.dge-overlay-dot,.dge-overlay-label')){
        const box=node.getBBox(),matrix=node.getScreenCTM(),style=getComputedStyle(node),
          padding=style.stroke==='none'?0:parseFloat(style.strokeWidth)*Math.hypot(matrix.a,matrix.b)/2,
          points=[[box.x,box.y],[box.x+box.width,box.y+box.height]].map(p=>new DOMPoint(...p).matrixTransform(matrix));
        add(points[0].x-padding,points[0].y-padding,points[1].x-points[0].x+2*padding,points[1].y-points[0].y+2*padding);
        // SVG getBBox() omits markers. Reserve their actual screen-sized
        // arrow width as well, without counting transparent pointer targets.
        if(node.matches('.dge-overlay-stroke[marker-end]')){
          const end=node.getPointAtLength(node.getTotalLength()),p=new DOMPoint(end.x,end.y).matrixTransform(matrix);
          add(p.x-8,p.y-8,16,16);
        }
      }
      const left=Math.min(...boxes.map(b=>b.x)),top=Math.min(...boxes.map(b=>b.y)),
        right=Math.max(...boxes.map(b=>b.x+b.width)),bottom=Math.max(...boxes.map(b=>b.y+b.height));
      return {paint:{x:left,y:top,width:right-left,height:bottom-top},
        viewport:{x:vb.x+viewport.clientLeft,y:vb.y+viewport.clientTop,width:viewport.clientWidth,height:viewport.clientHeight},
        zoom:document.querySelector('.dge-overlay-zoom').textContent,
        scroll:[viewport.scrollLeft,viewport.scrollTop],boxes};
    }''')


def assert_graph_fitted(snapshot):
    paint, view = snapshot['paint'], snapshot['viewport']
    for box in snapshot['boxes']:
        assert box['x'] >= view['x'] - 1
        assert box['y'] >= view['y'] - 1
        assert box['x'] + box['width'] <= view['x'] + view['width'] + 1
        assert box['y'] + box['height'] <= view['y'] + view['height'] + 1
    assert paint['x'] + paint['width'] / 2 == pytest.approx(view['x'] + view['width'] / 2, abs=3)
    assert paint['y'] + paint['height'] / 2 == pytest.approx(view['y'] + view['height'] / 2, abs=3)
    assert max(paint['width'] / view['width'], paint['height'] / view['height']) > .7


def pan_canvas(page):
    viewport = page.locator('.dge-overlay-viewport').bounding_box()
    x, y = viewport['x'] + viewport['width'] / 2, viewport['y'] + viewport['height'] * .7
    page.keyboard.down('Shift')
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x - 73, y + 47, steps=8)
    page.mouse.up()
    page.keyboard.up('Shift')


@pytest.mark.parametrize('variant', ['asymmetric', 'outside'])
def test_fit_centres_all_painted_graph_geometry_and_repeats_after_zoom_pan(fit_page, variant):
    page = fit_page
    mount_graph(page, variant)
    page.get_by_role('button', name='适应', exact=True).click()
    fitted = painted_snapshot(page)
    assert_graph_fitted(fitted)
    assert 'C ' in page.locator('[data-edge-id="loop"] .dge-overlay-stroke').get_attribute('d')
    assert 'Q ' in page.locator('[data-edge-id="curve1"] .dge-overlay-stroke').get_attribute('d')
    for _ in range(3):
        page.get_by_role('button', name='放大原图', exact=True).click()
    pan_canvas(page)
    displaced = painted_snapshot(page)
    assert displaced['zoom'] != fitted['zoom']
    assert displaced['paint'] != fitted['paint']
    page.get_by_role('button', name='适应', exact=True).click()
    restored = painted_snapshot(page)
    assert_graph_fitted(restored)
    for key in fitted['paint']:
        assert restored['paint'][key] == pytest.approx(fitted['paint'][key], abs=2)
    page.get_by_role('button', name='适应', exact=True).click()
    repeated = painted_snapshot(page)
    assert_graph_fitted(repeated)
    assert repeated['paint'] == pytest.approx(restored['paint'], abs=1)
    assert page.evaluate('JSON.stringify(editor.getDocument())===fitOriginal&&fitChanges===0')
    exported = page.evaluate('''async()=>{
      const svg=editor.getDrawingSvg(),blob=await DMateDrawingExport.pngBlob(svg),bitmap=await createImageBitmap(blob),
        document=DMateDrawingExport.documentForImage(editor.getDocument(),svg);
      return {type:blob.type,size:blob.size,width:bitmap.width,height:bitmap.height,
        vertices:document.graphs[0].vertices.map(v=>[v.x,v.y]),paths:document.graphs[0].edges.flatMap(e=>e.path||[]),
        edges:document.graphs[0].edges.length,controls:svg.querySelectorAll('.dge-overlay-hit,.dge-overlay-node-hit,.dge-overlay-handle').length};
    }''')
    assert exported['type'] == 'image/png' and exported['size'] > 300
    assert 64 <= exported['width'] <= 4096 and 64 <= exported['height'] <= 4096
    assert exported['edges'] == 4 and exported['controls'] == 0
    assert all(0 <= value <= 1 for point in exported['vertices'] + exported['paths'] for value in point)
    assert page.evaluate('JSON.stringify(editor.getDocument())===fitOriginal&&fitChanges===0')


def test_empty_drawing_fit_restores_the_centred_blank_page_without_editing(fit_page):
    page = fit_page
    mount_graph(page, 'empty')
    for _ in range(3):
        page.get_by_role('button', name='放大原图', exact=True).click()
    pan_canvas(page)
    page.get_by_role('button', name='适应', exact=True).click()
    snapshot = page.locator('.dge-overlay-viewport').evaluate('''e=>{
      const view=e.getBoundingClientRect(),image=e.querySelector('img').getBoundingClientRect();return {
        view:{x:view.x+e.clientLeft,y:view.y+e.clientTop,width:e.clientWidth,height:e.clientHeight},
        image:{x:image.x,y:image.y,width:image.width,height:image.height}};}''')
    view, image = snapshot['view'], snapshot['image']
    assert 100 < image['width'] <= view['width'] + 1
    assert 100 < image['height'] <= view['height'] + 1
    for axis, size in [('x', 'width'), ('y', 'height')]:
        assert image[axis] + image[size] / 2 == pytest.approx(view[axis] + view[size] / 2, abs=3)
    assert page.locator('.dge-overlay-node,.dge-overlay-edge').count() == 0
    assert page.evaluate('JSON.stringify(editor.getDocument())===fitOriginal&&fitChanges===0')
