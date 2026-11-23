/* Start Flask first. Uses real library records and browser controls to verify
 * independent multi-selection, combined filters and disconnected persistence.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const {revealInterface} = require('./offline-vault-browser-fixtures.cjs');
const concepts = require('../static/offline-content/concepts.zh-CN.json').concepts;
const questions = require('../static/offline-content/questions.zh-CN.json').questions;
const translations = require('../static/offline-content/translations.en.json');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const types = ['单项选择', '多项选择', '填空', '计算', '简答', '证明'];
const typeLabels = ['Single choice', 'Multiple choice', 'Fill in the blank', 'Calculation', 'Short answer', 'Proof'];
const questionMap = new Map(questions.map(question => [question.id, question]));
const letterQuestion = questions.find(question => question.type === '单项选择' && question.answer?.join('') === 'B');
const multipleQuestion = questions.find(question => question.type === '多项选择' && question.answer?.length > 1);
const writtenQuestion = questions.find(question => question.type === '证明' && /\$/.test(question.answer_text || '')
  && /\$/.test(translations.questions[question.id]?.answer_text || ''));
const linkedChild = concepts.find(concept => concept.id !== concept.graph_node_id && concept.related_questions?.length >= 3);
const selectableConcepts = concepts.filter(concept => ![linkedChild.id, linkedChild.graph_node_id].includes(concept.id));
const selectedConcepts = [selectableConcepts[0], selectableConcepts.find(concept => concept.category !== selectableConcepts[0].category)];
const selectedQuestions = [letterQuestion, multipleQuestion];
const linkedQuestion = (linkedChild.related_questions || []).map(id => questionMap.get(id))
  .find(question => question && !selectedQuestions.some(selected => selected.id === question.id));
assert.ok(letterQuestion && multipleQuestion && writtenQuestion && linkedQuestion && selectedConcepts.every(Boolean));
assert.deepEqual(new Set(questions.map(question => question.type)), new Set(types), 'The curriculum supplies all six question types');
const mobile = page => page.viewportSize().width <= 1100;
const level = value => value === '基础' ? '简单' : ['进阶', '提高'].includes(value) ? '困难' : value;
const rowSelector = kind => kind === 'concepts' ? '#conceptList .concept-item' : '#questionList .question-item';
const rowIds = (page, kind) => page.locator(rowSelector(kind)).evaluateAll((rows, kind) =>
  rows.map(row => row.dataset[kind === 'concepts' ? 'conceptId' : 'questionId']), kind);
const item = (page, kind, id) => page.locator(rowSelector(kind) + '[data-' + (kind === 'concepts' ? 'concept' : 'question') + '-id="' + id + '"]');
const checkbox = (page, kind, id) => page.locator('.offline-library-checkbox[data-selection-kind="' + kind + '"][data-selection-id="' + id + '"]');

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
  if (mobile(page) && !await page.evaluate(() => document.body.classList.contains('offline-nav-open'))) await page.locator('#offlineNavToggle').tap();
  await page.locator('.offline-nav-item[data-panel="' + panel + '"]').click();
  await page.locator('#' + panel + 'Panel').waitFor({ state: 'visible' });
  await settle(page);
}

async function choose(page, selector, value) {
  await closeLibraryDetail(page);
  const select = page.locator(selector);
  const selectionFilter = /^#(?:concept|question)Selection$/.test(selector);
  const english = await page.locator('html').getAttribute('data-ui-language') === 'en';
  const statusLabel = english ? 'Filter by status' : '按状态筛选';
  if (selectionFilter) {
    assert.equal(await select.getAttribute('aria-label'), statusLabel, 'The status picker uses the shorter shared label');
    assert.equal(await select.locator('option[value=""]').innerText(), english ? 'All statuses' : '全部状态',
      'The unfiltered status option names all statuses while retaining its empty value');
  }
  if (await select.inputValue() === value) return;
  if (mobile(page)) {
    const label = await select.evaluate((select, value) => [...select.options].find(option => option.value === value).label, value);
    await select.tap();
    await page.locator('#mobileChoiceModal').waitFor({ state: 'visible' });
    if (selectionFilter) assert.equal(await page.locator('#mobileChoiceTitle').innerText(), statusLabel,
      'The mobile choice dialog presents the same status label');
    await page.locator('#mobileChoiceModal').getByRole('radio', { name: label, exact: true }).tap();
    await page.locator('#mobileChoiceModal').waitFor({ state: 'hidden' });
  } else await select.selectOption(value);
  await settle(page);
  assert.equal(await select.inputValue(), value, 'Filtering retains canonical values in native and mobile controls');
}

async function clearFilters(page, kind) {
  await navigate(page, kind);
  const prefix = kind === 'concepts' ? 'concept' : 'question';
  await choose(page, '#' + prefix + 'Category', '');
  if (kind === 'questions') {
    await choose(page, '#questionDifficulty', '');
    await choose(page, '#questionType', '');
  }
  await choose(page, '#' + prefix + 'Selection', '');
  await settle(page);
}

async function openQuestion(page, question) {
  await clearFilters(page, 'questions');
  await item(page, 'questions', question.id).click();
  await openLibraryDetail(page, 'questions');
}

async function assertRows(page, kind, expected, message) {
  assert.deepEqual(await rowIds(page, kind), expected.map(record => record.id), message);
}

async function shapeAndIndependentSelection(page, kind, selected) {
  await clearFilters(page, kind);
  const records = kind === 'concepts' ? concepts : questions;
  await assertRows(page, kind, records, 'All current pack records are available before selection');
  assert.equal(await page.locator((kind === 'concepts' ? '#conceptList' : '#questionList') + ' [role="radio"]').count(), 0,
    'Library records use independent checkboxes rather than single-choice radio controls');
  const active = await page.locator(rowSelector(kind) + '.active').getAttribute('data-' + (kind === 'concepts' ? 'concept' : 'question') + '-id');
  const mark = checkbox(page, kind, selected[0].id);
  assert.equal(await mark.getAttribute('type'), 'checkbox');
  await mark.check();
  await settle(page);
  assert.equal(await page.locator(rowSelector(kind) + '.active').getAttribute('data-' + (kind === 'concepts' ? 'concept' : 'question') + '-id'), active,
    'Checking a record does not navigate away from the active detail');
  assert.equal(await mark.isChecked(), true);
  const circle = await mark.evaluate(input => {
    const style = getComputedStyle(input);
    return { width: input.getBoundingClientRect().width, radius: parseFloat(style.borderTopLeftRadius), appearance: style.appearance };
  });
  assert.ok(circle.width > 0 && circle.radius >= circle.width / 2, 'The visible selection control is circular');
  await choose(page, kind === 'concepts' ? '#conceptSelection' : '#questionSelection', 'unselected');
  assert.equal(await item(page, kind, selected[0].id).count(), 0, 'A checked record is excluded by Unselected');
  // The successful change immediately removes this row from Unselected, so
  // click the real input rather than waiting for a detached input to be checked.
  await checkbox(page, kind, selected[1].id).click();
  await settle(page);
  assert.equal(await item(page, kind, selected[1].id).count(), 0, 'Selecting while Unselected is active removes the row immediately');
  await choose(page, kind === 'concepts' ? '#conceptSelection' : '#questionSelection', 'selected');
  await assertRows(page, kind, records.filter(record => selected.some(value => value.id === record.id)), 'Selected contains exactly the checked records');
  for (const record of selected) assert.equal(await checkbox(page, kind, record.id).isChecked(), true);
}

async function conceptCombinedFilters(page) {
  const target = selectedConcepts[0];
  await choose(page, '#conceptCategory', target.category);
  await assertRows(page, 'concepts', [target], 'Concept chapter and selection filters combine');
  await choose(page, '#conceptSelection', 'unselected');
  assert.equal(await item(page, 'concepts', target.id).count(), 0);
  await choose(page, '#conceptSelection', 'selected');
  await assertRows(page, 'concepts', [target], 'Switching the selection filter retains other concept filters');
}

async function questionTypes(page, english = false) {
  await clearFilters(page, 'questions');
  const options = await page.locator('#questionType option').evaluateAll(options => options.map(option => ({ value: option.value, label: option.label })));
  assert.equal(options[0].value, '');
  assert.equal(options[0].label, english ? 'All question types' : '全部题型');
  assert.deepEqual(new Set(options.slice(1).map(option => option.value)), new Set(types));
  if (english) for (let i = 0; i < types.length; i++) assert.equal(options.find(option => option.value === types[i]).label, typeLabels[i]);
  for (const type of types) {
    await choose(page, '#questionType', type);
    await assertRows(page, 'questions', questions.filter(question => question.type === type), 'Question-type filter: ' + type);
  }
  await choose(page, '#questionType', '');
  await assertRows(page, 'questions', questions, 'All question types restores the complete current pack');
}

async function questionCombinedFilters(page) {
  await choose(page, '#questionType', letterQuestion.type);
  await choose(page, '#questionCategory', letterQuestion.category);
  await choose(page, '#questionDifficulty', level(letterQuestion.difficulty));
  await choose(page, '#questionSelection', 'selected');
  await assertRows(page, 'questions', [letterQuestion], 'Type, chapter, difficulty and selection combine');
  await choose(page, '#questionSelection', 'unselected');
  assert.equal(await item(page, 'questions', letterQuestion.id).count(), 0);
  await choose(page, '#questionSelection', 'selected');
  await assertRows(page, 'questions', [letterQuestion], 'Changing selection preserves the other practice filters');
}

async function answers(page, english = false) {
  for (const question of [letterQuestion, multipleQuestion]) {
    await openQuestion(page, question);
    await page.locator('#questionDetail .wrong-answer-summary').click();
    const answer = page.locator('#questionDetail .wrong-answer-inner');
    await answer.waitFor({ state: 'visible' });
    assert.equal((await answer.innerText()).trim(), question.answer.join('、'), 'Choice reference answers are plain option letters');
    assert.equal(await answer.locator('mjx-container,em,i').count(), 0, 'Choice answer letters have no math or italic rendering');
    assert.equal(await answer.evaluate(element => getComputedStyle(element).fontStyle), 'normal');
    if (question === letterQuestion) {
      await closeLibraryDetail(page);
      const other = questions.find(value => !selectedQuestions.some(selected => selected.id === value.id));
      const control = checkbox(page, 'questions', other.id);
      await control.check(); await settle(page);
      assert.equal(await page.locator('#questionList .question-item.active').getAttribute('data-question-id'), letterQuestion.id);
      await openLibraryDetail(page, 'questions');
      assert.equal(await page.locator('#questionDetail .wrong-answer-details[open]').isVisible(), true, 'Closing the detail and checking another row retains the revealed answer');
      await closeLibraryDetail(page);
      await control.uncheck();
    }
  }
  await openQuestion(page, writtenQuestion);
  await page.locator('#questionDetail .wrong-answer-summary').click();
  await page.locator('#questionDetail .wrong-answer-inner').waitFor({state:'visible'});
  await page.waitForFunction(() => !document.querySelector('#questionDetail [data-dmate-render-state="pending"]'));
  assert.ok(await page.locator('#questionDetail .wrong-answer-inner mjx-container').count() > 0,
    'Written reference answers retain mathematical typesetting in ' + (english ? 'English' : 'Chinese'));
}

async function language(page, value) {
  await page.evaluate(value => window.DMateI18n.setLanguage(value, false), value);
  await page.waitForFunction(value => document.documentElement.dataset.uiLanguage === value, value);
  await settle(page);
}

async function englishFilters(page) {
  await clearFilters(page, 'concepts');
  await choose(page, '#conceptSelection', 'selected');
  await language(page, 'en');
  for (const selector of ['#conceptSelection', '#questionSelection']) {
    assert.deepEqual(await page.locator(selector + ' option').evaluateAll(options => options.map(option => option.label)), ['All statuses', 'Selected', 'Unselected']);
  }
  assert.equal(await page.locator('#conceptSelection').inputValue(), 'selected', 'Changing language preserves the current selection filter');
  await assertRows(page, 'concepts', concepts.filter(concept => selectedConcepts.some(value => value.id === concept.id)));
  assert.equal(await checkbox(page, 'concepts', selectedConcepts[0].id).getAttribute('aria-label'),
    'Select concept: ' + translations.concepts[selectedConcepts[0].id].title);
  await questionTypes(page, true);
  await choose(page, '#questionType', letterQuestion.type);
  await choose(page, '#questionSelection', 'selected');
  await language(page, 'zh-CN');
  assert.equal(await page.locator('#questionType').inputValue(), letterQuestion.type);
  assert.equal(await page.locator('#questionSelection').inputValue(), 'selected');
  await assertRows(page, 'questions', selectedQuestions.filter(question => question.type === letterQuestion.type)
    .sort((a, b) => questions.indexOf(a) - questions.indexOf(b)), 'Language changes retain the selected/type filter intersection');
  await language(page, 'en');
}

async function conflictPracticeFilters(page) {
  await clearFilters(page, 'questions');
  await choose(page, '#questionType', types.find(type => type !== linkedQuestion.type));
  await choose(page, '#questionSelection', 'selected');
  await choose(page, '#questionCategory', questions.find(question => question.category !== linkedQuestion.category).category);
  await choose(page, '#questionDifficulty', ['简单', '中等', '困难'].find(value => value !== level(linkedQuestion.difficulty)));
  assert.equal(await item(page, 'questions', linkedQuestion.id).count(), 0);
}

async function assertLinkedQuestion(page) {
  await page.locator('#questionsPanel').waitFor({ state: 'visible' });
  for (const selector of ['#questionCategory', '#questionDifficulty', '#questionType', '#questionSelection']) {
    assert.equal(await page.locator(selector).inputValue(), '', 'Linked exercises clear conflicting filter: ' + selector);
  }
  assert.equal(await page.locator('#questionList .question-item.active').getAttribute('data-question-id'), linkedQuestion.id);
  assert.equal(await checkbox(page, 'questions', linkedQuestion.id).isChecked(), false, 'Opening a linked exercise does not select its checkbox');
}

async function linksClearConflicts(page) {
  // A practice -> concept link must remain reachable despite hidden targets.
  await clearFilters(page, 'concepts');
  await choose(page, '#conceptSelection', 'selected');
  await choose(page, '#conceptCategory', concepts.find(concept => concept.category !== linkedChild.category).category);
  assert.equal(await item(page, 'concepts', linkedChild.id).count(), 0);
  await openQuestion(page, linkedQuestion);
  await page.locator('#questionDetail .question-parent-concepts [data-concept-id="' + linkedChild.id + '"]').click();
  await page.locator('#conceptsPanel').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#conceptCategory').inputValue(), linkedChild.category,
    'A linked concept moves a conflicting chapter filter to the target chapter');
  assert.equal(await page.locator('#conceptSelection').inputValue(), '');
  assert.equal(await page.locator('#conceptList .concept-item.active').getAttribute('data-concept-id'), linkedChild.id);
  assert.equal(await checkbox(page, 'concepts', linkedChild.id).isChecked(), false);
  await conflictPracticeFilters(page);
  await navigate(page, 'concepts');
  await openLibraryDetail(page, 'concepts');
  await page.locator('#conceptDetail .concept-related-exercises [data-question-id="' + linkedQuestion.id + '"]').click();
  await assertLinkedQuestion(page);
  await conflictPracticeFilters(page);
  await navigate(page, 'concepts');
  await openLibraryDetail(page, 'concepts');
  await page.locator('#conceptDetail .concept-graph-module [data-graph-node-id="' + linkedChild.graph_node_id + '"]').click();
  await page.locator('#graphPanel').waitFor({ state: 'visible' });
  if (await page.locator('#knowledgeGraphModal').evaluate(modal => modal.classList.contains('graph-fullscreen-view'))) {
    await page.locator('.kg-mobile-expand').click(); await settle(page);
  }
  await page.locator('.graph-related-exercises [data-question-id="' + linkedQuestion.id + '"]').click();
  await assertLinkedQuestion(page);
}

async function assertSelectedRecords(page) {
  for (const [kind, selected, records] of [['concepts', selectedConcepts, concepts], ['questions', selectedQuestions, questions]]) {
    await clearFilters(page, kind);
    await choose(page, kind === 'concepts' ? '#conceptSelection' : '#questionSelection', 'selected');
    await assertRows(page, kind, records.filter(record => selected.some(value => value.id === record.id)), 'Checked records survive a disconnected reload');
    for (const record of selected) assert.equal(await checkbox(page, kind, record.id).isChecked(), true);
  }
}

async function runCase(browser, width, theme) {
  const context = await browser.newContext({ viewport: { width, height: 900 },
    ...(width <= 1100 ? { isMobile: true, hasTouch: true } : {}) });
  await context.addInitScript(theme => {
    let session;
    Object.defineProperty(window, 'DMateGuestSession', {configurable:true, get:()=>session, set(api) {
      session = api;
      // Seed this guest's legacy settings before encrypted workspace opening.
      // Reloads retain the migrated vault rather than recreating a raw copy.
      if (!api.getOwner() && !api.read('offline-vault-ref')) api.write('offline-settings', {
        appearance:{id:'appearance', settings:{mode:theme, accent:'blue', panelOpacity:100}, updatedAt:1}
      });
    }});
  }, theme);
  const page = await context.newPage(), errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(baseURL + '/offline', { waitUntil: 'networkidle' });
    await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
    await revealInterface(page);
    assert.equal(await page.locator('html').getAttribute('data-appearance-theme'), theme, 'Guest appearance migrates into the encrypted workspace');
    await shapeAndIndependentSelection(page, 'concepts', selectedConcepts);
    await conceptCombinedFilters(page);
    await shapeAndIndependentSelection(page, 'questions', selectedQuestions);
    await questionTypes(page);
    await questionCombinedFilters(page);
    await answers(page);
    await englishFilters(page);
    await answers(page, true);
    await linksClearConflicts(page);
    await page.evaluate(async () => {
      await navigator.serviceWorker.register('/offline-service-worker.js', { scope: '/' });
      await navigator.serviceWorker.ready;
    });
    await page.waitForFunction(() => navigator.serviceWorker.controller?.state === 'activated');
    await context.setOffline(true);
    await page.reload({ waitUntil: 'load' });
    await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
    await revealInterface(page);
    assert.equal(await page.locator('html').getAttribute('data-appearance-theme'), theme, 'Encrypted guest appearance survives disconnected reload');
    assert.equal(await page.evaluate(() => navigator.onLine), false);
    await language(page, 'en');
    await assertSelectedRecords(page);
    await questionTypes(page, true);
    await linksClearConflicts(page);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Extra filters and row circles do not cause horizontal page overflow');
    assert.deepEqual(errors, [], 'Library selections, filtering and linked navigation have no page errors');
    console.log('PASS ' + width + '/' + theme + ': independent circular multi-selection, all six CN/EN types, combined filters, plain choice answers, written mathematics and disconnected persistence/navigation');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    await runCase(browser, 1440, 'light');
    await runCase(browser, 390, 'dark');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
