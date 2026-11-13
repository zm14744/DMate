'use strict';

// Exercise the shared overlay itself: these are real SVG paint/geometry checks,
// independent of the drawing workspace's dialogs and property-panel layout.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5001';
const baseline = process.argv.includes('--baseline');
const source = baseline ? execFileSync('git', ['show', 'HEAD:static/graph-editor-overlay.js'], { cwd: root, encoding: 'utf8' })
  : fs.readFileSync(path.join(root, 'static/graph-editor-overlay.js'), 'utf8');
const settle = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));

async function mount(page, options = {}) {
  await page.evaluate(options => {
    const previousState = window.fixtureState;
    window.fixtureOverlay?.destroy();
    document.body.replaceChildren(Object.assign(document.createElement('main'), { id: 'overlay-fixture' }));
    if (options.hidden) document.getElementById('overlay-fixture').style.display = 'none';
    if (options.positioning) document.getElementById('overlay-fixture').dataset.positioning = 'true';
    const vertices = [], edges = [];
    const rows = [
      ['solid-unknown', 'solid', 'unknown'], ['solid-undirected', 'solid', 'undirected'],
      ['solid-forward', 'solid', 'forward'], ['solid-polyline', 'solid', 'undirected'],
      ['dashed', 'dashed', 'unknown'], ['dotted', 'dotted', 'undirected']
    ];
    for (const [index, [id, style, direction]] of rows.entries()) {
      const y = .1 + index * .145, from = id + '-a', to = id + '-b';
      vertices.push({ id: from, x: .1, y }, { id: to, x: .9, y });
      edges.push({ id, from, to, style, direction,
        ...(id === 'solid-polyline' ? { path: [[.1, y], [.3, y - .04], [.5, y + .04], [.7, y - .04], [.9, y]] } : {}) });
    }
    if (options.hugeDrawing) vertices[1].x = 30;
    window.fixtureGraph = options.graph || { id: 'G1', vertices, edges };
    window.fixtureSelected = null;
    const zoom = options.invalidZoom === 'NaN' ? NaN : options.invalidZoom === 'Infinity' ? Infinity : options.zoom ?? 100;
    window.fixtureState = options.reuseState ? previousState : { mode: 'select', zoom, visible: true };
    const imageHeight = options.tallImage ? 20000 : 400;
    const background = options.mixedImage ? '<rect width="1000" height="' + imageHeight + '" fill="white"/>'
      + Array.from({ length: 13 }, (_, i) => '<rect x="' + (i * 80) + '" width="40" height="' + imageHeight + '" fill="black"/>').join('')
      : '<rect width="1000" height="' + imageHeight + '" fill="white"/>';
    window.fixtureOverlay = DMateGraphOverlay.mount(document.getElementById('overlay-fixture'), {
      instance: 'overlay-regression', state: fixtureState, drawingOnly: options.drawingOnly !== false,
      originalUrl: 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="' + imageHeight + '">' + background + '</svg>'),
      graph: () => fixtureGraph, model: { getDocument: () => ({ graphs: [fixtureGraph] }) },
      nodeSelected: () => new Set(), edgeSelected: () => fixtureSelected
    });
    window.fixtureRestoredZoom = fixtureState.zoom;
  }, options);
  if (options.hidden) {
    await page.waitForFunction(() => { const img = document.querySelector('.dge-overlay-image'); return img?.complete && img.naturalWidth > 0; });
    await settle(page); return;
  }
  await page.waitForFunction(() => document.querySelector('.dge-overlay')?.dataset.geometryReady === 'true');
  await settle(page);
}

async function camera(page) {
  return page.evaluate(() => {
    const viewport = document.querySelector('.dge-overlay-viewport'), svg = document.querySelector('.dge-overlay-svg'),
      box = svg.viewBox.baseVal, rect = viewport.getBoundingClientRect();
    let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
    for (const shape of svg.querySelectorAll('.dge-overlay-stroke,.dge-overlay-dot,.dge-overlay-label')) {
      const style = getComputedStyle(shape), bounds = shape.getBBox(), matrix = shape.getScreenCTM(),
        pad = style.stroke === 'none' ? 0 : Number.parseFloat(style.strokeWidth) * Math.hypot(matrix.a, matrix.b) / 2;
      const a = new DOMPoint(bounds.x, bounds.y).matrixTransform(matrix),
        b = new DOMPoint(bounds.x + bounds.width, bounds.y + bounds.height).matrixTransform(matrix);
      left = Math.min(left, a.x - pad); top = Math.min(top, a.y - pad);
      right = Math.max(right, b.x + pad); bottom = Math.max(bottom, b.y + pad);
    }
    const drawing = Number.isFinite(left) ? { left: left - rect.left, top: top - rect.top,
      right: rect.left + viewport.clientWidth - right, bottom: rect.top + viewport.clientHeight - bottom,
      cx: (left + right) / 2 - (rect.left + viewport.clientWidth / 2),
      cy: (top + bottom) / 2 - (rect.top + viewport.clientHeight / 2) } : null;
    return { zoom: fixtureState.zoom, x: viewport.scrollLeft, y: viewport.scrollTop,
      bx: box.x, by: box.y, bw: box.width, bh: box.height, drawing };
  });
}

function equalCamera(actual, expected, message) {
  for (const key of ['zoom', 'x', 'y', 'bx', 'by', 'bw', 'bh']) assert.ok(Math.abs(actual[key] - expected[key]) < .1,
    message + ' (' + key + '): ' + JSON.stringify({ actual, expected }));
}

async function initialFit(page, name, { bounds = true } = {}) {
  // Capture the very first usable frame before ever invoking the Fit control.
  const initial = await camera(page);
  await page.locator('[data-overlay-tool="zoom-fit"]').click(); await settle(page);
  equalCamera(initial, await camera(page), name + ' first frame already equals a real Fit');
  if (bounds) {
    assert.ok(initial.drawing, name + ' has actual rendered geometry');
    for (const side of ['left', 'top', 'right', 'bottom']) assert.ok(initial.drawing[side] >= 27,
      name + ' keeps the fitted 28px margin: ' + JSON.stringify(initial));
    for (const axis of ['cx', 'cy']) assert.ok(Math.abs(initial.drawing[axis]) <= 1.1,
      name + ' visible drawing is centred: ' + JSON.stringify(initial));
  }
  return initial;
}

async function automaticFitCases(page) {
  const pageA = { id: 'saved-A', vertices: [{ id: 'a', label: 'A', x: .06, y: .12 }, { id: 'b', label: 'B', x: .35, y: .32 }],
    edges: [{ id: 'ab', from: 'a', to: 'b', direction: 'undirected', style: 'solid' }] };
  const pageB = { id: 'saved-B', vertices: [{ id: 'c', label: 'C', x: .58, y: .63 }, { id: 'd', label: 'D', x: .9, y: .88 }],
    edges: [{ id: 'cd', from: 'c', to: 'd', direction: 'undirected', style: 'solid', path: [[.58, .63], [.74, .55], [.9, .88]] }] };
  await mount(page, { graph: pageA, zoom: 25 }); const a = await initialFit(page, 'Saved page A');
  await page.evaluate(() => {
    for (let i = 0; i < 12; i++) document.querySelector('[data-overlay-tool="zoom-in"]').click();
    const viewport = document.querySelector('.dge-overlay-viewport'); viewport.scrollLeft += 123; viewport.scrollTop += 91;
  });
  assert.equal(await page.evaluate(() => fixtureState.zoom), 400, 'Reopen fixture contains a real previous zoom');
  await mount(page, { graph: pageB, reuseState: true }); await initialFit(page, 'Switch to differently placed page B');
  await mount(page, { graph: pageA, reuseState: true }); equalCamera(await initialFit(page, 'Reopen page A'), a, 'Page A forgets previous pan and zoom');
  await page.evaluate(() => {
    for (let i = 0; i < 12; i++) document.querySelector('[data-overlay-tool="zoom-in"]').click();
    const viewport = document.querySelector('.dge-overlay-viewport'); viewport.scrollLeft += 123; viewport.scrollTop += 91;
    const host = document.getElementById('overlay-fixture'); host.style.display = 'none'; fixtureOverlay.fitView();
  });
  assert.deepEqual(await page.evaluate(() => ({ width: document.querySelector('.dge-overlay-viewport').clientWidth,
    ready: document.querySelector('.dge-overlay').dataset.geometryReady })), { width: 0, ready: 'false' }, 'Reused hidden controller queues its explicit fit');
  await page.locator('#overlay-fixture').evaluate(node => { node.style.display = ''; });
  await page.waitForFunction(() => document.querySelector('.dge-overlay').dataset.geometryReady === 'true'); await settle(page);
  equalCamera(await initialFit(page, 'Reused hidden controller after returning to drawing'), a, 'Returning to drawing discards old pan and zoom');
  await page.evaluate(() => {
    for (let i = 0; i < 12; i++) document.querySelector('[data-overlay-tool="zoom-in"]').click();
    const viewport = document.querySelector('.dge-overlay-viewport'); viewport.scrollLeft += 123; viewport.scrollTop += 91;
    fixtureOverlay.fitView();
  }); await settle(page);
  equalCamera(await camera(page), a, 'Visible explicit fitView uses the same Fit camera');
  await mount(page, { graph: pageB, zoom: 400, hidden: true });
  assert.deepEqual(await page.evaluate(() => ({ width: document.querySelector('.dge-overlay-viewport').clientWidth,
    ready: document.querySelector('.dge-overlay').dataset.geometryReady })), { width: 0, ready: 'false' }, 'Loaded hidden image waits for real dimensions');
  await page.locator('#overlay-fixture').evaluate(node => { node.style.display = ''; });
  await page.waitForFunction(() => document.querySelector('.dge-overlay').dataset.geometryReady === 'true'); await settle(page);
  await initialFit(page, 'Hidden mount after becoming visible');
  await mount(page, { graph: pageA, zoom: 400, positioning: true });
  assert.deepEqual(await page.evaluate(() => ({ width: document.querySelector('.dge-overlay-viewport').clientWidth > 0,
    visibility: getComputedStyle(document.querySelector('.dge-overlay-svg')).visibility,
    labelVisibility: getComputedStyle(document.querySelector('.dge-overlay-label')).visibility })),
  { width: true, visibility: 'hidden', labelVisibility: 'hidden' }, 'Dialog positioning hides every descendant while retaining layout');
  const positioningCamera = await camera(page);
  await page.locator('#overlay-fixture').evaluate(node => { node.removeAttribute('data-positioning'); }); await settle(page);
  equalCamera(await camera(page), positioningCamera, 'Revealing positioned dialog preserves its already fitted camera');
  await initialFit(page, 'Initially visibility-hidden positioning dialog');
  // These documents represent the existing import/generation mount contract.
  await mount(page, { graph: { ...pageA, id: 'imported', vertices: pageA.vertices.map(v => ({ ...v, x: v.x + .3, y: v.y + .4 })) }, zoom: 400 });
  await initialFit(page, 'Imported document');
  await mount(page, { graph: { id: 'generated', vertices: [ { id: 'x', label: 'x', x: .18, y: .16 }, { id: 'y', label: 'y', x: .76, y: .22 }, { id: 'z', label: 'z', x: .39, y: .78 } ],
    edges: [ { id: 'xy', from: 'x', to: 'y', direction: 'undirected', style: 'solid' }, { id: 'yz', from: 'y', to: 'z', direction: 'undirected', style: 'solid' } ] }, zoom: 25 });
  await initialFit(page, 'Generated document');
  await page.evaluate(() => { for (let i = 0; i < 12; i++) document.querySelector('[data-overlay-tool="zoom-in"]').click(); });
  const editedCamera = await camera(page);
  await page.evaluate(() => { fixtureGraph.vertices[0].x += .015; fixtureOverlay.refresh(); }); await settle(page);
  equalCamera(await camera(page), editedCamera, 'Ordinary geometry edits keep the camera');
  await page.locator('#overlay-fixture').evaluate(node => { node.style.width = '85%'; }); await settle(page);
  assert.equal((await camera(page)).zoom, editedCamera.zoom, 'Ordinary ResizeObserver updates do not refit');
  await mount(page, { graph: { id: 'empty', vertices: [], edges: [] }, zoom: 400 });
  const empty = await initialFit(page, 'Blank page', { bounds: false }); assert.equal(empty.zoom, 100, 'Blank page naturally fits its source canvas');
}

async function paint(page, selected = null) {
  return page.evaluate(selected => {
    fixtureSelected = selected; fixtureOverlay.refresh();
    return [...document.querySelectorAll('.dge-overlay-edge')].map(group => {
      const stroke = group.querySelector('.dge-overlay-stroke'), halo = group.querySelector('.dge-overlay-contrast-halo');
      const read = node => {
        const style = getComputedStyle(node), scale = Math.hypot(node.getScreenCTM().a, node.getScreenCTM().b);
        return { dash: style.strokeDasharray === 'none' ? [] : style.strokeDasharray.split(/[ ,]+/).map(Number.parseFloat).map(x => x * scale),
          width: Number.parseFloat(style.strokeWidth) * scale, offset: Number.parseFloat(style.strokeDashoffset) * scale };
      };
      return { id: group.dataset.edgeId, stroke: read(stroke), halo: read(halo), marker: stroke.getAttribute('marker-end') };
    });
  }, selected);
}

function checkPaint(rows, selected) {
  for (const edge of rows) {
    const expected = edge.id === 'dashed' ? [9, 6] : edge.id === 'dotted' ? [2, 5] : [];
    for (const layer of ['stroke', 'halo']) {
      assert.equal(edge[layer].dash.length, expected.length, edge.id + ' ' + layer + ' dash kind');
      expected.forEach((value, index) => assert.ok(Math.abs(edge[layer].dash[index] - value) < .03,
        edge.id + ' ' + layer + ' keeps its dash length in screen pixels: ' + JSON.stringify(edge[layer])));
    }
    assert.ok(Math.abs(edge.stroke.width - (edge.id === selected ? 3.6 : 2.1)) < .03, edge.id + ' constant screen stroke');
    assert.ok(Math.abs(edge.halo.width - (edge.id === selected ? 6.2 : 4.8)) < .03, edge.id + ' constant screen halo');
    assert.ok(Math.abs(edge.halo.offset - edge.stroke.offset) < .03, edge.id + ' halo and ink dash phase agree');
    if (edge.id === 'solid-forward') assert.match(edge.marker, /^url\(#overlay-regression-arrow-dark\)$/, 'Forward arrow remains attached');
  }
}

async function rasterContinuity(page, id) {
  return page.evaluate(async id => {
    const original = document.querySelector('[data-edge-id="' + id + '"] .dge-overlay-stroke');
    const index = [...document.querySelectorAll('.dge-overlay-edge')].findIndex(node => node.dataset.edgeId === id);
    const output = fixtureOverlay.getDrawingSvg();
    const exportedEdges = [...output.querySelectorAll('.dge-overlay-edge')];
    exportedEdges.forEach((node, i) => { if (i !== index) node.remove(); });
    output.querySelectorAll('.dge-overlay-node').forEach(node => node.remove());
    const box = output.viewBox.baseVal, scale = Math.hypot(original.getScreenCTM().a, original.getScreenCTM().b);
    const canvas = document.createElement('canvas'); canvas.width = Math.ceil(box.width * scale); canvas.height = Math.ceil(box.height * scale);
    const image = new Image(), url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(output)], { type: 'image/svg+xml' }));
    try {
      image.src = url; await image.decode();
      const ctx = canvas.getContext('2d', { willReadFrequently: true }); ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
      const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      const length = original.getTotalLength(); let longestGap = 0, gap = 0, samples = 0;
      // Sample the actual SVG path every screen pixel, excluding vertex caps.
      for (let distance = 10 / scale; distance < length - 10 / scale; distance += 1 / scale) {
        const point = original.getPointAtLength(distance), x = Math.round((point.x - box.x) / box.width * canvas.width),
          y = Math.round((point.y - box.y) / box.height * canvas.height);
        let darkest = 255;
        for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
          const px = Math.max(0, Math.min(canvas.width - 1, x + dx)), py = Math.max(0, Math.min(canvas.height - 1, y + dy)), offset = (py * canvas.width + px) * 4;
          darkest = Math.min(darkest, (pixels[offset] + pixels[offset + 1] + pixels[offset + 2]) / 3);
        }
        gap = darkest > 225 ? gap + 1 : 0; longestGap = Math.max(longestGap, gap); samples++;
      }
      return { longestGap, samples, canvas: [canvas.width, canvas.height] };
    } finally { URL.revokeObjectURL(url); }
  }, id);
}

async function pinch(page, session, ratio) {
  const centre = await page.locator('.dge-overlay-viewport').evaluate(node => { const r = node.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; });
  const touch = distance => [ { x: centre.x - distance / 2, y: centre.y, id: 0 }, { x: centre.x + distance / 2, y: centre.y, id: 1 } ];
  await session.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: touch(60) });
  await session.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: touch(60 * ratio) });
  await session.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await settle(page);
}

async function run(browser, width) {
  const context = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: true, isMobile: width === 390 });
  const page = await context.newPage(), errors = []; page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(baseURL + '/health', { waitUntil: 'domcontentloaded' });
    await page.setContent('<meta name="viewport" content="width=device-width, initial-scale=1"><style>body{margin:0}#overlay-fixture{width:100%;max-width:1280px;margin:auto}#overlay-fixture[data-positioning],#overlay-fixture[data-positioning] *{visibility:hidden!important}</style>');
    await page.addStyleTag({ path: path.join(root, 'static/graph-editor.css') });
    await page.addScriptTag({ content: source });
    await automaticFitCases(page);
    await mount(page);
    await initialFit(page, 'Full paint fixture', { bounds: false });
    const session = await context.newCDPSession(page);
    await page.evaluate(() => { for (let i = 0; i < 12; i++) document.querySelector('[data-overlay-tool="zoom-in"]').click(); }); await settle(page);
    assert.equal(await page.evaluate(() => fixtureState.zoom), 400);
    await pinch(page, session, .25);
    assert.equal(await page.evaluate(() => fixtureState.zoom), 100, 'Real controls prepare exact 100% after the initial automatic fit');
    checkPaint(await paint(page), null);
    for (const id of ['solid-unknown', 'solid-polyline']) {
      const raster = await rasterContinuity(page, id); assert.ok(raster.samples > 100); assert.equal(raster.longestGap, 0, width + ' 100% continuous ' + id + ': ' + JSON.stringify(raster));
    }
    await page.evaluate(() => { for (let i = 0; i < 10; i++) document.querySelector('[data-overlay-tool="zoom-in"]').click(); }); await settle(page);
    assert.equal(await page.evaluate(() => fixtureState.zoom), 400);
    assert.ok(await page.locator('[data-overlay-tool="zoom-in"]').isDisabled(), 'Maximum zoom is reflected by the real button');
    assert.equal(await page.locator('[data-overlay-tool="zoom-in"]').getAttribute('aria-disabled'), 'true');
    await page.locator('.dge-overlay-viewport').dispatchEvent('wheel', { ctrlKey: true, deltaY: -100 });
    assert.equal(await page.evaluate(() => fixtureState.zoom), 400, 'Ctrl-wheel respects maximum');
    await pinch(page, session, 2); assert.equal(await page.evaluate(() => fixtureState.zoom), 400, 'Native pinch respects maximum');
    checkPaint(await paint(page), null); checkPaint(await paint(page, 'solid-polyline'), 'solid-polyline');
    for (const id of ['solid-unknown', 'solid-polyline']) {
      const raster = await rasterContinuity(page, id); assert.equal(raster.longestGap, 0, width + ' 400% continuous ' + id + ': ' + JSON.stringify(raster));
    }
    await page.evaluate(() => {
      const viewport = document.querySelector('.dge-overlay-viewport'), path = document.querySelector('[data-edge-id="solid-unknown"] .dge-overlay-stroke');
      for (const length of [0, path.getTotalLength()]) {
        const local = path.getPointAtLength(length), point = new DOMPoint(local.x, local.y).matrixTransform(path.getScreenCTM()), rect = viewport.getBoundingClientRect();
        viewport.scrollLeft += point.x - (rect.left + rect.width / 2); viewport.scrollTop += point.y - (rect.top + rect.height / 2);
        const moved = new DOMPoint(local.x, local.y).matrixTransform(path.getScreenCTM());
        if (moved.x < rect.left - 1 || moved.x > rect.right + 1 || moved.y < rect.top - 1 || moved.y > rect.bottom + 1) throw new Error('400% endpoint is unreachable by real scrolling');
      }
      const output = fixtureOverlay.getDrawingSvg();
      if (output.querySelector('.dge-overlay-hit,.dge-overlay-node-hit,.dge-overlay-handle')) throw new Error('Export contains interaction controls');
      if (!output.querySelector('[marker-end]') || !output.querySelector('defs marker')) throw new Error('Export lost its arrow');
      if ([...output.querySelectorAll('.dge-overlay-edge')].slice(0, 4).some(group => group.querySelector('.dge-overlay-stroke').style.strokeDasharray !== 'none')) throw new Error('Export changed solid style');
    });
    await page.evaluate(() => { for (let i = 0; i < 30; i++) document.querySelector('[data-overlay-tool="zoom-out"]').click(); }); await settle(page);
    assert.equal(await page.evaluate(() => fixtureState.zoom), 25);
    assert.ok(await page.locator('[data-overlay-tool="zoom-out"]').isDisabled(), 'Minimum zoom disables zoom-out');
    assert.equal(await page.locator('[data-overlay-tool="zoom-out"]').getAttribute('aria-disabled'), 'true');
    await page.locator('.dge-overlay-viewport').dispatchEvent('wheel', { ctrlKey: true, deltaY: 100 });
    assert.equal(await page.evaluate(() => fixtureState.zoom), 25, 'Ctrl-wheel respects minimum');
    await pinch(page, session, .5); assert.equal(await page.evaluate(() => fixtureState.zoom), 25, 'Native pinch respects minimum');
    await pinch(page, session, 2); assert.ok(Math.abs(await page.evaluate(() => fixtureState.zoom) - 50) < .1, 'Native pinch really changes zoom');
    const fits = [];
    for (let i = 0; i < 3; i++) {
      await page.locator('[data-overlay-tool="zoom-fit"]').click(); await settle(page);
      fits.push(await page.evaluate(() => { const v = document.querySelector('.dge-overlay-viewport'); return { zoom: fixtureState.zoom, x: v.scrollLeft, y: v.scrollTop }; }));
    }
    assert.ok(fits[0].zoom >= 25 && fits[0].zoom <= 400);
    for (const fit of fits.slice(1)) for (const key of ['zoom', 'x', 'y']) assert.ok(Math.abs(fit[key] - fits[0][key]) < .1, 'Repeated fit is stable: ' + JSON.stringify(fits));
    for (const options of [{ zoom: .02 }, { zoom: 900 }, { zoom: -10 }, { invalidZoom: 'NaN' }, { invalidZoom: 'Infinity' }]) {
      await mount(page, options); const restored = await page.evaluate(() => fixtureRestoredZoom);
      assert.ok(Number.isFinite(restored) && restored >= 25 && restored <= 400, 'Legacy zoom is normalized before image load: ' + JSON.stringify(options));
    }
    await mount(page, { hugeDrawing: true }); await page.locator('[data-overlay-tool="zoom-fit"]').click(); await settle(page);
    assert.equal(await page.evaluate(() => fixtureState.zoom), 25, 'Drawing fit respects meaningful lower limit');
    await mount(page, { drawingOnly: false, tallImage: true });
    assert.ok(await page.evaluate(() => fixtureState.zoom > 0 && fixtureState.zoom < 25), 'OCR can still fit an unusually tall source image');
    const ocr = await paint(page); assert.deepEqual(ocr.find(edge => edge.id === 'solid-unknown').stroke.dash.map(x => Math.round(x)), [7, 5], 'OCR retains unknown-direction feedback');
    await mount(page, { drawingOnly: false, mixedImage: true });
    const phases = await page.evaluate(() => {
      let traversed = 0;
      return [...document.querySelectorAll('[data-edge-id="dotted"] .dge-overlay-stroke')].map(stroke => {
        const scale = Math.hypot(stroke.getScreenCTM().a, stroke.getScreenCTM().b), style = getComputedStyle(stroke),
          halo = stroke.closest('.dge-overlay-edge').querySelectorAll('.dge-overlay-contrast-halo')[Array.from(stroke.parentNode.querySelectorAll('.dge-overlay-stroke')).indexOf(stroke)];
        const result = { offset: Number.parseFloat(style.strokeDashoffset) * scale, expected: -traversed,
          halo: Number.parseFloat(getComputedStyle(halo).strokeDashoffset) * scale,
          dash: style.strokeDasharray.split(/[ ,]+/).map(Number.parseFloat).map(x => x * scale) };
        traversed += stroke.getTotalLength() * scale; return result;
      });
    });
    assert.ok(phases.length > 1, 'Real mixed-image sampling must exercise multiple ink runs');
    for (const phase of phases) {
      assert.ok(Math.abs(phase.offset - phase.expected) < .05, 'Split strokes preserve their continuous dash phase: ' + JSON.stringify(phase));
      assert.ok(Math.abs(phase.halo - phase.offset) < .05);
      phase.dash.forEach((value, index) => assert.ok(Math.abs(value - [2, 5][index]) < .03));
    }
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ width, status: 'PASS', fits, baseline }));
  } finally { await context.close(); }
}

(async () => {
  const executablePath = process.env.CHROMIUM_EXECUTABLE_PATH || process.env.CHROMIUM_EXECUTABLE;
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'],
    ...(executablePath ? { executablePath } : {}) });
  try { for (const width of [1440, 390]) await run(browser, width); }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
