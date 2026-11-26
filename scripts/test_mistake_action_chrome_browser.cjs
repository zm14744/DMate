/* Local UI regressions: seeded learning records, actual PNG downloads, and no
 * model requests. A narrow desktop viewport also exercises the mobile layout.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const { expandGraphDetails } = require('./knowledge-graph-touch-fixtures.cjs');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const question = '设整数 n 为奇数，证明 n 的平方也是奇数。';
const settle = page => page.evaluate(async () => {
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  await Promise.all(document.getAnimations().filter(animation =>
    animation.effect?.getComputedTiming().iterations !== Infinity)
    .map(animation => animation.finished.catch(() => {})));
});

function installClipboardProbe() {
  const probe = window.actionChromeProbe = { text: [], images: 0, items: 0 };
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: {
    writeText: async text => { probe.text.push(text); },
    write: async () => { probe.images++; throw new Error('An image export must not write the clipboard'); }
  } });
  window.ClipboardItem = class { constructor() { probe.items++; } };
}

async function toolsEntry(page, id) {
  const mobile = page.viewportSize().width <= 1100;
  const kind = mobile ? 'mobile-tools-open' : 'desktop-tools-open';
  if (!await page.evaluate(kind => document.body.classList.contains(kind), kind)) {
    await page.locator(mobile ? '#mobileToolsBtn' : '#desktopToolsBtn').click();
  }
  await page.locator('#' + id).click();
  await settle(page);
}

const fontStyle = locator => locator.evaluate(node => {
  const css = getComputedStyle(node);
  return { size: css.fontSize, weight: css.fontWeight, color: css.color };
});
const controlStyle = locator => locator.evaluate(node => {
  const css = getComputedStyle(node), arrow = getComputedStyle(node, '::after');
  const keys = ['backgroundColor', 'borderTopWidth', 'borderTopStyle', 'borderTopColor',
    'borderRadius', 'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'minHeight', 'height', 'lineHeight', 'fontSize', 'color'];
  return { ...Object.fromEntries(keys.map(key => [key, css[key]])),
    renderedHeight: node.getBoundingClientRect().height,
    arrow: [arrow.width, arrow.height, arrow.borderRightWidth, arrow.borderBottomWidth, arrow.transform] };
});
const buttonPaint = locator => locator.evaluate(node => {
  const css = getComputedStyle(node);
  return { background: css.backgroundColor, image: css.backgroundImage,
    border: [css.borderTopWidth, css.borderRightWidth, css.borderBottomWidth, css.borderLeftWidth],
    shadow: css.boxShadow, outline: css.outlineStyle + ' ' + css.outlineWidth, color: css.color };
});

async function graphReference(page) {
  await toolsEntry(page, 'knowledgeGraphBtn');
  await page.waitForFunction(() => knowledgeGraphInitialized && Boolean(knowledgeGraphData));
  await page.evaluate(() => selectKnowledgeGraphDisplayMode('full'));
  if (page.viewportSize().width <= 760) {
    await page.locator('#knowledgeGraphModal .kg-mobile-node[data-knowledge-node-id="logic_truth"]').click();
    await expandGraphDetails(page);
  } else await page.evaluate(() => selectKnowledgeGraphNode('logic_truth'));
  await page.locator('.graph-detail-field-label').first().waitFor();
  const heading = await fontStyle(page.locator('.graph-detail-field-label').first());
  assert.equal(heading.size, '14px'); assert.equal(heading.weight, '600');
  const module = page.viewportSize().width <= 1100
    ? await controlStyle(page.locator('#knowledgeGraphCategoryTrigger')) : null;
  await page.evaluate(() => closeKnowledgeGraph());
  await settle(page);
  return { heading, module };
}

async function seedWrongBook(page) {
  await page.evaluate(question => {
    learningState = normalizeLearningState({ version: 9, events: [], wrongQuestions: [{
      id: 'chrome-regression-wrong', question, category: '证明与归纳', relatedCategories: [],
      knowledgePoints: ['直接证明与反证法'], focusPoints: [], difficulty: '简单', classificationVersion: 3,
      referenceAnswer: '奇数的平方仍为奇数。', answer: '设 n=2k+1，则 n²=2(2k²+2k)+1。',
      analysis: '', note: '使用奇数的定义。', corrected: false, retestPassed: true,
      retestRecords: [{ id: 'legacy-retest', question, answer: '通过', createdAt: 1 }],
      createdAt: 1, updatedAt: 2
    }], conceptNotebook: { notes: [
      { id: 'chrome-concept', title: '奇数', content: '形如 2k+1 的整数。', updatedAt: 1 },
      { id: 'chrome-even', title: '偶数', content: '形如 2k 的整数。', updatedAt: 2 }
    ], deleted: {} } });
    wrongBookFilter = 'pending'; wrongBookSearch = ''; wrongBookSort = 'recent';
  }, question);
}

async function checkHeadingLabels(page, reference) {
  await page.evaluate(question => openWrongSafePreview({ text: question }), question);
  await page.locator('#wrongSafeModal').waitFor({ state: 'visible' });
  for (const selector of ['#wrongSafePreviewLabel', '#wrongSafeModal label[for="wrongSafeQuestion"]']) {
    assert.deepEqual(await fontStyle(page.locator(selector)), reference, selector + ' matches the graph heading');
  }
  await page.evaluate(() => closeWrongSafePreview());
  await page.evaluate(() => openWrongEdit('chrome-regression-wrong'));
  for (const selector of ['#wrongEditModal label[for="wrongEditQuestion"]', '#wrongEditModal label[for="wrongEditNote"]']) {
    assert.deepEqual(await fontStyle(page.locator(selector)), reference, selector + ' matches the graph heading');
  }
  await page.evaluate(() => { closeWrongEdit(); closeWrongBook(); });
  await toolsEntry(page, 'conceptNotebookBtn');
  await page.locator('#conceptNotebookDialog').waitFor({ state: 'visible' });
  const notebook = page.locator('#conceptNotebookDialog');
  for (const checkbox of await notebook.getByRole('checkbox').all()) await checkbox.check();
  await notebook.locator('.dcn-relation-trigger').click();
  await notebook.getByRole('dialog', { name: '分析关联' }).waitFor();
  for (const selector of ['.dcn-title', '.dcn-original']) {
    assert.deepEqual(await fontStyle(page.locator('#conceptNotebookDialog ' + selector).locator('..')), reference,
      selector + ' label matches the graph heading');
  }
  const requirements = notebook.getByRole('textbox', { name: '分析要求（可选）' });
  const requirementsLabel = await fontStyle(requirements.locator('..'));
  assert.equal(requirementsLabel.size, reference.size);
  assert.equal(requirementsLabel.weight, '400', 'The floating panel uses a regular-weight field label');
  await notebook.locator('.dcn-question').press('Escape');
  await notebook.locator('.dcn-close').first().click();
  await settle(page);
}

async function pngDownload(download) {
  const chunks = [];
  for await (const chunk of await download.createReadStream()) chunks.push(chunk);
  const bytes = Buffer.concat(chunks);
  assert.match(download.suggestedFilename(), /\.png$/i);
  assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  assert.ok(bytes.readUInt32BE(16) > 64 && bytes.readUInt32BE(20) > 64, 'Export renders a usable PNG');
  assert.equal(await download.failure(), null);
}

async function exportImage(page, button) {
  const before = await page.evaluate(() => ({ ...actionChromeProbe, text: [...actionChromeProbe.text] }));
  const downloading = page.waitForEvent('download');
  await button.click();
  await pngDownload(await downloading);
  assert.deepEqual(await page.evaluate(() => actionChromeProbe), before, 'Image export leaves every clipboard API untouched');
}

async function checkWrongActions(page, reference, exports) {
  await toolsEntry(page, 'wrongBookBtn');
  const card = page.locator('#wrongBookList .wrong-card');
  assert.equal(await card.count(), 1);
  const actions = card.locator('.wrong-actions');
  assert.equal(await actions.getByRole('button', { name: /再测一道|再测一次|查看复测/ }).count(), 0,
    'Even a legacy passed retest cannot expose retest actions before correction');
  if (reference.module) {
    assert.deepEqual(await controlStyle(page.locator('#wrongBookSortTrigger')), reference.module,
      'Mobile sort uses the graph module picker surface and chevron');
    await page.locator('#wrongBookSortTrigger').click();
    await page.locator('#mobileChoiceModal').waitFor({ state: 'visible' });
    await page.getByRole('radio', { name: '最早更新', exact: true }).click();
    assert.equal(await page.locator('#wrongBookSort').inputValue(), 'oldest');
  }
  const image = actions.locator('.chat-image-copy');
  assert.equal(await image.count(), 1);
  assert.equal((await image.innerText()).trim(), '', 'Wrong-question export uses an icon without a text caption');
  assert.equal(await image.locator('svg[data-icon="image"]').count(), 1);
  assert.equal(await image.getAttribute('title'), '以图片形式导出');
  assert.equal(await image.getAttribute('aria-label'), '以图片形式导出');
  await page.mouse.move(0, 0);
  await page.locator('#wrongBookSearch').focus();
  await settle(page);
  for (const button of await actions.locator('button').all()) {
    const idle = await buttonPaint(button);
    assert.equal(idle.background, 'rgba(0, 0, 0, 0)', 'Idle actions have no fill');
    assert.equal(idle.image, 'none'); assert.equal(idle.shadow, 'none');
    assert.deepEqual(idle.border, ['0px', '0px', '0px', '0px'], 'Idle actions have no rectangular border');
  }
  const edit = actions.getByRole('button', { name: '编辑/笔记', exact: true });
  const idle = await buttonPaint(edit);
  if (page.viewportSize().width > 1100) {
    await edit.hover(); await settle(page);
    assert.notDeepEqual(await buttonPaint(edit), idle, 'Hover gives visible feedback');
    await page.mouse.move(0, 0);
  }
  await page.keyboard.press('Tab'); await edit.focus(); await settle(page);
  assert.notDeepEqual(await buttonPaint(edit), idle, 'Keyboard focus gives visible feedback');
  if (exports) await exportImage(page, image);
  await actions.getByRole('button', { name: '完成订正', exact: true }).click();
  assert.equal(await card.count(), 0, 'Completing correction removes the item from the pending filter');
  await page.locator('[data-wrong-filter="corrected"]').click();
  assert.equal(await card.count(), 1, 'The corrected filter contains the completed item');
  const corrected = card.locator('.wrong-actions');
  assert.equal(await corrected.getByRole('button', { name: /再测一道|再测一次/ }).count(), 1);
  assert.equal(await corrected.getByRole('button', { name: '查看复测', exact: true }).count(), 1);
}

async function checkChatActions(page, exports) {
  await page.evaluate(question => {
    closeWrongBook(); newChat();
    getCurrent().messages = [{ role: 'user', text: question, manualIsQuestion: true }];
    renderChat();
  }, question);
  const actions = page.locator('.msg.user .msg-actions');
  if (page.viewportSize().width <= 680) await page.locator('.msg.user > .msg-bubble').click();
  await actions.waitFor();
  assert.deepEqual(await actions.locator('svg[data-icon]').evaluateAll(icons => icons.map(icon => icon.dataset.icon)),
    ['copy', 'image', 'book-plus', 'pencil-line', 'trash'], 'Text copy comes before image export, then record, edit and delete');
  if (page.viewportSize().width > 1100) {
    await page.locator('.msg.user').hover(); await settle(page);
  }
  await actions.locator('.chat-text-copy').click();
  await page.waitForFunction(() => actionChromeProbe.text.length === 1);
  assert.ok((await page.evaluate(() => actionChromeProbe.text[0])).includes(question));
  const image = actions.locator('.chat-image-copy');
  for (const [language, label] of [['en', 'Export as image'], ['zh-CN', '以图片形式导出']]) {
    await page.evaluate(value => window.DMateI18n.setLanguage(value, false), language);
    await settle(page);
    assert.equal(await image.getAttribute('title'), label);
    assert.equal(await image.getAttribute('aria-label'), label);
    assert.equal(await page.locator('#knowledgeGraphCopyBtn').getAttribute('title'), label);
  }
  if (exports) await exportImage(page, image);
}

async function checkRetestLifecycle(page) {
  const before = await page.evaluate(question => {
    closeWrongBook();
    const item = learningState.wrongQuestions[0];
    Object.assign(item, { corrected: true, retestCount: 3, retestPassCount: 2, retestFailCount: 1,
      manualRetestPassCount: 1, passedRetestSessionIds: ['lifecycle-delete'], retestPassed: true });
    const retest = { wrongQuestionId: item.id, stage: 'finished', generatedQuestion: question,
      generatedAnswer: '设 n=2k+1，展开平方即得。', referenceQuestion: question,
      targetPoints: ['直接证明与反证法'], result: 'correct', startedAt: 100 };
    sessions = ['lifecycle-delete', 'lifecycle-keep'].map(id => ({ id, name: id, createdAt: 100,
      messages: [{ role: 'user', text: question }, { role: 'ai', text: retest.generatedAnswer }],
      retest: { ...retest }, teaching: null, learningQuestion: null }));
    currentId = sessions[0].id;
    saveState(); saveLearningState(); renderSessions(); renderChat();
    return JSON.parse(JSON.stringify(item));
  }, question);
  if (page.viewportSize().width <= 1100) {
    if (!await page.evaluate(() => document.body.classList.contains('mobile-left-open'))) await page.locator('#mobileNavBtn').click();
  } else if (await page.evaluate(() => document.documentElement.dataset.desktopSidebar !== 'expanded')) {
    await page.locator('#desktopSidebarOpen').click();
  }
  const row = page.locator('.session[data-session-id="lifecycle-delete"]');
  await row.hover(); await row.locator('.del').click();
  await page.locator('#appConfirmConfirm').click();
  await page.waitForFunction(() => !sessions.some(item => item.id === 'lifecycle-delete'));
  const after = await page.evaluate(() => learningState.wrongQuestions[0]);
  for (const key of ['retestCount', 'retestPassCount', 'retestFailCount', 'manualRetestPassCount', 'passedRetestSessionIds', 'retestPassed']) {
    assert.deepEqual(after[key], before[key], 'Deleting a conversation preserves wrong-book ' + key);
  }
  assert.deepEqual(after.retestRecords.slice(0, before.retestRecords.length), before.retestRecords,
    'Deleting a conversation preserves previously saved retest details');
  const saved = after.retestRecords.find(item => item.id === 'lifecycle-delete');
  assert.equal(saved?.question, question, 'Deletion saves the retest independently of its conversation');
  assert.equal(saved.answer, '设 n=2k+1，展开平方即得。');
  await page.evaluate(() => closeMobileShellDrawers());
  await toolsEntry(page, 'wrongBookBtn');
  await page.locator('#wrongBookList').getByRole('button', { name: '查看复测', exact: true }).click();
  const savedRow = page.locator('.wrong-retest-review-row').filter({ has: page.locator('.wrong-retest-review-check:checked') });
  assert.ok((await savedRow.innerText()).includes(question), 'The saved retest remains viewable after its conversation is deleted');
  await page.evaluate(() => closeWrongRetestReview());
  await page.locator('#wrongBookList').getByRole('button', { name: '移出错题本', exact: true }).click();
  await page.locator('#appConfirmConfirm').click();
  await page.waitForFunction(() => learningState.wrongQuestions.length === 0);
  const result = await page.evaluate(({ question, oldId }) => {
    const originalSession = sessions.find(item => item.id === 'lifecycle-keep');
    const originalMessages = JSON.stringify(originalSession.messages);
    const added = addWrongQuestion({ text: question, safeConfirmed: true,
      referenceAnswer: '奇数的平方仍为奇数。' }, '', 'manual').entry;
    const before = JSON.stringify(added);
    const history = getWrongRetestSessions(added);
    originalSession.retest.stage = 'checking';
    const handled = processWrongQuestionRetestReply(originalSession, '回答正确。');
    return { id: added.id, oldId, history, handled, unchanged: JSON.stringify(added) === before,
      retest: originalSession.retest, messagesKept: JSON.stringify(originalSession.messages) === originalMessages,
      tombstoned: Boolean(learningState.deletedWrongQuestionIds[oldId]),
      stats: [added.retestCount, added.retestPassCount, added.retestFailCount, added.manualRetestPassCount],
      records: added.retestRecords, passed: added.passedRetestSessionIds };
  }, { question, oldId: before.id });
  assert.equal(result.messagesKept, true, 'Removing a wrong-book entry preserves the original retest conversation');
  assert.equal(result.tombstoned, true, 'The removed wrong-book ID stays deleted');
  assert.notEqual(result.id, result.oldId, 'Re-adding the same question creates an independent wrong-book record');
  assert.deepEqual(result.stats, [0, 0, 0, 0]);
  assert.deepEqual([result.records, result.passed, result.history], [[], [], []]);
  assert.equal(result.handled, false, 'An old conversation cannot update the replacement wrong-book record');
  assert.equal(result.retest, null); assert.equal(result.unchanged, true);
}

async function runCase(browser, width, theme) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block',
    ...(width <= 1100 ? { isMobile: true, hasTouch: true } : {}) });
  await context.addInitScript(installClipboardProbe);
  const page = await context.newPage(), errors = [], modelRequests = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/auth/me', route => route.fulfill({ contentType: 'application/json',
    body: JSON.stringify({ configured: true, authenticated: false }) }));
  await page.route('**/chat', route => { modelRequests.push(route.request().url()); return route.abort(); });
  await page.route('**/analyze-questions', route => { modelRequests.push(route.request().url());
    return route.fulfill({ contentType: 'application/json', body: '{"results":[]}' }); });
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await page.waitForFunction(() => typeof openKnowledgeGraph === 'function');
    await page.evaluate(mode => { appearanceSettings.mode = mode; applyAppearanceSettings({ save: false }); }, theme);
    const reference = await graphReference(page);
    await seedWrongBook(page);
    await checkWrongActions(page, reference, theme === 'dark');
    await checkHeadingLabels(page, reference.heading);
    await checkChatActions(page, theme === 'dark');
    if (theme === 'dark') await checkRetestLifecycle(page);
    assert.deepEqual(modelRequests, [], 'The suite must not invoke AI endpoints');
    assert.deepEqual(errors, [], 'No browser script errors');
    console.log('PASS ' + width + '/' + theme + ': graph-matched labels/sort, quiet actions, correction gate, ordered copy/export' + (theme === 'dark' ? ', real PNG downloads and independent retest lifecycles' : ''));
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    const widths = process.env.DMATE_TEST_WIDTHS ? process.env.DMATE_TEST_WIDTHS.split(',').map(Number) : [390, 1440];
    assert.ok(widths.length && widths.every(width => [390, 1440].includes(width)), 'Use supported desktop/mobile test widths');
    for (const width of widths) await runCase(browser, width, 'dark');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
