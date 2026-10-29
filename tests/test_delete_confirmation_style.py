"""Deletion confirmations share the notebook's real red action button."""
import io
from pathlib import Path

import pytest

from test_appearance_surfaces import appearance_page, install_appearance

ROOT = Path(__file__).resolve().parents[1]


def button_paint(button):
    return button.evaluate('''e=>{
      const s=getComputedStyle(e),r=e.getBoundingClientRect();
      return {background:s.backgroundColor,color:s.color,textFill:s.webkitTextFillColor,
        border:s.borderTopColor,radius:s.borderTopLeftRadius,font:s.fontFamily,
        size:s.fontSize,weight:s.fontWeight,padding:s.padding,line:s.lineHeight,
        minHeight:s.minHeight,minWidth:s.minWidth,filter:s.filter,width:r.width,height:r.height};
    }''')


def install_shared_confirmation(page):
    script = (ROOT / 'static/script.js').read_text()
    helpers = script[script.index('function setAppConfirmOpen('):script.index('function closeMobileChoiceModal(')]
    events = script[script.index('        appConfirmClose?.addEventListener("click"'):script.index('        mobileChoiceClose?.addEventListener("click"')]
    page.add_script_tag(content='''
      var appConfirmResolver=null;
      const appConfirmModal=document.getElementById('appConfirmModal');
      const appConfirmClose=document.getElementById('appConfirmClose');
      const appConfirmConfirm=document.getElementById('appConfirmConfirm');
    ''' + helpers + events)


@pytest.mark.parametrize('theme', ['light', 'dark', 'navy'])
def test_shared_delete_buttons_match_real_notebook_and_resolve_actions(appearance_page, theme):
    page = appearance_page
    install_appearance(page)
    page.evaluate('''theme=>{appearanceSettings.mode=theme;applyAppearanceSettings({save:false});}''', theme)
    page.add_script_tag(content=(ROOT / 'static/concept-notebook.js').read_text())
    page.evaluate('''()=>{
      window.notes={notes:[{id:'kept',title:'集合',content:'保留的概念',updatedAt:1}],deleted:{}};
      window.notebook=DMateConceptNotebook.mount({
        button:document.getElementById('conceptNotebookBtn'),dialog:document.getElementById('conceptNotebookDialog'),
        getState:()=>structuredClone(notes),onChange:state=>notes=structuredClone(state),getContextKey:()=> 'same-user'});
      notebook.open();
    }''')
    page.get_by_role('button', name='删除概念：集合', exact=True).click()
    reference = button_paint(page.get_by_role('button', name='删除概念', exact=True))
    assert reference['background'] == reference['border'] == 'rgb(220, 38, 38)'
    assert reference['color'] == reference['textFill'] == 'rgb(255, 255, 255)'
    assert reference['height'] >= 42 and reference['width'] >= 90
    assert reference['radius'] == '10px' and reference['weight'] == '600'
    page.get_by_role('button', name='取消删除', exact=True).click()
    page.get_by_role('button', name='关闭笔记本', exact=True).click()
    assert page.evaluate('notes.notes.length') == 1
    install_shared_confirmation(page)

    for title, confirm_text, outcome in [
        ('删除这段对话？', '删除对话', 'close'),
        ('删除消息', '删除', 'backdrop'),
        ('移出错题本', '移出', 'confirm'),
    ]:
        page.evaluate('''({title,confirmText})=>{
          window.confirmOutcome='pending';showAppConfirm({title,
            body:'这段对话产生的学习统计会同步删除；已经加入错题本的题目仍会保留。',
            confirmText,confirmTone:'danger'}).then(result=>confirmOutcome=result);
        }''', {'title': title, 'confirmText': confirm_text})
        button = page.get_by_role('button', name=confirm_text, exact=True)
        button.wait_for(state='visible')
        page.locator('#appConfirmModal .app-confirm-card').evaluate(
            'e=>Promise.all(e.getAnimations().map(animation=>animation.finished.catch(()=>{})))')
        page.mouse.move(0, 0)
        current = button_paint(button)
        for key in ['background', 'color', 'textFill', 'border', 'radius', 'font', 'size', 'weight', 'padding', 'line', 'minHeight', 'minWidth', 'filter']:
            assert current[key] == reference[key], (theme, key, current, reference)
        assert current['height'] >= 42 and current['width'] >= 90
        assert button.evaluate('''e=>{
          const a=e.getBoundingClientRect(),b=e.closest('.app-confirm-card').getBoundingClientRect();
          return a.left>=b.left+12&&a.right<=b.right-12&&a.bottom<=b.bottom-12;
        }''')
        button.hover()
        assert button_paint(button)['background'] == 'rgb(185, 28, 28)'
        page.mouse.move(0, 0)
        button.evaluate('e=>e.disabled=true')
        assert button_paint(button)['background'] == 'rgb(220, 38, 38)'
        button.evaluate('e=>e.disabled=false')
        if title == '删除这段对话？':
            page.locator('#appConfirmModal .app-confirm-card').screenshot(
                path=f'/tmp/dmate-delete-action-{theme}-{page.viewport_size["width"]}.png')
        if outcome == 'close':
            page.locator('#appConfirmClose').click()
        elif outcome == 'backdrop':
            page.locator('#appConfirmModal').click(position={'x': 1, 'y': 1})
        else:
            button.click()
        page.wait_for_function('confirmOutcome!=="pending"')
        assert page.evaluate('confirmOutcome') is (outcome == 'confirm')
        assert page.locator('#appConfirmModal').is_hidden()

    # Inspect the existing account confirmation DOM without loading account
    # handlers or invoking any account operation. Its cancel action and grid
    # remain intact while the destructive action shares the same button paint.
    page.evaluate('''()=>{
      for(let node=document.getElementById('accountDeletePanel');node;node=node.parentElement)
        node.classList.remove('hidden');
    }''')
    account_button = page.locator('#accountDeleteConfirm')
    account_button.scroll_into_view_if_needed()
    page.mouse.move(0, 0)
    account = button_paint(account_button)
    for key in ['background', 'color', 'textFill', 'border', 'radius', 'font', 'size', 'weight', 'padding', 'line', 'minHeight', 'minWidth', 'filter']:
        assert account[key] == reference[key], (theme, key, account, reference)
    assert page.locator('.account-delete-actions').evaluate('e=>getComputedStyle(e).display') == 'grid'
    assert page.locator('#accountDeleteCancel').is_visible()
    assert page.locator('#accountDeleteCancel').evaluate('e=>getComputedStyle(e).backgroundColor') != account['background']
    image_module = pytest.importorskip('PIL.Image')
    for hover, color in [(False, (220, 38, 38)), (True, (185, 28, 28))]:
        if hover:
            account_button.hover()
        assert button_paint(account_button)['background'] == 'rgb' + str(color)
        pixels = image_module.open(io.BytesIO(account_button.screenshot(animations='disabled'))).convert('RGB')
        assert pixels.getpixel((pixels.width // 2, 3)) == color
    page.evaluate("document.getElementById('accountModal').classList.add('hidden')")

    # The drawing/scan confirmation is a native dialog above the already-open
    # editor. Its action must use the same paint and hit target as the notebook.
    page.add_script_tag(content=(ROOT / 'static/delete-confirm.js').read_text())
    page.evaluate('''()=>{
      const editor=document.getElementById('graphEditorDialog');
      const owner=document.getElementById('graphEditorMount');
      owner.classList.add('dmate-graph-editor');editor.showModal();
      window.nativeConfirmOutcome='pending';DMateDeleteConfirm.request(owner,{
        title:'删除这个文字框？',body:'删除后无法恢复。',confirmText:'删除文字框'
      }).then(result=>nativeConfirmOutcome=result);
    }''')
    native_button = page.get_by_role('button', name='删除文字框', exact=True)
    native_button.wait_for(state='visible')
    actual = button_paint(native_button)
    for key in ['background', 'color', 'textFill', 'border', 'radius', 'font', 'size', 'weight', 'padding', 'line', 'minHeight', 'minWidth', 'filter']:
        assert actual[key] == reference[key], (theme, key, actual, reference)
    assert native_button.evaluate('''e=>{
      const r=e.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===e;
    }''')
    close = page.get_by_role('button', name='取消删除', exact=True)
    assert close.evaluate('''e=>{
      const r=e.getBoundingClientRect(),s=getComputedStyle(e);
      return r.width===20&&r.height===20&&s.borderRadius==='50%'&&s.backgroundColor==='rgb(239, 68, 68)';
    }''')
    close.click()
    page.wait_for_function('nativeConfirmOutcome!=="pending"')
    assert page.evaluate('nativeConfirmOutcome') is False
    assert page.locator('#graphEditorDialog').evaluate('e=>e.open')
