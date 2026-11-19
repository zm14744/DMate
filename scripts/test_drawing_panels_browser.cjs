/* Uses the public persistent drawing API inside the actual online dialog.
 * Anonymous online galleries survive refresh within their tab.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const {installStorageProbe} = require('./offline-vault-browser-fixtures.cjs');
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
async function modalHeading(page, title) {
  const reference = page.locator(await page.locator('#appConfirmTitle').count() ? '#appConfirmTitle' : '#appearanceModal .modal-head > div:first-child');
  const read = control => control.evaluate(node => Object.fromEntries(['fontFamily','fontSize','fontWeight','fontStyle','lineHeight']
    .map(key => [key,getComputedStyle(node)[key]])));
  assert.deepEqual(await read(title), await read(reference), 'Drawing popup heading uses ordinary modal typography');
}
async function readyView(page) {
  await page.locator('.dge-overlay[data-geometry-ready="true"]').waitFor();
  await settle(page);
}

async function viewState(page) {
  return page.locator('.dge-overlay').evaluate(node => {
    const viewport = node.querySelector('.dge-overlay-viewport'), bounds = viewport.getBoundingClientRect();
    return { camera: [parseFloat(document.querySelector('.ddw-editor .dge-overlay-zoom').textContent), viewport.scrollLeft, viewport.scrollTop],
      nodes: [...node.querySelectorAll('.dge-overlay-dot')].map(dot => {
        const rect = dot.getBoundingClientRect();
        return [rect.x - bounds.x, rect.y - bounds.y, rect.width, rect.height];
      }), size: [viewport.clientWidth, viewport.clientHeight] };
  });
}

async function automaticFit(page, label) {
  const historyButton = page.locator('.ddw-page-actions>button[aria-expanded="true"]');
  if (await historyButton.count()) await historyButton.click();
  await readyView(page);
  const initial = await viewState(page);
  await page.locator('[data-overlay-tool="zoom-fit"]').click(); await settle(page);
  const fitted = await viewState(page);
  const actual = [...initial.camera, ...initial.nodes.flat()], expected = [...fitted.camera, ...fitted.nodes.flat()];
  assert.equal(actual.length, expected.length);
  actual.forEach((value, index) => assert.ok(Math.abs(value - expected[index]) <= (index === 0 ? .02 : 1),
    label + ': opening must already match Fit: ' + JSON.stringify({ initial, fitted })));
  for (const [x, y, width, height] of initial.nodes) {
    assert.ok(x + width / 2 >= 0 && x + width / 2 <= initial.size[0]
      && y + height / 2 >= 0 && y + height / 2 <= initial.size[1], label + ': fitted nodes stay visible');
  }
}

async function preservedView(page, expected, label) {
  await readyView(page);
  const actual = await viewState(page);
  const values = [...actual.camera, ...actual.nodes.flat()], baseline = [...expected.camera, ...expected.nodes.flat()];
  assert.equal(values.length, baseline.length);
  values.forEach((value, index) => assert.ok(Math.abs(value - baseline[index]) <= (index === 0 ? .02 : 1),
    label + ': restore the previous drawing camera: ' + JSON.stringify({ actual, expected })));
}

async function zoomAway(page) {
  const historyButton = page.locator('.ddw-page-actions>button[aria-expanded="true"]');
  if (await historyButton.count()) await historyButton.click();
  const before = (await viewState(page)).camera[0];
  const plus = page.locator('[data-overlay-tool="zoom-in"]');
  await page.locator('[data-overlay-tool="' + (await plus.isEnabled() ? 'zoom-in' : 'zoom-out') + '"]').click();
  await settle(page);
  assert.notEqual((await viewState(page)).camera[0], before, 'Fixture actually changes the camera before reopening');
}

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
  await readyView(page);
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
      scrollHeight: (panel.querySelector('.dge-property-body') || panel).scrollHeight,
      clientHeight: (panel.querySelector('.dge-property-body') || panel).clientHeight };
  });
  assert.ok(Math.abs(state.right - 12) <= 2, 'Properties stay 12px from the canvas right: ' + JSON.stringify(state));
  assert.ok(Math.abs(state.bottom - 12) <= 2, 'Properties stay at the canvas bottom: ' + JSON.stringify(state));
  assert.ok(state.top >= state.toolbarBottom + 3, 'Properties must not cover the canvas tools: ' + JSON.stringify(state));
  return state;
}

async function reachablePanelEnd(page, selector) {
  const panel = page.locator(selector);
  const overflow = await panel.evaluate(node => {
    node = node.querySelector('.dge-property-body') || node;
    const overflow = node.scrollHeight > node.clientHeight + 1;
    node.scrollTop = node.scrollHeight;
    return { overflow, moved: node.scrollTop, scrollable: getComputedStyle(node).overflowY };
  });
  if (overflow.overflow) {
    assert.ok(['auto', 'scroll'].includes(overflow.scrollable), 'Overflowing panel must have its own scroll');
    assert.ok(overflow.moved > 0, 'Long panel must actually scroll to its end');
  }
  let last = panel.locator('button:enabled:visible,input:enabled:visible,select:enabled:visible,textarea:enabled:visible').last();
  const actionable = await last.count() > 0;
  if (!actionable) last = panel.locator('*:visible').last();
  assert.ok(await last.count(), 'Panel has readable content');
  const inside = await last.evaluate((node, actionable) => {
    const rect = node.getBoundingClientRect(), parent = node.closest('.dge-property-body,.dge-selection-panel,.dge-float-content,.ddw-side-panel,.dge-overlay-tools').getBoundingClientRect();
    return (!actionable || rect.top >= Math.max(0, parent.top - 1))
      && rect.bottom >= parent.top - 1 && rect.bottom <= parent.bottom + 1
      && rect.left >= parent.left - 1 && rect.right <= parent.right + 1
      && rect.bottom <= innerHeight;
  }, actionable);
  assert.ok(inside, 'Last panel action remains inside the panel and visible viewport');
  if (actionable) await last.click({ trial: true }); // Hit testing without deleting or invoking AI.
}

async function compactPanel(page, selector, mobile) {
  const metrics = await page.locator(selector).evaluate(node => {
    const rect = node.getBoundingClientRect(), style = getComputedStyle(node);
    return { x: rect.x, y: rect.y, width: rect.width, height: rect.height,
      right: rect.right, bottom: rect.bottom, screenWidth: innerWidth, screenHeight: innerHeight,
      padding: parseFloat(style.paddingTop), horizontalOverflow: node.scrollWidth - node.clientWidth };
  });
  assert.ok(metrics.x >= 7 && metrics.right <= metrics.screenWidth - 7, 'Popover fits the horizontal viewport: ' + JSON.stringify(metrics));
  assert.ok(metrics.y >= 7 && metrics.bottom <= metrics.screenHeight - 7, 'Popover fits the vertical viewport: ' + JSON.stringify(metrics));
  assert.ok(metrics.horizontalOverflow <= 1, 'Panel does not require horizontal scrolling');
  if (mobile) {
    assert.ok(metrics.width <= 320, 'Mobile panel stays compact instead of filling the screen: ' + JSON.stringify(metrics));
    assert.ok(metrics.padding <= 10, 'Mobile panel has compact padding');
  }
  await reachablePanelEnd(page, selector);
  return metrics;
}

async function propertyCard(page, mobile) {
  const panel = page.locator('.dge-selection-panel');
  await modalHeading(page, panel.locator('.dge-property-head > h3'));
  assert.equal(await panel.getByRole('button', { name: /反转方向|Reverse direction/i }).count(), 0,
    'Drawing properties omit the redundant Reverse direction action');
  const body = panel.locator('.dge-property-body');
  await body.evaluate(node => { node.scrollTop = 0; }); await settle(page);
  const close = panel.locator('.dge-property-head .dge-panel-close');
  const before = await close.boundingBox();
  const bounds = await panel.evaluate(node => {
    const panel = node.getBoundingClientRect(), head = node.querySelector('.dge-property-head'), dot = head.querySelector('.dge-panel-close').getBoundingClientRect();
    const style = getComputedStyle(head);
    return { right: panel.right - dot.right, top: dot.top - panel.top, width: dot.width, height: dot.height,
      expectedRight: parseFloat(style.paddingRight) + parseFloat(getComputedStyle(node).borderRightWidth),
      expectedTop: parseFloat(style.paddingTop) + parseFloat(getComputedStyle(node).borderTopWidth) };
  });
  assert.ok(bounds.right >= 8 && bounds.right <= 20 && bounds.top >= 8 && bounds.top <= 20,
    'Close dot stays at the property card top-right: ' + JSON.stringify(bounds));
  const sharedSize = await page.locator(await page.locator('#graphEditorClose').count() ? '#graphEditorClose' : '#appearanceClose')
    .evaluate(node => parseFloat(getComputedStyle(node).width));
  assert.ok(Math.abs(bounds.width - sharedSize) <= 1 && Math.abs(bounds.height - sharedSize) <= 1,
    'Property close dot matches the responsive modal close size');
  await compactPanel(page, '.dge-selection-panel', mobile);
  const after = await close.boundingBox();
  for (const key of ['x', 'y', 'width', 'height']) assert.ok(Math.abs(before[key] - after[key]) <= .5, 'Property close dot does not scroll with fields');
  const scroll = await body.evaluate(node => {
    const style = getComputedStyle(node);
    return { hidden: style.scrollbarWidth === 'none', gutter: node.offsetWidth - node.clientWidth
      - parseFloat(style.borderLeftWidth) - parseFloat(style.borderRightWidth) };
  });
  assert.equal(scroll.hidden, true, 'Property fields hide the native scrollbar while retaining scrolling');
  assert.ok(scroll.gutter <= 1, 'Property fields reserve no large scrollbar gutter');
  await close.click({ trial: true });
}

async function closeProperty(page) {
  await page.locator('.dge-selection-panel .dge-panel-close').click();
  await page.locator('.dge-selection-panel').waitFor({ state: 'hidden' });
}

async function borderlessButtons(page, mobile) {
  const selector = '.ddw-page-actions>button:not(.ddw-upload-button),.ddw-editor>.dge-topline>button,.ddw-editor .dge-view-controls>button';
  const original = await page.evaluate(() => [document.documentElement.dataset.appearanceTheme, document.body.dataset.appearanceTheme]);
  try {
    for (const theme of ['light', 'dark']) {
      await page.evaluate(theme => { document.documentElement.dataset.appearanceTheme = document.body.dataset.appearanceTheme = theme; }, theme);
      await page.mouse.move(0, 0); await settle(page);
      const borders = await page.locator(selector).evaluateAll(nodes => nodes.map(node => {
        const s = getComputedStyle(node);
        return { text: node.textContent || node.getAttribute('aria-label'),
          borderless: ['Top', 'Right', 'Bottom', 'Left'].every(side => parseFloat(s['border' + side + 'Width']) === 0
            || s['border' + side + 'Style'] === 'none' || /(?:transparent|rgba\([^)]*,\s*0\))/.test(s['border' + side + 'Color'])) };
      }));
      assert.ok(borders.length >= 8, 'All page, history, and zoom toolbar controls are checked');
      assert.ok(borders.every(item => item.borderless), theme + ': toolbar buttons have no visible border: ' + JSON.stringify(borders));
      if (!mobile) for (const group of ['.ddw-page-actions>button:not(.ddw-upload-button):enabled', '.ddw-editor>.dge-topline>button:enabled', '.ddw-editor .dge-view-controls>button:enabled']) {
        const button = page.locator(group).first();
        await page.mouse.move(0, 0); await settle(page);
        const before = await button.evaluate(node => ({ background: getComputedStyle(node).backgroundColor,
          rect: [...['x', 'y', 'width', 'height']].map(key => node.getBoundingClientRect()[key]) }));
        await button.hover(); await settle(page);
        const after = await button.evaluate(node => ({ background: getComputedStyle(node).backgroundColor,
          rect: [...['x', 'y', 'width', 'height']].map(key => node.getBoundingClientRect()[key]) }));
        assert.notEqual(after.background, before.background, theme + ': enabled toolbar button retains a visible hover state');
        after.rect.forEach((value, i) => assert.ok(Math.abs(value - before.rect[i]) <= .5, 'Hover does not shift toolbar geometry'));
      }
    }
  } finally {
    await page.evaluate(values => [document.documentElement, document.body].forEach((node, i) => {
      if (values[i] == null) delete node.dataset.appearanceTheme; else node.dataset.appearanceTheme = values[i];
    }), original);
    await page.mouse.move(0, 0); await settle(page);
  }
}

async function canvasChrome(page) {
  return page.evaluate(() => {
    const viewport = document.querySelector('.dge-overlay-viewport'), frame = viewport.closest('.ddw-canvas-frame');
    const style = getComputedStyle(viewport), bounds = viewport.getBoundingClientRect(), outer = frame.getBoundingClientRect();
    const rect = node => {
      const r = node.getBoundingClientRect(); return [r.x, r.y, r.width, r.height];
    };
    return { controls: [document.querySelector('.dge-view-controls'), document.querySelector('.dge-tool-palette>summary'),
      ...document.querySelectorAll('.ddw-side-actions>button')].map(rect),
      scroll: [viewport.scrollLeft, viewport.scrollTop],
      gutter: [viewport.offsetWidth - viewport.clientWidth - parseFloat(style.borderLeftWidth) - parseFloat(style.borderRightWidth),
        viewport.offsetHeight - viewport.clientHeight - parseFloat(style.borderTopWidth) - parseFloat(style.borderBottomWidth)],
      frameGap: [outer.right - bounds.right, outer.bottom - bounds.bottom],
      frameOverflow: getComputedStyle(frame).overflow,
      size: [viewport.clientWidth, viewport.clientHeight] };
  });
}

async function viewportAndPopoverChecks(page, mobile, label, online = true) {
  await automaticFit(page, label + ' initial');
  await borderlessButtons(page, mobile);
  for (const language of ['en', 'zh-CN']) {
    await page.evaluate(language => DMateI18n.setLanguage(language, false), language);
    await settle(page);
    const expectedLabels = language === 'en'
      ? ['Drawing settings', 'Graph information', 'AI guidance', 'AI generation']
      : ['绘图设置', '图形信息', 'AI指导', 'AI生成'];
    const labels = await page.locator('.ddw-side-actions>button').evaluateAll(buttons => {
      const frame = document.querySelector('.ddw-canvas-frame').getBoundingClientRect();
      return buttons.map(button => {
        const rect = button.getBoundingClientRect(), style = getComputedStyle(button);
        return { text: button.textContent.trim(), overflow: button.scrollWidth - button.clientWidth,
          style: Object.fromEntries(['fontSize', 'fontWeight', 'lineHeight', 'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft',
            'borderRadius', 'borderTopWidth', 'borderTopStyle', 'borderTopColor', 'backgroundColor', 'color', 'minHeight']
            .map(key => [key, style[key]])),
          left: rect.left - frame.left, right: frame.right - rect.right };
      });
    });
    assert.deepEqual(labels.map(item => item.text), online ? expectedLabels : expectedLabels.slice(0, 2),
      label + '/' + language + ': online generation follows guidance; offline keeps its two local controls');
    if (online) {
      assert.deepEqual(labels[3].style, labels[2].style,
        label + '/' + language + ': AI generation uses the same rail button styling as AI guidance');
      assert.equal(await page.locator('.ddw-side-actions>[data-drawing-ai-generation]').count(), 1,
        'The AI generation panel entry belongs to the shared canvas control rail');
      assert.equal(await page.locator('.ddw-side-actions>[data-math-diagram-generate]').count(), 0,
        'The canvas rail does not send a generation request directly');
    }
    for (const item of labels) {
      assert.ok(item.overflow <= 1, label + '/' + language + ': button label must remain complete: ' + JSON.stringify(item));
      assert.ok(item.left >= 0 && item.right >= 0, 'Button remains within the canvas frame');
    }
  }
  const zoomIn = page.locator('[data-overlay-tool="zoom-in"]');
  for (let i = 0; i < 20 && await zoomIn.isEnabled(); i++) await zoomIn.click();
  assert.equal(await zoomIn.isEnabled(), false, 'Drawing zoom reaches its finite upper limit');
  await settle(page);
  await page.locator('.dge-overlay-viewport').evaluate(node => node.scrollTo(0, 0));
  await settle(page);
  const baseline = await canvasChrome(page);
  assert.ok(baseline.size[0] > 120 && baseline.size[1] > 120, 'Canvas retains useful dimensions');
  assert.ok(baseline.gutter.every(value => value <= 1), 'Canvas reserves no blank scrollbar strip: ' + JSON.stringify(baseline));
  assert.ok(baseline.frameGap.every(value => value <= 2), 'Canvas fills the frame at right and bottom');
  assert.ok(['hidden', 'clip'].includes(baseline.frameOverflow), 'Frame owns the rounded canvas clip');
  // Sample every painted frame while genuine pointer input pans the canvas.
  // A final-only comparison misses the overlay/workspace top-style race.
  await page.evaluate(() => {
    window.drawingChromeProbe = { samples: [], running: true };
    const tick = () => {
      const probe = window.drawingChromeProbe;
      probe.samples.push([document.querySelector('.dge-view-controls'), document.querySelector('.dge-tool-palette>summary'),
        ...document.querySelectorAll('.ddw-side-actions>button')].map(node => {
        const r = node.getBoundingClientRect(); return [r.x, r.y, r.width, r.height];
      }));
      if (probe.running) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
  const canvas = await page.locator('.dge-overlay-viewport').boundingBox();
  const start = { x: canvas.x + canvas.width * .65, y: canvas.y + canvas.height * .65 };
  await page.mouse.move(start.x, start.y); await page.mouse.down();
  for (let step = 1; step <= 8; step++) {
    await page.mouse.move(start.x - step * 9, start.y - step * 7);
    await settle(page);
  }
  await page.mouse.up();
  await page.mouse.wheel(180, 160); await settle(page);
  const after = await canvasChrome(page);
  const samples = await page.evaluate(() => {
    window.drawingChromeProbe.running = false; return window.drawingChromeProbe.samples;
  });
  assert.ok(samples.length >= 8, 'Pan records multiple real animation frames');
  assert.ok(after.scroll.some((value, i) => Math.abs(value - baseline.scroll[i]) > 20), 'The canvas really pans/scrolls');
  for (const sample of samples) sample.forEach((rect, i) => rect.forEach((value, axis) => {
    assert.ok(Math.abs(value - baseline.controls[i][axis]) <= 1,
      label + ': toolbar/button jumped during pan: ' + JSON.stringify({ baseline: baseline.controls, sample }));
  }));
  if (process.env.OFFLINE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/viewport-' + label + '-pan.png' });
  await page.locator('[data-overlay-tool="zoom-fit"]').click(); await settle(page);
  const popovers = [
    ['tools', '.dge-tool-palette>summary', '.dge-tool-palette[open]>.dge-overlay-tools'],
    ['settings', '.ddw-side-actions>button:first-child', '.dge-float-panel[data-panel-key="graphs"][open]>.dge-float-content'],
    ['information', '.ddw-side-actions>button:nth-child(2)', '.dge-float-panel[data-panel-key="results"][open]>.dge-float-content'],
    ['history', '.ddw-page-actions>button:nth-child(2)', '.ddw-side-panel:not([hidden])'],
  ];
  if (online) popovers.push(
    ['ai-guidance', '.ddw-side-actions>[data-drawing-ai-guidance]', '.ddw-side-panel:not([hidden])'],
    ['ai-generation', '.ddw-side-actions>[data-drawing-ai-generation]', '.ddw-side-panel:not([hidden])']
  );
  const metrics = {};
  for (const [name, trigger, panel] of popovers) {
    await page.locator(trigger).click(); await page.locator(panel).waitFor(); await settle(page);
    if (name !== 'tools') {
      const title = page.locator(panel + ' :is(.ddw-panel-header,.ddw-editor-panel-header) > h3');
      await modalHeading(page, title);
      await page.evaluate(() => DMateI18n.setLanguage('en', false));
      await modalHeading(page, title);
      await page.evaluate(() => DMateI18n.setLanguage('zh-CN', false));
    }
    if (name === 'ai-guidance' || name === 'ai-generation') {
      const generating = name === 'ai-generation';
      assert.equal(await page.locator(panel + ' [data-math-diagram-generate]').count(), generating ? 1 : 0,
        'Only the generation panel contains its explicit generation send button');
      assert.equal(await page.locator(panel + ' [data-drawing-guide]').count(), generating ? 0 : 1,
        'Only the guidance panel contains its explicit guidance send button');
      assert.equal(await page.locator(panel + ' .ddw-panel-header>h3').innerText(), generating ? 'AI生成' : 'AI指导');
      const requirementLabel = await page.locator(panel + ' .ddw-ai-label').innerText();
      if (generating) {
        assert.equal(requirementLabel, '绘图要求', 'Generation has a plain required request label');
        assert.equal(await page.locator(panel + ' .ddw-ai-requirement').getAttribute('required'), '');
        const requirement = await page.locator(panel + ' .ddw-ai-requirement').inputValue();
        assert.equal(await page.locator(panel + ' [data-math-diagram-generate]').isEnabled(), Boolean(requirement.trim()));
      } else {
        assert.match(requirementLabel, /可选|optional/i, 'Guidance requirements remain optional');
        assert.equal(await page.locator(panel + ' .ddw-ai-requirement').getAttribute('required'), null);
      }
    }
    try { metrics[name] = await compactPanel(page, panel, mobile); }
    catch (error) {
      if (process.env.OFFLINE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/viewport-' + label + '-' + name + '-failure.png' });
      throw new Error(label + ' ' + name + ': ' + error.message, { cause: error });
    }
    if(name==='settings'&&mobile){
      const position=await page.locator(panel).evaluate(node=>{
        const rect=node.getBoundingClientRect(),trigger=document.querySelector('.ddw-side-actions>button:first-child').getBoundingClientRect();
        return {left:rect.left,expected:Math.max(8,Math.min(trigger.left,innerWidth-8-rect.width))};
      });
      assert.ok(Math.abs(position.left-position.expected)<=2,
        label+': compact drawing settings opens toward its trigger instead of the left viewport edge');
    }
    if (['settings', 'information'].includes(name) && process.env.OFFLINE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/viewport-' + label + '-' + name + '.png' });
    await page.locator(trigger).click(); await settle(page);
  }
  console.log('PASS viewport ' + label + ': ' + samples.length + ' stable pan frames, no gutters; popovers ' + JSON.stringify(metrics));
}

async function history(page) {
  const button = page.locator('.ddw-page-actions').getByRole('button', { name: '历史绘图', exact: true });
  if (await button.getAttribute('aria-expanded') !== 'true') await button.click();
  await page.locator('.ddw-history-list').waitFor();
  return page.locator('.ddw-history-open');
}

async function headerExportChecks(page, label, offline = false) {
  const head = page.locator(offline ? '#drawingPanel>.graph-editor-dialog-head' : '#graphEditorDialog>.graph-editor-dialog-head');
  const trigger = head.locator('[data-drawing-export]');
  assert.equal(await trigger.count(), 1, 'Exactly one image export belongs to the drawing header');
  assert.equal(await page.locator('.ddw-page-actions [data-drawing-export]').count(), 0, 'Export is removed from the page action row');
  assert.equal(await trigger.textContent(), '', 'The header action uses the image icon without a text button');
  assert.equal(await trigger.locator('svg[data-icon="image"]').count(), 1);
  const geometry = await trigger.evaluate(node => {
    const box = node.getBoundingClientRect(), close = node.parentElement.querySelector('.graph-editor-close-dot')?.getBoundingClientRect();
    const css = getComputedStyle(node), icon = node.querySelector('svg').getBoundingClientRect();
    return {width:box.width, height:box.height, icon:icon.width, border:css.borderWidth,
      leftOfClose:!close || box.right <= close.left - 5,
      gap:close ? Math.round(close.left - box.right) : null,
      centered:!close || Math.abs(box.y + box.height / 2 - close.y - close.height / 2) < 1};
  });
  assert.deepEqual(geometry, {width:32, height:32, icon:20, border:'0px', leftOfClose:true, gap:offline ? null : 10, centered:true});
  await page.evaluate(() => {
    window.headerExportRecords = [];
    window.headerOriginalPng = DMateDrawingExport.pngBlob;
    window.headerOriginalSave = DMateDrawingExport.save;
    DMateDrawingExport.pngBlob = async (svg, ...args) => {
      const labels = svg.textContent;
      const blob = await window.headerOriginalPng(svg, ...args);
      window.headerExportSvg = labels;
      return blob;
    };
    DMateDrawingExport.save = async (blob, name) => {
      window.headerExportRecords.push({name, labels:window.headerExportSvg, type:blob.type, bytes:blob.size});
      await new Promise(resolve => { window.finishHeaderExport = resolve; });
      return {destination:'download'};
    };
  });
  try {
    for (const index of [0, 1]) {
      if (index) {
        await (await history(page)).getByText(names[index], {exact:true}).click();
        await readyView(page);
      }
      await trigger.click();
      await page.waitForFunction(count => window.headerExportRecords.length === count, index + 1);
      assert.equal(await trigger.isDisabled(), true, 'Export stays disabled until image saving completes');
      assert.equal(await trigger.getAttribute('aria-busy'), 'true');
      assert.equal(await page.locator('.ddw-name').isDisabled(), true);
      await trigger.dispatchEvent('click');
      const records = await page.evaluate(() => window.headerExportRecords);
      assert.equal(records.length, index + 1, 'A second click cannot start another image save');
      const record = records[index];
      assert.equal(record.name, names[index], 'The export filename is the current drawing name');
      assert.equal(record.type, 'image/png'); assert.ok(record.bytes > 1000, 'The current drawing produces a real PNG');
      assert.match(record.labels, new RegExp('ABC'[index] + '1'));
      for (const other of [0, 1, 2].filter(other => other !== index)) assert.doesNotMatch(record.labels, new RegExp('ABC'[other] + '1'), 'Other gallery drawings do not enter the exported image');
      await page.evaluate(() => finishHeaderExport());
      await page.waitForFunction(() => !document.querySelector('[data-drawing-export]').disabled);
    }
    await (await history(page)).getByText(names[0], {exact:true}).click();
    await readyView(page);
    const toggle = page.locator('.ddw-page-actions>button[aria-expanded="true"]');
    if (await toggle.count()) await toggle.click();
  } finally {
    await page.evaluate(() => { DMateDrawingExport.pngBlob = window.headerOriginalPng; DMateDrawingExport.save = window.headerOriginalSave; });
  }
  console.log('PASS ' + label + ': header image icon exports only the selected drawing, with real PNG and busy guards');
}

async function runCase(browser, width) {
  const page = await browser.newPage({ viewport: { width, height: width === 390 ? 740 : 900 },
    isMobile: width === 390, hasTouch: width === 390 });
  const errors = []; let modelCalls = 0;
  page.on('pageerror', error => errors.push(error.message));
  await page.route(/\/(?:chat|ocr|drawing\/[^?]+)(?:\?|$)/, route => { modelCalls++; return route.abort(); });
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await mount(page, true);
    await headerExportChecks(page, 'online-' + width);
    await viewportAndPopoverChecks(page, width === 390, 'online-' + width);
    await selectShape(page, 'vertex', width === 390);
    const vertex = await panelPosition(page);
    await propertyCard(page, width === 390);
    if (process.env.OFFLINE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/drawing-' + width + '-vertex.png' });
    if (width === 390) {
      const oldStyle = await page.addStyleTag({ content: '.ddw-editor .dge-workspace .dge-selection-panel{top:var(--ddw-property-top,120px)!important;bottom:auto!important}' });
      await settle(page);
      await assert.rejects(() => panelPosition(page), /Properties stay at the canvas bottom/);
      await oldStyle.evaluate(node => node.remove());
      await settle(page);
      await panelPosition(page);
    }
    await closeProperty(page);
    await selectShape(page, 'edge', width === 390);
    const edge = await panelPosition(page);
    // A compact layout may fit naturally. If it overflows it must scroll;
    // either way the final action must stay reachable, never clipped away.
    await propertyCard(page, width === 390);
    if (process.env.OFFLINE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/drawing-' + width + '-edge.png' });
    await closeProperty(page);
    assert.deepEqual(await (await history(page)).allTextContents(), names, 'History follows saved array order, not updatedAt');
    const savedViews = new Map();
    for (const index of [1, 0, 2]) {
      await zoomAway(page);
      savedViews.set(await page.locator('.ddw-name').inputValue(), await viewState(page));
      await history(page);
      await page.locator('.ddw-history-open').getByText(names[index], { exact: true }).click();
      if (savedViews.has(names[index])) await preservedView(page, savedViews.get(names[index]), 'Online selected ' + names[index]);
      else await automaticFit(page, 'Online first selected ' + names[index]);
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
    assert.equal(modelCalls, 0, 'Opening and closing drawing panels never invokes a model');
    assert.deepEqual(errors, []);
    console.log('PASS ' + width + ': vertex ' + JSON.stringify(vertex) + '; edge ' + JSON.stringify(edge) + '; stable selectable history and refresh');
  } finally { await page.close(); }
}

async function onlinePage(browser, width = 1440) {
  const page = await browser.newPage({ viewport: { width, height: width === 390 ? 740 : 900 },
    isMobile: width === 390, hasTouch: width === 390, serviceWorkers: 'block' });
  page.regressionErrors = []; page.modelCalls = 0;
  page.on('pageerror', error => page.regressionErrors.push(error.message));
  // The fixture grants local persistence permissions only; it never logs in
  // to a real account or sends a cloud/model request.
  await page.route('**/auth/me', route => route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ configured: true, authenticated: false }) }));
  await page.route(/\/(?:chat|ocr|drawing\/[^?]+)(?:\?|$)/, route => {
    page.modelCalls++; return route.abort();
  });
  await page.addInitScript(() => {
    window.drawingStorageWrites = [];
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function(key, value) {
      if (this === localStorage && /^dmate:graph-(?:gallery|drawing)/.test(key)) window.drawingStorageWrites.push(key);
      return original.call(this, key, value);
    };
  });
  await page.goto(baseURL, { waitUntil: 'networkidle' });
  await localPermissions(page);
  return page;
}

async function localPermissions(page, username = '') {
  await page.waitForFunction(() => document.documentElement.dataset.accountStateKnown === '1');
  await page.evaluate(username => {
    stopCloudLivePolling();
    accountState.authenticated = Boolean(username); accountState.username = username;
  }, username);
}

async function openOnline(page) {
  const toggle = page.locator(page.viewportSize().width <= 1100 ? '#mobileToolsBtn' : '#desktopToolsBtn');
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
  await page.locator('#graphDrawingBtn').click();
  await page.locator('#graphEditorDialog[open] .dmate-drawing-workspace').waitFor();
  await page.waitForFunction(() => !document.getElementById('graphEditorDialog').dataset.positioning);
  await readyView(page);
}

async function closeOnline(page) {
  await page.locator('#graphEditorClose').click();
  await page.waitForFunction(() => !document.getElementById('graphEditorDialog').open && ocrEditorController === null);
  assert.equal(await page.locator('#graphEditorDialog [data-drawing-export]').count(), 0, 'Closing removes the drawing-only header action before the dialog is reused');
}

async function onlineState(page) {
  return page.evaluate(() => ({ pages: ocrEditorController.getPages().map(p => ({
    id: p.id, name: p.name, document: p.document
  })), name: document.querySelector('.ddw-name').value }));
}

async function assertEditableBlank(page) {
  const state = await onlineState(page);
  assert.equal(state.pages.length, 1, 'Opening an empty online gallery creates exactly one page');
  assert.equal(state.pages[0].document.graphs.length, 1);
  assert.deepEqual(state.pages[0].document.graphs[0].vertices, []);
  assert.deepEqual(state.pages[0].document.graphs[0].edges, []);
  assert.equal(await page.locator('.ddw-name').isEnabled(), true, 'Blank page name is editable');
  assert.equal(await page.locator('[data-drawing-export]').isDisabled(), true, 'An empty drawing has no image to export');
  assert.equal(await page.locator('.dge-overlay-viewport').evaluate(node => Boolean(node.closest('[inert]'))), false,
    'Blank page canvas is editable, rather than the inert zero-page placeholder');
  return state;
}

async function deleteAllOnline(page) {
  const count = (await onlineState(page)).pages.length;
  await history(page);
  for (let remaining = count; remaining > 0; remaining--) {
    await page.locator('.ddw-history-delete').first().click();
    await page.locator('.dmate-delete-confirm-delete').click();
    await page.waitForFunction(expected => ocrEditorController.getPages().length === expected, remaining - 1);
  }
  await settle(page);
  assert.deepEqual((await onlineState(page)).pages, [], 'Deleting the last page keeps this opening empty');
  assert.equal(await page.locator('.ddw-name').isDisabled(), true);
}

async function runGuestBlankLifecycle(browser) {
  const page = await onlinePage(browser, 390);
  try {
    await openOnline(page);
    await assertEditableBlank(page);
    await page.locator('.ddw-name').fill('游客已有空白页');
    const existing = await onlineState(page);
    for (let i = 0; i < 2; i++) {
      await zoomAway(page);
      await closeOnline(page); await openOnline(page);
      assert.deepEqual(await onlineState(page), existing, 'An existing empty drawing is reused, not replaced or duplicated');
    }
    await deleteAllOnline(page);
    await closeOnline(page); await openOnline(page);
    const replacement = await assertEditableBlank(page);
    assert.notEqual(replacement.pages[0].id, existing.pages[0].id);
    await closeOnline(page); await openOnline(page);
    assert.deepEqual(await onlineState(page), replacement, 'Repeated reopening does not create more blank pages');
    assert.deepEqual(await page.evaluate(() => window.drawingStorageWrites), [], 'Guest drawings never write localStorage');
    assert.deepEqual(await page.evaluate(() => Object.keys(localStorage).filter(key => /^dmate:graph-(?:gallery|drawing)/.test(key))), []);
    await page.reload({ waitUntil: 'networkidle' }); await localPermissions(page); await openOnline(page);
    const refreshed = await assertEditableBlank(page);
    assert.equal(refreshed.pages[0].id, replacement.pages[0].id, 'Guest gallery survives refresh in the same tab');
    assert.deepEqual(await page.evaluate(() => window.drawingStorageWrites), []);
    assert.equal(page.modelCalls, 0); assert.deepEqual(page.regressionErrors, []);
    console.log('PASS online guest: initial blank, same-open deletion stays empty, reopen creates one, saved blank reused, no persistent writes');
  } finally { await page.close(); }
}

async function runAccountGalleryLifecycle(browser) {
  const page = await onlinePage(browser), username = 'drawing-panels-local-fixture';
  const key = 'dmate:graph-gallery:v1::' + encodeURIComponent('account:' + username);
  try {
    await localPermissions(page, username);
    await page.evaluate(({ key, gallery }) => localStorage.setItem(key, JSON.stringify(gallery)), { key, gallery: { ...gallery, activeId: 'page-B' } });
    await openOnline(page);
    assert.equal((await onlineState(page)).name, names[1], 'Online entry restores selected existing drawing');
    assert.equal(await page.locator('.dge-overlay-node').count(), 2);
    assert.deepEqual((await onlineState(page)).pages.map(p => p.id), gallery.pages.map(p => p.id));
    await automaticFit(page, 'First account drawing open');
    await zoomAway(page); const priorView = await viewState(page); await closeOnline(page); await openOnline(page);
    await preservedView(page, priorView, 'Account drawing reopen');
    assert.equal((await onlineState(page)).name, names[1], 'Reopening preserves the existing selected drawing');
    await page.locator('.ddw-page-actions').getByRole('button', { name: '新建空白页', exact: true }).click();
    await page.locator('.ddw-name').fill('账号保存空白页');
    const saved = await onlineState(page);
    assert.equal(saved.pages.length, 4);
    assert.equal(saved.pages.at(-1).document.graphs[0].vertices.length, 0);
    await closeOnline(page); await openOnline(page);
    assert.deepEqual(await onlineState(page), saved, 'Reopening reuses all drawings and the selected saved blank page');
    await closeOnline(page); await page.reload({ waitUntil: 'networkidle' });
    await localPermissions(page, username); await openOnline(page);
    assert.deepEqual(await onlineState(page), saved, 'Account gallery contents and selected blank survive refresh');
    await (await history(page)).getByText(names[1], { exact: true }).click();
    const selected = await onlineState(page);
    await closeOnline(page); await page.reload({ waitUntil: 'networkidle' });
    await localPermissions(page, username); await openOnline(page);
    assert.deepEqual(await onlineState(page), selected, 'Existing nonempty drawing selection also survives refresh');
    await deleteAllOnline(page); await closeOnline(page);
    assert.deepEqual(await page.evaluate(key => JSON.parse(localStorage.getItem(key)).pages, key), []);
    // An empty gallery saved by an older version is normalized on opening.
    await page.evaluate(key => localStorage.setItem(key, JSON.stringify({ version: 1, activeId: '', pages: [] })), key);
    await page.reload({ waitUntil: 'networkidle' }); await localPermissions(page, username); await openOnline(page);
    const created = await assertEditableBlank(page);
    await closeOnline(page); await openOnline(page);
    assert.deepEqual(await onlineState(page), created, 'Legacy empty gallery receives only one persisted blank');
    assert.equal(page.modelCalls, 0); assert.deepEqual(page.regressionErrors, []);
    console.log('PASS online account local fixture: existing/selected drawings, saved blank, refresh, and legacy empty gallery');
  } finally { await page.close(); }
}

async function runDefaultEmptyContract(browser) {
  const page = await onlinePage(browser);
  try {
    const count = await page.evaluate(() => {
      const fixture = DMateDrawingWorkspace.mount(document.getElementById('graphEditorMount'), {
        persistent: false, sessionState: { gallery: JSON.stringify({ version: 2, activeId: '', pages: [] }) },
        legacyDocument: DMateDrawingWorkspace.blankDocument(), features: { ai: false, upload: false }
      });
      const count = fixture.getPages().length; fixture.destroy(); return count;
    });
    assert.equal(count, 0, 'Shared component without createBlankIfEmpty retains its offline zero-page contract');
    assert.equal(page.modelCalls, 0); assert.deepEqual(page.regressionErrors, []);
    console.log('PASS shared component: no opt-in flag preserves an empty gallery');
  } finally { await page.close(); }
}

async function runOCRDirectionContract(browser) {
  const page = await onlinePage(browser);
  try {
    await page.evaluate(documentValue => {
      window.ocrDirectionFixture = DMateGraphEditor.mount(document.getElementById('graphEditorMount'), {
        document: documentValue, initialDocument: documentValue, drawingOnly: false,
        originalUrl: 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="700"><rect width="100%" height="100%" fill="white"/></svg>')
      });
      showGraphEditorDialog(document.getElementById('graphEditorDialog'));
    }, gallery.pages[0].document);
    await page.waitForFunction(() => document.getElementById('graphEditorDialog').open
      && !document.getElementById('graphEditorDialog').dataset.positioning);
    await readyView(page);
    await page.locator('[data-overlay-tool="zoom-fit"]').click(); await settle(page);
    await selectShape(page, 'edge', false);
    await page.locator('.dge-selection-panel').getByRole('button', { name: /反转方向|Reverse direction/i }).click();
    const edge = await page.evaluate(() => ocrDirectionFixture.getDocument().graphs[0].edges[0]);
    assert.equal(edge.from, 'v2'); assert.equal(edge.to, 'v1'); assert.equal(edge.direction, 'forward');
    assert.equal(page.modelCalls, 0); assert.deepEqual(page.regressionErrors, []);
    console.log('PASS OCR isolation: Reverse direction remains available and swaps the actual edge endpoints');
  } finally { await page.close(); }
}

async function runOfflineViewport(browser, width) {
  const page = await browser.newPage({ viewport: { width, height: width === 390 ? 740 : 900 },
    isMobile: width === 390, hasTouch: width === 390, serviceWorkers: 'block' });
  await installStorageProbe(page);
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  let modelCalls = 0;
  await page.route(/\/(?:chat|ocr|drawing\/[^?]+)(?:\?|$)/, route => { modelCalls++; return route.abort(); });
  try {
    await page.goto(baseURL + '/offline', { waitUntil: 'networkidle' });
    await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
    await page.evaluate(value => __offlineTestStore.put('drawings', {id:'gallery',gallery:JSON.stringify(value),updatedAt:Date.now()}), gallery);
    if (width === 390) await page.locator('#offlineNavToggle').click();
    await page.locator('#graphDrawingBtn').click();
    await page.locator('#offlineDrawingHost .dge-overlay-viewport').waitFor();
    await readyView(page);
    await headerExportChecks(page, 'offline-' + width, true);
    await viewportAndPopoverChecks(page, width === 390, 'offline-' + width, false);
    for (const kind of ['vertex', 'edge']) {
      await selectShape(page, kind, width === 390);
      const position = await panelPosition(page);
      await propertyCard(page, width === 390);
      if (process.env.OFFLINE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/drawing-offline-' + width + '-' + kind + '.png' });
      console.log('PASS offline ' + width + ' ' + kind + ': ' + JSON.stringify(position) + '; last action reachable');
      await closeProperty(page);
    }
    const savedViews = new Map();
    for (const index of [1, 0]) {
      await zoomAway(page);
      savedViews.set(await page.locator('.ddw-name').inputValue(), await viewState(page));
      await history(page);
      await page.locator('.ddw-history-open').getByText(names[index], { exact: true }).click();
      if (savedViews.has(names[index])) await preservedView(page, savedViews.get(names[index]), 'Offline selected ' + names[index]);
      else await automaticFit(page, 'Offline first selected ' + names[index]);
    }
    await zoomAway(page);
    const priorView = await viewState(page);
    for (const target of ['concepts', 'drawing']) {
      if (width === 390) await page.locator('#offlineNavToggle').click();
      await page.locator('.offline-nav-item[data-panel="' + target + '"]').click();
    }
    await preservedView(page, priorView, 'Offline navigation return');
    assert.equal(await page.locator('.ddw-name').inputValue(), names[0], 'Returning to drawing preserves the selected page');
    assert.equal(modelCalls, 0); assert.deepEqual(errors, []);
  } finally { await page.close(); }
}

(async () => {
  if (process.env.OFFLINE_SCREENSHOT_DIR) require('node:fs').mkdirSync(process.env.OFFLINE_SCREENSHOT_DIR, { recursive: true });
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const width of [390, 1440]) await runCase(browser, width);
    for (const width of [390, 1440]) await runOfflineViewport(browser, width);
    await runGuestBlankLifecycle(browser);
    await runAccountGalleryLifecycle(browser);
    await runDefaultEmptyContract(browser);
    await runOCRDirectionContract(browser);
  }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
