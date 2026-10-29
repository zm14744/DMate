"""Native picker uploads keep the chat shell in place before and after OCR."""
import base64
import os
from pathlib import Path
import re
import shutil

import pytest


ROOT = Path(__file__).resolve().parents[1]
PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ1sAAAAASUVORK5CYII='
)


@pytest.fixture(params=[(1440, 900, False), (390, 844, False), (390, 844, True)],
                ids=['desktop', 'phone', 'legacy-android'])
def upload_page(request):
    executable = os.environ.get('DMATE_BROWSER_EXECUTABLE') or shutil.which('chromium')
    if not executable:
        pytest.skip('Chromium unavailable')
    pw = pytest.importorskip('playwright.sync_api')
    html = (ROOT / 'templates/index.html').read_text()
    script = (ROOT / 'static/script.js').read_text()
    center = '<div class="center">' + html.split('<div class="center">', 1)[1].split('\n<div class="right">', 1)[0]
    styles = '\n'.join(re.findall(r'<style[^>]*>([\s\S]*?)</style>', html))

    def block(start, end):
        at = script.index(start)
        return script[at:script.index(end, at + len(start))]

    init = script.index('// 初始化')
    native_at = script.index('        if (imageInput) {', init)
    native_events = script[native_at:script.index('        initializeVoiceInput();', native_at)]
    with pw.sync_playwright() as runtime:
        browser = runtime.chromium.launch(executable_path=executable, headless=True)
        options = {'viewport': {'width': request.param[0], 'height': request.param[1]}}
        if request.param[2]:
            options['user_agent'] = ('Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 '
                                     'Chrome/90.0.4430.91 Mobile Safari/537.36 DMateAndroid/1.0.4')
        page = browser.new_page(**options)
        page.route('**/*', lambda route: route.fulfill(body='<html></html>', content_type='text/html'))
        page.goto('https://dmate.test/')
        page.set_content('<body data-appearance-theme="light"><div class="layout"><div class="left"></div>'
                         + center + '<div class="right"></div></div></body>')
        page.add_style_tag(content=styles)
        for name in ['voice-input.css', 'chat-composer.css']:
            page.add_style_tag(content=(ROOT / 'static' / name).read_text())
        page.add_script_tag(content=(ROOT / 'static/chat-composer.js').read_text())
        page.add_script_tag(content='''
            window.currentId='chat1';window.sessions=[{id:'chat1',messages:[]}];
            window.getCurrent=()=>sessions[0];window.sessionBusyKey=id=>String(id);
            window.isSessionBusy=()=>false;window.isSessionPendingAiStart=()=>false;
            window.isCurrentSessionTyping=()=>false;window.ocrReviewInProgress=false;
            window.ocrRequestInFlight=false;window.MAX_IMAGE_BYTES=20000000;
            window.queueChatJumpControlsUpdate=()=>{};window.handleSendOrStop=()=>{};
            window.makeOcrRequestId=()=>crypto.randomUUID();window.notifyOcrCancelled=()=>{};
            window.parseResponseJson=response=>response.json();window.showCurrentError=e=>{window.lastError=e;};
            window.requests=[];window.pendingOcr=[];
            window.fetch=async(url,options={})=>{
                requests.push(url);
                if(url==='/graph/session')return {ok:true,json:async()=>({})};
                if(url==='/ocr')return new Promise(resolve=>pendingOcr.push(()=>resolve({ok:true,
                    json:async()=>({workflow_profile:'layout_only',document:{body_text:'测试题目',graphs:[]},
                        source_sha256:'a'.repeat(64)})})));
                throw new Error('Unexpected request: '+url);
            };
        ''' + block('function refreshInputAvailability()', 'function setSessionBusy(')
            + block('const OCR_MAX_CONCURRENT', '\nfunction isClearlyNonQuestionWrongBookText')
            + '\nconst imageInput=document.getElementById("imageInput");\n' + native_events
            + '\ninitializeChatComposer();renderOcrTasks();'
            + '\ndocument.getElementById("imageBtn").addEventListener("click",openImagePicker);')
        page.evaluate('''()=>{
            const chat=document.getElementById('chat');
            chat.innerHTML=Array.from({length:50},(_,i)=>'<div class="msg ai">已有消息 '+i+'</div>').join('');
            chat.scrollTop=350;
            window.originalPicker=document.getElementById('imageInput');
            window.layoutSamples=[];
            window.sampleLayout=()=>{
                const rect=id=>{const e=document.querySelector(id);if(!e||!e.getClientRects().length)return null;
                    const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom,right:r.right};};
                return {pageX:scrollX,pageY:scrollY,chatTop:chat.scrollTop,
                    layoutTop:document.querySelector('.layout').scrollTop,layoutLeft:document.querySelector('.layout').scrollLeft,
                    centerTop:document.querySelector('.center').scrollTop,centerLeft:document.querySelector('.center').scrollLeft,
                    viewport:{x:visualViewport.offsetLeft,y:visualViewport.offsetTop},
                    center:rect('.center'),stage:rect('#ocrUploadStage'),picker:rect('#imageInput'),
                    focus:document.activeElement?.id||document.activeElement?.tagName};
            };
            window.recording=true;
            function sample(){if(!recording)return;layoutSamples.push(sampleLayout());requestAnimationFrame(sample);}
            requestAnimationFrame(sample);
        }''')
        yield page
        browser.close()


def frames(page, count=15):
    page.evaluate('''count=>new Promise(resolve=>{
        function next(){if(--count<=0)resolve();else requestAnimationFrame(next);}
        requestAnimationFrame(next);
    })''', count)


def assert_shell_stable(samples, before):
    assert len(samples) >= 5
    for sample in samples:
        for key in ('pageX', 'pageY', 'chatTop', 'layoutTop', 'layoutLeft', 'centerTop', 'centerLeft'):
            assert sample[key] == pytest.approx(before[key], abs=1), (key, before, sample)
        assert sample['viewport'] == before['viewport']
        for key in ('x', 'y', 'width'):
            assert sample['center'][key] == pytest.approx(before['center'][key], abs=1), sample
        assert sample['focus'] != 'text'  # Returning from the chooser must not open the keyboard.
        if sample['stage']:
            assert sample['stage']['x'] >= sample['center']['x'] + 7
            assert sample['stage']['right'] <= sample['center']['right'] - 7


def choose_image(page, filename):
    with page.expect_file_chooser() as chooser:
        page.locator('#imageInput').click()
    assert chooser.value.element.get_attribute('id') == 'imageInput'
    assert chooser.value.is_multiple() == ('DMateAndroid/1.0.4' not in page.evaluate('navigator.userAgent'))
    page.evaluate('layoutSamples=[]')
    before = page.evaluate('sampleLayout()')
    chooser.value.set_files({'name': filename, 'mimeType': 'image/png', 'buffer': PNG})
    return before


def test_native_upload_and_append_keep_first_visible_frame_in_place(upload_page):
    page = upload_page
    before = choose_image(page, '图片.png')
    page.wait_for_function('pendingOcr.length===1')
    frames(page)
    assert page.evaluate('ocrTasks.size') == 1
    samples = page.evaluate('layoutSamples')
    assert_shell_stable(samples, before)
    visible = [sample for sample in samples if sample['stage']]
    assert len(visible) >= 5
    for sample in visible:
        # Check every painted frame, including the first one after selection.
        assert sample['stage'] == visible[-1]['stage']
        assert sample['stage']['bottom'] <= sample['center']['bottom']

    before = choose_image(page, '另一张.png')
    page.wait_for_function('pendingOcr.length===2')
    frames(page)
    assert page.evaluate('ocrTasks.size') == 2  # Native input + change must not duplicate selections.
    assert_shell_stable(page.evaluate('layoutSamples'), before)
    assert page.evaluate('originalPicker===document.getElementById("imageInput")')
    assert page.locator('#imageInput').input_value() == ''
    native, visible_button = page.locator('#imageInput').bounding_box(), page.locator('#imageBtn').bounding_box()
    for key in ('x', 'y', 'width', 'height'):
        assert native[key] == pytest.approx(visible_button[key], abs=1)

    page.evaluate('layoutSamples=[];pendingOcr.forEach(resolve=>resolve())')
    page.wait_for_function('[...ocrTasks.values()].every(task=>task.state==="ready")')
    frames(page)
    assert_shell_stable(page.evaluate('layoutSamples'), before)
    assert page.evaluate('requests.filter(url=>url==="/ocr").length') == 2
    assert page.evaluate('window.lastError||null') is None


def test_native_upload_during_viewport_restore(upload_page):
    page = upload_page
    original = page.viewport_size
    page.set_viewport_size({'width': original['width'], 'height': 220})
    before = choose_image(page, '图片.png')
    page.wait_for_function('pendingOcr.length===1')
    # Native choosers/soft keyboards can leave a temporarily reduced viewport.
    # Even overflow:hidden ancestors can be panned by scrollIntoView here.
    frames(page)
    compressed = page.evaluate('layoutSamples')
    page.set_viewport_size(original)
    frames(page)
    assert_shell_stable(compressed, before)
    assert_shell_stable(page.evaluate('layoutSamples'), before)
    visible = [sample['stage'] for sample in compressed if sample['stage']]
    assert len(visible) >= 5
    assert all(stage == visible[0] for stage in visible)
    assert page.evaluate('ocrTasks.size') == 1


@pytest.mark.parametrize('activation', ['native_input', 'button_handler', 'keyboard_enter'])
def test_one_native_chooser_per_activation_and_cancel_never_reopens(upload_page, activation):
    page = upload_page
    choosers = []
    page.on('filechooser', lambda chooser: choosers.append(chooser))
    page.evaluate('''()=>{
        window.nativePickerClicks=0;window.uploadButtonClicks=0;
        document.getElementById('imageInput').addEventListener('click',()=>nativePickerClicks++);
        document.getElementById('imageBtn').addEventListener('click',()=>uploadButtonClicks++);
        window.pickerMoves=[];
        new MutationObserver(()=>{
            const parent=document.getElementById('imagePickerWrap').parentElement;
            pickerMoves.push(parent.className);
        }).observe(document.getElementById('imagePickerWrap').parentElement,{childList:true});
        layoutSamples=[];
    }''')
    before = page.evaluate('sampleLayout()')
    with page.expect_file_chooser() as opened:
        if activation == 'native_input':
            # Normal pointer/touch interaction hits the real overlaid input.
            page.locator('#imageInput').click()
        elif activation == 'button_handler':
            # Exercise the sibling button's public click handler separately;
            # the production native overlay normally receives pointer clicks.
            page.locator('#imageBtn').evaluate('button=>button.click()')
        else:
            page.locator('#imageBtn').focus()
            page.locator('#imageBtn').press('Enter')
    frames(page, 8)
    assert len(choosers) == 1
    assert opened.value.element.get_attribute('id') == 'imageInput'
    assert page.evaluate('nativePickerClicks') == (1 if activation == 'native_input' else 0)
    assert page.evaluate('uploadButtonClicks') == (0 if activation == 'native_input' else 1)
    assert page.evaluate('pickerMoves') == []
    assert page.evaluate('requests') == []
    assert page.evaluate('ocrTasks.size') == 0
    assert_shell_stable(page.evaluate('layoutSamples'), before)
    assert page.evaluate('originalPicker===document.getElementById("imageInput")')

    # Returning an empty selection exercises the browser input return path.
    # Playwright intercepts the OS window; it does not measure OS placement.
    opened.value.set_files([])
    frames(page, 12)
    assert len(choosers) == 1
    assert page.evaluate('pickerMoves') == []
    assert page.evaluate('ocrTasks.size') == 0
    assert page.evaluate('requests') == []
    assert page.locator('dialog[open]').count() == 0
    assert_shell_stable(page.evaluate('layoutSamples'), before)
