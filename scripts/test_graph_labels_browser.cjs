/* Actual glyph bounds and complete text, rather than CSS box dimensions, prove
 * the shared graph labels fit. No model endpoints or user galleries are used.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const settle = page => page.evaluate(async () => {
  await document.fonts.ready;
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
});

function installProbe() {
  const plain = text => String(text || '').replace(/\s+/gu, '');
  const union = boxes => ({ left: Math.min(...boxes.map(box => box.left)), top: Math.min(...boxes.map(box => box.top)),
    right: Math.max(...boxes.map(box => box.right)), bottom: Math.max(...boxes.map(box => box.bottom)) });
  function inspect(root, expected, language) {
    const issues = [], entries = [...root.querySelectorAll('.kg-node-group,.kg-mobile-node')];
    let badges = 0, lines = 0, maxCenterError = 0;
    const fail = (name, message) => issues.push(name + ': ' + message);
    entries.forEach((node, index) => {
      const html = node.matches('.kg-mobile-node'), rect = html ? node.getBoundingClientRect() : node.querySelector('rect').getBoundingClientRect();
      const width = html ? node.offsetWidth : Number(node.querySelector('rect').getAttribute('width'));
      const height = html ? node.offsetHeight : Number(node.querySelector('rect').getAttribute('height'));
      const sx = rect.width / width, sy = rect.height / height;
      const source = expected[index];
      if (!source) { fail(index, 'unexpected node'); return; }
      const label = DMateKnowledgeLanguage.label(source.name, language);
      const badge = source.badge === undefined ? DMateI18n.t(source.level || '') : source.badge;
      const title = node.querySelector(html ? '.kg-mobile-node-name' : '.kg-node-label');
      const subtitle = node.querySelector(html ? '.kg-mobile-node-badge' : '.kg-node-badge');
      const fontScale = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--font-scale')) || 1;
      const paddingX = (html ? 12 : 10) * fontScale;
      const paddingY = 10 * fontScale;
      const actualBoxes = [];
      const measure = element => {
        if (!element) return [];
        if (!html) {
          const bounds = element.getBBox(), matrix = element.getScreenCTM();
          const corners = [[bounds.x, bounds.y], [bounds.x + bounds.width, bounds.y],
            [bounds.x, bounds.y + bounds.height], [bounds.x + bounds.width, bounds.y + bounds.height]]
            .map(([x, y]) => new DOMPoint(x, y).matrixTransform(matrix));
          return [{ left: (Math.min(...corners.map(p => p.x)) - rect.left) / sx,
            top: (Math.min(...corners.map(p => p.y)) - rect.top) / sy,
            right: (Math.max(...corners.map(p => p.x)) - rect.left) / sx,
            bottom: (Math.max(...corners.map(p => p.y)) - rect.top) / sy }];
        }
        const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT), rectangles = [];
        while (walker.nextNode()) {
          const range = document.createRange(); range.selectNodeContents(walker.currentNode);
          rectangles.push(...range.getClientRects());
        }
        return rectangles.filter(box => box.width > .1 && box.height > .1).map(box => ({
          left: (box.left - rect.left) / sx, top: (box.top - rect.top) / sy,
          right: (box.right - rect.left) / sx, bottom: (box.bottom - rect.top) / sy }));
      };
      const part = (element, text, kind) => {
        if (!element) { if (text) fail(label, 'missing ' + kind); return []; }
        const children = [...element.querySelectorAll(html ? ':scope>span' : ':scope>tspan')];
        const textLines = children.length ? children.map(line => line.textContent) : [element.textContent];
        lines += textLines.length;
        if (plain(textLines.join('')) !== plain(text)) fail(label, kind + ' is incomplete: ' + JSON.stringify(textLines));
        if (textLines.some(line => /…|\.\.\./u.test(line)) && !/…|\.\.\./u.test(text)) fail(label, kind + ' is ellipsized');
        const bounds = measure(element);
        if (!bounds.length) fail(label, kind + ' has no rendered glyphs');
        for (const box of bounds) {
          if (box.left < paddingX - 1 || box.right > width - paddingX + 1
            || box.top < paddingY - 1 || box.bottom > height - paddingY + 1)
            fail(label, kind + ' crosses padding: ' + JSON.stringify({ box, width, height, paddingX, paddingY }));
        }
        if (language === 'en') {
          const canvas = document.createElement('canvas'), ctx = canvas.getContext('2d'), css = getComputedStyle(element);
          ctx.font = css.fontWeight + ' ' + css.fontSize + ' ' + css.fontFamily;
          for (const word of text.match(/\S+/gu) || []) {
            if (ctx.measureText(word).width <= width - paddingX * 2 + .5 && !textLines.some(line => line.includes(word)))
              fail(label, kind + ' splits a word which fits: ' + word + ' in ' + JSON.stringify(textLines));
          }
        }
        actualBoxes.push(...bounds);
        return bounds;
      };
      const titleBounds = part(title, label, 'title');
      const badgeBounds = badge ? part(subtitle, badge, 'badge') : [];
      if (badge) badges++;
      if (titleBounds.length && badgeBounds.length) {
        if (union(titleBounds).bottom > union(badgeBounds).top + .5) fail(label, 'title overlaps badge');
      }
      if (actualBoxes.length) {
        const ink = union(actualBoxes), dx = Math.abs((ink.left + ink.right) / 2 - width / 2),
          dy = Math.abs((ink.top + ink.bottom) / 2 - height / 2);
        maxCenterError = Math.max(maxCenterError, dx, dy);
        if (dx > 2 || dy > 2) fail(label, 'combined text is not centered: ' + JSON.stringify({ dx, dy, ink, width, height }));
      }
    });
    if (entries.length !== expected.length) issues.push('Expected ' + expected.length + ' nodes, rendered ' + entries.length);
    return { count: entries.length, badges, lines, maxCenterError, issues };
  }
  window.graphLabelProbe = { inspect, plain };
}

async function full(page) {
  if (page.viewportSize().width <= 760 && !await page.locator('#knowledgeGraphCanvas .kg-mobile-viewport').count()) {
    await page.locator('#knowledgeGraphCanvas .kg-mobile-expand').click();
  }
  await page.locator('#knowledgeGraphCanvas .kg-node-group,#knowledgeGraphCanvas .kg-mobile-node').first().waitFor();
  await settle(page);
}

async function filter(page, value) {
  // Dispatch the real select's change event even while mobile full-screen
  // intentionally hides its toolbar. Selection gestures are covered separately.
  await page.locator('#knowledgeGraphCategory').selectOption({ value }, { force: true });
  await full(page);
}

async function font(page, mode, offline) {
  await page.evaluate(({ mode, offline }) => {
    if (offline) DMateOfflineAppearance.apply({ ...DMateOfflineAppearance.getSettings(), mode: 'dark', fontSize: mode });
    else { appearanceSettings = { ...appearanceSettings, mode: 'dark', fontSize: mode }; applyAppearanceSettings({ save: false }); }
  }, { mode, offline });
  await settle(page);
}

async function check(page, expected, language, label) {
  const result = await page.evaluate(({ expected, language }) => {
    const root = document.getElementById('knowledgeGraphCanvas'), result = graphLabelProbe.inspect(root, expected, language);
    result.fontSize = parseFloat(getComputedStyle(root.querySelector('.kg-mobile-node-name,.kg-node-label')).fontSize);
    result.fontScale = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--font-scale')) || 1;
    return result;
  }, { expected, language });
  assert.deepEqual(result.issues, [], label + ': actual label bounds\n' + result.issues.slice(0, 12).join('\n'));
  assert.ok(Math.abs(result.fontSize - (page.viewportSize().width <= 760 ? 13 : 12) * result.fontScale) < .02,
    label + ': changing appearance really updates the label font, rather than reusing stale geometry');
  return result;
}

async function png(page, expected, language, offline) {
  const result = await page.evaluate(async ({ expected, language, offline }) => {
    const decode = async blob => {
      const url = URL.createObjectURL(blob), image = new Image();
      try {
        await new Promise((resolve, reject) => { image.onload = resolve; image.onerror = reject; image.src = url; });
        return { type: blob.type, bytes: blob.size, width: image.naturalWidth, height: image.naturalHeight };
      } finally { URL.revokeObjectURL(url); }
    };
    if (offline) {
      const exporter = DMateDrawingExport, original = exporter.pngBlob, download = exporter.download;
      const clipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined });
      const captured = new Promise((resolve, reject) => {
        exporter.pngBlob = async (svg, options) => {
          // A serialized SVG PNG has no page stylesheets. Measure its exact
          // clone in an isolated same-origin document for that same cascade.
          const host = document.createElement('iframe'); host.style.cssText = 'position:absolute;left:-20000px;top:0;width:1px;height:1px;border:0';
          document.body.append(host);
          host.contentDocument.body.append(svg.cloneNode(true));
          try {
            await document.fonts.ready;
            const labels = graphLabelProbe.inspect(host.contentDocument.body, expected, language);
            const blob = await original(svg, options);
            resolve({ ...await decode(blob), labels });
            return blob;
          } catch (error) { reject(error); throw error; } finally { host.remove(); }
        };
      });
      exporter.download = () => {}; // Capture local delivery; still render and decode the real PNG.
      try { document.getElementById('knowledgeGraphCopyBtn').click(); return await captured; }
      finally {
        exporter.pngBlob = original; exporter.download = download;
        if (clipboard) Object.defineProperty(navigator, 'clipboard', clipboard); else delete navigator.clipboard;
      }
    }
    const rectangle = window.drawKnowledgeGraphRoundRect, text = CanvasRenderingContext2D.prototype.fillText;
    const contexts = new Map();
    window.drawKnowledgeGraphRoundRect = function(ctx, x, y, width, height, ...rest) {
      if (!contexts.has(ctx)) contexts.set(ctx, []);
      contexts.get(ctx).push({ x, y, width, height, matrix: ctx.getTransform(), lines: [] });
      return rectangle.call(this, ctx, x, y, width, height, ...rest);
    };
    CanvasRenderingContext2D.prototype.fillText = function(value, x, y, ...rest) {
      const node = contexts.get(this)?.at(-1);
      if (node) {
        const metrics = this.measureText(value), matrix = this.getTransform(), inverse = node.matrix.inverse();
        const corners = [[x - metrics.actualBoundingBoxLeft, y - metrics.actualBoundingBoxAscent],
          [x + metrics.actualBoundingBoxRight, y + metrics.actualBoundingBoxDescent]]
          .map(([x, y]) => new DOMPoint(x, y).matrixTransform(matrix).matrixTransform(inverse));
        node.lines.push({ text: String(value), left: corners[0].x - node.x, top: corners[0].y - node.y,
          right: corners[1].x - node.x, bottom: corners[1].y - node.y });
      }
      return text.call(this, value, x, y, ...rest);
    };
    try {
      const blob = await renderKnowledgeGraphOffscreenPngBlob();
      const records = [...contexts.values()].find(nodes => nodes.length === expected.length);
      if (!records) throw new Error('The production PNG renderer did not draw all expected graph nodes');
      const issues = [];
      records.forEach((node, index) => {
        const source = expected[index], label = DMateKnowledgeLanguage.label(source.name, language), badge = DMateI18n.t(source.level || '');
        if (graphLabelProbe.plain(node.lines.map(line => line.text).join('')) !== graphLabelProbe.plain(label + badge))
          issues.push(label + ': PNG text incomplete: ' + JSON.stringify(node.lines.map(line => line.text)));
        for (const box of node.lines) if (box.left < 9 || box.top < 9 || box.right > node.width - 9 || box.bottom > node.height - 9)
          issues.push(label + ': PNG glyphs cross node padding: ' + JSON.stringify({ box, width: node.width, height: node.height }));
        const ink = { left: Math.min(...node.lines.map(line => line.left)), top: Math.min(...node.lines.map(line => line.top)),
          right: Math.max(...node.lines.map(line => line.right)), bottom: Math.max(...node.lines.map(line => line.bottom)) };
        if (Math.abs((ink.left + ink.right) / 2 - node.width / 2) > 2 || Math.abs((ink.top + ink.bottom) / 2 - node.height / 2) > 2)
          issues.push(label + ': PNG combined title/badge is not centered: ' + JSON.stringify(ink));
      });
      return { ...await decode(blob), labels: { count: records.length, issues } };
    } finally { window.drawKnowledgeGraphRoundRect = rectangle; CanvasRenderingContext2D.prototype.fillText = text; }
  }, { expected, language, offline });
  assert.equal(result.type, 'image/png');
  assert.ok(result.bytes > 1000 && result.width > 64 && result.height > 64, 'The production graph PNG decodes');
  assert.deepEqual(result.labels.issues, [], 'PNG export preserves complete centered labels\n' + result.labels.issues.slice(0, 8).join('\n'));
  assert.equal(result.labels.count, expected.length);
}

async function boundaries(page, language, tag) {
  for (const width of [132, 190]) {
    const result = await page.evaluate(({ width, language }) => {
      const fixtures = (language === 'en' ? [
        'Reachability and strongly connected components in directed multigraphs (including loops)',
        'Supercalifragilisticexpialidocious and complete words',
        'For every x ∈ V: d⁺(x) + d⁻(x) = 2|E|; α → β ∧ γ'
      ] : [
        '有向图中的可达关系与强连通分量（包含自环和平行边的完整说明）',
        '关系的自反闭包对称闭包与传递闭包及其矩阵表示',
        '∀x∈V：入度＋出度＝总度；α→β∧γ，|E|≥0'
      ]).map((name, index) => ({ id: 'label-fixture-' + index, name,
        badge: language === 'en' ? 'Core / #1' : '基础 · ∀/∃' }));
      const api = DMateKnowledgeGraphLabels, pack = api.prepare(fixtures, {
        label: node => node.name, badge: node => node.badge, width, minHeight: 58,
        titleSize: 13, weight: 600, badgeSize: 10, badgeWeight: 500, paddingX: 12, paddingY: 10, gap: 5, language
      });
      const host = document.createElement('div'); host.id = 'graphLabelFixtures';
      host.style.cssText = 'position:fixed;inset:0;z-index:100000;box-sizing:border-box;padding:16px;overflow:auto;display:flex;flex-wrap:wrap;align-content:flex-start;align-items:flex-start;gap:16px;background:#0f172a;color:#f8fafc;';
      const svgHost = document.createElement('section'), htmlHost = document.createElement('section');
      for (const node of [svgHost, htmlHost]) node.style.cssText = 'flex:none;width:' + width + 'px';
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      const step = pack.height + 16, totalHeight = step * fixtures.length;
      svg.setAttribute('width', width); svg.setAttribute('height', totalHeight); svg.setAttribute('viewBox', `0 0 ${width} ${totalHeight}`); svgHost.append(svg);
      const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = totalHeight;
      canvas.style.cssText = 'flex:none;background:#0f172a';
      const ctx = canvas.getContext('2d'), canvasIssues = [];
      fixtures.forEach((node, index) => {
        const value = pack.layouts.get(node.id), y = index * step;
        const group = document.createElementNS(svg.namespaceURI, 'g');group.setAttribute('class', 'kg-node-group');group.setAttribute('transform', `translate(0 ${y})`);
        const rect = document.createElementNS(svg.namespaceURI, 'rect');
        for (const [key, val] of Object.entries({ width, height: pack.height, rx: 12, fill: '#111827', stroke: '#475569' })) rect.setAttribute(key, val);
        group.append(rect); api.applySvg(group, value, { width, height: pack.height });svg.append(group);
        const button = document.createElement('button');button.type = 'button';button.className = 'kg-mobile-node';
        button.style.cssText = `position:relative;display:block;box-sizing:border-box;flex:none;width:${width}px;height:${pack.height}px;margin:0 0 16px;border:2px solid #475569;border-radius:12px;background:#111827;color:#f8fafc;overflow:hidden;`;
        api.applyHtml(button, value);htmlHost.append(button);
        ctx.fillStyle = '#111827';ctx.fillRect(0, y, width, pack.height);
        const calls = [], original = ctx.fillText;
        ctx.fillText = function(text, x, y) {
          const m = this.measureText(text);calls.push({ text, left: x - m.actualBoundingBoxLeft, right: x + m.actualBoundingBoxRight,
            top: y - m.actualBoundingBoxAscent, bottom: y + m.actualBoundingBoxDescent });
          return original.apply(this, arguments);
        };
        api.paint(ctx, value, 0, y, { width, height: pack.height });ctx.fillText = original;
        if (graphLabelProbe.plain(calls.map(call => call.text).join('')) !== graphLabelProbe.plain(node.name + node.badge)) canvasIssues.push(node.name + ': incomplete canvas fixture');
        if (calls.some(call => call.left < 11 || call.right > width - 11 || call.top < y + 9 || call.bottom > y + pack.height - 9)) canvasIssues.push(node.name + ': canvas fixture overflows padding');
        const center = (Math.min(...calls.map(call => call.top)) + Math.max(...calls.map(call => call.bottom))) / 2;
        if (Math.abs(center - y - pack.height / 2) > 2) canvasIssues.push(node.name + ': canvas fixture is not centered');
      });
      host.append(svgHost, htmlHost, canvas);document.body.append(host);
      return { svg: graphLabelProbe.inspect(svgHost, fixtures, language), html: graphLabelProbe.inspect(htmlHost, fixtures, language),
        canvasIssues, height: pack.height };
    }, { width, language });
    assert.deepEqual(result.svg.issues, [], 'SVG long-label boundary fixtures');
    assert.deepEqual(result.html.issues, [], 'HTML long-label boundary fixtures');
    assert.deepEqual(result.canvasIssues, [], 'PNG painter long-label boundary fixtures');
    assert.ok(result.height > 58, 'Long content expands its measured node height');
    if (width === 132 && process.env.OFFLINE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR
      + '/long-labels-' + tag + '-' + language + '.png' });
    await page.locator('#graphLabelFixtures').evaluate(node => node.remove());
  }
}

async function runCase(browser, width, offline) {
  const page = await browser.newPage({ viewport: { width, height: 900 }, isMobile: width <= 760,
    hasTouch: width <= 760, serviceWorkers: 'block' });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(baseURL + (offline ? '/offline' : '/'), { waitUntil: 'networkidle' });
    const data = await page.evaluate(async offline => offline
      ? await (await fetch('/static/offline-content/knowledge_graph.json')).json()
      : JSON.parse(document.getElementById('knowledgeGraphData').textContent), offline);
    const all = Array.isArray(data) ? data : data.nodes;
    assert.equal(all.length, 68);
    if (offline) {
      await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
      assert.equal(await page.locator('.offline-nav-item.active').getAttribute('data-panel'), 'graph', 'The inline graph is the default tool');
      assert.equal(await page.locator('#knowledgeGraphModal').evaluate(node => node.parentElement.id), 'graphPanel');
      assert.equal(await page.locator('#knowledgeGraphModal.modal,#knowledgeGraphClose').count(), 0,
        'Offline label checks exercise the embedded graph, without a modal overlay or close dot');
      const toggle = page.locator(width <= 760 ? '#offlineNavToggle' : '#offlineDesktopSidebarOpen');
      if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
      await page.locator('.offline-nav-item[data-panel="graph"]').click();
    } else await page.evaluate(() => openKnowledgeGraph());
    await page.locator('#knowledgeGraphCanvas .kg-section').waitFor();
    await page.evaluate(installProbe);
    const categories = await page.locator('#knowledgeGraphCategory option').evaluateAll(options => options.map(option => option.value));
    assert.equal(categories.length, 11);
    for (const language of ['zh-CN', 'en']) {
      await page.evaluate(value => DMateI18n.setLanguage(value, false), language);
      await font(page, 'standard', offline);
      let count = 0, maxCenter = 0;
      for (const category of categories) {
        await filter(page, category);
        const expected = all.filter(node => category === '全部' || node.category === category);
        const result = await check(page, expected, language, (offline ? 'offline' : 'online') + '/' + width + '/' + language + '/' + category);
        if (category === '全部') assert.ok(result.badges > 0, 'The full graph includes real badge nodes');
        count += result.count;
        maxCenter = Math.max(maxCenter, result.maxCenterError);
      }
      for (const size of ['small', 'large']) {
        await filter(page, '全部');
        await font(page, size, offline);
        await full(page);
        const result = await check(page, all, language, (offline ? 'offline' : 'online') + '/' + width + '/' + language + '/' + size);
        maxCenter = Math.max(maxCenter, result.maxCenterError);
      }
      await font(page, 'standard', offline);
      await filter(page, '全部');
      await png(page, all, language, offline);
      await boundaries(page, language, (offline ? 'offline' : 'online') + '-' + width);
      console.log('PASS ' + (offline ? 'offline' : 'online') + '/' + width + '/' + language
        + ': ' + categories.length + ' categories, ' + count + ' standard labels, all 68 labels at small/large sizes, real PNG and long/symbol fixtures; max center error '
        + maxCenter.toFixed(3) + 'px');
    }
    assert.deepEqual(errors, [], 'No label-layout page errors');
  } catch (error) {
    if (process.env.OFFLINE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR
      + '/FAILED-labels-' + (offline ? 'offline' : 'online') + '-' + width + '.png' }).catch(() => {});
    throw error;
  } finally { await page.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try { for (const offline of [false, true]) for (const width of [1440, 390]) await runCase(browser, width, offline); }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
