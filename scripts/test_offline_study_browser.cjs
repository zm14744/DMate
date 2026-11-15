/* Real online chat is the typography reference. The deployed Chinese/English
 * packs and a fresh, controlled service worker supply all offline study data. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const migrationReview = require('../offline-content/example-practice-migration.json');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const conceptsURL = '/static/offline-content/concepts.zh-CN.json';
const questionsURL = '/static/offline-content/questions.zh-CN.json';
const translationsURL = '/static/offline-content/translations.en.json';
const themes = ['light', 'dark', 'navy'];
const probe = [
  '### Markdown study probe', '',
  'A **bold** and *emphasized* paragraph with inline \\(x_i^2+1\\) and `literal_name`.', '',
  '- First item', '- Second item with \\(a_1\\)', '', '1. First step', '2. Second step', '',
  '> A quoted explanation.', '', '| Symbol | Value |', '| --- | --- |', '| n | 3 |', '',
  '```text', 'x_label = 2', '```', '', '\\[\\sum_{k=1}^{3}k=6\\]'
].join('\n');
const settle = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));

async function protectAPIs(page) {
  page.studyErrors = []; page.modelCalls = 0;
  page.on('pageerror', error => page.studyErrors.push(error.message));
  await page.route('**/auth/me', route => route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ configured: true, authenticated: false }) }));
  await page.route(/\/(?:chat|ocr|drawing\/(?:generate|guide|upload))(?:\?|$)/, route => {
    page.modelCalls++; return route.abort();
  });
}

async function setTheme(page, theme) {
  await page.evaluate(value => { document.documentElement.dataset.appearanceTheme = document.body.dataset.appearanceTheme = value; }, theme);
  await settle(page);
}

async function snapshot(locator) {
  return locator.evaluate(node => {
    const selectors = ['', 'h3', 'p', 'strong', 'em', 'ul', 'ul>li', 'ol', 'ol>li', 'blockquote',
      'table', 'th', 'td', 'pre', 'pre>code', 'p>code', 'mjx-container', 'mjx-container[display="true"]'];
    const styles = {};
    for (const selector of selectors) {
      const item = selector ? node.querySelector(selector) : node;
      if (!item) throw new Error('Missing real rendered Markdown node: ' + selector);
      const style = getComputedStyle(item);
      styles[selector || 'root'] = Object.fromEntries(['fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'color', 'whiteSpace']
        .map(key => [key, style[key]]));
    }
    return { styles, math: MathJax.startup.document.getMathItemsWithin([node]).map(item => [item.math, item.display]),
      structure: { ul: node.querySelectorAll('ul>li').length, ol: node.querySelectorAll('ol>li').length,
        rows: node.querySelectorAll('table tr').length, code: node.querySelector('pre>code').textContent.trim(),
        svg: node.querySelectorAll('mjx-container>svg').length,
        errors: node.querySelectorAll('[data-mml-node="merror"],mjx-merror,.math-render-fallback').length } };
  });
}

async function disconnectWorkerNetwork(browser, page, workerURL) {
  // Chromium can leave a worker's own fetch online after context.setOffline.
  // Disconnect that target too and prove an uncached fetch really rejects.
  const protocol = await browser.newBrowserCDPSession();
  const pageProtocol = await page.context().newCDPSession(page);
  const { targetInfo } = await pageProtocol.send('Target.getTargetInfo'); await pageProtocol.detach();
  const target = (await protocol.send('Target.getTargets')).targetInfos.find(info =>
    info.type === 'service_worker' && info.url === workerURL && info.browserContextId === targetInfo.browserContextId);
  assert.ok(target, 'The controlled page has an active service-worker target');
  const { sessionId } = await protocol.send('Target.attachToTarget', { targetId: target.targetId, flatten: false });
  let serial = 0;
  const send = async (method, params = {}) => {
    const id = ++serial; let listener;
    const result = new Promise((resolve, reject) => {
      listener = event => {
        if (event.sessionId !== sessionId) return;
        const response = JSON.parse(event.message); if (response.id !== id) return;
        if (response.error) reject(new Error(response.error.message)); else resolve(response.result);
      };
      protocol.on('Target.receivedMessageFromTarget', listener);
    });
    try { await protocol.send('Target.sendMessageToTarget', { sessionId, message: JSON.stringify({ id, method, params }) }); return await result; }
    finally { protocol.off('Target.receivedMessageFromTarget', listener); }
  };
  try {
    await send('Network.enable');
    await send('Network.emulateNetworkConditions', { offline: true, latency: 0, downloadThroughput: 0, uploadThroughput: 0 });
    const probe = await send('Runtime.evaluate', { expression: "fetch('/offline-study-network-probe', {cache:'no-store'}).then(() => false, () => true)", awaitPromise: true, returnByValue: true });
    assert.equal(probe.result.value, true, 'An uncached service-worker fetch rejects while disconnected');
    return protocol;
  } catch (error) { await protocol.detach(); throw error; }
}

async function onlineReference(browser, width) {
  const context = await browser.newContext({ viewport: { width, height: width === 390 ? 820 : 1000 },
    locale: 'zh-CN', isMobile: width === 390, hasTouch: width === 390, serviceWorkers: 'block' });
  const page = await context.newPage(); await protectAPIs(page);
  const result = {};
  try {
    await page.goto(baseURL + '/', { waitUntil: 'networkidle' });
    await page.waitForFunction(() => typeof renderChat === 'function' && window.DMateMathMarkdown && window.MathJax?.startup?.promise);
    for (const language of ['zh-CN', 'en']) for (const theme of themes) {
      await page.evaluate(({ language, source }) => {
        stopCloudLivePolling(); DMateI18n.setLanguage(language, false);
        newChat(); getCurrent().messages.push({ role: 'ai', text: source }); renderChat();
      }, { language, source: probe });
      await setTheme(page, theme);
      await page.waitForFunction(() => {
        const node = document.querySelector('#chat>.msg.ai>.msg-content>.ai-content');
        return node && !node.classList.contains('math-pending') && node.querySelectorAll('mjx-container>svg').length === 3;
      });
      result[language + '/' + theme] = await snapshot(page.locator('#chat>.msg.ai>.msg-content>.ai-content'));
      assert.deepEqual(result[language + '/' + theme].structure, { ul: 2, ol: 2, rows: 2, code: 'x_label = 2', svg: 3, errors: 0 });
    }
    assert.equal(page.modelCalls, 0); assert.deepEqual(page.studyErrors, []);
    return result;
  } finally { await context.close(); }
}

async function navigation(page, panel) {
  const toggle = page.locator(page.viewportSize().width <= 1100 ? '#offlineNavToggle' : '#offlineDesktopSidebarOpen');
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
  await page.locator('.offline-nav-item[data-panel="' + panel + '"]').click();
  await page.locator('#' + panel + 'Panel').waitFor({ state: 'visible' });
}

async function languageChoice(page, language) {
  const opener = page.locator(page.viewportSize().width <= 1100 ? '#offlineNavToggle' : '#offlineDesktopSidebarOpen');
  if (await opener.getAttribute('aria-expanded') !== 'true') await opener.click();
  await page.locator('#offlineAppearanceBtn').click();
  await page.locator('#appearanceModal:not(.hidden)').waitFor();
  await page.locator('#appearanceModal [data-dmate-language="' + language + '"]').click();
  await page.waitForFunction(value => document.documentElement.dataset.uiLanguage === value, language);
  await page.locator('#appearanceClose').click();
  await page.locator('#appearanceModal').waitFor({ state: 'hidden' });
}

async function hookRenderer(page) {
  await page.evaluate(() => {
    window.studyInputs = new WeakMap(); window.studyPending = new WeakMap();
    const render = DMateAIAnswer.render;
    DMateAIAnswer.render = function(target, source, options) {
      studyInputs.set(target, String(source ?? ''));
      const pending = render.call(this, target, source, options); studyPending.set(target, pending); return pending;
    };
  });
}

async function packs(page) {
  return page.evaluate(async ({ urls, reviewedExamples }) => {
    const [concepts, questions, en] = await Promise.all(urls.map(async url => {
      const response = await fetch(url); if (!response.ok) throw new Error('Actual deployed pack failed: ' + url); return response.json();
    }));
    const require = (value, message) => { if (!value) throw new Error(message); };
    const examples = concepts.concepts.filter(row => typeof row.example === 'string' && row.example.trim());
    const migrated = questions.questions.filter(row => row.source?.migrated_from?.kind === 'concept_example');
    require(concepts.concepts.length === Object.keys(reviewedExamples).length && questions.questions.length - migrated.length === 561,
      'The complete original curriculum is retained alongside migrated examples');
    require(migrated.length === examples.length && new Set(migrated.map(row => row.source.migrated_from.concept_id)).size === examples.length,
      'Every nonempty concept example has exactly one migrated exercise');
    const digest = async value => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))))
      .map(byte => byte.toString(16).padStart(2, '0')).join('');
    const conceptMap = new Map(concepts.concepts.map(concept => [concept.id, concept]));
    for (const question of questions.questions) {
      require(question.knowledge_points?.length && question.knowledge_points.every(id => {
        const concept = conceptMap.get(id); return concept && concept.id !== concept.graph_node_id;
      }), question.id + ': every exercise belongs to detailed concepts instead of topic overviews');
    }
    for (const concept of examples) {
      const question = migrated.find(row => row.source.migrated_from.concept_id === concept.id);
      require(question && concept.related_questions.includes(question.id), concept.id + ': migrated exercise is associated');
      const reviewed = reviewedExamples[concept.id];
      require(question.id === reviewed.question_id && JSON.stringify(question.knowledge_points)
        === JSON.stringify(reviewed.knowledge_points || [concept.id]), concept.id + ': reviewed precise concept assignments match');
      require(question.knowledge_points.every(id => {
        const linked = conceptMap.get(id);
        return linked.graph_node_id === concept.graph_node_id && linked.related_questions.includes(question.id);
      }), concept.id + ': precise concept links preserve source topic and reverse navigation');
      require(question.answer_text === concept.example, concept.id + ': original worked example remains the exact answer');
      require(en.questions[question.id]?.answer_text === en.concepts[concept.id]?.example,
        concept.id + ': original English worked example remains the exact answer');
      require(question.source.migrated_from.example_sha256 === await digest(concept.example), concept.id + ': migration source hash matches');
      if (question.source.migrated_from.english_example_sha256) require(question.source.migrated_from.english_example_sha256
        === await digest(en.concepts[concept.id].example), concept.id + ': English migration source hash matches');
      require(['简单', '中等', '困难'].includes(question.difficulty), question.id + ': migrated exercise has an explicit difficulty');
    }
    for (const [kind, fields] of [['concepts', ['title', 'summary', 'definition', 'explanation', 'notation', 'example', 'common_mistakes']],
      ['questions', ['title', 'statement', 'answer_text', 'explanation', 'grading_criteria']]]) {
      const rows = (kind === 'concepts' ? concepts : questions)[kind];
      require(JSON.stringify(Object.keys(en[kind]).sort()) === JSON.stringify(rows.map(row => row.id).sort()), kind + ': complete English ID coverage');
      for (const row of rows) {
        const translated = en[kind][row.id];
        for (const field of fields) {
          const value = translated[field], label = row.id + '.' + field;
          require(Array.isArray(row[field]) ? Array.isArray(value) : typeof value === 'string' && value.trim(), label + ': real English field missing or wrong type');
          require(!/[\u3400-\u9fff]/.test(JSON.stringify(value)), label + ': Chinese remains in English content');
          if (Array.isArray(row[field])) require(value.length === row[field].length && value.every(item => typeof item === 'string' && item.trim()), label + ': list content lost');
        }
        if (row.options) {
          require(JSON.stringify(translated.options.map(item => item.key)) === JSON.stringify(row.options.map(item => item.key)), row.id + ': complete option order');
          require(translated.options.every(item => item.text.trim() && !/[\u3400-\u9fff]/.test(item.text)), row.id + ': translated option missing');
          require(JSON.stringify(translated.answer_text.match(/\b[A-Z]\b/g) || []) === JSON.stringify(row.answer), row.id + ': translated choice answer changed');
        }
      }
    }
    window.studyPacks = { concepts: concepts.concepts, questions: questions.questions, en };
    const math = value => DMateMathMarkdown.protectMathForMarkdown(DMateMathMarkdown.prepareStudyText(value)).mathSegments.length;
    const concept = examples.find(row => row.id === row.graph_node_id && math(row.example) && math(en.concepts[row.id].example)
      && ['summary', 'definition', 'explanation', 'notation'].some(field => math(row[field]) && math(en.concepts[row.id][field])));
    const choice = questions.questions.find(row => row.options?.length && row.options.some(option => math(option.text)));
    const proof = questions.questions.find(row => row.type === '证明' && math(row.explanation) && math(en.questions[row.id].explanation));
    require(concept && choice && proof, 'Actual packs must provide mathematical concept, options, and proof examples');
    const example = migrated.find(row => row.source.migrated_from.concept_id === concept.id);
    return { concept: { id: concept.id, graphNodeId: concept.graph_node_id, query: en.concepts[concept.id].title }, example: {id:example.id, conceptId:concept.id},
      counts: {concepts:concepts.concepts.length, questions:questions.questions.length, examples:migrated.length},
      questions: [choice, proof].map(row => ({ id: row.id, category: row.category,
        difficulty: row.difficulty === '基础' ? '简单' : ['进阶', '提高'].includes(row.difficulty) ? '困难' : row.difficulty })) };
  }, { urls: [conceptsURL, questionsURL, translationsURL], reviewedExamples: migrationReview.examples });
}

async function assertContent(page, kind, id, language, reference) {
  const result = await page.evaluate(async ({ kind, id, language }) => {
    const row = studyPacks[kind].find(row => row.id === id), value = language === 'en' ? { ...row, ...studyPacks.en[kind][id] } : row;
    const detail = document.getElementById(kind === 'concepts' ? 'conceptDetail' : 'questionDetail');
    const choice = kind === 'questions' && ['单项选择', '多项选择'].includes(row.type);
    const expected = kind === 'concepts'
      ? [value.summary, value.definition, value.explanation, value.notation, value.common_mistakes]
      : [value.statement, ...(value.options || []).map(option => option.text), choice ? row.answer.join('、') : value.answer_text, value.explanation, value.grading_criteria];
    const nodes = kind === 'concepts' ? [detail.querySelector('.concept-summary'), ...detail.querySelectorAll('.concept-detail-text')]
      : [detail.querySelector('.wrong-question'), ...detail.querySelectorAll('.question-option-text'), detail.querySelector('.wrong-answer-inner'), detail.querySelector('.wrong-analysis-body'), detail.querySelector('.wrong-feedback-body')];
    if (nodes.length !== expected.length || nodes.some(node => !node)) throw new Error(id + ': complete content sections missing');
    const pending = await Promise.all(nodes.map(node => studyPending.get(node)));
    const styles = [], math = [];
    nodes.forEach((node, index) => {
      const text = Array.isArray(expected[index]) ? expected[index].map(item => '- ' + String(item).replace(/\n/g, '\n  ')).join('\n') : expected[index];
      if (choice && node.classList.contains('wrong-answer-inner')) {
        if (node.textContent !== text || node.querySelector('.msg-content,.ai-content,mjx-container') || studyInputs.has(node)) {
          throw new Error(id + ': choice answer must contain only the original option letters');
        }
        return;
      }
      if (studyInputs.get(node) !== DMateMathMarkdown.prepareStudyText(text)) throw new Error(id + ': author content changed or omitted at section ' + index);
      if (pending[index] !== true || node.dataset.dmateRenderState !== 'ready') throw new Error(id + ': shared renderer did not complete');
      const content = node.querySelector(':scope>.msg-content>.ai-content');
      if (!content || node.querySelector('[data-mml-node="merror"],mjx-merror,.math-render-fallback') || node.classList.contains('dmate-ai-answer-plain')) throw new Error(id + ': incomplete Markdown/MathJax output');
      const style = getComputedStyle(content);
      styles.push(Object.fromEntries(['fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'color', 'whiteSpace'].map(key => [key, style[key]])));
      math.push(...MathJax.startup.document.getMathItemsWithin([node]).map(item => item.math));
    });
    return { styles, math, text: detail.innerText };
  }, { kind, id, language });
  assert.ok(result.math.length > 0, id + ': actual mathematical nodes are typeset');
  for (const style of result.styles) assert.deepEqual(style, reference.styles.root, id + ': actual content typography matches real online AI');
  if (language === 'en') assert.doesNotMatch(result.text, /[\u3400-\u9fff]/, 'Full English detail has no untranslated Chinese');
}

async function corpusPreflight(page) {
  const result = await page.evaluate(async () => {
    await MathJax.startup.promise;
    const fields = { concepts: ['title', 'summary', 'definition', 'explanation', 'notation', 'example', 'common_mistakes'],
      questions: ['title', 'statement', 'options', 'answer_text', 'answer', 'explanation', 'grading_criteria'] };
    const strings = (value, path) => typeof value === 'string' ? [{ text: value, path }]
      : Array.isArray(value) ? value.flatMap((item, index) => strings(item, path + '.' + index))
        : value && typeof value === 'object' ? Object.entries(value).filter(([key]) => key !== 'key')
          .flatMap(([key, item]) => strings(item, path + '.' + key)) : [];
    const math = new Map(), missed = [], placeholders = [], errors = []; let records = 0;
    for (const language of ['zh-CN', 'en']) for (const kind of Object.keys(fields)) {
      const rows = language === 'en' ? Object.entries(studyPacks.en[kind]).map(([id, row]) => ({ id, ...row })) : studyPacks[kind];
      for (const row of rows) for (const field of fields[kind]) for (const record of strings(row[field], field)) {
        records++; const source = language + ':' + row.id + ':' + record.path;
        const prepared = DMateMathMarkdown.prepareStudyText(record.text);
        if (/\uE000DMATE_MATH_|MATHPROTECTTOKEN\d+ENDTOKEN/.test(prepared) && placeholders.length < 20) placeholders.push(source);
        const text = prepared.replace(/```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`/g, '');
        for (const match of text.matchAll(/\$\$([\s\S]*?)\$\$|\\\[([\s\S]*?)\\\]|\\\(([\s\S]*?)\\\)|(?<!\\)\$(?!\$)((?:\\.|[^$\n])+)\$/g)) {
          const tex = match[1] ?? match[2] ?? match[3] ?? match[4];
          if (!math.has(tex)) math.set(tex, source);
        }
        const remainder = text.replace(/\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|(?<!\\)\$(?!\$)(?:\\.|[^$\n])+\$/g, '');
        if (/[¬∧∨→↔⇒⇔∈∉⊆∩∪×∣²³ᵢⱼ₁₀]/.test(remainder) && missed.length < 20) missed.push({ source, prepared });
      }
    }
    for (const [tex, source] of math) {
      try {
        const svg = await MathJax.tex2svgPromise(tex, { display: false });
        const error = svg.querySelector('[data-mml-node="merror"],merror,[data-mjx-error]');
        if (error && errors.length < 20) errors.push({ source, tex, error: error.getAttribute('data-mjx-error') || error.textContent });
      } catch (error) { if (errors.length < 20) errors.push({ source, tex, error: String(error) }); }
    }
    return { records, uniqueMath: math.size, missed, placeholders, errors };
  });
  assert.ok(result.records > 12000 && result.uniqueMath > 4000, 'The preflight covers both complete real display corpora');
  assert.deepEqual(result.placeholders, [], 'Internal math placeholders never escape into study source');
  assert.deepEqual(result.missed, [], 'Core mathematical symbols are included in math segments');
  assert.deepEqual(result.errors, [], 'Every actual CN/EN TeX expression compiles without MathJax errors');
  console.log('PASS full study corpus: ' + result.records + ' real CN/EN strings; ' + result.uniqueMath + ' unique TeX expressions; no errors or missed core symbols');
}

async function formatProbe(page, reference) {
  const target = await page.evaluateHandle(async source => {
    const node = document.createElement('div'); node.className = 'concept-detail-text'; node.setAttribute('data-i18n-content', '');
    document.getElementById('conceptDetail').append(node);
    if (!await DMateAIAnswer.render(node, source, { typography: 'chat' })) throw new Error('Markdown study probe failed');
    return node;
  }, probe);
  try { assert.deepEqual(await snapshot(target.asElement()), reference, 'Lists/table/code/math and computed typography match the actual online chat renderer'); }
  finally { await target.evaluate(node => { DMateAIAnswer.clear(node); node.remove(); }); await target.dispose(); }
}

async function plainOptions(page) {
  const styles = await page.locator('#questionDetail .question-option').evaluateAll(nodes => nodes.map(node => {
    const wrappers = [node, ...node.querySelectorAll('.question-option-text,.msg-content,.ai-content')].map(item => {
      const style = getComputedStyle(item);
      return { border: ['Top', 'Right', 'Bottom', 'Left'].every(side => parseFloat(style['border' + side + 'Width']) === 0
          || style['border' + side + 'Style'] === 'none' || /(?:transparent|rgba\([^)]*,\s*0\))/.test(style['border' + side + 'Color'])),
        background: style.backgroundColor, image: style.backgroundImage, shadow: style.boxShadow };
    });
    return { wrappers,
      controls: node.querySelectorAll('input,select,textarea,button').length,
      selected: node.matches('.selected,[aria-pressed],[aria-checked]') };
  }));
  assert.ok(styles.length >= 2);
  assert.ok(styles.every(item => item.wrappers.every(style => style.border && style.background === 'rgba(0, 0, 0, 0)'
      && style.image === 'none' && style.shadow === 'none')
    && item.controls === 0 && !item.selected), 'Options remain plain, unboxed, read-only text: ' + JSON.stringify(styles));
  assert.equal(await page.locator('#questionDetail input,#questionDetail textarea,#questionDetail select').count(), 0);
  assert.equal(await page.locator('#questionDetail .question-actions button').count(), 1, 'Only the reference-answer toggle remains; no answer selection or save action');
  await page.locator('#questionDetail .question-option').first().click();
  assert.equal(await page.locator('#questionDetail').locator('.question-option.selected,[aria-pressed],[aria-checked]').count(), 0);
}

async function run(browser, width) {
  const references = await onlineReference(browser, width);
  const context = await browser.newContext({ viewport: { width, height: width === 390 ? 820 : 1000 }, locale: 'zh-CN',
    isMobile: width === 390, hasTouch: width === 390, serviceWorkers: 'allow' });
  const page = await context.newPage(); await protectAPIs(page);
  let workerProtocol;
  const cachedResponses = new Set(); page.on('response', response => { if (response.fromServiceWorker()) cachedResponses.add(new URL(response.url()).pathname); });
  try {
    await page.goto(baseURL + '/offline', { waitUntil: 'networkidle' });
    await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
    const cache = await page.evaluate(async () => {
      await navigator.serviceWorker.register('/offline-service-worker.js', { scope: '/' }); await navigator.serviceWorker.ready;
      const worker = await fetch('/offline-service-worker.js').then(response => response.text());
      const name = worker.match(/const CACHE_NAME\s*=\s*["']([^"']+)/)[1];
      const cache = await caches.open(name); return { name, assets: (await cache.keys()).map(request => new URL(request.url).pathname) };
    });
    assert.ok(Number(cache.name.match(/v(\d+)$/)[1]) >= 22, 'Bilingual/Markdown resources require cache v22 or later');
    for (const asset of ['/offline', '/static/math-markdown.js', translationsURL, conceptsURL, questionsURL]) assert.ok(cache.assets.includes(asset), 'Fresh worker precaches ' + asset);
    await page.waitForFunction(() => Boolean(navigator.serviceWorker.controller));
    await context.setOffline(true);
    workerProtocol = await disconnectWorkerNetwork(browser, page, await page.evaluate(() => navigator.serviceWorker.controller.scriptURL));
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
    assert.equal(await page.evaluate(() => navigator.onLine), false, 'The reload really runs with browser networking disabled');
    await hookRenderer(page); const data = await packs(page);
    for (const url of [conceptsURL, questionsURL, translationsURL]) assert.ok(cachedResponses.has(url), 'Actual deployed pack is served by the offline worker: ' + url);
    await languageChoice(page, 'zh-CN'); await setTheme(page, 'light'); await navigation(page, 'concepts');
    await page.locator('#conceptSearch').fill(data.concept.query);
    await page.locator('#conceptList [data-concept-id="' + data.concept.id + '"]').click();
    assert.equal(await page.locator('#conceptDetail').getByRole('heading', {name:/^(典型例题|Worked example)$/}).count(), 0,
      'Worked examples are now exercises rather than an embedded concept section');
    let checkedChineseProbe = false;
    for (const language of ['zh-CN', 'en', 'zh-CN']) {
      await languageChoice(page, language); await setTheme(page, 'light');
      assert.equal(await page.locator('#conceptSearch').inputValue(), data.concept.query, 'Language change preserves bilingual search');
      assert.equal(await page.locator('#conceptList .concept-item.active').getAttribute('data-concept-id'), data.concept.id, 'Language change preserves the selected concept');
      await assertContent(page, 'concepts', data.concept.id, language, references[language + '/light']);
      if (language === 'en') {
        const count = await page.locator('#conceptList .concept-item').count();
        assert.equal(await page.locator('#conceptCount').textContent(), count + (count === 1 ? ' concept' : ' concepts'), 'English filtered counters use the correct singular/plural');
      }
      if (language === 'en' && process.env.OFFLINE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/study-' + width + '-concept-en.png' });
      if (language === 'en' || !checkedChineseProbe) for (const theme of themes) {
        await setTheme(page, theme); await formatProbe(page, references[language + '/' + theme]);
      }
      if (language === 'zh-CN') checkedChineseProbe = true;
    }
    // Broad overviews keep their concept hierarchy; their practice links now
    // live on the corresponding graph topic. Follow that real navigation while
    // retaining the original migrated example's full CN/EN source and math.
    assert.equal(await page.locator('#conceptDetail .concept-related-exercises').count(), 0,
      'An overview has no duplicated related-exercise section');
    await page.locator('#conceptDetail .concept-graph-module [data-graph-node-id="' + data.concept.graphNodeId + '"]').click();
    await page.locator('#graphPanel').waitFor({state:'visible'});
    await page.waitForFunction(id => document.querySelector('#knowledgeGraphCanvas .selected[data-node-id]')?.dataset.nodeId === id,
      data.concept.graphNodeId);
    if (await page.locator('#knowledgeGraphModal').evaluate(node => node.classList.contains('graph-fullscreen-view'))) {
      await page.locator('#knowledgeGraphModal .kg-mobile-expand').click();
      await settle(page);
    }
    const learning = page.locator('#knowledgeGraphDetail .offline-graph-learning-links');
    assert.equal(await learning.locator('.graph-parent-concept [data-concept-id="' + data.concept.id + '"]').count(), 1,
      'The graph footer links back to the exact overview whose example was migrated');
    await learning.locator('.graph-related-exercises [data-question-id="' + data.example.id + '"]').click();
    await page.locator('#questionsPanel').waitFor({state:'visible'});
    assert.equal(await page.locator('#questionList .question-item.active').getAttribute('data-question-id'), data.example.id);
    await page.locator('#questionDetail .question-actions button').click();
    for (const language of ['en', 'zh-CN']) {
      await languageChoice(page, language); await setTheme(page, 'light');
      await assertContent(page, 'questions', data.example.id, language, references[language + '/light']);
      assert.equal(await page.evaluate(({conceptId, language}) => {
        const concept = studyPacks.concepts.find(row => row.id === conceptId);
        const source = language === 'en' ? studyPacks.en.concepts[conceptId].example : concept.example;
        return studyInputs.get(document.querySelector('#questionDetail .wrong-answer-inner'))
          === DMateMathMarkdown.prepareStudyText(source);
      }, {conceptId:data.example.conceptId, language}), true, 'The original worked example is rendered in the exercise answer');
    }
    await setTheme(page, 'light'); await navigation(page, 'questions');
    for (const [index, question] of data.questions.entries()) {
      await page.locator('#questionCategory').selectOption(question.category);
      await page.locator('#questionDifficulty').selectOption(question.difficulty);
      await page.locator('#questionList [data-question-id="' + question.id + '"]').click();
      await page.locator('#questionDetail .question-actions button').click();
      for (const language of ['en', 'zh-CN']) {
        await languageChoice(page, language); await setTheme(page, 'light');
        assert.equal(await page.locator('#questionCategory').inputValue(), question.category, 'Language change preserves the chapter filter');
        assert.equal(await page.locator('#questionDifficulty').inputValue(), question.difficulty, 'Language change preserves the difficulty filter');
        assert.equal(await page.locator('#questionList .question-item.active').getAttribute('data-question-id'), question.id, 'Language change preserves the selected exercise');
        assert.equal(await page.locator('#questionDetail .answer-panel').count(), 1, 'Language change preserves the open answer');
        if (language === 'en') {
          const count = await page.locator('#questionList .question-item').count();
          assert.equal(await page.locator('#questionCount').textContent(), count + (count === 1 ? ' exercise' : ' exercises'));
        }
        await assertContent(page, 'questions', question.id, language, references[language + '/light']);
        if (index === 0) {
          await plainOptions(page);
          if (process.env.OFFLINE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/study-' + width + '-options-' + language + '.png' });
        }
      }
    }
    if (process.env.OFFLINE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/study-' + width + '-cn.png' });
    await languageChoice(page, 'en');
    if (process.env.OFFLINE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.OFFLINE_SCREENSHOT_DIR + '/study-' + width + '-en.png' });
    await page.waitForFunction(() => new Promise(resolve => {
      const request = indexedDB.open('dmate-offline-workspace');
      request.onerror = () => resolve(false);
      request.onsuccess = () => {
        const db = request.result, get = db.transaction('settings', 'readonly').objectStore('settings').get('language');
        get.onsuccess = () => { const saved = get.result?.value === 'en'; db.close(); resolve(saved); };
        get.onerror = () => { db.close(); resolve(false); };
      };
    }));
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
    assert.equal(await page.locator('html').getAttribute('data-ui-language'), 'en', 'The English preference survives a true offline reload');
    if (width === 1440) { await packs(page); await corpusPreflight(page); }
    assert.equal(page.modelCalls, 0); assert.deepEqual(page.studyErrors, []);
    console.log('PASS offline study ' + width + ': ' + data.counts.concepts + ' concepts/' + data.counts.questions
      + ' exercises including ' + data.counts.examples + ' migrated examples; complete bilingual source/Markdown/MathJax; plain options; preserved selection/search/filters/open answers; fresh ' + cache.name + ' offline reload and language persistence');
  } finally { await context.close(); if (workerProtocol) await workerProtocol.detach().catch(() => {}); }
}

(async () => {
  if (process.env.OFFLINE_SCREENSHOT_DIR) require('node:fs').mkdirSync(process.env.OFFLINE_SCREENSHOT_DIR, { recursive: true });
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try { for (const width of [1440, 390]) await run(browser, width); }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
