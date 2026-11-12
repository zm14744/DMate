/* Real-app regression for mobile knowledge-graph fitting, selection and navigation.
 * Start the Flask app first. Set CHROMIUM_EXECUTABLE_PATH to use a system engine.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const near = (actual, expected, message, tolerance = 1.5) =>
  assert.ok(Math.abs(actual - expected) <= tolerance,
    message + ': ' + actual + ' vs ' + expected);

async function settleGraph(page) {
  await page.waitForFunction(() => {
    const viewport = document.querySelector('.kg-mobile-viewport');
    return viewport && viewport._kgScale && getComputedStyle(viewport).visibility === 'visible';
  });
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function snapshot(page) {
  return page.evaluate(() => {
    const viewport = document.querySelector('.kg-mobile-viewport');
    const stage = viewport.querySelector('.kg-mobile-stage');
    const rect = stage.getBoundingClientRect();
    const view = viewport.getBoundingClientRect();
    const css = getComputedStyle(viewport);
    const number = name => parseFloat(css[name]) || 0;
    const left = view.left + viewport.clientLeft + number('paddingLeft');
    const top = view.top + viewport.clientTop + number('paddingTop');
    const width = viewport.clientWidth - number('paddingLeft') - number('paddingRight');
    const height = viewport.clientHeight - number('paddingTop') - number('paddingBottom');
    const nodes = [...stage.querySelectorAll('.kg-mobile-node')].map(node => node.getBoundingClientRect());
    return {
      scale: viewport._kgScale,
      stage: { left: rect.left, top: rect.top, width: rect.width, height: rect.height },
      content: { left, top, width, height, right: left + width, bottom: top + height },
      scroll: { left: viewport.scrollLeft, top: viewport.scrollTop,
        width: viewport.scrollWidth, height: viewport.scrollHeight },
      nodes: { count: nodes.length, left: Math.min(...nodes.map(node => node.left)),
        top: Math.min(...nodes.map(node => node.top)), right: Math.max(...nodes.map(node => node.right)),
        bottom: Math.max(...nodes.map(node => node.bottom)) }
    };
  });
}

function checkCenteredAxes(state, label) {
  if (state.stage.width <= state.content.width + 1) {
    near(state.stage.left + state.stage.width / 2,
      state.content.left + state.content.width / 2, label + ': horizontal centering');
  }
  if (state.stage.height <= state.content.height + 1) {
    near(state.stage.top + state.stage.height / 2,
      state.content.top + state.content.height / 2, label + ': vertical centering');
  }
}

async function checkReachableEdges(page, label) {
  await page.locator('.kg-mobile-viewport').evaluate(view => { view.scrollLeft = 0; view.scrollTop = 0; });
  const start = await snapshot(page);
  assert.ok(start.nodes.left >= start.content.left - 1.5, label + ': first nodes clipped on left');
  assert.ok(start.nodes.top >= start.content.top - 1.5, label + ': first nodes clipped on top');
  assert.ok(start.nodes.left < start.content.right, label + ': left edge is not reachable');
  assert.ok(start.nodes.top < start.content.bottom, label + ': top edge is not reachable');
  await page.locator('.kg-mobile-viewport').evaluate(view => { view.scrollLeft = 1e7; view.scrollTop = 1e7; });
  const end = await snapshot(page);
  assert.ok(end.nodes.right <= end.content.right + 1.5, label + ': last nodes inaccessible on right');
  assert.ok(end.nodes.bottom <= end.content.bottom + 1.5, label + ': last nodes inaccessible below');
  assert.ok(end.nodes.right > end.content.left, label + ': horizontal scrolling overshoots graph');
  assert.ok(end.nodes.bottom > end.content.top, label + ': vertical scrolling overshoots graph');
}

async function fit(page) {
  await page.locator('.kg-mobile-zoom-fit').click();
  await settleGraph(page);
  return snapshot(page);
}

async function mobileCase(browser, width) {
  const page = await browser.newPage({ viewport: { width, height: 844 }, isMobile: true, hasTouch: true });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await page.evaluate(() => openKnowledgeGraph());
    await page.waitForSelector('.kg-mobile-entry-only');
    assert.equal(await page.locator('.kg-mobile-stage').count(), 0, 'Preview should keep only the full-view entry');
    await page.locator('.kg-mobile-expand').click();
    await settleGraph(page);
    const categories = await page.locator('#knowledgeGraphCategory option').evaluateAll(options => options.map(option => option.value));
    assert.ok(categories.length > 2, 'Expected real knowledge-graph categories');
    for (const category of categories) {
      const label = width + '/' + category;
      await page.evaluate(value => setKnowledgeGraphFilter(value), category);
      await settleGraph(page);
      const initial = await snapshot(page);
      assert.ok(initial.nodes.count > 0, label + ': category has no nodes');
      assert.ok(initial.scale >= .85 - .001, label + ': automatically fitted labels are too small');
      checkCenteredAxes(initial, label);
      await checkReachableEdges(page, label);
      await fit(page);
      await page.locator('.kg-mobile-zoom-btn').last().click();
      const zoomed = await snapshot(page);
      assert.ok(zoomed.scale > initial.scale, label + ': zoom-in does not change scale');
      await page.locator('.kg-mobile-zoom-btn').first().click();
      near((await snapshot(page)).scale, initial.scale, label + ': zoom-out reverses zoom-in', .0001);
      await page.locator('.kg-mobile-zoom-btn').last().click();
      const restored = await fit(page);
      near(restored.scale, initial.scale, label + ': Fit restores scale', .0001);
      checkCenteredAxes(restored, label + '/refit');
      console.log('PASS ' + label + ': ' + initial.nodes.count + ' nodes, fit ' + Math.round(initial.scale * 100) + '%');
    }

    // A manual zoom must survive viewport resize. Explicit Fit resumes automatic fitting.
    await page.evaluate(() => setKnowledgeGraphFilter('全部'));
    await settleGraph(page);
    await page.locator('.kg-mobile-zoom-btn').last().click();
    await page.locator('.kg-mobile-viewport').evaluate(view => {
      view.scrollLeft = (view.scrollWidth - view.clientWidth) / 2;
      view.scrollTop = (view.scrollHeight - view.clientHeight) / 2;
    });
    const manual = await snapshot(page);
    const centerPoint = state => ({
      x: (state.content.left + state.content.width / 2 - state.stage.left) / state.scale,
      y: (state.content.top + state.content.height / 2 - state.stage.top) / state.scale
    });
    const alternateWidth = width === 390 ? 620 : 390;
    await page.setViewportSize({ width: alternateWidth, height: 844 });
    await settleGraph(page);
    const resizedManual = await snapshot(page);
    near(resizedManual.scale, manual.scale, width + ': resize preserves manual zoom', .0001);
    near(centerPoint(resizedManual).x, centerPoint(manual).x, width + ': resize preserves horizontal graph center');
    near(centerPoint(resizedManual).y, centerPoint(manual).y, width + ': resize preserves vertical graph center');
    await fit(page);
    await page.setViewportSize({ width, height: 600 });
    await settleGraph(page);
    const automatic = await snapshot(page);
    const explicit = await fit(page);
    near(automatic.scale, explicit.scale, width + ': resize automatically refits', .0001);
    checkCenteredAxes(automatic, width + '/resize');
    await page.setViewportSize({ width, height: 844 });
    await settleGraph(page);
    const originalViewport = await snapshot(page);
    const originalExplicit = await fit(page);
    near(originalViewport.scale, originalExplicit.scale, width + ': height restoration refits', .0001);
    await page.setViewportSize({ width: 820, height: 844 });
    await page.waitForSelector('.kg-desktop-zoom-stage');
    assert.equal(await page.locator('.kg-mobile-stage').count(), 0, 'Breakpoint must replace the mobile graph');
    await page.setViewportSize({ width, height: 844 });
    await settleGraph(page);
    assert.equal(await page.locator('.kg-desktop-zoom-stage').count(), 0, 'Breakpoint must restore the mobile graph');
    checkCenteredAxes(await snapshot(page), width + '/breakpoint');
    assert.deepEqual(errors, [], width + ': page errors');
    console.log('PASS ' + width + ': resize, manual zoom and fit lifecycle');
  } finally { await page.close(); }
}

async function checkSelectionBorder(browser, theme) {
  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const desktop = await browser.newPage({ viewport: { width: 1024, height: 844 } });
  const errors = [];
  mobile.on('pageerror', error => errors.push(error.message));
  desktop.on('pageerror', error => errors.push(error.message));
  try {
    for (const page of [mobile, desktop]) {
      await page.goto(baseURL, { waitUntil: 'networkidle' });
      await page.evaluate(value => {
        document.documentElement.dataset.appearanceTheme = value;
        document.body.dataset.appearanceTheme = value;
        openKnowledgeGraph();
      }, theme);
      await page.waitForSelector('#knowledgeGraphCanvas .kg-section');
      await page.evaluate(() => setKnowledgeGraphFilter('证明与归纳'));
    }
    await mobile.locator('.kg-mobile-expand').click();
    await settleGraph(mobile);
    const accent = await mobile.evaluate(() => {
      const probe = document.createElement('span');
      probe.style.color = 'var(--accent)';
      document.body.appendChild(probe);
      const color = getComputedStyle(probe).color;
      probe.remove();
      return color;
    });
    const scale = (await snapshot(mobile)).scale;
    const firstName = await mobile.locator('.kg-mobile-node:not(.selected)').first().getAttribute('aria-label');
    const first = mobile.locator('.kg-mobile-stage').getByRole('button', { name: firstName, exact: true });
    await first.tap();
    assert.equal(await mobile.locator('.kg-mobile-node.selected').count(), 1, theme + ': only one node selected');
    assert.equal(await first.evaluate(node => node.classList.contains('selected')), true);
    const secondName = await mobile.locator('.kg-mobile-node:not(.selected)').first().getAttribute('aria-label');
    const second = mobile.locator('.kg-mobile-stage').getByRole('button', { name: secondName, exact: true });
    await second.tap();
    assert.equal(await first.evaluate(node => node.classList.contains('selected')), false, theme + ': previous node deselected');
    assert.equal(await second.evaluate(node => node.classList.contains('selected')), true);
    assert.equal(await mobile.locator('.kg-mobile-node.selected').count(), 1);
    const border = await second.evaluate(node => {
      const style = getComputedStyle(node);
      return { color: style.borderTopColor, width: parseFloat(style.borderTopWidth) };
    });
    assert.equal(border.color, accent, theme + ': tapped node must have a visible accent border');
    assert.ok(border.width >= 3, theme + ': selection border must remain prominent');
    near((await snapshot(mobile)).scale, scale, theme + ': node selection preserves zoom', .0001);
    // The shared focus layer can hide shadows while focused; the selection ring
    // must remain after focus moves away from the selected node.
    await second.evaluate(node => node.blur());
    assert.notEqual(await second.evaluate(node => getComputedStyle(node).boxShadow), 'none', theme + ': selected node ring');
    await desktop.locator('.kg-node-group:not(.selected)').first().click();
    const desktopStroke = await desktop.locator('.kg-node-group.selected rect').evaluate(rect => getComputedStyle(rect).stroke);
    assert.equal(border.color, desktopStroke, theme + ': mobile border matches desktop selection stroke');
    if (process.env.KG_SCREENSHOT_DIR) {
      await mobile.screenshot({ path: process.env.KG_SCREENSHOT_DIR + '/graph-selection-after-390-' + theme + '.png' });
    }
    assert.deepEqual(errors, [], theme + ': selection page errors');
    console.log('PASS ' + theme + ': mobile node taps switch the accent border, matching desktop');
  } finally { await mobile.close(); await desktop.close(); }
}

async function checkNodeGestures(browser, width) {
  const page = await browser.newPage({ viewport: { width, height: 844 }, isMobile: true, hasTouch: true });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await page.evaluate(() => openKnowledgeGraph());
    await page.waitForSelector('.kg-mobile-entry-only');
    // Exercise the actual module picker before testing the graph's gesture area.
    await page.locator('#knowledgeGraphCategoryTrigger').tap();
    await page.waitForSelector('#mobileChoiceModal[open]');
    await page.locator('.mobile-choice-option').filter({ hasText: '证明与归纳' }).tap();
    await page.waitForFunction(() => document.getElementById('knowledgeGraphCategory').value === '证明与归纳');
    assert.equal(await page.locator('#mobileChoiceModal').evaluate(modal => modal.open), false);
    await page.locator('.kg-mobile-expand').tap();
    await settleGraph(page);
    await page.evaluate(() => {
      const selectNode = selectKnowledgeGraphNode;
      window.graphSelectionCount = 0;
      window.selectKnowledgeGraphNode = (...args) => {
        window.graphSelectionCount++;
        return selectNode(...args);
      };
    });
    const cdp = await page.context().newCDPSession(page);
    const touch = (type, points) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints: points });
    const selectedName = () => page.locator('.kg-mobile-node.selected').getAttribute('aria-label');
    const nodePoint = () => page.evaluate(() => {
      const view = document.querySelector('.kg-mobile-viewport').getBoundingClientRect();
      const node = [...document.querySelectorAll('.kg-mobile-node:not(.selected)')].find(candidate => {
        const rect = candidate.getBoundingClientRect();
        const x = rect.left + rect.width / 2, y = rect.top + rect.height / 2;
        return x > view.left + 8 && x < view.right - 8 && y > view.top + 8 && y < view.bottom - 80;
      });
      if (!node) throw new Error('No visible unselected knowledge node');
      const rect = node.getBoundingClientRect();
      return { name: node.getAttribute('aria-label'), x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    });
    const nativeTap = async (point, dx = 0, dy = 0) => {
      const count = await page.evaluate(() => window.graphSelectionCount);
      await touch('touchStart', [{ id: 1, x: point.x, y: point.y }]);
      if (dx || dy) await touch('touchMove', [{ id: 1, x: point.x + dx, y: point.y + dy }]);
      await touch('touchEnd', []);
      await page.waitForFunction(name => document.querySelector('.kg-mobile-node.selected')?.getAttribute('aria-label') === name,
        point.name, { timeout: 2000 });
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
      assert.equal(await page.evaluate(() => window.graphSelectionCount), count + 1,
        width + ': one tap must activate exactly once');
    };
    let point = await nodePoint();
    await page.mouse.click(point.x, point.y);
    assert.equal(await selectedName(), point.name, width + ': mouse click must reach the node');
    assert.equal(await page.evaluate(() => window.graphSelectionCount), 1, width + ': one mouse click must activate once');
    for (const [dx, dy] of [[3, 2], [-4, 0]]) {
      point = await nodePoint();
      const before = await snapshot(page);
      await nativeTap(point, dx, dy);
      const after = await snapshot(page);
      near(after.scroll.left, before.scroll.left, width + ': finger jitter must not pan horizontally', .5);
      near(after.scroll.top, before.scroll.top, width + ': finger jitter must not pan vertically', .5);
    }

    await fit(page);
    // Enlarge this small module so both tested widths have a real pan range.
    for (let index = 0; index < 3; index++) await page.locator('.kg-mobile-zoom-btn').last().click();
    point = await nodePoint();
    const beforeDrag = await selectedName();
    const beforeDragCount = await page.evaluate(() => window.graphSelectionCount);
    const oldLeft = (await snapshot(page)).scroll.left;
    await touch('touchStart', [{ id: 1, x: point.x, y: point.y }]);
    await touch('touchMove', [{ id: 1, x: point.x - 24, y: point.y }]);
    await touch('touchEnd', []);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
    assert.equal(await selectedName(), beforeDrag, width + ': dragging must not select the pressed node');
    assert.equal(await page.evaluate(() => window.graphSelectionCount), beforeDragCount, width + ': drag must not activate a node');
    assert.ok((await snapshot(page)).scroll.left > oldLeft, width + ': horizontal drag must pan the graph');
    await nativeTap(await nodePoint()); // A new tap must work without a cooldown after dragging.

    await fit(page);
    const beforePinch = (await snapshot(page)).scale;
    const beforePinchCount = await page.evaluate(() => window.graphSelectionCount);
    const center = await page.locator('.kg-mobile-viewport').evaluate(view => {
      const rect = view.getBoundingClientRect();
      return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    });
    await touch('touchStart', [{ id: 1, x: center.x - 30, y: center.y }, { id: 2, x: center.x + 30, y: center.y }]);
    await touch('touchMove', [{ id: 1, x: center.x - 45, y: center.y }, { id: 2, x: center.x + 45, y: center.y }]);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
    await touch('touchEnd', []);
    assert.ok((await snapshot(page)).scale > beforePinch, width + ': native pinch must zoom');
    assert.equal(await page.evaluate(() => window.graphSelectionCount), beforePinchCount, width + ': pinch must not activate a node');
    await nativeTap(await nodePoint()); // Pinch suppression must not swallow the next distinct tap.
    assert.deepEqual(errors, [], width + ': gesture page errors');
    console.log('PASS ' + width + ': module picker, mouse click, touch jitter, drag and pinch followed by fresh taps');
  } finally { await page.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const width of [390, 620]) await checkNodeGestures(browser, width);
    for (const theme of ['light', 'dark', 'navy']) await checkSelectionBorder(browser, theme);
    for (const width of [390, 620]) await mobileCase(browser, width);
    const page = await browser.newPage({ viewport: { width: 820, height: 844 } });
    try {
      await page.goto(baseURL, { waitUntil: 'networkidle' });
      await page.evaluate(() => openKnowledgeGraph());
      await page.waitForSelector('.kg-desktop-zoom-stage');
      assert.equal(await page.locator('.kg-mobile-stage').count(), 0);
      assert.ok(await page.locator('.kg-node-group').count() > 20);
      await page.locator('#knowledgeGraphDesktopZoomFit').click();
      assert.ok(await page.locator('.kg-desktop-zoom-stage').isVisible());
      console.log('PASS 820: desktop graph branch');
    } finally { await page.close(); }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
