/* Start Flask first. Runs actual search controls without external AI requests;
 * the last case reloads the precached offline workspace with networking off.
 */
'use strict';
const assert = require('node:assert/strict');
const { revealInterface } = require('./offline-vault-browser-fixtures.cjs');
const { chromium } = require('playwright');
const concepts = require('../static/offline-content/concepts.zh-CN.json').concepts;
const questions = require('../static/offline-content/questions.zh-CN.json').questions;
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const isMobile = page => page.viewportSize().width <= 1100;
const difficulty = value => value === '基础' ? '简单' : ['进阶', '提高'].includes(value) ? '困难' : value;
const target = questions.find(question => question.id === 'q01');
assert.ok(target, 'Use a real exercise from the pack');

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
  const icon = wrapper.locator(':scope > svg.dmate-search-icon');
  assert.equal(await icon.count(), 1, 'Dynamically mounted controls get exactly one magnifier');
  assert.equal(await icon.getAttribute('aria-hidden'), 'true');
  const geometry = await input.evaluate(node => {
    const svg = node.parentElement.querySelector('.dmate-search-icon');
    const icon = svg.getBoundingClientRect(), field = node.getBoundingClientRect(), css = getComputedStyle(node);
    return {width:icon.width, height:icon.height, stroke:parseFloat(getComputedStyle(svg).strokeWidth),
      inset:icon.left-field.left, center:icon.top+icon.height/2-field.top-field.height/2,
      start:parseFloat(css.paddingInlineStart), end:parseFloat(css.paddingInlineEnd)};
  });
  assert.deepEqual([geometry.width,geometry.height,geometry.stroke], [20,20,1.8]);
  assert.deepEqual([geometry.start,geometry.end], [42,40], 'The input reserves room for both icons');
  assert.ok(geometry.inset > 0 && geometry.inset+geometry.width <= geometry.start && Math.abs(geometry.center) < 1,
    'The search icon is centered inside the leading padding');
  // A dialog may autofocus its search. Compare idle materials after focus styles settle.
  await input.evaluate(node => node.blur());
  await settle(input.page());
  const actual = await searchStyle(input);
  assert.equal(actual.border, 'solid');
  assert.equal(actual.width, '1px');
  assert.equal(actual.radius, '999px', 'Search retains the pill shape at every viewport');
  assert.deepEqual(actual.wrapperBorder, ['0px', '0px', '0px', '0px'], 'Only the input paints a border');
  if (expectedStyle) assert.deepEqual(actual, expectedStyle, 'Remaining searches use the shared surface');
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

async function checkQuestionResults(page, expected, language = 'zh-CN') {
  const ids = await page.locator('#questionList .question-item').evaluateAll(items => items.map(item => item.dataset.questionId));
  assert.deepEqual(ids, expected.map(question => question.id), 'Chapter, difficulty, type and status yield the exact exercises');
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
  assert.equal(await page.locator('#conceptSearch,#questionSearch').count(), 0,
    'Concept and exercise libraries have no search controls');
  assert.equal(await page.locator('#knowledgeGraphDetailTab,#knowledgeGraphModal .graph-side-tabs').count(), 0,
    'Offline graph has no redundant single tab row');
  assert.equal(await page.locator('#knowledgeGraphDetailTitle,#knowledgeGraphDetail').count(), 2,
    'Graph concept details remain');
  assert.ok((await page.locator('#knowledgeGraphDetail').innerText()).trim());
  await navigate(page, 'concepts');
  await choose(page, 'conceptCategory', '图论');
  const graphConcepts = concepts.filter(concept => concept.category === '图论');
  assert.deepEqual(await page.locator('#conceptList .concept-item').evaluateAll(items => items.map(item => item.dataset.conceptId)),
    graphConcepts.map(concept => concept.id), 'Concept chapters still filter the full library');
  await choose(page, 'conceptSelection', 'selected');
  assert.equal(await page.locator('#conceptList .concept-item').count(), 0);
  assert.equal((await page.locator('#conceptDetail .offline-empty').innerText()).trim(), '无');
  await choose(page, 'conceptSelection', '');
  await choose(page, 'conceptCategory', '');
  assert.equal(await page.locator('#conceptList .concept-item').count(), concepts.length);

  await navigate(page, 'questions');
  await choose(page, 'questionCategory', target.category);
  await choose(page, 'questionDifficulty', difficulty(target.difficulty));
  await choose(page, 'questionType', target.type);
  const base = questions.filter(question => question.category === target.category
    && difficulty(question.difficulty) === difficulty(target.difficulty) && question.type === target.type);
  assert.ok((await checkQuestionResults(page, base)).includes(target.id));
  await page.evaluate(() => window.DMateI18n.setLanguage('en', false));
  assert.equal(await page.locator('#questionCategory').inputValue(), target.category);
  assert.equal(await page.locator('#questionDifficulty').inputValue(), difficulty(target.difficulty));
  assert.equal(await page.locator('#questionType').inputValue(), target.type);
  await checkQuestionResults(page, base, 'en');
  await choose(page, 'questionSelection', 'selected');
  await checkQuestionResults(page, [], 'en');
  await choose(page, 'questionSelection', '');
  await checkQuestionResults(page, base, 'en');
  await noOverflow(page, 'Library filter toolbar without search');

  await page.evaluate(() => window.DMateI18n.setLanguage('zh-CN', false));
  await navigate(page, 'notes');
  const notebook = page.locator('#noteList .dcn-search');
  const reference = await checkSearch(notebook);
  await expectClear(notebook, false);
  await notebook.fill('__missing_local_note__');
  await clearSearch(notebook);
  await noOverflow(page, 'Offline notebook search');
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
  const wrongStyle = await checkSearch(wrong, reference);
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
  const notebookStyle = await checkSearch(notebook, wrongStyle);
  const composer = await searchStyle(page.locator('.center > .input-wrap > .input'));
  for (const key of ['background', 'image', 'color', 'shadow']) {
    assert.equal(notebookStyle[key], composer[key], 'Notebook and wrong-book searches share the composer ' + key);
  }
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
        await revealInterface(page);
        await page.evaluate(mode => window.DMateOfflineAppearance.apply({ mode }, null), theme);
        reference = await offlineSearches(page);
      } else {
        await page.evaluate(mode => { appearanceSettings.mode = mode; applyAppearanceSettings({ save: false }); }, theme);
        await onlineSearches(page, reference);
      }
      assert.deepEqual(errors, [], 'No search script errors');
      console.log('PASS ' + (offline ? 'offline ' : 'online ') + width + '/' + theme + ': search-free libraries, filters and remaining shared search controls');
    } finally { await context.close(); }
  }
}

async function disconnectedCase(browser) {
  const context = await browser.newContext({ viewport: { width: 390, height: 900 }, isMobile: true, hasTouch: true });
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
    await navigate(page, 'questions');
    await choose(page, 'questionCategory', target.category);
    await choose(page, 'questionDifficulty', difficulty(target.difficulty));
    assert.equal(await page.locator('#conceptSearch,#questionSearch').count(), 0);
    const base = questions.filter(question => question.category === target.category
      && difficulty(question.difficulty) === difficulty(target.difficulty));
    assert.ok((await checkQuestionResults(page, base)).includes(target.id));
    console.log('PASS disconnected reload: libraries stay search-free and chapter/difficulty filters remain available');
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
