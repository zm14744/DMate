/* Start Flask first; exercises the actual mobile drawer controls without AI. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const near = (actual, expected, message, tolerance = 2) => assert.ok(Math.abs(actual - expected) <= tolerance,
  message + ': ' + actual + ' vs ' + expected);

async function openDrawer(page, kind) {
  await page.locator(kind === 'tools' ? '#mobileToolsBtn' : '#mobileNavBtn').tap();
  await page.waitForFunction(value => document.body.classList.contains(value),
    kind === 'tools' ? 'mobile-tools-open' : 'mobile-left-open');
  await page.locator(kind === 'tools' ? '#learningToolsPanel' : '#conversationSidebar').evaluate(async node => {
    await Promise.all(node.getAnimations().map(animation => animation.finished.catch(() => {})));
  });
}

async function closeDrawer(page, kind) {
  await page.locator(kind === 'tools' ? '#mobileToolsClose' : '#mobileNavClose').tap();
  await page.waitForFunction(() => !document.body.classList.contains('mobile-left-open')
    && !document.body.classList.contains('mobile-tools-open'));
}

async function checkHeader(page, sidebar) {
  const state = await page.locator(sidebar + ' > .mobile-drawer-head').evaluate(head => {
    const button = head.querySelector('button'), box = head.getBoundingClientRect(), rect = button.getBoundingClientRect();
    const style = getComputedStyle(button), walker = document.createTreeWalker(head, NodeFilter.SHOW_TEXT);
    let node, visibleText = '';
    while ((node = walker.nextNode())) {
      if (!node.textContent.trim() || node.parentElement.closest('button')) continue;
      const range = document.createRange(); range.selectNode(node);
      const bounds = range.getBoundingClientRect();
      if (bounds.width && bounds.height) visibleText += node.textContent.trim();
    }
    return { text: visibleText, width: rect.width, height: rect.height,
      rightGap: box.right - rect.right, left: rect.left, background: style.backgroundColor, radius: style.borderRadius };
  });
  assert.equal(state.text, '', sidebar + ': top row contains only its close control');
  assert.ok(state.width >= 12 && state.height >= 12, sidebar + ': close dot is visible');
  near(state.width, state.height, sidebar + ': close dot is round', .5);
  assert.ok(state.rightGap >= -1 && state.rightGap <= 8, sidebar + ': close stays at the right edge');
  const [red, green, blue] = state.background.match(/[\d.]+/g).map(Number);
  assert.ok(red > 180 && green < 120 && blue < 120, sidebar + ': close dot remains red');
}

async function checkTools(page, empty) {
  const state = await page.evaluate(() => {
    const info = document.getElementById('info'), box = info.getBoundingClientRect(), css = getComputedStyle(info);
    const range = document.createRange(); range.selectNodeContents(info);
    const text = range.getBoundingClientRect();
    const first = document.querySelector('#learningToolsPanel > .panel-heading-row').firstElementChild;
    const second = document.querySelector('#learningToolsPanel .learning-title').firstElementChild;
    const firstBox = first.getBoundingClientRect(), secondBox = second.getBoundingClientRect();
    const style = node => Object.fromEntries(['fontSize', 'fontWeight', 'fontFamily', 'color', 'lineHeight']
      .map(key => [key, getComputedStyle(node)[key]]));
    const panel = document.querySelector('#learningToolsPanel .learning-panel'), panelBox = panel.getBoundingClientRect();
    const lines = [...info.querySelectorAll('.conversation-info-line')].map(line => {
      const lineRange = document.createRange(); lineRange.selectNodeContents(line);
      return lineRange.getBoundingClientRect().left;
    });
    return { text: info.textContent.trim(), center: box.x + box.width / 2, textCenter: text.x + text.width / 2,
      centerY: box.y + box.height / 2, textCenterY: text.y + text.height / 2,
      contentLeft: box.left + info.clientLeft + parseFloat(css.paddingLeft), lines,
      infoBottom: box.bottom, separatorTop: panelBox.top, border: parseFloat(getComputedStyle(panel).borderTopWidth),
      headingTop: secondBox.top, firstLeft: firstBox.left, secondLeft: secondBox.left,
      firstStyle: style(first), secondStyle: style(second), firstText: first.textContent.trim(), secondText: second.textContent.trim(),
      secondVisible: Boolean(secondBox.width && secondBox.height) };
  });
  assert.equal(state.firstText, '对话信息');
  assert.equal(state.secondText, '学习工具');
  assert.ok(state.secondVisible, 'Learning tools section heading remains visible');
  assert.ok(state.border > 0 && state.separatorTop >= state.infoBottom, 'Section separator follows conversation information');
  assert.ok(state.headingTop > state.separatorTop + state.border, 'Learning tools heading sits below the separator');
  near(state.firstLeft, state.secondLeft, 'Section headings share the same left alignment');
  assert.deepEqual(state.secondStyle, state.firstStyle, 'Section headings use matching typography');
  if (empty) {
    assert.equal(state.text, '无');
    near(state.textCenter, state.center, 'Empty conversation information is horizontally centered');
    near(state.textCenterY, state.centerY, 'Empty conversation information is vertically centered', 3);
  } else {
    assert.ok(state.lines.length >= 2, 'New conversation produces real information lines');
    for (const left of state.lines) near(left, state.contentLeft, 'Nonempty conversation information remains left aligned');
  }
}

async function runCase(browser, width, theme) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, isMobile: true, hasTouch: true });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await page.evaluate(value => {
      document.documentElement.dataset.appearanceTheme = value;
      document.body.dataset.appearanceTheme = value;
    }, theme);
    await page.waitForFunction(() => document.getElementById('info').textContent.trim() === '无');
    await openDrawer(page, 'tools');
    await checkHeader(page, '#learningToolsPanel');
    await checkTools(page, true);
    await closeDrawer(page, 'tools');
    await openDrawer(page, 'left');
    await checkHeader(page, '#conversationSidebar');
    const button = page.locator('#newChatBtn');
    const label = await button.evaluate(node => {
      const rect = node.getBoundingClientRect(), range = document.createRange();
      range.selectNodeContents(node); const text = range.getBoundingClientRect();
      return { center: rect.x + rect.width / 2, textCenter: text.x + text.width / 2, text: node.textContent.trim() };
    });
    assert.equal(label.text, '＋ 新对话');
    near(label.textCenter, label.center, 'New conversation label is centered');
    const oldCount = await page.locator('#sessions .session').count();
    await button.tap();
    await page.waitForFunction(count => document.querySelectorAll('#sessions .session').length === count + 1, oldCount);
    await page.waitForFunction(() => !document.body.classList.contains('mobile-left-open'));
    await openDrawer(page, 'tools');
    await checkTools(page, false);
    if (process.env.MOBILE_DRAWER_SCREENSHOT_DIR) {
      await page.screenshot({ path: process.env.MOBILE_DRAWER_SCREENSHOT_DIR + '/' + width + '-' + theme + '-tools.png' });
    }
    await closeDrawer(page, 'tools');
    await openDrawer(page, 'left');
    assert.equal(await page.locator('#sessions .session.active').count(), 1);
    if (process.env.MOBILE_DRAWER_SCREENSHOT_DIR) {
      await page.screenshot({ path: process.env.MOBILE_DRAWER_SCREENSHOT_DIR + '/' + width + '-' + theme + '-left.png' });
    }
    await closeDrawer(page, 'left');
    assert.deepEqual(errors, [], 'No drawer script errors');
    console.log('PASS ' + width + '/' + theme + ': close rows, centered empty info/new chat, section headings and conversation creation');
  } catch (error) {
    if (process.env.MOBILE_DRAWER_SCREENSHOT_DIR) {
      await page.screenshot({ path: process.env.MOBILE_DRAWER_SCREENSHOT_DIR + '/FAILED-' + width + '-' + theme + '.png' }).catch(() => {});
    }
    throw error;
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const width of [390, 620, 820]) for (const theme of ['light', 'dark', 'navy']) await runCase(browser, width, theme);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
