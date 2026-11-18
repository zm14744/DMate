/* Wrong-book filters search only the card focus and its graph concepts, keep
 * capture dates stable, and retain their workspace state. All AI replies are local.
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
  await page.evaluate(async questions => {
    await ensureKnowledgeGraphData();
    const entry = (id, question, corrected, order) => ({
      id, question, corrected, createdAt: Date.UTC(2024, 0, 1 + order, 12, 34),
      updatedAt: Date.UTC(2024, 0, 11 + order, 12, 34),
      category: '图论', relatedCategories: ['初等数论'], knowledgePoints: ['图的矩阵表示'],
      focusPoints: [id === 'filter-other' ? '数学归纳法' : '直接证明与反证法'],
      recognitionSnapshot: { version: 1, question, difficulty: '简单',
        points: id === 'filter-other' ? ['函数与映射'] : ['集合运算', '函数与映射'] },
      difficulty: '简单', classificationVersion: 3,
      answer: '仅答案内容', referenceAnswer: '仅参考答案内容', analysis: '仅解析内容', note: '仅笔记内容',
      feedback: '仅反馈内容', lastRetestQuestion: '仅复测题干内容', lastRetestFeedback: '仅复测反馈内容'
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
  const context = await browser.newContext({ viewport: { width, height: 900 }, timezoneId: 'UTC', serviceWorkers: 'block',
    ...(width <= 1100 ? { isMobile: true, hasTouch: true } : {}) });
  const page = await context.newPage(), errors = [], modelRequests = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/auth/me', route => route.fulfill({ contentType: 'application/json',
    body: JSON.stringify({ configured: true, authenticated: false }) }));
  await page.route(/\/(?:chat|conversation\/title|classify|analyze-questions|ocr)(?:\?|$)/, route => {
    modelRequests.push(new URL(route.request().url()).pathname);
    return route.fulfill({ contentType: 'application/json',
      body: JSON.stringify({ reply: '[[ANSWER_ONLY]]本地更新答案[[/ANSWER_ONLY]]', results: [] }) });
  });
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await page.waitForFunction(() => typeof openWrongBook === 'function');
    assert.equal(await page.evaluate(() => wrongBookFilter), 'pending', 'A new page starts at pending correction');
    await seed(page);
    await page.evaluate(() => openWrongBook());
    await page.locator('#wrongBookModal').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#wrongBookSearch').getAttribute('placeholder'), '搜索');
    assert.deepEqual(await page.locator('[data-wrong-filter]').allTextContents(), ['待订正', '已订正']);
    assert.match(await page.locator('#wrongBookStats').innerText(), /共 4 道\s+待订正 2\s+已订正 2/);
    const firstCard = page.locator('#wrongBookList .wrong-card').first();
    assert.deepEqual(await firstCard.locator('.wrong-meta-label').allTextContents(), ['难点'],
      'The card presents its focus without a whole-question concepts row');
    assert.equal((await page.locator('#wrongBookList').innerText()).includes('整题涉及'), false);
    assert.equal(await firstCard.getAttribute('data-wrong-question-id'), 'filter-new-pending');
    assert.equal(await firstCard.locator('.wrong-date').innerText(), '1月4日 12:34',
      'The displayed date is the original capture date, even when updatedAt differs');
    assert.equal(await firstCard.locator('.wrong-actions > button').nth(1).getAttribute('data-wrong-action'), 'graph',
      'View graph follows the existing image-export action');
    assert.equal(await firstCard.locator('.wrong-actions > button').nth(1).innerText(), '查看图谱');
    const printable = await page.evaluate(() => buildWrongBookPdfExportElement(learningState.wrongQuestions).textContent);
    assert.ok(printable.includes('难点：'));
    assert.equal(printable.includes('整题涉及'), false, 'PDF presentation follows the card focus-only metadata');
    assert.deepEqual(await page.evaluate(() => learningState.wrongQuestions[0].knowledgePoints), ['图的矩阵表示'],
      'Searching does not rewrite retained legacy classification data');
    await expectFilter(page, 'pending', [questions.newPending, questions.oldPending]);
    const pending = page.locator('[data-wrong-filter="pending"]');
    await pending.click(); await pending.click();
    await expectFilter(page, 'pending', [questions.newPending, questions.oldPending]);

    for (const term of ['直接证明与反证法', '集合运算', '函数与映射']) {
      await page.locator('#wrongBookSearch').fill(term);
      await expectFilter(page, 'pending', [questions.newPending, questions.oldPending]);
    }
    for (const term of ['筛选共同题', '仅答案内容', '仅参考答案内容', '仅解析内容', '仅笔记内容',
      '仅反馈内容', '仅复测题干内容', '仅复测反馈内容', '图的矩阵表示', '图论', '初等数论']) {
      await page.locator('#wrongBookSearch').fill(term);
      await expectFilter(page, 'pending', []);
      assert.equal(await page.locator('#wrongBookList .wrong-empty').innerText(), '无', term + ' is outside the search scope');
    }
    await page.locator('#wrongBookSearch').fill('集合运算');
    await oldestFirst(page);
    await expectFilter(page, 'pending', [questions.oldPending, questions.newPending]);
    const corrected = page.locator('[data-wrong-filter="corrected"]');
    await corrected.click(); await corrected.click();
    await expectFilter(page, 'corrected', [questions.corrected]);
    assert.equal(await page.locator('#wrongBookSearch').inputValue(), '集合运算');
    assert.equal(await page.locator('#wrongBookSort').inputValue(), 'oldest');
    await page.evaluate(() => setWrongBookFilter('all'));
    await expectFilter(page, 'corrected', [questions.corrected]);
    await reopen(page);
    await expectFilter(page, 'corrected', [questions.corrected]);
    assert.deepEqual(await page.evaluate(() => [wrongBookSearch, wrongBookSort]), ['集合运算', 'oldest'],
      'Reopening preserves the selected status, search, and sort');
    await pending.click();
    await reopen(page);
    await expectFilter(page, 'pending', [questions.oldPending, questions.newPending]);

    await page.locator('#wrongBookSearch').fill('');
    assert.deepEqual(modelRequests, [], 'Filtering and graph-concept searches never request model output');
    const captured = await page.evaluate(() => {
      const item = learningState.wrongQuestions.find(item => item.id === 'filter-new-pending');
      return { createdAt: item.createdAt, updatedAt: item.updatedAt };
    });
    const source = page.locator('#wrongBookList [data-wrong-question-id="filter-new-pending"]');
    await source.getByRole('button', { name: '完成订正', exact: true }).click();
    await corrected.click();
    const expectCapturedDate = async () => {
      assert.equal(await source.locator('.wrong-date').innerText(), '1月4日 12:34');
      assert.equal(await page.evaluate(() => learningState.wrongQuestions
        .find(item => item.id === 'filter-new-pending').createdAt), captured.createdAt);
    };
    await expectCapturedDate();
    assert.equal(await page.evaluate(() => processWrongQuestionRetestReply({ id: 'filter-local-retest',
      retest: { wrongQuestionId: 'filter-new-pending', stage: 'checking', targetPoints: ['直接证明与反证法'],
        generatedQuestion: '本地复测题', generatedAnswer: '本地复测答案' } }, '答案正确')), true);
    await expectCapturedDate();
    assert.equal(await page.evaluate(async () => {
      const item = learningState.wrongQuestions.find(item => item.id === 'filter-new-pending');
      item.referenceAnswer = ''; item.answer = '';
      return generateWrongQuestionAnswer(item.id, { silent: true });
    }), true, 'The answer refresh uses one local mocked response');
    await expectCapturedDate();
    const clocks = await page.evaluate(() => {
      const item = learningState.wrongQuestions.find(item => item.id === 'filter-new-pending');
      const newer = { ...item, updatedAt: item.updatedAt + 1000, note: '最新同步内容' };
      const older = { ...item, createdAt: item.createdAt - 86400000, updatedAt: item.updatedAt - 1000 };
      const snapshot = entry => ({ learning: { wrongQuestions: [entry] } });
      const merged = [mergeCloudSnapshots(snapshot(older), snapshot(newer)),
        mergeCloudSnapshots(snapshot(newer), snapshot(older))].map(value => value.learning.wrongQuestions[0]);
      const legacy = normalizeLearningState({ wrongQuestions: [{ ...item, id: 'wrong-1700000000000-legacy',
        createdAt: undefined, updatedAt: item.updatedAt }] }).wrongQuestions[0];
      return { updatedAt: item.updatedAt, answerUpdatedAt: item.answerUpdatedAt, correctedAt: item.correctedAt,
        retestAt: item.lastRetestAt, retestCount: item.retestCount, legacyCreatedAt: legacy.createdAt,
        merged: merged.map(entry => ({ createdAt: entry.createdAt, updatedAt: entry.updatedAt, note: entry.note })) };
    });
    assert.ok(clocks.correctedAt > captured.updatedAt && clocks.retestAt >= clocks.correctedAt);
    assert.equal(clocks.retestCount, 1);
    assert.ok(clocks.answerUpdatedAt >= clocks.retestAt && clocks.updatedAt >= clocks.answerUpdatedAt,
      'Answer updates retain the existing sync clock');
    assert.deepEqual(clocks.merged, Array(2).fill({ createdAt: captured.createdAt - 86400000,
      updatedAt: clocks.updatedAt + 1000, note: '最新同步内容' }),
    'Both merge directions preserve the capture time independently of newer editable fields');
    assert.equal(clocks.legacyCreatedAt, 1700000000000, 'A legacy entry recovers its capture time from its stable ID');

    for (const [language, empty] of [['zh-CN', '无'], ['en', 'None']]) {
      await page.evaluate(language => DMateI18n.setLanguage(language, false), language);
      assert.equal(await page.locator('#wrongBookSearch').getAttribute('placeholder'), language === 'en' ? 'Search' : '搜索');
      await page.locator('#wrongBookSearch').fill('__no_matching_concept__');
      assert.equal(await page.locator('#wrongBookList .wrong-empty').innerText(), empty, 'No search match');
      await page.locator('#wrongBookSearch').fill('');
      for (const filter of ['pending', 'corrected']) {
        await page.evaluate(filter => {
          for (const item of learningState.wrongQuestions) item.corrected = filter === 'pending';
          setWrongBookFilter(filter);
        }, filter);
        assert.equal(await page.locator('#wrongBookList .wrong-empty').innerText(), empty, 'No ' + filter + ' records');
      }
    }
    await page.evaluate(() => DMateI18n.setLanguage('zh-CN', false));
    await page.locator('#wrongBookSearch').fill('集合运算');
    await page.evaluate(() => clearLoggedOutWorkspace());
    assert.deepEqual(await page.evaluate(() => [wrongBookFilter, wrongBookSearch, wrongBookSort]),
      ['pending', '', 'recent'], 'An account workspace reset returns to pending correction');
    await seed(page);
    await page.evaluate(() => openWrongBook());
    await expectFilter(page, 'pending', [questions.newPending, questions.oldPending]);
    assert.equal(await page.locator('#wrongBookSearch').inputValue(), '');
    assert.equal(await page.locator('#wrongBookSort').inputValue(), 'recent');
    assert.deepEqual(modelRequests, ['/chat'], 'Only the deliberate local answer refresh requests model output');
    assert.deepEqual(errors, [], 'No browser script errors');
    console.log('PASS ' + width + ': scoped concept search, bilingual empty states, stable capture dates and sync clocks, sticky filters and account reset');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const width of [390, 1440]) await runCase(browser, width);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
