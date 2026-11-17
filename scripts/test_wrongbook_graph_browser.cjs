/* Wrong-question graphs use their own saved source pair and return to the
 * matching wrong-book record. Model/account routes are isolated in this suite.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const MAIN = '先求集合 A={1,2,3} 与 B={2,3,4} 的交集，再从交集中选出一个元素，有多少种选法';
const OTHER = '求集合 C={4,5} 与 D={5,6} 的交集';
const ANSWER = '交集为 {2,3}，共有2种选法';
const EXPECTED = ['count_perm_comb', 'set_operation'];

async function settle(page) {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function bounded(promise, label) {
  let timer;
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(Error(label)), 10000);
    })]);
  } finally { clearTimeout(timer); }
}

async function fixturePage(browser, width) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block',
    ...(width <= 760 ? { isMobile: true, hasTouch: true } : {}) });
  const page = await context.newPage(), errors = [], modelCalls = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/auth/me', route => route.fulfill({ contentType: 'application/json',
    body: '{"configured":true,"authenticated":false}' }));
  await page.route(/\/(?:chat|conversation\/title|classify|analyze-questions|ocr)(?:\?|$)/, route => {
    modelCalls.push(new URL(route.request().url()).pathname);
    return route.abort();
  });
  await page.goto(baseURL, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => typeof openWrongQuestionGraph === 'function' && !accountVerificationOperation);
  await page.evaluate(async () => {
    DMateI18n.setLanguage('zh-CN', false);
    await ensureKnowledgeGraphData();
    window.__wrongGraphTeaching = (question, solution, ids = ['set_operation', 'count_perm_comb']) => {
      const catalog = new Map(knowledgeGraphData.nodes.map(node => [node.id, node]));
      const points = ids.map(id => catalog.get(id).name);
      return { category: catalog.get(ids[0]).category, related_categories: ['计数与组合'],
        knowledge_points: [points[0]], related_knowledge_points: points.slice(1), focus_points: [points[0]],
        classification_revision: 'catalog-semantic-v5', classification_status: 'semantic',
        classification_source: 'AI语义复核', needs_review: false, difficulty: '简单',
        question_graph: { version: 1, classifier_revision: 'catalog-semantic-v5',
          classification_status: 'semantic', classification_source: 'catalog_semantic', needs_review: false,
          sources: { question, solution }, nodes: ids.map(id => ({ id, usage: 'assessed', origin: 'catalog_semantic',
            reason: id === 'set_operation' ? '题目要求求两个有限集合的交集' : '题目要求从已求出的交集中无序选择元素',
            evidence: [{ source: 'question', quote: id === 'set_operation' ? '交集' : '从交集中选出一个元素' }] })),
          edges: ids.length > 1 ? [{ from: 'set_operation', to: 'count_perm_comb', reason: '选择对象是第一步求出的交集',
            evidence: [{ source: 'question', quote: '再从交集中选出一个元素' }] }] : [] } };
    };
  });
  return { context, page, errors, modelCalls };
}

async function seed(page, { duplicates = true, legacy = false } = {}) {
  return page.evaluate(({ question, other, answer, duplicates, legacy }) => {
    const make = (id, text, corrected, createdAt, updatedAt) => ({
      id, question: text, corrected, createdAt, updatedAt,
      category: '集合与关系', relatedCategories: ['计数与组合'], knowledgePoints: ['集合运算', '排列与组合'],
      focusPoints: ['集合运算'], difficulty: '简单', classificationVersion: 3,
      referenceAnswer: text === question ? answer : '{5}', answer: text === question ? answer : '{5}', analysis: '',
      graphSolution: text === question ? answer : '{5}',
      questionTeaching: __wrongGraphTeaching(text, text === question ? answer : '{5}',
        text === question ? ['set_operation', 'count_perm_comb'] : ['set_operation'])
    });
    const primary = make('wrong-current', question, false, 30, 30);
    learningState = normalizeLearningState({ version: 9, events: [], wrongQuestions: [primary,
      ...(duplicates ? [make('wrong-earliest', question, false, 10, 40),
        make('wrong-corrected', question, true, 20, 50)] : []),
      make('wrong-unrelated', other, true, 1, 60)] });
    sessions = [{ id: 'wrongbook-current-conversation', name: '保持当前对话', nameSource: 'user',
      deletedMessageIds: {}, learningQuestion: null, messages: [
        { messageId: 'wrongbook-greeting', role: 'user', text: '你好', manualIsQuestion: false },
        { messageId: 'wrongbook-reply', role: 'ai', text: '你好' }] }];
    currentId = sessions[0].id;
    wrongBookFilter = 'pending'; wrongBookSearch = ''; wrongBookSort = 'recent';
    renderAll(); openWrongBook();
    if (legacy) {
      // Establish the already-open card first, then reproduce a legacy graph
      // discovered at graph-opening time. This isolates graph review from the
      // existing wrong-book batch repair that runs when its dialog opens.
      const entry = learningState.wrongQuestions.find(item => item.id === primary.id);
      entry.questionTeaching.classification_status = 'local';
      entry.questionTeaching.needs_review = true;
      entry.classificationVersion = 2;
      Object.assign(entry.questionTeaching.question_graph, { classifier_revision: 'catalog-structure/2',
        classification_status: 'local', classification_source: 'local_structure', needs_review: true,
        nodes: [{ id: 'count_inclusion', evidence: [{ source: 'question', quote: question }] }], edges: [] });
    }
    return JSON.stringify({ sessions, currentId });
  }, { question: MAIN, other: OTHER, answer: ANSWER, duplicates, legacy });
}

async function clickCardGraph(page, id = 'wrong-current') {
  const card = page.locator('#wrongBookList [data-wrong-question-id="' + id + '"]');
  await card.getByRole('button', { name: /^(查看图谱|View graph)$/ }).click();
  await page.locator('#knowledgeGraphModal').waitFor({ state: 'visible' });
  await page.waitForFunction(() => document.getElementById('knowledgeGraphModal').dataset.graphReady === 'true');
  await settle(page);
}

async function graphSnapshot(page) {
  return page.evaluate(() => {
    const context = getActiveKnowledgeContext(), nodes = knowledgeGraphDisplayedNodes(context);
    const ids = new Map(nodes.map(node => [node.name, node.id]));
    return { mode: knowledgeGraphViewMode, scope: knowledgeGraphScope,
      ids: nodes.map(node => node.id).sort(),
      purple: nodes.filter(node => knowledgeGraphNodeState(node.name, context).fill === '#5b21b6').map(node => node.id).sort(),
      edges: nodes.flatMap(node => node.prerequisites.filter(name => ids.has(name))
        .map(name => ids.get(name) + '>' + node.id)).sort() };
  });
}

async function assertOnlyWrongNavigation(page, label) {
  assert.equal(await page.locator('#knowledgeGraphWrongBtn').innerText(), '错题关联', label + ': dedicated wrong-question label');
  assert.equal(await page.locator('#knowledgeGraphWrongBtn').getAttribute('aria-pressed'), 'true');
  if (!await page.locator('#knowledgeGraphModal').evaluate(modal => modal.classList.contains('graph-fullscreen-view'))) {
    assert.equal(await page.locator('#knowledgeGraphWrongBtn').isVisible(), true, label + ': the dedicated navigation is visible');
  }
  for (const id of ['knowledgeGraphFocusBtn', 'knowledgeGraphHistoryBtn', 'knowledgeGraphScopeBtn']) {
    assert.equal(await page.locator('#' + id).isVisible(), false, label + ': usual navigation is hidden: ' + id);
  }
  assert.equal(await page.locator('#knowledgeGraphSideTabs').isVisible(), false, label + ': no history tabs inside a wrong-question graph');
  assert.equal(await page.locator('#knowledgeGraphHistoryWrap').isVisible(), false, label + ': no conversation-history list');
}

async function locateAndExpect(page, id, filter, conversation, label) {
  await page.evaluate(() => {
    wrongBookSearch = '不会匹配任何错题的搜索内容';
    wrongBookFilter = wrongBookFilter === 'pending' ? 'corrected' : 'pending';
  });
  await page.locator('#knowledgeGraphLocateOriginal').click();
  await page.locator('#knowledgeGraphModal').waitFor({ state: 'hidden' });
  await page.locator('#wrongBookModal').waitFor({ state: 'visible' });
  const target = page.locator('#wrongBookList .wrong-card.history-locate-flash');
  await target.waitFor({ state: 'visible' });
  assert.equal(await target.getAttribute('data-wrong-question-id'), id, label + ': correct duplicate is highlighted');
  assert.equal(await page.evaluate(() => wrongBookFilter), filter, label + ': target status filter is selected');
  assert.equal(await page.locator('#wrongBookSearch').inputValue(), '', label + ': old search cannot hide the target');
  await page.waitForFunction(id => {
    const card = document.querySelector('#wrongBookList [data-wrong-question-id="' + id + '"]');
    const box = card?.getBoundingClientRect();
    return box && box.bottom > 40 && box.top < innerHeight - 40;
  }, id);
  assert.equal(await page.evaluate(() => JSON.stringify({ sessions, currentId })), conversation,
    label + ': wrong-question locator leaves conversation selection and messages unchanged');
}

async function checkWrongBookGraph(browser, width) {
  const { context, page, errors, modelCalls } = await fixturePage(browser, width);
  const label = width + '/wrong-book';
  try {
    const conversation = await seed(page);
    const card = page.locator('#wrongBookList [data-wrong-question-id="wrong-current"]');
    assert.match(await card.locator('.wrong-meta').innerText(), /难点\s+集合运算/);
    assert.doesNotMatch(await card.locator('.wrong-meta').innerText(), /整题涉及|Concepts/,
      label + ': broad involvement row is removed without removing the stored graph concepts');
    const actionOrder = await card.locator('.wrong-actions > button').evaluateAll(buttons => buttons.map(button => ({
      title: button.title, label: button.getAttribute('aria-label'), text: button.textContent.trim(),
      action: button.dataset.wrongAction || ''
    })));
    assert.ok(/以图片形式导出|Export as image/.test(actionOrder[0].title + actionOrder[0].label));
    assert.equal(actionOrder[1].action, 'graph', label + ': View graph follows the image export action immediately');
    await clickCardGraph(page);
    await assertOnlyWrongNavigation(page, label);
    assert.deepEqual(await graphSnapshot(page), { mode: 'wrong', scope: 'wrong', ids: EXPECTED,
      purple: EXPECTED, edges: ['set_operation>count_perm_comb'] }, label + ': source-specific cross-module graph is reused immediately');
    assert.equal(await page.locator('#knowledgeGraphLocateOriginal').isVisible(), true,
      label + ': detail header offers wrong-book source navigation');
    await page.evaluate(() => selectKnowledgeGraphNode('set_operation'));
    await page.locator('#knowledgeGraphDetail .graph-detail-term[data-knowledge-node-id="count_perm_comb"]').click();
    assert.equal(await page.evaluate(() => knowledgeGraphSelectedNodeId), 'count_perm_comb',
      label + ': a relation chip selects the corresponding node in this wrong-question graph');
    assert.deepEqual(await graphSnapshot(page), { mode: 'wrong', scope: 'wrong', ids: EXPECTED,
      purple: EXPECTED, edges: ['set_operation>count_perm_comb'] },
    label + ': relation navigation preserves the dedicated wrong-question scope');
    await assertOnlyWrongNavigation(page, label + '/relation navigation');
    if (width <= 760 && !await page.locator('.kg-mobile-viewport').count()) await page.locator('.kg-mobile-expand').click();
    const drawn = page.locator('#knowledgeGraphCanvas [data-knowledge-node-id]');
    assert.deepEqual((await drawn.evaluateAll(nodes => nodes.map(node => node.dataset.knowledgeNodeId))).sort(), EXPECTED,
      label + ': actual renderer draws the same two involved nodes');
    if (width <= 760) await page.locator('.kg-mobile-expand').click();
    await page.evaluate(() => DMateI18n.setLanguage('en', false));
    await settle(page);
    assert.match(await page.locator('#knowledgeGraphWrongBtn').innerText(), /[A-Za-z]/,
      label + ': dedicated navigation updates with the current language');
    assert.doesNotMatch(await page.locator('#knowledgeGraphWrongBtn').innerText(), /错题/);
    assert.deepEqual((await graphSnapshot(page)).ids, EXPECTED, label + ': language changes preserve the exact source graph');
    await page.evaluate(() => DMateI18n.setLanguage('zh-CN', false));
    await locateAndExpect(page, 'wrong-corrected', 'corrected', conversation, label + '/corrected first');

    // Deliberately reverse update order and creation order. The locator follows
    // the oldest retained question, independently of the current sorting UI.
    await page.evaluate(() => {
      learningState.wrongQuestions = learningState.wrongQuestions.filter(item => item.id !== 'wrong-corrected');
      wrongBookFilter = 'pending'; wrongBookSearch = ''; renderWrongBook();
    });
    await clickCardGraph(page);
    await locateAndExpect(page, 'wrong-earliest', 'pending', conversation, label + '/oldest uncorrected');

    // Actual storage round-trip must retain the reviewed graph and its exact
    // solution pair, rather than rebuilding a graph from a four-name tag list.
    const stored = await page.evaluate(() => {
      saveLearningState();
      const raw = shouldPersistClientState() ? JSON.parse(localStorage.getItem(LEARNING_STORAGE_KEY))
        : DMateGuestSession.read('learning');
      learningState = normalizeLearningState(raw);
      const entry = learningState.wrongQuestions.find(item => item.id === 'wrong-current');
      renderWrongBook();
      return { question: entry.questionTeaching?.question_graph?.sources.question,
        solution: entry.questionTeaching?.question_graph?.sources.solution, snapshot: entry.graphSolution,
        ids: entry.questionTeaching?.question_graph?.nodes.map(node => node.id).sort() };
    });
    assert.deepEqual(stored, { question: MAIN, solution: ANSWER, snapshot: ANSWER, ids: EXPECTED },
      label + ': reviewed teaching and actual source survive persistence normalization');
    await clickCardGraph(page);
    assert.deepEqual((await graphSnapshot(page)).ids, EXPECTED);

    // Conversation snapshots can retain their original heading while the
    // wrong-book card stores the sanitized body. Keep the literal quote source
    // intact after confirming that both identify the same complete question.
    await page.locator('#knowledgeGraphClose').click();
    const headed = await page.evaluate(() => {
      const entry = learningState.wrongQuestions.find(item => item.id === 'wrong-current');
      const source = '【题目】\n' + entry.question;
      entry.questionTeaching.question_graph.sources.question = source;
      for (const node of entry.questionTeaching.question_graph.nodes) {
        node.evidence = [{ source: 'question', quote: source }];
      }
      saveLearningState();
      const raw = shouldPersistClientState() ? JSON.parse(localStorage.getItem(LEARNING_STORAGE_KEY))
        : DMateGuestSession.read('learning');
      learningState = normalizeLearningState(raw); renderWrongBook();
      return source;
    });
    await clickCardGraph(page);
    assert.deepEqual((await graphSnapshot(page)).ids, EXPECTED,
      label + ': heading-preserving saved sources retain their literal whole-question evidence');
    assert.equal(await page.evaluate(() => getActiveKnowledgeContext().questionText), headed,
      label + ': source projection never rewrites quoted evidence into the sanitized card text');

    await page.evaluate(other => {
      learningState.wrongQuestions.find(item => item.id === 'wrong-current').question = other;
      renderKnowledgeGraph();
    }, OTHER);
    assert.equal((await page.locator('#knowledgeGraphCanvas').innerText()).trim(), '无',
      label + ': editing the selected source cannot leave the old question graph visible');
    assert.equal(await page.locator('#knowledgeGraphLocateOriginal').isVisible(), false,
      label + ': an obsolete source action cannot navigate to another question');
    assert.deepEqual((await graphSnapshot(page)).ids, []);
    assert.deepEqual(modelCalls, [], label + ': reviewed graph opening, navigation and persistence request no model output');
    assert.deepEqual(errors, []);
    console.log('PASS ' + width + ': wrong-card graph action, exact purple graph, dedicated navigation, corrected/oldest locator and source persistence');
  } finally { await context.close(); }
}

async function checkLegacyReviewGuards(browser) {
  const { context, page, errors, modelCalls } = await fixturePage(browser, 1440);
  let observed, release;
  const received = new Promise(resolve => { observed = resolve; });
  const allowed = new Promise(resolve => { release = resolve; });
  const requests = [];
  try {
    await seed(page, { duplicates: false, legacy: true });
    await page.route('**/analyze-questions', async route => {
      const body = route.request().postDataJSON(); requests.push(body); observed(body);
      await allowed;
      const teaching = await page.evaluate(item => __wrongGraphTeaching(item.text, item.solution || ''), body.questions[0]);
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({
        results: [{ key: body.questions[0].key, teaching }]
      }) });
    });
    const opening = clickCardGraph(page);
    const request = await bounded(received, 'A legacy wrong-book graph did not request a bounded source-specific review');
    await opening;
    assert.equal(request.semantic_fallback, true);
    assert.equal(request.questions[0].text, MAIN);
    assert.equal(request.questions[0].solution, ANSWER, 'legacy review uses this saved answer, not conversation history');
    assert.deepEqual((await graphSnapshot(page)).ids, [], 'unreviewed wrong local labels cannot paint a purple graph');
    assert.match(await page.locator('#knowledgeGraphCanvas').innerText(), /正在核对/);
    await page.evaluate(other => {
      learningState.wrongQuestions.find(item => item.id === 'wrong-current').question = other;
      renderKnowledgeGraph();
    }, OTHER);
    const completed = page.waitForResponse(response => new URL(response.url()).pathname === '/analyze-questions');
    release();
    await (await completed).finished();
    await settle(page);
    await page.waitForFunction(() => ![...document.querySelectorAll('#knowledgeGraphCanvas .kg-node-group')].length);
    const stale = await page.evaluate(() => {
      const entry = learningState.wrongQuestions.find(item => item.id === 'wrong-current');
      const graph = entry.questionTeaching?.question_graph;
      return { question: entry.question, staleSemantic: graph?.classification_status === 'semantic' && graph.sources.question !== entry.question };
    });
    assert.deepEqual(stale, { question: OTHER, staleSemantic: false }, 'a delayed review cannot install the old question against an edited wrong-book entry');
    assert.deepEqual((await graphSnapshot(page)).ids, []);
    assert.equal(requests.length, 1, 'rerendering a stale wrong-book source does not start a request storm');
    assert.deepEqual(modelCalls, [], 'legacy graph review never requests a chat answer');
    assert.deepEqual(errors, []);
    console.log('PASS legacy wrong-book review: exact saved source, provisional-label hiding and edited-source response guard');
  } finally { release(); await context.close(); }
}

async function checkLegacyReviewCompletion(browser) {
  const { context, page, errors, modelCalls } = await fixturePage(browser, 1440);
  let observed, release;
  const received = new Promise(resolve => { observed = resolve; });
  const allowed = new Promise(resolve => { release = resolve; });
  const requests = [];
  try {
    await seed(page, { duplicates: false, legacy: true });
    await page.route('**/analyze-questions', async route => {
      const body = route.request().postDataJSON(); requests.push(body); observed(body);
      await allowed;
      const teaching = await page.evaluate(item => __wrongGraphTeaching(item.text, item.solution || ''), body.questions[0]);
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({
        results: [{ key: body.questions[0].key, teaching }]
      }) });
    });
    const opening = clickCardGraph(page);
    await bounded(received, 'A legacy wrong-book entry did not begin its graph review');
    await opening;
    assert.deepEqual((await graphSnapshot(page)).ids, []);
    release();
    await page.waitForFunction(() => learningState.wrongQuestions.find(item => item.id === 'wrong-current')
      .questionTeaching?.question_graph?.classification_status === 'semantic');
    assert.deepEqual((await graphSnapshot(page)).ids, EXPECTED, 'an accepted legacy review replaces the empty graph with the exact source-bound concepts');
    assert.deepEqual(await page.evaluate(() => {
      const entry = learningState.wrongQuestions.find(item => item.id === 'wrong-current');
      return { version: entry.classificationVersion, solution: entry.graphSolution,
        source: entry.questionTeaching.question_graph.sources.solution };
    }), { version: 3, solution: ANSWER, source: ANSWER });
    await page.locator('#knowledgeGraphClose').click();
    await page.evaluate(() => openWrongBook());
    await clickCardGraph(page);
    assert.deepEqual((await graphSnapshot(page)).ids, EXPECTED);
    assert.equal(requests.length, 1, 'the accepted legacy review is reused on reopening');
    assert.deepEqual(modelCalls, []);
    assert.deepEqual(errors, []);
    console.log('PASS legacy wrong-book completion: one source-bound review is saved and reused without another request');
  } finally { release(); await context.close(); }
}

async function checkStaleWrongBookLocators(browser) {
  const { context, page, errors, modelCalls } = await fixturePage(browser, 1440);
  try {
    const conversation = await seed(page);
    await clickCardGraph(page);
    const removed = await page.evaluate(() => {
      const stale = document.getElementById('knowledgeGraphLocateOriginal');
      learningState.wrongQuestions = learningState.wrongQuestions.filter(item => item.id !== 'wrong-current');
      renderKnowledgeGraph();
      const before = { filter: wrongBookFilter, currentId, sessions };
      stale.click();
      return { before: JSON.stringify(before), after: JSON.stringify({ filter: wrongBookFilter, currentId, sessions }),
        graphOpen: !document.getElementById('knowledgeGraphModal').classList.contains('hidden'),
        highlighted: document.querySelectorAll('#wrongBookList .wrong-card.history-locate-flash').length };
    });
    assert.equal(removed.before, removed.after, 'a detached locator cannot act after its selected wrong-book entry was deleted');
    assert.equal(removed.graphOpen, true, 'a deleted source does not navigate to another retained duplicate');
    assert.equal(removed.highlighted, 0);
    assert.equal(await page.evaluate(() => JSON.stringify({ sessions, currentId })), conversation);
    assert.deepEqual((await graphSnapshot(page)).ids, []);
    await page.locator('#knowledgeGraphClose').click();
    await seed(page);
    await clickCardGraph(page);
    const reset = await page.evaluate(() => {
      const stale = document.getElementById('knowledgeGraphLocateOriginal');
      const before = JSON.stringify({ currentId, wrongBookFilter, wrongBookSearch,
        graphOpen: !document.getElementById('knowledgeGraphModal').classList.contains('hidden') });
      bumpCloudSyncContext();
      stale.click();
      const after = JSON.stringify({ currentId, wrongBookFilter, wrongBookSearch,
        graphOpen: !document.getElementById('knowledgeGraphModal').classList.contains('hidden') });
      clearLoggedOutWorkspace();
      closeKnowledgeGraph(); closeWrongBook();
      stale.click();
      return { ownerActionIgnored: before === after, currentId, wrongCount: learningState.wrongQuestions.length,
        graphHidden: document.getElementById('knowledgeGraphModal').classList.contains('hidden'),
        wrongBookHidden: document.getElementById('wrongBookModal').classList.contains('hidden') };
    });
    assert.deepEqual(reset, { ownerActionIgnored: true, currentId: null, wrongCount: 0, graphHidden: true, wrongBookHidden: true },
      'a stale locator cannot reopen or restore wrong-book records after the account workspace changes');
    assert.deepEqual(modelCalls, []);
    assert.deepEqual(errors, []);
    console.log('PASS stale wrong-book locators: deleted records and changed account workspaces cannot redirect an old source action');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const width of [390, 1440]) await checkWrongBookGraph(browser, width);
    await checkLegacyReviewCompletion(browser);
    await checkLegacyReviewGuards(browser);
    await checkStaleWrongBookLocators(browser);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
