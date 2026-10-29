"""Selection is quiet and Save stays separate from sending to the solver."""
import pytest

from test_scan_drawing_separation import scan_page, open_scan, drag


def image_point(page, x, y):
    box = page.locator('.dgs-source .dge-overlay-image').bounding_box()
    return box['x'] + box['width'] * x, box['y'] + box['height'] * y


def test_scan_opens_in_selection_without_debug_instruction_or_placeholder(scan_page):
    page = scan_page
    page.evaluate('''()=>{ocrTasks.get('scan').result={review:{reasons:[
      '原图无题干文字，body_text为空；边均按视觉连线判读。交叉点未作为顶点处理。']}};}''')
    open_scan(page)
    assert page.locator('.dge-overlay-svg').get_attribute('data-mode') == 'select'
    assert page.get_by_role('button', name='选择 / 平移', exact=True).get_attribute('aria-pressed') == 'true'
    assert not page.locator('.dgs-status').inner_text()
    assert page.get_by_label('要求（可选）', exact=True).get_attribute('placeholder') is None
    # Unknown directions remain explicit rather than hidden with debug notes.
    assert '方向待核对' in page.locator('.dgs-information').inner_text()
    assert page.get_by_role('button', name='保存并确认', exact=True).count() == 0


def test_first_frame_click_with_pointer_tremor_does_not_move_source(scan_page):
    page = scan_page
    open_scan(page)
    page.get_by_role('button', name='图形框选', exact=True).click()
    drag(page, [(.25, .25), (.7, .75)])
    page.wait_for_function('graphCalls.length===1')
    page.get_by_role('button', name='选择 / 平移', exact=True).click()
    page.mouse.click(*image_point(page, .9, .9))
    assert page.evaluate('ocrTasks.get("scan").scanState.selectedGraphId') is None
    before = page.locator('.dgs-source .dge-overlay-image').bounding_box()
    x, y = image_point(page, .5, .5)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 1, y + 1)
    page.mouse.up()
    assert page.evaluate('ocrTasks.get("scan").scanState.selectedGraphId') == 'g1'
    after = page.locator('.dgs-source .dge-overlay-image').bounding_box()
    assert after == pytest.approx(before, abs=.5)
    assert page.evaluate('graphCalls.length') == 1


def test_first_pan_from_fitted_fractional_bounds_moves_only_drag_distance(scan_page):
    page = scan_page
    open_scan(page)
    before = page.locator('.dgs-source .dge-overlay-image').bounding_box()
    x, y = image_point(page, .5, .5)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 12, y + 12, steps=3)
    page.mouse.up()
    after = page.locator('.dgs-source .dge-overlay-image').bounding_box()
    assert after['x'] - before['x'] == pytest.approx(12, abs=1.5)
    assert after['y'] - before['y'] == pytest.approx(12, abs=1.5)
    assert after['width'] == pytest.approx(before['width'], abs=.5)
    assert after['height'] == pytest.approx(before['height'], abs=.5)
    assert page.evaluate('graphCalls.length') == 0


def test_save_is_at_dialog_bottom_right_and_exits(scan_page):
    page = scan_page
    open_scan(page)
    save = page.get_by_role('button', name='保存', exact=True)
    box, dialog = save.bounding_box(), page.locator('#graphEditorDialog').bounding_box()
    assert box['x'] + box['width'] >= dialog['x'] + dialog['width'] - 25
    assert box['y'] + box['height'] >= dialog['y'] + dialog['height'] - 25
    assert box['y'] + box['height'] <= dialog['y'] + dialog['height']
    save.click()
    page.wait_for_function('!document.getElementById("graphEditorDialog").open')
    assert page.evaluate('posts.length') == 1


def test_reopening_a_task_resets_last_framing_mode_to_selection(scan_page):
    page = scan_page
    open_scan(page)
    page.get_by_role('button', name='文字框选', exact=True).click()
    page.get_by_label('关闭图形识别编辑器', exact=True).click()
    open_scan(page)
    assert page.locator('.dge-overlay-svg').get_attribute('data-mode') == 'select'


def test_selection_controls_are_ready_before_hidden_modal_has_layout(scan_page):
    result = scan_page.evaluate('''() => {
        const host=document.createElement('div');host.hidden=true;document.body.append(host);
        const overlay=DMateGraphOverlay.mount(host,{scanOnly:true,originalUrl:'',
            state:{mode:'select',zoom:100,visible:true},graph:()=>null,
            model:{getDocument:()=>({graphs:[]})}});
        const result={width:host.clientWidth,mode:host.querySelector('svg').dataset.mode,
            pressed:host.querySelector('[data-overlay-tool="select"]').getAttribute('aria-pressed')};
        overlay.destroy();host.remove();return result;
    }''')
    assert result == {'width': 0, 'mode': 'select', 'pressed': 'true'}
