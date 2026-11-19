/* Real image-export destinations. Native album replies are mocked at the
 * existing WebView boundary; PNG rendering and local downloads remain real.
 */
'use strict';
const assert = require('node:assert/strict');
const { revealInterface } = require('./offline-vault-browser-fixtures.cjs');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const android = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36';
const iphone = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1';

async function settle(page) {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

function installProbe(nativeBridge) {
  const probe = window.imageExportProbe = { clipboard: 0, clipboardItems: 0, requests: [], shares: [], previousMessages: 0 };
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: {
    write: async () => { probe.clipboard++; throw new Error('Export must not write to the clipboard'); },
    writeText: async () => { probe.clipboard++; throw new Error('Export must not write clipboard text'); }
  } });
  window.ClipboardItem = class { constructor() { probe.clipboardItems++; } };
  Object.defineProperty(navigator, 'canShare', { configurable: true, value: data => Boolean(data?.files?.length) });
  Object.defineProperty(navigator, 'share', { configurable: true, value: async data => {
    probe.shares.push(await Promise.all((data.files || []).map(async file => ({
      name: file.name, type: file.type, size: file.size, magic: [...new Uint8Array(await file.slice(0, 8).arrayBuffer())]
    }))));
  } });
  if (nativeBridge) {
    const listeners = new Set();
    const previous = () => { probe.previousMessages++; };
    window.DMateGallery = { onmessage: previous,
      postMessage: raw => probe.requests.push(JSON.parse(raw)),
      ...(nativeBridge === 'events' ? { addEventListener: (type, fn) => { if (type === 'message') listeners.add(fn); },
        removeEventListener: (type, fn) => { if (type === 'message') listeners.delete(fn); } } : {}) };
    probe.reply = value => {
      const event = { data: typeof value === 'string' ? value : JSON.stringify(value) };
      if (nativeBridge === 'events') for (const listener of [...listeners]) listener(event);
      else window.DMateGallery.onmessage?.(event);
    };
    probe.listenerCount = () => listeners.size;
    probe.originalHandler = previous;
  }
}

async function fixture(browser, { offline = false, width = 1440, ua, nativeBridge, workers = false } = {}) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: workers ? 'allow' : 'block',
    ...(ua ? { userAgent: ua, hasTouch: true, isMobile: true } : {}) });
  await context.addInitScript(installProbe, nativeBridge);
  const page = await context.newPage(), errors = [], downloads = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('download', download => downloads.push(download));
  await page.route('**/auth/me', route => route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ configured: true, authenticated: false }) }));
  await page.goto(baseURL + (offline ? '/offline' : ''), { waitUntil: 'networkidle' });
  if (offline) {
    await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
    await revealInterface(page);
  }
  else {
    await page.waitForFunction(() => typeof openKnowledgeGraph === 'function');
    await page.evaluate(() => openKnowledgeGraph());
    await page.waitForFunction(() => knowledgeGraphInitialized);
    await page.evaluate(() => selectKnowledgeGraphDisplayMode('full'));
    await page.locator('#knowledgeGraphCanvas .kg-section').waitFor();
  }
  await smallModule(page);
  return { page, context, errors, downloads };
}

async function smallModule(page) {
  await page.waitForFunction(() => [...document.querySelector('#knowledgeGraphCategory').options]
    .some(option => option.value === '证明与归纳'));
  await page.locator('#knowledgeGraphCategory').evaluate(select => {
    select.value = '证明与归纳'; select.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await settle(page);
}

async function exportLabels(page) {
  for (const [language, label] of [['en', 'Export as image'], ['zh-CN', '以图片形式导出']]) {
    await page.evaluate(value => window.DMateI18n.setLanguage(value, false), language);
    await settle(page);
    assert.equal(await page.locator('#knowledgeGraphCopyBtn').getAttribute('title'), label);
    assert.equal(await page.locator('#knowledgeGraphCopyBtn').getAttribute('aria-label'), label);
  }
}

async function noClipboard(page) {
  assert.deepEqual(await page.evaluate(() => [imageExportProbe.clipboard, imageExportProbe.clipboardItems]), [0, 0],
    'Export bypasses the clipboard even when its APIs are available');
}

async function pngDownload(download) {
  const chunks = [];
  for await (const chunk of await download.createReadStream()) chunks.push(chunk);
  const bytes = Buffer.concat(chunks);
  assert.match(download.suggestedFilename(), /\.png$/i);
  assert.doesNotMatch(download.suggestedFilename(), /\.png\.png$/i);
  assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  assert.ok(bytes.readUInt32BE(16) > 64 && bytes.readUInt32BE(20) > 64, 'The exported PNG has usable graph dimensions');
  assert.equal(await download.failure(), null);
}

async function desktop(browser, offline, width) {
  const { page, context, errors, downloads } = await fixture(browser, { offline, width });
  try {
    await exportLabels(page);
    assert.equal(await page.evaluate(() => DMateDrawingExport.isMobileDevice()), false,
      'Resizing a desktop browser does not turn its download destination into a phone album');
    const downloading = page.waitForEvent('download');
    await page.locator('#knowledgeGraphCopyBtn').click();
    await pngDownload(await downloading);
    assert.equal(downloads.length, 1);
    assert.equal(await page.locator('.dmate-png-save-dialog').count(), 0);
    await noClipboard(page); assert.deepEqual(errors, []);
    console.log('PASS ' + (offline ? 'offline' : 'online') + '/desktop' + width + ': real PNG download and no clipboard writes');
  } finally { await context.close(); }
}

async function mobileWeb(browser, offline, ua, name) {
  const { page, context, errors, downloads } = await fixture(browser, { offline, width: 390, ua });
  try {
    assert.equal(await page.evaluate(() => DMateDrawingExport.isMobileDevice()), true);
    await page.locator('#knowledgeGraphCopyBtn').click();
    const preview = page.locator('.dmate-png-save-dialog');
    await preview.waitFor({ state: 'visible' });
    await page.waitForFunction(() => document.querySelector('.dmate-png-save-preview')?.naturalWidth > 64);
    assert.equal(downloads.length, 0, 'A phone browser presents a real image without claiming direct Photos access');
    assert.doesNotMatch(await preview.innerText(), /已保存到相册|saved to (?:Photos|the photo)/i);
    await preview.locator('[data-image-export="share"]').click();
    await page.waitForFunction(() => imageExportProbe.shares.length === 1);
    const shared = await page.evaluate(() => imageExportProbe.shares);
    assert.equal(shared.length, 1); assert.equal(shared[0].length, 1);
    assert.equal(shared[0][0].type, 'image/png');
    assert.deepEqual(shared[0][0].magic, [137, 80, 78, 71, 13, 10, 26, 10]);
    assert.doesNotMatch(await preview.innerText(), /已保存到相册|saved to (?:Photos|the photo)/i,
      'Opening system sharing is not reported as a confirmed album save');
    const downloading = page.waitForEvent('download');
    await preview.locator('[data-image-export="download"]').click();
    await pngDownload(await downloading);
    await preview.locator('[data-image-export="close"]').click();
    await preview.waitFor({ state: 'detached' });
    await noClipboard(page); assert.deepEqual(errors, []);
    console.log('PASS ' + (offline ? 'offline' : 'online') + '/' + name + ': decodable image, explicit share/save and download fallback');
  } finally { await context.close(); }
}

async function nativeAlbum(browser, offline) {
  const { page, context, errors, downloads } = await fixture(browser, { offline, width: 390, ua: android, nativeBridge: 'events' });
  try {
    await page.locator('#knowledgeGraphCopyBtn').click();
    await page.waitForFunction(() => imageExportProbe.requests.length === 1);
    const request = await page.evaluate(() => imageExportProbe.requests[0]);
    const bytes = Buffer.from(request.base64, 'base64');
    assert.ok(request.id && request.id.length <= 128); assert.match(request.filename, /\.png$/i);
    assert.doesNotMatch(request.filename, /\.png\.png$/i);
    assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
    assert.ok(bytes.readUInt32BE(16) > 64 && bytes.readUInt32BE(20) > 64);
    await page.evaluate(() => { imageExportProbe.reply('bad JSON'); imageExportProbe.reply({ id: 'wrong-request', ok: true }); });
    await settle(page);
    assert.equal(await page.locator('#knowledgeGraphCopyBtn').isDisabled(), true,
      'The button waits for its matching native save acknowledgement');
    assert.equal(await page.locator('.dmate-png-save-dialog').count(), 0);
    assert.doesNotMatch(await page.locator('body').innerText(), /已保存到相册/);
    await page.evaluate(id => imageExportProbe.reply({ id, ok: true, message: 'Album save confirmed by test bridge' }), request.id);
    await page.waitForFunction(() => !document.getElementById('knowledgeGraphCopyBtn').disabled);
    await page.waitForFunction(() => document.body.innerText.includes('Album save confirmed by test bridge'));
    assert.equal(await page.evaluate(() => imageExportProbe.listenerCount()), 0, 'Native reply listeners are cleaned after success');
    await page.locator('#knowledgeGraphCopyBtn').click();
    await page.waitForFunction(() => imageExportProbe.requests.length === 2);
    await page.evaluate(() => imageExportProbe.reply({ id: imageExportProbe.requests[1].id, ok: false, message: 'Album write denied by test bridge' }));
    await page.waitForFunction(() => !document.getElementById('knowledgeGraphCopyBtn').disabled);
    await page.waitForFunction(() => document.body.innerText.includes('Album write denied by test bridge'));
    assert.equal(downloads.length, 0, 'A failed native album save does not silently download somewhere else');
    assert.equal(await page.locator('.dmate-png-save-dialog').count(), 0);
    assert.equal(await page.evaluate(() => imageExportProbe.listenerCount()), 0);
    await noClipboard(page); assert.deepEqual(errors, []);
    console.log('PASS ' + (offline ? 'offline' : 'online') + '/Android app: verified album reply, wrong-id isolation and honest error handling');
  } finally { await context.close(); }
}

async function helperNativeContract(browser) {
  const { page, context, downloads } = await fixture(browser, { offline: true, nativeBridge: 'property' });
  try {
    const pending = page.evaluate(async () => {
      const canvas = document.createElement('canvas'); canvas.width = 96; canvas.height = 72;
      canvas.getContext('2d').fillRect(0, 0, 96, 72);
      const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
      return DMateDrawingExport.save(blob, 'native-contract.png', { document });
    });
    await page.waitForFunction(() => imageExportProbe.requests.length === 1);
    await page.evaluate(() => imageExportProbe.reply({ id: imageExportProbe.requests[0].id, ok: true, message: 'saved' }));
    const result = await pending;
    assert.equal(result.destination, 'gallery', 'An installed native bridge takes precedence even for a desktop user agent');
    assert.equal(await page.evaluate(() => DMateGallery.onmessage === imageExportProbe.originalHandler), true,
      'The onmessage fallback restores the handler that preceded the save');
    const oversized = await page.evaluate(async () => {
      try { await DMateDrawingExport.save(new Blob([new Uint8Array(20 * 1024 * 1024 + 1)], { type: 'image/png' }), 'too-large.png', { document }); return ''; }
      catch (error) { return error.message; }
    });
    assert.ok(oversized, 'Oversized native images are rejected');
    assert.equal(await page.evaluate(() => imageExportProbe.requests.length), 1, 'An invalid request is not sent to the app');
    assert.equal(downloads.length, 0); await noClipboard(page);
    console.log('PASS shared native helper: app precedence, property-handler cleanup and size limit');
  } finally { await context.close(); }
}

async function disconnectedExport(browser) {
  const { page, context, errors } = await fixture(browser, { offline: true, width: 390, workers: true });
  try {
    await page.evaluate(async () => {
      await navigator.serviceWorker.register('/offline-service-worker.js', { scope: '/' });
      await navigator.serviceWorker.ready;
    });
    await page.waitForFunction(() => navigator.serviceWorker.controller?.state === 'activated');
    await context.setOffline(true);
    await page.reload({ waitUntil: 'load' });
    await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
    await revealInterface(page);
    assert.equal(await page.evaluate(() => navigator.onLine), false);
    await smallModule(page);
    const downloading = page.waitForEvent('download');
    await page.locator('#knowledgeGraphCopyBtn').click();
    await pngDownload(await downloading);
    await noClipboard(page); assert.deepEqual(errors, []);
    console.log('PASS disconnected reload: the cached graph action still exports a real PNG');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const offline of [false, true]) for (const width of [1440, 390]) await desktop(browser, offline, width);
    await mobileWeb(browser, false, android, 'Android browser');
    await mobileWeb(browser, true, iphone, 'iPhone browser');
    for (const offline of [false, true]) await nativeAlbum(browser, offline);
    await helperNativeContract(browser);
    await disconnectedExport(browser);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
