/* Graph empty-state and question-history presentation regressions. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';

async function nextFrames(page) {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function assertEmpty(page, text, label) {
  assert.equal((await page.locator('#knowledgeGraphCanvas').innerText()).trim(), text, label + ': canvas contains only the empty label');
  assert.equal((await page.locator('#knowledgeGraphDetail').innerText()).trim(), text, label + ': detail contains only the empty label');
  assert.equal(await page.locator('#knowledgeGraphDetailTitle').isVisible(), false, label + ': no stale selected-node title');
  assert.equal(await page.locator('#knowledgeGraphCanvas .kg-section, #knowledgeGraphCanvas .kg-mobile-expand, #knowledgeGraphCanvas .kg-mobile-node, #knowledgeGraphCanvas .kg-node-group').count(), 0,
    label + ': no graph, complete-view entry, or unrelated nodes');
  assert.equal(await page.locator('#knowledgeGraphDetail .kg-video-section, #knowledgeGraphDetail .graph-detail-field').count(), 0,
    label + ': no stale videos or relationships');
  assert.deepEqual(await page.evaluate(() => ({ mode: knowledgeGraphViewMode, selected: knowledgeGraphSelectedNodeId,
    nodes: knowledgeGraphDisplayedNodes().length, key: knowledgeGraphCopyKey(), png: prepareKnowledgeGraphPng(),
    target: buildKnowledgeGraphImageCopyTarget() })),
  { mode: 'focus', selected: '', nodes: 0, key: '', png: null, target: null }, label + ': all graph/export paths share the empty set');
}

async function checkEmptyRecent(browser, width) {
  const mobile = width <= 760;
  const page = await browser.newPage({ viewport: { width, height: 844 },
    ...(mobile ? { isMobile: true, hasTouch: true } : {}) });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  // Reindexing is unrelated to this rendering test and must not invoke a model.
  await page.route('**/analyze-questions', route => route.fulfill({ contentType: 'application/json', body: '{"entries":[]}' }));
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await page.evaluate(() => { newChat(); openKnowledgeGraph(); });
    await page.waitForFunction(() => knowledgeGraphInitialized && document.getElementById('knowledgeGraphCanvas').innerText.trim() === '无');
    await assertEmpty(page, '无', width + '/new chat');

    // English must update the same open dialog, rather than requiring reopen.
    await page.evaluate(() => window.DMateI18n.setLanguage('en', false));
    await page.waitForFunction(() => document.getElementById('knowledgeGraphCanvas').innerText.trim() === 'None');
    await assertEmpty(page, 'None', width + '/live English');
    await page.evaluate(() => window.DMateI18n.setLanguage('zh-CN', false));
    await page.waitForFunction(() => document.getElementById('knowledgeGraphCanvas').innerText.trim() === '无');

    // A legacy session snapshot without a real question cannot revive that node.
    await page.evaluate(() => {
      const session = getCurrent();
      session.messages = [{ role: 'user', text: '你好' }, { role: 'ai', text: '你好。' }];
      session.learningQuestion = null;
      session.teaching = { category: '命题逻辑', knowledge_points: ['命题与真值'], focus_points: ['命题与真值'] };
      knowledgeGraphSelectedNodeId = 'logic_truth';
      renderKnowledgeGraph();
      selectKnowledgeGraphNode('logic_truth');
    });
    await assertEmpty(page, '无', width + '/stale snapshot and selected node');
    const rejected = await page.evaluate(async () => {
      let saves = 0;
      const original = window.DMateDrawingExport;
      window.DMateDrawingExport = { save: async () => { saves++; } };
      let rendered = false;
      try { await renderKnowledgeGraphPngBlob(); rendered = true; } catch (_) {}
      const exported = await exportKnowledgeGraphImage();
      window.DMateDrawingExport = original;
      return { saves, rendered, exported };
    });
    assert.deepEqual(rejected, { saves: 0, rendered: false, exported: false }, width + ': empty focus never exports a full graph');

    // Explicit full mode still renders the entire model and retains its camera
    // through a visit to the empty recent-question view.
    await page.evaluate(() => selectKnowledgeGraphDisplayMode('full'));
    await page.waitForSelector('#knowledgeGraphCanvas .kg-section');
    if (mobile) await page.locator('.kg-mobile-expand').click();
    const viewSelector = mobile ? '.kg-mobile-viewport' : '.kg-desktop-viewport';
    await page.waitForSelector(viewSelector);
    await nextFrames(page);
    assert.equal(await page.evaluate(() => knowledgeGraphDisplayedNodes().length), await page.evaluate(() => knowledgeGraphData.nodes.length));
    await page.evaluate(() => selectKnowledgeGraphNode('logic_truth'));
    assert.ok(await page.locator('#knowledgeGraphDetail .kg-video-section').count(), width + ': valid full node initially has videos');
    for (let index = 0; index < 5; index++) {
      if (mobile) await page.locator('.kg-mobile-zoom-btn').last().click();
      else await page.locator('#knowledgeGraphDesktopZoomIn').click();
    }
    await page.locator(viewSelector).evaluate(view => { view.scrollLeft = 60; view.scrollTop = 140; });
    await nextFrames(page);
    const camera = () => page.locator(viewSelector).evaluate(view => ({
      scale: view._kgScale || Number(view.querySelector('.kg-desktop-zoom-surface').dataset.scale),
      left: view.scrollLeft, top: view.scrollTop
    }));
    const before = await camera();
    assert.ok(before.top > 0, width + ': full graph test camera was moved');
    await page.evaluate(() => selectKnowledgeGraphDisplayMode('focus'));
    await assertEmpty(page, '无', width + '/full to empty');
    assert.equal(await page.locator('#knowledgeGraphModal').evaluate(modal => modal.classList.contains('graph-fullscreen-view')), false,
      width + ': empty mode exposes toolbar and detail');
    await page.evaluate(() => selectKnowledgeGraphDisplayMode('full'));
    await page.waitForSelector(viewSelector);
    await nextFrames(page);
    assert.deepEqual(await camera(), before, width + ': full to empty to full preserves camera');

    // Use a real manually identified question and its teaching snapshot, through
    // the application's active-question selector (no replaced context function).
    const fixture = await page.evaluate(() => {
      const session = getCurrent();
      const teaching = { category: '命题逻辑', knowledge_points: ['逻辑联结词'], focus_points: ['逻辑联结词'] };
      session.messages = [{ role: 'user', text: '判断命题 p 与 q 的合取在什么情况下为真。', manualIsQuestion: true, questionTeaching: teaching }];
      session.teaching = teaching;
      session.learningQuestion = null;
      selectKnowledgeGraphDisplayMode('focus');
      const displayed = knowledgeGraphDisplayedNodes();
      return { names: displayed.map(node => node.name), total: knowledgeGraphData.nodes.length,
        selected: knowledgeGraphSelectedNodeId };
    });
    assert.ok(fixture.names.includes('逻辑联结词'), width + ': question concept returns');
    assert.ok(fixture.names.includes('命题与真值'), width + ': direct prerequisite returns');
    assert.ok(fixture.names.includes('真值表'), width + ': direct follow-up returns');
    assert.ok(fixture.names.length < fixture.total, width + ': valid focus contains only related concepts');
    assert.equal(fixture.selected, 'logic_connectives');
    assert.equal(await page.locator('#knowledgeGraphDetailTitle').evaluate(title => title.hidden), false, width + ': selected title returns');
    assert.equal(await page.locator('#knowledgeGraphDetailTitle').textContent(), '逻辑联结词');
    assert.equal(await page.locator('#knowledgeGraphDetail .graph-detail-field').count(), 2);
    assert.ok(await page.locator('#knowledgeGraphDetail .kg-video-section').count(), width + ': valid focus videos return');
    const png = await page.evaluate(async () => { const blob = await renderKnowledgeGraphOffscreenPngBlob(); return { size: blob.size, type: blob.type }; });
    assert.equal(png.type, 'image/png');
    assert.ok(png.size > 1000, width + ': valid related graph can be exported');

    await page.evaluate(() => {
      const session = getCurrent();
      session.messages[0].questionTeaching = { category: '命题逻辑', knowledge_points: ['图谱中不存在的概念'] };
      session.teaching = session.messages[0].questionTeaching;
      renderKnowledgeGraph();
    });
    await assertEmpty(page, '无', width + '/unmatched question concepts');
    if (process.env.KG_SCREENSHOT_DIR) await page.screenshot({ path: process.env.KG_SCREENSHOT_DIR + '/graph-empty-recent-' + width + '.png' });
    assert.deepEqual(errors, [], width + ': browser errors');
    console.log('PASS ' + width + ': empty recent graph/detail, live language, export guard, full camera memory and valid-question recovery');
  } finally { await page.close(); }
}

async function checkHistoryPresentation(browser, width) {
  const page = await browser.newPage({ viewport: { width, height: 844 },
    ...(width <= 760 ? { isMobile: true, hasTouch: true } : {}) });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/analyze-questions', route => route.fulfill({ contentType: 'application/json', body: '{"entries":[]}' }));
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await page.evaluate(() => { newChat(); openKnowledgeGraph(); });
    await page.waitForFunction(() => knowledgeGraphInitialized);
    const metadataBefore = await page.evaluate(() => {
      const teaching = (point, difficulty, type) => ({ category: '命题逻辑', knowledge_points: [point], focus_points: [point],
        difficulty, question_type: type });
      const generatedQuestion = '证明命题 p 的双重否定与 p 等价。';
      getCurrent().messages = [
        { role: 'user', text: '判断 p 与 q 的合取在什么情况下为真。', manualIsQuestion: true,
          questionTeaching: teaching('逻辑联结词', '简单', '判断题') },
        { role: 'user', text: '【题目文字】\n判断 p 与 q 的析取在什么情况下为假。', source: 'ocr', ocrIsQuestion: true,
          questionTeaching: teaching('逻辑联结词', '中等', '选择题') },
        { role: 'ai', text: generatedQuestion, generatedQuestion, generatedExercise: true,
          generatedTeaching: teaching('逻辑等价', '困难', '证明题') }
      ];
      renderKnowledgeGraph();
      setKnowledgeGraphSideMode('history');
      return JSON.stringify(getCurrent().messages);
    });
    const cards = page.locator('#knowledgeGraphHistory .kg-history-item');
    assert.equal(await cards.count(), 3, width + ': all question sources remain in history');
    assert.equal(await page.locator('#knowledgeGraphModal .kg-history-source').count(), 0, width + ': no source badges');
    assert.deepEqual(await cards.locator('.kg-history-item-top').allTextContents(), ['第 1 题', '第 2 题', '第 3 题'],
      width + ': history headings contain only question numbers');
    assert.equal(await cards.locator('.kg-history-preview').count(), 3, width + ': previews remain');
    assert.equal(await cards.locator('.kg-history-points').count(), 3, width + ': knowledge classifications remain');
    assert.equal(await cards.locator('.kg-history-actions button').count(), 6, width + ': graph and locate actions remain');
    assert.deepEqual(await page.evaluate(() => getConversationQuestionHistory().map(item => ({
      role: item.role, source: item.source, category: item.teaching.category,
      type: item.teaching.question_type, difficulty: item.teaching.difficulty
    }))), [
      { role: 'user', source: '', category: '命题逻辑', type: '判断题', difficulty: '简单' },
      { role: 'user', source: 'ocr', category: '命题逻辑', type: '选择题', difficulty: '中等' },
      { role: 'ai', source: '', category: '命题逻辑', type: '证明题', difficulty: '困难' }
    ], width + ': underlying source, type, classification, and difficulty metadata remain intact');
    for (let index = 0; index < 3; index++) {
      await cards.nth(index).locator('.kg-history-actions button').first().click();
      assert.deepEqual(await page.evaluate(() => ({ scope: knowledgeGraphScope, index: knowledgeGraphHistoryMessageIndex,
        point: getActiveKnowledgeContext().knowledgePoints[0] })),
      { scope: 'history', index, point: index === 2 ? '逻辑等价' : '逻辑联结词' },
      width + ': view graph still selects history question ' + (index + 1));
      assert.equal(await page.locator('#knowledgeGraphModal .kg-history-source').count(), 0,
        width + ': source badges stay removed after graph navigation');
    }
    assert.equal(await page.evaluate(() => JSON.stringify(getCurrent().messages)), metadataBefore,
      width + ': presentation and graph navigation do not mutate question metadata');
    assert.deepEqual(errors, [], width + ': history browser errors');
    console.log('PASS ' + width + ': graph history hides manual/OCR/AI source badges, preserves metadata and graph navigation');
  } finally { await page.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const width of [1440, 390]) await checkEmptyRecent(browser, width);
    for (const width of [1440, 390]) await checkHistoryPresentation(browser, width);
  }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
