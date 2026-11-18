/* Start Flask first. Exercise cloud merges during OCR preparation without models. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';

(async () => {
  const browser = await chromium.launch({headless:true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? {executablePath:process.env.CHROMIUM_EXECUTABLE_PATH} : {})});
  const page = await browser.newPage();
  const errors = [], unexpected = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/auth/me', route => route.fulfill({contentType:'application/json',
    body:JSON.stringify({configured:true,authenticated:false})}));
  await page.route(/\/(?:chat|ocr(?:\/[^?]*)?|graph\/[^?]*|analyze-questions|classify|conversation\/title|sync)(?:\?|$)/,
    route => { unexpected.push(new URL(route.request().url()).pathname); return route.abort(); });
  try {
    await page.goto(baseURL,{waitUntil:'networkidle'});
    await page.waitForFunction(() => !accountVerificationOperation);
    const result = await page.evaluate(() => {
      newChat();
      const a = getCurrent(), oldId = a.id;
      a.name = 'A'; a.nameSource = 'user';
      newChat();
      const b = getCurrent();
      b.name = 'B'; b.nameSource = 'user';
      accountState.authenticated = true;
      accountState.username = 'ocr-sync-fixture';
      // A real batch waits for image confirmation before it starts any chat request.
      const makeRun = session => ({session,cancelled:false,preparing:true,
        contextVersion:cloudSyncContextVersion,controller:new AbortController()});
      const runA = makeRun(a), runB = makeRun(b);
      ocrBatchRuns.set(String(a.id),runA); ocrBatchRuns.set(String(b.id),runB);
      ocrSolvingSessions.add(a.id); ocrSolvingSessions.add(b.id);
      syncOcrBatchPreparing();
      const initial = {liveA:ocrBatchCanContinue(runA),liveB:ocrBatchCanContinue(runB),
        cloudBusy:cloudUiEditInProgress(),chatRequests:activeAiRequests.size};
      const sameSnapshot = JSON.parse(JSON.stringify(collectCloudSnapshot()));
      const appliedSame = applyCloudSnapshot(sameSnapshot);
      const same = {liveA:ocrBatchCanContinue(runA),liveB:ocrBatchCanContinue(runB),
        preservedA:sessions.includes(a),preservedB:sessions.includes(b)};

      DMateConversationDrafts.set(oldId,{text:'A pending requirements',manualQuestionMode:true});
      const file = new File(['source image'],'fixture.png',{type:'image/png'});
      const task = {id:'sync-source-image',sessionId:oldId,contextVersion:cloudSyncContextVersion,
        file,originalUrl:URL.createObjectURL(file),state:'ready',draft:{body_text:'A source',graphs:[]},
        startedAt:performance.now(),finishedAt:performance.now(),controller:null};
      ocrTasks.set(task.id,task);
      const branchId = String(oldId) + '-sync-fixture';
      const branchedSnapshot = JSON.parse(JSON.stringify(collectCloudSnapshot()));
      branchedSnapshot.sessions.sessions.find(session => String(session.id) === String(oldId)).id = branchId;
      const appliedBranch = applyCloudSnapshot(branchedSnapshot);
      const branch = {liveA:ocrBatchCanContinue(runA),liveB:ocrBatchCanContinue(runB),
        id:a.id,runMoved:ocrBatchRuns.get(branchId) === runA,oldRunRemoved:!ocrBatchRuns.has(String(oldId)),
        taskMoved:task.sessionId === branchId,solvingMoved:ocrSolvingSessions.has(branchId),
        draft:DMateConversationDrafts.get(branchId),oldDraft:DMateConversationDrafts.get(oldId)};

      const deletedSnapshot = JSON.parse(JSON.stringify(collectCloudSnapshot()));
      deletedSnapshot.sessions.sessions = deletedSnapshot.sessions.sessions.filter(session => String(session.id) !== branchId);
      deletedSnapshot.sessions.deletedSessionIds[branchId] = Date.now();
      const appliedDeletion = applyCloudSnapshot(deletedSnapshot);
      const deletion = {cancelledA:runA.cancelled,abortedA:runA.controller.signal.aborted,
        liveA:ocrBatchCanContinue(runA),liveB:ocrBatchCanContinue(runB),preservedB:sessions.includes(b),
        imageRemoved:!ocrTasks.has(task.id),draft:DMateConversationDrafts.get(branchId)};
      cancelOcrBatchRun(b.id);
      ocrBatchRuns.clear(); ocrSolvingSessions.clear();
      discardOcrTask(task); syncOcrBatchPreparing();
      return {initial,appliedSame,same,appliedBranch,branchId,branch,appliedDeletion,deletion};
    });
    assert.deepEqual(result.initial,{liveA:true,liveB:true,cloudBusy:true,chatRequests:0});
    assert.equal(result.appliedSame,true);
    assert.deepEqual(result.same,{liveA:true,liveB:true,preservedA:true,preservedB:true},
      'cloud merges retain both batches, including empty new conversations');
    assert.equal(result.appliedBranch,true);
    assert.deepEqual(result.branch,{liveA:true,liveB:true,id:result.branchId,runMoved:true,
      oldRunRemoved:true,taskMoved:true,solvingMoved:true,
      draft:{text:'A pending requirements',manualQuestionMode:true},
      oldDraft:{text:'',manualQuestionMode:false}},'cloud conflict IDs move only the matching batch state');
    assert.equal(result.appliedDeletion,true);
    assert.deepEqual(result.deletion,{cancelledA:true,abortedA:true,liveA:false,liveB:true,preservedB:true,
      imageRemoved:true,draft:{text:'',manualQuestionMode:false}},
      'a cloud deletion cancels only its own batch');

    const consumed = await page.evaluate(async () => {
      await DMateAccountOcrDrafts.ready();
      const owner = accountState.username, sessionId = getCurrent().id;
      const file = new File(['consumed image'],'consumed.png',{type:'image/png'});
      const task = {id:'consumed-image',sessionId,contextVersion:cloudSyncContextVersion,
        file,originalUrl:URL.createObjectURL(file),state:'ready',draft:{body_text:'Already submitted',graphs:[]},
        startedAt:performance.now(),finishedAt:performance.now(),controller:null};
      ocrTasks.set(task.id,task);
      const saved = await DMateAccountOcrDrafts.flush();
      const originalStore = DMateAccountImageDraftStore;
      let release, removal;
      window.DMateAccountImageDraftStore = {...originalStore,remove(...args) {
        removal = new Promise((resolve,reject) => {
          release = () => originalStore.remove(...args).then(resolve,reject);
        });
        return removal;
      }};
      try {
        // Simulate a database operation queued until after account revalidation.
        removeOcrTask(task.id);
        await DMateAccountOcrDrafts.reset({purge:false});
        await release();
        await removal;
        const afterConsumption = await originalStore.load(owner);
        const generation = afterConsumption.generation;
        await originalStore.clearOwner(owner);
        const staleSaved = await originalStore.save(owner,generation,[{
          id:'stale-image',sessionId,file,state:'ready',draft:{body_text:'stale source',graphs:[]}
        }],() => true);
        const afterLogout = await originalStore.load(owner);
        return {saved,remaining:afterConsumption.rows.length,staleSaved,afterLogout:afterLogout.rows.length};
      } finally { window.DMateAccountImageDraftStore = originalStore; }
    });
    assert.deepEqual(consumed,{saved:true,remaining:0,staleSaved:false,afterLogout:0},
      'authorized consumption survives context reset; a logout generation rejects old writers');
    const savedAcrossExpiry = await page.evaluate(async () => {
      await DMateAccountOcrDrafts.ready();
      const owner = accountState.username;
      const file = new File(['edited source'],'edited.png',{type:'image/png'});
      const task = {id:'save-during-expiry',sessionId:currentId,contextVersion:cloudSyncContextVersion,
        file,originalUrl:URL.createObjectURL(file),state:'ready',draft:{body_text:'Previous text',graphs:[]},
        userEditedAt:1,startedAt:performance.now(),finishedAt:performance.now(),controller:null};
      ocrTasks.set(task.id,task);
      await DMateAccountOcrDrafts.flush();
      const originalStore = DMateAccountImageDraftStore;
      let release;
      window.DMateAccountImageDraftStore = {...originalStore,save(...args) {
        return new Promise((resolve,reject) => {
          release = () => originalStore.save(...args).then(resolve,reject);
        });
      }};
      try {
        task.draft.body_text = 'Latest user edit';
        task.userEditedAt = 2;
        const saving = DMateAccountOcrDrafts.flush();
        await DMateAccountOcrDrafts.reset({purge:false});
        await release();
        const activeContext = await saving;
        const stored = await originalStore.load(owner);
        return {activeContext,text:stored.rows.find(row => row.id === task.id)?.draft.body_text};
      } finally {
        window.DMateAccountImageDraftStore = originalStore;
        ocrTasks.delete(task.id); URL.revokeObjectURL(task.originalUrl);
        await originalStore.clearOwner(owner);
      }
    });
    assert.deepEqual(savedAcrossExpiry,{activeContext:false,text:'Latest user edit'},
      'a queued authorized edit persists for its owner after UI context expiry without updating the new context');
    assert.deepEqual(errors,[]);
    assert.deepEqual(unexpected,[],'no network inference or synchronization is needed by this fixture');
    console.log('PASS OCR confirmation waits survive cloud merges and conflict IDs; deletion cancels only its owner');
    console.log('PASS queued consumed-image deletion survives context reset; logout rejects stale image writers');
    console.log('PASS queued image edits persist across context expiry without updating stale UI state');
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
