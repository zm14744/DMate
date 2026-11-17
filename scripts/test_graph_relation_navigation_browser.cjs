/* Exercise graph relations, mode decoration and export through the real app.
 * Model/account routes are isolated; no paid inference or cloud writes occur.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const historyCards = '#knowledgeGraphModal .kg-history-item';

async function settle(page) {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function nodeLabel(page, id) {
  return page.evaluate(id => dmateKnowledgeLabel(findKnowledgeGraphNodeById(id).name), id);
}

async function checkDecoration(page, focus, label) {
  const result = await page.evaluate(async () => {
    const decorations = target => ({
      purple: [...target.querySelectorAll('.kg-node-group > rect,.kg-mobile-node')].filter(node => {
        const color = node.tagName.toLowerCase() === 'rect' ? node.getAttribute('fill') : node.style.backgroundColor;
        return color === '#5b21b6' || color === 'rgb(91, 33, 182)';
      }).length,
      badges: [...target.querySelectorAll('[data-badge]')].map(node => node.dataset.badge).filter(Boolean)
    });
    const target = buildKnowledgeGraphImageCopyTarget();
    if (!target) throw Error('A valid graph must have an image-copy target');
    const clone = decorations(target);
    target.remove();
    const fills = [], text = [];
    const originalFill = CanvasRenderingContext2D.prototype.fill;
    const originalText = CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fill = function (...args) {
      fills.push(this.fillStyle); return originalFill.apply(this, args);
    };
    CanvasRenderingContext2D.prototype.fillText = function (value, ...args) {
      text.push(String(value)); return originalText.call(this, value, ...args);
    };
    try {
      const png = await renderKnowledgeGraphOffscreenPngBlob();
      return { clone, fills, text, png: { type: png.type, bytes: png.size },
        statusPills: document.querySelectorAll('#knowledgeGraphDetail .graph-status-pill.current').length,
        relatedLegend: [...document.querySelectorAll('#knowledgeGraphLegendRelated,.graph-legend')]
          .filter(node => node.getClientRects().length && getComputedStyle(node).visibility !== 'hidden').length };
    } finally {
      CanvasRenderingContext2D.prototype.fill = originalFill;
      CanvasRenderingContext2D.prototype.fillText = originalText;
    }
  });
  const related = value => /^(本题|本题相关|历史题|历史题相关|本对话相关|This question|Current question|Related to this question|Related to the selected question|Related to this conversation|Earlier question)$/i.test(value);
  assert.equal(result.png.type, 'image/png', label + ': real offscreen export produces PNG');
  assert.ok(result.png.bytes > 1000, label + ': real offscreen export contains graph pixels');
  if (focus) {
    assert.ok(result.clone.purple > 0, label + ': current-question nodes retain their focus decoration');
    assert.ok(result.fills.includes('#5b21b6'), label + ': focused PNG retains the current-question fill');
    assert.equal(result.statusPills, 0, label + ': focused details omit the redundant current-question pill');
  } else {
    assert.equal(result.clone.purple, 0, label + ': all-knowledge DOM/export clone has no current-question fill');
    assert.equal(result.fills.includes('#5b21b6'), false, label + ': all-knowledge PNG has no current-question fill');
    assert.deepEqual(result.clone.badges.filter(related), [], label + ': all-knowledge clone has no current-question node badge');
    assert.deepEqual(result.text.filter(related), [], label + ': all-knowledge PNG has no current-question badge');
    assert.equal(result.statusPills, 0, label + ': all-knowledge detail has no related pill');
    assert.equal(result.relatedLegend, 0, label + ': all-knowledge graph has no related legend');
  }
}

async function expectDestination(page, id, category, label) {
  await page.waitForFunction(({ id, category }) => knowledgeGraphViewMode === 'full'
    && knowledgeGraphFilter === category && knowledgeGraphSelectedNodeId === id, { id, category });
  await settle(page);
  assert.equal(await page.locator('#knowledgeGraphCategory').inputValue(), category, label + ': module selector follows the target');
  assert.equal(await page.locator('#knowledgeGraphDetailTitle').innerText(), await nodeLabel(page, id),
    label + ': target details are selected');
  assert.equal(await page.locator('#knowledgeGraphFocusBtn').getAttribute('aria-pressed'), 'true', label + ': all-knowledge mode is active');
  assert.equal(await page.locator('#knowledgeGraphHistoryTab').count(), 1, label + ': all-knowledge mode retains its question-history entry');
  const visible = await page.evaluate(id => {
    const canvas = document.getElementById('knowledgeGraphCanvas');
    const node = canvas.querySelector('.selected[data-knowledge-node-id="' + id + '"]');
    const viewport = canvas.querySelector('.kg-mobile-viewport,.kg-desktop-viewport');
    if (!node || !viewport) return false;
    const bounds = node.getBoundingClientRect(), frame = viewport.getBoundingClientRect();
    return bounds.width > 0 && bounds.height > 0 && bounds.left >= frame.left - 2 && bounds.right <= frame.right + 2
      && bounds.top >= frame.top - 2 && bounds.bottom <= frame.bottom + 2;
  }, id);
  assert.equal(visible, true, label + ': selected target is revealed in the graph viewport');
}

async function checkCase(browser, width, language) {
  const mobile = width <= 760, label = width + '/' + language;
  const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block',
    ...(mobile ? { isMobile: true, hasTouch: true } : {}) });
  const page = await context.newPage(), errors = [], modelCalls = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/auth/me', route => route.fulfill({ contentType: 'application/json', body: '{"configured":true,"authenticated":false}' }));
  await page.route(/\/(?:chat|analyze-questions|classify|conversation\/title|ocr)(?:\?|$)/, route => {
    modelCalls.push(new URL(route.request().url()).pathname); return route.abort();
  });
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    const before = await page.evaluate(language => {
      newChat();
      const teaching = { category: '证明与归纳', knowledge_points: ['数学归纳法'], focus_points: ['数学归纳法'] };
      const session = getCurrent();
      session.messages = [{ role: 'user', messageId: 'relation-question', text: '用数学归纳法证明自然数求和公式。',
        manualIsQuestion: true, questionTeaching: teaching }];
      session.teaching = teaching; session.learningQuestion = null;
      DMateI18n.setLanguage(language, false);
      void openKnowledgeGraph();
      return JSON.stringify(session.messages);
    }, language);
    await page.waitForFunction(() => knowledgeGraphInitialized && document.getElementById('knowledgeGraphModal').dataset.graphReady === 'true');
    assert.equal(await page.locator('#knowledgeGraphHistoryTab').isVisible(), false, label + ': recent-question view hides the history entry');
    assert.equal(await page.locator('#knowledgeGraphHistoryWrap').isVisible(), false, label + ': recent-question view hides history content');
    assert.equal(await page.locator(historyCards).count(), 0, label + ': recent-question view renders no history cards');
    await checkDecoration(page, true, label + '/recent');

    await page.locator('#knowledgeGraphFocusBtn').click();
    await checkDecoration(page, false, label + '/all');
    await page.locator('#knowledgeGraphScopeBtn').click();
    const predecessor = page.locator('#knowledgeGraphDetail .graph-detail-term[data-knowledge-node-id="logic_reasoning"]');
    await predecessor.waitFor({ state: 'visible' });
    assert.equal(await predecessor.evaluate(node => node.tagName), 'BUTTON', label + ': predecessor is keyboard-accessible');
    await predecessor.focus();
    await page.keyboard.press('Enter');
    await expectDestination(page, 'logic_reasoning', '命题逻辑', label + '/predecessor Enter');
    await checkDecoration(page, false, label + '/navigated full');

    await page.evaluate(() => {
      setKnowledgeGraphFullscreenView(false);
      setKnowledgeGraphFilter('全部'); selectKnowledgeGraphNode('set_operation');
    });
    const successor = page.locator('#knowledgeGraphDetail .graph-detail-term[data-knowledge-node-id="function_mapping"]');
    await successor.click();
    await expectDestination(page, 'function_mapping', '函数', label + '/cross-module successor');

    await page.evaluate(() => {
      setKnowledgeGraphFullscreenView(false);
      setKnowledgeGraphFilter('证明与归纳'); selectKnowledgeGraphNode('proof_induction');
    });
    if (mobile) await page.locator('.kg-mobile-expand').click();
    const viewSelector = mobile ? '.kg-mobile-viewport' : '.kg-desktop-viewport';
    await page.waitForSelector(viewSelector);
    await settle(page);
    const view = await page.locator(viewSelector).elementHandle();
    const camera = () => view.evaluate(node => ({ scale: node._kgScale || Number(node.querySelector('.kg-desktop-zoom-surface').dataset.scale),
      left: node.scrollLeft, top: node.scrollTop }));
    await page.locator(mobile ? '.kg-mobile-zoom-btn' : '#knowledgeGraphDesktopZoomIn').last().click();
    await settle(page);
    // Make the destination visible before testing the camera-preserving path;
    // a target outside the viewport is expected to scroll just into view.
    await view.evaluate(node => {
      const target = node.querySelector('[data-knowledge-node-id="proof_strong_induction"]');
      const bounds = target.getBoundingClientRect(), frame = node.getBoundingClientRect();
      if (bounds.left < frame.left + 10) node.scrollLeft += bounds.left - frame.left - 10;
      else if (bounds.right > frame.right - 10) node.scrollLeft += bounds.right - frame.right + 10;
      if (bounds.top < frame.top + 10) node.scrollTop += bounds.top - frame.top - 10;
      else if (bounds.bottom > frame.bottom - 10) node.scrollTop += bounds.bottom - frame.bottom + 10;
    });
    await settle(page);
    const cameraBefore = await camera();
    if (mobile) await page.evaluate(() => setKnowledgeGraphFullscreenView(false));
    await page.locator('#knowledgeGraphDetail .graph-detail-term[data-knowledge-node-id="proof_strong_induction"]').click();
    await expectDestination(page, 'proof_strong_induction', '证明与归纳', label + '/same-module successor');
    assert.equal(await view.evaluate(node => node.isConnected), true, label + ': same-module relation retains the graph DOM');
    await settle(page);
    assert.deepEqual(await camera(), cameraBefore, label + ': same-module relation preserves zoom/pan');
    assert.equal(await page.locator('#knowledgeGraphCanvas .selected[data-label]').getAttribute('data-label'),
      await nodeLabel(page, 'proof_strong_induction'), label + ': the destination node receives the selected outline');
    assert.equal(await page.evaluate(() => JSON.stringify(getCurrent().messages)), before, label + ': navigation leaves the real conversation untouched');
    assert.deepEqual(modelCalls, [], label + ': graph navigation/export invokes no model');
    assert.deepEqual(errors, [], label + ': browser errors');
    console.log('PASS ' + label + ': relation tags navigate modules by click/Enter, same-module camera stays, full mode/export omit question decoration while retaining the full-only history entry');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try { for (const width of [1440, 390]) for (const language of ['zh-CN', 'en']) await checkCase(browser, width, language); }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
