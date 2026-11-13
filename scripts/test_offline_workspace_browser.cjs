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
  const title = (await item.innerText()).trim();
  await item.click();
  await page.locator('#' + panel + 'Panel').waitFor({ state: 'visible' });
  if (page.viewportSize().width <= 1100) {
    await page.waitForFunction(expected => document.getElementById('offlineMobileTitle').textContent.trim() === expected, title);
  }
}

async function ready(page) {
  await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
  assert.equal(await page.locator('.offline-header,#networkStatus,#saveState').count(), 0,
    'The removed header, save-state label, and network status are absent from the DOM');
  assert.equal(await page.locator('#exportLocalData').count(), 0, 'The local-data export entry is removed');
  assert.equal(await page.locator('#offlineSidebar button').filter({ hasText: /^导出本地数据$/ }).count(), 0);
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

async function onlineOfflineEntry(page) {
  const mobile = page.viewportSize().width <= 1100;
  if (mobile) await page.locator('#mobileNavBtn').click();
  else if (await page.locator('html').getAttribute('data-desktop-sidebar') === 'collapsed') {
    await page.locator('#desktopSidebarOpen').click();
  }
  await page.locator('#offlineWorkspaceBtn').waitFor({ state: 'visible' });
  const entry = await page.evaluate(() => {
    const account = document.getElementById('accountBtn');
    const offline = document.getElementById('offlineWorkspaceBtn');
    const appearance = document.getElementById('appearanceBtn');
    const style = node => {
      const computed = getComputedStyle(node);
      return Object.fromEntries(['backgroundColor', 'borderTopWidth', 'borderTopStyle',
        'borderTopColor', 'borderRadius', 'boxShadow', 'fontSize', 'fontWeight', 'color']
        .map(key => [key, computed[key]]));
    };
    const icon = offline.querySelector('svg').getBoundingClientRect();
    const text = offline.querySelector('span').getBoundingClientRect();
    return { followsAccount: Boolean(account.compareDocumentPosition(offline) & Node.DOCUMENT_POSITION_FOLLOWING),
      precedesAppearance: Boolean(offline.compareDocumentPosition(appearance) & Node.DOCUMENT_POSITION_FOLLOWING),
      offline: style(offline), appearance: style(appearance), iconRight: icon.right, textLeft: text.left,
      centerDifference: Math.abs(icon.y + icon.height / 2 - text.y - text.height / 2) };
  });
  assert.ok(entry.followsAccount && entry.precedesAppearance, 'Offline entry sits below account and above appearance');
  assert.deepEqual(entry.offline, entry.appearance, 'Offline entry uses the neighboring sidebar button style');
  assert.equal(entry.offline.backgroundColor, 'rgba(0, 0, 0, 0)', 'Offline entry has no card background');
  assert.equal(entry.offline.boxShadow, 'none');
  assert.ok(entry.iconRight < entry.textLeft && entry.centerDifference <= 1, 'Offline entry icon and text share one centered row');
  await page.locator(mobile ? '#mobileNavClose' : '#desktopSidebarToggle').click();
}

async function onlineReference(page, theme) {
  await page.goto(baseURL + '/', { waitUntil: 'networkidle' });
  await page.evaluate(value => {
    document.documentElement.dataset.appearanceTheme = value;
    document.body.dataset.appearanceTheme = value;
  }, theme);
  await onlineOfflineEntry(page);
  const icons = {};
  for (const [panel, selector] of Object.entries(iconReferences)) icons[panel] = await geometry(page.locator(selector));
  return { icons, appearanceIcon: await geometry(page.locator('#appearanceBtn svg')),
    palette: await palette(page), close: await closeStyle(page.locator('#wrongBookClose')) };
}

async function noOverflow(page, panel) {
  const state = await page.evaluate(id => {
    const main = document.querySelector('.offline-main').getBoundingClientRect();
    const node = document.getElementById(id + 'Panel');
    return { viewport: innerWidth, document: document.documentElement.scrollWidth,
      mainLeft: main.left, mainRight: main.right, panelWidth: node.clientWidth, panelScroll: node.scrollWidth,
      panelTop: node.getBoundingClientRect().top - main.top, marginTop: parseFloat(getComputedStyle(node).marginTop) };
  }, panel);
  assert.ok(state.document <= state.viewport + 1, panel + ': page overflows horizontally: ' + JSON.stringify(state));
  assert.ok(state.mainLeft >= -1 && state.mainRight <= state.viewport + 1, panel + ': workspace outside viewport');
  assert.ok(state.panelScroll <= state.panelWidth + 1, panel + ': panel overflows outside its own controls');
  assert.ok(Math.abs(state.panelTop - state.marginTop) <= 2, panel + ': no empty header row precedes the content: ' + JSON.stringify(state));
}

async function sidebarControls(page, width) {
  const opener = page.locator('#offlineDesktopSidebarOpen');
  if (width <= 1100) {
    assert.equal(await opener.isVisible(), false, 'Desktop floating opener stays hidden on mobile');
    return;
  }
  if (await opener.getAttribute('aria-expanded') !== 'true') await opener.click();
  assert.equal(await opener.isVisible(), false, 'Expanded sidebar has no floating opener');
  const panelTop = await page.locator('#mistakesPanel').evaluate(node => node.getBoundingClientRect().top);
  await page.locator('#offlineDesktopSidebarToggle').click();
  await opener.waitFor({ state: 'visible' });
  assert.equal(await opener.getAttribute('aria-expanded'), 'false');
  assert.equal(await page.locator('#offlineSidebar').evaluate(node => node.inert), true);
  const floating = await opener.evaluate(node => ({ inMain: Boolean(node.closest('#offlineMain')), position: getComputedStyle(node).position }));
  assert.ok(floating.inMain && ['absolute', 'fixed'].includes(floating.position), 'Collapsed opener floats in the main area');
  await noOverflow(page, 'mistakes');
  assert.ok(Math.abs(await page.locator('#mistakesPanel').evaluate(node => node.getBoundingClientRect().top) - panelTop) <= 2,
    'Collapsing navigation does not add a top content row');
  await opener.click();
  await opener.waitFor({ state: 'hidden' });
  assert.equal(await page.locator('#offlineSidebar').evaluate(node => node.inert), false);
}

async function appearanceControls(page, width, theme, reference) {
  for (const selector of ['#offlineAppearanceBtn svg', '#offlineAppearanceToggle svg']) {
    assert.deepEqual(await geometry(page.locator(selector)), reference.appearanceIcon, 'Appearance entry shares the online icon: ' + selector);
  }
  await page.locator(width <= 1100 ? '#offlineAppearanceToggle' : '#offlineAppearanceBtn').click();
  const dialog = page.locator('#appearanceModal');
  await dialog.waitFor();
  assert.equal(await dialog.locator('[data-appearance-mode]').count(), 4, 'All four theme choices are available');
  assert.equal(await dialog.locator('[data-appearance-accent]').count(), 3, 'All accent choices are available');
  assert.equal(await dialog.locator('[data-appearance-font]').count(), 3, 'All font sizes are available');
  assert.equal(await dialog.locator('[data-appearance-fit]').count(), 2, 'Both wallpaper fit modes are available');
  for (const id of ['appearanceMaskRange', 'appearanceBlurRange', 'appearancePanelRange', 'appearanceBubbleRange']) {
    await dialog.locator('#' + id).waitFor({ state: 'visible' });
  }
  const alternate = theme === 'dark' ? 'light' : 'dark';
  await dialog.locator('[data-appearance-mode="' + alternate + '"]').click();
  await page.waitForFunction(value => document.documentElement.dataset.appearanceTheme === value, alternate);
  await page.locator('#appearanceClose').click();
  await page.waitForFunction(value => document.documentElement.dataset.appearanceTheme === value, theme);
  await page.locator(width <= 1100 ? '#offlineAppearanceToggle' : '#offlineAppearanceBtn').click();
  await dialog.locator('[data-appearance-mode="' + theme + '"]').click();
  await page.waitForFunction(value => document.documentElement.dataset.appearanceTheme === value, theme);
  assert.deepEqual(await closeStyle(page.locator('#appearanceClose')), reference.close, 'Appearance uses the shared close dot');
  await page.locator('#appearanceDone').click();
  await dialog.waitFor({ state: 'hidden' });
}

async function confirmDeletion(page, trigger, commit) {
  await trigger.click();
  const dialog = page.locator('.dmate-delete-confirm[open]');
  await dialog.waitFor({ state: 'visible' });
  await dialog.locator(commit ? '.dmate-delete-confirm-delete' : '.dmate-delete-confirm-close').click();
  await dialog.waitFor({ state: 'detached' });
}

async function notebookSnapshot(page, selector) {
  await page.mouse.move(0, 0);
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.locator(selector).evaluate(async node => {
    await Promise.all(node.getAnimations({ subtree: true }).map(animation => animation.finished.catch(() => {})));
  });
  return page.locator(selector).evaluate(content => {
    const origin = content.getBoundingClientRect();
    const selectors = [':scope', '.dcn-sidebar', '.dcn-sidebar > .dcn-primary', '.dcn-search-wrap', '.dcn-search',
      '.dcn-search-clear', '.dcn-selection', '.dcn-list', '.dcn-list-empty', '.dcn-note', '.dcn-note-select',
      '.dcn-note input[type=checkbox]', '.dcn-note-open', '.dcn-note-delete', '.dcn-main', '.dcn-editor',
      '.dcn-editor > label:first-child', '.dcn-title', '.dcn-editor > label:nth-child(2)', '.dcn-original',
      '.dcn-saved'];
    const properties = ['display', 'boxSizing', 'position', 'gridTemplateColumns', 'gridTemplateRows',
      'flexDirection', 'flexWrap', 'alignItems', 'justifyContent', 'gap', 'rowGap', 'columnGap',
      'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'marginTop', 'marginRight', 'marginBottom', 'marginLeft',
      'fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'textAlign', 'whiteSpace', 'color', 'backgroundColor',
      'borderTopWidth', 'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth', 'borderTopStyle',
      'borderTopColor', 'borderRadius', 'boxShadow', 'minHeight', 'appearance', 'opacity'];
    const elements = {};
    for (const key of selectors) {
      const node = key === ':scope' ? content : content.querySelector(key);
      const rect = node?.getBoundingClientRect(), style = node && getComputedStyle(node);
      const visible = Boolean(node && node.getClientRects().length && rect.width > 0 && rect.height > 0
        && style.display !== 'none' && style.visibility !== 'hidden');
      if (!visible) { elements[key] = { visible: false }; continue; }
      elements[key] = { visible: true, geometry: { x: rect.x - origin.x, y: rect.y - origin.y, width: rect.width, height: rect.height },
        style: Object.fromEntries(properties.map(property => [property, style[property]])) };
      if (node.matches('input,textarea')) elements[key].value = node.value;
      if (node.matches('input[type=checkbox]')) elements[key].checked = node.checked;
    }
    // Keep the real online AI area intact, excluding only its text from this
    // editor/list comparison. Its parent geometry is still measured above.
    const text = [], walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const parent = node.parentElement;
      if (parent.closest('.dcn-ai') || !parent.getClientRects().length) continue;
      const style = getComputedStyle(parent);
      if (style.display !== 'none' && style.visibility !== 'hidden') text.push(node.textContent);
    }
    return { text: text.join(' ').replace(/\s+/g, ' ').trim(), elements };
  });
}

async function compareNotebook(page, online, label, phase) {
  assert.equal(await page.locator('#notesPanel .dcn-ai,#notesPanel .dcn-question,#notesPanel .dcn-ai-actions').count(), 0,
    label + '/' + phase + ': the complete offline AI section is absent from the DOM');
  const size = await page.locator('#noteList').evaluate(node => {
    const rect = node.getBoundingClientRect(), panel = node.parentElement, box = panel.getBoundingClientRect(), style = getComputedStyle(panel);
    return { width: rect.width, height: rect.height, gaps: [
      rect.left - box.left - parseFloat(style.borderLeftWidth) - parseFloat(style.paddingLeft),
      box.right - rect.right - parseFloat(style.borderRightWidth) - parseFloat(style.paddingRight),
      rect.top - box.top - parseFloat(style.borderTopWidth) - parseFloat(style.paddingTop),
      box.bottom - rect.bottom - parseFloat(style.borderBottomWidth) - parseFloat(style.paddingBottom)] };
  });
  assert.ok(size.gaps.every(gap => Math.abs(gap) <= 2), label + '/' + phase + ': notebook content fills its embedded container: ' + JSON.stringify(size));
  // Match the content container, keeping the online component's actual CSS and
  // viewport breakpoints. Modal framing and embedded page placement differ.
  await online.evaluate(({ width, height }) => {
    const dialog = document.getElementById('conceptNotebookDialog'), content = dialog.querySelector('.dcn-content');
    const style = getComputedStyle(dialog), heading = dialog.querySelector('.dcn-heading').getBoundingClientRect();
    const horizontal = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight)
      + parseFloat(style.borderLeftWidth) + parseFloat(style.borderRightWidth);
    const vertical = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom)
      + parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth) + heading.height + parseFloat(style.rowGap);
    Object.assign(dialog.style, { width: width + horizontal + 'px', height: height + vertical + 'px',
      maxWidth: 'none', maxHeight: 'none', minHeight: '0' });
    Object.assign(content.style, { width: width + 'px', height: height + 'px', flex: 'none' });
  }, size);
  const expected = await notebookSnapshot(online, '#conceptNotebookDialog .dcn-content');
  const actual = await notebookSnapshot(page, '#noteList');
  assert.equal(actual.text, expected.text, label + '/' + phase + ': notebook text and visible structure match online');
  for (const [selector, reference] of Object.entries(expected.elements)) {
    const current = actual.elements[selector], message = label + '/' + phase + ': ' + selector;
    assert.equal(current.visible, reference.visible, message + ' visibility');
    if (!reference.visible) continue;
    assert.deepEqual(current.style, reference.style, message + ' computed style');
    assert.equal(current.value, reference.value, message + ' value');
    assert.equal(current.checked, reference.checked, message + ' checkbox');
    for (const key of ['x', 'y', 'width', 'height']) {
      assert.ok(Math.abs(current.geometry[key] - reference.geometry[key]) <= 2,
        message + ' ' + key + ': offline=' + current.geometry[key] + ', online=' + reference.geometry[key]);
    }
  }
  if (process.env.OFFLINE_SCREENSHOT_DIR) {
    const suffix = label.replace('/', '-') + '-' + phase + '.png';
    await online.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/notebook-online-' + suffix });
    await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/notebook-offline-' + suffix });
  }
}

async function notebookParity(browser, page, width, theme, label) {
  await navigate(page, 'notes');
  await page.locator('#addNote').waitFor();
  assert.equal(await page.locator('#notesPanel > .offline-toolbar,#notesPanel > .dcn-heading,#noteCount').count(), 0,
    'The embedded notebook has no replacement heading or toolbar');
  assert.deepEqual(await readStore(page, 'notes'), [], 'Notebook comparison begins with the real empty state');
  const context = await browser.newContext({ viewport: page.viewportSize(), isMobile: width < 1101,
    hasTouch: width < 1101, serviceWorkers: 'block' });
  const online = await context.newPage(), errors = [];
  online.on('pageerror', error => errors.push(error.message));
  try {
    await online.goto(baseURL + '/', { waitUntil: 'networkidle' });
    await online.evaluate(mode => { appearanceSettings = { ...APPEARANCE_DEFAULTS, mode }; applyAppearanceSettings({ save: false }); }, theme);
    const toggle = online.locator(width <= 1100 ? '#mobileToolsBtn' : '#desktopToolsBtn');
    if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
    await online.locator('#conceptNotebookBtn').click();
    await online.locator('#conceptNotebookDialog[open]').waitFor();
    await compareNotebook(page, online, label, 'empty');
    await page.locator('#addNote').click();
    await page.waitForFunction(() => Boolean(document.querySelector('#noteList .dcn-note.is-current')));
    await online.locator('#conceptNotebookDialog .dcn-sidebar > .dcn-primary').click();
    await compareNotebook(page, online, label, 'new');
    const title = '笔记布局示例', content = '集合与关系：先说明对象，再核对定义中的全部条件。';
    await page.locator('#noteList .dcn-title').fill(title);
    await online.locator('#conceptNotebookDialog .dcn-title').fill(title);
    await page.locator('#noteList .dcn-original').fill(content);
    await online.locator('#conceptNotebookDialog .dcn-original').fill(content);
    await waitRecord(page, 'notes', title, content);
    await page.locator('#noteList .dcn-note input[type=checkbox]').check();
    await online.locator('#conceptNotebookDialog .dcn-note input[type=checkbox]').check();
    assert.equal(await online.locator('#conceptNotebookDialog .dcn-ai-actions > button').first().isEnabled(), true);
    await compareNotebook(page, online, label, 'populated');
    const row = (await readStore(page, 'notes')).find(note => note.title === title);
    const fixture = page.locator('#noteList .dcn-note[data-note-id="' + row.id + '"]');
    await confirmDeletion(page, fixture.locator('.dcn-note-delete'), true);
    await fixture.waitFor({ state: 'detached' });
    assert.deepEqual(await readStore(page, 'notes'), [], 'Parity fixture is removed before CRUD regression');
    assert.deepEqual(errors, [], label + ': online notebook reference has no page errors');
  } finally { await context.close(); }
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

async function curriculum(page) {
  const [concepts, questions, graph, references] = await page.evaluate(async () => {
    const packs = await Promise.all(['concepts.zh-CN.json', 'questions.zh-CN.json',
      'knowledge_graph.json', 'references.zh-CN.json'].map(async name => {
      const response = await fetch('/static/offline-content/' + name);
      if (!response.ok) throw new Error('Offline pack unavailable: ' + name);
      return response.json();
    }));
    return [packs[0].concepts, packs[1].questions, packs[2].nodes, packs[3].sources];
  });
  assert.equal(await page.locator('#conceptList .concept-item').count(), concepts.length);
  assert.ok(concepts.length >= graph.length * 4, 'Topics contain substantive detailed concepts');
  assert.ok(questions.length >= graph.length * 8, 'Every broad topic has multiple exercises');
  assert.ok(references.length >= 3 && references.every(source => source.commercial_use_permitted),
    'The commercial-use reference registry is readable without a network');
  await navigate(page, 'questions');
  for (const difficulty of [...new Set(questions.map(question => question.difficulty))]) {
    await page.locator('#questionDifficulty').selectOption(difficulty);
    assert.equal(await page.locator('#questionList .question-item').count(),
      questions.filter(question => question.difficulty === difficulty).length, 'Difficulty filter: ' + difficulty);
  }
  await page.locator('#questionDifficulty').selectOption('');
  const categories = new Set();
  for (const topic of graph) {
    if (categories.has(topic.category)) continue;
    categories.add(topic.category);
    await navigate(page, 'concepts');
    await page.locator('#conceptList [data-concept-id="' + topic.id + '"]').click();
    const overview = concepts.find(item => item.id === topic.id);
    assert.equal(await page.locator('#conceptDetail .concept-topic-links [data-concept-id]').count(),
      overview.related_concepts.length);
    const child = concepts.find(item => item.id === overview.related_concepts[0]);
    await page.locator('#conceptDetail .concept-topic-links [data-concept-id="' + child.id + '"]').click();
    assert.equal(await page.locator('#conceptDetail .detail-title').innerText(), child.title);
    await page.locator('#conceptDetail [data-question-id="' + child.related_questions[0] + '"]').click();
    await page.locator('#questionsPanel').waitFor({ state: 'visible' });
    const question = questions.find(item => item.id === child.related_questions[0]);
    assert.equal(await page.locator('#questionDetail .detail-title').innerText(), question.title);
    await page.locator('#questionDetail').getByRole('button', {name:'查看参考答案', exact:true}).click();
    assert.ok((await page.locator('#questionDetail .answer-panel').innerText()).includes('评分要点'));
    await page.locator('#questionDetail .question-concept-links [data-concept-id="' + child.id + '"]').click();
    await page.locator('#conceptsPanel').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#conceptDetail .detail-title').innerText(), child.title);
    await page.locator('#conceptDetail .concept-topic-links [data-concept-id="' + topic.id + '"]').click();
    assert.equal(await page.locator('#conceptDetail .detail-title').innerText(), topic.name);
  }
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
  await host.locator('.offline-graph-concept-button').click();
  await page.locator('#conceptsPanel').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#conceptList .concept-item.active').getAttribute('data-concept-id'), nodeId,
    'The graph opens the overview for its exact topic ID');
  assert.ok(await page.locator('#conceptDetail .concept-topic-links [data-concept-id]').count() >= 3,
    'Every graph topic leads to its detailed concepts');
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
      const url = new URL(request.url());
      if (!['http:', 'https:'].includes(url.protocol)) return; // local Blob backup downloads do not call a server
      const path = url.pathname;
      if (!path.startsWith('/static/') && !['/offline', '/offline-service-worker.js', '/favicon.ico'].includes(path)) apiRequests.push(path);
    });
    page.on('dialog', async dialog => { nativeDialogs.push(dialog.type()); await dialog.dismiss(); });
    await context.setOffline(true);
    workerProtocol = await disconnectWorkerNetwork(browser, page, await page.evaluate(() => navigator.serviceWorker.controller.scriptURL));
    await page.reload({ waitUntil: 'networkidle' });
    await ready(page);
    assert.equal(await page.evaluate(() => navigator.onLine), false);
    await sidebarControls(page, width);
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
    await notebookParity(browser, page, width, theme, label);
    const noteTitle = await notesCRUD(page, label);
    const mistakeTitle = await mistakesCRUD(page, label, reference);
    await practice(page);
    await concepts(page);
    if (theme === 'dark') await curriculum(page);
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
  } finally {
    await context.close();
    if (workerProtocol) await workerProtocol.detach().catch(() => {});
  }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const width of [1440, 390]) for (const theme of ['light', 'dark', 'navy']) await runCase(browser, width, theme);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
