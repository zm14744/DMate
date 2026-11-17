/* Exercise the actual wrong-book opening order: batch repair starts before
 * the user opens a card graph. All provider work stays isolated locally.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const QUESTION = '求集合 A={1,2} 与 B={2,3} 的交集';
const ANSWER = '{2}';

function teaching(question, solution, status = 'semantic') {
  const ready = status === 'semantic';
  return { category: '集合与关系', knowledge_points: ['集合运算'], focus_points: ['集合运算'],
    difficulty: '简单', classification_revision: ready ? 'catalog-semantic-v5' : 'catalog-structure/2',
    classification_status: status, classification_source: ready ? 'AI语义复核' : 'local_structure', needs_review: !ready,
    question_graph: { version: 1, sources: { question, solution },
      classifier_revision: ready ? 'catalog-semantic-v5' : 'catalog-structure/2',
      classification_source: ready ? 'catalog_semantic' : 'local_structure',
      classification_status: status, needs_review: !ready,
      nodes: [{ id: ready ? 'set_operation' : 'count_inclusion', usage: 'assessed',
        reason: ready ? '题目要求计算两个有限集合的交集' : '尚未经过语义核对的本地候选',
        evidence: [{ source: 'question', quote: ready ? '交集' : question }] }], edges: [] } };
}

async function settle(page) {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function fixture(browser, width = 1440, clock = false) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block',
    ...(width <= 760 ? { isMobile: true, hasTouch: true } : {}) });
  const page = await context.newPage(), errors = [], unexpected = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/auth/me', route => route.fulfill({ contentType: 'application/json',
    body: '{"configured":true,"authenticated":false}' }));
  await page.route(/\/(?:chat|conversation\/title|classify|analyze-questions|ocr)(?:\?|$)/, route => {
    unexpected.push(new URL(route.request().url()).pathname); return route.abort();
  });
  await page.goto(baseURL, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => typeof openWrongQuestionGraph === 'function' && !accountVerificationOperation);
  await page.evaluate(async () => { DMateI18n.setLanguage('zh-CN', false); await ensureKnowledgeGraphData(); });
  if (clock) await page.clock.install();
  return { context, page, errors, unexpected };
}

async function seed(page, classificationVersion = 0) {
  await page.evaluate(({ question, answer, classificationVersion }) => {
    sessions = []; currentId = null;
    learningState = normalizeLearningState({ events: [], wrongQuestions: [{
      id: 'pending-graph-entry', question, referenceAnswer: answer, answer, analysis: '', source: 'manual',
      focusPoints: ['集合运算'], knowledgePoints: ['集合运算'], category: '集合与关系', difficulty: '简单',
      classificationVersion, corrected: false, createdAt: 1, updatedAt: 1
    }] });
    wrongBookFilter = 'pending'; wrongBookSearch = ''; renderAll(); openWrongBook();
  }, { question: QUESTION, answer: ANSWER, classificationVersion });
}

async function openGraph(page) {
  await page.locator('[data-wrong-question-id="pending-graph-entry"] [data-wrong-action="graph"]').click();
  await page.locator('#knowledgeGraphModal').waitFor({ state: 'visible' });
  await page.waitForFunction(() => document.getElementById('knowledgeGraphModal').dataset.graphReady === 'true');
  await settle(page);
}

async function ids(page) {
  return page.evaluate(() => knowledgeGraphDisplayedNodes(getActiveKnowledgeContext()).map(node => node.id).sort());
}

async function complete(page, route, status = 'semantic') {
  const body = route.request().postDataJSON(), item = body.questions[0];
  assert.equal(body.semantic_fallback, true);
  assert.equal(item.text, QUESTION);
  assert.equal(item.solution, ANSWER);
  await route.fulfill({ contentType: 'application/json', body: JSON.stringify({
    results: [{ key: item.key, teaching: teaching(item.text, item.solution, status) }]
  }) });
}

async function waitReady(page) {
  await page.waitForFunction(() => knowledgeGraphDisplayedNodes(getActiveKnowledgeContext()).some(node => node.id === 'set_operation'));
  assert.deepEqual(await ids(page), ['set_operation']);
  assert.equal(await page.locator('#knowledgeGraphCanvas > .kg-empty').count(), 0);
  assert.equal(await page.locator('#knowledgeGraphWrongBtn').count(), 0, 'redundant top-level wrong-question button stays removed');
}

async function checkBatchJoin(browser, width) {
  const { context, page, errors, unexpected } = await fixture(browser, width);
  const requests = [];
  let release;
  const allowed = new Promise(resolve => { release = resolve; });
  try {
    await page.route('**/analyze-questions', async route => {
      requests.push(route.request().postDataJSON()); await allowed; await complete(page, route);
    });
    await seed(page);
    await page.waitForFunction(() => wrongBookClassificationInFlight);
    await openGraph(page);
    assert.equal(requests.length, 1, 'opening a graph joins the batch already started by opening the wrong book');
    assert.deepEqual(await ids(page), [], 'local candidate tags cannot masquerade as confirmed purple points');
    assert.match(await page.locator('#knowledgeGraphCanvas').innerText(), /正在核对/);
    await page.evaluate(() => { for (let i = 0; i < 12; i++) renderKnowledgeGraph(); });
    assert.equal(requests.length, 1, 'rendering while the existing batch is pending never duplicates its request');
    release();
    await waitReady(page);
    assert.equal(requests.length, 1, 'the completed batch makes the open graph appear without closing or reopening it');
    assert.equal(await page.evaluate(() => learningState.wrongQuestions[0].questionTeaching.question_graph.sources.solution), ANSWER);
    assert.deepEqual(errors, []); assert.deepEqual(unexpected, []);
    console.log(`PASS ${width}: real wrong-book batch/open order shares one request and updates the open graph`);
  } finally { release(); await context.close(); }
}

async function checkTransientPending(browser) {
  const { context, page, errors, unexpected } = await fixture(browser);
  let requests = 0;
  try {
    await page.route('**/analyze-questions', async route => { requests += 1; await complete(page, route, requests === 1 ? 'pending' : 'semantic'); });
    // A legacy record can have complete flat classifications but no saved
    // graph. Its selected graph needs review, independently of bulk repair.
    await seed(page, 3); await openGraph(page);
    await page.waitForFunction(() => wrongQuestionGraphRetry !== null);
    assert.match(await page.locator('#knowledgeGraphCanvas').innerText(), /正在核对/,
      'another client/server in-flight result remains pending instead of becoming a permanent failure');
    assert.deepEqual(await ids(page), []);
    await page.evaluate(() => { for (let i = 0; i < 20; i++) renderKnowledgeGraph(); });
    assert.equal(requests, 1);
    await waitReady(page);
    assert.equal(requests, 2, 'a bounded delayed follow-up consumes the source-exact result after in-flight work completes');
    assert.equal(await page.evaluate(() => wrongQuestionGraphRetry), null);
    assert.deepEqual(errors, []); assert.deepEqual(unexpected, []);
    console.log('PASS transient server-pending result recovers automatically without rendering local guesses');
  } finally { await context.close(); }
}

async function checkNewAnalysisReplacesHeldBatch(browser) {
  const { context, page, errors, unexpected } = await fixture(browser);
  const analysis = '分别检查元素1、2、3，只有元素2同时属于A和B，因此交集为{2}';
  let analyzeRequests = 0, chatRequests = 0, release;
  const held = new Promise(resolve => { release = resolve; });
  try {
    await page.route('**/analyze-questions', async route => {
      analyzeRequests += 1; await held; await complete(page, route);
    });
    await page.route('**/chat', async route => {
      chatRequests += 1;
      const body = route.request().postDataJSON();
      assert.equal(body.question_context.question, QUESTION, 'the existing analysis request remains bound to its exact wrong question');
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({
        reply: analysis, teaching: teaching(QUESTION, analysis)
      }) });
    });
    await seed(page); await openGraph(page);
    assert.equal(analyzeRequests, 1);
    assert.deepEqual(await ids(page), []);
    await page.evaluate(() => generateWrongQuestionAnalysis('pending-graph-entry'));
    await page.locator('#knowledgeGraphCanvas .kg-node-group[data-knowledge-node-id="set_operation"]').waitFor({ state: 'visible' });
    const currentSource = () => page.evaluate(() => ({
      analysis: learningState.wrongQuestions[0].analysis,
      graph: learningState.wrongQuestions[0].questionTeaching.question_graph.sources.solution,
      rendered: knowledgeGraphRenderedQuestion.context.reviewSolutionText
    }));
    assert.deepEqual(await currentSource(), { analysis, graph: analysis, rendered: analysis },
      'the newly completed actual analysis repaints the already-open graph immediately');
    assert.equal(chatRequests, 1); assert.equal(analyzeRequests, 1,
      'inline metadata from the existing analysis request needs no extra classification request');
    release();
    await page.waitForFunction(() => !wrongBookClassificationInFlight
      && !knowledgeGraphWrongQuestionAnalyses.get(learningState.wrongQuestions[0]).inFlight);
    assert.deepEqual(await currentSource(), { analysis, graph: analysis, rendered: analysis },
      'the older answer-A batch cannot replace or blank the newer analysis-B graph');
    assert.deepEqual(await ids(page), ['set_operation']);
    assert.equal(analyzeRequests, 1); assert.equal(chatRequests, 1);
    assert.deepEqual(errors, []); assert.deepEqual(unexpected, []);
    console.log('PASS a new actual analysis repaints its inline graph while the older batch remains source-isolated');
  } finally { release(); await context.close(); }
}

async function checkHungBatchRecovery(browser) {
  const { context, page, errors, unexpected } = await fixture(browser, 1440, true);
  let requests = 0, release;
  const held = new Promise(resolve => { release = resolve; });
  try {
    await page.route('**/analyze-questions', async route => {
      requests += 1;
      if (requests === 1) {
        await held;
        try { await route.abort(); } catch (_) { /* The browser already aborted the timed-out request. */ }
      } else await complete(page, route);
    });
    await seed(page); await openGraph(page);
    assert.equal(requests, 1);
    await page.clock.fastForward(30001);
    await page.waitForFunction(() => !wrongBookClassificationInFlight && wrongBookClassificationRequests.size === 0
      && wrongQuestionGraphRetry !== null);
    assert.equal(requests, 1, 'the batch deadline releases its waiters without an immediate duplicate provider request');
    await page.clock.fastForward(16001);
    await waitReady(page);
    assert.equal(requests, 2, 'a source-bound retry recovers after the failed-result cache window');
    assert.deepEqual(errors, []); assert.deepEqual(unexpected, []);
    console.log('PASS a hung wrong-book batch has a deadline and its open graph recovers automatically');
  } finally { release(); await context.close(); }
}

async function checkBoundedRetryAndManualRecovery(browser) {
  const { context, page, errors, unexpected } = await fixture(browser, 1440, true);
  let requests = 0;
  try {
    await page.route('**/analyze-questions', async route => { requests += 1; await complete(page, route, requests <= 5 ? 'pending' : 'semantic'); });
    await seed(page, 3); await openGraph(page);
    for (const delay of [1100, 2100, 4100, 8100]) {
      const before = requests;
      await page.waitForFunction(() => wrongQuestionGraphRetry !== null);
      await page.clock.fastForward(delay);
      await page.waitForFunction(expected => {
        const operation = knowledgeGraphWrongQuestionAnalyses.get(learningState.wrongQuestions[0]);
        return operation && !operation.inFlight && operation.retryCount === expected;
      }, before);
      assert.equal(requests, before + 1);
    }
    assert.equal(requests, 5, 'four bounded follow-ups span the server worker deadline');
    await page.locator('#knowledgeGraphCanvas .kg-empty-retry').waitFor({ state: 'visible' });
    await page.clock.fastForward(120000);
    await page.evaluate(() => { for (let i = 0; i < 20; i++) renderKnowledgeGraph(); });
    assert.equal(requests, 5, 'exhaustion stops automatic requests while the same graph stays open');
    await page.locator('#knowledgeGraphCanvas .kg-empty-retry').click();
    await waitReady(page);
    assert.equal(requests, 6, 'a later explicit retry starts a fresh operation and can recover');
    assert.deepEqual(errors, []); assert.deepEqual(unexpected, []);
    console.log('PASS pending follow-ups are bounded and exhausted failures remain explicitly recoverable');
  } finally { await context.close(); }
}

async function checkCloseAndSourceGuards(browser) {
  for (const change of ['close-reopen', 'edit', 'delete', 'owner']) {
    const { context, page, errors, unexpected } = await fixture(browser, 1440, true);
    let requests = 0;
    try {
      await page.route('**/analyze-questions', async route => { requests += 1; await complete(page, route, requests === 1 ? 'pending' : 'semantic'); });
      await seed(page, 3); await openGraph(page);
      await page.waitForFunction(() => wrongQuestionGraphRetry !== null);
      if (change === 'close-reopen') {
        await page.locator('#knowledgeGraphClose').click();
        assert.equal(await page.evaluate(() => wrongQuestionGraphRetry), null);
      } else await page.evaluate(change => {
        if (change === 'edit') learningState.wrongQuestions[0].question = '求另一个集合的并集';
        if (change === 'delete') learningState.wrongQuestions = [];
        if (change === 'owner') { bumpCloudSyncContext(); clearLoggedOutWorkspace(); }
        renderKnowledgeGraph();
      }, change);
      await page.clock.fastForward(2000);
      assert.equal(requests, 1, change + ': obsolete timers never issue a source or account-mismatched request');
      if (change === 'close-reopen') {
        await openGraph(page); await page.clock.fastForward(1); await waitReady(page);
        assert.equal(requests, 2, 'reopening resumes the cancelled due retry without being stuck in a stale pending operation');
      } else if (change === 'owner') {
        const cleared = await page.evaluate(() => ({ mode: knowledgeGraphViewMode,
          wrong: learningState.wrongQuestions.length, source: getWrongQuestionGraphSubject(),
          purple: knowledgeGraphDisplayedNodes(getActiveKnowledgeContext()).filter(node =>
            knowledgeGraphNodeState(node.name, getActiveKnowledgeContext()).fill === '#5b21b6').length }));
        assert.deepEqual(cleared, { mode: 'full', wrong: 0, source: null, purple: 0 },
          'an owner reset may show the public course catalog, while retaining no former wrong-question evidence');
      } else assert.deepEqual(await ids(page), [], change + ': obsolete question evidence is never rendered');
      assert.deepEqual(errors, []); assert.deepEqual(unexpected, []);
      console.log('PASS wrong-question retry lifecycle: ' + change);
    } finally { await context.close(); }
  }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const width of [1440, 390]) await checkBatchJoin(browser, width);
    await checkTransientPending(browser);
    await checkNewAnalysisReplacesHeldBatch(browser);
    await checkHungBatchRecovery(browser);
    await checkBoundedRetryAndManualRecovery(browser);
    await checkCloseAndSourceGuards(browser);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
