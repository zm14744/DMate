/* Exercise painted topology growth in the real offline privacy dialog. The
 * cover must remain usable while motion starts, stops or is disabled. Start
 * Flask first; every case uses an isolated guest workspace and local assets.
 */
'use strict';
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const {installStorageProbe,revealInterface} = require('./offline-vault-browser-fixtures.cjs');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const launch = {headless:true, ...(process.env.CHROMIUM_EXECUTABLE_PATH
  ? {executablePath:process.env.CHROMIUM_EXECUTABLE_PATH} : {})};

async function installSamples(context) {
  await context.addInitScript(() => {
    if (location.pathname !== '/offline') return;
    window.__privacyMotionSnapshot = () => {
      const cover = document.getElementById('offlinePrivacyCover');
      const svg = cover?.querySelector('.offline-privacy-mark-growth');
      if (!svg) return null;
      const lines = [...svg.querySelectorAll('line')];
      const visible = lines.filter(line => getComputedStyle(line).display !== 'none');
      const segments = visible.map(line => {
        // The last samples include the closed dialog, where Chromium cannot measure rendered SVG paths.
        const length = Math.hypot(line.x2.baseVal.value - line.x1.baseVal.value,
          line.y2.baseVal.value - line.y1.baseVal.value);
        const dash = Number.parseFloat(line.getAttribute('stroke-dasharray'));
        return {length, drawn: Number.isFinite(dash) ? Math.min(dash, length) : length};
      });
      const style = getComputedStyle(svg);
      const shown = node => node && node.getClientRects().length && getComputedStyle(node).visibility === 'visible'
        && getComputedStyle(node).display !== 'none' && Number(getComputedStyle(node).opacity) > 0;
      const eye = document.getElementById('offlinePrivacyRestore');
      return {time:performance.now(), open:cover.open, lines:lines.length, visible:visible.length,
        eyeVisible:Boolean(shown(eye)), ready:document.documentElement.dataset.offlineReady === 'true',
        pending:document.documentElement.hasAttribute('data-offline-interface-pending'),
        workspaceVisible:!cover.open && Boolean(shown(document.querySelector('.offline-layout'))),
        panels:[...document.querySelectorAll('.offline-panel')].filter(shown).map(node => node.id),
        partial:segments.filter(segment => segment.drawn < segment.length - 0.05).length,
        length:segments.reduce((sum,segment) => sum + segment.drawn,0),
        painted:cover.open && style.visibility === 'visible' && style.display !== 'none'
          && svg.getBoundingClientRect().width > 0,
        signature:svg.innerHTML};
    };
    const frames = window.__privacyColdFrames = [];
    let first, firstClosed;
    function sample() {
      const row = window.__privacyMotionSnapshot();
      if (row) {
        first ??= row.time;
        frames.push(row);
        if (!row.open) firstClosed ??= row.time;
      }
      if (first === undefined || ((firstClosed === undefined || performance.now()-firstClosed < 250)
        && performance.now()-first < 6000)) requestAnimationFrame(sample);
      else window.__privacyColdSampleComplete = true;
    }
    requestAnimationFrame(sample);
  });
}

function assertGrowth(frames,label,settles=true) {
  const painted = frames.filter(frame => frame.painted);
  const partial = painted.filter(frame => frame.partial > 0 && frame.visible > 0);
  assert.ok(partial.length >= 3,label+': several painted frames contain growing edges');
  assert.ok(new Set(partial.map(frame => frame.length.toFixed(2))).size >= 3,
    label+': the visible drawing grows over time');
  for (let i=1;i<painted.length;i++) assert.ok(painted[i].length+0.1 >= painted[i-1].length,
    label+': growth does not jump back to an earlier drawing');
  const end = frames.at(-1);
  assert.equal(end.lines,42,label+': the original 21 edges retain both propagation directions');
  assert.equal(end.visible,21,label+': the final logo closes every original edge once');
  assert.equal(end.partial,0,label+': the final logo has no incomplete edges');
  if (settles) {
    const settled = painted.filter(frame => frame.time-end.time > -200);
    assert.ok(settled.length >= 2,label+': the completed logo actually paints');
    assert.equal(new Set(settled.map(frame => frame.signature)).size,1,label+': completed logo stays still');
  }
}

function assertIntro(frames,label,requiresGrowth=true) {
  const painted = frames.filter(frame => frame.painted);
  if (requiresGrowth) assert.ok(painted.length >= 3,label+': the automatic introduction paints before entering');
  assert.ok(painted.every(frame => !frame.eyeVisible),label+': autoplay has no eye button');
  assert.equal(frames.at(-1).open,false,label+': playback enters automatically');
  const revealed = frames.filter(frame => frame.workspaceVisible);
  assert.ok(revealed.length > 1,label+': the workspace is actually painted after playback');
  assert.ok(revealed.every(frame => frame.ready && !frame.pending),label+': reveal waits for restored content');
}

async function assertStartupGate(browser,reducedMotion) {
  const context = await browser.newContext({viewport:{width:390,height:844},serviceWorkers:'block',reducedMotion});
  let release;
  let hold = false;
  const held = new Promise(resolve => {release = resolve;});
  try {
    await installSamples(context);
    await installStorageProbe(context);
    await context.route('**/static/offline-content/concepts.zh-CN.json*',async route => {
      if (hold) await held;
      await route.continue();
    });
    const {page,errors} = await enter(context);
    await page.locator('#offlineNavToggle').click();
    await page.locator('.offline-nav-item[data-panel="notes"]').click();
    await page.waitForFunction(async () => (await __offlineTestStore.get('settings','view'))?.panel === 'notes');
    hold = true;
    await page.reload({waitUntil:'domcontentloaded'});
    await page.waitForFunction(() => {
      const snapshot = window.__privacyMotionSnapshot?.();
      return snapshot?.open && snapshot.visible === 21 && snapshot.partial === 0;
    });
    await page.waitForTimeout(150);
    await page.keyboard.press('Escape');
    const waiting = await page.evaluate(() => __privacyMotionSnapshot());
    assert.equal(waiting.open,true,reducedMotion+': completed intro waits while restoring data');
    assert.equal(waiting.eyeVisible,false,reducedMotion+': no eye appears while waiting for data');
    assert.equal(waiting.ready,false,reducedMotion+': delayed resource really holds startup');
    assert.equal(waiting.workspaceVisible,false,reducedMotion+': incomplete content is not exposed');
    release();
    await page.waitForFunction(() => window.__privacyColdSampleComplete);
    const frames = await page.evaluate(() => __privacyColdFrames);
    assertIntro(frames,reducedMotion+' delayed startup',reducedMotion !== 'reduce');
    const revealed = frames.filter(frame => frame.workspaceVisible);
    assert.ok(revealed.every(frame => frame.panels.length === 1 && frame.panels[0] === 'notesPanel'),
      reducedMotion+': the first revealed frame goes directly to the saved notes page');
    assert.deepEqual(errors,[],reducedMotion+': delayed startup raises no errors');
    console.log('PASS '+reducedMotion+' autoplay waits for saved page restoration without exposing an eye or graph flash');
  } finally {release();await context.close();}
}

async function enter(context) {
  const errors = [];
  await context.route(/\/(?:chat|ocr|drawing\/[^?]+|notebook\/analyze|analyze-questions)(?:\?|$)/,
    route => {throw new Error('Privacy motion must not call a model: '+route.request().url());});
  const page = await context.newPage();
  page.on('pageerror',error => errors.push(error.message));
  await page.goto(baseURL+'/offline',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
  await page.waitForFunction(() => !document.getElementById('offlinePrivacyCover')?.open);
  return {page,errors};
}

async function replayFrames(page) {
  return page.evaluate(async () => {
    const frames = [];
    document.getElementById(innerWidth <= 1100 ? 'offlineMobilePrivacyToggle' : 'offlineDesktopPrivacyToggle').click();
    const start = performance.now();
    await new Promise(resolve => {
      function sample() {
        frames.push(__privacyMotionSnapshot());
        if (performance.now()-start < 1050) requestAnimationFrame(sample); else resolve();
      }
      requestAnimationFrame(sample);
    });
    return frames;
  });
}

async function assertNoLateUpdates(page,label) {
  const result = await page.evaluate(async () => {
    // Drain the final synchronous draw and its observer delivery before tracking
    // stopped motion. The page's other interactive modules may keep their rAFs.
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const svg = document.querySelector('.offline-privacy-mark-growth');
    let mutations = 0;
    const observer = new MutationObserver(records => {mutations += records.length;});
    observer.observe(svg,{subtree:true,attributes:true,childList:true});
    const before = svg.innerHTML;
    await new Promise(resolve => setTimeout(resolve,900));
    observer.disconnect();
    return {mutations,unchanged:before === svg.innerHTML,
      open:document.getElementById('offlinePrivacyCover').open};
  });
  assert.equal(result.mutations,0,label+': no animation mutates the hidden/completed logo');
  assert.equal(result.unchanged,true,label+': stopped geometry is stable');
}

async function assertAsyncModalStaysBehind(page) {
  const result = await page.evaluate(async () => {
    const svg = document.querySelector('.offline-privacy-mark-growth');
    const before = svg.innerHTML;
    let mutations = 0;
    const observer = new MutationObserver(records => {mutations += records.length;});
    observer.observe(svg,{subtree:true,attributes:true,childList:true});
    // A real asynchronously opened dialog enters the top layer. The shell
    // raises the existing cover without treating that reorder as a new entry.
    const notice = document.createElement('dialog');
    notice.textContent = 'An asynchronous local notice';
    document.body.append(notice);
    notice.showModal();
    await new Promise(resolve => setTimeout(resolve,1000));
    observer.disconnect();
    const eye = document.getElementById('offlinePrivacyRestore');
    const rect = eye.getBoundingClientRect();
    const top = document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2);
    const result = {mutations,unchanged:svg.innerHTML === before,
      open:document.getElementById('offlinePrivacyCover').open,
      eyeOnTop:top === eye || eye.contains(top),
      privateInert:document.querySelector('.offline-layout').inert};
    notice.close();
    notice.remove();
    return result;
  });
  assert.equal(result.mutations,0,'Raising the privacy cover above an async modal does not replay growth');
  assert.equal(result.unchanged,true,'The completed logo stays stable during top-layer reordering');
  assert.equal(result.open,true,'The privacy cover remains open above an async notice');
  assert.equal(result.eyeOnTop,true,'The eye remains reachable at the top of the top layer');
  assert.equal(result.privateInert,true,'An async modal does not expose private controls');
}

async function assertLayout(page) {
  for (const viewport of [{width:1440,height:900},{width:390,height:844},
    {width:844,height:390},{width:240,height:700}]) {
    await page.setViewportSize(viewport);
    for (const theme of ['dark','navy']) {
      const result = await page.evaluate(theme => {
        document.documentElement.dataset.appearanceTheme = theme;
        document.body.dataset.appearanceTheme = theme;
        const cover = document.getElementById('offlinePrivacyCover');
        const svg = cover.querySelector('.offline-privacy-mark-growth');
        const rect = svg.getBoundingClientRect(), eye = document.getElementById('offlinePrivacyRestore').getBoundingClientRect();
        return {rect:{x:rect.x,y:rect.y,width:rect.width,height:rect.height},
          stroke:getComputedStyle(svg.querySelector('line')).stroke,
          background:getComputedStyle(cover).backgroundColor,
          overflow:document.documentElement.scrollWidth > innerWidth || cover.scrollWidth > cover.clientWidth,
          eyeInside:eye.x >= 0 && eye.y >= 0 && eye.right <= innerWidth && eye.bottom <= innerHeight,
          fallbackVisible:[...cover.querySelectorAll('img')].some(img => getComputedStyle(img).display !== 'none')};
      },theme);
      const label = viewport.width+'x'+viewport.height+' '+theme;
      assert.equal(result.stroke,'rgb(255, 255, 255)',label+': theme ink follows original logo');
      assert.equal(result.background,{dark:'rgb(13, 13, 13)',navy:'rgb(15, 23, 42)'}[theme],label+': theme background remains intact');
      assert.equal(result.overflow,false,label+': no horizontal overflow');
      assert.equal(result.eyeInside,true,label+': the reveal button stays inside the viewport');
      assert.equal(result.fallbackVisible,false,label+': the fallback does not overlap the growing logo');
      assert.ok(Math.abs(result.rect.width-result.rect.height)<1,label+': geometry keeps its aspect ratio');
      assert.ok(Math.abs(result.rect.x+result.rect.width/2-viewport.width/2)<2,label+': logo stays centered horizontally');
      assert.ok(Math.abs(result.rect.y+result.rect.height/2-viewport.height/2)<2,label+': logo stays centered vertically');
      assert.ok(result.rect.x>=0 && result.rect.y>=0 && result.rect.x+result.rect.width<=viewport.width
        && result.rect.y+result.rect.height<=viewport.height,label+': full geometry fits the viewport');
    }
  }
}

(async () => {
  const browser = await chromium.launch(launch);
  try {
    const context = await browser.newContext({viewport:{width:1440,height:900},serviceWorkers:'block',reducedMotion:'no-preference'});
    try {
      await installSamples(context);
      const {page,errors} = await enter(context);
      await page.waitForFunction(() => window.__privacyColdSampleComplete);
      const coldFrames = await page.evaluate(() => __privacyColdFrames);
      assertGrowth(coldFrames,'cold entry',false);
      assertIntro(coldFrames,'cold entry');
      await assertNoLateUpdates(page,'automatically revealed cover');
      const clockStart = new Date('2025-01-01T00:00:00Z');
      await page.clock.install({time:clockStart});
      await page.clock.pauseAt(new Date(clockStart.getTime()+60000));
      await page.reload({waitUntil:'domcontentloaded'});
      await page.clock.runFor(704);
      const growing = await page.evaluate(() => __privacyMotionSnapshot());
      assert.ok(growing.open && growing.partial > 0,'The original 740 ms intro is still drawing at 704 ms');
      await page.clock.runFor(80);
      const complete = await page.evaluate(() => __privacyMotionSnapshot());
      assert.ok(complete.visible === 21 && complete.partial === 0,'All edges are drawn by the frame after completion');
      await page.clock.resume();
      await page.waitForFunction(() => window.__privacyColdSampleComplete);
      const reloadFrames = await page.evaluate(() => __privacyColdFrames);
      assertGrowth(reloadFrames,'reload entry',false);
      assertIntro(reloadFrames,'reload entry');
      console.log('PASS cold entry and reload automatically play without an eye, then enter the workspace');
      assertGrowth(await replayFrames(page),'manual hide action');
      assert.equal(await page.locator('#offlinePrivacyRestore').isVisible(),true,'Manual privacy hiding retains the eye');
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('#offlinePrivacyCover').evaluate(node => node.open),true,'Escape cannot reveal a manually hidden workspace');
      await assertNoLateUpdates(page,'completed manual animation');
      await assertAsyncModalStaysBehind(page);
      console.log('PASS manual privacy still paints growth and stays closed until the eye is used');
      console.log('PASS asynchronous dialogs stay behind the cover without replaying completed growth');

      await page.evaluate(async () => {
        const frames = count => new Promise(resolve => {
          function next() {if (--count <= 0) resolve(); else requestAnimationFrame(next);}
          requestAnimationFrame(next);
        });
        for (let i=0;i<4;i++) {
          document.getElementById('offlinePrivacyRestore').click();
          document.getElementById('offlineDesktopPrivacyToggle').click();
          await frames(3);
        }
        document.getElementById('offlinePrivacyRestore').click();
      });
      await assertNoLateUpdates(page,'rapidly interrupted animation');
      assert.equal(await page.locator('#offlinePrivacyCover').evaluate(node => node.open),false,'Rapid hide/reveal leaves the requested workspace visible');
      await page.evaluate(() => document.getElementById('offlineDesktopPrivacyToggle').click());
      await page.emulateMedia({reducedMotion:'reduce'});
      await page.waitForFunction(() => __privacyMotionSnapshot()?.visible === 21 && __privacyMotionSnapshot()?.partial === 0);
      await assertNoLateUpdates(page,'reduced motion enabled during growth');
      console.log('PASS repeated hide/reveal cancels growth and changing reduced motion settles immediately');

      await assertLayout(page);
      await revealInterface(page);
      assert.equal(await page.locator('#offlinePrivacyCover').evaluate(node => node.open),false,'The mobile eye still reveals after resize and theme changes');
      assert.deepEqual(errors,[],'Animation and resizing raise no page errors');
      console.log('PASS desktop, narrow mobile and landscape geometry across both themes');
    } finally {await context.close();}

    const reduced = await browser.newContext({viewport:{width:390,height:844},serviceWorkers:'block',reducedMotion:'reduce'});
    try {
      await installSamples(reduced);
      const {page,errors} = await enter(reduced);
      await page.waitForFunction(() => window.__privacyColdSampleComplete);
      const coldFrames = await page.evaluate(() => __privacyColdFrames);
      assert.ok(coldFrames.length > 2,'Reduced-motion cold entry is observed');
      assert.ok(coldFrames.every(frame => frame.visible === 21 && frame.partial === 0),'Reduced-motion cold entry always retains the complete logo');
      assertIntro(coldFrames,'reduced-motion entry',false);
      const frames = await replayFrames(page);
      assert.ok(frames.every(frame => frame.visible === 21 && frame.partial === 0),'Reduced-motion hide action never starts growth');
      await assertNoLateUpdates(page,'reduced-motion static cover');
      assert.deepEqual(errors,[],'Reduced-motion page raises no errors');
      console.log('PASS reduced motion preserves a complete static logo on entry and hide');
    } finally {await reduced.close();}
    await assertStartupGate(browser,'no-preference');
    await assertStartupGate(browser,'reduce');
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
