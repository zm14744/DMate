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
        messages: Array.from({ length: 100 }, (_, index) => ({
          messageId: conversation + '-' + index, role: index % 2 ? 'ai' : 'user',
          text: index % 10 === 0 ? '证明命题 p 与 ' + index + ' 的关系。' + '条件 '.repeat(100) : '解释内容 '.repeat(120),
          manualIsQuestion: index % 10 === 0, questionTeaching: index % 10 === 0 ? teaching : null
        }))
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
    assert.equal(await page.locator('#knowledgeGraphHistoryTab').innerText(), '题目历史 (500)');
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
      session.messages.push({ role: 'user', messageId: 'selection-new-question-1', text: '证明命题 p 的双重否定与 p 等价',
        manualIsQuestion: true, questionTeaching: session.teaching });
      window.__selectionHistoryCalls = 0;
      renderKnowledgeGraph();
      return { calls: window.__selectionHistoryCalls, count: document.getElementById('knowledgeGraphHistoryTab').textContent };
    });
    assert.ok(updated.calls > 0, width + ': a data render rebuilds history from changed message contents');
    assert.equal(updated.count, '题目历史 (501)');
    if (mobile) await page.locator('.kg-mobile-expand').click();
    await page.evaluate(() => {
      sessions[0].messages.push({ role: 'user', messageId: 'selection-new-question-2', text: '证明命题 p 与 q 的双重否定定律',
        manualIsQuestion: true, questionTeaching: sessions[0].teaching });
      window.__selectionHistoryCalls = 0;
    });
    await page.locator('#knowledgeGraphHistoryTab').click();
    assert.ok(await page.evaluate(() => window.__selectionHistoryCalls) > 0,
      width + ': opening history always reads fresh records');
    assert.equal(await page.locator('#knowledgeGraphHistoryTab').innerText(), '题目历史 (502)');
    assert.equal(await page.locator('#knowledgeGraphHistory .kg-history-item').count(), 502);
    assert.equal(await page.locator('#knowledgeGraphHistory .kg-history-item[data-message-id="selection-new-question-2"]').count(), 1);
    await page.evaluate(() => { window.__selectionHistoryCalls = 0; selectKnowledgeGraphDisplayMode('focus'); });
    assert.equal(await page.evaluate(() => window.__selectionHistoryCalls), 0, width + ': recent mode does not aggregate global history');
    assert.equal(await page.locator('#knowledgeGraphHistoryTab').isVisible(), false);
    await page.evaluate(() => { window.__selectionHistoryCalls = 0; selectKnowledgeGraphDisplayMode('full'); });
    assert.ok(await page.evaluate(() => window.__selectionHistoryCalls) > 0, width + ': entering full mode refreshes the count');
    await page.evaluate(() => { window.__selectionHistoryCalls = 0; setKnowledgeGraphFilter('函数'); });
    assert.ok(await page.evaluate(() => window.__selectionHistoryCalls) > 0, width + ': a module change refreshes the count');
    assert.equal(await page.locator('#knowledgeGraphHistoryTab').innerText(), '题目历史 (502)');
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
