/* Wrong-book status filters retain one of two choices during the workspace
 * session. Run with Flask available; all learning entries are local fixtures.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const questions = {
  oldPending: '筛选共同题：待订正早期',
  newPending: '筛选共同题：待订正近期',
  corrected: '筛选共同题：已订正',
  other: '其他已订正题'
};

async function settle(page) {
  await page.evaluate(async () => {
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    await Promise.all(document.getAnimations().filter(animation =>
      animation.effect?.getComputedTiming().iterations !== Infinity)
      .map(animation => animation.finished.catch(() => {})));
  });
}

async function seed(page) {
  await page.evaluate(questions => {
    const entry = (id, question, corrected, updatedAt) => ({
      id, question, corrected, updatedAt, createdAt: updatedAt,
      category: '证明与归纳', relatedCategories: [], knowledgePoints: ['直接证明与反证法'],
      focusPoints: ['直接证明与反证法'], difficulty: '简单', classificationVersion: 3,
      answer: '本地参考答案', referenceAnswer: '本地参考答案', analysis: '已有解析', note: ''
    });
    learningState = normalizeLearningState({ version: 9, events: [], wrongQuestions: [
      entry('filter-old-pending', questions.oldPending, false, 1),
      entry('filter-new-pending', questions.newPending, false, 3),
      entry('filter-corrected', questions.corrected, true, 4),
      entry('filter-other', questions.other, true, 2)
    ] });
  }, questions);
}

async function expectFilter(page, filter, visible) {
  const state = await page.evaluate(() => ({ filter: wrongBookFilter,
    selected: [...document.querySelectorAll('[data-wrong-filter].active')]
      .map(button => button.dataset.wrongFilter) }));
  assert.equal(state.filter, filter);
  assert.deepEqual(state.selected, [filter], 'Exactly one status stays selected');
  for (const key of ['pending', 'corrected']) {
    assert.equal(await page.locator('[data-wrong-filter="' + key + '"]').getAttribute('aria-pressed'),
      String(key === filter));
  }
  assert.deepEqual((await page.locator('#wrongBookList .wrong-question').allTextContents()).map(text => text.trim()), visible,
    'Only records in the selected status are displayed, in the chosen order');
}

async function reopen(page) {
  await page.locator('#wrongBookClose').click();
  await page.locator('#wrongBookModal').waitFor({ state: 'hidden' });
  await page.evaluate(() => openWrongBook());
  await page.locator('#wrongBookModal').waitFor({ state: 'visible' });
  await settle(page);
}

async function oldestFirst(page) {
  if (page.viewportSize().width <= 1100) {
    await page.locator('#wrongBookSortTrigger').click();
    await page.getByRole('radio', { name: '最早更新', exact: true }).click();
  } else {
    await page.locator('#wrongBookSort').selectOption('oldest');
  }
}

async function runCase(browser, width) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block',
    ...(width <= 1100 ? { isMobile: true, hasTouch: true } : {}) });
  const page = await context.newPage(), errors = [], modelRequests = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/auth/me', route => route.fulfill({ contentType: 'application/json',
    body: JSON.stringify({ configured: true, authenticated: false }) }));
  for (const endpoint of ['**/chat', '**/analyze-questions']) {
    await page.route(endpoint, route => {
      modelRequests.push(route.request().url());
      return route.fulfill({ contentType: 'application/json', body: '{"results":[]}' });
    });
  }
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await page.waitForFunction(() => typeof openWrongBook === 'function');
    assert.equal(await page.evaluate(() => wrongBookFilter), 'pending', 'A new page starts at pending correction');
    await seed(page);
    await page.evaluate(() => openWrongBook());
    await page.locator('#wrongBookModal').waitFor({ state: 'visible' });
    assert.deepEqual(await page.locator('[data-wrong-filter]').allTextContents(), ['待订正', '已订正']);
    assert.match(await page.locator('#wrongBookStats').innerText(), /共 4 道\s+待订正 2\s+已订正 2/);
    const firstCard = page.locator('#wrongBookList .wrong-card').first();
    assert.deepEqual(await firstCard.locator('.wrong-meta-label').allTextContents(), ['难点'],
      'The card presents its focus without a whole-question concepts row');
    assert.equal((await page.locator('#wrongBookList').innerText()).includes('整题涉及'), false);
    assert.equal(await firstCard.getAttribute('data-wrong-question-id'), 'filter-new-pending');
    assert.equal(await firstCard.locator('.wrong-actions > button').nth(1).getAttribute('data-wrong-action'), 'graph',
      'View graph follows the existing image-export action');
    assert.equal(await firstCard.locator('.wrong-actions > button').nth(1).innerText(), '查看图谱');
    const printable = await page.evaluate(() => buildWrongBookPdfExportElement(learningState.wrongQuestions).textContent);
    assert.ok(printable.includes('难点：'));
    assert.equal(printable.includes('整题涉及'), false, 'PDF presentation follows the card focus-only metadata');
    assert.deepEqual(await page.evaluate(() => learningState.wrongQuestions[0].knowledgePoints), ['直接证明与反证法'],
      'Full classification data remains available for graphs and retests');
    await expectFilter(page, 'pending', [questions.newPending, questions.oldPending]);
    const pending = page.locator('[data-wrong-filter="pending"]');
    await pending.click(); await pending.click();
    await expectFilter(page, 'pending', [questions.newPending, questions.oldPending]);

    await page.locator('#wrongBookSearch').fill('筛选共同题');
    await oldestFirst(page);
    await expectFilter(page, 'pending', [questions.oldPending, questions.newPending]);
    const corrected = page.locator('[data-wrong-filter="corrected"]');
    await corrected.click(); await corrected.click();
    await expectFilter(page, 'corrected', [questions.corrected]);
    assert.equal(await page.locator('#wrongBookSearch').inputValue(), '筛选共同题');
    assert.equal(await page.locator('#wrongBookSort').inputValue(), 'oldest');
    await page.evaluate(() => setWrongBookFilter('all'));
    await expectFilter(page, 'corrected', [questions.corrected]);
    await reopen(page);
    await expectFilter(page, 'corrected', [questions.corrected]);
    assert.deepEqual(await page.evaluate(() => [wrongBookSearch, wrongBookSort]), ['筛选共同题', 'oldest'],
      'Reopening preserves the selected status, search, and sort');
    await pending.click();
    await reopen(page);
    await expectFilter(page, 'pending', [questions.oldPending, questions.newPending]);

    await page.locator('#wrongBookSearch').fill('');
    await page.evaluate(() => {
      learningState.wrongQuestions = learningState.wrongQuestions.filter(item => item.corrected);
      renderWrongBook();
    });
    assert.equal(await page.locator('#wrongBookList .wrong-empty').innerText(), '目前没有待订正的错题');
    await corrected.click();
    await page.locator('#wrongBookSearch').fill('筛选共同题');
    await page.evaluate(() => clearLoggedOutWorkspace());
    assert.deepEqual(await page.evaluate(() => [wrongBookFilter, wrongBookSearch, wrongBookSort]),
      ['pending', '', 'recent'], 'An account workspace reset returns to pending correction');
    await seed(page);
    await page.evaluate(() => openWrongBook());
    await expectFilter(page, 'pending', [questions.newPending, questions.oldPending]);
    assert.equal(await page.locator('#wrongBookSearch').inputValue(), '');
    assert.equal(await page.locator('#wrongBookSort').inputValue(), 'recent');
    assert.deepEqual(modelRequests, [], 'Status filtering never requests model output');
    assert.deepEqual(errors, [], 'No browser script errors');
    console.log('PASS ' + width + ': pending default, sticky two-state filters, reopen/search/sort retention, account reset');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const width of [390, 1440]) await runCase(browser, width);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
