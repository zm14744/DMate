/* Sample the actual graph on every animation frame. Only data availability is
 * delayed; graph rendering, selection, fitting and view restoration stay real.
 */
'use strict';
const assert = require('node:assert/strict');
const { revealInterface } = require('./offline-vault-browser-fixtures.cjs');
const { writeFileSync } = require('node:fs');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
let lastTrace = null;
const mobile = page => page.viewportSize().width <= 760;
const viewportSelector = page => mobile(page) ? '.kg-mobile-viewport' : '.kg-desktop-viewport';
const near = (a, b, label, tolerance = 1.5) => assert.ok(Number.isFinite(a) && Number.isFinite(b)
  && Math.abs(a - b) <= tolerance, label + ': ' + a + ' / ' + b);

function installFrameProbe() {
  const visible = node => {
    if (!node || !node.isConnected || !node.getClientRects().length) return false;
    const bounds = node.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return false;
    for (let parent = node; parent; parent = parent.parentElement) {
      const css = getComputedStyle(parent);
      if (css.display === 'none' || css.visibility === 'hidden' || css.visibility === 'collapse' || Number(css.opacity) === 0) return false;
    }
    return true;
  };
  const rect = node => {
    if (!node) return null;
    const box = node.getBoundingClientRect();
    return [box.x, box.y, box.width, box.height];
  };
  const capture = () => {
    const modal = document.getElementById('knowledgeGraphModal'), shown = visible(modal);
    const card = modal?.querySelector('.graph-modal-card') || modal;
    const canvas = document.getElementById('knowledgeGraphCanvas');
    const viewport = canvas?.querySelector('.kg-mobile-viewport,.kg-desktop-viewport');
    const nodeList = [...(canvas?.querySelectorAll('.kg-mobile-node,.kg-node-group') || [])];
    const selected = nodeList.find(node => node.classList.contains('selected')) || nodeList[0];
    const label = modal?.querySelector(viewport?.classList.contains('kg-mobile-viewport')
      ? '.kg-mobile-zoom-label' : '#knowledgeGraphDesktopZoomLabel');
    const loading = shown ? [...modal.querySelectorAll('.kg-empty,.wrong-empty,.offline-loading,[role="status"]')]
      .filter(visible).map(node => node.textContent.trim()).filter(text => /准备中|加载中|正在加载|preparing|loading/i.test(text)) : [];
    return { shown, fullscreen: Boolean(modal?.classList.contains('graph-fullscreen-view')),
      mode: modal?.dataset.graphView || '', ready: modal?.dataset.graphReady || '',
      modal: shown ? rect(modal) : null, card: shown ? rect(card) : null,
      canvas: shown ? rect(canvas) : null, loading,
      entry: shown && visible(canvas?.querySelector('.kg-mobile-expand')) ? rect(canvas.querySelector('.kg-mobile-expand')) : null,
      nodeCount: nodeList.length, viewportShown: shown && visible(viewport),
      viewport: shown && visible(viewport) ? rect(viewport) : null,
      scale: viewport?._kgScale || Number(viewport?.querySelector('.kg-desktop-zoom-surface')?.dataset.scale) || 0,
      scroll: viewport ? [viewport.scrollLeft, viewport.scrollTop] : null,
      selectedId: selected?.dataset.nodeId || '', selected: shown && visible(viewport) ? rect(selected) : null,
      first: shown && visible(viewport) ? rect(nodeList[0]) : null,
      zoomLabel: shown && visible(label) ? label.textContent.trim() : null };
  };
  window.graphOpeningProbe = { samples: [], running: false, capture,
    start() {
      this.samples = []; this.running = true;
      const tick = () => { if (!this.running) return; this.samples.push(capture()); this.frame = requestAnimationFrame(tick); };
      this.frame = requestAnimationFrame(tick);
    },
    stop() { this.running = false; cancelAnimationFrame(this.frame); return this.samples; }
  };
  if (location.pathname === '/offline') {
    document.addEventListener('DOMContentLoaded', () => window.graphOpeningProbe.start(), { once: true });
  }
}

const frames = (page, count = 24) => page.evaluate(count => new Promise(resolve => {
  const next = () => count-- > 0 ? requestAnimationFrame(next) : resolve(); next();
}), count);
const start = page => page.evaluate(() => graphOpeningProbe.start());
const stop = page => page.evaluate(() => graphOpeningProbe.stop());
const snapshot = page => page.evaluate(() => graphOpeningProbe.capture());

function sameRect(actual, expected, label) {
  assert.ok(actual && expected, label + ': measurable geometry');
  actual.forEach((value, index) => near(value, expected[index], label + '/' + index));
}

const relative = (box, origin) => box && origin ? [box[0] - origin[0], box[1] - origin[1], box[2], box[3]] : null;

function stableTrace(trace, label, { fullscreen = false, mode = 'full', nodes = null, graph = true } = {}) {
  lastTrace = { label, trace };
  assert.ok(trace.length >= 12, label + ': sampled multiple painted frames');
  for (const sample of trace) assert.deepEqual(sample.loading, [], label + ': no visible preparation/loading page');
  const matching = trace.filter(sample => sample.shown && sample.fullscreen === fullscreen
    && sample.mode === mode && (nodes === null || sample.nodeCount === nodes));
  assert.ok(matching.length >= 8, label + ': expected graph presentation became visible');
  const last = matching.at(-1);
  for (const sample of matching) {
    sameRect(sample.modal, last.modal, label + ': stable modal');
    sameRect(sample.card, last.card, label + ': stable card origin and dimensions');
    sameRect(relative(sample.canvas, sample.card), relative(last.canvas, last.card), label + ': stable canvas layout');
    if (sample.zoomLabel !== null) assert.equal(sample.zoomLabel, last.zoomLabel, label + ': no visible provisional zoom percentage');
  }
  if (graph) {
    const shown = matching.filter(sample => sample.viewportShown);
    assert.ok(shown.length >= 8 && last.viewportShown, label + ': graph viewport was actually visible');
    for (const sample of shown) {
      near(sample.scale, last.scale, label + ': first visible scale matches settled scale', .0001);
      assert.equal(sample.selectedId, last.selectedId, label + ': selection stays stable');
      sameRect(relative(sample.viewport, sample.card), relative(last.viewport, last.card), label + ': stable viewport layout');
      for (const key of ['selected', 'first']) sameRect(relative(sample[key], sample.viewport),
        relative(last[key], last.viewport), label + ': stable ' + key + ' inside viewport');
      sample.scroll.forEach((value, index) => near(value, last.scroll[index], label + ': no late camera scroll/' + index, 2));
    }
  } else {
    assert.ok(last.entry, label + ': mobile complete-view entry exists');
    for (const sample of matching) sameRect(relative(sample.entry, sample.card), relative(last.entry, last.card), label + ': stable complete-view entry');
  }
  return last;
}

async function ready(page, graph = true) {
  await page.waitForFunction(graph => {
    const modal = document.getElementById('knowledgeGraphModal');
    if (!modal || modal.classList.contains('hidden') || modal.dataset.graphReady !== 'true') return false;
    if (!graph) return Boolean(modal.querySelector('.kg-mobile-expand'));
    const view = modal.querySelector('.kg-mobile-viewport,.kg-desktop-viewport');
    return view?.dataset.kgReady === 'true' && getComputedStyle(view).visibility !== 'hidden';
  }, graph);
}

async function fixture(browser, width, offline = false) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block',
    ...(width <= 760 ? { isMobile: true, hasTouch: true } : {}) });
  await context.addInitScript(installFrameProbe);
  const page = await context.newPage(), errors = [], indexing = [], modelCalls = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/auth/me', route => route.fulfill({ contentType: 'application/json', body: '{"configured":true,"authenticated":false}' }));
  // The unanswered route would expose any accidental open-time reindex wait.
  await page.route('**/analyze-questions', route => { indexing.push(route.request().url()); return new Promise(() => {}); });
  await page.route('**/chat', route => { modelCalls.push(route.request().url()); return route.abort(); });
  await page.goto(baseURL + (offline ? '/offline' : ''), { waitUntil: 'networkidle' });
  if (offline) {
    await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
    await revealInterface(page);
  }
  else await page.evaluate(() => {
    newChat();
    const question = '判断命题 p 与 q 的合取在什么情况下为真。';
    const teaching = { category: '命题逻辑', knowledge_points: ['逻辑联结词'], focus_points: ['逻辑联结词'],
      question_graph: { version: 1,classifier_revision:'catalog-semantic-v5',classification_status:'semantic',classification_source:'catalog_semantic',needs_review:false, sources: { question, solution: '' },
        nodes: [{ id: 'logic_connectives', evidence: [{ source: 'question', quote: '合取' }] }], edges: [] } };
    getCurrent().messages = [{ role: 'user', text: question, manualIsQuestion: true, questionTeaching: teaching }];
    getCurrent().teaching = teaching; getCurrent().learningQuestion = null;
  });
  return { page, context, errors, indexing, modelCalls };
}

async function gatedData(page) {
  await page.evaluate(() => {
    const original = ensureKnowledgeGraphData;
    window.releaseGraphData = null;
    ensureKnowledgeGraphData = () => new Promise(resolve => {
      window.releaseGraphData = async () => { const data = await original(); resolve(data); };
    });
    window.restoreGraphData = () => { ensureKnowledgeGraphData = original; };
    knowledgeGraphData = null;
  });
}

async function fullView(page, label, nodes = null) {
  if (!mobile(page)) return;
  const fullscreen = await page.locator('#knowledgeGraphModal').evaluate(modal => modal.classList.contains('graph-fullscreen-view'));
  if (!fullscreen) {
    await start(page); await page.locator('.kg-mobile-expand').click();
    await ready(page); await frames(page);
    stableTrace(await stop(page), label, { fullscreen: true, nodes });
  }
}

async function customize(page) {
  const plus = page.locator(mobile(page) ? '.kg-mobile-zoom-btn' : '#knowledgeGraphDesktopZoomIn');
  for (let index = 0; index < 4; index++) await (mobile(page) ? plus.last() : plus).click();
  await page.locator(viewportSelector(page)).evaluate(view => { view.scrollLeft = 65; view.scrollTop = 120; });
  await frames(page, 4);
  return snapshot(page);
}

function remembered(actual, expected, label) {
  near(actual.scale, expected.scale, label + ': remembered scale', .0001);
  actual.scroll.forEach((value, index) => near(value, expected.scroll[index], label + ': remembered scroll/' + index, 2));
  sameRect(actual.selected, expected.selected, label + ': remembered selected-node position');
}

async function onlineCase(browser, width) {
  const { page, context, errors, indexing, modelCalls } = await fixture(browser, width);
  try {
    await gatedData(page); await start(page);
    await page.evaluate(() => { void openKnowledgeGraph(); });
    await frames(page, 18);
    assert.equal((await snapshot(page)).shown, false, 'Cold data preparation keeps the previous page visible');
    await page.evaluate(() => releaseGraphData());
    await ready(page, !mobile(page)); await frames(page);
    const initialCount = await page.evaluate(() => knowledgeGraphData.nodes.length);
    stableTrace(await stop(page), 'online/' + width + '/cold all knowledge',
      { nodes: mobile(page) ? 0 : initialCount, graph: !mobile(page) });
    assert.equal(await page.locator('#knowledgeGraphSideTabs').isVisible(), false,
      'The initial all-knowledge graph has only node details');
    await page.evaluate(() => restoreGraphData());

    await start(page); await page.locator('#knowledgeGraphScopeBtn').click();
    await ready(page, !mobile(page)); await frames(page);
    stableTrace(await stop(page), 'online/' + width + '/recent question', { mode: 'focus', nodes: mobile(page) ? 0 : 1, graph: !mobile(page) });
    await page.evaluate(() => closeKnowledgeGraph());
    await gatedData(page); await start(page);
    await page.evaluate(() => { void openKnowledgeGraph(); });
    await frames(page, 18);
    assert.equal((await snapshot(page)).shown, false, 'Cold recent data preparation keeps the previous page visible');
    await page.evaluate(() => releaseGraphData());
    await ready(page, !mobile(page)); await frames(page);
    stableTrace(await stop(page), 'online/' + width + '/cold focus', { mode: 'focus', graph: !mobile(page) });
    await page.evaluate(() => restoreGraphData());

    await start(page); await page.locator('#knowledgeGraphFocusBtn').click();
    const count = await page.evaluate(() => knowledgeGraphData.nodes.length);
    await ready(page, !mobile(page)); await frames(page);
    stableTrace(await stop(page), 'online/' + width + '/all knowledge', { nodes: mobile(page) ? 0 : count, graph: !mobile(page) });
    await fullView(page, 'online/' + width + '/first complete view', count);
    const saved = await customize(page);
    await page.evaluate(() => closeKnowledgeGraph());
    await start(page); await page.evaluate(() => { void openKnowledgeGraph(); });
    await ready(page, !mobile(page)); await frames(page);
    stableTrace(await stop(page), 'online/' + width + '/cached reopen', { nodes: mobile(page) ? 0 : count, graph: !mobile(page) });
    await fullView(page, 'online/' + width + '/remembered complete view', count);
    remembered(await snapshot(page), saved, 'online/' + width);

    await page.evaluate(() => closeKnowledgeGraph());
    await gatedData(page); await start(page);
    await page.evaluate(() => { void openKnowledgeGraph(); });
    await frames(page, 8); await page.evaluate(() => closeKnowledgeGraph());
    await page.evaluate(() => releaseGraphData()); await frames(page);
    assert.ok((await stop(page)).every(sample => !sample.shown), 'Closing during preparation cannot revive the graph');
    await page.evaluate(() => restoreGraphData());
    assert.deepEqual(indexing, [], 'Opening and reopening never wait on history reindexing');
    assert.deepEqual(modelCalls, []); assert.deepEqual(errors, []);
    console.log('PASS online/' + width + ': cold full/recent/reopen frames are stable, camera retained and canceled opens stay closed');
  } finally { await context.close(); }
}

async function offlineNavigation(page, name, measure) {
  const toggle = page.locator(page.viewportSize().width <= 1100 ? '#offlineNavToggle' : '#offlineDesktopSidebarOpen');
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
  await frames(page, 16);
  if (measure) await start(page);
  await page.locator('.offline-nav-item[data-panel="' + name + '"]').click();
}

async function offlineCase(browser, width) {
  const { page, context, errors, modelCalls } = await fixture(browser, width, true);
  try {
    await ready(page, !mobile(page)); await frames(page);
    stableTrace(await stop(page), 'offline/' + width + '/cold document first paint', { graph: !mobile(page) });
    await offlineNavigation(page, 'graph', true);
    await ready(page, !mobile(page)); await frames(page);
    const count = mobile(page) ? null : await page.locator('#knowledgeGraphCanvas .kg-node-group').count();
    stableTrace(await stop(page), 'offline/' + width + '/first graph', { nodes: count, graph: !mobile(page) });
    await fullView(page, 'offline/' + width + '/first complete view');
    const saved = await customize(page);
    if (mobile(page)) await page.locator('.kg-mobile-expand').click();
    await offlineNavigation(page, 'concepts', false);
    await offlineNavigation(page, 'graph', true);
    await ready(page, !mobile(page)); await frames(page);
    stableTrace(await stop(page), 'offline/' + width + '/reopen graph', { graph: !mobile(page) });
    await fullView(page, 'offline/' + width + '/remembered complete view');
    remembered(await snapshot(page), saved, 'offline/' + width);
    if (mobile(page)) await page.locator('.kg-mobile-expand').click();
    const select = page.locator('#knowledgeGraphCategory');
    const smallCount = require('../static/offline-content/knowledge_graph.json').nodes.filter(node => node.category === '证明与归纳').length;
    await start(page);
    await select.evaluate(select => {
      select.value = '证明与归纳'; select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await ready(page, !mobile(page)); await frames(page);
    stableTrace(await stop(page), 'offline/' + width + '/small module', { nodes: mobile(page) ? 0 : smallCount, graph: !mobile(page) });
    await fullView(page, 'offline/' + width + '/small complete view');
    assert.deepEqual(modelCalls, []); assert.deepEqual(errors, []);
    console.log('PASS offline/' + width + ': first/default/small/fullview frames stable and remembered camera retained');
  } finally { await context.close(); }
}

async function offlineEntry(browser, width) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block' });
  await context.addInitScript(() => {
    const never = new Promise(() => {});
    Object.defineProperty(navigator, 'serviceWorker', { configurable: true, value: {
      register: () => never, ready: never, controller: null, addEventListener() {}, removeEventListener() {}
    } });
  });
  const page = await context.newPage();
  try {
    await page.route('**/auth/me', route => route.fulfill({ contentType: 'application/json', body: '{"configured":true,"authenticated":false}' }));
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await page.evaluate(() => {
      window.DMateOfflineBridge = { snapshot: () => new Promise(resolve => { window.releaseOfflineSnapshot = () => resolve({ username: '', drawings: [] }); }) };
    });
    await page.locator(width <= 1100 ? '#mobileNavBtn' : '#desktopSidebarOpen').click();
    const button = page.locator('#offlineWorkspaceBtn'), label = button.locator('.dmate-ui-label');
    const original = await label.innerText();
    await button.click();
    assert.equal(await button.isDisabled(), true); assert.equal(await button.getAttribute('aria-busy'), 'true');
    for (let index = 0; index < 12; index++) {
      await frames(page, 1); assert.equal(await label.innerText(), original, 'Offline entry never shows a preparation label');
    }
    const navigation = page.waitForURL('**/offline', { waitUntil: 'commit', timeout: 10000 });
    await page.evaluate(() => releaseOfflineSnapshot());
    await navigation;
    // Navigation has committed without the service worker; settle the new
    // document before disposing its context to avoid racing browser teardown.
    await page.waitForLoadState('domcontentloaded');
    console.log('PASS offline entry/' + width + ': stable label, retained snapshot handoff and navigation bypasses unresolved service-worker promises');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true, ignoreDefaultArgs: ['--hide-scrollbars'],
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    const widths = process.env.DMATE_TEST_WIDTHS ? process.env.DMATE_TEST_WIDTHS.split(',').map(Number) : [1440, 390];
    assert.ok(widths.length && widths.every(width => [1440, 390].includes(width)), 'Use supported graph test widths');
    const kinds = process.env.DMATE_TEST_KINDS ? process.env.DMATE_TEST_KINDS.split(',') : ['online', 'offline', 'entry'];
    assert.ok(kinds.length && kinds.every(kind => ['online', 'offline', 'entry'].includes(kind)), 'Use supported graph test scenarios');
    for (const width of widths) {
      if (kinds.includes('online')) await onlineCase(browser, width);
      if (kinds.includes('offline')) await offlineCase(browser, width);
      if (kinds.includes('entry')) await offlineEntry(browser, width);
    }
  } finally { await browser.close(); }
})().catch(error => {
  if (lastTrace) writeFileSync('/tmp/dmate-graph-opening-last-trace.json', JSON.stringify(lastTrace));
  console.error(error); process.exitCode = 1;
});
