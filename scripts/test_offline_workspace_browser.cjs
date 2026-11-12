/* Start the application first. This suite warms a fresh service worker, then
 * disables networking and exercises the real persisted workspace in Chromium.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const panels = ['mistakes', 'notes', 'drawing', 'graph', 'questions', 'concepts'];
const iconReferences = { mistakes: '#wrongBookBtn svg', notes: '#conceptNotebookBtn svg',
  drawing: '#graphDrawingBtn svg', graph: '#knowledgeGraphBtn svg' };

async function navigate(page, panel) {
  const item = page.locator('.offline-nav-item[data-panel="' + panel + '"]');
  const toggle = page.locator((await page.viewportSize()).width <= 1100
    ? '#offlineNavToggle' : '#offlineDesktopSidebarOpen');
  // A closing drawer can still have an onscreen rectangle while already inert.
  // Its accessibility state, rather than animation timing, determines whether
  // the user needs to open navigation before selecting the next panel.
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
  await item.click();
  await page.locator('#' + panel + 'Panel').waitFor({ state: 'visible' });
}

async function ready(page) {
  await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
  assert.equal(await page.locator('#saveState').textContent(), '本地保存已启用');
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

async function onlineReference(page, theme) {
  await page.goto(baseURL + '/', { waitUntil: 'networkidle' });
  await page.evaluate(value => {
    document.documentElement.dataset.appearanceTheme = value;
    document.body.dataset.appearanceTheme = value;
  }, theme);
  const icons = {};
  for (const [panel, selector] of Object.entries(iconReferences)) icons[panel] = await geometry(page.locator(selector));
  return { icons, palette: await palette(page), close: await closeStyle(page.locator('#wrongBookClose')) };
}

async function noOverflow(page, panel) {
  const state = await page.evaluate(id => {
    const main = document.querySelector('.offline-main').getBoundingClientRect();
    const node = document.getElementById(id + 'Panel');
    return { viewport: innerWidth, document: document.documentElement.scrollWidth,
      mainLeft: main.left, mainRight: main.right, panelWidth: node.clientWidth, panelScroll: node.scrollWidth };
  }, panel);
  assert.ok(state.document <= state.viewport + 1, panel + ': page overflows horizontally: ' + JSON.stringify(state));
  assert.ok(state.mainLeft >= -1 && state.mainRight <= state.viewport + 1, panel + ': workspace outside viewport');
  assert.ok(state.panelScroll <= state.panelWidth + 1, panel + ': panel overflows outside its own controls');
}

async function appearanceControls(page, width, theme, reference) {
  await page.locator(width <= 1100 ? '#offlineAppearanceToggle' : '#offlineAppearanceBtn').click();
  const dialog = page.locator('#offlineAppearanceDialog[open]');
  await dialog.waitFor();
  const alternate = theme === 'dark' ? 'light' : 'dark';
  await dialog.locator('[data-offline-theme="' + alternate + '"]').click();
  await page.waitForFunction(value => document.documentElement.dataset.appearanceTheme === value, alternate);
  await dialog.locator('[data-offline-theme="' + theme + '"]').click();
  await page.waitForFunction(value => document.documentElement.dataset.appearanceTheme === value, theme);
  assert.deepEqual(await closeStyle(page.locator('#offlineAppearanceClose')), reference.close, 'Appearance uses the shared close dot');
  await page.locator('#offlineAppearanceClose').click();
}

async function confirmDeletion(page, trigger, commit) {
  await trigger.click();
  const dialog = page.locator('.dmate-delete-confirm[open]');
  await dialog.waitFor({ state: 'visible' });
  await dialog.locator(commit ? '.dmate-delete-confirm-delete' : '.dmate-delete-confirm-close').click();
  await dialog.waitFor({ state: 'detached' });
}

async function notesCRUD(page, label) {
  await navigate(page, 'notes');
  const addNote = async () => {
    const previousIds = await page.locator('#noteList .dcn-note').evaluateAll(nodes => nodes.map(node => node.dataset.noteId));
    await page.locator('#addNote').click();
    await page.waitForFunction(ids => {
      const selected = document.querySelector('#noteList .dcn-note.is-current');
      return selected?.dataset.noteId && !ids.includes(selected.dataset.noteId);
    }, previousIds);
    assert.equal(await page.locator('#noteList .dcn-title').inputValue(), '', 'New note editor is ready before typing');
  };
  await addNote();
  const title = '本地笔记 ' + label;
  await page.locator('#noteList .dcn-title').fill(title);
  await page.locator('#noteList .dcn-original').fill('归纳法：先验证初始情形，再证明递推步骤。');
  await waitRecord(page, 'notes', title, '初始情形');
  await page.locator('#noteList .dcn-original').fill('归纳法修订：先验证初始情形，再由 P(n) 推出 P(n+1)。');
  await waitRecord(page, 'notes', title, '修订');
  const survivorId = (await readStore(page, 'notes')).find(row => row.title === title).id;
  const survivor = page.locator('#noteList .dcn-note[data-note-id="' + survivorId + '"]');
  await confirmDeletion(page, survivor.locator('.dcn-note-delete'), false);
  assert.equal((await readStore(page, 'notes')).filter(row => row.title === title).length, 1, 'Cancel preserves note');
  await addNote();
  await page.locator('#noteList .dcn-title').fill('待删除笔记');
  await page.locator('#noteList .dcn-original').fill('只用于验证本机删除。');
  await waitRecord(page, 'notes', '待删除笔记');
  const temporaryId = (await readStore(page, 'notes')).find(row => row.title === '待删除笔记').id;
  const temporary = page.locator('#noteList .dcn-note[data-note-id="' + temporaryId + '"]');
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
  const host = page.locator('#graphNodes .offline-knowledge-graph[data-ready="true"]');
  await host.waitFor();
  assert.ok(await host.locator('svg .kg-node-group[data-node-id]').count() > 20, 'Graph renders real SVG nodes');
  assert.ok(await host.locator('svg .kg-edge[data-from][data-to]').count() > 20, 'Graph renders actual knowledge relations');
  const label = await host.locator('.kg-node-label').first().evaluate(node => {
    const style = getComputedStyle(node), box = node.getBBox();
    return { fill: style.fill, fontSize: parseFloat(style.fontSize), width: box.width, height: box.height,
      visibility: style.visibility, opacity: style.opacity };
  });
  assert.equal(label.fill, 'rgb(248, 250, 252)', 'Labels remain light against the shared dark graph nodes');
  assert.ok(label.fontSize > 0 && label.width > 0 && label.height > 0, 'Graph labels render visible text');
  assert.notEqual(label.visibility, 'hidden');
  assert.notEqual(label.opacity, '0');
  const node = host.locator('.kg-node-group:not(.selected)').first();
  const nodeId = await node.getAttribute('data-node-id');
  await node.click();
  assert.equal(await host.locator('.kg-node-group.selected').count(), 1);
  assert.equal(await host.locator('.kg-node-group.selected').getAttribute('aria-pressed'), 'true');
  assert.equal(await host.locator('.kg-node-group.selected').getAttribute('data-node-id'), nodeId);
  const viewport = host.locator('.offline-graph-canvas');
  const original = await viewport.evaluate(node => Number(node.dataset.scale));
  await host.locator('[data-graph-action="zoom-in"]').click();
  assert.ok(await viewport.evaluate(node => Number(node.dataset.scale)) > original);
  await host.locator('[data-graph-action="fit"]').click();
  const restored = await viewport.evaluate(node => Number(node.dataset.scale));
  assert.ok(Math.abs(restored - original) < .001, 'Fit restores graph scale');
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
    await page.reload({ waitUntil: 'networkidle' });
    await ready(page);
    assert.equal(await page.evaluate(() => navigator.onLine), false);
    assert.match(await page.locator('#networkStatus').textContent(), /离线/);
    assert.deepEqual(await palette(page), reference.palette, label + ': shared online appearance tokens');
    for (const [panel, expected] of Object.entries(reference.icons)) {
      assert.deepEqual(await geometry(page.locator('[data-panel="' + panel + '"] svg')), expected, label + ': shared icon ' + panel);
    }
    const iconStyles = await page.locator('.offline-nav-item[data-panel] svg').evaluateAll(icons => icons.map(icon => {
      const style = getComputedStyle(icon);
      return { viewBox: icon.getAttribute('viewBox'), width: style.width, height: style.height,
        strokeWidth: style.strokeWidth, fill: style.fill };
    }));
    assert.equal(iconStyles.length, 6);
    for (const style of iconStyles) assert.deepEqual(style,
      { viewBox: '0 0 24 24', width: '20px', height: '20px', strokeWidth: '1.8px', fill: 'none' },
      label + ': all navigation icons use the shared Lucide geometry');
    const navStyles = await page.locator('.offline-nav-item[data-panel]').evaluateAll(buttons => buttons.map(button => {
      const style = getComputedStyle(button);
      return { active: button.classList.contains('active'), background: style.backgroundColor,
        backgroundImage: style.backgroundImage, borderWidth: parseFloat(style.borderTopWidth),
        borderColor: style.borderTopColor, borderStyle: style.borderTopStyle, shadow: style.boxShadow };
    }));
    for (const style of navStyles) {
      if (!style.active) assert.equal(style.background, 'rgba(0, 0, 0, 0)', label + ': inactive navigation is frameless');
      assert.equal(style.backgroundImage, 'none');
      assert.ok(style.borderWidth === 0 || style.borderStyle === 'none' || style.borderColor === 'rgba(0, 0, 0, 0)',
        label + ': navigation must not acquire a generic button border');
      assert.equal(style.shadow, 'none');
    }
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
    await page.locator('#noteList .dcn-note-open').filter({ hasText: noteTitle }).click();
    assert.match(await page.locator('#noteList .dcn-original').inputValue(), /修订/);
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
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const width of [1440, 390]) for (const theme of ['light', 'dark', 'navy']) await runCase(browser, width, theme);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
