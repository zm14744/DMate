/* Start Flask first. The four-module workspace imports only drawing data;
 * removed notebook/wrong-book stores and journals must remain untouched.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.BASE_URL || process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const executablePath = process.env.CHROMIUM || process.env.CHROMIUM_EXECUTABLE_PATH;
const dbName = 'dmate-offline-workspace', journalKey = 'dmate:offline:notebook-journal:v1';
const galleryKey = 'dmate:offline:drawing-gallery:v1', migrationKey = 'dmate_offline_migration_v1';
const documentFor = label => ({ body_text: 'Body ' + label, graphs: [{ id:'G1', name:label,
  directed:false, weighted:false, vertices:[{ id:'v1', label, x:.3, y:.4 }], edges:[] }] });
const drawing = (id, name, label, updatedAt) => ({ id, name, document:documentFor(label),
  createdAt:1, updatedAt, requirement:'Retained request', custom:{ marker:id } });
const ready = page => page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
const removed = '#wrongBookBtn,#conceptNotebookBtn,#mistakesPanel,#notesPanel,#recordDialog,#recordForm';

async function bootstrap(context) {
  await context.route('**/__offline-data-test', route => route.fulfill({ contentType:'text/html', body:'<!doctype html><title>Local fixture</title>' }));
  const page = await context.newPage();
  await page.goto(baseURL + '/__offline-data-test');
  return page;
}

async function seed(page, fixture) {
  await page.evaluate(async ({ fixture, dbName, journalKey, galleryKey, migrationKey }) => {
    if (fixture.legacy) {
      const db = await new Promise((resolve, reject) => {
        const request = indexedDB.open(dbName, 2);
        request.onupgradeneeded = () => {
          for (const name of ['notes','mistakes','practice','settings']) request.result.createObjectStore(name, { keyPath:'id' });
        };
        request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
      });
      await new Promise((resolve, reject) => {
        const tx = db.transaction(['notes','mistakes','practice','settings'], 'readwrite');
        for (const name of ['notes','mistakes','practice','settings']) for (const row of fixture.legacy[name]) tx.objectStore(name).put(row);
        tx.oncomplete = resolve; tx.onerror = tx.onabort = () => reject(tx.error);
      });
      db.close();
    }
    localStorage.setItem(journalKey, fixture.journal);
    if (fixture.gallery) localStorage.setItem(galleryKey, JSON.stringify(fixture.gallery));
    sessionStorage.setItem(migrationKey, JSON.stringify(fixture.incoming));
  }, { fixture, dbName, journalKey, galleryKey, migrationKey });
}

async function guardRemovedData(context) {
  await context.addInitScript(({ journalKey }) => {
    if (location.pathname !== '/offline') return;
    const native = window.removedDataNative = { getItem:Storage.prototype.getItem,
      setItem:Storage.prototype.setItem, removeItem:Storage.prototype.removeItem,
      transaction:IDBDatabase.prototype.transaction, get:IDBObjectStore.prototype.get };
    window.removedDataAccesses = [];
    const forbidden = value => { window.removedDataAccesses.push(value); throw new Error('Removed data accessed: ' + value); };
    for (const method of ['getItem','setItem','removeItem']) {
      Storage.prototype[method] = function(key, ...args) {
        if (key === journalKey) return forbidden('journal.' + method);
        return native[method].call(this, key, ...args);
      };
    }
    IDBDatabase.prototype.transaction = function(stores, ...args) {
      const names = typeof stores === 'string' ? [stores] : [...stores];
      if (names.some(name => ['notes','mistakes'].includes(name))) return forbidden('stores:' + names.join(','));
      return native.transaction.call(this, stores, ...args);
    };
    IDBObjectStore.prototype.get = function(key) {
      if (this.name === 'settings' && key === 'notebook-deletions') return forbidden('notebook-deletions');
      return native.get.call(this, key);
    };
  }, { journalKey });
}

async function readState(page) {
  return page.evaluate(({ dbName, journalKey, galleryKey }) => new Promise((resolve, reject) => {
    const request = indexedDB.open(dbName, 2);
    request.onerror = () => reject(request.error);
    request.onsuccess = async () => {
      const db = request.result, native = window.removedDataNative;
      const result = { version:db.version, stores:[...db.objectStoreNames], records:{} };
      for (const name of result.stores) {
        result.records[name] = await new Promise((done, fail) => {
          // Inspection bypasses only the test's access guard, never application code.
          const tx = native.transaction.call(db, name, 'readonly'), get = tx.objectStore(name).getAll();
          tx.oncomplete = () => done(get.result); tx.onerror = tx.onabort = () => fail(tx.error);
        });
      }
      db.close();
      result.journal = native.getItem.call(localStorage, journalKey);
      result.gallery = JSON.parse(localStorage.getItem(galleryKey) || 'null');
      result.accesses = [...window.removedDataAccesses];
      resolve(result);
    };
  }), { dbName, journalKey, galleryKey });
}

async function verifyOfflineMigration(browser, legacy) {
  const context = await browser.newContext({ viewport:{ width:1440, height:900 }, serviceWorkers:'block' });
  const page = await bootstrap(context), errors = [], apiRequests = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    const url = new URL(request.url());
    if (['fetch','xhr'].includes(request.resourceType()) && url.origin === new URL(baseURL).origin
        && !url.pathname.startsWith('/static/')) apiRequests.push(url.pathname);
  });
  const records = { notes:[{ id:'keep-note', title:'Original note', content:'Untouched', custom:{ keep:true } }],
    mistakes:[{ id:'keep-mistake', statement:'Original question', answer:'Original answer', custom:'retain' }],
    practice:[{ id:'keep-practice', questionId:'q01', selected:['A'], custom:'keep' }],
    settings:[{ id:'notebook-deletions', deleted:{ deleted:12345 }, custom:{ retain:true } }] };
  const local = { version:2, activeId:'local-active', custom:{ gallery:'retain' },
    pages:[drawing('shared','Shared local','local shared',1000), drawing('local-active','Local active','local active',2000)] };
  const incomingGallery = { version:2, activeId:'incoming-only', custom:{ gallery:'must not replace local' },
    pages:[drawing('shared','Conflicting newer incoming','must not overwrite',999999), drawing('incoming-only','Incoming only','incoming',3000)] };
  const incoming = { username:'fixture-user', drawings:JSON.stringify(incomingGallery),
    notes:[{ id:'keep-note', title:'must ignore', content:'must ignore', updatedAt:999999 }],
    wrongQuestions:[{ id:'keep-mistake', question:'must ignore', updatedAt:999999 }] };
  const journal = legacy ? JSON.stringify({ version:1, rows:[{ id:'keep-note', title:'journal must ignore', content:'never replay' }],
    snapshot:{ notes:[], deleted:{ 'keep-note':999999 } } }) : '{malformed legacy journal';
  try {
    await seed(page, { legacy:legacy ? records : null, gallery:legacy ? local : null, journal, incoming });
    await guardRemovedData(context);
    await page.goto(baseURL + '/offline'); await ready(page);
    assert.equal(await page.locator(removed).count(), 0);
    assert.equal(await page.locator('.offline-nav-item.active').getAttribute('data-panel'), 'graph');
    assert.equal(await page.locator('#offlineDrawingHost .dmate-drawing-workspace').count(), 0,
      'The graph default leaves drawing lazily mounted');
    await page.locator('.offline-nav-item[data-panel="drawing"]').click();
    await page.locator('#offlineDrawingHost .dmate-drawing-workspace').waitFor();
    let value = await readState(page);
    assert.deepEqual(value.accesses, [], 'The app neither reads nor writes removed stores/journals');
    assert.equal(value.journal, journal, 'Legacy journal bytes remain untouched');
    assert.equal(value.version, 2);
    assert.deepEqual(value.stores, legacy ? ['mistakes','notes','practice','settings'] : ['practice','settings']);
    if (legacy) {
      assert.deepEqual(value.records.notes, records.notes);
      assert.deepEqual(value.records.mistakes, records.mistakes);
      assert.deepEqual(value.records.practice, records.practice);
      assert.deepEqual(value.records.settings.find(row => row.id === 'notebook-deletions'), records.settings[0]);
      assert.deepEqual(value.gallery.custom, local.custom, 'Unknown gallery metadata survives migration and opening the drawing module');
      assert.equal(value.gallery.activeId, 'local-active');
      assert.deepEqual(value.gallery.pages.map(row => row.id), ['shared','local-active','incoming-only']);
      assert.equal(value.gallery.pages[0].name, 'Shared local', 'Local content wins even when incoming timestamps are newer');
      for (const original of local.pages) {
        const row = value.gallery.pages.find(item => item.id === original.id);
        assert.deepEqual(row.custom, original.custom);
        assert.equal(row.document.body_text, original.document.body_text);
        assert.equal(row.document.graphs[0].vertices[0].label, original.document.graphs[0].vertices[0].label);
      }
      assert.deepEqual(value.gallery.pages[2].custom, incomingGallery.pages[1].custom);
      assert.equal(await page.locator('#offlineDrawingHost .ddw-name').inputValue(), 'Local active');
      await page.locator('#offlineDrawingHost .ddw-name').fill('Local active edited');
      await page.waitForFunction(key => JSON.parse(localStorage.getItem(key)).pages.some(row => row.id === 'local-active' && row.name === 'Local active edited'), galleryKey);
    } else {
      assert.deepEqual(value.gallery.pages.map(row => row.id), ['shared','incoming-only']);
      assert.equal(value.gallery.activeId, incomingGallery.activeId);
      assert.deepEqual(value.gallery.custom, incomingGallery.custom);
    }
    // Re-import the same page IDs and use a corrupt journal on the next load.
    await page.evaluate(({ incoming, migrationKey, journalKey }) => {
      sessionStorage.setItem(migrationKey, JSON.stringify(incoming));
      window.removedDataNative.setItem.call(localStorage, journalKey, '{broken journal after reload');
    }, { incoming, migrationKey, journalKey });
    await page.reload(); await ready(page);
    assert.equal(await page.locator('.offline-nav-item.active').getAttribute('data-panel'), 'graph');
    await page.locator('.offline-nav-item[data-panel="drawing"]').click();
    await page.locator('#offlineDrawingHost .dmate-drawing-workspace').waitFor();
    value = await readState(page);
    assert.deepEqual(value.accesses, []);
    assert.equal(value.journal, '{broken journal after reload');
    assert.deepEqual(value.gallery.pages.map(row => row.id), legacy ? ['shared','local-active','incoming-only'] : ['shared','incoming-only']);
    if (legacy) {
      assert.deepEqual(value.records.notes, records.notes);
      assert.deepEqual(value.records.mistakes, records.mistakes);
      assert.deepEqual(value.records.settings.find(row => row.id === 'notebook-deletions'), records.settings[0]);
      assert.deepEqual(value.gallery.custom, local.custom);
      assert.equal(value.gallery.activeId, 'local-active');
      assert.equal(await page.locator('#offlineDrawingHost .ddw-name').inputValue(), 'Local active edited');
    }
    assert.deepEqual(errors, []); assert.deepEqual(apiRequests, []);
    console.log('PASS ' + (legacy ? 'legacy v2' : 'fresh v2') + ': four-module init, ignored legacy payload/journals, drawing union/local precedence/metadata and refresh');
  } finally { await context.close(); }
}

async function verifyBridge(browser) {
  const context = await browser.newContext({ serviceWorkers:'block' }), page = await context.newPage();
  try {
    await page.goto(baseURL + '/', { waitUntil:'networkidle' });
    const value = await page.evaluate(async document => {
      if (accountState.authenticated) throw new Error('Snapshot fixture requires the anonymous test context');
      standaloneDrawingOwner = 'guest'; standaloneDrawingSessionState = {}; standaloneDrawing = document;
      const first = await DMateOfflineBridge.snapshot(), second = await DMateOfflineBridge.snapshot();
      const schema = await new Promise((resolve, reject) => {
        const request = indexedDB.open('dmate-offline-workspace',2);
        request.onerror = () => reject(request.error);
        request.onsuccess = () => { const db=request.result; resolve([...db.objectStoreNames]); db.close(); };
      });
      return { first, second, schema };
    }, documentFor('Legacy original'));
    assert.deepEqual(Object.keys(value.first).sort(), ['drawings','username']);
    assert.equal(value.first.username, '');
    assert.equal(value.first.drawings.length, 1);
    assert.equal(value.first.drawings[0].id, 'legacy-local');
    assert.deepEqual(value.first.drawings[0].document, documentFor('Legacy original'));
    assert.equal(value.second.drawings[0].id, 'legacy-local', 'Repeated legacy snapshots have a stable import identity');
    assert.deepEqual(value.schema, ['practice','settings']);
    console.log('PASS real online bridge: drawing-only snapshot, stable legacy ID and minimal v2 stores');
  } finally { await context.close(); }
}

async function verifyEntry(browser, kind) {
  const context = await browser.newContext({ serviceWorkers:'block' });
  const username = 'entry-user', pages = [drawing('entry-page','Entry page','entry',1)];
  const source = { version:2, activeId:'entry-page', custom:{ retained:true }, pages };
  await context.route('**/__offline-entry-test', route => route.fulfill({ contentType:'text/html', body:
    '<!doctype html><html data-account-authenticated="' + (kind === 'guest' ? '0' : '1') + '" data-account-username="entry-user"><body>'
    + '<button id="offlineWorkspaceBtn"><span class="dmate-ui-label">离线版</span></button><script src="/static/offline-entry.js"></script></body></html>' }));
  await context.route('**/offline', route => route.fulfill({ contentType:'text/html', body:'<!doctype html><title>Captured handoff</title>' }));
  await context.addInitScript(({ kind, username, source, pages, document }) => {
    if (location.pathname !== '/__offline-entry-test') return;
    localStorage.setItem('dmate:graph-drawing:v1:owner', 'account:' + username);
    localStorage.setItem('dmate:graph-drawing:v1', JSON.stringify(document));
    if (kind !== 'legacy') localStorage.setItem('dmate:graph-gallery:v1::' + encodeURIComponent('account:' + username), JSON.stringify(source));
    const get = Storage.prototype.getItem;
    Storage.prototype.getItem = function(key) {
      if (key === 'discrete_math_ai_learning_v1' || key === 'dmate:offline:notebook-journal:v1') throw new Error('Entry read removed learning data');
      return get.call(this,key);
    };
    if (kind === 'bridge') window.DMateOfflineBridge = { snapshot:async () => {
      const value = { username, drawings:pages };
      for (const key of ['notes','wrongQuestions']) Object.defineProperty(value,key,{ get(){ throw new Error('Entry read ' + key); } });
      return value;
    } };
  }, { kind, username, source, pages, document:documentFor('Entry legacy') });
  const page = await context.newPage();
  try {
    await page.goto(baseURL + '/__offline-entry-test');
    await page.locator('#offlineWorkspaceBtn').click(); await page.waitForURL(baseURL + '/offline');
    const payload = await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)), migrationKey);
    assert.deepEqual(Object.keys(payload).sort(), ['drawings','username']);
    assert.equal(payload.username, kind === 'guest' ? '' : username);
    if (kind === 'guest') assert.equal(payload.drawings, '', 'Stale account markers cannot import another account gallery');
    else if (kind === 'gallery') assert.deepEqual(JSON.parse(payload.drawings), source);
    else {
      const gallery = JSON.parse(payload.drawings);
      assert.equal(gallery.pages.length,1);
      assert.equal(gallery.pages[0].id, kind === 'legacy' ? 'legacy-local' : 'entry-page');
      assert.deepEqual(gallery.pages[0].document, kind === 'legacy' ? documentFor('Entry legacy') : pages[0].document);
    }
    console.log('PASS entry ' + kind + ': username/drawings only, no removed learning data access');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless:true, ...(executablePath ? { executablePath } : {}) });
  try {
    for (const legacy of [false,true]) await verifyOfflineMigration(browser,legacy);
    await verifyBridge(browser);
    for (const kind of ['bridge','gallery','legacy','guest']) await verifyEntry(browser,kind);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
