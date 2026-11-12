/* Start Flask first. Verify that entering offline mode again preserves local
 * edits, deletion records and metadata, including an outstanding journal. */
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
      tx.objectStore('settings').put({ id:'notebook-deletions', deleted:seed.deleted || {} });
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
      tx.oncomplete = () => { db.close(); resolve({ notes:notes.result, mistakes:mistakes.result, deleted:deletions.result.deleted }); };
      tx.onerror = tx.onabort = () => { db.close(); reject(tx.error); };
    };
  }));
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
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
