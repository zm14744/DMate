"""Batch image send uses actual JS transport, preserving each signed snapshot."""
from copy import deepcopy
import json
import subprocess

import pytest

from test_semantic_chat_snapshot_frontend import PROGRAM as BASE_PROGRAM, ROOT, NODE, context
from test_scan_drawing_separation import scan_page, open_scan


BATCH_OPERATIONS = r"""
 if(input.operation==='batch_send') {
   let number=0;
   for(const record of input.tasks) {
     number++;
     const saved=record.context;
     const task={id:saved.request_id,sessionId:'s',file:{name:'picture'+number+'.png'},
       sourceSha256:saved.source_sha256,originalUrl:'blob:picture'+number,
       state:record.state||'ready',draft:structuredClone(saved.document),initialDocument:structuredClone(saved.document),
       dirty:!!record.dirty,userRequest:record.userRequest||'',isQuestion:record.isQuestion!==false,groupId:record.groupId,error:'',notice:'',
       confirmation:record.saved===false?null:{document:structuredClone(saved.document),drawing_document:structuredClone(saved.document),semantic_context:saved},
       sending:false,confirming:false};
     vm.runInContext('ocrTasks',sandbox).set(task.id,task);
   }
   if(input.click){
     let completion;const original=sandbox.sendOcrBatch;
     sandbox.sendOcrBatch=()=>{completion=original();return completion;};
     sandbox.handleSendOrStop();await completion;
   } else if(input.double) await Promise.all([sandbox.sendOcrBatch(),sandbox.sendOcrBatch()]);
   else await sandbox.sendOcrBatch();
   result={requests,messages:sandbox.sessions[0].messages,notices,remaining:vm.runInContext('ocrTasks.size',sandbox)};
 } else if(input.operation==='batch_sanitize') {
   result=sandbox.sanitizeSemanticContexts(input.contexts,input.message??null);
 } else if(input.operation==='batch_merge') {
   const left=input.message,right={...left};delete right.semanticContexts;
   if(input.tamper)right.text='changed question';
   result=sandbox.mergeCloudMessage(left,right);
 } else if(input.operation==='batch_select') {
   const first=input.message;
   const latest={role:'user',text:input.latestText||'继续解释',...input.latest};
   const session={messages:[first,{role:'ai',text:'answer'},latest]};
   const target={index:0,role:'user',text:sandbox.ocrBatchQuestion(first.semanticContexts,'rendered_question_text')};
   if(input.tamperTarget)target.text='unrelated target';
   await sandbox.capturedExistingChat(session,target,input.options||{});
   result=requests[0].body;
 } else if(input.operation==='upload') {
"""
PROGRAM = BASE_PROGRAM.replace(" if(input.operation==='upload') {", BATCH_OPERATIONS).replace(
    'const fragments = [', "const fragments = [block('function handleSendOrStop()', '// -----------------------------\\n// 基础状态'),"
).replace(
    'requests.push({url,body});', "requests.push({url,body});if(url==='/graph/confirm'&&input.failConfirm===body.request_id)return {ok:false,json:async()=>({error:'结构校验失败'})};"
).replace(
    'const reviewed=input.reviewed;',
    "const reviewed=input.reviewed||{text:body.document.body_text,visualText:'公开边表 '+body.request_id,analysisVisualText:'内部边表 '+body.request_id};"
).replace('const sandbox={console, TextEncoder, AbortController,', 'const sandbox={console, TextEncoder, AbortController, structuredClone,')
PROGRAM = PROGRAM.replace('sandbox.requestAiReply=s=>sandbox.capturedExistingChat(s);',
    "sandbox.sessionBusyKey=id=>String(id??'');sandbox.getLatestUserMessage=s=>[...s.messages].reverse().find(m=>m.role==='user')||null;"
    "sandbox.requestAiReply=async s=>{await sandbox.capturedExistingChat(s);return {status:'success'};};")


def run(payload):
    if NODE is None:
        pytest.skip('Node unavailable')
    process = subprocess.run([NODE, '-e', PROGRAM], cwd=ROOT, input=json.dumps(payload, ensure_ascii=False),
                             text=True, capture_output=True, check=True)
    return json.loads(process.stdout)


def signed(index):
    result = context()
    result.update(source_sha256=f'{index:x}'*64, request_id=f'picture-{index}',
                  confirmation_token=f'token-{index}', document_sha256=f'{index:x}'*64,
                  revision=1, profile='editable-v1')
    result.pop('private', None)
    result['document'].pop('private', None)
    result['question_text'] = f'【题目文字】\n第{index}张图片求度数\n【图形信息】\n内部边表{index}'
    result['rendered_question_text'] = f'第{index}张图片求度数\n【图形信息】\n显示边表{index}'
    result['document']['body_text'] = f'第{index}张图片求度数'
    return result


def batch_message(count=4):
    contexts = [signed(i) for i in range(1, count+1)]
    question = '\n\n'.join(f'【图片 {i}】\n'+c['question_text'] for i,c in enumerate(contexts,1))
    rendered = '\n\n'.join(f'【图片 {i}】\n'+c['rendered_question_text'] for i,c in enumerate(contexts,1))
    return {'role':'user','source':'ocr','text':rendered+'\n\n【我的要求】\n完整解答',
            'apiText':'【当前指向题目】\n'+question+'\n【当前指向题目结束】\n完整解答',
            'semanticContexts':contexts}


@pytest.mark.parametrize('count',[1,4])
def test_same_group_combines_all_images_in_order_and_one_chat_request(count):
    result=run({'operation':'batch_send','click':True,'tasks':[{'context':signed(i),'groupId':'1'} for i in range(1,count+1)]})
    assert not result['notices']
    assert len(result['messages'])==1
    assert [r['url'] for r in result['requests']]==['/chat']
    payload=result['requests'][0]['body']
    assert 'semantic_context' not in payload
    assert [c['request_id'] for c in payload['semantic_contexts']]==[f'picture-{i}' for i in range(1,count+1)]
    assert [c['confirmation_token'] for c in payload['semantic_contexts']]==[f'token-{i}' for i in range(1,count+1)]
    assert len(result['messages'][0]['semanticContexts'])==count
    assert result['remaining']==0
    for i in range(1,count+1):assert f'【图片 {i}】' in payload['messages'][-1]['content']


def test_unsaved_ready_images_are_all_confirmed_before_one_ai_request():
    result=run({'operation':'batch_send','tasks':[{'context':signed(i),'saved':False,'groupId':'1'} for i in range(1,5)]})
    assert not result['notices']
    assert [r['url'] for r in result['requests']]==['/graph/session']+['/graph/confirm']*4+['/chat']
    assert [r['body']['request_id'] for r in result['requests'] if r['url']=='/graph/confirm']==[f'picture-{i}' for i in range(1,5)]
    assert len(result['messages'])==1


@pytest.mark.parametrize('state',['recognizing','failed'])
def test_unready_image_prevents_sending_any_of_its_ready_peers(state):
    result=run({'operation':'batch_send','tasks':[{'context':signed(1)},{'context':signed(2),'state':state}]})
    assert result['notices']
    assert result['requests']==[] and result['messages']==[] and result['remaining']==2


def test_double_send_cannot_duplicate_the_batch():
    result=run({'operation':'batch_send','double':True,'tasks':[{'context':signed(i),'saved':False,'groupId':'1'} for i in range(1,5)]})
    assert not result['notices']
    assert len([r for r in result['requests'] if r['url']=='/chat'])==1
    assert len(result['messages'])==1


def test_batch_snapshot_roundtrip_keeps_separate_tokens_and_rejects_duplicate_members():
    message=batch_message()
    result=run({'operation':'batch_sanitize','contexts':message['semanticContexts'],'message':message})
    assert [c['confirmation_token'] for c in result]==[f'token-{i}' for i in range(1,5)]
    contexts=[signed(1),signed(1)]
    assert run({'operation':'batch_sanitize','contexts':contexts}) is None
    assert run({'operation':'batch_sanitize','contexts':[signed(i) for i in range(1,6)]}) is None


def test_batch_is_kept_during_cloud_merge_but_not_rebound_to_changed_text():
    message=batch_message()
    result=run({'operation':'batch_merge','message':message})
    assert len(result['semanticContexts'])==4
    assert 'semantic_context' not in result
    assert 'semanticContexts' not in run({'operation':'batch_merge','message':message,'tamper':True})


def test_stored_batch_is_restored_without_changing_signature_fields():
    message=batch_message()
    result=run({'operation':'load','stored':{'sessions':[{'id':'s','messages':[message]}],'currentId':'s','deletedSessionIds':{}}})
    assert result['loaded'] is True
    restored=result['sessions'][0]['messages'][0]
    assert [c['confirmation_token'] for c in restored['semanticContexts']]==[f'token-{i}' for i in range(1,5)]
    assert [c['document_sha256'] for c in restored['semanticContexts']]==[f'{i:x}'*64 for i in range(1,5)]


def test_selected_batch_followup_uses_plural_snapshots_and_new_problem_does_not_inherit():
    message=batch_message()
    followup=run({'operation':'batch_select','message':message})
    assert len(followup['semantic_contexts'])==4
    assert 'semantic_context' not in followup
    new=run({'operation':'batch_select','message':message,'latest':{'text':'新题：求集合交集','manualIsQuestion':True}})
    assert 'semantic_contexts' not in new and 'semantic_context' not in new
    assert 'semantic_contexts' not in run({'operation':'batch_select','message':message,'tamperTarget':True})


def test_editor_save_closes_without_starting_ai(scan_page):
    page=scan_page
    page.evaluate('()=>{window.chatCalls=0;window.requestAiReply=()=>{chatCalls++;};}')
    open_scan(page)
    page.get_by_role('button',name='保存',exact=True).click()
    page.wait_for_function('posts.length===1 && !document.getElementById("graphEditorDialog").open')
    assert page.evaluate('chatCalls')==0


def test_any_confirmation_failure_prevents_all_ai_calls():
    result=run({'operation':'batch_send','failConfirm':'picture-2','tasks':[{'context':signed(i),'saved':False,'groupId':'1'} for i in range(1,5)]})
    assert result['notices']==['结构校验失败']
    assert not any(r['url']=='/chat' for r in result['requests'])
    assert result['messages']==[] and result['remaining']==4
