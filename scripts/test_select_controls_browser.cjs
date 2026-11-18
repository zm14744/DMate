/* Start Flask first. Exercises the real online/offline selectors and chapter
 * filters; mobile choices use taps, desktop choices keep the native select.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const concepts = require('../static/offline-content/concepts.zh-CN.json').concepts;
const questions = require('../static/offline-content/questions.zh-CN.json').questions;
const translations = require('../static/offline-content/translations.en.json');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const mobile = page => page.viewportSize().width <= 1100;
const modal = page => page.locator('#mobileChoiceModal');
const difficulty = value => value === '基础' ? '简单' : ['进阶', '提高'].includes(value) ? '困难' : value;

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
  if (await modal(page).isVisible()) {
    const box = await modal(page).locator('.mobile-choice-card').boundingBox();
    assert.ok(box && box.x >= -1 && box.x + box.width <= page.viewportSize().width + 1,
      label + ': chooser fits the viewport');
  }
}

async function checkChooser(page, selectedLabel) {
  const rows = modal(page).getByRole('radio');
  assert.ok(await rows.count() > 1, 'Real choices are present');
  assert.equal(await modal(page).locator('.mobile-choice-option-check,input[type="radio"]').count(), 0,
    'Choice rows have no decorative circle or native radio');
  const selected = rows.filter({ hasText: selectedLabel }).filter({ has: page.locator('span') });
  const active = modal(page).locator('.mobile-choice-option.active');
  assert.equal(await active.count(), 1, 'Exactly one active row remains');
  assert.equal(await active.getAttribute('aria-checked'), 'true');
  assert.equal((await active.innerText()).trim(), selectedLabel);
  const paint = await modal(page).locator('.mobile-choice-option').evaluateAll(rows => {
    const active = rows.find(row => row.classList.contains('active'));
    const idle = rows.find(row => !row.classList.contains('active'));
    return { active: getComputedStyle(active).backgroundColor, idle: getComputedStyle(idle).backgroundColor };
  });
  assert.notEqual(paint.active, paint.idle, 'Active background still identifies the selected option');
  assert.ok(await selected.count() >= 1);
  await noOverflow(page, 'Mobile choices');
}

async function openChoice(page, id, trigger) {
  const select = page.locator('#' + id);
  const label = await select.evaluate(select => select.selectedOptions[0]?.label || '');
  const source = trigger && await page.locator(trigger).isVisible() ? page.locator(trigger) : select;
  await source.tap();
  await modal(page).waitFor({ state: 'visible' });
  assert.equal(await modal(page).evaluate(dialog => dialog.open), true);
  await checkChooser(page, label);
  return source;
}

async function choose(page, id, value, trigger) {
  const select = page.locator('#' + id);
  const label = await select.evaluate((select, value) => [...select.options].find(option => option.value === value)?.label, value);
  assert.ok(label, id + ': requested canonical value exists');
  if (mobile(page)) {
    await openChoice(page, id, trigger);
    await modal(page).getByRole('radio', { name: label, exact: true }).tap();
    await modal(page).waitFor({ state: 'hidden' });
  } else {
    await select.click();
    assert.equal(await modal(page).evaluate(dialog => dialog.open), false, 'Desktop click keeps native choices');
    await page.keyboard.press('Escape');
    await select.selectOption(value);
  }
  await page.waitForFunction(({ id, value }) => document.getElementById(id).value === value, { id, value });
  await settle(page);
  assert.equal(await select.inputValue(), value);
}

async function navigate(page, panel) {
  if (mobile(page) && !await page.evaluate(() => document.body.classList.contains('offline-nav-open'))) {
    await page.locator('#offlineNavToggle').tap();
  }
  const item = page.locator('.offline-nav-item[data-panel="' + panel + '"]');
  if (mobile(page)) await item.tap(); else await item.click();
  await page.locator('#' + panel + 'Panel').waitFor({ state: 'visible' });
  await settle(page);
}

async function checkNativeStyle(page) {
  if (mobile(page)) return;
  const fields = await page.locator('select:not([multiple])').evaluateAll(selects => selects.filter(select => select.size <= 1)
    .map(select => {
      const css = getComputedStyle(select);
      return { id: select.id, appearance: css.appearance, border: css.borderTopStyle,
        width: parseFloat(css.borderTopWidth), radius: parseFloat(css.borderTopLeftRadius), image: css.backgroundImage };
    }));
  assert.ok(fields.length > 0);
  for (const field of fields) {
    assert.equal(field.appearance, 'auto', field.id + ': native desktop appearance');
    assert.equal(field.border, 'solid', field.id + ': input border');
    assert.ok(field.width >= 1 && field.radius >= 8, field.id + ': rounded input shape');
    assert.equal(field.image, 'none', field.id + ': no custom arrow image');
  }
}

async function cancellationAndDisabled(page) {
  if (!mobile(page)) return;
  const id = 'questionDifficulty', select = page.locator('#' + id), before = await select.inputValue();
  await select.evaluate(select => {
    const option = new Option('暂不可用选项', '__disabled_select_test__');
    option.disabled = true; select.add(option);
  });
  await openChoice(page, id);
  const disabled = modal(page).getByRole('radio', { name: '暂不可用选项', exact: true });
  assert.equal(await disabled.isDisabled(), true);
  const box = await disabled.boundingBox();
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  assert.equal(await select.inputValue(), before);
  assert.equal(await modal(page).evaluate(dialog => dialog.open), true, 'Disabled option cannot close or select');
  await page.locator('#mobileChoiceClose').tap();
  await modal(page).waitFor({ state: 'hidden' });
  await page.waitForFunction(id => document.activeElement?.id === id, id);
  assert.equal(await select.inputValue(), before, 'Close cancels without changing the value');
  await openChoice(page, id);
  await page.keyboard.press('Escape');
  await modal(page).waitFor({ state: 'hidden' });
  await page.waitForFunction(id => document.activeElement?.id === id, id);
  assert.equal(await select.inputValue(), before, 'Escape cancels without changing the value');
  await select.evaluate(select => { select.disabled = true; });
  const control = await select.boundingBox();
  await page.mouse.click(control.x + control.width / 2, control.y + control.height / 2);
  assert.equal(await modal(page).evaluate(dialog => dialog.open), false, 'Disabled select does not open choices');
  assert.equal(await select.inputValue(), before);
  await select.evaluate(select => {
    select.disabled = false;
    select.querySelector('option[value="__disabled_select_test__"]').remove();
  });
}

async function expectConceptRows(page, expected, language = 'zh-CN') {
  assert.deepEqual(await page.locator('#conceptList .concept-item').evaluateAll(items => items.map(item => item.dataset.conceptId)),
    expected.map(item => item.id), 'Chapter and search yield the expected real concepts');
  assert.equal(await page.locator('#conceptCount').innerText(), language === 'en'
    ? expected.length + (expected.length === 1 ? ' concept' : ' concepts') : expected.length + ' 个概念');
  if (!expected.length) {
    assert.equal(await page.locator('#conceptList .active').count(), 0, 'Empty results have no stale selection');
    assert.equal(await page.locator('#conceptDetail .detail-title').count(), 0, 'Empty results clear the old detail');
    assert.equal((await page.locator('#conceptDetail .offline-empty').innerText()).trim(),
      language === 'en' ? 'None' : '无');
    return;
  }
  const active = page.locator('#conceptList .concept-item.active');
  assert.equal(await active.count(), 1);
  assert.equal(await active.getAttribute('aria-current'), 'true');
  const id = await active.getAttribute('data-concept-id');
  const current = expected.find(item => item.id === id);
  assert.ok(current, 'Selected concept belongs to the filtered chapter');
  const title = language === 'en' ? translations.concepts[id].title : current.title;
  assert.equal((await page.locator('#conceptDetail .detail-title').innerText()).trim(), title);
}

async function conceptFilters(page) {
  await navigate(page, 'concepts');
  const categories = id => page.locator('#' + id + ' option').evaluateAll(options => options.map(option => option.value));
  assert.deepEqual((await categories('conceptCategory')).slice(1), (await categories('knowledgeGraphCategory')).slice(1),
    'Concept chapters use the graph category order');
  await expectConceptRows(page, concepts);
  await choose(page, 'conceptCategory', '图论');
  const graph = concepts.filter(item => item.category === '图论');
  await expectConceptRows(page, graph);
  await page.locator('#conceptList .concept-item[data-concept-id="graph_basic__simple_graph"]').click();
  await page.locator('#conceptSearch').fill('简单图');
  const simple = graph.filter(item => [item.title, translations.concepts[item.id].title].some(title => title.includes('简单图')));
  await expectConceptRows(page, simple);
  assert.equal(await page.locator('#conceptList .concept-item.active').getAttribute('data-concept-id'), 'graph_basic__simple_graph',
    'Search preserves the selected concept while it remains a match');
  await page.locator('#conceptSearch').fill('欧拉');
  const euler = graph.filter(item => [item.title, translations.concepts[item.id].title].some(title => title.includes('欧拉')));
  assert.ok(euler.length > 0 && euler.length < graph.length);
  await expectConceptRows(page, euler);
  await page.evaluate(() => window.DMateI18n.setLanguage('en', false));
  await page.waitForFunction(() => document.documentElement.dataset.uiLanguage === 'en');
  await expectConceptRows(page, euler, 'en');
  assert.equal(await page.locator('#conceptCategory').inputValue(), '图论', 'Language changes keep the canonical category');
  assert.equal(await page.locator('#conceptCategory').evaluate(select => select.selectedOptions[0].label), 'Graph Theory');
  await choose(page, 'conceptCategory', '命题逻辑');
  await expectConceptRows(page, [], 'en');
  assert.equal(await page.locator('#conceptSearch').inputValue(), '欧拉', 'Chapter changes preserve the search query');
  await page.locator('#conceptSearch').fill('');
  await expectConceptRows(page, concepts.filter(item => item.category === '命题逻辑'), 'en');
  await choose(page, 'conceptCategory', '');
  await expectConceptRows(page, concepts, 'en');
  await page.locator('#conceptSearch').fill('__dmate_no_matching_concept__');
  await expectConceptRows(page, [], 'en');
  await page.locator('#conceptSearch').fill('');
  await expectConceptRows(page, concepts, 'en');
  await noOverflow(page, 'Concept chapter/search');
}

async function offlineCase(browser, width, theme) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block',
    ...(width <= 1100 ? { isMobile: true, hasTouch: true } : {}) });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(baseURL + '/offline', { waitUntil: 'networkidle' });
    await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
    await page.evaluate(mode => window.DMateOfflineAppearance.apply({ mode }, null), theme);
    const values = id => page.locator('#' + id + ' option').evaluateAll(options => options.map(option => option.value));
    const graphCategories = await values('knowledgeGraphCategory');
    assert.equal(graphCategories[0], '全部', 'The all-module canonical value remains unchanged');
    assert.equal(await page.locator('#knowledgeGraphCategory option').first().textContent(), '全部模块');
    assert.equal(graphCategories.length, 11, 'All ten real major categories are available');
    await checkNativeStyle(page);
    await choose(page, 'knowledgeGraphCategory', '图论', '#knowledgeGraphCategoryTrigger');
    await navigate(page, 'questions');
    await choose(page, 'questionCategory', '图论');
    await choose(page, 'questionDifficulty', '简单');
    const expected = questions.filter(item => item.category === '图论' && difficulty(item.difficulty) === '简单');
    assert.deepEqual(await page.locator('#questionList .question-item').evaluateAll(items => items.map(item => item.dataset.questionId)),
      expected.map(item => item.id), 'Real chapter and difficulty filters compose');
    assert.equal(await page.locator('#questionCount').innerText(), expected.length + ' 道题目');
    await cancellationAndDisabled(page);
    await conceptFilters(page);
    assert.deepEqual(errors, [], 'No offline selection script errors');
    console.log('PASS offline ' + width + '/' + theme + ': graph/practice/concept choices, chapter-search intersection, selection and live English');
  } finally { await context.close(); }
}

async function onlineCase(browser, width, theme) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block',
    ...(width <= 1100 ? { isMobile: true, hasTouch: true } : {}) });
  const page = await context.newPage(), errors = [], modelRequests = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/auth/me', route => route.fulfill({ contentType: 'application/json',
    body: '{"configured":true,"authenticated":false}' }));
  await page.route(/\/(?:chat|ocr(?:\/[^?]*)?|graph\/[^?]*|analyze-questions|classify|conversation\/title)(?:\?|$)/, route => {
    modelRequests.push(new URL(route.request().url()).pathname); return route.abort();
  });
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await page.evaluate(mode => { appearanceSettings.mode = mode; applyAppearanceSettings({ save: false }); openKnowledgeGraph(); }, theme);
    await page.waitForFunction(() => knowledgeGraphInitialized);
    await page.evaluate(() => selectKnowledgeGraphDisplayMode('full'));
    await page.waitForSelector('#knowledgeGraphCanvas .kg-section');
    assert.equal(await page.locator('#knowledgeGraphCategory option').first().textContent(), '全部模块');
    await checkNativeStyle(page);
    await choose(page, 'knowledgeGraphCategory', '图论', '#knowledgeGraphCategoryTrigger');
    await noOverflow(page, 'Online graph choices');
    await ocrSelectors(page);
    assert.deepEqual(modelRequests, [], 'Changing OCR grouping and region mode never recognizes images');
    assert.deepEqual(errors, [], 'No online selection script errors');
    console.log('PASS online ' + width + '/' + theme + ': shared mobile choices and native desktop selects');
  } finally { await context.close(); }
}

async function ocrSelectors(page) {
  await page.evaluate(() => {
    closeKnowledgeGraph();
    const originalUrl = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400"><rect width="600" height="400" fill="white"/></svg>');
    ocrTasks.clear();
    ocrTasks.set('select-fixture', { id: 'select-fixture', groupId: '1', isQuestion: true, state: 'ready',
      file: new File(['local fixture'], 'local-selector.png', { type: 'image/png' }), sessionId: currentId,
      originalUrl, startedAt: performance.now(), finishedAt: performance.now(),
      draft: { body_text: '本地选择器测试', graphs: [] }, initialDocument: { body_text: '本地选择器测试', graphs: [] } });
    renderOcrTasks(); openOcrGrouping();
  });
  const group = page.locator('#ocrGroupingDialog select[data-group-field="groupId"]');
  const change = async (select, value) => {
    const label = await select.evaluate((node, value) => [...node.options].find(option => option.value === value).label, value);
    if (mobile(page)) {
      await select.tap(); await modal(page).waitFor({ state: 'visible' });
      await checkChooser(page, await select.evaluate(node => node.selectedOptions[0].label));
      await modal(page).getByRole('radio', { name: label, exact: true }).tap();
      await modal(page).waitFor({ state: 'hidden' });
    } else {
      await select.selectOption(value);
      assert.equal(await modal(page).evaluate(node => node.open), false);
    }
    assert.equal(await select.inputValue(), value);
  };
  const shape = async select => select.evaluate(node => {
    node.blur();
    const css = getComputedStyle(node);
    return ['borderTopStyle', 'borderTopWidth', 'borderTopLeftRadius', 'backgroundColor', 'color']
      .map(key => css[key]);
  });
  const reference = page.locator(mobile(page) ? '#knowledgeGraphCategoryTrigger' : '#knowledgeGraphCategory');
  assert.deepEqual(await shape(group), await shape(reference), 'OCR group choice shares the ordinary select surface');
  await change(group, '2');
  assert.equal(await page.evaluate(() => ocrTasks.get('select-fixture').groupId), '2', 'A dynamic choice reaches the real grouping handler');
  await page.locator('#ocrGroupingDialog .ocr-group-close').click();
  await page.evaluate(() => editOcrTask('select-fixture'));
  const region = page.locator('#graphEditorDialog .dge-overlay-tools select');
  await region.waitFor({ state: 'visible' });
  assert.deepEqual(await shape(region), await shape(reference), 'Region mode shares the ordinary select surface');
  await change(region, 'irregular');
  assert.equal(await page.evaluate(() => ocrTasks.get('select-fixture').scanState.view.irregular), true,
    'A dynamic choice reaches the real region-mode handler');
  await page.locator('#graphEditorClose').click();
  await page.evaluate(() => { ocrTasks.clear(); renderOcrTasks(); });
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
    await navigate(page, 'concepts');
    await choose(page, 'conceptCategory', '图论');
    await expectConceptRows(page, concepts.filter(item => item.category === '图论'));
    await page.locator('#conceptSearch').fill('欧拉');
    const expected = concepts.filter(item => item.category === '图论'
      && [item.title, translations.concepts[item.id].title].some(title => title.includes('欧拉')));
    await expectConceptRows(page, expected);
    console.log('PASS disconnected reload: cached mobile chooser and concept chapter-search filter work');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const [width, theme] of [[390, 'light'], [820, 'dark'], [1440, 'light']]) {
      await onlineCase(browser, width, theme);
      await offlineCase(browser, width, theme);
    }
    await disconnectedCase(browser);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
