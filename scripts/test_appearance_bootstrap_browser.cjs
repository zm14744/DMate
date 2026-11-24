/* Saved visuals must paint before the main application or account API is ready.
 * Identity in the HTML fixture represents the server-verified home hint. */
'use strict';
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const {installStorageProbe} = require('./offline-vault-browser-fixtures.cjs');
const base = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const owner = 'appearance-first-paint';
const profile = {mode:'navy',accent:'teal',backgroundFit:'contain',mask:17,blur:3,panelOpacity:80,bubbleOpacity:70};
function gate() {let release;const ready = new Promise(resolve => {release = resolve;});return {ready,release};}
async function sample(page) {
  return page.evaluate(() => ({theme:document.documentElement.dataset.appearanceTheme,
    bodyTheme:document.body?.dataset.appearanceTheme,
    accent:document.documentElement.style.getPropertyValue('--accent'),
    font:document.documentElement.style.getPropertyValue('--font-scale'),
    panel:document.documentElement.style.getPropertyValue('--panel-alpha'),
    bubble:document.documentElement.style.getPropertyValue('--bubble-alpha'),
    background:document.body?.classList.contains('has-custom-background'),
    backgroundImage:document.getElementById('appearanceBackgroundLayer')?.style.backgroundImage}));
}
async function savedPaint(page) {
  try { await page.waitForFunction(() => document.body?.classList.contains('has-custom-background')); }
  catch(error) {console.error('Missing wallpaper',await sample(page),await page.evaluate(()=>({bootstrap:window.DMateAppearanceBootstrap && {scope:DMateAppearanceBootstrap.scope,owner:DMateAppearanceBootstrap.owner,settings:DMateAppearanceBootstrap.settings},meta:localStorage.getItem('discrete_math_ai_cloud_sync_v1')})));throw error;}
  const actual = await sample(page);
  assert.deepEqual({...actual,backgroundImage:''},{theme:'navy',bodyTheme:'navy',accent:'#14b8a6',font:'1',panel:'0.8',bubble:'0.7',background:true,backgroundImage:''});
  assert.match(actual.backgroundImage,/blob:/);
}
async function seed(page, legacySize) {
  await page.goto(base+'/static/offline.html',{waitUntil:'networkidle'});
  await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
  await page.evaluate(async ({owner,profile}) => {
    const canvas = document.createElement('canvas');canvas.width=16;canvas.height=16;
    const drawing=canvas.getContext('2d');drawing.fillStyle='#a74060';drawing.fillRect(0,0,16,16);
    const blob = await new Promise(resolve => canvas.toBlob(resolve));
    localStorage.setItem('discrete_math_ai_appearance_v1::'+encodeURIComponent(owner),JSON.stringify(profile));
    localStorage.setItem('discrete_math_ai_cloud_sync_v1',JSON.stringify({username:owner}));
    await new Promise((resolve,reject) => {
      const opening=indexedDB.open('discrete_math_ai_appearance_assets_v1',1);
      opening.onupgradeneeded=()=>opening.result.createObjectStore('assets');
      opening.onerror=()=>reject(opening.error);
      opening.onsuccess=()=>{const db=opening.result,tx=db.transaction('assets','readwrite');
        tx.objectStore('assets').put(blob,'global_background');tx.oncomplete=()=>{db.close();resolve();};tx.onerror=()=>reject(tx.error);};
    });
    await __offlineTestStore.put('settings',{id:'appearance',settings:profile,backgroundBlob:blob});
    await DMateOfflineAppearance.apply(profile,blob);
    localStorage.setItem('dmate:offline:appearance-paint:v1',JSON.stringify(profile));
  },{owner,profile:{...profile,fontSize:legacySize}});
}
async function captureFrames(context) {
  await context.addInitScript(() => {
    window.__appearanceFrames=[];
    const frame=()=>{if (document.body && document.getElementById('appearanceBackgroundLayer')) {
      __appearanceFrames.push({theme:document.documentElement.dataset.appearanceTheme,font:document.documentElement.style.getPropertyValue('--font-scale'),
        panel:document.documentElement.style.getPropertyValue('--panel-alpha')});
    } if (__appearanceFrames.length<180) requestAnimationFrame(frame);};requestAnimationFrame(frame);
  });
}
async function verifiedOnline(context) {
  const page=await context.newPage(), main=gate(), auth=gate();let authRequested=false;
  await page.route(base+'/',async route=>{
    const response=await route.fetch(),html=(await response.text()).replace(/(id="dmateAppearanceBootstrap"[^>]*data-owner=")[^"]*/, '$1'+owner);
    await route.fulfill({response,body:html});
  });
  await page.route('**/static/script.js*',async route=>{await main.ready;await route.continue();});
  await page.route('**/auth/me',async route=>{authRequested=true;await auth.ready;await route.fulfill({json:{configured:true,authenticated:true,user:{username:owner}}});});
  await page.route('**/sync*',route=>route.fulfill({json:{revision:0,sessions:[],learning:{}}}));
  await page.goto(base+'/',{waitUntil:'commit'});
  await savedPaint(page); // Main script is still held, proving head restoration.
  const initialURL=(await sample(page)).backgroundImage;
  main.release();await page.waitForFunction(()=>typeof initAppearanceSystem==='function');
  await page.waitForTimeout(120);
  assert.equal(authRequested,true);
  await savedPaint(page); // The slower auth API must not repaint the OS default.
  assert.equal((await sample(page)).backgroundImage,initialURL,'Main script adopts the decoded wallpaper URL');
  auth.release();await page.waitForFunction(owner=>accountState.authenticated && accountState.username===owner,owner);
  await savedPaint(page);
  assert.equal((await sample(page)).backgroundImage,initialURL,'Verified account initialization keeps the same wallpaper');
  const frames=await page.evaluate(()=>__appearanceFrames);
  assert.ok(frames.length>0);
  assert.ok(frames.every(frame=>frame.theme==='navy' && frame.font==='1' && frame.panel==='0.8'),'Every painted frame keeps the saved colors and standard text size');
  await page.evaluate(()=>{appearanceSettings.mode='light';applyAppearanceSettings({save:false});});
  assert.equal(await page.evaluate(()=>document.documentElement.style.backgroundColor),'rgb(245, 245, 247)','Theme changes update the root overscroll color');
  await page.close();
}
async function offlineStartup(context) {
  const page=await context.newPage(), storage=gate();
  await page.route('**/static/offline-storage.js*',async route=>{await storage.ready;await route.continue();});
  await page.goto(base+'/static/offline.html',{waitUntil:'commit'});
  await savedPaint(page);
  assert.equal(await page.evaluate(()=>document.documentElement.dataset.offlineReady),undefined,'Device appearance loads independently of workspace migration');
  const initialURL=(await sample(page)).backgroundImage;
  storage.release();await page.waitForFunction(()=>document.documentElement.dataset.offlineReady==='true');
  await savedPaint(page);
  assert.equal((await sample(page)).backgroundImage,initialURL,'Offline application adopts its predecoded device wallpaper');
  const frames=await page.evaluate(()=>__appearanceFrames);
  assert.ok(frames.length>0 && frames.every(frame=>frame.theme==='navy' && frame.font==='1' && frame.panel==='0.8'));
  await page.close();
}
async function guestIsolation(context) {
  const page=await context.newPage(), main=gate();
  await page.route('**/static/script.js*',async route=>{await main.ready;await route.continue();});
  await page.route('**/auth/me',route=>route.fulfill({json:{configured:true,authenticated:false}}));
  await page.goto(base+'/',{waitUntil:'commit'});
  await page.waitForFunction(()=>document.body && document.getElementById('appearanceBackgroundLayer'));
  assert.equal((await sample(page)).theme,'light');assert.equal((await sample(page)).background,false,'Guest does not inherit account wallpaper or offline appearance');
  assert.deepEqual(await page.evaluate(()=>[
    document.documentElement.style.backgroundColor,
    document.querySelector('meta[name="theme-color"]').content,
    getComputedStyle(document.body).backgroundColor
  ]),['rgb(245, 245, 247)','#f5f5f7','rgb(245, 245, 247)'],'The first document paint, browser bar and page use the same light color');
  main.release();await page.waitForFunction(()=>typeof appearanceSettings!=='undefined' && accountState.configured!==null);
  await page.evaluate(async profile=>{appearanceSettings={...profile,mode:'dark'};applyAppearanceSettings({save:true});
    const canvas=document.createElement('canvas');canvas.width=canvas.height=8;const blob=await new Promise(resolve=>canvas.toBlob(resolve));
    await writeAppearanceBackgroundBlob(blob);setAppearanceBackgroundVisual(blob);},profile);
  await page.reload({waitUntil:'networkidle'});
  assert.equal((await sample(page)).theme,'dark');assert.equal((await sample(page)).background,true,'Same guest tab reload preserves its temporary appearance');
  await page.close();
  const fresh=await context.newPage();await fresh.goto(base+'/',{waitUntil:'domcontentloaded'});
  assert.equal((await sample(fresh)).theme,'light');assert.equal((await sample(fresh)).background,false,'Closed guest tab never restores in a new tab');
  await fresh.close();
}
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.CHROMIUM_EXECUTABLE_PATH}:{})});
  try {
    for (const width of [1440,390]) {
      // The offline seed page can install a worker that bypasses the routed HTML
      // identity and the deliberately held scripts used by these first-paint checks.
      const context=await browser.newContext({viewport:{width,height:900},colorScheme:'light',serviceWorkers:'block'});
      await installStorageProbe(context);await captureFrames(context);
      const seedPage=await context.newPage();await seed(seedPage,width===1440?'large':'small');await seedPage.close();
      await verifiedOnline(context);await offlineStartup(context);await guestIsolation(context);
      await context.close();console.log('Appearance first-paint, delayed initialization, and isolation passed at '+width+'px');
    }
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
