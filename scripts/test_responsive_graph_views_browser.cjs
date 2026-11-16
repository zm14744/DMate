/* Real responsive-layout round trips: first fit, then retain each camera.
 * Start Flask first. Neither model services nor real accounts are used.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const dimensions = { desktop: { width: 1440, height: 900 }, mobile: { width: 390, height: 844 } };
const username = 'responsive-view-local-fixture';
const gallery = { version: 2, activeId: 'responsive-A', pages: ['A', 'B'].map((name, index) => ({
  id: 'responsive-' + name, name: '视图测试 ' + name, createdAt: index + 1, updatedAt: index + 1,
  document: { body_text: '', graphs: [{ id: 'G1', name: '视图测试 ' + name, directed: false, weighted: false,
    vertices: [{ id: 'v1', label: name + '1', x: .16, y: .17 },
      { id: 'v2', label: name + '2', x: .83, y: .82 }],
    edges: [{ id: 'e1', from: 'v1', to: 'v2', direction: 'undirected', style: 'solid' }] }] }
})) };
const isMobile = page => page.viewportSize().width <= 760;
const near = (actual, expected, label, tolerance = 1.5) => assert.ok(Number.isFinite(actual)
  && Math.abs(actual - expected) <= tolerance, label + ': ' + actual + ' vs ' + expected);

async function settle(page) {
  await page.evaluate(async () => {
    const frame = () => new Promise(resolve => requestAnimationFrame(resolve));
    await frame(); await frame();
    await Promise.all(document.getAnimations().filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity)
      .map(animation => animation.finished.catch(() => {})));
    await frame(); await frame();
  });
}

async function offlinePanel(page, panel) {
  const toggle = page.locator(page.viewportSize().width <= 1100 ? '#offlineNavToggle' : '#offlineDesktopSidebarOpen');
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
  await page.locator('.offline-nav-item[data-panel="' + panel + '"]').click();
  await page.locator('#' + panel + 'Panel').waitFor({ state: 'visible' });
  await settle(page);
}

async function pageFixture(browser, kind, offline, startingMode) {
  const context = await browser.newContext({ viewport: dimensions[startingMode], hasTouch: true, serviceWorkers: 'block' });
  const page = await context.newPage(), errors = [];
  let modelCalls = 0;
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/auth/me', route => route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ configured: true, authenticated: false }) }));
  await page.route(/\/(?:chat|ocr|drawing\/[^?]+)(?:\?|$)/, route => { modelCalls++; return route.abort(); });
  await page.addInitScript(({ offline, key, gallery }) => {
    localStorage.setItem('dmate:offline:appearance:v1', JSON.stringify({ mode: 'dark', accent: 'blue', panelOpacity: 100 }));
    localStorage.setItem(offline ? 'dmate:offline:drawing-gallery:v1' : key, JSON.stringify(gallery));
  }, { offline, key: 'dmate:graph-gallery:v1::' + encodeURIComponent('account:' + username), gallery });
  await page.goto(baseURL + (offline ? '/offline' : ''), { waitUntil: 'networkidle' });
  if (offline) {
    await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
    assert.equal(await page.locator('#conceptsPanel .toolbar-muted,#questionsPanel .toolbar-muted').count(), 0,
      'Removed library heading hints stay absent');
    await offlinePanel(page, kind === 'drawing' ? 'drawing' : 'graph');
  } else {
    await page.waitForFunction(() => document.documentElement.dataset.accountStateKnown === '1');
    await page.evaluate(username => {
      stopCloudLivePolling(); accountState.authenticated = true; accountState.username = username;
    }, username);
    await page.evaluate(kind => kind === 'drawing' ? openGraphDrawing() : openKnowledgeGraph(), kind);
  }
  return { page, context, errors, calls: () => modelCalls };
}

function view(page, kind) {
  return page.locator(kind === 'drawing' ? '.dge-overlay-viewport'
    : isMobile(page) ? '.kg-mobile-viewport' : '.kg-desktop-viewport');
}

function controls(page, kind, action) {
  if (kind === 'drawing') return page.locator('[data-overlay-tool="zoom-' + action + '"]');
  if (!isMobile(page)) return page.locator('#knowledgeGraphDesktopZoom' + ({ in: 'In', out: 'Out', fit: 'Fit' }[action]));
  return page.locator(action === 'fit' ? '.kg-mobile-zoom-fit' : '.kg-mobile-zoom-btn').nth(action === 'in' ? 1 : 0);
}

async function ready(page, kind) {
  if (kind === 'drawing') {
    const history = page.locator('.ddw-page-actions > button[aria-expanded="true"]');
    if (await history.count()) await history.click();
    await page.locator('.dge-overlay[data-geometry-ready="true"]').waitFor();
    await page.waitForFunction(() => {
      const dialog = document.getElementById('graphEditorDialog');
      return !dialog?.open || !dialog.dataset.positioning;
    });
  } else {
    const modal = page.locator('#knowledgeGraphModal');
    if (isMobile(page) && !await modal.evaluate(node => node.classList.contains('graph-fullscreen-view'))) {
      await modal.locator('.kg-mobile-expand').click();
    }
    await view(page, kind).waitFor({ state: 'visible' });
    await page.waitForFunction(() => {
      const viewport = document.querySelector('.kg-mobile-viewport');
      return !viewport || (viewport._kgScale > 0 && getComputedStyle(viewport).visibility !== 'hidden');
    });
  }
  await settle(page);
}

async function camera(page, kind) {
  return view(page, kind).evaluate((viewport, kind) => {
    const stage = viewport.querySelector(kind === 'drawing' ? '.dge-overlay-stage'
      : '.kg-mobile-stage,.kg-desktop-zoom-stage');
    const scale = kind === 'drawing' ? parseFloat(document.querySelector('.dge-overlay-zoom').textContent) / 100
      : viewport._kgScale || Number(viewport.querySelector('.kg-desktop-zoom-surface')?.dataset.scale);
    const v = viewport.getBoundingClientRect(), s = stage.getBoundingClientRect();
    const nodes = [...stage.querySelectorAll(kind === 'drawing' ? '.dge-overlay-dot' : '.kg-mobile-node,.kg-node-group')];
    return { scale, left: viewport.scrollLeft, top: viewport.scrollTop,
      size: [viewport.clientWidth, viewport.clientHeight],
      center: [(v.left + viewport.clientLeft + viewport.clientWidth / 2 - s.left) / scale,
        (v.top + viewport.clientTop + viewport.clientHeight / 2 - s.top) / scale],
      nodeCenters: nodes.slice(0, 3).map(node => { const box = node.getBoundingClientRect();
        return [box.left + box.width / 2 - v.left, box.top + box.height / 2 - v.top]; }) };
  }, kind);
}

function sameCamera(actual, expected, label) {
  near(actual.scale, expected.scale, label + ' scale', .0002);
  for (const key of ['left', 'top']) near(actual[key], expected[key], label + ' ' + key, 2);
  assert.equal(actual.nodeCenters.length, expected.nodeCenters.length, label + ' node count');
  actual.nodeCenters.forEach((point, i) => point.forEach((value, axis) =>
    near(value, expected.nodeCenters[i][axis], label + ' visible node position ' + i + '/' + axis, 2)));
}

async function firstFit(page, kind, label) {
  await ready(page, kind);
  const initial = await camera(page, kind);
  await controls(page, kind, 'fit').click(); await settle(page);
  sameCamera(await camera(page, kind), initial, label + ': first entry already matches Adapt');
  return initial;
}

async function customize(page, kind, variant) {
  // Use real controls so the engine records a deliberate camera change.
  for (let i = 0; i < (kind === 'drawing' ? 8 : 5); i++) {
    const plus = controls(page, kind, 'in'); if (!await plus.isEnabled()) break;
    await plus.click();
  }
  await settle(page);
  await view(page, kind).evaluate((viewport, variant) => {
    viewport.scrollLeft = Math.round((viewport.scrollWidth - viewport.clientWidth) * (variant ? .67 : .31));
    viewport.scrollTop = Math.round((viewport.scrollHeight - viewport.clientHeight) * (variant ? .61 : .37));
  }, variant);
  await settle(page);
  const current = await camera(page, kind);
  assert.ok(current.left > 0 || current.top > 0, 'The camera fixture is actually panned');
  return current;
}

async function resize(page, kind, mode) {
  await page.setViewportSize(dimensions[mode]);
  await settle(page);
  await ready(page, kind);
}

async function sameModeEdgeResize(page, mode, label) {
  await view(page, 'graph').evaluate(viewport => { viewport.scrollLeft = 1e7; viewport.scrollTop = 1e7; });
  await settle(page);
  const edge = await camera(page, 'graph');
  await page.setViewportSize({ ...dimensions[mode], width: dimensions[mode].width + (mode === 'desktop' ? 160 : 40) });
  await settle(page);
  await ready(page, 'graph');
  await resize(page, 'graph', mode);
  sameCamera(await camera(page, 'graph'), edge, label + ': same-layout edge camera survives temporary viewport growth');
  return edge;
}

async function reopen(page, kind, offline) {
  if (offline) {
    if (kind === 'graph' && await page.locator('#knowledgeGraphModal').evaluate(node => node.classList.contains('graph-fullscreen-view'))) {
      await page.locator('.kg-mobile-expand').click(); await settle(page);
    }
    await offlinePanel(page, 'concepts');
    await offlinePanel(page, kind === 'graph' ? 'graph' : 'drawing');
  } else if (kind === 'drawing') {
    await page.locator('#graphEditorClose').click();
    await page.waitForFunction(() => !document.getElementById('graphEditorDialog').open && ocrEditorController === null);
    await page.evaluate(() => openGraphDrawing());
  } else {
    await page.evaluate(() => { closeKnowledgeGraph(); openKnowledgeGraph(); });
  }
  await ready(page, kind);
}

async function drawingPageRoundTrip(page, expected, label) {
  const openHistory = async () => {
    const button = page.locator('.ddw-page-actions').getByRole('button', { name: '历史绘图', exact: true });
    if (await button.getAttribute('aria-expanded') !== 'true') await button.click();
  };
  await openHistory();
  await page.locator('.ddw-history-open').getByText('视图测试 B', { exact: true }).click();
  await firstFit(page, 'drawing', label + ' second page');
  await customize(page, 'drawing', 1);
  await openHistory();
  await page.locator('.ddw-history-open').getByText('视图测试 A', { exact: true }).click();
  await ready(page, 'drawing');
  sameCamera(await camera(page, 'drawing'), expected, label + ': returning drawing keeps its own camera');
}

async function runCase(browser, kind, offline, first) {
  const { page, context, errors, calls } = await pageFixture(browser, kind, offline, first);
  const other = first === 'desktop' ? 'mobile' : 'desktop';
  const label = (offline ? 'offline' : 'online') + '/' + kind + '/' + first + '-first';
  try {
    const initial = await firstFit(page, kind, label + '/' + first);
    const remembered = { [first]: await customize(page, kind, 0) };
    assert.notEqual(remembered[first].scale, initial.scale, label + ': first camera really changed');
    if (kind === 'graph') remembered[first] = await sameModeEdgeResize(page, first, label);
    await resize(page, kind, other);
    const otherFit = await firstFit(page, kind, label + '/' + other);
    remembered[other] = await customize(page, kind, 1);
    assert.notEqual(remembered[other].scale, otherFit.scale, label + ': second camera really changed');
    for (const mode of [first, other, first]) {
      await resize(page, kind, mode);
      sameCamera(await camera(page, kind), remembered[mode], label + ': returning ' + mode);
    }
    await reopen(page, kind, offline);
    sameCamera(await camera(page, kind), remembered[first], label + ': close/panel return');
    if (kind === 'drawing') await drawingPageRoundTrip(page, remembered[first], label);
    // Explicit Adapt is still an action, not a permanently forced camera mode.
    await controls(page, kind, 'fit').click(); await settle(page);
    const adapted = await camera(page, kind);
    assert.notEqual(adapted.scale, remembered[first].scale, label + ': Adapt still resets custom zoom');
    await resize(page, kind, other); await resize(page, kind, first);
    sameCamera(await camera(page, kind), adapted, label + ': manually adapted view is retained');
    assert.equal(calls(), 0, label + ': responsive views never call a model');
    assert.deepEqual(errors, [], label + ': no page errors');
    console.log('PASS ' + label + ': first-fit, independent desktop/mobile cameras, return/reopen and explicit Adapt');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    const kinds = process.env.DMATE_RESPONSIVE_TEST_KIND ? [process.env.DMATE_RESPONSIVE_TEST_KIND] : ['graph', 'drawing'];
    assert.ok(kinds.every(kind => ['graph', 'drawing'].includes(kind)), 'The requested test component exists');
    for (const kind of kinds) for (const offline of [false, true]) {
      for (const first of ['desktop', 'mobile']) await runCase(browser, kind, offline, first);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
