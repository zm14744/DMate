/* Uses the public persistent drawing API inside the actual online dialog.
 * Anonymous online galleries intentionally do not persist across refreshes.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const storageKey = 'dmate:drawing-panels-browser-regression';
const names = ['测试 A', '测试 B', '测试 C'];
const gallery = { version: 2, activeId: 'page-A', pages: names.map((name, index) => ({
  id: 'page-' + 'ABC'[index], name, createdAt: index + 1, updatedAt: [100, 300, 200][index],
  document: { body_text: '', graphs: [{ id: 'G1', name, directed: true, weighted: true,
    vertices: [{ id: 'v1', label: 'ABC'[index] + '1', x: .25, y: .3 },
      { id: 'v2', label: 'ABC'[index] + '2', x: .65, y: .4 }],
    edges: [{ id: 'e1', from: 'v1', to: 'v2', direction: 'forward', weight: 3, edge_label: 'AB', style: 'solid' }] }] }
})) };
const settle = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));

async function mount(page, seed) {
  await page.evaluate(({ key, value, seed }) => {
    if (seed) localStorage.setItem(key, JSON.stringify(value));
    window.drawingPanelFixture = DMateDrawingWorkspace.mount(document.getElementById('graphEditorMount'), {
      storageKey: key, persistent: true, sessionState: {}, legacyDocument: { body_text: '', graphs: [] }
    });
    showGraphEditorDialog(document.getElementById('graphEditorDialog'));
  }, { key: storageKey, value: gallery, seed });
  await page.waitForFunction(() => document.getElementById('graphEditorDialog').open
    && !document.getElementById('graphEditorDialog').dataset.positioning);
  await page.locator('.dge-overlay-viewport').waitFor();
  await settle(page);
}

async function selectShape(page, kind, mobile) {
  const shape = page.locator(kind === 'vertex' ? '.dge-overlay-node[data-vertex-id="v1"] .dge-overlay-dot'
    : '.dge-overlay-edge[data-edge-id="e1"] .dge-overlay-stroke').first();
  const point = await shape.evaluate(node => {
    if (node.localName === 'path') {
      const middle = node.getPointAtLength(node.getTotalLength() / 2);
      const point = new DOMPoint(middle.x, middle.y).matrixTransform(node.getScreenCTM());
      return { x: point.x, y: point.y };
    }
    const rect = node.getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  });
  if (mobile) await page.touchscreen.tap(point.x, point.y); else await page.mouse.click(point.x, point.y);
  await page.waitForFunction(text => document.querySelector('.dge-selection-panel h3')?.textContent.includes(text),
    kind === 'vertex' ? '顶点的属性' : '边的属性');
  await settle(page);
}

async function panelPosition(page) {
  const state = await page.locator('.dge-selection-panel').evaluate(panel => {
    const rect = panel.getBoundingClientRect(), workspace = panel.closest('.dge-workspace').getBoundingClientRect();
    const toolbarBottom = Math.max(...['.dge-view-controls', '.ddw-side-actions', '.dge-tool-palette > summary']
      .map(selector => document.querySelector(selector)?.getBoundingClientRect().bottom || 0));
    return { right: workspace.right - rect.right, bottom: workspace.bottom - rect.bottom,
      top: rect.top, width: rect.width, height: rect.height, toolbarBottom,
      scrollHeight: panel.scrollHeight, clientHeight: panel.clientHeight };
  });
  assert.ok(Math.abs(state.right - 12) <= 2, 'Properties stay 12px from the canvas right: ' + JSON.stringify(state));
  assert.ok(Math.abs(state.bottom - 12) <= 2, 'Properties stay at the canvas bottom: ' + JSON.stringify(state));
  assert.ok(state.top >= state.toolbarBottom + 3, 'Properties must not cover the canvas tools: ' + JSON.stringify(state));
  return state;
}

async function reachablePanelEnd(page, selector) {
  const panel = page.locator(selector);
  const overflow = await panel.evaluate(node => {
    const overflow = node.scrollHeight > node.clientHeight + 1;
    node.scrollTop = node.scrollHeight;
    return { overflow, moved: node.scrollTop, scrollable: getComputedStyle(node).overflowY };
  });
  if (overflow.overflow) {
    assert.ok(['auto', 'scroll'].includes(overflow.scrollable), 'Overflowing panel must have its own scroll');
    assert.ok(overflow.moved > 0, 'Long panel must actually scroll to its end');
  }
  let last = panel.locator('button:enabled:visible,input:enabled:visible,select:enabled:visible,textarea:enabled:visible').last();
  const actionable = await last.count() > 0;
  if (!actionable) last = panel.locator('*:visible').last();
  assert.ok(await last.count(), 'Panel has readable content');
  const inside = await last.evaluate((node, actionable) => {
    const rect = node.getBoundingClientRect(), parent = node.closest('.dge-selection-panel,.dge-float-content,.ddw-side-panel,.dge-overlay-tools').getBoundingClientRect();
    return (!actionable || rect.top >= Math.max(0, parent.top - 1))
      && rect.bottom >= parent.top - 1 && rect.bottom <= parent.bottom + 1
      && rect.left >= parent.left - 1 && rect.right <= parent.right + 1
      && rect.bottom <= innerHeight;
  }, actionable);
  assert.ok(inside, 'Last panel action remains inside the panel and visible viewport');
  if (actionable) await last.click({ trial: true }); // Hit testing without deleting or invoking AI.
}

async function compactPanel(page, selector, mobile) {
  const metrics = await page.locator(selector).evaluate(node => {
    const rect = node.getBoundingClientRect(), style = getComputedStyle(node);
    return { x: rect.x, y: rect.y, width: rect.width, height: rect.height,
      right: rect.right, bottom: rect.bottom, screenWidth: innerWidth, screenHeight: innerHeight,
      padding: parseFloat(style.paddingTop), horizontalOverflow: node.scrollWidth - node.clientWidth };
  });
  assert.ok(metrics.x >= 7 && metrics.right <= metrics.screenWidth - 7, 'Popover fits the horizontal viewport: ' + JSON.stringify(metrics));
  assert.ok(metrics.y >= 7 && metrics.bottom <= metrics.screenHeight - 7, 'Popover fits the vertical viewport: ' + JSON.stringify(metrics));
  assert.ok(metrics.horizontalOverflow <= 1, 'Panel does not require horizontal scrolling');
  if (mobile) {
    assert.ok(metrics.width <= 320, 'Mobile panel stays compact instead of filling the screen: ' + JSON.stringify(metrics));
    assert.ok(metrics.padding <= 10, 'Mobile panel has compact padding');
  }
  await reachablePanelEnd(page, selector);
  return metrics;
}

async function canvasChrome(page) {
  return page.evaluate(() => {
    const viewport = document.querySelector('.dge-overlay-viewport'), frame = viewport.closest('.ddw-canvas-frame');
    const style = getComputedStyle(viewport), bounds = viewport.getBoundingClientRect(), outer = frame.getBoundingClientRect();
    const rect = node => {
      const r = node.getBoundingClientRect(); return [r.x, r.y, r.width, r.height];
    };
    return { controls: [document.querySelector('.dge-view-controls'), document.querySelector('.dge-tool-palette>summary'),
      ...document.querySelectorAll('.ddw-side-actions>button')].map(rect),
      scroll: [viewport.scrollLeft, viewport.scrollTop],
      gutter: [viewport.offsetWidth - viewport.clientWidth - parseFloat(style.borderLeftWidth) - parseFloat(style.borderRightWidth),
        viewport.offsetHeight - viewport.clientHeight - parseFloat(style.borderTopWidth) - parseFloat(style.borderBottomWidth)],
      frameGap: [outer.right - bounds.right, outer.bottom - bounds.bottom],
      frameOverflow: getComputedStyle(frame).overflow,
      size: [viewport.clientWidth, viewport.clientHeight] };
  });
}

async function viewportAndPopoverChecks(page, mobile, label, online = true) {
  for (const language of ['en', 'zh-CN']) {
    await page.evaluate(language => DMateI18n.setLanguage(language, false), language);
    await settle(page);
    const labels = await page.locator('.ddw-side-actions>button').evaluateAll(buttons => {
      const frame = document.querySelector('.ddw-canvas-frame').getBoundingClientRect();
      return buttons.map(button => {
        const rect = button.getBoundingClientRect();
        return { text: button.textContent, overflow: button.scrollWidth - button.clientWidth,
          left: rect.left - frame.left, right: frame.right - rect.right };
      });
    });
    for (const item of labels) {
      assert.ok(item.overflow <= 1, label + '/' + language + ': button label must remain complete: ' + JSON.stringify(item));
      assert.ok(item.left >= 0 && item.right >= 0, 'Button remains within the canvas frame');
    }
  }
  const zoomIn = page.locator('[data-overlay-tool="zoom-in"]');
  for (let i = 0; i < 20 && await zoomIn.isEnabled(); i++) await zoomIn.click();
  assert.equal(await zoomIn.isEnabled(), false, 'Drawing zoom reaches its finite upper limit');
  await settle(page);
  await page.locator('.dge-overlay-viewport').evaluate(node => node.scrollTo(0, 0));
  await settle(page);
  const baseline = await canvasChrome(page);
  assert.ok(baseline.size[0] > 120 && baseline.size[1] > 120, 'Canvas retains useful dimensions');
  assert.ok(baseline.gutter.every(value => value <= 1), 'Canvas reserves no blank scrollbar strip: ' + JSON.stringify(baseline));
  assert.ok(baseline.frameGap.every(value => value <= 2), 'Canvas fills the frame at right and bottom');
  assert.ok(['hidden', 'clip'].includes(baseline.frameOverflow), 'Frame owns the rounded canvas clip');
  // Sample every painted frame while genuine pointer input pans the canvas.
  // A final-only comparison misses the overlay/workspace top-style race.
  await page.evaluate(() => {
    window.drawingChromeProbe = { samples: [], running: true };
    const tick = () => {
      const probe = window.drawingChromeProbe;
      probe.samples.push([document.querySelector('.dge-view-controls'), document.querySelector('.dge-tool-palette>summary'),
        ...document.querySelectorAll('.ddw-side-actions>button')].map(node => {
        const r = node.getBoundingClientRect(); return [r.x, r.y, r.width, r.height];
      }));
      if (probe.running) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
  const canvas = await page.locator('.dge-overlay-viewport').boundingBox();
  const start = { x: canvas.x + canvas.width * .65, y: canvas.y + canvas.height * .65 };
  await page.mouse.move(start.x, start.y); await page.mouse.down();
  for (let step = 1; step <= 8; step++) {
    await page.mouse.move(start.x - step * 9, start.y - step * 7);
    await settle(page);
  }
  await page.mouse.up();
  await page.mouse.wheel(180, 160); await settle(page);
  const after = await canvasChrome(page);
  const samples = await page.evaluate(() => {
    window.drawingChromeProbe.running = false; return window.drawingChromeProbe.samples;
  });
  assert.ok(samples.length >= 8, 'Pan records multiple real animation frames');
  assert.ok(after.scroll.some((value, i) => Math.abs(value - baseline.scroll[i]) > 20), 'The canvas really pans/scrolls');
  for (const sample of samples) sample.forEach((rect, i) => rect.forEach((value, axis) => {
    assert.ok(Math.abs(value - baseline.controls[i][axis]) <= 1,
      label + ': toolbar/button jumped during pan: ' + JSON.stringify({ baseline: baseline.controls, sample }));
  }));
  if (process.env.OFFLINE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/viewport-' + label + '-pan.png' });
  await page.locator('[data-overlay-tool="zoom-fit"]').click(); await settle(page);
  const popovers = [
    ['tools', '.dge-tool-palette>summary', '.dge-tool-palette[open]>.dge-overlay-tools'],
    ['settings', '.ddw-side-actions>button:first-child', '.dge-float-panel[data-panel-key="graphs"][open]>.dge-float-content'],
    ['information', '.ddw-side-actions>button:nth-child(2)', '.dge-float-panel[data-panel-key="results"][open]>.dge-float-content'],
    ['history', '.ddw-page-actions>button:nth-child(2)', '.ddw-side-panel:not([hidden])'],
  ];
  if (online) popovers.push(['ai', '.ddw-side-actions>button:last-child', '.ddw-side-panel:not([hidden])']);
  const metrics = {};
  for (const [name, trigger, panel] of popovers) {
    await page.locator(trigger).click(); await page.locator(panel).waitFor(); await settle(page);
    try { metrics[name] = await compactPanel(page, panel, mobile); }
    catch (error) {
      if (process.env.OFFLINE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/viewport-' + label + '-' + name + '-failure.png' });
      throw new Error(label + ' ' + name + ': ' + error.message, { cause: error });
    }
    if (['settings', 'information'].includes(name) && process.env.OFFLINE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/viewport-' + label + '-' + name + '.png' });
    await page.locator(trigger).click(); await settle(page);
  }
  console.log('PASS viewport ' + label + ': ' + samples.length + ' stable pan frames, no gutters; popovers ' + JSON.stringify(metrics));
}

async function history(page) {
  const button = page.locator('.ddw-page-actions').getByRole('button', { name: '历史绘图', exact: true });
  if (await button.getAttribute('aria-expanded') !== 'true') await button.click();
  await page.locator('.ddw-history-list').waitFor();
  return page.locator('.ddw-history-open');
}

async function runCase(browser, width) {
  const page = await browser.newPage({ viewport: { width, height: width === 390 ? 740 : 900 },
    isMobile: width === 390, hasTouch: width === 390 });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await mount(page, true);
    await viewportAndPopoverChecks(page, width === 390, 'online-' + width);
    await selectShape(page, 'vertex', width === 390);
    const vertex = await panelPosition(page);
    await compactPanel(page, '.dge-selection-panel', width === 390);
    if (process.env.OFFLINE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/drawing-' + width + '-vertex.png' });
    if (width === 390) {
      const oldStyle = await page.addStyleTag({ content: '.ddw-editor .dge-workspace .dge-selection-panel{top:var(--ddw-property-top,120px)!important;bottom:auto!important}' });
      await settle(page);
      await assert.rejects(() => panelPosition(page), /Properties stay at the canvas bottom/);
      await oldStyle.evaluate(node => node.remove());
      await settle(page);
      await panelPosition(page);
    }
    await selectShape(page, 'edge', width === 390);
    const edge = await panelPosition(page);
    // A compact layout may fit naturally. If it overflows it must scroll;
    // either way the final action must stay reachable, never clipped away.
    await compactPanel(page, '.dge-selection-panel', width === 390);
    if (process.env.OFFLINE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/drawing-' + width + '-edge.png' });
    assert.deepEqual(await (await history(page)).allTextContents(), names, 'History follows saved array order, not updatedAt');
    for (const index of [1, 0, 2]) {
      await page.locator('.ddw-history-open').getByText(names[index], { exact: true }).click();
      assert.equal(await page.locator('.ddw-name').inputValue(), names[index]);
      assert.equal(await page.locator('.dge-overlay-node[data-vertex-id="v1"] .dge-overlay-label').textContent(), 'ABC'[index] + '1');
      assert.deepEqual(await (await history(page)).allTextContents(), names, 'Visiting another drawing must not reorder history');
    }
    await page.locator('.ddw-page-actions').getByRole('button', { name: '新建空白页', exact: true }).click();
    const added = await page.locator('.ddw-name').inputValue(), expected = [...names, added];
    assert.deepEqual(await (await history(page)).allTextContents(), expected, 'New pages append to the stable history');
    await page.reload({ waitUntil: 'networkidle' });
    await mount(page, false);
    assert.equal(await page.locator('.ddw-name').inputValue(), added, 'Active drawing persists across refresh');
    assert.deepEqual(await (await history(page)).allTextContents(), expected, 'History order persists across refresh');
    await page.locator('.ddw-history-open').getByText(names[1], { exact: true }).click();
    assert.equal(await page.locator('.ddw-name').inputValue(), names[1]);
    assert.deepEqual(await (await history(page)).allTextContents(), expected);
    assert.deepEqual(errors, []);
    console.log('PASS ' + width + ': vertex ' + JSON.stringify(vertex) + '; edge ' + JSON.stringify(edge) + '; stable selectable history and refresh');
  } finally { await page.close(); }
}

async function onlinePage(browser, width = 1440) {
  const page = await browser.newPage({ viewport: { width, height: width === 390 ? 740 : 900 },
    isMobile: width === 390, hasTouch: width === 390, serviceWorkers: 'block' });
  page.regressionErrors = []; page.modelCalls = 0;
  page.on('pageerror', error => page.regressionErrors.push(error.message));
  // The fixture grants local persistence permissions only; it never logs in
  // to a real account or sends a cloud/model request.
  await page.route('**/auth/me', route => route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ configured: true, authenticated: false }) }));
  await page.route(/\/(?:chat|ocr|drawing\/[^?]+)(?:\?|$)/, route => {
    page.modelCalls++; return route.abort();
  });
  await page.addInitScript(() => {
    window.drawingStorageWrites = [];
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function(key, value) {
      if (this === localStorage && /^dmate:graph-(?:gallery|drawing)/.test(key)) window.drawingStorageWrites.push(key);
      return original.call(this, key, value);
    };
  });
  await page.goto(baseURL, { waitUntil: 'networkidle' });
  await localPermissions(page);
  return page;
}

async function localPermissions(page, username = '') {
  await page.waitForFunction(() => document.documentElement.dataset.accountStateKnown === '1');
  await page.evaluate(username => {
    stopCloudLivePolling();
    accountState.authenticated = Boolean(username); accountState.username = username;
  }, username);
}

async function openOnline(page) {
  const toggle = page.locator(page.viewportSize().width <= 1100 ? '#mobileToolsBtn' : '#desktopToolsBtn');
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
  await page.locator('#graphDrawingBtn').click();
  await page.locator('#graphEditorDialog[open] .dmate-drawing-workspace').waitFor();
  await page.waitForFunction(() => !document.getElementById('graphEditorDialog').dataset.positioning);
  await settle(page);
}

async function closeOnline(page) {
  await page.locator('#graphEditorClose').click();
  await page.waitForFunction(() => !document.getElementById('graphEditorDialog').open && ocrEditorController === null);
}

async function onlineState(page) {
  return page.evaluate(() => ({ pages: ocrEditorController.getPages().map(p => ({
    id: p.id, name: p.name, document: p.document
  })), name: document.querySelector('.ddw-name').value }));
}

async function assertEditableBlank(page) {
  const state = await onlineState(page);
  assert.equal(state.pages.length, 1, 'Opening an empty online gallery creates exactly one page');
  assert.equal(state.pages[0].document.graphs.length, 1);
  assert.deepEqual(state.pages[0].document.graphs[0].vertices, []);
  assert.deepEqual(state.pages[0].document.graphs[0].edges, []);
  assert.equal(await page.locator('.ddw-name').isEnabled(), true, 'Blank page name is editable');
  assert.equal(await page.locator('.dge-overlay-viewport').evaluate(node => Boolean(node.closest('[inert]'))), false,
    'Blank page canvas is editable, rather than the inert zero-page placeholder');
  return state;
}

async function deleteAllOnline(page) {
  const count = (await onlineState(page)).pages.length;
  await history(page);
  for (let remaining = count; remaining > 0; remaining--) {
    await page.locator('.ddw-history-delete').first().click();
    await page.locator('.dmate-delete-confirm-delete').click();
    await page.waitForFunction(expected => ocrEditorController.getPages().length === expected, remaining - 1);
  }
  await settle(page);
  assert.deepEqual((await onlineState(page)).pages, [], 'Deleting the last page keeps this opening empty');
  assert.equal(await page.locator('.ddw-name').isDisabled(), true);
}

async function runGuestBlankLifecycle(browser) {
  const page = await onlinePage(browser, 390);
  try {
    await openOnline(page);
    await assertEditableBlank(page);
    await page.locator('.ddw-name').fill('游客已有空白页');
    const existing = await onlineState(page);
    for (let i = 0; i < 2; i++) {
      await closeOnline(page); await openOnline(page);
      assert.deepEqual(await onlineState(page), existing, 'An existing empty drawing is reused, not replaced or duplicated');
    }
    await deleteAllOnline(page);
    await closeOnline(page); await openOnline(page);
    const replacement = await assertEditableBlank(page);
    assert.notEqual(replacement.pages[0].id, existing.pages[0].id);
    await closeOnline(page); await openOnline(page);
    assert.deepEqual(await onlineState(page), replacement, 'Repeated reopening does not create more blank pages');
    assert.deepEqual(await page.evaluate(() => window.drawingStorageWrites), [], 'Guest drawings never write localStorage');
    assert.deepEqual(await page.evaluate(() => Object.keys(localStorage).filter(key => /^dmate:graph-(?:gallery|drawing)/.test(key))), []);
    await page.reload({ waitUntil: 'networkidle' }); await localPermissions(page); await openOnline(page);
    const refreshed = await assertEditableBlank(page);
    assert.notEqual(refreshed.pages[0].id, replacement.pages[0].id, 'Guest gallery does not survive refresh');
    assert.deepEqual(await page.evaluate(() => window.drawingStorageWrites), []);
    assert.equal(page.modelCalls, 0); assert.deepEqual(page.regressionErrors, []);
    console.log('PASS online guest: initial blank, same-open deletion stays empty, reopen creates one, saved blank reused, no persistent writes');
  } finally { await page.close(); }
}

async function runAccountGalleryLifecycle(browser) {
  const page = await onlinePage(browser), username = 'drawing-panels-local-fixture';
  const key = 'dmate:graph-gallery:v1::' + encodeURIComponent('account:' + username);
  try {
    await localPermissions(page, username);
    await page.evaluate(({ key, gallery }) => localStorage.setItem(key, JSON.stringify(gallery)), { key, gallery: { ...gallery, activeId: 'page-B' } });
    await openOnline(page);
    assert.equal((await onlineState(page)).name, names[1], 'Online entry restores selected existing drawing');
    assert.equal(await page.locator('.dge-overlay-node').count(), 2);
    assert.deepEqual((await onlineState(page)).pages.map(p => p.id), gallery.pages.map(p => p.id));
    await page.locator('.ddw-page-actions').getByRole('button', { name: '新建空白页', exact: true }).click();
    await page.locator('.ddw-name').fill('账号保存空白页');
    const saved = await onlineState(page);
    assert.equal(saved.pages.length, 4);
    assert.equal(saved.pages.at(-1).document.graphs[0].vertices.length, 0);
    await closeOnline(page); await openOnline(page);
    assert.deepEqual(await onlineState(page), saved, 'Reopening reuses all drawings and the selected saved blank page');
    await closeOnline(page); await page.reload({ waitUntil: 'networkidle' });
    await localPermissions(page, username); await openOnline(page);
    assert.deepEqual(await onlineState(page), saved, 'Account gallery contents and selected blank survive refresh');
    await (await history(page)).getByText(names[1], { exact: true }).click();
    const selected = await onlineState(page);
    await closeOnline(page); await page.reload({ waitUntil: 'networkidle' });
    await localPermissions(page, username); await openOnline(page);
    assert.deepEqual(await onlineState(page), selected, 'Existing nonempty drawing selection also survives refresh');
    await deleteAllOnline(page); await closeOnline(page);
    assert.deepEqual(await page.evaluate(key => JSON.parse(localStorage.getItem(key)).pages, key), []);
    // An empty gallery saved by an older version is normalized on opening.
    await page.evaluate(key => localStorage.setItem(key, JSON.stringify({ version: 1, activeId: '', pages: [] })), key);
    await page.reload({ waitUntil: 'networkidle' }); await localPermissions(page, username); await openOnline(page);
    const created = await assertEditableBlank(page);
    await closeOnline(page); await openOnline(page);
    assert.deepEqual(await onlineState(page), created, 'Legacy empty gallery receives only one persisted blank');
    assert.equal(page.modelCalls, 0); assert.deepEqual(page.regressionErrors, []);
    console.log('PASS online account local fixture: existing/selected drawings, saved blank, refresh, and legacy empty gallery');
  } finally { await page.close(); }
}

async function runDefaultEmptyContract(browser) {
  const page = await onlinePage(browser);
  try {
    const count = await page.evaluate(() => {
      const fixture = DMateDrawingWorkspace.mount(document.getElementById('graphEditorMount'), {
        persistent: false, sessionState: { gallery: JSON.stringify({ version: 2, activeId: '', pages: [] }) },
        legacyDocument: DMateDrawingWorkspace.blankDocument(), features: { ai: false, upload: false }
      });
      const count = fixture.getPages().length; fixture.destroy(); return count;
    });
    assert.equal(count, 0, 'Shared component without createBlankIfEmpty retains its offline zero-page contract');
    assert.equal(page.modelCalls, 0); assert.deepEqual(page.regressionErrors, []);
    console.log('PASS shared component: no opt-in flag preserves an empty gallery');
  } finally { await page.close(); }
}

async function runOfflineViewport(browser, width) {
  const page = await browser.newPage({ viewport: { width, height: width === 390 ? 740 : 900 },
    isMobile: width === 390, hasTouch: width === 390, serviceWorkers: 'block' });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  let modelCalls = 0;
  await page.route(/\/(?:chat|ocr|drawing\/[^?]+)(?:\?|$)/, route => { modelCalls++; return route.abort(); });
  try {
    await page.addInitScript(value => localStorage.setItem('dmate:offline:drawing-gallery:v1', JSON.stringify(value)), gallery);
    await page.goto(baseURL + '/offline', { waitUntil: 'networkidle' });
    await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
    if (width === 390) await page.locator('#offlineNavToggle').click();
    await page.locator('#graphDrawingBtn').click();
    await page.locator('#offlineDrawingHost .dge-overlay-viewport').waitFor();
    await settle(page);
    await viewportAndPopoverChecks(page, width === 390, 'offline-' + width, false);
    for (const kind of ['vertex', 'edge']) {
      if (kind === 'edge') await page.locator('.dge-selection-panel .dge-panel-close').click();
      await selectShape(page, kind, width === 390);
      const position = await panelPosition(page);
      await compactPanel(page, '.dge-selection-panel', width === 390);
      if (process.env.OFFLINE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/drawing-offline-' + width + '-' + kind + '.png' });
      console.log('PASS offline ' + width + ' ' + kind + ': ' + JSON.stringify(position) + '; last action reachable');
    }
    assert.equal(modelCalls, 0); assert.deepEqual(errors, []);
  } finally { await page.close(); }
}

(async () => {
  if (process.env.OFFLINE_SCREENSHOT_DIR) require('node:fs').mkdirSync(process.env.OFFLINE_SCREENSHOT_DIR, { recursive: true });
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const width of [390, 1440]) await runCase(browser, width);
    for (const width of [390, 1440]) await runOfflineViewport(browser, width);
    await runGuestBlankLifecycle(browser);
    await runAccountGalleryLifecycle(browser);
    await runDefaultEmptyContract(browser);
  }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
