/* Warm the real offline shell, disconnect both page and worker, then edit local records. */
'use strict';
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const styleKeys = ['fontFamily','fontSize','fontWeight','lineHeight','color','backgroundColor',
  'borderTopWidth','borderTopStyle','borderTopColor','borderRadius','boxShadow','paddingTop','paddingRight'];
const style = locator => locator.evaluate((node, keys) => Object.fromEntries(keys.map(key => [key,getComputedStyle(node)[key]])),styleKeys);
const circle = locator => locator.evaluate(node => Object.fromEntries(['width','height','borderRadius','backgroundColor',
  'borderTopWidth','borderTopStyle','borderTopColor','appearance'].map(key => [key,getComputedStyle(node)[key]])));
const ready = page => page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
const records = (page, name) => page.evaluate(name => Object.values(DMateGuestSession.read('offline-'+name) || {}),name);
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
  result.unchecked=await circle(notebook.locator('.dcn-note-select input'));
  await notebook.locator('.dcn-note-select input').check();await settle(page);
  result.checked=await circle(notebook.locator('.dcn-note-select input'));
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
async function confirmDeletion(page) {
  const dialog=page.locator('.dmate-delete-confirm[open]');await dialog.waitFor({state:'visible'});
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
  assert.equal((await page.locator('#mistakeList').innerText()).trim(),'无');
  assert.equal(await page.locator('#addMistake,#recordDialog,#recordForm,#recordTitle,#recordContent').count(),0,
    'The removed manual mistake controls are absent, not merely hidden');
  assert.equal((await page.locator('#mistakesPanel .offline-toolbar').innerText()).includes('仅保存在当前设备'),false);
  await navigate(page,'questions');
  if(width<=1100)await page.locator('#questionFullView').click();
  const add=page.locator('#questionDetail [data-action="add-to-mistakes"]');await add.waitFor({state:'visible'});await add.click();
  await page.waitForFunction(()=>Object.keys(DMateGuestSession.read('offline-mistakes')||{}).length===1);
  const first=(await records(page,'mistakes'))[0];
  assert.ok(first.questionId&&first.statement&&first.answer&&first.createdAt,'Practice capture retains the question, reference answer and capture time');
  await add.click();
  const repeated=(await records(page,'mistakes'));
  assert.equal(repeated.length,1,'Adding the same practice question updates its original record');
  assert.equal(repeated[0].createdAt,first.createdAt,'Repeated capture never changes the original capture time');
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
  await remove.click();await confirmDeletion(page);
  await page.waitForFunction(()=>Object.keys(DMateGuestSession.read('offline-mistakes')||{}).length===0);
  assert.equal((await page.locator('#mistakeList').innerText()).trim(),'无');
  await navigate(page,'questions');
  if(width<=1100)await page.locator('#questionFullView').click();
  await page.locator('#questionDetail [data-action="add-to-mistakes"]').click();
  await page.waitForFunction(()=>Object.keys(DMateGuestSession.read('offline-mistakes')||{}).length===1);
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
  await page.waitForFunction(()=>Object.values(DMateGuestSession.read('offline-notes')||{}).some(row=>row.content.includes('原始推导')));
  const firstNote=(await records(page,'notes'))[0];
  await page.mouse.move(0,0);await settle(page);assert.deepEqual(await style(page.locator('#addNote')),reference.create,'The original notebook create action has the online filled style');
  assert.deepEqual(await circle(page.locator('.dcn-note-delete')),reference.remove,'The notebook delete dot matches the online red circle');
  const check=page.locator('.dcn-note-select input');assert.deepEqual(await circle(check),reference.unchecked);
  await check.check();await settle(page);assert.deepEqual(await circle(check),reference.checked,'Selected notebook controls match online geometry');
  assert.match(await page.locator('.dcn-selection').innerText(),/1/);
  await page.locator('#addNote').click();await page.locator('.dcn-title').fill('图论笔记');await page.locator('.dcn-original').fill('路径、回路和连通性');
  await page.waitForFunction(()=>Object.keys(DMateGuestSession.read('offline-notes')||{}).length===2);
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
  await page.locator('.dcn-note[data-note-id="'+firstNote.id+'"] .dcn-note-delete').click();await confirmDeletion(page);
  await page.waitForFunction(()=>Object.keys(DMateGuestSession.read('offline-notes')||{}).length===1);
  await navigate(page,'mistakes');assert.equal(await page.locator('.wrong-card').count(),1,'Practice capture survives the same offline refresh');
}
async function run(browser,width,theme) {
  const context=await browser.newContext({viewport:{width,height:900},isMobile:width<=1100,hasTouch:width<=1100,serviceWorkers:'allow'});
  const page=await context.newPage(),errors=[],apiRequests=[],failures=[];let workerProtocol;
  await context.route('**/auth/me',route=>route.fulfill({contentType:'application/json',body:'{"configured":true,"authenticated":false}'}));
  await context.route(/\/(?:chat|ocr(?:\/[^?]*)?|graph\/[^?]*|notebook\/analyze|analyze-questions|classify|conversation\/title)(?:\?|$)/,
    route=>{apiRequests.push(new URL(route.request().url()).pathname);return route.abort();});
  page.on('pageerror',error=>errors.push(error.message));
  try{
    const reference=await onlineStyles(page,theme);
    await page.evaluate(async()=>{await navigator.serviceWorker.register('/offline-service-worker.js',{scope:'/'});await navigator.serviceWorker.ready;});
    await page.goto(baseURL+'/offline',{waitUntil:'networkidle'});await ready(page);await page.waitForFunction(()=>navigator.serviceWorker.controller);
    page.on('requestfailed',request=>failures.push(request.url()));
    await context.setOffline(true);workerProtocol=await disconnectWorker(browser,page);
    await page.reload({waitUntil:'networkidle'});await ready(page);assert.equal(await page.evaluate(()=>navigator.onLine),false);
    await exercise(page,reference,width);
    const fresh=await context.newPage();await fresh.goto(baseURL+'/offline',{waitUntil:'networkidle'});await ready(fresh);
    assert.deepEqual(await records(fresh,'mistakes'),[],'An ordinary new guest tab never inherits private wrong questions');
    assert.deepEqual(await records(fresh,'notes'),[],'An ordinary new guest tab never inherits private notes');await fresh.close();
    assert.deepEqual(errors,[]);assert.deepEqual(apiRequests,[],'Local record actions make no online AI, OCR or study API calls');
    assert.deepEqual(failures,[],'The restored pages and their resources are fully cached');
    console.log('PASS '+width+'/'+theme+': simplified wrong-book actions, shared concept labels and online controls, immutable capture dates and true offline persistence');
  }finally{await context.close();if(workerProtocol)await workerProtocol.detach().catch(()=>{});}
}
async function recordRaces(browser){
  const context=await browser.newContext({viewport:{width:1440,height:1000},serviceWorkers:'block'}),page=await context.newPage();
  const errors=[],calls=[];page.on('pageerror',error=>errors.push(error.message));
  await context.route(/\/(?:auth|chat|ocr|graph\/|notebook\/analyze|analyze-questions|classify|sync)(?:\/|\?|$)/,
    route=>{calls.push(new URL(route.request().url()).pathname);return route.abort();});
  const rows=store=>page.evaluate(store=>new Promise((resolve,reject)=>{
    const opening=indexedDB.open('dmate-offline-workspace');opening.onerror=()=>reject(opening.error);
    opening.onsuccess=()=>{const db=opening.result,request=db.transaction(store).objectStore(store).getAll();
      request.onsuccess=()=>{db.close();resolve(request.result);};request.onerror=()=>reject(request.error);};
  }),store);
  try{
    await page.goto(baseURL+'/offline',{waitUntil:'networkidle'});await ready(page);
    await page.evaluate(()=>DMateGuestSession.setAccountOwner('race-owner-a'));
    await page.reload({waitUntil:'networkidle'});await ready(page);await navigate(page,'notes');
    await page.locator('#addNote').click();await page.locator('.dcn-title').fill('Private A concept');
    await page.locator('.dcn-original').fill('A initial note');
    await page.waitForFunction(()=>new Promise(resolve=>{
      const opening=indexedDB.open('dmate-offline-workspace');opening.onsuccess=()=>{const db=opening.result,
        request=db.transaction('notes').objectStore('notes').getAll();request.onsuccess=()=>{db.close();resolve(request.result.some(row=>row.content==='A initial note'));};};
    }));
    await page.evaluate(()=>{
      const original=IDBDatabase.prototype.transaction;
      IDBDatabase.prototype.transaction=function(stores,mode,...args){const tx=original.call(this,stores,mode,...args);
        if(mode==='readwrite'&&(stores==='notes'||Array.isArray(stores)&&stores.includes('notes'))){
          IDBDatabase.prototype.transaction=original;
          Object.defineProperty(tx,'oncomplete',{configurable:true,set(handler){window.releaseNoteRace=()=>handler();}});
        }return tx;
      };
    });
    await page.locator('.dcn-original').fill('A first held save');
    await page.waitForFunction(()=>typeof releaseNoteRace==='function');
    await page.locator('.dcn-original').fill('A PRIVATE QUEUED SAVE');
    await Promise.all([page.waitForNavigation({waitUntil:'networkidle'}),page.evaluate(()=>{
      DMateGuestSession.setAccountOwner('race-owner-b');releaseNoteRace();
    })]);await ready(page);
    assert.equal(await page.evaluate(()=>DMateGuestSession.getOwner()),'race-owner-b');
    const saved=await rows('notes');
    assert.ok(saved.some(row=>row.id.endsWith('::account%3Arace-owner-a')),'The authorized first save remains with account A');
    assert.ok(!saved.some(row=>row.id.endsWith('::account%3Arace-owner-b')&&/A PRIVATE|A first/.test(row.content)),
      'A queued save never follows a later account owner into B');
    await navigate(page,'notes');assert.equal(await page.locator('.dcn-note').count(),0,'The new account sees no previous private concepts');
    assert.deepEqual(errors,[]);assert.deepEqual(calls,[]);
    console.log('PASS delayed notebook saves retain their original owner after account changes');
  }finally{await context.close();}
}
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.CHROMIUM_EXECUTABLE_PATH}:{})});
  try{
    if(process.env.DMATE_TEST_RECORDS_ONLY!=='races')for(const [width,theme]of [[1440,'light'],[390,'dark'],[1440,'navy']])await run(browser,width,theme);
    await recordRaces(browser);
  }
  finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
