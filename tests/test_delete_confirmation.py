"""Nested deletion prompts use one stable modal and cancel with their owner."""
from pathlib import Path

import pytest

from test_appearance_surfaces import appearance_page, install_appearance

ROOT = Path(__file__).resolve().parents[1]


def install_confirmation(page, theme='dark'):
    install_appearance(page)
    page.evaluate('''theme=>{
      appearanceSettings.mode=theme;applyAppearanceSettings({save:false});
      const parent=document.getElementById('graphEditorDialog');
      document.getElementById('graphEditorMount').innerHTML='<button id="confirmTrigger">删除入口</button><section id="confirmOwner"></section>';
      parent.showModal();window.confirmResults=[];
    }''', theme)
    page.add_script_tag(content=(ROOT / 'static/delete-confirm.js').read_text())
    page.evaluate(r'''()=>{
      window.confirmOwner=document.getElementById('confirmOwner');
      document.getElementById('confirmTrigger').onclick=()=>DMateDeleteConfirm.request(confirmOwner,{
        title:'删除这个绘图？',body:'删除后无法恢复。\n绘图 1',confirmText:'删除绘图'
      }).then(value=>confirmResults.push(value));
    }''')


@pytest.mark.parametrize('theme', ['light', 'dark', 'navy'])
def test_nested_delete_prompt_is_centered_before_visible_and_has_reference_actions(appearance_page, theme):
    page = appearance_page
    install_confirmation(page, theme)
    page.evaluate('''()=>{
      window.confirmOpening=[];window.confirmFrames=[];window.recordConfirm=true;
      const show=HTMLDialogElement.prototype.showModal;
      HTMLDialogElement.prototype.showModal=function(){
        show.call(this);
        if(this.classList.contains('dmate-delete-confirm'))confirmOpening.push({
          visible:getComputedStyle(this).visibility,
          visibleChildren:[...this.querySelectorAll('*')].filter(n=>getComputedStyle(n).visibility==='visible').length
        });
      };
      function record(){const dialog=document.querySelector('.dmate-delete-confirm');
        if(dialog&&getComputedStyle(dialog).visibility==='visible'){
          const r=dialog.getBoundingClientRect();confirmFrames.push([r.x,r.y,r.width,r.height]);
        }if(recordConfirm)requestAnimationFrame(record);
      }requestAnimationFrame(record);
    }''')
    page.get_by_role('button', name='删除入口', exact=True).click()
    prompt = page.get_by_role('dialog', name='删除这个绘图？', exact=True)
    page.wait_for_function('confirmFrames.length>=8')
    assert page.evaluate('confirmOpening') == [{'visible': 'hidden', 'visibleChildren': 0}]
    frames = page.evaluate('confirmFrames')
    for x, y, width, height in frames:
        assert abs(x + width / 2 - page.viewport_size['width'] / 2) < 1
        assert abs(y + height / 2 - page.viewport_size['height'] / 2) < 1
        assert [x, y, width, height] == pytest.approx(frames[0], abs=1)
    close = prompt.get_by_role('button', name='取消删除', exact=True)
    delete = prompt.get_by_role('button', name='删除绘图', exact=True)
    assert prompt.get_by_role('button', name='取消', exact=True).count() == 0
    assert close.inner_text() == ''
    assert close.evaluate('e=>getComputedStyle(e).backgroundColor') == 'rgb(239, 68, 68)'
    assert delete.evaluate('''e=>{const s=getComputedStyle(e);return s.backgroundColor==='rgb(220, 38, 38)'
      &&s.color==='rgb(255, 255, 255)'&&parseFloat(s.borderRadius)>=10&&parseFloat(s.paddingLeft)>=14;}''')
    assert delete.bounding_box()['height'] >= 42
    assert close.evaluate('e=>e===document.activeElement')
    prompt.screenshot(path=f'/tmp/dmate-delete-confirm-{theme}-{page.viewport_size["width"]}.png')
    close.click()
    assert page.evaluate('confirmResults') == [False]
    page.wait_for_function('document.activeElement.id==="confirmTrigger"')
    page.locator('#confirmTrigger').click()
    prompt.wait_for(state='visible')
    page.keyboard.press('Tab')
    assert delete.evaluate('e=>e===document.activeElement')
    page.keyboard.press('Enter')
    assert page.evaluate('confirmResults') == [False, True]
    assert page.locator('.dmate-delete-confirm').count() == 0
    page.evaluate('recordConfirm=false')


def test_replacement_parent_close_and_explicit_cancel_resolve_once(appearance_page):
    page = appearance_page
    install_confirmation(page)
    page.locator('#confirmTrigger').click()
    page.get_by_role('dialog', name='删除这个绘图？', exact=True).wait_for(state='visible')
    page.evaluate('''()=>{DMateDeleteConfirm.request(confirmOwner,{
      title:'第二个删除请求',confirmText:'删除第二项'
    }).then(value=>confirmResults.push(value));}''')
    page.get_by_role('dialog', name='第二个删除请求', exact=True).wait_for(state='visible')
    assert page.evaluate('confirmResults') == [False]
    assert page.locator('.dmate-delete-confirm').count() == 1
    page.evaluate("document.getElementById('graphEditorDialog').close()")
    page.wait_for_function('confirmResults.length===2')
    assert page.evaluate('confirmResults') == [False, False]
    assert page.locator('.dmate-delete-confirm').count() == 0
    page.evaluate('''()=>{
      document.getElementById('graphEditorDialog').showModal();
      DMateDeleteConfirm.request(confirmOwner,{title:'手动取消'}).then(value=>confirmResults.push(value));
      DMateDeleteConfirm.cancel(confirmOwner);DMateDeleteConfirm.cancel(confirmOwner);
    }''')
    assert page.evaluate('confirmResults') == [False, False, False]
    assert page.locator('.dmate-delete-confirm').count() == 0
