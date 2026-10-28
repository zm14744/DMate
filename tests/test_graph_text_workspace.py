"""Independent text selection, retained cameras and confirmed text in Chromium."""
import pytest
from test_graph_overlay import canvas_page


def text_pane(page):
    page.get_by_role('tab', name='文字识别', exact=True).click()
    pane = page.locator('.dge-text-workspace')
    page.wait_for_function("document.querySelector('.dge-text-workspace .dge-overlay-image').naturalWidth===900")
    return pane


def frame(page, pane, box=(.35,.25,.78,.65)):
    pane.get_by_role('button', name='框选文字', exact=True).click()
    image = pane.locator('.dge-overlay-image').bounding_box()
    a,b,c,d = box
    page.mouse.move(image['x'] + image['width']*a, image['y'] + image['height']*b)
    page.mouse.down()
    page.mouse.move(image['x'] + image['width']*c, image['y'] + image['height']*d, steps=5)
    page.mouse.up()
    return [[a,b],[c,b],[c,d],[a,d]]


def test_view_controls_are_outside_vertical_tools_and_merge_focus_are_removed(canvas_page):
    page=canvas_page
    rail=page.locator('.dge-tool-palette')
    assert rail.evaluate("e=>getComputedStyle(e.querySelector('.dge-overlay-tools')).flexDirection")=='column'
    for label in ('适应','隐藏原图','隐藏描绘','缩小原图','放大原图'):
        assert page.locator('.dge-view-controls').get_by_role('button',name=label,exact=True).is_visible()
        assert rail.get_by_role('button',name=label,exact=True).count()==0
    assert page.locator('.dge-view-controls').get_by_label('原图透明度').is_visible()
    assert page.get_by_role('button',name='聚焦图形',exact=True).count()==0
    page.evaluate('instance.model.addGraph()')
    page.get_by_role('button',name='选择 / 移动',exact=True).click()
    assert page.get_by_label('合并目标子图').count()==0
    assert page.get_by_role('button',name='合并到所选图',exact=True).count()==0
    page.locator('[data-edge-id="e1"] .dge-overlay-hit').click()
    panel=page.locator('.dge-selection-panel')
    assert panel.get_by_label('当前边起点').count()==0
    assert panel.get_by_label('当前边终点').count()==0
    assert panel.get_by_label('当前边端点一').is_visible()
    assert panel.get_by_label('当前边端点二').is_visible()


def test_text_tab_only_recognizes_selected_pixels_and_saves_corrected_text(canvas_page):
    page=canvas_page
    original_graphs=page.evaluate('instance.getDocument().graphs')
    assert page.evaluate('textAreas.length')==0
    pane=text_pane(page)
    assert page.evaluate('textAreas.length')==0
    assert pane.get_by_role('button',name='识别框内文字').is_disabled()
    assert pane.locator('.dge-frame-hit,.dge-overlay-node,.dge-overlay-edge').count()==0
    expected=frame(page,pane)
    pane.get_by_role('button',name='识别框内文字').click()
    assert pane.get_by_label('文字识别结果',exact=True).input_value()=='框选文字'
    actual=page.evaluate('textAreas[0]')
    for a,b in zip(actual,expected): assert a==pytest.approx(b,abs=.005)
    assert page.evaluate('instance.getDocument().graphs')==original_graphs
    pane.get_by_label('文字识别结果',exact=True).fill('已校正的题干及第（2）问')
    pane.get_by_label('手动输入要求（可选）',exact=True).fill('只解第二问')
    assert page.evaluate('requirementsChanges.at(-1)')=='只解第二问'
    page.get_by_role('tab',name='图像识别',exact=True).click()
    page.get_by_role('tab',name='文字识别',exact=True).click()
    assert pane.get_by_label('手动输入要求（可选）',exact=True).input_value()=='只解第二问'
    page.get_by_role('button',name='保存并确认',exact=True).click()
    assert page.evaluate('confirmed[0].body_text')=='已校正的题干及第（2）问'
    assert page.evaluate('confirmed[0].graphs')==original_graphs


def test_tabs_keep_independent_zoom_frames_and_fit_full_image(canvas_page):
    page=canvas_page
    image_pane=page.locator('.dge-workspace')
    image_pane.get_by_role('button',name='缩小原图',exact=True).click()
    original_zoom=image_pane.locator('.dge-overlay-zoom').text_content()
    original_camera=image_pane.locator('.dge-overlay-image').bounding_box()
    pane=text_pane(page)
    frame(page,pane)
    pane.get_by_role('button',name='缩小原图',exact=True).click()
    pane.get_by_role('button',name='缩小原图',exact=True).click()
    text_zoom=pane.locator('.dge-overlay-zoom').text_content()
    page.get_by_role('tab',name='图像识别',exact=True).click()
    assert image_pane.locator('.dge-overlay-zoom').text_content()==original_zoom
    assert image_pane.locator('.dge-overlay-image').bounding_box()==pytest.approx(original_camera,abs=1)
    assert image_pane.locator('.dge-overlay-text-region').count()==0
    page.get_by_role('tab',name='文字识别',exact=True).click()
    assert pane.locator('.dge-overlay-zoom').text_content()==text_zoom
    assert pane.locator('.dge-overlay-text-region').count()==1
    pane.get_by_role('button',name='适应',exact=True).click()
    image=pane.locator('.dge-overlay-image').bounding_box()
    viewport=pane.locator('.dge-overlay-viewport').bounding_box()
    assert image['width']<=viewport['width']+1 and image['height']<=viewport['height']+1
    assert image['x']+image['width']/2==pytest.approx(viewport['x']+viewport['width']/2,abs=2)
    assert image['y']+image['height']/2==pytest.approx(viewport['y']+viewport['height']/2,abs=2)


def test_text_reframing_during_request_does_not_apply_stale_result(canvas_page):
    page=canvas_page;pane=text_pane(page)
    frame(page,pane);page.evaluate('window.deferText=true')
    pane.get_by_role('button',name='识别框内文字').click()
    assert pane.get_by_role('button',name='识别框内文字').is_disabled()
    frame(page,pane,(.4,.35,.7,.75))
    page.evaluate("resolveText('旧区域文字')")
    page.wait_for_function("document.querySelector('.dge-text-status').textContent.includes('选区已更改')")
    assert pane.get_by_label('文字识别结果',exact=True).input_value()=='判断图中各边方向'
    assert pane.get_by_role('button',name='识别框内文字').is_enabled()


def test_polygon_text_region_and_clear_do_not_touch_graph_frames(canvas_page):
    page=canvas_page
    page.evaluate("instance.model.setGraphBounds('G1',[.1,.1,.9,.9])")
    page.get_by_role('button',name='选择 / 移动',exact=True).click()
    pane=text_pane(page)
    pane.get_by_label('选区方式').select_option('text_poly')
    image=pane.locator('.dge-overlay-image').bounding_box()
    for x,y in ((.35,.25),(.8,.25),(.7,.7)):
        page.mouse.click(image['x']+image['width']*x,image['y']+image['height']*y)
    pane.get_by_role('button',name='完成轮廓',exact=True).click()
    assert pane.locator('.dge-overlay-text-region').count()==1
    pane.get_by_role('button',name='识别框内文字',exact=True).click()
    assert len(page.evaluate('textAreas[0]'))==3
    pane.get_by_role('button',name='清除文字框',exact=True).click()
    assert pane.locator('.dge-overlay-text-region').count()==0
    assert pane.get_by_role('button',name='识别框内文字',exact=True).is_disabled()
    assert page.evaluate('instance.getDocument().graphs[0].bbox')==[.1,.1,.9,.9]


def test_manual_text_is_preserved_if_edited_while_ocr_is_pending(canvas_page):
    page=canvas_page;pane=text_pane(page)
    frame(page,pane);page.evaluate('window.deferText=true')
    pane.get_by_role('button',name='识别框内文字').click()
    pane.get_by_label('文字识别结果',exact=True).fill('我手动补充的条件')
    page.get_by_role('button',name='保存并确认',exact=True).click()
    assert page.evaluate('confirmed.length')==0
    page.evaluate("resolveText('模型识别文字')")
    page.wait_for_function("document.querySelector('.dge-text-status').textContent.includes('已保留输入')")
    assert page.evaluate('instance.getDocument().body_text')=='我手动补充的条件'
    assert '模型识别文字' in pane.locator('.dge-text-status').text_content()


def test_text_failure_keeps_draft_and_allows_retry(canvas_page):
    page=canvas_page;pane=text_pane(page)
    frame(page,pane);page.evaluate('window.deferText=true')
    pane.get_by_role('button',name='识别框内文字').click()
    page.evaluate("resolveText({text:'',warning:'选区内没有文字'})")
    page.wait_for_function("document.querySelector('.dge-text-status').textContent.includes('选区内没有文字')")
    assert page.evaluate('instance.getDocument().body_text')=='判断图中各边方向'
    page.evaluate('window.deferText=false')
    pane.get_by_role('button',name='识别框内文字').click()
    assert pane.get_by_label('文字识别结果',exact=True).input_value()=='框选文字'


def test_mobile_text_tab_controls_fit_and_keyboard_tabs(canvas_page):
    page=canvas_page;page.set_viewport_size({'width':390,'height':844})
    page.get_by_role('tab',name='图像识别',exact=True).focus()
    page.keyboard.press('ArrowRight')
    pane=page.locator('.dge-text-workspace')
    page.wait_for_function("document.querySelector('.dge-text-workspace img').naturalWidth===900")
    assert pane.is_visible()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
    view=pane.locator('.dge-overlay-viewport').bounding_box()
    rail=pane.locator('.dge-tool-palette').bounding_box()
    assert rail['y']>=view['y']
    for name in ('缩小原图','放大原图','适应'):
        assert pane.locator('.dge-view-controls').get_by_role('button',name=name,exact=True).is_visible()
    pane.get_by_role('button',name='适应',exact=True).click()
    photo=pane.locator('.dge-overlay-image').bounding_box()
    assert photo['x']+photo['width']/2==pytest.approx(view['x']+view['width']/2,abs=2)
    assert photo['y']+photo['height']/2==pytest.approx(view['y']+view['height']/2,abs=2)


def test_text_undo_redo_updates_visible_result_and_save_snapshot(canvas_page):
    page=canvas_page;pane=text_pane(page)
    pane.get_by_label('文字识别结果',exact=True).fill('人工修正的题干')
    page.get_by_role('button',name='撤销',exact=True).click()
    assert pane.get_by_label('文字识别结果',exact=True).input_value()=='判断图中各边方向'
    page.get_by_role('button',name='重做',exact=True).click()
    assert pane.get_by_label('文字识别结果',exact=True).input_value()=='人工修正的题干'
    page.get_by_role('button',name='保存并确认',exact=True).click()
    assert page.evaluate('confirmed[0].body_text')=='人工修正的题干'
