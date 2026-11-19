/* Standalone local regressions for encrypted workspace records and migration. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const {chromium} = require('playwright');
const root = path.resolve(__dirname,'..');
const server = http.createServer((request, response) => {
  if (request.url === '/') {response.setHeader('Content-Type','text/html');response.end('<script src="/static/guest-session.js"></script><script src="/static/offline-vault.js"></script><script src="/static/offline-storage.js"></script><script>window.fixturePage=(id,name,updatedAt=0)=>({id,name,updatedAt,document:{body_text:"",graphs:[{id:"G1",name,directed:false,weighted:false,vertices:[],edges:[]}]}})</script>');return;}
  if (/^\/static\/(?:guest-session|offline-vault|offline-storage)\.js$/.test(request.url)) {
    response.setHeader('Content-Type','application/javascript');response.end(fs.readFileSync(path.join(root,request.url)));return;
  }
  response.writeHead(404);response.end();
});
let browser;
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const base='http://127.0.0.1:'+server.address().port;
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH||process.env.DMATE_BROWSER_EXECUTABLE
    ?{executablePath:process.env.CHROMIUM_EXECUTABLE_PATH||process.env.DMATE_BROWSER_EXECUTABLE}:{})});
  const context=await browser.newContext(),page=await context.newPage();const errors=[];
  page.on('pageerror',cause=>errors.push(cause.message));await page.goto(base,{waitUntil:'networkidle'});
  const migrated=await page.evaluate(async()=>{
    DMateGuestSession.setAccountOwner('甲账号');
    const suffix='::'+encodeURIComponent('account:甲账号'),other='::'+encodeURIComponent('account:乙账号');
    const db=await new Promise((resolve,reject)=>{const opening=indexedDB.open('dmate-offline-workspace',3);
      opening.onupgradeneeded=()=>{for(const store of ['notes','mistakes','practice','settings'])opening.result.createObjectStore(store,{keyPath:'id'});};
      opening.onsuccess=()=>resolve(opening.result);opening.onerror=()=>reject(opening.error);});
    await new Promise((resolve,reject)=>{const tx=db.transaction(['notes','settings'],'readwrite');
      tx.objectStore('notes').put({id:'中文记录'+suffix,title:'PRIVATE TITLE',content:'PRIVATE OWN CONTENT',updatedAt:10});
      tx.objectStore('notes').put({id:'other'+other,title:'OTHER OWNER',content:'MUST RETAIN'});
      tx.objectStore('notes').put({id:'unknown',content:'UNKNOWN OWNER MUST RETAIN'});
      tx.objectStore('settings').put({id:'appearance'+suffix,settings:{mode:'dark'},backgroundBlob:new Blob(['PRIVATE PIXELS'],{type:'image/png'}),updatedAt:10});
      tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});db.close();
    localStorage.setItem('dmate:offline:drawing-gallery:v1'+suffix,JSON.stringify({version:2,activeId:'page-one',pages:[fixturePage('page-one','PRIVATE GALLERY',4)]}));
    localStorage.setItem('dmate:offline:appearance:v1'+suffix,JSON.stringify({mode:'light'}));
    localStorage.setItem('dmate:offline:notebook-journal:v1','UNKNOWN JOURNAL');
    window.first=await DMateOfflineStorage.open({owner:'甲账号',isCurrent:()=>DMateGuestSession.getOwner()==='甲账号'});
    const value=await first.get('notes','中文记录'),appearance=await first.get('settings','appearance');
    const gallery=await first.get('drawings','gallery');
    const legacy=await new Promise(resolve=>{const request=indexedDB.open('dmate-offline-workspace');request.onsuccess=()=>{
      const db=request.result,tx=db.transaction('notes'),get=tx.objectStore('notes').getAll();tx.oncomplete=()=>{resolve({version:db.version,rows:get.result});db.close();};};});
    const encrypted=await new Promise(resolve=>{const request=indexedDB.open('dmate-offline-vault-v1');request.onsuccess=()=>{
      const db=request.result,tx=db.transaction(['vaults','records']),meta=tx.objectStore('vaults').getAll(),rows=tx.objectStore('records').getAll();
      tx.oncomplete=()=>{resolve(JSON.stringify({meta:meta.result,rows:rows.result}));db.close();};};});
    return{value,settings:appearance.settings,pixels:await appearance.backgroundBlob.text(),gallery:JSON.parse(gallery.gallery),legacy,
      exposed:/PRIVATE|甲账号|乙账号|中文记录/.test(encrypted),galleryBackup:localStorage.getItem('dmate:offline:drawing-gallery:v1'+suffix),
      appearanceBackup:localStorage.getItem('dmate:offline:appearance:v1'+suffix),journal:localStorage.getItem('dmate:offline:notebook-journal:v1')};
  });
  assert.equal(migrated.value.content,'PRIVATE OWN CONTENT');assert.equal(migrated.value.id,'中文记录');
  assert.equal(migrated.pixels,'PRIVATE PIXELS');assert.equal(migrated.settings.mode,'dark');
  assert.equal(migrated.gallery.pages[0].name,'PRIVATE GALLERY');assert.equal(migrated.exposed,false);
  assert.equal(migrated.legacy.version,4);assert.equal(migrated.legacy.rows.length,2);
  assert.equal(migrated.galleryBackup,null);assert.equal(migrated.appearanceBackup,null);assert.equal(migrated.journal,'UNKNOWN JOURNAL');
  console.log('PASS own legacy rows, gallery and binary appearance migrate to ciphertext without assigning unknown records');
  const conflicts=await page.evaluate(async()=>{
    window.second=await DMateOfflineStorage.open({owner:'甲账号',isCurrent:()=>DMateGuestSession.getOwner()==='甲账号'});
    const old=await second.get('notes','中文记录');await first.put('notes',{...old,content:'LATEST EDIT',updatedAt:20});
    let conflict;try{await second.batch([{type:'delete',store:'notes',id:old.id},{type:'put',store:'settings',value:{id:'notebook-deletions',deleted:{[old.id]:30}}}]);}catch(error){conflict=error.code;}
    const retained=(await first.get('notes',old.id)).content,missing=await first.get('settings','notebook-deletions');
    await second.get('notes',old.id);await second.batch([{type:'delete',store:'notes',id:old.id},{type:'put',store:'settings',value:{id:'notebook-deletions',deleted:{[old.id]:30}}}]);
    const deleted=await second.get('notes',old.id),tombstone=await second.get('settings','notebook-deletions');
    await first.put('notes',{id:'enumerated',content:'before delete'});await second.all('notes');await first.remove('notes','enumerated');
    await second.all('notes');await second.put('notes',{id:'enumerated',content:'recreated after refreshed list'});
    const recreated=(await second.get('notes','enumerated')).content;
    first.close();second.close();DMateGuestSession.setAccountOwner('乙账号');
    const other=await DMateOfflineStorage.open({owner:'乙账号',isCurrent:()=>DMateGuestSession.getOwner()==='乙账号'});const otherRows=await other.all('notes');other.close();
    return{conflict,retained,atomic:missing===undefined,deleted:deleted===undefined,tombstone,otherRows,recreated};
  });
  assert.equal(conflicts.conflict,'CONFLICT');assert.equal(conflicts.retained,'LATEST EDIT');assert.equal(conflicts.atomic,true);
  assert.equal(conflicts.deleted,true);assert.equal(conflicts.tombstone.deleted['中文记录'],30);assert.equal(conflicts.otherRows[0].content,'MUST RETAIN');
  assert.equal(conflicts.recreated,'recreated after refreshed list');
  console.log('PASS CAS conflicts preserve newer edits and make deletion plus tombstone atomic across independent handles');
  const reopenedGallery=await page.evaluate(async()=>{
    DMateGuestSession.setAccountOwner('甲账号');
    const initial=await DMateOfflineStorage.open({owner:'甲账号',isCurrent:()=>true});
    await initial.put('drawings',{id:'gallery',updatedAt:100,gallery:JSON.stringify({version:2,activeId:'local',metadata:'ENCRYPTED META',pages:[
      fixturePage('page-one','encrypted old page',10),fixturePage('local','local only page',30)]})});initial.close();
    const key='dmate:offline:drawing-gallery:v1::'+encodeURIComponent('account:甲账号');
    localStorage.setItem(key,JSON.stringify({version:1,activeId:'external',metadata:'RAW META',pages:[
      fixturePage('page-one','newer old-tab edit',20),fixturePage('external','old-tab new page',15)]}));
    const reopened=await DMateOfflineStorage.open({owner:'甲账号',isCurrent:()=>true});const merged=JSON.parse((await reopened.get('drawings','gallery')).gallery);reopened.close();
    const cleaned=localStorage.getItem(key)===null;
    localStorage.setItem(key,JSON.stringify({version:2,activeId:'page-one',pages:[fixturePage('page-one','ambiguous same-time edit',20)]}));
    let code;try{await DMateOfflineStorage.open({owner:'甲账号',isCurrent:()=>true});}catch(error){code=error.code;}
    const retained=localStorage.getItem(key)?.includes('ambiguous same-time edit');
    localStorage.setItem(key,JSON.stringify(Object.fromEntries(Object.entries(merged).reverse())));
    const identical=await DMateOfflineStorage.open({owner:'甲账号',isCurrent:()=>true});identical.close();
    return{merged,cleaned,code,retained,identicalCleaned:localStorage.getItem(key)===null};
  });
  assert.equal(reopenedGallery.merged.activeId,'local');assert.equal(reopenedGallery.merged.metadata,'ENCRYPTED META');
  assert.deepEqual(reopenedGallery.merged.pages.map(page=>page.id),['page-one','local','external']);
  assert.equal(reopenedGallery.merged.pages[0].name,'newer old-tab edit');assert.equal(reopenedGallery.cleaned,true);
  assert.equal(reopenedGallery.code,'CONFLICT');assert.equal(reopenedGallery.retained,true);assert.equal(reopenedGallery.identicalCleaned,true);
  console.log('PASS returning old-tab galleries merge newer pages and preserve ambiguous source edits');
  const invalidGalleries=await page.evaluate(async()=>{
    const valid=()=>({version:2,activeId:'page',pages:[fixturePage('page','PRIVATE VALID PAGE',1)]});
    const values=[];
    let value=valid();delete value.version;values.push(['missing-version',value,'STORAGE_FAILED']);
    value=valid();value.pages={};values.push(['invalid-pages',value,'STORAGE_FAILED']);
    value=valid();value.pages.push({...value.pages[0]});values.push(['duplicate-id',value,'STORAGE_FAILED']);
    value=valid();value.pages[0].id='';values.push(['empty-id',value,'STORAGE_FAILED']);
    value=valid();value.pages[0].document.graphs=[];values.push(['empty-graphs',value,'STORAGE_FAILED']);
    value=valid();delete value.pages[0].document.graphs[0].edges;values.push(['missing-edges',value,'STORAGE_FAILED']);
    value=valid();value.pages=Array.from({length:26},(_,i)=>{const page=fixturePage('page-'+i,'PRIVATE SPLIT PAGE',1);
      page.document.graphs.push({...page.document.graphs[0],id:'G2'});return page;});values.push(['split-limit',value,'TOO_LARGE']);
    const results=[];
    for(const [name,value,expected] of values){
      const owner='invalid-gallery-'+name;DMateGuestSession.setAccountOwner(owner);
      const key='dmate:offline:drawing-gallery:v1::'+encodeURIComponent('account:'+owner),source=JSON.stringify(value);
      localStorage.setItem(key,source);let code;
      try{await DMateOfflineStorage.open({owner,isCurrent:()=>true});}catch(error){code=error.code;}
      const retained=localStorage.getItem(key)===source;localStorage.removeItem(key);
      const reopened=await DMateOfflineStorage.open({owner,isCurrent:()=>true}),saved=await reopened.get('drawings','gallery');reopened.close();
      results.push({name,code,expected,retained,absent:saved===undefined});
    }
    const owner='merged-split-limit';DMateGuestSession.setAccountOwner(owner);
    const store=await DMateOfflineStorage.open({owner,isCurrent:()=>true});
    const original=JSON.stringify({version:2,activeId:'page-0',pages:Array.from({length:50},(_,i)=>fixturePage('page-'+i,'PRIVATE EXISTING PAGE',1))});
    await store.put('drawings',{id:'gallery',gallery:original,updatedAt:1});
    const key='dmate:offline:drawing-gallery:v1::'+encodeURIComponent('account:'+owner),incoming=fixturePage('page-0','PRIVATE NEW SUBGRAPH',2);
    incoming.document.graphs.push({...incoming.document.graphs[0],id:'G2'});
    const source=JSON.stringify({version:1,activeId:'page-0',pages:[incoming]});localStorage.setItem(key,source);let code;
    try{await DMateOfflineStorage.open({owner,isCurrent:()=>true});}catch(error){code=error.code;}
    const retained=localStorage.getItem(key)===source,unchanged=(await store.get('drawings','gallery')).gallery===original;store.close();
    results.push({name:'merged-split-limit',code,expected:'TOO_LARGE',retained,unchanged});return results;
  });
  for(const result of invalidGalleries){
    assert.equal(result.code,result.expected,result.name);assert.equal(result.retained,true,result.name);
    if('absent' in result)assert.equal(result.absent,true,result.name);
    if('unchanged' in result)assert.equal(result.unchanged,true,result.name);
  }
  console.log('PASS invalid galleries and expanded legacy page limits retain raw sources without committing destructive replacements');
  const failure=await page.evaluate(async()=>{
    DMateGuestSession.setAccountOwner('故障账号');
    const id='retry::'+encodeURIComponent('account:故障账号');
    const raw=async action=>new Promise((resolve,reject)=>{const request=indexedDB.open('dmate-offline-workspace',4);
      request.onsuccess=()=>{const db=request.result,tx=db.transaction('notes','readwrite'),result=action(tx.objectStore('notes'));
        tx.oncomplete=()=>{resolve(result.result);db.close();};tx.onerror=()=>{reject(tx.error);db.close();};};request.onerror=()=>reject(request.error);});
    await raw(store=>store.put({id,content:'PRIVATE RETRY SOURCE',updatedAt:42}));
    const put=IDBObjectStore.prototype.put;let code;
    IDBObjectStore.prototype.put=function(value,...args){if(this.name==='records'&&value.collection==='notes')throw new DOMException('Injected quota failure','QuotaExceededError');return put.call(this,value,...args);};
    try{await DMateOfflineStorage.open({owner:'故障账号',isCurrent:()=>true});}catch(error){code=error.code;}finally{IDBObjectStore.prototype.put=put;}
    const source=await raw(store=>store.get(id));
    const retry=await DMateOfflineStorage.open({owner:'故障账号',isCurrent:()=>true}),saved=await retry.get('notes','retry');retry.close();
    return{code,source,saved,remaining:await raw(store=>store.get(id))};
  });
  assert.equal(failure.code,'QUOTA_EXCEEDED');assert.equal(failure.source.content,'PRIVATE RETRY SOURCE');
  assert.equal(failure.saved.content,'PRIVATE RETRY SOURCE');assert.equal(failure.remaining,undefined);
  console.log('PASS failed encrypted migration retains the original until a verified retry commits');
  const shared=await page.evaluate(async()=>{
    DMateGuestSession.reset();DMateGuestSession.write('offline-notes',{private:{id:'private',content:'OFFLINE LEGACY'}});
    const online={gallery:JSON.stringify({version:2,activeId:'online-copy',pages:[fixturePage('online-copy','ONLINE SOURCE')]})};DMateGuestSession.write('drawings',online);
    const store=await DMateOfflineStorage.open({owner:'',isCurrent:()=>true,preserveSharedGuestSource:true});
    const result={private:(await store.get('notes','private')).content,offlineSection:DMateGuestSession.read('offline-notes'),
      onlineSection:DMateGuestSession.read('drawings'),gallery:await store.get('drawings','gallery')};await store.destroyGuest();return result;
  });
  assert.equal(shared.private,'OFFLINE LEGACY');assert.equal(shared.offlineSection,null);
  assert.equal(shared.onlineSection.gallery.includes('ONLINE SOURCE'),true);assert.equal(shared.gallery,undefined);
  console.log('PASS a fresh online handoff preserves its shared online source while migrating private offline sections');
  await page.evaluate(async()=>{
    DMateGuestSession.reset();DMateGuestSession.write('offline-notes',{n:{id:'n',title:'PRIVATE GUEST TITLE',content:'PRIVATE GUEST BODY'}});
    DMateGuestSession.write('drawings',{gallery:JSON.stringify({version:2,activeId:'p',pages:[fixturePage('p','PRIVATE GUEST GALLERY')]})});
    window.guest=await DMateOfflineStorage.open({owner:'',isCurrent:()=>DMateGuestSession.getOwner()===''});
    const text=await guest.get('notes','n');if(text.content!=='PRIVATE GUEST BODY')throw Error('Guest migration failed');
    if(DMateGuestSession.read('offline-notes')||DMateGuestSession.read('drawings'))throw Error('Private guest plaintext remains');
    if(JSON.stringify(sessionStorage).includes('PRIVATE GUEST'))throw Error('Guest cleartext remains in Web Storage');guest.close();
  });
  await page.reload({waitUntil:'networkidle'});
  assert.equal(await page.evaluate(async()=>{window.guest=await DMateOfflineStorage.open({owner:'',isCurrent:()=>DMateGuestSession.getOwner()===''});return(await guest.get('notes','n')).content;}),'PRIVATE GUEST BODY');
  const blank=await context.newPage();await blank.goto(base,{waitUntil:'networkidle'});
  assert.equal(await blank.evaluate(async()=>{const store=await DMateOfflineStorage.open({owner:'',isCurrent:()=>true});const rows=await store.all('notes');store.close();return rows.length;}),0);
  const liveName=await page.evaluate(()=>{guest.close();const name=DMateGuestSession.read('offline-vault-ref').name;localStorage.setItem('dmate:offline-guest-last-seen:'+name,String(Date.now()-7200000));return name;});
  const expiredName=await blank.evaluate(async()=>{
    const name='guest-'+Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');
    const vault=await DMateOfflineVault.open({name});await vault.write('notes','expired','PRIVATE EXPIRED GUEST',{expectedRevision:null});vault.close();
    localStorage.setItem('dmate:offline-guest-last-seen:'+name,String(Date.now()-7200000));localStorage.setItem('dmate:offline-guest-scope:'+name,'dmate-guest-tab:expired||');
    DMateGuestSession.setAccountOwner('cleanup-trigger');const store=await DMateOfflineStorage.open({owner:'cleanup-trigger',isCurrent:()=>true});store.close();return name;
  });
  const hasVault=async name=>blank.evaluate(name=>new Promise(resolve=>{const request=indexedDB.open('dmate-offline-vault-v1');request.onsuccess=()=>{const db=request.result,tx=db.transaction('vaults'),get=tx.objectStore('vaults').get(name);tx.oncomplete=()=>{resolve(!!get.result);db.close();};};}),name);
  await assert.doesNotReject(async()=>{for(let attempt=0;attempt<100;attempt++){if(!await hasVault(expiredName))return;await new Promise(resolve=>setTimeout(resolve,20));}throw Error('Expired guest lease did not collect');});
  assert.equal(await hasVault(liveName),true);
  console.log('PASS expired guest collection preserves a live tab even after its offline handle closes');
  assert.equal(await page.evaluate(async()=>{const name=DMateGuestSession.read('offline-vault-ref').name;await Promise.all([guest.destroyGuest(),guest.destroyGuest()]);return await new Promise(resolve=>{const request=indexedDB.open('dmate-offline-vault-v1');request.onsuccess=()=>{const db=request.result,tx=db.transaction('vaults'),get=tx.objectStore('vaults').get(name);tx.oncomplete=()=>{resolve(get.result===undefined);db.close();};};});}),true);
  assert.deepEqual(errors,[]);console.log('PASS guest refresh, new-tab isolation and explicit encrypted guest destruction');
  await context.close();
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{await browser?.close();await new Promise(resolve=>server.close(resolve));});
