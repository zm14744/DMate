/* Start Flask first. Exercise native scrollbars, including a held thumb drag. */
'use strict';
const assert = require('node:assert/strict');
const { revealInterface } = require('./offline-vault-browser-fixtures.cjs');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const attribute = 'data-dmate-scroll-active';
const settle = (page, selector, active) => page.waitForFunction(({selector, active, attribute}) =>
  document.querySelector(selector)?.hasAttribute(attribute) === active, {selector, active, attribute});
const state = (page, selector) => page.locator(selector).evaluate((node, attribute) => {
  const css = getComputedStyle(node), thumb = getComputedStyle(node, '::-webkit-scrollbar-thumb');
  return { active:node.hasAttribute(attribute), axis:node.getAttribute(attribute), color:css.scrollbarColor, width:css.scrollbarWidth,
    thumb:thumb.backgroundColor, gutter:node.offsetWidth - node.clientWidth,
    horizontal:node.offsetHeight - node.clientHeight, left:node.scrollLeft, top:node.scrollTop };
}, attribute);
const transparent = value => value === 'transparent' || value === 'rgba(0, 0, 0, 0)';

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
    assert.ok(transparent(before.thumb), 'An idle thumb is transparent');
    const rect = await page.locator('#scroll-parent').boundingBox();
    await page.mouse.move(rect.x + rect.width - 4, rect.y + 100);
    await settle(page, '#scroll-parent', true);
    assert.equal((await state(page, '#scroll-parent')).axis, 'y', 'Right gutter hover reveals only the vertical scrollbar');
    await assertPaint(page, '#scroll-parent', 'y');
    await page.waitForTimeout(1000);
    assert.equal((await state(page, '#scroll-parent')).axis, 'y', 'Stationary gutter hover stays visible');
    await page.mouse.move(rect.x + 150, rect.y + rect.height - 4);
    await page.waitForFunction(() => document.getElementById('scroll-parent').getAttribute('data-dmate-scroll-active') === 'x');
    await assertPaint(page, '#scroll-parent', 'x');
    await page.mouse.move(1400, 20);
    await settle(page, '#scroll-parent', false);
    await assertPaint(page, '#scroll-parent', null);

    await page.locator('#scroll-parent').evaluate(node => { node.scrollTop = 45; });
    await settle(page, '#scroll-parent', true);
    const active = await state(page, '#scroll-parent');
    assert.equal(active.axis, 'y', 'Vertical scrolling selects only the vertical thumb');
    await assertPaint(page, '#scroll-parent', 'y');
    assert.equal(active.color, 'auto', 'Visible thumbs must not enable native arrow controls');
    assert.equal(active.gutter, before.gutter, 'Revealing paint never changes the gutter');
    assert.equal((await state(page, '#scroll-child')).active, false);
    assert.ok(transparent((await state(page, '#scroll-child')).thumb), 'Parent state does not inherit into a child');
    assert.ok(transparent((await state(page, '#scroll-sibling')).thumb), 'Unscrolled siblings stay hidden');
    await page.waitForTimeout(400);
    assert.equal((await state(page, '#scroll-parent')).active, true, 'Thumb persists briefly after scrolling');
    await page.locator('#scroll-child').evaluate(node => { node.scrollTop = 35; });
    await settle(page, '#scroll-child', true);
    await settle(page, '#scroll-parent', false);
    assert.equal((await state(page, '#scroll-child')).active, true, 'Nested scrollers use independent idle timers');
    await settle(page, '#scroll-child', false);
    assert.equal((await state(page, '#scroll-parent')).gutter, before.gutter);
    console.log('PASS gutter hover, axis-only paint, unchanged gutter and independent nested/sibling timers');

    // Both offsets remain nonzero while changing direction. The old vertical
    // position must never make the horizontal scroll reveal both axes.
    await page.locator('#scroll-parent').evaluate(node => { node.scrollLeft = 70; });
    await settle(page, '#scroll-parent', true);
    assert.equal((await state(page, '#scroll-parent')).axis, 'x');
    await assertPaint(page, '#scroll-parent', 'x');
    await page.locator('#scroll-parent').evaluate(node => { node.scrollTop = 90; });
    await page.waitForFunction(() => document.getElementById('scroll-parent').getAttribute('data-dmate-scroll-active') === 'y');
    await assertPaint(page, '#scroll-parent', 'y');
    await settle(page, '#scroll-parent', false);
    console.log('PASS changing scroll direction immediately hides the other axis');

    await page.evaluate(() => {
      const dynamic = document.createElement('div');
      dynamic.id = 'scroll-dynamic'; dynamic.className = 'scroll-probe';
      dynamic.innerHTML = '<div style="width:800px;height:80px;background:#000"></div>';
      document.getElementById('scrollbar-fixture').append(dynamic);
      dynamic.scrollLeft = 70;
    });
    await settle(page, '#scroll-dynamic', true);
    const horizontal = await state(page, '#scroll-dynamic');
    assert.equal(horizontal.left, 70);
    assert.equal(horizontal.axis, 'x', 'Dynamically added horizontal scrollers are observed');
    await assertPaint(page, '#scroll-dynamic', 'x');
    await settle(page, '#scroll-dynamic', false);
    assert.equal((await state(page, '#scroll-dynamic')).horizontal, horizontal.horizontal);
    await page.locator('#scroll-hidden').evaluate(node => { node.scrollTop = 40; });
    await settle(page, '#scroll-hidden', true);
    const hidden = await state(page, '#scroll-hidden');
    assert.equal(hidden.width, 'none', 'Explicitly hidden component scrollbars remain hidden');
    assert.equal(hidden.gutter, 0);
    assert.ok(hidden.top > 0, 'Hidden component still scrolls normally');
    console.log('PASS dynamic horizontal containers and preserved explicit scrollbar-width:none');

    await page.locator('#scroll-sibling').evaluate(node => { node.scrollTop = 30; });
    await settle(page, '#scroll-sibling', true);
    const thumb = await page.locator('#scroll-sibling').evaluate(node => {
      const r = node.getBoundingClientRect(), h = node.clientHeight;
      const thumbHeight = Math.max(20, h * h / node.scrollHeight);
      return {x:r.right - 4, y:r.top + (h - thumbHeight) * node.scrollTop / (node.scrollHeight - h) + thumbHeight / 2};
    });
    await page.mouse.move(thumb.x, thumb.y);
    await page.mouse.down();
    await page.mouse.move(thumb.x, thumb.y + 55, {steps:5});
    await page.waitForTimeout(1150);
    const dragging = await state(page, '#scroll-sibling');
    assert.ok(dragging.top > 30, 'Dragging the native thumb changes the real scroll position');
    assert.equal(dragging.active, true, 'A held native thumb stays visible beyond the idle timeout');
    assert.equal(dragging.gutter, before.gutter);
    await page.mouse.up();
    await page.mouse.move(1400, 20);
    await settle(page, '#scroll-sibling', false);
    console.log('PASS native scrollbar dragging and delayed hiding after release');

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
    await settle(page, 'html', true);
    assert.ok(await page.evaluate(() => window.scrollY > 0));
    assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).scrollbarColor), 'auto');
    assert.equal(await page.evaluate(() => document.documentElement.clientWidth), rootWidth);
    assert.equal((await state(page, '#scroll-parent')).active, false, 'Root scrolling does not reveal idle descendants');
    await settle(page, 'html', false);
    console.log('PASS root-document scrolling without geometry or descendant-state changes');

    const offline = await browser.newPage({viewport:{width:1440,height:950}});
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
    assert.ok(transparent(idleOffline.thumb));
    await offline.locator('#offline-scroll-probe').evaluate(node => { node.scrollTop = 40; });
    await settle(offline, '#offline-scroll-probe', true);
    const activeOffline = await state(offline, '#offline-scroll-probe');
    assert.equal(activeOffline.axis, 'y');
    await assertPaint(offline, '#offline-scroll-probe', 'y');
    assert.equal(activeOffline.gutter, idleOffline.gutter);
    assert.equal(activeOffline.color, 'auto');
    await settle(offline, '#offline-scroll-probe', false);
    assert.ok(transparent((await state(offline, '#offline-scroll-probe')).thumb));
    await assertPaint(offline, '#offline-scroll-probe', null);
    console.log('PASS actual offline entry idle/scroll/idle integration');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
