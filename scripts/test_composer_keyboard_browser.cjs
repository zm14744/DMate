'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

async function run(browser, width) {
  const page = await browser.newPage({ viewport:{ width, height:900 },
    ...(width <= 820 ? { isMobile:true, hasTouch:true } : {}) });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.setContent('<div class="input"><textarea id="draft" enterkeyhint="send" style="font-size:16px;line-height:24px;min-height:40px"></textarea></div>');
    await page.addScriptTag({ path:path.resolve(__dirname, '../static/chat-composer.js') });
    await page.evaluate(() => {
      window.sentDrafts = [];
      const input = document.getElementById('draft');
      window.keyboardComposer = DMateChatComposer.mount({ input, onSend:() => sentDrafts.push(input.value) });
    });
    const input = page.locator('#draft');
    await input.fill('发送这条消息');
    await input.press('Enter');
    assert.deepEqual(await page.evaluate(() => sentDrafts), ['发送这条消息'], 'Enter submits on this device');
    assert.equal(await input.inputValue(), '发送这条消息', 'Enter does not insert a newline');

    await input.fill('第一行');
    await input.press('Shift+Enter');
    await input.press('x');
    assert.equal(await input.inputValue(), '第一行\nx', 'Shift+Enter retains native multiline editing');
    assert.equal(await page.evaluate(() => sentDrafts.length), 1);
    for (const key of ['Control+Enter','Alt+Enter','Meta+Enter']) await input.press(key);
    assert.equal(await page.evaluate(() => sentDrafts.length), 1, 'Modified Enter does not submit');

    await page.evaluate(() => {
      const input = document.getElementById('draft');
      input.dispatchEvent(new CompositionEvent('compositionstart', { bubbles:true }));
      input.dispatchEvent(new KeyboardEvent('keydown', { key:'Enter', keyCode:229, isComposing:true, bubbles:true, cancelable:true }));
      input.dispatchEvent(new CompositionEvent('compositionend', { bubbles:true, data:'中文' }));
      input.dispatchEvent(new KeyboardEvent('keydown', { key:'Enter', keyCode:13, bubbles:true, cancelable:true }));
    });
    assert.equal(await page.evaluate(() => sentDrafts.length), 1, 'IME confirmation and its immediate follow-up do not submit');
    await page.waitForTimeout(60);
    await input.press('Enter');
    assert.equal(await page.evaluate(() => sentDrafts.length), 2, 'A separate Enter after composition submits');

    await page.evaluate(() => {
      const input = document.getElementById('draft');
      const enter = () => input.dispatchEvent(new KeyboardEvent('keydown', { key:'Enter', bubbles:true, cancelable:true }));
      input.disabled = true; enter(); input.disabled = false;
      input.readOnly = true; enter(); input.readOnly = false;
    });
    assert.equal(await page.evaluate(() => sentDrafts.length), 2, 'Disabled and read-only drafts never submit');
    await page.evaluate(() => keyboardComposer.destroy());
    await input.press('Enter');
    assert.equal(await page.evaluate(() => sentDrafts.length), 2, 'Destroyed composers remove their Enter listener');
    assert.deepEqual(errors, []);
    console.log('PASS ' + width + ': Enter submits, Shift+Enter edits multiline, IME and modifiers stay safe');
  } finally { await page.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless:true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath:process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try { for (const width of [390,820,1440]) await run(browser,width); }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
