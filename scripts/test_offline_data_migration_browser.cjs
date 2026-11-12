/* Start Flask first. Verify local migrations, queued notebook edits, storage
 * failures and deletion metadata in isolated browser contexts. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.BASE_URL || process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const executablePath = process.env.CHROMIUM || process.env.CHROMIUM_EXECUTABLE_PATH;
const journalKey = 'dmate:offline:notebook-journal:v1';
const iso = value => new Date(value).toISOString();
const note = (id, updatedAt, content, extra = {}) => ({ id, title:id, content, updatedAt:iso(updatedAt), ...extra });
const ready = page => page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');

async function openNotes(page) {
  const button = page.locator('.offline-nav-item[data-panel="notes"]');
  if (!await button.isVisible()) await page.locator('#offlineDesktopSidebarOpen').click();
  await button.click();
}

async function prepare(page, seed) {
  await page.goto(baseURL + '/offline');
  await ready(page);
  await page.evaluate(async ({ seed, journalKey }) => {
    const db = await new Promise((resolve, reject) => {
      const request = indexedDB.open('dmate-offline-workspace', 2);
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
    await new Promise((resolve, reject) => {
      const tx = db.transaction(['notes', 'settings', 'mistakes'], 'readwrite');
      for (const row of seed.notes || []) tx.objectStore('notes').put(row);
      for (const row of seed.mistakes || []) tx.objectStore('mistakes').put(row);
      tx.objectStore('settings').put({ ...seed.deletionMetadata, id:'notebook-deletions', deleted:seed.deleted || {} });
      tx.oncomplete = resolve; tx.onerror = tx.onabort = () => reject(tx.error);
    });
    db.close();
    if (seed.journal) localStorage.setItem(journalKey, JSON.stringify(seed.journal));
    sessionStorage.setItem('dmate_offline_migration_v1', JSON.stringify(seed.incoming));
  }, { seed, journalKey });
  await page.reload();
  await ready(page);
}

async function read(page) {
  return page.evaluate(() => new Promise((resolve, reject) => {
    const request = indexedDB.open('dmate-offline-workspace', 2);
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      const db = request.result, tx = db.transaction(['notes', 'settings', 'mistakes']);
      const notes = tx.objectStore('notes').getAll(), mistakes = tx.objectStore('mistakes').getAll();
      const deletions = tx.objectStore('settings').get('notebook-deletions');
      tx.oncomplete = () => {
        db.close();
        resolve({ notes:notes.result, mistakes:mistakes.result,
          deleted:deletions.result.deleted, deletionMetadata:deletions.result });
      };
      tx.onerror = tx.onabort = () => { db.close(); reject(tx.error); };
    };
  }));
}

async function waitForNote(page, id, expected) {
  await page.waitForFunction(({ id, expected }) => new Promise((resolve, reject) => {
    const request = indexedDB.open('dmate-offline-workspace', 2);
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      const db = request.result;
      const tx = db.transaction('notes', 'readonly');
      const row = tx.objectStore('notes').get(id);
      tx.oncomplete = () => {
        db.close();
        resolve(expected === null ? !row.result : row.result
          && Object.entries(expected).every(([key, value]) => row.result[key] === value));
      };
      tx.onerror = tx.onabort = () => { db.close(); reject(tx.error); };
    };
  }), { id, expected });
}

async function verifyNotebookWrites(browser) {
  const context = await browser.newContext({
    viewport: { width:1440, height:900 }, serviceWorkers:'block'
  });
  const page = await context.newPage();
  const pageErrors = [], apiRequests = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.origin === new URL(baseURL).origin
        && ['fetch', 'xhr'].includes(request.resourceType())
        && !url.pathname.startsWith('/static/')) apiRequests.push(url.pathname);
  });
  const selectNote = id => page.locator('.dcn-note[data-note-id="' + id + '"] .dcn-note-open').click();
  try {
    await prepare(page, {
      notes: [
        note('queue-a', 2000, 'alpha original', {
          title:'甲原', createdAt:'retain-created-a', custom:{ marker:'a' }
        }),
        note('queue-b', 1000, 'beta original', {
          title:'乙原', createdAt:'retain-created-b', custom:{ marker:'b' }
        })
      ],
      deleted: { 'older-deletion':1 },
      deletionMetadata: { custom:{ retained:true } },
      incoming: {}
    });
    await openNotes(page);
    await selectNote('queue-a');

    // Dispatch several inputs in one task, before any IndexedDB write can
    // complete. An older snapshot must not clear or overwrite the newest one.
    await page.evaluate(() => {
      const title = document.querySelector('#noteList .dcn-title');
      const body = document.querySelector('#noteList .dcn-original');
      for (const value of ['甲-1', '甲-final']) {
        title.value = value;
        title.dispatchEvent(new Event('input', { bubbles:true }));
      }
      body.value = 'alpha newest';
      body.dispatchEvent(new Event('input', { bubbles:true }));
    });
    await selectNote('queue-b');
    await page.locator('#noteList .dcn-original').fill('beta newest');
    await waitForNote(page, 'queue-a', { title:'甲-final', content:'alpha newest' });
    await waitForNote(page, 'queue-b', { content:'beta newest' });

    const persisted = (await read(page)).notes;
    for (const [id, marker, createdAt] of [
      ['queue-a', 'a', 'retain-created-a'], ['queue-b', 'b', 'retain-created-b']
    ]) {
      const row = persisted.find(item => item.id === id);
      assert.deepEqual(row.custom, { marker });
      assert.equal(row.createdAt, createdAt);
      assert.equal(new Date(row.updatedAt).toISOString(), row.updatedAt, 'Notebook timestamps remain ISO strings');
    }
    await page.locator('#noteList .dcn-search').fill('甲-final');
    assert.equal(await page.locator('.dcn-note').count(), 1);
    assert.equal((await read(page)).notes.length, 2, 'Searching must not remove stored notes');
    await page.locator('#noteList .dcn-search').fill('');
    await selectNote('queue-a');

    // Fail only this note's writes. Other reads and the rest of the workspace
    // remain usable, while the current page must retain the failed draft.
    await page.evaluate(() => {
      window.noteDataTestOriginalPut = IDBObjectStore.prototype.put;
      IDBObjectStore.prototype.put = function (value, ...args) {
        if (this.name === 'notes' && value.id === 'queue-a') {
          throw new DOMException('Simulated notebook storage failure', 'QuotaExceededError');
        }
        return window.noteDataTestOriginalPut.call(this, value, ...args);
      };
    });
    await page.locator('#noteList .dcn-original').fill('alpha pending retry');
    await page.locator('#noteList .dcn-saved').filter({ hasText:'保存失败' }).waitFor();
    await selectNote('queue-b');
    await selectNote('queue-a');
    assert.equal(await page.locator('#noteList .dcn-original').inputValue(), 'alpha pending retry');
    assert.equal((await read(page)).notes.find(row => row.id === 'queue-a').content, 'alpha newest');

    await page.locator('#addNote').click();
    await page.waitForFunction(() => document.getElementById('offlineToast').textContent.includes('尚未保存'));
    assert.equal((await read(page)).notes.length, 2, 'A failed draft must prevent creating a misleading blank note');
    assert.equal(await page.locator('#noteList .dcn-original').inputValue(), 'alpha pending retry');
    assert.equal(await page.locator('.dcn-note.is-current').getAttribute('data-note-id'), 'queue-a');

    await page.evaluate(() => { IDBObjectStore.prototype.put = window.noteDataTestOriginalPut; });
    await page.locator('.offline-nav-item[data-panel="mistakes"]').click();
    await openNotes(page);
    await waitForNote(page, 'queue-a', { content:'alpha pending retry' });

    await page.locator('.dcn-note[data-note-id="queue-b"] .dcn-note-delete').click();
    await page.locator('.dmate-delete-confirm[open] .dmate-delete-confirm-delete').click();
    await waitForNote(page, 'queue-b', null);
    await page.locator('.dcn-note[data-note-id="queue-b"]').waitFor({ state:'detached' });
    const afterDelete = await read(page);
    assert.equal(afterDelete.notes.length, 1);
    assert.equal(afterDelete.notes[0].id, 'queue-a');
    assert.ok(afterDelete.deleted['queue-b'] > Date.parse(persisted.find(row => row.id === 'queue-b').updatedAt));
    assert.equal(afterDelete.deleted['older-deletion'], 1);
    assert.deepEqual(afterDelete.deletionMetadata.custom, { retained:true });
    assert.equal(await page.locator('#noteList .dcn-original').inputValue(), 'alpha pending retry');
    assert.equal(await page.locator('.dcn-note.is-current').getAttribute('data-note-id'), 'queue-a');
    for (const name of ['AI 解释', '分析关联']) {
      assert.equal(await page.locator('#noteList').getByRole('button', { name, exact:true }).isDisabled(), true);
    }
    assert.deepEqual(apiRequests, [], 'Offline notebook actions must not call AI or other server APIs');
    assert.deepEqual(pageErrors, []);
    console.log('Notebook saves retain rapid edits and metadata, preserve failed drafts for retry, and record deletions without API calls.');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless:true, ...(executablePath ? { executablePath } : {}) });
  try {
    const context = await browser.newContext({ serviceWorkers:'block' }), page = await context.newPage();
    const extra = { createdAt:'original-created-at', custom:{ retained:true } };
    await prepare(page, {
      notes:[note('local-newer', 5000, 'latest offline edit', extra), note('incoming-newer', 1000, 'old local', extra)],
      mistakes:[{ id:'mistake-newer', title:'local', statement:'latest offline question', status:'resolved', updatedAt:iso(5000), custom:'keep' }],
      deleted:{ 'deleted-note':4000, 'restored-note':2000 },
      incoming:{ notes:[
        { id:'local-newer', title:'old online', content:'stale online edit', updatedAt:1000 },
        { id:'incoming-newer', title:'incoming-newer', content:'new online edit', updatedAt:5000 },
        { id:'new-note', title:'new-note', content:'newly imported', updatedAt:3000 },
        { id:'deleted-note', title:'deleted-note', content:'must stay deleted', updatedAt:3000 },
        { id:'restored-note', title:'restored-note', content:'newer than deletion', updatedAt:5000 }
      ], wrongQuestions:[{ id:'mistake-newer', question:'stale online question', updatedAt:1000 }] }
    });
    const first = await read(page), byId = new Map(first.notes.map(row => [row.id, row]));
    assert.equal(byId.get('local-newer').content, 'latest offline edit');
    assert.equal(byId.get('incoming-newer').content, 'new online edit');
    for (const id of ['local-newer', 'incoming-newer']) {
      assert.equal(byId.get(id).createdAt, extra.createdAt); assert.deepEqual(byId.get(id).custom, extra.custom);
    }
    assert.equal(byId.get('new-note').content, 'newly imported');
    assert.equal(byId.has('deleted-note'), false, 'an old import must not resurrect a deleted note');
    assert.equal(byId.get('restored-note').content, 'newer than deletion');
    assert.equal(first.deleted['deleted-note'], 4000);
    assert.equal(first.mistakes[0].statement, 'latest offline question');
    assert.equal(first.mistakes[0].status, 'resolved'); assert.equal(first.mistakes[0].custom, 'keep');
    await openNotes(page);
    await page.locator('.dcn-note-open').filter({ hasText:'new-note' }).waitFor();
    assert.equal(await page.locator('.dcn-note-open').filter({ hasText:'deleted-note' }).count(), 0);
    await context.close();

    const recoveryContext = await browser.newContext({ serviceWorkers:'block' }), recoveryPage = await recoveryContext.newPage();
    const pending = note('pending-note', 6000, 'durable journal edit', extra);
    await prepare(recoveryPage, {
      notes:[note('pending-note', 1000, 'outdated database edit', extra)],
      journal:{ version:1, rows:[pending], snapshot:{ notes:[{ ...pending, updatedAt:6000 }], deleted:{} } },
      incoming:{ notes:[{ id:'pending-note', title:'old online', content:'stale incoming', updatedAt:2000 },
        { id:'import-with-journal', title:'import-with-journal', content:'imported alongside recovery', updatedAt:3000 }] }
    });
    const recovered = (await read(recoveryPage)).notes.find(row => row.id === 'pending-note');
    assert.equal(recovered.content, 'durable journal edit'); assert.deepEqual(recovered.custom, extra.custom);
    assert.equal(recovered.createdAt, extra.createdAt);
    assert.equal(await recoveryPage.evaluate(key => localStorage.getItem(key), journalKey), null);
    await openNotes(recoveryPage);
    await recoveryPage.locator('.dcn-note-open').filter({ hasText:'import-with-journal' }).waitFor();
    await recoveryContext.close();
    console.log('Offline migration preserves newer edits, metadata, tombstones and journal recovery.');
    await verifyNotebookWrites(browser);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
