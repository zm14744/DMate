/* Compare the visible notebook, mistake book, graph and drawing frames at their real entry points. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const { revealInterface } = require('./offline-vault-browser-fixtures.cjs');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const desktop = { width:1440, height:900 }, narrow = { width:1120, height:600 };
const phone = { width:390, height:844 };
const tools = [
  { name:'notebook', button:'#conceptNotebookBtn', online:'#conceptNotebookDialog', offline:'#notesPanel', close:'#conceptNotebookDialog > header .dcn-close' },
  { name:'mistakes', button:'#wrongBookBtn', online:'#wrongBookModal > .modal-card', offline:'#mistakesPanel', close:'#wrongBookClose' },
  { name:'graph', button:'#knowledgeGraphBtn', online:'#knowledgeGraphModal > .graph-modal-card', offline:'#graphPanel .graph-modal-card', close:'#knowledgeGraphClose' },
  { name:'drawing', button:'#graphDrawingBtn', online:'#graphEditorDialog', offline:'#drawingPanel', close:'#graphEditorClose' }
];

const near = (actual, expected, label) => assert.ok(Math.abs(actual-expected) <= 1, label + ': ' + actual + ' vs ' + expected);
async function settle(page) {
  await page.evaluate(async () => {
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    await Promise.all(document.getAnimations().filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity)
      .map(animation => animation.finished.catch(() => {})));
    await new Promise(resolve => requestAnimationFrame(resolve));
  });
}

async function openTool(page, tool, offline) {
  const small = page.viewportSize().width <= 1100;
  const toggle = page.locator(offline ? (small ? '#offlineNavToggle' : '#offlineDesktopSidebarOpen')
    : (small ? '#mobileToolsBtn' : '#desktopToolsBtn'));
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
  await page.locator(tool.button).click();
  const surface = page.locator(offline ? tool.offline : tool.online);
  await surface.waitFor();
  if (tool.name === 'drawing') await surface.locator('.dge-overlay[data-geometry-ready="true"]').waitFor();
  if (tool.name === 'graph') await surface.locator('.kg-desktop-viewport,.kg-mobile-viewport').waitFor();
  return surface;
}

async function frame(surface) {
  return surface.evaluate(node => {
    const box = node.getBoundingClientRect(), css = getComputedStyle(node);
    return { x:box.x,y:box.y,width:box.width,height:box.height,radius:css.borderRadius,paint:css.backgroundColor };
  });
}

function compare(actual, expected, label) {
  for (const key of ['x','y','width','height']) near(actual[key],expected[key],label+'/'+key);
  assert.equal(actual.radius,expected.radius,label+'/corner radius');
}

async function checkGraph(page) {
  const mobile = page.viewportSize().width <= 760;
  const viewport = page.locator('#knowledgeGraphCanvas ' + (mobile ? '.kg-mobile-viewport' : '.kg-desktop-viewport'));
  await viewport.waitFor();
  const borders = await viewport.evaluate(node => {
    const toolbar = getComputedStyle(document.querySelector('#knowledgeGraphModal .graph-toolbar'));
    const style = getComputedStyle(node);
    return { width:toolbar.borderBottomWidth, line:toolbar.borderBottomStyle, bar:style.scrollbarWidth, gutter:style.scrollbarGutter };
  });
  assert.equal(borders.width,mobile ? '0px' : '1px','Graph toolbar separator at '+page.viewportSize().width);
  if (!mobile) assert.equal(borders.line,'solid');
  assert.equal(borders.bar,'none','The graph viewport hides its scrollbars');
  assert.equal(borders.gutter,'auto','Hidden scrollbars reserve no gutter');
}

async function compareTools(page, offline, active, sizes) {
  const reference = [];
  for (const tool of tools) {
    await page.setViewportSize(sizes[0]);
    const surface = await openTool(page,tool,offline);
    for (const [index,size] of sizes.entries()) {
      await page.setViewportSize(size);
      await settle(page);
      const box = await frame(surface), label = [offline ? 'offline' : active ? 'chat' : 'welcome',tool.name,size.width].join('/');
      assert.notEqual(box.paint,'rgba(0, 0, 0, 0)',label+' measures a painted surface');
      assert.ok(box.width > size.width * .6 && box.height > size.height * .7,label+' uses a large frame');
      assert.ok(box.x >= 0 && box.y >= 0 && box.x+box.width <= size.width+1 && box.y+box.height <= size.height+1,label+' fits the screen');
      assert.ok(parseFloat(box.radius) > 0,label+' has rounded corners');
      if (reference[index]) compare(box,reference[index],label);
      else reference[index] = box;
      if (!offline) {
        const composer = await page.locator('.center > .input-wrap > .input').boundingBox();
        assert.ok(composer,label+' has a visible composer');
        const bottom = box.y + box.height;
        if (active) near(bottom,composer.y+composer.height,label+' aligns with the composer capsule');
        else assert.ok(bottom > composer.y+composer.height+24,label+' extends below the centered welcome composer');
      }
      if (tool.name === 'graph') await checkGraph(page);
    }
    if (!offline) await page.locator(tool.close).click();
  }
}

async function checkEdition(browser, offline) {
  const context = await browser.newContext({viewport:desktop,serviceWorkers:'block'});
  const page = await context.newPage(), unexpected = [];
  await page.route('**/auth/me', route => route.fulfill({json:{configured:true,authenticated:false}}));
  await page.route(/\/(?:chat|analyze-questions|classify|conversation\/title|notebook\/analyze)(?:\?|$)/, route => {
    unexpected.push(new URL(route.request().url()).pathname); return route.abort();
  });
  try {
    await page.goto(baseURL+(offline ? '/offline' : '/'),{waitUntil:'networkidle'});
    if (offline) {
      await revealInterface(page);
      await compareTools(page,true,false,[desktop,narrow]);
    } else {
      await page.waitForFunction(() => !accountVerificationOperation);
      await page.locator('.center.chat-empty').waitFor();
      await compareTools(page,false,false,[desktop]);
      await page.evaluate(() => {
        newChat();
        getCurrent().messages.push({messageId:'geometry-message',role:'user',text:'窗口尺寸测试',manualIsQuestion:false,createdAt:Date.now()});
        renderAll();
      });
      await page.locator('.center:not(.chat-empty) #chat .msg.user').waitFor();
      await page.waitForFunction(() => !document.querySelector('.center').dataset.composerMotion);
      await page.locator('#text').fill('多行草稿\n用于测试输入框扩展\n窗口底边仍对齐');
      await compareTools(page,false,true,[desktop,narrow]);
    }
    await page.setViewportSize(phone);
    if (offline) await settle(page);
    await openTool(page,tools.find(tool => tool.name === 'graph'),offline);
    await settle(page);
    await checkGraph(page);
    assert.deepEqual(unexpected,[]);
    console.log('PASS '+(offline?'offline':'online')+' four tool frames, responsive geometry and graph separator');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({headless:true,ignoreDefaultArgs:['--hide-scrollbars'],
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? {executablePath:process.env.CHROMIUM_EXECUTABLE_PATH} : {})});
  try { await checkEdition(browser,false); await checkEdition(browser,true); }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
