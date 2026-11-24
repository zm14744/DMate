/* Start Flask first. Tests real online/offline drawing controls and shared
 * library fields; each fresh browser context owns its temporary drawing.
 */
'use strict';
const assert = require('node:assert/strict');
const { revealInterface } = require('./offline-vault-browser-fixtures.cjs');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const mobile = page => page.viewportSize().width <= 1100;
const officialPaths = {
  'undo-2': ['M9 14 4 9l5-5', 'M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5a5.5 5.5 0 0 1-5.5 5.5H11'],
  'redo-2': ['m15 14 5-5-5-5', 'M20 9H9.5A5.5 5.5 0 0 0 4 14.5A5.5 5.5 0 0 0 9.5 20H13']
};

async function settle(page) {
  await page.evaluate(async () => {
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    await Promise.all(document.getAnimations().filter(animation =>
      animation.effect?.getComputedTiming().iterations !== Infinity)
      .map(animation => animation.finished.catch(() => {})));
  });
}

async function navigate(page, panel) {
  if (mobile(page) && !await page.evaluate(() => document.body.classList.contains('offline-nav-open'))) {
    await page.locator('#offlineNavToggle').tap();
  }
  const entry = page.locator('.offline-nav-item[data-panel="' + panel + '"]');
  if (mobile(page)) await entry.tap(); else await entry.click();
  await page.locator('#' + panel + 'Panel').waitFor({ state: 'visible' });
  await settle(page);
}

async function toolsEntry(page, id) {
  const kind = mobile(page) ? 'mobile-tools-open' : 'desktop-tools-open';
  if (!await page.evaluate(kind => document.body.classList.contains(kind), kind)) {
    await page.locator(mobile(page) ? '#mobileToolsBtn' : '#desktopToolsBtn').click();
  }
  await page.locator('#' + id).click();
  await settle(page);
}

async function checkIcon(button, name, size) {
  const svg = button.locator('svg[data-lucide="' + name + '"][data-icon="' + name + '"]');
  assert.equal(await svg.count(), 1, name + ': official icon is identified');
  assert.equal(await svg.getAttribute('viewBox'), '0 0 24 24');
  assert.equal(await svg.getAttribute('stroke-width'), '1.8');
  assert.deepEqual(await svg.locator('path').evaluateAll(paths => paths.map(path => path.getAttribute('d'))), officialPaths[name]);
  const rect = await svg.boundingBox();
  assert.ok(rect && Math.abs(rect.width - size) <= 1 && Math.abs(rect.height - size) <= 1, name + ': glyph remains visible at its intended size');
}

async function drawingPaint(page, searchBackground, theme) {
  if (theme === 'light') {
    const paletteControls = [page.locator('.dge-tool-palette > summary'),
      page.locator('.ddw-side-actions > button').nth(0), page.locator('.ddw-side-actions > button').nth(1)];
    const palettePaint = control => control.evaluate(node => Object.fromEntries(
      ['backgroundColor','backgroundImage','borderTopColor','color'].map(key => [key,getComputedStyle(node)[key]])));
    await page.mouse.move(0,0); await settle(page);
    const expectedPalette = await palettePaint(paletteControls[1]);
    for (const control of paletteControls) assert.deepEqual(await palettePaint(control),expectedPalette,
      'Drawing tools, drawing settings and graph information share the same light-theme palette');
    if (!mobile(page)) {
      const hovered = [];
      for (const control of paletteControls) { await control.hover(); await settle(page); hovered.push(await palettePaint(control)); }
      for (const paint of hovered) assert.deepEqual(paint,hovered[0], 'All three drawing controls share hover colors');
      await page.mouse.move(0,0); await settle(page);
    }
  }
  const controls = await page.locator('.dge-view-controls').evaluate(node => {
    const css = getComputedStyle(node), minus = node.querySelector('[data-overlay-tool="zoom-out"]').getBoundingClientRect();
    const undo = document.querySelector('[data-editor-undo]').getBoundingClientRect(), clear = document.querySelector('[data-editor-clear]').getBoundingClientRect(), row=node.parentElement.getBoundingClientRect();
    return { border: [css.borderTopWidth, css.borderRightWidth, css.borderBottomWidth, css.borderLeftWidth],
      background: css.backgroundColor, image: css.backgroundImage, shadow: css.boxShadow,
      minusLeft: minus.left, clearRight: clear.right, minusCenter:minus.top+minus.height/2,undoCenter:undo.top+undo.height/2,
      right:node.getBoundingClientRect().right,rowRight:row.right };
  });
  assert.deepEqual(controls.border, ['0px', '0px', '0px', '0px'], 'Zoom controls have no outer rectangular border');
  assert.equal(controls.background, 'rgba(0, 0, 0, 0)');
  assert.equal(controls.image, 'none');
  assert.equal(controls.shadow, 'none');
  assert.ok(controls.minusLeft>=controls.clearRight, 'Zoom controls follow Clear on the right');
  assert.ok(Math.abs(controls.minusCenter-controls.undoCenter)<=1, 'Zoom and Undo share the same action row');
  assert.ok(Math.abs(controls.right-controls.rowRight)<=1, 'Zoom controls align with the action row’s right edge');
  if(page.viewportSize().width<=600){
    const layout=await page.locator('.dmate-drawing-workspace').evaluate(shell=>{
      const box=node=>{const r=node.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
      return {pages:[...shell.querySelectorAll('.ddw-page-actions>button')].map(box),
        tools:box(shell.querySelector('.dge-tool-palette>summary')),
        actions:[...shell.querySelectorAll('.ddw-side-actions>button')].map(box),
        clear:box(shell.querySelector('[data-editor-clear]')),frame:box(shell.querySelector('.ddw-canvas-frame'))};
    });
    assert.ok(layout.pages.every(button=>Math.abs(button.top-layout.pages[0].top)<1
      && Math.abs(button.width-layout.pages[0].width)<1),'Page actions occupy one row of equal-width buttons');
    const firstRow=[layout.tools,...layout.actions.slice(0,2)];
    assert.ok(firstRow.every(button=>Math.abs(button.top-layout.tools.top)<1
      && Math.abs(button.width-layout.tools.width)<1),'Drawing tools, settings and information form one aligned row');
    for(let i=1;i<firstRow.length;i++)assert.ok(firstRow[i].left-firstRow[i-1].right>=4,'Canvas buttons retain distinct tap targets');
    for(const button of [...firstRow,...layout.actions.slice(2)])assert.ok(button.left>=layout.frame.left&&button.right<=layout.frame.right,'Canvas buttons stay inside the drawing frame');
    if(layout.actions.length===4)assert.ok(layout.actions[2].top-layout.actions[0].bottom>=4
      && Math.abs(layout.actions[2].top-layout.actions[3].top)<1,'The two AI actions share the second row');
    assert.ok(layout.clear.height<=40,'Clear does not wrap in a narrow action row');
    assert.ok(controls.minusLeft-controls.clearRight>=6,'Clear and the zoom group remain visibly separated');
    const language=await page.evaluate(()=>document.documentElement.lang);
    try{
      await page.evaluate(()=>DMateI18n.setLanguage('en',false));await settle(page);
      const overflow=await page.locator('.ddw-page-actions>button,.dge-tool-palette>summary,.ddw-side-actions>button')
        .evaluateAll(buttons=>buttons.filter(button=>button.scrollWidth>button.clientWidth+1).map(button=>button.textContent));
      assert.deepEqual(overflow,[],'Long English labels wrap within their mobile buttons');
    }finally{await page.evaluate(language=>DMateI18n.setLanguage(language,false),language);await settle(page);}
  }
  assert.equal(await page.locator('.ddw-name').evaluate(input => getComputedStyle(input).backgroundColor), searchBackground,
    'Drawing name uses the search input surface without imposing search dimensions');
  await checkIcon(page.locator('[data-editor-undo]'), 'undo-2', 24);
  await checkIcon(page.locator('[data-editor-redo]'), 'redo-2', 24);
  const clear = page.locator('[data-editor-clear].dge-clear-button');
  assert.equal(await clear.locator('svg').count(), 0, 'Clear is a text-only action');
  assert.ok((await clear.innerText()).includes('清空'), 'Clear keeps its text label');
}

async function undoRedo(page) {
  const read = () => page.evaluate(() => window.__drawingControlsController.getDocument());
  const before = await read();
  await page.locator('.dge-tool-palette > summary').click();
  await page.locator('[data-overlay-tool="vertex"]').click();
  const view = await page.locator('.dge-overlay-viewport').boundingBox();
  const x = view.x + view.width * .55, y = view.y + view.height * .65;
  if (mobile(page)) await page.touchscreen.tap(x, y); else await page.mouse.click(x, y);
  const count = before.graphs.reduce((sum, graph) => sum + graph.vertices.length, 0);
  await page.waitForFunction(count => window.__drawingControlsController.getDocument().graphs
    .reduce((sum, graph) => sum + graph.vertices.length, 0) === count + 1, count);
  const added = await read();
  await page.locator('[data-editor-undo]').click();
  assert.deepEqual(await read(), before, 'Undo really restores the previous drawing document');
  await page.locator('[data-editor-redo]').click();
  assert.deepEqual(await read(), added, 'Redo restores the actual added vertex');
}

async function safeHistoryDelete(page, name, offline) {
  await page.locator('.ddw-page-actions > button').filter({ hasText: /^历史绘图$/ }).click();
  const row = page.locator('.ddw-history-item').filter({ hasText: name });
  const remove = row.locator('.ddw-history-delete');
  assert.equal(await remove.locator('*').count(), 0, 'History removal is the same empty red dot as a modal close, without a trash glyph');
  assert.equal((await remove.textContent()).trim(), '');
  const reference = page.locator(await page.locator('#graphEditorClose').count() ? '#graphEditorClose' : '#appearanceClose');
  const paint = control => control.evaluate(button => Object.fromEntries(
    ['width','height','padding','borderWidth','borderRadius',
      'backgroundColor','backgroundImage','boxShadow','filter'].map(key => [key, getComputedStyle(button)[key]])));
  const original = await page.evaluate(() => [document.documentElement.dataset.appearanceTheme, document.body.dataset.appearanceTheme]);
  try {
    for (const theme of ['light','dark','navy']) {
      await page.evaluate(theme => [document.documentElement,document.body].forEach(node => { node.dataset.appearanceTheme = theme; }), theme);
      await page.mouse.move(0,0); await settle(page);
      const expected = await paint(reference);
      assert.deepEqual(await paint(remove), expected, 'History dot matches modal close geometry and paint in ' + theme);
      await remove.hover(); await settle(page);
      assert.deepEqual(await paint(remove), expected, 'Hover does not change the solid close-dot parameters');
    }
  } finally {
    await page.evaluate(values => [document.documentElement,document.body].forEach((node,i) => {
      if (values[i] === undefined) delete node.dataset.appearanceTheme; else node.dataset.appearanceTheme = values[i];
    }), original);
  }
  const before = await page.evaluate(() => window.__drawingControlsController.getPages().map(page => ({ id: page.id, name: page.name })));
  const own = before.find(page => page.name === name);
  assert.ok(own, 'Delete is limited to this context’s temporary drawing');
  await remove.click();
  const prompt = page.locator('.dmate-delete-confirm[open]');
  await prompt.waitFor({ state: 'visible' });
  const heading = control => control.evaluate(node => Object.fromEntries(['fontFamily','fontSize','fontWeight','lineHeight']
    .map(key => [key,getComputedStyle(node)[key]])));
  const referenceTitle = page.locator(await page.locator('#appConfirmTitle').count() ? '#appConfirmTitle' : '#appearanceModal .modal-head > div:first-child');
  assert.deepEqual(await heading(prompt.locator('.dmate-delete-confirm-title')), await heading(referenceTitle),
    'Drawing confirmation heading shares ordinary modal typography');
  assert.deepEqual(await paint(prompt.locator('.dmate-delete-confirm-close')), await paint(reference),
    'Drawing confirmation also uses the shared red close dot');
  assert.equal(await prompt.locator('.dmate-delete-confirm-body').innerText(), offline ? '删除操作不可逆' : '删除后，绘画内容将不可恢复');
  assert.ok(!(await prompt.innerText()).includes(name), 'The confirmation omits the drawing name');
  await prompt.locator('.dmate-delete-confirm-close').click();
  assert.deepEqual(await page.evaluate(() => window.__drawingControlsController.getPages().map(page => ({ id: page.id, name: page.name }))), before,
    'Cancel leaves every drawing intact');
  await row.locator('.ddw-history-delete').click();
  await page.locator('.dmate-delete-confirm[open] .dmate-delete-confirm-delete').click();
  await page.waitForFunction(id => !window.__drawingControlsController.getPages().some(page => page.id === id), own.id);
  assert.deepEqual(await page.evaluate(() => window.__drawingControlsController.getPages().map(page => ({ id: page.id, name: page.name }))),
    before.filter(page => page.id !== own.id), 'Confirmed deletion removes only the temporary drawing');
}

async function filterMetrics(page) {
  const metrics = {};
  for (const [panel, prefix] of [['concepts', 'concept'], ['questions', 'question']]) {
    await navigate(page, panel);
    metrics[prefix] = await page.locator('#' + prefix + 'Category').evaluate(select => {
      const selection = document.getElementById(select.id.replace('Category', 'Selection'));
      const box = node => { const rect = node.getBoundingClientRect(); return { width: rect.width, height: rect.height }; };
      return { category: box(select), selection: box(selection) };
    });
    assert.equal(await page.locator('#' + panel + 'Panel input[type="search"]').count(), 0, 'Library filtering no longer includes a search field');
    const before = await page.locator('#' + panel + 'Panel').evaluate(panel => ({ panel: panel.scrollTop,
      body: document.body.scrollTop, root: document.scrollingElement.scrollTop,
      toolbarTop: panel.querySelector('.offline-toolbar').getBoundingClientRect().top }));
    const list = page.locator('#' + prefix + 'List');
    await list.evaluate(node => { node.scrollTop = 0; });
    await list.hover();
    await page.mouse.wheel(0, 360);
    await page.waitForFunction(id => document.getElementById(id).scrollTop > 0, prefix + 'List');
    assert.deepEqual(await page.locator('#' + panel + 'Panel').evaluate(panel => ({ panel: panel.scrollTop,
      body: document.body.scrollTop, root: document.scrollingElement.scrollTop,
      toolbarTop: panel.querySelector('.offline-toolbar').getBoundingClientRect().top })), before, 'Library controls keep independent scrolling');
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  }
  for (const field of ['category', 'selection']) for (const axis of ['width', 'height']) {
    assert.ok(Math.abs(metrics.concept[field][axis] - metrics.question[field][axis]) <= 1,
      'Concept/practice ' + field + ' ' + axis + ' match: ' + JSON.stringify(metrics));
  }
}

async function pdfPaint(page) {
  await toolsEntry(page, 'wrongBookBtn');
  const button = page.locator('#wrongPdfBtn');
  const paint = () => button.evaluate(button => {
    const css = getComputedStyle(button);
    return { border: css.borderTopWidth, background: css.backgroundColor, image: css.backgroundImage, shadow: css.boxShadow };
  });
  await page.mouse.move(0, 0);
  await button.evaluate(button => button.blur());
  await settle(page);
  const idle = await paint();
  assert.equal(idle.border, '0px');
  assert.equal(idle.background, 'rgba(0, 0, 0, 0)');
  assert.equal(idle.image, 'none');
  assert.equal(idle.shadow, 'none');
  if (!mobile(page)) {
    await button.hover();
    await settle(page);
    assert.notEqual((await paint()).background, idle.background, 'PDF export gets the shared hover fill');
    await page.mouse.move(0, 0);
    await page.keyboard.press('Tab');
    await button.focus();
    await settle(page);
    assert.equal(await button.evaluate(button => button.matches(':focus-visible')), true);
    assert.notEqual((await paint()).background, idle.background, 'Keyboard focus gets feedback');
  }
  await button.evaluate(button => { button.disabled = true; });
  const box = await button.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await settle(page);
  assert.deepEqual(await paint(), idle, 'Disabled PDF action does not light up on hover');
  await button.evaluate(button => { button.disabled = false; });
}

async function runCase(browser, width, theme, offline) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block',
    ...(width <= 1100 ? { isMobile: true, hasTouch: true } : {}) });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(baseURL + (offline ? '/offline' : ''), { waitUntil: 'networkidle' });
    if (offline) {
      await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
      await revealInterface(page);
      await page.evaluate(mode => window.DMateOfflineAppearance.apply({ mode }, null), theme);
      await filterMetrics(page);
      await navigate(page, 'notes');
    } else await page.evaluate(mode => { appearanceSettings.mode = mode; applyAppearanceSettings({ save: false }); }, theme);
    const searchBackground = await page.locator(offline ? '#notesPanel .dcn-search' : '#wrongBookSearch').evaluate(input => getComputedStyle(input).backgroundColor);
    // Capture the public controller while preserving the real mounted app.
    await page.evaluate(() => {
      const mount = window.DMateDrawingWorkspace.mount;
      window.DMateDrawingWorkspace.mount = function (...args) {
        const controller = mount.apply(this, args); window.__drawingControlsController = controller; return controller;
      };
    });
    if (offline) await navigate(page, 'drawing'); else await toolsEntry(page, 'graphDrawingBtn');
    await page.locator('.ddw-page-actions > button').filter({ hasText: /^新建空白页$/ }).click();
    await page.locator('.dge-overlay[data-geometry-ready="true"]').waitFor();
    const name = 'Drawing controls ' + width + (offline ? ' offline' : ' online');
    await page.locator('.ddw-name').fill(name);
    await settle(page);
    await drawingPaint(page, searchBackground, theme);
    await undoRedo(page);
    await safeHistoryDelete(page, name, offline);
    if (!offline) {
      await page.locator('#graphEditorClose').click();
      await pdfPaint(page);
    }
    assert.deepEqual(errors, [], 'No drawing control script errors');
    console.log('PASS ' + (offline ? 'offline ' : 'online ') + width + '/' + theme + ': drawing chrome, official icons, real undo/redo and safe history deletion');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const [width, theme] of [[1440, 'light'], [390, 'dark'], [320, 'dark']]) for (const offline of [false, true]) await runCase(browser, width, theme, offline);
    const context = await browser.newContext({ viewport: { width: 820, height: 900 }, isMobile: true, hasTouch: true, serviceWorkers: 'block' });
    try {
      const page = await context.newPage(); await page.goto(baseURL + '/offline', { waitUntil: 'networkidle' });
      await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
      await revealInterface(page);
      await page.evaluate(() => window.DMateOfflineAppearance.apply({ mode: 'navy' }, null));
      await filterMetrics(page);
      console.log('PASS offline 820/navy: matching library filter dimensions and independent scrolling');
    } finally { await context.close(); }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
