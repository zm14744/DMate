/* The real local workspace keeps its return-online control responsive while
 * encrypted storage is pending or fails. Native connectivity is a JS fixture;
 * this does not claim to exercise Android callbacks or an OS key store.
 */
'use strict';
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const {revealInterface} = require('./offline-vault-browser-fixtures.cjs');
const baseURL = (process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000').replace(/\/$/,'');
const launch = {headless:true, ...(process.env.CHROMIUM_EXECUTABLE_PATH
  ? {executablePath:process.env.CHROMIUM_EXECUTABLE_PATH} : {})};

async function fixture(browser, options = {}) {
  const context = await browser.newContext({viewport:{width:1440,height:900},serviceWorkers:'block'});
  await context.route('**/auth/me',route => route.fulfill({contentType:'application/json',
    body:'{"configured":true,"authenticated":false}'}));
  await context.addInitScript(options => {
    window.__startupDocument = Math.random().toString(36);
    if (options.native !== undefined) window.__DMATE_NATIVE_NETWORK_ONLINE__ = options.native;
    if (options.browser !== undefined) {
      window.__startupBrowserOnline = options.browser;
      Object.defineProperty(navigator,'onLine',{configurable:true,get:()=>window.__startupBrowserOnline});
    }
    let published;
    Object.defineProperty(window,'DMateOfflineStorage',{
      configurable:true,
      get:()=>published,
      set(api) {
        published = {...api, async open(settings) {
          window.__startupStorageStarted = true;
          if (options.failure) throw Object.assign(new Error('The system key store is locked'),{code:'KEYSTORE_UNAVAILABLE'});
          await new Promise(resolve => {window.__releaseStartupStorage=resolve;});
          return api.open(settings);
        }};
      }
    });
  },options);
  const page = await context.newPage(), errors = [], packs = new Set();
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>{
    const url = new URL(request.url());
    if (url.pathname.startsWith('/static/offline-content/') && url.pathname.endsWith('.json')) packs.add(url.pathname);
  });
  await page.goto(baseURL+'/offline',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.__startupStorageStarted === true);
  return {context,page,errors,packs};
}

async function pending(page) {
  assert.equal(await page.evaluate(()=>document.documentElement.hasAttribute('data-offline-interface-pending')),true,
    'The actual workspace initialization is still pending');
  assert.notEqual(await page.evaluate(()=>document.documentElement.dataset.offlineReady),'true');
}

async function realNetwork(browser) {
  const {context,page,errors,packs} = await fixture(browser);
  try {
    // Network-idle is independent of the held storage promise. It also ensures
    // lazy MathJax files finish before the browser's network is disconnected.
    await page.waitForLoadState('networkidle');
    assert.equal(packs.size,4,'All four public study packs start before encrypted storage is ready');
    await pending(page);
    const document = await page.evaluate(()=>window.__startupDocument);
    await context.setOffline(true);
    await page.waitForFunction(()=>navigator.onLine === false && document.getElementById('returnOnline').disabled);
    await context.setOffline(false);
    await page.waitForFunction(()=>navigator.onLine === true && !document.getElementById('returnOnline').disabled);
    await pending(page);
    assert.equal(await page.evaluate(()=>window.__startupDocument),document,'Reconnection updates the existing document');
    assert.equal(new URL(page.url()).pathname,'/offline','Reconnection never returns online automatically');
    await context.setOffline(true);
    await page.waitForFunction(()=>document.getElementById('returnOnline').disabled);
    await page.evaluate(()=>__releaseStartupStorage());
    await page.waitForFunction(()=>document.documentElement.dataset.offlineReady === 'true');
    await revealInterface(page);
    assert.equal(await page.locator('#returnOnline').isDisabled(),true,'Finishing initialization does not enable the icon while offline');
    await context.setOffline(false);
    await page.waitForFunction(()=>!document.getElementById('returnOnline').disabled);
    await page.waitForTimeout(150);
    assert.equal(new URL(page.url()).pathname,'/offline','The ready workspace also waits for a manual return');
    await page.locator('#returnOnline').click();
    await page.waitForURL(baseURL+'/');
    await page.waitForFunction(()=>!document.documentElement.hasAttribute('data-offline-workspace'));
    assert.deepEqual(errors,[]);
    console.log('PASS real network loss/recovery during pending storage and after readiness updates the icon without reload; public study packs load in parallel');
  } finally {await context.close();}
}

async function nativeNetwork(browser) {
  const {context,page,errors} = await fixture(browser,{native:false});
  try {
    await pending(page);
    assert.equal(await page.evaluate(()=>navigator.onLine),true,'The browser link remains up in the native-state fixture');
    assert.equal(await page.locator('#returnOnline').isDisabled(),true,'A validated native offline snapshot overrides the browser link');
    await page.evaluate(()=>dispatchEvent(new Event('online')));
    assert.equal(await page.locator('#returnOnline').isDisabled(),true,'A browser event cannot override a native offline snapshot');
    // Dispatch bypasses the disabled button only to exercise its guard. Actual
    // users cannot trigger a disabled control.
    await page.locator('#returnOnline').dispatchEvent('click');
    await page.waitForTimeout(75);
    assert.equal(new URL(page.url()).pathname,'/offline','The return handler uses the same native connectivity guard');
    await page.evaluate(()=>{
      __DMATE_NATIVE_NETWORK_ONLINE__=true;
      dispatchEvent(new CustomEvent('dmate:native-network-change',{detail:{online:true}}));
    });
    await page.waitForFunction(()=>!document.getElementById('returnOnline').disabled);
    await pending(page);
    assert.equal(new URL(page.url()).pathname,'/offline','Native recovery changes availability, not the current page');
    // The privacy introduction can still cover the page during pending I/O.
    // This checks logical action availability; the ready-state case above uses
    // a real pointer click after the actual interface is revealed.
    await page.evaluate(()=>document.getElementById('returnOnline').click());
    await page.waitForURL(baseURL+'/');
    assert.deepEqual(errors,[]);
    console.log('PASS native connectivity snapshot/events override stale browser status and allow a guarded manual return before storage becomes ready');
  } finally {await context.close();}
}

async function failureRecovery(browser) {
  const {context,page,errors} = await fixture(browser,{browser:false,failure:true});
  try {
    await page.waitForFunction(()=>!document.documentElement.hasAttribute('data-offline-interface-pending'));
    assert.notEqual(await page.evaluate(()=>document.documentElement.dataset.offlineReady),'true');
    assert.equal(await page.locator('#returnOnline').isDisabled(),true);
    const document = await page.evaluate(()=>window.__startupDocument);
    await page.evaluate(()=>{__startupBrowserOnline=true;dispatchEvent(new Event('focus'));});
    await page.waitForFunction(()=>!document.getElementById('returnOnline').disabled);
    await page.evaluate(()=>{__startupBrowserOnline=false;dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}));});
    await page.waitForFunction(()=>document.getElementById('returnOnline').disabled);
    assert.equal(await page.evaluate(()=>window.__startupDocument),document,'Resuming a failed startup never requires a reload');
    assert.deepEqual(errors,[],'A failed storage open leaves no unhandled parallel startup error');
    console.log('PASS failed initialization retains immediate focus/pageshow connectivity recovery without reloading');
  } finally {await context.close();}
}

(async()=>{
  const browser = await chromium.launch(launch);
  try {await realNetwork(browser);await nativeNetwork(browser);await failureRecovery(browser);}
  finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
