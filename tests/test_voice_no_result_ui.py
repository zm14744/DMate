"""A dictation attempt with no usable text quietly returns to the composer."""
import pytest

from test_voice_input_ui import (
    assert_no_visual_caption,
    end_recording,
    start_recording,
    voice_page,
)


def mount_probe(page, outcome):
    page.evaluate('''outcome => {
      voice.dispose();
      window.voiceErrors=[];window.voiceTexts=[];window.failedFetchCalls=0;
      window.outcome=outcome;
      const input=document.getElementById('text');
      input.focus();input.setSelectionRange(2,4);
      window.voice=DMateVoiceInput.mount({
        button:document.getElementById('voiceInputBtn'),input,
        status:document.getElementById('voiceInputStatus'),
        mediaDevices:fakeMedia,AudioContext:FakeAudio,
        onError:message=>voiceErrors.push(message),onText:text=>voiceTexts.push(text),
        fetch:async(url,options)=>{
          if(window.outcome==='network'){
            failedFetchCalls++;throw new TypeError('Failed to fetch');
          }
          const response=await transport(url,options);
          if(window.outcome==='provider')return {ok:false,status:502,json:async()=>({
            ok:false,code:'asr_provider_error',
            error:'语音模型或词库调用失败，请检查服务配置后重试。'})};
          if(window.outcome==='invalid-json')return {ok:true,json:async()=>{throw new SyntaxError('Invalid JSON');}};
          if(window.outcome==='empty'||window.outcome==='whitespace')return {
            ok:true,json:async()=>({ok:true,recognized:false,text:window.outcome==='empty'?'':'  \\n '})};
          return response;
        }
      });
    }''', outcome)


def assert_idle_unchanged(page):
    page.wait_for_function('voice.state==="idle"')
    assert page.locator('#text').input_value() == '已有内容'
    assert page.locator('#text').evaluate('e=>[e.selectionStart,e.selectionEnd]') == [2, 4]
    assert page.evaluate('voiceErrors') == []
    assert page.evaluate('voiceTexts') == []
    assert page.evaluate('inputEvents') == page.evaluate('sends') == 0
    assert page.evaluate('stops') == page.evaluate('closes') == 1
    assert page.locator('#voiceInputStatus').text_content() == ''
    assert page.get_by_role('alert').count() == 0
    assert page.get_by_role('button', name='语音输入', exact=True).is_enabled()
    assert page.locator('#voiceInputBtn').get_attribute('aria-pressed') == 'false'
    assert page.locator('#voiceInputBtn').get_attribute('aria-busy') == 'false'
    assert_no_visual_caption(page)


@pytest.mark.parametrize('outcome', ['empty', 'whitespace', 'provider', 'network', 'invalid-json'])
def test_no_transcript_does_not_call_the_chat_error_handler(voice_page, outcome):
    page = voice_page
    mount_probe(page, outcome)
    initial_height = page.locator('.input-wrap').bounding_box()['height']
    start_recording(page)
    end_recording(page)
    page.wait_for_function('calls.length+failedFetchCalls===1 && voice.state==="idle"')
    assert_idle_unchanged(page)
    assert page.locator('.input-wrap').bounding_box()['height'] == initial_height


def test_short_attempt_is_quiet_and_never_calls_the_model(voice_page):
    page = voice_page
    mount_probe(page, 'empty')
    start_recording(page)
    page.get_by_role('button', name='结束录音并识别', exact=True).click()
    assert_idle_unchanged(page)
    assert page.evaluate('calls.length+failedFetchCalls') == 0


def test_no_result_releases_resources_and_next_dictation_still_inserts(voice_page):
    page = voice_page
    mount_probe(page, 'provider')
    start_recording(page)
    end_recording(page)
    page.wait_for_function('calls.length===1 && voice.state==="idle"')
    assert_idle_unchanged(page)
    page.evaluate('window.outcome="success"')
    start_recording(page)
    end_recording(page)
    page.wait_for_function('calls.length===2 && voice.state==="idle"')
    assert page.locator('#text').input_value() == '已有语音结果内容'
    assert page.evaluate('voiceTexts') == ['语音结果']
    assert page.evaluate('voiceErrors') == []
    assert page.evaluate('inputEvents') == 1
    assert page.evaluate('sends') == 0
    assert page.evaluate('stops') == page.evaluate('closes') == 2
