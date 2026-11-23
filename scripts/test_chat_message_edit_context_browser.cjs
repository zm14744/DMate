/* Start Flask first. All model, OCR and account routes use local fixtures. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const marker = '\n\n【我的要求】\n';

function context(question, id = 'confirmed-image-one') {
  return { document:{ body_text:question, graphs:[{
    id:'graph-' + id, name:'已确认图', complete:true, directed:false, weighted:false,
    multigraph:false, vertices:[{id:'v-a',label:'A'},{id:'v-b',label:'B'}],
    edges:[{id:'edge-a-b',from:'v-a',to:'v-b',direction:'undirected',status:'accepted'}]
  }] }, question_text:question + '\n[canonical graph ' + id + ']',
  rendered_question_text:'【题目文字】\n' + question, source_sha256:'a'.repeat(64),
  confirmation_token:'fixture-confirmation-' + id, document_sha256:'b'.repeat(64),
  revision:1, request_id:id, profile:'editable-v1' };
}

(async () => {
  const browser = await chromium.launch({headless:true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? {executablePath:process.env.CHROMIUM_EXECUTABLE_PATH} : {})});
  try {
    const browserContext = await browser.newContext({viewport:{width:1440,height:1000},serviceWorkers:'block'});
    const page = await browserContext.newPage(), requests = [], imageRequests = [], errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const json = value => ({contentType:'application/json',body:JSON.stringify(value)});
    await page.route('**/auth/me', route => route.fulfill(json({configured:true,authenticated:false})));
    await page.route('**/analyze-questions', route => route.fulfill(json({entries:[]})));
    await page.route('**/conversation/title', route => route.fulfill(json({})));
    await page.route(/\/(?:ocr(?:\/|$)|graph\/)/, route => {
      imageRequests.push(route.request().url()); return route.abort();
    });
    await page.route('**/chat', route => { requests.push({route,payload:route.request().postDataJSON()}); });
    await page.goto(baseURL,{waitUntil:'networkidle'});
    await page.waitForFunction(() => !accountVerificationOperation);
    const seed = (messages,retest = null) => page.evaluate(({messages,retest}) => {
      stopCurrentAiReply(); newChat(); const session = getCurrent();
      session.name = '手动标题'; session.nameSource = 'user'; session.messages = messages;
      session.retest = retest; ensureSessionMessageIds(session); renderChat(); renderSessions();
    },{messages,retest});
    const sendEdit = async (index,text) => {
      const count = requests.length + 1;
      await page.locator(`.msg[data-message-index="${index}"]`).hover();
      await page.locator(`.msg[data-message-index="${index}"] .chat-message-edit-button`).click();
      await page.locator('.chat-message-edit-input').fill(text);
      await page.locator('.chat-message-edit-input').press('Enter');
      await assert.doesNotReject(async () => {
        for (let n = 0; n < 200 && requests.length < count; n++) await page.waitForTimeout(20);
        assert.equal(requests.length,count,'one chat request is made for the edited message');
      });
      return requests[count - 1].payload;
    };
    const message = () => page.evaluate(() => JSON.parse(JSON.stringify(getLatestUserMessage(getCurrent()))));

    // An unchanged confirmed question may reuse its exact signed graph snapshot.
    const signed = context('求图中顶点 A 的度数');
    const original = {role:'user',source:'ocr',ocrIsQuestion:true,
      text:signed.rendered_question_text + marker + '旧要求',
      apiText:signed.question_text + '\n旧要求',semanticContext:signed};
    await seed([original]);
    assert.equal(await page.evaluate(() => Boolean(sanitizeSemanticContext(
      getCurrent().messages[0].semanticContext,getCurrent().messages[0]))),true,'fixture passes the actual client schema');
    let payload = await sendEdit(0,signed.rendered_question_text + marker + '先说明每条边如何计数');
    let edited = await message();
    assert.equal(edited.source,'ocr'); assert.equal(edited.ocrIsQuestion,true);
    assert.deepEqual(payload.semantic_context,edited.semanticContext);
    assert.equal(payload.semantic_context.confirmation_token,signed.confirmation_token);
    assert.equal(payload.semantic_context.document.graphs[0].edges[0].status,'accepted');
    assert.ok(payload.messages.at(-1).content.endsWith(edited.apiText));
    assert.ok(edited.apiText.includes(signed.question_text));
    assert.ok(edited.apiText.includes('先说明每条边如何计数')); assert.ok(!edited.apiText.includes('旧要求'));
    console.log('PASS requirement-only edit preserves the confirmed graph, token and canonical question');

    // Altering the visible question must never keep the old signature or hidden canonical question.
    await seed([original]);
    payload = await sendEdit(0,'改为求图中顶点 B 的度数' + marker + '使用新的条件');
    edited = await message();
    for (const key of ['source','semanticContext','semanticContexts','ocrGroup','apiText'])
      assert.equal(edited[key],undefined,'changed question drops ' + key);
    assert.equal(edited.manualIsQuestion,true);
    assert.equal(edited.text,'改为求图中顶点 B 的度数\n\n使用新的条件');
    assert.equal(payload.semantic_context,undefined); assert.equal(payload.semantic_contexts,undefined);
    assert.ok(payload.messages.at(-1).content.includes(edited.text));
    assert.ok(!JSON.stringify(payload).includes(signed.confirmation_token));
    assert.ok(!JSON.stringify(payload).includes('[canonical graph'));
    console.log('PASS changed OCR question becomes fresh text without stale graph signatures or hidden context');

    // Group identity, order and question/supporting flags survive an edit to requirements only.
    const grouped = [context('第一张图的问题','image-one'),context('第二张图的补充材料','image-two')];
    const rendered = grouped.map((value,index) => `【图片 ${index + 1}】\n${value.rendered_question_text}`).join('\n\n');
    const canonical = grouped.map((value,index) => `【图片 ${index + 1}】\n${value.question_text}`).join('\n\n');
    const ocrGroup = {id:'confirmed-group',groupId:'group-one',members:[
      {requestId:'image-one',isQuestion:true},{requestId:'image-two',isQuestion:false}]};
    const assembled = await page.evaluate(contexts => {
      const tasks = contexts.map((context,index) => ({id:context.request_id,groupId:'group-one',
        sourceSha256:context.source_sha256,confirmation:{semantic_context:context},isQuestion:index===0,
        userRequest:index===0?'  用图2的条件解释图1。\n保留原图图号。  ':'核对两张图之间的差异。'}));
      const foreign = {...tasks[0],id:'foreign-image',groupId:'other-group',userRequest:'OTHER_GROUP_ONLY'};
      const original = tasks.map(task=>task.userRequest);
      const group = partitionOcrTasks([tasks[0],foreign,tasks[1]])[0];
      const message = buildOcrGroupMessage(group,'请逐条回应全部要求。');
      return {message,original,after:tasks.map(task=>task.userRequest),
        single:ocrGroupRequestForApi('只分析这张图。',1)};
    },grouped);
    assert.deepEqual(assembled.after,assembled.original,'Sharing scope never overwrites individual image drafts');
    assert.equal(assembled.single,'只分析这张图。','Single-image request semantics stay unchanged');
    for(const raw of assembled.original) assert.ok(assembled.message.apiText.includes(raw),'Keep each requirement verbatim');
    assert.ok(assembled.message.apiText.includes('要求适用于本组全部图片'));
    assert.ok(assembled.message.apiText.includes('引用组内其他图片'));
    assert.ok(assembled.message.apiText.includes('图片 1：'+assembled.original[0]));
    assert.ok(assembled.message.apiText.includes('图片 2：'+assembled.original[1]));
    assert.ok(!assembled.message.apiText.includes('OTHER_GROUP_ONLY'),'Requirements never leak from another group');
    assert.deepEqual(assembled.message.semanticContexts.map(context=>context.request_id),['image-one','image-two']);
    await seed([assembled.message]);
    payload = await sendEdit(0,assembled.message.text);
    assert.ok(payload.messages.at(-1).content.includes('要求适用于本组全部图片'));
    assert.ok(payload.messages.at(-1).content.includes(assembled.original[1]));
    assert.ok(!JSON.stringify(payload).includes('OTHER_GROUP_ONLY'));
    await seed([{role:'user',source:'ocr',ocrIsQuestion:true,text:rendered + marker + '旧组合要求',
      apiText:canonical,semanticContexts:grouped,ocrGroup}]);
    payload = await sendEdit(0,rendered + marker + '结合第二张图解释');
    edited = await message();
    assert.deepEqual(edited.ocrGroup,ocrGroup);
    assert.deepEqual(payload.semantic_contexts.map(value => value.request_id),['image-one','image-two']);
    assert.equal(payload.semantic_context,undefined);
    assert.deepEqual(payload.semantic_contexts,edited.semanticContexts);
    assert.ok(payload.messages.at(-1).content.includes('要求适用于本组全部图片'));
    assert.ok(payload.messages.at(-1).content.includes('结合第二张图解释'));
    console.log('PASS grouped OCR edits preserve confirmed image order and question/supporting membership');

    // A student answer is rechecked against the retained generated question and reference answer.
    const retest = {wrongQuestionId:'saved-question',stage:'finished',targetPoints:['关系'],
      referenceQuestion:'原错题 ORIGINAL_REFERENCE',targetDifficulty:'中等',
      generatedQuestion:'复测题 GENERATED_QUESTION',generatedAnswer:'系统答案 HIDDEN_REFERENCE',startedAt:1,result:'wrong'};
    await seed([{role:'user',text:'原始出题请求',isRetestPrompt:true},
      {role:'ai',text:retest.generatedQuestion,generatedQuestion:retest.generatedQuestion,generatedExercise:true},
      {role:'user',text:'旧学生答案 OLD_STUDENT_ANSWER',isRetestAnswer:true,apiText:'旧核验上下文 OLD_CHECK'},
      {role:'ai',text:'旧核验结果 OLD_FEEDBACK'}],retest);
    payload = await sendEdit(2,'新的学生答案 NEW_STUDENT_ANSWER');
    edited = await message();
    const continued = await page.evaluate(() => getCurrent().retest);
    assert.equal(continued.stage,'checking'); assert.equal(continued.result,'');
    assert.equal(continued.generatedQuestion,retest.generatedQuestion);
    assert.equal(continued.generatedAnswer,retest.generatedAnswer);
    assert.equal(continued.referenceQuestion,retest.referenceQuestion);
    assert.equal(edited.isRetestAnswer,true);
    assert.ok(edited.apiText.includes(retest.generatedQuestion));
    assert.ok(edited.apiText.includes(retest.generatedAnswer));
    assert.ok(edited.apiText.includes('NEW_STUDENT_ANSWER'));
    assert.ok(!edited.apiText.includes('OLD_STUDENT_ANSWER')); assert.ok(!edited.apiText.includes('OLD_CHECK'));
    assert.ok(payload.messages.at(-1).content.includes(edited.apiText));
    assert.ok(!JSON.stringify(payload.messages).includes('OLD_FEEDBACK'));
    console.log('PASS edited retest answer reuses the retained question/reference and clears the previous assessment');

    // Editing the generation prompt becomes an ordinary new request, with no obsolete retest state.
    await seed([{role:'user',text:'旧的复测出题请求',apiText:'旧隐藏指令 STALE_GENERATION_PROMPT',isRetestPrompt:true},
      {role:'ai',text:retest.generatedQuestion,generatedQuestion:retest.generatedQuestion,generatedExercise:true}],
      {...retest,stage:'generating',result:''});
    payload = await sendEdit(0,'请用自己的话说明等价关系 NEW_NORMAL_REQUEST');
    edited = await message();
    assert.equal(await page.evaluate(() => getCurrent().retest),null);
    assert.equal(edited.isRetestPrompt,undefined); assert.equal(edited.isRetestAnswer,undefined);
    assert.equal(edited.apiText,undefined); assert.equal(payload.exercise_reference,undefined);
    for (const stale of ['STALE_GENERATION_PROMPT','ORIGINAL_REFERENCE','HIDDEN_REFERENCE','GENERATED_QUESTION'])
      assert.ok(!JSON.stringify(payload).includes(stale),'new request excludes ' + stale);
    assert.ok(payload.messages.at(-1).content.includes(edited.text));
    assert.deepEqual(imageRequests,[],'re-editing never starts OCR, recognition or graph confirmation');
    assert.deepEqual(errors,[]);
    await page.evaluate(() => stopCurrentAiReply());
    await browserContext.close();
    console.log('PASS edited generation prompt exits the old retest without leaking its cached reference');
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode = 1;});
