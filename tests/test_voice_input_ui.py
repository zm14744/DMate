"""Real browser recording lifecycle with mocked microphone and ASR transport."""
import os
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=[(1440, 900), (390, 844)])
def voice_page(request):
    chromium = os.environ.get('DMATE_BROWSER_EXECUTABLE') or shutil.which('chromium')
    if not chromium:
        pytest.skip('Chromium unavailable')
    pw = pytest.importorskip('playwright.sync_api')
    with pw.sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=chromium, headless=True)
        page = browser.new_page(viewport={'width': request.param[0], 'height': request.param[1]})
        page.route('**/*', lambda route: route.fulfill(body='<html></html>', content_type='text/html'))
        page.goto('https://dmate.test/')
        page.set_content('''<body data-appearance-theme="light"><main style="max-width:600px"><div class="input-wrap"><div class="input">
        <div class="manual-question-composer" style="width:100%;height:60px"><input id="text" value="已有内容" style="width:100%;height:60px;box-sizing:border-box">
        <button id="voiceInputBtn"></button></div><button id="send" onclick="window.sends++">发送</button></div>
        <div id="voiceInputStatus"></div></div></main></body>''')
        page.add_style_tag(content=(ROOT / 'static/voice-input.css').read_text())
        page.add_script_tag(content='''window.sends=0;window.calls=[];window.permissionCalls=0;window.stops=0;window.closes=0;window.sessionKey='one';window.inputEvents=0;
        const text=document.getElementById('text');text.addEventListener('input',()=>inputEvents++);
        window.fakeMedia={getUserMedia:async()=>{
          permissionCalls++;if(window.permissionDenied)throw Object.assign(new Error('denied'),{name:'NotAllowedError'});
          if(window.holdPermission)return new Promise(resolve=>window.allowPermission=()=>resolve({getTracks:()=>[{stop:()=>{stops++}}]}));
          return {getTracks:()=>[{stop:()=>{stops++}}]};
        }};
        window.FakeAudio=class {
          constructor(){this.sampleRate=48000;this.state='suspended';this.destination={};}
          async resume(){this.state='running';}
          async close(){this.state='closed';closes++;}
          createMediaStreamSource(){return {connect(){},disconnect(){}};}
          createGain(){return {gain:{value:1},connect(){},disconnect(){}};}
          createScriptProcessor(){const node={connect(){},disconnect(){},onaudioprocess:null};window.audioProcessor=node;return node;}
        };
        window.pushAudio=(size=24000,marker=null)=>{const data=new Float32Array(size);for(let i=0;i<data.length;i++)data[i]=marker??(.25*Math.sin(i/12));
          audioProcessor.onaudioprocess?.({inputBuffer:{getChannelData:()=>data}});};
        window.transport=async(url,options)=>{
          const file=options.body.get('audio'), bytes=await file.arrayBuffer(),v=new DataView(bytes);
          const pcm=Array.from({length:v.getUint32(40,true)/2},(_,i)=>v.getInt16(44+i*2,true));
          calls.push({url,filename:file.name,type:file.type,length:bytes.byteLength,rate:v.getUint32(24,true),channels:v.getUint16(22,true),bits:v.getUint16(34,true),frames:pcm.length,pcm});
          if(window.holdResponse)return new Promise((resolve,reject)=>{
            window.reply=()=>resolve({ok:true,json:async()=>({ok:true,text:'语音结果'})});
            options.signal.addEventListener('abort',()=>{window.requestAborted=true;reject(new DOMException('cancelled','AbortError'));});
          });
          return {ok:!window.failResponse,json:async()=>window.failResponse?{ok:false,error:'模型服务暂时不可用。'}:{ok:true,text:window.responseText??'语音结果'}};
        };
        ''')
        page.add_script_tag(content=(ROOT / 'static/voice-input.js').read_text())
        page.evaluate('''()=>{window.voice=DMateVoiceInput.mount({button:document.getElementById('voiceInputBtn'),input:document.getElementById('text'),
          status:document.getElementById('voiceInputStatus'),mediaDevices:fakeMedia,AudioContext:FakeAudio,fetch:transport,getContextKey:()=>sessionKey});}''')
        yield page
        browser.close()


def start_recording(page):
    page.get_by_role('button', name='语音输入', exact=True).click()
    page.wait_for_function('voice.state==="preparing"')
    page.evaluate('pushAudio(1)')  # Device delivery, rather than permission alone, enables speaking.
    page.wait_for_function('voice.state==="recording"')


def end_recording(page):
    page.evaluate('pushAudio()')
    page.get_by_role('button', name='结束录音并识别', exact=True).click()


def assert_no_visual_caption(page):
    """Accessible progress has no painted text and consumes no input row."""
    appearance = page.locator('#voiceInputStatus').evaluate('''element=>{
      const style=getComputedStyle(element);return {position:style.position,
        clip:style.clipPath,width:style.width,height:style.height,
        hidden:element.hidden,error:element.classList.contains('voice-input-error'),
        buttons:element.querySelectorAll('button').length};}''')
    assert appearance['error'] is False and appearance['buttons'] == 0
    if not appearance['hidden']:
        assert appearance['position'] == 'absolute' and appearance['clip'] == 'inset(50%)'
        assert appearance['width'] == appearance['height'] == '1px'


def test_dictation_inserts_at_cursor_without_sending_and_releases_capture(voice_page):
    p = voice_page
    p.locator('#text').evaluate('(e)=>{e.focus();e.setSelectionRange(2,4)}')
    start_recording(p)
    assert p.get_by_role('button', name='结束录音并识别').get_attribute('aria-pressed') == 'true'
    end_recording(p)
    p.wait_for_function('voice.state==="idle" && calls.length===1')
    assert p.locator('#text').input_value() == '已有语音结果内容'
    assert p.evaluate('sends') == 0
    assert p.evaluate('inputEvents') == 1
    assert p.evaluate('stops') == p.evaluate('closes') == 1
    record = p.evaluate('calls[0]')
    assert record['url'] == '/voice/transcribe'
    assert record['filename'] == 'voice.wav'
    assert record['type'] == 'audio/wav'
    assert (record['rate'], record['channels'], record['bits']) == (16000, 1, 16)
    assert record['frames'] == 14401  # Real 0.5s + one source sample, and 0.4s boundary silence.
    assert_no_visual_caption(p)
    button = p.locator('#voiceInputBtn').bounding_box()
    field = p.locator('#text').bounding_box()
    assert button['x'] >= field['x'] and button['x'] + button['width'] <= field['x'] + field['width']


def test_permission_rejection_has_no_request_and_preserves_existing_text(voice_page):
    p = voice_page
    p.evaluate('window.permissionDenied=true')
    p.get_by_role('button', name='语音输入', exact=True).click()
    p.wait_for_function('voice.state==="idle" && permissionCalls===1')
    assert '麦克风权限被拒绝' in p.get_by_role('alert').inner_text()
    assert p.locator('#text').input_value() == '已有内容'
    assert p.evaluate('calls.length') == p.evaluate('sends') == 0


def test_duplicate_permission_clicks_are_ignored_and_late_permission_is_stopped(voice_page):
    p = voice_page
    p.evaluate('window.holdPermission=true')
    p.get_by_role('button', name='语音输入', exact=True).click()
    p.wait_for_function('voice.state==="requesting"')
    p.locator('#voiceInputBtn').dispatch_event('click')
    assert p.evaluate('permissionCalls') == 1
    p.keyboard.press('Escape')
    p.evaluate('allowPermission()')
    p.wait_for_function('stops===1')
    assert p.evaluate('voice.state') == 'idle'
    assert p.evaluate('calls.length') == 0
    assert_no_visual_caption(p)


def test_session_change_while_transcribing_aborts_and_does_not_write_new_session(voice_page):
    p = voice_page
    p.evaluate('window.holdResponse=true')
    start_recording(p)
    end_recording(p)
    p.wait_for_function('calls.length===1 && voice.state==="transcribing"')
    p.evaluate('window.sessionKey="two";document.getElementById("text").value="另一个会话"')
    p.wait_for_function('voice.state==="idle" && window.requestAborted===true')
    p.evaluate('reply()')
    assert p.locator('#text').input_value() == '另一个会话'
    assert p.evaluate('sends') == 0
    assert '已取消' in p.get_by_role('status').inner_text()
    assert_no_visual_caption(p)


def test_escape_and_input_lock_stop_recording_without_upload(voice_page):
    p = voice_page
    start_recording(p)
    p.keyboard.press('Escape')
    assert p.evaluate('voice.state') == 'idle'
    assert p.evaluate('stops') == 1
    start_recording(p)
    p.locator('#text').evaluate('e=>{e.disabled=true}')
    p.wait_for_function('voice.state==="idle"')
    assert p.evaluate('stops') == 2
    assert p.locator('#voiceInputBtn').is_disabled()
    assert p.evaluate('calls.length') == 0


def test_model_failure_restores_idle_without_message_or_erasing_text(voice_page):
    p = voice_page
    p.evaluate('window.failResponse=true')
    start_recording(p)
    end_recording(p)
    p.wait_for_function('voice.state==="idle" && calls.length===1')
    assert p.get_by_role('alert').count() == 0
    assert p.locator('#voiceInputStatus').text_content() == ''
    assert_no_visual_caption(p)
    assert p.locator('#text').input_value() == '已有内容'
    assert p.evaluate('sends') == 0


def test_audio_limit_auto_stops_and_uploads_only_bounded_pcm(voice_page):
    p = voice_page
    p.evaluate('''()=>{voice.dispose();window.voice=DMateVoiceInput.mount({button:document.getElementById('voiceInputBtn'),input:document.getElementById('text'),
      status:document.getElementById('voiceInputStatus'),mediaDevices:fakeMedia,AudioContext:FakeAudio,fetch:transport,getContextKey:()=>sessionKey,maxSeconds:1});}''')
    start_recording(p)
    p.evaluate('pushAudio(96000)')  # A 2s callback cannot exceed the configured 1s cap.
    p.wait_for_function('voice.state==="idle" && calls.length===1')
    assert p.evaluate('calls[0].frames') == 16000
    assert p.evaluate('calls[0].length') == 44 + 16000 * 2
    assert p.evaluate('stops') == 1
    assert p.evaluate('sends') == 0


def test_dispose_stops_active_microphone_without_posting(voice_page):
    p = voice_page
    start_recording(p)
    p.evaluate('voice.dispose()')
    assert p.evaluate('stops') == p.evaluate('closes') == 1
    p.locator('#voiceInputBtn').dispatch_event('click')
    assert p.evaluate('permissionCalls') == 1
    assert p.evaluate('calls.length') == 0


def test_unsupported_environment_explains_reason_instead_of_starting_request(voice_page):
    p = voice_page
    p.evaluate('''()=>{voice.dispose();window.voice=DMateVoiceInput.mount({button:document.getElementById('voiceInputBtn'),input:document.getElementById('text'),
      status:document.getElementById('voiceInputStatus'),mediaDevices:{},AudioContext:FakeAudio,fetch:transport});}''')
    p.get_by_role('button', name='语音输入', exact=True).click()
    assert '无法使用麦克风' in p.get_by_role('alert').inner_text()
    assert p.evaluate('permissionCalls') == p.evaluate('calls.length') == 0


def test_microphone_is_not_announced_ready_before_audio_blocks_arrive(voice_page):
    p = voice_page
    p.get_by_role('button', name='语音输入', exact=True).click()
    p.wait_for_function('voice.state==="preparing"')
    assert p.get_by_role('button', name='正在启动麦克风', exact=True).is_disabled()
    assert '准备' in p.get_by_role('status').inner_text()
    assert_no_visual_caption(p)
    assert p.evaluate('calls.length') == 0
    p.evaluate('pushAudio(960,.7)')
    p.wait_for_function('voice.state==="recording"')
    assert '已开始录音，请说话' in p.get_by_role('status').inner_text()
    assert_no_visual_caption(p)


def test_first_block_and_stop_grace_tail_are_kept_between_silent_boundaries(voice_page):
    p = voice_page
    p.get_by_role('button', name='语音输入', exact=True).click()
    p.wait_for_function('voice.state==="preparing"')
    p.evaluate('pushAudio(9600,.7)')
    p.wait_for_function('voice.state==="recording"')
    p.get_by_role('button', name='结束录音并识别', exact=True).click()
    p.wait_for_function('voice.state==="finishing"')
    assert p.get_by_role('button', name='正在收录尾音', exact=True).is_disabled()
    assert p.evaluate('calls.length') == p.evaluate('stops') == 0
    p.evaluate('pushAudio(9600,.9)')  # Browser delivery after Stop must still be included.
    p.locator('#voiceInputBtn').dispatch_event('click')
    p.wait_for_function('voice.state==="idle" && calls.length===1')
    pcm = p.evaluate('calls[0].pcm')
    assert pcm[:2400] == [0] * 2400
    assert pcm[2400] == round(.7 * 32767)
    assert min(pcm[2401:5599]) >= 22936
    assert min(pcm[-5000:-4000]) >= 29489
    assert pcm[-4001] == round(.9 * 32767)
    assert pcm[-4000:] == [0] * 4000
    assert p.evaluate('stops') == p.evaluate('closes') == 1
    assert p.evaluate('sends') == 0


def test_cancelling_during_stop_grace_releases_microphone_without_upload(voice_page):
    p = voice_page
    start_recording(p)
    p.evaluate('pushAudio()')
    p.get_by_role('button', name='结束录音并识别', exact=True).click()
    p.wait_for_function('voice.state==="finishing"')
    p.keyboard.press('Escape')
    p.wait_for_timeout(400)  # Cancelled grace must not submit on its timer.
    assert p.evaluate('voice.state') == 'idle'
    assert p.evaluate('calls.length') == 0
    assert p.evaluate('stops') == p.evaluate('closes') == 1
    assert_no_visual_caption(p)


def test_all_routine_states_have_no_visual_caption_or_extra_composer_row(voice_page):
    p = voice_page
    initial_height = p.locator('.input-wrap').bounding_box()['height']
    p.evaluate('window.holdPermission=true;window.holdResponse=true')
    p.get_by_role('button', name='语音输入', exact=True).click()
    p.wait_for_function('voice.state==="requesting"')
    assert_no_visual_caption(p)
    p.evaluate('allowPermission()')
    p.wait_for_function('voice.state==="preparing"')
    assert_no_visual_caption(p)
    p.evaluate('pushAudio()')
    p.wait_for_function('voice.state==="recording"')
    assert_no_visual_caption(p)
    p.get_by_role('button', name='结束录音并识别', exact=True).click()
    p.wait_for_function('voice.state==="finishing"')
    assert_no_visual_caption(p)
    p.wait_for_function('voice.state==="transcribing" && calls.length===1')
    assert_no_visual_caption(p)
    p.evaluate('reply()')
    p.wait_for_function('voice.state==="idle"')
    assert_no_visual_caption(p)
    assert p.locator('.input-wrap').bounding_box()['height'] == initial_height
    p.evaluate('voice.cancel("已取消语音输入。")')
    assert_no_visual_caption(p)
    assert p.locator('.input-wrap').bounding_box()['height'] == initial_height


def test_host_error_handler_receives_one_real_error_without_local_error_line(voice_page):
    p = voice_page
    p.evaluate('''()=>{voice.dispose();window.voiceErrors=[];window.voice=DMateVoiceInput.mount({
      button:document.getElementById('voiceInputBtn'),input:document.getElementById('text'),
      status:document.getElementById('voiceInputStatus'),mediaDevices:fakeMedia,
      AudioContext:FakeAudio,fetch:transport,onError:message=>voiceErrors.push(message)});}''')
    p.evaluate('window.permissionDenied=true')
    p.get_by_role('button', name='语音输入', exact=True).click()
    p.wait_for_function('voice.state==="idle" && voiceErrors.length===1')
    assert '麦克风权限被拒绝' in p.evaluate('voiceErrors[0]')
    assert_no_visual_caption(p)
    p.evaluate('voice.refresh();voice.cancel();')
    assert p.evaluate('voiceErrors.length') == 1
    assert p.locator('#text').input_value() == '已有内容'


def test_short_recording_restores_idle_silently_and_can_record_again(voice_page):
    p = voice_page
    start_recording(p)
    p.get_by_role('button', name='结束录音并识别', exact=True).click()
    p.wait_for_function('voice.state==="idle"')
    assert p.get_by_role('alert').count() == 0
    assert p.locator('#voiceInputStatus').text_content() == ''
    assert_no_visual_caption(p)
    assert p.evaluate('calls.length') == 0
    start_recording(p)
    assert_no_visual_caption(p)
