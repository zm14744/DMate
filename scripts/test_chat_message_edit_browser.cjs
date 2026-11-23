/* Start Flask first. Responses and classification are local fixtures, never model calls. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const reply = text => ({contentType:'text/event-stream',
 body:'event: final\ndata: '+JSON.stringify({reply:text})+'\n\n'});
const pause = ms => new Promise(resolve => setTimeout(resolve,ms));

async function checkPhoneComposer(browser) {
 const context = await browser.newContext({ viewport:{ width:390, height:844 },
  isMobile:true, hasTouch:true, serviceWorkers:'block' });
 const page = await context.newPage(), requests=[], errors=[];
 page.on('pageerror',error=>errors.push(error.message));
 await page.route('**/auth/me',route=>route.fulfill({json:{authenticated:false}}));
 await page.route('**/conversation/title',route=>route.fulfill({json:{}}));
 await page.route('**/chat',route=>{
  requests.push(route.request().postDataJSON());
  return route.fulfill(reply('手机编辑后的回答'));
 });
 await page.route('**/ocr',()=>{ throw new Error('Editing must not upload a new image'); });
 try {
  const original='第一行原消息\n第二行原消息';
  const regularDraft='原本尚未发送的聊天草稿';
  const editDraft='改好的消息\n跨过刷新后继续';
  await page.goto(baseURL,{waitUntil:'networkidle'});
  await page.evaluate(text=>{
   newChat();
   getCurrent().messages=[{role:'user',text,manualIsQuestion:false},{role:'ai',text:'原来的回答'}];
   saveState(); renderChat();
  },original);
  const input=page.locator('#text'), bar=page.locator('#chatComposerEditBar');
  const open=async()=>{
   await page.locator('.msg.user > .msg-bubble').tap();
   await page.locator('.chat-message-edit-button').click();
   await bar.waitFor({state:'visible'});
  };
  await input.fill(regularDraft);
  const icon=await page.locator('.chat-message-edit-button svg').evaluate(node=>node.outerHTML);
  await open();
  assert.equal(await input.inputValue(),original,'The full original message enters the phone composer');
  assert.equal(await input.evaluate(node=>node===document.activeElement),true);
  assert.equal(await bar.locator('svg').evaluate(node=>node.outerHTML),icon,'The editor reuses the exact message edit icon');
  assert.equal(await bar.innerText(),'','The strip has no visible heading or button text');
  assert.equal(await bar.locator('.modal-close-dot').getAttribute('id'),'chatComposerEditCancel');
  assert.equal(await page.locator('#imagePickerWrap').isHidden(),true);
  assert.equal(await page.locator('.chat-message-edit-input').count(),0);
  await page.evaluate(()=>enqueueOcrFiles([new File(['test'],'test.png',{type:'image/png'})]));
  assert.equal(await page.evaluate(()=>getSessionOcrTasks().length),0);

  await input.fill(editDraft);
  await page.setViewportSize({width:820,height:844});
  await page.locator('.chat-message-edit-input').waitFor();
  assert.equal(await page.locator('.chat-message-edit-input').inputValue(),editDraft);
  assert.equal(await input.inputValue(),regularDraft);
  await page.setViewportSize({width:390,height:844});
  await bar.waitFor({state:'visible'});
  assert.equal(await input.inputValue(),editDraft);
  await page.reload({waitUntil:'networkidle'});
  await bar.waitFor({state:'visible'});
  assert.equal(await input.inputValue(),editDraft,'Refreshing restores the edit draft in the same composer');
  await page.locator('#chatComposerEditCancel').click();
  assert.equal(await bar.isHidden(),true);
  assert.equal(await input.inputValue(),regularDraft,'Cancel restores the regular draft');
  assert.equal(await page.locator('#imagePickerWrap').isVisible(),true);
  assert.deepEqual(await page.evaluate(()=>getCurrent().messages.map(message=>message.text)),[original,'原来的回答']);
  assert.equal(requests.length,0);

  await open();
  await input.fill(editDraft);
  await page.locator('#sendBtn').click();
  await page.waitForFunction(()=>getCurrent().messages.some(message=>message.text==='手机编辑后的回答'));
  assert.equal(requests.length,1);
  assert.equal(requests[0].messages.at(-1).content,editDraft);
  assert.equal(await bar.isHidden(),true);
  assert.equal(await input.inputValue(),regularDraft,'Sending the edit also restores the regular draft');
  assert.deepEqual(errors,[]);
  console.log('PASS phone composer edit: full text, exact icon, no attachments, draft isolation, cancel and send');
 } finally { await context.close(); }
}

(async () => {
 const browser = await chromium.launch({headless:true,
  ...(process.env.CHROMIUM_EXECUTABLE_PATH ? {executablePath:process.env.CHROMIUM_EXECUTABLE_PATH} : {})});
 try {
  const context = await browser.newContext({viewport:{width:1440,height:1000},serviceWorkers:'block'});
  const page = await context.newPage(), errors=[], requests=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/auth/me',route=>route.fulfill({contentType:'application/json',body:'{"authenticated":false}'}));
  await page.route('**/analyze-questions',route=>route.fulfill({contentType:'application/json',body:'{"entries":[]}'}));
  await page.route('**/conversation/title',route=>route.fulfill({contentType:'application/json',body:'{}'}));
  await page.route('**/chat',route=>{requests.push({route,payload:route.request().postDataJSON()});});
  await page.goto(baseURL,{waitUntil:'networkidle'});
  const seed = messages => page.evaluate(messages=>{
   stopCurrentAiReply(); newChat(); const session=getCurrent();
   session.name='保留手动标题';session.nameSource='user';session.messages=messages;
   ensureSessionMessageIds(session); renderChat();renderSessions();
   window.editFixture={originals:[...session.messages]};
   return session.messages.map(message=>message.messageId);
  },messages);
  const open = async index => {
   const message=page.locator(`.msg[data-message-index="${index}"]`);
   await message.hover();await message.locator('.chat-message-edit-button').click();
  };
  const input = () => page.locator('.chat-message-edit-input');
  const requestCount = async count => {
   for(let n=0;n<200&&requests.length<count;n++)await pause(20);
   assert.equal(requests.length,count,'exactly one model request for each explicit send');
  };
  const finish = async (index,text) => {
   await requests[index].route.fulfill(reply(text));
   await page.waitForFunction(text=>getCurrent().messages.some(message=>message.role==='ai'&&message.text===text),text);
  };

  // Opening and canceling a draft leave both the original branch and live answer intact.
  await seed([{role:'user',text:'原来的请求',manualIsQuestion:false}]);
  await page.evaluate(()=>{window.editFixture.reply=requestAiReply(getCurrent(),{completeImmediately:true});});
  await requestCount(1); await open(0);
  await input().fill('尚未发送的修改');
  await input().evaluate(node=>node.setSelectionRange(2,5));
  await finish(0,'原来请求的完整回答');
  assert.equal(await input().inputValue(),'尚未发送的修改','a completed answer cannot erase an unsent draft');
  assert.deepEqual(await input().evaluate(node=>[node.selectionStart,node.selectionEnd]),[2,5]);
  await page.locator('.chat-message-edit-cancel').click();
  assert.deepEqual(await page.evaluate(()=>getCurrent().messages.map(message=>message.text)),
    ['原来的请求','原来请求的完整回答']);
  assert.equal(requests.length,1,'cancel does not call the model');
  console.log('PASS edit while generating: original reply completes, draft/focus survives render, Cancel retains branch');

  // Sending a draft while an older request is held cancels it and gives the edit a fresh identity.
  const ids=await seed([{role:'user',text:'旧输入',manualIsQuestion:false}]);
  await page.evaluate(()=>{window.editFixture.reply=requestAiReply(getCurrent(),{completeImmediately:true});});
  await requestCount(2); await open(0);
  await input().fill('修改后的输入');
  await input().press('Enter'); await requestCount(3);
  let branch=await page.evaluate(()=>({messages:getCurrent().messages.map(message=>({...message})),
    tombstones:getCurrent().deletedMessageIds, oldSame:getCurrent().messages[0]===editFixture.originals[0],
    busy:isSessionBusy(currentId),name:getCurrent().name}));
  assert.equal(branch.oldSame,false);assert.notEqual(branch.messages[0].messageId,ids[0]);
  assert.equal(await page.evaluate(()=>DMateChatEditDraft.snapshot()),null,'Send closes the draft lock before its replacement generates');
  assert.ok(branch.tombstones[ids[0]]);assert.equal(branch.busy,true);
  assert.equal(branch.name,'保留手动标题');
  assert.equal(requests[2].payload.messages.at(-1).content,'修改后的输入');
  await requests[1].route.fulfill(reply('不应复活的旧回答')).catch(()=>{});
  await finish(2,'修改后的回答');
  assert.deepEqual(await page.evaluate(()=>getCurrent().messages.map(message=>message.text)),['修改后的输入','修改后的回答']);
  assert.equal(await page.evaluate(()=>isSessionBusy(currentId)),false);
  assert.equal(await page.evaluate(()=>cloudUiEditInProgress()),false,'completed edited reply releases the cloud UI lock');
  console.log('PASS Send during generation aborts old work, tombstones old user identity, and commits only the new answer');

  // An earlier edit truncates all later turns without mutating independent saved work.
  const history=[{role:'user',text:'开始写一首诗 TASK_START',manualIsQuestion:false},
    {role:'ai',text:'开头回答 KEEP_PREFIX'}, {role:'user',text:'补充第二段 OLD_REQUEST',manualIsQuestion:false},
    {role:'ai',text:'过时的回答 OLD_ANSWER'}, {role:'user',text:'第三轮 OLD_SUFFIX',manualIsQuestion:false},
    {role:'ai',text:'第三轮回答 OLD_SUFFIX_ANSWER'}];
  const oldIds=await seed(history);
  await page.evaluate(()=>{editFixture.oldSnapshot=collectCloudSnapshot();});
  const saved=await page.evaluate(()=>{
   learningState.events.push({id:'edit-kept-event',sessionId:currentId,type:'practiced',points:['命题'],createdAt:1});
   learningState.wrongQuestions.push({id:'edit-kept-note',question:'保留的错题',notes:'保留的笔记',createdAt:1});
   return JSON.stringify(learningState);
  });
  await open(2); await input().fill('重新写第二段 NEW_REQUEST');
  await input().press('Shift+Enter');
  assert.ok((await input().inputValue()).endsWith('\n'));assert.equal(requests.length,3);
  await input().press('Enter');await requestCount(4);
  branch=await page.evaluate(()=>({ids:getCurrent().messages.map(message=>message.messageId),
    texts:getCurrent().messages.map(message=>message.text),deleted:getCurrent().deletedMessageIds,
    learning:JSON.stringify(learningState)}));
  assert.deepEqual(branch.ids.slice(0,2),oldIds.slice(0,2));
  assert.deepEqual(branch.texts,history.slice(0,2).map(message=>message.text).concat('重新写第二段 NEW_REQUEST'));
  for(const id of oldIds.slice(2))assert.ok(branch.deleted[id]);
  assert.equal(branch.learning,saved,'committed study events and independently saved notes remain intact');
  const payload=JSON.stringify(requests[3].payload.messages);
  assert.ok(payload.includes('TASK_START'));assert.ok(payload.includes('KEEP_PREFIX'));assert.ok(payload.includes('NEW_REQUEST'));
  for(const old of ['OLD_REQUEST','OLD_ANSWER','OLD_SUFFIX'])assert.ok(!payload.includes(old));
  await finish(3,'新的第二段');
  const merged=await page.evaluate(()=>mergeCloudSnapshots(collectCloudSnapshot(),editFixture.oldSnapshot)
    .sessions.sessions.flatMap(session=>session.messages.map(message=>message.text)));
  for(const old of ['OLD_REQUEST','OLD_ANSWER','OLD_SUFFIX'])assert.ok(!merged.some(text=>text.includes(old)),
    'an older synced snapshot cannot revive the discarded branch');
  console.log('PASS earlier edit replaces downstream history/context, preserves prefix IDs and saved learning/notes');

  // An asynchronous classifier belongs to the old object, never its replacement.
  await seed([{role:'user',text:'证明原条件 OLD_CLASSIFY',manualIsQuestion:true}]);
  await page.evaluate(()=>{
   editFixture.analyze=analyzeSingleQuestionTeaching;
   analyzeSingleQuestionTeaching=()=>new Promise(resolve=>{editFixture.resolveClassify=resolve;});
   queueManualQuestionClassification(getCurrent(),getCurrent().messages[0]);
   analyzeSingleQuestionTeaching=()=>Promise.resolve(null);
  });
  await open(0);await input().fill('请重新解释 NEW_CLASSIFY');
  await input().press('Enter');await requestCount(5);
  await page.evaluate(()=>{
   editFixture.resolveClassify({category:'命题逻辑',knowledge_points:['陈旧知识'],difficulty:'困难'});
   analyzeSingleQuestionTeaching=editFixture.analyze;
  });
  assert.equal(await page.evaluate(()=>getCurrent().messages[0].questionTeaching??null),null);
  await finish(4,'新分类回答');

  // The editor's persisted draft refers only to an existing user message in this account context.
  await open(0);await input().fill('刷新后保留的草稿');
  const draft=await page.evaluate(()=>DMateChatEditDraft.snapshot());
  assert.equal(draft.value,'刷新后保留的草稿');assert.ok(draft.messageId);
  assert.equal(await page.evaluate(draft=>DMateChatEditDraft.restore({...draft,messageId:'missing'}),draft),false);
  await page.evaluate(()=>{cloudSyncContextVersion++;renderChat();});
  assert.equal(await page.locator('.chat-message-edit-input').count(),0);
  assert.equal(await page.evaluate(()=>DMateChatEditDraft.snapshot()),null);
  console.log('PASS stale classifier and account-context drafts cannot update the edited branch');

  // A real browser ReadableStream delivers an initial delta and stays open during editing.
  await seed([{role:'user',text:'流式旧请求',manualIsQuestion:false}]);
  await page.evaluate(()=>{
   editFixture.fetch=window.fetch;editFixture.intercept=true;
   window.fetch=(url,options)=>{
    if(url==='/chat'&&editFixture.intercept){
     editFixture.intercept=false;
     return Promise.resolve(new Response(new ReadableStream({
      start(controller){
       editFixture.stream=controller;
       controller.enqueue(new TextEncoder().encode('event: delta\ndata: '+JSON.stringify({text:'正在显示的旧流式片段'})+'\n\n'));
      },cancel(){editFixture.streamCancelled=true;}
     }),{headers:{'Content-Type':'text/event-stream'}}));
    }
    return editFixture.fetch(url,options);
   };
   editFixture.reply=requestAiReply(getCurrent(),{completeImmediately:true});
  });
  await page.waitForFunction(()=>document.getElementById('chat').textContent.includes('正在显示的旧流式片段'));
  await open(0);await input().fill('替换流式请求');
  assert.equal(await page.evaluate(()=>isSessionBusy(currentId)),true);
  await input().press('Enter');await requestCount(6);
  const cancelled=await page.evaluate(async()=>{
   const result=await editFixture.reply;window.fetch=editFixture.fetch;
   return{status:result.status,cancelled:editFixture.streamCancelled,
    text:document.getElementById('chat').textContent};
  });
  assert.equal(cancelled.status,'cancelled');assert.equal(cancelled.cancelled,true);
  assert.ok(!cancelled.text.includes('正在显示的旧流式片段'));
  await finish(5,'替换流式后的回答');
  assert.deepEqual(await page.evaluate(()=>getCurrent().messages.map(message=>message.text)),['替换流式请求','替换流式后的回答']);
  console.log('PASS live SSE delta preview stays editable, is removed on Send, and its reader is canceled');

  for(const width of [390,1440]){
   await page.setViewportSize({width,height:900});
   await page.evaluate(()=>{renderChat();});
   if(width===390) await page.locator('.msg.user > .msg-bubble').click();
   const button=page.locator('.msg.user .chat-message-edit-button').first();
   const chrome=await button.evaluate(node=>{const r=node.getBoundingClientRect(),svg=node.querySelector('svg'),css=getComputedStyle(svg);
    return{width:r.width,height:r.height,icon:svg.dataset.icon,svgWidth:css.width,stroke:svg.getAttribute('stroke-width')};});
   assert.deepEqual(chrome,{width:32,height:32,icon:'pencil-line',svgWidth:'20px',stroke:'1.8'});
   assert.equal(await page.locator('.msg.ai .chat-message-edit-button').count(),0);
  }
  await page.evaluate(()=>DMateI18n.setLanguage('en',false));
  assert.equal(await page.locator('.chat-message-edit-button').first().getAttribute('aria-label'),'Edit message');
  await open(0);
  assert.equal(await input().inputValue(),'替换流式请求','UI language changes never rewrite the user draft');
  assert.equal(await page.locator('.chat-message-edit-cancel').textContent(),'Cancel');
  assert.equal(await page.locator('.chat-message-edit-send').textContent(),'Send');
  await page.locator('.chat-message-edit-cancel').click();
  assert.deepEqual(errors,[]);
  await context.close();
  console.log('PASS mobile/desktop Lucide action dimensions and user-only availability; no browser errors');

  // Cloud polling and an upload conflict must not replace a pending editor's objects.
  const cloud=await browser.newPage({viewport:{width:1440,height:1000},serviceWorkers:'block'});
  await cloud.route('**/auth/me',route=>route.fulfill({contentType:'application/json',body:'{"authenticated":false}'}));
  await cloud.goto(baseURL,{waitUntil:'networkidle'});
  await cloud.waitForFunction(()=>!accountVerificationOperation);
  const cloudLock=await cloud.evaluate(async()=>{
   newChat();const session=getCurrent();session.name='云同步测试';session.nameSource='user';
   session.messages=[{role:'user',text:'云端原消息',manualIsQuestion:false},{role:'ai',text:'云端原回答'}];
   ensureSessionMessageIds(session);renderChat();
   window.cloudEditFixture={fetch:accountFetch,session,original:session.messages[0],calls:0};
   accountState.authenticated=true;accountState.username='inline-edit-fixture';accountState.revision=1;
   accountState.syncing=false;cloudInitialSyncPending=false;cloudInitialSyncInFlight=false;
   cloudLivePollEnabled=true;cloudLivePollInFlight=false;cloudAppliedPartHashes=null;
   writeCloudSyncMeta({username:accountState.username,revision:1,dirty:false,sectionHashes:null});
   accountFetch=async()=>{cloudEditFixture.calls++;throw new Error('an open editor must postpone polling');};
   beginChatMessageEdit(currentId,0);
   const textarea=document.querySelector('.chat-message-edit-input');textarea.value='尚未提交的云同步草稿';
   textarea.dispatchEvent(new Event('input',{bubbles:true}));
   document.getElementById('text').focus();
   const result={locked:cloudUiEditInProgress(),nativeReminder:dmateCanShowClientUpdate(),
    unsaved:dmateHasUnsavedWork(),pulled:await pullLatestCloudSnapshot(),calls:cloudEditFixture.calls};
   cancelChatMessageEdit();result.unlocked=!cloudUiEditInProgress();
   result.nativeAfterCancel=dmateCanShowClientUpdate();
   return result;
  });
  assert.deepEqual(cloudLock,{locked:true,nativeReminder:false,unsaved:true,pulled:false,calls:0,
    unlocked:true,nativeAfterCancel:true});
  await cloud.evaluate(()=>{
   const fixture=cloudEditFixture;
   fixture.remote=JSON.parse(JSON.stringify(collectCloudSnapshot()));
   const remoteSession=fixture.remote.sessions.sessions.find(item=>item.id===currentId);
   remoteSession.deletedMessageIds=Object.fromEntries(remoteSession.messages.map(message=>[message.messageId,Date.now()]));
   remoteSession.messages=[];
   accountFetch=async(_url,options)=>{
    if(options.method!=='PUT')throw new Error('only the explicit upload is expected');
    fixture.calls++;
    if(fixture.calls===1)return new Promise(resolve=>{fixture.resolveConflict=resolve;});
    return{response:{status:200,ok:true},data:{ok:true,revision:3}};
   };
   fixture.push=pushCloudSnapshot(false);
   beginChatMessageEdit(currentId,0);
   const textarea=document.querySelector('.chat-message-edit-input');textarea.value='冲突合并时保留的草稿';
   textarea.dispatchEvent(new Event('input',{bubbles:true}));
   document.getElementById('text').focus();
   fixture.resolveConflict({response:{status:409,ok:false},data:{conflict:true,revision:2,data:fixture.remote}});
  });
  const held=await cloud.evaluate(async()=>{
   const fixture=cloudEditFixture,result=await fixture.push;
   clearTimeout(cloudSyncTimer);cloudSyncTimer=0;
   return{result,calls:fixture.calls,sameSession:getCurrent()===fixture.session,
    sameMessage:getCurrent().messages[0]===fixture.original,draft:DMateChatEditDraft.snapshot()?.value,
    dirty:readCloudSyncMeta().dirty,locked:cloudUiEditInProgress()};
  });
  assert.deepEqual(held,{result:false,calls:2,sameSession:true,sameMessage:true,
    draft:'冲突合并时保留的草稿',dirty:true,locked:true});
  const retried=await cloud.evaluate(async()=>{
   const fixture=cloudEditFixture;cancelChatMessageEdit();fixture.retryCalls=0;
   accountFetch=async()=>{
    fixture.retryCalls++;
    return fixture.retryCalls===1
     ?{response:{status:409,ok:false},data:{conflict:true,revision:3,data:fixture.remote}}
     :{response:{status:200,ok:true},data:{ok:true,revision:4}};
   };
   const result=await pushCloudSnapshot(false);
   accountFetch=fixture.fetch;stopCloudLivePolling();
   return{result,calls:fixture.retryCalls,messages:getCurrent().messages.length,
    deleted:Boolean(getCurrent().deletedMessageIds[fixture.original.messageId]),
    draft:DMateChatEditDraft.snapshot(),dirty:readCloudSyncMeta().dirty,locked:cloudUiEditInProgress()};
  });
  assert.deepEqual(retried,{result:true,calls:2,messages:0,deleted:true,draft:null,dirty:false,locked:false});
  await cloud.close();
  console.log('PASS cloud pulls/native updates wait for the draft; in-flight conflict defers replacement and later honors remote deletion');
  await checkPhoneComposer(browser);
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
