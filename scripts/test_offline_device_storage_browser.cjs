/* Device storage survives online identity changes, tabs and older partitions. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const {chromium} = require('playwright');
const root = path.resolve(__dirname,'..');
const assets = ['guest-session','offline-vault','offline-storage','offline-backup'];
const server = http.createServer((request,response) => {
  if (request.url === '/') {
    response.setHeader('Content-Type','text/html');
    response.end(assets.map(name => '<script src="/static/'+name+'.js"></script>').join(''));
  } else if (assets.some(name => request.url === '/static/'+name+'.js')) {
    response.setHeader('Content-Type','application/javascript');
    response.end(fs.readFileSync(path.join(root,request.url)));
  } else {response.writeHead(404);response.end();}
});
(async () => {
  await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
  const base = 'http://127.0.0.1:'+server.address().port;
  const browser = await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH
    ? {executablePath:process.env.CHROMIUM_EXECUTABLE_PATH} : {})});
  try {
    const context = await browser.newContext(), page = await context.newPage();
    await page.goto(base,{waitUntil:'networkidle'});
    const seeded = await page.evaluate(async () => {
      const fixture = (id,name) => ({id,name,document:{body_text:'',graphs:[{id:'G1',name,directed:false,weighted:false,
        vertices:[{id:'v1',label:'1',x:100,y:100}],edges:[]}]}});
      for (const owner of ['legacy-A','legacy-B','']) {
        DMateGuestSession.setAccountOwner(owner);
        const source = await DMateOfflineStorage.open({owner,isCurrent:()=>true});
        await source.put('notes',{id:owner ? 'same-id' : 'guest-id',title:'旧概念',content:owner || 'legacy guest',updatedAt:10});
        if (owner) await source.put('drawings',{id:'gallery',gallery:JSON.stringify({version:2,activeId:'same-page',
          pages:[fixture('same-page',owner)]})});
        source.close();
      }
      window.device = await DMateOfflineStorage.open({scope:'device',isCurrent:()=>true});
      return {rows:await device.all('notes'),gallery:JSON.parse((await device.get('drawings','gallery')).gallery),warnings:device.migrationWarnings};
    });
    assert.deepEqual(seeded.rows.map(row=>row.content).sort(),['legacy guest','legacy-A','legacy-B']);
    assert.equal(new Set(seeded.rows.map(row=>row.id)).size,3,'Conflicting old IDs keep separate records');
    assert.equal(seeded.gallery.pages.length,2,'Conflicting old drawing pages remain available');
    assert.equal(new Set(seeded.gallery.pages.map(page=>page.id)).size,2);
    assert.deepEqual(seeded.warnings,[]);
    const retained = await page.evaluate(async () => {
      for (const owner of ['login-A','login-B','']) {
        DMateGuestSession.setAccountOwner(owner);
        dispatchEvent(new CustomEvent('dmate:account-state'));
        dispatchEvent(new CustomEvent('dmate:guest-session-end'));
        if ((await device.all('notes')).length !== 3) return false;
      }
      await device.put('notes',{id:'device-only',title:'本地概念',content:'无需登录也持续保存'});
      let forbidden = false;
      try {await device.destroyGuest();} catch(error) {forbidden=error.code==='INVALID_ARGUMENT';}
      return forbidden && (await device.get('notes','device-only')).content==='无需登录也持续保存';
    });
    assert.equal(retained,true,'Identity changes cannot close or destroy device records');
    await page.evaluate(() => {device.close();DMateGuestSession.reset();});
    await page.close();
    const reopened = await context.newPage();await reopened.goto(base,{waitUntil:'networkidle'});
    const restored = await reopened.evaluate(async () => {
      window.device = await DMateOfflineStorage.open({scope:'device',isCurrent:()=>true});
      const rows = await device.all('notes');
      const migrated = rows.find(row=>row.content==='legacy-A');
      await device.batch([{type:'delete',store:'notes',id:migrated.id},
        {type:'put',store:'settings',value:{id:'notebook-deletions',deleted:{[migrated.id]:Date.now()}}}]);
      device.close();
      window.device = await DMateOfflineStorage.open({scope:'device',isCurrent:()=>true});
      return {rows:await device.all('notes'),deleted:await device.get('notes',migrated.id)};
    });
    assert.ok(restored.rows.some(row=>row.content==='无需登录也持续保存'),'Closing the guest tab retains local data');
    assert.equal(restored.deleted,undefined,'Retained legacy sources do not resurrect a device deletion');
    console.log('PASS device data merges old account/guest partitions and survives login, logout and guest-tab closure');
    const concurrency = await reopened.evaluate(async () => {
      const [first,second] = await Promise.all([
        DMateOfflineStorage.open({scope:'device',isCurrent:()=>true}),
        DMateOfflineStorage.open({scope:'device',isCurrent:()=>true})]);
      await second.put('notes',{id:'raced-new',title:'新概念',content:'保留另一页面的内容'});
      let conflict;
      try {await first.batch([{type:'put',store:'notes',expectAbsent:true,
        value:{id:'raced-new',title:'新概念',content:'不可覆盖'}}]);} catch(error) {conflict=error.code;}
      const content=(await second.get('notes','raced-new')).content;
      first.close();second.close();return {conflict,content};
    });
    assert.equal(concurrency.conflict,'CONFLICT');assert.equal(concurrency.content,'保留另一页面的内容');
    console.log('PASS concurrent device opens and insert-only commits retain the winning local record');
    const partial = await reopened.evaluate(async () => {
      const db=await new Promise(resolve=>{const r=indexedDB.open('dmate-offline-workspace',4);r.onsuccess=()=>resolve(r.result);});
      const suffixA='::'+encodeURIComponent('account:legacy-A'),suffixB='::'+encodeURIComponent('account:legacy-B');
      await new Promise((resolve,reject)=>{const tx=db.transaction(['notes','settings'],'readwrite');
        tx.objectStore('notes').put({id:'legacy-ghost'+suffixA,title:'已删除',content:'不可恢复的旧幽灵',updatedAt:10});
        tx.objectStore('settings').put({id:'notebook-deletions'+suffixA,deleted:{'legacy-ghost':20}});
        tx.objectStore('notes').put({id:'legacy-ghost'+suffixB,title:'另一分区',content:'另一分区同ID可用',updatedAt:10});
        tx.oncomplete=resolve;tx.onerror=reject;});db.close();
      const source=await DMateOfflineVault.open({name:'guest-'+'f'.repeat(32)});
      await source.write('notes','invalid-envelope','Unreadable source',{expectedRevision:null});source.close();
      device.close();window.device=await DMateOfflineStorage.open({scope:'device',isCurrent:()=>true});
      const first=await device.all('notes'),warnings=device.migrationWarnings;device.close();
      window.device=await DMateOfflineStorage.open({scope:'device',isCurrent:()=>true});
      return {first,second:await device.all('notes'),warnings};
    });
    assert.ok(partial.warnings.length,'An unreadable old source is reported');
    assert.ok(partial.second.some(row=>row.content==='另一分区同ID可用'));
    assert.ok(!partial.second.some(row=>row.content==='不可恢复的旧幽灵'),'Partition tombstones suppress only their own legacy ghost');
    assert.equal(partial.second.length,partial.first.length,'Legacy ghosts stay deleted after another open');
    console.log('PASS unreadable old sources retain local access and partition tombstones prevent ghost resurrection');
    const otherContext=await browser.newContext(),isolated=await otherContext.newPage();await isolated.goto(base,{waitUntil:'networkidle'});
    assert.equal(await isolated.evaluate(async()=>{const store=await DMateOfflineStorage.open({scope:'device',isCurrent:()=>true});return(await store.all('notes')).length;}),0,
      'Another browser profile/device does not inherit this device storage');
    await otherContext.close();await context.close();
    console.log('PASS a separate browser profile starts with independent device data');
  } finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;});
