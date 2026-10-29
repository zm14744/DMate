"""Production surfaces have separate information cards and no focus halos."""
from test_drawing_app_integration import drawing_app, open_drawing


def no_ring(control):
    control.focus()
    style = control.evaluate('''e=>{const s=getComputedStyle(e);return {
      outline:s.outlineStyle,shadow:s.boxShadow,border:s.borderColor,
      background:s.backgroundColor,radius:s.borderRadius};}''')
    assert style['outline'] == 'none'
    assert style['shadow'] == 'none'
    return style


def test_drawing_name_and_red_close_have_no_keyboard_or_click_ring(drawing_app):
    page = drawing_app
    open_drawing(page)
    name = page.get_by_label('绘图名称', exact=True)
    name.click()
    assert no_ring(name)['border'] != 'rgb(59, 130, 246)'
    red = page.get_by_label('关闭绘图', exact=True)
    assert no_ring(red)['background'] == 'rgb(239, 68, 68)'
    assert red.evaluate('e=>getComputedStyle(e).borderTopWidth') == '0px'
    page.get_by_role('button', name='历史绘图', exact=True).click()
    assert page.get_by_label('关闭历史绘图', exact=True).count() == 0
    remove = page.locator('.ddw-history-delete').first
    assert no_ring(remove)['background'] == 'rgb(239, 68, 68)'
    page.keyboard.press('Escape')
    assert page.locator('#graphEditorDialog').evaluate('e=>e.open')
    assert page.locator('.ddw-side-panel').is_hidden()
    assert page.get_by_role('button', name='历史绘图', exact=True).is_visible()
