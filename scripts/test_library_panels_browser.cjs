/* Start Flask first. Uses real offline packs, native wheel/touch scrolling and
 * curriculum links. The final case reloads the cached app with networking off.
 */
'use strict';
const assert = require('node:assert/strict');
const { revealInterface } = require('./offline-vault-browser-fixtures.cjs');
const { chromium } = require('playwright');
const concepts = require('../static/offline-content/concepts.zh-CN.json').concepts;
const questions = require('../static/offline-content/questions.zh-CN.json').questions;
const nodes = require('../static/offline-content/knowledge_graph.json').nodes;
const translations = require('../static/offline-content/translations.en.json');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const mobile = page => page.viewportSize().width <= 1100;
const difficulty = value => value === '基础' ? '简单' : ['进阶', '提高'].includes(value) ? '困难' : value;
const ranks = { '简单': 0, '中等': 1, '困难': 2 };
const child = concepts.find(concept => concept.graph_node_id !== concept.id
  && nodes.some(node => node.id === concept.graph_node_id) && concept.related_questions?.length);
const longConcepts = concepts.filter(concept => concept.id !== concept.graph_node_id).sort((a, b) => {
  const size = concept => JSON.stringify([concept.definition, concept.explanation, concept.notation,
    concept.common_mistakes, concept.related_questions]).length;
  return size(b) - size(a);
});
const longQuestion = questions.filter(question => question.source?.migrated_from?.kind !== 'concept_example').sort((a, b) => {
  const size = question => JSON.stringify([question.statement, question.options, question.answer_text,
    question.explanation, question.grading_criteria]).length;
  return size(b) - size(a);
})[0];
assert.ok(child && longConcepts.length && longQuestion, 'Real packs provide representative concepts and exercises');

async function settle(page) {
  await page.evaluate(async () => {
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    await Promise.all(document.getAnimations().filter(animation =>
      animation.effect?.getComputedTiming().iterations !== Infinity)
      .map(animation => animation.finished.catch(() => {})));
  });
}

async function closeLibraryDetail(page) {
  if (await page.locator('#libraryDetailDialog').evaluate(dialog => dialog.open)) {
    await page.locator('#libraryDetailClose').click();
    await page.locator('#libraryDetailDialog').waitFor({ state: 'hidden' });
    await settle(page);
  }
}

async function openLibraryDetail(page, kind) {
  if (mobile(page) && !await page.locator('#libraryDetailDialog').evaluate(dialog => dialog.open)) {
    await page.locator(kind === 'concepts' ? '#conceptFullView' : '#questionFullView').click();
    await page.locator('#libraryDetailDialog').waitFor({ state: 'visible' });
  }
  await page.locator(kind === 'concepts' ? '#conceptDetail' : '#questionDetail').waitFor({ state: 'visible' });
  await settle(page);
}

async function navigate(page, panel) {
  await closeLibraryDetail(page);
  if (mobile(page) && !await page.evaluate(() => document.body.classList.contains('offline-nav-open'))) {
    await page.locator('#offlineNavToggle').tap();
  }
  const link = page.locator('.offline-nav-item[data-panel="' + panel + '"]');
  if (mobile(page)) await link.tap(); else await link.click();
  await page.locator('#' + panel + 'Panel').waitFor({ state: 'visible' });
  await settle(page);
}

async function noOverflow(page, panel) {
  const result = await page.locator('#' + panel + 'Panel').evaluate(panel => {
    const toolbar = panel.querySelector('.offline-toolbar');
    const rect = toolbar.getBoundingClientRect();
    return { page: document.documentElement.scrollWidth <= innerWidth + 1,
      left: rect.left, right: rect.right, width: innerWidth,
      controls: [...toolbar.querySelectorAll('select,input,.dmate-search-wrap')].filter(node => node.getClientRects().length)
        .map(node => ({ left: node.getBoundingClientRect().left, right: node.getBoundingClientRect().right })) };
  });
  assert.equal(result.page, true, panel + ': page has no horizontal overflow');
  assert.ok(result.left >= -1 && result.right <= result.width + 1, panel + ': toolbar remains in viewport');
  assert.ok(result.controls.every(control => control.left >= result.left - 1 && control.right <= result.right + 1),
    panel + ': filters and search fit their toolbar');
}

async function openConcept(page, concept) {
  await closeLibraryDetail(page);
  if (!await page.locator('#conceptsPanel').isVisible()) await navigate(page, 'concepts');
  await page.locator('#conceptSearch').fill(concept.title);
  const entry = page.locator('#conceptList .concept-item[data-concept-id="' + concept.id + '"]');
  await entry.click();
  await page.waitForFunction(id => document.querySelector('#conceptList .concept-item.active')?.dataset.conceptId === id, concept.id);
  await page.locator('#conceptSearch').fill('');
  await openLibraryDetail(page, 'concepts');
  await page.waitForFunction(() => !document.querySelector('#conceptDetail [data-dmate-render-state="pending"]'));
  await settle(page);
}

async function openScrollableConcept(page) {
  for (const concept of longConcepts.slice(0, 20)) {
    await openConcept(page, concept);
    if (await page.locator('#conceptDetail').evaluate(element => element.scrollHeight > element.clientHeight + 5)) return concept;
  }
  assert.fail('A real child concept should overflow the independent detail pane at this viewport');
}

async function frameState(page, panel) {
  return page.locator('#' + panel + 'Panel').evaluate(panel => {
    const toolbar = panel.querySelector('.offline-toolbar').getBoundingClientRect();
    return { panel: panel.scrollTop, body: document.body.scrollTop,
      root: document.scrollingElement.scrollTop, main: document.getElementById('offlineMain').scrollTop,
      toolbar: { top: toolbar.top, left: toolbar.left } };
  });
}

async function gestureScroll(page, selector) {
  const pane = page.locator(selector);
  const box = await pane.boundingBox();
  assert.ok(box && box.width > 20 && box.height > 30, selector + ': usable pane');
  if (!mobile(page)) {
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.wheel(0, 480);
  } else {
    const protocol = await page.context().newCDPSession(page);
    const x = box.x + box.width / 2, start = box.y + box.height * .82;
    try {
      await protocol.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ id: 1, x, y: start }] });
      for (let i = 1; i <= 8; i++) {
        await protocol.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ id: 1, x, y: start - box.height * .58 * i / 8 }] });
      }
      await protocol.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    } finally { await protocol.detach(); }
  }
  await page.waitForFunction(selector => document.querySelector(selector).scrollTop > 0, selector);
}

async function independentScroll(page, panel, kind) {
  if (mobile(page)) {
    if (kind === 'list') await closeLibraryDetail(page);
    else await openLibraryDetail(page, panel);
  }
  const prefix = panel === 'concepts' ? 'concept' : 'question';
  const selector = '#' + prefix + (kind === 'list' ? 'List' : 'Detail');
  const other = '#' + prefix + (kind === 'list' ? 'Detail' : 'List');
  const pane = page.locator(selector);
  const metrics = await pane.evaluate(element => ({ height: element.clientHeight, total: element.scrollHeight,
    overflow: getComputedStyle(element).overflowY }));
  assert.ok(metrics.total > metrics.height + 5, selector + ': real content overflows the independent pane');
  assert.ok(['auto', 'scroll'].includes(metrics.overflow), selector + ': native vertical scrolling');
  await pane.evaluate(element => { element.scrollTop = 0; });
  const before = await frameState(page, panel), otherBefore = await page.locator(other).evaluate(element => element.scrollTop);
  await gestureScroll(page, selector);
  assert.deepEqual(await frameState(page, panel), before, selector + ': wheel/touch keeps outer panel, body and toolbar still');
  assert.equal(await page.locator(other).evaluate(element => element.scrollTop), otherBefore, selector + ': other pane does not scroll');
  await pane.evaluate(element => { element.scrollTop = element.scrollHeight; });
  await settle(page);
  const end = await pane.evaluate(element => {
    const rect = element.getBoundingClientRect(), last = element.lastElementChild.getBoundingClientRect();
    return { atEnd: element.scrollTop + element.clientHeight >= element.scrollHeight - 2,
      lastBottom: last.bottom, lastTop: last.top, top: rect.top, bottom: rect.top + element.clientTop + element.clientHeight };
  });
  assert.equal(end.atEnd, true, selector + ': can reach the bottom');
  assert.ok(end.lastBottom <= end.bottom + 2 && end.lastBottom > end.top, selector + ': final content is visible');
  // Continue a real gesture at the end: scrolling must not chain to the panel.
  await gestureScroll(page, selector);
  assert.deepEqual(await frameState(page, panel), before, selector + ': end-of-pane gesture does not move outer content');
}

async function checkConceptSections(page, concept, language = 'zh-CN') {
  await openLibraryDetail(page, 'concepts');
  const headings = await page.locator('#conceptDetail h3').allTextContents();
  assert.ok(!headings.some(heading => heading === '典型例题' || /typical examples?/i.test(heading)), 'Removed examples section stays absent');
  assert.ok(!headings.includes('所属图谱知识点') && !headings.includes('关联知识点'), 'Old headings are gone');
  const exercises = page.locator('#conceptDetail .concept-related-exercises');
  if (concept.id === concept.graph_node_id) {
    assert.equal(await exercises.count(), 0, 'Overview concepts keep their data links without showing a practice section');
    return [];
  }
  assert.equal((await exercises.locator('h3').innerText()).trim(), language === 'en' ? 'Related exercises' : '关联练习');
  assert.equal(await exercises.locator('[data-concept-id]').count(), 0, 'Exercise links do not include prerequisite concepts');
  const actual = await exercises.locator('[data-question-id]').evaluateAll(links => links.map(link => ({
    id: link.dataset.questionId, difficulty: link.dataset.difficulty, text: link.textContent.trim() })));
  const expected = [...new Set(concept.related_questions)].map(id => questions.find(question => question.id === id)).filter(Boolean)
    .sort((a, b) => ranks[difficulty(a.difficulty)] - ranks[difficulty(b.difficulty)]);
  assert.deepEqual(actual.map(item => item.id), expected.map(item => item.id), 'Related exercises are ordered by normalized difficulty');
  for (const link of actual) {
    const question = questions.find(question => question.id === link.id);
    assert.equal(link.difficulty, difficulty(question.difficulty));
    assert.ok(Object.hasOwn(ranks, link.difficulty));
    const label = language === 'en' ? { '简单': 'Easy', '中等': 'Medium', '困难': 'Hard' }[link.difficulty] : link.difficulty;
    assert.ok(link.text.startsWith(label), 'Each related exercise visibly declares its difficulty');
  }
  return actual;
}

async function graphRoundTrip(page, concept, language = 'zh-CN') {
  const node = nodes.find(node => node.id === concept.graph_node_id);
  assert.ok(node);
  const module = page.locator('#conceptDetail .concept-graph-module');
  assert.equal((await module.locator('h3').innerText()).trim(), language === 'en' ? 'Knowledge-map module' : '所属图谱模块');
  const link = module.locator('[data-graph-node-id]');
  const expectedName = await page.evaluate(name => window.DMateKnowledgeLanguage.label(name), node.name);
  assert.equal((await link.innerText()).trim(), expectedName, 'Graph module uses the actual graph node name');
  assert.equal(await link.getAttribute('data-graph-node-id'), node.id);
  assert.equal(await link.getAttribute('data-graph-category'), node.category);
  await link.click();
  await page.locator('#graphPanel').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#knowledgeGraphCategory').inputValue(), node.category, 'Navigation opens the node category');
  const selected = page.locator('#knowledgeGraphCanvas [data-node-id="' + node.id + '"].selected');
  await selected.waitFor({ state: 'visible' });
  assert.equal(await selected.getAttribute('aria-pressed'), 'true');
  await page.waitForFunction(id => {
    const selected = document.querySelector('#knowledgeGraphCanvas [data-node-id="' + id + '"]');
    const viewport = selected?.closest('.kg-mobile-viewport,.kg-desktop-viewport');
    if (!selected || !viewport) return false;
    const node = selected.getBoundingClientRect(), view = viewport.getBoundingClientRect();
    return node.right > view.left && node.left < view.right && node.bottom > view.top && node.top < view.bottom;
  }, node.id);
  assert.equal((await page.locator('#knowledgeGraphDetailTitle').innerText()).trim(), expectedName);
  if (await page.locator('#knowledgeGraphModal').evaluate(modal => modal.classList.contains('graph-fullscreen-view'))) {
    await page.locator('.kg-mobile-expand').click();
    await settle(page);
  }
  await page.locator('.graph-parent-concept [data-concept-id="' + node.id + '"]').click();
  await page.locator('#conceptsPanel').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#conceptList .concept-item.active').getAttribute('data-concept-id'), node.id,
    'Graph details can return to the associated concept');
}

async function openRelatedExercise(page, concept, language = 'zh-CN') {
  const related = await checkConceptSections(page, concept, language);
  const migrated = related.find(link => {
    const source = questions.find(question => question.id === link.id)?.source?.migrated_from;
    return source?.kind === 'concept_example' && source.concept_id === concept.id;
  });
  assert.ok(migrated, 'The migrated concept example is present among real related exercises');
  const question = questions.find(question => question.id === migrated.id);
  assert.ok(question.knowledge_points.includes(concept.id));
  assert.ok((question.answer_text || question.answer?.length) && question.explanation,
    'Migrated exercise has a reference answer and explanation');
  assert.ok(translations.questions[question.id]?.title && translations.questions[question.id]?.explanation,
    'Migrated exercise includes the matching English study content');
  await page.locator('#conceptDetail [data-question-id="' + question.id + '"]').click();
  await page.locator('#questionsPanel').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#questionList .question-item.active').getAttribute('data-question-id'), question.id);
  await page.locator('#questionDetail .question-actions .offline-primary').click();
  await page.locator('#questionDetail .answer-panel').waitFor({ state: 'visible' });
  await page.waitForFunction(() => !document.querySelector('#questionDetail [data-dmate-render-state="pending"]'));
  assert.ok(await page.locator('#questionDetail .wrong-answer-inner').evaluate(element =>
    Boolean(element.textContent.trim() || element.querySelector('mjx-container'))), 'Migrated exercise reference answer is rendered');
  assert.ok(await page.locator('#questionDetail .wrong-analysis-body').evaluate(element =>
    Boolean(element.textContent.trim() || element.querySelector('mjx-container'))), 'Migrated exercise explanation is rendered');
}

async function libraryFeatures(page) {
  await openConcept(page, child);
  assert.equal((await page.locator('#conceptDetail .concept-topic-links h3').innerText()).trim(), '所属总概念');
  await checkConceptSections(page, child);
  await graphRoundTrip(page, child);
  await openConcept(page, child);
  await page.evaluate(() => window.DMateI18n.setLanguage('en', false));
  await page.waitForFunction(() => document.documentElement.dataset.uiLanguage === 'en');
  assert.equal((await page.locator('#conceptDetail .detail-title').innerText()).trim(), translations.concepts[child.id].title);
  assert.equal((await page.locator('#conceptDetail .concept-topic-links h3').innerText()).trim(), 'Parent concept');
  await checkConceptSections(page, child, 'en');
  await graphRoundTrip(page, child, 'en');
  await page.evaluate(() => window.DMateI18n.setLanguage('zh-CN', false));
  await openConcept(page, child);
  await openRelatedExercise(page, child);
}

async function runCase(browser, width, height) {
  const context = await browser.newContext({ viewport: { width, height }, serviceWorkers: 'block',
    ...(width <= 1100 ? { isMobile: true, hasTouch: true } : {}) });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(baseURL + '/offline', { waitUntil: 'networkidle' });
    await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
    await revealInterface(page);
    const longConcept = await openScrollableConcept(page);
    await checkConceptSections(page, longConcept);
    await independentScroll(page, 'concepts', 'detail');
    await independentScroll(page, 'concepts', 'list');
    await noOverflow(page, 'concepts');
    await navigate(page, 'questions');
    await page.locator('#questionSearch').fill(longQuestion.title);
    await page.locator('#questionList .question-item[data-question-id="' + longQuestion.id + '"]').click();
    await page.locator('#questionSearch').fill('');
    await openLibraryDetail(page, 'questions');
    await page.locator('#questionDetail .question-actions .offline-primary').click();
    await page.waitForFunction(() => !document.querySelector('#questionDetail [data-dmate-render-state="pending"]'));
    await settle(page);
    await independentScroll(page, 'questions', 'detail');
    await independentScroll(page, 'questions', 'list');
    await noOverflow(page, 'questions');
    await libraryFeatures(page);
    assert.deepEqual(errors, [], 'No library panel script errors');
    console.log('PASS ' + width + 'x' + height + ': ' + (mobile(page) ? 'extended list and full-view detail scrolling' : 'independent wheel/touch panes')
      + ', fixed toolbar, graph round-trip and bilingual related exercises');
  } finally { await context.close(); }
}

async function disconnectedCase(browser) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const page = await context.newPage();
  try {
    await page.goto(baseURL + '/offline', { waitUntil: 'networkidle' });
    await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
    await revealInterface(page);
    await page.evaluate(async () => {
      await navigator.serviceWorker.register('/offline-service-worker.js', { scope: '/' });
      await navigator.serviceWorker.ready;
    });
    await page.waitForFunction(() => navigator.serviceWorker.controller?.state === 'activated');
    await context.setOffline(true);
    await page.reload({ waitUntil: 'load' });
    await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
    await revealInterface(page);
    assert.equal(await page.evaluate(() => navigator.onLine), false);
    await libraryFeatures(page);
    console.log('PASS disconnected reload: concept graph navigation and migrated bilingual exercises remain available');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const [width, height] of [[1440, 900], [390, 844], [820, 720]]) await runCase(browser, width, height);
    await disconnectedCase(browser);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
