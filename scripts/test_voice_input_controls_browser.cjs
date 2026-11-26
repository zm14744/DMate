/* Exercise the actual composer with deterministic capture and delayed speech
 * responses. No microphone permission or model endpoint is used. */
'use strict';
const assert = require('node:assert/strict');
const { mkdirSync } = require('node:fs');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';

function installVoiceProbe() {
  const nativeFetch = window.fetch.bind(window);
  const probe = window.voiceControlsProbe = { stopped: 0, closed: 0, chooserClicks: 0,
    requests: [], pending: [], holdPermission: false, requestAborts: 0 };
  const makeStream = () => ({ getTracks: () => [{ stop: () => { probe.stopped++; } }] });
  const devices = { getUserMedia: () => probe.holdPermission
    ? new Promise(resolve => probe.pending.push(() => resolve(makeStream()))) : Promise.resolve(makeStream()) };
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: devices });
  class Audio {
    constructor() { this.sampleRate = 16000; this.state = 'suspended'; this.destination = {}; }
    createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
    createGain() { return { gain: { value: 0 }, connect() {}, disconnect() {} }; }
    createScriptProcessor() { return this.processor = { connect() {}, disconnect() {}, onaudioprocess: null }; }
    resume() {
      this.state = 'running';
      this.timer = setInterval(() => this.processor?.onaudioprocess?.({ inputBuffer: {
        getChannelData: () => Float32Array.from({ length: 1024 }, (_, index) => Math.sin(index / 10) / 8)
      } }), 20);
      return Promise.resolve();
    }
    close() { clearInterval(this.timer); this.state = 'closed'; probe.closed++; return Promise.resolve(); }
  }
  window.AudioContext = Audio;
  window.fetch = (input, options) => {
    if (String(input).includes('/voice/transcribe')) {
      return new Promise(resolve => {
        options.signal.addEventListener('abort', () => { probe.requestAborts++; });
        // Keep the cancelled request resolvable too, to verify that a service
        // returning after cancellation cannot overwrite the draft/new capture.
        probe.requests.push({ audio: options.body.get('audio'), signal: options.signal,
          respond: text => resolve(new Response(JSON.stringify({ ok: true, text }), {
            status: 200, headers: { 'Content-Type': 'application/json' }
          })) });
      });
    }
    return nativeFetch(input, options);
  };
  addEventListener('DOMContentLoaded', () => document.getElementById('imageInput').addEventListener('click', () => { probe.chooserClicks++; }));
}

async function settle(page) {
  await page.evaluate(async () => {
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    await Promise.all(document.getAnimations().filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity)
      .map(animation => animation.finished.catch(() => {})));
  });
}

const paint = locator => locator.evaluate(node => {
  const css = getComputedStyle(node), rect = node.getBoundingClientRect();
  return { width: Number(rect.width.toFixed(3)), height: Number(rect.height.toFixed(3)), background: css.backgroundColor,
    border: css.borderWidth, radius: css.borderRadius, padding: css.padding, shadow: css.boxShadow };
});

async function idle(page) {
  await page.waitForFunction(() => dmateVoiceInput.state === 'idle');
  await settle(page);
  assert.equal(await page.locator('#voiceCancelBtn').getAttribute('aria-hidden'), 'true');
  assert.equal(await page.locator('#voiceCancelBtn').isEnabled(), false);
  assert.equal(await page.locator('#voiceCancelBtn').evaluate(node => getComputedStyle(node).opacity), '0');
  assert.equal(await page.locator('#imageInput').isEnabled(), true);
  assert.equal(await page.locator('#imageBtn').evaluate(node => getComputedStyle(node).opacity), '1');
}

async function active(page, expected, reference) {
  await page.waitForFunction(state => dmateVoiceInput.state === state, expected);
  await settle(page);
  await page.mouse.move(0, 0);
  assert.deepEqual(await paint(page.locator('#voiceCancelBtn')), reference, 'Voice cancel is the same red circle as AI stop');
  assert.equal(await page.locator('#voiceCancelBtn').getAttribute('aria-label'), '取消语音输入');
  assert.equal(await page.locator('#voiceCancelBtn').getAttribute('aria-hidden'), 'false');
  assert.equal(await page.locator('#voiceCancelBtn').isEnabled(), true);
  assert.equal(await page.locator('#imageInput').isEnabled(), false, 'The real native file chooser stays disabled during voice input');
  assert.equal(await page.locator('#imageInput').getAttribute('aria-hidden'), 'true');
  assert.equal(await page.locator('#imageBtn').getAttribute('aria-hidden'), 'true');
  assert.equal(await page.locator('#imageBtn').evaluate(node => getComputedStyle(node).opacity), '0');
  assert.equal(await page.locator('#sendBtn').isEnabled(), false, 'Voice transcription does not send prematurely');
}

async function runCase(browser, width, theme, reducedMotion = 'no-preference') {
  const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion, serviceWorkers: 'block',
    ...(width <= 1100 ? { isMobile: true, hasTouch: true } : {}) });
  await context.addInitScript(installVoiceProbe);
  const page = await context.newPage(), errors = [], modelRequests = [], choosers = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('filechooser', chooser => { choosers.push(chooser); });
  await page.route('**/auth/me', route => route.fulfill({ contentType: 'application/json',
    body: JSON.stringify({ configured: true, authenticated: false }) }));
  for (const endpoint of ['**/chat', '**/analyze-questions']) await page.route(endpoint, route => {
    modelRequests.push(route.request().url()); return route.abort();
  });
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await page.waitForFunction(() => Boolean(window.dmateVoiceInput));
    await page.evaluate(theme => {
      appearanceSettings.mode = theme; applyAppearanceSettings({ save: false }); newChat();
      setSessionBusy(currentId, true);
    }, theme);
    const reference = await paint(page.locator('#sendBtn'));
    await page.evaluate(() => setSessionBusy(currentId, false));
    await page.locator('#text').fill('保留原有草稿');
    await idle(page);
    // Initial font/layout restoration may still be moving the composer. Start
    // the strict replacement check only after that independent motion settles.
    await page.evaluate(async () => { await document.fonts?.ready; });
    await page.waitForFunction(() => !document.querySelector('.center')?.hasAttribute('data-composer-motion'));
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const frame = () => page.locator('.input').evaluate(node => {
      const rect = node.getBoundingClientRect(); return [rect.x, rect.y, rect.width, rect.height];
    });
    const before = await frame();

    // Cancellation works while permission is still pending; a late granted
    // stream is stopped without starting a capture or opening Photos.
    await page.evaluate(() => { voiceControlsProbe.holdPermission = true; });
    await page.locator('#voiceInputBtn').click();
    await active(page, 'requesting', reference);
    if (process.env.VOICE_SCREENSHOT_DIR && theme === 'dark') await page.locator('.input').screenshot({ path: process.env.VOICE_SCREENSHOT_DIR + '/voice-active-' + width + '.png' });
    assert.deepEqual(await frame(), before, 'The replacement keeps composer geometry stable');
    await page.locator('#voiceCancelBtn').click();
    await idle(page);
    if (process.env.VOICE_SCREENSHOT_DIR && theme === 'dark') await page.locator('.input').screenshot({ path: process.env.VOICE_SCREENSHOT_DIR + '/voice-restored-' + width + '.png' });
    await page.evaluate(() => { voiceControlsProbe.pending.shift()(); voiceControlsProbe.holdPermission = false; });
    await page.waitForFunction(() => voiceControlsProbe.stopped === 1);
    assert.equal(await page.evaluate(() => voiceControlsProbe.requests.length), 0);
    assert.equal(await page.locator('#text').inputValue(), '保留原有草稿');
    assert.equal(choosers.length, 0, 'Cancelling must never trigger the file chooser');

    // Both directions animate while the same native input remains mounted.
    const transitions = await page.evaluate(async () => {
      const mic = document.getElementById('voiceInputBtn'), cancel = document.getElementById('voiceCancelBtn');
      const originalInput = document.getElementById('imageInput');
      voiceControlsProbe.holdPermission = true; mic.click();
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      const entering = cancel.getAnimations().length;
      for (const animation of cancel.getAnimations()) { animation.pause(); const timing = animation.effect.getComputedTiming(); animation.currentTime = (Number(timing.duration) + timing.delay) / 2; }
      await new Promise(resolve => requestAnimationFrame(resolve));
      const enterOpacity = Number(getComputedStyle(cancel).opacity), enterMatrix = new DOMMatrix(getComputedStyle(cancel).transform);
      const enterScale = Math.hypot(enterMatrix.a, enterMatrix.b);
      for (const animation of cancel.getAnimations()) animation.finish();
      cancel.click();
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      const leaving = cancel.getAnimations().length;
      for (const animation of cancel.getAnimations()) { animation.pause(); const timing = animation.effect.getComputedTiming(); animation.currentTime = (Number(timing.duration) + timing.delay) / 2; }
      await new Promise(resolve => requestAnimationFrame(resolve));
      const leaveOpacity = Number(getComputedStyle(cancel).opacity), leaveMatrix = new DOMMatrix(getComputedStyle(cancel).transform);
      const leaveScale = Math.hypot(leaveMatrix.a, leaveMatrix.b);
      for (const animation of cancel.getAnimations()) animation.finish();
      voiceControlsProbe.pending.shift()(); voiceControlsProbe.holdPermission = false;
      return { entering, leaving, enterOpacity, leaveOpacity, enterScale, leaveScale,
        sameInput: originalInput === document.getElementById('imageInput') };
    });
    assert.equal(transitions.sameInput, true);
    if (reducedMotion === 'reduce') assert.deepEqual([transitions.entering, transitions.leaving], [0, 0], 'Reduced motion skips the transition');
    else {
      assert.ok(transitions.entering > 0 && transitions.leaving > 0, 'Entry and cancellation both animate');
      for (const opacity of [transitions.enterOpacity, transitions.leaveOpacity]) assert.ok(opacity > 0 && opacity < 1, 'Both transitions have a real intermediate opacity');
      for (const scale of [transitions.enterScale, transitions.leaveScale]) assert.ok(scale > .55 && scale < 1, 'The visible circle smoothly scales in both directions');
    }
    await idle(page);

    // A second microphone click finishes capture and submits a valid WAV.
    await page.locator('#voiceInputBtn').click();
    await active(page, 'recording', reference);
    await page.locator('#voiceInputBtn').click();
    await active(page, 'transcribing', reference);
    assert.ok(await page.evaluate(() => voiceControlsProbe.closed > 0), 'Microphone capture closes before transcription');
    assert.equal(await page.evaluate(() => voiceControlsProbe.requests.length), 1);
    const wave = await page.evaluate(async () => {
      const audio = voiceControlsProbe.requests[0].audio, bytes = new Uint8Array(await audio.arrayBuffer());
      return { type: audio.type, size: audio.size, header: String.fromCharCode(...bytes.subarray(0, 4)),
        format: String.fromCharCode(...bytes.subarray(8, 12)) };
    });
    assert.equal(wave.type, 'audio/wav'); assert.equal(wave.header, 'RIFF'); assert.equal(wave.format, 'WAVE'); assert.ok(wave.size > 8000);
    await page.locator('#voiceCancelBtn').click();
    await idle(page);
    assert.equal(await page.evaluate(() => voiceControlsProbe.requestAborts), 1, 'Cancel aborts the transcription request');

    // Even a service resolving an aborted request cannot affect a new capture.
    await page.locator('#voiceInputBtn').click();
    await active(page, 'recording', reference);
    await page.evaluate(() => voiceControlsProbe.requests[0].respond('不应写入的旧识别'));
    await settle(page);
    assert.equal(await page.locator('#text').inputValue(), '保留原有草稿');
    assert.equal(await page.evaluate(() => dmateVoiceInput.state), 'recording');
    await page.locator('#voiceInputBtn').click();
    await active(page, 'transcribing', reference);
    await page.evaluate(() => voiceControlsProbe.requests[1].respond('新的识别内容'));
    await idle(page);
    assert.ok((await page.locator('#text').inputValue()).includes('新的识别内容'));
    assert.ok((await page.locator('#text').inputValue()).includes('保留原有草稿'));
    assert.equal(choosers.length, 0);

    // New-chat/account context changes cancel permission/capture immediately.
    await page.evaluate(() => { voiceControlsProbe.holdPermission = true; });
    await page.locator('#voiceInputBtn').click();
    await active(page, 'requesting', reference);
    await page.evaluate(() => newChat());
    await idle(page);
    await page.evaluate(() => { voiceControlsProbe.pending.shift()(); voiceControlsProbe.holdPermission = false; });
    await page.locator('#voiceInputBtn').click();
    await active(page, 'recording', reference);
    await page.evaluate(() => { accountState.authenticated = true; accountState.username = 'voice-context-only'; refreshInputAvailability(); });
    await idle(page);
    await page.evaluate(() => { accountState.authenticated = false; accountState.username = ''; });

    // Once restored, clicking the actual native input still opens the chooser.
    const chooser = page.waitForEvent('filechooser');
    await page.locator('#imageInput').click();
    await (await chooser).setFiles([]);
    assert.equal(choosers.length, 1);
    assert.equal(await page.evaluate(() => voiceControlsProbe.chooserClicks), 1);
    assert.deepEqual(modelRequests, [], 'No AI requests'); assert.deepEqual(errors, [], 'No script errors');
    if (process.env.VOICE_SCREENSHOT_DIR) await page.screenshot({ path: process.env.VOICE_SCREENSHOT_DIR + '/voice-controls-' + width + '-' + theme + '.png' });
    console.log('PASS ' + width + '/' + theme + '/' + reducedMotion + ': matching stop circle, reversible transitions, permission/capture/transcription cancellation, late-result safety and native chooser restoration');
  } finally { await context.close(); }
}

(async () => {
  if (process.env.VOICE_SCREENSHOT_DIR) mkdirSync(process.env.VOICE_SCREENSHOT_DIR, { recursive: true });
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for (const width of (process.env.DMATE_TEST_WIDTHS || '390,1440').split(',').map(Number))
      await runCase(browser, width, 'dark', process.env.DMATE_TEST_MOTION || 'no-preference');
    if (!process.env.DMATE_TEST_WIDTHS) await runCase(browser, 390, 'dark', 'reduce');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
