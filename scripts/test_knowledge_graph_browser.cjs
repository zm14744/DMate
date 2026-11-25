/* Real-app regression for mobile knowledge-graph fitting, selection and navigation.
 * Start the Flask app first. Set CHROMIUM_EXECUTABLE_PATH to use a system engine.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const {pinchGraph, expandGraphDetails} = require('./knowledge-graph-touch-fixtures.cjs');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const near = (actual, expected, message, tolerance = 1.5) =>
  assert.ok(Math.abs(actual - expected) <= tolerance,
    message + ': ' + actual + ' vs ' + expected);

async function openFullGraph(page) {
  await page.evaluate(() => openKnowledgeGraph());
  await page.waitForFunction(() => knowledgeGraphInitialized
    && document.getElementById('knowledgeGraphModal').dataset.graphView);
  await page.evaluate(() => selectKnowledgeGraphDisplayMode('full'));
  await page.waitForSelector('#knowledgeGraphCanvas .kg-section');
}

async function settleGraph(page) {
  await page.waitForFunction(() => {
    const viewport = document.querySelector('.kg-mobile-viewport');
    return viewport && viewport._kgScale && getComputedStyle(viewport).visibility === 'visible';
  });
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function snapshot(page) {
  return page.evaluate(() => {
    const viewport = document.querySelector('.kg-mobile-viewport');
    const stage = viewport.querySelector('.kg-mobile-stage');
    const rect = stage.getBoundingClientRect();
    const view = viewport.getBoundingClientRect();
    const css = getComputedStyle(viewport);
    const number = name => parseFloat(css[name]) || 0;
    const left = view.left + viewport.clientLeft + number('paddingLeft');
    const top = view.top + viewport.clientTop + number('paddingTop');
    const width = viewport.clientWidth - number('paddingLeft') - number('paddingRight');
    const height = viewport.clientHeight - number('paddingTop') - number('paddingBottom');
    const nodes = [...stage.querySelectorAll('.kg-mobile-node')].map(node => node.getBoundingClientRect());
    return {
      scale: viewport._kgScale,
      stage: { left: rect.left, top: rect.top, width: rect.width, height: rect.height },
      content: { left, top, width, height, right: left + width, bottom: top + height },
      scroll: { left: viewport.scrollLeft, top: viewport.scrollTop,
        width: viewport.scrollWidth, height: viewport.scrollHeight },
      nodes: { count: nodes.length, left: Math.min(...nodes.map(node => node.left)),
        top: Math.min(...nodes.map(node => node.top)), right: Math.max(...nodes.map(node => node.right)),
        bottom: Math.max(...nodes.map(node => node.bottom)) }
    };
  });
}

function checkCenteredAxes(state, label) {
  if (state.stage.width <= state.content.width + 1) {
    near(state.stage.left + state.stage.width / 2,
      state.content.left + state.content.width / 2, label + ': horizontal centering');
  }
  if (state.stage.height <= state.content.height + 1) {
    near(state.stage.top + state.stage.height / 2,
      state.content.top + state.content.height / 2, label + ': vertical centering');
  }
}

async function checkReachableEdges(page, label) {
  await page.locator('.kg-mobile-viewport').evaluate(view => { view.scrollLeft = 0; view.scrollTop = 0; });
  const start = await snapshot(page);
  assert.ok(start.nodes.left >= start.content.left - 1.5, label + ': first nodes clipped on left');
  assert.ok(start.nodes.top >= start.content.top - 1.5, label + ': first nodes clipped on top');
  assert.ok(start.nodes.left < start.content.right, label + ': left edge is not reachable');
  assert.ok(start.nodes.top < start.content.bottom, label + ': top edge is not reachable');
  await page.locator('.kg-mobile-viewport').evaluate(view => { view.scrollLeft = 1e7; view.scrollTop = 1e7; });
  const end = await snapshot(page);
  assert.ok(end.nodes.right <= end.content.right + 1.5, label + ': last nodes inaccessible on right');
  assert.ok(end.nodes.bottom <= end.content.bottom + 1.5, label + ': last nodes inaccessible below');
  assert.ok(end.nodes.right > end.content.left, label + ': horizontal scrolling overshoots graph');
  assert.ok(end.nodes.bottom > end.content.top, label + ': vertical scrolling overshoots graph');
}

async function checkCourseGeometry(page, mobile) {
  const result = await page.locator('#knowledgeGraphCanvas').evaluate((canvas, mobile) => {
    const model = JSON.parse(document.getElementById('knowledgeGraphData').textContent).nodes;
    const byName = new Map(model.map(node => [node.name, node.id]));
    const relation = (from, to) => from + ' → ' + to;
    const expectedEdges = model.flatMap(node => node.prerequisites
      .filter(name => byName.has(name)).map(name => relation(byName.get(name), node.id)));
    const paths = [...canvas.querySelectorAll(mobile ? '.kg-mobile-edge' : '.kg-edge')];
    const nodes = [...canvas.querySelectorAll(mobile ? '.kg-mobile-node' : '.kg-node-group')];
    const toGraph = paths[0].ownerSVGElement.getScreenCTM().inverse();
    const boxes = new Map();
    const ranks = new Map();
    const issues = [];
    for (const node of nodes) {
      const id = node.dataset.knowledgeNodeId;
      const rect = (mobile ? node : node.querySelector('rect')).getBoundingClientRect();
      const start = new DOMPoint(rect.left, rect.top).matrixTransform(toGraph);
      const end = new DOMPoint(rect.right, rect.bottom).matrixTransform(toGraph);
      boxes.set(id, { left: start.x, top: start.y, right: end.x, bottom: end.y });
      const depth = Math.round(mobile ? start.y : start.x);
      if (!ranks.has(depth)) ranks.set(depth, []);
      ranks.get(depth).push({id, position: mobile ? start.x : start.y});
      const label = node.querySelector(mobile ? '.kg-mobile-node-name' : '.kg-node-label');
      if (getComputedStyle(label).writingMode !== 'horizontal-tb') issues.push(id + ': label direction');
    }
    const edges = [], traces = [];
    for (const path of paths) {
      const { from, to } = path.dataset, key = relation(from, to);
      edges.push(key);
      const parent = boxes.get(from), child = boxes.get(to);
      if (!parent || !child) continue; // The relationship list is checked below.
      const d = path.getAttribute('d');
      if (!/[cqsta]/i.test(d) || /[lhvz]/i.test(d)) issues.push(key + ': straight path command');
      if ((d.match(/C/g)?.length || 0) > 5) issues.push(key + ': too many bends');
      const length = path.getTotalLength(), start = path.getPointAtLength(0), end = path.getPointAtLength(length);
      const direction = mobile ? end.y - start.y : end.x - start.x;
      const portErrors = mobile ? [start.y - parent.bottom, end.y - child.top]
        : [start.x - parent.right, end.x - child.left];
      const withinPort = (point, box) => mobile ? point.x >= box.left && point.x <= box.right
        : point.y >= box.top && point.y <= box.bottom;
      if (direction <= 0 || portErrors.some(error => Math.abs(error) > .1)
        || !withinPort(start, parent) || !withinPort(end, child)) issues.push(key + ': port direction');
      const dx = end.x - start.x, dy = end.y - start.y;
      const otherNodes = [...boxes].filter(([id]) => id !== from && id !== to);
      const samples = [];
      let bend = 0, lastProgress = mobile ? start.y : start.x;
      for (let distance = 3; distance < length; distance += 6) {
        const point = path.getPointAtLength(distance);
        if (distance > 12 && length - distance > 12) samples.push(point);
        const progress = mobile ? point.y : point.x;
        if (progress < lastProgress - .1) { issues.push(key + ': doubles back'); break; }
        lastProgress = progress;
        bend = Math.max(bend, Math.abs(dx * (point.y - start.y) - dy * (point.x - start.x)) / Math.hypot(dx, dy));
        const crossing = otherNodes.find(([, r]) => point.x > r.left && point.x < r.right
          && point.y > r.top && point.y < r.bottom);
        if (crossing) { issues.push(key + ': crosses ' + crossing[0]); break; }
      }
      if (bend < 1) issues.push(key + ': no visible curvature');
      traces.push({key, samples, stroke: new Path2D(d), box: path.getBBox(), start, end});
    }
    // Probe six consecutive points along one centreline against a narrow stroke of
    // the other. A single crossing or a shared connection at a node is allowed.
    const ctx = document.createElement('canvas').getContext('2d');
    ctx.lineWidth = .7;
    for (let i = 0; i < traces.length; i++) {
      for (const other of traces.slice(i + 1)) {
        let run = 0;
        for (const {x, y} of traces[i].samples) {
          const r = other.box;
          const inside = x >= r.x - 1 && x <= r.x + r.width + 1 && y >= r.y - 1 && y <= r.y + r.height + 1;
          if (inside && Math.hypot(x - other.start.x, y - other.start.y) > 12
            && Math.hypot(x - other.end.x, y - other.end.y) > 12 && ctx.isPointInStroke(other.stroke, x, y)) {
            if (++run === 6) { issues.push(traces[i].key + ': overlaps ' + other.key); break; }
          } else run = 0;
        }
      }
    }
    return { ids: nodes.map(node => node.dataset.knowledgeNodeId).sort(), expectedIds: model.map(node => node.id).sort(),
      edges: edges.sort(), expectedEdges: expectedEdges.sort(), issues,
      ranks: [...ranks].sort(([a], [b]) => a - b).map(([, nodes]) =>
        nodes.sort((a, b) => a.position - b.position).map(node => node.id)) };
  }, mobile);
  assert.deepEqual(result.ids, result.expectedIds, 'The full graph displays each course node once');
  assert.deepEqual(result.edges, result.expectedEdges, 'The full graph displays each course relationship once');
  assert.deepEqual(result.issues, [], 'Every course edge curves between the correct ports and clears other nodes');
  return result.ranks;
}

async function checkZoomLimits(browser, width) {
  const mobile = width <= 760;
  const page = await browser.newPage({viewport:{width,height:900},
    ...(mobile ? {isMobile:true,hasTouch:true} : {})});
  const errors = [];
  let courseRanks;
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(baseURL, {waitUntil:'networkidle'});
    await openFullGraph(page);
    const categories = await page.locator('#knowledgeGraphCategory option').evaluateAll(options => options.map(option => option.value));
    for (const category of categories) {
      await page.evaluate(value => setKnowledgeGraphFilter(value), category);
      await page.locator(mobile ? '.kg-mobile-viewport' : '.kg-desktop-viewport').waitFor();
      if (category === '全部') courseRanks = await checkCourseGeometry(page, mobile);
      if (mobile) {
        await settleGraph(page);
        for (const [factor, limit] of [[6, 3], [.15, .65]]) {
          await pinchGraph(page, factor);
          const before = await snapshot(page);
          near(before.scale, limit, category + ': pinch reaches the mobile limit', .0001);
          const watch = await page.locator('.kg-mobile-viewport').evaluateHandle(view => {
            const camera = () => [view._kgScale, view.scrollLeft, view.scrollTop].join(',');
            const initial = camera();
            let stable = true, frame;
            const sample = () => { stable &&= camera() === initial; frame = requestAnimationFrame(sample); };
            sample();
            const observer = new MutationObserver(() => { stable = false; });
            observer.observe(view, {subtree:true, childList:true, attributes:true,
              attributeFilter:['style','data-scale','data-kg-ready']});
            return () => { cancelAnimationFrame(frame); observer.disconnect(); return stable; };
          });
          await pinchGraph(page, factor);
          assert.ok(await watch.evaluate(stop => stop()), category + ': every clamped pinch frame keeps the graph stable');
          await watch.dispose();
          assert.deepEqual(await snapshot(page), before, category + ': repeating a clamped pinch retains the camera');
        }
        continue;
      }
      const result = await page.evaluate(async extendedIdle => {
        const view = document.querySelector('.kg-desktop-viewport');
        const surface = view.querySelector('.kg-desktop-zoom-surface'), stage = surface.querySelector('.kg-desktop-zoom-stage');
        const label = document.getElementById('knowledgeGraphDesktopZoomLabel');
        const plus = document.getElementById('knowledgeGraphDesktopZoomIn'), minus = document.getElementById('knowledgeGraphDesktopZoomOut');
        const scale = () => Number(surface.dataset.scale);
        const frames = count => new Promise(resolve => {
          const tick = () => --count ? requestAnimationFrame(tick) : resolve();
          requestAnimationFrame(tick);
        });
        const capture = () => {
          const rect = stage.getBoundingClientRect();
          return {scale:scale(), label:label.textContent, visible:getComputedStyle(view).visibility,
            dimensions:[view.clientWidth,view.clientHeight,surface.clientWidth,surface.clientHeight],
            scroll:[view.scrollLeft,view.scrollTop], stage:[rect.x,rect.y,rect.width,rect.height],
            nodes:stage.querySelectorAll('.kg-mobile-node,.kg-node-group').length};
        };
        const traces = [];
        for (const [kind,button,limit] of [['maximum',plus,2.5],['minimum',minus,.8]]) {
          // Reach the clamp through the actual control, including scrollbar
          // transitions; never assign a scale directly for this regression.
          let previous = null;
          for (let clicks = 0; clicks < 60; clicks++) {
            button.click();
            await frames(2);
            if (scale() === previous) break;
            previous = scale();
          }
          await frames(6);
          const before = capture(), samples = [], mutations = [];
          const observer = new MutationObserver(records => mutations.push(...records.map(record => ({
            type:record.type, name:record.attributeName || '',
            element:record.target.nodeType === Node.TEXT_NODE ? record.target.parentElement.className : record.target.className
          }))));
          observer.observe(view, {attributes:true,attributeFilter:['style','data-scale','data-kg-ready'],subtree:true,childList:true,characterData:true});
          observer.observe(label, {subtree:true,childList:true,characterData:true});
          for (let repeat = 0; repeat < 8; repeat++) {
            button.click(); await frames(1); samples.push(capture());
          }
          for (let idle = 0; idle < (extendedIdle ? 100 : 8); idle++) {
            await frames(1); samples.push(capture());
          }
          observer.disconnect();
          traces.push({kind,limit,before,samples,mutations});
        }
        return traces;
      }, category === categories[1]);
      for (const trace of result) {
        const label = width + '/' + category + '/' + trace.kind;
        if (trace.limit !== null) near(trace.before.scale, trace.limit, label + ': reached the zoom clamp', .000001);
        assert.equal(trace.before.visible, 'visible', label + ': graph remains visible');
        assert.ok(trace.before.nodes > 0, label + ': the graph still contains its nodes');
        assert.deepEqual(trace.mutations, [], label + ': repeated clamped controls do not rewrite or rebuild graph/label');
        for (const sample of trace.samples) assert.deepEqual(sample, trace.before,
          label + ': every painted frame preserves scale, camera and geometry');
      }
    }
    assert.deepEqual(errors, [], width + ': zoom-limit browser errors');
    console.log('PASS ' + width + ': every module keeps all frames and graph/label DOM stable at both zoom limits');
    return courseRanks;
  } finally { await page.close(); }
}

async function checkReturnPreservesView(browser, width) {
  const mobile = width <= 760;
  const page = await browser.newPage({ viewport: { width, height: 844 },
    ...(mobile ? { isMobile: true, hasTouch: true } : {}) });
  const viewSelector = mobile ? '.kg-mobile-viewport' : '.kg-desktop-viewport';
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    // Camera restoration belongs to an existing conversation. Closing a graph
    // over the landing page intentionally resets it to all knowledge.
    await page.evaluate(() => { appearanceSettings.mode = 'navy'; applyAppearanceSettings({save:false}); newChat(); });
    await openFullGraph(page);
    if (mobile) await settleGraph(page);
    else await page.waitForSelector(viewSelector);
    const truth = page.locator(viewSelector + ' [data-knowledge-node-id="logic_truth"]');
    await truth.click();
    const enlarge = async clicks => {
      if (mobile) await pinchGraph(page, 1.2 ** clicks);
      else for (let i = 0; i < clicks; i++) await page.locator('#knowledgeGraphDesktopZoomIn').click();
    };
    await enlarge(5);
    const viewport = await page.locator(viewSelector).elementHandle();
    const state = () => viewport.evaluate(view => ({
      scale: view._kgScale || Number(view.querySelector('.kg-desktop-zoom-surface').dataset.scale),
      left: view.scrollLeft, top: view.scrollTop
    }));
    await viewport.evaluate(view => { view.scrollLeft = 70; view.scrollTop = 160; });
    const before = await state();
    assert.ok(before.left > 0 && before.top > 0, width + ': test starts with a panned graph');
    const checkPreserved = async label => {
      assert.equal(await viewport.evaluate(view => view.isConnected), true, label + ': graph is not rebuilt');
      assert.deepEqual(await state(), before, label + ': zoom and scroll are preserved');
    };
    for (const type of ['focus', 'pageshow', 'visibilitychange']) {
      await page.evaluate(type => (type === 'visibilitychange' ? document : window).dispatchEvent(new Event(type)), type);
      await checkPreserved(width + '/' + type);
    }
    for (const colorScheme of ['dark', 'light']) {
      await page.emulateMedia({ colorScheme });
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      assert.equal(await page.locator('html').getAttribute('data-appearance-theme'), 'navy');
      await checkPreserved(width + '/OS ' + colorScheme);
    }

    // Open the real lesson link in its popup, substituting only the external page.
    if (mobile) await expandGraphDetails(page);
    const video = page.locator('.kg-video-section a[target="_blank"]').first();
    const href = await video.getAttribute('href');
    await page.context().route(href, route => route.fulfill({ contentType: 'text/html', body: '<title>Lesson</title>' }));
    const popupPromise = page.waitForEvent('popup');
    await video.evaluate(link => link.click());
    const popup = await popupPromise;
    await popup.waitForLoadState('domcontentloaded');
    await popup.close();
    await page.bringToFront();
    await page.evaluate(() => window.dispatchEvent(new Event('focus')));
    await checkPreserved(width + '/video return');

    // A previously unseen category fits once; reopening retains its custom camera.
    await page.evaluate(() => setKnowledgeGraphFilter('命题逻辑'));
    if (mobile) await settleGraph(page);
    else await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.equal(await viewport.evaluate(view => view.isConnected), false, width + ': category rebuilds the graph');
    const fitted = () => page.locator(viewSelector).evaluate(view => ({
      scale: view._kgScale || Number(view.querySelector('.kg-desktop-zoom-surface').dataset.scale),
      left: view.scrollLeft, top: view.scrollTop
    }));
    const categoryFit = await fitted();
    if (!mobile) {
      await page.locator('#knowledgeGraphDesktopZoomFit').click();
      assert.deepEqual(await fitted(), categoryFit, width + ': category is already fitted');
    }
    await enlarge(3);
    await page.locator(viewSelector).evaluate(view => { view.scrollLeft = 40; view.scrollTop = 80; });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const categoryCustom = await fitted();
    await page.evaluate(() => { closeKnowledgeGraph(); openKnowledgeGraph(); });
    if (mobile) await settleGraph(page);
    else await page.waitForSelector(viewSelector);
    if (!mobile) await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.deepEqual(await fitted(), categoryCustom, width + ': reopening restores the category camera');
    if (!mobile) {
      await page.locator('#knowledgeGraphDesktopZoomFit').click();
      assert.deepEqual(await fitted(), categoryFit, width + ': explicit Fit restores the initial category framing');
    }
    console.log('PASS ' + width + ': tab/video/reopen preserve view; unseen categories fit once');
  } finally { await page.close(); }
}

async function checkPanelPresentation(browser, width) {
  const mobile = width <= 760;
  const page = await browser.newPage({ viewport: { width, height: 844 },
    ...(mobile ? { isMobile: true, hasTouch: true } : {}) });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await openFullGraph(page);
    await page.waitForSelector('#knowledgeGraphCanvas .kg-section');
    assert.equal(await page.locator('#knowledgeGraphSummary, #knowledgeGraphModal .graph-summary').count(), 0,
      width + ': remove the whole summary row');

    // Keep this same dialog open while changing language in both directions.
    if (mobile) {
      await page.locator('.kg-mobile-node[data-knowledge-node-id="logic_truth"]').tap();
      await expandGraphDetails(page);
    } else await page.evaluate(() => selectKnowledgeGraphNode('logic_truth'));
    const heading = page.locator('[data-kg-video-heading]');
    await heading.waitFor();
    for (const [language, expected] of [['en', 'Teaching videos'], ['zh-CN', '教学视频']]) {
      await page.evaluate(value => window.DMateI18n.setLanguage(value, false), language);
      await page.waitForFunction(text => document.querySelector('[data-kg-video-heading]')?.textContent === text, expected);
      const exportLabel = language === 'en' ? 'Export as image' : '以图片形式导出';
      assert.equal(await page.locator('#knowledgeGraphCopyBtn').getAttribute('title'), exportLabel);
      assert.equal(await page.locator('#knowledgeGraphCopyBtn').getAttribute('aria-label'), exportLabel);
      assert.equal(await page.locator('#knowledgeGraphModal').evaluate(modal => modal.classList.contains('hidden')), false);
      const styles = await page.evaluate(() => {
        const title = document.querySelector('[data-kg-video-heading]');
        const field = document.querySelector('#knowledgeGraphDetail .graph-detail-field-label:not([data-kg-video-heading])');
        const values = node => {
          const css = getComputedStyle(node);
          return Object.fromEntries(['fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'color'].map(key => [key, css[key]]));
        };
        return { title: values(title), field: values(field) };
      });
      assert.deepEqual(styles.title, styles.field, width + '/' + language + ': video heading matches adjacent field labels');
    }

    if (!mobile) {
      const frameState = () => page.evaluate(() => {
        const frame = document.querySelector('#knowledgeGraphCanvas .kg-section');
        const canvas = document.getElementById('knowledgeGraphCanvas');
        const rect = frame.getBoundingClientRect(), parent = canvas.getBoundingClientRect();
        const css = getComputedStyle(frame);
        const outsideRoundedCorner = (x, y) => !frame.contains(document.elementFromPoint(x, y));
        return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom,
          parentLeft: parent.left, parentRight: parent.right, overflow: css.overflow,
          radii: [css.borderTopLeftRadius, css.borderTopRightRadius, css.borderBottomLeftRadius, css.borderBottomRightRadius].map(parseFloat),
          clippedCorners: [outsideRoundedCorner(rect.left + 1, rect.top + 1),
            outsideRoundedCorner(rect.right - 1, rect.top + 1),
            outsideRoundedCorner(rect.left + 1, rect.bottom - 1),
            outsideRoundedCorner(rect.right - 1, rect.bottom - 1)] };
      });
      const initial = await frameState();
      assert.ok(initial.left >= initial.parentLeft && initial.right <= initial.parentRight + 1,
        width + ': graph frame fits the visible canvas');
      assert.equal(initial.overflow, 'hidden', width + ': frame clips content at its rounded outline');
      assert.ok(initial.radii.every(radius => radius >= 10), width + ': every frame corner is rounded');
      assert.deepEqual(initial.clippedCorners, [true, true, true, true], width + ': hit testing respects all four rounded corners');
      await page.locator('#knowledgeGraphDesktopZoomIn').click({ clickCount: 5 });
      const scroll = await page.locator('.kg-desktop-viewport').evaluate(view => {
        view.scrollLeft = view.scrollWidth;
        view.scrollTop = view.scrollHeight;
        const rect = view.getBoundingClientRect();
        const rightmostNode = Math.max(...[...view.querySelectorAll('.kg-node-group')].map(node => node.getBoundingClientRect().right));
        return { left: view.scrollLeft, top: view.scrollTop, viewLeft: rect.left, right: rect.right, rightmostNode };
      });
      assert.ok(scroll.left > 0, width + ': zoomed graph still scrolls horizontally');
      assert.ok(scroll.rightmostNode <= scroll.right + 1.5, width + ': far-right nodes remain reachable');
      assert.ok(scroll.rightmostNode > scroll.viewLeft, width + ': horizontal scrolling cannot overshoot all graph nodes');
      const zoomed = await frameState();
      for (const edge of ['left', 'right', 'top', 'bottom']) near(zoomed[edge], initial[edge], width + ': scrolling preserves frame ' + edge);
      assert.deepEqual(zoomed.clippedCorners, [true, true, true, true], width + ': zoomed content stays clipped at both right corners');
      await page.locator('#knowledgeGraphDesktopZoomFit').click();
      assert.equal(await page.locator('.kg-desktop-viewport').evaluate(view => view.scrollLeft), 0,
        width + ': Fit resets the internal horizontal scroll');
      // Crossing from a centered small graph into horizontal scrolling must
      // preserve the graph point under the viewport center.
      await page.evaluate(() => {
        setKnowledgeGraphFilter('命题逻辑');
        const view = document.querySelector('.kg-desktop-viewport');
        const stage = view.querySelector('.kg-desktop-zoom-stage');
        setKnowledgeGraphDesktopScale(view.clientWidth * .9 / Number(stage.dataset.baseWidth), false);
        view.scrollLeft = 0;
      });
      const centerPoint = () => page.locator('.kg-desktop-viewport').evaluate(view => {
        const rect = view.getBoundingClientRect(), stage = view.querySelector('.kg-desktop-zoom-stage').getBoundingClientRect();
        const scale = Number(view.querySelector('.kg-desktop-zoom-surface').dataset.scale);
        return (rect.left + view.clientLeft + view.clientWidth / 2 - stage.left) / scale;
      });
      const centered = await centerPoint();
      await page.locator('#knowledgeGraphDesktopZoomIn').click();
      near(await centerPoint(), centered, width + ': centered graph keeps its zoom anchor', .75);
      if (process.env.KG_SCREENSHOT_DIR) {
        await page.evaluate(() => window.DMateI18n.setLanguage('en', false));
        await page.waitForFunction(() => document.querySelector('[data-kg-video-heading]')?.textContent === 'Teaching videos');
        await page.screenshot({ path: process.env.KG_SCREENSHOT_DIR + '/graph-panel-after-' + width + '-en.png' });
      }
    }
    assert.deepEqual(errors, [], width + ': graph presentation page errors');
    console.log('PASS ' + width + ': summary removed, video typography and live language switching' + (mobile ? '' : ', clipped frame and zoomed horizontal scrolling'));
  } finally { await page.close(); }
}

async function mobileCase(browser, width) {
  const page = await browser.newPage({ viewport: { width, height: 844 }, isMobile: true, hasTouch: true });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await openFullGraph(page);
    await settleGraph(page);
    assert.equal(await page.locator('.kg-mobile-entry-only,.kg-mobile-expand,.kg-mobile-zoom-controls,.kg-mobile-zoom-btn,.kg-mobile-zoom-fit,.kg-mobile-zoom-label').count(), 0,
      'Opening the mobile graph immediately displays the touch canvas without view or zoom buttons');
    const categories = await page.locator('#knowledgeGraphCategory option').evaluateAll(options => options.map(option => option.value));
    assert.ok(categories.length > 2, 'Expected real knowledge-graph categories');
    for (const category of categories) {
      const label = width + '/' + category;
      await page.evaluate(value => setKnowledgeGraphFilter(value), category);
      await settleGraph(page);
      const initial = await snapshot(page);
      assert.ok(initial.nodes.count > 0, label + ': category has no nodes');
      assert.ok(initial.scale >= .85 - .001, label + ': automatically fitted labels are too small');
      checkCenteredAxes(initial, label);
      await checkReachableEdges(page, label);
      await pinchGraph(page, 1.25);
      assert.ok((await snapshot(page)).scale > initial.scale, label + ': spreading two fingers enlarges the graph');
      await pinchGraph(page, .8);
      near((await snapshot(page)).scale, initial.scale, label + ': pinching in reverses pinching out', .002);
      console.log('PASS ' + label + ': ' + initial.nodes.count + ' nodes, fit ' + Math.round(initial.scale * 100) + '%');
    }

    // Resize preserves the last touch camera.
    await page.evaluate(() => setKnowledgeGraphFilter('全部'));
    await settleGraph(page);
    await pinchGraph(page, 1.2);
    await page.locator('.kg-mobile-viewport').evaluate(view => {
      view.scrollLeft = (view.scrollWidth - view.clientWidth) / 2;
      view.scrollTop = (view.scrollHeight - view.clientHeight) / 2;
    });
    await settleGraph(page);
    const manual = await snapshot(page);
    const centerPoint = state => ({
      x: (state.content.left + state.content.width / 2 - state.stage.left) / state.scale,
      y: (state.content.top + state.content.height / 2 - state.stage.top) / state.scale
    });
    const alternateWidth = width === 390 ? 620 : 390;
    await page.setViewportSize({ width: alternateWidth, height: 844 });
    await settleGraph(page);
    const resizedManual = await snapshot(page);
    near(resizedManual.scale, manual.scale, width + ': resize preserves manual zoom', .0001);
    near(centerPoint(resizedManual).x, centerPoint(manual).x, width + ': resize preserves horizontal graph center');
    near(centerPoint(resizedManual).y, centerPoint(manual).y, width + ': resize preserves vertical graph center');
    const beforeHeightChange = await snapshot(page);
    await page.setViewportSize({ width, height: 600 });
    await settleGraph(page);
    const retained = await snapshot(page);
    near(retained.scale, beforeHeightChange.scale, width + ': height changes preserve the pinch scale', .0001);
    checkCenteredAxes(retained, width + '/resize');
    await page.setViewportSize({ width, height: 844 });
    await settleGraph(page);
    const originalViewport = await snapshot(page);
    near(originalViewport.scale, beforeHeightChange.scale, width + ': height restoration preserves scale', .0001);
    await page.setViewportSize({ width: 820, height: 844 });
    await page.waitForSelector('.kg-desktop-zoom-stage');
    assert.equal(await page.locator('.kg-mobile-stage').count(), 0, 'Breakpoint must replace the mobile graph');
    await page.setViewportSize({ width, height: 844 });
    await settleGraph(page);
    assert.equal(await page.locator('.kg-desktop-zoom-stage').count(), 0, 'Breakpoint must restore the mobile graph');
    checkCenteredAxes(await snapshot(page), width + '/breakpoint');
    assert.deepEqual(errors, [], width + ': page errors');
    console.log('PASS ' + width + ': resize, manual zoom and fit lifecycle');
  } finally { await page.close(); }
}

async function checkSelectionBorder(browser, theme) {
  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const desktop = await browser.newPage({ viewport: { width: 1024, height: 844 } });
  const errors = [];
  mobile.on('pageerror', error => errors.push(error.message));
  desktop.on('pageerror', error => errors.push(error.message));
  try {
    for (const page of [mobile, desktop]) {
      await page.goto(baseURL, { waitUntil: 'networkidle' });
      await page.evaluate(value => {
        document.documentElement.dataset.appearanceTheme = value;
        document.body.dataset.appearanceTheme = value;
      }, theme);
      await openFullGraph(page);
      await page.waitForSelector('#knowledgeGraphCanvas .kg-section');
      await page.evaluate(() => setKnowledgeGraphFilter('证明与归纳'));
    }
    await settleGraph(mobile);
    const accent = await mobile.evaluate(() => {
      const probe = document.createElement('span');
      probe.style.color = 'var(--accent)';
      document.body.appendChild(probe);
      const color = getComputedStyle(probe).color;
      probe.remove();
      return color;
    });
    const scale = (await snapshot(mobile)).scale;
    const firstName = await mobile.locator('.kg-mobile-node:not(.selected)').first().getAttribute('aria-label');
    const first = mobile.locator('.kg-mobile-stage').getByRole('button', { name: firstName, exact: true });
    await first.tap();
    assert.equal(await mobile.locator('.kg-mobile-node.selected').count(), 1, theme + ': only one node selected');
    assert.equal(await first.evaluate(node => node.classList.contains('selected')), true);
    const secondName = await mobile.locator('.kg-mobile-node:not(.selected)').first().getAttribute('aria-label');
    const second = mobile.locator('.kg-mobile-stage').getByRole('button', { name: secondName, exact: true });
    await second.tap();
    assert.equal(await first.evaluate(node => node.classList.contains('selected')), false, theme + ': previous node deselected');
    assert.equal(await second.evaluate(node => node.classList.contains('selected')), true);
    assert.equal(await mobile.locator('.kg-mobile-node.selected').count(), 1);
    const border = await second.evaluate(node => {
      const style = getComputedStyle(node);
      return { color: style.borderTopColor, width: parseFloat(style.borderTopWidth) };
    });
    assert.equal(border.color, accent, theme + ': tapped node must have a visible accent border');
    assert.ok(border.width >= 3, theme + ': selection border must remain prominent');
    near((await snapshot(mobile)).scale, scale, theme + ': node selection preserves zoom', .0001);
    // The shared focus layer can hide shadows while focused; the selection ring
    // must remain after focus moves away from the selected node.
    await second.evaluate(node => node.blur());
    assert.notEqual(await second.evaluate(node => getComputedStyle(node).boxShadow), 'none', theme + ': selected node ring');
    await desktop.locator('.kg-node-group:not(.selected)').first().click();
    const desktopStroke = await desktop.locator('.kg-node-group.selected rect').evaluate(rect => getComputedStyle(rect).stroke);
    assert.equal(border.color, desktopStroke, theme + ': mobile border matches desktop selection stroke');
    assert.equal(await desktop.locator('#knowledgeGraphModal').getAttribute('data-kg-sheet'), null);
    assert.equal(await desktop.locator('.kg-sheet-handle:visible').count(), 0);
    for (const [page, selector] of [[mobile, '.kg-mobile-edge'], [desktop, '.kg-edge']]) {
      const edge = page.locator('#knowledgeGraphCanvas ' + selector).first();
      const source = await edge.getAttribute('data-from');
      const stroke = () => edge.evaluate(path => {
        const style = getComputedStyle(path);
        return [style.stroke, style.strokeWidth, style.opacity];
      });
      await page.locator('#knowledgeGraphCanvas [data-knowledge-node-id="' + source + '"]').click();
      const selectedStyle = await stroke();
      await page.locator('#knowledgeGraphCanvas [data-knowledge-node-id="proof_direct_contradiction"]').click();
      const plainStyle = await stroke();
      assert.notEqual(plainStyle[0], accent, theme + ': unrelated edges use the normal stroke');
      assert.deepEqual(selectedStyle, plainStyle, theme + ': selection preserves edge color, width and opacity');
    }
    if (process.env.KG_SCREENSHOT_DIR) {
      await mobile.screenshot({ path: process.env.KG_SCREENSHOT_DIR + '/graph-selection-after-390-' + theme + '.png' });
    }
    assert.deepEqual(errors, [], theme + ': selection page errors');
    console.log('PASS ' + theme + ': mobile node taps switch the accent border, matching desktop');
  } finally { await mobile.close(); await desktop.close(); }
}

async function checkNodeGestures(browser, width) {
  const page = await browser.newPage({ viewport: { width, height: 844 }, isMobile: true, hasTouch: true });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await openFullGraph(page);
    await settleGraph(page);
    // Exercise the actual module picker before testing the graph's gesture area.
    await page.locator('#knowledgeGraphCategoryTrigger').tap();
    await page.waitForSelector('#mobileChoiceModal[open]');
    await page.locator('.mobile-choice-option').filter({ hasText: '证明与归纳' }).tap();
    await page.waitForFunction(() => document.getElementById('knowledgeGraphCategory').value === '证明与归纳');
    assert.equal(await page.locator('#mobileChoiceModal').evaluate(modal => modal.open), false);
    await settleGraph(page);
    await page.evaluate(() => {
      const selectNode = selectKnowledgeGraphNode;
      window.graphSelectionCount = 0;
      window.selectKnowledgeGraphNode = (...args) => {
        window.graphSelectionCount++;
        return selectNode(...args);
      };
    });
    const cdp = await page.context().newCDPSession(page);
    const touch = (type, points) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints: points });
    const selectedName = () => page.locator('.kg-mobile-node.selected').getAttribute('aria-label');
    const nodePoint = () => page.evaluate(() => {
      const view = document.querySelector('.kg-mobile-viewport').getBoundingClientRect();
      const node = [...document.querySelectorAll('.kg-mobile-node:not(.selected)')].find(candidate => {
        const rect = candidate.getBoundingClientRect();
        const x = rect.left + rect.width / 2, y = rect.top + rect.height / 2;
        return x > view.left + 8 && x < view.right - 8 && y > view.top + 8 && y < view.bottom - 8
          && candidate.contains(document.elementFromPoint(x, y));
      });
      if (!node) throw new Error('No visible unselected knowledge node');
      const rect = node.getBoundingClientRect();
      return { name: node.getAttribute('aria-label'), x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    });
    const nativeTap = async (point, dx = 0, dy = 0) => {
      const count = await page.evaluate(() => window.graphSelectionCount);
      await touch('touchStart', [{ id: 1, x: point.x, y: point.y }]);
      if (dx || dy) await touch('touchMove', [{ id: 1, x: point.x + dx, y: point.y + dy }]);
      await touch('touchEnd', []);
      await page.waitForFunction(name => document.querySelector('.kg-mobile-node.selected')?.getAttribute('aria-label') === name,
        point.name, { timeout: 2000 });
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
      assert.equal(await page.evaluate(() => window.graphSelectionCount), count + 1,
        width + ': one tap must activate exactly once');
    };
    let point = await nodePoint();
    await page.mouse.click(point.x, point.y);
    assert.equal(await selectedName(), point.name, width + ': mouse click must reach the node');
    assert.equal(await page.evaluate(() => window.graphSelectionCount), 1, width + ': one mouse click must activate once');
    for (const [dx, dy] of [[3, 2], [-4, 0]]) {
      point = await nodePoint();
      const before = await snapshot(page);
      await nativeTap(point, dx, dy);
      const after = await snapshot(page);
      near(after.scroll.left, before.scroll.left, width + ': finger jitter must not pan horizontally', .5);
      near(after.scroll.top, before.scroll.top, width + ': finger jitter must not pan vertically', .5);
    }

    // Enlarge this small module so both tested widths have a real pan range.
    await pinchGraph(page, 1.8);
    point = await nodePoint();
    const beforeDrag = await selectedName();
    const beforeDragCount = await page.evaluate(() => window.graphSelectionCount);
    const oldLeft = (await snapshot(page)).scroll.left;
    await touch('touchStart', [{ id: 1, x: point.x, y: point.y }]);
    await touch('touchMove', [{ id: 1, x: point.x - 24, y: point.y }]);
    await touch('touchEnd', []);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
    assert.equal(await selectedName(), beforeDrag, width + ': dragging must not select the pressed node');
    assert.equal(await page.evaluate(() => window.graphSelectionCount), beforeDragCount, width + ': drag must not activate a node');
    assert.ok((await snapshot(page)).scroll.left > oldLeft, width + ': horizontal drag must pan the graph');
    await nativeTap(await nodePoint()); // A new tap must work without a cooldown after dragging.

    await pinchGraph(page, .75);
    const beforePinch = (await snapshot(page)).scale;
    const beforePinchCount = await page.evaluate(() => window.graphSelectionCount);
    const center = await page.locator('.kg-mobile-viewport').evaluate(view => {
      const rect = view.getBoundingClientRect();
      return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    });
    await touch('touchStart', [{ id: 1, x: center.x - 30, y: center.y }, { id: 2, x: center.x + 30, y: center.y }]);
    await touch('touchMove', [{ id: 1, x: center.x - 45, y: center.y }, { id: 2, x: center.x + 45, y: center.y }]);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
    await touch('touchEnd', []);
    assert.ok((await snapshot(page)).scale > beforePinch, width + ': native pinch must zoom');
    assert.equal(await page.evaluate(() => window.graphSelectionCount), beforePinchCount, width + ': pinch must not activate a node');
    await nativeTap(await nodePoint()); // Pinch suppression must not swallow the next distinct tap.
    assert.deepEqual(errors, [], width + ': gesture page errors');
    console.log('PASS ' + width + ': module picker, mouse click, touch jitter, drag and pinch followed by fresh taps');
  } finally { await page.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    // Hiding native bars masks the client-size changes that used to restore
    // an old fitted camera after each zoom and cause repeated flashing.
    ignoreDefaultArgs:['--hide-scrollbars'],
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    const desktopRanks = await checkZoomLimits(browser, 1440);
    const mobileRanks = await checkZoomLimits(browser, 390);
    assert.ok(desktopRanks?.length > 1, 'The reference graph contains multiple prerequisite levels');
    assert.deepEqual(mobileRanks, desktopRanks, 'Mobile rows preserve the nodes and order of each desktop column');
    for (const width of [1440, 390]) await checkReturnPreservesView(browser, width);
    for (const width of [1440, 820, 390]) await checkPanelPresentation(browser, width);
    for (const width of [390, 620]) await checkNodeGestures(browser, width);
    for (const theme of ['dark', 'navy']) await checkSelectionBorder(browser, theme);
    for (const width of [390, 620]) await mobileCase(browser, width);
    const page = await browser.newPage({ viewport: { width: 820, height: 844 } });
    try {
      await page.goto(baseURL, { waitUntil: 'networkidle' });
      await openFullGraph(page);
      await page.waitForSelector('.kg-desktop-zoom-stage');
      assert.equal(await page.locator('.kg-mobile-stage').count(), 0);
      assert.ok(await page.locator('.kg-node-group').count() > 20);
      await page.locator('#knowledgeGraphDesktopZoomFit').click();
      assert.ok(await page.locator('.kg-desktop-zoom-stage').isVisible());
      console.log('PASS 820: desktop graph branch');
    } finally { await page.close(); }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
