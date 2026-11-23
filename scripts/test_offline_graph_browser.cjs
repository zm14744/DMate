/* Real online/offline graph parity and disconnected-browser interaction.
 * No model endpoints are called. Start the Flask app before running this file.
 */
'use strict';
const assert = require('node:assert/strict');
const { revealInterface } = require('./offline-vault-browser-fixtures.cjs');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const mobile = page => page.viewportSize().width <= 760;
const frame = page => page.locator('#knowledgeGraphModal');
const nodes = page => frame(page).locator(mobile(page) ? '.kg-mobile-node' : '.kg-node-group');
const view = page => frame(page).locator(mobile(page) ? '.kg-mobile-viewport' : '.kg-desktop-viewport');
const zoom = (page, action) => mobile(page)
  ? action === 'fit' ? frame(page).locator('.kg-mobile-zoom-fit')
    : frame(page).locator('.kg-mobile-zoom-btn').nth(action === 'in' ? 1 : 0)
  : frame(page).locator('#knowledgeGraphDesktopZoom' + ({ in: 'In', out: 'Out', fit: 'Fit' }[action]));
const near = (actual, expected, label, tolerance = 1.5) => assert.ok(Math.abs(actual - expected) <= tolerance,
  label + ': ' + actual + ' vs ' + expected);
const settle = page => page.evaluate(async () => {
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  await Promise.all([...document.getAnimations()].filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity)
    .map(animation => animation.finished.catch(() => {})));
});

async function removeOnlineOnly(page) {
  await page.evaluate(() => {
    document.querySelectorAll('#knowledgeGraphFocusBtn,#knowledgeGraphScopeBtn,#knowledgeGraphHistoryBtn,#knowledgeGraphHistoryTab,#knowledgeGraphHistoryWrap,'
      + '#knowledgeGraphLegendRelated,.graph-legend,.kg-video-section,.graph-side-tabs').forEach(node => node.remove());
  });
}

async function category(page, name) {
  const option = await frame(page).locator('#knowledgeGraphCategory').evaluate((select, name) => {
    const option = [...select.options].find(option => option.value === name || option.label === name);
    return option && { value: option.value, label: option.label };
  }, name);
  assert.ok(option, 'The requested canonical module or display label exists: ' + name);
  if (mobile(page)) {
    if (await view(page).count()) await frame(page).locator('.kg-mobile-expand').click();
    await frame(page).locator('#knowledgeGraphCategoryTrigger').click();
    await page.locator('#mobileChoiceModal').getByRole('radio', { name: option.label, exact: true }).click();
  } else await frame(page).locator('#knowledgeGraphCategory').selectOption(option.value);
  await settle(page);
}

async function fullGraph(page) {
  if (mobile(page)) {
    // A viewport resize can return before its media-query renderer runs.
    // Wait for that renderer, then avoid clicking an already restored exit.
    await frame(page).locator('.kg-mobile-section').waitFor({ state: 'attached' });
    if (!await frame(page).evaluate(root => root.classList.contains('graph-fullscreen-view'))) {
      await frame(page).locator('.kg-mobile-expand').click();
    }
  }
  await view(page).waitFor();
  await page.waitForFunction(() => {
    const element = document.querySelector('.kg-mobile-viewport');
    return !element || (element._kgScale > 0 && getComputedStyle(element).visibility !== 'hidden');
  });
  await settle(page);
}

async function scale(page) {
  return view(page).evaluate(node => node._kgScale || Number(node.dataset.scale)
    || Number(node.querySelector('.kg-desktop-zoom-surface')?.dataset.scale));
}

async function visual(page, size) {
  await page.mouse.move(0, 0);
  return frame(page).locator('.graph-modal-card').evaluate(async (card, size) => {
    const original = card.getAttribute('style');
    // Offline learning links add content below the common graph fields.
    // Exclude their space for comparison, then restore the actual controls.
    const concept = card.querySelector('.offline-graph-learning-links');
    const conceptParent = concept?.parentElement, conceptNext = concept?.nextSibling;
    concept?.remove();
    // Only the online dialog has a close button beside the shared copy action.
    const close = card.querySelector('#knowledgeGraphClose');
    const closeParent = close?.parentElement, closeNext = close?.nextSibling;
    close?.remove();
    if (size) {
      card.style.setProperty('width', size.width + 'px', 'important');
      card.style.setProperty('height', size.height + 'px', 'important');
      card.style.setProperty('max-width', 'none', 'important');
      card.style.setProperty('max-height', 'none', 'important');
      card.style.setProperty('min-width', '0', 'important');
      card.style.setProperty('min-height', '0', 'important');
    }
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await Promise.all(card.getAnimations({ subtree: true }).map(animation => animation.finished.catch(() => {})));
    const origin = card.getBoundingClientRect(), result = {};
    for (const selector of ['.graph-toolbar', '.graph-toolbar-left',
      '#knowledgeGraphCopyBtn', '.knowledge-graph-layout', '.knowledge-graph-main',
      '.knowledge-graph-canvas', '.kg-section', '.knowledge-graph-side',
      '.graph-detail-title', '.graph-detail-body']) {
      const node = selector === ':scope' ? card : card.querySelector(selector);
      if (!node) throw new Error('Missing graph comparison node: ' + selector);
      const rect = node.getBoundingClientRect(), css = getComputedStyle(node);
      result[selector] = { rect: [rect.x - origin.x, rect.y - origin.y, rect.width, rect.height],
        style: Object.fromEntries(['display', 'fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'color',
          'backgroundColor', 'borderTopWidth', 'borderTopColor', 'borderTopStyle', 'borderRadius',
          'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'gap'].map(key => [key, css[key]])) };
    }
    if (size) {
      if (original === null) card.removeAttribute('style'); else card.setAttribute('style', original);
    }
    if (concept) conceptParent.insertBefore(concept, conceptNext);
    if (close) closeParent.insertBefore(close, closeNext);
    return { size: { width: origin.width, height: origin.height }, blocks: result };
  }, size || null);
}

async function topology(page) {
  return frame(page).locator('#knowledgeGraphCanvas').evaluate(canvas => {
    const mobile = Boolean(canvas.querySelector('.kg-mobile-stage'));
    const stage = canvas.querySelector(mobile ? '.kg-mobile-stage' : '.kg-svg');
    const nodeList = [...canvas.querySelectorAll(mobile ? '.kg-mobile-node' : '.kg-node-group')];
    const properties = node => {
      const css = getComputedStyle(node);
      return Object.fromEntries(['fontFamily', 'fontSize', 'fontWeight', 'color', 'fill', 'backgroundColor',
        'borderTopWidth', 'borderTopColor', 'borderRadius'].map(key => [key, css[key]]));
    };
    return { stage: mobile ? [stage.style.width, stage.style.height] : stage.getAttribute('viewBox'),
      nodes: nodeList.map(node => mobile ? { name: node.getAttribute('aria-label'),
        box: ['left', 'top', 'width', 'height'].map(key => node.style[key]), style: properties(node),
        label: properties(node.querySelector('.kg-mobile-node-name')) }
        : { name: node.querySelector('.kg-node-label').textContent, transform: node.getAttribute('transform'),
          rect: ['width', 'height', 'rx', 'fill', 'stroke', 'stroke-width'].map(key => node.querySelector('rect').getAttribute(key)),
          label: properties(node.querySelector('.kg-node-label')) }),
      paths: [...canvas.querySelectorAll(mobile ? '.kg-mobile-edge' : '.kg-edge')].map(node => node.getAttribute('d')) };
  });
}

async function selectFirst(page) {
  const node = nodes(page).first();
  await node.scrollIntoViewIfNeeded();
  await node.click();
  await settle(page);
  assert.equal(await frame(page).locator(mobile(page) ? '.kg-mobile-node.selected' : '.kg-node-group.selected').count(), 1);
  const selection = await node.evaluate(node => {
    const marker = node.matches('.kg-mobile-node') ? node : node.querySelector('rect');
    const css = getComputedStyle(marker), probe = document.createElement('span');
    probe.style.color = 'var(--accent)'; document.body.append(probe);
    const accent = getComputedStyle(probe).color; probe.remove();
    return { color: node.matches('.kg-mobile-node') ? css.borderTopColor : css.stroke,
      width: parseFloat(node.matches('.kg-mobile-node') ? css.borderTopWidth : css.strokeWidth), accent };
  });
  assert.equal(selection.color, selection.accent, 'Selected node has the shared accent outline');
  assert.ok(selection.width >= 3, 'Selected outline remains visible');
  return frame(page).locator('#knowledgeGraphDetail').evaluate(detail =>
    [...detail.querySelectorAll('.graph-detail-field')].filter(field => !field.closest('.kg-video-section'))
      .map(field => ({ label: field.querySelector('.graph-detail-field-label').textContent.trim(),
        terms: [...field.querySelectorAll('.graph-detail-term')].map(term => term.textContent.trim()),
        value: field.querySelector('.graph-detail-field-value').textContent.trim() })));
}

async function checkFocusedFrame(node, label, keyboard = false) {
  const appearance = await node.evaluate(node => {
    const mobile = node.matches('.kg-mobile-node'), marker = mobile ? node : node.querySelector('rect');
    const css = getComputedStyle(marker), probe = document.createElement('span');
    probe.style.color = 'var(--accent)'; document.body.append(probe);
    const accent = getComputedStyle(probe).color; probe.remove();
    return { focused: document.activeElement === node, focusVisible: node.matches(':focus-visible'),
      frames: [...new Set([node, marker])].map(element => {
        const style = getComputedStyle(element);
        return { element: element.tagName, outlineStyle: style.outlineStyle };
      }), color: mobile ? css.borderTopColor : css.stroke,
      width: parseFloat(mobile ? css.borderTopWidth : css.strokeWidth),
      radius: mobile ? parseFloat(css.borderTopLeftRadius) : marker.rx.baseVal.value, accent };
  });
  assert.equal(appearance.focused, true, label + ': node has actual browser focus');
  if (keyboard) assert.equal(appearance.focusVisible, true, label + ': Tab makes keyboard focus visible');
  for (const frame of appearance.frames) {
    assert.equal(frame.outlineStyle, 'none', label + ': focused ' + frame.element + ' has no rectangular outer outline');
  }
  assert.equal(appearance.color, appearance.accent, label + ': focus uses the shared accent border');
  assert.ok(appearance.width >= 3, label + ': focus remains visible');
  assert.ok(appearance.radius > 0, label + ': focus follows the rounded node border');
}

async function onlineReference(browser, width, theme, available) {
  const context = await browser.newContext({ viewport: { width, height: 900 },
    isMobile: width < 761, hasTouch: width < 761, serviceWorkers: 'block' });
  const page = await context.newPage();
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await page.evaluate(value => {
      appearanceSettings = {...APPEARANCE_DEFAULTS, mode:value};
      applyAppearanceSettings({save:true});
      DMateI18n.setLanguage('zh-CN', false);
      openKnowledgeGraph();
    }, theme);
    assert.equal(await page.locator('body').getAttribute('data-appearance-theme'), theme);
    await page.waitForFunction(() => knowledgeGraphInitialized);
    await page.evaluate(() => selectKnowledgeGraphDisplayMode('full'));
    await frame(page).locator('.kg-section').waitFor();
    await removeOnlineOnly(page);
    await settle(page);
    const initial = await visual(page, available), categories = await frame(page).locator('#knowledgeGraphCategory option').allTextContents();
    assert.equal(categories[0], '全部模块', 'The all-module option has the explicit browsing label');
    if (process.env.OFFLINE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/online-graph-' + width + '-' + theme + '.png' });
    const expected = {};
    await fullGraph(page);
    for (const name of categories) {
      await category(page, name);
      await fullGraph(page);
      await removeOnlineOnly(page);
      expected[name] = { topology: await topology(page), details: await selectFirst(page) };
      await removeOnlineOnly(page);
    }
    if (mobile(page) && process.env.OFFLINE_SCREENSHOT_DIR) {
      await category(page, '初等数论');
      await fullGraph(page);
      await selectFirst(page);
      await removeOnlineOnly(page);
      await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/online-graph-full-' + width + '-' + theme + '.png' });
    }
    return { initial, categories, expected };
  } finally { await context.close(); }
}

async function disconnectWorkerNetwork(browser, page) {
  // Playwright context.setOffline does not consistently disconnect a worker's
  // independent network target. Verify a failed fetch inside that target too.
  const protocol = await browser.newBrowserCDPSession();
  const pageProtocol = await page.context().newCDPSession(page);
  const { targetInfo } = await pageProtocol.send('Target.getTargetInfo');
  await pageProtocol.detach();
  const workerURL = await page.evaluate(() => navigator.serviceWorker.controller.scriptURL);
  const target = (await protocol.send('Target.getTargets')).targetInfos.find(info => info.type === 'service_worker'
    && info.url === workerURL && info.browserContextId === targetInfo.browserContextId);
  assert.ok(target, 'The offline worker has a real browser target');
  const { sessionId } = await protocol.send('Target.attachToTarget', { targetId: target.targetId, flatten: false });
  let serial = 0;
  const send = async (method, params = {}) => {
    const id = ++serial;
    let listener;
    const response = new Promise((resolve, reject) => {
      listener = event => {
        if (event.sessionId !== sessionId) return;
        const result = JSON.parse(event.message);
        if (result.id !== id) return;
        if (result.error) reject(new Error(result.error.message)); else resolve(result.result);
      };
      protocol.on('Target.receivedMessageFromTarget', listener);
    });
    try {
      await protocol.send('Target.sendMessageToTarget', { sessionId, message: JSON.stringify({ id, method, params }) });
      return await response;
    } finally { protocol.off('Target.receivedMessageFromTarget', listener); }
  };
  await send('Network.enable');
  await send('Network.emulateNetworkConditions', { offline: true, latency: 0, downloadThroughput: 0, uploadThroughput: 0 });
  const probe = await send('Runtime.evaluate', { expression: "fetch('/offline-graph-network-probe',{cache:'no-store'}).then(()=>false,()=>true)",
    awaitPromise: true, returnByValue: true });
  assert.equal(probe.result.value, true, 'Service worker networking is actually unavailable');
  return protocol;
}

async function openOfflineGraph(page) {
  await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
  await revealInterface(page);
  const toggle = page.locator(page.viewportSize().width <= 1100 ? '#offlineNavToggle' : '#offlineDesktopSidebarOpen');
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
  await page.locator('.offline-nav-item[data-panel="graph"]').click();
  await frame(page).locator('.kg-section').waitFor();
}

async function inlineLayout(page) {
  const state = await frame(page).evaluate(root => {
    const main = document.getElementById('offlineMain'), sidebar = document.getElementById('offlineSidebar');
    const box = element => {
      const rect = element.getBoundingClientRect();
      return { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height };
    };
    return { parent: root.parentElement.id, insideMain: main.contains(root), modal: root.classList.contains('modal'),
      fullscreen: root.classList.contains('graph-fullscreen-view'), close: root.querySelector('#knowledgeGraphClose') !== null,
      position: getComputedStyle(root).position, background: getComputedStyle(root).backgroundColor,
      root: box(root), main: box(main), sidebar: box(sidebar), documentWidth: document.documentElement.scrollWidth,
      viewportWidth: innerWidth, portalMarkers: [...document.getElementById('graphPanel').childNodes]
        .filter(node => node.nodeType === Node.COMMENT_NODE && node.textContent.includes('fullscreen origin')).length };
  });
  assert.equal(state.parent, 'graphPanel');
  assert.equal(state.insideMain, true, 'The normal graph belongs to the main content area');
  assert.equal(state.modal, false, 'The embedded graph has no modal overlay');
  assert.equal(state.fullscreen, false);
  assert.equal(state.close, false, 'The embedded tool does not acquire a modal close dot');
  assert.equal(state.position, 'relative');
  assert.equal(state.background, 'rgba(0, 0, 0, 0)', 'The inline host has no backdrop');
  assert.equal(state.portalMarkers, 0, 'Exited full view leaves no portal placeholder');
  assert.ok(state.root.left >= state.main.left - 1 && state.root.right <= state.main.right + 1
    && state.root.top >= state.main.top - 1 && state.root.bottom <= state.main.bottom + 1,
  'The graph fits the main content bounds: ' + JSON.stringify(state));
  assert.ok(state.root.width > 250 && state.root.height > 300, 'The main area provides a usable embedded graph');
  assert.ok(state.documentWidth <= state.viewportWidth + 1, 'The graph does not overflow the page horizontally');
  if (page.viewportSize().width > 1100) assert.ok(state.root.left >= state.sidebar.right - 1,
    'The graph does not cover the desktop sidebar');
}

async function inlineLifecycle(page) {
  await inlineLayout(page);
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('.offline-nav-item.active').getAttribute('data-panel'), 'graph',
    'Escape in the ordinary inline tool does not switch modules');
  const switchPanel = async panel => {
    const toggle = page.locator(page.viewportSize().width <= 1100 ? '#offlineNavToggle' : '#offlineDesktopSidebarOpen');
    if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
    await page.locator('.offline-nav-item[data-panel="' + panel + '"]').click();
    await page.locator('#' + panel + 'Panel').waitFor({ state: 'visible' });
  };
  await switchPanel('concepts'); // Real navigation remains clickable beside an inline graph.
  await openOfflineGraph(page);
  await inlineLayout(page);
  if (!mobile(page)) return;
  for (const exit of ['button', 'Escape']) {
    await fullGraph(page);
    assert.equal(await frame(page).evaluate(root => root.parentElement === document.body), true,
      'Only mobile full view is portalled to the body');
    if (exit === 'button') await frame(page).locator('.kg-mobile-expand').click();
    else await page.keyboard.press('Escape');
    await settle(page);
    await inlineLayout(page);
    assert.equal(await frame(page).locator('.kg-mobile-entry-only').count(), 1);
  }
  await fullGraph(page);
  await page.setViewportSize({ width: 820, height: 900 });
  await frame(page).locator('.kg-node-group').first().waitFor();
  await settle(page);
  await inlineLayout(page);
  await page.setViewportSize({ width: 390, height: 900 });
  await fullGraph(page);
  assert.equal(await frame(page).evaluate(root => root.classList.contains('graph-fullscreen-view')
    && root.parentElement === document.body), true, 'Returning to mobile restores its prior full-view layout');
  // Exercise the real navigation handler during full view, as an application
  // navigation can occur while its sidebar button is intentionally covered.
  await page.locator('.offline-nav-item[data-panel="concepts"]').evaluate(button => button.click());
  await page.locator('#conceptsPanel').waitFor({ state: 'visible' });
  assert.equal(await frame(page).isVisible(), false, 'Switching modules removes the portalled full-view surface');
  assert.equal(await frame(page).evaluate(root => root.parentElement.id), 'graphPanel');
  await openOfflineGraph(page);
  await inlineLayout(page);
  assert.equal(await page.locator('#knowledgeGraphModal').count(), 1, 'Repeated portal lifecycles keep one graph instance');
}

async function checkClampedZoom(page) {
  for (const action of ['in', 'out']) {
    const button = zoom(page, action);
    // Reach both bounds through the disconnected tool's real controls.
    for (let repeat = 0; repeat < 45; repeat++) await button.evaluate(node => node.click());
    await settle(page);
    await page.evaluate(() => new Promise(resolve => {
      let frames = 6; const tick = () => --frames ? requestAnimationFrame(tick) : resolve();
      requestAnimationFrame(tick);
    }));
    const result = await button.evaluate(async button => {
      const root = document.getElementById('knowledgeGraphModal');
      const view = root.querySelector('.kg-mobile-viewport,.kg-desktop-viewport');
      const surface = view.querySelector('.kg-mobile-zoom-surface,.kg-desktop-zoom-surface');
      const stage = surface.querySelector('.kg-mobile-stage,.kg-desktop-zoom-stage');
      const label = root.querySelector('.kg-mobile-zoom-label,#knowledgeGraphDesktopZoomLabel');
      const capture = () => {
        const rect = stage.getBoundingClientRect();
        return {scale:view._kgScale || Number(surface.dataset.scale),label:label.textContent,
          visible:getComputedStyle(view).visibility,
          rect:[rect.x,rect.y,rect.width,rect.height],scroll:[view.scrollLeft,view.scrollTop],
          dimensions:[view.clientWidth,view.clientHeight,surface.clientWidth,surface.clientHeight]};
      };
      const before = capture(), samples = []; let mutations = 0;
      const observer = new MutationObserver(records => { mutations += records.length; });
      observer.observe(view,{attributes:true,attributeFilter:['style','data-scale','data-kg-ready'],subtree:true,childList:true,characterData:true});
      observer.observe(label,{subtree:true,childList:true,characterData:true});
      for (let frame = 0; frame < 12; frame++) {
        if (frame < 6) button.click();
        await new Promise(resolve => requestAnimationFrame(resolve));
        samples.push(capture());
      }
      observer.disconnect();
      return {before,samples,mutations};
    });
    const limit = action === 'out' ? (mobile(page) ? .65 : .8) : (mobile(page) ? 3 : 2.5);
    near(result.before.scale, limit, 'Offline '+action+' reaches its zoom clamp', .000001);
    assert.equal(result.mutations,0,'Offline '+action+' at its clamp causes no graph or label rewrites');
    assert.equal(result.before.visible,'visible','The disconnected graph remains visible at its limit');
    for (const sample of result.samples) assert.deepEqual(sample,result.before,
      'Every disconnected '+action+' clamp frame retains the camera and geometry');
  }
  await zoom(page,'fit').click();
  await settle(page);
}

async function gestures(page) {
  await category(page, '证明与归纳');
  await fullGraph(page);
  await zoom(page, 'fit').click();
  const fitted = await scale(page);
  await zoom(page, 'in').click();
  assert.ok(await scale(page) > fitted, 'Zoom-in changes the actual graph scale');
  await zoom(page, 'fit').click();
  near(await scale(page), fitted, 'Fit restores the category scale', .001);
  await checkClampedZoom(page);
  for (let i = 0; i < 5; i++) await zoom(page, 'in').click();
  await view(page).evaluate(node => { node.scrollLeft = 0; node.scrollTop = 0; });
  const before = await view(page).evaluate(node => ({ x: node.scrollLeft, y: node.scrollTop, max: node.scrollWidth - node.clientWidth }));
  assert.ok(before.max > 30, 'The zoomed chart has a meaningful horizontal pan range');
  const rect = await view(page).boundingBox(), x = rect.x + rect.width * .7, y = rect.y + rect.height * .65;
  if (mobile(page)) {
    const cdp = await page.context().newCDPSession(page);
    const touch = (type, touchPoints) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints });
    await touch('touchStart', [{ id: 1, x, y }]);
    await touch('touchMove', [{ id: 1, x: x - 40, y }]);
    await touch('touchEnd', []);
    assert.ok(await view(page).evaluate(node => node.scrollLeft) > before.x, 'A real finger drag pans the graph');
    const initial = await scale(page), center = rect.x + rect.width / 2;
    await touch('touchStart', [{ id: 1, x: center - 30, y }, { id: 2, x: center + 30, y }]);
    await touch('touchMove', [{ id: 1, x: center - 48, y }, { id: 2, x: center + 48, y }]);
    await touch('touchEnd', []);
    assert.ok(await scale(page) > initial, 'A real two-finger pinch zooms the graph');
    await cdp.detach();
  } else {
    await page.mouse.move(x, y);
    await page.mouse.wheel(80, 0);
    await page.waitForFunction(() => document.querySelector('.kg-desktop-viewport').scrollLeft > 0);
    const corners = await frame(page).locator('.kg-section').evaluate(node => {
      const rect = node.getBoundingClientRect(), css = getComputedStyle(node);
      return { overflow: css.overflow, radius: parseFloat(css.borderTopRightRadius), clipped:
        [[rect.left + 1, rect.top + 1], [rect.right - 1, rect.top + 1],
          [rect.left + 1, rect.bottom - 1], [rect.right - 1, rect.bottom - 1]]
          .map(([x, y]) => !node.contains(document.elementFromPoint(x, y))) };
    });
    assert.equal(corners.overflow, 'hidden');
    assert.ok(corners.radius >= 10);
    assert.deepEqual(corners.clipped, [true, true, true, true], 'Zoomed graph respects all four rounded corners');
  }
  const edges = await view(page).evaluate(view => {
    view.scrollLeft = view.scrollWidth; view.scrollTop = view.scrollHeight;
    const rect = view.getBoundingClientRect();
    const nodes = [...view.querySelectorAll('.kg-mobile-node,.kg-node-group')].map(node => node.getBoundingClientRect());
    return { right: Math.max(...nodes.map(node => node.right)), bottom: Math.max(...nodes.map(node => node.bottom)),
      viewRight: rect.right, viewBottom: rect.bottom };
  });
  assert.ok(edges.right <= edges.viewRight + 2 && edges.bottom <= edges.viewBottom + 2,
    'Scrolling reaches the farthest nodes without clipping: ' + JSON.stringify(edges));
  await zoom(page, 'fit').click();
  await selectFirst(page); // Gestures must not swallow the next independent selection.
}

async function liveLanguage(page) {
  await category(page, '初等数论');
  await fullGraph(page);
  await selectFirst(page);
  if (mobile(page)) await frame(page).locator('.kg-mobile-expand').click();
  const original = await frame(page).elementHandle();
  for (const language of ['en', 'zh-CN']) {
    await page.evaluate(value => DMateI18n.setLanguage(value, false), language);
    await page.waitForFunction(() => {
      const labels = document.querySelectorAll('#knowledgeGraphDetail .graph-detail-field-label');
      return labels[0]?.textContent.trim() === DMateI18n.t('前置知识')
        && labels[1]?.textContent.trim() === DMateI18n.t('后续知识');
    });
    const text = await frame(page).evaluate(root => ({
      category: root.querySelector('#knowledgeGraphCategory option[value="初等数论"]').textContent.trim(),
      expectedCategory: DMateKnowledgeLanguage.label('初等数论'),
      fields: [...root.querySelectorAll('.graph-detail-field-label')].slice(0, 2).map(field => field.textContent.trim()),
      expectedFields: ['前置知识', '后续知识'].map(label => DMateI18n.t(label)),
      language: DMateI18n.getLanguage(), visible: !root.classList.contains('hidden') }));
    assert.equal(text.category, text.expectedCategory, 'The existing module selector changes language immediately');
    assert.deepEqual(text.fields, text.expectedFields, 'The existing node details change language immediately');
    assert.equal(text.language, language);
    assert.equal(text.visible, true);
    assert.equal(await original.evaluate(node => node === document.getElementById('knowledgeGraphModal')), true,
      'Language switching keeps the same graph modal mounted');
  }
  await original.dispose();
}

async function png(page) {
  // Exercise the real PNG rasterizer and local download fallback; no system
  // clipboard is modified by this browser regression.
  await page.evaluate(() => Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined }));
  if (mobile(page) && await view(page).count()) await frame(page).locator('.kg-mobile-expand').click();
  const downloading = page.waitForEvent('download');
  await frame(page).locator('#knowledgeGraphCopyBtn').click();
  const download = await downloading, chunks = [];
  for await (const chunk of await download.createReadStream()) chunks.push(chunk);
  const bytes = Buffer.concat(chunks);
  assert.match(download.suggestedFilename(), /\.png$/);
  assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  assert.ok(bytes.readUInt32BE(16) > 64 && bytes.readUInt32BE(20) > 64, 'Graph export contains a useful raster image');
  assert.equal(await download.failure(), null);
}

async function relationNavigation(page) {
  const selected = id => frame(page).locator('[data-node-id="' + id + '"].selected');
  const assertDestination = async (id, name, module) => {
    await page.waitForFunction(({id, name, module}) => {
      const host = document.getElementById('knowledgeGraphModal');
      const node = host.querySelector('[data-node-id="' + id + '"].selected');
      const viewport = host.querySelector('.kg-mobile-viewport,.kg-desktop-viewport');
      if (!node || !viewport || host.querySelector('#knowledgeGraphCategory').value !== module
        || host.querySelector('#knowledgeGraphDetailTitle').textContent !== DMateI18n.t(name)) return false;
      const box = node.getBoundingClientRect(), view = viewport.getBoundingClientRect();
      return document.activeElement === node
        && box.right > view.left && box.left < view.right && box.bottom > view.top && box.top < view.bottom;
    }, {id, name, module});
    assert.equal(await selected(id).count(), 1, 'A relation selects its canonical destination node');
    assert.equal(await selected(id).evaluate(node => document.activeElement === node), true,
      'Relation navigation moves keyboard focus to the visible destination');
    await checkFocusedFrame(selected(id), 'Relation destination ' + id);
  };

  await category(page, '全部');
  await fullGraph(page);
  await frame(page).locator('[data-node-id="logic_reasoning"]').scrollIntoViewIfNeeded();
  await frame(page).locator('[data-node-id="logic_reasoning"]').click();
  if (mobile(page)) await frame(page).locator('.kg-mobile-expand').click();
  const successor = frame(page).locator('#knowledgeGraphDetail button.graph-detail-term[data-graph-node-id="proof_induction"]');
  await successor.click();
  await assertDestination('proof_induction', '数学归纳法', '证明与归纳');

  await page.evaluate(() => DMateI18n.setLanguage('en', false));
  await category(page, '全部');
  if (!mobile(page)) await fullGraph(page);
  const prerequisite = frame(page).locator('#knowledgeGraphDetail button.graph-detail-term[data-graph-node-id="logic_reasoning"]');
  await prerequisite.focus();
  await prerequisite.press('Enter');
  await assertDestination('logic_reasoning', '命题推理', '命题逻辑');
  if (!mobile(page)) {
    await zoom(page, 'in').click();
    const target = frame(page).locator('[data-node-id="logic_equivalence"]');
    await target.scrollIntoViewIfNeeded();
    await settle(page);
    const previousNode = await target.elementHandle(), previousView = await view(page).elementHandle();
    const before = await view(page).evaluate(node => ({x:node.scrollLeft, y:node.scrollTop}));
    const previousScale = await scale(page);
    await frame(page).locator('#knowledgeGraphDetail button.graph-detail-term[data-graph-node-id="logic_equivalence"]').click();
    await assertDestination('logic_equivalence', '逻辑等价', '命题逻辑');
    assert.equal(await target.evaluate((node, previous) => node === previous, previousNode), true,
      'A same-module relation reuses the existing canvas node');
    assert.equal(await view(page).evaluate((node, previous) => node === previous, previousView), true,
      'A same-module relation reuses the existing viewport');
    near(await scale(page), previousScale, 'A same-module relation preserves zoom', .001);
    const after = await view(page).evaluate(node => ({x:node.scrollLeft, y:node.scrollTop}));
    near(after.x, before.x, 'An already visible relation preserves horizontal camera', 1);
    near(after.y, before.y, 'An already visible relation preserves vertical camera', 1);
    await previousNode.dispose(); await previousView.dispose();

    // Keyboard focus must remain visible on a node that has not been selected,
    // using its rounded stroke rather than the SVG group's rectangular outline.
    const preceding = await nodes(page).evaluateAll(list => list.findIndex((node, index) =>
      index + 1 < list.length && !list[index + 1].classList.contains('selected')));
    assert.ok(preceding >= 0, 'The module has an unselected node to visit by keyboard');
    await nodes(page).nth(preceding).focus();
    await page.keyboard.press('Tab');
    const focused = nodes(page).nth(preceding + 1);
    await checkFocusedFrame(focused, 'Unselected keyboard destination', true);
    assert.equal(await focused.evaluate(node => node.classList.contains('selected')), false,
      'Keyboard focus does not change the selected knowledge node');
    assert.equal(await selected('logic_equivalence').count(), 1,
      'The original selected node retains its accent border while another node is focused');
  }
  await page.evaluate(() => DMateI18n.setLanguage('zh-CN', false));
  if (mobile(page)) {
    await category(page, '全部');
    assert.equal(await view(page).count(), 0, 'The inline mobile graph shows its entry rather than a canvas');
    await frame(page).locator('#knowledgeGraphDetail button.graph-detail-term[data-graph-node-id="proof_induction"]').click();
    await assertDestination('proof_induction', '数学归纳法', '证明与归纳');
    assert.equal(await frame(page).evaluate(root => root.classList.contains('graph-fullscreen-view')), true,
      'A mobile inline relation opens the full graph to reveal its destination');
  }
}

async function runCase(browser, width, theme) {
  const label = width + '/' + theme;
  const context = await browser.newContext({ viewport: { width, height: 900 },
    isMobile: width <= 760, hasTouch: width <= 760, serviceWorkers: 'allow' });
  const page = await context.newPage(), errors = [], failures = [], api = [];
  let protocol;
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await page.evaluate(async () => {
      await navigator.serviceWorker.register('/offline-service-worker.js', { scope: '/' });
      const registration = await navigator.serviceWorker.ready, worker = registration.active;
      if (worker.state !== 'activated') await new Promise(resolve => worker.addEventListener('statechange', () => {
        if (worker.state === 'activated') resolve();
      }));
    });
    await page.goto(baseURL + '/offline', { waitUntil: 'networkidle' });
    await page.waitForFunction(() => navigator.serviceWorker.controller && document.documentElement.dataset.offlineReady === 'true');
    await revealInterface(page);
    await page.evaluate(() => DMateOfflineAppearance.open());
    await page.locator('#appearanceModal [data-appearance-mode="' + theme + '"]').click();
    await page.locator('#appearanceDone').click();
    await page.locator('#appearanceModal').waitFor({state:'hidden'});
    await openOfflineGraph(page);
    await inlineLayout(page);
    const available = await frame(page).locator('.graph-modal-card').evaluate(card => {
      const rect = card.getBoundingClientRect(); return { width: rect.width, height: rect.height };
    });
    const reference = await onlineReference(browser, width, theme, available);
    near(reference.initial.size.width, available.width, 'Online reference uses the embedded content width');
    near(reference.initial.size.height, available.height, 'Online reference uses the embedded content height');
    await context.setOffline(true);
    protocol = await disconnectWorkerNetwork(browser, page);
    page.on('requestfailed', request => failures.push(request.url()));
    page.on('request', request => {
      const url = new URL(request.url());
      if (['http:', 'https:'].includes(url.protocol) && !url.pathname.startsWith('/static/')
        && !['/offline', '/offline-service-worker.js', '/favicon.ico'].includes(url.pathname)) api.push(url.href);
    });
    await page.reload({ waitUntil: 'networkidle' });
    await openOfflineGraph(page);
    assert.equal(await page.locator('body').getAttribute('data-appearance-theme'), theme, 'The device retains its theme offline');
    assert.equal(await page.evaluate(() => navigator.onLine), false);
    assert.equal(await frame(page).locator('#knowledgeGraphFocusBtn').count(), 0,
      'The offline graph omits the redundant All knowledge button');
    assert.equal(await frame(page).locator('.graph-side-tabs,#knowledgeGraphDetailTab').count(), 0,
      'The offline graph omits the redundant single detail tab');
    assert.ok(await frame(page).locator('#knowledgeGraphDetailTitle,#knowledgeGraphDetail').count() === 2,
      'The node title and detail content remain available');
    assert.equal(await frame(page).locator('#knowledgeGraphScopeBtn,#knowledgeGraphHistoryTab,#knowledgeGraphHistoryWrap,'
      + '#knowledgeGraphLegendRelated,.graph-legend,.kg-video-section,iframe,a[href*="bilibili"],a[href*="youtube"]').count(), 0,
    'Question association, history, videos and the purple legend are absent');
    await inlineLayout(page);
    const actual = await visual(page);
    if (process.env.OFFLINE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/offline-graph-preview-' + width + '-' + theme + '.png' });
    for (const [selector, expected] of Object.entries(reference.initial.blocks)) {
      assert.deepEqual(actual.blocks[selector].style, expected.style, label + ': shared graph styles ' + selector);
      actual.blocks[selector].rect.forEach((value, index) => near(value, expected.rect[index],
        label + ': shared graph geometry ' + selector));
    }
    assert.deepEqual(await frame(page).locator('#knowledgeGraphCategory option').allTextContents(), reference.categories);
    await fullGraph(page);
    for (const name of reference.categories) {
      await category(page, name);
      await fullGraph(page);
      assert.deepEqual(await topology(page), reference.expected[name].topology, label + '/' + name + ': shared node geometry, labels and edge routing');
      assert.deepEqual(await selectFirst(page), reference.expected[name].details, label + '/' + name + ': direct prerequisites and successors');
    }
    await relationNavigation(page);
    await gestures(page);
    await png(page);
    await liveLanguage(page);
    await inlineLifecycle(page);
    await category(page, '全部');
    assert.equal(await frame(page).locator('#knowledgeGraphCategory').inputValue(), '全部', 'The module selector restores the complete graph');
    await page.reload({ waitUntil: 'networkidle' });
    await openOfflineGraph(page);
    await fullGraph(page);
    assert.equal(await nodes(page).count(), reference.expected[reference.categories[0]].topology.nodes.length, 'The complete graph is available after another disconnected reload');
    await category(page, '初等数论');
    await fullGraph(page);
    await selectFirst(page);
    if (process.env.OFFLINE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/offline-graph-' + width + '-' + theme + '.png' });
    assert.deepEqual(errors, [], label + ': no page errors');
    assert.deepEqual(failures, [], label + ': all necessary graph assets are cached');
    assert.deepEqual(api, [], label + ': no online video or API calls');
    console.log('PASS ' + label + ': online layout/styles, ' + reference.categories.length
      + ' categories, relation module navigation, selected outlines, zoom/Fit/' + (mobile(page) ? 'drag/pinch' : 'scroll/clipping')
      + ', live language switching, PNG and two truly offline reloads');
  } catch (error) {
    if (process.env.OFFLINE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/FAILED-offline-graph-' + width + '-' + theme + '.png' }).catch(() => {});
    throw error;
  } finally { await context.close(); if (protocol) await protocol.detach().catch(() => {}); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ignoreDefaultArgs:['--hide-scrollbars'],
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try { for (const width of [1440, 390]) for (const theme of ['light', 'dark']) await runCase(browser, width, theme); }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
