/* Account dialogs use app chrome; every authentication write is intercepted. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';

async function fixture(browser, width) {
  const context = await browser.newContext({ viewport:{ width, height:950 }, serviceWorkers:'block' });
  const page = await context.newPage();
  const server = { commands:[], mode:'wrong-password', held:null, errors:[], nativeDialogs:[] };
  const reply = (route, status, data) => route.fulfill({ status, contentType:'application/json', body:JSON.stringify(data) });
  page.on('pageerror', error => server.errors.push(error.message));
  page.on('dialog', dialog => { server.nativeDialogs.push(dialog.type()); void dialog.dismiss(); });
  await page.route('**/auth/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/auth/me') return reply(route, 200, { configured:true, authenticated:false });
    server.commands.push(path);
    if (server.mode === 'hold') { server.held = route; server.heldReady?.(); return; }
    return reply(route, 401, { error:'密码不正确。' });
  });
  await page.route(/\/sync(?:\?|$)/, route => reply(route, 503, { error:'暂时不可用' }));
  for (const path of ['**/chat', '**/conversation/title', '**/analyze-questions', '**/notebook/analyze'])
    await page.route(path, route => route.abort());
  await page.goto(baseURL, { waitUntil:'networkidle' });
  await page.waitForFunction(() => accountState.configured === true && !accountVerificationOperation);
  return { page, context, server, reply };
}

async function seedAccount(page, owner = 'account-a') {
  await page.evaluate(owner => {
    stopCloudLivePolling(); bumpCloudSyncContext();
    accountState = { ...accountState, configured:true, emailConfigured:true, authenticated:true,
      username:owner, email:'person@example.test', hasRecoveryCode:true, syncing:false, status:'', revision:4 };
    writeCloudSyncMeta({ username:owner, revision:4, dirty:false });
    renderAccountUi(); openAccountModal();
  }, owner);
}

async function panels(page) {
  const entries = [
    ['#accountEmailBindOpen', '#accountEmailBindPanel', ['#accountEmailBindPassword', '#accountEmailBindCode']],
    ['#accountRecoveryCodeOpen', '#accountRecoveryCodePanel', ['#accountRecoveryCurrentPassword', '#accountRecoveryNewCode', '#accountRecoveryNewCodeConfirm']],
    ['#accountDeleteOpen', '#accountDeletePanel', ['#accountDeletePassword']]
  ];
  for (const [trigger, panel, fields] of [...entries, entries[0], entries[2], entries[1]]) {
    await page.locator(trigger).click();
    for (const [, candidate, secrets] of entries) {
      assert.equal(await page.locator(candidate).isVisible(), candidate === panel, 'Only the requested account panel is visible');
      if (candidate !== panel) for (const field of secrets) assert.equal(await page.locator(field).inputValue(), '', 'Hidden panel credentials are cleared');
    }
    for (const field of fields) await page.locator(field).fill('12345678');
  }
}

async function typographyAndCopy(page, width) {
  const raw = '3.14。\nhttps://example.test/a.b。\n登录。';
  for (const theme of ['dark', 'light', 'navy']) for (const language of ['zh-CN', 'en']) for (const scale of [1, 1.2]) {
    await page.evaluate(({ theme, language, scale }) => {
      appearanceSettings.mode = theme; applyAppearanceSettings({ save:false });
      document.documentElement.style.setProperty('--font-scale', String(scale));
      DMateI18n.setLanguage(language, false);
      setAccountRecoveryCodePanel(true);
      DMateModalText.refresh(document.getElementById('accountModal'));
    }, { theme, language, scale });
    const fonts = await page.evaluate(() => {
      const paint = node => Object.fromEntries(['fontFamily', 'fontSize', 'fontWeight', 'lineHeight']
        .map(key => [key, getComputedStyle(node)[key]]));
      return { title:paint(document.getElementById('appConfirmTitle')), body:paint(document.getElementById('appConfirmBody')),
        titles:[...document.querySelectorAll('#accountModal .account-panel-title,#accountModal .account-delete-title,#accountModal .account-field > span')].map(paint),
        bodies:[...document.querySelectorAll('#accountModal .account-panel-copy,#accountModal .account-delete-copy,#accountModal .account-message')].map(paint) };
    });
    for (const value of fonts.titles) assert.deepEqual(value, fonts.title, 'Account title/labels match the confirmation title at ' + [width, theme, language, scale]);
    for (const value of fonts.bodies) assert.deepEqual(value, fonts.body, 'Account instructions match the confirmation body at ' + [width, theme, language, scale]);
    const copy = await page.locator('#accountRecoveryCodePanel .account-panel-copy').innerText();
    assert.ok(!/[。]|\.(?:\s|$)/.test(copy), 'Account UI copy has no sentence full stops');
    assert.equal(/[A-Za-z]/.test(copy), language === 'en', 'Instructions still switch languages after punctuation formatting');
  }
  await page.evaluate(raw => {
    window.modalChromeResult = null;
    void showAppConfirm({ title:'删除这段对话？', body:'这是提示。下一句。', content:raw })
      .then(value => { window.modalChromeResult = value; });
  }, raw);
  assert.equal(await page.locator('#appConfirmBody [data-i18n-content]').innerText(), raw);
  for (const language of ['zh-CN', 'en', 'zh-CN']) {
    await page.evaluate(language => DMateI18n.setLanguage(language, false), language);
    assert.equal(await page.locator('#appConfirmBody [data-i18n-content]').innerText(), raw, 'User excerpts retain math, links and punctuation through language changes');
  }
  await page.locator('#appConfirmClose').click();
  assert.equal(await page.evaluate(() => modalChromeResult), false);
  await page.evaluate(raw => {
    void DMateDeleteConfirm.request(document.body, { title:'确认删除？', body:'删除后无法恢复。\n' + raw, content:raw });
  }, raw);
  await page.locator('.dmate-delete-confirm[open]').waitFor();
  const native = await page.evaluate(() => {
    const paint = node => Object.fromEntries(['fontFamily', 'fontSize', 'fontWeight', 'lineHeight']
      .map(key => [key, getComputedStyle(node)[key]]));
    return { title:paint(document.getElementById('appConfirmTitle')), body:paint(document.getElementById('appConfirmBody')),
      nativeTitle:paint(document.querySelector('.dmate-delete-confirm-title')), nativeBody:paint(document.querySelector('.dmate-delete-confirm-body')) };
  });
  assert.deepEqual(native.nativeTitle, native.title); assert.deepEqual(native.nativeBody, native.body);
  for (const language of ['en', 'zh-CN']) {
    await page.evaluate(language => DMateI18n.setLanguage(language, false), language);
    assert.equal(await page.locator('.dmate-delete-confirm-content').innerText(), raw);
    assert.equal(await page.evaluate(() => document.querySelector('.dmate-delete-confirm-body').firstChild.nodeValue.trim()),
      language === 'en' ? 'This cannot be undone' : '删除后无法恢复');
  }
  await page.locator('.dmate-delete-confirm-close').click();
  const formatted = await page.evaluate(() => ({
    english:DMateModalText.instruction('First sentence. Next sentence.'),
    chinese:DMateModalText.instruction('第一句。第二句。'),
    data:DMateModalText.instruction('3.14 v1.2.3 diagram.png https://example.test/a.b user@example.test ...')
  }));
  assert.equal(formatted.english, 'First sentence; Next sentence');
  assert.equal(formatted.chinese, '第一句；第二句');
  assert.equal(formatted.data, '3.14 v1.2.3 diagram.png https://example.test/a.b user@example.test ...');
}

async function confirmations(page, server, reply) {
  await seedAccount(page);
  await page.locator('#accountDeleteOpen').click(); await page.locator('#accountDeletePassword').fill('password-123');
  await page.locator('#accountDeleteConfirm').click();
  await page.locator('#appConfirmModal').waitFor({ state:'visible' });
  await page.locator('#appConfirmClose').click();
  assert.deepEqual(server.commands, [], 'Cancel never calls account deletion');
  await page.locator('#accountDeleteConfirm').click(); await page.locator('#appConfirmConfirm').click();
  await page.waitForFunction(() => !accountState.syncing);
  assert.equal(await page.evaluate(() => accountState.authenticated), true, 'A wrong-password 401 retains the active account');
  assert.equal(await page.locator('#accountDeleteMessage').innerText(), '密码不正确');
  assert.deepEqual(server.commands, ['/auth/delete-account']);

  await page.locator('#accountDeleteConfirm').click();
  await page.locator('#appConfirmModal').waitFor({ state:'visible' });
  await seedAccount(page, 'account-b');
  await page.locator('#appConfirmConfirm').click();
  assert.equal(server.commands.length, 1, 'A confirmation from a previous owner cannot delete the new account');

  await seedAccount(page);
  await page.locator('#accountDeleteOpen').click(); await page.locator('#accountDeletePassword').fill('password-123');
  server.mode = 'hold';
  const heldReady = new Promise(resolve => { server.heldReady = resolve; });
  await page.evaluate(() => { window.accountDeleteOperation = deleteAccount(); });
  await page.locator('#appConfirmConfirm').click();
  await heldReady;
  assert.ok(server.held, 'The mocked delete request is pending');
  await seedAccount(page, 'account-b');
  await reply(server.held, 200, { ok:true }); server.held = null;
  await page.evaluate(() => window.accountDeleteOperation);
  assert.equal(await page.evaluate(() => accountState.username), 'account-b', 'An old success response cannot clear a new owner');

  await seedAccount(page);
  server.mode = 'wrong-password';
  await page.evaluate(() => { writeCloudSyncMeta({ username:accountState.username, revision:4, dirty:true }); void logoutAccount(); });
  await page.locator('#appConfirmModal').waitFor({ state:'visible' });
  assert.equal(await page.locator('#appConfirmTitle').innerText(), '仍然退出登录？');
  await page.locator('#appConfirmClose').click();
  assert.ok(!server.commands.includes('/auth/logout'), 'Canceling the unsynced warning leaves the account signed in');
  await page.evaluate(() => { void logoutAccount(); });
  await page.locator('#appConfirmModal').waitFor({ state:'visible' });
  await seedAccount(page, 'account-b');
  await page.locator('#appConfirmConfirm').click();
  assert.ok(!server.commands.includes('/auth/logout'), 'An old unsynced warning cannot sign out a new owner');
}

(async () => {
  const browser = await chromium.launch({ executablePath:process.env.CHROMIUM_EXECUTABLE_PATH || process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || '/usr/bin/chromium', headless:true, args:['--no-sandbox'] });
  try {
    for (const width of [390, 1440]) {
      const { page, context, server, reply } = await fixture(browser, width);
      try {
        await seedAccount(page); await panels(page); await typographyAndCopy(page, width);
        await confirmations(page, server, reply);
        assert.deepEqual(server.nativeDialogs, [], 'Account actions use the shared app modal');
        assert.deepEqual(server.errors, []);
        console.log('PASS ' + width + ': exclusive panels, dialog fonts, punctuation/content boundaries and guarded mocked confirmations');
      } finally { await context.close(); }
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
