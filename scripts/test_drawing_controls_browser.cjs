/* Start Flask first. Tests real online/offline drawing controls and shared
 * library fields; each fresh browser context owns its temporary drawing.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const mobile = page => page.viewportSize().width <= 1100;
const officialPaths = {
  'undo-2': ['M9 14 4 9l5-5', 'M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5a5.5 5.5 0 0 1-5.5 5.5H11'],
  'redo-2': ['m15 14 5-5-5-5', 'M20 9H9.5A5.5 5.5 0 0 0 4 14.5A5.5 5.5 0 0 0 9.5 20H13'],
  'trash-2': ['M3 6h18', 'M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6', 'M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2']
};

async function settle(page) {
  await page.evaluate(async () => {
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    await Promise.all(document.getAnimations().filter(animation =>
      animation.effect?.getComputedTiming().iterations !== Infinity)
      .map(animation => animation.finished.catch(() => {})));
  });
}

async function navigate(page, panel) {
  if (mobile(page) && !await page.evaluate(() => document.body.classList.contains('offline-nav-open'))) {
    await page.locator('#offlineNavToggle').tap();
  }
  const entry = page.locator('.offline-nav-item[data-panel="' + panel + '"]');
  if (mobile(page)) await entry.tap(); else await entry.click();
  await page.locator('#' + panel + 'Panel').waitFor({ state: 'visible' });
  await settle(page);
}

async function toolsEntry(page, id) {
  const kind = mobile(page) ? 'mobile-tools-open' : 'desktop-tools-open';
  if (!await page.evaluate(kind => document.body.classList.contains(kind), kind)) {
    await page.locator(mobile(page) ? '#mobileToolsBtn' : '#desktopToolsBtn').click();
  }
  await page.locator('#' + id).click();
  await settle(page);
}

async function checkIcon(button, name, size) {
  const svg = button.locator('svg[data-lucide="' + name + '"][data-icon="' + name + '"]');
  assert.equal(await svg.count(), 1, name + ': official icon is identified');
  assert.equal(await svg.getAttribute('viewBox'), '0 0 24 24');
  assert.equal(await svg.getAttribute('stroke-width'), '1.8');
  assert.deepEqual(await svg.locator('path').evaluateAll(paths => paths.map(path => path.getAttribute('d'))), officialPaths[name]);
  if (name === 'trash-2') {
    assert.deepEqual(await svg.locator('line').evaluateAll(lines => lines.map(line =>
      ['x1', 'x2', 'y1', 'y2'].map(name => line.getAttribute(name)))), [['10', '10', '11', '17'], ['14', '14', '11', '17']]);
  }
  const rect = await svg.boundingBox();
  assert.ok(rect && Math.abs(rect.width - size) <= 1 && Math.abs(rect.height - size) <= 1, name + ': glyph remains visible at its intended size');
}

async function drawingPaint(page, searchBackground) {
  const controls = await page.locator('.dge-view-controls').evaluate(node => {
    const css = getComputedStyle(node), minus = node.querySelector('[data-overlay-tool="zoom-out"]').getBoundingClientRect();
    const undo = document.querySelector('[data-editor-undo]').getBoundingClientRect();
    return { border: [css.borderTopWidth, css.borderRightWidth, css.borderBottomWidth, css.borderLeftWidth],
      background: css.backgroundColor, image: css.backgroundImage, shadow: css.boxShadow, minusLeft: minus.left, undoLeft: undo.left };
  });
  assert.deepEqual(controls.border, ['0px', '0px', '0px', '0px'], 'Zoom controls have no outer rectangular border');
  assert.equal(controls.background, 'rgba(0, 0, 0, 0)');
  assert.equal(controls.image, 'none');
  assert.equal(controls.shadow, 'none');
  assert.ok(Math.abs(controls.minusLeft - controls.undoLeft) <= 1, 'Zoom minus is aligned below Undo in the same column');
  assert.equal(await page.locator('.ddw-name').evaluate(input => getComputedStyle(input).backgroundColor), searchBackground,
    'Drawing name uses the search input surface without imposing search dimensions');
  await checkIcon(page.locator('[data-editor-undo]'), 'undo-2', 24);
  await checkIcon(page.locator('[data-editor-redo]'), 'redo-2', 24);
  const clear = page.locator('[data-editor-clear].dge-clear-button');
  await checkIcon(clear, 'trash-2', 20);
  assert.ok((await clear.innerText()).includes('清空'), 'Clear keeps its text label');
}

async function undoRedo(page) {
  const read = () => page.evaluate(() => window.__drawingControlsController.getDocument());
  const before = await read();
  await page.locator('.dge-tool-palette > summary').click();
  await page.locator('[data-overlay-tool="vertex"]').click();
  const view = await page.locator('.dge-overlay-viewport').boundingBox();
  const x = view.x + view.width * .55, y = view.y + view.height * .65;
  if (mobile(page)) await page.touchscreen.tap(x, y); else await page.mouse.click(x, y);
  const count = before.graphs.reduce((sum, graph) => sum + graph.vertices.length, 0);
  await page.waitForFunction(count => window.__drawingControlsController.getDocument().graphs
    .reduce((sum, graph) => sum + graph.vertices.length, 0) === count + 1, count);
  const added = await read();
  await page.locator('[data-editor-undo]').click();
  assert.deepEqual(await read(), before, 'Undo really restores the previous drawing document');
  await page.locator('[data-editor-redo]').click();
  assert.deepEqual(await read(), added, 'Redo restores the actual added vertex');
}

async function safeHistoryDelete(page, name) {
  await page.locator('.ddw-page-actions > button').filter({ hasText: /^历史绘图$/ }).click();
  const row = page.locator('.ddw-history-item').filter({ hasText: name });
  const remove = row.locator('.ddw-history-delete');
  await checkIcon(remove, 'trash-2', 16);
  const paint = await remove.evaluate(button => {
    const css = getComputedStyle(button), rect = button.getBoundingClientRect();
    const stroke = getComputedStyle(button.querySelector('svg path')).stroke;
    return { background: css.backgroundColor, radius: css.borderRadius, width: rect.width, height: rect.height, stroke };
  });
  const [red, green, blue] = paint.background.match(/[\d.]+/g).map(Number);
  assert.ok(red > 200 && green < 120 && blue < 120, 'History delete keeps its red circle');
  assert.ok(Math.abs(paint.width - paint.height) <= 1 && parseFloat(paint.radius) >= paint.width / 2);
  assert.ok(/rgb\(255, 255, 255\)/.test(paint.stroke), 'Trash lines remain white inside the red circle');
  const before = await page.evaluate(() => window.__drawingControlsController.getPages().map(page => ({ id: page.id, name: page.name })));
  const own = before.find(page => page.name === name);
  assert.ok(own, 'Delete is limited to this context’s temporary drawing');
  await remove.click();
  const prompt = page.locator('.dmate-delete-confirm[open]');
  await prompt.waitFor({ state: 'visible' });
  assert.ok((await prompt.innerText()).includes(name), 'Confirmation names the drawing being removed');
  await prompt.locator('.dmate-delete-confirm-close').click();
  assert.deepEqual(await page.evaluate(() => window.__drawingControlsController.getPages().map(page => ({ id: page.id, name: page.name }))), before,
    'Cancel leaves every drawing intact');
  await row.locator('.ddw-history-delete').click();
  await page.locator('.dmate-delete-confirm[open] .dmate-delete-confirm-delete').click();
  await page.waitForFunction(id => !window.__drawingControlsController.getPages().some(page => page.id === id), own.id);
  assert.deepEqual(await page.evaluate(() => window.__drawingControlsController.getPages().map(page => ({ id: page.id, name: page.name }))),
    before.filter(page => page.id !== own.id), 'Confirmed deletion removes only the temporary drawing');
}

async function filterMetrics(page) {
  const metrics = {};
  for (const [panel, prefix] of [['concepts', 'concept'], ['questions', 'question']]) {
    await navigate(page, panel);
    metrics[prefix] = await page.locator('#' + prefix + 'Category').evaluate(select => {
      const search = document.getElementById(select.id.replace('Category', 'Search'));
      const box = node => { const rect = node.getBoundingClientRect(); return { width: rect.width, height: rect.height }; };
      return { category: box(select), search: box(search) };
    });
    const before = await page.locator('#' + panel + 'Panel').evaluate(panel => ({ panel: panel.scrollTop,
      body: document.body.scrollTop, root: document.scrollingElement.scrollTop,
      toolbarTop: panel.querySelector('.offline-toolbar').getBoundingClientRect().top }));
    const list = page.locator('#' + prefix + 'List');
    await list.evaluate(node => { node.scrollTop = 0; });
    await list.hover();
    await page.mouse.wheel(0, 360);
    await page.waitForFunction(id => document.getElementById(id).scrollTop > 0, prefix + 'List');
    assert.deepEqual(await page.locator('#' + panel + 'Panel').evaluate(panel => ({ panel: panel.scrollTop,
      body: document.body.scrollTop, root: document.scrollingElement.scrollTop,
      toolbarTop: panel.querySelector('.offline-toolbar').getBoundingClientRect().top })), before, 'Library controls keep independent scrolling');
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  }
  for (const field of ['category', 'search']) for (const axis of ['width', 'height']) {
    assert.ok(Math.abs(metrics.concept[field][axis] - metrics.question[field][axis]) <= 1,
      'Concept/practice ' + field + ' ' + axis + ' match: ' + JSON.stringify(metrics));
  }
}

async function pdfPaint(page) {
  await toolsEntry(page, 'wrongBookBtn');
  const button = page.locator('#wrongPdfBtn');
  const paint = () => button.evaluate(button => {
    const css = getComputedStyle(button);
    return { border: css.borderTopWidth, background: css.backgroundColor, image: css.backgroundImage, shadow: css.boxShadow };
  });
  await page.mouse.move(0, 0);
  await button.evaluate(button => button.blur());
  await settle(page);
  const idle = await paint();
  assert.equal(idle.border, '0px');
  assert.equal(idle.background, 'rgba(0, 0, 0, 0)');
  assert.equal(idle.image, 'none');
  assert.equal(idle.shadow, 'none');
  if (!mobile(page)) {
    await button.hover();
    await settle(page);
    assert.notEqual((await paint()).background, idle.background, 'PDF export gets the shared hover fill');
    await page.mouse.move(0, 0);
    await page.keyboard.press('Tab');
    await button.focus();
    await settle(page);
    assert.equal(await button.evaluate(button => button.matches(':focus-visible')), true);
    assert.notEqual((await paint()).background, idle.background, 'Keyboard focus gets feedback');
  }
  await button.evaluate(button => { button.disabled = true; });
  const box = await button.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await settle(page);
  assert.deepEqual(await paint(), idle, 'Disabled PDF action does not light up on hover');
  await button.evaluate(button => { button.disabled = false; });
}

async function runCase(browser, width, theme, offline) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block',
    ...(width <= 1100 ? { isMobile: true, hasTouch: true } : {}) });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(baseURL + (offline ? '/offline' : ''), { waitUntil: 'networkidle' });
    if (offline) {
      await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
      await page.evaluate(mode => window.DMateOfflineAppearance.apply({ mode }, null), theme);
      await filterMetrics(page);
    } else await page.evaluate(mode => { appearanceSettings.mode = mode; applyAppearanceSettings({ save: false }); }, theme);
    const searchBackground = await page.locator(offline ? '#conceptSearch' : '#wrongBookSearch').evaluate(input => getComputedStyle(input).backgroundColor);
    // Capture the public controller while preserving the real mounted app.
    await page.evaluate(() => {
      const mount = window.DMateDrawingWorkspace.mount;
      window.DMateDrawingWorkspace.mount = function (...args) {
        const controller = mount.apply(this, args); window.__drawingControlsController = controller; return controller;
      };
    });
    if (offline) await navigate(page, 'drawing'); else await toolsEntry(page, 'graphDrawingBtn');
    await page.locator('.ddw-page-actions > button').filter({ hasText: /^新建空白页$/ }).click();
    await page.locator('.dge-overlay[data-geometry-ready="true"]').waitFor();
    const name = 'Drawing controls ' + width + (offline ? ' offline' : ' online');
    await page.locator('.ddw-name').fill(name);
    await settle(page);
    await drawingPaint(page, searchBackground);
    await undoRedo(page);
    await safeHistoryDelete(page, name);
    if (!offline) {
      await page.locator('#graphEditorClose').click();
      await pdfPaint(page);
    }
    assert.deepEqual(errors, [], 'No drawing control script errors');
    console.log('PASS ' + (offline ? 'offline ' : 'online ') + width + '/' + theme + ': drawing chrome, official icons, real undo/redo and safe history deletion');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const [width, theme] of [[1440, 'light'], [390, 'dark']]) for (const offline of [false, true]) await runCase(browser, width, theme, offline);
    const context = await browser.newContext({ viewport: { width: 820, height: 900 }, isMobile: true, hasTouch: true, serviceWorkers: 'block' });
    try {
      const page = await context.newPage(); await page.goto(baseURL + '/offline', { waitUntil: 'networkidle' });
      await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
      await page.evaluate(() => window.DMateOfflineAppearance.apply({ mode: 'navy' }, null));
      await filterMetrics(page);
      console.log('PASS offline 820/navy: matching library filter dimensions and independent scrolling');
    } finally { await context.close(); }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
