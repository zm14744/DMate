"""Real arbitrary-border drags and continuous control-point ink in Chromium."""
import math

import pytest

from test_graph_elastic_regions import region, set_regions
from test_scan_drawing_separation import scan_page
from test_graph_overlay import canvas_page, tool


@pytest.mark.parametrize('edge_index', [0, 1, 2, 3, 4])
def test_every_outline_segment_grabs_outside_thin_stroke_without_remounting(scan_page, edge_index):
    page = scan_page
    polygon = [[.2, .25], [.45, .15], [.78, .3], [.7, .78], [.25, .8]]
    set_regions(page)
    # Keep all vertices well apart: the grabbed point is in a segment's middle,
    # including diagonal edges, rather than one of the original polygon points.
    page.evaluate('''polygon=>{const row=ocrTasks.get('scan').scanState.graphRegions[0];
      row.polygon=polygon;ocrEditorController.destroy();ocrEditorController=null;
      document.getElementById('graphEditorDialog').close();}''', polygon)
    page.wait_for_function('ocrEditorTaskId===null')
    page.get_by_role('button', name='编辑核对', exact=True).click()
    page.wait_for_function('document.querySelector(".dgs-source .dge-overlay")?.dataset.geometryReady==="true"')
    box = page.locator('.dgs-source .dge-overlay-image').bounding_box()
    a, b = polygon[edge_index], polygon[(edge_index + 1) % len(polygon)]
    midpoint = [(a[i] + b[i]) / 2 for i in (0, 1)]
    dx, dy = (b[0] - a[0]) * box['width'], (b[1] - a[1]) * box['height']
    length = math.hypot(dx, dy)
    outward = [dy / length, -dx / length]
    # The visible frame is only 1px. Grab beyond even its transparent SVG
    # stroke to exercise screen-distance detection around every edge segment.
    offset = 14 if page.viewport_size['width'] < 760 else 8
    start = [box['x'] + midpoint[0] * box['width'] + outward[0] * offset,
             box['y'] + midpoint[1] * box['height'] + outward[1] * offset]
    page.evaluate('window.grabbedOutline=document.querySelector(".dge-overlay-polygon")')
    before_points = page.locator('.dge-overlay-polygon').get_attribute('points')
    page.mouse.move(*start)
    page.mouse.down()
    for distance in [4, 8, 12, 16, 20]:
        page.mouse.move(start[0] + outward[0] * distance, start[1] + outward[1] * distance)
    page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>resolve()))')
    assert page.locator('.dge-overlay-polygon').evaluate('e=>e===grabbedOutline')
    assert page.locator('.dge-overlay-polygon').get_attribute('points') != before_points
    assert page.evaluate('graphCalls.length') == 0
    assert region(page) == polygon
    assert page.locator('.dgs-source .dge-overlay-image').bounding_box() == pytest.approx(box, abs=1)
    page.mouse.up()
    page.wait_for_function('graphCalls.length===1')
    output = region(page)
    expected = [midpoint[0] + outward[0] * 20 / box['width'],
                midpoint[1] + outward[1] * 20 / box['height']]
    assert min(math.hypot(p[0] - expected[0], p[1] - expected[1]) for p in output) < .015
    assert 24 <= len(output) <= 64


def test_control_point_ink_is_continuous_and_halos_do_not_cut_the_incoming_line(canvas_page):
    page = canvas_page
    page.evaluate("instance.model.setEdgePath('G1','e1',[[.2,.25],[.5,.12],[.8,.75]])")
    tool(page, '选择 / 移动')
    source = page.locator('.dge-overlay-image').bounding_box()
    page.mouse.click(source['x'] + source['width'] * .35, source['y'] + source['height'] * .185)
    assert page.locator('.dge-overlay-handle').evaluate('e=>getComputedStyle(e).fill') == 'rgba(0, 0, 0, 0)'
    result = page.evaluate('''async()=>{
      const original=instance.getDrawingSvg(),group=original.querySelector('.dge-overlay-edge');
      const halos=[...group.querySelectorAll('.dge-overlay-contrast-halo')],strokes=[...group.querySelectorAll('.dge-overlay-stroke')];
      const before=original.cloneNode(true),oldGroup=before.querySelector('.dge-overlay-edge');
      // Recreate the former interleaved painting to ensure this probes the
      // actual erased incoming ink, rather than just checking SVG structure.
      oldGroup.querySelectorAll('.dge-overlay-contrast-halo,.dge-overlay-stroke').forEach(e=>e.remove());
      for(let i=0;i<halos.length;i++)oldGroup.append(halos[i].cloneNode(true),strokes[i].cloneNode(true));
      const numbers=strokes[0].getAttribute('d').match(/[-+]?\\d*\\.?\\d+(?:e[-+]?\\d+)?/gi).map(Number);
      const a=numbers.slice(0,2),joint=numbers.slice(2,4),dx=joint[0]-a[0],dy=joint[1]-a[1],length=Math.hypot(dx,dy);
      const unit=[dx/length,dy/length],pixelUnit=parseFloat(strokes[0].style.strokeWidth)/3.6;
      async function inspect(svg){
        const span=18*pixelUnit,size=216;
        svg.setAttribute('viewBox',[joint[0]-span/2,joint[1]-span/2,span,span].join(' '));
        svg.setAttribute('width',size);svg.setAttribute('height',size);
        const image=new Image();image.src='data:image/svg+xml;base64,'+btoa(unescape(encodeURIComponent(new XMLSerializer().serializeToString(svg))));
        await image.decode();const canvas=document.createElement('canvas');canvas.width=canvas.height=size;
        const context=canvas.getContext('2d');context.fillStyle='white';context.fillRect(0,0,size,size);context.drawImage(image,0,0,size,size);
        return [.8,1,1.2,1.4,1.6,1.8,2,2.2].map(distance=>{
          const x=Math.round(size/2-unit[0]*distance*pixelUnit/span*size),y=Math.round(size/2-unit[1]*distance*pixelUnit/span*size);
          return context.getImageData(x,y,1,1).data[0];
        });
      }
      return {fixed:await inspect(original),former:await inspect(before)};
    }''')
    assert max(result['fixed']) < 120
    assert max(result['former']) > max(result['fixed']) + 50


def test_loaded_image_cannot_accept_a_gesture_before_its_fit_handler_runs(scan_page):
    page = scan_page
    # Chromium may publish naturalWidth before dispatching load. Hold just that
    # queued callback, deterministically, instead of relying on timer delays or
    # a particular headless browser's image-cache event ordering.
    page.evaluate('''()=>{
      let owner=HTMLImageElement.prototype,descriptor;
      while(owner&&!descriptor){descriptor=Object.getOwnPropertyDescriptor(owner,'onload');owner=Object.getPrototypeOf(owner);}
      Object.defineProperty(HTMLImageElement.prototype,'onload',{configurable:true,
        get(){return descriptor.get.call(this);},
        set(callback){descriptor.set.call(this,callback?event=>{window.pendingGeometryLoad=()=>callback.call(this,event);}:null);}});
    }''')
    polygon = set_regions(page)
    page.wait_for_function('typeof pendingGeometryLoad==="function"')
    assert page.locator('.dgs-source .dge-overlay-image').evaluate('e=>e.naturalWidth') == 600
    assert page.locator('.dgs-source .dge-overlay').get_attribute('data-geometry-ready') == 'false'
    assert page.locator('.dge-overlay-svg').get_attribute('aria-busy') == 'true'
    point = page.locator('.dge-overlay-svg').evaluate('''svg=>{
      const p=svg.createSVGPoint();p.x=730;p.y=520;const screen=p.matrixTransform(svg.getScreenCTM());return [screen.x,screen.y];}''')
    page.mouse.move(*point)
    page.mouse.down()
    page.mouse.move(point[0] + 20, point[1], steps=4)
    page.mouse.up()
    assert region(page) == polygon
    assert page.evaluate('graphCalls.length') == 0
    page.evaluate('pendingGeometryLoad()')
    page.wait_for_function('document.querySelector(".dgs-source .dge-overlay").dataset.geometryReady==="true"')
    assert page.locator('.dge-overlay-svg').get_attribute('aria-busy') == 'false'
