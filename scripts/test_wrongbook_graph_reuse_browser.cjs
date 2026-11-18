/* Reuse actual registered question sources without inference during graph viewing. */
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
  await page.waitForFunction(() => typeof registeredQuestionSnapshot === 'function' && !accountVerificationOperation);
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
    renderAll(); saveLearningState();
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
    const source = await page.evaluate(question => {
      const resolved = wrongQuestionTeachingFromConversation(learningState.wrongQuestions[0], question);
      return { id: resolved?.sourceMessageId, solution: resolved?.solution };
    }, QUESTION);
    assert.deepEqual(source, { id: 'reuse-first', solution: FIRST },
      'the independent legacy source resolver still binds the unique actual question and answer');
    await openGraph(page);
    assert.deepEqual((await state(page)).ids, ['set_operation'],
      'a graded legacy record uses its own registered concepts immediately without waiting for chat hydration');
    const stored = await page.evaluate(() => {
      saveLearningState();
      const raw = shouldPersistClientState() ? JSON.parse(localStorage.getItem(LEARNING_STORAGE_KEY))
        : DMateGuestSession.read('learning');
      learningState = normalizeLearningState(raw);
      const entry = learningState.wrongQuestions[0], snapshot = entry.recognitionSnapshot;
      return { question: snapshot?.question, difficulty: snapshot?.difficulty, count: snapshot?.points.length };
    });
    assert.deepEqual(stored, { question: QUESTION, difficulty: '简单', count: 1 });
    await page.evaluate(() => closeKnowledgeGraph());
    await openGraph(page);
    assert.deepEqual((await state(page)).ids, ['set_operation']);
    assert.deepEqual(calls, []); assert.deepEqual(errors, []);
    console.log('PASS wrong-book reuse: unique actual sources and graded legacy snapshots survive save/load with zero viewing requests');
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
    const actual = await page.evaluate(question =>
      wrongQuestionTeachingFromConversation(learningState.wrongQuestions[0], question)?.solution, QUESTION);
    assert.equal(actual, FIRST + '\n\n' + SECOND,
      'generated source resolution preserves its actual hidden answer and visible explanation');
    await openGraph(page);
    assert.deepEqual((await state(page)).ids, ['set_operation'],
      'the wrong-book record displays its already registered question concepts without source re-analysis');
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
      const recognition = entry.recognitionSnapshot || registeredQuestionSnapshot(entry.questionTeaching, question);
      if (!recognition?.points.length) throw Error('The recognized concept list must survive an obsolete graph record');
    }, { question: QUESTION, answer: FIRST });
    await openGraph(page);
    assert.deepEqual((await state(page)).ids, ['set_operation']);
    assert.deepEqual(calls, []); assert.deepEqual(errors, []);
    console.log('PASS wrong-book reuse: recognized concepts survive obsolete graph records without a new request');
  } finally { await context.close(); }
}

async function checkAmbiguousAndNewAnalysis(browser) {
  const { context, page, errors, calls } = await fixturePage(browser);
  try {
    await seed(page, { duplicate: true });
    assert.equal(await page.evaluate(question =>
      wrongQuestionTeachingFromConversation(learningState.wrongQuestions[0], question), QUESTION), null,
      'a legacy entry without source identity cannot select an arbitrary duplicate conversation answer');
    await openGraph(page);
    assert.deepEqual((await state(page)).ids, ['set_operation'],
      'an ambiguous conversation origin does not discard this record\'s own recognized question concepts');
    assert.equal((await state(page)).solution, '', 'viewing the graph does not borrow a duplicate answer as its source');
    await page.evaluate(() => closeKnowledgeGraph());
    await seed(page, { analysis: ANALYSIS });
    await openGraph(page);
    assert.equal(await page.evaluate(() => getActiveKnowledgeContext().reviewSolutionText), ANALYSIS,
      'the actual newer wrong-book analysis remains the solution source');
    assert.deepEqual((await state(page)).ids, ['set_operation']);
    assert.deepEqual(await page.evaluate(() => knowledgeGraphDisplayedNodes().flatMap(node => node.prerequisites)), [],
      'question-only registered concepts do not invent dependencies from another conversation answer');
    assert.equal((await state(page)).solution, '', 'old conversation A is not copied over the newer own analysis B');
    assert.deepEqual(calls, []); assert.deepEqual(errors, []);
    console.log('PASS wrong-book reuse: ambiguous origins and newer analyses retain their own registered concepts without inference');
  } finally { await context.close(); }
}

async function checkLaterUnboundAnswer(browser) {
  const { context, page, errors, calls } = await fixturePage(browser);
  try {
    await seed(page, { sourceMessageId: 'reuse-first' });
    const result = await page.evaluate(({ question, later }) => {
      const entry = learningState.wrongQuestions[0];
      sessions[0].messages.push({ role: 'ai', messageId: 'legacy-later-answer', text: later });
      return { actual: wrongQuestionTeachingFromConversation(entry, question)?.solution,
        stored: entry.graphSolution };
    }, { question: QUESTION, later: ANALYSIS });
    assert.deepEqual(result, { actual: ANALYSIS, stored: '' },
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
