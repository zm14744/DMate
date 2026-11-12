/* Start the application first. This suite warms a fresh service worker, then
 * disables networking and exercises the real persisted workspace in Chromium.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const panels = ['mistakes', 'notes', 'drawing', 'graph', 'questions', 'concepts'];
const iconReferences = { mistakes: '#wrongBookBtn svg', notes: '#conceptNotebookBtn svg',
  drawing: '#graphDrawingBtn svg', graph: '#knowledgeGraphBtn svg', review: '#learningReviewBtn svg' };
const toolButtons = { mistakes: '#wrongBookBtn', notes: '#conceptNotebookBtn', drawing: '#graphDrawingBtn',
  graph: '#knowledgeGraphBtn', review: '#learningReviewBtn' };
const moduleRoots = { mistakes: '#wrongBookModal', notes: '#conceptNotebookDialog', drawing: '#graphEditorDialog',
  graph: '#knowledgeGraphModal', review: '#learningReviewModal', questions: '#offlineQuestionsModal', concepts: '#offlineConceptsModal' };
const settle = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));

async function drawer(page, kind, open) {
  const mobile = page.viewportSize().width <= 1100;
  const panel = page.locator(kind === 'tools' ? '#learningToolsPanel' : '#conversationSidebar');
  const expanded = mobile ? await page.locator('body').evaluate((body, key) => body.classList.contains(key),
    kind === 'tools' ? 'mobile-tools-open' : 'mobile-left-open')
    : await page.locator(kind === 'tools' ? '#desktopToolsBtn' : '#desktopSidebarOpen').getAttribute('aria-expanded') === 'true';
  if (expanded !== open) await page.locator(mobile ? (kind === 'tools' ? (open ? '#mobileToolsBtn' : '#mobileToolsClose')
    : (open ? '#mobileNavBtn' : '#mobileNavClose')) : (kind === 'tools' ? '#desktopToolsBtn'
    : (open ? '#desktopSidebarOpen' : '#desktopSidebarToggle'))).click();
  await panel.evaluate(async node => Promise.all(node.getAnimations().map(animation => animation.finished.catch(() => {}))));
  await settle(page);
}

async function closeModules(page) {
  for (const selector of ['#conceptNotebookDialog[open] .dcn-heading .dcn-close', '#graphEditorDialog[open] #graphEditorClose',
    '#offlineQuestionsModal:not(.hidden) [data-offline-close="questions"]', '#offlineConceptsModal:not(.hidden) [data-offline-close="concepts"]',
    '#wrongBookModal:not(.hidden) #wrongBookClose', '#knowledgeGraphModal:not(.hidden) #knowledgeGraphClose',
    '#learningReviewModal:not(.hidden) #learningReviewClose']) {
    if (await page.locator(selector).isVisible()) await page.locator(selector).click();
  }
}

async function navigate(page, panel) {
  await closeModules(page);
  await drawer(page, 'tools', true);
  await page.locator(toolButtons[panel] || toolButtons.review).click();
  if (panel === 'questions' || panel === 'concepts') {
    await page.locator('#learningReviewModal').waitFor({ state: 'visible' });
    await page.locator('#learningReviewModal [data-offline-panel="' + panel + '"]').click();
  }
  await page.locator(moduleRoots[panel]).waitFor({ state: 'visible' });
}

async function ready(page) {
  await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
  await page.locator('.dmate-symbol-keyboard').waitFor();
}

async function readStore(page, name) {
  return page.evaluate(store => new Promise((resolve, reject) => {
    const request = indexedDB.open('dmate-offline-workspace');
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      const db = request.result;
      const tx = db.transaction(store, 'readonly');
      const get = tx.objectStore(store).getAll();
      tx.oncomplete = () => { db.close(); resolve(get.result); };
      tx.onerror = () => { db.close(); reject(tx.error); };
    };
  }), name);
}

async function waitRecord(page, store, title, content) {
  await page.waitForFunction(async ({ store, title, content }) => {
    const rows = await new Promise((resolve, reject) => {
      const request = indexedDB.open('dmate-offline-workspace');
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        const db = request.result, tx = db.transaction(store, 'readonly');
        const get = tx.objectStore(store).getAll();
        tx.oncomplete = () => { db.close(); resolve(get.result); };
        tx.onerror = () => { db.close(); reject(tx.error); };
      };
    });
    return rows.some(row => row.title === title && (!content || (row.content || row.statement || '').includes(content)));
  }, { store, title, content });
}

async function geometry(locator) {
  return locator.evaluate(svg => ({ viewBox: svg.getAttribute('viewBox'), children: [...svg.children].map(child => [
    child.localName, [...child.attributes].filter(attr => /^(d|x|y|x1|x2|y1|y2|cx|cy|r|rx|ry|width|height|points)$/.test(attr.name))
      .map(attr => [attr.name, attr.value.replace(/\s+/g, ' ').trim()]).sort((a, b) => a[0].localeCompare(b[0]))
  ]) }));
}

async function palette(page) {
  return page.evaluate(() => {
    const result = {};
    for (const key of ['--surface-0', '--surface-1', '--surface-2', '--surface-3', '--border-strong', '--text-primary', '--text-secondary', '--accent']) {
      const probe = document.createElement('span');
      probe.style.color = 'var(' + key + ')';
      document.body.appendChild(probe);
      result[key] = getComputedStyle(probe).color;
      probe.remove();
    }
    result.fontFamily = getComputedStyle(document.body).fontFamily;
    return result;
  });
}

async function closeStyle(locator) {
  return locator.evaluate(node => {
    const style = getComputedStyle(node);
    return Object.fromEntries(['width', 'height', 'borderRadius', 'backgroundColor'].map(key => [key, style[key]]));
  });
}

async function elementSnapshot(page, selectors) {
  return page.evaluate(values => Object.fromEntries(values.map(selector => {
    const node = document.querySelector(selector), rect = node.getBoundingClientRect(), style = getComputedStyle(node);
    return [selector, { x: rect.x, y: rect.y, width: rect.width, height: rect.height,
      background: style.backgroundColor, color: style.color, radius: style.borderRadius,
      font: style.fontFamily, fontSize: style.fontSize, fontWeight: style.fontWeight }];
  })), selectors);
}

function sameLayout(actual, expected, label) {
  for (const selector of Object.keys(expected)) for (const [key, value] of Object.entries(expected[selector])) {
    if (typeof value === 'number') assert.ok(Math.abs(actual[selector][key] - value) <= 2,
      label + ' ' + selector + '.' + key + ': ' + actual[selector][key] + ' vs ' + value);
    else assert.equal(actual[selector][key], value, label + ' ' + selector + '.' + key);
  }
}

async function shellSnapshot(page) {
  await settle(page);
  const center = await elementSnapshot(page, ['body', '.center', '.chat', '.input-wrap', '.input', '#text', '#manualQuestionMode']);
  const composerIcons = { voice: await geometry(page.locator('#voiceInputBtn svg')),
    keyboard: await geometry(page.locator('.dmate-symbol-keyboard svg')) };
  await drawer(page, 'left', true);
  const sidebar = await elementSnapshot(page, ['#conversationSidebar', '.dmate-brand', '.dmate-brand-mark', '#newChatBtn', '#appearanceBtn']);
  await drawer(page, 'left', false);
  await drawer(page, 'tools', true);
  const tools = await elementSnapshot(page, ['#learningToolsPanel', '#learningToolsPanel > .panel-heading-row',
    '#learningToolsPanel .learning-title', ...Object.values(toolButtons)]);
  const icons = {};
  for (const [panel, selector] of Object.entries(iconReferences)) icons[panel] = await geometry(page.locator(selector));
  await drawer(page, 'tools', false);
  return { center, sidebar, tools, icons, composerIcons };
}

async function modalChrome(page, panel) {
  const root = page.locator(moduleRoots[panel]);
  const card = root.locator(':scope > .modal-card');
  const surface = await card.count() ? card : root;
  const heading = root.locator(panel === 'notes' ? '.dcn-heading h2' : panel === 'drawing' ? '#graphEditorTitle' : '.modal-head > div').first();
  return { surface: await surface.evaluate(node => {
    const style = getComputedStyle(node);
    return { background: style.backgroundColor, color: style.color, border: style.borderColor, radius: style.borderRadius };
  }), heading: await heading.evaluate(node => {
    const style = getComputedStyle(node);
    return { title: node.textContent.trim(), color: style.color, size: style.fontSize, weight: style.fontWeight, font: style.fontFamily };
  }) };
}

async function openTool(page, panel) {
  await closeModules(page);
  await drawer(page, 'tools', true);
  await page.locator(toolButtons[panel]).click();
  await page.locator(moduleRoots[panel]).waitFor({ state: 'visible' });
  await settle(page);
}

async function onlineReference(page, theme) {
  await page.goto(baseURL + '/', { waitUntil: 'networkidle' });
  await page.evaluate(value => {
    document.documentElement.dataset.appearanceTheme = value;
    document.body.dataset.appearanceTheme = value;
  }, theme);
  const icons = {};
  for (const [panel, selector] of Object.entries(iconReferences)) icons[panel] = await geometry(page.locator(selector));
  const shell = await shellSnapshot(page), chrome = {};
  for (const panel of Object.keys(toolButtons)) {
    await openTool(page, panel);
    chrome[panel] = await modalChrome(page, panel);
  }
  await closeModules(page);
  return { icons, shell, chrome, palette: await palette(page), close: await closeStyle(page.locator('#wrongBookClose')) };
}

async function noOverflow(page, panel) {
  const state = await page.evaluate(id => {
    const selectors = { mistakes:'#wrongBookModal', notes:'#conceptNotebookDialog', drawing:'#graphEditorDialog',
      graph:'#knowledgeGraphModal', questions:'#offlineQuestionsModal', concepts:'#offlineConceptsModal' };
    const node = document.querySelector(selectors[id]), main = node.getBoundingClientRect();
    return { viewport: innerWidth, document: document.documentElement.scrollWidth,
      mainLeft: main.left, mainRight: main.right, panelWidth: node.clientWidth, panelScroll: node.scrollWidth };
  }, panel);
  assert.ok(state.document <= state.viewport + 1, panel + ': page overflows horizontally: ' + JSON.stringify(state));
  assert.ok(state.mainLeft >= -1 && state.mainRight <= state.viewport + 1, panel + ': workspace outside viewport');
  assert.ok(state.panelWidth > 0, panel + ': actual online-style modal is visible');
}

async function appearanceControls(page, width, theme, reference) {
  await closeModules(page);
  await drawer(page, 'left', true);
  await page.locator('#appearanceBtn').click();
  const dialog = page.locator('#appearanceModal');
  await dialog.waitFor();
  const alternate = theme === 'dark' ? 'light' : 'dark';
  await dialog.locator('[data-appearance-mode="' + alternate + '"]').click();
  await page.waitForFunction(value => document.documentElement.dataset.appearanceTheme === value, alternate);
  await page.locator('#appearanceClose').click();
  await page.waitForFunction(value => document.documentElement.dataset.appearanceTheme === value, theme);
  await drawer(page, 'left', true);
  await page.locator('#appearanceBtn').click();
  await dialog.locator('[data-appearance-mode="' + theme + '"]').click();
  await page.waitForFunction(value => document.documentElement.dataset.appearanceTheme === value, theme);
  assert.deepEqual(await closeStyle(page.locator('#appearanceClose')), reference.close, 'Appearance uses the shared close dot');
  await page.locator('#appearanceDone').click();
  await dialog.waitFor({ state: 'hidden' });
  await drawer(page, 'left', false);
}

async function confirmDeletion(page, trigger, commit) {
  await trigger.click();
  const dialog = page.locator('.dmate-delete-confirm[open],.dcn-confirm[open]');
  await dialog.waitFor({ state: 'visible' });
  await dialog.locator(commit ? '.dmate-delete-confirm-delete,.dcn-confirm-delete' : '.dmate-delete-confirm-close,.dcn-confirm-head .dcn-close').click();
  await dialog.waitFor({ state: 'detached' });
}

async function notesCRUD(page, label) {
  await navigate(page, 'notes');
  const addNote = async () => {
    const previousIds = await page.locator('#conceptNotebookDialog .dcn-note').evaluateAll(nodes => nodes.map(node => node.dataset.noteId));
    await page.locator('#conceptNotebookDialog').getByRole('button', {name:'新建概念',exact:true}).click();
    await page.waitForFunction(ids => {
      const selected = document.querySelector('#conceptNotebookDialog .dcn-note.is-current');
      return selected?.dataset.noteId && !ids.includes(selected.dataset.noteId);
    }, previousIds);
    assert.equal(await page.locator('#conceptNotebookDialog .dcn-title').inputValue(), '', 'New note editor is ready before typing');
  };
  await addNote();
  const title = '本地笔记 ' + label;
  await page.locator('#conceptNotebookDialog .dcn-title').fill(title);
  await page.locator('#conceptNotebookDialog .dcn-original').fill('归纳法：先验证初始情形，再证明递推步骤。');
  await waitRecord(page, 'notes', title, '初始情形');
  await page.locator('#conceptNotebookDialog .dcn-original').fill('归纳法修订：先验证初始情形，再由 P(n) 推出 P(n+1)。');
  await waitRecord(page, 'notes', title, '修订');
  const survivorId = (await readStore(page, 'notes')).find(row => row.title === title).id;
  const survivor = page.locator('#conceptNotebookDialog .dcn-note[data-note-id="' + survivorId + '"]');
  await confirmDeletion(page, survivor.locator('.dcn-note-delete'), false);
  assert.equal((await readStore(page, 'notes')).filter(row => row.title === title).length, 1, 'Cancel preserves note');
  await addNote();
  await page.locator('#conceptNotebookDialog .dcn-title').fill('待删除笔记');
  await page.locator('#conceptNotebookDialog .dcn-original').fill('只用于验证本机删除。');
  await waitRecord(page, 'notes', '待删除笔记');
  const temporaryId = (await readStore(page, 'notes')).find(row => row.title === '待删除笔记').id;
  const temporary = page.locator('#conceptNotebookDialog .dcn-note[data-note-id="' + temporaryId + '"]');
  await confirmDeletion(page, temporary.locator('.dcn-note-delete'), true);
  await temporary.waitFor({ state: 'detached' });
  assert.equal((await readStore(page, 'notes')).length, 1);
  return title;
}

async function saveMistake(page, title, content) {
  await page.locator('#recordTitle').fill(title);
  await page.locator('#recordContent').fill(content);
  await page.locator('#recordForm button[type="submit"]').click();
  await page.locator('#recordDialog').waitFor({ state: 'hidden' });
  await waitRecord(page, 'mistakes', title, content);
}

async function mistakeCard(page, title) {
  const row = (await readStore(page, 'mistakes')).find(item => item.title === title);
  assert.ok(row, 'Saved mistake exists: ' + title);
  return page.locator('#mistakeList .wrong-card[data-record-id="' + row.id + '"]');
}

async function mistakesCRUD(page, label, reference) {
  await navigate(page, 'mistakes');
  await page.locator('#addMistake').click();
  assert.deepEqual(await closeStyle(page.locator('#cancelRecord')), reference.close, 'Record dialog close dot matches online');
  const title = '本地错题 ' + label;
  const formula = '**勾股关系**：\\(a^2+b^2=c^2\\)。';
  await saveMistake(page, title, formula);
  const item = await mistakeCard(page, title);
  await item.locator('[data-action="edit-mistake"]').click();
  await saveMistake(page, title, formula + ' 已核对条件。');
  await item.locator('.wrong-question strong').waitFor();
  await item.locator('.wrong-question mjx-container svg').waitFor();
  await confirmDeletion(page, item.locator('[data-action="delete-mistake"]'), false);
  assert.equal((await readStore(page, 'mistakes')).length, 1, 'Cancel preserves mistake');
  await page.locator('#addMistake').click();
  await saveMistake(page, '待删除错题', '验证删除记录。');
  const temporary = await mistakeCard(page, '待删除错题');
  await confirmDeletion(page, temporary.locator('[data-action="delete-mistake"]'), true);
  await temporary.waitFor({ state: 'detached' });
  assert.equal((await readStore(page, 'mistakes')).length, 1);
  return title;
}

async function practice(page) {
  await navigate(page, 'questions');
  await page.locator('#questionList .question-item').filter({ hasText: '判断命题' }).click();
  await page.locator('#questionDetail .question-option').first().click();
  assert.equal(await page.locator('#questionDetail .question-option.selected').count(), 1);
  await page.locator('#questionDetail').getByRole('button', { name: '记录本次练习', exact: true }).click();
  await page.waitForFunction(() => document.getElementById('offlineToast').textContent.includes('练习记录'));
  await page.locator('#questionDetail').getByRole('button', { name: '查看参考答案', exact: true }).click();
  await page.locator('#questionDetail .answer-panel').waitFor();
  assert.match(await page.locator('#questionDetail .answer-panel').textContent(), /参考答案/);
  await page.locator('#questionDetail').getByRole('button', { name: '加入错题本', exact: true }).click();
  await page.waitForFunction(() => document.getElementById('offlineToast').textContent.includes('错题'));
  assert.ok((await readStore(page, 'mistakes')).some(row => row.questionId === 'q01' && row.answer.includes('C')));
  await page.locator('#questionList .question-item').filter({ hasText: '逻辑等价变形' }).click();
  await page.locator('#questionResponse').fill('¬p∨q');
  await page.locator('#questionDetail').getByRole('button', { name: '查看参考答案', exact: true }).click();
  assert.equal(await page.locator('#questionResponse').inputValue(), '¬p∨q', 'Revealing answer preserves unfinished response');
  await page.locator('#questionDetail').getByRole('button', { name: '记录本次练习', exact: true }).click();
  await page.waitForFunction(() => document.getElementById('offlineToast').textContent.includes('练习记录'));
  const rows = await readStore(page, 'practice');
  assert.ok(rows.some(row => row.questionId === 'q01' && row.selected.includes('A')));
  assert.ok(rows.some(row => row.questionId === 'q03' && row.response === '¬p∨q'));
}

async function concepts(page) {
  await navigate(page, 'concepts');
  await page.locator('#conceptSearch').fill('等价关系');
  assert.ok(await page.locator('#conceptList .concept-item').count() > 0);
  await page.locator('#conceptList .concept-item').first().click();
  assert.match(await page.locator('#conceptDetail').textContent(), /等价关系/);
  assert.match(await page.locator('#conceptDetail').textContent(), /基本定义/);
  await page.locator('#conceptSearch').fill('不存在的概念 xyzzy');
  assert.equal(await page.locator('#conceptList .concept-item').count(), 0);
  assert.match(await page.locator('#conceptDetail').textContent(), /没有找到/);
  await page.locator('#conceptSearch').fill('');
}

async function graph(page) {
  await navigate(page, 'graph');
  const host = page.locator('#knowledgeGraphCanvas[data-ready="true"]');
  await host.waitFor();
  const mobile = page.viewportSize().width <= 760;
  if (mobile && await host.locator('.kg-mobile-entry-only').count()) {
    await host.locator('.kg-mobile-expand').click();
    await host.locator('.kg-mobile-node').first().waitFor();
  }
  const nodeSelector = mobile ? '.kg-mobile-node' : '.kg-node-group';
  const edgeSelector = mobile ? '.kg-mobile-edge' : '.kg-edge';
  assert.ok(await host.locator(nodeSelector + '[data-node-id]').count() > 20, 'Graph renders actual knowledge nodes');
  assert.ok(await host.locator(edgeSelector + '[data-from][data-to]').count() > 20, 'Graph renders actual knowledge relations');
  const label = await host.locator(mobile ? '.kg-mobile-node-name' : '.kg-node-label').first().evaluate(node => {
    const style = getComputedStyle(node), box = node.getBoundingClientRect();
    return { color: node instanceof SVGElement ? style.fill : style.color, fontSize: parseFloat(style.fontSize),
      width: box.width, height: box.height, visibility: style.visibility, opacity: style.opacity };
  });
  assert.equal(label.color, 'rgb(248, 250, 252)', 'Labels remain light against the original dark graph nodes');
  assert.ok(label.fontSize > 0 && label.width > 0 && label.height > 0);
  assert.notEqual(label.visibility, 'hidden'); assert.notEqual(label.opacity, '0');
  const node = host.locator(nodeSelector + ':not(.selected)').first(), nodeId = await node.getAttribute('data-node-id');
  await node.click();
  assert.equal(await host.locator(nodeSelector + '.selected').count(), 1);
  assert.equal(await host.locator(nodeSelector + '.selected').getAttribute('aria-pressed'), 'true');
  assert.equal(await host.locator(nodeSelector + '.selected').getAttribute('data-node-id'), nodeId);
  const viewport = mobile ? host.locator('.kg-mobile-viewport') : host;
  const original = await viewport.evaluate(node => Number(node.dataset.scale));
  await page.locator(mobile ? '.kg-mobile-zoom-btn' : '#knowledgeGraphDesktopZoomIn').last().click();
  assert.ok(await viewport.evaluate(node => Number(node.dataset.scale)) > original);
  await page.locator(mobile ? '.kg-mobile-zoom-fit' : '#knowledgeGraphDesktopZoomFit').click();
  assert.ok(Math.abs(await viewport.evaluate(node => Number(node.dataset.scale)) - original) < .001, 'Fit restores scale');
}

async function drawing(page) {
  await navigate(page, 'drawing');
  const workspace = page.locator('#offlineDrawingHost .dmate-drawing-workspace');
  await workspace.waitFor();
  await workspace.getByRole('button', { name: '新建空白页', exact: true }).click();
  await workspace.locator('.ddw-name').fill('离线保存画板');
  await page.waitForFunction(() => (localStorage.getItem('dmate:offline:drawing-gallery:v1') || '').includes('离线保存画板'));
  assert.equal(await workspace.locator('.ddw-name').inputValue(), '离线保存画板');
}

async function disconnectWorkerNetwork(browser, page, workerURL) {
  // Older Playwright versions do not apply context.setOffline to the service
  // worker's own network target. Exercise an actual failed fetch there too.
  const protocol = await browser.newBrowserCDPSession();
  const pageProtocol = await page.context().newCDPSession(page);
  const {targetInfo} = await pageProtocol.send('Target.getTargetInfo');
  await pageProtocol.detach();
  const target = (await protocol.send('Target.getTargets')).targetInfos.find(info =>
    info.type === 'service_worker' && info.url === workerURL && info.browserContextId === targetInfo.browserContextId);
  assert.ok(target, 'The active service worker must have a browser target');
  const { sessionId } = await protocol.send('Target.attachToTarget', { targetId: target.targetId, flatten: false });
  let serial = 0;
  const send = async (method, params = {}) => {
    const id = ++serial;
    let listener;
    const result = new Promise((resolve, reject) => {
      listener = event => {
        if (event.sessionId !== sessionId) return;
        const response = JSON.parse(event.message);
        if (response.id !== id) return;
        if (response.error) reject(new Error(response.error.message)); else resolve(response.result);
      };
      protocol.on('Target.receivedMessageFromTarget', listener);
    });
    try {
      await protocol.send('Target.sendMessageToTarget', { sessionId, message: JSON.stringify({ id, method, params }) });
      return await result;
    } finally { protocol.off('Target.receivedMessageFromTarget', listener); }
  };
  try {
    await send('Network.enable');
    await send('Network.emulateNetworkConditions', { offline: true, latency: 0, downloadThroughput: 0, uploadThroughput: 0 });
    const probe = await send('Runtime.evaluate', {expression: "fetch('/offline-network-probe', {cache:'no-store'}).then(() => false, () => true)", awaitPromise:true, returnByValue:true});
    assert.equal(probe.result.value, true, 'The service worker itself must be disconnected');
    return protocol;
  } catch (error) { await protocol.detach(); throw error; }
}

async function runCase(browser, width, theme) {
  const label = width + '/' + theme;
  const context = await browser.newContext({ viewport: { width, height: 900 }, isMobile: width < 1101,
    hasTouch: width < 1101, serviceWorkers: 'allow' });
  await context.addInitScript(value => {
    if (!localStorage.getItem('dmate:offline:appearance:v1')) {
      localStorage.setItem('dmate:offline:appearance:v1', JSON.stringify({ mode: value, accent: 'blue', panelOpacity: 100 }));
    }
  }, theme);
  const page = await context.newPage(), errors = [], failures = [], nativeDialogs = [], apiRequests = [];
  let workerProtocol;
  try {
    const reference = await onlineReference(page, theme);
    await page.evaluate(async () => {
      await navigator.serviceWorker.register('/offline-service-worker.js', { scope: '/' });
      const registration = await navigator.serviceWorker.ready;
      const worker = registration.active;
      if (worker.state !== 'activated') await new Promise((resolve, reject) => {
        worker.addEventListener('statechange', () => {
          if (worker.state === 'activated') resolve();
          if (worker.state === 'redundant') reject(new Error('Offline service worker became redundant'));
        });
      });
    });
    // Enter through a new navigation after installation, as the online entry
    // button does. An already-loaded document need not be controlled by .ready.
    await page.goto(baseURL + '/offline', { waitUntil: 'networkidle' });
    await ready(page);
    await page.waitForFunction(() => Boolean(navigator.serviceWorker.controller));
    assert.match(await page.evaluate(() => navigator.serviceWorker.controller.scriptURL), /\/offline-service-worker\.js$/);
    page.on('pageerror', error => errors.push(error.message));
    page.on('requestfailed', request => failures.push(request.url() + ': ' + request.failure()?.errorText));
    page.on('request', request => {
      const path = new URL(request.url()).pathname;
      if (!path.startsWith('/static/') && !['/offline', '/offline-service-worker.js', '/favicon.ico'].includes(path)) apiRequests.push(path);
    });
    page.on('dialog', async dialog => { nativeDialogs.push(dialog.type()); await dialog.dismiss(); });
    await context.setOffline(true);
    workerProtocol = await disconnectWorkerNetwork(browser, page, await page.evaluate(() => navigator.serviceWorker.controller.scriptURL));
    await page.reload({ waitUntil: 'networkidle' });
    await ready(page);
    assert.equal(await page.evaluate(() => navigator.onLine), false);
    if (await page.locator('#networkStatus').count()) assert.match(await page.locator('#networkStatus').textContent(), /离线/);
    assert.deepEqual(await palette(page), reference.palette, label + ': shared online appearance tokens');
    const actualShell = await shellSnapshot(page);
    sameLayout(actualShell.center, reference.shell.center, label + ': original center/composer');
    sameLayout(actualShell.sidebar, reference.shell.sidebar, label + ': original conversation sidebar');
    sameLayout(actualShell.tools, reference.shell.tools, label + ': original learning-tools panel');
    assert.deepEqual(actualShell.icons, reference.shell.icons, label + ': five original tool icons');
    assert.deepEqual(actualShell.composerIcons, reference.shell.composerIcons, label + ': original composer icons');
    for (const panel of Object.keys(toolButtons)) {
      await openTool(page, panel);
      assert.deepEqual(await modalChrome(page, panel), reference.chrome[panel], label + ': original modal chrome ' + panel);
    }
    await closeModules(page);
    for (const panel of panels) {
      await navigate(page, panel);
      await noOverflow(page, panel);
    }
    await appearanceControls(page, width, theme, reference);
    const noteTitle = await notesCRUD(page, label);
    const mistakeTitle = await mistakesCRUD(page, label, reference);
    await practice(page);
    await concepts(page);
    await graph(page);
    await drawing(page);
    // A second fully offline navigation must restore records and the drawing.
    await page.reload({ waitUntil: 'networkidle' });
    await ready(page);
    assert.equal(await page.evaluate(() => document.documentElement.dataset.appearanceTheme), theme, 'Offline appearance persists');
    await navigate(page, 'notes');
    assert.equal((await readStore(page, 'notes'))[0].title, noteTitle);
    await page.locator('#conceptNotebookDialog .dcn-note-open').filter({ hasText: noteTitle }).click();
    assert.match(await page.locator('#conceptNotebookDialog .dcn-original').inputValue(), /修订/);
    await navigate(page, 'mistakes');
    assert.ok((await readStore(page, 'mistakes')).some(row => row.title === mistakeTitle));
    await (await mistakeCard(page, mistakeTitle)).locator('mjx-container svg').waitFor();
    assert.ok((await readStore(page, 'practice')).length >= 2);
    await navigate(page, 'drawing');
    assert.equal(await page.locator('#offlineDrawingHost .ddw-name').inputValue(), '离线保存画板');
    for (const panel of panels) {
      await navigate(page, panel);
      await noOverflow(page, panel);
      if (process.env.OFFLINE_SCREENSHOT_DIR) {
        await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/' + width + '-' + theme + '-' + panel + '.png' });
      }
    }
    assert.deepEqual(nativeDialogs, [], label + ': deletion uses the shared in-app confirmation');
    assert.deepEqual(apiRequests, [], label + ': offline work must not call server APIs');
    assert.deepEqual(failures, [], label + ': required resources must be cached');
    assert.deepEqual(errors, [], label + ': no page errors');
    console.log('PASS ' + label + ': six panels, shared appearance/icons, CRUD, practice, math, graph, drawing and offline reload');
  } catch (error) {
    const workerStatus = await page.evaluate(async () => {
      const describe = worker => worker && ({ state: worker.state, scriptURL: worker.scriptURL });
      return { controller: describe(navigator.serviceWorker.controller),
        registrations: (await navigator.serviceWorker.getRegistrations()).map(registration => ({
          scope: registration.scope, active: describe(registration.active), waiting: describe(registration.waiting),
          installing: describe(registration.installing)
        })), caches: await Promise.all((await caches.keys()).map(async name => ({
          name, entries: (await (await caches.open(name)).keys()).length
        }))) };
    }).catch(() => null);
    console.error('Offline worker status at failure:', JSON.stringify(workerStatus));
    if (process.env.OFFLINE_SCREENSHOT_DIR) {
      await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/FAILED-' + width + '-' + theme + '.png' }).catch(() => {});
    }
    throw error;
  } finally { await workerProtocol?.detach().catch(() => {}); await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const width of [1440, 390]) for (const theme of ['light', 'dark', 'navy']) await runCase(browser, width, theme);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
