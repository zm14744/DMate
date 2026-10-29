"""Image grouping exercises production upload state/transport and actual popup CSS.

All contexts, images and AI replies are synthetic; no model service is called.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from test_ocr_batch_frontend import PROGRAM, ROOT, NODE, run, signed
from test_ocr_upload_layout import layout_page


def test_default_images_are_independent_requests_with_only_their_own_tokens():
    result = run({'operation': 'batch_send', 'tasks': [{'context': signed(i)} for i in range(1, 5)]})
    assert not result['notices']
    assert result['remaining'] == 0
    assert len(result['messages']) == 4
    chats = [row['body'] for row in result['requests'] if row['url'] == '/chat']
    assert len(chats) == 4
    for index, payload in enumerate(chats, 1):
        assert [context['request_id'] for context in payload['semantic_contexts']] == [f'picture-{index}']
        assert payload['semantic_contexts'][0]['confirmation_token'] == f'token-{index}'
        assert len(payload['messages']) == 1
        assert f'第{index}张图片求度数' in payload['messages'][0]['content']
        for other in set(range(1, 5)) - {index}:
            assert f'第{other}张图片求度数' not in payload['messages'][0]['content']


def test_matching_groups_integrate_once_and_supporting_images_keep_their_flags():
    result = run({'operation': 'batch_send', 'tasks': [
        {'context': signed(1), 'groupId': '1', 'isQuestion': True},
        {'context': signed(2), 'groupId': '1', 'isQuestion': False},
        {'context': signed(3), 'groupId': '3', 'isQuestion': True},
        {'context': signed(4), 'groupId': '4', 'isQuestion': False},
    ]})
    assert not result['notices']
    chats = [row['body'] for row in result['requests'] if row['url'] == '/chat']
    assert [[c['request_id'] for c in row['semantic_contexts']] for row in chats] == [
        ['picture-1', 'picture-2'], ['picture-3'], ['picture-4']]
    assert [row['ocrIsQuestion'] for row in result['messages']] == [True, True, False]
    assert result['messages'][0]['ocrGroup']['members'] == [
        {'requestId': 'picture-1', 'isQuestion': True}, {'requestId': 'picture-2', 'isQuestion': False}]
    assert result['remaining'] == 0


def test_nonadjacent_group_requirements_use_group_local_image_numbering():
    result = run({'operation': 'batch_send', 'tasks': [
        {'context': signed(1), 'groupId': '2', 'userRequest': '先求角一'},
        {'context': signed(2), 'groupId': '1', 'userRequest': '计算另一道'},
        {'context': signed(3), 'groupId': '2', 'userRequest': '再求角三'},
    ]})
    chats = [row['body'] for row in result['requests'] if row['url'] == '/chat']
    assert len(chats) == 2
    first = chats[0]['messages'][-1]['content']
    assert '图片 1：先求角一' in first and '图片 2：再求角三' in first
    assert '图片 3：' not in first and '计算另一道' not in first
    assert '图片 1：计算另一道' in chats[1]['messages'][-1]['content']


def test_group_metadata_survives_reload_cloud_merge_and_cannot_rebind_to_changed_members():
    message = run({'operation': 'batch_send', 'tasks': [
        {'context': signed(1), 'groupId': '1', 'isQuestion': False},
        {'context': signed(2), 'groupId': '1', 'isQuestion': False},
    ]})['messages'][0]
    restored = run({'operation': 'load', 'stored': {'sessions': [
        {'id': 's', 'messages': [message]}], 'currentId': 's', 'deletedSessionIds': {}}})
    assert restored['sessions'][0]['messages'][0]['ocrGroup'] == message['ocrGroup']
    assert restored['sessions'][0]['messages'][0]['ocrIsQuestion'] is False
    merged = run({'operation': 'batch_merge', 'message': message})
    assert merged['ocrGroup'] == message['ocrGroup']
    assert 'ocrGroup' not in run({'operation': 'batch_merge', 'message': message, 'tamper': True})
    tampered = json.loads(json.dumps(message))
    tampered['ocrGroup']['members'].reverse()
    assert 'ocrGroup' not in run({'operation': 'batch_merge', 'message': tampered})


QUEUE_PROGRAM = PROGRAM.replace(
    "sandbox.requestAiReply=async s=>{await sandbox.capturedExistingChat(s);return {status:'success'};};",
    """let calls=0; const timeline=[];
    sandbox.requestAiReply=async (session, options)=>{
      calls++; const call=calls;
      if(!options.completeImmediately || options.expectedUserMessage!==sandbox.getLatestUserMessage(session))
        throw Error('queue did not pin its current user message');
      timeline.push('begin'+call);
      await new Promise(resolve=>setTimeout(resolve, 5));
      await sandbox.capturedExistingChat(session);
      if(input.failAt===call) {timeline.push('error'+call);return {status:'error'};}
      if(input.stopAt===call) {sandbox.cancelOcrBatchRun('s');timeline.push('stop'+call);return {status:'cancelled'};}
      session.messages.push({role:'ai',text:'answer'+call});
      if(input.switchAt===call){sandbox.pauseOcrBatchRun('s');sandbox.currentId='other';if(input.switchBack)sandbox.currentId='s';}
      if(input.deleteAt===call){sandbox.deletedSessionIds.s=1;sandbox.sessions.splice(0,1);}
      timeline.push('finish'+call);return {status:'success'};
    };"""
).replace("result={requests,messages:sandbox.sessions[0].messages,notices,remaining:vm.runInContext('ocrTasks.size',sandbox)};",
    "result={requests,messages:sandbox.sessions[0]?.messages||[],notices,timeline,currentId:sandbox.currentId,remaining:vm.runInContext('ocrTasks.size',sandbox)};")
QUEUE_PROGRAM = QUEUE_PROGRAM.replace('else await sandbox.sendOcrBatch();',
    "else await sandbox.sendOcrBatch();if(input.retry){input.failAt=null;input.stopAt=null;sandbox.currentId='s';await sandbox.sendOcrBatch();}")
QUEUE_PROGRAM = QUEUE_PROGRAM.replace('const requests=[], notices=[];',
    "const requests=[], notices=[];const typed={value:input.sharedRequest||'',dispatchEvent(){}};")
QUEUE_PROGRAM = QUEUE_PROGRAM.replace('document:{getElementById:()=>null,querySelector:()=>null}',
    "document:{getElementById:id=>id==='text'?typed:null,querySelector:()=>null}")
QUEUE_PROGRAM = QUEUE_PROGRAM.replace('const sandbox={console, TextEncoder, AbortController, structuredClone,',
    'const sandbox={console, TextEncoder, AbortController, structuredClone, Event,')
QUEUE_PROGRAM = QUEUE_PROGRAM.replace("requests.push({url,body});if(url==='/graph/confirm'", "requests.push({url,body});if(url==='/graph/confirm'&&input.stopConfirm===body.request_id)sandbox.cancelOcrBatchRun('s');if(url==='/graph/confirm'")


def queued(payload):
    if NODE is None:
        pytest.skip('Node unavailable')
    process = subprocess.run([NODE, '-e', QUEUE_PROGRAM], cwd=ROOT, input=json.dumps(payload, ensure_ascii=False),
                             text=True, capture_output=True, check=True)
    return json.loads(process.stdout)


def test_queue_waits_for_each_answer_and_preserves_message_pair_order():
    result = queued({'operation': 'batch_send', 'tasks': [{'context': signed(i)} for i in range(1, 5)]})
    assert result['timeline'] == [item for i in range(1, 5) for item in (f'begin{i}', f'finish{i}')]
    assert [row['role'] for row in result['messages']] == ['user', 'ai'] * 4
    assert result['remaining'] == 0


@pytest.mark.parametrize('event', ['failAt', 'stopAt'])
def test_error_or_stop_keeps_current_and_unsent_groups_and_retry_reuses_the_user_message(event):
    payload = {'operation': 'batch_send', event: 2, 'tasks': [{'context': signed(i)} for i in range(1, 5)]}
    result = queued(payload)
    assert result['remaining'] == 3
    assert len([row for row in result['requests'] if row['url'] == '/chat']) == 2
    assert [row['role'] for row in result['messages']] == ['user', 'ai', 'user']
    retry = queued({**payload, 'retry': True})
    assert retry['remaining'] == 0
    assert len([row for row in retry['messages'] if row['role'] == 'user']) == 4
    assert [row['role'] for row in retry['messages']] == ['user', 'ai'] * 4


def test_stop_during_confirmation_sends_no_ai_and_keeps_every_image():
    result = queued({'operation': 'batch_send', 'stopConfirm': 'picture-2',
                     'tasks': [{'context': signed(i), 'saved': False} for i in range(1, 5)]})
    assert result['remaining'] == 4 and not result['messages'] and not result['notices']
    assert not any(row['url'] == '/chat' for row in result['requests'])


@pytest.mark.parametrize('switch_back', [False, True])
def test_switching_conversation_pauses_remaining_groups_without_switching_it_back(switch_back):
    result = queued({'operation': 'batch_send', 'switchAt': 1, 'switchBack': switch_back,
                     'tasks': [{'context': signed(i)} for i in range(1, 5)]})
    assert result['remaining'] == 3
    assert len([row for row in result['requests'] if row['url'] == '/chat']) == 1
    assert result['currentId'] == ('s' if switch_back else 'other')


def test_deleting_session_stops_future_groups():
    result = queued({'operation': 'batch_send', 'deleteAt': 1,
                     'tasks': [{'context': signed(i)} for i in range(1, 5)]})
    assert result['remaining'] == 3
    assert len([row for row in result['requests'] if row['url'] == '/chat']) == 1


@pytest.mark.parametrize('event', ['failAt', 'stopAt', 'switchAt'])
def test_shared_request_survives_partial_failure_or_pause_and_retry(event):
    result = queued({'operation': 'batch_send', event: 2, 'retry': True,
                     'sharedRequest': '只解第2问',
                     'tasks': [{'context': signed(i)} for i in range(1, 5)]})
    assert result['remaining'] == 0
    assert len([row for row in result['messages'] if row['role'] == 'user']) == 4
    requests = [row['body'] for row in result['requests'] if row['url'] == '/chat']
    assert all('只解第2问' in row['messages'][-1]['content'] for row in requests)
    assert sum([c['request_id'] for c in row['semantic_contexts']] == ['picture-1'] for row in requests) == 1


def test_later_oversized_group_is_rejected_before_any_first_group_request():
    large = signed(4)
    large['question_text'] = large['rendered_question_text'] = '很长的题目' * 7000
    result = run({'operation': 'batch_send', 'tasks': [{'context': signed(1)}, {'context': large}]})
    assert result['notices']
    assert result['remaining'] == 2 and not result['messages']
    assert not any(row['url'] == '/chat' for row in result['requests'])


@pytest.mark.parametrize('layout_page', [
    (1440, 900, 'light'), (1440, 900, 'dark'), (390, 844, 'light'), (390, 844, 'dark'),
], indirect=True)
def test_group_popup_defaults_dots_red_close_and_bounded_layout(layout_page):
    page = layout_page
    source = (ROOT / 'static/script.js').read_text()
    helpers = source[source.index('function nextOcrGroupId()'):source.index('function renderOcrTasks()')]
    page.add_style_tag(content=(ROOT / 'static/image-groups.css').read_text())
    page.add_style_tag(content=(ROOT / 'static/chat-composer.css').read_text())
    page.add_style_tag(content=(ROOT / 'static/modal-chrome.css').read_text())
    page.add_script_tag(content='window.OCR_MAX_CONCURRENT=4;window.ocrBatchPreparing=false;window.ocrSolvingSessions=new Set();' + helpers)
    page.evaluate("""() => {
      window.renderOcrTasks=window.renderTasks;
      for(let i=1;i<=4;i++)ocrTasks.set('picture-'+i,{id:'picture-'+i,file:{name:'数学题目'+i+'.png'},
        originalUrl:'data:image/png;base64,iVBORw0KGgo=',state:'recognizing',startedAt:0,finishedAt:null});
      renderTasks();document.getElementById('imageInput').dataset.identity='same-native-picker';
    }""")
    group_button = page.get_by_role('button', name='分组', exact=True)
    header = page.locator('.ocr-task-panel-head').bounding_box()
    button = group_button.bounding_box()
    assert button['x'] > header['x'] + header['width'] / 2
    before = page.locator('#ocrTaskPanel').bounding_box()
    group_button.click()
    dialog = page.get_by_role('dialog', name='分组', exact=True)
    assert dialog.is_visible()
    assert page.locator('.ocr-group-row').count() == 4
    assert [page.get_by_label(f'图片{i}组别').input_value() for i in range(1, 5)] == ['1', '2', '3', '4']
    assert page.locator('.ocr-group-question-choice[aria-pressed="true"]').all_text_contents() == ['是'] * 4
    assert page.locator('#ocrTaskPanel').bounding_box() == before
    bounds = dialog.bounding_box()
    assert bounds['x'] >= 0 and bounds['y'] >= 0
    assert bounds['x'] + bounds['width'] <= page.viewport_size['width'] + 1
    assert bounds['y'] + bounds['height'] <= page.viewport_size['height'] + 1
    colors = dialog.evaluate("e=>({background:getComputedStyle(e).backgroundColor,color:getComputedStyle(e).color})")
    if page.locator('body').get_attribute('data-appearance-theme') == 'dark':
        assert colors['background'] != 'rgb(255, 255, 255)' and colors['color'] != 'rgb(30, 41, 59)'
    close = page.get_by_role('button', name='关闭分组', exact=True)
    assert close.evaluate("e=>getComputedStyle(e).backgroundColor") == 'rgb(239, 68, 68)'
    close_box = close.bounding_box()
    assert close_box['width'] == close_box['height'] == (22 if page.viewport_size['width'] <= 760 else 20)
    assert close_box['x'] > bounds['x'] + bounds['width'] / 2
    assert close.evaluate("e=>getComputedStyle(e).outlineStyle") == 'none'
    dot = page.locator('.ocr-group-question-choice[aria-pressed="true"] .ocr-group-question-dot').first
    assert dot.bounding_box()['width'] >= 20
    assert dot.evaluate("e=>getComputedStyle(e).borderRadius") == '50%'
    assert dot.evaluate("""e=>{const probe=document.createElement('i');probe.style.background='var(--accent)';
      e.append(probe);const same=getComputedStyle(probe).backgroundColor===getComputedStyle(e).backgroundColor;
      probe.remove();return same;}""")
    group_field = page.get_by_label('图片2组别')
    group_field.focus()
    group_field.select_option('1')
    assert group_field.evaluate('e=>e===document.activeElement')
    page.get_by_role('group', name='图片2是否为题目', exact=True).get_by_role('button', name='否', exact=True).click()
    assert page.evaluate("partitionOcrTasks([...ocrTasks.values()]).map(g=>g.tasks.map(t=>t.id))") == [
        ['picture-1', 'picture-2'], ['picture-3'], ['picture-4']]
    close.click()
    assert not dialog.is_visible()
    assert page.locator('#imageInput').get_attribute('data-identity') == 'same-native-picker'
    group_button.click()
    assert page.get_by_label('图片2组别').input_value() == '1'
    assert page.get_by_role('group', name='图片2是否为题目', exact=True).get_by_role('button', name='否', exact=True).get_attribute('aria-pressed') == 'true'
    # A large filename list scrolls internally; its close control stays fixed.
    page.evaluate("""() => {for(const task of ocrTasks.values()) task.file.name='很长的数学题目名称'.repeat(30)+'.png';
      document.getElementById('ocrGroupingDialog').dataset.fingerprint='';renderOcrGrouping(document.getElementById('ocrTaskPanel'),true);}""")
    close_before = close.bounding_box()
    page.get_by_label('图片4组别').scroll_into_view_if_needed()
    assert close.is_visible() and close.bounding_box() == close_before
    assert page.locator('.ocr-group-list').evaluate('e=>e.scrollWidth<=e.clientWidth+1')
    page.keyboard.press('Escape')
    assert not dialog.is_visible()
