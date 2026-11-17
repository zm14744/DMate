/* Reuse actual question/answer sources before scheduling another graph review. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const QUESTION = '求集合 A={1,2} 与 B={2,3} 的交集';
const FIRST = '交集为 {2}';
const SECOND = '逐个比较元素，交集为 {2}';
const ANALYSIS = '使用元素隶属的等价条件，交集为 {2}';

async function fixturePage(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: 'block' });
  const page = await context.newPage(), errors = [], calls = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/auth/me', route => route.fulfill({ contentType: 'application/json',
    body: '{"configured":true,"authenticated":false}' }));
  await page.route(/\/(?:chat|conversation\/title|classify|analyze-questions|ocr)(?:\?|$)/, route => {
    calls.push(new URL(route.request().url()).pathname);
    return route.abort();
  });
  await page.goto(baseURL, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => typeof hydrateWrongQuestionGraph === 'function' && !accountVerificationOperation);
  await page.evaluate(async () => {
    DMateI18n.setLanguage('zh-CN', false);
    await ensureKnowledgeGraphData();
    window.__reuseTeaching = (question, solution) => ({
      category: '集合与关系', related_categories: [], knowledge_points: ['集合运算'],
      related_knowledge_points: [], focus_points: ['集合运算'], difficulty: '简单',
      classification_revision: 'catalog-semantic-v5', classification_status: 'semantic',
      classification_source: 'AI语义复核', needs_review: false,
      question_graph: { version: 1, classifier_revision: 'catalog-semantic-v5',
        classification_status: 'semantic', classification_source: 'catalog_semantic', needs_review: false,
        sources: { question, solution }, nodes: [{ id: 'set_operation', usage: 'assessed',
          reason: '题目要求计算两个集合的交集', origin: 'catalog_semantic',
          evidence: [{ source: 'question', quote: '交集' }] }], edges: [] }
    });
    window.__reuseEntry = (question, answer, extra = {}) => ({
      id: 'reuse-entry', question, sessionId: 'reuse-session', category: '集合与关系',
      knowledgePoints: ['集合运算'], focusPoints: ['集合运算'], difficulty: '简单',
      classificationVersion: 2, referenceAnswer: answer, answer, analysis: '',
      corrected: false, createdAt: 1, updatedAt: 1, ...extra
    });
  });
  return { context, page, errors, calls };
}

async function seed(page, { duplicate = false, sourceMessageId = '', analysis = '' } = {}) {
  await page.evaluate(({ question, first, second, duplicate, sourceMessageId, analysis }) => {
    const messages = [
      { role: 'user', messageId: 'reuse-first', manualIsQuestion: true, text: question,
        questionTeaching: __reuseTeaching(question, first) },
      { role: 'ai', messageId: 'reuse-first-answer', targetQuestionMessageId: 'reuse-first', text: first }
    ];
    if (duplicate) messages.push(
      { role: 'user', messageId: 'reuse-second', manualIsQuestion: true, text: question,
        questionTeaching: __reuseTeaching(question, second) },
      { role: 'ai', messageId: 'reuse-second-answer', targetQuestionMessageId: 'reuse-second', text: second }
    );
    sessions = [{ id: 'reuse-session', name: '实际题目来源', nameSource: 'user', deletedMessageIds: {}, messages }];
    currentId = 'reuse-session';
    learningState = normalizeLearningState({ version: 9, events: [], wrongQuestions: [
      __reuseEntry(question, sourceMessageId === 'reuse-second' ? second : first, { sourceMessageId, analysis })
    ] });
    renderAll();
  }, { question: QUESTION, first: FIRST, second: SECOND, duplicate, sourceMessageId, analysis });
}

async function openGraph(page, id = 'reuse-entry') {
  await page.evaluate(id => openWrongQuestionGraph(id), id);
  await page.waitForFunction(() => document.getElementById('knowledgeGraphModal').dataset.graphReady === 'true');
}

async function state(page) {
  return page.evaluate(() => {
    const entry = learningState.wrongQuestions[0];
    const stored = shouldPersistClientState() ? JSON.parse(localStorage.getItem(LEARNING_STORAGE_KEY))
      : DMateGuestSession.read('learning');
    return { source: entry.sourceMessageId, solution: entry.graphSolution,
      status: entry.questionTeaching?.question_graph?.classification_status,
      ids: knowledgeGraphDisplayedNodes().map(node => node.id),
      storedSource: normalizeLearningState(stored).wrongQuestions[0]?.sourceMessageId };
  });
}

async function checkLaterDuplicate(browser) {
  const { context, page, errors, calls } = await fixturePage(browser);
  try {
    await seed(page, { duplicate: true });
    const id = await page.evaluate(second => {
      learningState = createEmptyLearningState();
      const info = questionInfoFromChatMessage(sessions[0], 2);
      return addWrongQuestion({ ...info, referenceAnswer: second, safeConfirmed: true }, '', 'manual').entry.id;
    }, SECOND);
    await openGraph(page, id);
    assert.deepEqual(await state(page), { source: 'reuse-second', solution: SECOND, status: 'semantic',
      ids: ['set_operation'], storedSource: 'reuse-second' },
    'a clicked later duplicate keeps its own stable source and actual answer instead of the deduplicated first entry');
    assert.deepEqual(calls, []); assert.deepEqual(errors, []);
    console.log('PASS wrong-book reuse: later identical question retains its own reviewed answer and stable identity');
  } finally { await context.close(); }
}

async function checkLegacyUnique(browser) {
  const { context, page, errors, calls } = await fixturePage(browser);
  try {
    await seed(page);
    await openGraph(page);
    assert.deepEqual(await state(page), { source: 'reuse-first', solution: FIRST, status: 'semantic',
      ids: ['set_operation'], storedSource: 'reuse-first' },
    'a unique legacy question reuses its existing reviewed conversation result and saves its source');
    await page.evaluate(() => {
      closeKnowledgeGraph();
      const stored = shouldPersistClientState() ? JSON.parse(localStorage.getItem(LEARNING_STORAGE_KEY))
        : DMateGuestSession.read('learning');
      learningState = normalizeLearningState(stored);
    });
    await openGraph(page);
    assert.deepEqual(calls, []); assert.deepEqual(errors, []);
    console.log('PASS wrong-book reuse: legacy unique source hydrates immediately and survives actual save/load');
  } finally { await context.close(); }
}

async function checkGeneratedComposite(browser) {
  const { context, page, errors, calls } = await fixturePage(browser);
  try {
    await page.evaluate(({ question, answer, explanation }) => {
      const solution = answer + '\n\n' + explanation;
      sessions = [{ id: 'reuse-session', name: '生成题', nameSource: 'user', deletedMessageIds: {}, messages: [
        { role: 'user', messageId: 'generation-request', text: '出一道集合题并给解析' },
        { role: 'ai', messageId: 'generated-question', generatedExercise: true, generatedQuestion: question,
          generatedAnswer: answer, text: '【题目】\n\n' + question + '\n\n【解析】\n\n' + explanation,
          generatedTeaching: __reuseTeaching(question, solution) }
      ] }];
      currentId = 'reuse-session';
      learningState = normalizeLearningState({ version: 9, events: [], wrongQuestions: [__reuseEntry(question, answer)] });
      renderAll();
    }, { question: QUESTION, answer: FIRST, explanation: SECOND });
    await openGraph(page);
    assert.deepEqual(await state(page), { source: 'generated-question', solution: FIRST + '\n\n' + SECOND,
      status: 'semantic', ids: ['set_operation'], storedSource: 'generated-question' });
    assert.deepEqual(calls, []); assert.deepEqual(errors, []);
    console.log('PASS wrong-book reuse: unique generated source validates hidden answer and actual explanation composite');
  } finally { await context.close(); }
}

async function checkEmptyReviewedSnapshot(browser) {
  const { context, page, errors, calls } = await fixturePage(browser);
  try {
    await seed(page);
    await page.evaluate(({ question, answer }) => {
      const entry = learningState.wrongQuestions[0];
      entry.questionTeaching = __reuseTeaching(question, answer);
      entry.questionTeaching.question_graph.nodes[0].id = 'obsolete-catalog-id';
      entry.graphSolution = answer;
      if (isWrongQuestionGraphReady(wrongQuestionGraphContext(entry, null))) {
        throw Error('Undrawable legacy metadata cannot be treated as a completed graph');
      }
    }, { question: QUESTION, answer: FIRST });
    await openGraph(page);
    assert.deepEqual((await state(page)).ids, ['set_operation']);
    assert.deepEqual(calls, []); assert.deepEqual(errors, []);
    console.log('PASS wrong-book reuse: completed flags on an undrawable snapshot recover from actual reviewed sources');
  } finally { await context.close(); }
}

async function checkAmbiguousAndNewAnalysis(browser) {
  const { context, page, errors, calls } = await fixturePage(browser);
  let release = () => {};
  try {
    await seed(page, { duplicate: true });
    assert.equal(await page.evaluate(() => hydrateWrongQuestionGraph(learningState.wrongQuestions[0])), false,
      'a legacy entry without source identity cannot select a duplicate merely because it is active');
    await seed(page, { analysis: ANALYSIS });
    assert.equal(await page.evaluate(() => hydrateWrongQuestionGraph(learningState.wrongQuestions[0])), false,
      'an independently newer wrong-book analysis cannot be replaced by a different conversation answer');
    let requested;
    const ready = new Promise(resolve => { requested = resolve; });
    const allowed = new Promise(resolve => { release = resolve; });
    await page.route('**/analyze-questions', async route => {
      const body = route.request().postDataJSON(); requested(body); await allowed;
      const item = body.questions[0];
      const teaching = await page.evaluate(item => __reuseTeaching(item.text, item.solution || ''), item);
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ results: [{ key: item.key, teaching }] }) });
    });
    await openGraph(page);
    const body = await ready;
    assert.equal(body.semantic_fallback, true);
    assert.equal(body.questions[0].text, QUESTION);
    assert.equal(body.questions[0].solution, ANALYSIS);
    assert.deepEqual((await state(page)).ids, [], 'old conversation A is not painted while actual analysis B is reviewed');
    release();
    await page.waitForFunction(analysis => learningState.wrongQuestions[0].graphSolution === analysis, ANALYSIS);
    assert.equal((await state(page)).solution, ANALYSIS);
    assert.deepEqual((await state(page)).ids, ['set_operation']);
    assert.deepEqual(calls, []); assert.deepEqual(errors, []);
    console.log('PASS wrong-book reuse: ambiguous origins abstain and new own-analysis sources receive their own review');
  } finally { release(); await context.close(); }
}

async function checkLaterUnboundAnswer(browser) {
  const { context, page, errors, calls } = await fixturePage(browser);
  try {
    await seed(page, { sourceMessageId: 'reuse-first' });
    const result = await page.evaluate(({ question, later }) => {
      const entry = learningState.wrongQuestions[0];
      sessions[0].messages.push({ role: 'ai', messageId: 'legacy-later-answer', text: later });
      return { actual: wrongQuestionTeachingFromConversation(entry, question)?.solution,
        reused: hydrateWrongQuestionGraph(entry) };
    }, { question: QUESTION, later: ANALYSIS });
    assert.deepEqual(result, { actual: ANALYSIS, reused: false },
      'a later eligible unbound answer must supersede the earlier explicit answer through legacy ownership checks');
    assert.deepEqual(calls, []); assert.deepEqual(errors, []);
    console.log('PASS wrong-book reuse: direct source lookup retains later legacy-answer ownership checks');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    await checkLaterDuplicate(browser); await checkLegacyUnique(browser);
    await checkGeneratedComposite(browser); await checkEmptyReviewedSnapshot(browser);
    await checkAmbiguousAndNewAnalysis(browser); await checkLaterUnboundAnswer(browser);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
