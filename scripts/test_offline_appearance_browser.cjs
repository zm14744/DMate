/* Compare the real online/offline wallpaper layers, then exercise the copied
 * appearance controls and their persisted preview/confirm behavior.
 * Start Flask first; each run uses an isolated browser context.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const profile = { mode:'dark', accent:'purple', fontSize:'large', backgroundFit:'contain',
  mask:17, blur:3, panelOpacity:80, bubbleOpacity:70 };

async function ready(page) {
  await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
}
async function openAppearance(page) {
  if (await page.locator('#offlineAppearanceBtn').count()) {
    const mobile = page.viewportSize().width <= 1100;
    if (!mobile && await page.locator('#offlineDesktopSidebarOpen').getAttribute('aria-expanded') !== 'true') {
      await page.locator('#offlineDesktopSidebarOpen').click();
    }
    await page.locator(mobile ? '#offlineAppearanceToggle' : '#offlineAppearanceBtn').click();
  } else {
    if (await page.locator('html').getAttribute('data-desktop-sidebar') === 'collapsed') {
      await page.locator('#desktopSidebarOpen').click();
    }
    await page.locator('#appearanceBtn').click();
  }
  await page.locator('#appearanceModal').waitFor({ state:'visible' });
}
async function settledWallpaper(page) {
  await page.waitForFunction(() => {
    const style = getComputedStyle(document.getElementById('appearanceBackgroundLayer'));
    return style.opacity === '1' && style.filter === 'blur(3px)';
  });
}
async function appearance(page) {
  return page.evaluate(() => {
    const result = {};
    for (const key of ['--panel-alpha','--workspace-alpha','--shell-alpha','--composer-alpha',
      '--bubble-alpha','--font-scale','--background-mask-alpha','--background-blur','--background-size','--accent']) {
      result[key] = document.documentElement.style.getPropertyValue(key);
    }
    // The offline workspace retains its four-panel layout. Only shared wallpaper
    // layers and appearance settings must match the online application.
    for (const [name,selector] of [['background','#appearanceBackgroundLayer'],['mask','.appearance-mask-layer']]) {
      const node = document.querySelector(selector);
      if (!node) throw new Error('Missing shared visual element: ' + selector);
      const style = getComputedStyle(node);
      result[name] = { background:style.backgroundColor, opacity:style.opacity,
        filter:style.filter, backgroundSize:style.backgroundSize };
    }
    result.hasBackground = document.body.classList.contains('has-custom-background');
    return result;
  });
}
async function appearanceControls(page) {
  return page.locator('#appearanceModal').evaluate(dialog => {
    const selectors = ['.appearance-card', '.modal-head', '.appearance-section-title',
      '[data-appearance-mode="dark"]', '[data-appearance-accent="purple"]', '[data-appearance-font="large"]',
      '[data-appearance-fit="contain"]', '#appearanceMaskRange', '#appearanceBlurRange',
      '#appearancePanelRange', '#appearanceBubbleRange', '#appearanceDone', '#appearanceClose'];
    return Object.fromEntries(selectors.map(selector => {
      const node = dialog.querySelector(selector), style = getComputedStyle(node);
      return [selector, Object.fromEntries(['backgroundColor', 'color', 'fontFamily', 'fontSize', 'fontWeight',
        'borderTopColor', 'borderTopWidth', 'borderRadius', 'boxShadow'].map(key => [key, style[key]]))];
    }));
  });
}

(async () => {
  const browser = await chromium.launch({ headless:true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath:process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  const context = await browser.newContext({ viewport:{ width:1440, height:900 } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(baseURL + '/', { waitUntil:'networkidle' });
    await page.evaluate(async settings => {
      appearanceSettings = { ...APPEARANCE_DEFAULTS, ...settings };
      applyAppearanceSettings({ save:true });
      const canvas = document.createElement('canvas'); canvas.width = 80; canvas.height = 60;
      const drawing = canvas.getContext('2d'); drawing.fillStyle = '#326a8f'; drawing.fillRect(0,0,80,60);
      const blob = await new Promise(resolve => canvas.toBlob(resolve,'image/png'));
      await writeAppearanceBackgroundBlob(blob);
      setAppearanceBackgroundVisual(blob);
      await window.DMateOfflineBridge.snapshot();
    }, profile);
    await settledWallpaper(page);
    const online = await appearance(page);
    await openAppearance(page);
    const onlineControls = await appearanceControls(page);
    await page.locator('#appearanceClose').click();
    await page.goto(baseURL + '/offline', { waitUntil:'networkidle' });
    await ready(page);
    await settledWallpaper(page);
    assert.deepEqual(await appearance(page), online,
      'Offline wallpaper, theme, font, opacity, and shared background layers must match online');
    console.log('PASS online/offline custom wallpaper, ten appearance variables, and both background layers match');

    await openAppearance(page);
    assert.deepEqual(await appearanceControls(page), onlineControls, 'The full appearance dialog retains online control styles');
    const png = await page.evaluate(() => {
      const canvas = document.createElement('canvas'); canvas.width = canvas.height = 8;
      const drawing = canvas.getContext('2d'); drawing.fillStyle = '#c78336'; drawing.fillRect(0,0,8,8);
      return canvas.toDataURL('image/png').split(',')[1];
    });
    await page.locator('#appearanceBackgroundInput').setInputFiles({
      name:'background.png', mimeType:'image/png', buffer:Buffer.from(png,'base64')
    });
    await page.waitForFunction(() => document.getElementById('appearanceBackgroundPreview').dataset.hasBackground === 'true'
      && !document.getElementById('appearanceDone').disabled);
    await page.locator('#appearanceBackgroundPreview').click();
    await page.locator('#appearanceBackgroundViewer').waitFor({ state:'visible' });
    await page.locator('#appearanceBackgroundViewerClose').click();
    await page.locator('#appearanceDone').click();
    await page.locator('#appearanceModal').waitFor({ state:'hidden' });
    await page.reload({ waitUntil:'networkidle' }); await ready(page); await settledWallpaper(page);
    assert.deepEqual(await page.evaluate(() => window.DMateOfflineAppearance.getSettings()), profile);
    assert.equal(await page.evaluate(() => window.DMateOfflineAppearance.getBackground()?.type), 'image/webp');
    assert.equal(await page.evaluate(() => document.body.classList.contains('has-custom-background')), true);
    console.log('PASS uploaded PNG is prepared, previewed, confirmed, and retained with settings after reload');

    await openAppearance(page);
    await page.locator('#appearanceBackgroundRemove').click();
    assert.equal(await page.evaluate(() => document.body.classList.contains('has-custom-background')), false);
    await page.locator('#appearanceClose').click();
    assert.equal(await page.evaluate(() => document.body.classList.contains('has-custom-background')), true);
    await settledWallpaper(page);
    console.log('PASS closing a removal preview restores the confirmed wallpaper');

    // Fail only this isolated context's appearance write, then retry through
    // the real controls. The failed draft must remain editable and uncommitted.
    await openAppearance(page);
    await page.locator('[data-appearance-accent="teal"]').click();
    await page.evaluate(() => {
      window.restoreAppearanceTransaction = IDBDatabase.prototype.transaction;
      IDBDatabase.prototype.transaction = function(stores, mode, ...options) {
        if (this.name === 'dmate-offline-workspace' && mode === 'readwrite' && stores === 'settings') {
          throw new DOMException('Appearance write blocked for regression test','QuotaExceededError');
        }
        return window.restoreAppearanceTransaction.call(this,stores,mode,...options);
      };
    });
    await page.locator('#appearanceDone').click();
    await page.locator('.dmate-delete-confirm[open]').waitFor({ state:'visible' });
    assert.equal(await page.locator('#appearanceDone').isDisabled(), false, 'Saving failure must permit retry');
    assert.equal(await page.evaluate(() => window.DMateOfflineAppearance.getSettings().accent), 'purple');
    await page.keyboard.press('Escape');
    await page.locator('.dmate-delete-confirm[open]').waitFor({ state:'detached' });
    assert.equal(await page.locator('#appearanceModal').isVisible(), true, 'Notice dismissal must preserve the draft');
    await page.evaluate(() => {
      IDBDatabase.prototype.transaction = window.restoreAppearanceTransaction;
      delete window.restoreAppearanceTransaction;
    });
    await page.locator('#appearanceDone').click();
    await page.locator('#appearanceModal').waitFor({ state:'hidden' });
    await page.reload({ waitUntil:'networkidle' }); await ready(page);
    assert.equal(await page.evaluate(() => window.DMateOfflineAppearance.getSettings().accent), 'teal');
    assert.equal(await page.evaluate(() => document.body.classList.contains('has-custom-background')), true);
    assert.deepEqual(errors, [], 'Appearance interactions must not produce page errors');
    console.log('PASS failed storage preserves the draft and wallpaper; retry persists successfully');
  } finally {
    await context.close();
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
