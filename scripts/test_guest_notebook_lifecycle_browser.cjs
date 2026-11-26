/* Guest notes survive refresh within their tab; authentication expiry revokes the
 * live workspace without destroying its verified owner's recoverable cache. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const learningKey = 'discrete_math_ai_learning_v1';
const metaKey = 'discrete_math_ai_cloud_sync_v1';
const note = (owner, text = owner + ' private notes') => ({ id:'note-' + owner, title:owner + ' concept',
  content:text, createdAt:1000, updatedAt:1001 });

async function fixture(browser, width = 1440, delayedGuest = false) {
  const context = await browser.newContext({ viewport:{ width, height:900 }, serviceWorkers:'block' });
  const page = await context.newPage();
  const server = { owner:'', mode:'ok', authStatus:200, revision:4, uploads:[], held:null, authHeld:null, errors:[] };
  page.on('pageerror', error => server.errors.push(error.message));
  const reply = (route, status, value) => route.fulfill({ status, contentType:'application/json', body:JSON.stringify(value) });
  await page.route('**/auth/me', route => {
    if (delayedGuest && !server.authHeld) { server.authHeld = route; return; }
    if (server.authStatus === 401) return reply(route, 401, { error:'请先登录' });
    return reply(route, 200, { ok:true, configured:true, authenticated:Boolean(server.owner),
      ...(server.owner ? { user:{ username:server.owner, email:'' } } : {}) });
  });
  await page.route('**/auth/logout', route => { server.owner = ''; return reply(route, 200, { ok:true }); });
  await page.route('**/auth/email/bind', route => reply(route, 401, { ok:false, error:'密码不正确' }));
  await page.route(/\/sync(?:\?|$)/, route => {
    if (server.mode === 'hold') { server.held = route; return; }
    if (server.mode === 'expired') return reply(route, 401, { ok:false, error:'请先登录' });
    if (server.mode === 'temporary') return reply(route, 503, { ok:false, error:'暂时不可用' });
    if (route.request().method() === 'PUT') {
      const payload = route.request().postDataJSON(); server.uploads.push(payload);
      server.revision = Math.max(server.revision, payload.baseRevision || 0) + 1;
      return reply(route, 200, { ok:true, revision:server.revision });
    }
    return reply(route, 200, { ok:true, revision:server.revision, data:{
      sessions:{ sessions:[], currentId:null, deletedSessionIds:{} },
      learning:{ conceptNotebook:{ notes:[note(server.owner || 'account-a')], deleted:{} } }
    } });
  });
  for (const path of ['**/chat', '**/notebook/analyze', '**/conversation/title', '**/analyze-questions'])
    await page.route(path, route => route.abort());
  await page.goto(baseURL, { waitUntil:delayedGuest ? 'domcontentloaded' : 'networkidle' });
  await page.waitForFunction(() => Boolean(window.dmateConceptNotebook));
  if (!delayedGuest) await page.waitForFunction(() => accountState.configured === true && !accountVerificationOperation);
  return { page, context, server, reply };
}

async function stopTimers(page) {
  await page.evaluate(() => { stopCloudLivePolling(); if (cloudSyncTimer) clearTimeout(cloudSyncTimer); cloudSyncTimer = 0; });
}

async function seedVerifiedAccount(page, owner = 'account-a') {
  await page.evaluate(({ owner, record }) => {
    stopCloudLivePolling(); bumpCloudSyncContext();
    accountState = { ...accountState, configured:true, authenticated:true, username:owner,
      revision:4, syncing:false, status:'' };
    sessions = []; currentId = null;
    learningState = createEmptyLearningState();
    setConceptNotebookState({ notes:[record], deleted:{} });
    if (cloudSyncTimer) clearTimeout(cloudSyncTimer); cloudSyncTimer = 0;
    writeCloudSyncMeta({ username:owner, revision:4, dirty:true });
    window.dmateConceptNotebook.refresh(); renderAccountUi();
  }, { owner, record:note(owner) });
}

async function state(page) {
  return page.evaluate(({ learningKey, metaKey }) => ({ authenticated:accountState.authenticated,
    persistent:shouldPersistClientState(), notes:learningState.conceptNotebook.notes,
    editorNotes:window.dmateConceptNotebook.getState().notes,
    cache:localStorage.getItem(learningKey), meta:JSON.parse(localStorage.getItem(metaKey) || 'null') }),
  { learningKey, metaKey });
}

async function guestPageLifecycle(browser, width) {
  const { page, context, server, reply } = await fixture(browser, width, true);
  try {
    await page.evaluate(() => window.dmateConceptNotebook.open());
    await page.locator('.dcn-new').click();
    await page.locator('.dcn-title').fill('This page only');
    await page.locator('.dcn-original').fill('Guest concept content');
    await page.waitForFunction(() => accountVerificationOperation != null);
    await reply(server.authHeld, 200, { configured:true, authenticated:false });
    await page.waitForFunction(() => !accountVerificationOperation);
    assert.equal((await state(page)).notes.length, 1, 'A delayed guest verification does not erase current-page edits');
    assert.equal((await state(page)).cache, null, 'Guest edits never enter account learning storage');
    if (width <= 760 && await page.locator('.dcn-mobile-sheet').isVisible()) await page.locator('.dcn-sheet-close').click();
    await page.locator('.dcn-heading .dcn-close').click();
    await page.evaluate(() => window.dmateConceptNotebook.open());
    if (width <= 760) await page.locator('.dcn-note-open').click();
    assert.equal(await page.locator('.dcn-title').inputValue(), 'This page only', 'Closing a modal does not end the page session');
    await page.evaluate(({ learningKey, metaKey, record }) => {
      localStorage.setItem(learningKey, JSON.stringify({ conceptNotebook:{ notes:[record], deleted:{} } }));
      localStorage.setItem(metaKey, JSON.stringify({ username:'old-account', revision:4, dirty:true }));
    }, { learningKey, metaKey, record:note('old-account') });
    await page.reload({ waitUntil:'networkidle' });
    await page.waitForFunction(() => !accountVerificationOperation);
    assert.equal((await state(page)).notes.length, 1, 'A guest reload restores this tab\'s notebook');
    assert.equal((await state(page)).cache, null, 'An ordinary guest bootstrap removes legacy account snapshots instead of recovering them');
    await page.evaluate(() => window.dmateConceptNotebook.open());
    assert.equal(await page.locator('.dcn-note').count(), 1);
    if (width <= 760) await page.locator('.dcn-note-open').click();
    assert.equal(await page.locator('.dcn-title').inputValue(), 'This page only');
    const another = await context.newPage();
    await another.goto(baseURL, {waitUntil:'networkidle'});
    await another.waitForFunction(() => !accountVerificationOperation);
    assert.deepEqual((await state(another)).notes, [], 'A new tab cannot restore another tab\'s notes');
    await another.close();
    assert.deepEqual(server.errors, []);
    console.log('PASS ' + width + ': delayed verification, no account writes, modal reopen, reload recovery and fresh-tab isolation');
  } finally { await context.close(); }
}

async function expiryAndRecovery(browser, width) {
  const { page, context, server } = await fixture(browser, width);
  try {
    await seedVerifiedAccount(page);
    server.owner = 'account-a'; server.mode = 'temporary';
    const before = await state(page);
    await page.evaluate(() => pushCloudSnapshot(false));
    await stopTimers(page);
    assert.equal((await state(page)).authenticated, true, 'A 503 does not log out or clear private notes');
    await page.evaluate(() => accountFetch('/auth/email/bind', { method:'POST', body:'{}' }).catch(() => {}));
    assert.equal((await state(page)).authenticated, true, 'A wrong-password 401 is not a session-expiry signal');
    server.mode = 'expired';
    await page.evaluate(() => pushCloudSnapshot(false));
    const expired = await state(page);
    assert.equal(expired.authenticated, false); assert.equal(expired.persistent, false);
    assert.deepEqual(expired.notes, []); assert.deepEqual(expired.editorNotes, []);
    assert.equal(expired.cache, before.cache, 'Expiry preserves the verified owner\'s unsynced cache');
    assert.equal(expired.meta.username, 'account-a');
    await page.evaluate(record => setConceptNotebookState({ notes:[record], deleted:{} }), note('guest', 'New guest content'));
    assert.equal((await state(page)).cache, before.cache, 'Guest edits cannot overwrite retained account data');
    server.mode = 'ok';
    await page.evaluate(() => restoreVerifiedAccountSession());
    await stopTimers(page);
    const restored = await state(page);
    assert.equal(restored.authenticated, true);
    assert.deepEqual(restored.notes.map(row => row.id), ['note-account-a'], 'Only verified matching ownership recovers its cache');
    assert.ok(server.uploads.length > 0);
    for (const upload of server.uploads) assert.ok(!JSON.stringify(upload).includes('New guest content'), 'Guest notes are not uploaded into the recovered account');
    assert.deepEqual(server.errors, []);
    console.log('PASS ' + width + ': transient/wrong-password protection, expiry clears UI, owner cache preserved and verified recovery');
  } finally { await context.close(); }
}

async function freshGuest401(browser) {
  const { page, context, server, reply } = await fixture(browser, 1440, true);
  try {
    await page.evaluate(({ learningKey, metaKey, record }) => {
      localStorage.setItem(learningKey, JSON.stringify({ conceptNotebook:{ notes:[record], deleted:{} } }));
      localStorage.setItem(metaKey, JSON.stringify({ username:'legacy-owner', revision:3, dirty:true }));
      window.dmateConceptNotebook.open();
    }, { learningKey, metaKey, record:note('legacy-owner') });
    await page.locator('.dcn-new').click();
    await page.locator('.dcn-title').fill('Guest typed before verification');
    await page.locator('.dcn-original').fill('Only this open page');
    await reply(server.authHeld, 401, { error:'请先登录' });
    await page.waitForFunction(() => !accountVerificationOperation);
    const guest = await state(page);
    assert.equal(guest.authenticated, false);
    assert.equal(guest.persistent, false);
    assert.equal(guest.cache, null, 'Initial 401 removes old account learning bytes');
    assert.equal(guest.meta, null, 'Initial 401 removes stale account ownership metadata');
    assert.equal(guest.notes.length, 1, 'Initial guest verification does not erase the live guest notebook');
    assert.equal(guest.notes[0].title, 'Guest typed before verification');
    assert.equal(await page.locator('.dcn-title').inputValue(), 'Guest typed before verification');
    assert.deepEqual(server.errors, []);
    console.log('PASS fresh guest HTTP401: legacy account cache purged while pending guest edits remain in memory');
  } finally { await context.close(); }
}

async function identityBoundaries(browser) {
  const { page, context, server, reply } = await fixture(browser);
  try {
    await seedVerifiedAccount(page);
    server.mode = 'hold';
    await page.evaluate(() => { window.pendingOldIdentity = accountFetch('/sync').catch(error => error.status); });
    const deadline = Date.now() + 5000;
    while (!server.held && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 5));
    assert.ok(server.held, 'The previous account request reaches the mocked transport');
    await seedVerifiedAccount(page, 'account-b');
    const current = await state(page);
    await reply(server.held, 401, { error:'请先登录' });
    await page.evaluate(() => window.pendingOldIdentity);
    assert.equal((await state(page)).cache, current.cache);
    assert.equal((await state(page)).authenticated, true, 'A late previous-account 401 cannot revoke the current account');

    server.mode = 'expired';
    await page.evaluate(() => accountFetch('/sync').catch(() => {}));
    server.owner = 'account-c'; server.mode = 'ok'; server.revision = 1;
    await page.evaluate(() => restoreVerifiedAccountSession());
    await stopTimers(page);
    assert.deepEqual((await state(page)).notes.map(row => row.id), ['note-account-c'], 'A different verified account never hydrates the previous owner\'s notes');

    // A successful identity response can revoke a cookie without using HTTP401.
    server.owner = '';
    await page.evaluate(() => restoreVerifiedAccountSession());
    assert.equal((await state(page)).authenticated, false);
    assert.deepEqual((await state(page)).notes, []);

    server.owner = 'account-c';
    await page.evaluate(() => restoreVerifiedAccountSession());
    await stopTimers(page);
    server.authStatus = 401;
    await page.evaluate(() => restoreVerifiedAccountSession());
    assert.equal((await state(page)).authenticated, false, 'HTTP401 from identity verification also revokes the current workspace');
    assert.deepEqual((await state(page)).notes, []);

    server.authStatus = 200;
    await page.evaluate(() => restoreVerifiedAccountSession());
    await stopTimers(page);
    await page.evaluate(() => writeCloudSyncMeta({ dirty:false }));
    const navigation = page.waitForEvent('framenavigated', frame => frame === page.mainFrame());
    await page.evaluate(() => { void logoutAccount(); });
    await navigation;
    await page.waitForLoadState('networkidle');
    await page.waitForFunction(() => !accountVerificationOperation);
    assert.equal((await state(page)).authenticated, false);
    assert.deepEqual((await state(page)).notes, []);
    assert.equal((await state(page)).cache, null, 'Explicit logout keeps its existing cache-purge behavior');
    assert.deepEqual(server.errors, []);
    console.log('PASS account boundaries: stale 401, different-owner isolation, identity expiry and explicit logout');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless:true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath:process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const width of [1440, 390]) { await guestPageLifecycle(browser, width); await expiryAndRecovery(browser, width); }
    await freshGuest401(browser);
    await identityBoundaries(browser);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
