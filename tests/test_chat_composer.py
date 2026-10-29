"""The production composer grows with typing/dictation and preserves attachments."""
import os
from pathlib import Path
import re
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=[(1440, 900, 'light'), (1440, 900, 'dark'), (390, 844, 'light'), (390, 844, 'dark')])
def composer_page(request):
    chromium = os.environ.get('DMATE_BROWSER_EXECUTABLE') or shutil.which('chromium')
    if not chromium:
        pytest.skip('Chromium unavailable')
    pw = pytest.importorskip('playwright.sync_api')
    html = (ROOT / 'templates/index.html').read_text()
    script = (ROOT / 'static/script.js').read_text()
    fragment = '<div id="ocrUploadStage"' + html.split('<div id="ocrUploadStage"', 1)[1].split('\n<div class="right">', 1)[0]
    styles = '\n'.join(re.findall(r'<style[^>]*>([\s\S]*?)</style>', html))
    width, height, theme = request.param
    with pw.sync_playwright() as runtime:
        browser = runtime.chromium.launch(executable_path=chromium, headless=True)
        page = browser.new_page(viewport={'width': width, 'height': height})
        page.route('**/*', lambda route: route.fulfill(body='<html></html>', content_type='text/html'))
        page.goto('https://dmate.test/')
        page.set_content('<body data-appearance-theme="' + theme + '"><div class="center" style="height:90dvh;display:flex;flex-direction:column;justify-content:flex-end">' + fragment + '</body>')
        page.add_style_tag(content=styles)
        page.add_style_tag(content=(ROOT / 'static/voice-input.css').read_text())
        page.add_style_tag(content=(ROOT / 'static/chat-composer.css').read_text())
        page.add_script_tag(content=(ROOT / 'static/chat-composer.js').read_text())
        def block(start, end):
            at = script.index(start)
            return script[at:script.index(end, at + len(start))]
        page.add_script_tag(content='''window.sends=0;window.currentId=1;window.ocrReviewInProgress=false;window.ocrBatchPreparing=false;
            window.waiting=false;window.typing=false;window.ocrTasks=new Map();window.OCR_MAX_CONCURRENT=4;
            window.isSessionBusy=()=>waiting;window.isSessionPendingAiStart=()=>false;window.isCurrentSessionTyping=()=>typing;
            window.ocrActiveCount=()=>0;window.ocrTaskLabel=()=>"识别中";window.ocrTaskSeconds=()=>0;
            window.updateOcrTaskTimes=()=>{};window.queueChatJumpControlsUpdate=()=>{};
            window.send=()=>{sends++;const input=document.getElementById('text');input.value='';input.dispatchEvent(new Event('input',{bubbles:true}));};
            window.handleSendOrStop=()=>waiting?(waiting=false,refreshInputAvailability()):send();
            window.syncOcrTaskAvailability=()=>refreshInputAvailability();
        ''' + block('function refreshInputAvailability()', 'function setSessionBusy(')
            + block('function initializeChatComposer()', 'function initializeVoiceInput()')
            + block('function renderOcrTasks()', 'function draftFromOcrResponse')
            + '\ninitializeChatComposer();refreshInputAvailability();')
        yield page
        browser.close()


def test_rounded_composer_grows_caps_and_resets_after_dictation_and_send(composer_page):
    page = composer_page
    field = page.locator('#text')
    assert field.evaluate('e=>e.tagName') == 'TEXTAREA'
    initial = field.bounding_box()['height']
    field.fill('集合 A\n二元关系 R\n第三行概念\n第四行说明')
    assert field.bounding_box()['height'] > initial + 40
    # Dictation uses the same input event as the real microphone module.
    field.evaluate("e=>{e.setSelectionRange(e.value.length,e.value.length);e.setRangeText('\\n语音补充内容',e.selectionStart,e.selectionEnd,'end');e.dispatchEvent(new Event('input',{bubbles:true}));}")
    assert '语音补充内容' in field.input_value()
    field.fill('\n'.join('很多内容第' + str(i) + '行' for i in range(35)))
    height = field.bounding_box()['height']
    assert 90 <= height <= 180
    assert field.evaluate('e=>getComputedStyle(e).overflowY') == 'auto'
    page.locator('#sendBtn').click()
    assert page.evaluate('sends') == 1
    assert field.input_value() == ''
    assert field.bounding_box()['height'] == pytest.approx(initial, abs=1)


def test_keyboard_newlines_ime_and_send_do_not_double_submit(composer_page):
    page = composer_page
    field = page.locator('#text')
    field.fill('第一行')
    field.press('Shift+Enter')
    field.press('a')
    assert '\n' in field.input_value()
    assert page.evaluate('sends') == 0
    field.evaluate("e=>e.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',isComposing:true,bubbles:true,cancelable:true}))")
    assert page.evaluate('sends') == 0
    field.evaluate("e=>{e.dispatchEvent(new CompositionEvent('compositionstart'));e.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));e.dispatchEvent(new CompositionEvent('compositionend'));}")
    assert page.evaluate('sends') == 0
    page.wait_for_timeout(60)
    field.press('Enter')
    assert page.evaluate('sends') == (0 if page.viewport_size['width'] < 681 else 1)
    if page.viewport_size['width'] < 681:
        assert field.input_value().count('\n') >= 2
    # Main initialization is idempotent and cannot add a second key handler.
    page.evaluate('initializeChatComposer()')
    field.fill('下一条')
    page.locator('#sendBtn').click()
    assert page.evaluate('sends') == (1 if page.viewport_size['width'] < 681 else 2)


def test_attachment_stage_reuses_labelled_upload_and_send_then_restores_icons(composer_page):
    page = composer_page
    picker_before = page.locator('#imageInput').evaluate("e=>{e.dataset.identity='same-picker';return e.dataset.identity}")
    page.evaluate("ocrTasks.set('one',{id:'one',state:'recognizing',file:{name:'图片.png'},originalUrl:'data:image/png;base64,iVBORw0KGgo=',startedAt:0,finishedAt:null});renderOcrTasks()")
    assert page.locator('.center > .input-wrap').is_hidden()
    assert page.locator('#imageBtn').is_visible() and page.locator('#sendBtn').is_visible()
    assert page.locator('#imageBtn').inner_text() == '上传图片'
    assert page.locator('#sendBtn').inner_text() == '发送'
    assert page.locator('#imageBtn').evaluate('e=>parseFloat(getComputedStyle(e).fontSize)') >= 14
    assert page.locator('#sendBtn').evaluate('e=>parseFloat(getComputedStyle(e).fontSize)') >= 14
    assert page.locator('#imageInput').count() == page.locator('#sendBtn').count() == 1
    assert page.locator('#imageInput').get_attribute('data-identity') == picker_before
    first, second = page.locator('#imageBtn').bounding_box(), page.locator('#sendBtn').bounding_box()
    assert first['x'] + first['width'] <= second['x']
    page.evaluate('ocrTasks.clear();renderOcrTasks()')
    assert page.locator('.center > .input-wrap').is_visible()
    assert page.locator('#sendBtn').evaluate('e=>getComputedStyle(e).fontSize') == '0px'


def test_controls_fit_all_themes_and_busy_state_keeps_stop_action(composer_page):
    page = composer_page
    field = page.locator('#text')
    field.fill('普通消息')
    wrapper = page.locator('.center > .input-wrap > .input').bounding_box()
    plus, mic, send = [page.locator('#' + name).bounding_box() for name in ('imageBtn', 'voiceInputBtn', 'sendBtn')]
    assert plus['x'] < field.bounding_box()['x'] < mic['x'] < send['x']
    for box in [plus, mic, send]:
        assert box['x'] >= wrapper['x'] and box['x'] + box['width'] <= wrapper['x'] + wrapper['width'] + 1
        assert box['y'] >= wrapper['y'] and box['y'] + box['height'] <= wrapper['y'] + wrapper['height'] + 1
    assert page.evaluate('document.documentElement.scrollWidth') <= page.viewport_size['width']
    assert float(page.locator('.input').evaluate('e=>parseFloat(getComputedStyle(e).borderRadius)')) >= 24
    mode = page.evaluate('document.body.dataset.appearanceTheme')
    size = 'mobile' if page.viewport_size['width'] < 681 else 'desktop'
    page.screenshot(path='/tmp/composer-' + size + '-' + mode + '.png')
    page.evaluate('waiting=true;refreshInputAvailability()')
    assert field.is_disabled()
    assert page.locator('#sendBtn').get_attribute('aria-label') == '停止当前 AI 回复'
    assert page.locator('#sendBtn').is_visible()
    assert page.locator('#imagePickerWrap').is_hidden()
    page.locator('#sendBtn').click()
    assert not field.is_disabled()


def test_voice_preparation_and_tail_cannot_send_partial_dictation(composer_page):
    page = composer_page
    script = (ROOT / 'static/script.js').read_text()
    at = script.index('function handleSendOrStop()')
    code = script[at:script.index('// -----------------------------\n// 基础状态', at)]
    page.evaluate("code=>{window.handleSendOrStop=new Function(code+';return handleSendOrStop;')();window.dmateVoiceInput={state:'idle',refresh(){}};}", code)
    field = page.locator('#text')
    for state in ('requesting', 'preparing', 'recording', 'finishing', 'transcribing'):
        field.fill('尚未完成的语音输入')
        page.evaluate('state=>{dmateVoiceInput.state=state;refreshInputAvailability();}', state)
        assert page.locator('#sendBtn').is_disabled()
        page.evaluate('handleSendOrStop()')
        if page.viewport_size['width'] >= 681:
            field.press('Enter')
        assert page.evaluate('sends') == 0
    page.evaluate("dmateVoiceInput.state='idle';refreshInputAvailability()")
    assert page.locator('#sendBtn').is_enabled()
    page.locator('#sendBtn').click()
    assert page.evaluate('sends') == 1


def test_single_line_capsule_is_short_wide_spaced_from_bottom_and_blue_send(composer_page):
    page=composer_page
    capsule=page.locator('.center > .input-wrap > .input').bounding_box()
    center=page.locator('.center').bounding_box()
    outer=page.locator('.center > .input-wrap').bounding_box()
    assert capsule['height']==pytest.approx(48 if page.viewport_size['width']<681 else 52,abs=1)
    padding=page.locator('.center > .input-wrap').evaluate('e=>parseFloat(getComputedStyle(e).paddingLeft)')
    assert capsule['width']==pytest.approx(min(1440,center['width']-padding*2),abs=2)
    assert outer['y']+outer['height']-(capsule['y']+capsule['height'])>=15
    send=page.locator('#sendBtn')
    assert send.evaluate('e=>getComputedStyle(e).backgroundColor')=='rgb(59, 130, 246)'
    assert send.evaluate('e=>getComputedStyle(e,"::before").backgroundColor')=='rgb(255, 255, 255)'


def test_pointer_click_has_no_ring_and_keyboard_focus_remains_visible(composer_page):
    page=composer_page
    for selector in ['#voiceInputBtn','#sendBtn']:
        page.locator(selector).click()
        style=page.locator(selector).evaluate('e=>({outline:getComputedStyle(e).outlineStyle,shadow:getComputedStyle(e).boxShadow})')
        assert style['outline']=='none'
        assert style['shadow']=='none'
    page.locator('#text').click()
    page.keyboard.press('Tab')
    assert page.evaluate('document.activeElement.id')=='voiceInputBtn'
    assert page.locator('#voiceInputBtn').evaluate('e=>e.matches(":focus-visible")')
    assert page.locator('#voiceInputBtn').evaluate('e=>getComputedStyle(e).outlineStyle')=='solid'
