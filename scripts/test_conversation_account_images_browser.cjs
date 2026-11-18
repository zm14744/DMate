/* Real browser-profile shutdown/reopen; account, OCR and solver APIs are fixtures. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {chromium} = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const owners = ['image-account-a', 'image-account-b'], ids = ['image-session-one', 'image-session-two'];
const image = name => '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="60"><text x="2" y="20">' + name + '</text></svg>';
const clone = value => JSON.parse(JSON.stringify(value));
const snapshot = owner => ({schemaVersion:1,sessions:{currentId:null,deletedSessionIds:{},sessions:ids.map(id =>
  ({id,name:owner + ' ' + id,nameSource:'user',createdAt:1700000000000,messages:[],teaching:null,learningQuestion:null,retest:null}))},learning:{}});
const json = value => ({contentType:'application/json',body:JSON.stringify(value)});
const server = {owner:owners[0],accounts:new Map(owners.map(owner => [owner,{revision:2,data:snapshot(owner)}])),
  recognitions:0, chats:0, hold:false, errors:[],unexpected:[]};
const profile = fs.mkdtempSync(path.join(os.tmpdir(),'dmate-account-images-'));
let context;
async function launch() {
  context = await chromium.launchPersistentContext(profile,{headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE_PATH || '/usr/bin/chromium',
    viewport:{width:1440,height:1000},serviceWorkers:'block',args:['--no-sandbox']});
  context.on('page',page=>page.on('pageerror',error=>server.errors.push(error.message)));
  await context.addInitScript(() => {
    const put=IDBObjectStore.prototype.put; window.imageBlobWrites=0;
    IDBObjectStore.prototype.put=function(...args){if(this.name==='files')window.imageBlobWrites++;return put.apply(this,args);};
  });
  await context.route('**/*',async route=>{
    const request=route.request(), endpoint=new URL(request.url()).pathname;
    if(endpoint==='/auth/me')return route.fulfill(json({configured:true,authenticated:Boolean(server.owner),...(server.owner?{user:{username:server.owner,email:''}}:{})}));
    if(endpoint==='/auth/logout'){server.owner='';return route.fulfill(json({ok:true}));}
    if(endpoint==='/auth/login'){server.owner=request.postDataJSON().identifier;return route.fulfill(json({ok:true,configured:true,user:{username:server.owner,email:''}}));}
    if(endpoint==='/sync'){
      const account=server.accounts.get(server.owner);if(!account)return route.fulfill({status:401,...json({error:'Sign in'})});
      if(request.method()==='PUT'){const body=request.postDataJSON();account.data=clone(body.data);account.revision=Math.max(account.revision,body.baseRevision||0)+1;return route.fulfill(json({ok:true,revision:account.revision}));}
      return route.fulfill(json({ok:true,revision:account.revision,data:clone(account.data)}));
    }
    if(endpoint==='/graph/session'||endpoint==='/ocr/cancel')return route.fulfill(json({ok:true}));
    if(endpoint==='/ocr/status'){
      const query=new URL(request.url()).searchParams;
      return route.fulfill(json({status:'processing',request_id:query.get('request_id'),source_sha256:query.get('source_sha256'),retry_after:2}));
    }
    if(endpoint==='/graph/source'){
      const encoded=request.postDataBuffer().toString('utf8');
      const field=name=>new RegExp('name="'+name+'"\\r\\n\\r\\n([^\\r]*)').exec(encoded)?.[1];
      return route.fulfill(json({ok:true,request_id:field('request_id'),source_sha256:field('source_sha256')}));
    }
    if(endpoint==='/ocr'){
      server.recognitions++;if(server.hold)return;
      return route.fulfill(json({text:'Recognized initial text',document:{body_text:'Recognized initial text',graphs:[]},source_sha256:'a'.repeat(64)}));
    }
    if(endpoint==='/graph/confirm'){
      const {document,source_sha256,request_id}=request.postDataJSON();
      const semantic_context={document,source_sha256,request_id,question_text:document.body_text,rendered_question_text:document.body_text,
        confirmation_token:'fixture-'+request_id,document_sha256:'b'.repeat(64),revision:1,profile:'editable-v1'};
      return route.fulfill(json({document,drawing_document:document,confirmation_token:semantic_context.confirmation_token,revision:1,semantic_context}));
    }
    if(endpoint==='/chat'){
      server.chats++;const reply='Saved fixture answer';
      return route.fulfill({contentType:'text/event-stream',body:'event: final\ndata: '+JSON.stringify({reply})+'\n\n'});
    }
    if(['/analyze-questions','/classify','/conversation/title'].includes(endpoint))return route.fulfill(json({entries:[]}));
    if(request.method()!=='GET'){server.unexpected.push(request.method()+' '+endpoint);return route.abort();}
    return route.continue();
  });
  const page=await context.newPage();await page.goto(baseURL,{waitUntil:'networkidle'});
  await page.waitForFunction(()=>!accountVerificationOperation&&!cloudInitialSyncInFlight);
  await page.evaluate(()=>stopCloudLivePolling());
  if(server.owner)await page.evaluate(()=>DMateAccountOcrDrafts.ready());
  return page;
}
async function select(page,id){await page.evaluate(id=>{currentId=id;renderAll();},id);}
async function upload(page,id,name){
  await select(page,id);const previous=server.recognitions;const taskCount=await page.evaluate(()=>getSessionOcrTasks().length);
  await page.locator('#imageInput').setInputFiles({name:name+'.svg',mimeType:'image/svg+xml',buffer:Buffer.from(image(name))});
  await page.waitForFunction(({id,expected})=>getSessionOcrTasks(id).length===expected,{id,expected:taskCount+1});
  await page.waitForFunction(()=>ocrRecognitionRuns.size>0||getSessionOcrTasks().every(task=>task.state==='ready'));
  assert.equal(server.recognitions,previous+1);
  if(!server.hold)await page.waitForFunction(()=>getSessionOcrTasks().every(task=>task.state==='ready'));
  return page.evaluate(name=>getSessionOcrTasks().find(task=>task.file.name===name+'.svg').id,name);
}
async function flush(page){assert.equal(await page.evaluate(()=>DMateAccountOcrDrafts.flush()),true);}
async function reopen(){await context.close();return launch();}
(async()=>{
  let page=await launch();
  await page.evaluate(()=>{const requestIds=['z-first-upload','a-second-upload','pending-upload'];makeOcrRequestId=()=>requestIds.shift()||crypto.randomUUID();});
  const aReady=await upload(page,ids[0],'PRIVATE_READY_SOURCE');
  const graph={id:'G1',name:'Edited graph',directed:false,weighted:false,vertices:[{id:'v1',x:10,y:20},{id:'v2',x:40,y:30}],edges:[{id:'e1',from:'v1',to:'v2',direction:'undirected'}]};
  await page.evaluate(({id,graph})=>{
    const task=ocrTasks.get(id);task.draft={body_text:'PRIVATE_EDITED_TEXT',graphs:[graph]};task.dirty=true;task.userRequest='Keep my edited graph';
    task.userEditedAt=Date.now();task.scanState={mode:'select',graphRegions:[{id:'region-one',polygon:[[0,0],[1,0],[1,1]]}],camera:{zoom:135,panX:18,panY:27}};
    task.textEditorState={mode:'text_rect',zoom:125,visible:true,regions:[{id:'text-one',text:'PRIVATE_TEXT_REGION'}]};renderOcrTasks();
  },{id:aReady,graph});
  await flush(page);
  const aSecond=await upload(page,ids[0],'PRIVATE_SECOND_SOURCE');
  await page.evaluate(()=>{for(const task of getSessionOcrTasks())task.groupId='1';renderOcrTasks();});
  await flush(page);
  server.hold=true;const aPending=await upload(page,ids[1],'PRIVATE_PENDING_SOURCE');await flush(page);
  assert.equal(await page.evaluate(()=>imageBlobWrites),3,'Each source blob is stored once');
  await page.evaluate(()=>{for(let i=0;i<8;i++)renderOcrTasks();});await flush(page);
  assert.equal(await page.evaluate(()=>imageBlobWrites),3,'Repeated rendering does not rewrite image blobs');
  page=await reopen();
  assert.equal(server.recognitions,3,'Closing and reopening the browser never restarts paid OCR');
  const restored=await page.evaluate(async({ready,pending})=>{
    const a=ocrTasks.get(ready),b=ocrTasks.get(pending);return{size:ocrTasks.size,ready:{draft:a.draft,scan:a.scanState,text:a.textEditorState,request:a.userRequest,bytes:await a.file.text()},
      pending:{state:b.state,bytes:await b.file.text()},cards:document.querySelectorAll('[data-ocr-task-id]').length};
  },{ready:aReady,pending:aPending});
  assert.equal(restored.size,3);assert.equal(restored.cards,0,'A fresh app opens home without another conversation image');
  assert.equal(restored.ready.draft.body_text,'PRIVATE_EDITED_TEXT');assert.deepEqual(restored.ready.draft.graphs,[graph]);
  assert.equal(restored.ready.scan.camera.zoom,135);assert.equal(restored.ready.text.regions[0].text,'PRIVATE_TEXT_REGION');
  assert.equal(restored.ready.request,'Keep my edited graph');assert.equal(restored.ready.bytes,image('PRIVATE_READY_SOURCE'));
  assert.equal(restored.pending.state,'recognizing');assert.equal(restored.pending.bytes,image('PRIVATE_PENDING_SOURCE'));
  assert.equal(await page.evaluate(()=>imageBlobWrites),0,'Restoring existing drafts does not rewrite original blobs');
  await select(page,ids[0]);assert.equal(await page.locator('[data-ocr-task-id]').count(),2);
  assert.deepEqual(await page.evaluate(()=>getSessionOcrTasks().map(task=>task.id)),[aReady,aSecond],'Upload order survives restart even when random IDs sort backwards');
  await select(page,ids[1]);assert.equal(await page.locator('[data-ocr-task-id]').count(),1);

  // Account B uses the same conversation IDs, but can read only its own images.
  server.owner=owners[1];page=await reopen();assert.equal(await page.evaluate(()=>ocrTasks.size),0);
  server.hold=false;const bReady=await upload(page,ids[0],'PRIVATE_B_SOURCE');await flush(page);
  server.owner=owners[0];page=await reopen();assert.equal(await page.evaluate(()=>ocrTasks.size),3);
  assert.equal(await page.evaluate(id=>ocrTasks.has(id),bReady),false,'Different verified accounts never share image drafts');
  await select(page,ids[0]);await page.locator('#sendBtn').click();
  await page.waitForFunction(id=>!ocrTasks.has(id)&&!ocrBatchRuns.size,aReady,{timeout:8000}).catch(async error=>{
    console.error('Send fixture state',await page.evaluate(()=>({tasks:[...ocrTasks.values()].map(t=>({id:t.id,error:t.error,state:t.state,confirm:t.confirmation})),messages:getCurrent()?.messages,runs:ocrBatchRuns.size})),server.chats,server.unexpected,server.errors);throw error;
  });
  assert.equal(server.chats,1,'The saved edited graph can be sent through fixture confirmation and solver');
  await page.evaluate(async()=>{saveState();await pushCloudSnapshot(false);});
  await flush(page);page=await reopen();assert.equal(await page.evaluate(id=>ocrTasks.has(id),aReady),false,'A successfully sent image is consumed durably');
  await page.evaluate(id=>{markSessionDeleted(id);sessions=sessions.filter(session=>session.id!==id);saveState();renderAll();},ids[1]);
  await page.evaluate(()=>pushCloudSnapshot(false));await flush(page);page=await reopen();
  assert.equal(await page.evaluate(()=>ocrTasks.size),0,'Deleting a conversation consumes its persisted image drafts');

  // A cloud conflict can keep both old and forked conversations: only the fork owns the image.
  const remapped=await upload(page,ids[0],'PRIVATE_REMAP_SOURCE');await flush(page);
  const split='image-session-one-split';
  await page.evaluate(async({previous,next,id})=>{
    sessions.push({...sessions.find(session=>session.id===previous),id:next,name:'Forked conversation',messages:[]});
    ocrTasks.get(id).sessionId=next;await remapAccountOcrDrafts(previous,next);saveState();await pushCloudSnapshot(false);
  },{previous:ids[0],next:split,id:remapped});
  page=await reopen();
  assert.equal(await page.evaluate(id=>ocrTasks.get(id)?.sessionId,remapped),split,'Durable remap cannot attach an image to the still-existing old conversation');
  await select(page,ids[0]);assert.equal(await page.locator('[data-ocr-task-id]').count(),0);
  await select(page,split);assert.equal(await page.locator('[data-ocr-task-id]').count(),1);
  await page.evaluate(id=>removeOcrTask(id),remapped);await flush(page);

  // Logout removes owner data, and an ordinary guest cannot read the retained B owner.
  server.hold=false;await upload(page,ids[0],'PRIVATE_LOGOUT_SOURCE');await flush(page);
  const load=page.waitForEvent('load');await page.evaluate(()=>{void logoutAccount();});await load;
  await page.waitForFunction(()=>!accountVerificationOperation&&!accountState.authenticated);
  assert.equal(await page.evaluate(()=>ocrTasks.size),0);
  assert.equal(await page.evaluate(async owner=>{
    const rows=await DMateAccountImageDraftStore.load(owner);return rows.rows.length;
  },owners[0]),0,'Explicit logout removes account image metadata and source blobs');
  assert.equal(await page.evaluate(()=>ocrTasks.size),0,'Reading account identity markers never imports private images into a guest');
  server.owner=owners[0];page=await reopen();assert.equal(await page.evaluate(()=>ocrTasks.size),0,'Logging in again cannot resurrect logout drafts');
  server.owner=owners[1];page=await reopen();assert.equal(await page.evaluate(id=>ocrTasks.has(id),bReady),true,'Unrelated owner drafts survive another owner logout');
  // A real storage failure is visible and retains the in-memory original for retry.
  await select(page,ids[0]);const recognitionCount=server.recognitions;
  const failedSave=await page.evaluate(async id=>{
    const transaction=IDBDatabase.prototype.transaction;
    IDBDatabase.prototype.transaction=function(...args){
      if(this.name==='dmate-account-image-drafts-v1')throw new DOMException('Fixture storage failure','QuotaExceededError');
      return transaction.apply(this,args);
    };
    try{ocrTasks.get(id).userRequest='Retry saved requirement';const saved=await DMateAccountOcrDrafts.flush();
      if(typingTimer)forceCompleteTyping();return{saved,warning:accountOcrSaveFailure,bytes:await ocrTasks.get(id).file.text(),
        visible:document.body.textContent.includes('图片草稿未能保存到本机')};}
    finally{IDBDatabase.prototype.transaction=transaction;}
  },bReady);
  assert.deepEqual(failedSave,{saved:false,warning:true,bytes:image('PRIVATE_B_SOURCE'),visible:true});
  await flush(page);assert.equal(await page.evaluate(()=>accountOcrSaveFailure),false);
  assert.equal(server.recognitions,recognitionCount,'A storage failure never triggers another OCR request');
  assert.deepEqual(server.errors,[]);assert.deepEqual(server.unexpected,[]);
  console.log('PASS account images: real browser restart, edited graph/text/camera and exact source blobs, per-owner/session isolation, interrupted OCR without retry, send/delete/logout consumption, stable blob storage');
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{if(context)await context.close();fs.rmSync(profile,{recursive:true,force:true});});
