"""Numbered text frames: automatic ordered batches and floating results."""
import pytest
from test_graph_overlay import canvas_page


def text_pane(page):
    page.get_by_role('tab', name='文字识别', exact=True).click()
    pane = page.locator('.dge-text-workspace')
    page.wait_for_function("document.querySelector('.dge-text-workspace .dge-overlay-image').naturalWidth===900")
    return pane


def show_results(pane):
    pane.locator('.dge-text-results').evaluate('e=>e.open=true')


def frame(page, pane, box=(.35,.25,.78,.65)):
    pane.locator('.dge-text-results').evaluate('e=>e.open=false')
    pane.get_by_role('button', name='框选文字', exact=True).click()
    image = pane.locator('.dge-overlay-image').bounding_box()
    a,b,c,d = box
    page.mouse.move(image['x'] + image['width']*a, image['y'] + image['height']*b)
    page.mouse.down()
    page.mouse.move(image['x'] + image['width']*c, image['y'] + image['height']*d, steps=2)
    page.mouse.up()
    return [[a,b],[c,b],[c,d],[a,d]]


def wait_batches(page,n=1):
    page.wait_for_function('(n)=>textAreas.length===n',arg=n)


def test_view_controls_outside_rail_and_irrelevant_graph_controls_removed(canvas_page):
    page=canvas_page
    rail=page.locator('.dge-tool-palette')
    assert rail.evaluate("e=>getComputedStyle(e.querySelector('.dge-overlay-tools')).flexDirection")=='column'
    for label in ('适应','隐藏原图','隐藏描绘','缩小原图','放大原图'):
        assert page.locator('.dge-view-controls').get_by_role('button',name=label,exact=True).is_visible()
        assert rail.get_by_role('button',name=label,exact=True).count()==0
    assert page.get_by_role('button',name='聚焦图形',exact=True).count()==0
    page.locator('[data-edge-id="e1"] .dge-overlay-hit').click()
    panel=page.locator('.dge-selection-panel')
    assert panel.get_by_label('当前边起点').count()==0
    assert panel.get_by_label('当前边方向').count()==0
    assert panel.get_by_label('当前边端点一').is_visible()


def test_framing_automatically_recognizes_only_selected_pixels_and_saves_text(canvas_page):
    page=canvas_page;original_graphs=page.evaluate('instance.getDocument().graphs')
    pane=text_pane(page)
    assert page.evaluate('textAreas.length')==0
    assert pane.get_by_role('button',name='识别框内文字').count()==0
    assert pane.locator('.dge-frame-hit,.dge-overlay-node,.dge-overlay-edge').count()==0
    expected=frame(page,pane);wait_batches(page)
    page.wait_for_function("instance.getDocument().body_text==='框选文字 1'")
    assert page.evaluate('textAreas[0][0].id')==1
    for a,b in zip(page.evaluate('textAreas[0][0].polygon'),expected): assert a==pytest.approx(b,abs=.005)
    assert page.evaluate('instance.getDocument().graphs')==original_graphs
    show_results(pane)
    pane.get_by_label('文字识别结果',exact=True).fill('已校正的题干及第（2）问')
    pane.get_by_label('手动输入要求（可选）',exact=True).fill('只解第二问')
    assert page.evaluate('requirementsChanges.at(-1)')=='只解第二问'
    page.get_by_role('button',name='保存并确认',exact=True).click()
    assert page.evaluate('confirmed[0].body_text')=='已校正的题干及第（2）问'


def test_continuous_frames_are_numbered_and_recognized_in_one_batch(canvas_page):
    page=canvas_page;pane=text_pane(page)
    frame(page,pane,(.3,.6,.7,.8))
    frame(page,pane,(.3,.2,.7,.4))
    wait_batches(page)
    page.wait_for_function("instance.getDocument().body_text==='框选文字 1\\n\\n框选文字 2'")
    assert page.evaluate('textAreas.length')==1
    assert page.evaluate('textAreas[0].map(r=>r.id)')==[1,2]
    assert pane.locator('.dge-overlay-text-region').count()==2
    assert pane.locator('.dge-text-frame-number').all_text_contents()==['1','2']
    assert pane.locator('.dge-text-results').evaluate("e=>getComputedStyle(e.querySelector('.dge-float-content')).position")=='absolute'
    show_results(pane)
    before=pane.locator('.dge-overlay-viewport').bounding_box()
    pane.locator('.dge-text-results > summary').click()
    assert pane.locator('.dge-overlay-viewport').bounding_box()==pytest.approx(before,abs=1)


def test_new_frame_while_batch_running_is_queued_without_repeating_completed_frames(canvas_page):
    page=canvas_page;pane=text_pane(page);page.evaluate('window.deferText=true')
    frame(page,pane);wait_batches(page)
    frame(page,pane,(.4,.35,.7,.75))
    assert pane.locator('.dge-overlay-text-region').count()==2
    page.evaluate("window.deferText=false;resolveText({regions:[{id:1,text:'第一段'}]})")
    wait_batches(page,2)
    page.wait_for_function("instance.getDocument().body_text==='第一段\\n\\n框选文字 2'")
    assert page.evaluate('textAreas[1].map(r=>r.id)')==[2]


def test_deleting_in_flight_frame_cannot_resurrect_its_text(canvas_page):
    page=canvas_page;pane=text_pane(page);page.evaluate('window.deferText=true')
    frame(page,pane);wait_batches(page);show_results(pane)
    pane.get_by_role('button',name='删除文字框 1',exact=True).click()
    page.evaluate("resolveText({regions:[{id:1,text:'被删的段落'}]})")
    page.wait_for_timeout(100)
    assert '被删的段落' not in page.evaluate('instance.getDocument().body_text')
    assert pane.locator('.dge-overlay-text-region').count()==0


def test_manual_edits_are_preserved_while_ocr_is_pending(canvas_page):
    page=canvas_page;pane=text_pane(page);page.evaluate('window.deferText=true')
    frame(page,pane);wait_batches(page);show_results(pane)
    pane.get_by_label('文字识别结果',exact=True).fill('我手动补充的条件')
    page.get_by_role('button',name='保存并确认',exact=True).click()
    assert page.evaluate('confirmed.length')==0
    page.evaluate("resolveText({regions:[{id:1,text:'模型识别文字'}]})")
    page.wait_for_function("document.querySelector('.dge-text-status').textContent.includes('已保留手动修改')")
    assert page.evaluate('instance.getDocument().body_text')=='我手动补充的条件'
    pane.get_by_role('button',name='使用编号顺序的识别结果',exact=True).click()
    assert page.evaluate('instance.getDocument().body_text')=='模型识别文字'


def test_empty_result_is_distinct_from_failure_and_retry_is_explicit(canvas_page):
    page=canvas_page;pane=text_pane(page);page.evaluate('window.deferText=true')
    frame(page,pane);wait_batches(page)
    page.evaluate("resolveText({regions:[{id:1,text:''}]})")
    page.wait_for_function("document.querySelector('.dge-text-region-row').textContent.includes('未识别到文字')")
    assert page.evaluate('instance.getDocument().body_text')=='判断图中各边方向'
    page.evaluate('window.deferText=false');show_results(pane)
    pane.get_by_role('button',name='重试文字框 1',exact=True).click()
    wait_batches(page,2)
    page.wait_for_function("instance.getDocument().body_text==='框选文字 1'")


def test_clear_all_removes_numbered_frames_without_affecting_graph(canvas_page):
    page=canvas_page;pane=text_pane(page)
    original=page.evaluate('instance.getDocument().graphs')
    frame(page,pane);frame(page,pane,(.4,.4,.7,.7));wait_batches(page)
    pane.get_by_role('button',name='清空文字框',exact=True).click()
    assert pane.locator('.dge-overlay-text-region,.dge-text-frame-number').count()==0
    assert page.evaluate('instance.getDocument().graphs')==original


def test_tabs_keep_independent_zoom_and_numbered_frames(canvas_page):
    page=canvas_page;image_pane=page.locator('.dge-workspace')
    image_pane.get_by_role('button',name='缩小原图',exact=True).click()
    camera=image_pane.locator('.dge-overlay-image').bounding_box()
    pane=text_pane(page);frame(page,pane)
    pane.get_by_role('button',name='缩小原图',exact=True).click()
    zoom=pane.locator('.dge-overlay-zoom').text_content()
    page.get_by_role('tab',name='图像识别',exact=True).click()
    assert image_pane.locator('.dge-overlay-image').bounding_box()==pytest.approx(camera,abs=1)
    page.get_by_role('tab',name='文字识别',exact=True).click()
    assert pane.locator('.dge-overlay-zoom').text_content()==zoom
    assert pane.locator('.dge-overlay-text-region').count()==1


def test_mobile_fit_keyboard_tabs_and_popup_stay_inside_viewport(canvas_page):
    page=canvas_page;page.set_viewport_size({'width':390,'height':844})
    page.get_by_role('tab',name='图像识别',exact=True).focus();page.keyboard.press('ArrowRight')
    pane=page.locator('.dge-text-workspace')
    page.wait_for_function("document.querySelector('.dge-text-workspace img').naturalWidth===900")
    pane.get_by_role('button',name='适应',exact=True).click()
    view=pane.locator('.dge-overlay-viewport').bounding_box();photo=pane.locator('.dge-overlay-image').bounding_box()
    assert photo['x']+photo['width']/2==pytest.approx(view['x']+view['width']/2,abs=2)
    assert photo['y']+photo['height']/2==pytest.approx(view['y']+view['height']/2,abs=2)
    show_results(pane)
    box=pane.locator('.dge-float-content').bounding_box()
    assert box['x']>=0 and box['x']+box['width']<=392
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')


def test_text_undo_redo_matches_visible_and_saved_text(canvas_page):
    page=canvas_page;pane=text_pane(page);show_results(pane)
    pane.get_by_label('文字识别结果',exact=True).fill('人工修正的题干')
    page.get_by_role('button',name='撤销',exact=True).click()
    assert pane.get_by_label('文字识别结果',exact=True).input_value()=='判断图中各边方向'
    page.get_by_role('button',name='重做',exact=True).click()
    assert pane.get_by_label('文字识别结果',exact=True).input_value()=='人工修正的题干'
    page.get_by_role('button',name='保存并确认',exact=True).click()
    assert page.evaluate('confirmed[0].body_text')=='人工修正的题干'
