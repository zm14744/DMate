"""Local, broad outline deformation rather than bbox scaling or single-point edits."""
import json
import math
from pathlib import Path
import shutil
import subprocess

import pytest

from test_scan_drawing_separation import scan_page, open_scan, drag

ROOT = Path(__file__).resolve().parents[1]


def circle(cx=.48, cy=.52, rx=.25, ry=.30, count=40):
    return [[cx + rx*math.cos(i*2*math.pi/count), cy + ry*math.sin(i*2*math.pi/count)]
            for i in range(count)]


def test_geometry_moves_a_broad_smooth_band_and_keeps_remote_outline_fixed():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node unavailable')
    program = '''const assert=require('node:assert/strict');
const {elasticRegionStart:start,elasticRegionPoints:deform}=require('./static/graph-editor-overlay.js');
const shape=JSON.parse(process.argv[1]);
for(const metric of [[600,400],[300,200],[1200,800]]){
 const op=start(shape,[.73,.52],metric),out=deform(op,[.81,.52]),inside=deform(op,[.63,.52]);
 assert(out.length<=64&&out.length>=24);
 const changed=op.weights.filter(w=>w>.2).length,remote=op.weights.filter(w=>w===0).length;
 assert(changed>=8&&remote>=24); // A region of the outline follows, never just one handle.
 for(let i=0;i<out.length;i++){
  assert(Math.abs(out[i][1]-op.samples[i][1])<1e-12);
  if(op.weights[i]===0)assert.deepEqual(out[i],op.samples[i]);
  if(op.weights[i]>.5){assert(out[i][0]>op.samples[i][0]+.039);assert(inside[i][0]<op.samples[i][0]-.049);}
 }
 assert(Math.abs(Math.min(...out.map(p=>p[0]))-.23)<1e-10);
 assert(Math.abs(Math.max(...out.map(p=>p[0]))-.81)<1e-10);
 const hard=deform(op,[-10,10]);
 assert(hard.every(p=>p.every(v=>Number.isFinite(v)&&v>=0&&v<=1)));
 const area=hard.reduce((sum,p,i)=>{const q=hard[(i+1)%hard.length];return sum+p[0]*q[1]-q[0]*p[1];},0)/2;
 assert(area*op.orientation>=op.minimumArea);
 const second=start(out,[.81,.52],metric),again=deform(second,[.69,.52]);
 assert(Math.min(...again.map(p=>p[0]))<.231);
 assert.deepEqual(deform(op,[.73,.52]),shape);
}
'''
    subprocess.run([node, '-e', program, json.dumps(circle())], cwd=ROOT, check=True, capture_output=True, text=True)


def set_regions(page, *, kind='graph', irregular=True, two=False):
    polygon = circle() if irregular else [[.25,.2],[.7,.2],[.7,.8],[.25,.8]]
    if page.viewport_size['width'] < 760:
        page.evaluate("Object.defineProperty(navigator,'maxTouchPoints',{configurable:true,value:5})")
    page.evaluate('''args=>{
        const task=ocrTasks.get('scan'), rows=[{id:args.kind==='graph'?'g1':1,polygon:args.polygon,
            irregular:args.irregular,status:'complete',version:1,graphs:structuredClone(sample.graphs),text:'原文字'}];
        if(args.two)rows.push({id:'g2',polygon:[[.05,.65],[.18,.65],[.18,.9],[.05,.9]],irregular:false,
            status:'complete',version:1,graphs:structuredClone(sample.graphs)});
        task.scanState={graphRegions:args.kind==='graph'?rows:[],textRegions:args.kind==='text'?rows:[],
            nextGraph:3,nextText:2,graphSelectionActive:args.kind==='graph',textSelectionActive:args.kind==='text'};
    }''', {'polygon': polygon, 'kind': kind, 'irregular': irregular, 'two': two})
    open_scan(page)
    return polygon


def region(page, kind='graph', index=0):
    return page.evaluate('''args=>ocrTasks.get('scan').scanState[args.kind==='graph'?'graphRegions':'textRegions'][args.index].polygon''',
                         {'kind': kind, 'index': index})


def assert_view_unchanged(before, page):
    assert page.locator('.dgs-source .dge-overlay-image').bounding_box() == pytest.approx(before, abs=1)


def test_graph_outline_pulls_out_then_in_as_a_local_band_without_moving_other_graph(scan_page):
    page = scan_page
    original = set_regions(page, two=True)
    untouched = region(page, index=1)
    view = page.locator('.dgs-source .dge-overlay-image').bounding_box()
    drag(page, [(.73,.52), (.81,.52)])
    page.wait_for_function('graphCalls.length===1')
    outside = region(page)
    assert 24 <= len(outside) <= 64
    assert max(p[0] for p in outside) == pytest.approx(.81, abs=.008)
    assert min(p[0] for p in outside) == pytest.approx(min(p[0] for p in original), abs=.002)
    assert sum(p[0] > .71 for p in outside) >= 8
    assert min(p[1] for p in outside) == pytest.approx(min(p[1] for p in original), abs=.002)
    assert region(page, index=1) == untouched
    assert_view_unchanged(view, page)
    drag(page, [(.81,.52), (.69,.52)])
    page.wait_for_function('graphCalls.length===2')
    inside = region(page)
    assert min(math.hypot(p[0]-.69,p[1]-.52) for p in inside) < .01
    assert min(p[0] for p in inside) == pytest.approx(.23, abs=.002)
    assert region(page, index=1) == untouched
    assert_view_unchanged(view, page)


def test_text_outline_uses_same_local_deformation_and_one_ocr_after_release(scan_page):
    page = scan_page
    original = set_regions(page, kind='text')
    view = page.locator('.dgs-source .dge-overlay-image').bounding_box()
    bounds = page.locator('.dgs-source .dge-overlay-image').bounding_box()
    page.mouse.move(bounds['x']+bounds['width']*.73,bounds['y']+bounds['height']*.52)
    page.mouse.down()
    page.mouse.move(bounds['x']+bounds['width']*.81,bounds['y']+bounds['height']*.52,steps=7)
    assert page.evaluate('textCalls.length') == 0
    assert region(page, kind='text') == original
    page.mouse.up()
    page.wait_for_function('textCalls.length===1')
    output = region(page, kind='text')
    assert max(p[0] for p in output) == pytest.approx(.81, abs=.008)
    assert min(p[0] for p in output) == pytest.approx(.23, abs=.002)
    assert page.evaluate('textCalls[0][0].id') == 1
    assert_view_unchanged(view, page)


def test_outline_click_and_cancel_do_not_change_region_or_start_recognition(scan_page):
    page = scan_page
    original = set_regions(page)
    drag(page, [(.73,.52), (.732,.52)])
    assert region(page) == original
    assert page.evaluate('graphCalls.length') == 0
    bounds = page.locator('.dgs-source .dge-overlay-image').bounding_box()
    page.mouse.move(bounds['x']+bounds['width']*.73,bounds['y']+bounds['height']*.52)
    page.mouse.down()
    page.mouse.move(bounds['x']+bounds['width']*.82,bounds['y']+bounds['height']*.52,steps=5)
    page.locator('.dge-overlay-svg').dispatch_event('pointercancel', {'pointerId': 1})
    page.mouse.up()
    assert region(page) == original
    assert page.evaluate('graphCalls.length') == 0


def test_rectangles_still_resize_whole_side_and_elastic_outline_works_after_zoom(scan_page):
    page = scan_page
    set_regions(page, irregular=False)
    drag(page, [(.7,.5), (.77,.5)])
    page.wait_for_function('graphCalls.length===1')
    for actual, expected in zip(region(page), [[.25,.2],[.77,.2],[.77,.8],[.25,.8]]):
        assert actual == pytest.approx(expected, abs=.008)
    page.get_by_label('关闭图形识别编辑器', exact=True).click()
    set_regions(page)
    page.get_by_role('button', name='缩小原图', exact=True).click()
    view = page.locator('.dgs-source .dge-overlay-image').bounding_box()
    drag(page, [(.73,.52), (.81,.52)])
    page.wait_for_function('graphCalls.length===2')
    assert max(p[0] for p in region(page)) == pytest.approx(.81, abs=.01)
    assert min(p[0] for p in region(page)) == pytest.approx(.23, abs=.002)
    assert_view_unchanged(view, page)
