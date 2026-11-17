/* Graph selection must stay independent of the size of conversation history.
 * All account/model routes are isolated; fixtures do not write cloud data.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';

async function checkCase(browser, width) {
  const mobile = width <= 760;
  const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block',
    ...(mobile ? { isMobile: true, hasTouch: true } : {}) });
  const page = await context.newPage(), errors = [], modelCalls = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/auth/me', route => route.fulfill({ contentType: 'application/json',
    body: '{"configured":true,"authenticated":false}' }));
  await page.route(/\/(?:chat|conversation\/title|classify|analyze-questions|ocr)(?:\?|$)/, route => {
    modelCalls.push(new URL(route.request().url()).pathname); return route.abort();
  });
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await page.waitForFunction(() => !accountVerificationOperation);
    const fixture = await page.evaluate(async () => {
      const teaching = { category: '证明与归纳', knowledge_points: ['数学归纳法'], focus_points: ['数学归纳法'] };
      sessions = Array.from({ length: 50 }, (_, conversation) => ({
        id: 'selection-history-' + conversation, name: 'Performance fixture ' + conversation, nameSource: 'user',
        deletedMessageIds: {}, learningQuestion: null, teaching,
        messages: Array.from({ length: 100 }, (_, index) => {
          const text = index % 10 === 0 ? '使用数学归纳法证明命题 p 与 ' + index + ' 的关系。' + '条件 '.repeat(100) : '解释内容 '.repeat(120);
          return { messageId: conversation + '-' + index, role: index % 2 ? 'ai' : 'user', text,
            manualIsQuestion: index % 10 === 0, questionTeaching: index % 10 === 0 ? {...teaching,
              question_graph: {version: 1,classifier_revision:'catalog-semantic-v5',classification_status:'semantic',classification_source:'catalog_semantic',needs_review:false, sources: {question: text, solution: '解释内容 '.repeat(120)},
                nodes: [{id: 'proof_induction', evidence: [{source: 'question', quote: '数学归纳法'}]}], edges: []}} : null };
        })
      }));
      currentId = sessions[0].id;
      const bytes = new TextEncoder().encode(JSON.stringify(sessions)).length;
      const before = JSON.stringify(sessions);
      await openKnowledgeGraph();
      setKnowledgeGraphFilter('证明与归纳');
      window.__selectionHistoryOriginal = getKnowledgeGraphQuestionHistory;
      window.__selectionHistoryCalls = 0;
      getKnowledgeGraphQuestionHistory = function (...args) {
        window.__selectionHistoryCalls++;
        return window.__selectionHistoryOriginal.apply(this, args);
      };
      return { bytes, immutable: before === JSON.stringify(sessions) };
    });
    assert.ok(fixture.bytes < 12 * 1024 * 1024, 'The 5000-message fixture stays below the account snapshot limit');
    assert.equal(fixture.immutable, true, 'Initial graph browsing leaves conversation records unchanged');
    assert.equal(await page.locator('#knowledgeGraphSideTabs').isVisible(), false, width + ': all knowledge exposes only node details');
    assert.equal(await page.locator('#knowledgeGraphHistoryWrap').isVisible(), false, width + ': all knowledge hides the history pane');
    if (mobile) await page.locator('.kg-mobile-expand').click();
    const node = page.locator('#knowledgeGraphCanvas [data-knowledge-node-id="proof_strong_induction"]');
    await node.waitFor({ state: 'visible' });
    await page.evaluate(() => { window.__selectionHistoryCalls = 0; });
    await node.click();
    assert.equal(await page.evaluate(() => window.__selectionHistoryCalls), 0,
      width + ': a real node click does not copy or scan any conversation history');
    assert.equal(await page.locator('#knowledgeGraphDetailTitle').textContent(), '强归纳法');
    const timings = await page.evaluate(() => {
      const before = JSON.stringify(sessions), selectionMs = [], aggregateMs = [];
      for (let iteration = 0; iteration < 3; iteration++) {
        const start = performance.now(); window.__selectionHistoryOriginal(); aggregateMs.push(performance.now() - start);
      }
      for (let iteration = 0; iteration < 6; iteration++) {
        const target = document.querySelector('#knowledgeGraphCanvas [data-knowledge-node-id="'
          + (iteration % 2 ? 'proof_induction' : 'proof_strong_induction') + '"]');
        const start = performance.now(); target.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        selectionMs.push(performance.now() - start);
      }
      return { aggregateMs, selectionMs, immutable: before === JSON.stringify(sessions), calls: window.__selectionHistoryCalls };
    });
    assert.equal(timings.calls, 0, width + ': repeated selections still perform zero global history reads');
    assert.equal(timings.immutable, true, width + ': node selection never edits conversation records');

    // Mutate the existing messages array: object-identity caches would go stale.
    const updated = await page.evaluate(() => {
      const session = sessions[0];
      const text = '用真值表证明命题 p 的双重否定与 p 等价';
      session.messages.push({ role: 'user', messageId: 'selection-new-question-1', text,
        manualIsQuestion: true, questionTeaching: {category: '命题逻辑', knowledge_points: ['逻辑等价'], focus_points: ['逻辑等价'],
          question_graph: {version: 1,classifier_revision:'catalog-semantic-v5',classification_status:'semantic',classification_source:'catalog_semantic',needs_review:false, sources: {question: text, solution: ''},
            nodes: [{id: 'logic_truth_table', evidence: [{source: 'question', quote: '真值表'}]},
              {id: 'logic_equivalence', evidence: [{source: 'question', quote: '双重否定'}]}],
            edges: [{from: 'logic_truth_table', to: 'logic_equivalence', evidence: [{source: 'question', quote: text}]}]}} });
      window.__selectionHistoryCalls = 0;
      renderKnowledgeGraph();
      return { calls: window.__selectionHistoryCalls, count: document.getElementById('knowledgeGraphHistoryTab').textContent };
    });
    assert.equal(updated.calls, 0, width + ': a full-graph data render does not aggregate unrelated question history');
    assert.equal(await page.locator('#knowledgeGraphHistoryTab').isVisible(), false);
    if (mobile && await page.locator('#knowledgeGraphModal').evaluate(modal => modal.classList.contains('graph-fullscreen-view')))
      await page.locator('.kg-mobile-expand').click();
    await page.evaluate(() => { window.__selectionHistoryCalls = 0; });
    await page.locator('#knowledgeGraphHistoryBtn').click();
    assert.ok(await page.evaluate(() => window.__selectionHistoryCalls) > 0, width + ': entering the history page reads current message contents');
    assert.equal(await page.locator('#knowledgeGraphHistoryTab').innerText(), '历史题目 (501)');
    assert.equal(await page.locator('#knowledgeGraphHistory .kg-history-item').count(), 501);
    await page.locator('#knowledgeGraphHistory .kg-history-item[data-message-id="selection-new-question-1"] [data-history-action="graph"]').click();
    if (mobile) await page.locator('.kg-mobile-expand').click();
    await page.evaluate(() => { window.__selectionHistoryCalls = 0; });
    await page.locator('#knowledgeGraphCanvas [data-knowledge-node-id="logic_truth_table"]').click();
    assert.equal(await page.evaluate(() => window.__selectionHistoryCalls), 0,
      width + ': a historical question node click also avoids global history scans');
    assert.equal(await page.locator('#knowledgeGraphDetailTitle').textContent(), '真值表');
    if (mobile) await page.locator('.kg-mobile-expand').click();
    await page.evaluate(() => {
      const text = '证明命题 p 与 q 的双重否定定律';
      sessions[0].messages.push({ role: 'user', messageId: 'selection-new-question-2', text,
        manualIsQuestion: true, questionTeaching: {category: '命题逻辑', knowledge_points: ['逻辑等价'], focus_points: ['逻辑等价'],
          question_graph: {version: 1,classifier_revision:'catalog-semantic-v5',classification_status:'semantic',classification_source:'catalog_semantic',needs_review:false, sources: {question: text, solution: ''},
            nodes: [{id: 'logic_equivalence', evidence: [{source: 'question', quote: '双重否定'}]}], edges: []}} });
      window.__selectionHistoryCalls = 0;
    });
    await page.locator('#knowledgeGraphHistoryTab').click();
    assert.ok(await page.evaluate(() => window.__selectionHistoryCalls) > 0,
      width + ': opening history always reads fresh records');
    assert.equal(await page.locator('#knowledgeGraphHistoryTab').innerText(), '历史题目 (502)');
    assert.equal(await page.locator('#knowledgeGraphHistory .kg-history-item').count(), 502);
    assert.equal(await page.locator('#knowledgeGraphHistory .kg-history-item[data-message-id="selection-new-question-2"]').count(), 1);
    await page.evaluate(() => { window.__selectionHistoryCalls = 0; selectKnowledgeGraphDisplayMode('focus'); });
    assert.equal(await page.evaluate(() => window.__selectionHistoryCalls), 0, width + ': recent mode does not aggregate global history');
    assert.equal(await page.locator('#knowledgeGraphHistoryTab').isVisible(), false);
    await page.evaluate(() => { window.__selectionHistoryCalls = 0; selectKnowledgeGraphDisplayMode('full'); });
    assert.equal(await page.evaluate(() => window.__selectionHistoryCalls), 0, width + ': entering full mode does not aggregate question history');
    await page.evaluate(() => { window.__selectionHistoryCalls = 0; setKnowledgeGraphFilter('函数'); });
    assert.equal(await page.evaluate(() => window.__selectionHistoryCalls), 0, width + ': browsing another course module does not aggregate question history');
    assert.equal(await page.locator('#knowledgeGraphSideTabs').isVisible(), false);
    await page.locator('#knowledgeGraphHistoryBtn').click();
    assert.ok(await page.evaluate(() => window.__selectionHistoryCalls) > 0, width + ': reentering history refreshes the count');
    assert.equal(await page.locator('#knowledgeGraphHistoryTab').innerText(), '历史题目 (502)');
    assert.deepEqual(modelCalls, [], width + ': selection and history do not invoke models');
    assert.deepEqual(errors, [], width + ': no page errors');
    console.log('PASS ' + width + ': 5000 messages, zero history scans on node clicks; data/mode/module/history changes stay fresh; '
      + JSON.stringify({ bytes: fixture.bytes, aggregateMs: timings.aggregateMs, selectionMs: timings.selectionMs }));
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try { for (const width of [1440, 390]) await checkCase(browser, width); }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
