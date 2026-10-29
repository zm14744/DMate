"""Inline sidebar text stays bare and both searches use real red clear buttons."""
from pathlib import Path

import pytest

from test_appearance_surfaces import appearance_page, install_appearance, paint

ROOT = Path(__file__).resolve().parents[1]


def assert_red_clear(button):
    button.page.mouse.move(0, 0)
    style = button.evaluate('''e=>{
      const s=getComputedStyle(e),r=e.getBoundingClientRect();
      return {color:s.backgroundColor,image:s.backgroundImage,radius:s.borderRadius,
        border:s.borderTopWidth,width:r.width,height:r.height,text:e.textContent,
        before:getComputedStyle(e,'::before').content,after:getComputedStyle(e,'::after').content};
    }''')
    assert style == {'color': 'rgb(239, 68, 68)', 'image': 'none', 'radius': '50%',
                     'border': '0px', 'width': 18, 'height': 18, 'text': '',
                     'before': 'none', 'after': 'none'}


def test_sidebar_info_text_has_no_independent_background_in_any_theme(appearance_page):
    page = appearance_page
    install_appearance(page)
    page.evaluate('document.querySelector("#info").textContent="无";document.body.classList.add("mobile-tools-open")')
    for theme in ['light', 'dark', 'navy']:
        for wallpaper in [False, True]:
            for amount in [100, 75]:
                page.evaluate('''({theme,wallpaper,amount})=>{
                  appearanceSettings.mode=theme;appearanceSettings.panelOpacity=amount;
                  document.body.classList.toggle('has-custom-background',wallpaper);applyAppearanceSettings();
                }''', {'theme': theme, 'wallpaper': wallpaper, 'amount': amount})
                info = paint(page, '#info')
                assert info['alpha'] == 0 and info['image'] == 'none'
                assert info['opacity'] == '1'
                assert page.locator('#info').evaluate('''e=>{
                  const s=getComputedStyle(e);return [s.borderTopWidth,s.borderRadius,s.boxShadow,s.padding];
                }''') == ['0px', '0px', 'none', '0px']
                assert page.locator('#info').inner_text() == '无'
                assert paint(page, '.right')['alpha'] == amount / 100
    assert page.locator('.learning-panel').evaluate('e=>getComputedStyle(e).borderTopWidth') == '1px'


@pytest.mark.parametrize('theme', ['light', 'dark', 'navy'])
def test_notebook_clear_is_an_accessible_red_circle_and_restores_filtered_notes(appearance_page, theme):
    page = appearance_page
    install_appearance(page)
    page.evaluate('theme=>{appearanceSettings.mode=theme;applyAppearanceSettings();}', theme)
    page.add_script_tag(content=(ROOT / 'static/concept-notebook.js').read_text())
    page.evaluate('''()=>{
      window.notes={notes:[{id:'a',title:'集合',content:'概念一',updatedAt:1},
        {id:'b',title:'关系',content:'概念二',updatedAt:2}],deleted:{}};
      window.notebook=DMateConceptNotebook.mount({button:document.querySelector('#conceptNotebookBtn'),
        dialog:document.querySelector('#conceptNotebookDialog'),getState:()=>structuredClone(notes),
        onChange:value=>notes=value,getContextKey:()=> 'alice'});notebook.open();
    }''')
    dialog = page.locator('#conceptNotebookDialog')
    search = dialog.get_by_role('searchbox', name='搜索', exact=True)
    clear = dialog.get_by_role('button', name='清空搜索', exact=True)
    assert clear.is_hidden()
    assert search.evaluate('e=>getComputedStyle(e).fontSize') == '14px'
    dialog.get_by_role('checkbox', name='选择概念：集合', exact=True).check()
    original = page.evaluate('structuredClone(notes)')
    for keyboard in [False, True]:
        search.fill('关键时glj')
        assert clear.is_visible()
        assert dialog.locator('.dcn-list').inner_text() == '没有匹配的概念。'
        assert_red_clear(clear)
        field, button = search.bounding_box(), clear.bounding_box()
        assert field['x'] < button['x'] < button['x'] + button['width'] < field['x'] + field['width']
        assert field['y'] < button['y'] < button['y'] + button['height'] < field['y'] + field['height']
        if keyboard:
            clear.focus()
            clear.press('Space')
        else:
            clear.click()
        assert search.input_value() == '' and clear.is_hidden()
        assert search.evaluate('e=>document.activeElement===e')
        assert dialog.locator('.dcn-note').count() == 2
        assert dialog.get_by_role('checkbox', name='选择概念：集合', exact=True).is_checked()
        assert page.evaluate('notes') == original
    page.get_by_role('button', name='关闭笔记本', exact=True).click()
    page.evaluate('notebook.open()')
    assert clear.is_hidden()


@pytest.mark.parametrize('theme', ['light', 'dark', 'navy'])
def test_wrongbook_existing_clear_button_stays_red_and_keeps_native_clear_handler(appearance_page, theme):
    page = appearance_page
    install_appearance(page)
    page.evaluate('theme=>{appearanceSettings.mode=theme;applyAppearanceSettings();}', theme)
    script = (ROOT / 'static/script.js').read_text()
    start = script.index('        if (wrongBookSearchBox) {', script.index('const wrongBookSearchClear ='))
    handlers = script[start:script.index('        if (wrongBookSortBox) {', start)]
    # Bind the app's actual input and clear listeners; list rendering is outside
    # this visual regression and is recorded rather than booting the backend.
    page.add_script_tag(content='''
      const wrongBookSearchBox=document.querySelector('#wrongBookSearch');
      const wrongBookSearchClear=document.querySelector('#wrongBookSearchClear');
      window.searches=[];window.setWrongBookSearch=value=>searches.push(value);
    ''' + handlers)
    page.evaluate('document.querySelector("#wrongBookModal").classList.remove("hidden")')
    search, clear = page.locator('#wrongBookSearch'), page.locator('#wrongBookSearchClear')
    assert clear.is_hidden()
    search.fill('关键时glj')
    assert_red_clear(clear)
    clear.click()
    assert search.input_value() == '' and clear.is_hidden()
    assert search.evaluate('e=>document.activeElement===e')
    assert page.evaluate('searches') == ['关键时glj', '']
