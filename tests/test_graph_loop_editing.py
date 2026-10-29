"""Editable self-loops and forgiving edge endpoints use actual browser geometry."""
import base64
from collections import deque
import io
import json
import os
from pathlib import Path
import shutil

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=[(1440, 900), (390, 844)])
def loop_page(request):
    executable = os.environ.get('DMATE_BROWSER_EXECUTABLE') or shutil.which('chromium')
    if not executable:
        pytest.skip('Chromium unavailable')
    pw = pytest.importorskip('playwright.sync_api')
    with Image.new('RGB', (1000, 700), 'white') as picture:
        stream = io.BytesIO()
        picture.save(stream, format='PNG')
    url = 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()
    with pw.sync_playwright() as engine:
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
          window.originalUrl=url;window.saved=[];
          window.sample={body_text:'',graphs:[{id:'G1',name:'图',directed:true,weighted:true,
            vertices:[{id:'a',label:'A',x:.42,y:.62},{id:'b',label:'B',x:.68,y:.74}],
            edges:[{id:'loop',from:'a',to:'a',direction:'forward',weight:4},
              {id:'ab',from:'a',to:'b',direction:'forward',weight:2}]}]};
          window.openEditor=value=>{window.editor?.destroy?.();window.editor=DMateGraphEditor.mount(document.getElementById('editor'),{
            drawingOnly:true,originalUrl,document:value||sample,onConfirm:async doc=>saved.push(doc)});};
          openEditor();
        }''', url)
        page.wait_for_function('document.querySelector(".dge-overlay").dataset.geometryReady==="true"')
        yield page
        browser.close()


def node_center(page, node):
    return page.locator('[data-vertex-id="' + node + '"] .dge-overlay-dot').evaluate('''e=>{
      const p=new DOMPoint(+e.getAttribute('cx'),+e.getAttribute('cy')).matrixTransform(e.getScreenCTM());return [p.x,p.y];}''')


def path_point(page, edge, part=.5):
    return page.locator('[data-edge-id="' + edge + '"] .dge-overlay-hit').evaluate('''(e,t)=>{
      const p=e.getPointAtLength(e.getTotalLength()*t),v=new DOMPoint(p.x,p.y).matrixTransform(e.getScreenCTM());return [v.x,v.y];}''', part)


def drag_handle(page, edge, dx, dy):
    page.mouse.click(*path_point(page, edge))
    handle = page.locator('[data-handle-id="' + edge + '"]')
    assert handle.is_visible()
    covered = handle.evaluate('''e=>{const b=e.getBoundingClientRect(),
      top=document.elementFromPoint(b.x+b.width/2,b.y+b.height/2);return !!top?.closest('.dge-selection-panel');}''')
    if covered:
        page.get_by_role('button', name='关闭属性', exact=True).click()
        assert handle.is_visible(), 'Closing the property popup must retain its selected shape handle.'
    box = handle.bounding_box()
    start = [box['x'] + box['width'] / 2, box['y'] + box['height'] / 2]
    page.mouse.move(*start)
    page.mouse.down()
    page.mouse.move(start[0] + dx, start[1] + dy, steps=8)
    page.mouse.up()


def test_self_loop_can_resize_rotate_save_reopen_and_follow_its_vertex(loop_page):
    page = loop_page
    old = page.locator('[data-edge-id="loop"] .dge-overlay-hit').get_attribute('d')
    drag_handle(page, 'loop', 35, -24)
    edge = page.evaluate('editor.getDocument().graphs[0].edges.find(e=>e.id==="loop")')
    assert edge['from'] == edge['to'] == 'a'
    assert edge['direction'] == 'forward' and edge['weight'] == 4
    assert len(edge['path']) == 3 and edge['path'][0] == edge['path'][-1]
    assert page.locator('[data-edge-id="loop"] .dge-overlay-hit').get_attribute('d') != old
    page.get_by_role('button', name='保存绘图', exact=True).click()
    page.wait_for_function('saved.length===1')
    saved = page.evaluate('structuredClone(saved[0])')
    page.evaluate('openEditor(saved[0])')
    page.wait_for_function('document.querySelector(".dge-overlay").dataset.geometryReady==="true"')
    assert page.evaluate('editor.getDocument().graphs[0].edges.find(e=>e.id==="loop").path') == edge['path']
    page.evaluate('''()=>{const v=editor.getDocument().graphs[0].vertices[0];
      editor.model.moveVertex('G1','a',v.x+.04,v.y+.03);}''')
    page.get_by_role('button', name='选择 / 移动', exact=True).click()
    moved = page.evaluate('editor.getDocument().graphs[0].edges.find(e=>e.id==="loop").path')
    for before, after in zip(edge['path'], moved):
        assert after == pytest.approx([before[0] + .04, before[1] + .03])
    assert saved['graphs'][0]['edges'][0]['path'] == edge['path']
    exported = page.evaluate('''async()=>{const svg=editor.getDrawingSvg(),blob=await DMateDrawingExport.pngBlob(svg),
      document=DMateDrawingExport.documentForImage(editor.getDocument(),svg),graph=document.graphs[0];return {
        size:blob.size,type:blob.type,document,loop:graph.edges.find(e=>e.id==='loop'),
        handles:svg.querySelectorAll('.dge-overlay-handle').length,
        ink:svg.querySelector('[data-edge-id="loop"] .dge-overlay-stroke')?.getAttribute('d')||svg.querySelector('.dge-overlay-edge .dge-overlay-stroke').getAttribute('d')};}''')
    assert exported['type'] == 'image/png' and exported['size'] > 300
    assert exported['handles'] == 0 and len(exported['ink']) > 40
    assert exported['loop']['from'] == exported['loop']['to'] == 'a'
    assert len(exported['loop']['path']) == 3
    assert all(0 <= value <= 1 for point in exported['loop']['path'] for value in point)
    Path('/tmp/dmate-loop-export-document.json').write_text(json.dumps(exported['document']))


def test_adjusting_one_loop_does_not_change_another_loop(loop_page):
    page = loop_page
    page.evaluate('''()=>{window.otherLoop=editor.model.addEdge('G1',{from:'a',to:'a',direction:'forward',weight:9});}''')
    page.get_by_role('button', name='选择 / 移动', exact=True).click()
    before = page.evaluate('editor.getDocument().graphs[0].edges.find(e=>e.id===otherLoop)')
    shape = page.locator('[data-edge-id="' + before['id'] + '"] .dge-overlay-hit').get_attribute('d')
    assert shape != page.locator('[data-edge-id="loop"] .dge-overlay-hit').get_attribute('d')
    drag_handle(page, 'loop', 24, -18)
    assert page.evaluate('editor.getDocument().graphs[0].edges.find(e=>e.id===otherLoop)') == before
    assert page.locator('[data-edge-id="' + before['id'] + '"] .dge-overlay-hit').get_attribute('d') == shape


@pytest.mark.parametrize('zoom_steps', [('缩小原图', 3), ('放大原图', 3)])
def test_edge_add_uses_large_screen_targets_without_enlarging_visible_dots(loop_page, zoom_steps):
    page = loop_page
    page.evaluate('''()=>{const value=structuredClone(sample);value.graphs[0].edges=[];openEditor(value);}''')
    page.wait_for_function('document.querySelector(".dge-overlay").dataset.geometryReady==="true"')
    for _ in range(zoom_steps[1]):
        page.get_by_role('button', name=zoom_steps[0], exact=True).click()
    page.get_by_role('button', name='添加边', exact=True).click()
    page.locator('.dge-tool-palette > summary').click()
    before = page.locator('[data-vertex-id="a"] .dge-overlay-dot').bounding_box()
    for node in ['a', 'b']:
        x, y = node_center(page, node)
        page.mouse.click(x, y - 22)
    edges = page.evaluate('editor.getDocument().graphs[0].edges')
    assert len(edges) == 1 and (edges[0]['from'], edges[0]['to']) == ('a', 'b')
    after = page.locator('[data-vertex-id="a"] .dge-overlay-dot').bounding_box()
    assert after['width'] == pytest.approx(before['width'], abs=.1)
    # The same generous endpoint selection can create a loop intentionally.
    x, y = node_center(page, 'a')
    page.mouse.click(x, y - 22)
    page.mouse.click(x, y - 22)
    edges = page.evaluate('editor.getDocument().graphs[0].edges')
    assert len(edges) == 2 and edges[-1]['from'] == edges[-1]['to'] == 'a'


def test_overlapping_endpoint_targets_choose_the_nearest_vertex(loop_page):
    page = loop_page
    page.evaluate('''()=>{const image=document.querySelector('.dge-overlay-image').getBoundingClientRect(),value=structuredClone(sample);
      value.graphs[0].vertices[1].x=value.graphs[0].vertices[0].x+40/image.width;
      value.graphs[0].vertices[1].y=value.graphs[0].vertices[0].y;
      value.graphs[0].edges=[];openEditor(value);}''')
    page.wait_for_function('document.querySelector(".dge-overlay").dataset.geometryReady==="true"')
    page.get_by_role('button', name='添加边', exact=True).click()
    page.locator('.dge-tool-palette > summary').click()
    a, b = node_center(page, 'a'), node_center(page, 'b')
    page.mouse.click(a[0] + 18, a[1])
    page.mouse.click(*b)
    edges = page.evaluate('editor.getDocument().graphs[0].edges')
    assert len(edges) == 1 and (edges[0]['from'], edges[0]['to']) == ('a', 'b')


def test_solid_ink_is_a_continuous_path_with_one_final_arrow(loop_page):
    page = loop_page
    result = page.evaluate('''()=>[...document.querySelectorAll('.dge-overlay-edge')].map(group=>{
      const ink=[...group.querySelectorAll('.dge-overlay-stroke')];return {
        count:ink.length,arrows:ink.filter(e=>e.getAttribute('marker-end')).length,
        joins:ink.map(e=>getComputedStyle(e).strokeLinejoin),caps:ink.map(e=>getComputedStyle(e).strokeLinecap),
        dashes:ink.map(e=>getComputedStyle(e).strokeDasharray),length:ink.reduce((n,e)=>n+e.getTotalLength(),0)};})''')
    assert len(result) == 2
    for edge in result:
        assert edge['count'] == 1 and edge['arrows'] == 1
        assert edge['joins'] == edge['caps'] == ['round']
        assert edge['dashes'] == ['none'] and edge['length'] > 50


def test_both_loop_arms_and_straight_edge_are_visibly_connected_to_the_vertex(loop_page):
    page = loop_page
    # Test the actual painted pixels, without labels making unrelated ink
    # look connected. Restrict traversal to the vertex neighbourhood so the
    # two loop arms cannot reach each other by travelling around the apex.
    page.add_style_tag(content='.dge-overlay-label { visibility:hidden!important; }')

    def assert_connected():
        geometry = page.evaluate('''()=>{
          const dot=document.querySelector('[data-vertex-id="a"] .dge-overlay-dot'),
            screen=p=>new DOMPoint(p.x,p.y).matrixTransform(dot.getScreenCTM()),
            center=screen({x:+dot.getAttribute('cx'),y:+dot.getAttribute('cy')}),targets=[];
          for(const [id,end]of [['loop',false],['loop',true],['ab',false]]){
            const path=document.querySelector('[data-edge-id="'+id+'"] .dge-overlay-stroke'),
              matrix=path.getScreenCTM(),scale=Math.hypot(matrix.a,matrix.b),
              length=path.getTotalLength(),point=path.getPointAtLength(end?length-13/scale:13/scale),
              target=new DOMPoint(point.x,point.y).matrixTransform(matrix);
            targets.push({name:id+(end?'-return':'-start'),x:target.x,y:target.y});
          }
          return {center:{x:center.x,y:center.y},targets};
        }''')
        center = geometry['center']
        left, top = int(center['x']) - 28, int(center['y']) - 28
        png = page.screenshot(clip={'x': left, 'y': top, 'width': 56, 'height': 56})
        image = Image.open(io.BytesIO(png)).convert('RGB')
        cx, cy = center['x'] - left, center['y'] - top
        dark = {(x, y) for y in range(56) for x in range(56)
                if (x - cx) ** 2 + (y - cy) ** 2 < 23 ** 2
                and max(image.getpixel((x, y))) < 160}
        origin = (round(cx), round(cy))
        assert origin in dark, 'The visible vertex must remain filled.'
        connected, pending = {origin}, deque([origin])
        while pending:
            x, y = pending.popleft()
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    neighbour = (x + dx, y + dy)
                    if neighbour in dark and neighbour not in connected:
                        connected.add(neighbour)
                        pending.append(neighbour)
        for target in geometry['targets']:
            x, y = round(target['x'] - left), round(target['y'] - top)
            nearby = {(x + dx, y + dy) for dx in [-1, 0, 1] for dy in [-1, 0, 1]}
            assert nearby & dark, target['name'] + ' must be painted in the crop.'
            assert nearby & connected, target['name'] + ' has a visible white gap at the vertex.'

    assert_connected()
    drag_handle(page, 'loop', 35, -24)
    close = page.get_by_role('button', name='关闭属性', exact=True)
    if close.is_visible():
        close.click()
    assert_connected()


def test_saved_loop_apex_outside_old_canvas_remains_in_the_scrollable_world(loop_page):
    page = loop_page
    before = node_center(page, 'a')
    old = page.locator('.dge-overlay-viewport').evaluate('e=>[e.scrollWidth,e.scrollHeight]')
    page.evaluate('''()=>{const a=editor.getDocument().graphs[0].vertices.find(v=>v.id==='a');
      editor.model.setEdgePath('G1','loop',[[a.x,a.y],[2,-1],[a.x,a.y]]);editor.refresh();}''')
    page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>resolve()))')
    after = node_center(page, 'a')
    assert after == pytest.approx(before, abs=1)
    result = page.locator('.dge-overlay-svg').evaluate('''e=>{
      const box=e.viewBox.baseVal,viewport=e.closest('.dge-overlay-viewport');return {
        box:[box.x,box.y,box.width,box.height],size:[viewport.scrollWidth,viewport.scrollHeight]};}''')
    x, y, width, height = result['box']
    assert x <= 2000 <= x + width
    assert y <= -700 <= y + height
    assert result['size'][0] > old[0] and result['size'][1] > old[1]
    assert page.evaluate('editor.getDocument().graphs[0].edges.find(e=>e.id==="loop").path[1]') == [2, -1]
