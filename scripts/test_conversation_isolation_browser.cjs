/* Start Flask first. All model/OCR/account requests use local fixtures. */
'use strict';
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const baseline = process.env.DMATE_TEST_BASELINE_HEAD === '1';
const json = value => ({contentType:'application/json',body:JSON.stringify(value)});

async function setup(browser, width) {
  const context = await browser.newContext({viewport:{width,height:1000},serviceWorkers:'block'});
  const page = await context.newPage();
  const errors = [], unexpected = [], chats = [], recognitions = [], confirmations = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/auth/me', route => route.fulfill(json({configured:true,authenticated:false})));
  await page.route(/\/(?:analyze-questions|classify|conversation\/title)(?:\?|$)/,
    route => route.fulfill(json({entries:[]})));
  await page.route(/\/(?:ocr(?:\/[^?]*)?|graph\/[^?]*)(?:\?|$)/, route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/graph/session') return route.fulfill(json({ok:true}));
    if (path === '/ocr/cancel') return route.fulfill(json({ok:true}));
    if (path === '/ocr') { recognitions.push({route}); return; }
    if (path === '/graph/confirm') {
      confirmations.push({route,payload:route.request().postDataJSON()}); return;
    }
    unexpected.push(path); return route.abort();
  });
  await page.route('**/chat', route => {
    chats.push({route,payload:route.request().postDataJSON()});
  });
  if (baseline) {
    const script = execFileSync('git',['show','HEAD:static/script.js'],{encoding:'utf8'});
    await page.route('**/static/script.js?*', route => route.fulfill({contentType:'application/javascript',body:script}));
  }
  await page.goto(baseURL,{waitUntil:'networkidle'});
  await page.waitForFunction(() => !accountVerificationOperation);
  return {context,page,errors,unexpected,chats,recognitions,confirmations};
}

async function create(page, name) {
  return page.evaluate(name => {
    newChat(); const session = getCurrent(); session.name = name; session.nameSource = 'user';
    saveState(); renderSessions(); return session.id;
  },name);
}

async function select(page, id) {
  if (await page.evaluate(id => String(currentId) === String(id),id)) return;
  await openSidebar(page);
  const row = page.locator(`.session[data-session-id="${id}"] [data-session-name]`);
  await row.click();
  await page.waitForFunction(id => String(currentId) === String(id),id);
}

async function openSidebar(page) {
  if (!await page.evaluate(() => isMobileAppShell())) {
    if (await page.evaluate(() => document.documentElement.dataset.desktopSidebar !== 'expanded')) await page.locator('#desktopSidebarOpen').click();
  } else if (!await page.evaluate(() => document.body.classList.contains('mobile-left-open'))) {
    await page.locator('#mobileNavBtn').click();
  }
}

async function waitForCount(page, list, count, label) {
  await assert.doesNotReject(async () => {
    const deadline = Date.now() + 8000;
    while (list.length < count && Date.now() < deadline) await page.waitForTimeout(25);
    assert.equal(list.length,count,label);
  });
}

async function completeChat(request, reply, cancelled = false) {
  const body = 'event: delta\ndata: ' + JSON.stringify({text:reply}) + '\n\n'
    + 'event: final\ndata: ' + JSON.stringify({reply}) + '\n\n';
  try { await request.route.fulfill({contentType:'text/event-stream',body}); }
  catch (error) { if (!cancelled) throw error; }
}

async function sendText(fixture, id, text) {
  const {page,chats} = fixture;
  await select(page,id);
  await page.locator('#text').fill(text);
  const count = chats.length + 1;
  await page.locator('#sendBtn').click();
  await waitForCount(page,chats,count,'one request starts in its own conversation');
  return chats[count-1];
}

async function waitForAnswer(page, id, reply) {
  await page.waitForFunction(({id,reply}) => {
    const session = sessions.find(value => String(value.id) === String(id));
    return session?.messages.some(value => value.role === 'ai' && value.text === reply)
      && !isSessionBusy(id) && !isSessionPendingAiStart(id)
      && !(typingContext?.session === session);
  },{id,reply});
}

async function deleteConversation(page, id) {
  await openSidebar(page);
  const row = page.locator(`.session[data-session-id="${id}"]`);
  await row.hover();
  await row.locator('.del').click();
  await page.locator('#appConfirmConfirm').click();
  await page.waitForFunction(id => !sessions.some(session => String(session.id) === String(id)),id);
  await page.evaluate(() => closeMobileShellDrawers());
}

async function draftIsolation(fixture) {
  const {page} = fixture;
  await page.locator('#text').fill('首页草稿 HOME');
  const a = await create(page,'隔离 A');
  assert.equal(await page.locator('#text').inputValue(),'','a newly created conversation starts empty');
  await page.locator('#text').fill('A 未发送的草稿');
  await page.locator('[data-manual-question="yes"]').click();
  const b = await create(page,'隔离 B');
  assert.equal(await page.locator('#text').inputValue(),'','B does not inherit the A draft');
  assert.equal(await page.locator('[data-manual-question="no"]').getAttribute('aria-pressed'),'true');
  await page.locator('#text').fill('B 未发送的草稿');
  await select(page,a);
  assert.equal(await page.locator('#text').inputValue(),'A 未发送的草稿');
  assert.equal(await page.locator('[data-manual-question="yes"]').getAttribute('aria-pressed'),'true');
  await select(page,b);
  assert.equal(await page.locator('#text').inputValue(),'B 未发送的草稿');
  assert.equal(await page.locator('[data-manual-question="no"]').getAttribute('aria-pressed'),'true');
  await page.evaluate(() => { checkpointGuestDrafts(); saveState(); });
  await page.reload({waitUntil:'networkidle'});
  await page.waitForFunction(() => !accountVerificationOperation);
  assert.equal(await page.locator('#text').inputValue(),'B 未发送的草稿','the active draft survives refresh');
  await select(page,a);
  assert.equal(await page.locator('#text').inputValue(),'A 未发送的草稿','other conversation drafts survive refresh');
  const empty = await create(page,'返回首页');
  await deleteConversation(page,empty);
  assert.equal(await page.locator('#text').inputValue(),'首页草稿 HOME','home retains its independent draft');
  const count = fixture.chats.length + 1;
  await page.locator('#sendBtn').click();
  await waitForCount(page,fixture.chats,count,'home input creates one new conversation and request');
  const home = await page.evaluate(() => currentId);
  await completeChat(fixture.chats[count-1],'首页回复');
  await waitForAnswer(page,home,'首页回复');
  await select(page,a);
  assert.equal(await page.locator('#text').inputValue(),'A 未发送的草稿','sending from home does not clear A');
  return {a,b};
}

async function concurrentChat(fixture) {
  const {page} = fixture;
  const a = await create(page,'并行 A');
  const firstA = await sendText(fixture,a,'A_FIRST');
  const b = await create(page,'并行 B');
  const firstB = await sendText(fixture,b,'B_FIRST');
  assert.equal(await page.evaluate(() => activeAiRequests.size),2,'both requests are active together');
  assert.ok(firstA.payload.messages.at(-1).content.includes('A_FIRST'));
  assert.ok(!JSON.stringify(firstA.payload).includes('B_FIRST'));
  assert.ok(firstB.payload.messages.at(-1).content.includes('B_FIRST'));
  assert.ok(!JSON.stringify(firstB.payload).includes('A_FIRST'));
  await completeChat(firstB,'乙首轮回复');
  await waitForAnswer(page,b,'乙首轮回复');
  await page.locator('#text').fill('B 草稿在 A 后台完成时保留');
  await completeChat(firstA,'甲首轮回复');
  await waitForAnswer(page,a,'甲首轮回复');
  assert.equal(await page.locator('#text').inputValue(),'B 草稿在 A 后台完成时保留');
  assert.ok(!await page.locator('#chat').innerText().then(text => text.includes('甲首轮回复')));
  await select(page,a);
  assert.ok((await page.locator('#chat').innerText()).includes('甲首轮回复'),await page.locator('#chat').innerText());

  const secondA = await sendText(fixture,a,'A_AFTER_STOP');
  const secondB = await sendText(fixture,b,'B_STOP_ONLY');
  await page.locator('#sendBtn').click();
  await page.waitForFunction(({a,b}) => isSessionBusy(a) && !isSessionBusy(b),{a,b});
  await completeChat(secondB,'乙停止后迟到回复',true);
  await completeChat(secondA,'甲停止测试回复');
  await waitForAnswer(page,a,'甲停止测试回复');
  assert.equal(await page.evaluate(id => sessions.find(session => session.id === id).messages.some(
    message => message.text === '乙停止后迟到回复'),b),false,'stopped B cannot commit a late response');

  const thirdA = await sendText(fixture,a,'A_DELETE_ONLY');
  const thirdB = await sendText(fixture,b,'B_SURVIVES_DELETE');
  await deleteConversation(page,a);
  assert.equal(await page.evaluate(() => isSessionBusy(currentId)),true,'deleting A does not stop active B');
  await completeChat(thirdA,'甲删除后迟到回复',true);
  await completeChat(thirdB,'乙删除测试回复');
  await waitForAnswer(page,b,'乙删除测试回复');
  assert.equal(await page.evaluate(id => sessions.some(session => session.id === id),a),false);
  const texts = await page.evaluate(id => sessions.find(session => session.id === id).messages.map(message => message.text),b);
  assert.ok(texts.includes('乙首轮回复') && texts.includes('乙删除测试回复'));
  assert.ok(!texts.some(text => /甲首轮回复|甲停止测试回复|迟到回复/.test(text)));
}

async function upload(fixture, sessionId, name) {
  const {page,recognitions} = fixture;
  await select(page,sessionId);
  const count = recognitions.length + 1;
  await page.locator('#imageInput').setInputFiles({name:name + '.svg',mimeType:'image/svg+xml',
    buffer:Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="60" height="40"><rect width="60" height="40" fill="white"/></svg>')});
  await waitForCount(page,recognitions,count,'an upload starts its own recognition');
  const task = await page.evaluate(({sessionId,name}) => {
    const task = [...ocrTasks.values()].find(task => task.sessionId === sessionId && task.file.name === name + '.svg');
    return task && {id:task.id,sessionId:task.sessionId};
  },{sessionId,name});
  assert.ok(task,'the uploaded file belongs to its starting conversation');
  return {...task,recognition:recognitions[count-1]};
}

async function recognize(task, text, cancelled = false) {
  try { await task.recognition.route.fulfill(json({text,document:{body_text:text,graphs:[]},source_sha256:'a'.repeat(64)})); }
  catch (error) { if (!cancelled) throw error; }
}

async function confirm(entry, cancelled = false) {
  const {document,source_sha256,request_id} = entry.payload;
  const context = {document,source_sha256,request_id,question_text:document.body_text,
    rendered_question_text:document.body_text,confirmation_token:'local-confirm-' + request_id,
    document_sha256:'b'.repeat(64),revision:1,profile:'editable-v1'};
  try { await entry.route.fulfill(json({document,drawing_document:document,
    confirmation_token:context.confirmation_token,revision:1,semantic_context:context})); }
  catch (error) { if (!cancelled) throw error; }
}

async function waitTask(page, id, state) {
  await page.waitForFunction(({id,state}) => ocrTasks.get(id)?.state === state,{id,state});
}

async function visibleTasks(page) {
  return page.locator('.ocr-task-card').evaluateAll(cards => cards.map(card => card.dataset.ocrTaskId));
}

async function imageIsolation(fixture) {
  const {page,chats,confirmations} = fixture;
  const a = await create(page,'图片 A');
  await page.locator('#text').fill('A_IMAGE_REQUIREMENT');
  const imageA = await upload(fixture,a,'image-A');
  assert.deepEqual(await visibleTasks(page),[imageA.id]);
  const b = await create(page,'图片 B');
  assert.deepEqual(await visibleTasks(page),[],'A uploads are absent from B');
  assert.equal(await page.locator('#text').isVisible(),true,'A recognition does not occupy B composer');
  const textB = await sendText(fixture,b,'B_TEXT_DURING_A_RECOGNITION');
  await completeChat(textB,'乙文字回复');
  await waitForAnswer(page,b,'乙文字回复');
  await page.locator('#text').fill('B_IMAGE_REQUIREMENT');
  const imageB = await upload(fixture,b,'image-B');
  assert.deepEqual(await visibleTasks(page),[imageB.id]);
  assert.equal(await page.evaluate(() => [...ocrTasks.values()].filter(task => task.state === 'recognizing').length),2,
    'both conversations recognize images simultaneously');
  await recognize(imageB,'B_IMAGE_QUESTION');
  await waitTask(page,imageB.id,'ready');
  await page.locator('#sendBtn').click();
  await waitForCount(page,confirmations,1,'B confirmation starts');
  assert.equal(confirmations[0].payload.request_id,imageB.id);
  await select(page,a);
  await recognize(imageA,'A_IMAGE_QUESTION');
  await waitTask(page,imageA.id,'ready');
  assert.deepEqual(await visibleTasks(page),[imageA.id]);
  await page.locator('#sendBtn').click();
  await waitForCount(page,confirmations,2,'A confirmation also starts while B confirmation is pending');
  assert.equal(confirmations[1].payload.request_id,imageA.id);
  await select(page,b);
  const chatCount = chats.length;
  await confirm(confirmations[0]);
  await waitForCount(page,chats,chatCount+1,'B starts its image answer while A confirms in background');
  const replyB = chats[chatCount];
  assert.ok(JSON.stringify(replyB.payload).includes('B_IMAGE_QUESTION'));
  assert.ok(JSON.stringify(replyB.payload).includes('B_IMAGE_REQUIREMENT'));
  assert.ok(!JSON.stringify(replyB.payload).includes('A_IMAGE_'));
  await completeChat(replyB,'乙图片回复');
  await waitForAnswer(page,b,'乙图片回复');
  await page.locator('#text').fill('B_DRAFT_WHILE_A_CONFIRMS');
  await confirm(confirmations[1]);
  await waitForCount(page,chats,chatCount+2,'A continues after switching away during confirmation');
  const replyA = chats[chatCount+1];
  assert.ok(JSON.stringify(replyA.payload).includes('A_IMAGE_QUESTION'));
  assert.ok(JSON.stringify(replyA.payload).includes('A_IMAGE_REQUIREMENT'));
  assert.ok(!JSON.stringify(replyA.payload).includes('B_IMAGE_'));
  assert.equal(await page.locator('#text').inputValue(),'B_DRAFT_WHILE_A_CONFIRMS','A confirmation does not clear B draft');
  await completeChat(replyA,'甲图片回复');
  await waitForAnswer(page,a,'甲图片回复');
  assert.equal(await page.locator('#text').inputValue(),'B_DRAFT_WHILE_A_CONFIRMS','A background completion does not clear B draft');
  assert.equal(await page.evaluate(() => ocrTasks.size),0,'each finished batch removes only its own images');
  await select(page,a);
  assert.ok((await page.locator('#chat').innerText()).includes('甲图片回复'));
  assert.ok(!(await page.locator('#chat').innerText()).includes('乙图片回复'));

  // Stopping one confirming batch must leave the other batch and draft alive.
  const stopA = await upload(fixture,a,'stop-A');
  await recognize(stopA,'A_STOP_IMAGE'); await waitTask(page,stopA.id,'ready');
  await page.locator('#sendBtn').click();
  await waitForCount(page,confirmations,3,'A second confirmation starts');
  const stopB = await upload(fixture,b,'keep-B');
  await recognize(stopB,'B_KEEP_IMAGE'); await waitTask(page,stopB.id,'ready');
  await page.locator('#sendBtn').click();
  await waitForCount(page,confirmations,4,'B second confirmation starts');
  await select(page,a);
  await page.locator('#sendBtn').click();
  await page.waitForFunction(({a,b}) => !ocrBatchRuns.has(sessionBusyKey(a)) && ocrBatchRuns.has(sessionBusyKey(b)),{a,b});
  await confirm(confirmations[2],true);
  await confirm(confirmations[3]);
  await waitForCount(page,chats,chatCount+3,'B confirmation survives stopping A');
  await completeChat(chats[chatCount+2],'乙保留图片回复');
  await waitForAnswer(page,b,'乙保留图片回复');
  assert.equal(await page.evaluate(id => ocrTasks.has(id),stopA.id),true,'stopped A retains its image for retry');
  await deleteConversation(page,a);
  assert.equal(await page.evaluate(id => [...ocrTasks.values()].some(task => task.sessionId === id),a),false,
    'deleting A removes its queued image');
  await select(page,b);
  assert.deepEqual(await visibleTasks(page),[],'a deleted conversation cannot reappear in another composer');
}

async function guestImageLifecycle(fixture) {
  const {page} = fixture;
  const a = await create(page,'刷新 A');
  await page.locator('#text').fill('A_REFRESH_DRAFT');
  const imageA = await upload(fixture,a,'refresh-A');
  await recognize(imageA,'A_REFRESH_IMAGE'); await waitTask(page,imageA.id,'ready');
  const b = await create(page,'刷新 B');
  await page.locator('#text').fill('B_REFRESH_DRAFT');
  const imageB = await upload(fixture,b,'refresh-B');
  await recognize(imageB,'B_REFRESH_IMAGE'); await waitTask(page,imageB.id,'ready');
  await page.evaluate(async () => { checkpointGuestDrafts(); await checkpointGuestOcrTasks(); saveState(); });
  await page.reload({waitUntil:'networkidle'});
  await page.waitForFunction(() => !accountVerificationOperation && ocrTasks.size === 2);
  assert.deepEqual(await visibleTasks(page),[imageB.id]);
  await select(page,a);
  assert.deepEqual(await visibleTasks(page),[imageA.id]);
  assert.equal(await page.locator('#text').inputValue(),'A_REFRESH_DRAFT');
  assert.equal(await page.evaluate(id => ocrTasks.get(id).draft.body_text,imageA.id),'A_REFRESH_IMAGE');
  await deleteConversation(page,a);
  await select(page,b);
  assert.deepEqual(await visibleTasks(page),[imageB.id]);
  assert.equal(await page.locator('#text').inputValue(),'B_REFRESH_DRAFT');
  await page.evaluate(() => { clearLoggedOutWorkspace(); });
  assert.equal(await page.locator('#text').inputValue(),'');
  assert.equal(await page.evaluate(() => sessions.length + ocrTasks.size),0,'account reset clears every conversation input');
  await page.reload({waitUntil:'networkidle'});
  await page.waitForFunction(() => !accountVerificationOperation);
  assert.equal(await page.locator('#text').inputValue(),'');
  assert.equal(await page.evaluate(() => sessions.length + ocrTasks.size),0,'reset drafts cannot restore after refresh');
}

async function imageQueue(fixture) {
  const {page,recognitions} = fixture;
  const four = name => Array.from({length:4},(_,index) => ({name:`${name}-${index}.svg`,mimeType:'image/svg+xml',
    buffer:Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="5" height="5"/>')}));
  const a = await create(page,'四图 A');
  await page.locator('#imageInput').setInputFiles(four('queue-A'));
  await waitForCount(page,recognitions,4,'A fills the shared four-slot recognition limit');
  const b = await create(page,'四图 B');
  assert.equal(await page.locator('#imageInput').isDisabled(),false,'A recognition limit does not prevent B queueing uploads');
  await page.locator('#imageInput').setInputFiles(four('queue-B'));
  await page.waitForFunction(() => ocrTasks.size === 8 && ocrRecognitionRuns.size === 4 && ocrRecognitionQueue.size === 4);
  assert.equal(recognitions.length,4,'B waits until shared recognition slots are available');
  assert.equal(await page.locator('.ocr-task-card').count(),4);
  assert.deepEqual(await page.evaluate(() => [...ocrTasks.values()].filter(task => task.sessionId === currentId).map(task => task.groupId)),['1','2','3','4']);
  await deleteConversation(page,a);
  await waitForCount(page,recognitions,8,'deleting A releases slots to B without user retry');
  await page.waitForFunction(() => ocrRecognitionRuns.size === 4 && ocrRecognitionQueue.size === 0);
  for (const request of recognitions.slice(0,4)) {
    await request.route.fulfill(json({text:'DELETED_A_LATE_RESPONSE',document:{body_text:'DELETED_A_LATE_RESPONSE',graphs:[]}})).catch(() => {});
  }
  for (const request of recognitions.slice(4)) await request.route.fulfill(json({text:'B_QUEUE_IMAGE',document:{body_text:'B_QUEUE_IMAGE',graphs:[]}}));
  await page.waitForFunction(() => ocrRecognitionRuns.size === 0 && [...ocrTasks.values()].every(task => task.state === 'ready'));
  assert.deepEqual(await page.evaluate(() => [...new Set([...ocrTasks.values()].map(task => task.sessionId))]),[b]);
  const c = await create(page,'四图 C');
  await page.locator('#imageInput').setInputFiles(four('queue-C'));
  await waitForCount(page,recognitions,12,'C can store a separate four-image batch');
  for (const request of recognitions.slice(8)) await request.route.fulfill(json({text:'C_QUEUE_IMAGE',document:{body_text:'C_QUEUE_IMAGE',graphs:[]}}));
  await page.waitForFunction(() => ocrTasks.size === 8 && [...ocrTasks.values()].every(task => task.state === 'ready'));
  await page.evaluate(async () => { checkpointGuestDrafts(); await checkpointGuestOcrTasks(); saveState(); });
  await page.reload({waitUntil:'networkidle'});
  await page.waitForFunction(() => !accountVerificationOperation && ocrTasks.size === 8);
  assert.equal(await page.locator('.ocr-task-card').count(),4,'refresh shows only the current four-image batch');
  assert.deepEqual(await page.evaluate(() => [...new Set([...ocrTasks.values()].map(task => task.sessionId))]),[b,c]);
}

(async () => {
  const browser = await chromium.launch({headless:true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? {executablePath:process.env.CHROMIUM_EXECUTABLE_PATH} : {})});
  try {
    for (const width of [1440,390]) for (const [name,run] of [
      ['drafts/input mode/home/guest refresh',draftIsolation],['parallel chat/stop/delete',concurrentChat],
      ['image ownership/parallel recognition and confirmation/stop/delete',imageIsolation],
      ['guest image refresh/deletion/account reset',guestImageLifecycle],
      ['per-conversation four-image capacity/shared queue/eight-image refresh',imageQueue]
    ]) {
      if (process.env.DMATE_TEST_CASE && !name.includes(process.env.DMATE_TEST_CASE)) continue;
      const fixture = await setup(browser,width);
      try {
        await run(fixture);
        assert.deepEqual(fixture.errors,[]);
        assert.deepEqual(fixture.unexpected,[]);
        console.log('PASS ' + width + ': ' + name);
      } finally { await fixture.context.close(); }
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
