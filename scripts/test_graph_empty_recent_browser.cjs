/* Empty recent graphs and the separate full/recent/history navigation modes. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';

async function nextFrames(page) {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function assertEmpty(page, text, label) {
  assert.equal((await page.locator('#knowledgeGraphCanvas').innerText()).trim(), text, label + ': canvas contains only the empty label');
  const canvasPosition = await page.locator('#knowledgeGraphCanvas').evaluate(canvas => {
    const pane = canvas.getBoundingClientRect(), empty = canvas.querySelector(':scope > .kg-empty').getBoundingClientRect();
    return { x: empty.left + empty.width / 2 - (pane.left + pane.width / 2),
      y: empty.top + empty.height / 2 - (pane.top + pane.height / 2),
      height: pane.height, availableHeight: canvas.parentElement.clientHeight };
  });
  assert.ok(Math.abs(canvasPosition.x) <= 1 && Math.abs(canvasPosition.y) <= 1,
    label + ': empty canvas label is centered in both axes');
  assert.ok(Math.abs(canvasPosition.height - canvasPosition.availableHeight) <= 1 && canvasPosition.height > 120,
    label + ': empty canvas fills its available graph body');
  assert.equal((await page.locator('#knowledgeGraphDetail').innerText()).trim(), text, label + ': detail contains only the empty label');
  assert.equal(await page.locator('#knowledgeGraphDetailTitle').isVisible(), false, label + ': no stale selected-node title');
  const position = await page.locator('#knowledgeGraphDetail').evaluate(body => {
    const pane = body.getBoundingClientRect(), empty = body.querySelector('.graph-detail-empty').getBoundingClientRect();
    const layout = body.closest('.knowledge-graph-layout'), layoutBox = layout.getBoundingClientRect();
    const availableBottom = layoutBox.top + layout.clientTop + layout.clientHeight - parseFloat(getComputedStyle(layout).paddingBottom);
    return { x: empty.left + empty.width / 2 - (pane.left + pane.width / 2),
      y: empty.top + empty.height / 2 - (pane.top + pane.height / 2),
      height: pane.height, availableHeight: body.parentElement.getBoundingClientRect().height,
      remainingSpace: availableBottom - pane.bottom };
  });
  assert.ok(Math.abs(position.x) <= 1 && Math.abs(position.y) <= 1, label + ': empty detail label is centered in both axes');
  assert.ok(Math.abs(position.height - position.availableHeight) <= 1, label + ': empty detail fills the available pane');
  assert.ok(position.height > 100, label + ': empty detail uses the remaining sidebar height');
  if (page.viewportSize().width <= 760) assert.ok(Math.abs(position.remainingSpace) <= 1,
    label + ': mobile empty detail fills the remaining visible graph pane');
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
    await page.waitForFunction(() => knowledgeGraphInitialized && knowledgeGraphViewMode === 'full');
    assert.equal(await page.locator('#knowledgeGraphFocusBtn').getAttribute('aria-pressed'), 'true', width + ': initial view is all knowledge');
    assert.equal(await page.locator('#knowledgeGraphSideTabs').isVisible(), false, width + ': all knowledge has only node details');
    assert.equal(await page.locator('#knowledgeGraphHistoryWrap').isVisible(), false, width + ': all knowledge has no history pane');
    assert.equal(await page.evaluate(() => knowledgeGraphDisplayedNodes().length), await page.evaluate(() => knowledgeGraphData.nodes.length),
      width + ': initial all-knowledge view contains the complete course graph');
    await page.locator('#knowledgeGraphScopeBtn').click();
    await page.waitForFunction(() => knowledgeGraphInitialized && document.getElementById('knowledgeGraphCanvas').innerText.trim() === '无');
    await assertEmpty(page, '无', width + '/explicit recent view of a new chat');

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
      const question = '判断命题 p 与 q 的合取在什么情况下为真。';
      const teaching = { category: '命题逻辑', knowledge_points: ['逻辑联结词'], focus_points: ['逻辑联结词'],
        question_graph: { version: 1,classifier_revision:'catalog-semantic-v5',classification_status:'semantic',classification_source:'catalog_semantic',needs_review:false, sources: { question, solution: '' },
          nodes: [{ id: 'logic_connectives', evidence: [{ source: 'question', quote: '合取' }] }], edges: [] } };
      session.messages = [{ role: 'user', text: question, manualIsQuestion: true, questionTeaching: teaching }];
      session.teaching = teaching;
      session.learningQuestion = null;
      selectKnowledgeGraphDisplayMode('focus');
      const displayed = knowledgeGraphDisplayedNodes();
      return { names: displayed.map(node => node.name), total: knowledgeGraphData.nodes.length,
        selected: knowledgeGraphSelectedNodeId };
    });
    assert.deepEqual(fixture.names, ['逻辑联结词'], width + ': only this question concept returns, with no course prerequisite or follow-up');
    assert.ok(fixture.names.length < fixture.total, width + ': valid focus contains only related concepts');
    assert.equal(fixture.selected, 'logic_connectives');
    assert.deepEqual(await page.evaluate(() => knowledgeGraphDisplayedNodes().map(node => ({
      prerequisites: node.prerequisites, fill: knowledgeGraphNodeState(node.name, getActiveKnowledgeContext()).fill
    }))), [{ prerequisites: [], fill: '#5b21b6' }], width + ': every involved node is purple and its relations come only from the question');
    assert.equal(await page.locator('#knowledgeGraphDetailTitle').evaluate(title => title.hidden), false, width + ': selected title returns');
    assert.equal(await page.locator('#knowledgeGraphDetailTitle').textContent(), '逻辑联结词');
    assert.equal(await page.locator('#knowledgeGraphDetail .graph-detail-field').count(), 2);
    assert.ok(await page.locator('#knowledgeGraphDetail .kg-video-section').count(), width + ': valid focus videos return');
    const png = await page.evaluate(async () => { const blob = await renderKnowledgeGraphOffscreenPngBlob(); return { size: blob.size, type: blob.type }; });
    assert.equal(png.type, 'image/png');
    assert.ok(png.size > 1000, width + ': valid related graph can be exported');

    await page.evaluate(() => {
      const session = getCurrent();
      session.messages[0].questionTeaching = { category: '命题逻辑', knowledge_points: ['图谱中不存在的概念'],
        question_graph: { version: 1,classifier_revision:'catalog-semantic-v5',classification_status:'semantic',classification_source:'catalog_semantic',needs_review:false, sources: { question: session.messages[0].text, solution: '' },
          nodes: [{ id: 'unknown-concept', evidence: [{ source: 'question', quote: '合取' }] }], edges: [] } };
      session.teaching = session.messages[0].questionTeaching;
      renderKnowledgeGraph();
    });
    await assertEmpty(page, '知识点归类暂未完成', width + '/unmatched question concepts');
    if (process.env.KG_SCREENSHOT_DIR) await page.screenshot({ path: process.env.KG_SCREENSHOT_DIR + '/graph-empty-recent-' + width + '.png' });
    assert.deepEqual(errors, [], width + ': browser errors');
    console.log('PASS ' + width + ': empty recent graph/detail, live language, export guard, full camera memory and valid-question recovery');
  } finally { await page.close(); }
}

async function checkHistoryModes(browser, width) {
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
      const teaching = (point, difficulty, type, question, id, quote) => ({ category: '命题逻辑', knowledge_points: [point], focus_points: [point],
        difficulty, question_type: type, question_graph: { version: 1,classifier_revision:'catalog-semantic-v5',classification_status:'semantic',classification_source:'catalog_semantic',needs_review:false, sources: { question, solution: '' },
          nodes: [{ id, evidence: [{ source: 'question', quote }] }], edges: [] } });
      const generatedQuestion = '证明命题 p 的双重否定与 p 等价。';
      getCurrent().messages = [
        { role: 'user', text: '判断 p 与 q 的合取在什么情况下为真。', manualIsQuestion: true,
          questionTeaching: teaching('逻辑联结词', '简单', '判断题', '判断 p 与 q 的合取在什么情况下为真。', 'logic_connectives', '合取') },
        { role: 'user', text: '【题目文字】\n判断 p 与 q 的析取在什么情况下为假。', source: 'ocr', ocrIsQuestion: true,
          questionTeaching: teaching('逻辑联结词', '中等', '选择题', '判断 p 与 q 的析取在什么情况下为假。', 'logic_connectives', '析取') },
        { role: 'ai', text: generatedQuestion, generatedQuestion, generatedExercise: true,
          generatedTeaching: teaching('逻辑等价', '困难', '证明题', generatedQuestion, 'logic_equivalence', '双重否定') }
      ];
      getCurrent().learningQuestion = null;
      getCurrent().teaching = getCurrent().messages[2].generatedTeaching;
      renderKnowledgeGraph();
      return JSON.stringify(getCurrent().messages);
    });
    for (const language of ['zh-CN', 'en']) {
      await page.evaluate(value => DMateI18n.setLanguage(value, false), language);
      for (const mode of ['focus', 'full', 'history', 'focus']) {
        await page.evaluate(value => selectKnowledgeGraphDisplayMode(value), mode);
        await nextFrames(page);
        assert.equal(await page.locator('#knowledgeGraphFocusBtn').getAttribute('aria-pressed'), String(mode === 'full'));
        assert.equal(await page.locator('#knowledgeGraphScopeBtn').getAttribute('aria-pressed'), String(mode === 'focus'));
        assert.equal(await page.locator('#knowledgeGraphHistoryBtn').getAttribute('aria-pressed'), String(mode === 'history'));
        if (mode !== 'history') {
          assert.equal(await page.locator('#knowledgeGraphSideTabs').isVisible(), false,
            width + '/' + language + ': full/recent views have no sidebar tabs');
          assert.equal(await page.locator('#knowledgeGraphHistoryTab').isVisible(), false,
            width + '/' + language + ': full/recent views hide the history tab');
          assert.equal(await page.locator('#knowledgeGraphHistoryWrap').isVisible(), false,
            width + '/' + language + ': full/recent views hide history content');
          assert.equal(await page.locator('#knowledgeGraphModal .kg-history-item').count(), 0,
            width + '/' + language + ': full/recent views render no history cards');
        } else {
          assert.equal(await page.locator('#knowledgeGraphSideTabs').isVisible(), true,
            width + '/' + language + ': history has detail/history sidebar tabs');
          assert.equal(await page.locator('#knowledgeGraphHistoryTab').isVisible(), true,
            width + '/' + language + ': history view exposes the history tab');
          assert.match(await page.locator('#knowledgeGraphHistoryTab').innerText(), /(?:历史题目|Past questions).*3/,
            width + '/' + language + ': all three question sources are counted');
          assert.equal(await page.locator('#knowledgeGraphHistoryWrap').isVisible(), true,
            width + '/' + language + ': entering history initially shows the question list');
          assert.equal(await page.locator('#knowledgeGraphModal .kg-history-item').count(), 3);
          await page.locator('#knowledgeGraphHistory .kg-history-item').last().locator('[data-history-action="graph"]').click();
          await page.waitForFunction(() => knowledgeGraphViewMode === 'history' && knowledgeGraphSelectedNodeId === 'logic_equivalence');
          assert.equal(await page.locator('#knowledgeGraphDetailWrap').isVisible(), true,
            width + '/' + language + ': selecting a historical graph opens its node details');
          assert.equal(await page.locator('#knowledgeGraphLocateOriginal').count(), 0,
            width + '/' + language + ': historical node details omit the recent-only locate action');
        }
        assert.equal(await page.locator('#knowledgeGraphDetailTitle').evaluate(title => title.hidden), false,
          width + ': latest-question node details remain available');
        assert.equal(await page.evaluate(() => JSON.stringify(getCurrent().messages)), metadataBefore,
          width + ': graph mode/language navigation does not mutate chat or question metadata');
      }
    }
    await page.evaluate(() => { closeKnowledgeGraph(); openKnowledgeGraph(); });
    await page.waitForFunction(() => document.getElementById('knowledgeGraphModal').dataset.graphReady === 'true');
    assert.equal(await page.locator('#knowledgeGraphHistoryTab').isVisible(), false,
      width + ': reopening in recent-question mode keeps history hidden');
    assert.equal(await page.locator('#knowledgeGraphModal .kg-history-item').count(), 0,
      width + ': recent-question mode does not restore old history cards');
    assert.equal(await page.evaluate(() => JSON.stringify(getCurrent().messages)), metadataBefore,
      width + ': manual/OCR/generated source, classification, type and difficulty remain in actual messages');
    assert.deepEqual(errors, [], width + ': browser errors');
    console.log('PASS ' + width + ': separate full/recent/history modes in both languages; original manual/OCR/AI metadata retained');
  } finally { await page.close(); }
}

async function checkConversationModes(browser, width) {
  const page = await browser.newPage({ viewport: { width, height: 844 },
    ...(width <= 760 ? { isMobile: true, hasTouch: true } : {}) });
  const errors = [], analysis = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/auth/me', route => route.fulfill({ contentType: 'application/json', body: '{"configured":true,"authenticated":false}' }));
  await page.route('**/analyze-questions', route => {
    analysis.push(route.request().url()); return route.fulfill({ contentType: 'application/json', body: '{"entries":[]}' });
  });
  const open = async () => {
    await page.evaluate(() => openKnowledgeGraph());
    await page.waitForFunction(() => document.getElementById('knowledgeGraphModal').dataset.graphReady === 'true');
  };
  const navigate = async id => {
    await page.evaluate(() => closeKnowledgeGraph());
    await page.locator('#sessions > .session[data-session-id="' + id + '"] [data-session-name]').evaluate(node => node.click());
    await page.waitForFunction(id => String(currentId) === id, id);
    await open();
  };
  const home = async () => {
    await page.evaluate(() => { closeKnowledgeGraph(); currentId = null; renderAll(); });
    await open();
  };
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await page.waitForFunction(() => !accountVerificationOperation);
    await page.evaluate(() => {
      const conversation = (id, question, quote) => {
        const teaching = { category: '命题逻辑', knowledge_points: ['逻辑联结词'], focus_points: ['逻辑联结词'],
          question_graph: { version: 1,classifier_revision:'catalog-semantic-v5',classification_status:'semantic',classification_source:'catalog_semantic',needs_review:false, sources: { question, solution: '' },
            nodes: [{ id: 'logic_connectives', evidence: [{ source: 'question', quote }] }], edges: [] } };
        return { id, name: id, nameSource: 'user', learningQuestion: null, teaching,
          messages: [{ messageId: id + '-question', role: 'user', text: question, manualIsQuestion: true, questionTeaching: teaching }] };
      };
      sessions = [conversation('mode-a', '判断 p 与 q 的合取在什么情况下为真。', '合取'),
        conversation('mode-b', '判断 p 与 r 的析取在什么情况下为真。', '析取'),
        { id: 'mode-empty', name: 'Existing empty conversation', nameSource: 'user', messages: [], teaching: null, learningQuestion: null }];
      currentId = 'mode-a'; renderAll();
    });
    await open();
    assert.equal(await page.evaluate(() => knowledgeGraphViewMode), 'full', width + ': first graph defaults to all knowledge');
    for (const mode of ['focus', 'history']) {
      await page.evaluate(mode => selectKnowledgeGraphDisplayMode(mode), mode);
      for (const destination of ['mode-b', 'mode-empty', 'mode-a']) {
        await navigate(destination);
        assert.equal(await page.evaluate(() => knowledgeGraphViewMode), mode,
          width + ': switching to ' + destination + ' preserves the selected ' + mode + ' page');
      }
    }
    await home();
    assert.equal(await page.evaluate(() => knowledgeGraphViewMode), 'full', width + ': entering the centered home resets to all knowledge');
    for (const mode of ['focus', 'history']) {
      await page.evaluate(mode => { selectKnowledgeGraphDisplayMode(mode); renderAll(); }, mode);
      assert.equal(await page.evaluate(() => knowledgeGraphViewMode), mode,
        width + ': rerendering the same home does not undo an explicit ' + mode + ' selection');
      await page.evaluate(() => closeKnowledgeGraph());
      await open();
      assert.equal(await page.evaluate(() => knowledgeGraphViewMode), 'full', width + ': closing a home graph resets the next opening to all knowledge');
    }
    await navigate('mode-a');
    assert.equal(await page.evaluate(() => knowledgeGraphViewMode), 'full', width + ': entering a conversation retains the reset all-knowledge page');
    await page.locator('#knowledgeGraphScopeBtn').click();
    await page.evaluate(() => newChat());
    assert.deepEqual(await page.evaluate(() => ({ mode: knowledgeGraphViewMode, empty: getCurrent()?.messages.length === 0,
      hasConversation: currentId !== null })), { mode: 'focus', empty: true, hasConversation: true },
    width + ': creating a new conversation preserves the page and is distinct from home');
    await home();
    assert.equal(await page.evaluate(() => knowledgeGraphViewMode), 'full', width + ': returning home resets all knowledge again');
    await navigate('mode-b');
    assert.equal(await page.evaluate(() => knowledgeGraphViewMode), 'full', width + ': conversation entry retains the reset full page');
    assert.deepEqual(analysis, [], width + ': navigation uses source-bound fixtures without reclassification');
    assert.deepEqual(errors, [], width + ': conversation/home mode checks have no page errors');
    console.log('PASS ' + width + ': full default, conversation/new-chat page preservation, home-entry reset and explicit home selection');
  } finally { await page.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true, ignoreDefaultArgs: ['--hide-scrollbars'],
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const width of [1440, 390]) await checkEmptyRecent(browser, width);
    for (const width of [1440, 390]) await checkHistoryModes(browser, width);
    for (const width of [1440, 390]) await checkConversationModes(browser, width);
  }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
