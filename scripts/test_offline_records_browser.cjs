/* Warm the real offline shell, disconnect both page and worker, then edit local records. */
'use strict';
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const {installStorageProbe,records, revealInterface} = require('./offline-vault-browser-fixtures.cjs');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const mistakeRemovalText = '确定要把这道题移出错题本吗？';
const noteDeletionText = '删除后，笔记内容将不可恢复';
const savedQuestion = require('../static/offline-content/questions.zh-CN.json').questions
  .find(question => question.statement && (question.answer_text || question.answer?.length));
const styleKeys = ['fontFamily','fontSize','fontWeight','lineHeight','color','backgroundColor',
  'borderTopWidth','borderTopStyle','borderTopColor','borderRadius','boxShadow','paddingTop','paddingRight'];
const style = locator => locator.evaluate((node, keys) => Object.fromEntries(keys.map(key => [key,getComputedStyle(node)[key]])),styleKeys);
const circle = locator => locator.evaluate(node => Object.fromEntries(['width','height','borderRadius','backgroundColor',
  'borderTopWidth','borderTopStyle','borderTopColor','appearance'].map(key => [key,getComputedStyle(node)[key]])));
const ready = async page => {
  await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
  await revealInterface(page);
};
const settle = page => page.evaluate(async()=>{
  await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
  await Promise.all(document.getAnimations().filter(animation=>animation.effect?.getComputedTiming().iterations!==Infinity)
    .map(animation=>animation.finished.catch(()=>{})));
});
async function navigate(page, panel) {
  const detail = page.locator('#libraryDetailDialog');
  if (await detail.evaluate(node => node.open)) await page.locator('#libraryDetailClose').click();
  if (await page.locator('#knowledgeGraphClose').isVisible()) await page.locator('#knowledgeGraphClose').click();
  const toggle=page.locator(page.viewportSize().width<=1100?'#offlineNavToggle':'#offlineDesktopSidebarOpen');
  if(await toggle.getAttribute('aria-expanded')!=='true')await toggle.click();
  await page.locator('.offline-nav-item[data-panel="'+panel+'"]').click();
  await page.locator('#'+panel+'Panel').waitFor({state:'visible'});
}
async function onlineStyles(page,theme) {
  await page.goto(baseURL,{waitUntil:'networkidle'});
  await page.evaluate(theme=>{
    appearanceSettings={...APPEARANCE_DEFAULTS,mode:theme};applyAppearanceSettings({save:true});
    learningState=normalizeLearningState({wrongQuestions:[{id:'style-only',question:'按钮样式参考',createdAt:1,
      updatedAt:1,corrected:false,answer:'已有答案',referenceAnswer:'已有答案',analysis:'已有解析',recognitionSnapshot:{version:1,question:'按钮样式参考',
      difficulty:'简单',points:['集合运算']},focusPoints:['集合运算']}]});
    openWrongBook();
  },theme);
  const removeAction=page.locator('#wrongBookModal').getByRole('button',{name:'移出错题本',exact:true});
  await page.mouse.move(0,0);await settle(page);
  const result={removeAction:await style(removeAction)};
  if(page.viewportSize().width>1100){await removeAction.hover();await settle(page);result.removeActionHover=await style(removeAction);await page.mouse.move(0,0);}
  await removeAction.click();
  await page.locator('#appConfirmBody').waitFor({state:'visible'});
  assert.equal(await page.locator('#appConfirmBody').innerText(),mistakeRemovalText);
  await page.locator('#appConfirmClose').click();
  await page.locator('#wrongBookClose').click();
  await page.evaluate(()=>{
    learningState.conceptNotebook={notes:[{id:'style-note',title:'样式参考',content:'参考笔记',updatedAt:1}],deleted:{}};
    initializeConceptNotebook();window.dmateConceptNotebook.open();
  });
  const notebook=page.locator('#conceptNotebookDialog');
  await notebook.waitFor({state:'visible'});
  result.create=await style(notebook.locator('.dcn-new'));
  assert.equal(await notebook.locator('.dcn-new').innerText(),'＋ 新概念');
  assert.equal(await notebook.locator('.dcn-original').getAttribute('aria-label'),'概念内容');
  assert.equal((await notebook.locator('.dcn-editor label').last().innerText()).trim(),'概念内容');
  result.remove=await circle(notebook.locator('.dcn-note-delete'));
  await notebook.locator('.dcn-note-delete').click();
  assert.equal(await notebook.locator('.dcn-confirm-body').innerText(),noteDeletionText);
  await notebook.locator('.dcn-confirm .dcn-close').click();
  await notebook.locator('.dcn-close').first().click();
  return result;
}
async function disconnectWorker(browser,page) {
  const protocol=await browser.newBrowserCDPSession(),pageProtocol=await page.context().newCDPSession(page);
  const {targetInfo}=await pageProtocol.send('Target.getTargetInfo');await pageProtocol.detach();
  const url=await page.evaluate(()=>navigator.serviceWorker.controller.scriptURL);
  const target=(await protocol.send('Target.getTargets')).targetInfos.find(info=>info.type==='service_worker'
    &&info.url===url&&info.browserContextId===targetInfo.browserContextId);
  assert.ok(target,'The cached shell has an actual service worker target');
  const {sessionId}=await protocol.send('Target.attachToTarget',{targetId:target.targetId,flatten:false});
  let serial=0;
  async function send(method,params={}){
    const id=++serial;let listener;
    const pending=new Promise((resolve,reject)=>{listener=event=>{
      if(event.sessionId!==sessionId)return;const response=JSON.parse(event.message);if(response.id!==id)return;
      response.error?reject(new Error(response.error.message)):resolve(response.result);
    };protocol.on('Target.receivedMessageFromTarget',listener);});
    try{await protocol.send('Target.sendMessageToTarget',{sessionId,message:JSON.stringify({id,method,params})});return await pending;}
    finally{protocol.off('Target.receivedMessageFromTarget',listener);}
  }
  await send('Network.enable');
  await send('Network.emulateNetworkConditions',{offline:true,latency:0,downloadThroughput:0,uploadThroughput:0});
  const probe=await send('Runtime.evaluate',{expression:"fetch('/offline-record-network-probe',{cache:'no-store'}).then(()=>false,()=>true)",awaitPromise:true,returnByValue:true});
  assert.equal(probe.result.value,true,'The worker cannot silently use the server');
  return protocol;
}
async function confirmDeletion(page,expectedBody) {
  const dialog=page.locator('.dmate-delete-confirm[open]');await dialog.waitFor({state:'visible'});
  assert.equal(await dialog.locator('.dmate-delete-confirm-body').innerText(),expectedBody);
  await dialog.locator('.dmate-delete-confirm-delete').click();await dialog.waitFor({state:'detached'});
}
async function noOverflow(page,panel) {
  const dimensions=await page.locator('#'+panel+'Panel').evaluate(node=>({viewport:innerWidth,
    document:document.documentElement.scrollWidth,width:node.clientWidth,scroll:node.scrollWidth}));
  assert.ok(dimensions.document<=dimensions.viewport+1&&dimensions.scroll<=dimensions.width+1,
    panel+' fits its desktop/mobile viewport: '+JSON.stringify(dimensions));
}
async function exercise(page,reference,width) {
  await navigate(page,'mistakes');
  await page.waitForFunction(()=>document.getElementById('mistakeList').textContent.trim().length>0);
  assert.equal((await page.locator('#mistakeList').innerText()).trim(),'无');
  assert.equal(await page.locator('#addMistake,#recordDialog,#recordForm,#recordTitle,#recordContent').count(),0,
    'The removed manual mistake controls are absent, not merely hidden');
  assert.equal((await page.locator('#mistakesPanel .offline-toolbar').innerText()).includes('仅保存在当前设备'),false);
  await navigate(page,'questions');
  if(width<=1100)await page.locator('#questionFullView').click();
  assert.equal(await page.locator('#questionDetail [data-action="add-to-mistakes"]').count(),0,
    'The offline library offers answers without an add-to-mistake action');
  // Wrong-book actions operate on records already saved or brought online,
  // independently of the removed practice-capture control.
  const existingMistake={id:'saved-reference-one',questionId:savedQuestion.id,title:savedQuestion.title,
    statement:savedQuestion.statement,answer:savedQuestion.answer_text || (savedQuestion.answer || []).join('、'),
    explanation:savedQuestion.explanation,knowledgePoints:savedQuestion.knowledge_points || [],
    focusPoints:savedQuestion.knowledge_points || [],createdAt:new Date().toISOString(),updatedAt:new Date().toISOString()};
  await page.evaluate(value=>__offlineTestStore.put('mistakes',value),existingMistake);
  await navigate(page,'mistakes');
  const card=page.locator('#mistakeList .wrong-card');await card.waitFor({state:'visible'});
  assert.equal(await card.locator('.wrong-status,.wrong-analysis-details,[data-action="edit-mistake"]').count(),0,
    'Offline cards omit correction state, explanation and editing controls');
  assert.equal(await card.locator('.wrong-actions > button').count(),1,'The only card action is removal');
  const remove=card.locator('[data-action="delete-mistake"]');
  assert.equal((await remove.innerText()).trim(),'移出错题本');
  assert.equal(await remove.locator('svg').count(),0,'Removal is a text action without its old trash icon');
  await page.mouse.move(0,0);await settle(page);
  assert.deepEqual(await style(remove),reference.removeAction,'Offline removal matches the online action parameters');
  if(width>1100){await remove.hover();await settle(page);assert.deepEqual(await style(remove),reference.removeActionHover,'Offline removal reuses online hover feedback');await page.mouse.move(0,0);}
  await card.locator('.wrong-answer-summary').click();
  await page.waitForFunction(()=>document.querySelector('#mistakeList .wrong-answer-details')?.open);
  assert.ok((await card.locator('.wrong-answer-inner').textContent()).trim());
  await remove.click();await page.locator('.dmate-delete-confirm-close').click();
  assert.equal((await records(page,'mistakes')).length,1,'Cancel removal retains the original record');
  await remove.click();await confirmDeletion(page,mistakeRemovalText);
  await page.waitForFunction(async()=>(await __offlineTestStore.all('mistakes')).length===0);
  await page.waitForFunction(()=>document.getElementById('mistakeList').textContent.trim()==='无');
  assert.equal((await page.locator('#mistakeList').innerText()).trim(),'无');
  await navigate(page,'questions');
  if(width<=1100)await page.locator('#questionFullView').click();
  assert.equal(await page.locator('#questionDetail [data-action="add-to-mistakes"]').count(),0);
  await page.evaluate(value=>__offlineTestStore.put('mistakes',{...value,id:'saved-reference-two'}),existingMistake);
  await navigate(page,'mistakes');
  await noOverflow(page,'mistakes');
  if(width===390&&process.env.OFFLINE_RECORDS_SCREENSHOTS==='1')await page.screenshot({path:'/tmp/dmate-offline-records-390-mistakes.png'});

  await navigate(page,'notes');
  assert.equal(await page.locator('#notesPanel .dcn-ai,#notesPanel .dcn-ai-actions,#notesPanel .dcn-question').count(),0,'The restored notebook has its original local controls and no AI panel');
  assert.equal((await page.locator('#addNote').innerText()).trim(),'＋ 新概念');
  await page.locator('#addNote').click();
  assert.equal(await page.locator('.dcn-original').getAttribute('aria-label'),'概念内容');
  assert.equal((await page.locator('.dcn-editor label').last().innerText()).trim(),'概念内容');
  await page.locator('.dcn-title').fill('集合笔记');await page.locator('.dcn-original').fill('保留我的原始推导：幂集含有所有子集');
  await page.waitForFunction(async()=>(await __offlineTestStore.all('notes')).some(row=>row.content.includes('原始推导')));
  const firstNote=(await records(page,'notes'))[0];
  await page.mouse.move(0,0);await settle(page);assert.deepEqual(await style(page.locator('#addNote')),reference.create,'The original notebook create action has the online filled style');
  assert.deepEqual(await circle(page.locator('.dcn-note-delete')),reference.remove,'The notebook delete dot matches the online red circle');
  assert.equal(await page.locator('#notesPanel .dcn-note-select,#notesPanel input[type="checkbox"]').count(),0,'Offline note rows have no selection circles');
  assert.equal(await page.locator('#notesPanel .dcn-selection').count(),0,'Offline notes have no selected-count hint');
  await page.locator('#addNote').click();
  await page.waitForFunction(previous=>{
    const current=document.querySelector('#noteList .dcn-note.is-current');
    return current && current.dataset.noteId!==previous;
  },firstNote.id);
  await page.locator('.dcn-title').fill('图论笔记');await page.locator('.dcn-original').fill('路径、回路和连通性');
  await page.waitForFunction(async()=>{
    const notes=await __offlineTestStore.all('notes');
    return notes.length===2&&notes.some(row=>row.content==='路径、回路和连通性');
  });
  assert.equal((await records(page,'notes')).find(row=>row.id===firstNote.id)?.content,'保留我的原始推导：幂集含有所有子集',
    'Creating and editing another note retains the original note content');
  const search=page.locator('.dcn-search');await search.fill('不会匹配的内容');
  assert.equal((await page.locator('.dcn-list-empty').innerText()).trim(),'无');
  await search.fill('原始推导');assert.equal(await page.locator('.dcn-note').count(),1,'Original note search includes its content');
  await page.locator('.dcn-search-clear').click();
  await page.locator('.dcn-note[data-note-id="'+firstNote.id+'"] .dcn-note-open').click();
  assert.equal(await page.locator('.dcn-original').inputValue(),'保留我的原始推导：幂集含有所有子集');
  assert.equal(await page.locator('.dcn-original').evaluate(node=>getComputedStyle(node).resize),'none');
  await noOverflow(page,'notes');
  if(width===390&&process.env.OFFLINE_RECORDS_SCREENSHOTS==='1')await page.screenshot({path:'/tmp/dmate-offline-records-390-notes.png'});
  await page.reload({waitUntil:'networkidle'});await ready(page);await navigate(page,'notes');
  assert.equal((await records(page,'notes')).length,2,'Notes survive a fully offline refresh');
  await page.locator('.dcn-note[data-note-id="'+firstNote.id+'"] .dcn-note-open').click();
  assert.equal(await page.locator('.dcn-original').inputValue(),'保留我的原始推导：幂集含有所有子集');
  await page.locator('.dcn-note[data-note-id="'+firstNote.id+'"] .dcn-note-delete').click();await confirmDeletion(page,noteDeletionText);
  await page.waitForFunction(async()=>(await __offlineTestStore.all('notes')).length===1);
  await navigate(page,'mistakes');await page.locator('#mistakeList .wrong-card').waitFor({state:'visible'});
  assert.equal(await page.locator('.wrong-card').count(),1,'The existing saved wrong question survives the same offline refresh');
}
async function run(browser,width,theme) {
  const context=await browser.newContext({viewport:{width,height:900},isMobile:width<=1100,hasTouch:width<=1100,serviceWorkers:'allow'});
  await installStorageProbe(context);
  const page=await context.newPage(),errors=[],apiRequests=[],failures=[];let workerProtocol;
  await context.route('**/auth/me',route=>route.fulfill({contentType:'application/json',body:'{"configured":true,"authenticated":false}'}));
  await context.route(/\/(?:chat|ocr(?:\/[^?]*)?|graph\/[^?]*|notebook\/analyze|analyze-questions|classify|conversation\/title)(?:\?|$)/,
    route=>{apiRequests.push(new URL(route.request().url()).pathname);return route.abort();});
  page.on('pageerror',error=>errors.push(error.message));
  try{
    const reference=await onlineStyles(page,theme);
    await page.evaluate(async()=>{await navigator.serviceWorker.register('/offline-service-worker.js',{scope:'/'});await navigator.serviceWorker.ready;});
    await page.goto(baseURL+'/offline',{waitUntil:'networkidle'});await ready(page);await page.waitForFunction(()=>navigator.serviceWorker.controller);
    // Local appearance is a device preference, independent of the online
    // account. Give this visual comparison fixture its matching local theme.
    await page.evaluate(theme=>__offlineTestStore.put('settings',{id:'appearance',settings:{mode:theme},updatedAt:Date.now()}),theme);
    page.on('requestfailed',request=>failures.push(request.url()));
    await context.setOffline(true);workerProtocol=await disconnectWorker(browser,page);
    await page.reload({waitUntil:'networkidle'});await ready(page);assert.equal(await page.evaluate(()=>navigator.onLine),false);
    await exercise(page,reference,width);
    const savedMistakes=await records(page,'mistakes'),savedNotes=await records(page,'notes');
    const fresh=await context.newPage();await fresh.goto(baseURL+'/offline',{waitUntil:'networkidle'});await ready(fresh);
    assert.deepEqual(await records(fresh,'mistakes'),savedMistakes,'A new tab opens the same device-local wrong questions');
    assert.deepEqual(await records(fresh,'notes'),savedNotes,'A new tab opens the same device-local concepts');await fresh.close();
    assert.deepEqual(errors,[]);assert.deepEqual(apiRequests,[],'Local record actions make no online AI, OCR or study API calls');
    assert.deepEqual(failures,[],'The restored pages and their resources are fully cached');
    console.log('PASS '+width+'/'+theme+': simplified wrong-book actions, shared concept labels and online controls, saved wrong-question records and true offline persistence');
  }finally{await context.close();if(workerProtocol)await workerProtocol.detach().catch(()=>{});}
}
async function recordRaces(browser){
  const context=await browser.newContext({viewport:{width:1440,height:1000},serviceWorkers:'block'});
  await installStorageProbe(context);
  const page=await context.newPage(),errors=[],calls=[];
  page.on('pageerror',error=>errors.push(error.message));
  await context.route(/\/(?:auth|chat|ocr|graph\/|notebook\/analyze|analyze-questions|classify|sync)(?:\/|\?|$)/,
    route=>{calls.push(new URL(route.request().url()).pathname);return route.abort();});
  try{
    await page.goto(baseURL+'/offline',{waitUntil:'networkidle'});await ready(page);
    let navigations=0;
    page.on('framenavigated',frame=>{if(frame===page.mainFrame())navigations++;});
    await page.evaluate(()=>{
      window.__deviceDocumentProbe=crypto.randomUUID();window.__deviceOriginalStore=__offlineTestStore;
      DMateGuestSession.setAccountOwner('race-owner-a');
      window.dispatchEvent(new CustomEvent('dmate:account-state',{detail:{authenticated:true,username:'race-owner-a'}}));
    });
    const documentProbe=await page.evaluate(()=>__deviceDocumentProbe);
    await navigate(page,'notes');
    await page.locator('#addNote').click();await page.locator('.dcn-title').fill('Local device concept');
    await page.locator('.dcn-original').fill('A initial note');
    await page.waitForFunction(async()=>(await __offlineTestStore.all('notes')).some(row=>row.content==='A initial note'));
    await page.evaluate(()=>{window.__holdNextOfflineNoteSave=true;});
    await page.locator('.dcn-original').fill('A first held save');
    await page.waitForFunction(()=>typeof __releaseOfflineNoteSave==='function');
    const queued='LATEST DEVICE NOTE AFTER ACCOUNT CHANGE';
    await page.locator('.dcn-original').fill(queued);
    await page.evaluate(()=>{
      DMateGuestSession.setAccountOwner('race-owner-b');__releaseOfflineNoteSave();
      window.dispatchEvent(new CustomEvent('dmate:account-state',{detail:{authenticated:true,username:'race-owner-b'}}));
    });
    await page.waitForFunction(async content=>(await __offlineTestStore.all('notes')).some(row=>row.content===content),queued);
    assert.equal(await page.evaluate(()=>DMateGuestSession.getOwner()),'race-owner-b');
    assert.equal(await page.evaluate(()=>__deviceOriginalStore===__offlineTestStore),true,'Changing the online account keeps the current device storage handle');
    assert.equal(await page.locator('.dcn-original').inputValue(),queued,'The active editor and queued draft remain intact after A to B');
    await page.evaluate(()=>{
      DMateGuestSession.setAccountOwner('race-owner-a');
      window.dispatchEvent(new CustomEvent('dmate:account-state',{detail:{authenticated:true,username:'race-owner-a'}}));
    });
    await settle(page);
    const saved=await records(page,'notes');
    assert.equal(saved.length,1,'Changing online accounts does not duplicate or partition the device note');
    assert.equal(saved[0].content,queued,'The queued latest save finishes against the same local record across A/B/A');
    assert.equal(await page.evaluate(()=>__deviceDocumentProbe),documentProbe,'Account events do not reload the active local document');
    assert.equal(navigations,0,'Account events cause no local workspace navigation');
    const fresh=await context.newPage();await fresh.goto(baseURL+'/offline',{waitUntil:'networkidle'});await ready(fresh);
    assert.deepEqual(await records(fresh,'notes'),saved,'Another tab opens the same finished device note');
    await fresh.close();
    const afterClose='DEVICE NOTE REMAINS EDITABLE AFTER SECOND TAB CLOSES';
    await page.locator('.dcn-original').fill(afterClose);
    await page.waitForFunction(async content=>(await __offlineTestStore.all('notes')).some(row=>row.content===content),afterClose);
    assert.equal(await page.evaluate(()=>__deviceDocumentProbe),documentProbe);
    assert.deepEqual(errors,[]);assert.deepEqual(calls,[]);
    console.log('PASS delayed encrypted notebook saves and the active editor survive online account A/B/A changes and shared-tab reopening');
  }finally{await context.close();}
}
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.CHROMIUM_EXECUTABLE_PATH}:{})});
  try{
    const themes=(process.env.DMATE_TEST_THEMES||'light,dark,navy').split(',');
    if(process.env.DMATE_TEST_RECORDS_ONLY!=='races')for(const [width,theme]of [[1440,'light'],[390,'dark'],[1440,'navy']])
      if(themes.includes(theme))await run(browser,width,theme);
    await recordRaces(browser);
  }
  finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
