/* Load only files produced for native packaging, with a fresh browser and no network. */
'use strict';
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const {mkdtemp, readFile, rm} = require('node:fs/promises');
const {tmpdir} = require('node:os');
const {extname, join, resolve} = require('node:path');
const {chromium} = require('playwright');
const {installStorageProbe, revealInterface} = require('./offline-vault-browser-fixtures.cjs');

const origin = 'https://dmate.zeabur.app';
const desktopAssets = 'http://dmate-offline.localhost';
const types = {'.html':'text/html', '.js':'application/javascript', '.json':'application/json',
  '.css':'text/css', '.svg':'image/svg+xml', '.png':'image/png', '.ico':'image/x-icon'};

async function main() {
  const output = await mkdtemp(join(tmpdir(), 'dmate-offline-bundle-'));
  let browser;
  try {
    execFileSync(process.env.PYTHON || 'python3', [resolve(__dirname, 'stage_native_offline.py'),
      '--destination', output]);
    const assets = new Set((await readFile(join(output, 'paths.txt'), 'utf8')).trim().split(/\r?\n/));
    browser = await chromium.launch({headless:true,
      ...(process.env.CHROMIUM_EXECUTABLE_PATH ? {executablePath:process.env.CHROMIUM_EXECUTABLE_PATH} : {})});
    const context = await browser.newContext({offline:true, serviceWorkers:'block',
      viewport:{width:1440,height:900}, reducedMotion:'reduce'});
    await installStorageProbe(context);
    const missing = [];
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin === origin && url.pathname === '/') {
        return route.fulfill({contentType:'text/html',body:'<!doctype html><title>Online fixture</title>'});
      }
      if (![origin,desktopAssets].includes(url.origin) || route.request().method() !== 'GET'
          || !assets.has(url.pathname)) {
        missing.push(url.pathname);
        return route.abort();
      }
      const file = ['/offline','/static/offline.html'].includes(url.pathname)
        ? 'offline.html' : url.pathname.slice(1);
      if (file === 'offline.html' && url.searchParams.has('desktop')) {
        const html = await readFile(join(output,file), 'utf8');
        return route.fulfill({body:html.replace('<head>',`<head><base href="${desktopAssets}/">`),
          contentType:'text/html'});
      }
      await route.fulfill({path:join(output,file),contentType:types[extname(file)],
        headers:{'Access-Control-Allow-Origin':origin}});
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(origin+'/offline?native_offline=1');
    await revealInterface(page);
    assert.equal(await page.evaluate(() => navigator.onLine), false);
    assert.deepEqual(await page.evaluate(() => caches.keys()), []);
    assert.ok(await page.locator('#returnOnline').isDisabled());
    for (const panel of ['concepts','questions','notes','mistakes','drawing','graph']) {
      await page.locator(`.offline-nav-item[data-panel="${panel}"]`).click();
      await page.locator(`#${panel}Panel`).waitFor({state:'visible'});
    }
    assert.ok(await page.locator('#conceptCount').textContent());
    assert.ok(await page.locator('#questionCount').textContent());
    console.log('PASS installed offline assets open all learning tools in a fresh disconnected browser');

    // WebView2 resolves desktop resources through a local protocol host. The
    // actual workspace URL still owns the previously saved IndexedDB record.
    await page.evaluate(() => __offlineTestStore.put('notes',{id:'local-note',title:'本机笔记',content:'原有内容'}));
    await page.goto(origin+'/offline?desktop=1');
    await revealInterface(page);
    const note = await page.evaluate(() => __offlineTestStore.get('notes','local-note'));
    assert.equal(note.content, '原有内容');
    await context.setOffline(false);
    await page.locator('#returnOnline').click();
    await page.waitForURL(origin+'/');
    assert.equal(await page.title(), 'Online fixture');
    console.log('PASS desktop asset base retains the workspace origin, prior data, and online return');
    assert.deepEqual(errors, []);
    assert.deepEqual(missing, [], 'Packaged workspace must not request server resources');
  } finally {
    await browser?.close();
    await rm(output,{recursive:true,force:true});
  }
}

main().catch(error => {console.error(error); process.exitCode = 1;});
