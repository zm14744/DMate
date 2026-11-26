/* Start Flask first. Exercise native scrollbars, including a held thumb drag. */
'use strict';
const assert = require('node:assert/strict');
const { revealInterface } = require('./offline-vault-browser-fixtures.cjs');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const state = (page, selector) => page.locator(selector).evaluate(node => {
  const css = getComputedStyle(node);
  return { color:css.scrollbarColor, width:css.scrollbarWidth, gutter:node.offsetWidth - node.clientWidth,
    horizontal:node.offsetHeight - node.clientHeight, left:node.scrollLeft, top:node.scrollTop };
});

async function hoverThumb(page, selector, axis) {
  const point = await page.locator(selector).evaluate((node, axis) => {
    const box = node.getBoundingClientRect();
    // Our borderless black fixtures have one 8px gutter on each edge.
    return axis === 'x'
      ? {x:box.left + node.clientWidth * (node.scrollLeft + node.clientWidth / 2) / node.scrollWidth, y:box.bottom - 4}
      : {x:box.right - 4, y:box.top + node.clientHeight * (node.scrollTop + node.clientHeight / 2) / node.scrollHeight};
  }, axis);
  await page.mouse.move(point.x, point.y);
  return point;
}

// CSSOM cannot inspect scrollbar-thumb:vertical/:horizontal. Sample the real
// rendered gutters instead, decoding the screenshot with the browser's canvas.
async function paintedAxes(page, selector) {
  const png = (await page.locator(selector).screenshot()).toString('base64');
  return page.evaluate(async png => {
    const image = new Image(); image.src = 'data:image/png;base64,' + png;
    await image.decode();
    const canvas = document.createElement('canvas'); canvas.width = image.width; canvas.height = image.height;
    const context = canvas.getContext('2d'); context.drawImage(image, 0, 0);
    const {data} = context.getImageData(0, 0, canvas.width, canvas.height);
    const count = (left, top, right, bottom) => {
      let result = 0;
      for (let y = top; y < bottom; y++) for (let x = left; x < right; x++) {
        const i = (y * canvas.width + x) * 4;
        if (Math.max(data[i], data[i + 1], data[i + 2]) > 30) result++;
      }
      return result;
    };
    return {y:count(canvas.width - 8, 0, canvas.width, canvas.height - 8),
      x:count(0, canvas.height - 8, canvas.width - 8, canvas.height)};
  }, png);
}
async function assertPaint(page, selector, axis) {
  const paint = await paintedAxes(page, selector);
  assert.equal(paint.x > 0, axis === 'x', selector + ': horizontal paint ' + JSON.stringify(paint));
  assert.equal(paint.y > 0, axis === 'y', selector + ': vertical paint ' + JSON.stringify(paint));
}

(async () => {
  const browser = await chromium.launch({ headless:true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? {executablePath:process.env.CHROMIUM_EXECUTABLE_PATH} : {}),
    // Playwright hides scrollbars by default. Real gutters and thumb dragging
    // are essential here; pseudo-element computed styles alone are insufficient.
    ignoreDefaultArgs:['--hide-scrollbars'],
    args:['--disable-features=OverlayScrollbar,OverlayScrollbars'] });
  try {
    const page = await browser.newPage({viewport:{width:1440,height:950}});
    await page.goto(baseURL, {waitUntil:'networkidle'});
    await page.waitForFunction(() => window.__dmateScrollbarsInstalled === true);
    await page.evaluate(() => {
      const fixture = document.createElement('section');
      fixture.id = 'scrollbar-fixture';
      fixture.style.cssText = 'position:fixed;z-index:100000;left:20px;top:100px;display:flex;gap:20px;align-items:flex-start';
      fixture.innerHTML = `<style>
        #scrollbar-fixture .scroll-probe{display:block!important;position:relative!important;box-sizing:border-box!important;
          width:250px!important;height:160px!important;min-height:0!important;max-height:none!important;
          overflow:scroll!important;margin:0!important;padding:0!important;border:0!important;flex:none!important;
          background:#000!important;border-radius:0!important;box-shadow:none!important}
        #scrollbar-fixture .scroll-fill{position:relative;width:800px;height:800px;flex:none;background:#000!important}
        #scrollbar-fixture #scroll-child{position:absolute!important;left:12px;top:12px;width:150px!important;height:100px!important}
      </style>
      <div id="scroll-parent" class="scroll-probe"><div class="scroll-fill">
        <div id="scroll-child" class="scroll-probe"><div class="scroll-fill"></div></div>
      </div></div>
      <div id="scroll-sibling" class="scroll-probe"><div class="scroll-fill"></div></div>
      <div id="scroll-hidden" class="scroll-probe dge-property-body"><div class="scroll-fill"></div></div>`;
      document.body.append(fixture);
    });

    const before = await state(page, '#scroll-parent');
    assert.equal(before.gutter, 8, 'The existing custom 8px gutter is present at rest');
    assert.equal(before.color, 'auto', 'Chromium must keep using custom WebKit scrollbars');
    const rect = await page.locator('#scroll-parent').boundingBox();
    await assertPaint(page, '#scroll-parent', null);
    await page.mouse.move(rect.x + rect.width - 4, rect.y + 110);
    await assertPaint(page, '#scroll-parent', null);
    await page.mouse.click(rect.x + rect.width - 4, rect.y + 110);
    await page.waitForFunction(() => document.getElementById('scroll-parent').scrollTop > 0);
    // A platform can page toward the pointer or jump straight to it. Move to
    // the empty end of the track after native paging has landed.
    const emptyTrackY = await page.locator('#scroll-parent').evaluate(node =>
      node.scrollTop * 2 < node.scrollHeight - node.clientHeight ? node.clientHeight - 4 : 4);
    await page.mouse.move(rect.x + rect.width - 4, rect.y + emptyTrackY);
    await assertPaint(page, '#scroll-parent', null);
    await page.locator('#scroll-parent').evaluate(node => { node.scrollTop = 0; });
    await page.mouse.move(rect.x + 180, rect.y + rect.height - 4);
    await assertPaint(page, '#scroll-parent', null);
    await hoverThumb(page, '#scroll-parent', 'x');
    await assertPaint(page, '#scroll-parent', 'x');
    await hoverThumb(page, '#scroll-parent', 'y');
    await assertPaint(page, '#scroll-parent', 'y');
    assert.equal((await state(page, '#scroll-parent')).gutter, before.gutter, 'Revealing paint never changes the gutter');
    await assertPaint(page, '#scroll-child', null);
    await assertPaint(page, '#scroll-sibling', null);
    await hoverThumb(page, '#scroll-child', 'y');
    await assertPaint(page, '#scroll-child', 'y');
    await assertPaint(page, '#scroll-parent', null);
    await page.mouse.move(rect.x + rect.width - 20, rect.y + 110);
    await assertPaint(page, '#scroll-child', null);

    await page.mouse.wheel(0, 60);
    await page.waitForFunction(() => document.getElementById('scroll-parent').scrollTop > 0);
    await assertPaint(page, '#scroll-parent', null);
    await page.locator('#scroll-parent').evaluate(node => { node.scrollLeft = 70; });
    await assertPaint(page, '#scroll-parent', null);
    await hoverThumb(page, '#scroll-parent', 'x');
    await assertPaint(page, '#scroll-parent', 'x');
    await hoverThumb(page, '#scroll-parent', 'y');
    await assertPaint(page, '#scroll-parent', 'y');
    await page.mouse.move(1400, 20);
    await assertPaint(page, '#scroll-parent', null);
    console.log('PASS blank tracks, axis-specific thumb hover, nested scrollbars and quiet wheel/programmatic scrolling');

    await page.evaluate(() => {
      const dynamic = document.createElement('div');
      dynamic.id = 'scroll-dynamic'; dynamic.className = 'scroll-probe';
      dynamic.innerHTML = '<div style="width:800px;height:80px;background:#000"></div>';
      document.getElementById('scrollbar-fixture').append(dynamic);
      dynamic.scrollLeft = 70;
    });
    const horizontal = await state(page, '#scroll-dynamic');
    assert.equal(horizontal.left, 70);
    await assertPaint(page, '#scroll-dynamic', null);
    await hoverThumb(page, '#scroll-dynamic', 'x');
    await assertPaint(page, '#scroll-dynamic', 'x');
    await page.mouse.move(1400, 20);
    await assertPaint(page, '#scroll-dynamic', null);
    assert.equal((await state(page, '#scroll-dynamic')).horizontal, horizontal.horizontal);
    await page.locator('#scroll-hidden').evaluate(node => { node.scrollTop = 40; });
    const hidden = await state(page, '#scroll-hidden');
    assert.equal(hidden.width, 'none', 'Explicitly hidden component scrollbars remain hidden');
    assert.equal(hidden.gutter, 0);
    assert.ok(hidden.top > 0, 'Hidden component still scrolls normally');
    console.log('PASS dynamically added horizontal scrollbars and explicit scrollbar-width:none');

    await page.locator('#scroll-sibling').evaluate(node => { node.scrollTop = 30; });
    const thumb = await hoverThumb(page, '#scroll-sibling', 'y');
    await assertPaint(page, '#scroll-sibling', 'y');
    await page.mouse.down();
    await page.mouse.move(thumb.x - 30, thumb.y + 55, {steps:5});
    await page.waitForFunction(() => document.getElementById('scroll-sibling').scrollTop > 30);
    const dragging = await state(page, '#scroll-sibling');
    assert.ok(dragging.top > 30, 'Dragging the native thumb changes the real scroll position');
    assert.equal(dragging.gutter, before.gutter);
    await assertPaint(page, '#scroll-sibling', 'y');
    await page.mouse.up();
    await assertPaint(page, '#scroll-sibling', null);
    console.log('PASS the native thumb stays painted during a drag outside the gutter and hides on release');

    await page.evaluate(() => {
      for (const node of [document.documentElement, document.body]) {
        node.style.setProperty('overflow', 'auto', 'important');
        node.style.setProperty('height', 'auto', 'important');
      }
      const spacer = document.createElement('div'); spacer.style.height = '2400px';
      document.body.append(spacer);
    });
    const rootWidth = await page.evaluate(() => document.documentElement.clientWidth);
    await page.evaluate(() => window.scrollTo(0, 300));
    assert.ok(await page.evaluate(() => window.scrollY > 0));
    assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).scrollbarColor), 'auto');
    assert.equal(await page.evaluate(() => document.documentElement.clientWidth), rootWidth);
    await assertPaint(page, '#scroll-parent', null);
    console.log('PASS root-document scrolling without geometry or descendant-state changes');

    const offline = await browser.newPage({viewport:{width:1440,height:950}, hasTouch:true});
    await offline.goto(baseURL + '/offline', {waitUntil:'networkidle'});
    await offline.waitForFunction(() => window.__dmateScrollbarsInstalled === true);
    await revealInterface(offline);
    await offline.evaluate(() => {
      const node = document.createElement('div'); node.id = 'offline-scroll-probe';
      node.style.cssText = 'position:fixed;z-index:100000;left:20px;top:100px;width:250px;height:160px;overflow:scroll;border:0;padding:0;background:#000;border-radius:0';
      node.innerHTML = '<div style="width:800px;height:800px;background:#000"></div>';
      document.body.append(node);
    });
    const idleOffline = await state(offline, '#offline-scroll-probe');
    await assertPaint(offline, '#offline-scroll-probe', null);
    await offline.locator('#offline-scroll-probe').evaluate(node => { node.scrollTop = 40; });
    await assertPaint(offline, '#offline-scroll-probe', null);
    await hoverThumb(offline, '#offline-scroll-probe', 'y');
    const activeOffline = await state(offline, '#offline-scroll-probe');
    await assertPaint(offline, '#offline-scroll-probe', 'y');
    assert.equal(activeOffline.gutter, idleOffline.gutter);
    assert.equal(activeOffline.color, 'auto');
    await offline.mouse.move(1400, 20);
    await assertPaint(offline, '#offline-scroll-probe', null);
    console.log('PASS offline entry paints only the hovered thumb');

    await offline.setViewportSize({width:390, height:844});
    const touch = await offline.context().newCDPSession(offline);
    await touch.send('Input.dispatchTouchEvent', {type:'touchStart', touchPoints:[{x:110,y:230}]});
    for (const y of [215, 195, 175, 155]) {
      await touch.send('Input.dispatchTouchEvent', {type:'touchMove', touchPoints:[{x:110,y}]});
    }
    await touch.send('Input.dispatchTouchEvent', {type:'touchEnd', touchPoints:[]});
    await offline.waitForFunction(() => document.getElementById('offline-scroll-probe').scrollTop > 40);
    await assertPaint(offline, '#offline-scroll-probe', 'y');
    await offline.waitForFunction(() => !document.getElementById('offline-scroll-probe').hasAttribute('data-dmate-scroll-active'));
    await assertPaint(offline, '#offline-scroll-probe', null);
    await touch.detach();
    console.log('PASS a touch swipe temporarily reveals its scrolling axis on a narrow screen');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
