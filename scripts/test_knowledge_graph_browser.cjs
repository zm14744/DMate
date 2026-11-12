/* Real-app regression for mobile knowledge-graph fitting and navigation.
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

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
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
