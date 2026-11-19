/* Exercise the actual sidebar ZIP buttons against encrypted workspaces. No
 * backend backup endpoint or model is available to hide a broken local flow. */
'use strict';
const assert = require('node:assert/strict');
const {mkdtemp,readFile,rm} = require('node:fs/promises');
const {tmpdir} = require('node:os');
const {join} = require('node:path');
const {execFileSync} = require('node:child_process');
const {chromium} = require('playwright');
const {installStorageProbe,revealInterface,records} = require('./offline-vault-browser-fixtures.cjs');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const launch = {headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH
  ? {executablePath:process.env.CHROMIUM_EXECUTABLE_PATH} : {})};
const savedAt = '2026-10-01T08:00:00.000Z';
const note = {id:'source-note',title:'集合的概念',content:'幂集包含所有子集。',updatedAt:savedAt,
  custom:{source:'preserve the complete note record'}};
const mistake = {id:'source-mistake',title:'集合运算',statement:'求 $A \\cap B$。',
  answer:'$A \\cap B=\\{2,4\\}$',explanation:'逐个比较两个集合的元素。',
  knowledgePoints:['集合运算'],focusPoints:['交集'],status:'pending',createdAt:savedAt,updatedAt:savedAt,
  recognitionSnapshot:{version:1,question:'原始识别题目',points:['集合运算']},custom:{preserve:'answer metadata'}};
const gallery = {version:2,activeId:'source-page',custom:{preserve:'gallery metadata'},pages:[{
  id:'source-page',name:'带权有向图',createdAt:10,updatedAt:20,requirement:'保留顶点和边的权值',
  custom:{timeline:[1,3,5]},viewState:{zoom:1.2,x:10,y:20},
  document:{body_text:'可编辑数学图形',custom:{preserve:'document metadata'},graphs:[{
    id:'G1',name:'带权有向图',directed:true,weighted:true,
    vertices:[{id:'v1',label:'甲',x:210,y:220},{id:'v2',label:'乙',x:530,y:390}],
    edges:[{id:'e1',from:'v1',to:'v2',direction:'forward',weight:'7'}]
  }]}
}]};

async function open(browser,width,owner) {
  const context = await browser.newContext({viewport:{width,height:900},isMobile:width<1100,
    hasTouch:width<1100,serviceWorkers:'block',acceptDownloads:true});
  await installStorageProbe(context);
  const calls = [],errors = [];
  await context.route(/\/(?:chat|ocr|graph\/|notebook\/analyze|analyze-questions|sync|classify)(?:\/|\?|$)/,
    route => {calls.push(route.request().url());return route.abort();});
  await context.route('**/auth/me',route => route.fulfill({contentType:'application/json',body:JSON.stringify({
    configured:true,authenticated:Boolean(owner),user:owner ? {username:owner} : null})}));
  await context.route('**/__backup-fixture',route => route.fulfill({contentType:'text/html',body:
    '<!doctype html><script src="/static/guest-session.js"></script><a href="/offline">Offline</a>'}));
  const page = await context.newPage();
  page.on('pageerror',error => errors.push(error.message));
  await page.goto(baseURL+'/__backup-fixture');
  await page.evaluate(owner => DMateGuestSession.setAccountOwner(owner),owner);
  await page.locator('a').click();
  await revealInterface(page);
  return {context,page,calls,errors};
}

async function sidebar(page) {
  if (page.viewportSize().width <= 1100) {
    if (!await page.locator('body').evaluate(node => node.classList.contains('offline-nav-open')))
      await page.locator('#offlineNavToggle').click();
  } else if (await page.locator('#offlineDesktopSidebarOpen').isVisible()) {
    await page.locator('#offlineDesktopSidebarOpen').click();
  }
}

async function navigate(page,panel) {
  await sidebar(page);
  await page.locator('.offline-nav-item[data-panel="'+panel+'"]').click();
  await page.locator('#'+panel+'Panel').waitFor({state:'visible'});
}

async function idle(page) {
  await page.waitForFunction(() => {
    const button = document.getElementById('offlineImportDataBtn');
    return !button.disabled && button.getAttribute('aria-busy') !== 'true';
  });
}

async function importZIP(page,buffer,name='DMate-restored.zip') {
  await sidebar(page);
  const picked = page.waitForEvent('filechooser');
  await page.locator('#offlineImportDataBtn').click();
  const chooser = await picked;
  assert.equal(chooser.isMultiple(),false,'Import chooses exactly one ZIP package');
  await chooser.setFiles({name,mimeType:'application/zip',buffer});
  await idle(page);
}

async function createZIP(page,payload) {
  return Buffer.from(await page.evaluate(async payload =>
    [...new Uint8Array(await (await DMateOfflineBackup.create(payload)).arrayBuffer())],payload));
}

async function decodeZIP(page,buffer) {
  return page.evaluate(async bytes => {
    const value = await DMateOfflineBackup.read(new Blob([new Uint8Array(bytes)],{type:'application/zip'}));
    const attachment = value.notes[0]?.attachment;
    return {...value,attachment:attachment instanceof Blob ? {text:await attachment.text(),type:attachment.type} : null};
  },[...buffer]);
}

async function businessRows(page) {
  return page.evaluate(async () => {
    const result = {};
    for (const name of ['notes','mistakes','drawings']) result[name] = (await __offlineTestStore.all(name))
      .sort((a,b) => a.id.localeCompare(b.id));
    return result;
  });
}

async function downloadZIP(page,directory,name) {
  await sidebar(page);
  const downloaded = page.waitForEvent('download');
  await page.locator('#offlineExportDataBtn').click();
  const file = await downloaded;
  assert.match(file.suggestedFilename(),/^DMate-.*\.zip$/i,'Export produces a ZIP filename');
  const target = join(directory,name);
  await file.saveAs(target);
  await idle(page);
  const bytes = await readFile(target);
  assert.equal(bytes.subarray(0,4).toString('hex'),'504b0304','Export is a real ZIP archive');
  return {bytes,target};
}

async function nativeSaveProtocol(page) {
  let browserDownloads = 0;
  const downloaded = () => {browserDownloads++;};
  page.on('download',downloaded);
  await page.evaluate(() => {
    window.__nativeBackups = [];
    window.DMateFileSave = {postMessage(message) {__nativeBackups.push(JSON.parse(message));}};
  });
  try {
    await sidebar(page);
    await page.locator('#offlineExportDataBtn').click();
    await page.waitForFunction(() => window.__nativeBackups.length===1);
    const message = await page.evaluate(() => __nativeBackups[0]);
    assert.equal(message.mime,'application/zip');
    assert.match(message.name,/^DMate-.*\.zip$/i);
    const bytes = Buffer.from(message.data,'base64');
    assert.equal(bytes.subarray(0,4).toString('hex'),'504b0304','The native bridge receives actual ZIP bytes');
    assert.equal((await decodeZIP(page,bytes)).notes.length,1);
    assert.equal(await page.locator('#offlineExportDataBtn').isDisabled(),true,'Export awaits the native save response');
    await page.evaluate(() => DMateFileSave.onmessage({data:JSON.stringify({type:'dmate:file-save',id:'unrelated-save',ok:true})}));
    assert.equal(await page.locator('#offlineExportDataBtn').isDisabled(),true,'An unrelated native response does not complete this save');
    await page.evaluate(() => DMateFileSave.onmessage({data:JSON.stringify({type:'dmate:file-save',id:__nativeBackups[0].id,ok:true})}));
    await idle(page);
    assert.match(await page.locator('#offlineToast').innerText(),/已导出|exported/i);
    await page.evaluate(() => {document.getElementById('offlineToast').textContent='';document.getElementById('offlineToast').hidden=true;});
    await page.locator('#offlineExportDataBtn').click();
    await page.waitForFunction(() => window.__nativeBackups.length===2);
    await page.evaluate(() => DMateFileSave.onmessage({data:JSON.stringify({type:'dmate:file-save',id:__nativeBackups[1].id,cancelled:true})}));
    await idle(page);
    assert.doesNotMatch(await page.locator('#offlineToast').textContent(),/已导出|exported/i,'Cancellation does not claim that a ZIP was saved');
    assert.equal(browserDownloads,0,'A native save does not also trigger an unsupported WebView browser download');
    console.log('PASS Android save bridge protocol carries real ZIP bytes, waits for matching acknowledgement and handles cancellation');
  } finally {
    page.off('download',downloaded);
    await page.evaluate(() => {delete window.DMateFileSave;});
  }
}

(async () => {
  const directory = await mkdtemp(join(tmpdir(),'dmate-backup-browser-'));
  const browser = await chromium.launch(launch);
  let source,target;
  try {
    source = await open(browser,1440,'backup-source');
    const page = source.page;
    await page.evaluate(async data => {
      await __offlineTestStore.put('notes',{...data.note,attachment:new Blob(['PRIVATE ATTACHMENT'],{type:'text/plain'})});
      await __offlineTestStore.put('mistakes',data.mistake);
      await __offlineTestStore.put('drawings',{id:'gallery',gallery:JSON.stringify(data.gallery),updatedAt:data.note.updatedAt});
      await __offlineTestStore.put('settings',{id:'appearance',settings:{accent:'not part of this backup'}});
      await __offlineTestStore.put('practice',{id:'private-practice',answer:'not part of this backup'});
    },{note,mistake,gallery});
    await navigate(page,'notes');
    await page.locator('.dcn-note-open').click();
    await page.evaluate(() => {window.__holdNextOfflineNoteSave = true;});
    const edited = '正在输入的概念推导也必须进入备份：$|\\mathcal P(A)|=2^{|A|}$。';
    await page.locator('.dcn-original').fill(edited);
    await page.waitForFunction(() => typeof window.__releaseOfflineNoteSave === 'function');
    await sidebar(page);
    let downloadStarted = false;
    const pending = page.waitForEvent('download').then(value => {downloadStarted=true;return value;});
    await page.locator('#offlineExportDataBtn').click();
    await page.waitForTimeout(100);
    assert.equal(downloadStarted,false,'Export waits for the in-flight note save');
    await page.evaluate(() => window.__releaseOfflineNoteSave());
    const firstDownload = await pending;
    const firstPath = join(directory,'held-note.zip');
    await firstDownload.saveAs(firstPath);await idle(page);
    const initialBytes = await readFile(firstPath),initial = await decodeZIP(page,initialBytes);
    assert.equal(initial.notes[0].content,edited,'The currently edited concept is backed up');
    assert.deepEqual(initial.notes[0].custom,note.custom,'All note metadata survives export');
    assert.deepEqual(initial.attachment,{text:'PRIVATE ATTACHMENT',type:'text/plain'},'Binary note attachments survive the ZIP codec');
    assert.deepEqual(initial.mistakes,[mistake],'Wrong-question text, answer, analysis and recognition fields remain intact');
    assert.deepEqual(initial.drawings,gallery,'The complete editable drawing gallery is exported');

    await navigate(page,'drawing');
    await page.locator('.ddw-name').fill('尚未等待自动保存的绘图');
    const exported = await downloadZIP(page,directory,'complete-backup.zip');
    const decoded = await decodeZIP(page,exported.bytes);
    assert.equal(decoded.drawings.pages[0].name,'尚未等待自动保存的绘图','Export flushes the drawing debounce');
    assert.deepEqual(decoded.drawings.pages[0].custom,gallery.pages[0].custom);
    for (const kind of ['vertices','edges']) for (const original of gallery.pages[0].document.graphs[0][kind]) {
      const actual = decoded.drawings.pages[0].document.graphs[0][kind].find(row=>row.id===original.id);
      // The live editor may add derived position descriptions; every original
      // editable field, including labels, coordinates and edge weights, remains.
      assert.ok(actual,'The exported drawing retains '+kind+' '+original.id);
      for (const [key,value] of Object.entries(original)) assert.deepEqual(actual[key],value);
    }
    const zipCheck = JSON.parse(execFileSync('python3',['-c',
      'import json,sys,zipfile\nwith zipfile.ZipFile(sys.argv[1]) as z:\n assert z.testzip() is None\n print(json.dumps({"files":z.namelist(),"manifest":json.loads(z.read("manifest.json"))}))',
      exported.target],{encoding:'utf8'}));
    for (const filename of ['manifest.json','notes.json','mistakes.json','drawings.json']) assert.ok(zipCheck.files.includes(filename));
    assert.equal(zipCheck.manifest.format,'dmate-offline-backup');
    assert.equal(zipCheck.manifest.version,1);
    assert.equal(zipCheck.files.some(name => /settings|practice|vault|key|credential|account/i.test(name)),false,
      'The package contains only the requested personal study data and attachments');
    console.log('PASS real ZIP export includes pending concepts, wrong-question answers/analysis, binary attachments and editable drawings');
    await nativeSaveProtocol(page);

    target = await open(browser,390,'backup-target');
    const restored = target.page;
    const localNote = {...note,content:'LOCAL NEWER CONCEPT MUST REMAIN',updatedAt:'2026-11-20T10:00:00.000Z'};
    const localMistake = {...mistake,answer:'LOCAL NEWER ANSWER MUST REMAIN',updatedAt:'2026-11-20T10:00:00.000Z'};
    const localGallery = structuredClone(gallery);
    localGallery.pages[0].name = 'LOCAL NEWER DRAWING MUST REMAIN';
    localGallery.pages[0].updatedAt = 999999;
    await restored.evaluate(async data => {
      await __offlineTestStore.put('notes',data.note);
      await __offlineTestStore.put('notes',{id:'unrelated-note',title:'已有的其他概念',content:'保留现有记录',updatedAt:data.note.updatedAt});
      await __offlineTestStore.put('mistakes',data.mistake);
      await __offlineTestStore.put('drawings',{id:'gallery',gallery:JSON.stringify(data.gallery),updatedAt:data.note.updatedAt});
    },{note:localNote,mistake:localMistake,gallery:localGallery});
    await importZIP(restored,exported.bytes);
    const firstRestored = await businessRows(restored);
    assert.equal(firstRestored.notes.length,3,'Import merges concepts and retains unrelated notes');
    assert.ok(firstRestored.notes.some(row => row.id===note.id && row.content===localNote.content),'An existing conflicting note is retained');
    assert.ok(firstRestored.notes.some(row => row.content===edited),'The conflicting backup note is restored as a separate record');
    assert.equal(firstRestored.mistakes.length,2);
    assert.ok(firstRestored.mistakes.some(row => row.id===mistake.id && row.answer===localMistake.answer));
    assert.ok(firstRestored.mistakes.some(row => row.answer===mistake.answer && row.explanation===mistake.explanation));
    const mergedGallery = JSON.parse(firstRestored.drawings[0].gallery);
    assert.equal(mergedGallery.pages.length,2,'A conflicting drawing is retained alongside its restored version');
    assert.ok(mergedGallery.pages.some(row => row.name===localGallery.pages[0].name));
    assert.ok(mergedGallery.pages.some(row => row.name==='尚未等待自动保存的绘图'));
    await importZIP(restored,exported.bytes);
    assert.deepEqual(await businessRows(restored),firstRestored,'Importing the same ZIP again is idempotent');
    console.log('PASS mobile file chooser imports a portable ZIP into another account without overwriting existing or duplicating restored records');

    const copiedNote = firstRestored.notes.find(row=>row.content===edited);
    const copiedMistake = firstRestored.mistakes.find(row=>row.answer===mistake.answer);
    await restored.evaluate(async ids => {
      await __offlineTestStore.batch([
        {type:'delete',store:'notes',id:ids.note},
        {type:'put',store:'settings',value:{id:'notebook-deletions',deleted:{[ids.note]:Date.now()}}},
        {type:'delete',store:'mistakes',id:ids.mistake},
        {type:'put',store:'settings',value:{id:'mistake-deletions',deleted:{[ids.mistake]:Date.now()}}}
      ]);
    },{note:copiedNote.id,mistake:copiedMistake.id});
    await importZIP(restored,exported.bytes);
    const restoredAgain = await businessRows(restored);
    assert.equal(restoredAgain.notes.length,3);
    assert.ok(restoredAgain.notes.some(row=>row.content===edited && row.id!==copiedNote.id),
      'Deleting an earlier restored copy does not make a later restore invisible');
    assert.equal(restoredAgain.mistakes.length,2);
    assert.ok(restoredAgain.mistakes.some(row=>row.answer===mistake.answer && row.id!==copiedMistake.id));
    await importZIP(restored,exported.bytes);
    assert.deepEqual(await businessRows(restored),restoredAgain,'A restored replacement remains idempotent after an earlier copy was deleted');
    console.log('PASS deleting a restored copy still allows visible recovery and duplicate-free retries');

    await navigate(restored,'drawing');
    await restored.locator('.ddw-name').fill('IMPORT MUST RETAIN THIS CURRENT DRAWING EDIT');
    const extraGallery = structuredClone(gallery);
    extraGallery.activeId = extraGallery.pages[0].id = 'new-imported-page';
    extraGallery.pages[0].name = '本次新导入的绘图';
    const extraDrawingZIP = await createZIP(restored,{notes:[],mistakes:[],drawings:extraGallery});
    await importZIP(restored,extraDrawingZIP);
    await restored.locator('.ddw-name').waitFor({state:'visible'});
    assert.equal(await restored.locator('.ddw-name').inputValue(),'IMPORT MUST RETAIN THIS CURRENT DRAWING EDIT',
      'Import flushes the current local drawing and remounts the merged gallery');
    // The old editor's delayed persistence would otherwise replace the merged
    // gallery after the import returned successfully.
    await restored.waitForTimeout(450);
    const afterEditorImport = JSON.parse((await records(restored,'drawings'))[0].gallery);
    assert.equal(afterEditorImport.pages.length,3);
    assert.ok(afterEditorImport.pages.some(page=>page.id==='new-imported-page'));
    assert.ok(afterEditorImport.pages.some(page=>page.name==='IMPORT MUST RETAIN THIS CURRENT DRAWING EDIT'));
    await navigate(restored,'graph');
    console.log('PASS importing into a mounted drawing editor retains unsaved local edits and cannot overwrite restored pages later');

    const invalidBefore = await businessRows(restored);
    await importZIP(restored,Buffer.from('This is not a ZIP package'),'invalid.zip');
    assert.deepEqual(await businessRows(restored),invalidBefore,'An invalid ZIP changes no records');
    const damaged = Buffer.from(await restored.evaluate(async bytes => {
      const files = fflate.unzipSync(new Uint8Array(bytes));
      files['notes.json'] = fflate.strToU8(fflate.strFromU8(files['notes.json']).replace('集合的概念','损坏的概念'));
      return [...fflate.zipSync(files)];
    },[...exported.bytes]));
    await importZIP(restored,damaged,'tampered.zip');
    assert.deepEqual(await businessRows(restored),invalidBefore,'A valid ZIP with invalid integrity changes no records');
    assert.equal(await restored.locator('#offlineImportDataBtn').isEnabled(),true,'A rejected import leaves the control usable');
    console.log('PASS malformed packages and mismatched integrity leave every original study record untouched');

    const deletedNote = {id:'deleted-note',title:'恢复已删除概念',content:'从备份恢复的概念内容',updatedAt:savedAt};
    const deletedMistake = {...mistake,id:'deleted-mistake',statement:'从备份恢复的错题'};
    await restored.evaluate(async ids => {
      await __offlineTestStore.put('settings',{id:'notebook-deletions',deleted:{[ids.note]:Date.now()}});
      await __offlineTestStore.put('settings',{id:'mistake-deletions',deleted:{[ids.mistake]:Date.now()}});
    },{note:deletedNote.id,mistake:deletedMistake.id});
    const deletedZIP = await createZIP(restored,{notes:[deletedNote],mistakes:[deletedMistake],drawings:null});
    await importZIP(restored,deletedZIP);
    await navigate(restored,'notes');
    await restored.locator('.dcn-note-open').filter({hasText:deletedNote.title}).waitFor({state:'visible'});
    assert.equal(await restored.locator('.dcn-note-open').filter({hasText:deletedNote.title}).count(),1,
      'Restored deleted concepts become visible instead of remaining hidden by old tombstones');
    await navigate(restored,'mistakes');
    await restored.locator('.wrong-card').filter({hasText:deletedMistake.statement}).waitFor({state:'visible'});
    assert.equal(await restored.locator('.wrong-card').filter({hasText:deletedMistake.statement}).count(),1,
      'Restored deleted wrong questions become visible');
    console.log('PASS backup restoration makes previously deleted concepts and wrong questions visible');

    const bulkNotes = Array.from({length:131},(_,i) => ({id:'bulk-'+i,title:'批量概念 '+i,
      content:'超过单次128条加密写入上限的备份内容 '+i,updatedAt:savedAt}));
    const bulkZIP = await createZIP(restored,{notes:bulkNotes,mistakes:[],drawings:null});
    await restored.evaluate(() => {
      const original = __offlineTestStore.batch;
      let calls = 0;
      window.__restoreBackupBatch = () => {__offlineTestStore.batch=original;};
      __offlineTestStore.batch = async operations => {
        if (++calls===2) throw Object.assign(new Error('Injected storage quota'),{code:'QUOTA_EXCEEDED'});
        return original(operations);
      };
    });
    const beforeBulk = await records(restored,'notes');
    await importZIP(restored,bulkZIP);
    const partial = await records(restored,'notes');
    assert.ok(partial.filter(row=>row.id.startsWith('bulk-')).length<131,'A failed later batch is not reported as a complete restore');
    assert.match(await restored.locator('#offlineToast').innerText(),/未完成|失败|空间|incomplete|failed|storage/i);
    for (const row of beforeBulk) assert.deepEqual(partial.find(item=>item.id===row.id),row,'A failed import retains preexisting concepts');
    await restored.evaluate(() => window.__restoreBackupBatch());
    await importZIP(restored,bulkZIP);
    const complete = await records(restored,'notes');
    assert.equal(complete.filter(row=>row.id.startsWith('bulk-')).length,131,'Retry imports a large backup beyond one encrypted batch');
    assert.equal(complete.length,beforeBulk.length+131,'Retry does not duplicate an earlier committed batch');
    await importZIP(restored,bulkZIP);
    assert.equal((await records(restored,'notes')).length,complete.length,'Large repeated imports remain idempotent');
    console.log('PASS large imports cross encrypted batch limits, preserve existing data on failure and retry without duplicates');

    await restored.reload({waitUntil:'domcontentloaded'});await revealInterface(restored);
    assert.equal((await records(restored,'notes')).length,complete.length,'Imported concepts survive reopening');
    assert.equal((await records(restored,'mistakes')).length,3,'Imported wrong questions and answers survive reopening');
    assert.equal(JSON.parse((await records(restored,'drawings'))[0].gallery).pages.length,3,'Imported drawings survive reopening');
    assert.deepEqual(source.errors,[]);assert.deepEqual(target.errors,[]);
    assert.deepEqual(source.calls,[]);assert.deepEqual(target.calls,[]);
    console.log('PASS restored ZIP data persists in the encrypted workspace without backend or model calls');
  } finally {
    await source?.context.close();await target?.context.close();
    await browser.close();await rm(directory,{recursive:true,force:true});
  }
})().catch(error => {console.error(error);process.exitCode=1;});
