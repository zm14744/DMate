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

function visibleChatFormulaSource() {
  const chat=document.getElementById('chat'),found=[];
  const walker=document.createTreeWalker(chat,NodeFilter.SHOW_TEXT);
  for(let text;text=walker.nextNode();){
    const element=text.parentElement;
    if(!element||element.closest('mjx-container,script,style,textarea,input'))continue;
    let hidden=false,left=0,right=innerWidth,top=0,bottom=innerHeight;
    for(let node=element;node;node=node.parentElement){
      const css=getComputedStyle(node),rect=node.getBoundingClientRect();
      if(css.display==='none'||css.visibility==='hidden'||Number(css.opacity)===0){hidden=true;break;}
      if(/auto|scroll|hidden|clip/.test(css.overflowX)){left=Math.max(left,rect.left+node.clientLeft);right=Math.min(right,rect.left+node.clientLeft+node.clientWidth);}
      if(/auto|scroll|hidden|clip/.test(css.overflowY)){top=Math.max(top,rect.top+node.clientTop);bottom=Math.min(bottom,rect.top+node.clientTop+node.clientHeight);}
    }
    if(hidden)continue;
    for(const match of text.nodeValue.matchAll(/\\(?:frac|sqrt|sum|begin|\(|\[)|\$\$?/g)){
      const range=document.createRange();range.setStart(text,match.index);range.setEnd(text,match.index+match[0].length);
      if([...range.getClientRects()].some(rect=>Math.min(right,rect.right)>Math.max(left,rect.left)+1
        &&Math.min(bottom,rect.bottom)>Math.max(top,rect.top)+1))found.push(match[0]);
    }
  }
  return found;
}

async function historicalMathVisibility(browser,width) {
  const context=await browser.newContext({viewport:{width,height:900},serviceWorkers:'block',
    ...(width<=760?{isMobile:true,hasTouch:true}:{})});
  const page=await context.newPage(),modelCalls=[];
  let release,requested;
  const held=new Promise(resolve=>{release=resolve;}),started=new Promise(resolve=>{requested=resolve;});
  await page.route('**/static/vendor/mathjax-3.2.2/es5/tex-svg.js',async route=>{
    requested();await held;await route.continue();
  });
  await page.route('**/auth/me',route=>route.fulfill({contentType:'application/json',body:'{"configured":true,"authenticated":false}'}));
  await page.route(/\/(?:chat|conversation\/title|classify|analyze-questions|ocr)(?:\?|$)/,route=>{
    modelCalls.push(new URL(route.request().url()).pathname);return route.abort();
  });
  try{
    await page.goto(baseURL,{waitUntil:'networkidle'});
    await page.waitForFunction(()=>!accountVerificationOperation);
    await page.evaluate(()=>{
      const common={nameSource:'user',createdAt:1,updatedAt:1,deletedMessageIds:{},learningQuestion:null,teaching:null};
      sessions=[{...common,id:'historical-math',name:'已有公式对话',messages:[
        {messageId:'old-user-math',role:'user',text:'原题：\\(\\frac{1}{2}+\\frac{1}{2}=1\\)'},
        {messageId:'old-ai-math',role:'ai',text:'讲解：\\[\\sum_{k=1}^{n}k=\\frac{n(n+1)}2\\]'},
        {messageId:'old-prose',role:'ai',text:'这段普通讲解应该立即可见。'}
      ]},{...common,id:'empty-before-math',name:'空白对话',messages:[]}];
      currentId='empty-before-math';renderAll();
    });
    await page.locator(width<=760?'#mobileNavBtn':'#desktopSidebarOpen').click();
    await page.locator('.session[data-session-id="historical-math"] [data-session-name]').click();
    await page.waitForFunction(()=>currentId==='historical-math'&&!document.body.classList.contains('mobile-left-open'));
    await started;
    await page.evaluate(async()=>{await Promise.all(document.getAnimations().filter(animation=>
      animation.effect?.getComputedTiming().iterations!==Infinity).map(animation=>animation.finished.catch(()=>{})));});
    for(let frame=0;frame<4;frame++){
      await page.evaluate(()=>new Promise(requestAnimationFrame));
      assert.deepEqual(await page.evaluate(visibleChatFormulaSource),[],width+': held MathJax never paints historical formula source');
    }
    const prose=page.locator('#chat .msg[data-message-index="2"] .ai-content');
    assert.equal(await prose.isVisible(),true,width+': unrelated prose stays visible while formulas load');
    assert.equal(await prose.innerText(),'这段普通讲解应该立即可见。');
    release();
    for(const index of [0,1])await page.locator('#chat .msg[data-message-index="'+index+'"] mjx-container').waitFor({state:'visible'});
    assert.deepEqual(await page.evaluate(visibleChatFormulaSource),[],width+': the completed history shows real math without source');
    assert.deepEqual(modelCalls,[],width+': opening stored math does not invoke a model');
    console.log('PASS historical math '+width+': cold runtime hides formula source, keeps prose visible and reveals actual SVGs');
  }finally{release();await context.close();}
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
  try {
    for(const width of [1440,390])await historicalMathVisibility(browser,width);
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
