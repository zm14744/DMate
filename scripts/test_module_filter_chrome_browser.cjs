/* Start Flask first. Exercises graph module controls, the offline topbar and
 * plain study metadata without rewriting authored mathematics or content.
 */
'use strict';
const assert = require('node:assert/strict');
const { revealInterface } = require('./offline-vault-browser-fixtures.cjs');
const { chromium } = require('playwright');
const nodes = require('../static/offline-content/knowledge_graph.json').nodes;
const concepts = require('../static/offline-content/concepts.zh-CN.json').concepts;
const questions = require('../static/offline-content/questions.zh-CN.json').questions;
const translations = require('../static/offline-content/translations.en.json');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const mobile = page => page.viewportSize().width <= 1100;
const graphMobile = page => page.viewportSize().width <= 760;
const normalize = value => value.replace(/\s+/g, ' ').trim();
const difficulty = value => value === '基础' ? '简单' : ['进阶', '提高'].includes(value) ? '困难' : value;

async function settle(page) {
  await page.evaluate(async () => {
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    await Promise.all(document.getAnimations().filter(animation =>
      animation.effect?.getComputedTiming().iterations !== Infinity)
      .map(animation => animation.finished.catch(() => {})));
  });
}

async function noOverflow(page) {
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Module controls do not create horizontal overflow');
}

async function moduleLabel(page, value, english) {
  return value === '全部' ? english ? 'All modules' : '全部模块'
    : page.evaluate(value => window.DMateKnowledgeLanguage.label(value), value);
}

async function chooseModule(page, value, english = false) {
  const select = page.locator('#knowledgeGraphCategory');
  if (mobile(page)) {
    await page.locator('#knowledgeGraphCategoryTrigger').tap();
    const modal = page.locator('#mobileChoiceModal');
    await modal.waitFor({ state: 'visible' });
    assert.equal((await page.locator('#mobileChoiceTitle').innerText()).trim(), english ? 'Filter by module' : '按模块筛选');
    assert.equal(await modal.getByRole('radio', { name: english ? 'All modules' : '全部模块', exact: true }).count(), 1);
    await modal.getByRole('radio', { name: await moduleLabel(page, value, english), exact: true }).tap();
    await modal.waitFor({ state: 'hidden' });
  } else {
    await select.selectOption(value);
    assert.equal(await page.locator('#mobileChoiceModal').evaluate(modal => modal.open), false);
  }
  await settle(page);
  assert.equal(await select.inputValue(), value, 'Filtering keeps canonical category values');
  const expected = value === '全部' ? nodes : nodes.filter(node => node.category === value);
  assert.equal(await page.locator('#knowledgeGraphCanvas ' + (graphMobile(page) ? '.kg-mobile-node' : '.kg-node-group')).count(),
    expected.length, 'The chosen real module controls the displayed graph');
  assert.equal(await select.evaluate(select => select.selectedOptions[0].label), await moduleLabel(page, value, english));
  if (mobile(page)) assert.equal((await page.locator('#knowledgeGraphCategoryTrigger').innerText()).trim(), await moduleLabel(page, value, english));
}

async function triggerPaint(page) {
  const trigger = page.locator('#knowledgeGraphCategoryTrigger');
  if (!mobile(page)) {
    assert.equal(await trigger.isVisible(), false, 'Desktop keeps its native select');
    assert.equal(await page.locator('#knowledgeGraphCategory').evaluate(select => getComputedStyle(select).appearance), 'auto');
    return;
  }
  const read = () => trigger.evaluate(button => {
    const css = getComputedStyle(button), probe = document.createElement('span');
    probe.style.cssText = 'position:fixed;visibility:hidden;background:var(--surface-1)'; document.body.append(probe);
    const surface = getComputedStyle(probe).backgroundColor; probe.remove();
    return { background: css.backgroundColor, surface, image: css.backgroundImage,
      border: css.borderTopWidth, style: css.borderTopStyle, radius: css.borderTopLeftRadius,
      shadow: css.boxShadow, filter: css.filter };
  });
  const idle = await read();
  assert.equal(idle.background, idle.surface, 'Module trigger uses the native input surface');
  assert.equal(idle.border, '1px'); assert.equal(idle.style, 'solid');
  assert.ok(parseFloat(idle.radius) >= 8);
  assert.equal(idle.image, 'none'); assert.equal(idle.shadow, 'none'); assert.equal(idle.filter, 'none');
  await trigger.hover(); await settle(page);
  assert.deepEqual(await read(), idle, 'Hover does not turn the selector into a raised button');
}

async function graphNavigationPaint(page) {
  const ids = ['knowledgeGraphFocusBtn', 'knowledgeGraphScopeBtn', 'knowledgeGraphHistoryBtn'];
  const read = id => page.locator('#' + id).evaluate(button => {
    const css = getComputedStyle(button);
    return Object.fromEntries(['backgroundColor', 'backgroundImage', 'borderTopColor', 'borderTopWidth',
      'borderTopStyle', 'boxShadow', 'borderRadius', 'fontFamily', 'fontSize', 'fontWeight',
      'lineHeight', 'padding', 'minHeight', 'color', 'opacity', 'outlineStyle', 'outlineWidth', 'outlineOffset']
      .map(name => [name, css[name]]));
  });
  const assertMatching = async (label, focused = false) => {
    const styles = [];
    for (const id of ids) {
      if (focused) { await page.locator('#' + id).focus(); await settle(page); }
      styles.push(await read(id));
    }
    for (const style of styles.slice(1)) assert.deepEqual(style, styles[0], label + ': all three graph pages use the same button parameters');
    assert.equal(styles[0].borderTopColor, 'rgba(0, 0, 0, 0)', label + ': no visible button border');
    assert.equal(styles[0].boxShadow, 'none', label + ': no raised surface');
    assert.equal(styles[0].backgroundImage, 'none', label + ': no image fill');
    return styles[0];
  };
  await page.mouse.move(0, 0);
  try {
    for (const state of ['idle', 'active', 'disabled']) {
      await page.evaluate(({ids, state}) => {
        for (const id of ids) {
          const button = document.getElementById(id);
          button.classList.toggle('active', state === 'active');
          button.setAttribute('aria-pressed', String(state === 'active'));
          button.disabled = state === 'disabled';
          button.blur();
        }
      }, {ids, state});
      await settle(page);
      const style = await assertMatching(state);
      if (state !== 'active') assert.equal(style.backgroundColor, 'rgba(0, 0, 0, 0)', state + ': inactive choices remain transparent');
      else assert.notEqual(style.backgroundColor, 'rgba(0, 0, 0, 0)', 'Selected choices keep a visible filled surface');
    }
    await page.evaluate(ids => ids.forEach(id => { document.getElementById(id).disabled = false; }), ids);
    await page.keyboard.press('Tab');
    const focused = await assertMatching('keyboard focus', true);
    assert.equal(focused.outlineStyle, 'solid');
    assert.equal(focused.outlineWidth, '2px', 'Frameless choices retain visible keyboard focus');
    if (await page.evaluate(() => matchMedia('(hover:hover)').matches)) {
      const hovered = [];
      for (const id of ids) {
        await page.locator('#' + id).evaluate(button => button.blur());
        await page.locator('#' + id).hover(); await settle(page);
        hovered.push(await read(id));
      }
      for (const style of hovered.slice(1)) assert.deepEqual(style, hovered[0], 'Hover paint matches all graph page choices');
      assert.equal(hovered[0].borderTopColor, 'rgba(0, 0, 0, 0)', 'Hover keeps the frame transparent');
    }
  } finally {
    await page.mouse.move(0, 0);
    await page.evaluate(() => selectKnowledgeGraphDisplayMode('full'));
    await settle(page);
  }
}

async function moduleControls(page) {
  assert.equal(await page.locator('label[for="knowledgeGraphCategory"]').count(), 0, 'No outside Module label remains');
  const first = page.locator('#knowledgeGraphCategory option').first();
  assert.equal(await first.getAttribute('value'), '全部');
  assert.equal((await first.textContent()).trim(), '全部模块');
  assert.equal(await page.locator('#knowledgeGraphCategory').getAttribute('aria-label'), '按模块筛选');
  await triggerPaint(page);
  for (const value of ['图论', '初等数论', '全部']) await chooseModule(page, value);
  if (mobile(page)) {
    await page.locator('#knowledgeGraphCategoryTrigger').tap();
    await page.locator('#mobileChoiceModal').waitFor({ state: 'visible' });
    await page.locator('#mobileChoiceClose').tap();
    assert.equal(await page.locator('#knowledgeGraphCategory').inputValue(), '全部', 'Cancelling leaves the current module unchanged');
  }
  await page.evaluate(() => window.DMateI18n.setLanguage('en', false));
  await page.waitForFunction(() => document.querySelector('#knowledgeGraphCategory option')?.textContent.trim() === 'All modules');
  assert.equal(await page.locator('#knowledgeGraphCategory').getAttribute('aria-label'), 'Filter by module');
  await chooseModule(page, '图论', true);
  await chooseModule(page, '全部', true);
  await noOverflow(page);
}

async function offlineHeader(page, wallpaper = false) {
  assert.equal(await page.locator('#offlineAppearanceToggle').count(), 0, 'The topbar palette button is removed');
  assert.equal(await page.locator('#offlineAppearanceBtn').count(), 1, 'Sidebar appearance action remains');
  if (!mobile(page)) return;
  const result = await page.locator('.offline-topbar').evaluate(header => {
    const css = getComputedStyle(header), main = document.getElementById('offlineMain');
    const background = node => {
      for (; node; node = node.parentElement) {
        const color = getComputedStyle(node).backgroundColor;
        if (color !== 'rgba(0, 0, 0, 0)' && color !== 'transparent') return color;
      }
      return 'rgba(0, 0, 0, 0)';
    };
    const toggle = header.querySelector('#offlineNavToggle').getBoundingClientRect();
    return { border: [css.borderTopWidth, css.borderRightWidth, css.borderBottomWidth, css.borderLeftWidth],
      radius: css.borderRadius, shadow: css.boxShadow, blur: css.backdropFilter,
      ownBackground: css.backgroundColor, mainBackground: getComputedStyle(main).backgroundColor,
      background: background(header), main: background(main),
      branding: header.querySelectorAll('.mobile-topbar-brand,.mobile-dmate-mark,.mobile-topbar-title').length,
      text: header.textContent.trim(), toggle: { left: toggle.left, width: toggle.width, height: toggle.height },
      buttons: [...header.querySelectorAll('button')].map(button => button.id) };
  });
  assert.deepEqual(result.border, ['0px', '0px', '0px', '0px']);
  assert.equal(parseFloat(result.radius), 0); assert.equal(result.shadow, 'none'); assert.equal(result.blur, 'none');
  assert.equal(result.background, result.main, 'Topbar and main share the background paint');
  assert.equal(result.branding, 0, 'The centered logo and panel title are removed');
  assert.equal(result.text, '', 'The header has no leftover branding text');
  assert.deepEqual(result.buttons, ['offlineNavToggle', 'offlineMobilePrivacyToggle'],
    'The mobile header contains the learning-tool drawer and privacy buttons in order');
  assert.ok(result.toggle.left >= 0 && result.toggle.left < 25, 'The drawer button stays at the left edge');
  assert.ok(result.toggle.width >= 42 && result.toggle.height >= 42, 'The drawer button keeps its mobile touch target');
  if (wallpaper) assert.equal(result.ownBackground, result.mainBackground, 'Wallpaper uses the same transparent background through the header');
}

async function closeLibraryDetail(page) {
  if (await page.locator('#libraryDetailDialog').evaluate(dialog => dialog.open)) {
    await page.locator('#libraryDetailClose').click();
    await page.locator('#libraryDetailDialog').waitFor({ state: 'hidden' });
  }
}

async function openLibraryDetail(page, panel) {
  if (page.viewportSize().width > 1100) return;
  if (!await page.locator('#libraryDetailDialog').evaluate(dialog => dialog.open)) {
    await page.locator(panel === 'concepts' ? '#conceptFullView' : '#questionFullView').click();
  }
  await page.locator(panel === 'concepts' ? '#conceptDetail' : '#questionDetail').waitFor({ state: 'visible' });
}

async function navigate(page, panel) {
  await closeLibraryDetail(page);
  if (mobile(page) && !await page.evaluate(() => document.body.classList.contains('offline-nav-open'))) await page.locator('#offlineNavToggle').tap();
  await page.locator('.offline-nav-item[data-panel="' + panel + '"]').click();
  await page.locator('#' + panel + 'Panel').waitFor({ state: 'visible' });
  await settle(page);
}

async function sidebarAppearance(page) {
  if (mobile(page)) await page.locator('#offlineNavToggle').tap();
  await page.locator('#offlineAppearanceBtn').click();
  await page.locator('#appearanceModal').waitFor({ state: 'visible' });
  await page.locator('#appearanceClose').click();
  await page.locator('#appearanceModal').waitFor({ state: 'hidden' });
}

async function chooseStudyChapter(page, kind, category) {
  const select = page.locator('#' + kind + 'Category');
  if (await select.inputValue() !== category) {
    if (mobile(page)) {
      const label = await select.evaluate((node, value) => [...node.options].find(option => option.value === value).label, category);
      await select.tap();
      const dialog = page.locator('#mobileChoiceModal');
      await dialog.waitFor({state:'visible'});
      await dialog.getByRole('radio', {name:label, exact:true}).tap();
      await dialog.waitFor({state:'hidden'});
    } else await select.selectOption(category);
    await settle(page);
  }
  assert.equal(await select.inputValue(), category, 'The content fixture uses its actual chapter filter');
}

async function studyMetadata(page) {
  await page.evaluate(() => {
    window.DMateI18n.setLanguage('zh-CN', false);
    const render = window.DMateAIAnswer.render;
    window.__moduleFilterSources = new WeakMap();
    window.DMateAIAnswer.render = function (target, source, ...args) {
      window.__moduleFilterSources.set(target, source); return render.call(this, target, source, ...args);
    };
  });
  await navigate(page, 'questions');
  const question = questions.find(question => question.id === 'q01');
  await chooseStudyChapter(page, 'question', question.category);
  const entry = page.locator('#questionList .question-item[data-question-id="' + question.id + '"]');
  await entry.click();
  await openLibraryDetail(page, 'questions');
  const expected = [question.category, difficulty(question.difficulty), question.type].join(' ');
  assert.equal(normalize(await entry.locator('small').textContent()), expected, 'List metadata uses readable spaces');
  assert.equal(normalize(await page.locator('#questionDetail .detail-kicker').textContent()), expected, 'Detail metadata uses readable spaces');
  for (const mathematical of [questions.find(question => question.statement.includes('/')),
    questions.find(question => /[·⋅]/.test(question.statement))]) {
    assert.ok(mathematical, 'The source pack includes authored division and multiplication examples');
    await closeLibraryDetail(page);
    await chooseStudyChapter(page, 'question', mathematical.category);
    await page.locator('#questionList .question-item[data-question-id="' + mathematical.id + '"]').click();
    await openLibraryDetail(page, 'questions');
    const source = await page.locator('#questionDetail .wrong-question').evaluate((node, authored) => ({
      actual: window.__moduleFilterSources.get(node), expected: window.DMateMathMarkdown.prepareStudyText(authored)
    }), mathematical.statement);
    assert.equal(source.actual, source.expected, 'Removing UI separators preserves the complete authored mathematical statement');
  }
  await navigate(page, 'concepts');
  await chooseStudyChapter(page, 'concept', concepts.find(concept => concept.id === 'logic_truth').category);
  await page.locator('#conceptList .concept-item[data-concept-id="logic_truth"]').click();
  await openLibraryDetail(page, 'concepts');
  assert.equal(await page.locator('#conceptDetail .concept-related-exercises').count(), 0,
    'The broad overview keeps exercise links on its graph topic');
  await page.locator('#conceptDetail .concept-graph-module [data-graph-node-id="logic_truth"]').click();
  await page.locator('#graphPanel').waitFor({state:'visible'});
  await page.waitForFunction(() => document.querySelector('#knowledgeGraphCanvas .selected[data-node-id]')?.dataset.nodeId === 'logic_truth');
  const related = page.locator('#knowledgeGraphDetail .graph-related-exercises [data-question-id="q01"]');
  await page.waitForFunction(() => !document.querySelector('#knowledgeGraphDetail [data-dmate-render-state="pending"]'));
  assert.equal(normalize(await related.textContent()), difficulty(question.difficulty) + ' ' + question.title,
    'Graph-related exercise difficulty and title are separated by a plain space');
  await page.evaluate(() => window.DMateI18n.setLanguage('en', false));
  await page.waitForFunction(() => !document.querySelector('#knowledgeGraphDetail [data-dmate-render-state="pending"]'));
  assert.equal(normalize(await related.textContent()), 'Easy ' + translations.questions[question.id].title);
}

async function runCase(browser, width, theme, offline) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block',
    ...(width <= 1100 ? { isMobile: true, hasTouch: true } : {}) });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(baseURL + (offline ? '/offline' : ''), { waitUntil: 'networkidle' });
    if (offline) {
      await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
      await revealInterface(page);
      await page.evaluate(mode => window.DMateOfflineAppearance.apply({ mode }, null), theme);
      await settle(page);
      await offlineHeader(page);
    } else {
      await page.evaluate(mode => {
        const question = '判断命题 p 与 q 的合取在什么情况下为真';
        sessions = [{id:'navigation-paint',name:'Navigation paint',nameSource:'user',
          messages:[{messageId:'navigation-question',role:'user',text:question,manualIsQuestion:true}],
          learningQuestion:null,teaching:null}];
        currentId='navigation-paint';
        appearanceSettings.mode = mode; applyAppearanceSettings({ save: false }); openKnowledgeGraph();
      }, theme);
      await page.waitForFunction(() => knowledgeGraphInitialized);
      await page.evaluate(() => selectKnowledgeGraphDisplayMode('full'));
      await page.waitForSelector('#knowledgeGraphCanvas .kg-section');
      await graphNavigationPaint(page);
    }
    await moduleControls(page);
    if (offline) {
      await sidebarAppearance(page);
      if (mobile(page)) {
        await page.evaluate(() => {
          const layer = document.getElementById('appearanceBackgroundLayer');
          layer.style.backgroundImage = 'linear-gradient(45deg, #164e63, #f59e0b)';
          document.body.classList.add('has-custom-background');
        });
        await offlineHeader(page, true);
      }
      await studyMetadata(page);
    }
    await noOverflow(page);
    assert.deepEqual(errors, [], 'No module/header/metadata script errors');
    console.log('PASS ' + (offline ? 'offline ' : 'online ') + width + '/' + theme + ': module labels, canonical filtering and flat input chrome' + (offline ? ', seamless header and preserved study content' : ''));
  } finally { await context.close(); }
}

async function disconnectedCase(browser) {
  const context = await browser.newContext({ viewport: { width: 390, height: 900 }, isMobile: true, hasTouch: true });
  const page = await context.newPage();
  try {
    await page.goto(baseURL + '/offline', { waitUntil: 'networkidle' });
    await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
    await revealInterface(page);
    await page.evaluate(async () => {
      await navigator.serviceWorker.register('/offline-service-worker.js', { scope: '/' });
      await navigator.serviceWorker.ready;
    });
    await page.waitForFunction(() => navigator.serviceWorker.controller?.state === 'activated');
    await context.setOffline(true);
    await page.reload({ waitUntil: 'load' });
    await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
    await revealInterface(page);
    assert.equal(await page.evaluate(() => navigator.onLine), false);
    await offlineHeader(page);
    await moduleControls(page);
    await studyMetadata(page);
    console.log('PASS disconnected reload: new module picker labels, offline chrome and plain study metadata remain available');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const width of [390, 1440]) for (const theme of ['dark', 'navy']) await runCase(browser, width, theme, false);
    for (const [width, theme] of [[390, 'dark'], [1440, 'navy']]) await runCase(browser, width, theme, true);
    await runCase(browser, 820, 'navy', true);
    await disconnectedCase(browser);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
