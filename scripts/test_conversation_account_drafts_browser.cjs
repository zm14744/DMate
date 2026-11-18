/* Account drafts persist per conversation; authentication and cloud writes use fixtures. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const owners = ['account-a', 'account-b'];
const ids = ['shared-conversation-one', 'shared-conversation-two'];
const privateDrafts = ['PRIVATE ACCOUNT A FIRST DRAFT', 'PRIVATE ACCOUNT A SECOND DRAFT'];
const otherDraft = 'PRIVATE OTHER TAB EDIT';
const homeDraft = 'PRIVATE ACCOUNT HOME DRAFT';
const quotaDraft = 'PRIVATE UNSAVED DURING QUOTA';
const deletedDraft = 'PRIVATE ACCOUNT B DELETED DRAFT';
const clone = value => JSON.parse(JSON.stringify(value));

function accountSnapshot(owner) {
  return {schemaVersion:1, sessions:{currentId:null, deletedSessionIds:{}, sessions:ids.map((id, index) => ({
    id, createdAt:1700000000000 + index, name:owner + ' conversation ' + (index + 1), nameSource:'user',
    messages:[], teaching:null, learningQuestion:null, retest:null
  }))}, learning:{}};
}

async function ready(page, owner) {
  await page.waitForFunction(owner => !accountVerificationOperation && !cloudInitialSyncInFlight
    && !accountState.syncing && accountState.authenticated === Boolean(owner)
    && accountState.username === owner, owner);
  await page.evaluate(() => stopCloudLivePolling());
}

async function select(page, id) {
  if (await page.evaluate(id => currentId === id, id)) return;
  await page.locator(`.session[data-session-id="${id}"] [data-session-name]`).evaluate(node => node.click());
  await page.waitForFunction(id => currentId === id, id);
}

async function assertBlankConversations(page, reason) {
  assert.equal(await page.locator('#text').inputValue(), '', reason + ': home');
  for (const id of ids) {
    await select(page, id);
    assert.equal(await page.locator('#text').inputValue(), '', reason + ': ' + id);
  }
}

function assertNoDrafts(snapshot) {
  const encoded = JSON.stringify(snapshot);
  for (const draft of [...privateDrafts, otherDraft, homeDraft, quotaDraft, deletedDraft]) assert.ok(!encoded.includes(draft), 'Cloud data excludes unsent private text');
  assert.ok(!/conversationComposerDrafts|composer-drafts|manualQuestionMode/.test(encoded),
    'Cloud data excludes composer draft state');
}

(async () => {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'dmate-account-drafts-'));
  const launch = () => chromium.launchPersistentContext(profile, {headless:true,
    executablePath:process.env.CHROMIUM_EXECUTABLE_PATH || '/usr/bin/chromium', args:['--no-sandbox'],
    viewport:{width:1440, height:1000}, serviceWorkers:'block'});
  let context = await launch();
  const server = {owner:owners[0], accounts:new Map(owners.map(owner => [owner, {revision:4, data:accountSnapshot(owner)}])),
    uploads:[], unexpected:[], errors:[]};
  const reply = (route, status, value) => route.fulfill({status, contentType:'application/json', body:JSON.stringify(value)});
  const mock = async context => {
    context.on('page', page => page.on('pageerror', error => server.errors.push(error.message)));
    await context.route('**/*', route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (path === '/auth/me') return reply(route, 200, {ok:true, configured:true, emailConfigured:true,
      authenticated:Boolean(server.owner), ...(server.owner ? {user:{username:server.owner, email:''}} : {})});
    if (path === '/auth/login') {
      const {identifier} = request.postDataJSON();
      if (!server.accounts.has(identifier)) return reply(route, 401, {error:'Unknown fixture account'});
      server.owner = identifier;
      return reply(route, 200, {ok:true, configured:true, user:{username:identifier, email:''}});
    }
    if (path === '/auth/logout') { server.owner = ''; return reply(route, 200, {ok:true}); }
    if (path === '/sync') {
      const account = server.accounts.get(server.owner);
      if (!account) return reply(route, 401, {error:'Please sign in'});
      if (request.method() === 'PUT') {
        const payload = request.postDataJSON();
        server.uploads.push({owner:server.owner, payload});
        account.data = clone(payload.data);
        account.revision = Math.max(account.revision, payload.baseRevision || 0) + 1;
        return reply(route, 200, {ok:true, revision:account.revision});
      }
      return reply(route, 200, {ok:true, revision:account.revision, data:clone(account.data)});
    }
    if (request.method() !== 'GET' || /^\/(?:chat|ocr|analyze-questions|conversation\/title|notebook\/analyze)(?:\/|$)/.test(path)) {
      server.unexpected.push(request.method() + ' ' + path);
      return route.abort();
    }
    return route.continue();
    });
  };
  await mock(context);

  let page = await context.newPage();
  try {
    await page.goto(baseURL, {waitUntil:'networkidle'});
    await ready(page, owners[0]);
    await select(page, ids[0]);
    await page.locator('#text').fill(privateDrafts[0]);
    await page.locator('[data-manual-question="yes"]').click();
    await select(page, ids[1]);
    assert.equal(await page.locator('#text').inputValue(), '', 'A second conversation starts without the first draft');
    await page.locator('#text').fill(privateDrafts[1]);
    await select(page, ids[0]);
    assert.equal(await page.locator('#text').inputValue(), privateDrafts[0]);
    await select(page, ids[1]);
    assert.equal(await page.locator('#text').inputValue(), privateDrafts[1]);
    await page.evaluate(async () => { saveState(); await pushCloudSnapshot(false); });
    assert.ok(server.uploads.length, 'The cloud upload fixture was exercised');
    assertNoDrafts(await page.evaluate(() => collectCloudSnapshot()));
    for (const {payload} of server.uploads) assertNoDrafts(payload);

    await page.reload({waitUntil:'networkidle'});
    await ready(page, owners[0]);
    assert.equal(await page.locator('#text').inputValue(), '', 'Account reload opens its independent home composer');
    await select(page, ids[0]);
    assert.equal(await page.locator('#text').inputValue(), privateDrafts[0], 'First account draft survives refresh');
    assert.equal(await page.locator('[data-manual-question="yes"]').getAttribute('aria-pressed'), 'true');
    await select(page, ids[1]);
    assert.equal(await page.locator('#text').inputValue(), privateDrafts[1], 'Second account draft survives refresh');

    await page.evaluate(() => {
      window.accountDraftOriginalSetItem = Storage.prototype.setItem;
      Storage.prototype.setItem = function(key, value) {
        if (this === localStorage && key.startsWith('dmate_conversation_composer_drafts_account_v1:'))
          throw new DOMException('Fixture quota exhausted', 'QuotaExceededError');
        return window.accountDraftOriginalSetItem.call(this, key, value);
      };
    });
    await page.locator('#text').fill(quotaDraft);
    assert.match(await page.locator('.copy-toast').innerText(), /草稿未能保存|draft could not be saved/);
    assert.equal(await page.locator('#text').inputValue(), quotaDraft, 'A quota failure preserves the editable draft');
    assert.ok(!await page.evaluate(value => Object.values(localStorage).some(raw => raw.includes(value)), quotaDraft),
      'A failed checkpoint does not falsely claim durable storage');
    await page.evaluate(() => {
      Storage.prototype.setItem = window.accountDraftOriginalSetItem;
      delete window.accountDraftOriginalSetItem;
      checkpointGuestDrafts();
    });
    assert.ok(await page.evaluate(value => Object.values(localStorage).some(raw => raw.includes(value)), quotaDraft),
      'The pending draft retries successfully after storage is available');
    await page.locator('#text').fill(privateDrafts[1]);

    // New tabs start at home, then recover the account's durable conversation drafts.
    const popup = page.waitForEvent('popup');
    await page.evaluate(url => window.open(url, '_blank'), baseURL);
    const other = await popup;
    await other.waitForLoadState('networkidle');
    await ready(other, owners[0]);
    assert.notEqual(await other.evaluate(() => window.name), await page.evaluate(() => window.name));
    assert.equal(await other.locator('#text').inputValue(), '', 'An ordinary new tab starts at an empty home composer');
    for (let index = 0; index < ids.length; index++) {
      await select(other, ids[index]);
      assert.equal(await other.locator('#text').inputValue(), privateDrafts[index], 'Selecting a conversation recovers its durable account draft');
    }
    await select(page, ids[0]);
    await Promise.all([page.locator('#text').fill(privateDrafts[0] + ' editing'), other.locator('#text').fill(privateDrafts[1] + ' editing')]);
    await Promise.all([page.locator('#text').fill(privateDrafts[0]), other.locator('#text').fill(privateDrafts[1])]);
    const probe = await context.newPage();
    await probe.goto(baseURL, {waitUntil:'networkidle'});
    await ready(probe, owners[0]);
    for (let index = 0; index < ids.length; index++) {
      await select(probe, ids[index]);
      assert.equal(await probe.locator('#text').inputValue(), privateDrafts[index], 'Concurrent tabs saving different conversations retain both drafts');
    }
    await probe.close();
    await select(other, ids[0]);
    await other.locator('#text').fill(otherDraft);
    await select(page, ids[0]);
    assert.equal(await page.locator('#text').inputValue(), privateDrafts[0], 'Another tab cannot overwrite an existing local draft');
    await other.close();

    await page.evaluate(() => { currentId = null; renderAll(); });
    await page.locator('#text').fill(homeDraft);
    await context.close();
    context = await launch();
    await mock(context);
    page = await context.newPage();
    await page.goto(baseURL, {waitUntil:'networkidle'});
    await ready(page, owners[0]);
    assert.equal(await page.locator('#text').inputValue(), '', 'A fresh browser session does not recover a home draft');
    await select(page, ids[0]);
    assert.equal(await page.locator('#text').inputValue(), otherDraft, 'Closing and reopening the same profile recovers the last saved conversation draft');
    await select(page, ids[1]);
    assert.equal(await page.locator('#text').inputValue(), privateDrafts[1], 'Other conversation drafts survive a real browser shutdown');

    // A different verified account intentionally uses the same conversation IDs.
    server.owner = owners[1];
    await page.reload({waitUntil:'networkidle'});
    await ready(page, owners[1]);
    await assertBlankConversations(page, 'Switching the verified account does not reveal A drafts');
    server.owner = owners[0];
    await page.reload({waitUntil:'networkidle'});
    await ready(page, owners[0]);
    assert.equal(await page.locator('#text').inputValue(), '', 'Returning to account A opens home');
    await select(page, ids[0]);
    assert.equal(await page.locator('#text').inputValue(), otherDraft, 'An account can recover only its own durable conversation draft');

    await select(page, ids[0]);
    await page.locator('#text').fill(privateDrafts[0]);
    await page.waitForFunction(() => !accountState.syncing);
    const reloaded = page.waitForEvent('load');
    await page.evaluate(() => { void logoutAccount(); });
    await reloaded;
    await ready(page, '');
    assert.equal(await page.locator('#text').inputValue(), '', 'Successful logout clears the composer');
    assert.equal(await page.locator('.session[data-session-id]').count(), 0, 'Logout enters the empty guest workspace');
    const remaining = await page.evaluate(() => JSON.stringify([localStorage, sessionStorage].map(store =>
      Object.fromEntries(Object.keys(store).map(key => [key, store.getItem(key)])))));
    for (const draft of [...privateDrafts, otherDraft, homeDraft, quotaDraft]) assert.ok(!remaining.includes(draft), 'Logout removes account drafts from browser storage');

    await page.evaluate(() => openAccountModal());
    await page.locator('#accountUsername').fill(owners[1]);
    await page.locator('#accountPassword').fill('fixture-password');
    await page.locator('#accountLogin').click();
    await ready(page, owners[1]);
    await page.evaluate(() => closeAccountModal());
    await assertBlankConversations(page, 'Account B after logout cannot inherit A drafts');
    await select(page, ids[0]);
    await page.locator('#text').fill(deletedDraft);
    await page.locator(`.session[data-session-id="${ids[0]}"] .del`).evaluate(node => node.click());
    await page.locator('#appConfirmConfirm').click();
    await page.waitForFunction(id => !sessions.some(session => session.id === id), ids[0]);
    assert.ok(!await page.evaluate(value => Object.values(localStorage).some(raw => raw.includes(value)), deletedDraft),
      'Deleting a conversation removes its durable draft');
    for (const {payload} of server.uploads) assertNoDrafts(payload);
    assert.deepEqual(server.unexpected, [], 'All paid/model endpoints remain unused and intercepted');
    assert.deepEqual(server.errors, []);
    console.log('PASS account drafts: isolation, refresh, real browser reopen, private cloud payloads, new tabs, owner switch, logout and deletion');
  } finally { await context.close(); fs.rmSync(profile, {recursive:true, force:true}); }
})().catch(error => { console.error(error); process.exitCode = 1; });
