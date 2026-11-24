/* Viewing registered questions reads their saved recognition results only.
 * No test replaces a graph/source helper or permits a model request.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const QUESTION = '求集合 A={1,2,3} 与 B={2,4} 的交集，再从交集中选出一个元素，有多少种选法';
const ANSWER = '交集为 {2}，共有1种选法';
const EXPLANATION = '先确定交集，再从交集中无序选择一个元素';
const IDS = ['count_perm_comb', 'set_operation'];

async function settle(page) {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function fixturePage(browser, width) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block',
    ...(width <= 760 ? { isMobile: true, hasTouch: true } : {}) });
  const page = await context.newPage(), errors = [], modelCalls = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/auth/me', route => route.fulfill({ contentType: 'application/json',
    body: '{"configured":true,"authenticated":false}' }));
  await page.route(/\/(?:chat|ocr(?:\/[^?]*)?|graph\/[^?]*|analyze-questions|classify|conversation\/title)(?:\?|$)/, route => {
    modelCalls.push(new URL(route.request().url()).pathname);
    return route.abort();
  });
  await page.goto(baseURL, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => !accountVerificationOperation);
  await page.evaluate(async () => {
    DMateI18n.setLanguage('zh-CN', false);
    await ensureKnowledgeGraphData();
    window.__snapshotTeaching = (question, ids, { flat = false, solution = '', edgeSource = 'question' } = {}) => {
      const points = ids.map(id => findKnowledgeGraphNodeById(id).name);
      const teaching = { category: findKnowledgeGraphNodeById(ids[0]).category,
        knowledge_points: points.slice(0, 1), related_knowledge_points: points.slice(1), focus_points: points.slice(0, 1),
        related_categories: [], difficulty: '中等', confidence: '中', classification_source: 'local_structure',
        classification_revision: 'catalog-structure/2', classification_status: 'local', needs_review: true };
      if (!flat) teaching.question_graph = { version: 1, classifier_revision: 'catalog-structure/2',
        classification_source: 'local_structure', classification_status: 'local', needs_review: true,
        sources: { question, solution },
        nodes: ids.map(id => ({ id, origin: 'task_structure', usage: 'assessed',
          evidence: [{ source: 'question', quote: question }] })),
        edges: ids.length > 1 ? [{ from: ids[0], to: ids[1],
          evidence: [{ source: edgeSource, quote: edgeSource === 'solution' ? solution : '再从交集中选出一个元素' }] }] : [] };
      return teaching;
    };
    window.__snapshotSession = messages => ({ id: 'instant-snapshot-session', name: '已识别题目', nameSource: 'user',
      deletedMessageIds: {}, learningQuestion: null, messages });
    window.__snapshotSeed = messages => {
      sessions = [__snapshotSession(messages)]; currentId = sessions[0].id;
      learningState = createEmptyLearningState(); deletedSessionIds = Object.create(null); renderAll();
    };
  });
  modelCalls.length = 0;
  return { context, page, errors, modelCalls };
}

async function openRecent(page) {
  await page.evaluate(async () => {
    await openKnowledgeGraph(); selectKnowledgeGraphDisplayMode('focus');
  });
  await settle(page);
}

async function assertGraph(page, width, expected, expectedEdges, label) {
  const snapshot = await page.evaluate(() => {
    const context = getActiveKnowledgeContext(), nodes = knowledgeGraphDisplayedNodes(context);
    const names = new Map(nodes.map(node => [node.name, node.id]));
    return { ids: nodes.map(node => node.id).sort(),
      edges: nodes.flatMap(node => node.prerequisites.filter(name => names.has(name))
        .map(name => names.get(name) + '>' + node.id)).sort(),
      text: document.getElementById('knowledgeGraphCanvas').textContent };
  });
  assert.deepEqual(snapshot.ids, expected, label + ': saved recognized concepts are available without waiting');
  assert.deepEqual(snapshot.edges, expectedEdges, label + ': only recorded question-specific dependencies are drawn');
  assert.doesNotMatch(snapshot.text, /正在核对|归类暂未完成|暂时无法生成|Reviewing|classification is not complete/i,
    label + ': no review/verification gate is presented');
  assert.equal(await page.locator('.kg-empty-retry').count(), 0, label + ': viewing has no classification retry action');
  if (!expected.length) return;
  const rendered = await page.locator(width <= 760 ? '#knowledgeGraphCanvas .kg-mobile-node' : '#knowledgeGraphCanvas .kg-node-group')
    .evaluateAll(nodes => nodes.map(node => node.dataset.knowledgeNodeId).sort());
  assert.deepEqual(rendered, expected, label + ': actual graph renderer immediately draws the saved concepts');
}

async function checkManualAndOcr(browser, width) {
  const { context, page, errors, modelCalls } = await fixturePage(browser, width);
  try {
    for (const source of ['text', 'ocr']) {
      await page.evaluate(({ question, source }) => {
        const teaching = __snapshotTeaching(question, ['set_operation', 'count_perm_comb']);
        __snapshotSeed([{ role: 'user', messageId: 'registered-' + source, source,
          text: source === 'ocr' ? '【题目文字】\n' + question : question,
          ...(source === 'ocr' ? { ocrIsQuestion: true } : { manualIsQuestion: true }), questionTeaching: teaching }]);
      }, { question: QUESTION, source });
      await openRecent(page);
      await assertGraph(page, width, IDS, ['set_operation>count_perm_comb'], width + '/' + source);
      await page.evaluate(() => { closeKnowledgeGraph(); saveState(); loadState({ guest: true }); });
      await openRecent(page);
      await assertGraph(page, width, IDS, ['set_operation>count_perm_comb'], width + '/' + source + '/saved');
      await page.evaluate(() => closeKnowledgeGraph());
    }
    assert.deepEqual(modelCalls, []); assert.deepEqual(errors, []);
    console.log('PASS ' + width + ': manual and OCR difficulty snapshots render local results immediately, including save/load');
  } finally { await context.close(); }
}

async function checkHistoricalFlat(browser, width) {
  const { context, page, errors, modelCalls } = await fixturePage(browser, width);
  try {
    await page.evaluate(question => {
      const teaching = __snapshotTeaching(question, ['set_operation', 'count_perm_comb'], { flat: true });
      __snapshotSeed([{ role: 'user', messageId: 'historical-flat', text: question, manualIsQuestion: true,
        questionTeaching: teaching }]);
    }, QUESTION);
    await page.evaluate(async () => { await openKnowledgeGraph(); selectKnowledgeGraphDisplayMode('history'); });
    await page.locator('#knowledgeGraphHistory .kg-history-item[data-message-id="historical-flat"] [data-history-action="graph"]').click();
    await assertGraph(page, width, IDS, [], width + '/flat history');
    await page.evaluate(() => selectKnowledgeGraphDisplayMode('focus'));
    await assertGraph(page, width, IDS, [], width + '/flat recent');
    await page.evaluate(() => { closeKnowledgeGraph(); saveState(); loadState({ guest: true }); });
    await openRecent(page);
    await assertGraph(page, width, IDS, [], width + '/flat restored');
    assert.deepEqual(modelCalls, []); assert.deepEqual(errors, []);
    console.log('PASS ' + width + ': historical flat recognition labels are reused without another identification or course-neighbor expansion');
  } finally { await context.close(); }
}

async function checkWrongBookFlat(browser, width) {
  const { context, page, errors, modelCalls } = await fixturePage(browser, width);
  try {
    await page.evaluate(({ question, answer }) => {
      __snapshotSeed([{ role: 'user', messageId: 'unrelated-chat', text: '你好', manualIsQuestion: false }]);
      learningState = normalizeLearningState({ version: 9, events: [], wrongQuestions: [{
        id: 'instant-wrong', question, difficulty: '中等', category: '集合与关系',
        knowledgePoints: ['集合运算', '排列与组合'], focusPoints: ['集合运算'], classificationVersion: 0,
        corrected: false, source: 'manual', referenceAnswer: answer, answer, analysis: '',
        createdAt: 1, updatedAt: 1, sessionId: null
      }] });
      wrongBookFilter = 'pending'; wrongBookSearch = ''; renderAll(); openWrongBook();
    }, { question: QUESTION, answer: ANSWER });
    await page.locator('#wrongBookList [data-wrong-question-id="instant-wrong"] [data-wrong-action="graph"]').click();
    await assertGraph(page, width, IDS, [], width + '/wrong-book flat');
    await page.evaluate(() => {
      closeKnowledgeGraph(); saveLearningState();
      const saved = shouldPersistClientState() ? JSON.parse(localStorage.getItem(LEARNING_STORAGE_KEY))
        : DMateGuestSession.read('learning');
      learningState = normalizeLearningState(saved);
    });
    await page.evaluate(() => openWrongQuestionGraph('instant-wrong'));
    await assertGraph(page, width, IDS, [], width + '/wrong-book restored');
    assert.deepEqual(modelCalls, []); assert.deepEqual(errors, []);
    console.log('PASS ' + width + ': a rated wrong-book record opens and restores its saved concepts with zero model requests');
  } finally { await context.close(); }
}

async function checkGenerated(browser, width) {
  const { context, page, errors, modelCalls } = await fixturePage(browser, width);
  try {
    await page.evaluate(({ question, answer, explanation }) => {
      const solution = answer + '\n\n' + explanation;
      const teaching = __snapshotTeaching(question, ['set_operation', 'count_perm_comb'], { solution, edgeSource: 'solution' });
      __snapshotSeed([
        { role: 'user', messageId: 'exercise-request', text: '出一道集合和选择的题目', manualIsQuestion: false },
        { role: 'ai', messageId: 'generated-registered', generatedExercise: true, generatedQuestion: question,
          generatedAnswer: answer, generatedTeaching: teaching,
          text: '【题目】\n\n' + question + '\n\n【解析】\n\n' + explanation + '\n\n【涉及知识点】\n\n欧拉图' }
      ]);
    }, { question: QUESTION, answer: ANSWER, explanation: EXPLANATION });
    await openRecent(page);
    await assertGraph(page, width, IDS, ['set_operation>count_perm_comb'], width + '/generated');
    assert.deepEqual(modelCalls, []); assert.deepEqual(errors, []);
    console.log('PASS ' + width + ': generated questions reuse the saved hidden-answer/explanation result and ignore unrelated footer text');
  } finally { await context.close(); }
}

async function checkWrongBookWhileAnswerPending(browser) {
  const { context, page, errors, modelCalls } = await fixturePage(browser, 1440);
  let release;
  const allowed = new Promise(resolve => { release = resolve; });
  try {
    await page.route('**/chat', async route => {
      modelCalls.push('/chat');
      await allowed;
      const teaching = await page.evaluate(question =>
        __snapshotTeaching(question, ['set_operation', 'count_perm_comb'], { flat: true }), QUESTION);
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({
        reply: '[[ANSWER_ONLY]]' + ANSWER + '[[/ANSWER_ONLY]]', teaching
      }) });
    });
    const requested = page.waitForRequest('**/chat', { timeout: 10000 });
    await page.evaluate(question => {
      __snapshotSeed([{ role: 'user', messageId: 'unrelated-auto-answer-chat', text: '你好', manualIsQuestion: false }]);
      learningState = normalizeLearningState({ version: 9, events: [], wrongQuestions: [{
        id: 'answer-pending-wrong', question, difficulty: '中等', category: '集合与关系',
        knowledgePoints: ['集合运算', '排列与组合'], focusPoints: ['集合运算'], classificationVersion: 0,
        corrected: false, source: 'manual', referenceAnswer: '', answer: '', analysis: '',
        createdAt: 1, updatedAt: 1, sessionId: null
      }] });
      wrongBookFilter = 'pending'; wrongBookSearch = ''; renderAll(); openWrongBook();
    }, QUESTION);
    await requested;
    const beforeGraph = [...modelCalls];
    assert.deepEqual(beforeGraph, ['/chat'], 'the existing missing-answer feature may run its one answer request');
    await page.locator('#wrongBookList [data-wrong-question-id="answer-pending-wrong"] [data-wrong-action="graph"]').click();
    await assertGraph(page, 1440, IDS, [], 'wrong-book while its optional answer is still pending');
    assert.deepEqual(modelCalls, beforeGraph, 'opening the graph neither waits for nor adds a request to the pending answer');
    release();
    await page.waitForFunction(() => Boolean(learningState.wrongQuestions[0]?.answer));
    await assertGraph(page, 1440, IDS, [], 'wrong-book after its optional answer completes');
    assert.deepEqual(modelCalls, beforeGraph); assert.deepEqual(errors, []);
    console.log('PASS optional wrong-book answer preparation does not delay the already-recognized graph or trigger a second request');
  } finally { release(); await context.close(); }
}

async function checkAnswerCompletion(browser) {
  const { context, page, errors, modelCalls } = await fixturePage(browser, 1440);
  try {
    for (const generated of [false, true]) {
      await page.route('**/chat', async route => {
        modelCalls.push('/chat');
        const teaching = await page.evaluate(({ question, answer }) =>
          __snapshotTeaching(question, ['set_operation', 'count_perm_comb'], { solution: answer }),
        { question: QUESTION, answer: ANSWER });
        const body = generated ? { reply: '【题目】\n\n' + QUESTION, teaching, generated_teaching: teaching,
          generated_question: QUESTION, generated_answer: ANSWER, generated_exercise: true }
          : { reply: ANSWER, teaching, generated_exercise: false };
        await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
      });
      await page.evaluate(({ question, generated }) => {
        __snapshotSeed([{ role: 'user', messageId: generated ? 'answer-generation-command' : 'answer-question',
          text: generated ? '出一道集合运算和选择的题目' : question,
          manualIsQuestion: !generated,
          ...(!generated ? { questionTeaching: __snapshotTeaching(question, ['set_operation', 'count_perm_comb']) } : {}) }]);
      }, { question: QUESTION, generated });
      const before = modelCalls.length;
      const outcome = await page.evaluate(() => requestAiReply(getCurrent(), { completeImmediately: true }));
      assert.equal(outcome.status, 'success', (generated ? 'generated' : 'ordinary') + ' answer completes normally');
      assert.deepEqual(modelCalls.slice(before), ['/chat'], 'the ordinary answer/generation request adds no separate classification request');
      await openRecent(page);
      await assertGraph(page, 1440, IDS, ['set_operation>count_perm_comb'], generated ? 'completed generated question' : 'completed answer');
      assert.deepEqual(modelCalls.slice(before), ['/chat'], 'viewing the completed answer uses the same saved recognition result');
      await page.evaluate(() => closeKnowledgeGraph());
    }
    assert.deepEqual(errors, []);
    console.log('PASS ordinary and generated answer commits save their recognized graph without a post-answer review request');
  } finally { await context.close(); }
}

async function checkSourceAndCatalogBoundary(browser, width) {
  const { context, page, errors, modelCalls } = await fixturePage(browser, width);
  try {
    await page.evaluate(question => {
      __snapshotSeed([{ role: 'user', messageId: 'edited-original', text: question, manualIsQuestion: true,
        questionTeaching: __snapshotTeaching(question, ['set_operation', 'count_perm_comb']) }]);
    }, QUESTION);
    await openRecent(page);
    await assertGraph(page, width, IDS, ['set_operation>count_perm_comb'], width + '/before edit');
    await page.evaluate(() => {
      sessions[0].messages[0].text = '判断 f(x)=2x 是否能取到每一个整数';
      renderKnowledgeGraph();
    });
    await assertGraph(page, width, [], [], width + '/edited source');
    await page.evaluate(() => {
      const prefix = '设有限集合 A 与 B，以下固定条件保持不变。'.repeat(150);
      const original = prefix + '求两个集合的交集';
      const changed = prefix + '判断函数是否为满射';
      __snapshotSeed([{ role: 'user', messageId: 'long-mismatch', text: changed, manualIsQuestion: true,
        questionTeaching: __snapshotTeaching(original, ['set_operation']) }]);
    });
    await openRecent(page);
    await assertGraph(page, width, [], [], width + '/same-prefix foreign snapshot');
    await page.evaluate(() => {
      const question = '解释函数的性质';
      __snapshotSeed([{ role: 'user', messageId: 'unknown-label', text: question, manualIsQuestion: true,
        questionTeaching: { category: '函数', difficulty: '简单', knowledge_points: ['非现有图谱中的标签'], focus_points: [] } }]);
    });
    await openRecent(page);
    await assertGraph(page, width, [], [], width + '/unknown catalog label');
    assert.deepEqual(modelCalls, []); assert.deepEqual(errors, []);
    console.log('PASS ' + width + ': stale/foreign sources and unknown labels are not replaced by unrelated course nodes or a new model request');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const width of [1440, 390]) {
      await checkManualAndOcr(browser, width);
      await checkHistoricalFlat(browser, width);
      await checkWrongBookFlat(browser, width);
      await checkGenerated(browser, width);
      await checkSourceAndCatalogBoundary(browser, width);
    }
    await checkWrongBookWhileAnswerPending(browser);
    await checkAnswerCompletion(browser);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
