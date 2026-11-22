/* Real profile restarts and delayed task recovery; every account/model API is local. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const {execFileSync} = require('node:child_process');
const {chromium} = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const baseline = process.env.DMATE_TEST_BASELINE_HEAD === '1';
const ownerA = '图形学习者', ownerB = 'reopen-owner-b';
const sessions = ['reopen-conversation-a', 'reopen-conversation-b'];
const clone = value => JSON.parse(JSON.stringify(value));
const json = value => ({contentType:'application/json',body:JSON.stringify(value)});
const image = id => '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80"><text x="8" y="30">'+id+'</text></svg>';
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
const snapshot = () => ({schemaVersion:1,sessions:{currentId:null,deletedSessionIds:{},sessions:sessions.map(id =>
  ({id,name:id,nameSource:'user',createdAt:1700000000000,messages:[],teaching:null,learningQuestion:null,retest:null}))},learning:{}});
function field(request, name) {
  return new RegExp('name="'+name+'"\\r\\n\\r\\n([^\\r]*)').exec(request.postDataBuffer().toString('utf8'))?.[1] || '';
}
async function until(predicate, message, timeout=10000) {
  const deadline=Date.now()+timeout;
  while(Date.now()<deadline){if(await predicate())return;await new Promise(resolve=>setTimeout(resolve,25));}
  assert.fail(message);
}
async function fixture(run) {
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),'dmate-ocr-reopen-'));
  const state={owner:ownerA,accounts:new Map([ownerA,ownerB].map(owner=>[owner,{revision:2,data:snapshot()}])),
    jobs:new Map(),posts:[],reads:[],sources:[],bindings:new Set(),held:[],holdStatus:new Set(),
    mode:'processing',modelStarts:0,chats:0,errors:[],unexpected:[],expiredStatusOwners:new Set()};
  let context;
  const key=(owner,id)=>owner+'|'+id;
  const result=id=>({request_id:id,source_sha256:hash(image(id)),text:'恢复后的完整识别内容 '+id,
    document:{body_text:'恢复后的完整识别内容 '+id,graphs:[]},recognition_status:'completed'});
  function status(id, owner) {
    const job=state.jobs.get(key(owner,id));
    return {status:job?.status||'missing',request_id:id,source_sha256:hash(image(id)),
      ...(job?.status==='completed'?{result:job.result,http_status:200}:{}),retry_after:0.05};
  }
  async function fulfillStatus(route,id,owner) {await route.fulfill(json(status(id,owner))).catch(()=>{});}
  async function release(id) {
    state.holdStatus.delete(id);
    const ready=state.held.filter(item=>item.id===id);state.held=state.held.filter(item=>item.id!==id);
    for(const item of ready)await fulfillStatus(item.route,item.id,item.owner);
  }
  async function open() {
    context=await chromium.launchPersistentContext(profile,{headless:true,viewport:{width:1440,height:1000},
      executablePath:process.env.CHROMIUM_EXECUTABLE_PATH||'/usr/bin/chromium',serviceWorkers:'block',args:['--no-sandbox']});
    context.on('page',page=>page.on('pageerror',error=>state.errors.push(error.message)));
    await context.route('**/*',async route=>{
      const request=route.request(),url=new URL(request.url()),endpoint=url.pathname;
      if(baseline&&endpoint==='/static/script.js')return route.fulfill({contentType:'application/javascript',
        body:execFileSync('git',['show','HEAD:static/script.js'],{encoding:'utf8'})});
      if(endpoint==='/auth/me')return route.fulfill(json({configured:true,authenticated:Boolean(state.owner),
        ...(state.owner?{user:{username:state.owner,email:''}}:{})}));
      if(endpoint==='/sync'){
        const account=state.accounts.get(state.owner);if(!account)return route.fulfill({status:401,...json({error:'Sign in'})});
        if(request.method()==='PUT'){const body=request.postDataJSON();account.data=clone(body.data);account.revision++;return route.fulfill(json({ok:true,revision:account.revision}));}
        return route.fulfill(json({ok:true,revision:account.revision,data:clone(account.data)}));
      }
      if(endpoint==='/graph/session')return route.fulfill(json({ok:true}));
      if(endpoint==='/ocr/status'){
        const id=url.searchParams.get('request_id'),owner=state.owner;
        assert.equal(decodeURIComponent(request.headers()['x-dmate-draft-owner']),owner,'Recovery status is bound to the verified account');
        assert.equal(url.searchParams.get('source_sha256'),hash(image(id)),'Recovery asks about the exact original pixels');
        state.reads.push({id,owner});
        // Restored and newly opened tabs share the same account session.
        if(state.expiredStatusOwners.has(owner))return route.fulfill({status:401,...json({error:'登录状态已变化，请重新登录后继续图片识别'})});
        if(state.holdStatus.has(id)){state.held.push({id,owner,route});return;}
        return fulfillStatus(route,id,owner);
      }
      if(endpoint==='/ocr'){
        const id=field(request,'request_id'),owner=state.owner;
        assert.ok(request.postDataBuffer().includes(Buffer.from(image(id))),'An upload/recovery keeps the original image bytes');
        state.posts.push({id,owner});
        if(state.mode==='missing'){return;}
        state.modelStarts++;
        state.bindings.add(key(owner,id));
        const job={status:state.mode==='completed'?'completed':'processing',result:result(id)};
        state.jobs.set(key(owner,id),job);
        if(job.status==='completed')return route.fulfill(json(job.result));
        if(state.mode==='accepted')return route.fulfill({status:202,...json({status:'processing',request_id:id,
          source_sha256:hash(image(id)),retry_after:0.05})});
        return; // The server keeps its task even when this HTTP document disappears.
      }
      if(endpoint==='/ocr/cancel'){
        const id=request.postDataJSON().request_id,job=state.jobs.get(key(state.owner,id));
        if(job)job.status='cancelled';
        return route.fulfill(json({cancelled:true}));
      }
      if(endpoint==='/graph/source'){
        const id=field(request,'request_id'),sha=field(request,'source_sha256');
        assert.equal(sha,hash(image(id)));assert.ok(request.postDataBuffer().includes(Buffer.from(image(id))));
        state.sources.push(id);state.bindings.add(key(state.owner,id));
        return route.fulfill(json({ok:true,request_id:id,source_sha256:sha}));
      }
      if(endpoint==='/graph/confirm'){
        const data=request.postDataJSON(),id=data.request_id;
        if(!state.bindings.has(key(state.owner,id)))return route.fulfill({status:409,...json({error:'Original source expired',error_code:'unknown_source_task'})});
        const semantic_context={request_id:id,source_sha256:data.source_sha256,document:data.document,
          question_text:data.document.body_text,rendered_question_text:data.document.body_text,
          confirmation_token:'fixture-'+id,document_sha256:'b'.repeat(64),revision:1,profile:'editable-v1'};
        return route.fulfill(json({document:data.document,drawing_document:data.document,semantic_context,
          confirmation_token:semantic_context.confirmation_token,revision:1}));
      }
      if(endpoint==='/chat'){
        state.chats++;const reply='恢复后可以继续解题';
        return route.fulfill({contentType:'text/event-stream',body:'event: final\ndata: '+JSON.stringify({reply})+'\n\n'});
      }
      if(['/analyze-questions','/classify','/conversation/title'].includes(endpoint))return route.fulfill(json({entries:[]}));
      if(request.method()!=='GET'||/^\/(?:ocr|graph)\//.test(endpoint)){
        state.unexpected.push(request.method()+' '+endpoint);return route.abort();
      }
      return route.continue();
    });
    const page=await context.newPage();await page.goto(baseURL,{waitUntil:'domcontentloaded'});
    await page.waitForFunction(()=>!accountVerificationOperation&&!cloudInitialSyncInFlight,{timeout:15000});
    await page.evaluate(()=>stopCloudLivePolling());
    await page.evaluate(()=>DMateAccountOcrDrafts.ready());
    return page;
  }
  async function reopen(beforeOpen){await context.close();beforeOpen?.();return open();}
  async function select(page,id){await page.evaluate(id=>{currentId=id;renderAll();},id);}
  async function upload(page,id,session=sessions[0]){
    await select(page,session);await page.evaluate(id=>{makeOcrRequestId=()=>id;},id);
    await page.locator('#imageInput').setInputFiles({name:id+'.svg',mimeType:'image/svg+xml',buffer:Buffer.from(image(id))});
    await until(()=>state.posts.some(item=>item.id===id),'The original upload reaches its owner');
    await page.evaluate(()=>DMateAccountOcrDrafts.flush());
  }
  async function recovering(page,id){
    await until(()=>state.reads.some(item=>item.id===id),'A restored recognizing image must resume its existing server task rather than become failed',8000);
    assert.equal(await page.evaluate(id=>ocrTasks.get(id)?.state,id),'recognizing');
  }
  async function completed(page,id){
    await page.waitForFunction(id=>ocrTasks.get(id)?.state==='ready',id,{timeout:10000});
    assert.equal(await page.evaluate(id=>ocrTasks.get(id).draft.body_text,id),result(id).document.body_text);
    assert.equal(await page.evaluate(id=>ocrTasks.get(id).error||'',id),'');
  }
  const api={state,open,reopen,select,upload,recovering,completed,release,key,result};
  try{await run(api);assert.deepEqual(state.errors,[]);assert.deepEqual(state.unexpected,[]);}
  finally{if(context)await context.close();fs.rmSync(profile,{recursive:true,force:true});}
}
async function runningResume(api){
  const {state,open,reopen,upload,recovering,completed,key,result,select}=api;
  const id='running-original';let page=await open();await upload(page,id);page=await reopen();
  await recovering(page,id);
  assert.equal(state.posts.length,1,'Reopening an active task never reuploads or starts another model call');
  state.jobs.set(key(ownerA,id),{status:'completed',result:result(id)});await completed(page,id);
  assert.equal(state.modelStarts,1);assert.equal(await page.locator('[data-ocr-task-id]').count(),0,'Background recovery does not open another conversation');
  await select(page,sessions[0]);assert.equal(await page.locator('[data-ocr-task-id]').count(),1);
  assert.equal(state.posts.length,1);console.log('PASS browser shutdown resumes an active task by status only and shows its completed result');
}
async function completedRebind(api){
  const {state,open,reopen,upload,select}=api;state.mode='completed';const id='completed-original';
  let page=await open();await upload(page,id);await page.waitForFunction(id=>ocrTasks.get(id)?.state==='ready',id);
  await page.evaluate(id=>{const task=ocrTasks.get(id);task.draft.body_text='保留已编辑的题干';task.dirty=true;task.userEditedAt=Date.now();renderOcrTasks();},id);
  await page.evaluate(()=>DMateAccountOcrDrafts.flush());state.bindings.clear();page=await reopen();
  assert.equal(state.posts.length,1);assert.equal(state.sources.length,0,'Opening cached recognition does not perform source or model work');
  await select(page,sessions[0]);assert.equal(await page.evaluate(id=>ocrTasks.get(id).draft.body_text,id),'保留已编辑的题干');
  await page.locator('#sendBtn').click();
  await page.waitForFunction(id=>!ocrTasks.has(id)&&!ocrBatchRuns.size,id,{timeout:10000});
  assert.equal(state.chats,1);assert.equal(state.sources.length,1,'Sending restores source binding without repeating recognition');
  assert.equal(state.posts.length,1);assert.equal(state.modelStarts,1);
  console.log('PASS completed and edited recognition survives shutdown; expired source registration is repaired without OCR');
}
async function legacyInterrupted(api){
  const {state,open,reopen,upload,completed,key,result}=api;const id='legacy-interrupted';
  let page=await open();await upload(page,id);
  await page.evaluate(async id=>{
    const task=ocrTasks.get(id);task.state='failed';
    task.error='上次关闭中断了图片识别，可以直接编辑原图和已有内容。';
    renderOcrTasks();await DMateAccountOcrDrafts.flush();
  },id);
  state.jobs.set(key(ownerA,id),{status:'completed',result:result(id)});
  page=await reopen();await completed(page,id);
  assert.equal(state.posts.length,1);assert.equal(state.modelStarts,1);
  assert.ok(state.reads.some(item=>item.id===id),'Previously broken interrupted drafts recover by their existing request ID');
  console.log('PASS previously saved interrupted-failure drafts recover existing results without another recognition');
}
async function missingResume(api){
  const {state,open,reopen,upload,completed,key,result}=api;state.mode='missing';const id='unreceived-original';
  let page=await open();await upload(page,id);state.mode='accepted';page=await reopen();
  await until(()=>state.posts.length===2&&state.reads.length>=2,'The recovered upload accepts HTTP 202 and watches the same task');
  state.jobs.set(key(ownerA,id),{status:'completed',result:result(id)});await completed(page,id);
  assert.equal(state.posts.length,2,'A task never received by the server resumes once with its original identity');
  assert.deepEqual(state.posts.map(item=>item.id),[id,id]);assert.equal(state.modelStarts,1);
  console.log('PASS an upload absent from the server resumes once with the same original file and request ID');
}
async function cancelledDeletedOwnerRace(api){
  const {state,open,reopen,upload,recovering,release,key,result,select}=api;
  const ids=['cancel-recovery','delete-recovery','owner-recovery'];let page=await open();
  await upload(page,ids[0]);await upload(page,ids[1],sessions[1]);await upload(page,ids[2]);
  ids.forEach(id=>state.holdStatus.add(id));page=await reopen();
  for(const id of ids)await recovering(page,id);
  await select(page,sessions[0]);await page.evaluate(id=>cancelOcrTask(id),ids[0]);
  state.jobs.set(key(ownerA,ids[0]),{status:'completed',result:result(ids[0])});await release(ids[0]);
  await page.waitForTimeout(100);assert.equal(await page.evaluate(id=>ocrTasks.has(id),ids[0]),false,'Cancellation wins over a late completed status');
  await page.evaluate(id=>{markSessionDeleted(id);sessions=sessions.filter(session=>session.id!==id);saveState();renderAll();},sessions[1]);
  state.jobs.set(key(ownerA,ids[1]),{status:'completed',result:result(ids[1])});await release(ids[1]);
  await page.waitForTimeout(100);assert.equal(await page.evaluate(id=>ocrTasks.has(id),ids[1]),false,'A deleted conversation cannot receive its old recognition');
  await page.evaluate(()=>expireVerifiedAccountSession(accountState.username,cloudSyncContextVersion));
  state.owner=ownerB;await page.evaluate(()=>restoreVerifiedAccountSession());
  state.jobs.set(key(ownerA,ids[2]),{status:'completed',result:result(ids[2])});await release(ids[2]);
  await page.waitForTimeout(100);assert.equal(await page.evaluate(()=>accountState.username),ownerB);
  assert.equal(await page.evaluate(()=>ocrTasks.size),0,'An old account response cannot enter the new verified account');
  assert.equal(state.posts.length,3);assert.equal(state.modelStarts,3);
  console.log('PASS cancelling, deleting and changing account discard late recovered results without restarting OCR');
}
async function editedRecoveryRace(api){
  const {state,open,reopen,upload,recovering,release,key,result}=api;const id='edited-recovery';
  let page=await open();await upload(page,id);state.holdStatus.add(id);page=await reopen();await recovering(page,id);
  await page.evaluate(id=>{const task=ocrTasks.get(id);task.draft={body_text:'用户恢复期间的新编辑',graphs:[]};task.dirty=true;task.userEditedAt=Date.now();renderOcrTasks();},id);
  state.jobs.set(key(ownerA,id),{status:'completed',result:result(id)});await release(id);
  await page.waitForFunction(id=>ocrTasks.get(id)?.state==='ready'&&!ocrTasks.get(id)?.recovering,id);
  assert.equal(await page.evaluate(id=>ocrTasks.get(id).draft.body_text,id),'用户恢复期间的新编辑','A late original result cannot replace newer user edits');
  assert.equal(state.posts.length,1);console.log('PASS a late recovered recognition preserves newer local edits');
}
async function groupedRecoveryRace(api){
  const {state,open,reopen,upload,recovering,completed,release,key,result,select}=api;const id='grouped-recovery';
  let page=await open();await upload(page,id);state.holdStatus.add(id);page=await reopen();await recovering(page,id);
  await select(page,sessions[0]);await page.locator('#ocrGroupButton').click();
  await page.locator('#ocrGroupingDialog [data-task-id="'+id+'"][data-group-question="false"]').click();
  await page.locator('#ocrGroupingDialog select[data-task-id="'+id+'"]').selectOption('3');
  await page.locator('#ocrGroupingDialog .ocr-group-close').click();
  assert.deepEqual(await page.evaluate(id=>{const task=ocrTasks.get(id);return{state:task.state,group:task.groupId,question:task.isQuestion};},id),
    {state:'recognizing',group:'3',question:false},'Grouping controls update metadata while recovery is still pending');
  state.jobs.set(key(ownerA,id),{status:'completed',result:result(id)});await release(id);await completed(page,id);
  assert.deepEqual(await page.evaluate(id=>{const task=ocrTasks.get(id);return{group:task.groupId,question:task.isQuestion,result:task.result};},id),
    {group:'3',question:false,result:result(id)},'A metadata-only change keeps the complete recognition and the new group/mode');
  await page.evaluate(()=>DMateAccountOcrDrafts.flush());page=await reopen();
  assert.deepEqual(await page.evaluate(id=>{const task=ocrTasks.get(id);return{group:task.groupId,question:task.isQuestion,result:task.result,draft:task.draft};},id),
    {group:'3',question:false,result:result(id),draft:result(id).document},'The completed result and chosen metadata survive another browser restart');
  assert.equal(state.posts.length,1);assert.equal(state.modelStarts,1);
  console.log('PASS group/mode changes during recovery preserve the full recognition result and persist both choices');
}
async function reverifiedRecovery(api){
  const {state,open,reopen,upload,completed,key,result}=api;const id='reverified-recovery';
  let page=await open();await upload(page,id);page=await reopen(()=>state.expiredStatusOwners.add(ownerA));
  await page.waitForFunction(id=>ocrTasks.get(id)?.state==='failed'&&ocrTasks.get(id)?.recoveryPending,id,{timeout:5000}).catch(async error=>{
    console.error('Revalidation fixture',await page.evaluate(id=>ocrTasks.get(id),id),state.reads,state.errors);throw error;
  });
  await page.evaluate(()=>DMateAccountOcrDrafts.flush());
  state.jobs.set(key(ownerA,id),{status:'completed',result:result(id)});
  page=await reopen(()=>state.expiredStatusOwners.delete(ownerA));await completed(page,id);
  assert.equal(await page.evaluate(id=>ocrTasks.get(id).draft.body_text,id),result(id).document.body_text);
  assert.equal(state.posts.length,1);assert.equal(state.modelStarts,1);
  console.log('PASS account revalidation resumes a paused recognition without starting it as a guest or repeating OCR');
}
(async()=>{
  for(const [name,run] of [['running',runningResume],['completed',completedRebind],['legacy',legacyInterrupted],['missing',missingResume],['isolation',cancelledDeletedOwnerRace],['edited',editedRecoveryRace],['grouped',groupedRecoveryRace],['reverified',reverifiedRecovery]]){
    if(process.env.DMATE_TEST_CASE&&!name.includes(process.env.DMATE_TEST_CASE))continue;
    await fixture(run);
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
