/* Real encrypted cross-navigation transport. No application models or services. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const {chromium} = require('playwright');
const root = path.resolve(__dirname,'..');
const sources = {
  '/offline-handoff.js':fs.readFileSync(path.join(root,'static/offline-handoff.js'),'utf8'),
  '/offline-entry.js':fs.readFileSync(path.join(root,'static/offline-entry.js'),'utf8'),
  '/bridge.js':fs.readFileSync(path.join(root,'static/script.js'),'utf8').split('window.DMateOfflineBridge = Object.freeze({')[1]
};
sources['/bridge.js'] = 'window.DMateOfflineBridge = Object.freeze({' + sources['/bridge.js'];
const setup = `<script>
window.handoffTestOwner ||= 'PRIVATE_交接账号';
window.name ||= 'handoff-test-tab:' + crypto.randomUUID();
window.DMateGuestSession={getOwner:()=>handoffTestOwner};
window.testToasts=[];window.showCopyToast=value=>testToasts.push(value);
</script>`;
const baseHTML = '<!doctype html><meta charset="utf-8"><link rel="icon" href="data:,">'+setup;
const bridgeSetup = `<script>
let cloudSyncContextVersion=1;
let accountState={username:handoffTestOwner};
let appearanceSettings={mode:'dark',fontSize:'large',mask:27};
let learningState={wrongQuestions:[{id:'one',question:'PRIVATE QUESTION',createdAt:123},{id:'removed',question:'PRIVATE DELETED'}],
  deletedWrongQuestionIds:{removed:456},conceptNotebook:{notes:[{id:'note',title:'PRIVATE TITLE',content:'PRIVATE BODY',updatedAt:123},{id:'gone',title:'PRIVATE GONE',content:'gone',updatedAt:1}],deleted:{gone:2}}};
function shouldPersistClientState(){return Boolean(handoffTestOwner);}
function drawingStorageOwner(){return handoffTestOwner?'account:'+handoffTestOwner:'guest';}
let standaloneDrawingOwner=drawingStorageOwner(),standaloneDrawing=null;
let standaloneDrawingSessionState={gallery:JSON.stringify({version:2,activeId:'blank-two',privateLayout:'PRIVATE METADATA',pages:[
  {id:'blank-one',name:'PRIVATE BLANK FIRST',document:{body_text:'',graphs:[{id:'G1',name:'FIRST',vertices:[],edges:[]}]}},
  {id:'blank-two',name:'PRIVATE BLANK SECOND',document:{body_text:'',graphs:[{id:'G2',name:'SECOND',vertices:[],edges:[]}]}}]})};
let ocrEditorTaskId=null,ocrEditorController=null;
const DRAWING_STORAGE_KEY='dmate:graph-drawing:v1';
function collectLearningReviewDrawings(){throw new Error('The learning-review filter must not export the gallery');}
async function readAppearanceBackgroundBlob(){if(window.backgroundGate)await backgroundGate;return new Blob(['PRIVATE IMAGE PIXELS'],{type:'image/png'});}
</script><script src="/bridge.js"></script>`;
const server = http.createServer((request,response) => {
  if(sources[request.url]){response.writeHead(200,{'Content-Type':'text/javascript; charset=utf-8','Cache-Control':'no-store'});response.end(sources[request.url]);return;}
  if(request.url==='/'||request.url==='/offline'){
    response.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'});
    response.end(baseHTML+'<script src="/offline-handoff.js"></script>');return;
  }
  if(request.url==='/entry'){
    response.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'});
    response.end(baseHTML+'<button id="offlineWorkspaceBtn">离线版</button>'+bridgeSetup+'<script src="/offline-handoff.js"></script><script src="/offline-entry.js"></script>');return;
  }
  response.writeHead(404);response.end();
});
async function expectCode(page,code,source,args){
  assert.equal(await page.evaluate(async({source,args})=>{
    try{await (0,eval)('('+source+')')(args);return 'RESOLVED';}catch(error){return error.code;}
  },{source:source.toString(),args}),code);
}
async function raw(page){
  return page.evaluate(()=>new Promise((resolve,reject)=>{
    const request=indexedDB.open('dmate-offline-handoff-v1');request.onerror=()=>reject(request.error);
    request.onsuccess=()=>{const db=request.result,tx=db.transaction(['stages','chunks'],'readonly'),stages=tx.objectStore('stages').getAll(),chunks=tx.objectStore('chunks').getAll();
      tx.oncomplete=()=>{db.close();resolve({stages:stages.result.map(row=>({token:row.token,extractable:row.key.extractable,algorithm:row.key.algorithm,length:row.meta.ciphertext.byteLength,fields:Object.keys(row)})),
        chunks:chunks.result.map(row=>({token:row.token,index:row.index,fields:Object.keys(row),length:row.ciphertext.byteLength})),
        storage:Object.fromEntries(Object.entries(sessionStorage)),local:Object.fromEntries(Object.entries(localStorage))});};};
  }));
}
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const baseURL='http://127.0.0.1:'+server.address().port;
  const browser=await chromium.launch({headless:true,executablePath:process.env.DMATE_BROWSER_EXECUTABLE||process.env.CHROMIUM_EXECUTABLE_PATH||'/usr/bin/chromium'});
  const context=await browser.newContext({serviceWorkers:'block'}),page=await context.newPage(),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  try{
    await page.goto(baseURL,{waitUntil:'load'});
    const token=await page.evaluate(async()=>{
      window.privatePayload={username:handoffTestOwner,notes:[{id:'note-one',title:'PRIVATE TITLE',content:'PRIVATE CONCEPT CONTENT',updatedAt:1722222222222}],
        wrongQuestions:[{id:'wrong-one',question:'PRIVATE QUESTION'}],drawings:'PRIVATE DRAWING JSON',
        appearance:{settings:{mode:'dark'},backgroundBlob:new File(['PRIVATE IMAGE PIXELS'],'PRIVATE FILE.png',{type:'image/png',lastModified:1722222222333})},
        binary:new Uint8Array([1,4,9]),special:{'__proto__':'safe',constructor:'safe'}};
      return DMateOfflineHandoff.stage(privatePayload);
    });
    assert.match(token,/^[a-f0-9]{64}$/);
    let value=await raw(page);
    assert.equal(value.stages.length,1);assert.equal(value.chunks.length,1);
    assert.equal(value.stages[0].extractable,false);assert.equal(value.stages[0].algorithm.length,256);
    assert.deepEqual(value.stages[0].fields.sort(),['key','meta','token']);
    assert.deepEqual(value.chunks[0].fields.sort(),['ciphertext','index','iv','token']);
    assert.deepEqual(value.storage,{dmate_offline_handoff_token_v1:token});assert.deepEqual(value.local,{});
    assert.ok(!JSON.stringify(value).includes('PRIVATE'),'No business metadata leaks to stored keys or Web Storage');
    await page.reload({waitUntil:'load'});
    const restored=await page.evaluate(async()=>{
      const first=await DMateOfflineHandoff.read(DMateOfflineHandoff.pendingToken());
      const second=await DMateOfflineHandoff.read(DMateOfflineHandoff.pendingToken());
      return{username:first.username,notes:first.notes,drawings:first.drawings,pixels:await first.appearance.backgroundBlob.text(),
        file:first.appearance.backgroundBlob.name,type:first.appearance.backgroundBlob.type,modified:first.appearance.backgroundBlob.lastModified,
        bytes:[...first.binary],second:second.notes[0].content};
    });
    assert.equal(restored.username,'PRIVATE_交接账号');assert.equal(restored.notes[0].title,'PRIVATE TITLE');
    assert.equal(restored.pixels,'PRIVATE IMAGE PIXELS');assert.equal(restored.file,'PRIVATE FILE.png');
    assert.equal(restored.type,'image/png');assert.equal(restored.modified,1722222222333);
    assert.deepEqual(restored.bytes,[1,4,9]);assert.equal(restored.second,'PRIVATE CONCEPT CONTENT');
    assert.equal((await raw(page)).stages.length,1,'Reading does not delete a handoff before target-vault verification');
    const foreign=await context.newPage();await foreign.goto(baseURL);
    await expectCode(foreign,'HANDOFF_OWNER_CHANGED',async token=>DMateOfflineHandoff.read(token),token);
    await foreign.evaluate(()=>{window.name='wrong-account-tab';handoffTestOwner='OTHER ACCOUNT';});
    await expectCode(foreign,'HANDOFF_OWNER_CHANGED',async token=>DMateOfflineHandoff.read(token),token);
    await foreign.close();
    await page.evaluate(token=>DMateOfflineHandoff.ack(token),token);
    value=await raw(page);assert.equal(value.stages.length,0);assert.equal(value.chunks.length,0);assert.deepEqual(value.storage,{});
    console.log('PASS encrypted JSON/File transport: opaque token only, private metadata, reload, owner/tab binding and explicit acknowledgement');

    const failure=await page.evaluate(async()=>{
      const first=await DMateOfflineHandoff.stage({username:handoffTestOwner,notes:['SAFE PRIOR CONTENT']});
      const add=IDBObjectStore.prototype.add;
      IDBObjectStore.prototype.add=function(...args){if(this.name==='chunks')throw new DOMException('Fixture quota','QuotaExceededError');return add.apply(this,args);};
      let code;try{await DMateOfflineHandoff.stage({username:handoffTestOwner,notes:['PRIVATE NEW CONTENT']});}catch(error){code=error.code;}
      finally{IDBObjectStore.prototype.add=add;}
      return{code,pending:DMateOfflineHandoff.pendingToken(),first,prior:await DMateOfflineHandoff.read(first)};
    });
    assert.equal(failure.code,'HANDOFF_SAVE_FAILED');assert.equal(failure.pending,failure.first);
    assert.deepEqual(failure.prior.notes,['SAFE PRIOR CONTENT']);assert.equal((await raw(page)).stages.length,1);
    await page.evaluate(async()=>{await DMateOfflineHandoff.ack(DMateOfflineHandoff.pendingToken());});
    console.log('PASS atomic staging failure preserves the prior encrypted handoff and current source');

    const race=await page.evaluate(async()=>{
      const encrypt=crypto.subtle.encrypt.bind(crypto.subtle);let release,entered;
      const gate=new Promise(resolve=>release=resolve),started=new Promise(resolve=>entered=resolve);
      crypto.subtle.encrypt=async(...args)=>{entered();await gate;return encrypt(...args);};
      let version=1;const operation=DMateOfflineHandoff.stage({username:handoffTestOwner,notes:['PRIVATE LATE CONTENT']},{isCurrent:()=>version===1})
        .then(()=>null,error=>error.code);
      await started;version=2;release();const code=await operation;crypto.subtle.encrypt=encrypt;
      return{code,pending:DMateOfflineHandoff.pendingToken()};
    });
    assert.deepEqual(race,{code:'HANDOFF_OWNER_CHANGED',pending:null});assert.equal((await raw(page)).stages.length,0);
    console.log('PASS an owner-context change while encrypting never publishes a late snapshot');

    const large=await page.evaluate(async()=>{
      const bytes=new Uint8Array(13*1024*1024);for(let i=0;i<bytes.length;i++)bytes[i]=i%251;
      const digest=await crypto.subtle.digest('SHA-256',bytes),token=await DMateOfflineHandoff.stage({username:handoffTestOwner,file:new Blob([bytes],{type:'application/octet-stream'})});
      const saved=await DMateOfflineHandoff.read(token),actual=await crypto.subtle.digest('SHA-256',await saved.file.arrayBuffer());
      return{token,size:saved.file.size,equal:[...new Uint8Array(digest)].join() === [...new Uint8Array(actual)].join()};
    });
    assert.equal(large.size,13*1024*1024);assert.equal(large.equal,true);assert.ok((await raw(page)).chunks.length>=4);
    await page.evaluate(token=>DMateOfflineHandoff.ack(token),large.token);
    const tampered=await page.evaluate(async()=>{
      const token=await DMateOfflineHandoff.stage({username:handoffTestOwner,notes:['PRIVATE TAMPER CONTENT']});
      await new Promise((resolve,reject)=>{const request=indexedDB.open('dmate-offline-handoff-v1');request.onsuccess=()=>{const db=request.result,tx=db.transaction('chunks','readwrite'),store=tx.objectStore('chunks'),row=store.get([token,0]);
        row.onsuccess=()=>{const value=row.result;window.savedCipher=value.ciphertext.slice(0);const bytes=new Uint8Array(value.ciphertext);bytes[0]^=1;store.put({...value,ciphertext:bytes.buffer});};tx.oncomplete=()=>{db.close();resolve();};tx.onerror=()=>reject(tx.error);};});
      return token;
    });
    await expectCode(page,'HANDOFF_INVALID',async token=>DMateOfflineHandoff.read(token),tampered);
    assert.equal((await raw(page)).stages.length,1,'Authentication failures preserve the encrypted source');
    await page.evaluate(token=>DMateOfflineHandoff.ack(token),tampered);
    console.log('PASS multi-chunk Blob bytes round-trip exactly; ciphertext corruption is rejected without a reset');

    await page.goto(baseURL+'/entry',{waitUntil:'load'});
    const gallery=await page.evaluate(async()=>JSON.parse((await DMateOfflineBridge.snapshot()).drawings));
    assert.deepEqual(gallery.pages.map(page=>page.name),['PRIVATE BLANK FIRST','PRIVATE BLANK SECOND']);
    assert.equal(gallery.activeId,'blank-two');assert.equal(gallery.privateLayout,'PRIVATE METADATA');
    const dirtyGallery=await page.evaluate(async()=>{
      const next={version:2,activeId:'new-blank',privateLayout:'PRIVATE NEW METADATA',pages:[
        {id:'new-blank',name:'PRIVATE NEW BLANK',document:{body_text:'',graphs:[{id:'G3',name:'NEW BLANK',vertices:[],edges:[]}]}}]};
      ocrEditorTaskId='standalone-drawing';ocrEditorController={getPages:()=>next.pages,
        flush:async()=>{standaloneDrawingSessionState.gallery=JSON.stringify(next);standaloneDrawingSessionState.galleryDirty=true;return false;}};
      return JSON.parse((await DMateOfflineBridge.snapshot()).drawings);
    });
    assert.equal(dirtyGallery.activeId,'new-blank');assert.equal(dirtyGallery.pages[0].name,'PRIVATE NEW BLANK');
    assert.equal(dirtyGallery.privateLayout,'PRIVATE NEW METADATA');
    console.log('PASS the production bridge preserves blank named pages, order, active page, metadata and newer drafts after an online write failure');
    await page.locator('#offlineWorkspaceBtn').click();await page.waitForURL(baseURL+'/offline');
    assert.equal(await page.evaluate(()=>sessionStorage.getItem('dmate_offline_migration_v1')),null);
    const transferred=await page.evaluate(async()=>{const value=await DMateOfflineHandoff.read(DMateOfflineHandoff.pendingToken());return{username:value.username,
      notes:value.notes,wrong:value.wrongQuestions,settings:value.appearance.settings,bytes:await value.appearance.backgroundBlob.text(),gallery:JSON.parse(value.drawings)};});
    assert.equal(transferred.notes.length,1);assert.equal(transferred.wrong.length,1);assert.equal(transferred.settings.mode,'dark');
    assert.equal(transferred.bytes,'PRIVATE IMAGE PIXELS');assert.deepEqual((await raw(page)).local,{});
    assert.equal(transferred.gallery.activeId,'new-blank');assert.equal(transferred.gallery.pages[0].name,'PRIVATE NEW BLANK');
    await page.evaluate(()=>DMateOfflineHandoff.ack(DMateOfflineHandoff.pendingToken()));
    await page.goto(baseURL+'/entry',{waitUntil:'load'});
    await page.evaluate(()=>{DMateOfflineHandoff={stage:async()=>{throw new Error('Fixture secure-store failure');}};});
    await page.locator('#offlineWorkspaceBtn').click();await page.waitForFunction(()=>testToasts.length===1);
    assert.equal(new URL(page.url()).pathname,'/entry');assert.equal(await page.locator('#offlineWorkspaceBtn').isDisabled(),false);
    assert.equal(await page.locator('#offlineWorkspaceBtn').getAttribute('aria-busy'),null);
    assert.ok((await page.evaluate(()=>testToasts[0])).includes('当前页面内容仍保留'));
    assert.deepEqual(errors,[]);
    console.log('PASS the production bridge/entry navigate only after encrypted staging; failures restore the button and retain source data');
  }finally{await context.close();await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
