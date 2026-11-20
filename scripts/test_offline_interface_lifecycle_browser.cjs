/* Every offline entry plays a buttonless introduction, then reveals the
 * restored workspace. Exercise reloads, navigation and browser restoration.
 * Start Flask first; account/sync responses are local fixtures and models are
 * forbidden. The native case changes only the existing app-launch marker.
 */
'use strict';
const assert = require('node:assert/strict');
const {mkdtemp, rm} = require('node:fs/promises');
const {tmpdir} = require('node:os');
const {join} = require('node:path');
const {chromium} = require('playwright');
const {installStorageProbe, revealInterface, records} = require('./offline-vault-browser-fixtures.cjs');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const launch = {headless:true, ...(process.env.CHROMIUM_EXECUTABLE_PATH
  ? {executablePath:process.env.CHROMIUM_EXECUTABLE_PATH} : {})};
const account = 'interface-lifecycle-account';
const content = 'An unfinished concept remains in its original offline workspace';
const ready = page => page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');

async function observeRestoredPanel(page) {
  // Delay a real startup resource so the browser has time to paint the shell
  // before the encrypted view is read. Final-state assertions miss that flash.
  let delayedLoads = 0;
  await page.route('**/static/offline-content/concepts.zh-CN.json*',async route => {
    delayedLoads++;
    await new Promise(resolve => setTimeout(resolve,400));
    await route.continue();
  });
  await page.addInitScript(() => {
    if (location.pathname !== '/offline') return;
    const frames = window.__offlineRestorationFrames = [];
    let running = true;
    window.__stopOfflineRestorationFrames = () => {running = false;};
    const shown = node => {
      if (!node || !node.getClientRects().length) return false;
      const style = getComputedStyle(node);
      return style.display !== 'none' && style.visibility === 'visible' && Number(style.opacity) > 0;
    };
    function sample(time) {
      if (!running) return;
      const layout = document.querySelector('.offline-layout');
      if (layout) frames.push({
        time, ready:document.documentElement.dataset.offlineReady === 'true',
        shown:shown(layout) && !document.getElementById('offlinePrivacyCover')?.open
          && !document.body.classList.contains('offline-content-hidden'),
        active:[...document.querySelectorAll('.offline-nav-item[data-panel].active')].map(node => node.dataset.panel),
        panels:[...document.querySelectorAll('.offline-panel')].filter(shown).map(node => node.id)
      });
      requestAnimationFrame(sample);
    }
    addEventListener('pageshow',event => {
      if (!event.persisted) return;
      frames.length = 0;
      running = true;
      requestAnimationFrame(sample);
    });
    requestAnimationFrame(sample);
  });
  return () => delayedLoads;
}

async function assertRestorationFrames(page,panel,label,loading=true) {
  const frames = await page.evaluate(async () => {
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    __stopOfflineRestorationFrames();
    return __offlineRestorationFrames;
  });
  const visible = frames.filter(frame => frame.shown);
  if (loading) assert.ok(frames.some(frame => !frame.ready),label+': startup was observed before initialization completed');
  assert.ok(visible.length >= 2,label+': the restored workspace actually painted');
  const wrong = visible.filter(frame => frame.active.length !== 1 || frame.active[0] !== panel
    || frame.panels.length !== 1 || frame.panels[0] !== panel+'Panel');
  assert.deepEqual(wrong.slice(0,8),[],label+': every visible frame goes directly to '+panel+', without painting the graph or another selection');
}

async function prepare(context, username='', nativeLaunch) {
  await installStorageProbe(context);
  await context.addInitScript(() => {
    // A window.open document may still report about:blank when init scripts
    // run. Arm the final document at DOMContentLoaded, after deferred scripts
    // start the introduction and before its first painted animation frames.
    let raf = 0;
    function start() {
      cancelAnimationFrame(raf);
      const frames = window.__offlineEntryFrames = [];
      window.__offlineEntryStartedHidden = document.hidden;
      let visibleFrames = 0;
      const started = performance.now();
      const shown = node => node && node.getClientRects().length
        && getComputedStyle(node).visibility === 'visible' && getComputedStyle(node).display !== 'none';
      function sample(time) {
        const cover = document.getElementById('offlinePrivacyCover');
        const layout = document.querySelector('.offline-layout');
        if (cover && layout) {
          const visible = !cover.open && shown(layout) && !document.body.classList.contains('offline-content-hidden');
          frames.push({time,open:cover.open,eye:shown(document.getElementById('offlinePrivacyRestore')),
            modal:cover.open && cover.matches(':modal'),inert:layout.inert,visible,
            ready:document.documentElement.dataset.offlineReady === 'true'});
          visibleFrames = visible ? visibleFrames+1 : 0;
        }
        if (visibleFrames < 3 && performance.now()-started < 15000) raf = requestAnimationFrame(sample);
      }
      raf = requestAnimationFrame(sample);
    }
    addEventListener('pageshow',event => {if (event.persisted) start();});
    // Bind on window: Chromium reuses the popup window across about:blank but
    // replaces its initial document before loading the actual offline page.
    addEventListener('DOMContentLoaded',() => {if (location.pathname === '/offline') start();},{once:true});
  });
  const modelCalls = [];
  await context.route(/\/(?:chat|ocr|drawing\/[^?]+|notebook\/analyze|analyze-questions|conversation\/title)(?:\?|$)/,
    route => {modelCalls.push(route.request().url());return route.abort();});
  await context.route('**/auth/me', route => route.fulfill({contentType:'application/json', body:JSON.stringify({
    configured:true,authenticated:Boolean(username),user:username ? {username} : null
  })}));
  await context.route('**/sync', route => {
    const data = route.request().postDataJSON();
    return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,
      revision:route.request().method()==='GET' ? 0 : Number(data?.baseRevision || 0)+1,data:{},parts:{}})});
  });
  await context.route('**/__offline-interface-fixture', route => route.fulfill({contentType:'text/html',body:
    '<!doctype html><title>Verified local owner</title>'
    +(nativeLaunch ? '<script>window.__DMATE_NATIVE_GUEST_SESSION__='+JSON.stringify(nativeLaunch())+'</script>' : '')
    +'<script src="/static/guest-session.js"></script><a href="/offline">Offline</a>'}));
  if (nativeLaunch) await context.route('**/offline', async route => {
    const response = await route.fetch();
    const html = await response.text();
    return route.fulfill({response,body:html.replace('<head>','<head><script>window.__DMATE_NATIVE_GUEST_SESSION__='
      +JSON.stringify(nativeLaunch())+'</script>')});
  });
  return modelCalls;
}

async function enter(context, username='') {
  const page = await context.newPage();
  await page.goto(baseURL+'/__offline-interface-fixture');
  await page.evaluate(username => DMateGuestSession.setAccountOwner(username),username);
  await page.locator('a[href="/offline"]').click();
  await ready(page);
  return page;
}

async function assertHidden(page, label) {
  await page.waitForFunction(() => document.getElementById('offlinePrivacyCover').open);
  assert.equal(await page.locator('#offlinePrivacyCover').evaluate(node => node.matches(':modal')),true,label+': the cover owns the top layer');
  assert.equal(await page.locator('.offline-layout').evaluate(node => node.inert),true,label+': private controls remain inert');
  assert.equal(await page.locator('#offlinePrivacyRestore').isVisible(),true,label+': the eye remains usable');
  assert.equal(await page.locator('#offlineMain').isVisible(),false,label+': private content is not shown');
}

async function assertAutoEntry(page,label,{sampled=true}={}) {
  await ready(page);
  await page.waitForFunction(() => !document.getElementById('offlinePrivacyCover').open);
  const frames = await page.evaluate(async () => {
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    return window.__offlineEntryFrames || [];
  });
  const intro = frames.filter(frame => frame.open);
  if (sampled) assert.ok(intro.length >= 2,label+': the automatic opening actually paints');
  assert.ok(intro.every(frame => !frame.eye),label+': automatic playback has no eye button');
  assert.ok(intro.every(frame => frame.modal && frame.inert),label+': startup stays above inert private content');
  assert.ok(frames.every(frame => !frame.visible || frame.ready),label+': unfinished restoration is never exposed');
  assert.equal(await page.locator('.offline-layout').evaluate(node => node.inert),false,label+': completion enters the usable workspace automatically');
}

async function assertVisible(page, label) {
  await page.waitForFunction(() => !document.getElementById('offlinePrivacyCover').open);
  assert.equal(await page.locator('.offline-layout').evaluate(node => node.inert),false,label+': workspace is usable');
  if(await page.locator('#notesPanel').evaluate(node => node.hidden)) {
    console.error('Unexpected interface view',await page.evaluate(async () => ({
      path:location.pathname,referrer:document.referrer,tab:window.name,owner:DMateGuestSession.getOwner(),
      type:performance.getEntriesByType('navigation')[0]?.type,
      selected:document.querySelector('.offline-nav-item.active')?.dataset.panel,
      saved:(await __offlineTestStore.all('settings')).filter(row=>row.id.startsWith('view')).map(row=>({id:row.id,panel:row.panel}))
    })));
  }
  assert.equal(await page.locator('#notesPanel').evaluate(node => node.hidden),false,label+': current tool is preserved');
  assert.equal(await page.locator('.dcn-original').inputValue(),content,label+': the ongoing note remains in the editor');
}

async function navigate(page,panel) {
  const mobile = page.viewportSize().width <= 1100;
  const opener = page.locator(mobile ? '#offlineNavToggle' : '#offlineDesktopSidebarOpen');
  if (await opener.getAttribute('aria-expanded')!=='true') await opener.click();
  await page.locator('.offline-nav-item[data-panel="'+panel+'"]').click();
  await page.locator('#'+panel+'Panel').waitFor({state:'visible'});
}

async function createNote(page) {
  await navigate(page,'notes');
  await page.locator('#addNote').click();
  await page.locator('.dcn-title').fill('A concept still being edited');
  await page.locator('.dcn-original').fill(content);
  await page.waitForFunction(async content => (await __offlineTestStore.all('notes')).some(note => note.content===content),content);
  // Checkpointing must commit the current module, not just its data records.
  await page.waitForFunction(async () => {
    const id = 'view:'+window.name;
    return (await __offlineTestStore.get('settings',id))?.panel==='notes';
  });
}

async function hide(page) {
  await page.locator(page.viewportSize().width<=1100 ? '#offlineMobilePrivacyToggle' : '#offlineDesktopPrivacyToggle').click();
  await assertHidden(page,'hide action');
}

async function navigationSession(browser, width, username) {
  const context = await browser.newContext({viewport:{width,height:900},serviceWorkers:'block',reducedMotion:'no-preference'});
  const models = await prepare(context,username), errors=[];
  try {
    const page = await enter(context,username);page.on('pageerror',error => errors.push(error.message));
    await assertAutoEntry(page,'cold '+(username ? 'account' : 'guest'));
    await hide(page);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#offlinePrivacyCover').evaluate(node => node.open),true,'Escape does not expose a hidden workspace');
    await revealInterface(page);await createNote(page);
    const delayedLoads = await observeRestoredPanel(page);
    let beforeLoad = delayedLoads();
    await page.reload({waitUntil:'networkidle'});await ready(page);
    await assertAutoEntry(page,'visible refresh');
    await assertVisible(page,'visible refresh');
    assert.ok(delayedLoads()>beforeLoad,'Visible refresh exercised delayed startup I/O');
    await assertRestorationFrames(page,'notes','visible refresh');
    beforeLoad = delayedLoads();
    await page.goto(baseURL+'/offline',{waitUntil:'networkidle'});await ready(page);
    await assertAutoEntry(page,'same live tab direct navigation');
    await assertVisible(page,'same live tab direct navigation');
    assert.ok(delayedLoads()>beforeLoad,'Direct navigation exercised delayed startup I/O');
    await assertRestorationFrames(page,'notes','same live tab direct navigation');
    await hide(page);await page.reload({waitUntil:'networkidle'});await ready(page);
    await assertAutoEntry(page,'previously hidden refresh');
    await assertVisible(page,'previously hidden refresh');
    assert.equal(await page.locator('#notesPanel').evaluate(node => node.hidden),false,'Refresh retains the current module after automatic entry');
    assert.equal(await page.locator('.dcn-original').inputValue(),content);
    await revealInterface(page);
    if (width>1100) {
      await page.locator('#offlineDesktopSidebarToggle').click();
      await page.reload({waitUntil:'networkidle'});await ready(page);
      await assertAutoEntry(page,'collapsed desktop refresh');
      await assertVisible(page,'collapsed desktop refresh');
      assert.equal(await page.locator('html').getAttribute('data-offline-sidebar'),'collapsed');
    } else {
      await page.locator('#offlineNavToggle').click();
      await page.reload({waitUntil:'networkidle'});await ready(page);
      await assertAutoEntry(page,'open mobile drawer refresh');
      await assertVisible(page,'open mobile drawer refresh');
      assert.equal(await page.locator('body').evaluate(node => node.classList.contains('offline-nav-open')),true);
      await page.locator('#offlineNavClose').click();
    }
    // Use the real online entry, which opens the same device workspace rather
    // than replacing it with the currently signed-in account's cloud records.
    const onlineOpener = page.locator(width<=1100 ? '#offlineNavToggle' : '#offlineDesktopSidebarOpen');
    if(await onlineOpener.getAttribute('aria-expanded')!=='true')await onlineOpener.click();
    await page.locator('#returnOnline').click();
    await page.waitForURL(baseURL+'/');
    await page.waitForFunction(() => document.documentElement.dataset.accountStateKnown==='1'
      && !accountVerificationOperation && !cloudInitialSyncInFlight);
    await page.evaluate(() => {if(typeof stopCloudLivePolling==='function')stopCloudLivePolling();});
    if(width>1100) {
      const opener = page.locator('#desktopSidebarOpen');
      if(await opener.getAttribute('aria-expanded')!=='true')await opener.click();
    } else await page.locator('#mobileNavBtn').click();
    beforeLoad = delayedLoads();
    await page.locator('#offlineWorkspaceBtn').click();
    await page.waitForURL('**/offline');await ready(page);
    await assertAutoEntry(page,'same-tab online round trip');
    await assertVisible(page,'same-tab online round trip');
    assert.ok(delayedLoads()>beforeLoad,'Online round trip exercised delayed startup I/O');
    await assertRestorationFrames(page,'notes','same-tab online round trip');
    await page.goBack({waitUntil:'domcontentloaded'});
    await page.waitForFunction(() => document.documentElement.dataset.accountStateKnown==='1'
      && !accountVerificationOperation && !cloudInitialSyncInFlight);
    beforeLoad = delayedLoads();
    await page.goForward({waitUntil:'domcontentloaded'});await ready(page);
    await assertAutoEntry(page,'same-session history back and forward');
    await assertVisible(page,'same-session history back and forward');
    await assertRestorationFrames(page,'notes','same-session history back and forward',delayedLoads()>beforeLoad);
    // A real window.open receives an opener copy of sessionStorage in Chromium;
    // it must still play its own introduction without mutating the source tab.
    const copied = page.waitForEvent('popup');
    await page.evaluate(() => window.open('/offline','_blank'));
    const other = await copied;await ready(other);await assertAutoEntry(other,'opener-copied new tab');
    assert.ok((await records(other,'notes')).some(note=>note.content===content),'Every tab sees this device’s offline concepts without verifying an account');
    await revealInterface(other);await navigate(other,'questions');
    await other.waitForFunction(async () => (await __offlineTestStore.get('settings','view:'+window.name))?.panel==='questions');
    await page.reload({waitUntil:'networkidle'});await ready(page);await assertAutoEntry(page,'independent device tab navigation');await assertVisible(page,'independent device tab navigation');
    assert.doesNotMatch(await page.locator('#offlineToast').textContent(),/CONFLICT|另一页面|another page/i);
    await other.close();await assertVisible(page,'source tab after opening another tab');
    await page.close();
    const reopened = await enter(context,username);await assertAutoEntry(reopened,'closed tab opened again');
    const restored = await records(reopened,'notes');
    assert.ok(restored.some(note=>note.content===content),'Device data remains available after closing the original tab, including without an account');
    assert.deepEqual(models,[]);assert.deepEqual(errors,[]);
    console.log('PASS interface session '+width+'/'+(username?'account':'guest')+': buttonless automatic entry, manual cover, frame-by-frame restored panel, refresh, drawer state, real online hop and copied/new tabs');
  } finally {await context.close();}
}

async function restoredBrowserProcess() {
  const profile = await mkdtemp(join(tmpdir(),'dmate-interface-restored-'));
  const options = {...launch,args:['--restore-last-session'],serviceWorkers:'block',viewport:{width:1440,height:900},reducedMotion:'no-preference'};
  let context;
  try {
    context = await chromium.launchPersistentContext(profile,options);await prepare(context);
    for(const blank of context.pages())if(blank.url()==='about:blank')await blank.close();
    const page = await enter(context);await assertAutoEntry(page,'first unsigned-in browser process');
    await revealInterface(page);await createNote(page);
    await page.evaluate(() => sessionStorage.setItem('__interface_restore_probe','restored-session-storage'));
    await context.close();context=null;
    context = await chromium.launchPersistentContext(profile,options);await prepare(context);
    // Chromium restores the actual previous /offline tab, including its
    // sessionStorage. A new page here would miss the critical restored-tab case.
    const candidates = context.pages();
    const waitForRestored = page => page.waitForURL('**/offline',{timeout:15000}).then(() => page);
    const restored = await Promise.any([
      ...candidates.map(waitForRestored),
      context.waitForEvent('page',{timeout:15000}).then(waitForRestored)
    ]);
    await restored.waitForLoadState('domcontentloaded');await ready(restored);
    const originState = await restored.evaluate(() => ({
      copied:sessionStorage.getItem('__interface_restore_probe'),
      type:performance.getEntriesByType('navigation')[0]?.type,
      referrer:document.referrer
    }));
    assert.equal(originState.copied,'restored-session-storage','The test exercises a genuine browser-restored tab with retained sessionStorage');
    // Session restoration starts while launchPersistentContext is resolving,
    // before prepare() can install frame observers on the existing document.
    await assertAutoEntry(restored,'restarted browser restored tab',{sampled:false});
    const restoredNotes=await restored.evaluate(async()=>{
      // The restored document can finish before prepare installs its probe.
      // Read the same device vault through a second real adapter in that case.
      if(window.__offlineTestStore)return __offlineTestStore.all('notes');
      const storage=await DMateOfflineStorage.open({scope:'device',isCurrent:()=>true});
      try{return await storage.all('notes');}finally{storage.close();}
    });
    assert.ok(restoredNotes.some(note=>note.content===content),'Device notes survive a real process restart without account verification');
    // Signing in after reopening changes online identity, not offline contents.
    await restored.goto(baseURL+'/__offline-interface-fixture');
    await restored.evaluate(username=>DMateGuestSession.setAccountOwner(username),account);
    await restored.locator('a[href="/offline"]').click();await ready(restored);
    assert.ok((await records(restored,'notes')).some(note=>note.content===content),'Signing in after restart retains the same encrypted device notes');
    console.log('PASS real process restore: retained sessionStorage plays automatic entry; device notes survive without login ('+originState.type+')');
  } finally {await context?.close();await rm(profile,{recursive:true,force:true});}
}

async function nativeLaunchPersistence(browser) {
  let nativeLaunch = 'interface-native-launch-one';
  const context = await browser.newContext({viewport:{width:390,height:844},serviceWorkers:'block',reducedMotion:'no-preference'});
  const models = await prepare(context,'',()=>nativeLaunch);
  try {
    const page = await enter(context);await assertAutoEntry(page,'native first launch');
    await revealInterface(page);await createNote(page);
    await page.reload({waitUntil:'networkidle'});await ready(page);await assertAutoEntry(page,'same native launch refresh');await assertVisible(page,'same native launch refresh');
    nativeLaunch = 'interface-native-launch-two';
    await page.reload({waitUntil:'networkidle'});await ready(page);await assertAutoEntry(page,'new native launch');
    assert.ok((await records(page,'notes')).some(note=>note.content===content),'A new native launch retains device notes even when the online guest session changes');
    await navigate(page,'notes');await assertVisible(page,'new native launch device contents');
    assert.deepEqual(models,[]);
    console.log('PASS native launch marker: every launch enters automatically and device concepts survive a new online guest session');
  } finally {await context.close();}
}

(async()=>{
  const browser = await chromium.launch(launch);
  const selected = process.env.DMATE_TEST_INTERFACE_CASE;
  try {
    if(!selected || selected==='account')await navigationSession(browser,1440,account);
    if(!selected || selected==='guest')await navigationSession(browser,390,'');
    if(!selected || selected==='native')await nativeLaunchPersistence(browser);
  }
  finally {await browser.close();}
  if(!selected || selected==='process')await restoredBrowserProcess();
})().catch(error=>{console.error(error);process.exitCode=1;});
