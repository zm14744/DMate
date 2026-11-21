/* Selection-bound explanations and notebook input typography, without AI calls. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';

function installNotebookTransport() {
  const original = window.fetch.bind(window);
  const probe = window.notebookSelectionProbe = { requests: [], holdNext: false };
  window.fetch = (input, init = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    if (url.pathname !== '/notebook/analyze') return original(input, init);
    const payload = JSON.parse(init.body), hold = probe.holdNext;
    probe.holdNext = false;
    const response = { ok: true, action: payload.action,
      explanations: payload.notes.map(note => ({ note_id: note.id, explanation: '解释 ' + note.id })),
      relations: payload.action === 'relations' ? [{ from: payload.notes[0].id, to: payload.notes[1].id,
        type: '比较', explanation: '只分析选中的概念。' }] : [],
      summary: 'mock ' + payload.action + ' ' + payload.notes.map(note => note.id).join(',') };
    const entry = { payload, signal: init.signal, waiting: false };
    probe.requests.push(entry);
    return Promise.resolve({ ok: true, json: () => {
      if (!hold) return Promise.resolve(response);
      entry.waiting = true;
      // Deliberately finish JSON after cancellation to check the stale-result
      // guard as well as the transport's AbortSignal.
      return new Promise(resolve => { entry.release = () => resolve(response); });
    } });
  };
}

async function runCase(browser, width, theme) {
  const context = await browser.newContext({ viewport: { width, height: 950 }, serviceWorkers: 'block',
    reducedMotion: 'reduce', ...(width <= 1100 ? { isMobile: true, hasTouch: true } : {}) });
  await context.addInitScript(installNotebookTransport);
  const page = await context.newPage(), errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/auth/me', route => route.fulfill({ contentType: 'application/json',
    body: '{"configured":true,"authenticated":false}' }));
  for (const path of ['**/chat', '**/conversation/title', '**/analyze-questions']) await page.route(path, route => route.abort());
  const count = () => page.evaluate(() => notebookSelectionProbe.requests.length);
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await page.evaluate(theme => {
      appearanceSettings.mode = theme; applyAppearanceSettings({ save: false });
      learningState.conceptNotebook = { notes: [
        { id: 'alpha', title: '当前打开的群概念', content: '群的原始笔记。', updatedAt: 1 },
        { id: 'beta', title: '真正选中的格概念', content: '格中每对元素有唯一交与并。', updatedAt: 2 },
        { id: 'gamma', title: '另外的环概念', content: '环的加法、乘法与分配律。', updatedAt: 3 }
      ], deleted: {} };
      initializeConceptNotebook(); window.dmateConceptNotebook.open();
    }, theme);
    const dialog = page.locator('#conceptNotebookDialog');
    assert.equal(await dialog.getByLabel('概念内容', {exact:true}).count(), 1,
      'The online concept editor exposes its current content label');
    const explain = dialog.locator('.dcn-ai-actions > .dcn-primary');
    const relations = dialog.locator('.dcn-ai-actions > button').nth(1);
    const checkbox = id => dialog.locator('.dcn-note[data-note-id="' + id + '"] input[type="checkbox"]');
    await dialog.waitFor({ state: 'visible' });

    for (const scale of [1, 1.2]) {
      const fonts = await page.evaluate(scale => {
        document.documentElement.style.setProperty('--font-scale', String(scale));
        const paint = node => Object.fromEntries(['fontFamily', 'fontSize', 'fontWeight', 'fontStyle', 'lineHeight']
          .map(key => [key, getComputedStyle(node)[key]]));
        return { expected: paint(document.getElementById('wrongEditNote')),
          inputs: ['.dcn-title', '.dcn-original', '.dcn-question'].map(selector => paint(document.querySelector(selector))),
          labelWeight: getComputedStyle(document.querySelector('.dcn-title').parentElement).fontWeight };
      }, scale);
      const {lineHeight: wrongBookLineHeight, ...wrongBookFont} = fonts.expected;
      assert.equal(wrongBookLineHeight, 'normal', 'Wrong-book notes use the default line height');
      for (const {lineHeight, ...font} of fonts.inputs) {
        assert.deepEqual(font, wrongBookFont, 'Notebook and wrong-book fonts match at scale ' + scale);
        assert.ok(Math.abs(parseFloat(lineHeight) - 1.5 * parseFloat(font.fontSize)) < 0.01,
          'Autosizing notebook fields use 1.5 line spacing at scale ' + scale);
      }
      assert.equal(wrongBookFont.fontWeight, '400');
      assert.equal(fonts.labelWeight, '600', 'Label emphasis stays separate from editable text');
    }
    await page.evaluate(() => document.documentElement.style.removeProperty('--font-scale'));

    assert.equal(await explain.isEnabled(), false);
    assert.equal(await relations.isEnabled(), false);
    await explain.dispatchEvent('click');
    assert.equal(await count(), 0, 'A forced click with no selection cannot call AI');

    await checkbox('beta').check();
    await dialog.locator('.dcn-note[data-note-id="alpha"] .dcn-note-open').click();
    assert.equal(await dialog.locator('.dcn-title').inputValue(), '当前打开的群概念');
    assert.equal(await explain.isEnabled(), true);
    assert.equal(await relations.isEnabled(), false);
    await explain.click();
    await page.waitForFunction(() => document.querySelector('.dcn-results').textContent.includes('解释 beta'));
    const payload = await page.evaluate(() => notebookSelectionProbe.requests[0].payload);
    assert.equal(payload.action, 'explain');
    assert.deepEqual(payload.notes, [{ id: 'beta', title: '真正选中的格概念', content: '格中每对元素有唯一交与并。' }],
      'Explain sends the selected concept, independently of the open editor');
    assert.equal(await checkbox('beta').isChecked(), true);

    await checkbox('gamma').check();
    assert.equal(await explain.isEnabled(), false, 'Multiple selections cannot enable AI explanation');
    assert.equal(await relations.isEnabled(), true, 'Relationship analysis still accepts multiple selections');
    await explain.dispatchEvent('click');
    assert.equal(await count(), 1, 'Even a forced multi-selection explain event is rejected before transport');
    await relations.click();
    await page.waitForFunction(() => document.querySelector('.dcn-results').textContent.includes('mock relations beta,gamma'));
    assert.deepEqual(await page.evaluate(() => notebookSelectionProbe.requests[1].payload.notes.map(note => note.id)), ['beta', 'gamma']);

    await checkbox('beta').uncheck();
    assert.equal(await explain.isEnabled(), true);
    await page.evaluate(() => { notebookSelectionProbe.holdNext = true; });
    await explain.click();
    await page.waitForFunction(() => notebookSelectionProbe.requests[2]?.waiting);
    assert.equal(await explain.isEnabled(), false);
    await checkbox('gamma').uncheck();
    await checkbox('beta').check();
    assert.equal(await page.evaluate(() => notebookSelectionProbe.requests[2].signal.aborted), true);
    await page.evaluate(async () => {
      notebookSelectionProbe.requests[2].release();
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    });
    assert.equal(await dialog.locator('.dcn-results').innerText(), '', 'An old selection cannot publish a late explanation');
    assert.equal(await explain.isEnabled(), true);

    await page.evaluate(() => { notebookSelectionProbe.holdNext = true; });
    await explain.click();
    await page.waitForFunction(() => notebookSelectionProbe.requests[3]?.waiting);
    await dialog.locator('.dcn-heading > .dcn-close').click();
    await page.evaluate(async () => {
      notebookSelectionProbe.requests[3].release();
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    });
    assert.equal(await page.evaluate(() => notebookSelectionProbe.requests[3].signal.aborted), true);
    assert.equal(await dialog.isVisible(), false);
    await page.evaluate(() => window.dmateConceptNotebook.open());
    assert.equal(await checkbox('beta').isChecked(), true, 'Closing and reopening retains the selected concept');
    assert.equal(await explain.isEnabled(), true);
    assert.equal(await dialog.locator('.dcn-results').innerText(), '', 'A closed request never restores stale output');
    assert.equal(await count(), 4);
    assert.deepEqual(errors, []);
    console.log('PASS ' + width + '/' + theme + ': exact-one explanation, selected-source payload, multi-note relations, stale/close guards and wrong-book font parity');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try { for (const width of [390, 1440]) for (const theme of ['dark', 'light', 'navy']) await runCase(browser, width, theme); }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
