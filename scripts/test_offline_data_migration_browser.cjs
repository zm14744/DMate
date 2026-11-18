/* Personal offline pages restore only their owner's records; no model API runs. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.BASE_URL || process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const executablePath = process.env.CHROMIUM || process.env.CHROMIUM_EXECUTABLE_PATH;
const dbName = 'dmate-offline-workspace', migrationKey = 'dmate_offline_migration_v1';
const journalKey = 'dmate:offline:notebook-journal:v1', ownerA = 'fixture-user', ownerB = 'other-user';
const suffix = owner => '::' + encodeURIComponent('account:' + owner);
const owned = (row, owner = ownerA) => ({...row, id:row.id + suffix(owner)});
const json = value => ({contentType:'application/json',body:JSON.stringify(value)});
const iso = value => new Date(value).toISOString();
const time = value => Number(value) || Date.parse(value) || 0;
const documentFor = label => ({body_text:'Body ' + label, graphs:[{id:'G1',name:label,
  directed:false,weighted:false,vertices:[{id:'v1',label,x:.3,y:.4}],edges:[]}]});
const drawing = (id, name, label, updatedAt) => ({id,name,document:documentFor(label),
  createdAt:1,updatedAt,requirement:'Retained request',custom:{marker:id}});
const ready = page => page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
async function bootstrap(context, owner = ownerA) {
  await context.route('**/__offline-data-test', route => route.fulfill({contentType:'text/html',body:
    '<!doctype html><title>Migration fixture</title><script src="/static/guest-session.js"></script>'}));
  const page = await context.newPage();
  await page.goto(baseURL + '/__offline-data-test');
  await page.evaluate(owner => DMateGuestSession.setAccountOwner(owner), owner);
  return page;
}
async function seed(page, fixture) {
  await page.evaluate(async ({fixture,dbName,migrationKey,journalKey}) => {
    const db = await new Promise((resolve,reject) => {
      const request = indexedDB.open(dbName, 2);
      request.onupgradeneeded = () => {
        for (const store of fixture.legacy ? ['mistakes','notes','practice','settings'] : ['practice','settings'])
          request.result.createObjectStore(store,{keyPath:'id'});
      };
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
    const records = fixture.records || {};
    if (Object.keys(records).length) await new Promise((resolve,reject) => {
      const tx = db.transaction(Object.keys(records),'readwrite');
      for (const [name,rows] of Object.entries(records)) for (const row of rows) tx.objectStore(name).put(row);
      tx.oncomplete = resolve; tx.onerror = tx.onabort = () => reject(tx.error);
    });
    db.close();
    if (fixture.journal) localStorage.setItem(journalKey,fixture.journal);
    if (fixture.gallery) localStorage.setItem('dmate:offline:drawing-gallery:v1::' + encodeURIComponent('account:' + fixture.owner),JSON.stringify(fixture.gallery));
    sessionStorage.setItem(migrationKey,JSON.stringify(fixture.incoming));
  },{fixture,dbName,migrationKey,journalKey});
}
async function readState(page) {
  return page.evaluate(({dbName,journalKey}) => new Promise((resolve,reject) => {
    const request = indexedDB.open(dbName);
    request.onerror = () => reject(request.error);
    request.onsuccess = async () => {
      const db = request.result, records = {};
      try {
        for (const name of db.objectStoreNames) records[name] = await new Promise((done,fail) => {
          const tx = db.transaction(name,'readonly'), result = tx.objectStore(name).getAll();
          tx.oncomplete = () => done(result.result); tx.onerror = tx.onabort = () => fail(tx.error);
        });
        resolve({version:db.version,stores:[...db.objectStoreNames],records,journal:localStorage.getItem(journalKey)});
      } catch(error) { reject(error); } finally { db.close(); }
    };
  }),{dbName,journalKey});
}
async function migration(browser, legacy) {
  const context = await browser.newContext({viewport:{width:1440,height:950},serviceWorkers:'block'});
  const page = await bootstrap(context), errors = [], forbidden = [];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route(/\/(?:chat|ocr(?:\/[^?]*)?|notebook\/analyze|auth\/[^?]*|sync)(?:\?|$)/,route=>{
    forbidden.push(new URL(route.request().url()).pathname); return route.abort();
  });
  const globalNote = {id:'unknown-note',title:'PRIVATE UNOWNED NOTE',content:'Do not assign to the current account',custom:{retained:true}};
  const globalMistake = {id:'unknown-mistake',title:'PRIVATE UNOWNED MISTAKE',statement:'Unassigned old question',custom:{retained:true}};
  const currentNote = {id:'local-note',title:'Local title',content:'Newest local note',updatedAt:iso(9000),custom:'retain local extra'};
  const oldNote = {id:'updated-note',title:'Previous title',content:'Previous text',updatedAt:iso(1000),custom:'retain on incoming edit'};
  const currentMistake = {id:'local-mistake',title:'Local mistake',statement:'Newest local question',answer:'Local answer',status:'resolved',createdAt:iso(1000),updatedAt:iso(9000),custom:'keep'};
  const oldMistake = {id:'updated-mistake',title:'Old mistake',statement:'Old question',status:'pending',createdAt:iso(1000),updatedAt:iso(1000),custom:'retain on incoming edit'};
  const otherNote = owned({id:'local-note',title:'PRIVATE OTHER ACCOUNT NOTE',content:'Other owner text',updatedAt:iso(5000)},ownerB);
  const otherMistake = owned({id:'local-mistake',title:'PRIVATE OTHER ACCOUNT MISTAKE',statement:'Other owner question',updatedAt:iso(5000)},ownerB);
  const records = legacy ? {
    notes:[globalNote,owned(currentNote),owned(oldNote),otherNote],
    mistakes:[globalMistake,owned(currentMistake),owned(oldMistake),otherMistake],
    practice:[{id:'legacy-practice',custom:{retain:true}}],
    settings:[owned({id:'notebook-deletions',deleted:{'deleted-note':5000},updatedAt:iso(5000)}),
      owned({id:'mistake-deletions',deleted:{'deleted-mistake':5000},updatedAt:iso(5000)})]
  } : {};
  const incoming = {username:ownerA,
    notes:[{id:'local-note',title:'Older incoming title',content:'Older incoming text',updatedAt:8000},
      {id:'updated-note',title:'Updated from online',content:'New online content',updatedAt:2000},
      {id:'deleted-note',title:'Deleted old note',content:'Must not return',updatedAt:4000}],
    wrongQuestions:[{id:'local-mistake',question:'Older incoming question',referenceAnswer:'Older answer',corrected:false,createdAt:5000,updatedAt:8000},
      {id:'updated-mistake',category:'集合运算',question:'Updated online question',referenceAnswer:{text:'Updated answer'},analysis:'Saved explanation',knowledgePoints:['集合运算'],corrected:true,createdAt:5000,updatedAt:2000},
      {id:'deleted-mistake',question:'Must not return',updatedAt:4000}],
    drawings:JSON.stringify({version:2,activeId:'incoming-only',pages:[drawing('shared','Incoming duplicate','incoming duplicate',99999),drawing('incoming-only','New drawing','incoming',3000)]})};
  const localGallery = {version:2,activeId:'shared',custom:{retained:true},pages:[drawing('shared','Existing drawing','local',1000)]};
  const journal = '{unassigned legacy journal stays unchanged';
  try {
    await seed(page,{legacy,owner:ownerA,records,journal,gallery:legacy?localGallery:null,incoming});
    await page.goto(baseURL+'/offline'); await ready(page);
    assert.equal(await page.locator('.offline-nav-item.active').getAttribute('data-panel'),'graph');
    assert.equal(await page.locator('#mistakesPanel,#notesPanel').count(),2);
    let state = await readState(page);
    assert.equal(state.version,3); assert.deepEqual(state.stores,['mistakes','notes','practice','settings']);
    assert.equal(state.journal,journal,'Unknown-owner legacy journal is preserved without replay');
    const note = id => state.records.notes.find(row=>row.id===id+suffix(ownerA));
    const mistake = id => state.records.mistakes.find(row=>row.id===id+suffix(ownerA));
    assert.equal(note('local-note').content,legacy?'Newest local note':'Older incoming text');
    assert.equal(note('updated-note').content,'New online content');
    assert.equal(mistake('local-mistake').statement,legacy?'Newest local question':'Older incoming question');
    assert.equal(mistake('updated-mistake').statement,'Updated online question');
    assert.equal(mistake('updated-mistake').answer,'Updated answer');
    assert.equal(mistake('updated-mistake').explanation,'Saved explanation');
    assert.equal(mistake('updated-mistake').status,'resolved');
    assert.equal(time(mistake('updated-mistake').createdAt),legacy?1000:5000,'Import keeps the original capture date');
    if (legacy) {
      assert.equal(note('deleted-note'),undefined);assert.equal(mistake('deleted-mistake'),undefined);
      assert.equal(note('updated-note').custom,oldNote.custom);assert.equal(mistake('updated-mistake').custom,oldMistake.custom);
      assert.deepEqual(state.records.notes.find(row=>row.id===globalNote.id),globalNote);
      assert.deepEqual(state.records.mistakes.find(row=>row.id===globalMistake.id),globalMistake);
      assert.deepEqual(state.records.notes.find(row=>row.id===otherNote.id),otherNote);
      assert.deepEqual(state.records.mistakes.find(row=>row.id===otherMistake.id),otherMistake);
      assert.deepEqual(state.records.practice,records.practice);
    }
    await page.locator('.offline-nav-item[data-panel="notes"]').click();
    await page.locator('#notesPanel .dcn-note-open').first().waitFor({state:'visible'});
    assert.ok(!(await page.locator('#notesPanel').textContent()).includes('PRIVATE'));
    assert.equal(await page.locator('#notesPanel [data-note-id="unknown-note"]').count(),0);
    await page.locator('.offline-nav-item[data-panel="mistakes"]').click();
    await page.locator('#mistakeList [data-record-id]').first().waitFor({state:'visible'});
    assert.ok(!(await page.locator('#mistakesPanel').textContent()).includes('PRIVATE'));
    assert.equal(await page.locator('#mistakeList [data-record-id="unknown-mistake"]').count(),0);
    assert.ok(!(await page.locator('#mistakeList').textContent()).includes('Other owner question'));
    assert.equal(await page.locator('#mistakeList .wrong-status,#mistakeList .wrong-analysis-details,#mistakeList [data-action="edit-mistake"],#addMistake,#recordDialog').count(),0,
      'Stored correction and explanation data do not recreate removed offline controls');
    assert.equal(await page.locator('#mistakeList [data-action="delete-mistake"] svg').count(),0);
    assert.ok((await page.locator('#mistakeList .wrong-date').count())>0,'Original capture dates remain visible');
    const gallery = await page.evaluate(key=>JSON.parse(localStorage.getItem(key)), 'dmate:offline:drawing-gallery:v1'+suffix(ownerA));
    assert.deepEqual(gallery.pages.map(row=>row.id),['shared','incoming-only']);
    if (legacy) { assert.equal(gallery.pages[0].name,'Existing drawing');assert.equal(gallery.activeId,'shared');assert.deepEqual(gallery.custom,localGallery.custom); }
    await page.evaluate(({incoming,migrationKey})=>sessionStorage.setItem(migrationKey,JSON.stringify(incoming)),{incoming,migrationKey});
    await page.reload();await ready(page);state=await readState(page);
    assert.equal(state.records.notes.filter(row=>row.id==='local-note'+suffix(ownerA)).length,1,'Re-entry does not duplicate notes');
    assert.equal(state.records.mistakes.filter(row=>row.id==='local-mistake'+suffix(ownerA)).length,1,'Re-entry does not duplicate mistakes');
    if (legacy) {
      await page.evaluate(owner=>DMateGuestSession.setAccountOwner(owner),ownerB);await page.reload();await ready(page);
      await page.locator('.offline-nav-item[data-panel="notes"]').click();
      await page.locator('#notesPanel .dcn-note-open').filter({hasText:'PRIVATE OTHER ACCOUNT NOTE'}).waitFor({state:'visible'});
      assert.ok((await page.locator('#notesPanel').textContent()).includes('PRIVATE OTHER ACCOUNT NOTE'));
      assert.ok(!(await page.locator('#notesPanel').textContent()).includes('Newest local note'));
    }
    assert.deepEqual(errors,[]);assert.deepEqual(forbidden,[]);
    console.log('PASS '+(legacy?'legacy v2 upgrade':'fresh v2 upgrade')+': scoped records, local edits, tombstones, immutable dates and original drawing migration');
  } finally { await context.close(); }
}
async function guestMigration(browser) {
  const context=await browser.newContext({serviceWorkers:'block'}),page=await bootstrap(context,'');
  try {
    await page.evaluate(key=>sessionStorage.setItem(key,JSON.stringify({username:'',drawings:'',
      notes:[{id:'guest-note',title:'Guest note',content:'Temporary text',updatedAt:1000}],
      wrongQuestions:[{id:'guest-wrong',question:'Temporary question',updatedAt:1000}]})),migrationKey);
    await page.goto(baseURL+'/offline');await ready(page);
    assert.equal(await page.evaluate(()=>Object.values(DMateGuestSession.read('offline-notes')||{}).length),1);
    assert.equal(await page.evaluate(()=>Object.values(DMateGuestSession.read('offline-mistakes')||{}).length),1);
    const state=await readState(page);assert.deepEqual(state.records.notes,[]);assert.deepEqual(state.records.mistakes,[]);
    await page.reload();await ready(page);
    assert.equal(await page.evaluate(()=>Object.values(DMateGuestSession.read('offline-notes')||{}).length),1);
    const fresh=await context.newPage();await fresh.goto(baseURL+'/offline');await ready(fresh);
    assert.deepEqual(await fresh.evaluate(()=>DMateGuestSession.read('offline-notes')||{}),{});
    assert.deepEqual(await fresh.evaluate(()=>DMateGuestSession.read('offline-mistakes')||{}),{});
    assert.equal(await page.evaluate(()=>Object.values(localStorage).some(value=>value.includes('Temporary text')||value.includes('Temporary question'))),false);
    console.log('PASS guest records: current-tab import and refresh, empty new tab, no permanent personal records');
  } finally { await context.close(); }
}
async function bridge(browser) {
  const context=await browser.newContext({serviceWorkers:'block'}),page=await context.newPage();
  await page.route('**/auth/me',route=>route.fulfill(json({configured:true,authenticated:false})));
  try {
    await page.goto(baseURL+'/',{waitUntil:'networkidle'});
    const result=await page.evaluate(async document=>{
      learningState.wrongQuestions=[{id:'active-wrong',question:'Retained current question'},{id:'deleted-wrong',question:'Deleted question'}];
      learningState.deletedWrongQuestionIds={'deleted-wrong':2000};
      learningState.conceptNotebook={notes:[{id:'active-note',title:'Current note',content:'My own text',updatedAt:1000},
        {id:'deleted-note',title:'Removed note',content:'Do not import',updatedAt:1000}],deleted:{'deleted-note':2000}};
      standaloneDrawingOwner='guest';standaloneDrawingSessionState={};standaloneDrawing=document;
      const snapshot=await DMateOfflineBridge.snapshot();
      const read=readAppearanceBackgroundBlob;let release;
      readAppearanceBackgroundBlob=()=>new Promise(resolve=>{release=resolve;});
      const pending=DMateOfflineBridge.snapshot();bumpCloudSyncContext();release(null);
      let rejected=false;try{await pending;}catch(_){rejected=true;}finally{readAppearanceBackgroundBlob=read;}
      return {snapshot,rejected};
    },documentFor('Legacy original'));
    assert.deepEqual(Object.keys(result.snapshot).sort(),['drawings','notes','username','wrongQuestions']);
    assert.equal(result.snapshot.username,'');assert.deepEqual(result.snapshot.notes.map(row=>row.id),['active-note']);
    assert.deepEqual(result.snapshot.wrongQuestions.map(row=>row.id),['active-wrong']);
    assert.equal(result.snapshot.drawings[0].id,'legacy-local');assert.equal(result.rejected,true,'A late snapshot cannot cross an account context change');
    console.log('PASS real online bridge: only current in-memory personal records, deleted filtering and stale-owner rejection');
  } finally { await context.close(); }
}
async function entry(browser,kind) {
  const context=await browser.newContext({serviceWorkers:'block'}), username='entry-user';
  const gallery={version:2,pages:[drawing('entry-page','Entry','entry',1)]};
  const notes=[{id:'entry-note',title:'Own note',content:'Own text',updatedAt:1000}],wrongQuestions=[{id:'entry-wrong',question:'Own question',updatedAt:1000}];
  await context.route('**/__offline-entry-test',route=>route.fulfill({contentType:'text/html',body:
    '<!doctype html><html data-account-authenticated="'+(kind==='guest'?'0':'1')+'" data-account-username="'+username+'"><body><button id="offlineWorkspaceBtn">离线版</button><script src="/static/offline-entry.js"></script>'}));
  await context.route('**/offline',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><title>Captured handoff</title>'}));
  await context.addInitScript(({kind,username,gallery,notes,wrongQuestions})=>{
    if(location.pathname!=='/__offline-entry-test')return;
    localStorage.setItem('dmate:graph-gallery:v1::'+encodeURIComponent('account:'+username),JSON.stringify(gallery));
    const get=Storage.prototype.getItem;Storage.prototype.getItem=function(key){
      if(key==='discrete_math_ai_learning_v1')throw new Error('Fallback must not read unverified old learning caches');
      return get.call(this,key);
    };
    if(kind==='bridge')window.DMateOfflineBridge={snapshot:async()=>({username,drawings:gallery.pages,notes,wrongQuestions})};
  },{kind,username,gallery,notes,wrongQuestions});
  const page=await context.newPage();
  try {
    await page.goto(baseURL+'/__offline-entry-test');await page.locator('#offlineWorkspaceBtn').click();await page.waitForURL(baseURL+'/offline');
    const payload=await page.evaluate(key=>JSON.parse(sessionStorage.getItem(key)),migrationKey);
    assert.deepEqual(Object.keys(payload).sort(),['drawings','notes','username','wrongQuestions']);
    assert.equal(payload.username,kind==='guest'?'':username);
    assert.deepEqual(payload.notes,kind==='bridge'?notes:[]);assert.deepEqual(payload.wrongQuestions,kind==='bridge'?wrongQuestions:[]);
    if(kind==='guest')assert.equal(payload.drawings,'');else assert.deepEqual(JSON.parse(payload.drawings).pages,gallery.pages);
    console.log('PASS entry '+kind+': current snapshot handoff, safe fallback and guest stale-account exclusion');
  } finally { await context.close(); }
}
async function blockedUpgrade(browser) {
  const context=await browser.newContext({serviceWorkers:'block'}),page=await context.newPage();
  await page.route('**/auth/me',route=>route.fulfill(json({configured:true,authenticated:true,user:{username:ownerA}})));
  await page.route(/\/sync(?:\?|$)/,route=>route.fulfill(json({revision:1,data:{sessions:{sessions:[],currentId:null,deletedSessionIds:{}},learning:{}}})));
  try {
    await page.goto(baseURL+'/',{waitUntil:'networkidle'});
    await page.waitForFunction(owner=>accountState.username===owner&&!cloudInitialSyncInFlight,ownerA);
    const result=await page.evaluate(async dbName=>{
      stopCloudLivePolling();
      const legacy=await new Promise((resolve,reject)=>{
        const request=indexedDB.open(dbName,2);
        request.onupgradeneeded=()=>{for(const name of ['practice','settings'])request.result.createObjectStore(name,{keyPath:'id'});};
        request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
      });
      let snapshot;
      try {
        snapshot=await Promise.race([DMateOfflineBridge.snapshot(),new Promise((_,reject)=>setTimeout(()=>reject(new Error('Blocked upgrade hung the offline entry')),2000))]);
      } finally {legacy.close();}
      const saved=await new Promise((resolve,reject)=>{
        const request=indexedDB.open(dbName);
        request.onerror=()=>reject(request.error);
        request.onsuccess=()=>{
          const db=request.result,tx=db.transaction('settings','readonly'),rows=tx.objectStore('settings').getAll();
          tx.oncomplete=()=>{db.close();resolve(rows.result);};tx.onerror=()=>reject(tx.error);
        };
      });
      return{username:snapshot.username,settings:saved};
    },dbName);
    assert.equal(result.username,ownerA);assert.deepEqual(result.settings,[],'A rejected upgrade cannot later write stale appearance data');
    console.log('PASS blocked v2 upgrade: offline handoff settles promptly and a late database connection is closed');
  } finally {await context.close();}
}
(async()=>{
  const browser=await chromium.launch({headless:true,...(executablePath?{executablePath}:{})});
  try {for(const legacy of [false,true])await migration(browser,legacy);await guestMigration(browser);await bridge(browser);
    for(const kind of ['bridge','gallery','guest'])await entry(browser,kind);await blockedUpgrade(browser);
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
