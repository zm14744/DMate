/* Real mobile library browsing: title-only search, long lists, and full detail.
 * Start Flask first. The final case reloads the installed shell without a network.
 */
'use strict';
const assert = require('node:assert/strict');
const { revealInterface } = require('./offline-vault-browser-fixtures.cjs');
const { chromium } = require('playwright');
const concepts = require('../static/offline-content/concepts.zh-CN.json').concepts;
const questions = require('../static/offline-content/questions.zh-CN.json').questions;
const translations = require('../static/offline-content/translations.en.json');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const mobile = page => page.viewportSize().width <= 1100;
const normalize = value => String(value || '').normalize('NFKC').trim().toLocaleLowerCase();
const prefix = kind => kind === 'concepts' ? 'concept' : 'question';
const records = kind => kind === 'concepts' ? concepts : questions;
const dialog = page => page.locator('#libraryDetailDialog');
const child = concepts.find(concept => concept.id !== concept.graph_node_id && concept.related_questions?.length >= 3);
const linkedQuestion = questions.find(question => child.related_questions.includes(question.id));
const longConcept = concepts.filter(concept => concept.id !== concept.graph_node_id)
  .sort((a, b) => JSON.stringify(b).length - JSON.stringify(a).length)[0];
const longQuestion = questions.filter(question => question.type === '证明')
  .sort((a, b) => JSON.stringify(b).length - JSON.stringify(a).length)[0];
const title = (record, kind, language = 'zh-CN') => language === 'en' ? translations[kind][record.id].title : record.title;

async function settle(page) {
  await page.evaluate(async () => {
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    await Promise.all(document.getAnimations().filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity)
      .map(animation => animation.finished.catch(() => {})));
  });
}

async function closeDetail(page, escape = false) {
  if (!await dialog(page).evaluate(node => node.open)) return;
  if (escape) await page.keyboard.press('Escape'); else await page.locator('#libraryDetailClose').click();
  await dialog(page).waitFor({ state: 'hidden' });
  await settle(page);
}

async function navigate(page, kind) {
  await closeDetail(page);
  if (mobile(page) && await page.locator('#offlineNavToggle').getAttribute('aria-expanded') !== 'true') await page.locator('#offlineNavToggle').click();
  await page.locator('.offline-nav-item[data-panel="' + kind + '"]').click();
  await page.locator('#' + kind + 'Panel').waitFor({ state: 'visible' });
  await settle(page);
}

async function choose(page, id, value) {
  const select = page.locator('#' + id);
  if (await select.inputValue() === value) return;
  if (mobile(page)) {
    const label = await select.evaluate((node, value) => [...node.options].find(option => option.value === value).label, value);
    await select.click();
    await page.locator('#mobileChoiceModal').getByRole('radio', { name: label, exact: true }).click();
    await page.locator('#mobileChoiceModal').waitFor({ state: 'hidden' });
  } else await select.selectOption(value);
  await settle(page);
}

async function clearFilters(page, kind) {
  await navigate(page, kind);
  const p = prefix(kind);
  await choose(page, p + 'Category', '');
  await choose(page, p + 'Selection', '');
  if (kind === 'questions') {
    await choose(page, 'questionDifficulty', ''); await choose(page, 'questionType', '');
  }
  await page.locator('#' + p + 'Search').fill('');
  await settle(page);
}

async function ids(page, kind) {
  const p = prefix(kind);
  return page.locator('#' + p + 'List .' + p + '-item').evaluateAll((nodes, p) => nodes.map(node => node.dataset[p + 'Id']), p);
}

async function openRecord(page, kind, record) {
  await clearFilters(page, kind);
  const p = prefix(kind);
  await page.locator('#' + p + 'Search').fill(record.title);
  await page.locator('#' + p + 'List [data-' + p + '-id="' + record.id + '"]').click();
  await page.locator('#' + p + 'Search').fill('');
  await settle(page);
  assert.equal(await dialog(page).evaluate(node => node.open), false, 'Choosing a list title does not open a detail overlay');
}

async function expand(page, kind) {
  if (mobile(page)) {
    await page.locator('#' + prefix(kind) + 'FullView').click();
    await dialog(page).waitFor({ state: 'visible' });
  }
  await settle(page);
  await page.locator('#' + prefix(kind) + 'Detail').waitFor({ state: 'visible' });
}

async function layout(page, kind) {
  const p = prefix(kind);
  const state = await page.locator('#' + kind + 'Panel').evaluate((panel, p) => {
    const list = document.getElementById(p + 'List'), detail = document.getElementById(p + 'Detail');
    const preview = document.getElementById(p + 'FullView'), box = node => node.getBoundingClientRect();
    const l = box(list), root = box(panel), t = box(panel.querySelector('.offline-toolbar'));
    return { panelScroll: panel.scrollTop, body: document.scrollingElement.scrollTop,
      pageWidth: document.documentElement.scrollWidth, width: innerWidth,
      list: { top: l.top, bottom: l.bottom, height: l.height }, panel: { top: root.top, bottom: root.bottom },
      toolbarBottom: t.bottom, detailVisible: detail.getClientRects().length > 0 && getComputedStyle(detail).display !== 'none',
      previewVisible: preview.getClientRects().length > 0 && getComputedStyle(preview).display !== 'none',
      preview: { top: box(preview).top, bottom: box(preview).bottom, regionTop: box(preview.parentElement).top } };
  }, p);
  assert.ok(state.pageWidth <= state.width + 1, 'The expanded list does not create horizontal page scrolling');
  assert.equal(state.panelScroll, 0); assert.equal(state.body, 0);
  if (mobile(page)) {
    assert.equal(state.detailVisible, false, 'Mobile detail is opened through Complete view');
    assert.equal(state.previewVisible, true);
    assert.ok(state.list.height >= 36, 'The list retains an operable scrollport');
    assert.ok(state.list.bottom <= state.preview.top + 1, 'Complete view follows the extended list');
    assert.ok(state.preview.bottom <= state.panel.bottom + 1, 'Complete view remains reachable at the bottom');
    assert.ok(state.preview.regionTop - state.list.bottom <= 20,
      'The list extends to the Complete view row without a reserved detail area: ' + JSON.stringify(state));
    assert.ok(state.list.top - state.toolbarBottom <= 24, 'The list starts directly below the fixed toolbar: ' + JSON.stringify(state));
  } else {
    assert.equal(state.detailVisible, true, 'Desktop retains its side-by-side detail pane');
    assert.equal(state.previewVisible, false);
  }
}

async function rowPaint(page, kind) {
  const p = prefix(kind);
  for (const mode of ['light', 'dark', 'navy']) {
    await page.evaluate(mode => window.DMateOfflineAppearance.apply({ mode }, null), mode); await settle(page);
    const paints = await page.locator('#' + p + 'List .' + p + '-item').evaluateAll(nodes => [nodes[0], nodes[1]].filter(Boolean).map(node => {
      const css = getComputedStyle(node);
      return { background: css.backgroundColor, image: css.backgroundImage, shadow: css.boxShadow,
        border: [css.borderTopWidth, css.borderRightWidth, css.borderBottomWidth, css.borderLeftWidth] };
    }));
    for (const paint of paints) {
      assert.match(paint.background, /rgba\([^)]*,\s*0\)|transparent/, 'Only the outer selection row paints a background');
      assert.equal(paint.image, 'none'); assert.equal(paint.shadow, 'none');
      assert.deepEqual(paint.border, ['0px', '0px', '0px', '0px'], 'Inner title button has no rectangular border');
    }
  }
}

async function titleSearch(page, kind) {
  await clearFilters(page, kind);
  const p = prefix(kind), record = kind === 'concepts' ? child : linkedQuestion;
  const search = page.locator('#' + p + 'Search');
  for (const value of [record.title, translations[kind][record.id].title]) {
    await search.fill(value);
    const expected = records(kind).filter(row => [row.title, translations[kind][row.id].title]
      .some(text => normalize(text).includes(normalize(value)))).map(row => row.id);
    assert.deepEqual(await ids(page, kind), expected, 'Search returns only matching bilingual titles');
  }
  const body = kind === 'concepts' ? record.definition : record.statement;
  for (const value of [record.id, body]) {
    await search.fill(value);
    assert.deepEqual(await ids(page, kind), [], 'IDs and descriptive content do not match white-title search');
    if (mobile(page)) assert.equal(await page.locator('#' + p + 'FullView').isDisabled(), true, 'No stale full view can open after empty results');
  }
  await search.fill(record.title);
  const check = page.locator('.offline-library-checkbox[data-selection-kind="' + kind + '"][data-selection-id="' + record.id + '"]');
  await check.check();
  assert.equal(await dialog(page).evaluate(node => node.open), false, 'Checking a record leaves the list in view');
  await choose(page, p + 'Selection', 'selected');
  assert.deepEqual(await ids(page, kind), [record.id], 'Title and selected-state filters intersect');
  if (kind === 'questions') {
    await choose(page, 'questionType', record.type);
    assert.deepEqual(await ids(page, kind), [record.id], 'Question type combines with title and selection');
  }
  await clearFilters(page, kind);
}

async function fullDetails(page, kind, record) {
  const p = prefix(kind);
  await openRecord(page, kind, record); await rowPaint(page, kind); await layout(page, kind);
  await page.locator('#' + p + 'List').evaluate(list => { list.scrollTop = 170; }); await settle(page);
  const listScroll = await page.locator('#' + p + 'List').evaluate(list => list.scrollTop);
  await expand(page, kind);
  const detail = page.locator('#' + p + 'Detail');
  assert.equal((await detail.locator('.detail-title').innerText()).trim(), record.title);
  if (kind === 'questions' && !await detail.locator('.wrong-answer-details').evaluate(node => node.open))
    await detail.locator('.wrong-answer-summary').click();
  await detail.evaluate(node => { node.scrollTop = Math.min(160, node.scrollHeight - node.clientHeight); }); await settle(page);
  const offset = await detail.evaluate(node => node.scrollTop);
  if (mobile(page)) {
    assert.equal(await dialog(page).evaluate(node => node.contains(document.activeElement)), true, 'Focus enters the native full-detail dialog');
    assert.equal(await page.locator('#libraryDetailHost #' + p + 'Detail').count(), 1, 'Full view reuses the original detail article');
    await closeDetail(page, true);
    assert.equal(await page.evaluate(id => document.activeElement.id === id, p + 'FullView'), true, 'Escape restores focus to Complete view');
    assert.equal(await page.locator('#' + p + 'List').evaluate(list => list.scrollTop), listScroll, 'Closing restores the list scroll position');
    await expand(page, kind);
    assert.ok(Math.abs(await detail.evaluate(node => node.scrollTop) - offset) <= 1, 'Reopening retains the detail scroll position');
    if (kind === 'questions') {
      assert.equal(await detail.locator('.wrong-answer-details[open] .wrong-answer-inner').count(), 1, 'The revealed answer survives close and reopen');
      await page.evaluate(() => window.DMateI18n.setLanguage('en', false)); await settle(page);
      assert.equal((await page.locator('#libraryDetailTitle').innerText()).trim(), 'Exercise details');
      assert.equal((await detail.locator('.detail-title').innerText()).trim(), title(record, kind, 'en'));
      assert.equal(await detail.locator('.wrong-answer-details[open] .wrong-answer-inner').count(), 1, 'Language changes retain an open answer in full view');
      await page.evaluate(() => window.DMateI18n.setLanguage('zh-CN', false)); await settle(page);
    }
    await closeDetail(page);
    assert.equal(await page.evaluate(id => document.activeElement.id === id, p + 'FullView'), true, 'Red close restores focus to Complete view');
  }
}

async function links(page) {
  await clearFilters(page, 'questions');
  await choose(page, 'questionType', questions.find(question => question.type !== linkedQuestion.type).type);
  await page.locator('#questionSearch').fill('__conflicting_title__');
  await openRecord(page, 'concepts', child); await expand(page, 'concepts');
  await page.locator('#conceptDetail .concept-related-exercises [data-question-id="' + linkedQuestion.id + '"]').click();
  await page.locator('#questionDetail').waitFor({ state: 'visible' }); await settle(page);
  if (mobile(page)) assert.equal(await dialog(page).evaluate(node => node.open), true, 'Related exercises open a complete mobile detail');
  assert.equal(await page.locator('#questionSearch').inputValue(), ''); assert.equal(await page.locator('#questionType').inputValue(), '');
  await page.locator('#questionDetail .question-parent-concepts [data-concept-id="' + child.id + '"]').click();
  await page.locator('#conceptDetail').waitFor({ state: 'visible' });
  await page.locator('#conceptDetail .concept-graph-module-link').click();
  await page.locator('#graphPanel').waitFor({ state: 'visible' });
  assert.equal(await dialog(page).evaluate(node => node.open), false, 'Graph links close the library detail overlay');
  const graph = page.locator('#knowledgeGraphModal');
  if (await graph.evaluate(node => node.classList.contains('graph-fullscreen-view'))) await page.locator('.kg-mobile-expand').click();
  await page.locator('.graph-parent-concept [data-concept-id="' + child.graph_node_id + '"]').click();
  await page.locator('#conceptDetail').waitFor({ state: 'visible' }); await settle(page);
  assert.equal((await page.locator('#conceptDetail .detail-title').innerText()).trim(), concepts.find(c => c.id === child.graph_node_id).title);
  assert.equal(await page.locator('#conceptDetail,#questionDetail').count(), 2, 'Navigation never duplicates detail article IDs');
  await closeDetail(page);
}

async function responsive(page, original) {
  if (!mobile(page)) return;
  await openRecord(page, 'concepts', child); await expand(page, 'concepts');
  await page.setViewportSize({ width: 1440, height: 900 }); await settle(page);
  await dialog(page).waitFor({ state: 'hidden' });
  assert.equal(await page.locator('#conceptDetail').isVisible(), true, 'Changing to desktop restores the inline article');
  assert.equal(await page.locator('#libraryDetailHost #conceptDetail').count(), 0);
  await page.setViewportSize(original); await settle(page);
  await layout(page, 'concepts'); await expand(page, 'concepts');
  assert.equal((await page.locator('#conceptDetail .detail-title').innerText()).trim(), child.title);
  await closeDetail(page);
}

async function runCase(browser, width, height, full) {
  const context = await browser.newContext({ viewport: { width, height }, serviceWorkers: 'block', hasTouch: true });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(baseURL + '/offline', { waitUntil: 'networkidle' });
    await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
    await revealInterface(page);
    await fullDetails(page, 'concepts', longConcept);
    await fullDetails(page, 'questions', longQuestion);
    if (full) { await titleSearch(page, 'concepts'); await titleSearch(page, 'questions'); await links(page); }
    await responsive(page, { width, height });
    assert.deepEqual(errors, [], 'List, portal and responsive transitions have no page errors');
    console.log('PASS ' + width + 'x' + height + ': extended list, quiet title rows, complete detail/focus/state' + (full ? ', title-only search and linked navigation' : ''));
  } finally { await context.close(); }
}

async function disconnectedCase(browser) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true });
  const page = await context.newPage();
  try {
    await page.goto(baseURL + '/offline', { waitUntil: 'networkidle' });
    await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
    await revealInterface(page);
    await titleSearch(page, 'questions');
    await page.evaluate(async () => { await navigator.serviceWorker.register('/offline-service-worker.js', { scope: '/' }); await navigator.serviceWorker.ready; });
    await page.waitForFunction(() => navigator.serviceWorker.controller?.state === 'activated');
    await context.setOffline(true); await page.reload({ waitUntil: 'load' });
    await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
    await revealInterface(page);
    assert.equal(await page.evaluate(() => navigator.onLine), false);
    await clearFilters(page, 'questions'); await choose(page, 'questionSelection', 'selected');
    await page.locator('#questionSearch').fill(translations.questions[linkedQuestion.id].title);
    assert.deepEqual(await ids(page, 'questions'), [linkedQuestion.id], 'Saved selection and title search remain usable offline');
    await page.locator('#questionList [data-question-id="' + linkedQuestion.id + '"]').click(); await expand(page, 'questions');
    if (!await page.locator('#questionDetail .wrong-answer-details').evaluate(node => node.open))
      await page.locator('#questionDetail .wrong-answer-summary').click();
    assert.equal(await page.locator('#questionDetail .wrong-answer-details[open] .wrong-answer-inner').count(), 1);
    await closeDetail(page);
    console.log('PASS disconnected reload: title-only search, selected records and complete exercise/answer view');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const [width, height, full] of [[1440, 900, true], [390, 844, true], [820, 900, false], [844, 390, false]]) await runCase(browser, width, height, full);
    await disconnectedCase(browser);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
