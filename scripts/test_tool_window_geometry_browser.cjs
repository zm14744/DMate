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
const offlineTools = [tools[1], tools[0], tools[2], tools[3],
  { name:'concepts', button:'.offline-nav-item[data-panel="concepts"]', offline:'#conceptsPanel' },
  { name:'questions', button:'.offline-nav-item[data-panel="questions"]', offline:'#questionsPanel' }
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

async function titleBar(surface) {
  return surface.locator(':scope > :is(.dcn-heading,.modal-head,.graph-editor-dialog-head)').evaluate(head => {
    const box = head.getBoundingClientRect(), title = head.firstElementChild;
    const close = head.querySelector('.dcn-close,.modal-close-dot,.graph-editor-close-dot').getBoundingClientRect();
    const font = getComputedStyle(title), edge = getComputedStyle(head);
    return {height:box.height, titleInset:title.getBoundingClientRect().left-box.left,
      closeInset:box.right-close.right, closeSize:[close.width,close.height],
      closeCenter:close.top+close.height/2-box.top,
      font:[font.fontFamily,font.fontSize,font.fontWeight,font.lineHeight],
      border:[edge.borderBottomWidth,edge.borderBottomColor]};
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
  assert.equal(borders.bar,mobile ? 'none' : 'auto','The desktop graph uses shared scrollbars and mobile hides them');
  assert.equal(borders.gutter,mobile ? 'auto' : 'stable','Only the desktop graph reserves a scrollbar gutter');
}

async function compareTools(page, offline, active, sizes, previousFrames) {
  const reference = [];
  const frames = {}, notebookTitles = [];
  for (const tool of offline ? offlineTools : tools) {
    frames[tool.name] = [];
    await page.setViewportSize(sizes[0]);
    const surface = await openTool(page,tool,offline);
    for (const [index,size] of sizes.entries()) {
      await page.setViewportSize(size);
      await settle(page);
      const box = await frame(surface), label = [offline ? 'offline' : active ? 'chat' : 'welcome',tool.name,size.width].join('/');
      assert.notEqual(box.paint,'rgba(0, 0, 0, 0)',label+' measures a painted surface');
      assert.ok(box.width > size.width * .6,label+' uses a large desktop frame');
      near(box.height,Math.min(size.height*.88,920),label+' retains the full window height');
      assert.ok(box.x >= 0 && box.y >= 0 && box.x+box.width <= size.width+1 && box.y+box.height <= size.height+1,label+' fits the screen');
      assert.ok(parseFloat(box.radius) > 0,label+' has rounded corners');
      if (reference[index]) compare(box,reference[index],label);
      else reference[index] = box;
      frames[tool.name][index] = box;
      if (previousFrames) {
        const previous = previousFrames[tool.name][index];
        compare(box,previous,label+' matches the same tool across conversation states');
        assert.equal(box.paint,previous.paint,label+' keeps the same surface color');
      }
      if (!offline) {
        if (active) {
          const composer = await page.locator('.center > .input-wrap > .input').boundingBox();
          near(box.y+box.height,composer.y+composer.height,label+' aligns with the conversation composer');
        }
        const chrome = await titleBar(surface);
        if (tool.name === 'notebook') notebookTitles[index] = chrome;
        else assert.deepEqual(chrome,notebookTitles[index],label+' shares the notebook title bar');
      }
      if (tool.name === 'graph') await checkGraph(page);
    }
    if (!offline) await page.locator(tool.close).click();
  }
  return frames;
}

async function checkEdition(browser, offline, theme) {
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
      await page.evaluate(theme => { appearanceSettings.mode=theme; applyAppearanceSettings({save:false}); },theme);
      assert.equal(await page.locator('html').getAttribute('data-appearance-theme'),theme);
      const welcomeFrames = await compareTools(page,false,false,[desktop,narrow]);
      await page.evaluate(() => {
        newChat();
        getCurrent().messages.push({messageId:'geometry-message',role:'user',text:'窗口尺寸测试',manualIsQuestion:false,createdAt:Date.now()});
        renderAll();
      });
      await page.locator('.center:not(.chat-empty) #chat .msg.user').waitFor();
      await page.waitForFunction(() => !document.querySelector('.center').dataset.composerMotion);
      const activeFrames = await compareTools(page,false,true,[desktop,narrow],welcomeFrames);
      await page.setViewportSize(desktop);
      await settle(page);
      const singleLine = await page.locator('.center > .input-wrap > .input').boundingBox();
      await page.locator('#text').fill('多行草稿\n用于测试输入框扩展\n窗口底边仍对齐');
      await settle(page);
      const expanded = await page.locator('.center > .input-wrap > .input').boundingBox();
      assert.ok(expanded.height > singleLine.height+20,'The fixture really expands the composer before comparing frames');
      await compareTools(page,false,true,[desktop,narrow]);
      await page.setViewportSize(desktop);
      await page.evaluate(() => { currentId=null;renderAll(); });
      await page.locator('.center.chat-empty').waitFor();
      await page.waitForFunction(() => !document.querySelector('.center').dataset.composerMotion);
      await compareTools(page,false,false,[desktop,narrow],activeFrames);
      await page.setViewportSize(desktop);
      const notebook = tools[0];
      await page.locator('.center > .input-wrap').evaluate(node => { node.hidden=true; });
      const fallback = await openTool(page,notebook,false);
      await settle(page);
      const hiddenFrame = await frame(fallback);
      near(hiddenFrame.y+hiddenFrame.height,desktop.height-16,'A hidden composer keeps the full-size frame');
      await page.locator(notebook.close).click();
      await page.locator('.center > .input-wrap').evaluate(node => { node.hidden=false; });
      await settle(page);
    }
    await page.setViewportSize(phone);
    if (offline) await settle(page);
    await openTool(page,tools.find(tool => tool.name === 'graph'),offline);
    await settle(page);
    await checkGraph(page);
    assert.deepEqual(unexpected,[]);
    console.log('PASS '+(offline?'offline workspace frames':'online '+theme+' tool frames over welcome and active chat')+', responsive geometry and graph separator');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({headless:true,ignoreDefaultArgs:['--hide-scrollbars'],
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? {executablePath:process.env.CHROMIUM_EXECUTABLE_PATH} : {})});
  try {
    await checkEdition(browser,false,'dark');
    await checkEdition(browser,true);
  }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
