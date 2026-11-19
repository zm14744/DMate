/* The privacy cover belongs to a tab/app use session, independently of the
 * encrypted records. Exercise real reloads, navigation and browser restoration.
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

async function prepare(context, username='', nativeLaunch) {
  await installStorageProbe(context);
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
    const id = DMateGuestSession.getOwner() ? 'view:'+window.name : 'view';
    return (await __offlineTestStore.get('settings',id))?.panel==='notes';
  });
}

async function hide(page) {
  await page.locator(page.viewportSize().width<=1100 ? '#offlineMobilePrivacyToggle' : '#offlineDesktopPrivacyToggle').click();
  await assertHidden(page,'hide action');
}

async function navigationSession(browser, width, username) {
  const context = await browser.newContext({viewport:{width,height:900},serviceWorkers:'block'});
  const models = await prepare(context,username), errors=[];
  try {
    const page = await enter(context,username);page.on('pageerror',error => errors.push(error.message));
    await assertHidden(page,'cold '+(username ? 'account' : 'guest'));
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#offlinePrivacyCover').evaluate(node => node.open),true,'Escape does not expose a hidden workspace');
    await revealInterface(page);await createNote(page);
    await page.reload({waitUntil:'networkidle'});await ready(page);
    await assertVisible(page,'visible refresh');
    await page.goto(baseURL+'/offline',{waitUntil:'networkidle'});await ready(page);
    await assertVisible(page,'same live tab direct navigation');
    await hide(page);await page.reload({waitUntil:'networkidle'});await ready(page);
    await assertHidden(page,'hidden refresh');
    assert.equal(await page.locator('#notesPanel').evaluate(node => node.hidden),false,'Hidden refresh retains the current module behind its cover');
    assert.equal(await page.locator('.dcn-original').inputValue(),content);
    await revealInterface(page);
    if (width>1100) {
      await page.locator('#offlineDesktopSidebarToggle').click();
      await page.reload({waitUntil:'networkidle'});await ready(page);
      await assertVisible(page,'collapsed desktop refresh');
      assert.equal(await page.locator('html').getAttribute('data-offline-sidebar'),'collapsed');
    } else {
      await page.locator('#offlineNavToggle').click();
      await page.reload({waitUntil:'networkidle'});await ready(page);
      await assertVisible(page,'open mobile drawer refresh');
      assert.equal(await page.locator('body').evaluate(node => node.classList.contains('offline-nav-open')),true);
      await page.locator('#offlineNavClose').click();
    }
    // Use the real online entry and its encrypted handoff, rather than copying
    // the session marker into another fixture document.
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
    await page.locator('#offlineWorkspaceBtn').click();
    await page.waitForURL('**/offline');await ready(page);
    await assertVisible(page,'same-tab online round trip');
    await page.goBack({waitUntil:'domcontentloaded'});
    await page.waitForFunction(() => document.documentElement.dataset.accountStateKnown==='1'
      && !accountVerificationOperation && !cloudInitialSyncInFlight);
    await page.goForward({waitUntil:'domcontentloaded'});await ready(page);
    await assertVisible(page,'same-session history back and forward');
    // A real window.open receives an opener copy of sessionStorage in Chromium;
    // it must still start hidden and must not mutate the source tab's state.
    const copied = page.waitForEvent('popup');
    await page.evaluate(() => window.open('/offline','_blank'));
    const other = await copied;await ready(other);await assertHidden(other,'opener-copied new tab');
    if(username) {
      await other.goto(baseURL+'/__offline-interface-fixture');
      await other.evaluate(username=>DMateGuestSession.setAccountOwner(username),username);
      await other.locator('a[href="/offline"]').click();await ready(other);await revealInterface(other);
      await navigate(other,'questions');
      await other.waitForFunction(async () => (await __offlineTestStore.get('settings','view:'+window.name))?.panel==='questions');
      await page.reload({waitUntil:'networkidle'});await ready(page);await assertVisible(page,'independent account tab navigation');
      assert.doesNotMatch(await page.locator('#offlineToast').textContent(),/CONFLICT|另一页面|another page/i);
    }
    await other.close();await assertVisible(page,'source tab after opening another tab');
    await page.close();
    const reopened = await enter(context,username);await assertHidden(reopened,'closed tab opened again');
    const restored = await records(reopened,'notes');
    if(username)assert.ok(restored.some(note=>note.content===content),'Account data remains available behind a new-session cover');
    else assert.deepEqual(restored,[],'A new guest tab does not adopt the old guest note');
    assert.deepEqual(models,[]);assert.deepEqual(errors,[]);
    console.log('PASS interface session '+width+'/'+(username?'account':'guest')+': default cover, refresh, drawer state, real online hop and copied/new tabs');
  } finally {await context.close();}
}

async function restoredBrowserProcess() {
  const profile = await mkdtemp(join(tmpdir(),'dmate-interface-restored-'));
  const options = {...launch,args:['--restore-last-session'],serviceWorkers:'block',viewport:{width:1440,height:900}};
  let context;
  try {
    context = await chromium.launchPersistentContext(profile,options);await prepare(context,account);
    for(const blank of context.pages())if(blank.url()==='about:blank')await blank.close();
    const page = await enter(context,account);await assertHidden(page,'first browser process');
    await revealInterface(page);await createNote(page);
    await page.evaluate(() => sessionStorage.setItem('__interface_restore_probe','restored-session-storage'));
    await context.close();context=null;
    context = await chromium.launchPersistentContext(profile,options);await prepare(context,account);
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
    await assertHidden(restored,'restarted browser restored tab');
    // Restored browser tabs may no longer be verified as the old account.
    // Reverify through the local fixture, then confirm the persistent records.
    await restored.goto(baseURL+'/__offline-interface-fixture');
    await restored.evaluate(username=>DMateGuestSession.setAccountOwner(username),account);
    await restored.locator('a[href="/offline"]').click();await ready(restored);
    assert.ok((await records(restored,'notes')).some(note=>note.content===content),'Encrypted account notes survive a real process restart');
    console.log('PASS real process restore: retained sessionStorage starts covered; account records survive ('+originState.type+')');
  } finally {await context?.close();await rm(profile,{recursive:true,force:true});}
}

async function nativeLaunchReset(browser) {
  let nativeLaunch = 'interface-native-launch-one';
  const context = await browser.newContext({viewport:{width:390,height:844},serviceWorkers:'block'});
  const models = await prepare(context,'',()=>nativeLaunch);
  try {
    const page = await enter(context);await assertHidden(page,'native first launch');
    await revealInterface(page);await createNote(page);
    await page.reload({waitUntil:'networkidle'});await ready(page);await assertVisible(page,'same native launch refresh');
    nativeLaunch = 'interface-native-launch-two';
    await page.reload({waitUntil:'networkidle'});await ready(page);await assertHidden(page,'new native launch');
    assert.deepEqual(await records(page,'notes'),[],'A new native guest launch rejects the previous guest workspace');
    assert.deepEqual(models,[]);
    console.log('PASS native launch marker: same-launch state is retained; a new launch resets cover and guest workspace');
  } finally {await context.close();}
}

(async()=>{
  const browser = await chromium.launch(launch);
  const selected = process.env.DMATE_TEST_INTERFACE_CASE;
  try {
    if(!selected || selected==='account')await navigationSession(browser,1440,account);
    if(!selected || selected==='guest')await navigationSession(browser,390,'');
    if(!selected || selected==='native')await nativeLaunchReset(browser);
  }
  finally {await browser.close();}
  if(!selected || selected==='process')await restoredBrowserProcess();
})().catch(error=>{console.error(error);process.exitCode=1;});
