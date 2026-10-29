"""Concept notes remain editable originals; AI reads only explicit selections."""
import json
import os
import re
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=[(1440, 900), (390, 844)])
def notebook_page(request):
    chromium = os.environ.get('DMATE_BROWSER_EXECUTABLE') or shutil.which('chromium')
    if not chromium:
        pytest.skip('Chromium unavailable')
    pw = pytest.importorskip('playwright.sync_api')
    html = (ROOT / 'templates/index.html').read_text()
    styles = '\n'.join(re.findall(r'<style[^>]*>([\s\S]*?)</style>', html))
    with pw.sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=chromium, headless=True)
        page = browser.new_page(viewport={'width': request.param[0], 'height': request.param[1]})
        page.route('**/*', lambda route: route.fulfill(body='<html></html>', content_type='text/html'))
        page.goto('https://dmate.test/')
        page.set_content('''<body data-appearance-theme="light"><button id="conceptNotebookBtn">笔记本</button>
        <dialog id="conceptNotebookDialog"></dialog></body>''')
        page.add_style_tag(content=styles)
        page.add_style_tag(content=(ROOT / 'static/concept-notebook.css').read_text())
        page.add_script_tag(content='''window.contextKey='alice';window.persistent=true;window.changes=[];window.calls=[];
        window.stored={notes:[{id:'set',title:'集合',content:'集合是一组对象。',updatedAt:1},
            {id:'relation',title:'关系',content:'关系是笛卡尔积的子集。',updatedAt:2}],deleted:{}};
        window.getReply=body=>({ok:true,action:body.action,notes_digest:'a'.repeat(64),
            explanations:body.notes.map(n=>({note_id:n.id,explanation:window.responseText||n.title+'的AI解释。'})),
            relations:body.action==='relations'?[{from:body.notes[0].id,to:body.notes[1].id,type:'定义基础',explanation:'关系的定义以集合为基础。'}]:[],summary:'所选概念分析'});
        window.transport=async(url,options)=>{
            const body=JSON.parse(options.body);calls.push({url,body});
            if(window.hold)return new Promise(resolve=>{
                window.reply=()=>resolve({ok:true,json:async()=>getReply(body)});
                options.signal.addEventListener('abort',()=>window.aborted=true);
            });
            return {ok:!window.fail,json:async()=>window.fail?{ok:false,error:'AI服务暂时不可用。'}:getReply(body)};
        };
        ''')
        page.add_script_tag(content=(ROOT / 'static/concept-notebook.js').read_text())
        page.evaluate('''()=>{window.notebook=DMateConceptNotebook.mount({
            button:document.getElementById('conceptNotebookBtn'),dialog:document.getElementById('conceptNotebookDialog'),
            getState:()=>structuredClone(stored),onChange:value=>{
                if(window.saveFailure)throw new Error('本地存储空间不足，尚未保存。');
                changes.push(value);stored=structuredClone(value);
            },getContextKey:()=>contextKey,isPersistent:()=>persistent,fetch:transport});}''')
        yield page
        browser.close()


def open_notebook(page):
    page.get_by_role('button', name='笔记本', exact=True).click()
    assert page.locator('#conceptNotebookDialog').is_visible()


def select_both(page):
    page.get_by_role('checkbox', name='选择概念：集合', exact=True).check()
    page.get_by_role('checkbox', name='选择概念：关系', exact=True).check()


def test_notes_autosave_reopen_and_relation_analysis_does_not_modify_original(notebook_page):
    p = notebook_page
    open_notebook(p)
    p.get_by_label('我的概念笔记', exact=True).fill('集合是一组确定的对象。\n例如 A={1,2}。')
    assert p.locator('.dcn-saved').inner_text() == ''
    assert p.evaluate('stored.notes[0].content') == '集合是一组确定的对象。\n例如 A={1,2}。'
    p.get_by_role('button', name='关闭笔记本', exact=True).click()
    open_notebook(p)
    assert p.get_by_label('我的概念笔记', exact=True).input_value() == '集合是一组确定的对象。\n例如 A={1,2}。'
    select_both(p)
    before = p.evaluate('structuredClone(stored)')
    p.get_by_label('补充要求（可选）', exact=True).fill('请给一个具体例子。')
    p.get_by_role('button', name='分析关联', exact=True).click()
    p.wait_for_function('calls.length===1 && document.querySelector(".dcn-relation")')
    sent = p.evaluate('calls[0]')
    assert sent['url'] == '/notebook/analyze'
    assert sent['body'] == {'action': 'relations', 'notes': [
        {'id': 'set', 'title': '集合', 'content': before['notes'][0]['content']},
        {'id': 'relation', 'title': '关系', 'content': before['notes'][1]['content']}], 'question': '请给一个具体例子。'}
    assert p.evaluate('stored') == before
    assert p.locator('.dcn-relation').inner_text().startswith('集合 → 关系 · 定义基础')
    if p.viewport_size['width'] == 1440:
        p.screenshot(path='/tmp/concept-notebook-desktop.png')
    else:
        p.screenshot(path='/tmp/concept-notebook-mobile.png')
    dialog = p.locator('#conceptNotebookDialog').bounding_box()
    assert dialog['x'] >= 0 and dialog['x'] + dialog['width'] <= p.viewport_size['width']
    assert p.locator('#conceptNotebookDialog').evaluate('n=>n.scrollWidth<=n.clientWidth')


def test_ai_reads_only_selected_note_and_renders_untrusted_text_without_markup(notebook_page):
    p = notebook_page
    open_notebook(p)
    p.get_by_role('checkbox', name='选择概念：集合', exact=True).check()
    payload = '<img src=x onerror="window.injected=true"><script>window.injected=true</script>'
    p.evaluate('(text)=>window.responseText=text', payload)
    p.get_by_role('button', name='AI 解释', exact=True).click()
    p.wait_for_function('calls.length===1 && document.querySelector(".dcn-explanation")')
    assert [n['id'] for n in p.evaluate('calls[0].body.notes')] == ['set']
    assert p.locator('.dcn-ai-text').inner_text() == payload
    assert p.locator('.dcn-results script,.dcn-results img').count() == 0
    assert not p.evaluate('!!window.injected')
    assert p.get_by_label('我的概念笔记', exact=True).input_value() == '集合是一组对象。'


def test_edit_selection_and_close_ignore_late_analysis(notebook_page):
    p = notebook_page
    open_notebook(p)
    p.get_by_role('checkbox', name='选择概念：集合', exact=True).check()
    p.evaluate('window.hold=true')
    p.get_by_role('button', name='AI 解释', exact=True).click()
    p.wait_for_function('calls.length===1')
    p.get_by_label('我的概念笔记', exact=True).fill('用户已修改原文')
    assert p.evaluate('window.aborted')
    p.evaluate('reply()')
    assert p.locator('.dcn-results').inner_text() == ''
    assert p.evaluate('stored.notes[0].content') == '用户已修改原文'
    p.get_by_role('button', name='AI 解释', exact=True).click()
    p.wait_for_function('calls.length===2')
    p.get_by_role('checkbox', name='选择概念：集合', exact=True).uncheck()
    p.evaluate('reply()')
    assert p.locator('.dcn-results').inner_text() == ''
    p.get_by_role('checkbox', name='选择概念：关系', exact=True).check()
    p.get_by_role('button', name='AI 解释', exact=True).click()
    p.wait_for_function('calls.length===3')
    p.get_by_role('button', name='关闭笔记本', exact=True).click()
    p.evaluate('reply()')
    open_notebook(p)
    assert p.locator('.dcn-results').inner_text() == ''


def test_new_note_explicit_selection_confirmed_delete_and_search(notebook_page):
    p = notebook_page
    open_notebook(p)
    assert p.locator('input[type=checkbox]:checked').count() == 0
    assert p.get_by_role('button', name='AI 解释', exact=True).is_disabled()
    p.get_by_role('button', name='新建概念', exact=True).click()
    p.get_by_label('概念名称', exact=True).fill('偏序关系')
    assert not p.get_by_role('checkbox', name='选择概念：偏序关系', exact=True).is_checked()
    p.get_by_role('checkbox', name='选择概念：偏序关系', exact=True).check()
    p.get_by_role('button', name='AI 解释', exact=True).click()
    p.wait_for_function('calls.length===1')
    assert p.evaluate('calls[0].body.notes[0].title') == '偏序关系'
    assert p.evaluate('calls[0].body.notes[0].content') == ''
    identifier = p.evaluate('stored.notes[0].id')
    p.get_by_label('搜索概念', exact=True).fill('偏序')
    assert p.locator('.dcn-note').count() == 1
    p.get_by_role('button', name='删除概念', exact=True).click()
    prompt = p.locator('.dcn-confirm')
    assert prompt.is_visible()
    assert p.evaluate('(id)=>stored.notes.some(n=>n.id===id)', identifier)
    assert p.locator('.dcn-note-open', has_text='偏序关系').count() == 1
    assert prompt.get_by_role('button', name='取消', exact=True).count() == 0
    prompt.get_by_role('button', name='取消删除', exact=True).click()
    assert p.evaluate('(id)=>stored.notes.some(n=>n.id===id)', identifier)
    p.get_by_role('button', name='删除概念', exact=True).click()
    p.locator('.dcn-confirm').get_by_role('button', name='删除概念', exact=True).click()
    assert not p.evaluate('(id)=>stored.notes.some(n=>n.id===id)', identifier)
    assert p.evaluate('(id)=>stored.deleted[id]', identifier) > 0
    assert p.locator('.dcn-note-open', has_text='偏序关系').count() == 0
    assert p.get_by_role('button', name='撤销删除', exact=True).count() == 0
    assert p.get_by_role('button', name='取消选择', exact=True).count() == 0


def test_save_error_is_not_success_and_network_failure_can_retry(notebook_page):
    p = notebook_page
    open_notebook(p)
    p.get_by_role('checkbox', name='选择概念：集合', exact=True).check()
    p.evaluate('window.saveFailure=true')
    p.get_by_label('我的概念笔记', exact=True).fill('尚未保存的新原文')
    assert '尚未保存' in p.locator('.dcn-saved').inner_text()
    p.get_by_role('button', name='AI 解释', exact=True).click()
    assert p.evaluate('calls.length') == 0
    assert '尚未保存' in p.locator('.dcn-status').inner_text()
    p.evaluate('window.saveFailure=false;window.fail=true')
    p.get_by_role('button', name='AI 解释', exact=True).click()
    p.wait_for_function('document.querySelector(".dcn-status").textContent.includes("服务暂时不可用")')
    assert p.evaluate('stored.notes[0].content') == '尚未保存的新原文'
    p.evaluate('window.fail=false')
    p.get_by_role('button', name='AI 解释', exact=True).click()
    p.wait_for_function('document.querySelector(".dcn-explanation")')
    assert p.evaluate('calls.length') == 2


def test_account_refresh_does_not_show_other_accounts_text_or_late_ai(notebook_page):
    p = notebook_page
    open_notebook(p)
    p.get_by_role('checkbox', name='选择概念：集合', exact=True).check()
    p.get_by_label('补充要求（可选）', exact=True).fill('alice的私有问题')
    p.evaluate('window.hold=true')
    p.get_by_role('button', name='AI 解释', exact=True).click()
    p.wait_for_function('calls.length===1')
    p.evaluate('''()=>{contextKey='bob';stored={notes:[{id:'bob-note',title:'函数',content:'bob的笔记',updatedAt:3}],deleted:{}};notebook.refresh();reply();}''')
    assert p.get_by_label('概念名称', exact=True).input_value() == '函数'
    assert p.get_by_label('我的概念笔记', exact=True).input_value() == 'bob的笔记'
    assert p.get_by_label('补充要求（可选）', exact=True).input_value() == ''
    assert p.locator('.dcn-results').inner_text() == ''
    assert '集合' not in p.locator('.dcn-list').inner_text()


def test_no_routine_persistence_blurbs_but_autosave_still_updates_state(notebook_page):
    p = notebook_page
    p.evaluate('window.persistent=false;window.contextKey="guest"')
    open_notebook(p)
    assert p.locator('.dcn-persistence,.dcn-empty,.dcn-scope').count() == 0
    assert p.locator('.dcn-saved').inner_text() == ''
    p.get_by_label('我的概念笔记', exact=True).fill('访客当前页面的笔记')
    assert p.locator('.dcn-saved').inner_text() == ''
    assert p.evaluate('stored.notes[0].content') == '访客当前页面的笔记'
    p.evaluate('window.persistent=true;window.contextKey="bob";notebook.refresh()')
    assert p.locator('.dcn-persistence').count() == 0
    assert p.locator('input[type=checkbox]:checked').count() == 0


def test_switch_to_empty_account_clears_hidden_editor_and_old_save_error(notebook_page):
    p = notebook_page
    open_notebook(p)
    p.evaluate('window.saveFailure=true')
    p.get_by_label('我的概念笔记', exact=True).fill('alice不能留在隐藏DOM的私有笔记')
    assert '尚未保存' in p.locator('.dcn-saved').inner_text()
    p.get_by_label('补充要求（可选）', exact=True).fill('alice的私有问题')
    p.evaluate('''()=>{contextKey='empty-account';saveFailure=false;stored={notes:[],deleted:{}};notebook.refresh();}''')
    assert p.locator('.dcn-title').input_value() == ''
    assert p.locator('.dcn-original').input_value() == ''
    assert p.locator('.dcn-question').input_value() == ''
    assert p.locator('.dcn-editor').is_hidden()
    assert p.locator('.dcn-saved').inner_text() == ''
    assert p.locator('.dcn-list').inner_text() == '还没有概念笔记。'
    assert p.locator('.dcn-results').inner_text() == ''


def test_new_first_note_and_open_note_never_implicitly_select_for_ai(notebook_page):
    p = notebook_page
    p.evaluate('stored={notes:[],deleted:{}}')
    open_notebook(p)
    p.get_by_role('button', name='新建概念', exact=True).click()
    p.get_by_label('概念名称', exact=True).fill('第一个概念')
    assert p.locator('input[type=checkbox]:checked').count() == 0
    p.get_by_role('button', name='第一个概念', exact=True).click()
    assert p.locator('input[type=checkbox]:checked').count() == 0
    assert p.get_by_role('button', name='AI 解释', exact=True).is_disabled()
    assert p.evaluate('calls.length') == 0


def test_large_solid_circle_multiselect_and_red_close_are_clickable(notebook_page):
    p = notebook_page
    open_notebook(p)
    circle = p.get_by_role('checkbox', name='选择概念：集合', exact=True)
    dimensions = circle.bounding_box()
    assert dimensions['width'] >= 22 and dimensions['height'] >= 22
    hit = p.locator('[data-note-id="set"] .dcn-note-select')
    assert hit.bounding_box()['width'] >= 44 and hit.bounding_box()['height'] >= 44
    hit.click(position={'x': 2, 'y': 2})
    assert circle.is_checked()
    p.get_by_role('checkbox', name='选择概念：关系', exact=True).check()
    assert p.locator('input[type=checkbox]:checked').count() == 2
    assert circle.evaluate('e=>getComputedStyle(e).backgroundColor') != 'rgba(0, 0, 0, 0)'
    assert circle.evaluate('e=>getComputedStyle(e).borderRadius') == '50%'
    close = p.get_by_role('button', name='关闭笔记本', exact=True)
    assert close.inner_text() == ''
    assert close.evaluate('e=>getComputedStyle(e).backgroundColor') == 'rgb(239, 68, 68)'
    assert close.evaluate('e=>getComputedStyle(e).borderRadius') == '50%'
    size = 'mobile' if p.viewport_size['width'] < 681 else 'desktop'
    p.screenshot(path='/tmp/dmate-notebook-' + size + '-clean.png')
    top = close.bounding_box()['y']
    p.locator('.dcn-main').evaluate('e=>e.scrollTop=e.scrollHeight')
    assert close.bounding_box()['y'] == pytest.approx(top)
    close.click()
    assert p.locator('#conceptNotebookDialog').is_hidden()


def test_delete_confirmation_escape_and_account_switch_keep_notes(notebook_page):
    p = notebook_page
    open_notebook(p)
    p.get_by_role('button', name='删除概念', exact=True).click()
    size = 'mobile' if p.viewport_size['width'] < 681 else 'desktop'
    p.screenshot(path='/tmp/dmate-notebook-' + size + '-delete.png')
    p.locator('.dcn-confirm').press('Escape')
    assert p.locator('.dcn-confirm').count() == 0
    assert p.evaluate('stored.notes.length') == 2
    assert p.locator('#conceptNotebookDialog').is_visible()
    p.get_by_role('button', name='删除概念', exact=True).click()
    p.evaluate("contextKey='bob';stored={notes:[{id:'bob',title:'bob概念',content:'保留内容',updatedAt:3}],deleted:{}};notebook.refresh()")
    assert p.locator('.dcn-confirm').count() == 0
    assert p.evaluate('stored.notes[0].id') == 'bob'
    assert p.evaluate('Object.keys(stored.deleted).length') == 0
    assert p.get_by_label('我的概念笔记', exact=True).input_value() == '保留内容'


def test_external_delete_confirmation_callback_checks_current_context(notebook_page):
    p = notebook_page
    p.evaluate("""()=>{notebook.destroy();notebook=DMateConceptNotebook.mount({
      button:document.getElementById('conceptNotebookBtn'),dialog:document.getElementById('conceptNotebookDialog'),
      getState:()=>structuredClone(stored),onChange:v=>stored=structuredClone(v),getContextKey:()=>contextKey,
      confirmDelete:settings=>{window.deleteSettings=settings;return new Promise(resolve=>window.resolveDelete=resolve)}});notebook.open();}""")
    p.get_by_role('button', name='删除概念', exact=True).click()
    assert p.evaluate('deleteSettings.confirmTone') == 'danger'
    assert p.get_by_role('button', name='删除概念', exact=True).is_disabled()
    p.evaluate('resolveDelete(false)')
    assert p.evaluate('stored.notes.length') == 2
    p.get_by_role('button', name='删除概念', exact=True).click()
    p.evaluate("contextKey='bob';notebook.refresh();resolveDelete(true)")
    assert p.evaluate('stored.notes.length') == 2
    assert p.evaluate('Object.keys(stored.deleted).length') == 0
