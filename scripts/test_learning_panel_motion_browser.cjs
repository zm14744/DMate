/* The learning heading takes the empty information heading's exact place.
 * Exercise real rendered frames, rapid reversals and the current session data;
 * no model or backend study operation is needed. Start Flask first. */
'use strict';
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const near = (a,b,label,tolerance=2) => assert.ok(Math.abs(a-b)<=tolerance,label+': '+a+' vs '+b);

async function openTools(page,width) {
  if (width>1100) {
    if (await page.locator('#desktopToolsBtn').getAttribute('aria-expanded')!=='true') await page.locator('#desktopToolsBtn').click();
  } else if (!await page.evaluate(() => document.body.classList.contains('mobile-tools-open'))) {
    await page.locator('#mobileToolsBtn').tap();
  }
  await page.locator('#learningToolsPanel').evaluate(async panel => {
    await Promise.all(panel.getAnimations().map(animation => animation.finished.catch(()=>{})));
    await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
  });
}

async function settle(page) {
  await page.waitForFunction(() => !document.getElementById('conversationInfoSection').hasAttribute('data-info-animating'));
  await page.evaluate(() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
}

async function snapshot(page) {
  return page.evaluate(() => __learningPanelSnapshot());
}

async function transition(page,action) {
  return page.evaluate(async action => {
    const before=__learningPanelSnapshot();
    if(action==='show')getCurrent().messages.push({role:'user',text:'用真实会话消息检查学习工具的连续移动。'});
    else if(action==='grow') {
      getCurrent().nameSource='user';
      getCurrent().name='用于核对对话信息换行和学习工具连续移动的较长对话名称。'.repeat(3);
    } else getCurrent().messages=[];
    renderInfo();
    const sync=__learningPanelSnapshot(),frames=[];
    const start=performance.now();
    await new Promise(resolve=>{
      function frame(timestamp){
        // Animation progress follows the browser frame clock. A busy callback
        // can run late, so wall-clock sampling would distort adjacent deltas.
        frames.push({...__learningPanelSnapshot(),time:timestamp});
        if(performance.now()-start<420)requestAnimationFrame(frame);else resolve();
      }
      requestAnimationFrame(frame);
    });
    return {before,sync,frames};
  },action);
}

function assertMotion(result,label,minDistance=30) {
  const end=result.frames.at(-1),distance=Math.abs(end.y-result.before.y),direction=Math.sign(end.y-result.before.y);
  near(result.sync.y,result.before.y,label+': synchronous state change keeps the painted heading position');
  near(result.sync.height,result.before.height,label+': information height does not snap before motion');
  assert.ok(distance>minDistance,label+': fixture produces meaningful movement');
  const intermediate=result.frames.filter(row=>Math.abs(row.y-result.before.y)>2&&Math.abs(row.y-end.y)>2);
  assert.ok(intermediate.length>=3,label+': several real frames show the moving heading');
  for(let i=1;i<result.frames.length;i++) {
    const previous=result.frames[i-1],next=result.frames[i];
    assert.ok(direction*(next.y-previous.y)>=-1.5,label+': heading does not reverse unexpectedly');
    if(next.time-previous.time<35)assert.ok(Math.abs(next.y-previous.y)<=distance*6*(next.time-previous.time)/220+3,
      label+': heading has no single-frame jump '+JSON.stringify({before:result.before,end,previous,next,distance}));
  }
  assert.equal(end.animating,false,label+': motion completes');
  assert.equal(end.stableNodes,true,label+': headings, information and tool buttons retain their DOM identity');
}

async function run(browser,width,theme,language='zh-CN') {
  const context=await browser.newContext({viewport:{width,height:900},isMobile:width<1100,hasTouch:width<1100,
    serviceWorkers:'block',reducedMotion:'no-preference'});
  const page=await context.newPage(),errors=[],calls=[];
  page.on('pageerror',error=>errors.push(error.message));
  await context.route(/\/(?:chat|ocr|notebook\/analyze|analyze-questions|conversation\/title)(?:\?|$)/,
    route=>{calls.push(route.request().url());return route.abort();});
  try {
    await page.goto(baseURL,{waitUntil:'networkidle'});
    await page.waitForFunction(() => window.DMateLearningPanel && document.getElementById('conversationInfoSection'));
    await page.evaluate(({theme,language})=>{
      appearanceSettings={...APPEARANCE_DEFAULTS,mode:theme};applyAppearanceSettings({save:false});
      window.DMateI18n.setLanguage(language,false);
      currentId=null;renderAll();
    },{theme,language});
    await settle(page);await openTools(page,width);
    await page.evaluate(()=>{
      const section=document.getElementById('conversationInfoSection'),info=document.getElementById('info');
      const heading=document.getElementById('conversationInfoHeading'),tools=document.querySelector('#learningToolsPanel .learning-title');
      const buttons=['wrongBookBtn','conceptNotebookBtn','knowledgeGraphBtn','graphDrawingBtn','learningReviewBtn'].map(id=>document.getElementById(id));
      window.__learningPanelSnapshot=()=>{
        const current=document.getElementById('conversationInfoSection'),title=document.querySelector('#learningToolsPanel .learning-title');
        const box=current.getBoundingClientRect(),rect=title.getBoundingClientRect();
        return {time:performance.now(),height:box.height,x:rect.x,y:rect.y,hidden:current.hidden,
          ariaHidden:current.getAttribute('aria-hidden'),animating:current.hasAttribute('data-info-animating'),
          hasInfo:document.getElementById('learningToolsPanel').dataset.hasConversationInfo,
          separator:parseFloat(getComputedStyle(title.parentElement).borderTopWidth),
          stableNodes:current===section && document.getElementById('info')===info
            && document.getElementById('conversationInfoHeading')===heading && title===tools
            && buttons.every(button=>document.getElementById(button.id)===button)};
      };
    });
    const label=width+'/'+theme+'/'+language,empty=await snapshot(page);
    assert.equal(empty.hidden,true,label+': no session removes the entire information area');
    assert.equal(empty.ariaHidden,'true',label+': empty area is unavailable to assistive technology');
    assert.equal(empty.separator,0,label+': no empty separator is left above learning tools');
    assert.equal(await page.locator('#info').isVisible(),false,label+': the old None placeholder is not visible');
    await page.evaluate(()=>newChat());await settle(page);await openTools(page,width);
    const fresh=await snapshot(page);
    assert.equal(fresh.hidden,true,label+': a new zero-message conversation also has no information area');
    near(fresh.y,empty.y,label+': creating an empty conversation does not move learning tools');
    const appearing=await transition(page,'show');assertMotion(appearing,label+'/show');
    const visible=appearing.frames.at(-1);
    assert.equal(visible.hidden,false);assert.equal(visible.hasInfo,'true');
    const informationHeading=await page.locator('#conversationInfoHeading').boundingBox();
    near(empty.x,informationHeading.x,label+': learning tools occupy the original information heading left position');
    near(empty.y,informationHeading.y,label+': learning tools occupy the original information heading top position');
    assert.ok((await page.locator('#info .conversation-info-line').count())>=2,label+': real information lines appear');
    const growing=await transition(page,'grow');assertMotion(growing,label+'/content-height',10);
    const hiding=await transition(page,'hide');assertMotion(hiding,label+'/hide');
    assert.equal(hiding.sync.ariaHidden,'true',label+': collapsing information immediately leaves the accessibility tree');
    assert.equal(hiding.frames.at(-1).hidden,true);near(hiding.frames.at(-1).y,empty.y,label+': final collapsed position matches the original top');

    const rapid=await page.evaluate(async()=>{
      const next=count=>new Promise(resolve=>{
        function frame(){if(--count<=0)resolve();else requestAnimationFrame(frame);}requestAnimationFrame(frame);
      });
      const changes=[];
      getCurrent().messages.push({role:'user',text:'连续反向切换检查。'});renderInfo();await next(4);
      let before=__learningPanelSnapshot();getCurrent().messages=[];renderInfo();changes.push([before,__learningPanelSnapshot()]);
      await next(3);before=__learningPanelSnapshot();getCurrent().messages.push({role:'user',text:'再次显示。'});renderInfo();changes.push([before,__learningPanelSnapshot()]);
      await next(3);before=__learningPanelSnapshot();getCurrent().messages=[];renderInfo();changes.push([before,__learningPanelSnapshot()]);
      await new Promise(resolve=>setTimeout(resolve,420));return {changes,end:__learningPanelSnapshot()};
    });
    for(const [before,after] of rapid.changes)near(after.y,before.y,label+': interrupted animation starts from its currently visible frame');
    assert.equal(rapid.end.hidden,true);assert.equal(rapid.end.animating,false);near(rapid.end.y,empty.y,label+': interrupted motion reaches the requested final position');
    assert.equal(rapid.end.stableNodes,true);
    await page.emulateMedia({reducedMotion:'reduce'});
    const reduced=await page.evaluate(()=>{
      getCurrent().messages.push({role:'user',text:'减少动态效果检查。'});renderInfo();const shown=__learningPanelSnapshot();
      getCurrent().messages=[];renderInfo();return {shown,hidden:__learningPanelSnapshot()};
    });
    assert.equal(reduced.shown.animating,false);assert.equal(reduced.shown.hidden,false);
    assert.equal(reduced.hidden.animating,false);assert.equal(reduced.hidden.hidden,true);near(reduced.hidden.y,empty.y,label+': reduced motion applies final layout immediately');
    for(const id of ['wrongBookBtn','conceptNotebookBtn','knowledgeGraphBtn','graphDrawingBtn','learningReviewBtn']) {
      assert.equal(await page.locator('#'+id).isVisible(),true,label+'/'+id+': tool remains visible');
      assert.equal(await page.locator('#'+id).isEnabled(),true,label+'/'+id+': tool remains usable');
    }
    assert.deepEqual(errors,[],label+': no page errors');assert.deepEqual(calls,[],label+': no model or study endpoint is called');
    console.log('PASS '+label+': empty/header alignment, painted content motion, reversal, reduced motion and usable tools');
  } finally {await context.close();}
}

(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.CHROMIUM_EXECUTABLE_PATH}:{})});
  try {
    for(const width of [1440,390]) {
      for(const theme of ['dark','navy'])await run(browser,width,theme);
      await run(browser,width,'navy','en');
    }
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
