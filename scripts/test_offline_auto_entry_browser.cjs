/* Exercise real Chromium network loss for both page and service-worker targets.
 * Local mode is entered automatically; returning online remains a manual action. */
'use strict';
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const {revealInterface} = require('./offline-vault-browser-fixtures.cjs');
const baseURL = (process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000').replace(/\/$/,'');
const launch = {headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH
  ? {executablePath:process.env.CHROMIUM_EXECUTABLE_PATH} : {})};

async function workerNetwork(browser,page) {
  const protocol = await browser.newBrowserCDPSession(), pageProtocol = await page.context().newCDPSession(page);
  const {targetInfo} = await pageProtocol.send('Target.getTargetInfo');
  await pageProtocol.detach();
  const target = (await protocol.send('Target.getTargets')).targetInfos.find(info => info.type==='service_worker'
    && info.url===new URL('/offline-service-worker.js',baseURL).href && info.browserContextId===targetInfo.browserContextId);
  assert.ok(target,'The real offline worker has a separate browser network target');
  const {sessionId} = await protocol.send('Target.attachToTarget',{targetId:target.targetId,flatten:false});
  let serial = 0;
  async function send(method,params={}) {
    const id=++serial;let listener;
    const pending=new Promise((resolve,reject)=>{
      listener=event=>{
        if(event.sessionId!==sessionId)return;
        const response=JSON.parse(event.message);if(response.id!==id)return;
        if(response.error)reject(Error(response.error.message));else resolve(response.result);
      };
      protocol.on('Target.receivedMessageFromTarget',listener);
    });
    try {
      await protocol.send('Target.sendMessageToTarget',{sessionId,message:JSON.stringify({id,method,params})});
      return await pending;
    } finally {protocol.off('Target.receivedMessageFromTarget',listener);}
  }
  await send('Network.enable');
  return {
    async offline(value) {
      await send('Network.emulateNetworkConditions',{offline:value,latency:0,
        downloadThroughput:value?0:-1,uploadThroughput:value?0:-1});
    },
    async probe() {
      const result = await send('Runtime.evaluate',{expression:
        "fetch('/health?automatic_offline_probe='+Date.now(),{cache:'no-store'}).then(()=>false,()=>true)",
        awaitPromise:true,returnByValue:true});
      return result.result.value;
    },
    close:() => protocol.detach()
  };
}

async function online(page) {
  await page.waitForFunction(() => !!document.getElementById('offlineWorkspaceBtn')
    && !document.documentElement.hasAttribute('data-offline-workspace'));
}
async function offline(page) {
  try {await page.waitForURL('**/offline');}
  catch(error) {
    console.error('Automatic entry context',await page.evaluate(async()=>({
      url:location.href,onLine:navigator.onLine,native:window.__DMATE_NATIVE_OFFLINE_AVAILABLE__,
      notice:document.getElementById('offlinePreparationStatus')?.textContent,
      controller:navigator.serviceWorker.controller?.scriptURL,
      caches:await Promise.all((await caches.keys()).map(async name=>({name,
        shell:!!await(await caches.open(name)).match('/offline'),
        ready:!!await(await caches.open(name)).match('/__dmate_offline_ready__/'+name)})))
    })).catch(()=>null));
    throw error;
  }
  await revealInterface(page);
  assert.equal(await page.evaluate(()=>navigator.onLine),false);
  assert.equal(await page.evaluate(()=>document.documentElement.hasAttribute('data-offline-workspace')),true);
}
async function warm(page) {
  await page.evaluate(async()=>{await navigator.serviceWorker.ready;});
  await page.waitForFunction(()=>navigator.serviceWorker.controller?.state==='activated');
  // This Playwright runtime treats an async waitForFunction predicate's Promise
  // as truthy. Await the cache Boolean in Node before disconnecting again.
  const deadline=Date.now()+30000;
  while(Date.now()<deadline) {
    if(await page.evaluate(async()=>{
      const cache=await caches.open('dmate-offline-shell-v141');
      return !!await cache.match('/offline')
        && !!await cache.match('/__dmate_offline_ready__/dmate-offline-shell-v141');
    }))return;
    await page.waitForTimeout(50);
  }
  throw new Error('The complete current offline shell was not cached');
}
async function manualReturn(page) {
  await page.locator('#returnOnline').click();
  await online(page);
  await page.waitForLoadState('load');
  assert.equal(new URL(page.url()).pathname,'/');
}

(async()=>{
  const browser=await chromium.launch(launch);
  let context,worker;
  try {
    context=await browser.newContext({viewport:{width:1440,height:900},serviceWorkers:'allow'});
    const page=await context.newPage(),errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto(baseURL+'/',{waitUntil:'load'});await online(page);await warm(page);
    worker=await workerNetwork(browser,page);
    const network=async value=>{await worker.offline(value);await context.setOffline(value);};
    const draft='网络中断前正在编辑的内容，返回在线版仍保留。';
    await page.locator('#text').fill(draft);
    await network(true);await offline(page);
    assert.equal(await worker.probe(),true,'The worker cannot silently use a live connection');
    assert.equal(await page.evaluate(()=>fetch('/health?automatic_page_probe='+Date.now(),{cache:'no-store'}).then(()=>false,()=>true)),true,
      'The page also experiences actual failed network requests');
    await network(false);
    await page.waitForFunction(()=>!document.getElementById('returnOnline').disabled);
    await page.waitForTimeout(500);
    assert.equal(new URL(page.url()).pathname,'/offline','Reconnection preserves manually controlled online return');
    await manualReturn(page);
    await page.waitForFunction(expected=>document.getElementById('text').value===expected,draft);
    console.log('PASS a real network dropout automatically enters canonical /offline and preserves the guest composer draft on manual return');

    // Native hosts can suppress page routing while owning their bundle. This
    // also isolates the worker's redirect from the page offline-event handler.
    await page.evaluate(()=>{window.__DMATE_NATIVE_OFFLINE_AVAILABLE__=true;});
    await network(true);await page.waitForTimeout(150);
    assert.equal(new URL(page.url()).pathname,'/','An explicit native capability owns its navigation');
    assert.equal(await page.evaluate(()=>document.documentElement.hasAttribute('data-offline-workspace')),false);
    await page.reload({waitUntil:'domcontentloaded'});await offline(page);
    assert.equal(new URL(page.url()).pathname,'/offline','Offline navigation fallback redirects instead of serving the native vault under /');
    await network(false);await manualReturn(page);
    console.log('PASS service-worker navigation fallback canonicalizes /offline without a redirect loop, while an explicit native route remains authoritative');

    await page.evaluate(async()=>{
      let shell,latest;
      for(const name of await caches.keys()) if(name.startsWith('dmate-offline-shell-')) {
        const response=await(await caches.open(name)).match('/offline');
        if(response){shell=response;latest=name;}
        await caches.delete(name);
      }
      // An online /offline navigation can leave just HTML after cache eviction.
      // Its presence must not claim that all required scripts/data are ready.
      if(shell)await(await caches.open(latest)).put('/offline',shell);
    });
    await network(true);
    await page.locator('#offlinePreparationStatus').waitFor({state:'visible'});
    assert.equal(new URL(page.url()).pathname,'/','Missing cached resources keep the loaded page rather than displaying a browser network error');
    assert.equal(await page.locator('#text').inputValue(),draft,'The missing-cache notice retains the current draft');
    await network(false);await page.locator('#offlinePreparationStatus').waitFor({state:'detached'});await warm(page);
    await network(true);await offline(page);
    await network(false);await manualReturn(page);
    console.log('PASS an evicted cache containing only HTML shows a truthful notice, repairs on reconnection and supports the next automatic entry');

    // During a rollout the previous worker has a complete offline shell but
    // the new online scripts may still be in flight when the connection drops.
    const bundlePattern=/\/static\/online\/(workspace|controls)\.js\?/;
    const heldRoutes=[];
    await page.route(bundlePattern,route=>{heldRoutes.push(route);});
    try {
      await Promise.all([
        ...['workspace','controls'].map(group=>page.waitForRequest(request=>
          new URL(request.url()).pathname===`/static/online/${group}.js`)),
        page.reload({waitUntil:'commit'})
      ]);
      await network(true);
      await page.waitForURL('**/offline',{waitUntil:'commit',timeout:10000});
      await offline(page);
      assert.equal(heldRoutes.length,2,'Both online bundles were held throughout entry');
      assert.equal(await worker.probe(),true,'The worker cannot fetch from the server');
      await page.locator('.offline-nav-item[data-panel="notes"]').click();
      await page.locator('#notesPanel').waitFor({state:'visible'});
    } finally {
      await page.unroute(bundlePattern);
      await Promise.all(heldRoutes.map(route=>route.abort().catch(()=>{})));
      await network(false);
    }
    await manualReturn(page);
    console.log('PASS pending online bundles do not block automatic entry into working offline notes');

    // A restored/cached online document may start its scripts only after the
    // connection vanished. Run the real entry module from its cached URL in
    // an already same-origin document, without dispatching fake network events.
    const startup=await context.newPage();
    await startup.goto(baseURL+'/health',{waitUntil:'domcontentloaded'});
    await page.evaluate(()=>{window.__DMATE_NATIVE_OFFLINE_AVAILABLE__=true;});
    await network(true);
    await startup.setContent('<!doctype html><html><body><button id="offlineWorkspaceBtn">离线版</button>'
      +'<script src="'+baseURL+'/static/offline-entry.js?v=50"></script></body></html>',{waitUntil:'domcontentloaded'});
    await offline(startup);await startup.close();
    console.log('PASS entry scripts initialized while already disconnected use the cached offline workspace automatically');
    assert.deepEqual(errors,[],'Automatic navigation and cache repair raise no page errors');

    const cold=await browser.newContext({serviceWorkers:'allow'});
    try {
      await cold.setOffline(true);const fresh=await cold.newPage();let failure;
      try {await fresh.goto(baseURL+'/',{waitUntil:'domcontentloaded'});}catch(error){failure=error.message;}
      assert.match(failure||'',/ERR_INTERNET_DISCONNECTED/,'A first-ever disconnected browser visit cannot manufacture an uncached app');
      console.log('PASS the first-ever disconnected browser limitation is explicit; no cached offline availability is claimed');
    } finally {await cold.close();}
  } finally {
    await worker?.close().catch(()=>{});await context?.close();await browser.close();
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
