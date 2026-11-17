/* Real conversation lifecycle and navigation chrome; no AI requests. */
'use strict';
const assert = require('node:assert/strict');
const { mkdirSync } = require('node:fs');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const screenshotDir = process.env.HEADER_SCREENSHOT_DIR;
const mobile = page => page.viewportSize().width <= 1100;
const near = (a, b, label) => assert.ok(Math.abs(a - b) <= 1, label + ': ' + a + ' / ' + b);
const settle = page => page.evaluate(async () => {
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  await Promise.all(document.getAnimations().filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity)
    .map(animation => animation.finished.catch(() => {})));
});

async function sidebar(page, open) {
  const isOpen = await page.evaluate(() => innerWidth <= 1100
    ? document.body.classList.contains('mobile-left-open') : document.documentElement.dataset.desktopSidebar === 'expanded');
  if (isOpen === open) return;
  await page.locator(mobile(page) ? (open ? '#mobileNavBtn' : '#mobileNavClose')
    : (open ? '#desktopSidebarOpen' : '#desktopSidebarToggle')).click();
  await page.waitForFunction(open => (innerWidth <= 1100 ? document.body.classList.contains('mobile-left-open')
    : document.documentElement.dataset.desktopSidebar === 'expanded') === open, open);
  await settle(page);
}

async function headerTitle(page, expected) {
  const title = page.locator('#desktopConversationTitle');
  if (!expected) {
    assert.equal(await title.isVisible(), false, 'No current conversation leaves the desktop header blank');
    assert.equal(await title.textContent(), '', 'No fallback brand or stale conversation title');
    assert.ok(!await title.getAttribute('title'), 'An empty header has no stale tooltip');
  }
  if (mobile(page)) {
    assert.equal(await title.isVisible(), false, 'Conversation title is desktop only');
    assert.equal(await page.locator('#mobileConversationTitle').count(), 0, 'Mobile topbar stays icon only');
  } else if (expected) {
    assert.equal(await title.innerText(), expected, 'Header follows the current conversation');
    assert.equal(await title.getAttribute('title'), expected);
    assert.equal(await title.getAttribute('data-i18n-content'), '');
  }
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Header causes no page overflow');
}

async function sharedTooltip(page, target, text) {
  await target.hover();
  const tooltip = page.locator('.dm-ui-tooltip[role="tooltip"]');
  await tooltip.waitFor({ state: 'visible' });
  assert.equal(await tooltip.innerText(), text, 'The shared tooltip displays the complete protected conversation name');
  assert.equal(await tooltip.locator('*').count(), 0, 'Conversation names stay literal text inside the tooltip');
  assert.equal(await target.getAttribute('title'), '', 'Native rectangular tooltip is suppressed while the shared tooltip is active');
  assert.ok((await target.getAttribute('aria-describedby') || '').split(/\s+/).includes(await tooltip.getAttribute('id')));
  const style = await tooltip.evaluate(node => Object.fromEntries(['backgroundColor', 'backgroundImage', 'borderWidth', 'borderColor',
    'borderRadius', 'boxShadow', 'color', 'fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'padding']
    .map(key => [key, getComputedStyle(node)[key]])));
  await page.mouse.move(0, 0);
  await tooltip.waitFor({ state: 'hidden' });
  await settle(page);
  return style;
}

async function headerIcons(page, expanded) {
  const icon = page.locator(mobile(page) ? '#mobileNewChatBtn' : '#desktopNewChatBtn');
  assert.equal(await icon.isVisible(), !expanded, 'Sidebar expansion hides the redundant new-conversation icon');
  if (expanded) {
    if (!mobile(page)) {
      assert.equal(await page.locator('#desktopSidebarOpen').isVisible(), false);
      const offsets = await page.locator('#desktopConversationTitle').evaluate(node => {
        const parent = node.closest('.desktop-chat-toolbar');
        return [node.getBoundingClientRect().left - parent.getBoundingClientRect().left, parseFloat(getComputedStyle(parent).paddingLeft)];
      });
      near(offsets[0], offsets[1], 'Expanded sidebar leaves the title at the toolbar start');
    }
    return;
  }
  const toggle = page.locator(mobile(page) ? '#mobileNavBtn' : '#desktopSidebarOpen');
  const style = locator => locator.evaluate(node => {
    const css = getComputedStyle(node), rect = node.getBoundingClientRect(), svg = node.querySelector('svg').getBoundingClientRect();
    return { width: rect.width, height: rect.height, iconWidth: svg.width, iconHeight: svg.height,
      padding: css.padding, border: css.borderWidth, radius: css.borderRadius,
      background: css.backgroundColor, color: css.color };
  });
  await page.mouse.move(0, 0); await page.locator('#text').focus(); await settle(page);
  assert.deepEqual(await style(icon), await style(toggle), 'New conversation keeps the adjacent sidebar control dimensions and feedback');
  const iconColors = await icon.evaluate(node => {
    const probe = document.createElement('span'); probe.style.color = 'var(--text-muted)'; document.body.append(probe);
    const expected = getComputedStyle(probe).color; probe.remove();
    return { actual:getComputedStyle(node.querySelector('svg')).color,
      adjacent:getComputedStyle(node.previousElementSibling.querySelector('svg')).color, expected };
  });
  assert.equal(iconColors.actual, iconColors.expected, 'New-conversation icon uses the quieter theme color on every viewport');
  assert.notEqual(iconColors.actual, iconColors.adjacent, 'New-conversation icon is visibly quieter than the sidebar icon');
  assert.equal(await icon.locator('svg[data-icon="square-pen"]').count(), 1, 'Use the local Lucide square-pen icon');
  assert.equal((await icon.innerText()).trim(), '', 'Topbar button has no visible text');
  assert.equal(await icon.getAttribute('title'), '＋ 新对话');
  assert.equal(await icon.getAttribute('aria-label'), '＋ 新对话');
  const positions = await icon.evaluate(node => {
    const prior = node.previousElementSibling.getBoundingClientRect(), current = node.getBoundingClientRect();
    return { gap: current.left - prior.right, center: current.y + current.height / 2,
      priorCenter: prior.y + prior.height / 2 };
  });
  assert.ok(positions.gap >= 8 && positions.gap <= 12, 'Header icons have the slightly wider shared spacing');
  near(positions.center, positions.priorCenter, 'Adjacent header icons share a baseline');
}

async function renameCurrent(page, name) {
  await sidebar(page, true);
  const current = page.locator('#sessions .session.active [data-session-name]');
  if (!mobile(page)) {
    const original = await current.elementHandle();
    await current.click();
    assert.equal(await original.evaluate(node => node.isConnected), true,
      'Selecting the active conversation preserves its name node for reliable double-click renaming');
    await original.dispose();
  }
  // Two rename operations can run faster than the application's deliberate
  // duplicate-gesture guard when reduced motion is enabled in the test.
  await page.waitForFunction(() => Date.now() - lastSessionRenameAt >= 400);
  await current.dblclick();
  await page.locator('#sessionRenameModal').waitFor({ state: 'visible' });
  await page.locator('#sessionRenameInput').fill(name);
  await page.locator('#sessionRenameSave').click();
  await page.locator('#sessionRenameModal').waitFor({ state: 'hidden' });
  await settle(page);
}

async function language(page, value) {
  await page.mouse.move(0, 0);
  await page.evaluate(() => document.activeElement?.blur());
  await page.evaluate(value => window.DMateI18n.setLanguage(value, false), value);
  await settle(page);
}

async function conversationLifecycle(page, width, theme) {
  await page.evaluate(() => { sessions = []; currentId = null; saveState(); renderAll(); });
  await settle(page);
  await headerTitle(page, ''); await headerIcons(page, false);
  const create = page.locator(mobile(page) ? '#mobileNewChatBtn' : '#desktopNewChatBtn');
  await create.click();
  await page.waitForFunction(() => sessions.length === 1 && Boolean(getCurrent()));
  const firstId = await page.evaluate(() => String(currentId));
  await headerTitle(page, '新对话');
  await language(page, 'en');
  await headerTitle(page, 'New conversation');
  assert.equal(await create.getAttribute('title'), '＋ New chat');
  assert.equal(await create.getAttribute('aria-label'), '＋ New chat');
  await language(page, 'zh-CN');
  const derivedName = await page.evaluate(() => {
    getCurrent().messages = [{ role: 'user', text: '集合的包含关系与幂集' }];
    renderSessions();
    return sessionDisplayName(getCurrent());
  });
  assert.ok(derivedName.includes('集合') && derivedName !== '新对话', 'Real saved user content auto-names a default conversation');
  await headerTitle(page, derivedName);
  await renameCurrent(page, '新对话');
  await language(page, 'en');
  await headerTitle(page, '新对话'); // A user's chosen name is content, even if it matches UI text.
  await language(page, 'zh-CN');
  await headerIcons(page, true);
  await page.locator('#newChatBtn').click();
  await page.waitForFunction(() => sessions.length === 2);
  await headerTitle(page, '新对话');
  await sidebar(page, true);
  await page.locator('#sessions .session[data-session-id="' + firstId + '"] [data-session-name]').click();
  await page.waitForFunction(id => String(currentId) === id, firstId);
  await headerTitle(page, '新对话');
  const longName = ('<b>集合 & “逻辑”</b> ' + '很长的对话名称'.repeat(12)).slice(0, 80);
  await renameCurrent(page, longName);
  await headerTitle(page, longName);
  assert.equal(await page.locator('#desktopConversationTitle b,#sessions [data-session-name] b').count(), 0,
    'User-supplied title markup is displayed as text');
  let conversationTooltipStyle;
  if (!mobile(page)) {
    const sidebarTooltip = await sharedTooltip(page, page.locator('#sessions .session.active [data-session-name]'), longName);
    conversationTooltipStyle = await sharedTooltip(page, page.locator('#desktopConversationTitle'), longName);
    assert.deepEqual(conversationTooltipStyle, sidebarTooltip, 'Sidebar and header conversation names share the same tooltip');
    const overflow = await page.locator('#desktopConversationTitle').evaluate(node => {
      const css = getComputedStyle(node), bounds = node.getBoundingClientRect();
      return { overflow: css.overflowX, ellipsis: css.textOverflow, wrap: css.whiteSpace,
        right: bounds.right, toolsLeft: document.getElementById('desktopToolsBtn').getBoundingClientRect().left };
    });
    assert.deepEqual([overflow.overflow, overflow.ellipsis, overflow.wrap], ['hidden', 'ellipsis', 'nowrap']);
    assert.ok(overflow.right <= overflow.toolsLeft, 'A long title leaves the tools button usable');
  }
  if (screenshotDir && theme === 'dark' && width === 1440) {
    await page.screenshot({ path: screenshotDir + '/desktop-expanded.png' });
  }
  await sidebar(page, false);
  await headerIcons(page, false); await headerTitle(page, longName);
  if (!mobile(page)) {
    assert.deepEqual(await sharedTooltip(page, page.locator('#desktopNewChatBtn'), '＋ 新对话'), conversationTooltipStyle,
      'Conversation labels use the existing interface tooltip styling');
    await language(page, 'en');
    await sharedTooltip(page, page.locator('#desktopConversationTitle'), longName);
    await language(page, 'zh-CN');
  }
  if (screenshotDir && theme === 'dark' && [390, 1440].includes(width)) {
    await page.screenshot({ path: screenshotDir + (width === 390 ? '/mobile-topbar.png' : '/desktop-collapsed.png') });
  }
  if (!mobile(page)) {
    await page.setViewportSize({ width: 1101, height: 900 }); await settle(page);
    await headerTitle(page, longName);
    await page.setViewportSize({ width, height: 900 }); await settle(page);
  }
  await sidebar(page, true);
  await page.locator('#sessions .session.active > .del').click();
  await page.locator('#appConfirmModal').waitFor({ state: 'visible' });
  await page.locator('#appConfirmConfirm').click();
  await page.waitForFunction(() => currentId === null && sessions.length === 1);
  await headerTitle(page, '');
  await sidebar(page, false);
}

const notebookStyle = locator => locator.evaluate(node => {
  const css = getComputedStyle(node);
  return { ...Object.fromEntries(['backgroundColor', 'backgroundImage', 'borderTopWidth', 'borderTopStyle', 'borderTopColor',
    'color', 'borderRadius', 'fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'padding', 'height', 'boxShadow']
    .map(key => [key, css[key]])), renderedHeight: node.getBoundingClientRect().height };
});

const aiActionPaint = locator => locator.evaluate(node => {
  const css = getComputedStyle(node);
  return { background: css.backgroundColor, image: css.backgroundImage, border: css.borderWidth,
    shadow: css.boxShadow, outline: [css.outlineStyle, css.outlineWidth, css.outlineColor], color: css.color };
});

async function notebookAiActions(page, newButton) {
  const actions = page.locator('#conceptNotebookDialog .dcn-ai-actions > button:not(.dcn-analysis-cancel)');
  assert.equal(await actions.count(), 2);
  assert.equal(await actions.nth(0).isDisabled(), true, 'No selected concepts disables explanation');
  assert.equal(await actions.nth(1).isDisabled(), true, 'No selected concepts disables relation analysis');
  const filled = async button => {
    const paint = await aiActionPaint(button);
    assert.notEqual(paint.background, 'rgba(0, 0, 0, 0)', 'Notebook AI actions have the shared filled surface');
    assert.equal(paint.image, 'none'); assert.equal(paint.border, '0px'); assert.equal(paint.shadow, 'none');
    return paint;
  };
  await page.mouse.move(0, 0); await page.locator('#conceptNotebookTitle').focus(); await settle(page);
  for (const button of await actions.all()) await filled(button);
  await page.locator('#conceptNotebookDialog .dcn-note input[type="checkbox"]').first().check();
  assert.equal(await actions.nth(0).isEnabled(), true, 'One selected concept enables explanation');
  assert.equal(await actions.nth(1).isDisabled(), true, 'Relation analysis still requires two concepts');
  await newButton.click();
  await page.locator('#conceptNotebookDialog .dcn-title').fill('关联概念');
  for (const checkbox of await page.locator('#conceptNotebookDialog .dcn-note input[type="checkbox"]').all()) await checkbox.check();
  assert.equal(await actions.nth(0).isDisabled(), true, 'Multiple concepts disable single-concept explanation');
  assert.equal(await actions.nth(1).isEnabled(), true, 'Two selected concepts enable relation analysis');
  for (const button of await actions.all()) {
    if (await button.isDisabled()) continue;
    await page.mouse.move(0, 0); await page.locator('#conceptNotebookTitle').focus(); await settle(page);
    const idle = await filled(button);
    if (!mobile(page)) {
      await button.hover(); await settle(page);
      assert.notDeepEqual(await aiActionPaint(button), idle, 'Enabled notebook AI action has hover feedback');
    }
    await page.mouse.move(0, 0); await page.keyboard.press('Tab'); await button.focus(); await settle(page);
    assert.notDeepEqual(await aiActionPaint(button), idle, 'Enabled notebook AI action has keyboard focus feedback');
  }
  await page.locator('#conceptNotebookDialog .dcn-note input[type="checkbox"]').last().uncheck();
  assert.equal(await actions.nth(0).isEnabled(), true, 'Returning to exactly one concept restores explanation');
  assert.equal(await actions.nth(1).isDisabled(), true);
}

async function notebookButton(page) {
  await sidebar(page, true);
  const source = page.locator('#newChatBtn');
  await page.mouse.move(0, 0); await page.locator(mobile(page) ? '#mobileNavClose' : '#desktopSidebarToggle').focus();
  await settle(page);
  const idle = await notebookStyle(source);
  let hovered;
  if (!mobile(page)) { await source.hover(); await settle(page); hovered = await notebookStyle(source); }
  await sidebar(page, false);
  await page.locator(mobile(page) ? '#mobileToolsBtn' : '#desktopToolsBtn').click();
  await page.locator('#conceptNotebookBtn').click();
  await page.locator('#conceptNotebookDialog').waitFor({ state: 'visible' });
  const button = page.locator('#conceptNotebookDialog .dcn-sidebar > .dcn-new');
  assert.equal(await button.innerText(), '＋ 新概念');
  await page.mouse.move(0, 0); await page.locator('#conceptNotebookTitle').focus(); await settle(page);
  assert.deepEqual(await notebookStyle(button), idle, 'New concept matches the new-conversation button surface and typography');
  if (!mobile(page)) { await button.hover(); await settle(page);
    assert.deepEqual(await notebookStyle(button), hovered, 'New concept shares new-conversation hover feedback'); }
  const before = await page.locator('#conceptNotebookDialog .dcn-note').count();
  await button.click();
  assert.equal(await page.locator('#conceptNotebookDialog .dcn-note').count(), before + 1, 'New concept still creates an editable notebook entry');
  await page.locator('#conceptNotebookDialog .dcn-title').fill('局部概念');
  await notebookAiActions(page, button);
  const savedTitle = await page.locator('#conceptNotebookDialog .dcn-title').inputValue();
  await language(page, 'en');
  assert.equal(await button.innerText(), '＋ New concept');
  assert.equal(await page.locator('#conceptNotebookDialog .dcn-title').inputValue(), savedTitle, 'Language changes preserve concept content');
  await language(page, 'zh-CN');
  await page.locator('#conceptNotebookDialog .dcn-close').first().click();
}

async function runCase(browser, width, theme) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: 'reduce', serviceWorkers: 'block',
    ...(width <= 1100 ? { isMobile: true, hasTouch: true } : {}) });
  const page = await context.newPage(), errors = [], modelRequests = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/auth/me', route => route.fulfill({ contentType: 'application/json',
    body: JSON.stringify({ configured: true, authenticated: false }) }));
  for (const endpoint of ['**/chat', '**/analyze-questions', '**/notebook/analyze']) await page.route(endpoint, route => {
    modelRequests.push(route.request().url()); return route.abort();
  });
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await page.waitForFunction(() => typeof refreshConversationTitle === 'function');
    await page.evaluate(theme => { appearanceSettings.mode = theme; applyAppearanceSettings({ save: false }); }, theme);
    await conversationLifecycle(page, width, theme);
    await notebookButton(page);
    assert.deepEqual(modelRequests, [], 'No AI endpoint calls'); assert.deepEqual(errors, [], 'No browser script errors');
    console.log('PASS ' + width + '/' + theme + ': blank/header lifecycle, shared conversation tooltips, sidebar state, live language and filled notebook AI actions');
  } finally { await context.close(); }
}

(async () => {
  if (screenshotDir) mkdirSync(screenshotDir, { recursive: true });
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    const widths = process.env.DMATE_TEST_WIDTHS ? process.env.DMATE_TEST_WIDTHS.split(',').map(Number) : [390, 820, 1440];
    assert.ok(widths.length && widths.every(width => [390, 820, 1440].includes(width)), 'Use supported navigation test widths');
    for (const width of widths) for (const theme of ['dark', 'light', 'navy']) await runCase(browser, width, theme);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
