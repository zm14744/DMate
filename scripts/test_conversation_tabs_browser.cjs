/* Native tab links transfer one explicit conversation without shared guest storage. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const fixtureSessions = () => ['a', 'b'].map((suffix, index) => ({ id:'tab-' + suffix, name:'对话 ' + suffix,
  nameSource:'user', createdAt:100 + index, messages:[{messageId:'tab-message-' + suffix,role:'user',text:'私有聊天 ' + suffix}] }));
async function load(page, url = baseURL) {
  await page.goto(url, {waitUntil:'domcontentloaded'});
  await page.waitForFunction(() => guestWorkspaceReady && accountState.configured !== null
    && !accountVerificationOperation && !cloudInitialSyncPending && !cloudInitialSyncInFlight);
}
async function snapshot(page) {
  return page.evaluate(async () => ({ id:currentId, sessions:sessions.map(item => item.id),
    draft:document.getElementById('text').value,
    images:await Promise.all([...ocrTasks.values()].map(async task => ({sessionId:task.sessionId,
      content:await task.file.text(),state:task.state,draft:task.draft?.body_text,notice:task.error}))) }));
}
async function draggedURL(page, id) {
  await page.waitForSelector('[data-session-id="' + id + '"] .conversation-tab-link');
  return page.evaluate(id => {
    const row = document.querySelector('[data-session-id="' + id + '"]'), data = new DataTransfer();
    row.querySelector('[data-session-name]').dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:data}));
    return { plain:data.getData('text/plain'), uri:data.getData('text/uri-list'),
      types:Array.from(data.types),href:row.querySelector('a').href };
  }, id);
}
(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.CHROMIUM_EXECUTABLE_PATH
    ? {executablePath:process.env.CHROMIUM_EXECUTABLE_PATH} : {})});
  const context = await browser.newContext({viewport:{width:1500,height:1000},serviceWorkers:'block'});
  const errors = [], owners = new WeakMap(), snapshots = new Map();
  let paidRequests = 0;
  const respond = (route,data) => route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
  await context.route('**/auth/me', route => {
    const owner = owners.get(route.request().frame().page()) || '';
    return respond(route,{configured:true,authenticated:Boolean(owner),user:owner ? {username:owner} : null});
  });
  await context.route(/\/sync(?:\?|$)/, route => {
    const owner = owners.get(route.request().frame().page()) || '';
    if (route.request().method() === 'PUT') {
      const body = route.request().postDataJSON();
      snapshots.set(owner,{revision:Number(body.baseRevision || 1) + 1,data:body.data});
      return respond(route,{ok:true,...snapshots.get(owner)});
    }
    return respond(route,snapshots.get(owner) || {revision:1,data:{sessions:{sessions:[],currentId:null,deletedSessionIds:{}}}});
  });
  for (const path of ['**/chat','**/analyze-questions','**/conversation/title','**/notebook/analyze','**/ocr'])
    await context.route(path,route => { paidRequests++; return route.abort(); });
  async function page(owner = '') {
    const next = await context.newPage(); owners.set(next,owner);
    next.on('pageerror',error => errors.push(error.message));
    return next;
  }
  try {
    const source = await page();
    await load(source);
    await source.evaluate(rows => {
      sessions=rows; currentId='tab-a'; saveState(); renderAll();
      DMateConversationDrafts.set('tab-a',{text:'A 的未发送草稿',manualQuestionMode:true});
      DMateConversationDrafts.set('tab-b',{text:'B 的未发送草稿',manualQuestionMode:false});
      for (const [id,sessionId,state] of [['image-a','tab-a','recognizing'],['image-b','tab-b','ready']]) {
        const file = new File(['private ' + id], id + '.png',{type:'image/png'});
        ocrTasks.set(id,{id,groupId:'group-' + id,sessionId,state,file,originalUrl:URL.createObjectURL(file),
          contextVersion:cloudSyncContextVersion,controller:new AbortController(),draft:{body_text:'已有识别结果 ' + id,graphs:[]},
          initialDocument:{body_text:'已有识别结果 ' + id,graphs:[]},userRequest:'',isQuestion:false,error:'',notice:'',dirty:false});
      }
      renderOcrTasks();
    },fixtureSessions());
    const native = await draggedURL(source,'tab-a');
    assert.equal(native.uri,native.plain);
    assert.equal(native.href,native.uri);
    assert.deepEqual(native.types.sort(),['text/plain','text/uri-list']);
    assert.equal(new URL(native.uri).searchParams.get('conversation'),'tab-a');
    assert.ok(!native.uri.includes('私有') && !native.uri.includes('草稿') && !native.uri.includes('private'));
    const target = await page();
    await load(target,native.uri);
    await target.waitForFunction(() => currentId === 'tab-a' && ocrTasks.size === 1);
    let result = await snapshot(target);
    assert.deepEqual(result.sessions,['tab-a']);
    assert.equal(result.draft,'A 的未发送草稿');
    assert.deepEqual(result.images.map(image => [image.sessionId,image.content,image.state,image.draft]),
      [['tab-a','private image-a','failed','已有识别结果 image-a']]);
    assert.ok(result.images[0].notice.includes('原标签页'));
    assert.equal(await source.evaluate(() => ocrTasks.get('image-a').state),'recognizing','Source task keeps running');
    assert.equal(new URL(target.url()).searchParams.has('handoff'),false);
    const newTargetId = await target.evaluate(() => {
      newChat(); DMateConversationDrafts.set(currentId,{text:'目标页继续输入',manualQuestionMode:false}); return currentId;
    });
    await source.evaluate(() => {
      sessions.find(item => item.id === 'tab-a').messages.push({messageId:'tab-final-a',role:'ai',text:'源标签页完成的回答'});
      const image = ocrTasks.get('image-a'); image.state='ready'; image.draft.body_text='源标签页完成的识图';
      saveState();
    });
    await target.waitForFunction(() => sessions.find(item => item.id === 'tab-a').messages.some(message => message.messageId === 'tab-final-a')
      && ocrTasks.get('image-a').state === 'ready');
    assert.equal(await target.evaluate(() => currentId),newTargetId,'Final source results cannot switch the destination conversation');
    assert.equal(await target.locator('#text').inputValue(),'目标页继续输入','Final source results cannot replace the destination draft');
    await target.evaluate(() => { currentId='tab-a'; saveState(); renderAll(); });
    await target.reload({waitUntil:'domcontentloaded'});
    await target.waitForFunction(() => currentId === 'tab-a' && ocrTasks.size === 1 && !accountVerificationOperation);
    result = await snapshot(target);
    assert.equal(result.draft,'A 的未发送草稿');
    assert.equal(result.images[0].content,'private image-a');
    assert.equal(result.images[0].draft,'源标签页完成的识图');
    const blank = await page(); await load(blank);
    assert.deepEqual((await snapshot(blank)).sessions,[],'Ordinary guest tab stays empty');
    assert.equal(await source.evaluate(() => Object.values(localStorage).some(value => /私有聊天|未发送草稿|private image/.test(value))),false);
    await target.close();
    const closedReplacement = await page(); await load(closedReplacement);
    assert.deepEqual((await snapshot(closedReplacement)).sessions,[]);
    console.log('PASS native URI/plain URL, targeted guest conversation/draft/image handoff, refresh and fresh-tab privacy');
    console.log('PASS source final chat/recognition results arrive without changing destination selection or text');

    await source.evaluate(() => {
      ocrBatchRuns.set(sessionBusyKey('tab-a'),{preparing:true,cancelled:false});
      const file = new File(['private image-c'],'image-c.png',{type:'image/png'});
      ocrTasks.set('image-c',{id:'image-c',groupId:'group-image-c',sessionId:'tab-a',state:'ready',file,
        originalUrl:URL.createObjectURL(file),contextVersion:cloudSyncContextVersion,draft:{body_text:'识图 C',graphs:[]},
        initialDocument:{body_text:'识图 C',graphs:[]},userRequest:'',isQuestion:false,error:'',notice:'',dirty:false});
    });
    const preparingLink = await draggedURL(source,'tab-a'), preparing = await page();
    await load(preparing,preparingLink.uri);
    await preparing.waitForFunction(() => currentId === 'tab-a' && ocrTasks.size === 2);
    await preparing.evaluate(() => { ocrTasks.get('image-c').userRequest='目标页自己修改的要求'; });
    await source.evaluate(() => {
      ocrBatchRuns.delete(sessionBusyKey('tab-a')); ocrTasks.delete('image-a'); ocrTasks.delete('image-c');
      sessions.find(item => item.id === 'tab-a').messages.push({messageId:'tab-prepared-final',role:'ai',text:'图片准备之后完成的回答'});
      saveState();
    });
    await preparing.waitForFunction(() => sessions.find(item => item.id === 'tab-a').messages.some(message => message.messageId === 'tab-prepared-final')
      && !ocrTasks.has('image-a'));
    assert.equal(await preparing.evaluate(() => ocrTasks.get('image-c').userRequest),'目标页自己修改的要求');
    await preparing.close();
    console.log('PASS OCR preparing-phase completion, consumed-image cleanup and preservation of destination image edits');

    await source.evaluate(() => busySessionIds.add(sessionBusyKey('tab-a')));
    const localLink = await draggedURL(source,'tab-a'), localProcessing = await page();
    let localChat;
    await localProcessing.route('**/chat',route => { localChat=route; });
    await load(localProcessing,localLink.uri);
    await localProcessing.waitForFunction(() => currentId === 'tab-a' && !location.search.includes('handoff'));
    await localProcessing.evaluate(() => {
      const session=getCurrent(); session.messages.push({messageId:'destination-user',role:'user',text:'目标页自己的追问'});
      saveState(); renderAll(); window.destinationRequest=requestAiReply(session,{completeImmediately:true});
    });
    await localProcessing.waitForFunction(() => activeAiRequests.has(sessionBusyKey('tab-a')));
    await source.evaluate(() => {
      busySessionIds.delete(sessionBusyKey('tab-a'));
      sessions.find(item => item.id === 'tab-a').messages.push({messageId:'source-after-local',role:'ai',text:'原标签后完成'});
      saveState();
    });
    await localProcessing.waitForTimeout(1600);
    assert.equal(await localProcessing.evaluate(() => activeAiRequests.get(sessionBusyKey('tab-a')).controller.signal.aborted),false);
    assert.equal(await localProcessing.evaluate(() => currentId),'tab-a');
    assert.equal(await localProcessing.evaluate(() => sessions.some(item => String(item.id).includes('-sync-'))),false);
    await localChat.fulfill({contentType:'text/event-stream',body:'event: final\ndata: ' + JSON.stringify({reply:'目标页自己的回答'}) + '\n\n'});
    assert.equal(await localProcessing.evaluate(async () => (await destinationRequest).status),'success');
    assert.equal(await localProcessing.evaluate(() => getCurrent().messages.at(-1).text),'目标页自己的回答');
    await localProcessing.close();
    console.log('PASS a new request in the same destination conversation survives source completion without branching or switching');

    const expiredLink = await draggedURL(source,'tab-a');
    await source.evaluate(() => { window.realTabNow = Date.now; Date.now = () => realTabNow() + 7 * 60 * 1000; });
    const expired = await page(); await load(expired,expiredLink.uri);
    await expired.waitForFunction(() => !location.search.includes('handoff'),{timeout:9000});
    assert.deepEqual((await snapshot(expired)).sessions,[]);
    const refreshed = await source.evaluate(() => {
      const row=document.querySelector('[data-session-id="tab-a"]');
      row.querySelector('[data-session-name]').dispatchEvent(new MouseEvent('contextmenu',{bubbles:true}));
      return row.querySelector('a').href;
    });
    assert.notEqual(new URL(refreshed).searchParams.get('handoff'),new URL(expiredLink.uri).searchParams.get('handoff'),
      'Native context menu refreshes an expired link before the browser opens it');
    await source.evaluate(() => { Date.now=realTabNow; });
    const deletedLink = await draggedURL(source,'tab-b');
    await source.evaluate(() => { markSessionDeleted('tab-b'); sessions=sessions.filter(item => item.id !== 'tab-b'); saveState(); renderAll(); });
    const deleted = await page(); await load(deleted,deletedLink.uri);
    await deleted.waitForFunction(() => !location.search.includes('handoff'),{timeout:9000});
    assert.deepEqual((await snapshot(deleted)).sessions,[]);
    console.log('PASS expired capability and deleted source cannot import guest history');

    snapshots.set('account-a',{revision:1,data:{sessions:{sessions:fixtureSessions(),currentId:null,deletedSessionIds:{}}}});
    const accountSource = await page('account-a'); await load(accountSource);
    await accountSource.evaluate(() => { currentId='tab-b'; saveState(); renderAll(); });
    const accountLink = await draggedURL(accountSource,'tab-a');
    const accountTarget = await page('account-a'); await load(accountTarget,accountLink.uri);
    await accountTarget.waitForFunction(() => currentId === 'tab-a' && !location.search.includes('handoff'));
    assert.equal(await accountSource.evaluate(() => currentId),'tab-b','Opening another tab leaves the source selection alone');
    await accountSource.evaluate(() => {
      currentId='tab-b'; saveState(); renderAll();
      localStorage.setItem(STORAGE_KEY,JSON.stringify({sessions,currentId:'tab-b',deletedSessionIds:{}}));
    });
    await accountTarget.waitForTimeout(150);
    assert.equal(await accountTarget.evaluate(() => currentId),'tab-a','Shared storage cannot navigate another open tab');
    await accountTarget.locator('#desktopSidebarOpen').click();
    await accountTarget.locator('[data-session-id="tab-b"] [data-session-name]').click();
    await accountTarget.waitForFunction(() => new URL(location.href).searchParams.get('conversation') === 'tab-b');
    assert.equal(await accountSource.evaluate(() => currentId),'tab-b');
    await accountTarget.locator('[data-session-id="tab-b"] [data-session-name]').dblclick();
    await accountTarget.locator('#sessionRenameModal').waitFor({state:'visible'});
    await accountTarget.locator('#sessionRenameClose').click();
    await accountTarget.locator('[data-session-id="tab-a"] .conversation-tab-link').press('Enter');
    await accountTarget.waitForFunction(() => currentId === 'tab-a');
    await accountTarget.locator('[data-session-id="tab-b"] [data-session-name]').click();
    const widths = await accountTarget.locator('[data-session-id="tab-b"]').evaluate(row => ({
      row:row.clientWidth,link:row.querySelector('a').clientWidth,name:row.querySelector('span').clientWidth,
      ellipsis:getComputedStyle(row.querySelector('span')).textOverflow }));
    assert.ok(widths.link > 20 && widths.link < widths.row && widths.name <= widths.link);
    assert.equal(widths.ellipsis,'ellipsis');
    await accountTarget.locator('#conversationSidebar').screenshot({path:'/tmp/dmate-conversation-tab-links.png'});
    const direct = await page('account-a'); await load(direct,baseURL + '/?conversation=tab-a');
    await direct.waitForFunction(() => currentId === 'tab-a');
    const foreign = await page('account-b'); await load(foreign,accountLink.uri);
    await foreign.waitForFunction(() => !location.search.includes('handoff'),{timeout:9000});
    assert.deepEqual((await snapshot(foreign)).sessions,[],'A different verified account cannot claim the handoff');
    assert.equal(paidRequests,0,'Opening tabs never triggers recognition or generation');
    assert.deepEqual(errors,[]);
    console.log('PASS verified-account direct URLs, independent selection, route updates and foreign-account refusal');
  } finally { await context.close(); await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
