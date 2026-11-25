/* A controlled browser must receive current online asset revisions while the
 * offline shell keeps its own precached resources available without a network.
 * Start Flask first; the test uses a fresh, isolated browser context.
 */
'use strict';
const assert = require('node:assert/strict');
// Playwright 1.56 requires this opt-in to observe requests made by the worker.
process.env.PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS = '1';
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
    const packURL = new URL('/static/offline-content/questions.zh-CN.json?v=34', baseURL).href;
    const [plainPack, compressedPack] = await Promise.all(['identity', 'gzip'].map(encoding =>
      context.request.get(packURL, {headers:{'Accept-Encoding':encoding}})));
    assert.equal(compressedPack.headers()['content-encoding'], 'gzip');
    assert.match(compressedPack.headers().vary, /Accept-Encoding/i);
    assert.ok(Number(compressedPack.headers()['content-length']) < Number(plainPack.headers()['content-length']));
    assert.deepEqual(await compressedPack.body(), await plainPack.body(), 'Compressed study content decodes to the original bytes');
    const sharedAssets = await Promise.all(['/static/dmate-main.css?v=89', '/static/graph-editor.css?v=28', '/static/button-themes.css?v=70', '/static/scrollbars.css?v=25', '/static/scrollbars.js?v=25',
      '/static/select-controls.css?v=44', '/static/mobile-select.js?v=26', '/static/offline.css?v=74',
      '/static/appearance-panels.css', '/static/dmate-shared-overrides.css?v=25',
      '/static/concept-notebook.css?v=9', '/static/textarea-autosize.css?v=1', '/static/textarea-autosize.js?v=1',
      '/static/drawing-workspace.css?v=57', '/static/graph-editor.js?v=55', '/static/graph-editor-overlay.js?v=43', '/static/drawing-workspace.js?v=63', '/static/drawing-export.js?v=39',
      '/static/modal-chrome.css', '/static/modal-text.js?v=53', '/static/delete-confirm.js', '/static/guest-session.js?v=53', '/static/offline-interface-state.js?v=1', '/static/language.js?v=59',
      '/static/graph-editor-format.js?v=32', '/static/language-catalog.js?v=73', '/static/offline-privacy-motion.js?v=4', '/static/offline-shell.js?v=42',
      '/static/offline-vault.js?v=2', '/static/offline-handoff.js?v=1', '/static/offline-storage.js?v=4',
      '/static/vendor/fflate-0.8.2/fflate.min.js', '/static/offline-backup.js?v=3',
      '/static/backup-download.js?v=1', '/static/appearance-bootstrap.js?v=4',
      '/static/offline-appearance-preload.js?v=1', '/static/offline-appearance.js?v=13',
      '/static/offline.js?v=80', '/static/offline-knowledge-graph.js?v=67', '/static/knowledge-graph-labels.js?v=22',
      '/static/ui-tooltip.js?v=50',
      '/static/offline-knowledge-graph.css?v=56', '/static/offline-entry.js?v=50',
      '/static/knowledge-graph-sheet.css?v=5', '/static/knowledge-graph-sheet.js?v=3', '/static/math-markdown.js?v=23',
      '/static/search-controls.css?v=29', '/static/search-controls.js?v=29',
      '/static/offline-content/concepts.zh-CN.json?v=34', '/static/offline-content/questions.zh-CN.json?v=34',
      '/static/offline-content/knowledge_graph.json?v=28',
      '/static/offline-content/translations.en.json?v=34']
      .map(async path => {
        const response = await context.request.get(new URL(path, baseURL).href);
        assert.equal(response.status(), 200, 'The server must provide ' + path);
        return { path, text: await response.text() };
      }));

    const reusablePacks = sharedAssets.filter(asset => asset.path.startsWith('/static/offline-content/'));
    const workerRequests = [];
    context.on('request',request => {
      if(typeof request.serviceWorker === 'function' && request.serviceWorker()) workerRequests.push(request.url());
    });
    // A complete previous release can contribute exact immutable URLs, while
    // changed versions and unversioned application code still come fresh.
    await page.goto(new URL('/health', baseURL).href);
    await page.evaluate(async packs => {
      const cache = await caches.open('dmate-offline-shell-v136');
      await cache.put('/static/appearance-bootstrap.js?v=3',new Response('/* obsolete appearance bootstrap */'));
      await cache.put('/static/graph-editor-model.js',new Response('/* obsolete unversioned editor model */'));
      for(const asset of packs) await cache.put(asset.path,new Response(asset.text,{headers:{'Content-Type':'application/json'}}));
      await cache.put('/__dmate_offline_ready__/dmate-offline-shell-v136',new Response('ready'));
    },reusablePacks);
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
    assert.equal(current.name, 'dmate-offline-shell-v137', 'The offline workspace uses the refreshed shell cache');
    assert.equal((await fetchAsset(page, current.canonical)).text, networkCSS,
      'The refreshed shell loads current frameless controls instead of the obsolete stylesheet');
    for (const asset of sharedAssets) {
      const cached = await page.evaluate(async ({ name, path }) => {
        const response = await (await caches.open(name)).match(path);
        return response ? response.text() : null;
      }, { name: current.name, path: asset.path });
      assert.equal(cached, asset.text, 'The refreshed shell precaches ' + asset.path);
    }
    assert.ok(workerRequests.length > 0,'The browser exposes actual service-worker network requests');
    for(const asset of reusablePacks) assert.ok(!workerRequests.includes(new URL(asset.path,baseURL).href),
      'Upgrade reuses the complete prior immutable study pack without downloading it again: '+asset.path);
    assert.ok(workerRequests.includes(new URL('/static/appearance-bootstrap.js?v=4',baseURL).href),'The updated appearance bootstrap is fetched');
    assert.ok(workerRequests.includes(new URL('/static/graph-editor-model.js',baseURL).href),'Unversioned application code is fetched');
    assert.notEqual(await page.evaluate(async name => (await(await caches.open(name)).match('/static/graph-editor-model.js')).text(),current.name),
      '/* obsolete unversioned editor model */');
    const redundant = /\/(?:output\/svg\/fonts\/tex|input\/tex\/extensions\/(?:ams|newcommand|noundefined|require|autoload|configmacros))\.js$/;
    assert.ok(!workerRequests.some(url=>redundant.test(new URL(url).pathname)),
      'The combined MathJax bundle does not download its seven duplicate components');
    console.log('PASS cache upgrades reuse '+reusablePacks.length+' unchanged study packs, fetch changed code and skip duplicate MathJax components');
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
    for (const asset of sharedAssets) {
      const offlineAsset = await fetchAsset(page, asset.path);
      assert.equal(offlineAsset.status, 200);
      const expected = new URL(asset.path, baseURL).pathname === assetPath ? canonicalSentinel : asset.text;
      assert.equal(offlineAsset.text, expected, 'Shared controls retain their current cache entry offline: ' + asset.path);
    }
    console.log('PASS the previous shell cache upgrades and shared UI resources remain available offline');
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

    await page.reload({waitUntil:'domcontentloaded'});
    await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
    await page.waitForFunction(() => {
      const cover = document.getElementById('offlinePrivacyCover');
      const lines = [...cover.querySelectorAll('.offline-privacy-mark-growth line')];
      const visible = lines.filter(line => getComputedStyle(line).display !== 'none');
      return !cover.open && lines.length === 42 && visible.length === 21
        && visible.every(line => Number.parseFloat(line.getAttribute('stroke-dasharray')) >=
          Math.hypot(line.x2.baseVal.value-line.x1.baseVal.value, line.y2.baseVal.value-line.y1.baseVal.value)-0.05);
    });
    console.log('PASS a fully offline reload completes the precached intro and automatically enters the workspace');
    const downloadPending = page.waitForEvent('download');
    await page.locator('#offlineExportDataBtn').click();
    const download = await downloadPending;
    assert.match(download.suggestedFilename(),/^DMate-.*\.zip$/);
    const archive = await require('node:fs/promises').readFile(await download.path());
    assert.equal(archive.subarray(0,4).toString('hex'),'504b0304','The offline export is a real ZIP archive');
    console.log('PASS fully disconnected offline mode exports a ZIP using only precached backup resources');
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
