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
async function lazyDeviceOpen(browser,base) {
  const context = await browser.newContext(), page = await context.newPage();
  try {
    await page.goto(base,{waitUntil:'networkidle'});
    const result = await page.evaluate(async () => {
      const original = DMateOfflineVault, scans = [];
      window.DMateOfflineVault = {...original,async open(options) {
        const vault = await original.open(options);
        return {...vault,list(store) {
          if (options.name === 'device-workspace-v1') scans.push(store);
          return vault.list(store);
        }};
      }};
      const open = () => DMateOfflineStorage.open({scope:'device',isCurrent:()=>true});
      let store = await open();
      const coldScans = scans.splice(0);
      for (let offset=0;offset<320;offset+=80) await store.batch(Array.from({length:80},(_,index) => ({
        type:'put',store:'notes',expectAbsent:true,
        value:{id:'large-'+(offset+index),title:'Retained concept '+(offset+index),content:'PRIVATE '.repeat(100),updatedAt:1}
      })));
      store.close();
      const started = performance.now();
      store = await open();
      const reopenMs = performance.now()-started, reopenScans = scans.splice(0);
      // A first write must fetch the touched record, rather than requiring an
      // eager scan to populate every compare-and-swap token during open().
      await store.put('notes',{id:'large-0',title:'Updated',content:'FIRST UNREAD WRITE',updatedAt:2});
      let explicit, absent;
      try { await store.batch([{type:'put',store:'notes',expectedRevision:null,
        value:{id:'large-0',title:'Invalid replace',content:'MUST NOT REPLACE'}}]); }
      catch (error) { explicit = error.code; }
      const untouched = await store.get('notes','large-319');
      const first = await open(), second = await open();
      try { await first.batch([{type:'put',store:'notes',expectAbsent:true,
        value:{id:'large-0',title:'Invalid insert',content:'MUST NOT REPLACE'}}]); }
      catch (error) { absent = error.code; }
      const old = await first.get('notes','large-1'), revision = first.revisionOf('notes',old);
      await second.put('notes',{...old,content:'OTHER HANDLE EDIT',updatedAt:3});
      await first.all('notes');
      let stale;
      try { await first.batch([{type:'put',store:'notes',expectedRevision:revision,
        value:{...old,content:'STALE SNAPSHOT'}}]); } catch (error) { stale = error.code; }
      const latest = await first.get('notes','large-1');
      await first.batch([{type:'delete',store:'notes',id:latest.id,expectedRevision:first.revisionOf('notes',latest)},
        {type:'put',store:'settings',value:{id:'notebook-deletions',deleted:{[latest.id]:4}}}]);
      first.close(); second.close(); store.close();
      scans.length = 0;
      store = await open();
      const deletedOpenScans = scans.splice(0);
      const deleted = await store.get('notes','large-1'), tombstone = await store.get('settings','notebook-deletions');
      const retained = await store.get('notes','large-0');
      store.close();
      DMateGuestSession.setAccountOwner('lazy-source');
      let source = await DMateOfflineStorage.open({owner:'lazy-source',isCurrent:()=>true});
      await source.put('notes',{id:'incoming',title:'Legacy concept',content:'SOURCE VERSION ONE',updatedAt:10});
      source.close(); DMateGuestSession.setAccountOwner('');
      scans.length = 0;
      store = await open();
      const firstMigrationScans = scans.splice(0);
      const migrated = (await store.all('notes')).filter(row => row.content === 'SOURCE VERSION ONE').length;
      store.close(); scans.length = 0;
      store = await open();
      const unchangedMigrationScans = scans.splice(0);
      store.close();
      // An old page can still save another revision after its first migration.
      DMateGuestSession.setAccountOwner('lazy-source');
      source = await DMateOfflineStorage.open({owner:'lazy-source',isCurrent:()=>true});
      await source.put('notes',{id:'incoming',title:'Legacy concept',content:'SOURCE VERSION TWO',updatedAt:20});
      source.close(); DMateGuestSession.setAccountOwner('');
      scans.length = 0;
      store = await open();
      const laterMigrationScans = scans.splice(0), rows = await store.all('notes');
      store.close(); scans.length = 0;
      store = await open();
      const retriedScans = scans.splice(0), retried = await store.all('notes');
      store.close();
      return {coldScans,reopenScans,reopenMs,deletedOpenScans,explicit,absent,stale,untouched,retained,
        deleted:deleted === undefined,tombstone,migrated,firstMigrationScans,unchangedMigrationScans,laterMigrationScans,
        versions:rows.filter(row => row.id === 'incoming' || row.id.startsWith('migrated-')).map(row => row.content).sort(),
        retriedScans,stable:JSON.stringify(retried) === JSON.stringify(rows)};
    });
    for (const name of ['coldScans','reopenScans','deletedOpenScans','unchangedMigrationScans','retriedScans'])
      assert.deepEqual(result[name],[],name+': opening an unchanged device vault must not decrypt complete collections');
    for (const name of ['explicit','absent','stale']) assert.equal(result[name],'CONFLICT',name+': lazy opening preserves compare-and-swap checks');
    assert.equal(result.untouched.title,'Retained concept 319');
    assert.equal(result.retained.content,'FIRST UNREAD WRITE');
    assert.equal(result.deleted,true); assert.equal(result.tombstone.deleted['large-1'],4);
    assert.equal(result.migrated,1);
    assert.equal(result.firstMigrationScans.length,5,'A new migration still initializes the complete deduplication indexes');
    assert.equal(result.laterMigrationScans.length,5,'A returning old source still imports its later edit');
    assert.deepEqual(result.versions,['SOURCE VERSION ONE','SOURCE VERSION TWO']); assert.equal(result.stable,true);
    console.log('PASS lazy open of 320 encrypted records: no eager collection decryption; unread writes, explicit revisions, insert-only CAS, tombstones and later source migrations remain safe ('+result.reopenMs.toFixed(1)+' ms local reopen)');
  } finally {await context.close();}
}
(async () => {
  await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
  const base = 'http://127.0.0.1:'+server.address().port;
  const browser = await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH
    ? {executablePath:process.env.CHROMIUM_EXECUTABLE_PATH} : {})});
  try {
    await lazyDeviceOpen(browser,base);
    const context = await browser.newContext(), page = await context.newPage();
    await page.goto(base,{waitUntil:'networkidle'});
    const seeded = await page.evaluate(async () => {
      const fixture = (id,name) => ({id,name,document:{body_text:'',graphs:[{id:'G1',name,directed:false,weighted:false,
        vertices:[{id:'v1',label:'1',x:100,y:100}],edges:[]}]}});
      for (const owner of ['legacy-A','legacy-B','']) {
        DMateGuestSession.setAccountOwner(owner);
        const source = await DMateOfflineStorage.open({owner,isCurrent:()=>true});
        await source.put('notes',{id:owner ? 'same-id' : 'guest-id',title:'旧概念',content:owner || 'legacy guest',updatedAt:10});
        await source.put('mistakes',{id:'same-wrong-id',statement:owner ? '设 A={1,2}，求 A 的幂集。' : '求集合 B 的补集。',
          answer:owner ? '保留答案-'+owner : '游客的另一道题',
          focusPoints:[owner || '集合运算'],createdAt:owner==='legacy-A' ? 10 : 20,updatedAt:30});
        if (owner) await source.put('drawings',{id:'gallery',gallery:JSON.stringify({version:2,activeId:'same-page',
          pages:[fixture('same-page',owner)]})});
        source.close();
      }
      window.device = await DMateOfflineStorage.open({scope:'device',isCurrent:()=>true});
      return {rows:await device.all('notes'),mistakes:await device.all('mistakes'),
        gallery:JSON.parse((await device.get('drawings','gallery')).gallery),warnings:device.migrationWarnings};
    });
    assert.deepEqual(seeded.rows.map(row=>row.content).sort(),['legacy guest','legacy-A','legacy-B']);
    assert.equal(new Set(seeded.rows.map(row=>row.id)).size,3,'Conflicting old IDs keep separate records');
    assert.equal(seeded.gallery.pages.length,2,'Conflicting old drawing pages remain available');
    assert.equal(new Set(seeded.gallery.pages.map(page=>page.id)).size,2);
    assert.deepEqual(seeded.warnings,[]);
    assert.equal(seeded.mistakes.length,2,'The same question merges across old partitions even with different answers and dates');
    assert.ok(JSON.stringify(seeded.mistakes).includes('保留答案-legacy-A'));
    assert.ok(JSON.stringify(seeded.mistakes).includes('保留答案-legacy-B'),'Merging keeps both old answers');
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
      return {rows:await device.all('notes'),mistakes:await device.all('mistakes'),deleted:await device.get('notes',migrated.id)};
    });
    assert.ok(restored.rows.some(row=>row.content==='无需登录也持续保存'),'Closing the guest tab retains local data');
    assert.equal(restored.deleted,undefined,'Retained legacy sources do not resurrect a device deletion');
    assert.deepEqual(restored.mistakes,seeded.mistakes,'Retrying old-source migration is idempotent for merged answers');
    console.log('PASS device data merges old account/guest partitions and survives login, logout and guest-tab closure');
    const editedSource = await reopened.evaluate(async () => {
      DMateGuestSession.setAccountOwner('legacy-A');
      const source=await DMateOfflineStorage.open({owner:'legacy-A',isCurrent:()=>true});
      const row=await source.get('mistakes','same-wrong-id');
      await source.put('mistakes',{...row,answer:'旧页面追加的答案',updatedAt:40});source.close();
      DMateGuestSession.setAccountOwner('');
      device.close();window.device=await DMateOfflineStorage.open({scope:'device',isCurrent:()=>true});
      return await device.all('mistakes');
    });
    assert.equal(editedSource.length,2,'An edited old source still adds no duplicate question');
    for(const answer of ['保留答案-legacy-A','保留答案-legacy-B','旧页面追加的答案'])
      assert.ok(JSON.stringify(editedSource).includes(answer),'A returning source keeps '+answer);
    console.log('PASS old-source mistakes merge by question and retain differing answers through reopening and later edits');
    const concurrency = await reopened.evaluate(async () => {
      const [first,second] = await Promise.all([
        DMateOfflineStorage.open({scope:'device',isCurrent:()=>true}),
        DMateOfflineStorage.open({scope:'device',isCurrent:()=>true})]);
      await second.put('notes',{id:'raced-new',title:'新概念',content:'保留另一页面的内容'});
      let conflict;
      try {await first.batch([{type:'put',store:'notes',expectAbsent:true,
        value:{id:'raced-new',title:'新概念',content:'不可覆盖'}}]);} catch(error) {conflict=error.code;}
      const content=(await second.get('notes','raced-new')).content;
      const question={id:'raced-wrong',statement:'求 A 与 B 的交集。',answer:'original'};
      await first.put('mistakes',question);
      const old=(await first.all('mistakes')).find(row=>row.id===question.id);
      const expectedRevision=first.revisionOf('mistakes',old);
      await second.put('mistakes',{...question,answer:'OTHER TAB NEW ANSWER'});
      // Rendering can refresh the handle's revision cache while the import is
      // computing fingerprints. Its original snapshot still owns the token.
      await first.all('mistakes');
      const stale=await DMateOfflineBackup.mergeMistakes(old,{...question,answer:'IMPORTED ANSWER'});
      let mergeConflict;
      try {await first.batch([{type:'put',store:'mistakes',value:stale,expectedRevision}]);}
      catch(error) {mergeConflict=error.code;}
      const retained=await second.get('mistakes',question.id);
      const latest=await first.get('mistakes',question.id);
      const merged=await DMateOfflineBackup.mergeMistakes(latest,stale);
      await first.batch([{type:'put',store:'mistakes',value:merged,expectedRevision:first.revisionOf('mistakes',latest)}]);
      const retried=await first.get('mistakes',question.id);
      first.close();second.close();return {conflict,content,mergeConflict,retained,retried};
    });
    assert.equal(concurrency.conflict,'CONFLICT');assert.equal(concurrency.content,'保留另一页面的内容');
    assert.equal(concurrency.mergeConflict,'CONFLICT','A later re-render cannot advance an old import snapshot revision');
    assert.equal(concurrency.retained.answer,'OTHER TAB NEW ANSWER','A stale import never overwrites another page answer');
    for(const answer of ['original','OTHER TAB NEW ANSWER','IMPORTED ANSWER'])
      assert.ok(JSON.stringify(concurrency.retried).includes(answer),'Retry retains '+answer);
    console.log('PASS concurrent device opens and insert-only commits retain the winning local record');
    console.log('PASS snapshot-bound import CAS survives intervening UI reads and retries without losing answers');
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
