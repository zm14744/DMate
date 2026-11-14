/* Start Flask first. These browser regressions serve local SSE fixtures only;
 * no model or external service is called.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const reply = '完整回答与 <b>原文</b> 应保留。';

async function withPage(browser, run, { networkFailure = false, finalOnly = false, replyText = reply } = {}) {
  const page = await browser.newPage();
  let posts = 0;
  await page.route('**/chat', route => {
    posts++;
    const sse = (finalOnly ? '' : 'event: delta\ndata: ' + JSON.stringify({ text: replyText }) + '\n\n')
      + 'event: final\ndata: ' + JSON.stringify({ reply: replyText }) + '\n\n';
    return networkFailure ? route.abort('connectionfailed')
      : route.fulfill({ status: 200, contentType: 'text/event-stream', body: sse });
  });
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await page.evaluate(() => {
      newChat();
      const session = getCurrent();
      session.messages.push({ role: 'user', text: '你好' });
      renderChat();
    });
    await run(page, () => posts);
  } finally { await page.close(); }
}

async function failedFormatting(browser, kind, finalOnly) {
  await withPage(browser, async (page, posts) => {
    const result = await page.evaluate(async kind => {
      const original = kind === 'formatter' ? markdownToHtml : renderMath;
      let failed = false;
      if (kind === 'formatter') {
        // A formatter may remain unavailable after its first initialization error.
        markdownToHtml = () => { throw new Error('Formatting initialization failed'); };
      } else {
        renderMath = target => {
          if (!failed) { failed = true; throw new Error('First typeset initialization failed'); }
          return original(target);
        };
      }
      let first;
      try { first = await requestAiReply(getCurrent()); }
      finally {
        if (kind === 'formatter') markdownToHtml = original;
        else renderMath = original;
      }
      const firstMessages = getCurrent().messages.map(message => ({
        role: message.role, text: message.text, error: message.isError === true
      }));
      const rendered = document.querySelector('.msg.ai .ai-content');
      const firstVisible = rendered?.textContent;
      const injectedMarkup = Boolean(rendered?.querySelector('b'));
      getCurrent().messages.push({ role: 'user', text: '再次你好' });
      const second = await requestAiReply(getCurrent());
      return { first, second, firstMessages, firstVisible, injectedMarkup,
        answers: getCurrent().messages.filter(message => message.role === 'ai').map(message => message.text),
        busy: isSessionBusy(currentId) };
    }, kind);
    assert.equal(result.first.status, 'success', kind + ': the first valid reply survives formatting failure');
    assert.deepEqual(result.firstMessages, [
      { role: 'user', text: '你好', error: false }, { role: 'ai', text: reply, error: false }
    ]);
    assert.equal(result.firstVisible, reply, kind + ': the whole reply is visible immediately');
    assert.equal(result.injectedMarkup, false, kind + ': fallback treats reply markup as text');
    assert.equal(result.second.status, 'success');
    assert.deepEqual(result.answers, [reply, reply]);
    assert.equal(result.busy, false);
    assert.equal(posts(), 2, kind + ': two explicit requests make exactly two POSTs');
    console.log('PASS ' + kind + (finalOnly ? '/final-only' : '/deltas')
      + ': first reply retained safely, next request succeeds, no automatic retry');
  }, { finalOnly });
}

async function cancelledFormatting(browser, rejects) {
  await withPage(browser, async (page, posts) => {
    await page.evaluate(() => {
      const original = renderMath;
      window.chatFinalizationFixture = { original, waiting: false };
      renderMath = target => {
        const fixture = window.chatFinalizationFixture;
        if (target.classList.contains('reply-render-stage')) {
          fixture.waiting = true;
          return new Promise((resolve, reject) => { fixture.resolve = resolve; fixture.reject = reject; });
        }
        return original(target);
      };
      window.chatFinalizationFixture.result = requestAiReply(getCurrent());
    });
    await page.waitForFunction(() => window.chatFinalizationFixture.waiting);
    const result = await page.evaluate(async rejects => {
      const fixture = window.chatFinalizationFixture;
      const request = activeAiRequests.get(sessionBusyKey(currentId));
      request.cancelled = true;
      request.controller.abort();
      if (rejects) fixture.reject(new Error('Formatting failed after cancellation'));
      else fixture.resolve();
      const result = await fixture.result;
      renderMath = fixture.original;
      return { result, messages: getCurrent().messages.map(message => message.role),
        busy: isSessionBusy(currentId), preview: Boolean(document.querySelector('.chat-stream-preview')) };
    }, rejects);
    assert.equal(result.result.status, 'cancelled');
    assert.deepEqual(result.messages, ['user'], 'cancellation prevents the final reply from being committed');
    assert.equal(result.busy, false);
    assert.equal(result.preview, false);
    assert.equal(posts(), 1);
    console.log('PASS cancellation during finalization' + (rejects ? ' with late formatting failure' : ''));
  });
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const finalOnly of [false, true]) for (const kind of ['typeset', 'formatter']) {
      await failedFormatting(browser, kind, finalOnly);
    }
    for (const rejects of [false, true]) await cancelledFormatting(browser, rejects);
    await withPage(browser, async (page, posts) => {
      const result = await page.evaluate(async () => {
        const result = await requestAiReply(getCurrent());
        forceCompleteTyping();
        return { result, messages: getCurrent().messages.map(message => ({
          role: message.role, error: message.isError === true, text: message.text
        })), busy: isSessionBusy(currentId) };
      });
      assert.equal(result.result.status, 'error');
      assert.equal(result.messages.length, 2);
      assert.equal(result.messages[1].error, true);
      assert.match(result.messages[1].text, /网络连接失败/);
      assert.equal(result.busy, false);
      assert.equal(posts(), 1, 'a real connection failure is not silently retried');
      console.log('PASS connection failure still reports a request error');
    }, { networkFailure: true });
    const mathReply = '因为 $2k^2+2k$ 是整数，所以 $n^2$ 是奇数。证毕。 □';
    await withPage(browser, async (page, posts) => {
      const result = await page.evaluate(async () => {
        const result = await requestAiReply(getCurrent());
        return { result, answer: getCurrent().messages.find(message => message.role === 'ai')?.text,
          busy: isSessionBusy(currentId) };
      });
      assert.equal(result.result.status, 'success');
      assert.equal(result.answer, mathReply, 'the original completed response remains in message history');
      assert.equal(result.busy, false);
      assert.equal(posts(), 1);
      await page.waitForSelector('.msg.ai mjx-container');
      assert.equal(await page.locator('.msg.ai mjx-container').count(), 2);
      assert.equal(await page.locator('.msg.ai mjx-merror, .msg.ai [data-mml-node="merror"]').count(), 0);
      assert.equal(await page.locator('.msg.ai .math-render-fallback').count(), 0,
        'the normal first reply uses the real formatter and MathJax');
      assert.doesNotMatch(await page.locator('.msg.ai .ai-content').textContent(), /[□■▢▣◻◼]/u);
      console.log('PASS first final-only mathematical reply: real MathJax, no merror or trailing proof square');
    }, { finalOnly: true, replyText: mathReply });
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
