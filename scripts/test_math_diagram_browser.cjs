/* Real online drawing controls and Graphviz WASM; only paid API responses are
 * intercepted. Start Flask first, then run with the same env as browser suites.
 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const settle = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));

function fixture(kind, title, cycle = false) {
  const count = kind === 'hasse' ? 3 : 5;
  const vertices = Array.from({ length: count }, (_, i) => ({ id: 'vertex-' + i, label: kind === 'hasse' ? String(2 ** i) : String(i) }));
  const edges = [];
  for (let i = 0; i < count; i++) for (let j = i + 1; j < count; j++) {
    if (kind === 'hasse' ? j === i + 1 : !cycle || j === i + 1 || (i === 0 && j === count - 1)) edges.push({ id: 'edge-' + edges.length,
      from: vertices[i].id, to: vertices[j].id, direction: 'undirected' });
  }
  return { ok: true, title, kind, document: { body_text: '', graphs: [{ id: 'G1', name: title,
    directed: false, weighted: false, vertices, edges }] } };
}

async function openDrawing(page) {
  const toggle = page.locator(page.viewportSize().width <= 1100 ? '#mobileToolsBtn' : '#desktopToolsBtn');
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
  await page.locator('#graphDrawingBtn').click();
  await page.locator('#graphEditorDialog[open] .dmate-drawing-workspace').waitFor();
  await page.waitForFunction(() => !document.getElementById('graphEditorDialog').dataset.positioning);
  await settle(page);
}

async function state(page) {
  return page.evaluate(() => ({ pages: ocrEditorController.getPages(), document: ocrEditorController.getDocument(),
    name: document.querySelector('.ddw-name').value }));
}

async function ai(page, requirement) {
  const historyToggle = page.locator('.ddw-page-actions button').nth(1);
  if (await historyToggle.getAttribute('aria-expanded') === 'true') await historyToggle.click();
  const toggle = page.locator('[data-drawing-ai-generation]');
  assert.equal(await toggle.isEnabled(), true, 'AI generation must be reachable even with an empty gallery');
  assert.equal(await toggle.evaluate(button => Boolean(button.closest('[inert]'))), false, 'AI entry must not inherit inert');
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
  await page.locator('.ddw-ai-requirement').fill(requirement);
  const generate = page.locator('[data-math-diagram-generate]');
  assert.equal(await generate.evaluate(button => Boolean(button.closest('.ddw-side-panel'))), true,
    'Only the generation popover arrow submits a request');
  assert.equal(await generate.isEnabled(), Boolean(requirement.trim()), 'Generation requires nonblank drawing requirements');
  return generate;
}

async function panelStyle(page, action) {
  await page.mouse.move(0, 0);
  await page.evaluate(() => document.activeElement?.blur());
  await page.evaluate(async () => {
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    await Promise.all(document.getAnimations().filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity)
      .map(animation => animation.finished.catch(() => {})));
  });
  return page.locator('.ddw-side-panel').evaluate((panel, action) => {
    const css = node => Object.fromEntries(['backgroundColor', 'backgroundImage', 'borderWidth', 'borderColor',
      'borderRadius', 'boxShadow', 'color', 'fontSize', 'fontFamily', 'fontWeight', 'padding', 'lineHeight']
      .map(key => [key, getComputedStyle(node)[key]]));
    const input = panel.querySelector('.ddw-ai-requirement'), button = panel.querySelector(action);
    const box = node => { const rect = node.getBoundingClientRect(); return [rect.width, rect.height]; };
    return { panel: css(panel), heading: css(panel.querySelector('h3')), label: css(panel.querySelector('.ddw-ai-label')),
      input: css(input), inputSize: box(input), button: css(button), buttonSize: box(button),
      arrow: button.querySelector('svg').outerHTML };
  }, action);
}

async function passiveGenerationPanel(page, mock, guideRequests, initial, language) {
  const generation = page.locator('[data-drawing-ai-generation]'), guidance = page.locator('[data-drawing-ai-guidance]');
  assert.equal(await generation.locator('[data-math-diagram-generate]').count(), 0, 'The rail is a toggle, not a submit control');
  assert.equal(await generation.getAttribute('data-math-diagram-generate'), null);
  const unchanged = async label => {
    assert.equal(mock.requests.length, 0, label + ': no generation request');
    assert.deepEqual(guideRequests, [], label + ': no guidance request');
    const current = await state(page);
    assert.deepEqual(current.pages.map(item => item.id), initial.pages.map(item => item.id), label + ': no new drawing page');
    assert.deepEqual(current.document, initial.document, label + ': current drawing stays intact');
  };
  const requiredLabel = language === 'en' ? 'Diagram request' : '绘图要求';
  const guidanceLabel = language === 'en' ? 'Guidance request' : '指导要求';
  const request = 'K5 request retained without submitting';
  await ai(page, '');
  assert.equal(await page.locator('.ddw-side-panel h3').innerText(), language === 'en' ? 'AI generation' : 'AI生成');
  assert.equal(await page.locator('.ddw-ai-requirement').getAttribute('aria-label'), requiredLabel);
  assert.equal(await page.locator('.ddw-ai-requirement').getAttribute('required'), '');
  assert.equal(await page.locator('[data-drawing-guide]').count(), 0, 'Generation and guidance have separate submit actions');
  const originalTheme = await page.evaluate(() => [document.documentElement.dataset.appearanceTheme, document.body.dataset.appearanceTheme]);
  for (const theme of ['dark', 'navy']) {
    await page.evaluate(value => { document.documentElement.dataset.appearanceTheme = document.body.dataset.appearanceTheme = value; }, theme);
    const disabledStyle = await panelStyle(page, '[data-math-diagram-generate]');
    const composerStyle = await page.locator('#sendBtn').evaluate(button => ({
      background: getComputedStyle(button).backgroundColor, arrow: getComputedStyle(button, '::before').backgroundColor
    }));
    assert.equal(disabledStyle.button.backgroundColor, composerStyle.background, theme + ': the inactive generation arrow shares the composer surface');
    assert.equal(disabledStyle.button.color, composerStyle.arrow, theme + ': the inactive generation arrow shares the composer icon color');
  }
  await page.evaluate(([rootTheme, bodyTheme]) => {
    document.documentElement.dataset.appearanceTheme = rootTheme; document.body.dataset.appearanceTheme = bodyTheme;
  }, originalTheme);
  const disabledStyle = await panelStyle(page, '[data-math-diagram-generate]');
  for (const value of ['', '  \n\t  ']) {
    await page.locator('.ddw-ai-requirement').fill(value);
    assert.equal(await page.locator('[data-math-diagram-generate]').isDisabled(), true);
    await page.locator('[data-math-diagram-generate]').evaluate(button => {
      button.click();
      button.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await page.locator('.ddw-ai-requirement').press('Enter');
    await settle(page);
    await unchanged('Blank input, click and Enter');
  }
  if (process.env.OFFLINE_SCREENSHOT_DIR) {
    await fs.mkdir(process.env.OFFLINE_SCREENSHOT_DIR, { recursive: true });
    await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/generation-panel-' + page.viewportSize().width + '-' + language + '.png' });
  }
  await unchanged('Opening generation');
  await page.locator('.ddw-ai-requirement').fill(request); await settle(page);
  assert.equal(await page.locator('[data-math-diagram-generate]').isEnabled(), true);
  const generationStyle = await panelStyle(page, '[data-math-diagram-generate]');
  assert.equal(generationStyle.buttonSize[0], generationStyle.buttonSize[1], 'Generation submit is circular');
  assert.ok(parseFloat(generationStyle.button.borderRadius) >= generationStyle.buttonSize[0] / 2
    || generationStyle.button.borderRadius.includes('%'), 'Generation uses the guidance arrow circle');
  const rgb = generationStyle.button.backgroundColor.match(/[\d.]+/g).map(Number);
  assert.ok(rgb[2] > rgb[0] + 30 && rgb[2] > rgb[1], 'A valid generation request activates the blue action color');
  await page.locator('.ddw-ai-requirement').fill('  ');
  assert.equal(await page.locator('[data-math-diagram-generate]').isDisabled(), true, 'Deleting the requirement disables send again');
  assert.equal((await panelStyle(page, '[data-math-diagram-generate]')).button.backgroundColor,
    disabledStyle.button.backgroundColor, 'Deleting the requirement restores the inactive surface');
  await page.locator('.ddw-ai-requirement').fill(request);
  await unchanged('Typing the required request');
  await generation.click();
  assert.equal(await page.locator('.ddw-side-panel').isVisible(), false, 'Clicking the rail again closes the panel');
  await unchanged('Closing generation');
  await generation.click();
  assert.equal(await page.locator('.ddw-ai-requirement').inputValue(), request);
  await unchanged('Reopening generation');
  await guidance.click();
  assert.equal(await generation.getAttribute('aria-expanded'), 'false');
  assert.equal(await guidance.getAttribute('aria-expanded'), 'true');
  assert.equal(await page.locator('.ddw-side-panel:visible').count(), 1, 'There is one anchored popover');
  assert.equal(await page.locator('.ddw-side-panel h3').innerText(), language === 'en' ? 'AI guidance' : 'AI指导');
  assert.equal(await page.locator('[data-math-diagram-generate]').count(), 0);
  const popoverIntersectsRail = await page.locator('.ddw-side-panel').evaluate(panel => {
    const p = panel.getBoundingClientRect(), r = panel.closest('.dmate-drawing-workspace').querySelector('.ddw-side-actions').getBoundingClientRect();
    return p.left < r.right && p.right > r.left && p.top < r.bottom && p.bottom > r.top;
  });
  assert.equal(popoverIntersectsRail, false, 'Guidance leaves every wrapped toolbar row reachable');
  assert.equal(await page.locator('.ddw-ai-requirement').getAttribute('aria-label'), guidanceLabel);
  assert.equal(await page.locator('.ddw-ai-requirement').getAttribute('required'), '');
  assert.deepEqual(await panelStyle(page, '[data-drawing-guide]'), generationStyle,
    'Generation and guidance share the same popover, input and enabled arrow styling');
  for (const value of ['', '  \n\t　']) {
    await page.locator('.ddw-ai-requirement').fill(value);
    const send = page.locator('[data-drawing-guide]');
    assert.equal(await send.isDisabled(), true, 'Blank guidance disables the arrow');
    assert.deepEqual((await panelStyle(page, '[data-drawing-guide]')).button, disabledStyle.button,
      'Blank guidance matches the disabled generation arrow');
    await send.dispatchEvent('click');
    await page.locator('.ddw-ai-requirement').press('Enter');
    await settle(page);
    await unchanged('Blank guidance, click and Enter');
  }
  await page.locator('.ddw-ai-requirement').fill(request);
  assert.equal(await page.locator('[data-drawing-guide]').isEnabled(), true, 'Typing a guidance request enables the arrow');
  await unchanged('Switching to guidance');
  await generation.click();
  await page.evaluate(value => DMateI18n.setLanguage(value, false), language === 'en' ? 'zh-CN' : 'en');
  await settle(page); await unchanged('Changing the language');
  await page.evaluate(value => DMateI18n.setLanguage(value, false), language);
  await settle(page);
  assert.equal(await page.locator('.ddw-ai-requirement').inputValue(), request);
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('.ddw-side-panel').isVisible(), false);
  assert.equal(await generation.evaluate(button => document.activeElement === button), true, 'Escape restores focus to the generation rail');
  await unchanged('Escaping generation');
}

async function notice(page, expected) {
  const dialog = page.locator('.dmate-delete-confirm[open]');
  await dialog.waitFor();
  const message = await dialog.locator('.dmate-delete-confirm-body').textContent();
  assert.match(message, expected);
  await dialog.locator('.dmate-delete-confirm-close').click();
  await dialog.waitFor({ state: 'detached' });
  return message;
}

async function history(page) {
  const toggle = page.locator('.ddw-page-actions button').nth(1);
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
  await page.locator('.ddw-history-list').waitFor();
  return page.locator('.ddw-history-open');
}

function mockGenerator(page) {
  const plans = [], unexpected = [], requests = [];
  const install = page.route('**/drawing/generate', async route => {
    const payload = route.request().postDataJSON(); requests.push(payload);
    const plan = plans.shift();
    if (!plan) { unexpected.push(payload); await route.abort(); return; }
    plan.received({ payload, request: route.request() });
    await plan.released;
    await route.fulfill({ status: plan.response.status || 200,
      contentType: plan.response.raw === undefined ? 'application/json' : 'text/plain',
      body: plan.response.raw === undefined ? JSON.stringify(plan.response.json) : plan.response.raw }).catch(() => {});
  });
  return { install, unexpected, requests, enqueue(response, hold = false) {
    let received, release;
    const started = new Promise(resolve => { received = resolve; });
    const released = new Promise(resolve => { release = resolve; });
    plans.push({ response, received, released });
    if (!hold) release();
    return { started, release };
  } };
}

async function checkDiagram(page, expected) {
  const actual = await state(page), graph = actual.document.graphs[0], source = expected.document.graphs[0];
  assert.equal(actual.name, expected.title);
  assert.deepEqual(graph.vertices.map(vertex => [vertex.id, vertex.label]), source.vertices.map(vertex => [vertex.id, vertex.label]));
  assert.deepEqual(graph.edges.map(edge => [edge.from, edge.to]), source.edges.map(edge => [edge.from, edge.to]));
  for (const vertex of graph.vertices) assert.ok(Number.isFinite(vertex.x) && vertex.x >= 0 && vertex.x <= 1
    && Number.isFinite(vertex.y) && vertex.y >= 0 && vertex.y <= 1, 'Graphviz supplies real normalized coordinates');
  const vertices = new Map(graph.vertices.map(vertex => [vertex.id, vertex]));
  for (const edge of graph.edges) {
    assert.ok(Array.isArray(edge.path) && edge.path.length >= 2 && edge.path.length <= 128,
      edge.id + ': Graphviz routing survives import into the editor');
    for (const point of edge.path) assert.ok(Array.isArray(point) && point.length === 2
      && point.every(value => Number.isFinite(value) && value >= 0 && value <= 1), edge.id + ': finite normalized path coordinates');
    for (const [point, vertex] of [[edge.path[0], vertices.get(edge.from)], [edge.path.at(-1), vertices.get(edge.to)]]) {
      assert.ok(Math.hypot(point[0] - vertex.x, point[1] - vertex.y) < 1e-9, edge.id + ': routed endpoints match their vertices');
    }
  }
  assert.equal(new Set(graph.vertices.map(vertex => vertex.x + ',' + vertex.y)).size, graph.vertices.length, 'Layout must not collapse all vertices');
  assert.equal(await page.locator('.dge-overlay-node').count(), source.vertices.length);
  assert.equal(await page.locator('.dge-overlay-edge').count(), source.edges.length);
  const renderedPaths = await page.locator('.dge-overlay-edge').evaluateAll(groups => groups.map(group => [group.dataset.edgeId,
    (group.querySelector('.dge-overlay-hit').getAttribute('d').match(/L/g) || []).length]));
  for (const [id, segments] of renderedPaths) assert.equal(segments, graph.edges.find(edge => edge.id === id).path.length - 1,
    id + ': real SVG renders the routed path rather than a replacement straight line');
  assert.equal(await page.locator('script[src="/static/vendor/viz-js-3.31.0/viz-global.js"]').count(), 1, 'The real pinned Graphviz bundle was loaded');
  if (expected.kind === 'hasse') assert.ok(graph.vertices[0].y > graph.vertices[1].y && graph.vertices[1].y > graph.vertices[2].y,
    'Hasse layout orders the divisibility chain from bottom to top');
  return actual;
}

async function pngDownload(page, mobile) {
  const historyToggle = page.locator('.ddw-page-actions button').nth(1);
  if (await historyToggle.getAttribute('aria-expanded') === 'true') await historyToggle.click();
  const downloading = page.waitForEvent('download');
  downloading.catch(() => {});
  await page.locator('[data-drawing-export]').click();
  if (mobile) {
    const preview = page.locator('.ddw-export-preview'); await preview.waitFor();
    await page.waitForFunction(() => document.querySelector('.ddw-export-image')?.naturalWidth > 64);
    const typography = locator => locator.evaluate(node => Object.fromEntries(
      ['fontFamily','fontSize','fontWeight','lineHeight'].map(key => [key,getComputedStyle(node)[key]])));
    assert.deepEqual(await typography(preview.locator('.ddw-export-header>h3')),
      await typography(page.locator('#appConfirmTitle')), 'Drawing export title matches ordinary modal typography');
    const dot = locator => locator.evaluate(node => {
      const style = getComputedStyle(node), box = node.getBoundingClientRect();
      return { width:box.width, height:box.height, background:style.backgroundColor,
        border:style.borderWidth, radius:style.borderRadius };
    });
    assert.deepEqual(await dot(preview.locator('.ddw-export-close')),
      await dot(page.locator('#graphEditorClose')), 'Image preview uses the same solid red close dot as the drawing dialog');
    await preview.locator('.ddw-export-download').click();
  }
  const download = await downloading;
  assert.match(download.suggestedFilename(), /\.png$/);
  const stream = await download.createReadStream(), chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
  const bytes = Buffer.concat(chunks);
  assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  assert.ok(bytes.readUInt32BE(16) > 64 && bytes.readUInt32BE(20) > 64, 'Export contains a usable raster drawing');
  assert.equal(await download.failure(), null);
  if (mobile) await page.locator('.ddw-export-close').click();
  return { bytes: bytes.length, width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

async function runCase(browser, width, language) {
  const page = await browser.newPage({ viewport: { width, height: 900 }, isMobile: width < 760, hasTouch: width < 760,
    ...(width < 760 ? { userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36' } : {}),
    serviceWorkers: 'block' }); // keep paid endpoints entirely inside Playwright's route interception
  const errors = [], guideRequests = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/drawing/guide', route => { guideRequests.push(route.request().url()); return route.abort(); });
  const mock = mockGenerator(page); await mock.install;
  try {
    await page.goto(baseURL + '/', { waitUntil: 'networkidle' });
    await page.evaluate(value => DMateI18n.setLanguage(value, false), language);
    await openDrawing(page);
    const initial = await state(page);
    assert.equal(initial.pages.length, 1, 'Opening an empty online gallery creates one blank page');
    assert.deepEqual(initial.document.graphs[0].vertices, []);
    assert.deepEqual(initial.document.graphs[0].edges, []);
    assert.equal(await page.locator('.ddw-name').isEnabled(), true, 'The automatic page is editable');
    await passiveGenerationPanel(page, mock, guideRequests, initial, language);
    // Keep covering AI generation from a genuinely empty gallery after the
    // user deletes the automatic page, without reopening the workspace.
    await history(page);
    await page.locator('.ddw-history-delete').click();
    await page.locator('.dmate-delete-confirm-delete').click();
    await page.waitForFunction(() => ocrEditorController.getPages().length === 0);
    assert.deepEqual((await state(page)).pages, [], 'Deleting the last page keeps this open gallery empty');
    const emptySubmit = await ai(page, '');
    assert.equal(mock.requests.length, 0, 'Opening generation from an empty gallery still makes no request');
    assert.equal((await state(page)).pages.length, 0, 'The empty-gallery request panel creates no page before send');
    assert.equal(await emptySubmit.isDisabled(), true, 'An empty gallery also requires an explicit drawing request');
    await emptySubmit.evaluate(button => button.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    await settle(page);
    assert.equal(mock.requests.length, 0, 'Blank submission never falls back to a preset mathematical diagram');
    assert.equal((await state(page)).pages.length, 0);
    const cycleRequirement = language === 'en' ? 'Draw a cycle graph C5.' : '生成五阶环图 C5。';
    const starter = fixture('graph', 'C5', true), cycleRequest = mock.enqueue({ json: starter });
    await (await ai(page, '  ' + cycleRequirement + '  ')).click();
    const cyclePayload = (await cycleRequest.started).payload;
    assert.deepEqual(cyclePayload, { requirement: cycleRequirement, language }, 'Generation submits the explicit trimmed drawing request');
    await notice(page, language === 'en' ? /diagram generated/i : /数学图已生成/);
    assert.equal(await page.locator('.ddw-ai-requirement').count(), 0,
      'Successful generation closes the request popover');
    const started = await checkDiagram(page, starter);
    assert.equal(started.pages[0].requirement, cycleRequirement, 'The generated page retains the explicit drawing requirement');
    await history(page);
    await page.locator('.ddw-history-delete').click();
    await page.locator('.dmate-delete-confirm-delete').click();
    await page.waitForFunction(() => ocrEditorController.getPages().length === 0);

    const requirement = language === 'en' ? 'Draw the complete graph K5 with vertices 0,1,2,3,4.' : '生成完全图 K5，顶点为 0、1、2、3、4。';
    const complete = fixture('graph', 'K5'), first = mock.enqueue({ json: complete });
    await (await ai(page, requirement)).click();
    assert.deepEqual((await first.started).payload, { requirement, language });
    await notice(page, language === 'en' ? /diagram generated/i : /数学图已生成/);
    const original = await checkDiagram(page, complete);
    await page.locator('.ddw-page-actions button').nth(0).click();
    const before = await state(page);
    const hasse = fixture('hasse', language === 'en' ? 'Divisibility Hasse diagram' : '整除关系哈斯图');
    mock.enqueue({ json: hasse });
    await (await ai(page, language === 'en' ? 'Draw the Hasse diagram of divisibility on {1,2,4}.' : '生成集合 {1,2,4} 整除关系的哈斯图。')).click();
    await notice(page, language === 'en' ? /diagram generated/i : /数学图已生成/);
    const generated = await checkDiagram(page, hasse);
    assert.deepEqual(generated.pages.slice(0, 2).map(item => item.id), before.pages.map(item => item.id), 'Generation appends without replacing or sorting existing pages');
    assert.deepEqual(generated.pages[0].document, original.document, 'Original mathematical drawing is preserved');
    assert.deepEqual(generated.pages[1].document, before.document, 'The existing blank page remains available');
    assert.deepEqual(await (await history(page)).allTextContents(), generated.pages.map(item => item.name));
    console.log('CHECK ' + width + '/' + language + ': required explicit C5, empty-gallery K5 and Hasse generation rendered with real WASM; previous pages retained');

    for (const action of ['edit', 'requirement-edit', 'switch', 'dismiss', 'guidance', 'close']) {
      const held = mock.enqueue({ json: fixture('graph', 'STALE ' + action) }, true);
      await (await ai(page, 'K5 pending ' + action)).click(); await held.started;
      assert.equal(await page.locator('[data-math-diagram-generate]').isDisabled(), true, 'Only one generation runs at a time');
      const count = (await state(page)).pages.length;
      if (action === 'edit') await page.locator('.ddw-name').fill('Edited during ' + action);
      if (action === 'requirement-edit') await page.locator('.ddw-ai-requirement').fill('');
      if (action === 'switch') await (await history(page)).first().click();
      if (action === 'dismiss') await page.locator('[data-drawing-ai-generation]').click();
      if (action === 'guidance') await page.locator('[data-drawing-ai-guidance]').click();
      if (action === 'close') {
        await page.locator('#graphEditorClose').click();
        await page.locator('#graphEditorDialog').waitFor({ state: 'hidden' });
      }
      held.release();
      await page.waitForTimeout(150); // allow the deliberately late network response to arrive
      if (action === 'close') await openDrawing(page);
      const current = await state(page);
      assert.equal(current.pages.length, count, action + ' cancels stale generation');
      assert.ok(!current.pages.some(item => item.name.startsWith('STALE')), 'Cancelled results never enter history');
      assert.equal(await page.locator('.dmate-delete-confirm[open]').count(), 0, 'Cancellation does not show an error');
    }

    const localized = language === 'en' ? 'Enter a valid mathematical diagram request.' : '请输入有效的数学图要求。';
    for (const response of [{ status: 400, json: { ok: false, error: localized } }, { json: null }, { raw: 'invalid JSON' }]) {
      mock.enqueue(response);
      const count = (await state(page)).pages.length;
      await (await ai(page, 'K5 error')).click();
      const message = await notice(page, language === 'en' ? /request|invalid|service/i : /数学图|返回内容无效/);
      if (language === 'en') assert.doesNotMatch(message, /[\u3400-\u9fff]/, 'English errors must not fall back to Chinese');
      assert.equal((await state(page)).pages.length, count, 'API failures preserve every page');
      assert.equal(await page.locator('[data-math-diagram-generate]').isEnabled(), true, 'Generation can be retried after failure');
    }
    await (await history(page)).first().click();
    const restored = await checkDiagram(page, complete);
    assert.deepEqual(restored.document.graphs[0].edges.map(edge => [edge.id, edge.path]),
      original.document.graphs[0].edges.map(edge => [edge.id, edge.path]), 'History switching and reopening preserve every sampled route');
    const png = await pngDownload(page, width < 760);
    if (process.env.OFFLINE_SCREENSHOT_DIR) {
      await fs.mkdir(process.env.OFFLINE_SCREENSHOT_DIR, { recursive: true });
      await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/math-diagram-' + width + '-' + language + '.png' });
    }
    assert.deepEqual(mock.unexpected, [], 'Every generation request is mocked');
    assert.deepEqual(guideRequests, [], 'No paid guidance call is made');
    assert.deepEqual(errors, [], 'No page errors');
    console.log('PASS ' + width + '/' + language + ': passive matching AI popovers, required generation and disabled empty arrow, explicit C5, real Graphviz K5/Hasse with hyphen IDs and retained SVG routes, stable pages, edit/switch/dismiss/close cancellation, localized errors and PNG ' + JSON.stringify(png));
  } catch (error) {
    console.error('Drawing state at failure:', JSON.stringify(await state(page).catch(() => null)));
    if (process.env.OFFLINE_SCREENSHOT_DIR) {
      await fs.mkdir(process.env.OFFLINE_SCREENSHOT_DIR, { recursive: true });
      await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/FAILED-math-diagram-' + width + '-' + language + '.png' }).catch(() => {});
    }
    throw error;
  } finally { await page.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try { for (const width of [390, 1440]) for (const language of ['zh-CN', 'en']) await runCase(browser, width, language); }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
