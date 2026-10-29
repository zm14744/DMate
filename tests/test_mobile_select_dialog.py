"""Mobile selectors reuse the module chooser above the native editor."""
import os
import re
import shutil
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_mobile_choices_are_modal_cancel_safe_and_leave_desktop_selects_native():
    executable = os.environ.get('DMATE_BROWSER_EXECUTABLE') or shutil.which('chromium')
    if not executable:
        pytest.skip('Chromium unavailable')
    playwright = pytest.importorskip('playwright.sync_api')
    html = (ROOT / 'templates/index.html').read_text()
    source = (ROOT / 'static/script.js').read_text()
    chooser = '<dialog id="mobileChoiceModal"' + html.split('<dialog id="mobileChoiceModal"', 1)[1].split('</dialog>', 1)[0] + '</dialog>'
    helpers = source[source.index('function setMobileChoiceOpen('):source.index('// 删除标记保留')]
    handlers = source[source.index('        mobileChoiceClose?.addEventListener'):
                      source.index('        document.addEventListener("keydown", event =>', source.index('        mobileChoiceClose?.addEventListener'))]
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(executable_path=executable, headless=True)
        page = browser.new_page(viewport={'width': 390, 'height': 844}, has_touch=True)
        page.set_default_timeout(4000)
        page.route('**/*', lambda route: route.abort())
        page.set_content('''<dialog id="editor"><label>绘图方向<select aria-label="绘图方向">
          <option value="no">无向</option><option value="yes">有向</option></select></label>
          <label>绘图权值<select aria-label="绘图权值"><option value="no">无权</option>
          <option value="yes">带权</option></select></label></dialog>''' + chooser)
        page.add_style_tag(content='\n'.join(re.findall(r'<style[^>]*>([\s\S]*?)</style>', html)))
        page.add_script_tag(content='''let mobileChoiceResolver=null,mobileChoiceOptions=[],mobileChoiceOpenVersion=0;
          function escapeRawHtml(text){const span=document.createElement('span');span.textContent=text;return span.innerHTML;}
          const mobileChoiceModal=document.getElementById('mobileChoiceModal');
          const mobileChoiceClose=document.getElementById('mobileChoiceClose');
        ''' + helpers + handlers)
        page.add_script_tag(content=(ROOT / 'static/mobile-select.js').read_text())
        page.evaluate('''()=>{window.events=[];const editor=document.getElementById('editor');
          for(const kind of ['input','change'])editor.addEventListener(kind,e=>events.push(e.type));
          window.parentEscapes=0;window.parentOutside=0;
          document.addEventListener('keydown',e=>{if(e.key==='Escape'){parentEscapes++;e.preventDefault();}},true);
          document.addEventListener('pointerdown',e=>{if(e.target.closest('#mobileChoiceModal'))parentOutside++;},true);
          editor.showModal();}''')
        page.locator('#editor').get_by_label('绘图方向', exact=True).tap()
        page.wait_for_function('mobileChoiceModal.open&&!mobileChoiceModal.hasAttribute("data-positioning")')
        card = page.locator('#mobileChoiceModal .mobile-choice-card')
        assert card.evaluate('el=>getComputedStyle(el).borderRadius') == '18px'
        box = card.bounding_box()
        assert 0 <= box['x'] and box['x'] + box['width'] <= 390
        assert 0 <= box['y'] and box['y'] + box['height'] <= 844
        assert page.get_by_role('radio', name='无向', exact=True).get_attribute('aria-checked') == 'true'
        page.get_by_role('radio', name='有向', exact=True).tap()
        page.wait_for_function('document.querySelector("select").value==="yes"')
        assert page.evaluate('events') == ['input', 'change']
        assert page.evaluate('parentOutside') == 0
        assert page.evaluate('document.getElementById("editor").open')
        page.locator('#editor').get_by_label('绘图权值', exact=True).tap()
        page.wait_for_function('mobileChoiceModal.open&&!mobileChoiceModal.hasAttribute("data-positioning")')
        page.keyboard.press('Escape')
        assert page.locator('#editor').get_by_label('绘图权值', exact=True).input_value() == 'no'
        assert page.evaluate('document.getElementById("editor").open&&!mobileChoiceModal.open')
        assert page.evaluate('parentEscapes') == 0
        page.locator('#editor').get_by_label('绘图方向', exact=True).tap()
        page.evaluate('document.querySelector("select").remove()')
        page.wait_for_function('!mobileChoiceModal.open')
        # The original knowledge-graph entry uses this exact same chooser.
        page.evaluate('''()=>{document.getElementById('editor').close();
          openMobileChoiceModal({title:'旧选项',options:[{value:'old'}]});closeMobileChoiceModal();
          window.choice=openMobileChoiceModal({title:'选择知识图谱模块',value:'集合',
            options:[{value:'集合'},{value:'关系'}]}).then(value=>window.chosen=value);}''')
        page.wait_for_function('mobileChoiceModal.open&&!mobileChoiceModal.hasAttribute("data-positioning")')
        page.get_by_role('radio', name='关系', exact=True).tap()
        page.wait_for_function('window.chosen?.value==="关系"')
        page.set_viewport_size({'width': 1280, 'height': 900})
        assert page.evaluate('''()=>{const select=document.createElement('select');
          select.add(new Option('A','a'));document.body.append(select);
          const event=new PointerEvent('pointerdown',{bubbles:true,cancelable:true});
          select.dispatchEvent(event);return !event.defaultPrevented&&!mobileChoiceModal.open;}''')
        browser.close()
