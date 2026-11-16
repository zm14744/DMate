/* Exercise both wrong-question previews with real Markdown/MathJax and hold
 * completed renders to make stale completion races deterministic. No AI calls.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const original = '设集合 **A**，已知 $A = \\{1, 2\\}$。\n\n1. 求 $|A|$。\n2. 判断 $A \\subseteq A$。';
const other = '给定整数 $n$，求 $n+1$。';

async function ready(page, selector, text) {
  await page.waitForFunction(({ selector, text }) => {
    const preview = document.querySelector(selector);
    return preview && !preview.hasAttribute('aria-busy')
      && preview.querySelector('[data-dmate-render-state="ready"]')
      && preview.textContent.includes(text);
  }, { selector, text });
}

const paint = locator => locator.evaluate(node => {
  const css = getComputedStyle(node);
  return Object.fromEntries(['fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'color',
    'backgroundColor', 'borderTopWidth', 'borderTopColor', 'borderRadius'].map(key => [key, css[key]]));
});

async function holdNext(page, marker, textarea) {
  await page.evaluate(marker => { previewProbe.holds[marker] = true; }, marker);
  await page.locator(textarea).fill(marker);
  await page.waitForFunction(marker => previewProbe.waiting.includes(marker), marker);
}

async function release(page, marker) {
  await page.evaluate(async marker => {
    previewProbe.release[marker]();
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  }, marker);
}

async function runCase(browser, width) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block',
    ...(width <= 1100 ? { isMobile: true, hasTouch: true } : {}) });
  const page = await context.newPage(), errors = [], modelRequests = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/auth/me', route => route.fulfill({ contentType: 'application/json',
    body: '{"configured":true,"authenticated":false}' }));
  for (const endpoint of ['**/chat', '**/analyze-questions']) {
    await page.route(endpoint, route => {
      modelRequests.push(route.request().url());
      return route.fulfill({ contentType: 'application/json', body: '{"results":[]}' });
    });
  }
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await page.waitForFunction(() => typeof openWrongEdit === 'function' && Boolean(window.DMateAIAnswer));
    await page.evaluate(({ original, other }) => {
      const entry = (id, question) => ({ id, question, note: '原有笔记 ' + id, corrected: false,
        category: '集合论', relatedCategories: [], knowledgePoints: ['集合运算'], focusPoints: [],
        difficulty: '简单', classificationVersion: 3, answer: '参考答案', createdAt: 1, updatedAt: 1 });
      learningState = normalizeLearningState({ version: 9, wrongQuestions: [
        entry('preview-a', original), entry('preview-b', other)
      ] });
      window.previewProbe = { holds: {}, waiting: [], release: {} };
      const renderer = window.DMateAIAnswer.render;
      window.DMateAIAnswer.render = async function(target, source, options) {
        const result = await renderer.call(this, target, source, options);
        const marker = Object.keys(previewProbe.holds).find(marker => String(source).includes(marker));
        if (result && marker) {
          delete previewProbe.holds[marker];
          await new Promise(resolve => {
            previewProbe.release[marker] = resolve;
            previewProbe.waiting.push(marker);
          });
        }
        return result;
      };
    }, { original, other });

    await page.evaluate(text => openWrongSafePreview({ text }), original);
    await ready(page, '#wrongSafePreview', '设集合');
    assert.equal(await page.locator('#wrongSafeProgress').isVisible(), false);
    assert.equal(await page.locator('#wrongSafeProgress').textContent(), '');
    assert.equal((await page.locator('#wrongSafeModal').innerText()).includes('请确认下面就是要保存的题目'), false);
    assert.ok(await page.locator('#wrongSafePreview mjx-container').count(), 'Safe preview typesets math');
    assert.equal(await page.locator('#wrongSafePreview strong').count(), 1);
    const safeBox = await paint(page.locator('#wrongSafePreview'));
    const safeText = await paint(page.locator('#wrongSafePreview .wrong-safe-rendered'));
    const safeLabel = await paint(page.locator('#wrongSafePreviewLabel'));
    await page.evaluate(() => closeWrongSafePreview());
    await page.evaluate(() => openWrongSafePreview([{ text: '求 $1+1$。' }, { text: '求 $2+2$。' }]));
    assert.equal(await page.locator('#wrongSafeProgress').innerText(), '第 1 / 2 道');
    assert.equal(await page.locator('#wrongSafeProgress').isVisible(), true);
    await page.evaluate(() => closeWrongSafePreview());

    await page.evaluate(() => openWrongEdit('preview-a'));
    await ready(page, '#wrongEditPreview', '设集合');
    assert.equal(await page.locator('label[for="wrongEditQuestion"]').innerText(), '编辑题目');
    assert.equal(await page.locator('#wrongEditPreviewLabel').innerText(), '题目预览');
    assert.deepEqual(await paint(page.locator('#wrongEditPreview')), safeBox);
    assert.deepEqual(await paint(page.locator('#wrongEditPreview .wrong-safe-rendered')), safeText);
    assert.deepEqual(await paint(page.locator('#wrongEditPreviewLabel')), safeLabel);
    assert.ok(await page.locator('#wrongEditPreview mjx-container').count(), 'Edit preview uses the same math renderer');
    assert.equal(await page.locator('#wrongEditPreview strong').count(), 1);
    assert.equal(await page.locator('#wrongEditPreview').evaluate(node => node.isContentEditable), false);
    assert.equal(await page.locator('#wrongEditPreview input, #wrongEditPreview textarea').count(), 0);
    assert.ok(await page.evaluate(() => Boolean(document.getElementById('wrongEditPreview')
      .compareDocumentPosition(document.getElementById('wrongEditQuestion')) & Node.DOCUMENT_POSITION_FOLLOWING)),
    'The rendered preview appears above the editable source');
    assert.equal(await page.locator('#wrongEditQuestion').inputValue(), original);
    assert.equal(await page.locator('#wrongEditNote').inputValue(), '原有笔记 preview-a');

    await page.locator('#wrongEditQuestion').fill('求 **安全预览** $1+1$。<script>window.previewInjected=true</script><img onerror="window.previewInjected=true"><a href="javascript:window.previewInjected=true">链接</a>');
    await ready(page, '#wrongEditPreview', '安全预览');
    assert.equal(await page.locator('#wrongEditPreview script, #wrongEditPreview [onerror], #wrongEditPreview [href^="javascript:"]').count(), 0);
    assert.equal(await page.evaluate(() => Boolean(window.previewInjected)), false);
    await page.locator('#wrongEditQuestion').fill('过时的连续输入');
    await page.locator('#wrongEditQuestion').fill('最新连续输入：求 $3+3$。');
    await ready(page, '#wrongEditPreview', '最新连续输入');
    assert.equal((await page.locator('#wrongEditPreview').innerText()).includes('过时的连续输入'), false);

    await holdNext(page, '旧稿迟到：求 $4+4$。', '#wrongEditQuestion');
    await page.locator('#wrongEditQuestion').fill('新稿完成：求 $5+5$。');
    await ready(page, '#wrongEditPreview', '新稿完成');
    await release(page, '旧稿迟到：求 $4+4$。');
    assert.equal((await page.locator('#wrongEditPreview').innerText()).includes('旧稿迟到'), false);

    await holdNext(page, '切换前迟到：求 $6+6$。', '#wrongEditQuestion');
    await page.evaluate(() => openWrongEdit('preview-b'));
    await ready(page, '#wrongEditPreview', '给定整数');
    await release(page, '切换前迟到：求 $6+6$。');
    assert.equal((await page.locator('#wrongEditPreview').innerText()).includes('切换前迟到'), false);
    assert.equal(await page.locator('#wrongEditQuestion').inputValue(), other);
    await holdNext(page, '关闭前迟到：求 $7+7$。', '#wrongEditQuestion');
    await page.locator('#wrongEditClose').click();
    await page.evaluate(() => openWrongEdit('preview-a'));
    await ready(page, '#wrongEditPreview', '设集合');
    await release(page, '关闭前迟到：求 $7+7$。');
    assert.equal((await page.locator('#wrongEditPreview').innerText()).includes('关闭前迟到'), false);

    const saved = '保存中的新题：求 $8+8$。';
    await holdNext(page, saved, '#wrongEditQuestion');
    await page.locator('#wrongEditNote').fill('保存后的笔记');
    await page.locator('#wrongEditSave').click();
    assert.equal(await page.locator('#wrongEditModal').isVisible(), false);
    await page.evaluate(() => openWrongEdit('preview-b'));
    await ready(page, '#wrongEditPreview', '给定整数');
    await release(page, saved);
    assert.equal((await page.locator('#wrongEditPreview').innerText()).includes('保存中的新题'), false);
    assert.deepEqual(await page.evaluate(() => learningState.wrongQuestions.map(item => [item.question, item.note])),
      [[saved, '保存后的笔记'], [other, '原有笔记 preview-b']], 'Save modifies only the edited record and keeps notes');
    await page.evaluate(() => { closeWrongEdit(); openWrongSafePreview({ text: '求 $9+9$。' }); });
    await ready(page, '#wrongSafePreview', '求');
    await holdNext(page, '安全页迟到：求 $10+10$。', '#wrongSafeQuestion');
    await page.evaluate(() => { closeWrongSafePreview(); openWrongSafePreview({ text: '新的安全页：求 $11+11$。' }); });
    await ready(page, '#wrongSafePreview', '新的安全页');
    await release(page, '安全页迟到：求 $10+10$。');
    assert.equal((await page.locator('#wrongSafePreview').innerText()).includes('安全页迟到'), false);
    assert.deepEqual(modelRequests, [], 'Editing and previewing never request AI output');
    assert.deepEqual(errors, [], 'No browser script errors');
    console.log('PASS ' + width + ': shared safe/edit previews, Markdown/math sanitization, latest edit wins across switch/close/save');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const width of [390, 1440]) await runCase(browser, width);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
