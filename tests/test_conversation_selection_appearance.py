"""The current chat stays visible while idle rows merge into every sidebar."""
import io
from pathlib import Path

import pytest

from test_appearance_surfaces import appearance_page, install_appearance

ROOT = Path(__file__).resolve().parents[1]


def install_conversations(page):
    source = (ROOT / 'static/script.js').read_text()
    render = source[source.index('function renderSessions()'):source.index('function uniqueTextList(')]
    page.add_script_tag(content='''
      var sessions=[{id:'older',name:'较早对话',messages:[]},
        {id:'current',name:'当前对话',messages:[]},{id:'later',name:'另一对话',messages:[]}];
      var currentId='current',typingTimer=null,mobileSessionTapTimer=0,
        mobileSessionTapId='',mobileSessionTapAt=0,mobileSessionLastTouchAt=0;
      var refreshUnnamedSessionNames=()=>{},pauseOcrBatchRun=()=>{},saveState=()=>{};
      var isMobileAppShell=()=>innerWidth<=1100,animateMobileConversationSwitch=()=>{},
        closeMobileShellDrawers=()=>{},renderAll=()=>renderSessions();
    ''' + render + '''
      document.body.classList.add('mobile-left-open');renderSessions();
    ''')
    page.wait_for_function("document.querySelector('.left').getBoundingClientRect().left>=-1")


def row_style(row):
    return row.evaluate('''e=>{
      const s=getComputedStyle(e);return {background:s.backgroundColor,image:s.backgroundImage,
        border:s.borderTopColor,shadow:s.boxShadow,radius:parseFloat(s.borderRadius),
        before:getComputedStyle(e,'::before').content,after:getComputedStyle(e,'::after').content};
    }''')


def assert_sidebar_pixels(page):
    image_module = pytest.importorskip('PIL.Image')
    image = image_module.open(io.BytesIO(page.screenshot()))
    for row in page.locator('#sessions .session').all():
        bounds = row.bounding_box()
        x, y = round(bounds['x']), round(bounds['y'] + bounds['height'] / 2)
        fill, sidebar = image.getpixel((x + 5, y)), image.getpixel((x - 3, y))
        distance = max(abs(a - b) for a, b in zip(fill[:3], sidebar[:3]))
        if row.get_attribute('aria-current') == 'true':
            # Actual composited pixels must visibly differ from the sidebar,
            # including the low-alpha panel setting and the mobile drawer.
            assert distance >= 24, (page.viewport_size, fill, sidebar)
        else:
            assert distance <= 1, (page.viewport_size, fill, sidebar)


@pytest.mark.parametrize('theme', ['light', 'dark', 'navy'])
@pytest.mark.parametrize('panel_opacity', [75, 100])
def test_selection_is_distinct_without_idle_row_boxes(appearance_page, theme, panel_opacity):
    page = appearance_page
    install_appearance(page)
    page.evaluate('''({theme,panelOpacity})=>{
      appearanceSettings.mode=theme;appearanceSettings.panelOpacity=panelOpacity;
      applyAppearanceSettings({save:false});
    }''', {'theme': theme, 'panelOpacity': panel_opacity})
    install_conversations(page)
    page.mouse.move(0, 0)
    selected = page.locator('#sessions [aria-current="true"]')
    assert selected.get_attribute('data-session-id') == 'current'
    selected_fill = row_style(selected)['background']
    assert selected_fill != 'rgba(0, 0, 0, 0)'
    if theme == 'dark':
        assert selected_fill == 'rgb(61, 61, 61)'
    for row in page.locator('#sessions .session').all():
        style = row_style(row)
        assert style['border'] == 'rgba(0, 0, 0, 0)' and style['shadow'] == 'none'
        assert style['radius'] >= 8
        if row.get_attribute('aria-current') != 'true':
            assert style['background'] == 'rgba(0, 0, 0, 0)' and style['image'] == 'none'
    assert_sidebar_pixels(page)

    # A hover/focused delete control must not hide the persistent current fill.
    page.locator('[data-session-id="later"] span').hover()
    assert row_style(selected)['background'] == selected_fill
    selected.get_by_role('button', name='删除这个对话').focus()
    assert row_style(selected)['background'] == selected_fill
    assert selected.get_by_role('button', name='删除这个对话').evaluate(
        'e=>getComputedStyle(e).backgroundColor') == 'rgb(239, 68, 68)'

    # Use the actual session click/tap handler: selection must move cleanly,
    # leaving the former current chat without a stale filled card or border.
    page.locator('[data-session-id="older"] span').click()
    page.wait_for_function("document.querySelector('#sessions [aria-current=true]')?.dataset.sessionId==='older'")
    page.mouse.move(0, 0)
    assert page.locator('#sessions [aria-current="true"]').count() == 1
    assert row_style(page.locator('[data-session-id="current"]'))['background'] == 'rgba(0, 0, 0, 0)'
    assert_sidebar_pixels(page)
    if panel_opacity == 100:
        page.locator('.left').screenshot(path=f'/tmp/dmate-session-{theme}-{page.viewport_size["width"]}.png')
