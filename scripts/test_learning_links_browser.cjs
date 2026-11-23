/* Real curriculum links in the offline app, including a disconnected reload.
 * Start Flask first; no remote model or video endpoints are called.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const {revealInterface} = require('./offline-vault-browser-fixtures.cjs');
const concepts = require('../static/offline-content/concepts.zh-CN.json').concepts;
const questions = require('../static/offline-content/questions.zh-CN.json').questions;
const nodes = require('../static/offline-content/knowledge_graph.json').nodes;
const translations = require('../static/offline-content/translations.en.json');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const conceptMap = new Map(concepts.map(item => [item.id, item]));
const questionMap = new Map(questions.map(item => [item.id, item]));
const nodeMap = new Map(nodes.map(item => [item.id, item]));
const overview = concepts.filter(item => item.id === item.graph_node_id);
const parentIds = question => [...new Set([
  ...(question.knowledge_points || []).map(id => conceptMap.get(id)?.graph_node_id),
  ...(question.graph_node_ids || [])
])].filter(id => nodeMap.has(id));
const sameParent = questions.find(question => question.knowledge_points.length > 1 && parentIds(question).length === 1);
const multipleParents = questions.find(question => parentIds(question).length > 1);
const richOverview = [...overview].sort((a, b) => b.related_questions.length - a.related_questions.length)[0];
const child = concepts.find(item => item.id !== item.graph_node_id && item.related_questions?.length);
const ranks = { '简单': 0, '中等': 1, '困难': 2 };
const difficulty = value => value === '基础' ? '简单' : ['进阶', '提高'].includes(value) ? '困难' : value;
const mobile = page => page.viewportSize().width <= 1100;
const graphMobile = page => page.viewportSize().width <= 760;
const title = (item, kind, language) => language === 'en' ? translations[kind][item.id].title : item.title;
assert.equal(questions.length, 561 + concepts.length, 'The learning UI retains original exercises and every migrated concept example');
assert.equal(overview.length, 68, 'Every graph node retains its overview concept');
assert.ok(sameParent && multipleParents && child && richOverview);

async function settle(page) {
  await page.evaluate(async () => {
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    await Promise.all(document.getAnimations().filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity)
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
  await page.locator('.offline-nav-item[data-panel="' + panel + '"]').click();
  await page.locator('#' + panel + 'Panel').waitFor({ state: 'visible' });
  await settle(page);
}

async function choose(page, selector, value) {
  await closeLibraryDetail(page);
  const select = page.locator(selector);
  if (await select.inputValue() === value) return;
  if (mobile(page)) {
    const label = await select.evaluate((select, value) => [...select.options].find(option => option.value === value).label, value);
    await select.tap();
    await page.locator('#mobileChoiceModal').getByRole('radio', { name: label, exact: true }).tap();
    await page.locator('#mobileChoiceModal').waitFor({ state: 'hidden' });
  } else await select.selectOption(value);
  await settle(page);
}

async function openQuestion(page, question) {
  await navigate(page, 'questions');
  await choose(page, '#questionCategory', question.category);
  await choose(page, '#questionDifficulty', '');
  await page.locator('#questionList [data-question-id="' + question.id + '"]').click();
  await page.waitForFunction(id => document.querySelector('#questionList .question-item.active')?.dataset.questionId === id, question.id);
  await openLibraryDetail(page, 'questions');
}

async function openConcept(page, concept) {
  await navigate(page, 'concepts');
  await choose(page, '#conceptCategory', concept.category);
  await page.locator('#conceptList [data-concept-id="' + concept.id + '"]').click();
  await openLibraryDetail(page, 'concepts');
}

async function language(page, value) {
  await page.evaluate(value => window.DMateI18n.setLanguage(value, false), value);
  await page.waitForFunction(value => document.documentElement.dataset.uiLanguage === value, value);
  await settle(page);
}

async function checkQuestionLinks(page, question, lang) {
  await openLibraryDetail(page, 'questions');
  const section = page.locator('#questionDetail .question-parent-concepts');
  assert.equal((await section.locator('h3').innerText()).trim(), lang === 'en' ? 'Related concepts' : '所属概念');
  const conceptIds = [...new Set(question.knowledge_points)].filter(id => conceptMap.has(id));
  assert.deepEqual(await section.locator('[data-concept-id]').evaluateAll(links => links.map(link => link.dataset.conceptId)), conceptIds);
  for (const id of conceptIds) {
    assert.equal((await section.locator('[data-concept-id="' + id + '"]').innerText()).trim(), title(conceptMap.get(id), 'concepts', lang),
      'Practice links use the concept name without a knowledge-point prefix');
  }
  const modules = page.locator('#questionDetail .question-graph-modules');
  assert.equal((await modules.locator('h3').innerText()).trim(), lang === 'en' ? 'Knowledge-map module' : '所属图谱模块');
  const actual = await modules.locator('[data-graph-node-id]').evaluateAll(links => links.map(link => ({
    id: link.dataset.graphNodeId, category: link.dataset.graphCategory, text: link.textContent.trim()
  })));
  assert.deepEqual(actual.map(link => link.id), parentIds(question), 'Modules preserve source order and deduplicate shared parents');
  for (const link of actual) {
    const node = nodeMap.get(link.id);
    assert.equal(link.category, node.category);
    assert.equal(link.text, await page.evaluate(name => window.DMateKnowledgeLanguage.label(name), node.name));
  }
  return actual;
}

async function exitFullGraph(page) {
  if (await page.locator('#knowledgeGraphModal').evaluate(modal => modal.classList.contains('graph-fullscreen-view'))) {
    await page.locator('.kg-mobile-expand').click();
    await settle(page);
  }
}

async function checkGraphSelection(page, node) {
  await page.locator('#graphPanel').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#knowledgeGraphCategory').inputValue(), node.category);
  await page.locator('#knowledgeGraphCanvas [data-node-id="' + node.id + '"].selected').waitFor({ state: 'visible' });
  const name = await page.evaluate(name => window.DMateKnowledgeLanguage.label(name), node.name);
  assert.equal((await page.locator('#knowledgeGraphDetailTitle').innerText()).trim(), name);
}

async function checkGraphLinks(page, node, lang) {
  const links = page.locator('#knowledgeGraphDetail .offline-graph-learning-links');
  assert.equal(await links.count(), 1, 'Node selection replaces the learning footer without stale copies');
  assert.equal((await links.locator('.graph-parent-concept h3').innerText()).trim(), lang === 'en' ? 'Overview concept' : '总概念');
  const parent = links.locator('.graph-parent-concept [data-concept-id]');
  assert.equal(await parent.count(), 1);
  assert.equal(await parent.getAttribute('data-concept-id'), node.id);
  assert.equal((await parent.innerText()).trim(), title(conceptMap.get(node.id), 'concepts', lang));
  const related = links.locator('.graph-related-exercises');
  assert.equal((await related.locator('h3').innerText()).trim(), lang === 'en' ? 'Related exercises' : '关联练习');
  const actual = await related.locator('[data-question-id]').evaluateAll(buttons => buttons.map(button => ({
    id: button.dataset.questionId, difficulty: button.dataset.difficulty
  })));
  const expected = [...new Set(conceptMap.get(node.id).related_questions)].map(id => questionMap.get(id)).filter(Boolean)
    .sort((a, b) => ranks[difficulty(a.difficulty)] - ranks[difficulty(b.difficulty)]);
  assert.deepEqual(actual.map(link => link.id), expected.map(question => question.id),
    'Graph exercises equal the overview data associations, sorted stably by difficulty');
  actual.forEach(link => assert.equal(link.difficulty, difficulty(questionMap.get(link.id).difficulty)));
  assert.equal(await links.locator('.offline-graph-concept-button').count(), 0, 'The old View concept control is absent');
  return actual;
}

async function clickModule(page, selector, node) {
  if (selector.startsWith('#conceptDetail')) await openLibraryDetail(page, 'concepts');
  if (selector.startsWith('#questionDetail')) await openLibraryDetail(page, 'questions');
  await page.locator(selector + '[data-graph-node-id="' + node.id + '"]').click();
  await checkGraphSelection(page, node);
  await settle(page);
}

async function checkChild(page, lang) {
  await openConcept(page, child);
  assert.equal((await page.locator('#conceptDetail .concept-topic-links h3').innerText()).trim(), lang === 'en' ? 'Parent concept' : '所属总概念');
  assert.equal(await page.locator('#conceptDetail .concept-related-exercises').count(), 1,
    'A detailed concept keeps its associated exercises');
  const parent = page.locator('#conceptDetail .concept-topic-links [data-concept-id]');
  assert.equal(await parent.getAttribute('data-concept-id'), child.graph_node_id);
  await parent.click();
  assert.equal(await page.locator('#conceptList .concept-item.active').getAttribute('data-concept-id'), child.graph_node_id);
  assert.equal(await page.locator('#conceptDetail .concept-related-exercises').count(), 0);
}

async function allOverviewSections(page) {
  await navigate(page, 'concepts');
  await choose(page, '#conceptCategory', '');
  for (const concept of overview) {
    assert.ok(concept.related_questions.length, 'Source overview exercise links remain present: ' + concept.id);
    await page.locator('#conceptList [data-concept-id="' + concept.id + '"]').click();
    assert.equal(await page.locator('#conceptList .concept-item.active').getAttribute('data-concept-id'), concept.id);
    assert.equal(await page.locator('#conceptDetail .concept-related-exercises').count(), 0,
      'Overview has no practice UI: ' + concept.id);
  }
  assert.equal(await page.locator('#conceptList .concept-item').count(), concepts.length, 'All concepts remain available');
}

async function footerReachable(page) {
  await exitFullGraph(page);
  const last = page.locator('.graph-related-exercises [data-question-id]').last();
  await last.scrollIntoViewIfNeeded();
  const state = await last.evaluate(button => {
    const box = button.getBoundingClientRect(), pane = document.getElementById('knowledgeGraphDetail').getBoundingClientRect();
    return { top: box.top, bottom: box.bottom, paneBottom: pane.bottom, height: innerHeight,
      overflow: document.documentElement.scrollWidth > innerWidth + 1,
      root: document.scrollingElement.scrollTop, body: document.body.scrollTop };
  });
  assert.ok(state.top >= 0 && state.bottom <= state.paneBottom + 2 && state.bottom <= state.height + 2,
    'The last graph exercise is reachable within the detail pane and viewport');
  assert.equal(state.overflow, false, 'Learning links do not cause horizontal page overflow');
  assert.equal(state.root, 0); assert.equal(state.body, 0);
}

async function graphPracticeRoundTrip(page, lang) {
  await openQuestion(page, multipleParents);
  const modules = await checkQuestionLinks(page, multipleParents, lang);
  const initial = nodeMap.get(modules[0].id), next = nodeMap.get(modules[1].id);
  assert.equal(initial.category, next.category, 'The multi-module fixture supports an actual same-category node click');
  await clickModule(page, '#questionDetail .question-graph-modules ', initial);
  await checkGraphLinks(page, initial, lang);
  // This is a real graph-node click, with the mobile canvas expanded by reveal.
  const node = page.locator('#knowledgeGraphCanvas ' + (graphMobile(page) ? '.kg-mobile-node' : '.kg-node-group') + '[data-node-id="' + next.id + '"]');
  await node.scrollIntoViewIfNeeded();
  await node.click();
  await checkGraphSelection(page, next);
  const related = await checkGraphLinks(page, next, lang);
  await exitFullGraph(page);
  await page.locator('.graph-parent-concept [data-concept-id="' + next.id + '"]').click();
  await page.locator('#conceptsPanel').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#conceptList .concept-item.active').getAttribute('data-concept-id'), next.id);
  assert.equal(await page.locator('#conceptDetail .concept-related-exercises').count(), 0);
  assert.equal(await page.locator('#knowledgeGraphModal').evaluate(modal =>
    modal.closest('#graphPanel') !== null && !modal.classList.contains('graph-fullscreen-view')), true,
  'Leaving a full mobile graph restores its inline host');

  // Keep deliberately conflicting practice filters while visiting graph.
  await openQuestion(page, sameParent);
  const otherCategory = nodes.find(node => node.category !== next.category).category;
  await choose(page, '#questionCategory', otherCategory);
  await choose(page, '#questionDifficulty', '困难');
  await navigate(page, 'graph');
  await exitFullGraph(page);
  await checkGraphLinks(page, next, lang);
  const target = questionMap.get(related.find(link => link.id !== sameParent.id).id);
  await page.locator('.graph-related-exercises [data-question-id="' + target.id + '"]').click();
  await page.locator('#questionsPanel').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#questionCategory').inputValue(), '');
  assert.equal(await page.locator('#questionDifficulty').inputValue(), '');
  assert.equal(await page.locator('#questionList .question-item.active').getAttribute('data-question-id'), target.id);
  await page.locator('#questionDetail .wrong-answer-summary').click();
  await page.locator('#questionDetail .wrong-answer-details[open]').waitFor({ state: 'visible' });
  await page.locator('#questionDetail .wrong-analysis-summary').click();
  await page.locator('#questionDetail .wrong-analysis-details[open]').waitFor({ state: 'visible' });
  await page.waitForFunction(() => !document.querySelector('#questionDetail [data-dmate-render-state="pending"]'));
  assert.ok(await page.locator('#questionDetail .wrong-answer-inner').evaluate(element =>
    Boolean(element.textContent.trim() || element.querySelector('mjx-container'))), 'Linked exercise has its reference answer');
  assert.ok(await page.locator('#questionDetail .wrong-analysis-body').evaluate(element =>
    Boolean(element.textContent.trim() || element.querySelector('mjx-container'))), 'Linked exercise has its explanation');
  const linkedConcept = page.locator('#questionDetail .question-parent-concepts [data-concept-id]').first();
  const conceptId = await linkedConcept.getAttribute('data-concept-id');
  await linkedConcept.click();
  await page.locator('#conceptsPanel').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#conceptList .concept-item.active').getAttribute('data-concept-id'), conceptId);
  const module = nodeMap.get(conceptMap.get(conceptId).graph_node_id);
  await clickModule(page, '#conceptDetail .concept-graph-module ', module);
  await exitFullGraph(page);
  await checkGraphLinks(page, module, lang);

  // Returning from the graph opens the same exercise and its localized detail.
  const matched = questionMap.get(conceptMap.get(module.id).related_questions[0]);
  await openQuestion(page, matched);
  await clickModule(page, '#questionDetail .question-graph-modules ', module);
  await exitFullGraph(page);
  await page.locator('.graph-related-exercises [data-question-id="' + matched.id + '"]').click();
  assert.equal((await page.locator('#questionDetail .detail-title').innerText()).trim(), title(matched, 'questions', lang));
  assert.equal(await page.locator('#questionList .question-item.active').getAttribute('data-question-id'), matched.id);
}

async function richFooter(page, lang) {
  await openConcept(page, richOverview);
  const node = nodeMap.get(richOverview.id);
  await clickModule(page, '#conceptDetail .concept-graph-module ', node);
  await checkGraphLinks(page, node, lang);
  await footerReachable(page);
}

async function ready(page) {
  await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
  await revealInterface(page);
}

async function runCase(browser, width, height, theme) {
  const context = await browser.newContext({ viewport: { width, height }, serviceWorkers: 'block',
    ...(width <= 1100 ? { isMobile: true, hasTouch: true } : {}) });
  await context.addInitScript(theme => {
    let session;
    Object.defineProperty(window, 'DMateGuestSession', {configurable:true, get:()=>session, set(api) {
      session = api;
      if (!api.getOwner() && !api.read('offline-vault-ref')) api.write('offline-settings', {
        appearance:{id:'appearance', settings:{mode:theme, accent:'blue', panelOpacity:100}, updatedAt:1}
      });
    }});
  }, theme);
  const page = await context.newPage(), errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(baseURL + '/offline', { waitUntil: 'networkidle' }); await ready(page);
    assert.equal(await page.locator('html').getAttribute('data-appearance-theme'), theme, 'Guest appearance migrates into the encrypted workspace');
    if (width === 1440) await allOverviewSections(page);
    await openQuestion(page, sameParent);
    await checkQuestionLinks(page, sameParent, 'zh-CN');
    await checkChild(page, 'zh-CN');
    await graphPracticeRoundTrip(page, 'zh-CN');
    await language(page, 'en');
    await openQuestion(page, sameParent);
    await checkQuestionLinks(page, sameParent, 'en');
    await checkChild(page, 'en');
    await graphPracticeRoundTrip(page, 'en');
    await richFooter(page, 'en');
    assert.deepEqual(errors, [], 'No learning-link script errors');
    console.log('PASS ' + width + 'x' + height + '/' + theme + ': concept/module dedup, live CN/EN graph exercises and actual bidirectional navigation');
  } finally { await context.close(); }
}

async function landscapeSmoke(browser) {
  const context = await browser.newContext({ viewport: { width: 844, height: 390 }, isMobile: true, hasTouch: true, serviceWorkers: 'block' });
  const page = await context.newPage();
  try {
    await page.goto(baseURL + '/offline', { waitUntil: 'networkidle' }); await ready(page);
    await richFooter(page, 'zh-CN');
    await language(page, 'en');
    await checkGraphLinks(page, nodeMap.get(richOverview.id), 'en');
    await footerReachable(page);
    console.log('PASS 844x390: long graph exercise footer reachable in both languages without page overflow');
  } finally { await context.close(); }
}

async function disconnected(browser) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const page = await context.newPage();
  try {
    await page.goto(baseURL + '/offline', { waitUntil: 'networkidle' }); await ready(page);
    await page.evaluate(async () => {
      await navigator.serviceWorker.register('/offline-service-worker.js', { scope: '/' });
      await navigator.serviceWorker.ready;
    });
    await page.waitForFunction(() => navigator.serviceWorker.controller?.state === 'activated');
    await context.setOffline(true);
    await page.reload({ waitUntil: 'load' }); await ready(page);
    assert.equal(await page.evaluate(() => navigator.onLine), false);
    await language(page, 'en');
    await openQuestion(page, sameParent);
    await checkQuestionLinks(page, sameParent, 'en');
    await checkChild(page, 'en');
    await graphPracticeRoundTrip(page, 'en');
    console.log('PASS disconnected reload: English concept/module/graph exercise links and reference answers remain usable');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    await runCase(browser, 1440, 900, 'light');
    await runCase(browser, 390, 844, 'dark');
    await landscapeSmoke(browser);
    await disconnected(browser);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
