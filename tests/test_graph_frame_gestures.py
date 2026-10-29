"""Real pointer gestures for one-stroke framing and border resizing."""
import math
import pytest
from test_graph_overlay import canvas_page,stroke
from test_graph_text_workspace import text_pane,frame,wait_batches


def point(page,x,y,pane=None):
    area=pane or page
    box=area.locator('.dge-overlay-image:visible').bounding_box()
    return box['x']+box['width']*x,box['y']+box['height']*y


def drag(page,a,b,pane=None):
    page.mouse.move(*point(page,*a,pane));page.mouse.down()
    page.mouse.move(*point(page,*b,pane),steps=8);page.mouse.up()


def circle(cx=.43,cy=.48,rx=.18,ry=.26):
    return [(cx+rx*math.cos(i*math.pi/32),cy+ry*math.sin(i*math.pi/32)) for i in range(65)]


def select_tool(page):
    page.locator('.dge-workspace').get_by_role('button',name='选择 / 移动',exact=True).click()


def test_clear_is_one_click_and_history_buttons_are_accessible_arrows(canvas_page):
    page=canvas_page;before=page.evaluate('instance.getDocument()')
    page.evaluate("instance.model.addVertex('G1','新顶点',.6,.3);instance.model.addGraph({bbox:[.2,.2,.5,.7]})")
    select_tool(page)
    for label in ['撤销','重做']:
        control=page.get_by_role('button',name=label,exact=True)
        assert control.text_content()==''
        icon=control.locator('svg')
        assert icon.get_attribute('viewBox')=='0 0 24 24'
        assert icon.get_attribute('aria-hidden')=='true'
        assert icon.get_attribute('focusable')=='false'
        assert icon.locator('path').count()==2
    assert page.get_by_role('button',name='清空修改',exact=True).count()==0
    page.get_by_role('button',name='清空',exact=True).click()
    assert page.evaluate('instance.getDocument()')==before
    page.get_by_role('button',name='撤销',exact=True).click()
    assert page.evaluate('instance.getDocument().graphs.length')==2
    page.get_by_role('button',name='重做',exact=True).click()
    assert page.evaluate('instance.getDocument()')==before


def test_graph_manager_does_not_have_add_or_delete_actions(canvas_page):
    page=canvas_page
    page.locator('.dge-float-graphs > summary').click()
    manager=page.locator('.dge-float-graphs')
    assert manager.get_by_role('button',name='添加子图',exact=True).count()==0
    assert manager.get_by_role('button',name='删除子图',exact=True).count()==0
    assert manager.get_by_label('当前子图',exact=True).is_visible()


def test_freehand_commits_on_release_has_no_vertices_and_is_selectable(canvas_page):
    page=canvas_page
    page.get_by_label('选区方式').select_option('graph_poly')
    assert page.get_by_role('button',name='完成轮廓').count()==0
    stroke(page,circle())
    polygon=page.evaluate('instance.getDocument().graphs.at(-1).region_polygon')
    assert 8<len(polygon)<=64
    assert page.locator('.dge-overlay-draft-dot,.dge-freehand-draft').count()==0
    assert page.get_by_label('选区方式').input_value()=='graph_poly'
    count=page.evaluate('instance.getDocument().graphs.length')
    # Clicking the outline in drawing mode selects the graph rather than adding one.
    page.mouse.click(*point(page,*polygon[0]))
    assert page.get_by_label('当前子图名称',exact=True).is_visible()
    assert page.get_by_label('当前子图名称',exact=True).input_value()=='图 2'
    assert page.evaluate('instance.getDocument().graphs.length')==count


@pytest.mark.parametrize('irregular',[False,True])
def test_border_drag_expands_and_contracts_region_atomically_without_moving_graph(canvas_page,irregular):
    page=canvas_page
    if irregular:
        page.evaluate("instance.model.setGraphPolygon('G1',[[.25,.25],[.4,.2],[.55,.3],[.55,.65],[.25,.65]])")
    else:page.evaluate("instance.model.setGraphBounds('G1',[.25,.2,.55,.65])")
    select_tool(page)
    original=page.evaluate('instance.getDocument().graphs[0]')
    before=page.locator('.dge-overlay-image').bounding_box()
    drag(page,(.4,.2),(.4,.12))
    graph=page.evaluate('instance.getDocument().graphs[0]')
    top=min(p[1] for p in graph['region_polygon']) if irregular else graph['bbox'][1]
    assert top==pytest.approx(.12,abs=.006)
    assert graph['vertices']==original['vertices'] and graph['edges']==original['edges']
    assert page.locator('.dge-overlay-image').bounding_box()==pytest.approx(before,abs=1)
    page.get_by_role('button',name='撤销',exact=True).click()
    assert page.evaluate('instance.getDocument().graphs[0]')==original
    # Contract the right edge, keeping the opposing side fixed.
    drag(page,(.55,.47),(.48,.47))
    graph=page.evaluate('instance.getDocument().graphs[0]')
    if irregular:
        # Irregular outlines bend locally around the grabbed border, leaving
        # distant portions in place instead of scaling their whole bounding box.
        assert min(math.hypot(p[0]-.48,p[1]-.47) for p in graph['region_polygon'])<.01
        assert sum(.25<p[0]<.55 for p in graph['region_polygon'])>=8
        assert min(p[0] for p in graph['region_polygon'])==pytest.approx(.25,abs=.006)
    else:assert graph['bbox']==pytest.approx([.25,.2,.48,.65],abs=.006)


def test_resize_cancel_leaves_original_range_unchanged(canvas_page):
    page=canvas_page;page.evaluate("instance.model.setGraphBounds('G1',[.25,.2,.55,.65])");select_tool(page)
    before=page.evaluate('instance.getDocument()')
    page.mouse.move(*point(page,.4,.2));page.mouse.down();page.mouse.move(*point(page,.4,.1),steps=4)
    page.locator('.dge-overlay-svg').dispatch_event('pointercancel',{'pointerId':1});page.mouse.up()
    assert page.evaluate('instance.getDocument()')==before


def test_freehand_text_auto_recognizes_then_resize_reuses_number(canvas_page):
    page=canvas_page;pane=text_pane(page)
    pane.get_by_label('选区方式').select_option('text_poly')
    stroke(page,circle());wait_batches(page)
    page.wait_for_function("instance.getDocument().body_text==='框选文字 1'")
    first=page.evaluate('textAreas[0][0].polygon')
    pane.get_by_role('button',name='选择 / 移动',exact=True).click()
    # The leftmost point is clear of graph ink and floating controls.
    left=min(first,key=lambda p:p[0]);drag(page,left,(left[0]-.05,left[1]),pane)
    wait_batches(page,2)
    assert page.evaluate('textAreas[1][0].id')==1
    assert min(p[0] for p in page.evaluate('textAreas[1][0].polygon'))<min(p[0] for p in first)-.04
    assert pane.locator('.dge-text-frame-number').all_text_contents()==['1']


def test_rect_text_resize_does_not_apply_old_in_flight_result(canvas_page):
    page=canvas_page;pane=text_pane(page);page.evaluate('window.deferText=true')
    frame(page,pane,(.3,.3,.6,.6));wait_batches(page)
    drag(page,(.45,.3),(.45,.23),pane)
    page.evaluate("window.deferText=false;resolveText({regions:[{id:1,text:'旧框的文字'}]})")
    wait_batches(page,2)
    page.wait_for_function("instance.getDocument().body_text==='框选文字 1'")
    assert '旧框' not in page.evaluate('instance.getDocument().body_text')
    assert page.evaluate('textAreas[1][0].polygon[0][1]')==pytest.approx(.23,abs=.006)


def test_mobile_border_drag_works_after_fit_and_zoom(canvas_page):
    page=canvas_page;page.set_viewport_size({'width':390,'height':844})
    page.evaluate("instance.model.setGraphBounds('G1',[.3,.2,.7,.75]);Object.defineProperty(navigator,'maxTouchPoints',{configurable:true,value:5})")
    select_tool(page)
    page.get_by_role('button',name='适应',exact=True).click()
    page.get_by_role('button',name='缩小原图',exact=True).click()
    assert page.locator('.dge-frame-edge-hit').evaluate('e=>parseFloat(getComputedStyle(e).strokeWidth)')>=24
    drag(page,(.5,.2),(.5,.1))
    assert page.evaluate('instance.getDocument().graphs[0].bbox[1]')==pytest.approx(.1,abs=.01)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')


def test_clear_drops_text_frames_and_late_ocr_does_not_restore_them(canvas_page):
    page=canvas_page;pane=text_pane(page);page.evaluate('window.deferText=true')
    frame(page,pane);wait_batches(page)
    page.get_by_role('button',name='清空',exact=True).click()
    assert pane.locator('.dge-overlay-text-region,.dge-text-frame-number').count()==0
    page.get_by_role('button',name='保存并确认',exact=True).click()
    assert page.evaluate('confirmed.length')==1
    page.evaluate("resolveText({regions:[{id:1,text:'清空前的文字'}]})")
    page.wait_for_timeout(100)
    assert '清空前' not in page.evaluate('instance.getDocument().body_text')
