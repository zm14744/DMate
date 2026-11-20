/* The existing online export button produces the portable study ZIP consumed
 * by offline mode, using the current verified page rather than another owner. */
'use strict';
const assert = require('node:assert/strict');
const {readFile} = require('node:fs/promises');
const {execFileSync} = require('node:child_process');
const {chromium} = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const launch = {headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH
  ? {executablePath:process.env.CHROMIUM_EXECUTABLE_PATH} : {})};
const note = {id:'online-note',title:'等价关系',content:'自反、对称与传递。',updatedAt:1000,custom:{keep:'note metadata'}};
const wrong = {id:'online-mistake',category:'关系',question:'证明 $R$ 是等价关系。',
  referenceAnswer:{text:'依次验证自反、对称与传递。',rubric:['自反','对称','传递']},
  analysis:'分别使用三个定义。',recognitionSnapshot:{version:1,question:'原始题目',points:['等价关系']},
  focusPoints:['传递性'],corrected:false,createdAt:100,updatedAt:200};
const gallery = {version:2,activeId:'online-drawing',custom:{keep:'editable gallery'},pages:[{
  id:'online-drawing',name:'关系图',updatedAt:500,requirement:'保留边与权值',document:{body_text:'关系的有向图',graphs:[{
    id:'G1',name:'关系图',directed:true,weighted:true,
    vertices:[{id:'a',label:'甲',x:100,y:100},{id:'b',label:'乙',x:400,y:250}],
    edges:[{id:'e1',from:'a',to:'b',weight:'3'}]
  }]}
}]};

async function run(browser,width) {
  const context = await browser.newContext({viewport:{width,height:900},serviceWorkers:'block',acceptDownloads:true});
  const errors = [],modelCalls = [];
  await context.route('**/auth/me',route => route.fulfill({contentType:'application/json',body:JSON.stringify({
    configured:true,authenticated:false})}));
  await context.route(/\/(?:chat|ocr|notebook\/analyze|analyze-questions|classify)(?:\/|\?|$)/,route => {
    modelCalls.push(route.request().url()); return route.abort();
  });
  const page = await context.newPage();
  page.on('pageerror',error => errors.push(error.message));
  try {
    await page.goto(baseURL+'/',{waitUntil:'networkidle'});
    await page.waitForFunction(() => window.DMateOfflineBridge && window.DMateOfflineBackup
      && window.DMateBackupDownload && accountState.configured !== null && !accountVerificationOperation);
    await page.evaluate(({note,wrong,gallery}) => {
      const originalToast = window.showCopyToast;
      window.__backupToasts = [];
      window.showCopyToast = message => { window.__backupToasts.push(message); originalToast(message); };
      learningState = {...createEmptyLearningState(),wrongQuestions:[wrong,{...wrong,id:'deleted-wrong'}],
        deletedWrongQuestionIds:{'deleted-wrong':300},
        conceptNotebook:{notes:[note,{...note,id:'deleted-note'}],deleted:{'deleted-note':2000}}};
      standaloneDrawingOwner = drawingStorageOwner();
      standaloneDrawingSessionState = {gallery:JSON.stringify(gallery)};
      standaloneDrawing = null;
      appearanceSettings = {...appearanceSettings,accent:'appearance-must-not-be-in-backup'};
    },{note,wrong,gallery});
    if (width <= 1100) await page.locator('#mobileNavBtn').click();
    else if (await page.locator('#desktopSidebarOpen').isVisible()) await page.locator('#desktopSidebarOpen').click();
    const button = page.locator('#exportDataBtn');
    const [download] = await Promise.all([page.waitForEvent('download'),button.click()]);
    assert.match(download.suggestedFilename(),/^DMate-.*\.zip$/i);
    const path = await download.path(), bytes = await readFile(path);
    assert.equal(bytes.readUInt16LE(0),0x4b50,'The download is a real ZIP archive');
    const standard = JSON.parse(execFileSync('python',['-c',
      'import json,sys,zipfile\nwith zipfile.ZipFile(sys.argv[1]) as z:\n assert z.testzip() is None\n print(json.dumps({"files":z.namelist(),"notes":json.loads(z.read("notes.json")),"mistakes":json.loads(z.read("mistakes.json")),"drawings":json.loads(z.read("drawings.json"))},ensure_ascii=False))',path],{encoding:'utf8'}));
    assert.deepEqual(standard.files.sort(),['drawings.json','manifest.json','mistakes.json','notes.json']);
    assert.deepEqual(standard.notes,[note],'Concept notes keep their complete metadata and deleted notes stay excluded');
    assert.equal(standard.mistakes.length,1,'Only the live mistake is exported');
    const exported = standard.mistakes[0];
    assert.equal(exported.statement,wrong.question);
    assert.equal(exported.answer,wrong.referenceAnswer.text);
    assert.equal(exported.explanation,wrong.analysis);
    assert.equal(Object.hasOwn(exported,'createdAt'),false,'Online ZIPs omit wrong-question creation times');
    assert.equal(Object.hasOwn(exported,'updatedAt'),false,'Online ZIPs omit wrong-question update times');
    assert.deepEqual(exported.referenceAnswer,wrong.referenceAnswer);
    assert.deepEqual(exported.recognitionSnapshot,wrong.recognitionSnapshot);
    assert.deepEqual(standard.drawings,gallery,'The complete editable gallery is included');
    assert.doesNotMatch(bytes.toString('utf8'),/appearance-must-not-be-in-backup/);
    const restored = await page.evaluate(async bytes => DMateOfflineBackup.read(new Uint8Array(bytes)),[...bytes]);
    assert.deepEqual(restored.notes,[note]);
    assert.equal(restored.mistakes[0].answer,wrong.referenceAnswer.text);
    assert.equal(Object.hasOwn(restored.mistakes[0],'createdAt'),false);
    assert.equal(Object.hasOwn(restored.mistakes[0],'updatedAt'),false);
    assert.deepEqual(await page.evaluate(() => ({createdAt:learningState.wrongQuestions[0].createdAt,
      updatedAt:learningState.wrongQuestions[0].updatedAt})),{createdAt:wrong.createdAt,updatedAt:wrong.updatedAt},
      'Time-free exports retain the source learning record unchanged');
    assert.deepEqual(restored.drawings,gallery,'The ZIP is readable by offline mode without conversion');
    await page.waitForFunction(() => !document.getElementById('exportDataBtn').disabled);
    console.log('PASS online '+width+': real study ZIP includes notes, full answers and editable drawings without unrelated records');

    let unexpectedDownloads = 0;
    page.on('download',() => unexpectedDownloads++);
    await page.evaluate(() => {
      const original = DMateOfflineBackup;
      window.DMateOfflineBackup = {...original,async create(value) {
        const blob = await original.create(value);
        bumpCloudSyncContext();
        return blob;
      }};
    });
    await button.click();
    await page.waitForFunction(() => !document.getElementById('exportDataBtn').disabled);
    await page.locator('.copy-toast').filter({hasText:'账号状态已变化'}).waitFor();
    assert.equal(unexpectedDownloads,0,'An account/context change cancels export before any file is downloaded');
    assert.equal(await button.getAttribute('aria-busy'),null,'Cancelled export restores the button');
    assert.deepEqual(errors,[]);
    assert.deepEqual(modelCalls,[]);
    console.log('PASS online '+width+': account changes cancel export and leave the button usable');
  } catch (error) {
    console.error('Online backup page context',await page.evaluate(() => ({
      toasts:window.__backupToasts,button:{disabled:document.getElementById('exportDataBtn')?.disabled,
        busy:document.getElementById('exportDataBtn')?.getAttribute('aria-busy')},
      modals:[...document.querySelectorAll('dialog[open]')].map(node => node.id),
      helper:typeof window.DMateBackupDownload?.save,codec:typeof window.DMateOfflineBackup?.create
    })).catch(() => null),errors);
    throw error;
  } finally {await context.close();}
}

(async () => {
  const browser = await chromium.launch(launch);
  try {for (const width of [1440,390]) await run(browser,width);}
  finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
