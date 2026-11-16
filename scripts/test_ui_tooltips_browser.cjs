/* Shared hints on the real file picker, above available controls, and deliberate
 * keyboard navigation; OS capture/restore and modal autofocus stay quiet. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function hidden(page, label) {
  await sleep(420);
  assert.equal(await page.locator('.dm-ui-tooltip:visible').count(), 0, label);
}

async function hint(page, target, label, above = true) {
  await target.hover();
  const popup = page.locator('.dm-ui-tooltip:visible');
  await popup.waitFor();
  assert.equal(await popup.innerText(), label);
  const box = await popup.boundingBox();
  const anchor = await target.boundingBox();
  if (above) assert.ok(box.y + box.height <= anchor.y - 6,
    'A hint with room above its control belongs above it: ' + JSON.stringify({box, anchor}));
  assert.ok(box.x >= 10 && box.y >= 10 && box.x + box.width <= page.viewportSize().width - 10,
    'The tooltip stays inside the viewport');
  assert.equal(await popup.evaluate(node => getComputedStyle(node).borderWidth), '0px');
  return popup;
}

async function test(browser, width) {
  const context = await browser.newContext({viewport:{width, height:900}, serviceWorkers:'block'});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/auth/me', route => route.fulfill({contentType:'application/json', body:'{"configured":true,"authenticated":false}'}));
  await page.route('**/conversation/title', route => route.abort());
  try {
    await page.goto(baseURL, {waitUntil:'networkidle'});
    await page.waitForFunction(() => typeof openLearningReview === 'function');
    // Real pointer hit testing lands on the transparent mounted file input,
    // not the plus icon underneath it. Keep that real picker intact.
    const file = page.locator('#imageInput');
    const originalButtonTitle = await page.locator('#imageBtn').getAttribute('title');
    await hint(page, file, originalButtonTitle);
    assert.equal(await file.getAttribute('title'), '', 'Native file-name hint is suppressed');
    assert.equal(await page.locator('#imageBtn').getAttribute('title'), '', 'Native button hint is suppressed too');
    const chooserEvent = page.waitForEvent('filechooser');
    await file.click();
    const chooser = await chooserEvent;
    assert.equal(await chooser.element().getAttribute('id'), 'imageInput');
    assert.equal(chooser.isMultiple(), true);
    await chooser.setFiles([]);
    await page.locator('#text').focus();
    await page.mouse.move(2, 2);
    await hidden(page, 'Picker close and pointer leave hide the shared hint');

    await page.evaluate(() => {
      sessions = [{id:'tooltip-title', name:'集合运算与德摩根律', nameSource:'user', messages:[]}];
      currentId = 'tooltip-title'; renderAll();
    });
    const sidebarButton = page.locator(width <= 1100 ? '#mobileNavBtn' : '#desktopSidebarOpen');
    await sidebarButton.click();
    await page.waitForFunction(() => innerWidth <= 1100 ? document.body.classList.contains('mobile-left-open')
      : document.documentElement.dataset.desktopSidebar === 'expanded');
    await page.evaluate(async () => Promise.all(document.getAnimations().filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity)
      .map(animation => animation.finished.catch(() => {}))));
    const name = page.locator('#sessions [data-session-name]');
    await hint(page, name, '集合运算与德摩根律');
    assert.equal(await name.getAttribute('title'), '', 'Conversation name uses shared rather than native tooltip');
    await page.locator(width <= 1100 ? '#mobileNavClose' : '#desktopSidebarToggle').click();
    await page.mouse.move(2, 2);

    // PrintScreen can switch Chromium into keyboard modality. Opening this real
    // modal focuses its red close button, which must not advertise itself.
    await page.keyboard.press('PrintScreen');
    await page.evaluate(() => openLearningReview());
    const close = page.locator('#learningReviewClose');
    await close.waitFor();
    assert.equal(await close.evaluate(node => node === document.activeElement), true);
    await hidden(page, 'Modal autofocus after screenshot keys has no unsolicited close hint');
    await hint(page, close, '关闭', false);
    await page.keyboard.press('PrintScreen');
    await hidden(page, 'PrintScreen dismisses an already visible close hint');
    await page.evaluate(() => {
      window.dispatchEvent(new Event('blur'));
      window.dispatchEvent(new Event('focus'));
      const button = document.getElementById('learningReviewClose');
      button.blur(); button.focus();
      const rect = button.getBoundingClientRect();
      button.dispatchEvent(new PointerEvent('pointerover', {bubbles:true, pointerType:'mouse',
        clientX:rect.x + rect.width/2, clientY:rect.y + rect.height/2}));
    });
    await hidden(page, 'OS focus restoration and synthetic pointer entry stay quiet');
    const rect = await close.boundingBox();
    await page.mouse.move(rect.x + rect.width/2 + 2, rect.y + rect.height/2);
    await page.locator('.dm-ui-tooltip:visible').waitFor();
    await page.keyboard.press('Meta+Shift+s');
    await hidden(page, 'Screenshot modifier shortcut dismisses the hint');
    await page.evaluate(() => closeLearningReview());

    // Actual Tab navigation still exposes the focused icon's accessible hint.
    await page.evaluate(() => {
      const dialog = document.createElement('dialog'); dialog.id = 'tooltip-test-dialog';
      dialog.style.cssText = 'position:fixed;inset:200px auto auto 24px;margin:0;width:280px;transform:scale(.9);overflow:visible';
      dialog.innerHTML = '<button title="第一个">甲</button><button title="第二个">乙</button>';
      document.body.append(dialog); dialog.showModal();
    });
    await hidden(page, 'Native dialog autofocus is quiet too');
    await page.keyboard.press('Tab');
    const popup = page.locator('.dm-ui-tooltip:visible');
    await popup.waitFor();
    assert.equal(await popup.innerText(), '第二个', 'Real Tab navigation gets a focus hint');
    assert.equal(await popup.evaluate(node => node.parentElement.id), 'tooltip-test-dialog', 'Tooltip remains in the native dialog top layer');
    const focusedBox = await page.locator('#tooltip-test-dialog button').nth(1).boundingBox();
    const popupBox = await popup.boundingBox();
    assert.ok(popupBox.y + popupBox.height <= focusedBox.y - 6, 'Scaled native dialogs still place hints above');
    await page.evaluate(() => document.getElementById('tooltip-test-dialog').remove());
    await page.mouse.move(2, 2);
    await hidden(page, 'Closing the dialog removes its hint');
    await page.evaluate(() => {
      const content = document.createElement('div'); content.className = 'ai-content';
      content.style.cssText = 'position:fixed;top:300px;left:24px;z-index:9999999';
      content.innerHTML = '<button id="tooltip-protected-content" title="正文里的原始标题">用户内容</button>';
      document.body.append(content);
    });
    await page.locator('#tooltip-protected-content').hover();
    await hidden(page, 'Protected answer content is not turned into an interface tooltip');
    assert.equal(await page.locator('#tooltip-protected-content').getAttribute('title'), '正文里的原始标题');
    assert.deepEqual(errors, []);
    console.log('PASS ' + width + ': native plus picker, above placement, screenshot/autofocus suppression, real keyboard focus, scaled dialog and protected content');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({headless:true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? {executablePath:process.env.CHROMIUM_EXECUTABLE_PATH} : {})});
  try { for (const width of [1440,390]) await test(browser, width); }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
