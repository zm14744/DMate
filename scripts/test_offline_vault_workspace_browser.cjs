/* Exercise the real offline UI against its encrypted storage. Model endpoints
 * are forbidden; all local persistence, encryption and browser APIs are real. */
'use strict';
const assert = require('node:assert/strict');
const {mkdtemp, rm} = require('node:fs/promises');
const {tmpdir} = require('node:os');
const {join} = require('node:path');
const {chromium} = require('playwright');
const {installStorageProbe, records, row, revealInterface} = require('./offline-vault-browser-fixtures.cjs');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const executablePath = process.env.CHROMIUM_EXECUTABLE_PATH;
const launch = {headless:true,...(executablePath ? {executablePath} : {})};
const owner = 'vault-ui-account';
const secret = {title:'VAULT-UI-PRIVATE-NOTE-71',content:'VAULT-UI-PRIVATE-CONTENT-73',
  drawing:'VAULT-UI-PRIVATE-DRAWING-79',filename:'VAULT-UI-PRIVATE-BACKGROUND-83.png',wrong:'VAULT-UI-PRIVATE-MISTAKE-89'};
const ready = async page => {
  await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
  await revealInterface(page);
};

async function prepare(context) {
  await installStorageProbe(context);
  const network = [];
  await context.route(/\/(?:auth|chat|ocr|graph\/|notebook\/analyze|analyze-questions|classify|sync|conversation\/title)(?:\/|\?|$)/,
    route => {network.push(route.request().url());return route.abort();});
  context.on('request', request => {
    const value = request.url() + '\n' + (request.postData() || '');
    if (Object.values(secret).some(marker => value.includes(marker))) network.push(value);
  });
  await context.route('**/__offline-vault-ui-fixture', route => route.fulfill({contentType:'text/html',body:
    '<!doctype html><title>Verified owner fixture</title><script src="/static/guest-session.js"></script>'}));
  return network;
}
async function enter(context, username='') {
  const page = await context.newPage();
  await page.goto(baseURL+'/__offline-vault-ui-fixture');
  await page.evaluate(username => DMateGuestSession.setAccountOwner(username),username);
  await page.goto(baseURL+'/offline',{waitUntil:'networkidle'});
  return page;
}
async function navigate(page,panel) {
  const detail = page.locator('#libraryDetailDialog');
  if (await detail.evaluate(node => node.open)) await page.locator('#libraryDetailClose').click();
  if (await page.locator('#knowledgeGraphClose').isVisible()) await page.locator('#knowledgeGraphClose').click();
  const opener = page.locator(page.viewportSize().width <= 1100 ? '#offlineNavToggle' : '#offlineDesktopSidebarOpen');
  if (await opener.getAttribute('aria-expanded') !== 'true') await opener.click();
  await page.locator('.offline-nav-item[data-panel="'+panel+'"]').click();
  await page.locator('#'+panel+'Panel').waitFor({state:'visible'});
}
async function createNote(page,title,content) {
  await navigate(page,'notes');
  const previous=(await records(page,'notes')).map(note=>note.id);
  await page.locator('#addNote').click();
  await page.waitForFunction(previous=>{
    const selected=document.querySelector('.dcn-note.is-current');
    return selected&&!previous.includes(selected.dataset.noteId)
      &&document.querySelector('.dcn-title')?.value===''
      &&document.querySelector('.dcn-original')?.value==='';
  },previous);
  await page.locator('.dcn-title').fill(title);
  await page.locator('.dcn-original').fill(content);
  await page.waitForFunction(async ({title,content}) => (await __offlineTestStore.all('notes'))
    .some(note => note.title===title && note.content===content),{title,content});
}

// Inspect raw database values, including Blob/ArrayBuffer bytes, rather than
// merely checking that encrypted adapter reads return the expected data.
async function inspectPersistence(page, markers, imageBytes=[]) {
  return page.evaluate(async ({markers,imageBytes}) => {
    const findings=[],databases=[],cachesSeen=[];
    const bytesContain=(source,target)=>target.length>0&&source.some((_,start)=>start+target.length<=source.length
      &&target.every((byte,index)=>source[start+index]===byte));
    const markerBytes=markers.map(value=>Array.from(new TextEncoder().encode(value)));
    async function visit(value,path) {
      if(typeof value==='string') {
        for(const marker of markers)if(value.includes(marker))findings.push(path+': '+marker);
      } else if(value instanceof Blob || value instanceof ArrayBuffer || ArrayBuffer.isView(value)) {
        const bytes=Array.from(new Uint8Array(value instanceof Blob?await value.arrayBuffer():
          value instanceof ArrayBuffer?value:value.buffer.slice(value.byteOffset,value.byteOffset+value.byteLength)));
        if(markerBytes.some(marker=>bytesContain(bytes,marker))||bytesContain(bytes,imageBytes))findings.push(path+': private bytes');
      } else if(value && typeof value==='object' && !(value instanceof CryptoKey)) {
        for(const [key,child]of Object.entries(value)){await visit(key,path+'.key');await visit(child,path+'.'+key);}
      }
    }
    for(const [name,storage]of [['localStorage',localStorage],['sessionStorage',sessionStorage]])
      for(let index=0;index<storage.length;index++){const key=storage.key(index);await visit(key,name+'.key');await visit(storage.getItem(key),name+'.'+key);}
    for(const info of await indexedDB.databases()) {
      const db=await new Promise((resolve,reject)=>{const request=indexedDB.open(info.name);request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});
      try {
        for(const name of db.objectStoreNames) {
          const rows=await new Promise((resolve,reject)=>{const tx=db.transaction(name),request=tx.objectStore(name).getAll();tx.oncomplete=()=>resolve(request.result);tx.onerror=()=>reject(tx.error);});
          databases.push({name:info.name,store:name,count:rows.length});await visit(rows,info.name+'.'+name);
        }
      } finally {db.close();}
    }
    for(const name of await caches.keys()) {
      const cache=await caches.open(name);
      for(const request of await cache.keys()) {
        cachesSeen.push(request.url);await visit(request.url,'CacheStorage.url');
        await visit(await(await cache.match(request)).arrayBuffer(),'CacheStorage.body');
      }
    }
    return {findings,databases,cachesSeen};
  },{markers,imageBytes});
}

async function accountUI(browser) {
  const context=await browser.newContext({viewport:{width:1440,height:950},serviceWorkers:'allow'});
  const network=await prepare(context),errors=[];
  try {
    const page=await enter(context,owner);page.on('pageerror',error=>errors.push(error.message));await ready(page);
    // Warm the real static cache, then exercise writes with all networking off.
    await page.evaluate(async()=>{await navigator.serviceWorker.register('/offline-service-worker.js',{scope:'/'});await navigator.serviceWorker.ready;});
    await page.reload({waitUntil:'networkidle'});await ready(page);
    await context.setOffline(true);
    await createNote(page,secret.title,secret.content);
    const note=(await records(page,'notes'))[0];
    await navigate(page,'questions');
    assert.equal(await page.locator('#questionDetail [data-action="add-to-mistakes"]').count(),0,
      'Offline exercises omit the removed add-to-mistake control');
    await page.evaluate(async statement=>{
      const now=new Date().toISOString();
      await __offlineTestStore.put('mistakes',{id:'saved-private-wrong-89',title:'Existing wrong question',
        statement,answer:'A saved reference answer',focusPoints:['集合运算'],createdAt:now,updatedAt:now});
    },secret.wrong);
    await navigate(page,'mistakes');
    assert.equal(await page.locator('#mistakeList .wrong-status,#mistakeList .wrong-analysis-details,#mistakeList [data-action="edit-mistake"],#addMistake').count(),0);
    assert.equal(await page.locator('[data-action="delete-mistake"] svg').count(),0);
    const drawingOpener=page.locator('#offlineDesktopSidebarOpen');
    if(await drawingOpener.getAttribute('aria-expanded')!=='true')await drawingOpener.click();
    await page.evaluate(async()=>{
      for(const panel of ['drawing','notes','drawing'])document.querySelector('.offline-nav-item[data-panel="'+panel+'"]').click();
      await __offlineTestStore.get('drawings','gallery');
      await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    });
    await page.locator('#drawingPanel .dmate-drawing-workspace').waitFor({state:'visible'});
    assert.equal(await page.locator('#offlineDrawingHost .dmate-drawing-workspace').count(),1,
      'Rapid drawing → notes → drawing navigation creates a single editor after async vault reads');
    await page.locator('.ddw-page-actions').getByRole('button',{name:'新建空白页',exact:true}).click();
    await page.locator('.ddw-name').fill(secret.drawing);
    await page.waitForFunction(async marker=>JSON.stringify(await __offlineTestStore.get('drawings','gallery')).includes(marker),secret.drawing);
    const opener=page.locator('#offlineDesktopSidebarOpen');
    if(await opener.getAttribute('aria-expanded')!=='true')await opener.click();
    await page.locator('#offlineAppearanceBtn').click();
    const png=await page.evaluate(()=>{
      const canvas=document.createElement('canvas');canvas.width=17;canvas.height=13;
      const drawing=canvas.getContext('2d');drawing.fillStyle='#7b3d91';drawing.fillRect(0,0,17,13);
      return canvas.toDataURL('image/png').split(',')[1];
    });
    await page.locator('#appearanceBackgroundInput').setInputFiles({name:secret.filename,mimeType:'image/png',buffer:Buffer.from(png,'base64')});
    await page.waitForFunction(()=>document.getElementById('appearanceBackgroundPreview').dataset.hasBackground==='true'&&!document.getElementById('appearanceDone').disabled);
    await page.locator('#appearanceDone').click();await page.locator('#appearanceModal').waitFor({state:'hidden'});
    const imageBytes=await page.evaluate(async()=>Array.from(new Uint8Array(await DMateOfflineAppearance.getBackground().arrayBuffer())));
    // The existing wrong question is private just like the note. Its record
    // identity and saved timestamp must also stay out of the static cache.
    const privateMarkers=[...Object.values(secret),note.id,...(await records(page,'mistakes')).flatMap(value=>[value.id,value.createdAt])];
    let raw=await inspectPersistence(page,privateMarkers,imageBytes);
    assert.deepEqual(raw.findings,[],'Text, image names and background bytes are absent from all raw browser persistence and caches');
    assert.ok(raw.databases.some(value=>value.name==='dmate-offline-vault-v1'&&value.store==='records'&&value.count>0));
    assert.ok(raw.cachesSeen.length>0,'Privacy assertions inspect the actual installed static cache');
    await page.reload({waitUntil:'networkidle'});await ready(page);
    await navigate(page,'notes');await page.locator('.dcn-note[data-note-id="'+note.id+'"] .dcn-note-open').click();
    assert.equal(await page.locator('.dcn-original').inputValue(),secret.content);
    assert.equal((await records(page,'mistakes')).length,1);
    assert.ok(JSON.stringify(await row(page,'drawings','gallery')).includes(secret.drawing));
    assert.equal(await page.evaluate(()=>DMateOfflineAppearance.getBackground()?.size>0),true);
    // Two actual adapters retain optimistic concurrency rather than silently
    // overwriting a note read before another window committed its edit.
    const cas=await page.evaluate(async note=>{
      const first=__offlineTestStore;
      const second=await DMateOfflineStorage.open({scope:'device',isCurrent:()=>true});
      try {
        const stale=await second.get('notes',note.id);
        await first.put('notes',{...note,content:'Committed concurrent UI value'});
        let code='';try{await second.put('notes',{...stale,content:'Stale overwrite'});}catch(error){code=error.code;}
        return {code,content:(await first.get('notes',note.id)).content};
      } finally {second.close();window.__offlineTestStore=first;}
    },note);
    assert.equal(cas.code,'CONFLICT');assert.equal(cas.content,'Committed concurrent UI value');
    await context.setOffline(false);
    const stable = {notes:await records(page,'notes'),mistakes:await records(page,'mistakes'),gallery:await row(page,'drawings','gallery')};
    await page.evaluate(() => {
      window.__deviceOfflineDocument = crypto.randomUUID();
      DMateGuestSession.setAccountOwner('vault-ui-other');
      dispatchEvent(new CustomEvent('dmate:account-state'));
    });
    const documentToken=await page.evaluate(()=>window.__deviceOfflineDocument);
    await page.evaluate(() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    assert.equal(await page.evaluate(()=>window.__deviceOfflineDocument),documentToken,'Signing in does not reload or replace the active offline workspace');
    assert.deepEqual(await records(page,'notes'),stable.notes);
    assert.deepEqual(await records(page,'mistakes'),stable.mistakes);
    assert.deepEqual(await row(page,'drawings','gallery'),stable.gallery);
    await page.evaluate(() => {
      DMateGuestSession.reset();
      dispatchEvent(new CustomEvent('dmate:guest-session-end'));
      dispatchEvent(new StorageEvent('storage',{key:'dmate_account_logout_signal_v1',newValue:String(Date.now())}));
    });
    await page.evaluate(() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    assert.equal(await page.evaluate(()=>window.__deviceOfflineDocument),documentToken,'Logging out preserves the same active offline document');
    assert.equal(await page.locator('html').getAttribute('data-offline-ready'),'true');
    assert.deepEqual(await records(page,'notes'),stable.notes);
    assert.deepEqual(await records(page,'mistakes'),stable.mistakes);
    assert.deepEqual(await row(page,'drawings','gallery'),stable.gallery);
    const other=await enter(context,'vault-ui-other');await ready(other);
    assert.deepEqual(await records(other,'notes'),stable.notes,'A different online account sees the same device concepts');
    assert.deepEqual(await records(other,'mistakes'),stable.mistakes,'A different online account sees the same device mistakes');
    assert.deepEqual(await row(other,'drawings','gallery'),stable.gallery,'A different online account sees the same editable device gallery');
    await other.close();await page.close();
    const reopened=await enter(context,owner);await ready(reopened);
    assert.equal((await records(reopened,'notes'))[0].content,'Committed concurrent UI value');
    raw=await inspectPersistence(reopened,[...Object.values(secret),'Committed concurrent UI value'],imageBytes);
    assert.deepEqual(raw.findings,[]);assert.deepEqual(network,[]);assert.deepEqual(errors,[]);
    console.log('PASS vault UI: real cached/offline notes, mistakes, drawings and wallpaper; ciphertext privacy, reload, concurrency and login-independent device contents');
  } finally {await context.close();}
}

async function migrationFailure(browser,native=false) {
  const context=await browser.newContext({serviceWorkers:'block',...(native?{userAgent:'DMateDesktop/1.0.2'}:{})});
  const network=await prepare(context);
  const original={id:'failure-note::'+encodeURIComponent('account:'+owner),title:'Failure source',content:'KEEP-PRIVATE-MIGRATION-SOURCE-89',updatedAt:1000};
  try {
    const page=await context.newPage();await page.goto(baseURL+'/__offline-vault-ui-fixture');
    await page.evaluate(async({owner,original})=>{
      DMateGuestSession.setAccountOwner(owner);
      const db=await new Promise((resolve,reject)=>{const r=indexedDB.open('dmate-offline-workspace',3);r.onupgradeneeded=()=>{for(const name of ['mistakes','notes','practice','settings'])r.result.createObjectStore(name,{keyPath:'id'});};r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
      await new Promise((resolve,reject)=>{const tx=db.transaction('notes','readwrite');tx.objectStore('notes').put(original);tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});db.close();
    },{owner,original});
    if(!native) {
      await page.evaluate(()=>sessionStorage.setItem('__offlineVaultFault','1'));
      await page.addInitScript(()=>{
        const put=IDBObjectStore.prototype.put;
        IDBObjectStore.prototype.put=function(...args){
          if(sessionStorage.getItem('__offlineVaultFault')==='1'&&this.transaction.db.name==='dmate-offline-vault-v1'&&this.name==='records')
            throw new DOMException('Injected vault write failure','QuotaExceededError');
          return put.apply(this,args);
        };
      });
    }
    await page.goto(baseURL+'/offline',{waitUntil:'networkidle'});
    if(native) {
      await page.waitForFunction(()=>Boolean(window.__offlineTestOpenError));
      assert.notEqual(await page.locator('html').getAttribute('data-offline-ready'),'true','An unavailable native vault never falls back to a working plaintext database');
      assert.equal(await page.evaluate(()=>__offlineTestOpenError.code),'NATIVE_UNAVAILABLE');
    } else {
      await ready(page);
      assert.equal(await page.locator('html').getAttribute('data-offline-ready'),'true','An old-source migration error leaves the existing device workspace usable');
    }
    const legacy=await page.evaluate(()=>new Promise((resolve,reject)=>{const r=indexedDB.open('dmate-offline-workspace');r.onsuccess=()=>{const db=r.result,tx=db.transaction('notes'),get=tx.objectStore('notes').getAll();tx.oncomplete=()=>{db.close();resolve(get.result);};};r.onerror=()=>reject(r.error);}));
    assert.deepEqual(legacy,[original],'Encryption/key failure preserves the exact old source for retry');
    const storage=await page.evaluate(()=>[...Object.values(localStorage),...Object.values(sessionStorage)]);
    assert.equal(storage.some(value=>value.includes('KEEP-PRIVATE-MIGRATION-SOURCE-89')),false,'Failure does not fall back to plaintext WebStorage');
    assert.ok((await page.locator('#offlineToast').textContent()).trim(),'Storage initialization failures have visible feedback');
    if(!native) {
      await page.evaluate(()=>sessionStorage.removeItem('__offlineVaultFault'));
      await page.reload({waitUntil:'networkidle'});await ready(page);
      assert.equal((await records(page,'notes'))[0].content,original.content,'Retry encrypts and restores the retained source');
      assert.deepEqual((await inspectPersistence(page,[original.content,original.title])).findings,[],
        'After verified migration, plaintext source is removed and only ciphertext remains');
    }
    assert.deepEqual(network,[]);
    console.log('PASS '+(native?'old native client':'old-source write failure')+': visible feedback, retained old source and no plaintext fallback');
  } finally {await context.close();}
}

async function processLifetime() {
  const profile=await mkdtemp(join(tmpdir(),'dmate-vault-lifetime-'));
  let context;
  try {
    context=await chromium.launchPersistentContext(profile,{...launch,serviceWorkers:'block'});await prepare(context);
    const account=await enter(context,owner);await ready(account);await createNote(account,'Process account note','RESTART-ACCOUNT-SECRET-97');
    const guest=await enter(context);await ready(guest);
    assert.ok((await records(guest,'notes')).some(note=>note.content==='RESTART-ACCOUNT-SECRET-97'),'Signing out leaves the device concept visible');
    await createNote(guest,'Process unsigned-in note','RESTART-GUEST-SECRET-101');
    await guest.reload();await ready(guest);
    assert.deepEqual((await records(guest,'notes')).map(note=>note.content).sort(),
      ['RESTART-ACCOUNT-SECRET-97','RESTART-GUEST-SECRET-101'].sort(),'Reload retains both device concepts without login');
    await context.close();context=null;
    context=await chromium.launchPersistentContext(profile,{...launch,serviceWorkers:'block'});await prepare(context);
    const reopened=await enter(context);await ready(reopened);
    const expectedContents=['RESTART-ACCOUNT-SECRET-97','RESTART-GUEST-SECRET-101'].sort();
    assert.deepEqual((await records(reopened,'notes')).map(note=>note.content).sort(),expectedContents,'A real browser restart restores device concepts without login');
    const signedIn=await enter(context,'another-online-account');await ready(signedIn);
    assert.deepEqual((await records(signedIn,'notes')).map(note=>note.content).sort(),expectedContents,'Signing into another account after reopening does not partition device data');
    assert.deepEqual((await inspectPersistence(reopened,['RESTART-ACCOUNT-SECRET-97','RESTART-GUEST-SECRET-101'])).findings,[]);
    console.log('PASS real browser restart: encrypted device concepts persist before and after login without a server or account verification');
  } finally {if(context)await context.close();await rm(profile,{recursive:true,force:true});}
}

async function handoffOverflow(browser) {
  const context=await browser.newContext({serviceWorkers:'block'}),network=await prepare(context);
  try {
    const page=await enter(context,owner);await ready(page);
    const staged=await page.evaluate(async()=>{
      const drawing=id=>({id,name:'OVERFLOW-PRIVATE-'+id,document:{body_text:'',graphs:[
        {id:'graph-'+id,directed:false,weighted:false,vertices:[],edges:[]}
      ]},createdAt:1,updatedAt:1});
      const gallery={version:2,activeId:'local-0',pages:Array.from({length:50},(_,index)=>drawing('local-'+index))};
      await __offlineTestStore.put('drawings',{id:'gallery',gallery:JSON.stringify(gallery)});
      const token=await DMateOfflineHandoff.stage({username:DMateGuestSession.getOwner(),notes:[],wrongQuestions:[],
        drawings:JSON.stringify({version:2,activeId:'incoming',pages:[drawing('incoming')]})});
      return {token,gallery};
    });
    await page.reload({waitUntil:'networkidle'});
    await page.waitForFunction(()=>Boolean(document.getElementById('offlineToast').textContent.trim()));
    await ready(page);
    assert.equal(await page.locator('html').getAttribute('data-offline-ready'),'true','A legacy handoff that exceeds the gallery limit does not disable the existing device workspace');
    assert.match(await page.locator('#offlineToast').textContent(),/迁移|保留|retained|migration/i,'An over-limit legacy handoff has visible retained-source feedback');
    assert.equal(await page.evaluate(()=>DMateOfflineHandoff.pendingToken()),staged.token,'Overflow never acknowledges or discards the source handoff');
    const original=(await row(page,'drawings','gallery')).gallery;
    assert.deepEqual(JSON.parse(original),staged.gallery,'All fifty existing drawings remain byte-for-byte logically intact');
    const pending=await page.evaluate(()=>DMateOfflineHandoff.read(DMateOfflineHandoff.pendingToken()));
    assert.equal(JSON.parse(pending.drawings).pages[0].id,'incoming');
    assert.deepEqual((await inspectPersistence(page,['OVERFLOW-PRIVATE-'])).findings,[]);
    assert.deepEqual(network,[]);
    console.log('PASS real handoff overflow: existing fifty pages and encrypted incoming source remain recoverable');
  } finally {await context.close();}
}

(async()=>{
  const browser=await chromium.launch(launch);
  try {await accountUI(browser);await migrationFailure(browser);await migrationFailure(browser,true);await handoffOverflow(browser);}
  finally {await browser.close();}
  await processLifetime();
})().catch(error=>{console.error(error);process.exitCode=1;});
