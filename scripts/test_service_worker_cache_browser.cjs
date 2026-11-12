/* A controlled browser must receive current online asset revisions while the
 * offline shell keeps its own precached resources available without a network.
 * Start Flask first; the test uses a fresh, isolated browser context.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const assetPath = '/static/button-themes.css';

async function fetchAsset(page, path) {
  return page.evaluate(async value => {
    const response = await fetch(value, { cache: 'no-store' });
    return { status: response.status, text: await response.text() };
  }, path);
}

async function disconnectWorkerNetwork(browser, workerURL) {
  // Older Playwright versions do not apply context.setOffline to the service
  // worker's own network target. Exercise an actual failed fetch there too.
  const protocol = await browser.newBrowserCDPSession();
  const target = (await protocol.send('Target.getTargets')).targetInfos.find(info =>
    info.type === 'service_worker' && info.url === workerURL);
  assert.ok(target, 'The active service worker must have a browser target');
  const { sessionId } = await protocol.send('Target.attachToTarget', { targetId: target.targetId, flatten: false });
  let serial = 0;
  const send = async (method, params = {}) => {
    const id = ++serial;
    let listener;
    const result = new Promise((resolve, reject) => {
      listener = event => {
        if (event.sessionId !== sessionId) return;
        const response = JSON.parse(event.message);
        if (response.id !== id) return;
        if (response.error) reject(new Error(response.error.message)); else resolve(response.result);
      };
      protocol.on('Target.receivedMessageFromTarget', listener);
    });
    try {
      await protocol.send('Target.sendMessageToTarget', { sessionId, message: JSON.stringify({ id, method, params }) });
      return await result;
    } finally { protocol.off('Target.receivedMessageFromTarget', listener); }
  };
  try {
    await send('Network.enable');
    await send('Network.emulateNetworkConditions', { offline: true, latency: 0, downloadThroughput: 0, uploadThroughput: 0 });
    return protocol;
  } catch (error) { await protocol.detach(); throw error; }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  const context = await browser.newContext();
  const page = await context.newPage();
  let workerProtocol;
  try {
    // APIRequestContext bypasses service workers, providing the actual file
    // against which the controlled page's network-first response is compared.
    const reference = await context.request.get(new URL(assetPath, baseURL).href);
    assert.equal(reference.status(), 200, 'The server must provide the shared stylesheet');
    const networkCSS = await reference.text();
    assert.ok(networkCSS.trim().length, 'The shared stylesheet must not be empty');

    await page.goto(new URL('/offline', baseURL).href, { waitUntil: 'networkidle' });
    await page.evaluate(async () => {
      await navigator.serviceWorker.register('/offline-service-worker.js', { scope: '/' });
      await navigator.serviceWorker.ready;
    });
    await page.waitForFunction(() => navigator.serviceWorker.controller?.state === 'activated');

    const current = await page.evaluate(async path => {
      const names = (await caches.keys()).filter(name => name.startsWith('dmate-offline-shell-'));
      if (names.length !== 1) throw new Error('Expected one active offline cache, found: ' + names.join(', '));
      const cache = await caches.open(names[0]);
      const canonical = (await cache.keys()).filter(request => new URL(request.url).pathname === path);
      if (canonical.length !== 1) throw new Error('Expected exactly one precached shared stylesheet');
      return { name: names[0], canonical: canonical[0].url };
    }, assetPath);
    const token = Date.now().toString(36);
    const revision = assetPath + '?v=online-cache-regression-' + token;
    const unseen = assetPath + '?v=unseen-cache-regression-' + token;
    const oldOnly = assetPath + '?v=obsolete-cache-regression-' + token;
    const canonicalSentinel = '/* Current offline shell stylesheet: ' + token + ' */';
    const obsoleteSentinel = '/* Obsolete cache must never answer: ' + token + ' */';

    await page.evaluate(async setup => {
      const headers = { 'Content-Type': 'text/css; charset=utf-8' };
      const currentCache = await caches.open(setup.current.name);
      await currentCache.put(setup.current.canonical, new Response(setup.canonicalSentinel, { headers }));
      // Install the obsolete fixture only after activation has cleaned up old
      // versions. These entries must not participate in current fallbacks.
      const oldName = setup.current.name === 'dmate-offline-shell-v3'
        ? 'dmate-offline-shell-obsolete' : 'dmate-offline-shell-v3';
      const oldCache = await caches.open(oldName);
      await oldCache.put(setup.current.canonical, new Response(setup.obsoleteSentinel, { headers }));
      await oldCache.put(setup.oldOnly, new Response(setup.obsoleteSentinel, { headers }));
    }, { current, canonicalSentinel, obsoleteSentinel, oldOnly });

    const online = await fetchAsset(page, revision);
    assert.equal(online.status, 200);
    assert.equal(online.text, networkCSS,
      'A current online revision must reach the network instead of reusing the canonical offline stylesheet');
    const retained = await page.evaluate(async ({ name, path }) => {
      const response = await (await caches.open(name)).match(path);
      return response ? response.text() : null;
    }, { name: current.name, path: revision });
    assert.equal(retained, networkCSS, 'The fetched online revision must be cached under its exact URL');
    console.log('PASS online revision bypasses the offline canonical cache and retains its exact response');

    const canonical = await fetchAsset(page, current.canonical);
    assert.equal(canonical.status, 200);
    assert.equal(canonical.text, canonicalSentinel, 'The exact precached URL must remain cache-first');
    console.log('PASS the canonical offline asset remains cache-first');

    await context.setOffline(true);
    workerProtocol = await disconnectWorkerNetwork(browser, new URL('/offline-service-worker.js', baseURL).href);
    const exactOffline = await fetchAsset(page, revision);
    assert.equal(exactOffline.status, 200);
    assert.equal(exactOffline.text, networkCSS, 'Offline lookup must prefer the requested exact revision');
    console.log('PASS offline requests retain their previously fetched exact revision');

    const fallback = await fetchAsset(page, unseen);
    assert.equal(fallback.status, 200);
    assert.equal(fallback.text, canonicalSentinel, 'An unseen offline revision must use the current precached asset');
    console.log('PASS unseen offline revisions fall back to the current canonical asset');

    const isolated = await fetchAsset(page, oldOnly);
    assert.equal(isolated.status, 200);
    assert.equal(isolated.text, canonicalSentinel, 'An exact match in an obsolete cache must be ignored');
    assert.notEqual(isolated.text, obsoleteSentinel);
    console.log('PASS obsolete cache versions cannot supply shared assets');
  } catch (error) {
    console.error('Worker cache context:', await page.evaluate(async () => ({
      controller: navigator.serviceWorker.controller?.scriptURL,
      caches: await caches.keys()
    })).catch(() => null));
    throw error;
  } finally {
    await workerProtocol?.detach();
    await context.close();
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
