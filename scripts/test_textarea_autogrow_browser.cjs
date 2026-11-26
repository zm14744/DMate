/* Real editor fields grow with their contents; requests for model output are
 * blocked. Chat and inline-message editors retain their own keyboard handling.
 */
'use strict';
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const {revealInterface} = require('./offline-vault-browser-fixtures.cjs');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const longText = Array.from({length:30}, (_,i) => `第${i+1}行：自动增高的输入内容`).join('\n');
const longTitle = Array.from({length:24}, (_,i) => `标题${i+1}`).join('\n');
const settle = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
const metrics = input => input.evaluate(node => {
  const css = getComputedStyle(node);
  return {height:node.getBoundingClientRect().height,client:node.clientHeight,scroll:node.scrollHeight,
    resize:css.resize,overflow:css.overflowY,max:parseFloat(css.maxHeight),value:node.value};
});
async function grows(page, input, label, content = longText) {
  await input.waitFor({state:'visible'});
  await input.fill('短内容'); await settle(page);
  const short = await metrics(input);
  assert.equal(short.resize,'none',label+': manual resize is removed');
  await input.fill(content); await settle(page);
  const long = await metrics(input);
  assert.ok(long.height>short.height+8,label+': more lines increase the visible height '+JSON.stringify({short,long}));
  assert.ok(long.height<=long.max+2,label+': height stays within its limit');
  assert.equal(long.overflow,'auto',label+': longer content scrolls inside the capped field');
  assert.ok(long.scroll>long.client+10,label+': fixture really exceeds the visible cap');
  await input.evaluate(node => node.setSelectionRange(3,12));
  await page.evaluate(() => dispatchEvent(new Event('resize'))); await settle(page);
  assert.deepEqual(await input.evaluate(node => [node.selectionStart,node.selectionEnd]),[3,12],label+': measuring preserves the selection');
  assert.equal(await input.inputValue(),content,label+': resizing preserves the complete text');
  await input.fill('短内容'); await settle(page);
  assert.ok(Math.abs((await metrics(input)).height-short.height)<=2,label+': deleting text shrinks the field again');
}
async function graphTextFields(page, offline) {
  await page.evaluate(offline => {
    const host=offline?document.createElement('div'):document.getElementById('graphEditorMount');
    const dialog=offline?document.createElement('dialog'):document.getElementById('graphEditorDialog');
    if(offline){dialog.className='graph-editor-dialog';dialog.style.cssText='width:90vw;height:85vh';dialog.append(host);document.body.append(dialog);}
    window.__autogrowGraphDialog=dialog;
    window.__autogrowGraph=DMateGraphEditor.mount(host,{document:{body_text:'预先回填的文字',graphs:[]},
      originalUrl:'data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500"/>'),
      onConfirm:async()=>{}});
    if(offline)dialog.showModal();else showGraphEditorDialog(dialog);
  },offline);
  await page.locator('.dge-tabs [role="tab"]').nth(1).click();
  await page.locator('.dge-text-results > summary').click();
  await grows(page,page.locator('.dge-text-body'),'graph recognized text');
  await grows(page,page.locator('.dge-text-requirements'),'graph supplementary request');
  await page.evaluate(()=>{__autogrowGraph.destroy();__autogrowGraphDialog.close();});
}
async function reinsertedField(page,width) {
  await page.evaluate(value=>{
    const field=document.createElement('textarea');field.id='reinserted-field';
    field.style.cssText='display:block;width:250px;min-height:40px;max-height:none;font:16px/24px sans-serif';
    field.value=value;document.body.append(field);window.__reinsertedField=field;
  },longText);
  const field=page.locator('#reinserted-field');await settle(page);
  const initial=await metrics(field);assert.equal(initial.max,360);
  await field.evaluate(node=>node.remove());await settle(page);
  await page.setViewportSize({width,height:500});
  await page.evaluate(()=>document.body.append(__reinsertedField));await settle(page);
  assert.equal((await metrics(field)).max,225,'A retained field follows the shorter viewport after remount');
  await field.evaluate(node=>node.remove());await settle(page);
  await page.setViewportSize({width,height:900});
  await page.evaluate(()=>document.body.append(__reinsertedField));await settle(page);
  assert.equal((await metrics(field)).max,360,'A previous dynamic cap does not become the retained field\'s permanent CSS maximum');
  await field.evaluate(node=>node.remove());
}
async function online(page,width) {
  await page.goto(baseURL,{waitUntil:'networkidle'});
  await page.waitForFunction(()=>!accountVerificationOperation&&Boolean(window.DMateTextareaAutosize));
  await page.evaluate(long => {
    learningState=normalizeLearningState({wrongQuestions:[{id:'autogrow-wrong',question:long,focusPoints:['集合运算'],
      knowledgePoints:['集合运算'],difficulty:'简单',note:long,referenceAnswer:'本地答案',analysis:'本地解析',createdAt:1,updatedAt:2}]});
    openWrongEdit('autogrow-wrong');
  },longText);
  const question=page.locator('#wrongEditQuestion'),note=page.locator('#wrongEditNote');
  await settle(page);
  assert.equal((await metrics(question)).overflow,'auto','Opening a hidden editor sizes its programmatically prefilled question');
  await grows(page,question,'wrong-book question'); await grows(page,note,'wrong-book note');
  await note.fill(longText);await page.evaluate(()=>closeWrongEdit());
  await page.evaluate(long=>{learningState.wrongQuestions[0].note=long;openWrongEdit('autogrow-wrong');},longText);await settle(page);
  assert.equal((await metrics(note)).overflow,'auto','A retained textarea resizes after hidden programmatic refill');
  await page.evaluate(()=>closeWrongEdit());
  await page.evaluate(()=>{
    learningState.conceptNotebook={notes:[
      {id:'auto-note',title:'自动增高',content:'已有内容',updatedAt:1},
      {id:'auto-note-2',title:'换行',content:'新增一行',updatedAt:2}
    ],deleted:{}};
    initializeConceptNotebook();dmateConceptNotebook.open();
  });
  await grows(page,page.locator('.dcn-title'),'notebook concept name',longTitle);
  await grows(page,page.locator('.dcn-original'),'notebook original content');
  const original=page.locator('.dcn-original');
  const wrapped='多行输入会跟随当前宽度自动重新换行并保持所有原始文字'.repeat(12);
  await original.fill(wrapped);await settle(page);
  const before=await metrics(original);
  await page.setViewportSize({width:width===390?430:1240,height:900});await settle(page);
  assert.equal(await original.inputValue(),wrapped,'Responsive remeasurement retains content');
  await page.evaluate(()=>document.documentElement.style.setProperty('--font-scale','1.2'));await settle(page);
  const after=await metrics(original);assert.equal(after.resize,'none');assert.ok(after.height<=after.max+2);
  assert.ok(before.height>0&&after.height>0,'Width/font changes preserve a measured editable field');
  await page.evaluate(()=>document.documentElement.style.removeProperty('--font-scale'));
  const notebook=page.locator('#conceptNotebookDialog');
  for(const checkbox of await notebook.getByRole('checkbox').all()) await checkbox.check();
  await notebook.locator('.dcn-relation-trigger').click();
  await grows(page,notebook.getByRole('dialog',{name:'分析关联'}).getByRole('textbox',{name:'分析要求（可选）'}),'notebook analysis request');
  await page.evaluate(()=>dmateConceptNotebook.close());
  await page.setViewportSize({width,height:900});
  await page.evaluate(()=>{
    const svg='<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500"/>';
    const file=new File([svg],'autogrow.svg',{type:'image/svg+xml'}),draft={body_text:'本地题目',graphs:[]};
    ocrTasks.clear();ocrTasks.set('autogrow-scan',{id:'autogrow-scan',groupId:'1',file,sessionId:currentId,
      state:'ready',originalUrl:URL.createObjectURL(file),draft,initialDocument:structuredClone(draft),startedAt:performance.now(),finishedAt:performance.now()});
    renderOcrTasks();editOcrTask('autogrow-scan');
  });
  const scanRequest=page.locator('.dgs-requirements');
  await grows(page,scanRequest,'scan request');
  const wrappedRequest='宽度变化应自动重新测量输入内容。'.repeat(8);
  await scanRequest.fill(wrappedRequest);await settle(page);
  const wide=await metrics(scanRequest);
  await scanRequest.evaluate(node=>node.style.width='140px');await settle(page);
  assert.ok((await metrics(scanRequest)).height>wide.height+8,'A field actually grows after its available width narrows');
  await scanRequest.evaluate(node=>node.style.removeProperty('width'));await settle(page);
  assert.ok(Math.abs((await metrics(scanRequest)).height-wide.height)<=2,'Restoring width shrinks wrapped content again');
  await scanRequest.fill('');await settle(page);const normalFont=await metrics(scanRequest);
  await scanRequest.evaluate(node=>node.parentElement.style.setProperty('--font-base','64px'));await settle(page);
  assert.ok((await metrics(scanRequest)).height>normalFont.height+8,'A shared input font change remeasures the minimum visible line');
  await scanRequest.evaluate(node=>node.parentElement.style.removeProperty('--font-base'));await settle(page);
  await page.locator('.dgs-requirements').fill('第一行');await page.locator('.dgs-requirements').press('End');await page.locator('.dgs-requirements').press('Enter');
  assert.equal(await page.locator('.dgs-requirements').inputValue(),'第一行\n','Supplementary request Enter remains a native newline');
  await page.locator('#graphEditorClose').click();
  await page.waitForFunction(()=>ocrEditorTaskId===null&&ocrEditorController===null);
  await page.evaluate(()=>openGraphDrawing());
  await page.locator('[data-drawing-ai-generation]').click();
  await grows(page,page.locator('.ddw-ai-requirement'),'drawing AI request');
  await page.locator('#graphEditorClose').click();
  await page.waitForFunction(()=>ocrEditorTaskId===null&&ocrEditorController===null);
  await graphTextFields(page,false);
  await page.evaluate(()=>{
    const host=document.createElement('section');host.id='autogrow-message-edit';document.body.append(host);window.__autoEdits=[];
    window.__autoMessageEditor=DMateChatMessageEdit.mount({host,value:'编辑内容',onSubmit:value=>__autoEdits.push(value)});
  });
  const edit=page.locator('.chat-message-edit-input');await edit.fill('保留编辑键盘行为');await edit.press('Shift+Enter');await edit.press('x');
  assert.equal(await edit.inputValue(),'保留编辑键盘行为\nx');await edit.press('Enter');
  assert.deepEqual(await page.evaluate(()=>__autoEdits),['保留编辑键盘行为\nx']);
  assert.equal(await edit.evaluate(node=>node.classList.contains('dmate-textarea-autosize')),false,'Inline message editing keeps its own size controller');
  assert.equal(await page.locator('#text').evaluate(node=>node.classList.contains('dmate-textarea-autosize')),false,'Main composer keeps its own size controller');
  await page.evaluate(()=>{__autoMessageEditor.destroy();document.getElementById('autogrow-message-edit').remove();});
  await reinsertedField(page,width);
}
async function runCase(browser,width) {
  const context=await browser.newContext({viewport:{width,height:900},serviceWorkers:'block'}),page=await context.newPage(),errors=[],requests=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/auth/me',route=>route.fulfill({contentType:'application/json',body:'{"configured":true,"authenticated":false}'}));
  await page.route(/\/(?:chat|ocr(?:\/[^?]*)?|graph\/[^?]*|analyze-questions|classify|conversation\/title|notebook\/analyze)(?:\?|$)/,
    route=>{requests.push(new URL(route.request().url()).pathname);return route.abort();});
  try{
    await online(page,width);
    await page.goto(new URL('/offline',baseURL).href,{waitUntil:'networkidle'});
    await page.waitForFunction(()=>document.documentElement.dataset.offlineReady==='true'&&Boolean(window.DMateTextareaAutosize));
    await revealInterface(page);
    if(width<=1100)await page.locator('#offlineNavToggle').click();
    await page.locator('.offline-nav-item[data-panel="notes"]').click();
    await page.locator('#addNote').click();
    await grows(page,page.locator('.dcn-title'),'offline notebook concept name',longTitle);
    await grows(page,page.locator('.dcn-original'),'offline notebook concept content');
    await graphTextFields(page,true);
    assert.deepEqual(requests,[],'Resizing and editing fields never generates model output');assert.deepEqual(errors,[]);
    console.log('PASS '+width+': real online/offline fields grow, cap, shrink, refill and retain values/selection/keyboard behavior');
  }finally{await context.close();}
}
(async()=>{const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.CHROMIUM_EXECUTABLE_PATH}:{})});
  try{for(const width of [390,1440])await runCase(browser,width);}finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
