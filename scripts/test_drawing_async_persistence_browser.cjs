/* Real drawing controls with delayed local commits; no model/API requests. */
'use strict';
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const json = value => ({contentType:'application/json',body:JSON.stringify(value)});

async function run(browser,width) {
  const context=await browser.newContext({viewport:{width,height:1000},serviceWorkers:'block'});
  const page=await context.newPage(), errors=[],unexpected=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/auth/me',route=>route.fulfill(json({configured:true,authenticated:false})));
  await page.route(/\/(?:chat|ocr(?:\/[^?]*)?|graph\/[^?]*|drawing\/(?:guide|generate|upload)|notebook\/analyze|sync|classify|analyze-questions|conversation\/title)(?:\?|$)/,
    route=>{unexpected.push(new URL(route.request().url()).pathname);return route.abort();});
  try {
    await page.goto(baseURL,{waitUntil:'networkidle'});
    await page.evaluate(()=>{
      const seed={version:2,activeId:'first-page',custom:{preserve:'gallery metadata'},pages:[{
        id:'first-page',name:'PRIVATE first drawing',createdAt:10,updatedAt:20,requirement:'PRIVATE request',
        document:{body_text:'',graphs:[{id:'G1',name:'PRIVATE first drawing',directed:false,weighted:false,
          vertices:[{id:'v1',label:'A',x:200,y:200},{id:'v2',label:'B',x:500,y:400}],
          edges:[{id:'e1',from:'v1',to:'v2',direction:'undirected'}]}]}}]};
      const fixture=window.asyncDrawingFixture={mode:'auto',failCode:'STORAGE_FAILED',calls:[],pending:[],committed:null,notices:[],storageCalls:[]};
      const copy=value=>JSON.parse(JSON.stringify(value));
      const originalMount=DMateGraphEditor.mount;
      DMateGraphEditor.mount=(host,options)=>{fixture.editorOptions=options;return originalMount(host,options);};
      DMateDeleteConfirm.request=(_owner,settings)=>{fixture.notices.push(settings.body);return Promise.resolve(false);};
      for(const name of ['getItem','setItem','removeItem']){
        const original=Storage.prototype[name];Storage.prototype[name]=function(...args){
          if(new Error().stack.includes('drawing-workspace.js')){
            fixture.storageCalls.push(name);throw new Error('Drawing persistence touched Web Storage');
          }
          return original.apply(this,args);
        };
      }
      const forbiddenSession=new Proxy({}, {get(){throw Error('Legacy session read');},set(){throw Error('Legacy session write');}});
      fixture.mount=initial=>DMateDrawingWorkspace.mount(document.getElementById('graphEditorMount'),{
        storageKey:'must-not-read-or-write',persistent:true,sessionState:forbiddenSession,
        features:{ai:false,upload:false},confirmDelete:()=>Promise.resolve(true),
        persistence:{initialGallery:initial,save:async snapshot=>{
          fixture.calls.push(copy(snapshot));
          if(fixture.mode==='fail')throw Object.assign(new Error('Fixture save failure'),{code:fixture.failCode});
          if(fixture.mode==='hold')await new Promise((resolve,reject)=>fixture.pending.push({resolve,reject}));
          fixture.committed=copy(snapshot);
        }}
      });
      fixture.controller=fixture.mount(seed);
      showGraphEditorDialog(document.getElementById('graphEditorDialog'));
    });
    assert.equal(await page.evaluate(()=>asyncDrawingFixture.controller.flush()),true);
    assert.equal(await page.evaluate(()=>asyncDrawingFixture.controller.hasUnsavedChanges()),false);
    assert.equal(await page.evaluate(()=>asyncDrawingFixture.controller.getPages()[0].name),'PRIVATE first drawing');

    await page.evaluate(()=>{asyncDrawingFixture.mode='hold';});
    await page.locator('.ddw-name').fill('PRIVATE edit one');
    await page.waitForFunction(()=>asyncDrawingFixture.pending.length===1);
    await page.locator('.ddw-name').fill('PRIVATE edit two');
    assert.equal(await page.evaluate(()=>asyncDrawingFixture.controller.hasUnsavedChanges()),true,
      'Changes are dirty immediately, including during the save debounce');
    await page.evaluate(()=>asyncDrawingFixture.pending.shift().resolve());
    assert.equal(await page.evaluate(()=>asyncDrawingFixture.controller.hasUnsavedChanges()),true,
      'An older completed snapshot cannot mark a newer edit as saved');
    assert.equal(await page.evaluate(()=>asyncDrawingFixture.committed.pages[0].name),'PRIVATE edit one');
    await page.waitForFunction(()=>asyncDrawingFixture.pending.length===1);

    await page.evaluate(()=>{
      const fixture=asyncDrawingFixture;fixture.confirmed=false;
      fixture.confirmation=fixture.editorOptions.onConfirm(fixture.controller.getDocument()).then(()=>{fixture.confirmed=true;});
    });
    assert.equal(await page.evaluate(()=>asyncDrawingFixture.confirmed),false,'Editor save waits for the encrypted commit');
    assert.equal(await page.evaluate(async()=>{
      const fixture=asyncDrawingFixture;fixture.mode='auto';for(const pending of fixture.pending.splice(0))pending.resolve();
      await fixture.confirmation;return fixture.controller.flush();
    }),true);
    assert.equal(await page.evaluate(()=>asyncDrawingFixture.confirmed),true);
    assert.equal(await page.evaluate(()=>asyncDrawingFixture.committed.pages[0].name),'PRIVATE edit two');

    await page.evaluate(()=>{asyncDrawingFixture.mode='fail';});
    await page.locator('.ddw-name').fill('PRIVATE retained after failure');
    const failed=await page.evaluate(async()=>{
      const fixture=asyncDrawingFixture, saved=await fixture.controller.flush();let rejected=false;
      try{await fixture.editorOptions.onConfirm(fixture.controller.getDocument());}catch(_){rejected=true;}
      await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
      return {saved,rejected,dirty:fixture.controller.hasUnsavedChanges(),name:fixture.controller.getPages()[0].name,
        warning:fixture.notices.some(text=>text.includes('绘图未能保存'))};
    });
    assert.deepEqual(failed,{saved:false,rejected:true,dirty:true,name:'PRIVATE retained after failure',warning:true});
    assert.equal(await page.evaluate(async()=>{
      const fixture=asyncDrawingFixture;fixture.failCode='QUOTA_EXCEEDED';await fixture.controller.flush();
      await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
      return fixture.notices.some(text=>text.includes('存储空间不足'));
    }),true,'Quota failure displays its actual cause');
    assert.equal(await page.evaluate(async()=>{asyncDrawingFixture.mode='auto';return asyncDrawingFixture.controller.flush();}),true);

    await page.locator('.ddw-page-actions > button').filter({hasText:'新建空白页'}).click();
    await page.locator('.ddw-name').fill('PRIVATE second page');
    assert.equal(await page.evaluate(()=>asyncDrawingFixture.controller.flush()),true);
    assert.equal(await page.evaluate(()=>asyncDrawingFixture.committed.pages.length),2);
    await page.locator('.ddw-page-actions > button').filter({hasText:'历史绘图'}).click();
    await page.locator('.ddw-history-open').filter({hasText:'PRIVATE retained after failure'}).click();
    await page.evaluate(()=>asyncDrawingFixture.controller.flush());
    assert.equal(await page.evaluate(()=>asyncDrawingFixture.committed.activeId),'first-page','Changing the selected page is persisted');
    await page.locator('.ddw-history-item').filter({hasText:'PRIVATE second page'}).locator('.ddw-history-delete').click();
    await page.waitForFunction(()=>asyncDrawingFixture.controller.getPages().length===1);
    await page.evaluate(()=>asyncDrawingFixture.controller.flush());
    assert.equal(await page.evaluate(()=>asyncDrawingFixture.committed.pages.length),1,'Page deletion is part of the saved gallery');

    const reopened=await page.evaluate(async()=>{
      const fixture=asyncDrawingFixture;fixture.controller.destroy();fixture.controller=fixture.mount(JSON.stringify(fixture.committed));
      const saved=await fixture.controller.flush();return{saved,pages:fixture.controller.getPages(),metadata:fixture.committed.custom,storage:fixture.storageCalls};
    });
    assert.equal(reopened.saved,true);assert.equal(reopened.pages.length,1);
    assert.equal(reopened.pages[0].name,'PRIVATE retained after failure');
    assert.deepEqual(reopened.metadata,{preserve:'gallery metadata'});assert.deepEqual(reopened.storage,[]);
    assert.deepEqual(errors,[]);assert.deepEqual(unexpected,[]);
    console.log('PASS '+width+': async drawing commits, failure retention/retry, gallery mutations and reopen without Web Storage');
  } finally {await context.close();}
}
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.CHROMIUM_EXECUTABLE_PATH}:{})});
  try{for(const width of [1440,390])await run(browser,width);}finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
