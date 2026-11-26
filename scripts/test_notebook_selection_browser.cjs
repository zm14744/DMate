/* Selection-bound notebook relationship analysis, without AI calls. */
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
        { id: 'gamma', title: '另外的环概念', content: '环的加法、乘法与分配律。', updatedAt: 3 },
        { id: 'blank', title: '', content: '', updatedAt: 4 }
      ], deleted: {} };
      initializeConceptNotebook(); window.dmateConceptNotebook.open();
    }, theme);
    const dialog = page.locator('#conceptNotebookDialog');
    assert.equal(await dialog.getByLabel('条目内容', {exact:true}).count(), 1,
      'The online concept editor exposes its current content label');
    const relations = dialog.locator('.dcn-relation-trigger');
    const panel = dialog.locator('.dcn-analysis-panel');
    const submit = panel.locator('.dcn-analysis-submit');
    const checkbox = id => dialog.locator('.dcn-note[data-note-id="' + id + '"] input[type="checkbox"]');
    await dialog.waitFor({ state: 'visible' });
    assert.equal(await relations.innerText(), '分析关联');
    assert.equal(await dialog.getByRole('button', { name: /AI\s*解释/ }).count(), 0);
    assert.equal(await panel.isVisible(), false);
    assert.equal(await relations.isDisabled(), true);
    await relations.dispatchEvent('click');
    assert.equal(await panel.isVisible(), false);
    assert.equal(await count(), 0);

    await checkbox('beta').check();
    await dialog.locator('.dcn-note[data-note-id="alpha"] .dcn-note-open').click();
    assert.equal(await dialog.locator('.dcn-title').inputValue(), '当前打开的群概念');
    assert.equal(await relations.isDisabled(), true);
    await checkbox('gamma').check();
    await relations.click();
    await dialog.getByRole('dialog', { name: '分析关联', exact: true }).waitFor();
    assert.equal(await panel.getByRole('heading').count(), 0);
    const question = panel.getByRole('textbox', { name: '分析要求（可选）', exact: true });
    assert.equal(await question.inputValue(), '');

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

    await submit.click();
    await panel.getByText('mock relations beta,gamma', { exact: true }).waitFor();
    const payload = await page.evaluate(() => notebookSelectionProbe.requests[0].payload);
    assert.equal(payload.action, 'relations');
    assert.equal(payload.question, '', 'Analysis accepts an empty optional request');
    assert.deepEqual(payload.notes, [
      { id: 'beta', title: '真正选中的格概念', content: '格中每对元素有唯一交与并。' },
      { id: 'gamma', title: '另外的环概念', content: '环的加法、乘法与分配律。' }
    ], 'Only the checked entries are submitted, independently of the open editor');

    const beginPending = async () => {
      if (!await panel.isVisible()) await relations.click();
      const index = await count();
      await page.evaluate(() => { notebookSelectionProbe.holdNext = true; });
      await submit.click();
      await page.waitForFunction(index => notebookSelectionProbe.requests[index]?.waiting, index);
      return index;
    };
    const releaseCanceled = async index => {
      const aborted = await page.evaluate(async index => {
        const entry = notebookSelectionProbe.requests[index];
        entry.release();
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        return entry.signal.aborted;
      }, index);
      assert.equal(aborted, true);
      assert.equal(await panel.locator('.dcn-results').textContent(), '', 'Canceled results stay cleared after a late reply');
    };
    await question.fill('比较二者的运算');
    const canceled = await beginPending();
    assert.equal(await page.evaluate(index => notebookSelectionProbe.requests[index].payload.question, canceled), '比较二者的运算');
    await panel.locator('.dcn-analysis-cancel').click();
    await releaseCanceled(canceled);

    const changed = await beginPending();
    await page.keyboard.press('Escape');
    await panel.waitFor({ state: 'hidden' });
    assert.equal(await page.evaluate(index => notebookSelectionProbe.requests[index].signal.aborted, changed), false,
      'Dismissing the popup while the notebook is open keeps the request available');
    await checkbox('gamma').uncheck();
    await releaseCanceled(changed);
    await checkbox('blank').check();
    if (!await panel.isVisible()) await relations.click();
    await submit.click();
    await panel.getByText('请先完善所选条目', { exact: true }).waitFor();
    assert.equal(await count(), 3, 'A selected blank entry is rejected before transport');
    await page.keyboard.press('Escape');
    await panel.waitFor({ state: 'hidden' });
    await checkbox('blank').uncheck();
    await checkbox('gamma').check();
    const closing = await beginPending();
    await dialog.locator('.dcn-heading > .dcn-close').click();
    await releaseCanceled(closing);
    assert.equal(await dialog.isVisible(), false);
    await page.evaluate(() => window.dmateConceptNotebook.open());
    assert.equal(await checkbox('beta').isChecked(), true);
    assert.equal(await checkbox('gamma').isChecked(), true);
    await relations.click();
    assert.equal(await panel.locator('.dcn-results').textContent(), '', 'Reopening does not restore stale output');
    assert.equal(await count(), 4);
    assert.deepEqual(errors, []);
    console.log('PASS ' + width + '/' + theme + ': relationship dialog, selected entries, optional request, cancellation, stale/close guards and input font parity');
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try { for (const width of [390, 1440]) await runCase(browser, width, 'dark'); }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
