/* Guest snapshots are scoped to a tab/native launch and retain binary drafts. */
'use strict';
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.CHROMIUM_EXECUTABLE_PATH ? {executablePath:process.env.CHROMIUM_EXECUTABLE_PATH} : {})});
  const context = await browser.newContext({serviceWorkers:'block'});
  let launch = 'native-launch-one';
  await context.route('**/__guest-session-test', route => route.fulfill({contentType:'text/html',body:
    '<!doctype html><script>window.__DMATE_NATIVE_GUEST_SESSION__=' + JSON.stringify(launch) + '</script><script src="/static/guest-session.js"></script>'}));
  const page = await context.newPage();
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  try {
    await page.goto(baseURL + '/__guest-session-test');
    await page.evaluate(async () => {
      DMateGuestSession.write('draft', 'Unsent guest text');
      if (!await DMateGuestSession.writeBlob('background', new Blob(['private pixels'], {type:'image/png'}))) throw Error('blob save failed');
    });
    await page.reload();
    assert.deepEqual(await page.evaluate(async () => [DMateGuestSession.read('draft'), await (await DMateGuestSession.readBlob('background')).text()]), ['Unsent guest text','private pixels']);
    const copied = await page.evaluate(() => sessionStorage.getItem('dmate:guest-tab:v1'));
    const other = await context.newPage();
    await other.addInitScript(value => sessionStorage.setItem('dmate:guest-tab:v1', value), copied);
    await other.goto(baseURL + '/__guest-session-test');
    assert.equal(await other.evaluate(() => DMateGuestSession.read('draft')), null, 'A new tab rejects opener-copied sessionStorage');
    await other.close();
    assert.equal(await page.evaluate(async () => {
      const original = Storage.prototype.setItem;
      Storage.prototype.setItem = function(key, value) { if(key === 'dmate:guest-tab:v1') throw new DOMException('quota','QuotaExceededError'); return original.call(this,key,value); };
      try { return await DMateGuestSession.writeBlob('background',new Blob(['replacement'])); }
      finally { Storage.prototype.setItem = original; }
    }), false);
    assert.equal(await page.evaluate(async () => (await DMateGuestSession.readBlob('background')).text()), 'private pixels', 'A failed checkpoint preserves the last saved blob');
    const live = await context.newPage();
    await live.goto(baseURL + '/__guest-session-test');
    const liveId = await live.evaluate(async () => {
      await DMateGuestSession.writeBlob('draft-image',new Blob(['live image']));
      return DMateGuestSession.read('draft-image').id;
    });
    await live.waitForFunction(async () => (await navigator.locks.query()).held.some(lock => lock.name.includes(window.name + '|')));
    await page.evaluate(async id => {
      localStorage.setItem('dmate:guest-asset-last-seen:closed-tab|old-launch|',String(Date.now()-7200000));
      const db = await new Promise((resolve,reject) => {const r=indexedDB.open('dmate-guest-tab-assets-v1',1);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
      await new Promise((resolve,reject) => {
        const tx=db.transaction('assets','readwrite'), store=tx.objectStore('assets'), read=store.get(id);
        read.onsuccess=()=>{store.put({...read.result,updatedAt:0});store.put({...read.result,id:'closed-tab|old-launch|draft|orphan',updatedAt:0});};
        tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);
      });db.close();
    },liveId);
    await page.reload();
    await page.waitForFunction(async () => {
      const db=await new Promise(resolve=>{const r=indexedDB.open('dmate-guest-tab-assets-v1',1);r.onsuccess=()=>resolve(r.result);});
      const rows=await new Promise(resolve=>{const tx=db.transaction('assets'),r=tx.objectStore('assets').getAll();tx.oncomplete=()=>resolve(r.result);});db.close();
      return !rows.some(row=>row.id==='closed-tab|old-launch|draft|orphan');
    });
    assert.equal(await live.evaluate(async () => (await DMateGuestSession.readBlob('draft-image')).text()),'live image','Orphan cleanup retains an old image owned by a live background tab');
    await live.route('**/__guest-session-test', route => route.fulfill({contentType:'text/html',body:'<!doctype html><script>window.__DMATE_NATIVE_GUEST_SESSION__="native-launch-one"</script>'}),{times:1});
    await live.reload();
    await page.reload();
    await live.addScriptTag({url:baseURL+'/static/guest-session.js'});
    assert.equal(await live.evaluate(async () => (await DMateGuestSession.readBlob('draft-image')).text()),'live image','The pagehide lease stamp protects an image during the reload document gap');
    await live.close();
    await page.evaluate(() => DMateGuestSession.setAccountOwner('account-a'));
    assert.equal(await page.evaluate(() => DMateGuestSession.read('draft')), null);
    await page.evaluate(() => { DMateGuestSession.beginGuest(); DMateGuestSession.write('draft','New guest'); });
    launch = 'native-launch-two';
    await page.reload();
    assert.equal(await page.evaluate(() => DMateGuestSession.read('draft')), null, 'A cold native launch rejects prior sessionStorage');
    await page.evaluate(() => { DMateGuestSession.write('draft','one more'); dispatchEvent(new Event('dmate:guest-session-end')); });
    assert.equal(await page.evaluate(() => DMateGuestSession.read('draft')), null);
    assert.deepEqual(errors, []);
    console.log('PASS guest store: refresh, binary drafts, copied-tab rejection, quota recovery, owner reset and native launch reset');
    await context.route('**/auth/me', route => route.fulfill({contentType:'application/json',body:JSON.stringify({configured:true,authenticated:false})}));
    for (const path of ['**/chat','**/analyze-questions','**/conversation/title']) await context.route(path,route=>route.abort());
    await page.goto(baseURL, {waitUntil:'networkidle'});
    await page.waitForFunction(() => !accountVerificationOperation && window.dmateConceptNotebook);
    await page.evaluate(async () => {
      newChat();
      getCurrent().messages.push({messageId:'guest-msg',role:'user',text:'Guest question'}); saveState();
      setConceptNotebookState({notes:[{id:'guest-note',title:'Draft definition',content:'A guest concept',createdAt:1,updatedAt:2}],deleted:{}});
      dmateConceptNotebook.restoreViewState({currentId:'guest-note',selected:['guest-note'],search:'Draft',question:'Explain my example'});
      document.getElementById('text').value = 'Unsent composer draft';
      DMateI18n.setLanguage('en');
      const file = new File(['queued original image bytes'],'queued.png',{type:'image/png'});
      ocrTasks.set('guest-image',{id:'guest-image',groupId:'group-1',file,sessionId:currentId,originalUrl:URL.createObjectURL(file),state:'ready',
        draft:{body_text:'Confirmed problem',graphs:[]},initialDocument:{body_text:'Confirmed problem',graphs:[]},confirmation:null,
        userRequest:'Use my method',isQuestion:true,error:'',notice:'',dirty:true});
      const wrong = addWrongQuestion({text:'证明有限集合的并运算满足交换律',safeConfirmed:true},null,'manual').entry;
      openWrongEdit(wrong.id);
      document.getElementById('wrongEditQuestion').value='Unsaved edited exercise';
      document.getElementById('wrongEditNote').value='Unsent learning note';
      renderOcrTasks(); checkpointGuestDrafts();
      await checkpointGuestOcrTasks();
    });
    await page.reload({waitUntil:'networkidle'});
    await page.waitForFunction(() => !accountVerificationOperation && ocrTasks.size === 1);
    const workspace = await page.evaluate(async () => ({
      draft:document.getElementById('text').value,
      messages:getCurrent().messages.map(message => message.text),
      language:DMateI18n.getLanguage(), notebook:dmateConceptNotebook.getState().notes,
      view:dmateConceptNotebook.getViewState(),
      image:await ocrTasks.get('guest-image').file.text(), requirements:ocrTasks.get('guest-image').userRequest,
      document:ocrTasks.get('guest-image').draft.body_text,
      wrongDraft:[document.getElementById('wrongEditQuestion').value,document.getElementById('wrongEditNote').value],
      wrongOpen:!document.getElementById('wrongEditModal').classList.contains('hidden')
    }));
    assert.equal(workspace.draft,'Unsent composer draft');
    assert.deepEqual(workspace.messages,['Guest question']);
    assert.equal(workspace.language,'en');
    assert.equal(workspace.notebook[0].content,'A guest concept');
    assert.equal(workspace.view.question,'Explain my example');
    assert.deepEqual(workspace.view.selected,['guest-note']);
    assert.equal(workspace.image,'queued original image bytes');
    assert.equal(workspace.requirements,'Use my method');
    assert.equal(workspace.document,'Confirmed problem');
    assert.deepEqual(workspace.wrongDraft,['Unsaved edited exercise','Unsent learning note']);
    assert.equal(workspace.wrongOpen,true);
    assert.deepEqual(errors,[]);
    console.log('PASS real guest workspace: chat, notebook selection/requirements, composer, language and queued original/draft survive refresh');
  } finally { await context.close(); await browser.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
