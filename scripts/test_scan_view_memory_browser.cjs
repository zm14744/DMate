/* Real image-review dialogs retain independent responsive cameras. All remote
 * recognition and chat routes are blocked; fixtures contain completed sources.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const settle = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() =>
  requestAnimationFrame(() => requestAnimationFrame(resolve)))));

async function ready(page) {
  await page.locator('#graphEditorDialog .dge-overlay[data-geometry-ready="true"]').waitFor();
  await settle(page);
}
async function open(page, id) {
  await page.evaluate(id => editOcrTask(id), id);
  await page.locator('#graphEditorDialog').waitFor({ state: 'visible' });
  await ready(page);
}
async function close(page) {
  await page.locator('#graphEditorClose').click();
  await page.waitForFunction(() => ocrEditorTaskId === null);
}
async function camera(page) {
  return page.locator('#graphEditorDialog .dge-overlay').evaluate(node => {
    const viewport = node.querySelector('.dge-overlay-viewport'), image = node.querySelector('img'),
      v = viewport.getBoundingClientRect(), box = image.getBoundingClientRect();
    return { zoom: parseFloat(node.closest('#graphEditorDialog').querySelector('.dge-overlay-zoom').textContent),
      cx: (v.left + viewport.clientLeft + viewport.clientWidth / 2 - box.left) / box.width,
      cy: (v.top + viewport.clientTop + viewport.clientHeight / 2 - box.top) / box.height,
      scale: box.width, height: box.height,
      margins: [box.left - v.left, box.top - v.top, v.right - box.right, v.bottom - box.bottom] };
  });
}
function sameCamera(actual, expected, label) {
  assert.ok(Math.abs(actual.zoom - expected.zoom) <= .02, label + ': zoom ' + JSON.stringify({ actual, expected }));
  for (const [axis, pixels] of [['cx', actual.scale], ['cy', actual.height]])
    assert.ok(Math.abs(actual[axis] - expected[axis]) * pixels <= 2,
      label + ': visible image centre ' + axis + ' ' + JSON.stringify({ actual, expected }));
}
async function firstFit(page, label) {
  const initial = await camera(page);
  for (const gap of initial.margins) assert.ok(gap >= -2, label + ': the complete source image initially fits');
  await page.locator('[data-overlay-tool="zoom-fit"]').click(); await settle(page);
  sameCamera(await camera(page), initial, label + ': first frame already equals explicit Fit');
  return initial;
}
async function adjust(page) {
  const before = await camera(page);
  for (let count = 0; count < 3; count++) await page.locator('[data-overlay-tool="zoom-in"]').click();
  const area = await page.locator('.dge-overlay-viewport').boundingBox();
  await page.mouse.move(area.x + area.width * .6, area.y + area.height * .6);
  await page.mouse.down();
  await page.mouse.move(area.x + area.width * .6 - 39, area.y + area.height * .6 - 31, { steps: 5 });
  await page.mouse.up(); await settle(page);
  const changed = await camera(page);
  assert.notEqual(changed.zoom, before.zoom, 'The fixture actually changes the visible zoom');
  assert.ok(Math.abs(changed.cx - .5) + Math.abs(changed.cy - .5) > .01, 'The fixture actually pans the image');
  return changed;
}
async function resize(page, width, height = 900) {
  await page.setViewportSize({ width, height }); await ready(page);
}

async function runCase(browser, width) {
  const language = width === 390 ? 'en' : 'zh-CN';
  const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block' });
  const page = await context.newPage(), calls = [], errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/auth/me', route => route.fulfill({ contentType: 'application/json',
    body: '{"configured":true,"authenticated":false}' }));
  await page.route(/\/(?:chat|ocr(?:\/[^?]*)?|graph\/[^?]*|analyze-questions|classify|conversation\/title)(?:\?|$)/,
    route => { calls.push(new URL(route.request().url()).pathname); return route.abort(); });
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await page.waitForFunction(() => !accountVerificationOperation);
    await page.evaluate(language => {
      DMateI18n.setLanguage(language, false);
      const make = (id, height) => {
        const graph = { id: 'G1', name: '图G1', vertices: [{ id: 'v1', x: .2, y: .2 }, { id: 'v2', x: .8, y: .7 }], edges: [] };
        const draft = { body_text: '本地识图内容', graphs: [graph] };
        const originalUrl = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="' + height
          + '"><rect width="1000" height="' + height + '" fill="white"/><path d="M0 0L1000 ' + height + '" stroke="black"/></svg>');
        return { id, groupId: '1', isQuestion: true, state: 'ready',
          file: new File(['local source'], id + '.png', { type: 'image/png' }), sessionId: currentId,
          originalUrl, startedAt: performance.now(), finishedAt: performance.now(), dirty: false,
          draft: structuredClone(draft), initialDocument: structuredClone(draft),
          scanState: { mode: 'native', sourcesVersion: 3, nativeDocument: structuredClone(draft),
            graphRegions: [{ id: 'g1', selected: true, status: 'complete', polygon: [[.1,.1],[.9,.1],[.9,.8],[.1,.8]], graphs: [graph] }],
            textRegions: [], view: { zoom: 400, visible: true } } };
      };
      ocrTasks.clear();
      ocrTasks.set('scan-A', make('scan-A', 1400)); ocrTasks.set('scan-B', make('scan-B', 600));
      ocrTasks.set('scan-hidden', make('scan-hidden', 1800)); renderOcrTasks();
    }, language);
    await open(page, 'scan-A'); await firstFit(page, width + '/first layout');
    assert.equal((await page.locator('.dgs-graph-title').first().innerText()).trim(), language === 'en' ? 'Graph G₁' : '图 G₁');
    let first = await adjust(page);
    assert.deepEqual(await page.evaluate(() => ({ dirty: ocrTasks.get('scan-A').dirty,
      name: ocrTasks.get('scan-A').draft.graphs[0].name })), { dirty: false, name: '图G1' },
    'View adjustments and display headings do not edit the source document');
    await resize(page, width === 390 ? 430 : 1360, 850);
    sameCamera(await camera(page), first, width + '/same-layout resize');
    await resize(page, width); sameCamera(await camera(page), first, width + '/resize back');
    // Mode/source refresh rebuilds the information cards while preserving the image.
    await page.locator('.dgs-modes [role="tab"]').nth(1).click(); await settle(page);
    sameCamera(await camera(page), first, width + '/information refresh');
    await page.locator('.dgs-modes [role="tab"]').first().click(); await settle(page);
    await close(page); await open(page, 'scan-A');
    sameCamera(await camera(page), first, width + '/reopen same image');
    await close(page); await open(page, 'scan-B'); await firstFit(page, width + '/independent image');
    await close(page);
    await page.evaluate(() => { const task = ocrTasks.get('scan-A'); task.scanState = JSON.parse(JSON.stringify(task.scanState)); });
    await open(page, 'scan-A'); sameCamera(await camera(page), first, width + '/serialized state');
    const otherWidth = width === 390 ? 1440 : 390;
    await resize(page, otherWidth); await firstFit(page, width + '/first alternate layout');
    const second = await adjust(page);
    await resize(page, width); sameCamera(await camera(page), first, width + '/return to first layout');
    first = await adjust(page);
    await resize(page, otherWidth); sameCamera(await camera(page), second, width + '/return to adjusted alternate layout');
    await page.locator('[data-overlay-tool="zoom-fit"]').click(); await settle(page);
    const refitted = await camera(page);
    await close(page); await open(page, 'scan-A'); sameCamera(await camera(page), refitted, width + '/explicit Fit remembered');
    await resize(page, width); sameCamera(await camera(page), first, width + '/other layout remains adjusted');
    await close(page);

    // Real image review mounts before its dialog opens. Delay that public open
    // once so a cached source can finish loading while the viewport is hidden.
    await page.evaluate(() => {
      window.__scanShowDialog = showGraphEditorDialog;
      showGraphEditorDialog = dialog => { window.__scanHiddenDialog = dialog; };
      editOcrTask('scan-hidden');
    });
    await page.waitForFunction(() => document.querySelector('#graphEditorDialog .dge-overlay-image')?.complete);
    assert.equal(await page.locator('.dge-overlay').getAttribute('data-geometry-ready'), 'false');
    await page.evaluate(() => { showGraphEditorDialog = window.__scanShowDialog; showGraphEditorDialog(window.__scanHiddenDialog); });
    await ready(page); await firstFit(page, width + '/hidden first image');
    await close(page);
    assert.deepEqual(calls, [], 'Layout, zoom, pan, reopening and information refresh never recognize the image again');
    assert.deepEqual(errors, [], 'No browser errors');
    console.log('PASS ' + width + ': first-fit responsive image cameras, independent pan/zoom memory, reopen/serialization/hidden mount and clean source names');
  } finally { await context.close(); }
}
(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try { for (const width of [1440, 390]) await runCase(browser, width); }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
