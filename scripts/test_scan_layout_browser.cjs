/* Image review uses one mobile information flow and one compact header row.
 * Recognition and chat endpoints are blocked; all sources are local fixtures.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const settle = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));

async function runCase(browser, width) {
  const context = await browser.newContext({viewport:{width,height:900},serviceWorkers:'block',
    ...(width<=760?{isMobile:true,hasTouch:true}:{})});
  const page = await context.newPage(), errors = [], requests = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/auth/me', route => route.fulfill({contentType:'application/json',body:'{"configured":true,"authenticated":false}'}));
  await page.route(/\/(?:chat|ocr(?:\/[^?]*)?|graph\/[^?]*|analyze-questions|classify|conversation\/title)(?:\?|$)/,
    route => {requests.push(new URL(route.request().url()).pathname);return route.abort();});
  try {
    await page.goto(baseURL,{waitUntil:'networkidle'});
    await page.waitForFunction(()=>!accountVerificationOperation);
    await page.evaluate(()=>{
      const graph = index => ({id:'G'+index,name:'图 '+index,directed:false,weighted:false,
        vertices:[{id:'v1',label:'A',x:.2,y:.2},{id:'v2',label:'B',x:.8,y:.7}],
        edges:[{id:'e1',from:'v1',to:'v2',direction:'undirected',style:'solid'}],
        visual_description:'这幅图用于验证完整识别内容连续展示，用户不需要在独立信息窗内滚动'});
      const graphs=Array.from({length:8},(_,index)=>graph(index+1));
      const body_text=Array.from({length:12},(_,index)=>'第'+(index+1)+'行识别文字：验证图片、文字、图形和要求输入按顺序连续下滑').join('\n');
      const draft={body_text,graphs};
      const svg='<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="800"><rect width="1000" height="800" fill="white"/><path d="M80 80L850 650" stroke="black"/></svg>';
      const file=new File([svg],'continuous-scan.svg',{type:'image/svg+xml'});
      ocrTasks.clear();ocrTasks.set('continuous-scan',{id:'continuous-scan',groupId:'1',file,sessionId:currentId,
        state:'ready',isQuestion:true,originalUrl:URL.createObjectURL(file),startedAt:performance.now(),finishedAt:performance.now(),
        draft:structuredClone(draft),initialDocument:structuredClone(draft),
        scanState:{mode:'manual',sourcesVersion:3,nativeDocument:structuredClone(draft),
          graphRegions:graphs.map((graph,index)=>({id:'g'+(index+1),status:'complete',selected:true,
            polygon:[[.1,.1],[.9,.1],[.9,.8],[.1,.8]],graphs:[graph]})),
          textRegions:[{id:1,status:'complete',selected:true,polygon:[[.1,.1],[.9,.1],[.9,.8],[.1,.8]],text:body_text}]}});
      renderOcrTasks();editOcrTask('continuous-scan');
    });
    await page.locator('#graphEditorDialog .dge-overlay[data-geometry-ready="true"]').waitFor();await settle(page);
    const header = await page.evaluate(()=>{
      const modes=document.querySelector('.dgs-modes'),buttons=[...modes.querySelectorAll('[role="tab"]')],zoom=document.querySelector('.dmate-graph-scan .dge-view-controls');
      const box=node=>{const rect=node.getBoundingClientRect();return {left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom,center:rect.top+rect.height/2};};
      const frames=[modes,zoom,document.querySelector('.dge-scan-only .dge-overlay-tools')].map(node=>{
        const css=getComputedStyle(node);return {border:[css.borderTopWidth,css.borderRightWidth,css.borderBottomWidth,css.borderLeftWidth],background:css.backgroundColor};
      });
      return {modes:box(document.querySelector('.dgs-toolbar')),tabs:buttons.map(box),zoom:box(zoom),frames};
    });
    assert.equal(header.tabs.length,2);
    for(const tab of header.tabs)assert.ok(Math.abs(tab.center-header.zoom.center)<=3,width+': zoom controls and both recognition tabs share one row');
    assert.ok(header.zoom.left>=header.tabs[1].right+3,width+': right-hand zoom group does not overlap mode buttons');
    assert.ok(header.zoom.right<=header.modes.right+1,width+': controls fit inside the mode row');
    for(const frame of header.frames){assert.deepEqual(frame.border,['0px','0px','0px','0px']);assert.equal(frame.background,'rgba(0, 0, 0, 0)');}
    const sourceButtons=page.locator('.dgs-section-head [data-source-picker]');
    assert.equal(await sourceButtons.count(),2);
    for(const button of await sourceButtons.all())assert.equal(await button.evaluate(node=>getComputedStyle(node).borderTopWidth),'0px');
    assert.equal(await page.locator('.dge-overlay-tools select').isVisible(),false,'Selection/pan mode hides the region-shape choice');
    await page.locator('[data-overlay-tool="bounds"]').click();
    assert.equal(await page.locator('.dge-overlay-tools select').isVisible(),true);
    await page.locator('[data-overlay-tool="select"]').click();

    if(width<=760){
      const flow=await page.evaluate(()=>{
        const info=document.querySelector('.dgs-information'),outer=document.querySelector('.dgs-content');
        const css=getComputedStyle(info);return {overflow:css.overflowY,maxHeight:css.maxHeight,
          infoHeight:info.clientHeight,infoScroll:info.scrollHeight,outerHeight:outer.clientHeight,outerScroll:outer.scrollHeight};
      });
      assert.equal(flow.maxHeight,'none');assert.equal(flow.overflow,'visible');
      assert.ok(flow.infoHeight>=flow.infoScroll-1,'The full long information section participates in the outer page flow');
      assert.ok(flow.outerScroll>flow.outerHeight*2,'Fixture really spans multiple screenfuls');
      // Put ordinary recognized text under the pointer and wheel over it.
      const text=page.locator('.dgs-body');await text.scrollIntoViewIfNeeded();await settle(page);
      const before=await page.locator('.dgs-content').evaluate(node=>node.scrollTop);
      const contentBox=await page.locator('.dgs-content').boundingBox(),textBox=await text.boundingBox();
      await page.mouse.move(contentBox.x+contentBox.width/2,Math.max(contentBox.y+20,Math.min(contentBox.y+contentBox.height-20,textBox.y+30)));
      await page.mouse.wheel(0,280);
      await page.waitForFunction(value=>document.querySelector('.dgs-content').scrollTop>value,before);
      assert.equal(await page.locator('.dgs-information').evaluate(node=>node.scrollTop),0,'Wheel scrolling does not create an inner information scroll position');
      await page.locator('.dgs-content').evaluate(node=>{node.scrollTop=node.scrollHeight;});await settle(page);
      assert.equal(await page.locator('.dgs-requirements').isVisible(),true);
      const reachable=await page.locator('.dgs-requirements').evaluate(node=>{
        const box=node.getBoundingClientRect(),outer=node.closest('.dgs-content').getBoundingClientRect();return box.top>=outer.top-1&&box.bottom<=outer.bottom+1;
      });
      assert.equal(reachable,true,'The same outer scroll reaches the requirements after every graph');
    }
    await page.locator('[data-source-picker="graph"]').click();
    const popup=page.locator('.dgs-source-picker');await popup.waitFor({state:'visible'});await settle(page);
    assert.equal(await popup.locator('.dgs-source-choice input[type="checkbox"]').count(),8);
    const within=()=>popup.evaluate(node=>{
      const box=node.getBoundingClientRect(),dialog=node.closest('dialog').getBoundingClientRect();
      return box.left>=Math.max(0,dialog.left)-1&&box.right<=Math.min(innerWidth,dialog.right)+1&&box.top>=Math.max(0,dialog.top)-1&&box.bottom<=Math.min(innerHeight,dialog.bottom)+1;
    });
    assert.equal(await within(),true,'The portaled source picker stays within the visible dialog');
    const checkbox=popup.locator('input[type="checkbox"]').first();await checkbox.uncheck();
    assert.equal(await page.evaluate(()=>ocrTasks.get('continuous-scan').scanState.graphRegions[0].selected),false,'Source selection still updates the correct record');
    await page.locator('.dgs-content').evaluate(node=>{node.scrollTop=Math.max(0,node.scrollTop-80);});await settle(page);
    assert.equal(await within(),true,'Source popup repositions after the outer page scrolls');
    await page.keyboard.press('Escape');assert.equal(await popup.count(),0);
    await page.locator('#graphEditorClose').click();
    assert.deepEqual(requests,[],'Layout, scrolling and source selection never repeat recognition');assert.deepEqual(errors,[]);
    console.log('PASS '+width+': compact unframed header, continuous mobile information scrolling and live source-picker behavior');
  }finally{await context.close();}
}
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.CHROMIUM_EXECUTABLE_PATH}:{})});
  try{for(const width of [390,1440])await runCase(browser,width);}finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
