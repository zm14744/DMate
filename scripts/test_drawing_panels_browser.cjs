/* Uses the public persistent drawing API inside the actual online dialog.
 * Anonymous online galleries intentionally do not persist across refreshes.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const storageKey = 'dmate:drawing-panels-browser-regression';
const names = ['测试 A', '测试 B', '测试 C'];
const gallery = { version: 2, activeId: 'page-A', pages: names.map((name, index) => ({
  id: 'page-' + 'ABC'[index], name, createdAt: index + 1, updatedAt: [100, 300, 200][index],
  document: { body_text: '', graphs: [{ id: 'G1', name, directed: true, weighted: true,
    vertices: [{ id: 'v1', label: 'ABC'[index] + '1', x: .25, y: .3 },
      { id: 'v2', label: 'ABC'[index] + '2', x: .65, y: .4 }],
    edges: [{ id: 'e1', from: 'v1', to: 'v2', direction: 'forward', weight: 3, edge_label: 'AB', style: 'solid' }] }] }
})) };
const settle = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));

async function mount(page, seed) {
  await page.evaluate(({ key, value, seed }) => {
    if (seed) localStorage.setItem(key, JSON.stringify(value));
    window.drawingPanelFixture = DMateDrawingWorkspace.mount(document.getElementById('graphEditorMount'), {
      storageKey: key, persistent: true, sessionState: {}, legacyDocument: { body_text: '', graphs: [] }
    });
    showGraphEditorDialog(document.getElementById('graphEditorDialog'));
  }, { key: storageKey, value: gallery, seed });
  await page.waitForFunction(() => document.getElementById('graphEditorDialog').open
    && !document.getElementById('graphEditorDialog').dataset.positioning);
  await page.locator('.dge-overlay-viewport').waitFor();
  await settle(page);
}

async function selectShape(page, kind, mobile) {
  const shape = page.locator(kind === 'vertex' ? '.dge-overlay-node[data-vertex-id="v1"] .dge-overlay-dot'
    : '.dge-overlay-edge[data-edge-id="e1"] .dge-overlay-stroke').first();
  const point = await shape.evaluate(node => {
    if (node.localName === 'path') {
      const middle = node.getPointAtLength(node.getTotalLength() / 2);
      const point = new DOMPoint(middle.x, middle.y).matrixTransform(node.getScreenCTM());
      return { x: point.x, y: point.y };
    }
    const rect = node.getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  });
  if (mobile) await page.touchscreen.tap(point.x, point.y); else await page.mouse.click(point.x, point.y);
  await page.waitForFunction(text => document.querySelector('.dge-selection-panel h3')?.textContent.includes(text),
    kind === 'vertex' ? '顶点的属性' : '边的属性');
  await settle(page);
}

async function panelPosition(page) {
  const state = await page.locator('.dge-selection-panel').evaluate(panel => {
    const rect = panel.getBoundingClientRect(), workspace = panel.closest('.dge-workspace').getBoundingClientRect();
    const toolbarBottom = Math.max(...['.dge-view-controls', '.ddw-side-actions', '.dge-tool-palette > summary']
      .map(selector => document.querySelector(selector)?.getBoundingClientRect().bottom || 0));
    return { right: workspace.right - rect.right, bottom: workspace.bottom - rect.bottom,
      top: rect.top, width: rect.width, height: rect.height, toolbarBottom,
      scrollHeight: panel.scrollHeight, clientHeight: panel.clientHeight };
  });
  assert.ok(Math.abs(state.right - 12) <= 2, 'Properties stay 12px from the canvas right: ' + JSON.stringify(state));
  assert.ok(Math.abs(state.bottom - 12) <= 2, 'Properties stay at the canvas bottom: ' + JSON.stringify(state));
  assert.ok(state.top >= state.toolbarBottom + 3, 'Properties must not cover the canvas tools: ' + JSON.stringify(state));
  return state;
}

async function history(page) {
  const button = page.locator('.ddw-page-actions').getByRole('button', { name: '历史绘图', exact: true });
  if (await button.getAttribute('aria-expanded') !== 'true') await button.click();
  await page.locator('.ddw-history-list').waitFor();
  return page.locator('.ddw-history-open');
}

async function runCase(browser, width) {
  const page = await browser.newPage({ viewport: { width, height: width === 390 ? 740 : 900 },
    isMobile: width === 390, hasTouch: width === 390 });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await mount(page, true);
    await selectShape(page, 'vertex', width === 390);
    const vertex = await panelPosition(page);
    if (process.env.OFFLINE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/drawing-' + width + '-vertex.png' });
    if (width === 390) {
      const oldStyle = await page.addStyleTag({ content: '.ddw-editor .dge-workspace .dge-selection-panel{top:var(--ddw-property-top,120px)!important;bottom:auto!important}' });
      await settle(page);
      await assert.rejects(() => panelPosition(page), /Properties stay at the canvas bottom/);
      await oldStyle.evaluate(node => node.remove());
      await settle(page);
      await panelPosition(page);
    }
    await selectShape(page, 'edge', width === 390);
    const edge = await panelPosition(page);
    if (width === 390) {
      assert.ok(edge.scrollHeight > edge.clientHeight, 'Long edge properties must scroll within the small screen');
      await page.locator('.dge-selection-panel').evaluate(panel => { panel.scrollTop = panel.scrollHeight; });
      const inside = await page.locator('.dge-selection-panel').evaluate(panel => {
        const rect = panel.getBoundingClientRect(), button = panel.querySelector('.dge-danger').getBoundingClientRect();
        return button.top >= rect.top && button.bottom <= rect.bottom;
      });
      assert.ok(inside, 'Last edge action remains reachable inside the scrolling panel');
    }
    if (process.env.OFFLINE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/drawing-' + width + '-edge.png' });
    assert.deepEqual(await (await history(page)).allTextContents(), names, 'History follows saved array order, not updatedAt');
    for (const index of [1, 0, 2]) {
      await page.locator('.ddw-history-open').getByText(names[index], { exact: true }).click();
      assert.equal(await page.locator('.ddw-name').inputValue(), names[index]);
      assert.equal(await page.locator('.dge-overlay-node[data-vertex-id="v1"] .dge-overlay-label').textContent(), 'ABC'[index] + '1');
      assert.deepEqual(await (await history(page)).allTextContents(), names, 'Visiting another drawing must not reorder history');
    }
    await page.locator('.ddw-page-actions').getByRole('button', { name: '新建空白页', exact: true }).click();
    const added = await page.locator('.ddw-name').inputValue(), expected = [...names, added];
    assert.deepEqual(await (await history(page)).allTextContents(), expected, 'New pages append to the stable history');
    await page.reload({ waitUntil: 'networkidle' });
    await mount(page, false);
    assert.equal(await page.locator('.ddw-name').inputValue(), added, 'Active drawing persists across refresh');
    assert.deepEqual(await (await history(page)).allTextContents(), expected, 'History order persists across refresh');
    await page.locator('.ddw-history-open').getByText(names[1], { exact: true }).click();
    assert.equal(await page.locator('.ddw-name').inputValue(), names[1]);
    assert.deepEqual(await (await history(page)).allTextContents(), expected);
    assert.deepEqual(errors, []);
    console.log('PASS ' + width + ': vertex ' + JSON.stringify(vertex) + '; edge ' + JSON.stringify(edge) + '; stable selectable history and refresh');
  } finally { await page.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try { for (const width of [390, 1440]) await runCase(browser, width); }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
