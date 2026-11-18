/* Scan regions remain selectable and movable without moving the image camera.
 * Region recognition is locally fulfilled; no real model/account requests run.
 */
'use strict';
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const settle = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
const GRAPH = [[.10,.12],[.60,.12],[.60,.32],[.34,.32],[.34,.58],[.10,.58]];
const TEXT = [[.55,.64],[.94,.64],[.94,.96],[.76,.88],[.55,.96],[.49,.79]];

async function point(page, source) {
  return page.locator('.dge-overlay-image').evaluate((node, source) => {
    const box=node.getBoundingClientRect();return {x:box.left+source[0]*box.width,y:box.top+source[1]*box.height};
  }, source);
}
async function snapshot(page) {
  return page.evaluate(()=>{
    const state=ocrTasks.get('region-fixture').scanState,viewport=document.querySelector('.dge-overlay-viewport');
    return {graph:structuredClone(state.graphRegions[0].polygon),text:structuredClone(state.textRegions[0].polygon),
      graphSelected:state.selectedGraphId||null,textSelected:state.view.selectedId??null,
      camera:[viewport.scrollLeft,viewport.scrollTop,state.view.zoom],
      graphCount:state.graphRegions.length,textCount:state.textRegions.length};
  });
}
async function drag(page, start, delta, touch=false, shift=false, beforeRelease=null) {
  const target=await point(page,start);
  if(touch){
    const client=await page.context().newCDPSession(page);
    await client.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:target.x,y:target.y,id:1}]});
    for(let step=1;step<=6;step++)await client.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:target.x+delta[0]*step/6,y:target.y+delta[1]*step/6,id:1}]});
    if(beforeRelease)await beforeRelease();
    await client.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await client.detach();
  }else{
    if(shift)await page.keyboard.down('Shift');
    await page.mouse.move(target.x,target.y);await page.mouse.down();
    await page.mouse.move(target.x+delta[0],target.y+delta[1],{steps:6});
    if(beforeRelease)await beforeRelease();
    await page.mouse.up();
    if(shift)await page.keyboard.up('Shift');
  }
  await settle(page);
}
function translated(before, after, label) {
  const delta=after[0].map((value,index)=>value-before[0][index]);
  assert.ok(Math.hypot(...delta)>.01,label+': the region actually moved');
  for(let index=0;index<before.length;index++)for(let axis=0;axis<2;axis++)
    assert.ok(Math.abs(after[index][axis]-before[index][axis]-delta[axis])<1e-6,label+': every point moves by the same amount');
}
async function selected(page, kind, label) {
  const state=await snapshot(page);
  assert.equal(state.graphSelected,kind==='graph'?'g1':null,label+': graph selection is exclusive');
  assert.equal(state.textSelected,kind==='text'?1:null,label+': text selection is exclusive');
  if(kind){
    const shapes=page.locator('.dge-frame-hit.is-current');assert.equal(await shapes.count(),1,label+': one frame is visibly selected');
    assert.ok(await shapes.evaluate(node=>parseFloat(getComputedStyle(node).strokeWidth))>=2,label+': selected outline is visibly emphasized');
  }
}
const minima=points=>[0,1].map(axis=>Math.min(...points.map(point=>point[axis])));
const maxima=points=>[0,1].map(axis=>Math.max(...points.map(point=>point[axis])));
async function fixture(browser,width) {
  const context=await browser.newContext({viewport:{width,height:1000},serviceWorkers:'block',...(width<=760?{isMobile:true,hasTouch:true}:{})});
  const page=await context.newPage(),errors=[],recognition=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/auth/me',route=>route.fulfill({contentType:'application/json',body:'{"configured":true,"authenticated":false}'}));
  await page.route('**/graph/recognize-region',async route=>{
    recognition.push('graph');
    const body=route.request().postData()||'', field=name=>new RegExp('name="'+name+'"\\r\\n\\r\\n([^\\r]+)').exec(body)?.[1];
    await route.fulfill({contentType:'application/json',body:JSON.stringify({request_id:field('request_id'),operation_id:field('operation_id'),source_sha256:'a'.repeat(64),
      document:{body_text:'',graphs:[{id:'G1',name:'本地图',vertices:[{id:'a',label:'A',x:.2,y:.2},{id:'b',label:'B',x:.8,y:.8}],edges:[]}]},recognition_status:'complete'})});
  });
  await page.route('**/graph/text-region',async route=>{
    recognition.push('text');
    const body=route.request().postData()||'',field=name=>new RegExp('name="'+name+'"\\r\\n\\r\\n([^\\r]+)').exec(body)?.[1];
    const regions=JSON.parse(field('regions')||'[]');
    await route.fulfill({contentType:'application/json',body:JSON.stringify({request_id:field('request_id'),operation_id:field('operation_id'),source_sha256:'a'.repeat(64),
      regions:regions.map(row=>({id:row.id,text:'本地识别文字',recognition_status:'complete'}))})});
  });
  const unexpected=[];
  await page.route(/\/(?:chat|ocr(?:\/[^?]*)?|graph\/[^?]*|analyze-questions|classify|conversation\/title)(?:\?|$)/,route=>{
    const path=new URL(route.request().url()).pathname;
    if(['/graph/recognize-region','/graph/text-region'].includes(path))return route.fallback();
    unexpected.push(path);return route.abort();
  });
  await page.goto(baseURL,{waitUntil:'networkidle'});await page.waitForFunction(()=>!accountVerificationOperation);
  await page.evaluate(({graph,text})=>{
    const document={body_text:'本地识别文字',graphs:[{id:'G1',name:'本地图',vertices:[{id:'a',label:'A',x:.2,y:.2},{id:'b',label:'B',x:.8,y:.8}],edges:[]}]};
    const file=new File(['local fixture'],'regions.svg',{type:'image/svg+xml'}),svg='<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="1000"><rect width="1000" height="1000" fill="white"/></svg>';
    ocrTasks.clear();ocrTasks.set('region-fixture',{id:'region-fixture',groupId:'1',file,sourceSha256:'a'.repeat(64),sessionId:currentId,state:'ready',isQuestion:true,
      originalUrl:'data:image/svg+xml,'+encodeURIComponent(svg),startedAt:performance.now(),finishedAt:performance.now(),
      draft:structuredClone(document),initialDocument:structuredClone(document),
      scanState:{mode:'manual',sourcesVersion:3,nativeDocument:structuredClone(document),
        graphRegions:[{id:'g1',irregular:true,status:'complete',selected:true,polygon:graph,graphs:structuredClone(document.graphs)}],
        textRegions:[{id:1,irregular:true,status:'complete',selected:true,polygon:text,text:document.body_text}],view:{zoom:100,visible:true}}});
    renderOcrTasks();editOcrTask('region-fixture');
  },{graph:GRAPH,text:TEXT});
  await page.locator('.dge-overlay[data-geometry-ready="true"]').waitFor();await settle(page);
  return {context,page,errors,recognition,unexpected};
}

async function runCase(browser,width) {
  const {context,page,errors,recognition,unexpected}=await fixture(browser,width),touch=width<=760;
  try {
    const graphPoint=await point(page,[.23,.24]);
    if(touch)await page.touchscreen.tap(graphPoint.x,graphPoint.y);else await page.mouse.click(graphPoint.x,graphPoint.y);
    await settle(page);
    await selected(page,'graph',width+'/graph interior click');
    const before=await snapshot(page);
    const originalPoints=await page.locator('.dge-frame-hit[data-graph-id="g1"]').getAttribute('points');
    await drag(page,[.23,.24],[24,18],touch,false,async()=>{
      await settle(page);assert.deepEqual((await snapshot(page)).graph,before.graph,'A drag preview does not commit crop data before release');
      assert.notEqual(await page.locator('.dge-frame-hit[data-graph-id="g1"]').getAttribute('points'),originalPoints,'The grabbed frame visibly follows the pointer before release');
      assert.deepEqual(recognition,[],'Pointer moves never repeat recognition before the single commit');
    });
    const moved=await snapshot(page);
    translated(before.graph,moved.graph,width+'/graph interior drag');assert.deepEqual(moved.text,before.text,'Moving graph leaves text untouched');
    assert.deepEqual(moved.camera,before.camera,'Region dragging does not pan or zoom its source image');
    assert.equal(moved.graphSelected,'g1');assert.equal(moved.graphCount,1);assert.equal(moved.textCount,1);

    const textPoint=await point(page,[.73,.78]);
    if(touch)await page.touchscreen.tap(textPoint.x,textPoint.y);else await page.mouse.click(textPoint.x,textPoint.y);
    await settle(page);await selected(page,'text',width+'/text interior click');
    const beforeText=await snapshot(page);
    await drag(page,[.73,.78],[-18,-12],touch);
    const movedText=await snapshot(page);
    translated(beforeText.text,movedText.text,width+'/text interior drag');assert.deepEqual(movedText.graph,beforeText.graph);
    assert.deepEqual(movedText.camera,beforeText.camera);
    assert.equal(movedText.textSelected,1);assert.equal(movedText.graphCount,1);assert.equal(movedText.textCount,1);
    await page.waitForFunction(()=>{const state=ocrTasks.get('region-fixture').scanState;return state.graphRegions[0].status==='complete'&&state.textRegions[0].status==='complete';});
    if(touch){
      const prior=await snapshot(page),corner=prior.graph[0],start=await point(page,[corner[0]+.13,corner[1]+.12]);
      const outline=await page.locator('.dge-frame-hit[data-graph-id="g1"]').getAttribute('points'),count=recognition.length;
      const client=await context.newCDPSession(page);
      await client.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:start.x,y:start.y,id:1}]});
      await client.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:start.x+14,y:start.y+9,id:1}]});await settle(page);
      assert.notEqual(await page.locator('.dge-frame-hit[data-graph-id="g1"]').getAttribute('points'),outline,'The pending single-finger move has a real visible preview');
      await client.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:start.x+14,y:start.y+9,id:1},{x:start.x+54,y:start.y+9,id:2}]});
      await client.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await client.detach();await settle(page);
      const cancelled=await snapshot(page);assert.deepEqual(cancelled.graph,prior.graph);assert.deepEqual(cancelled.text,prior.text);assert.deepEqual(cancelled.camera,prior.camera);
      assert.equal(await page.locator('.dge-frame-hit[data-graph-id="g1"]').getAttribute('points'),outline,'A second finger rolls the uncommitted preview back even without a pinch move');
      assert.equal(recognition.length,count,'Cancelling a pending move never recognizes a new crop');
    }

    // Grabbing an actual edge still locally deforms the outline rather than
    // translating it or silently switching to canvas navigation.
    for(const kind of ['graph','text']){
      const prior=await snapshot(page),outline=prior[kind],edge=[(outline[0][0]+outline[1][0])/2,outline[0][1]];
      await drag(page,edge,[0,-12],touch);
      const current=await snapshot(page);
      assert.notDeepEqual(current[kind],outline,width+'/'+kind+': edge drag changes the real crop');
      assert.ok(minima(current[kind])[1]<minima(outline)[1]-.003,kind+': the grabbed top edge moves');
      assert.ok(Math.abs(maxima(current[kind])[1]-maxima(outline)[1])<1e-6,kind+': the distant opposite edge stays fixed');
      assert.deepEqual(current[kind==='graph'?'text':'graph'],prior[kind==='graph'?'text':'graph']);
      assert.deepEqual(current.camera,prior.camera,kind+': elastic edge edit preserves the camera');
    }

    // Zoom changes the source transform, not the normalized region movement.
    await page.locator('[data-overlay-tool="zoom-in"]').click();await settle(page);
    const zoomed=await snapshot(page),origin=zoomed.graph[0],inside=[origin[0]+.13,origin[1]+.12];
    await drag(page,inside,[10,8],touch);
    const zoomMoved=await snapshot(page);
    translated(zoomed.graph,zoomMoved.graph,width+'/zoomed graph drag');assert.deepEqual(zoomMoved.camera,zoomed.camera);

    // A concave polygon's empty bounding-box corner is genuine background.
    const shifted=zoomMoved.graph[0],notch=[shifted[0]+.38,shifted[1]+.28],notchPoint=await point(page,notch);
    if(touch)await page.touchscreen.tap(notchPoint.x,notchPoint.y);else await page.mouse.click(notchPoint.x,notchPoint.y);
    await settle(page);await selected(page,null,width+'/concave bounding-box gap');
    const emptyBefore=await snapshot(page);await drag(page,notch,[-14,-9],touch);
    const emptyAfter=await snapshot(page);
    assert.deepEqual(emptyAfter.graph,emptyBefore.graph);assert.deepEqual(emptyAfter.text,emptyBefore.text);
    assert.notDeepEqual(emptyAfter.camera,emptyBefore.camera,'Dragging empty background still pans the source');

    // Desktop Shift is an explicit navigation gesture even over a real crop.
    if(!touch){
      const prior=await snapshot(page),corner=prior.graph[0];
      await drag(page,[corner[0]+.13,corner[1]+.12],[13,9],false,true);
      const current=await snapshot(page);assert.deepEqual(current.graph,prior.graph);assert.deepEqual(current.text,prior.text);
      assert.notDeepEqual(current.camera,prior.camera,'Shift-drag pans without changing a region');
    }else{
      // Two fingers must cancel a pending region move and zoom the image.
      const prior=await snapshot(page),area=await page.locator('.dge-overlay-viewport').boundingBox(),client=await context.newCDPSession(page);
      const center={x:area.x+area.width/2,y:area.y+area.height/2};
      await client.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:center.x-30,y:center.y,id:1}]});
      await client.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:center.x-30,y:center.y,id:1},{x:center.x+30,y:center.y,id:2}]});
      await client.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:center.x-44,y:center.y,id:1},{x:center.x+44,y:center.y,id:2}]});
      await client.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await client.detach();await settle(page);
      const current=await snapshot(page);assert.deepEqual(current.graph,prior.graph);assert.deepEqual(current.text,prior.text);
      assert.notEqual(current.camera[2],prior.camera[2],'Two-finger pinch zooms rather than moving either crop');
    }
    await page.waitForFunction(()=>{const state=ocrTasks.get('region-fixture').scanState;return state.graphRegions[0].status==='complete'&&state.textRegions[0].status==='complete';});

    // Text is painted above graphs. Its interior must not grab a graph edge
    // underneath it, even inside that edge's larger touch hit tolerance.
    await page.locator('#graphEditorClose').click();await page.waitForFunction(()=>ocrEditorTaskId===null);
    await page.evaluate(graph=>{
      const state=ocrTasks.get('region-fixture').scanState;
      state.graphRegions[0].polygon=graph;state.textRegions[0].polygon=[[.14,.14],[.54,.15],[.57,.54],[.16,.52]];
      state.viewState={};
      editOcrTask('region-fixture');
    },GRAPH);
    await page.locator('.dge-overlay[data-geometry-ready="true"]').waitFor();await settle(page);
    const overlapPoint=await point(page,[.35,.31]);
    if(touch)await page.touchscreen.tap(overlapPoint.x,overlapPoint.y);else await page.mouse.click(overlapPoint.x,overlapPoint.y);
    await settle(page);await selected(page,'text',width+'/overlap topmost selection');
    const overlap=await snapshot(page);await drag(page,[.35,.31],[15,10],touch);
    const overlapMoved=await snapshot(page);
    translated(overlap.text,overlapMoved.text,width+'/overlap text move');assert.deepEqual(overlapMoved.graph,overlap.graph);
    assert.deepEqual(overlapMoved.camera,overlap.camera);
    const offset=overlapMoved.text[0].map((value,index)=>value-overlap.text[0][index]);
    const insideText=[.35+offset[0],.31+offset[1]],start=await point(page,insideText),end=await point(page,[.99,.99]);
    await drag(page,insideText,[end.x-start.x,end.y-start.y],touch);
    const clipped=await snapshot(page);
    translated(overlapMoved.text,clipped.text,width+'/whole crop bounds clamp');
    assert.ok(clipped.text.every(point=>point.every(value=>value>=0&&value<=1)),'A translated crop cannot leave the original image');
    for(const bound of maxima(clipped.text))assert.ok(Math.abs(bound-1)<1e-6,'Clamping moves the whole shape to the image edge');
    assert.deepEqual(clipped.graph,overlapMoved.graph);assert.deepEqual(clipped.camera,overlapMoved.camera);
    await page.waitForFunction(()=>ocrTasks.get('region-fixture').scanState.textRegions[0].status==='complete');
    for(const irregular of [false,true]){
      const imageHeight=await page.locator('.dge-overlay-image').evaluate(node=>node.getBoundingClientRect().height),height=15/imageHeight,top=.42;
      const polygon=irregular?[[.58,top],[.90,top+height*.2],[.93,top+height*.75],[.84,top+height],[.58,top+height*.8]]
        :[[.58,top],[.92,top],[.92,top+height],[.58,top+height]];
      await page.locator('#graphEditorClose').click();await page.waitForFunction(()=>ocrEditorTaskId===null);
      await page.evaluate(({polygon,irregular})=>{
        const state=ocrTasks.get('region-fixture').scanState;
        state.textRegions[0].polygon=polygon;state.textRegions[0].irregular=irregular;state.viewState={};
        editOcrTask('region-fixture');
      },{polygon,irregular});
      await page.locator('.dge-overlay[data-geometry-ready="true"]').waitFor();await settle(page);
      const actualHeight=await page.locator('.dge-frame-hit[data-text-region-id="1"]').evaluate(node=>node.getBoundingClientRect().height);
      assert.ok(Math.abs(actualHeight-15)<1,'The thin text fixture is really 15 screen pixels high');
      const prior=await snapshot(page);await drag(page,[.75,top+height/2],[12,7],touch);
      const current=await snapshot(page);translated(prior.text,current.text,width+'/'+(irregular?'irregular':'rectangular')+' narrow text move');
      assert.equal(current.text.length,prior.text.length,'Moving a narrow crop retains its original outline vertices');
      assert.deepEqual(current.graph,prior.graph);assert.deepEqual(current.camera,prior.camera);
      await selected(page,'text',width+'/narrow text selection');
      await page.waitForFunction(()=>ocrTasks.get('region-fixture').scanState.textRegions[0].status==='complete');
    }
    assert.deepEqual(errors,[]);assert.deepEqual(unexpected,[]);
    console.log('PASS '+width+': irregular and 15px text selection, rigid moves/clamps, elastic edges, overlapping hits and zoom/pan cancellation retain source ownership');
  }finally{await context.close();}
}
(async()=>{const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.CHROMIUM_EXECUTABLE_PATH}:{})});
try{for(const width of [1440,390])await runCase(browser,width);}finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
