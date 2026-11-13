/* Start the application first. This suite warms a fresh service worker, then
 * disables networking and exercises the real persisted workspace in Chromium.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const panels = ['graph', 'concepts', 'questions', 'drawing'];
const iconReferences = { drawing: '#graphDrawingBtn svg', graph: '#knowledgeGraphBtn svg' };

async function navigate(page, panel) {
  const graphClose = page.locator('#knowledgeGraphClose');
  if (await graphClose.isVisible()) await graphClose.click();
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
  assert.equal(await page.locator('.offline-nav-item[data-panel="mistakes"],.offline-nav-item[data-panel="notes"],'
    + '#wrongBookBtn,#conceptNotebookBtn,#mistakesPanel,#notesPanel,#wrongBookModal,#conceptNotebookDialog,'
    + '#recordDialog,#recordForm,#recordTitle,#recordContent,#cancelRecord,#addMistake,#addNote,#noteList,#mistakeList').count(), 0,
  'Removed wrong-book and notebook navigation, panels and editors are absent');
  assert.equal(await page.locator('#questionsPanel button').filter({ hasText: '加入错题本' }).count(), 0);
  assert.deepEqual(await page.locator('.offline-nav-item[data-panel]').evaluateAll(items => items.map(item => item.dataset.panel)), panels);
  const entries = await page.evaluate(() => {
    const online = document.getElementById('returnOnline'), appearance = document.getElementById('offlineAppearanceBtn');
    return { order: Boolean(online.compareDocumentPosition(appearance) & Node.DOCUMENT_POSITION_FOLLOWING),
      onlineBottom: online.getBoundingClientRect().bottom, appearanceTop: appearance.getBoundingClientRect().top };
  });
  assert.equal(entries.order, true, 'The online entry precedes appearance in sidebar reading order');
  assert.ok(entries.onlineBottom <= entries.appearanceTop + 1, 'The online button is displayed above appearance');
  await page.locator('#graphPanel').waitFor({ state: 'visible' });
  assert.equal(await page.locator('.offline-nav-item.active').getAttribute('data-panel'), 'graph', 'The first module is the default');
  if (page.viewportSize().width <= 1100) assert.equal(await page.locator('#offlineMobileTitle').innerText(), '知识图谱');
  const schema = await page.evaluate(() => new Promise((resolve, reject) => {
    const request = indexedDB.open('dmate-offline-workspace', 2);
    request.onerror = () => reject(request.error);
    request.onsuccess = () => { const db = request.result; resolve({ version: db.version, stores: [...db.objectStoreNames] }); db.close(); };
  }));
  assert.deepEqual(schema, { version: 2, stores: ['practice', 'settings'] }, 'Fresh databases contain only active data stores');
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
  const drawing = await drawingReference(page);
  return { icons, appearanceIcon: await geometry(page.locator('#appearanceBtn svg')),
    palette: await palette(page), close: await closeStyle(page.locator('#appearanceClose')), drawing };
}

// Compare the real component at equal content sizes: its online modal and the
// offline embedded panel intentionally have different outer dimensions.
async function drawingSnapshot(page, selector) {
  await page.mouse.move(0, 0); // Compare the same resting state, rather than one recently clicked button's hover.
  return page.locator(selector).evaluate(async host => {
    const original = host.getAttribute('style');
    const width = innerWidth < 760 ? 320 : 900;
    host.style.setProperty('width', width + 'px', 'important');
    host.style.setProperty('height', '600px', 'important');
    host.style.setProperty('flex', 'none', 'important');
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await Promise.all(host.getAnimations({ subtree: true }).map(animation => animation.finished.catch(() => {})));
    const origin = host.getBoundingClientRect();
    const selectors = ['.dmate-drawing-workspace', '.ddw-header', '.ddw-name', '.ddw-page-actions',
      ...[1, 2, 3].map(index => '.ddw-page-actions>button:nth-child(' + index + ')'),
      '.ddw-body', '.ddw-editor', '.dge-topline', '[data-editor-undo]', '[data-editor-redo]',
      '.dge-view-controls', '.ddw-canvas-frame', '.dge-overlay-viewport', '.ddw-side-actions',
      '.ddw-side-actions>button:first-child', '.ddw-side-actions>button:nth-child(2)', '.dge-tool-palette>summary'];
    const result = {};
    for (const selector of selectors) {
      const node = host.querySelector(selector);
      if (!node) throw new Error('Missing drawing comparison node: ' + selector);
      const style = getComputedStyle(node), rect = node.getBoundingClientRect();
      result[selector] = { rect: [rect.x - origin.x, rect.y - origin.y, rect.width, rect.height],
        style: Object.fromEntries(['display', 'fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'color',
          'backgroundColor', 'borderTopWidth', 'borderTopStyle', 'borderTopColor', 'borderRadius',
          'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'gap', 'boxShadow'].map(key => [key, style[key]])) };
    }
    if (original === null) host.removeAttribute('style'); else host.setAttribute('style', original);
    return result;
  });
}

async function drawingShellStyle(page, selector) {
  return page.locator(selector).evaluate(node => {
    const capture = element => {
      const style = getComputedStyle(element);
      return Object.fromEntries(['backgroundColor', 'borderTopColor', 'borderTopWidth', 'borderTopStyle',
        'borderRadius', 'fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'color',
        'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft'].map(key => [key, style[key]]));
    };
    return { shell: capture(node), heading: capture(node.querySelector('.graph-editor-dialog-head')),
      title: capture(node.querySelector('.graph-editor-dialog-head>h2')) };
  });
}

async function drawingReference(page) {
  await page.locator(page.viewportSize().width <= 1100 ? '#mobileToolsBtn' : '#desktopToolsBtn').click();
  await page.locator('#graphDrawingBtn').click();
  const dialog = page.locator('#graphEditorDialog');
  await page.waitForFunction(() => document.getElementById('graphEditorDialog').open
    && !document.getElementById('graphEditorDialog').dataset.positioning);
  const workspace = dialog.locator('.dmate-drawing-workspace');
  await workspace.waitFor();
  assert.equal(await workspace.getByRole('button', { name: '上传', exact: true }).count(), 1, 'Online upload remains available');
  await workspace.getByRole('button', { name: 'AI指导', exact: true }).click();
  await workspace.locator('.ddw-ai-requirement').waitFor();
  assert.equal(await workspace.locator('[data-drawing-guide],[data-math-diagram-generate]').count(), 2,
    'Online guidance and mathematical generation remain available');
  await workspace.getByRole('button', { name: 'AI指导', exact: true }).click();
  // Remove only the two intentionally unavailable controls from this reference
  // page, after proving the real online UI provides both capabilities.
  await workspace.evaluate(node => {
    node.querySelector('.ddw-upload-button').remove();
    [...node.querySelectorAll('.ddw-side-actions>button')].find(button => button.textContent === 'AI指导').remove();
  });
  await workspace.getByRole('button', { name: '新建空白页', exact: true }).click();
  const result = { inner: await drawingSnapshot(page, '#graphEditorMount'), outer: await drawingShellStyle(page, '#graphEditorDialog') };
  await dialog.evaluate(node => node.close());
  return result;
}

async function noOverflow(page, panel) {
  const state = await page.evaluate(id => {
    const main = document.querySelector('.offline-main').getBoundingClientRect();
    const node = document.getElementById(id + 'Panel');
    const bounds = node.getBoundingClientRect();
    return { viewport: innerWidth, document: document.documentElement.scrollWidth,
      mainLeft: main.left, mainRight: main.right, panelWidth: node.clientWidth, panelScroll: node.scrollWidth,
      panelTop: bounds.top - main.top, marginTop: parseFloat(getComputedStyle(node).marginTop),
      top: bounds.top, bottom: bounds.bottom, viewportHeight: innerHeight };
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
  const activePanel = await page.locator('.offline-nav-item.active').getAttribute('data-panel');
  const currentPanel = page.locator('#' + activePanel + 'Panel');
  const panelTop = await currentPanel.evaluate(node => node.getBoundingClientRect().top);
  await page.locator('#offlineDesktopSidebarToggle').click();
  await opener.waitFor({ state: 'visible' });
  assert.equal(await opener.getAttribute('aria-expanded'), 'false');
  assert.equal(await page.locator('#offlineSidebar').evaluate(node => node.inert), true);
  const floating = await opener.evaluate(node => ({ inMain: Boolean(node.closest('#offlineMain')), position: getComputedStyle(node).position }));
  assert.ok(floating.inMain && ['absolute', 'fixed'].includes(floating.position), 'Collapsed opener floats in the main area');
  await noOverflow(page, activePanel);
  assert.ok(Math.abs(await currentPanel.evaluate(node => node.getBoundingClientRect().top) - panelTop) <= 2,
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

const displayDifficulty = value => ({ 基础: '简单', 简单: '简单', 中等: '中等', 进阶: '困难', 提高: '困难', 困难: '困难' }[value] || value);

async function questionDifficulties(page, questions) {
  const filter = page.locator('#questionDifficulty');
  assert.deepEqual(await filter.locator('option').evaluateAll(options => options.map(option => [option.value, option.textContent])),
    [['', '全部难度'], ['简单', '简单'], ['中等', '中等'], ['困难', '困难']], 'Difficulty choices use the three requested labels');
  assert.ok(questions.every(question => ['简单', '中等', '困难'].includes(displayDifficulty(question.difficulty))),
    'Every bundled difficulty has a known display/filter mapping');
  for (const difficulty of ['简单', '中等', '困难', '']) {
    await filter.selectOption(difficulty);
    const expected = questions.filter(question => !difficulty || displayDifficulty(question.difficulty) === difficulty);
    assert.deepEqual(await page.locator('#questionList .question-item').evaluateAll(items => items.map(item => item.dataset.questionId)),
      expected.map(question => question.id), 'Difficulty filter includes the exact complete-pack IDs: ' + difficulty);
    assert.equal(await page.locator('#questionCount').textContent(), expected.length + ' 道题目');
    assert.deepEqual(await page.locator('#questionList .question-item small').allTextContents(),
      expected.map(question => question.category + ' · ' + displayDifficulty(question.difficulty) + ' · ' + question.type),
      'Question list uses normalized difficulty labels');
    if (expected.length) {
      const currentId = await page.locator('#questionList .question-item.active').getAttribute('data-question-id');
      const current = expected.find(question => question.id === currentId);
      assert.ok(current, 'The selected question belongs to the filtered result');
      assert.equal(await page.locator('#questionDetail .detail-kicker').textContent(),
        current.category + ' / ' + displayDifficulty(current.difficulty) + ' / ' + current.type);
    }
  }
  // Chapter and difficulty filters must compose, including legacy pack labels.
  const category = questions[0].category;
  await page.locator('#questionCategory').selectOption(category);
  for (const difficulty of ['简单', '中等', '困难']) {
    await filter.selectOption(difficulty);
    const expected = questions.filter(question => question.category === category && displayDifficulty(question.difficulty) === difficulty);
    assert.equal(await page.locator('#questionList .question-item').count(), expected.length);
    assert.equal(await page.locator('#questionCount').textContent(), expected.length + ' 道题目');
  }
  await page.locator('#questionCategory').selectOption('');
  await filter.selectOption('');
}

async function practice(page) {
  await navigate(page, 'questions');
  const questions = await page.evaluate(async () => (await (await fetch('/static/offline-content/questions.zh-CN.json')).json()).questions);
  await questionDifficulties(page, questions);
  assert.deepEqual(await readStore(page, 'practice'), [], 'Browsing starts with a fresh empty practice store');
  // Record complete source values passed to the real rich renderer, without
  // replacing its Markdown, sanitization or MathJax behavior in this test.
  await page.evaluate(() => {
    const original = window.DMateAIAnswer.render;
    window.__testQuestionSources = new WeakMap();
    window.DMateAIAnswer.render = function (target, value, ...args) {
      window.__testQuestionSources.set(target, String(value ?? ''));
      return original.call(this, target, value, ...args);
    };
  });
  const detail = page.locator('#questionDetail');
  const select = async question => {
    await page.locator('#questionList [data-question-id="' + question.id + '"]').click();
    assert.equal(await detail.locator('.detail-title').innerText(), question.title);
    assert.equal(await detail.locator('textarea,input,select,[contenteditable="true"],#questionResponse').count(), 0,
      question.type + ': the question detail has no answer input');
    assert.equal(await detail.getByRole('heading', { name: '你的作答', exact: true }).count(), 0);
    assert.equal(await detail.getByRole('button', { name: /记录本次练习|保存记录|加入错题本/ }).count(), 0);
    assert.deepEqual(await detail.locator('.question-actions button').allTextContents(), ['查看参考答案'],
      'Only the reference-answer action remains');
    assert.equal(await detail.locator('.question-option.selected,[aria-pressed],[aria-checked]').count(), 0,
      question.type + ': there is no choice-selection state');
    const actual = await detail.locator('.question-option').evaluateAll(nodes => nodes.map(node => ({
      key: node.querySelector('.question-option-key').textContent,
      source: window.__testQuestionSources.get(node.querySelector('.question-option-text')),
      rendered: Boolean(node.querySelector('.question-option-text').textContent.trim()),
      interactive: node.matches('button,a,input,[role="button"],[role="radio"],[role="checkbox"]')
        || node.tabIndex >= 0 || Boolean(node.querySelector('button,a,input,select,textarea,[role="radio"],[role="checkbox"]'))
    })));
    assert.deepEqual(actual, (question.options || []).map(option => ({ key: option.key + '.', source: option.text,
      rendered: true, interactive: false })), question.id + ': every option remains complete and read-only');
    if (actual.length) {
      await detail.locator('.question-option').first().click();
      assert.equal(await detail.locator('.question-option.selected,[aria-pressed],[aria-checked]').count(), 0,
        'Clicking a displayed option does not select it');
    }
  };
  const types = ['单项选择', '多项选择', '填空', '计算', '简答', '证明'];
  const representatives = types.map(type => {
    const question = questions.find(item => item.type === type);
    assert.ok(question, 'The complete pack contains ' + type);
    return question;
  });
  for (const question of representatives) {
    await select(question);
    const reveal = detail.getByRole('button', { name: '查看参考答案', exact: true });
    assert.equal(await reveal.locator('svg').count(), 0, 'The reference-answer toggle has no eye icon');
    assert.equal(await detail.locator('.answer-panel').count(), 0);
    await reveal.click();
    const answer = detail.locator('.answer-panel');
    await answer.waitFor();
    assert.match(await answer.textContent(), /参考答案/);
    assert.equal(await answer.locator('.wrong-answer-inner').first().evaluate(node => window.__testQuestionSources.get(node)),
      question.answer_text || (question.answer || []).join('、'), 'The original reference answer remains available');
    assert.equal(await answer.locator('.wrong-analysis-body').evaluate(node => window.__testQuestionSources.get(node)), question.explanation);
    const collapse = detail.getByRole('button', { name: '收起参考答案', exact: true });
    assert.equal(await collapse.locator('svg').count(), 0);
    await collapse.click();
    assert.equal(await detail.locator('.answer-panel').count(), 0, 'The reference answer can be collapsed');
  }
  // All choice questions, rather than just the first example, retain all four
  // option bodies while losing their old selection/save behavior.
  for (const question of questions.filter(item => item.options?.length)) await select(question);
  assert.deepEqual(await readStore(page, 'practice'), [], 'Reading options/answers never creates practice records');
  const legacy = [
    { id: 'legacy-choice', questionId: 'q06', selected: ['B', 'D'], response: '', createdAt: '2025-03-01T00:00:00Z',
      custom: { feedback: '原有记录保留', attempts: [1, 2] } },
    { id: 'legacy-written', questionId: 'archived-question', selected: [], response: '原有证明：α²≤Γ₁',
      createdAt: '2025-03-02T00:00:00Z', custom: { futureField: true } }
  ];
  await page.evaluate(rows => new Promise((resolve, reject) => {
    const request = indexedDB.open('dmate-offline-workspace');
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      const db = request.result, tx = db.transaction('practice', 'readwrite');
      for (const row of rows) tx.objectStore('practice').put(row);
      tx.oncomplete = () => { db.close(); resolve(); };
      tx.onerror = () => { db.close(); reject(tx.error); };
    };
  }), legacy);
  await select(representatives.at(-1));
  await detail.getByRole('button', { name: '查看参考答案', exact: true }).click();
  assert.deepEqual(await readStore(page, 'practice'), legacy, 'Existing practice content and metadata are untouched');
  return legacy;
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
  // Complete-pack difficulty labels, counts and IDs are exercised by practice()
  // for every viewport/theme, independently of the concept-link round trips.
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
  const host = page.locator('#knowledgeGraphModal[data-ready="true"]');
  await host.waitFor();
  const mobile = await page.evaluate(() => matchMedia('(max-width:760px)').matches);
  if (mobile) await host.locator('.kg-mobile-expand').click();
  const nodeSelector = mobile ? '.kg-mobile-node' : 'svg .kg-node-group';
  const edgeSelector = mobile ? '.kg-mobile-edge' : 'svg .kg-edge';
  assert.ok(await host.locator(nodeSelector + '[data-node-id]').count() > 20, 'Graph renders the real course nodes');
  assert.ok(await host.locator(edgeSelector).count() > 20, 'Graph renders actual knowledge relations');
  const label = await host.locator(mobile ? '.kg-mobile-node-name' : '.kg-node-label').first().evaluate(node => {
    const style = getComputedStyle(node), box = node.getBBox ? node.getBBox() : node.getBoundingClientRect();
    return { fill: node.getBBox ? style.fill : style.color, fontSize: parseFloat(style.fontSize), width: box.width, height: box.height,
      visibility: style.visibility, opacity: style.opacity };
  });
  assert.equal(label.fill, 'rgb(248, 250, 252)', 'Labels remain light against the shared dark graph nodes');
  assert.ok(label.fontSize > 0 && label.width > 0 && label.height > 0, 'Graph labels render visible text');
  assert.notEqual(label.visibility, 'hidden');
  assert.notEqual(label.opacity, '0');
  const node = host.locator(nodeSelector + ':not(.selected)').first();
  const nodeId = await node.getAttribute('data-node-id');
  await node.click();
  assert.equal(await host.locator(nodeSelector + '.selected').count(), 1);
  assert.equal(await host.locator(nodeSelector + '.selected').getAttribute('aria-pressed'), 'true');
  assert.equal(await host.locator(nodeSelector + '.selected').getAttribute('data-node-id'), nodeId);
  const viewport = host.locator('.offline-graph-canvas');
  const original = await viewport.evaluate(node => Number(node.dataset.scale));
  await host.locator(mobile ? '.kg-mobile-zoom-btn' : '#knowledgeGraphDesktopZoomIn').last().click();
  assert.ok(await viewport.evaluate(node => Number(node.dataset.scale)) > original);
  await host.locator(mobile ? '.kg-mobile-zoom-fit' : '#knowledgeGraphDesktopZoomFit').click();
  const restored = await viewport.evaluate(node => Number(node.dataset.scale));
  assert.ok(Math.abs(restored - original) < .001, 'Fit restores graph scale');
  if (mobile) await host.locator('.kg-mobile-expand').click();
  await host.locator('.offline-graph-concept-button').click();
  await page.locator('#conceptsPanel').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#conceptList .concept-item.active').getAttribute('data-concept-id'), nodeId,
    'The graph opens the overview for its exact topic ID');
  assert.ok(await page.locator('#conceptDetail .concept-topic-links [data-concept-id]').count() >= 3,
    'Every graph topic leads to its detailed concepts');
}

async function drawing(page, reference) {
  await navigate(page, 'drawing');
  const workspace = page.locator('#offlineDrawingHost .dmate-drawing-workspace');
  await workspace.waitFor();
  assert.equal(await page.locator('#offlineDrawingTitle').innerText(), '绘图');
  assert.deepEqual(await drawingShellStyle(page, '#drawingPanel'), reference.outer,
    'Online/offline drawing shell background, outline, typography, padding and heading match');
  assert.equal(await page.locator('#drawingPanel .offline-intro').count(), 0, 'The old standalone drawing introduction is removed');
  assert.equal(await workspace.getByRole('button', { name: /AI指导|上传|生成数学图/ }).count(), 0);
  assert.equal(await workspace.locator('.ddw-ai-requirement,.ddw-ai-label,.ddw-ai-actions,.ddw-ai-answer,'
    + '[data-drawing-guide],[data-math-diagram-generate],.ddw-upload-button,input[type="file"]').count(), 0,
  'Unavailable AI/upload functionality has no controls or request form in the offline DOM');
  const frame = await page.locator('#offlineDrawingHost').evaluate(node => {
    const style = getComputedStyle(node);
    return { parent: node.parentElement.id, border: parseFloat(style.borderTopWidth),
      padding: ['paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft'].map(key => parseFloat(style[key])),
      canvasHeight: node.querySelector('.dge-overlay-viewport').clientHeight };
  });
  assert.equal(frame.parent, 'drawingPanel', 'The shared component mounts directly beneath the drawing header');
  assert.equal(frame.border, 0, 'No extra inner card surrounds the shared drawing component');
  assert.deepEqual(frame.padding, [0, 0, 0, 0]);
  assert.ok(frame.canvasHeight > 200, 'The native embedded layout provides a usable canvas: ' + JSON.stringify(frame));
  await workspace.getByRole('button', { name: '新建空白页', exact: true }).click();
  const actual = await drawingSnapshot(page, '#offlineDrawingHost');
  for (const [selector, expected] of Object.entries(reference.inner)) {
    assert.deepEqual(actual[selector].style, expected.style, 'Online/offline drawing styles: ' + selector);
    actual[selector].rect.forEach((value, index) => assert.ok(Math.abs(value - expected.rect[index]) <= 1.5,
      'Online/offline drawing relative geometry: ' + selector + ': ' + JSON.stringify({ actual: actual[selector].rect, expected: expected.rect })));
  }
  await workspace.locator('.ddw-name').fill('离线保存画板');
  const tool = async mode => {
    const summary = workspace.locator('.dge-tool-palette>summary');
    if (await summary.getAttribute('aria-expanded') !== 'true') await summary.click();
    await workspace.locator('[data-overlay-tool="' + mode + '"]').click();
    await summary.click();
  };
  const tap = async point => {
    if (page.viewportSize().width < 760) await page.touchscreen.tap(point.x, point.y);
    else await page.mouse.click(point.x, point.y);
  };
  await tool('vertex');
  const canvas = await workspace.locator('.dge-overlay-viewport').boundingBox();
  for (const [x, y] of [[.35, .55], [.7, .72]]) await tap({ x: canvas.x + canvas.width * x, y: canvas.y + canvas.height * y });
  assert.equal(await workspace.locator('.dge-overlay-node').count(), 2, 'Real canvas gestures add vertices');
  await tool('edge');
  for (const index of [0, 1]) {
    const point = await workspace.locator('.dge-overlay-node .dge-overlay-dot').nth(index).evaluate(node => {
      const r = node.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
    });
    await tap(point);
  }
  assert.equal(await workspace.locator('.dge-overlay-edge').count(), 1, 'Real canvas gestures connect vertices');
  await workspace.locator('[data-editor-undo]').click();
  assert.equal(await workspace.locator('.dge-overlay-edge').count(), 0);
  await workspace.locator('[data-editor-redo]').click();
  assert.equal(await workspace.locator('.dge-overlay-edge').count(), 1);
  await workspace.getByRole('button', { name: '清空', exact: true }).click();
  assert.equal(await workspace.locator('.dge-overlay-node').count(), 0);
  await workspace.locator('[data-editor-undo]').click();
  assert.equal(await workspace.locator('.dge-overlay-node').count(), 2, 'Clear can be undone without losing the drawing');
  await workspace.locator('[data-overlay-tool="zoom-in"]').click();
  const zoomed = await workspace.locator('.dge-overlay-zoom').innerText();
  await workspace.locator('[data-overlay-tool="zoom-fit"]').click();
  assert.notEqual(await workspace.locator('.dge-overlay-zoom').innerText(), zoomed, 'Fit recalculates the view after zoom');
  const downloading = page.waitForEvent('download');
  await workspace.getByRole('button', { name: '导出图片', exact: true }).click();
  if (page.viewportSize().width < 760) {
    await workspace.locator('.ddw-export-preview').waitFor();
    await page.waitForFunction(() => document.querySelector('.ddw-export-image')?.naturalWidth > 64);
    await workspace.locator('.ddw-export-download').click();
  }
  const download = await downloading;
  const stream = await download.createReadStream(), chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
  const png = Buffer.concat(chunks);
  assert.deepEqual([...png.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  assert.ok(png.readUInt32BE(16) > 64 && png.readUInt32BE(20) > 64, 'Offline PNG export renders a usable image');
  if (page.viewportSize().width < 760) await workspace.locator('.ddw-export-close').click();
  const history = workspace.getByRole('button', { name: '历史绘图', exact: true });
  const historyNames = async () => {
    if (await history.getAttribute('aria-expanded') !== 'true') await history.click();
    return workspace.locator('.ddw-history-open').allTextContents();
  };
  assert.deepEqual(await historyNames(), ['离线保存画板']);
  await history.click();
  await workspace.getByRole('button', { name: '新建空白页', exact: true }).click();
  await workspace.locator('.ddw-name').fill('待删除画板');
  assert.deepEqual(await historyNames(), ['离线保存画板', '待删除画板']);
  await workspace.locator('.ddw-history-open').getByText('离线保存画板', { exact: true }).click();
  assert.equal(await workspace.locator('.dge-overlay-node').count(), 2);
  assert.deepEqual(await historyNames(), ['离线保存画板', '待删除画板'], 'Selecting history does not change creation order');
  await workspace.locator('.ddw-history-item').filter({ hasText: '待删除画板' })
    .locator('.ddw-history-delete').click();
  await page.locator('.dmate-delete-confirm-delete').click();
  await page.waitForFunction(() => document.querySelectorAll('.ddw-history-open').length === 1);
  assert.deepEqual(await historyNames(), ['离线保存画板']);
  await history.click();
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
      if (!['http:', 'https:'].includes(url.protocol)) return; // local Blob URLs do not call a server
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
    assert.equal(iconStyles.length, panels.length);
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
    const preservedPractice = await practice(page);
    await concepts(page);
    if (theme === 'dark') await curriculum(page);
    await graph(page);
    await drawing(page, reference.drawing);
    // A second fully offline navigation preserves old records and the drawing.
    await page.reload({ waitUntil: 'networkidle' });
    await ready(page);
    assert.equal(await page.evaluate(() => document.documentElement.dataset.appearanceTheme), theme, 'Offline appearance persists');
    assert.deepEqual(await readStore(page, 'practice'), preservedPractice,
      'Offline reload preserves existing records without creating or rewriting practice data');
    await navigate(page, 'drawing');
    assert.equal(await page.locator('#offlineDrawingHost .ddw-name').inputValue(), '离线保存画板');
    assert.equal(await page.locator('#offlineDrawingHost .dge-overlay-node').count(), 2, 'Edited vertices survive offline refresh');
    assert.equal(await page.locator('#offlineDrawingHost .dge-overlay-edge').count(), 1, 'Edited edges survive offline refresh');
    for (const panel of panels) {
      await navigate(page, panel);
      await noOverflow(page, panel);
      if (process.env.OFFLINE_SCREENSHOT_DIR) {
        await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/' + width + '-' + theme + '-' + panel + '.png' });
      }
    }
    assert.deepEqual(nativeDialogs, [], label + ': actions do not open native browser dialogs');
    assert.deepEqual(apiRequests, [], label + ': offline work must not call server APIs');
    assert.deepEqual(failures, [], label + ': required resources must be cached');
    assert.deepEqual(errors, [], label + ': no page errors');
    console.log('PASS ' + label + ': four panels, shared appearance/icons, read-only questions, normalized difficulty, preserved legacy records, curriculum, graph, drawing and offline reload');
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
    const themes = (process.env.DMATE_TEST_THEMES || 'light,dark,navy').split(',');
    assert.ok(themes.length && themes.every(theme => ['light', 'dark', 'navy'].includes(theme)), 'Supported theme selection');
    for (const width of [1440, 390]) for (const theme of themes) await runCase(browser, width, theme);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
