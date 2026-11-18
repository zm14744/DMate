/* Start Flask first. Runs actual search controls without external AI requests;
 * the last case reloads the precached offline workspace with networking off.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const concepts = require('../static/offline-content/concepts.zh-CN.json').concepts;
const questions = require('../static/offline-content/questions.zh-CN.json').questions;
const translations = require('../static/offline-content/translations.en.json');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const isMobile = page => page.viewportSize().width <= 1100;
const difficulty = value => value === '基础' ? '简单' : ['进阶', '提高'].includes(value) ? '困难' : value;
const target = questions.find(question => question.id === 'q01');
assert.ok(target && translations.questions[target.id].title, 'Use a real bilingual exercise from the pack');

async function settle(page) {
  await page.evaluate(async () => {
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    await Promise.all(document.getAnimations().filter(animation =>
      animation.effect?.getComputedTiming().iterations !== Infinity)
      .map(animation => animation.finished.catch(() => {})));
  });
}

async function noOverflow(page, label) {
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), label + ': no page overflow');
}

function clearButton(input) {
  return input.locator('xpath=..').locator('button.dmate-search-clear');
}

async function searchStyle(input) {
  return input.evaluate(input => {
    const css = getComputedStyle(input), wrapper = getComputedStyle(input.parentElement);
    return { background: css.backgroundColor, image: css.backgroundImage,
      border: css.borderTopStyle, width: css.borderTopWidth, color: css.borderTopColor,
      radius: css.borderTopLeftRadius, shadow: css.boxShadow,
      wrapperBorder: [wrapper.borderTopWidth, wrapper.borderRightWidth, wrapper.borderBottomWidth, wrapper.borderLeftWidth] };
  });
}

async function checkSearch(input, expectedStyle, placeholder = '搜索') {
  await input.waitFor({ state: 'visible' });
  await input.page().waitForFunction(input => input.classList.contains('dmate-search-input'), await input.elementHandle());
  assert.equal(await input.getAttribute('placeholder'), placeholder);
  const wrapper = input.locator('xpath=..');
  assert.equal(await wrapper.locator('button').count(), 1, 'Exactly one clear button, including legacy controls');
  assert.equal(await clearButton(input).count(), 1);
  const actual = await searchStyle(input);
  assert.equal(actual.border, 'solid');
  assert.equal(actual.width, '1px');
  assert.ok(parseFloat(actual.radius) >= 8, 'Search uses a rounded input');
  assert.equal(actual.image, 'none');
  assert.equal(actual.shadow, 'none');
  assert.deepEqual(actual.wrapperBorder, ['0px', '0px', '0px', '0px'], 'Only the input paints a border');
  if (expectedStyle) assert.deepEqual(actual, expectedStyle, 'All searches use the concept-search surface');
  return actual;
}

async function expectClear(input, visible) {
  const button = clearButton(input);
  assert.equal(await button.isVisible(), visible, visible ? 'Nonempty search exposes clear' : 'Empty search hides clear');
  if (!visible) return;
  const paint = await button.evaluate(button => {
    const css = getComputedStyle(button), rect = button.getBoundingClientRect();
    return { color: css.backgroundColor, width: rect.width, height: rect.height, radius: css.borderRadius };
  });
  const [red, green, blue] = paint.color.match(/[\d.]+/g).map(Number);
  assert.ok(red >= 200 && green < 120 && blue < 120, 'Clear is a red dot');
  assert.ok(paint.width >= 12 && Math.abs(paint.width - paint.height) < 1, 'Clear remains circular and usable');
  assert.ok(parseFloat(paint.radius) >= paint.width / 2 || paint.radius.includes('%'));
}

async function clearSearch(input) {
  await expectClear(input, true);
  const button = clearButton(input);
  if (isMobile(input.page())) await button.tap(); else await button.click();
  await input.page().waitForFunction(input => input.value === '' && document.activeElement === input, await input.elementHandle());
  await expectClear(input, false);
}

async function navigate(page, panel) {
  if (isMobile(page) && !await page.evaluate(() => document.body.classList.contains('offline-nav-open'))) {
    await page.locator('#offlineNavToggle').tap();
  }
  const item = page.locator('.offline-nav-item[data-panel="' + panel + '"]');
  if (isMobile(page)) await item.tap(); else await item.click();
  await page.locator('#' + panel + 'Panel').waitFor({ state: 'visible' });
  await settle(page);
}

async function choose(page, id, value) {
  const select = page.locator('#' + id);
  if (!isMobile(page)) await select.selectOption(value);
  else {
    const label = await select.evaluate((select, value) => [...select.options].find(option => option.value === value)?.label, value);
    assert.ok(label, 'Canonical filter value exists: ' + value);
    await select.tap();
    const modal = page.locator('#mobileChoiceModal');
    await modal.waitFor({ state: 'visible' });
    await modal.getByRole('radio', { name: label, exact: true }).tap();
    await modal.waitFor({ state: 'hidden' });
  }
  await settle(page);
  assert.equal(await select.inputValue(), value);
}

async function checkQuestionResults(page, base, language = 'zh-CN', exact = false) {
  const ids = await page.locator('#questionList .question-item').evaluateAll(items => items.map(item => item.dataset.questionId));
  assert.ok(ids.every(id => base.some(question => question.id === id)), 'Search results stay inside chapter and difficulty');
  const query = await page.locator('#questionSearch').inputValue();
  const normalized = text => String(text || '').normalize('NFKC').trim().toLocaleLowerCase();
  const expected = exact ? base : base.filter(question => !normalized(query)
    || [question.title, translations.questions[question.id].title].some(title => normalized(title).includes(normalized(query))));
  assert.deepEqual(ids, expected.map(question => question.id), 'Only bilingual white titles participate in exercise search');
  assert.equal(await page.locator('#questionCount').innerText(), language === 'en'
    ? ids.length + (ids.length === 1 ? ' exercise' : ' exercises') : ids.length + ' 道题目');
  if (ids.length) {
    const active = page.locator('#questionList .question-item.active');
    assert.equal(await active.count(), 1);
    assert.ok(ids.includes(await active.getAttribute('data-question-id')));
  } else {
    assert.equal(await page.locator('#questionList .active').count(), 0);
    assert.equal(await page.locator('#questionDetail .detail-title').count(), 0, 'No stale exercise detail');
    assert.equal((await page.locator('#questionDetail .offline-empty').innerText()).trim(),
      language === 'en' ? 'None' : '无');
  }
  return ids;
}

async function offlineSearches(page) {
  assert.equal(await page.locator('#knowledgeGraphDetailTab,#knowledgeGraphModal .graph-side-tabs').count(), 0,
    'Offline graph has no redundant single tab row');
  assert.equal(await page.locator('#knowledgeGraphDetailTitle,#knowledgeGraphDetail').count(), 2,
    'Graph concept details remain');
  assert.ok((await page.locator('#knowledgeGraphDetail').innerText()).trim());
  await navigate(page, 'concepts');
  const concept = page.locator('#conceptSearch');
  const reference = await checkSearch(concept);
  await expectClear(concept, false);
  await concept.fill('欧拉');
  await expectClear(concept, true);
  const ids = await page.locator('#conceptList .concept-item').evaluateAll(items => items.map(item => item.dataset.conceptId));
  assert.ok(ids.includes('graph_euler') && ids.length < concepts.length, 'Existing concept filtering still works');
  await clearSearch(concept);
  assert.equal(await page.locator('#conceptList .concept-item').count(), concepts.length);
  const definitionOnly = concepts.find(item => item.definition.length > 70 && !item.definition.includes('\n'));
  await concept.fill(definitionOnly.definition);
  assert.equal(await page.locator('#conceptList .concept-item').count(), 0, 'Definitions are excluded from concept title search');
  assert.equal((await page.locator('#conceptDetail .offline-empty').innerText()).trim(), '无',
    'An empty concept search uses the shared None label');
  await clearSearch(concept);
  await concept.fill(definitionOnly.id);
  assert.equal(await page.locator('#conceptList .concept-item').count(), 0, 'Concept IDs are excluded from title search');
  await clearSearch(concept);

  await navigate(page, 'questions');
  const search = page.locator('#questionSearch');
  await checkSearch(search, reference);
  await expectClear(search, false);
  await choose(page, 'questionCategory', target.category);
  await choose(page, 'questionDifficulty', difficulty(target.difficulty));
  const base = questions.filter(question => question.category === target.category
    && difficulty(question.difficulty) === difficulty(target.difficulty));
  await checkQuestionResults(page, base, 'zh-CN', true);
  await search.fill(target.title);
  let result = await checkQuestionResults(page, base);
  assert.ok(result.includes(target.id) && result.length < base.length, 'Chinese exercise titles are searchable');
  await expectClear(search, true);
  await clearSearch(search);
  await checkQuestionResults(page, base, 'zh-CN', true);
  const englishTitle = translations.questions[target.id].title;
  await search.fill(englishTitle);
  result = await checkQuestionResults(page, base);
  assert.ok(result.includes(target.id), 'English titles remain searchable before changing UI language');
  await page.evaluate(() => window.DMateI18n.setLanguage('en', false));
  await page.waitForFunction(() => document.getElementById('questionSearch').placeholder === 'Search');
  assert.equal(await search.inputValue(), englishTitle, 'Live language change retains the search');
  assert.equal(await page.locator('#questionCategory').inputValue(), target.category);
  assert.equal(await page.locator('#questionDifficulty').inputValue(), difficulty(target.difficulty));
  result = await checkQuestionResults(page, base, 'en');
  assert.ok(result.includes(target.id));
  await clearSearch(search);
  await checkQuestionResults(page, base, 'en', true);
  await search.fill(target.id);
  assert.deepEqual(await checkQuestionResults(page, base, 'en'), [], 'Exercise IDs are not visible titles and are not searched');
  await search.fill(target.statement);
  assert.deepEqual(await checkQuestionResults(page, base, 'en'), [], 'Question body text cannot produce title-search matches');
  await search.fill(englishTitle);
  await choose(page, 'questionDifficulty', '困难');
  await checkQuestionResults(page, [], 'en', true);
  await clearSearch(search);
  const hard = questions.filter(question => question.category === target.category && difficulty(question.difficulty) === '困难');
  await checkQuestionResults(page, hard, 'en', true);
  await choose(page, 'questionDifficulty', difficulty(target.difficulty));
  await search.fill(englishTitle);
  await choose(page, 'questionCategory', '图论');
  await checkQuestionResults(page, [], 'en', true);
  await clearSearch(search);
  const graph = questions.filter(question => question.category === '图论'
    && difficulty(question.difficulty) === difficulty(target.difficulty));
  await checkQuestionResults(page, graph, 'en', true);
  await search.fill('__dmate_no_matching_exercise__');
  await checkQuestionResults(page, [], 'en', true);
  await navigate(page, 'concepts');
  await concept.fill('__dmate_no_matching_concept__');
  assert.equal((await page.locator('#conceptDetail .offline-empty').innerText()).trim(), 'None',
    'An English empty concept search uses the shared None label');
  await clearSearch(concept);
  await navigate(page, 'questions');
  await clearSearch(search);
  await checkQuestionResults(page, graph, 'en', true);
  await noOverflow(page, 'Offline search toolbar');
  return reference;
}

async function toolsEntry(page, id) {
  const kind = isMobile(page) ? 'mobile-tools-open' : 'desktop-tools-open';
  if (!await page.evaluate(kind => document.body.classList.contains(kind), kind)) {
    await page.locator(isMobile(page) ? '#mobileToolsBtn' : '#desktopToolsBtn').click();
  }
  await page.locator('#' + id).click();
  await settle(page);
}

async function onlineSearches(page, reference) {
  await toolsEntry(page, 'wrongBookBtn');
  const wrong = page.locator('#wrongBookSearch');
  await checkSearch(wrong, reference);
  await expectClear(wrong, false);
  assert.equal(await clearButton(wrong).getAttribute('id'), 'wrongBookSearchClear', 'Reuse the original wrong-book clear control');
  await wrong.fill('No matching saved exercise');
  await clearSearch(wrong);
  await page.evaluate(() => window.DMateI18n.setLanguage('en', false));
  await page.waitForFunction(() => document.getElementById('wrongBookSearch').placeholder === 'Search');
  await wrong.fill('English search');
  await clearSearch(wrong);
  await page.locator('#wrongBookClose').click();
  await page.evaluate(() => window.DMateI18n.setLanguage('zh-CN', false));
  await toolsEntry(page, 'conceptNotebookBtn');
  await page.locator('#conceptNotebookDialog').waitFor({ state: 'visible' });
  const notebook = page.locator('#conceptNotebookDialog .dcn-search');
  await checkSearch(notebook, reference);
  assert.ok((await clearButton(notebook).getAttribute('class')).includes('dcn-search-clear'), 'Reuse notebook clear control');
  await expectClear(notebook, false);
  for (const name of ['Alpha Graph', 'Beta Logic']) {
    await page.locator('#conceptNotebookDialog .dcn-sidebar > .dcn-new').click();
    await page.locator('#conceptNotebookDialog .dcn-title').fill(name);
  }
  assert.equal(await page.locator('.dcn-list .dcn-note').count(), 2);
  await notebook.fill('Alpha');
  assert.equal(await page.locator('.dcn-list .dcn-note').count(), 1);
  assert.ok((await page.locator('.dcn-list .dcn-note-open').innerText()).includes('Alpha Graph'));
  await clearSearch(notebook);
  assert.equal(await page.locator('.dcn-list .dcn-note').count(), 2);
  await page.evaluate(() => window.DMateI18n.setLanguage('en', false));
  await page.waitForFunction(() => document.querySelector('.dcn-search').placeholder === 'Search');
  await notebook.fill('__missing_note__');
  assert.equal(await page.locator('.dcn-list .dcn-note').count(), 0);
  assert.equal((await page.locator('.dcn-list-empty').innerText()).trim(), 'None',
    'An empty notebook search uses the shared None label');
  await clearSearch(notebook);
  assert.equal(await page.locator('.dcn-list .dcn-note').count(), 2);
  await noOverflow(page, 'Online wrong-book and notebook searches');
}

async function runCase(browser, width, theme) {
  const settings = { viewport: { width, height: 900 }, serviceWorkers: 'block',
    ...(width <= 1100 ? { isMobile: true, hasTouch: true } : {}) };
  let reference;
  for (const offline of [true, false]) {
    const context = await browser.newContext(settings), page = await context.newPage(), errors = [];
    page.on('pageerror', error => errors.push(error.message));
    try {
      await page.goto(baseURL + (offline ? '/offline' : ''), { waitUntil: 'networkidle' });
      if (offline) {
        await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
        await page.evaluate(mode => window.DMateOfflineAppearance.apply({ mode }, null), theme);
        reference = await offlineSearches(page);
      } else {
        await page.evaluate(mode => { appearanceSettings.mode = mode; applyAppearanceSettings({ save: false }); }, theme);
        await onlineSearches(page, reference);
      }
      assert.deepEqual(errors, [], 'No search script errors');
      console.log('PASS ' + (offline ? 'offline ' : 'online ') + width + '/' + theme + ': shared search paint, one red clear, focus and bilingual filtering');
    } finally { await context.close(); }
  }
}

async function disconnectedCase(browser) {
  const context = await browser.newContext({ viewport: { width: 390, height: 900 }, isMobile: true, hasTouch: true });
  const page = await context.newPage();
  try {
    await page.goto(baseURL + '/offline', { waitUntil: 'networkidle' });
    await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
    await page.evaluate(async () => {
      await navigator.serviceWorker.register('/offline-service-worker.js', { scope: '/' });
      await navigator.serviceWorker.ready;
    });
    await page.waitForFunction(() => navigator.serviceWorker.controller?.state === 'activated');
    await context.setOffline(true);
    await page.reload({ waitUntil: 'load' });
    await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
    assert.equal(await page.evaluate(() => navigator.onLine), false);
    await navigate(page, 'questions');
    await choose(page, 'questionCategory', target.category);
    await choose(page, 'questionDifficulty', difficulty(target.difficulty));
    const search = page.locator('#questionSearch');
    await checkSearch(search);
    await search.fill(translations.questions[target.id].title);
    const base = questions.filter(question => question.category === target.category
      && difficulty(question.difficulty) === difficulty(target.difficulty));
    assert.ok((await checkQuestionResults(page, base)).includes(target.id));
    await clearSearch(search);
    await checkQuestionResults(page, base, 'zh-CN', true);
    console.log('PASS disconnected reload: question search, filter intersection and red clear remain available');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const [width, theme] of [[390, 'dark'], [1440, 'light']]) await runCase(browser, width, theme);
    await disconnectedCase(browser);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
