/* Freehand scan regions are final; rectangles retain their editing gestures.
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
      graphCount:state.graphRegions.length,textCount:state.textRegions.length,
      graphs:state.graphRegions.map(row=>({id:row.id,polygon:structuredClone(row.polygon),irregular:row.irregular})),
      texts:state.textRegions.map(row=>({id:row.id,polygon:structuredClone(row.polygon),irregular:row.irregular}))};
  });
}
async function drag(page, start, delta, touch=false, shift=false, beforeRelease=null, afterPress=null) {
  const target=await point(page,start);
  if(touch){
    const client=await page.context().newCDPSession(page);
    await client.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:target.x,y:target.y,id:1}]});
    if(afterPress)await afterPress();
    for(let step=1;step<=6;step++)await client.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:target.x+delta[0]*step/6,y:target.y+delta[1]*step/6,id:1}]});
    if(beforeRelease)await beforeRelease();
    await client.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await client.detach();
  }else{
    if(shift)await page.keyboard.down('Shift');
    await page.mouse.move(target.x,target.y);await page.mouse.down();
    if(afterPress)await afterPress();
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

async function tap(page, source, touch) {
  const target=await point(page,source);
  if(touch)await page.touchscreen.tap(target.x,target.y);else await page.mouse.click(target.x,target.y);
  await settle(page);
}
async function fit(page) { await page.locator('[data-overlay-tool="zoom-fit"]').click();await settle(page); }
async function stroke(page, points, touch) {
  const positions=[];for(const source of points)positions.push(await point(page,source));
  if(touch){
    const client=await page.context().newCDPSession(page);
    await client.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{...positions[0],id:1}]});
    for(const position of positions.slice(1))await client.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{...position,id:1}]});
    await client.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await client.detach();
  }else{
    await page.mouse.move(positions[0].x,positions[0].y);await page.mouse.down();
    for(const position of positions.slice(1))await page.mouse.move(position.x,position.y,{steps:2});
    await page.mouse.up();
  }
  await settle(page);
}
async function drawIrregular(page,kind,points,touch){
  await page.locator('[data-overlay-tool="'+(kind==='graph'?'bounds':'text_rect')+'"]').click();
  await page.locator('.dge-overlay-tools select[aria-label="选区方式"]').selectOption('irregular');
  await fit(page);
  const oldIds=await page.evaluate(kind=>ocrTasks.get('region-fixture').scanState[kind==='graph'?'graphRegions':'textRegions'].map(row=>row.id),kind);
  await stroke(page,points,touch);
  await page.waitForFunction(({kind,oldIds})=>ocrTasks.get('region-fixture').scanState[kind==='graph'?'graphRegions':'textRegions']
    .some(row=>!oldIds.includes(row.id)&&row.status==='complete'),{kind,oldIds});
  const row=await page.evaluate(({kind,oldIds})=>{
    const row=ocrTasks.get('region-fixture').scanState[kind==='graph'?'graphRegions':'textRegions'].find(row=>!oldIds.includes(row.id));
    return{id:row.id,polygon:row.polygon,irregular:row.irregular};
  },{kind,oldIds});
  assert.equal(row.irregular,true,'A one-stroke crop retains its irregular source marker');
  await page.locator('[data-overlay-tool="select"]').click();await fit(page);
  return row;
}
async function checkFixed(page,kind,id,interior,edge,touch,recognition,label){
  await tap(page,interior,touch);
  assert.equal(await page.evaluate(({kind})=>{const state=ocrTasks.get('region-fixture').scanState;
    return kind==='graph'?state.selectedGraphId:state.view.selectedId;},{kind}),id,label+': remains selectable');
  const prior=await snapshot(page),calls=recognition.length;
  for(const start of [interior,edge]){
    await drag(page,start,[21,13],touch);
    const current=await snapshot(page);
    assert.deepEqual(current.graphs,prior.graphs,label+': dragging never changes graph polygons');
    assert.deepEqual(current.texts,prior.texts,label+': dragging never changes text polygons');
    assert.equal(recognition.length,calls,label+': dragging a finished outline never recognizes a new crop');
    await fit(page);
  }
}
async function runCase(browser,width) {
  const {context,page,errors,recognition,unexpected}=await fixture(browser,width),touch=width<=760;
  try {
    await checkFixed(page,'graph','g1',[.23,.24],[.35,.12],touch,recognition,width+'/saved graph');
    await checkFixed(page,'text',1,[.73,.78],[.74,.64],touch,recognition,width+'/saved text');
    assert.equal(recognition.length,0,'Opening and selecting saved irregular crops never repeats recognition');

    // Geometry inside a polygon's empty concavity remains ordinary canvas.
    await tap(page,[.49,.47],touch);await selected(page,null,width+'/concave gap');
    const beforePan=await snapshot(page);await drag(page,[.49,.47],[-16,-10],touch);
    const afterPan=await snapshot(page);
    assert.deepEqual(afterPan.graphs,beforePan.graphs);assert.deepEqual(afterPan.texts,beforePan.texts);
    assert.notDeepEqual(afterPan.camera,beforePan.camera,'Background drag still pans the image');
    await fit(page);

    // New freehand graph and text crops each complete once, then stay fixed.
    const graphStroke=[[.68,.12],[.89,.14],[.93,.37],[.80,.34],[.68,.41],[.68,.12]],
      textStroke=[[.07,.70],[.35,.70],[.39,.86],[.25,.94],[.07,.87],[.07,.70]];
    const freshGraph=await drawIrregular(page,'graph',graphStroke,touch);
    await checkFixed(page,'graph',freshGraph.id,[.78,.23],[.78,.13],touch,recognition,width+'/new graph');
    const freshText=await drawIrregular(page,'text',textStroke,touch);
    await checkFixed(page,'text',freshText.id,[.22,.80],[.20,.70],touch,recognition,width+'/new text');
    assert.deepEqual(recognition,['graph','text'],'Each finished source is recognized exactly once');

    // A finished crop can be removed and redrawn with the original controls.
    await page.locator('[data-source-picker="graph"]').click();
    await page.locator('.dgs-source-card[data-source-id="'+freshGraph.id+'"] .dgs-source-delete').click();
    await page.locator('.dmate-delete-confirm-delete').click();
    await page.waitForFunction(id=>!ocrTasks.get('region-fixture').scanState.graphRegions.some(row=>row.id===id),freshGraph.id);
    const redrawn=await drawIrregular(page,'graph',graphStroke,touch);
    assert.notEqual(redrawn.id,freshGraph.id,'Redrawing creates a new source rather than mutating the old outline');
    await checkFixed(page,'graph',redrawn.id,[.78,.23],[.78,.13],touch,recognition,width+'/redrawn graph');

    // Existing rectangle tools retain selection, fine moves and edge resizes.
    await page.locator('#graphEditorClose').click();await page.waitForFunction(()=>ocrEditorTaskId===null);
    await page.evaluate(()=>{
      const state=ocrTasks.get('region-fixture').scanState;
      state.graphRegions[0].irregular=false;state.graphRegions[0].polygon=[[.10,.12],[.60,.12],[.60,.58],[.10,.58]];
      state.textRegions[0].irregular=false;state.textRegions[0].polygon=[[.55,.64],[.94,.64],[.94,.96],[.55,.96]];
      state.viewState={};editOcrTask('region-fixture');
    });
    await page.locator('.dge-overlay[data-geometry-ready="true"]').waitFor();await settle(page);
    const fineBefore=await snapshot(page),imageWidth=await page.locator('.dge-overlay-image').evaluate(node=>node.getBoundingClientRect().width);
    await drag(page,[.23,.24],[2.5,0],touch);
    const fineAfter=await snapshot(page);
    assert.ok(Math.abs((fineAfter.graph[0][0]-fineBefore.graph[0][0])*imageWidth-2.5)<.15,'Rectangle fine movement commits on release');
    await page.waitForFunction(()=>ocrTasks.get('region-fixture').scanState.graphRegions[0].status==='complete');
    const graphBefore=await snapshot(page),painted=await page.locator('.dge-frame-hit[data-graph-id="g1"]').getAttribute('points');
    await drag(page,[.23,.24],[24,18],touch,false,async()=>{
      await settle(page);assert.deepEqual((await snapshot(page)).graph,graphBefore.graph,'Rectangle preview waits until release to commit crop data');
      assert.notEqual(await page.locator('.dge-frame-hit[data-graph-id="g1"]').getAttribute('points'),painted,'A rectangle still follows the pointer');
    });
    const graphMoved=await snapshot(page);translated(graphBefore.graph,graphMoved.graph,width+'/rectangle graph move');
    assert.deepEqual(graphMoved.texts,graphBefore.texts);assert.deepEqual(graphMoved.camera,graphBefore.camera);
    await page.waitForFunction(()=>ocrTasks.get('region-fixture').scanState.graphRegions[0].status==='complete');
    await drag(page,[.73,.78],[-18,-12],touch);
    const textMoved=await snapshot(page);translated(graphMoved.text,textMoved.text,width+'/rectangle text move');
    assert.deepEqual(textMoved.graphs,graphMoved.graphs);assert.deepEqual(textMoved.camera,graphMoved.camera);
    await page.waitForFunction(()=>ocrTasks.get('region-fixture').scanState.textRegions[0].status==='complete');
    for(const kind of ['graph','text']){
      const prior=await snapshot(page),outline=prior[kind],edge=[(outline[0][0]+outline[1][0])/2,outline[0][1]];
      await drag(page,edge,[0,-12],touch);
      const current=await snapshot(page);
      assert.ok(minima(current[kind])[1]<minima(outline)[1]-.003,kind+': a rectangular edge can still be resized');
      assert.ok(Math.abs(maxima(current[kind])[1]-maxima(outline)[1])<1e-6,kind+': resizing retains the opposite edge');
      assert.deepEqual(current.camera,prior.camera);
    }
    await page.waitForFunction(()=>{const state=ocrTasks.get('region-fixture').scanState;
      return state.graphRegions[0].status==='complete'&&state.textRegions[0].status==='complete';});

    // Pinch zoom and the desktop's explicit Shift-pan remain navigation.
    if(touch){
      const prior=await snapshot(page),area=await page.locator('.dge-overlay-viewport').boundingBox(),client=await context.newCDPSession(page),
        center={x:area.x+area.width/2,y:area.y+area.height/2};
      await client.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:center.x-30,y:center.y,id:1}]});
      await client.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:center.x-30,y:center.y,id:1},{x:center.x+30,y:center.y,id:2}]});
      await client.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:center.x-44,y:center.y,id:1},{x:center.x+44,y:center.y,id:2}]});
      await client.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await client.detach();await settle(page);
      const current=await snapshot(page);assert.deepEqual(current.graphs,prior.graphs);assert.deepEqual(current.texts,prior.texts);
      assert.notEqual(current.camera[2],prior.camera[2],'Pinch still zooms the original image');
    }else{
      const prior=await snapshot(page),corner=prior.graph[0];
      await drag(page,[corner[0]+.13,corner[1]+.12],[13,9],false,true);
      const current=await snapshot(page);assert.deepEqual(current.graphs,prior.graphs);assert.deepEqual(current.texts,prior.texts);
      assert.notDeepEqual(current.camera,prior.camera,'Shift-drag still pans without editing a rectangle');
    }
    assert.deepEqual(errors,[]);assert.deepEqual(unexpected,[]);
    console.log('PASS '+width+': saved/new irregular regions are final, selection and redraw remain, rectangles and canvas navigation still work');
  }finally{await context.close();}
}
(async()=>{const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.CHROMIUM_EXECUTABLE_PATH}:{})});
try{for(const width of [1440,390])await runCase(browser,width);}finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
