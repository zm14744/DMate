/* The offline book represents questions rather than save events. Exercise
 * actual cards, ZIP downloads and file selection against the encrypted store. */
'use strict';
const assert = require('node:assert/strict');
const {mkdtemp,readFile,rm} = require('node:fs/promises');
const {tmpdir} = require('node:os');
const {join} = require('node:path');
const {createHash} = require('node:crypto');
const {chromium} = require('playwright');
const {installStorageProbe,revealInterface,records} = require('./offline-vault-browser-fixtures.cjs');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const launch = {headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH
  ? {executablePath:process.env.CHROMIUM_EXECUTABLE_PATH} : {})};
const question = '求集合 A 与 B 的交集。';
const classification = points => ({version:1,question,
  question_sha256:createHash('sha256').update(question).digest('hex'),
  classification_source:'question_snapshot',classification_status:'fixed',focus_points:points,
  category:'集合',difficulty:'中等',catalog_revision:'offline-test-catalog-v1',related_categories:[],
  knowledge_points:points,related_knowledge_points:[],node_ids:[],focus_node_ids:[]});
const local = {id:'primary-local-question',title:'本地主分类',statement:question,
  answer:'PRIMARY ANSWER: 2 and 4',explanation:'PRIMARY ANALYSIS: compare the elements',
  knowledgePoints:['集合运算'],focusPoints:['集合运算'],
  question_classification:classification(['集合运算']),
  createdAt:'2001-01-01T00:00:00.000Z',updatedAt:'2002-01-01T00:00:00.000Z',
  custom:{keep:'original local metadata'}};
const duplicate = {...local,id:'older-duplicate-question',title:'另一分类',
  answer:'ALTERNATE ANSWER: {2,4}',explanation:'ALTERNATE ANALYSIS: inspect both sets',
  knowledgePoints:['关系性质'],focusPoints:['关系性质'],
  question_classification:classification(['关系性质']),
  createdAt:'2040-01-01T00:00:00.000Z',updatedAt:'2041-01-01T00:00:00.000Z',
  history:[{at:'2042-01-01T00:00:00.000Z',action:'retain the history details'}]};
const note = {id:'unrelated-concept',title:'保留概念',content:'导入错题不应改动此笔记。',updatedAt:123};

async function open(browser) {
  const context = await browser.newContext({viewport:{width:1440,height:1000},serviceWorkers:'block',acceptDownloads:true});
  await installStorageProbe(context);
  const calls = [], errors = [];
  await context.route(/\/(?:chat|ocr|graph\/|notebook\/analyze|analyze-questions|sync|classify)(?:\/|\?|$)/,
    route => {calls.push(route.request().url());return route.abort();});
  await context.route('**/auth/me',route => route.fulfill({contentType:'application/json',body:'{"configured":true,"authenticated":false}'}));
  const page = await context.newPage();
  page.on('pageerror',error => errors.push(error.message));
  await page.goto(baseURL+'/offline',{waitUntil:'domcontentloaded'});
  await revealInterface(page);
  return {context,page,calls,errors};
}
async function sidebar(page) {
  if (await page.locator('#offlineDesktopSidebarOpen').isVisible()) await page.locator('#offlineDesktopSidebarOpen').click();
}
async function book(page) {
  await sidebar(page);
  await page.locator('.offline-nav-item[data-panel="mistakes"]').click();
  await page.locator('#mistakesPanel').waitFor({state:'visible'});
}
async function idle(page) {
  await page.waitForFunction(() => {
    const control = document.getElementById('offlineImportDataBtn');
    return !control.disabled && control.getAttribute('aria-busy') !== 'true';
  });
}
async function createZIP(page,payload) {
  return Buffer.from(await page.evaluate(async payload => [...new Uint8Array(
    await (await DMateOfflineBackup.create(payload)).arrayBuffer())],payload));
}
async function legacyTimes(page,buffer) {
  return Buffer.from(await page.evaluate(async bytes => {
    const files = fflate.unzipSync(new Uint8Array(bytes));
    const rows = JSON.parse(fflate.strFromU8(files['mistakes.json']));
    for (const row of rows) {
      row.createdAt = '2099-01-01T00:00:00.000Z';
      row.updatedAt = '2099-02-01T00:00:00.000Z';
      row.answerUpdatedAt = '2099-03-01T00:00:00.000Z';
    }
    const content = files['mistakes.json'] = fflate.strToU8(JSON.stringify(rows));
    const manifest = JSON.parse(fflate.strFromU8(files['manifest.json']));
    manifest.files['mistakes.json'] = {size:content.length,sha256:[...new Uint8Array(
      await crypto.subtle.digest('SHA-256',content))].map(byte => byte.toString(16).padStart(2,'0')).join('')};
    files['manifest.json'] = fflate.strToU8(JSON.stringify(manifest));
    return [...fflate.zipSync(files)];
  },[...buffer]));
}
async function nestedZIP(page,buffer,foreign = false) {
  return Buffer.from(await page.evaluate(async ({bytes,foreign,question}) => {
    const files = fflate.unzipSync(new Uint8Array(bytes));
    const rows = JSON.parse(fflate.strFromU8(files['mistakes.json']));
    rows[0].mergedRecords = [{statement:question,answer:'HISTORICAL ANSWER',explanation:'HISTORICAL ANALYSIS',
      mergedRecords:[{statement:foreign ? '这是一道完全不同的题目。' : question,
        answer:'DEEPEST ANSWER',explanation:'DEEPEST ANALYSIS'}]}];
    const content = files['mistakes.json'] = fflate.strToU8(JSON.stringify(rows));
    const manifest = JSON.parse(fflate.strFromU8(files['manifest.json']));
    manifest.files['mistakes.json'] = {size:content.length,sha256:[...new Uint8Array(
      await crypto.subtle.digest('SHA-256',content))].map(byte => byte.toString(16).padStart(2,'0')).join('')};
    files['manifest.json'] = fflate.strToU8(JSON.stringify(manifest));
    return [...fflate.zipSync(files)];
  },{bytes:[...buffer],foreign,question}));
}
async function importZIP(page,buffer) {
  await sidebar(page);
  const selecting = page.waitForEvent('filechooser');
  await page.locator('#offlineImportDataBtn').click();
  await (await selecting).setFiles({name:'DMate-questions.zip',mimeType:'application/zip',buffer});
  await idle(page);
}
async function exportZIP(page,directory,name) {
  await sidebar(page);
  const downloading = page.waitForEvent('download');
  await page.locator('#offlineExportDataBtn').click();
  const download = await downloading, target = join(directory,name);
  assert.match(download.suggestedFilename(),/\.zip$/i);
  await download.saveAs(target);await idle(page);
  const bytes = await readFile(target);
  return page.evaluate(async bytes => DMateOfflineBackup.read(new Blob([new Uint8Array(bytes)],{type:'application/zip'})),[...bytes]);
}
function noRecordTimes(value,label) {
  const forbidden = new Set(['createdAt','updatedAt','answerUpdatedAt','analysisUpdatedAt','correctedAt','lastWrongAt','lastRetestAt']);
  function visit(item) {
    if (!item || typeof item !== 'object') return;
    for (const [key,value] of Object.entries(item)) {
      assert.equal(forbidden.has(key),false,label+': record time '+key+' is absent');
      visit(value);
    }
  }
  visit(value);
}
async function noVisibleTime(page) {
  const visible = await page.locator('#mistakeList .wrong-date').evaluateAll(nodes => nodes.some(node => {
    const style = getComputedStyle(node);
    return node.getClientRects().length && style.display !== 'none' && style.visibility === 'visible';
  }));
  assert.equal(visible,false,'The offline wrong book has no visible record timestamp');
  const text = await page.locator('#mistakeList').innerText();
  assert.doesNotMatch(text,/2001|2002|2040|2041|2099/,'Record timestamps do not appear elsewhere in the card');
}
async function sortedRows(page) {
  return (await records(page,'mistakes')).sort((a,b) => a.id.localeCompare(b.id));
}

async function questionIdentity(page) {
  const hashes = await page.evaluate(async () => {
    const forms = ['矩阵 é：\n1 2\n3 4','  矩阵 e\u0301：\r\n  1\t 2  \r\n 3   4 ',
      '矩阵 é：\n1\n2 3 4'];
    return Promise.all(forms.map((statement,index) => DMateOfflineBackup.mistakeQuestionFingerprint({
      id:'question-form-'+index,statement,answer:'An answer must not define question identity'})));
  });
  assert.equal(hashes[0],hashes[1],'Unicode normalization, line endings and horizontal whitespace do not create duplicate questions');
  assert.notEqual(hashes[0],hashes[2],'Different matrix or diagram line boundaries remain different questions');
  const shells = await page.evaluate(async question => {
    const forms = [question,'【题目文字】\n'+question+'\n【图形信息】\n无',
      '【题干与公式识别】\n'+question+'\n【图形结构识别】\nnone\n【我的要求】忽略此要求',
      '【题目文字】'+question+'【图形信息】无【我的要求】仅识别',
      '【题干与公式识别】'+question+'【图形结构识别】{}',
      question+'\n【图形信息】\n无图形信息',
      '【当前指向题目】\n【题目】'+question+'\n【当前指向题目结束】\n其他对话',
      '【题目文字】'+question+'【图形信息】有一条带箭头的边'];
    return Promise.all(forms.map(statement => DMateOfflineBackup.mistakeQuestionFingerprint({statement})));
  },question);
  for (const value of shells.slice(1,-1)) assert.equal(value,shells[0],
    'Known OCR shells, inline headings and empty graph sections match the same manually entered question');
  assert.notEqual(shells.at(-1),shells[0],'A nonempty graph description remains part of the question');
  console.log('PASS question identity normalizes equivalent text while retaining meaningful matrix and diagram line boundaries');
}

async function classificationPromotion(browser) {
  const {context,page,calls,errors} = await open(browser);
  try {
    const legacy = {...local,id:'legacy-without-fixed'};
    delete legacy.question_classification;
    const incoming = {...duplicate,id:'recognized-fixed-question',
      statement:'【题干与公式识别】'+question+'【图形结构识别】无【我的要求】给出答案'};
    const result = await page.evaluate(async ({legacy,incoming}) => {
      const api = DMateOfflineBackup;
      const merged = await api.mergeMistakes(legacy,incoming);
      const repeated = await api.mergeMistakes(merged,incoming);
      const existing = await api.mergeMistakes(incoming,{...incoming,
        question_classification:{...incoming.question_classification,focus_points:['不可替换已有难点']}});
      const rejected = [];
      for (const snapshot of [
        {...incoming.question_classification,question_sha256:'0'.repeat(64)},
        {...incoming.question_classification,question:'不同题干'},
        {...incoming.question_classification,related_knowledge_points:undefined},
        {...incoming.question_classification,node_ids:[],focus_node_ids:['missing-node']},
        {...incoming.question_classification,knowledge_points:['']}
      ]) {
        const row = {...incoming,question_classification:snapshot};
        const attempted = await api.mergeMistakes(legacy,row);
        rejected.push({snapshot:await api.mistakeClassification(row),promoted:!!attempted.question_classification});
      }
      let foreignError;
      try {await api.mergeMistakes(legacy,{...incoming,statement:'完全不同的题目'});}
      catch (error) {foreignError=error.code;}
      return {merged,repeatedJSON:JSON.stringify(repeated),mergedJSON:JSON.stringify(merged),existing,rejected,foreignError};
    },{legacy,incoming});
    assert.deepEqual(result.merged.question_classification,incoming.question_classification,
      'A real question-bound fixed snapshot is promoted from OCR output into a legacy question');
    for (const key of Object.keys(legacy)) assert.deepEqual(result.merged[key],legacy[key],
      'Promoting the fixed classification preserves the local '+key);
    assert.ok(result.merged.mergedRecords.some(row => row.answer === legacy.answer && !row.question_classification),
      'The pre-promotion primary record remains available in retained history');
    assert.equal(result.repeatedJSON,result.mergedJSON,'Repeating a fixed-snapshot merge is byte-equivalent');
    assert.deepEqual(result.existing.question_classification,incoming.question_classification,
      'An existing valid fixed classification cannot be replaced by another answer');
    assert.ok(result.rejected.every(value => value.snapshot === null && !value.promoted),
      'Wrong hashes, foreign snapshot questions and malformed schemas cannot promote a classification');
    assert.equal(result.foreignError,'BACKUP_INVALID','A different question cannot supply its fixed snapshot');

    await page.evaluate(async ({legacy,note}) => {
      await __offlineTestStore.put('mistakes',legacy);await __offlineTestStore.put('notes',note);
    },{legacy,note});
    const zip = await createZIP(page,{notes:[],mistakes:[incoming],drawings:null});
    await importZIP(page,zip);
    const rows = await sortedRows(page);
    assert.equal(rows.length,1,'OCR and manually entered versions import as one question');
    assert.equal(rows[0].id,legacy.id);assert.equal(rows[0].answer,legacy.answer);
    assert.deepEqual(rows[0].question_classification,incoming.question_classification);
    const firstJSON = JSON.stringify(rows);
    await importZIP(page,zip);
    assert.equal(JSON.stringify(await sortedRows(page)),firstJSON,'Repeated fixed-snapshot ZIP import is byte-equivalent');
    assert.deepEqual(await records(page,'notes'),[note]);
    assert.deepEqual(calls,[]);assert.deepEqual(errors,[]);
    console.log('PASS real-SHA fixed snapshots promote once across manual/OCR questions, retain primary answers, and reject invalid snapshots');
  } finally {await context.close();}
}

async function legacyDuplicates(browser,directory) {
  const {context,page,calls,errors} = await open(browser);
  try {
    await questionIdentity(page);
    await page.evaluate(async data => {
      for (const row of data.mistakes) await __offlineTestStore.put('mistakes',row);
      await __offlineTestStore.put('notes',data.note);
    },{mistakes:[local,duplicate],note});
    const originals = await sortedRows(page);
    await book(page);
    await page.waitForFunction(() => document.querySelectorAll('#mistakeList .wrong-card').length === 1);
    assert.equal(await page.locator('#mistakeCount').innerText(),'1 道错题');
    await noVisibleTime(page);
    assert.ok(await page.locator('#mistakeList .wrong-meta-row.focus').count() <= 1,
      'One question presents only its primary classification');
    await page.locator('#mistakeList .wrong-answer-details > summary').click();
    await page.waitForFunction(() => document.getElementById('mistakeList').textContent.includes('PRIMARY ANSWER')
      && document.getElementById('mistakeList').textContent.includes('ALTERNATE ANSWER'));
    const exported = await exportZIP(page,directory,'existing-duplicates.zip');
    assert.equal(exported.mistakes.length,1,'Export represents duplicate save records as one question');
    const details = JSON.stringify(exported.mistakes[0]);
    for (const text of ['PRIMARY ANSWER','ALTERNATE ANSWER','PRIMARY ANALYSIS','ALTERNATE ANALYSIS','original local metadata'])
      assert.ok(details.includes(text),'The merged export retains '+text);
    noRecordTimes(exported.mistakes,'Export');
    assert.doesNotMatch(details,/2042-01-01/,'Nested record-history timestamps are not exported');
    assert.deepEqual(await sortedRows(page),originals,'Rendering and export do not delete or rewrite old local records');
    assert.deepEqual(await records(page,'notes'),[note]);
    console.log('PASS old duplicate questions render and export once, retain all answers/analysis, and show no timestamps');

    await book(page);
    await page.locator('#mistakeList [data-action="delete-mistake"]').click();
    const confirmation = page.locator('.dmate-delete-confirm[open]');
    await confirmation.waitFor({state:'visible'});
    await confirmation.locator('.dmate-delete-confirm-delete').click();
    await page.waitForFunction(async () => (await __offlineTestStore.all('mistakes')).length === 0);
    assert.deepEqual(await records(page,'notes'),[note],'Removing the question leaves unrelated concepts intact');
    assert.deepEqual(calls,[]);assert.deepEqual(errors,[]);
    console.log('PASS explicitly removing the displayed question removes its old duplicate records together');
  } finally {await context.close();}
}

async function imports(browser,directory) {
  const {context,page,calls,errors} = await open(browser);
  try {
    await page.evaluate(async data => {
      await __offlineTestStore.put('mistakes',data.local);
      await __offlineTestStore.put('notes',data.note);
    },{local,note});
    const different = {...duplicate,id:'new-different-question',statement:'求集合 A 与 B 的并集。',
      answer:'UNION ANSWER: 1, 2, 3, 4',explanation:'UNION ANALYSIS: include all elements'};
    const incoming = {...duplicate,id:'incoming-same-question',statement:'\r\n'+question+'\r\n',
      answer:'IMPORTED ANSWER: the common elements',explanation:'IMPORTED ANALYSIS: another derivation'};
    const zip = await legacyTimes(page,await createZIP(page,{notes:[],mistakes:[incoming,different],drawings:null}));
    await importZIP(page,zip);
    const rows = await sortedRows(page);
    assert.equal(rows.length,2,'Same questions merge while a genuinely different question is appended');
    const primary = rows.find(row => row.id === local.id);
    assert.ok(primary,'The original local question ID is retained');
    for (const key of ['answer','explanation','title','knowledgePoints','focusPoints','question_classification','custom','createdAt','updatedAt'])
      assert.deepEqual(primary[key],local[key],'Import preserves the original local '+key);
    const content = JSON.stringify(primary);
    assert.ok(content.includes('IMPORTED ANSWER') && content.includes('IMPORTED ANALYSIS'),
      'The existing question retains newly imported answer and analysis information');
    assert.doesNotMatch(content,/2099-/,'Legacy incoming times are not copied into the local question');
    const added = rows.find(row => row.statement === different.statement);
    assert.ok(added,'The different question remains independently accessible');
    noRecordTimes(added,'Imported new question');
    assert.deepEqual(await records(page,'notes'),[note]);
    await book(page);await page.waitForFunction(() => document.querySelectorAll('#mistakeList .wrong-card').length === 2);
    await noVisibleTime(page);
    await importZIP(page,zip);
    assert.deepEqual(await sortedRows(page),rows,'Repeating the ZIP import adds no duplicate variants or questions');
    await page.reload({waitUntil:'domcontentloaded'});await revealInterface(page);await book(page);
    await page.waitForFunction(() => document.querySelectorAll('#mistakeList .wrong-card').length === 2);
    assert.deepEqual(await sortedRows(page),rows,'The merged question survives a real reload without changing again');
    const exported = await exportZIP(page,directory,'imported-questions.zip');
    assert.equal(exported.mistakes.length,2);noRecordTimes(exported.mistakes,'Round-trip export');
    assert.ok(JSON.stringify(exported.mistakes).includes('IMPORTED ANALYSIS'));
    assert.deepEqual(calls,[]);assert.deepEqual(errors,[]);
    console.log('PASS differing answers/classifications/times merge into the local question, new questions append, and repeats stay idempotent');
  } finally {await context.close();}
}

async function nestedHistory(browser,directory) {
  const {context,page,calls,errors} = await open(browser);
  try {
    await page.evaluate(row => __offlineTestStore.put('mistakes',row),local);
    const base = await createZIP(page,{notes:[],mistakes:[{...duplicate,id:'nested-incoming',
      answer:'ROOT IMPORTED ANSWER',explanation:'ROOT IMPORTED ANALYSIS'}],drawings:null});
    const valid = await nestedZIP(page,base);
    await importZIP(page,valid);
    const before = await sortedRows(page);
    assert.equal(before.length,1);
    for (const text of ['PRIMARY ANSWER','ROOT IMPORTED ANSWER','HISTORICAL ANSWER','DEEPEST ANSWER',
      'ROOT IMPORTED ANALYSIS','HISTORICAL ANALYSIS','DEEPEST ANALYSIS'])
      assert.ok(JSON.stringify(before).includes(text),'Nested history retains '+text);
    assert.ok(before[0].mergedRecords.every(row => !row.mergedRecords),'Nested history is flattened without dropping its records');
    await importZIP(page,valid);
    assert.deepEqual(await sortedRows(page),before,'Repeating nested-history imports never grows duplicate variants');
    const exported = await exportZIP(page,directory,'nested-history.zip');
    assert.ok(JSON.stringify(exported.mistakes).includes('DEEPEST ANALYSIS'));
    noRecordTimes(exported.mistakes,'Nested export');
    const invalid = await nestedZIP(page,base,true);
    const readError = await page.evaluate(async bytes => {
      try {await DMateOfflineBackup.read(new Blob([new Uint8Array(bytes)]));return null;}
      catch (error) {return error.code;}
    },[...invalid]);
    assert.equal(readError,'BACKUP_INVALID','A foreign question hidden in nested history is rejected');
    await importZIP(page,invalid);
    assert.deepEqual(await sortedRows(page),before,'Rejecting a foreign nested question writes no local record');
    const createError = await page.evaluate(async row => {
      try {await DMateOfflineBackup.create({notes:[],drawings:null,mistakes:[{...row,
        mergedRecords:[{statement:'另一道不相干的题目。',answer:'Do not lose this foreign answer'}]}]});return null;}
      catch (error) {return error.code;}
    },local);
    assert.equal(createError,'BACKUP_INVALID','Export rejects mixed-question history instead of silently dropping it');
    assert.deepEqual(calls,[]);assert.deepEqual(errors,[]);
    console.log('PASS deep same-question history is retained and idempotent while foreign nested questions are rejected without writes');
  } finally {await context.close();}
}

async function concurrentImport(browser) {
  const {context,page,calls,errors} = await open(browser);
  try {
    await page.evaluate(row => __offlineTestStore.put('mistakes',row),local);
    const zip = await createZIP(page,{notes:[],drawings:null,mistakes:[{...duplicate,id:'concurrent-import',
      answer:'IMPORT ANSWER C',explanation:'IMPORT ANALYSIS C'}]});
    await page.evaluate(id => {
      const original = window.__originalBackup = DMateOfflineBackup;
      let held = false;
      window.DMateOfflineBackup = {...original,async contentFingerprint(kind,row) {
        const value = await original.contentFingerprint(kind,row);
        if (!held && kind === 'mistakes' && row.id === id) {
          held = true;
          await new Promise(resolve => {window.__releaseImportHash = resolve;});
        }
        return value;
      }};
    },local.id);
    await sidebar(page);
    const selecting = page.waitForEvent('filechooser');
    await page.locator('#offlineImportDataBtn').click();
    await (await selecting).setFiles({name:'DMate-concurrent.zip',mimeType:'application/zip',buffer:zip});
    await page.waitForFunction(() => typeof window.__releaseImportHash === 'function');
    await page.evaluate(async ({id,question}) => {
      const main = __offlineTestStore;
      const other = await DMateOfflineStorage.open({scope:'device',isCurrent:()=>true});
      const original = await other.get('mistakes',id);
      const merged = await __originalBackup.mergeMistakes(original,{id:'other-editor',statement:question,
        answer:'CONCURRENT ANSWER B',explanation:'CONCURRENT ANALYSIS B'});
      await other.put('mistakes',merged);other.close();
      // A newer UI read must not update the already planned import's token.
      window.__offlineTestStore = main;
      await main.all('mistakes');
      __releaseImportHash();
    },{id:local.id,question});
    await idle(page);
    const preserved = await sortedRows(page);
    assert.equal(preserved.length,1);
    assert.ok(JSON.stringify(preserved).includes('CONCURRENT ANSWER B'),'The other editor\'s committed answer survives the stale import');
    assert.equal(JSON.stringify(preserved).includes('IMPORT ANSWER C'),false,'A stale plan cannot silently replace the newer merge');
    assert.match(await page.locator('#offlineToast').innerText(),/另一页面|冲突|changed|conflict/i);
    await importZIP(page,zip);
    const retried = await sortedRows(page);
    assert.equal(retried.length,1);
    for (const text of ['PRIMARY ANSWER','CONCURRENT ANSWER B','IMPORT ANSWER C'])
      assert.ok(JSON.stringify(retried).includes(text),'Retry retains '+text);
    assert.deepEqual(calls,[]);assert.deepEqual(errors,[]);
    console.log('PASS a stale import cannot lose a concurrently merged answer even after its handle rereads; retry retains all answers');
  } finally {await context.close();}
}

(async () => {
  const directory = await mkdtemp(join(tmpdir(),'dmate-mistake-merge-'));
  const browser = await chromium.launch(launch);
  try {await legacyDuplicates(browser,directory);await classificationPromotion(browser);await imports(browser,directory);
    await nestedHistory(browser,directory);await concurrentImport(browser);}
  finally {await browser.close();await rm(directory,{recursive:true,force:true});}
})().catch(error => {console.error(error);process.exitCode=1;});
