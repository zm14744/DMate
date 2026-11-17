/* Full graph history follows sidebar conversations and each message sequence.
 * All model/account paths are mocked; no paid requests or cloud writes occur.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const cards = '#knowledgeGraphHistory .kg-history-item';

async function settle(page) {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function openHistory(page) {
  await page.evaluate(async () => {
    if (document.getElementById('knowledgeGraphModal').classList.contains('hidden')) await openKnowledgeGraph();
    if (knowledgeGraphViewMode !== 'full') selectKnowledgeGraphDisplayMode('full');
    setKnowledgeGraphFullscreenView(false);
  });
  await page.locator('#knowledgeGraphHistoryTab').click();
  await page.locator('#knowledgeGraphHistoryWrap').waitFor({state:'visible'});
  await settle(page);
}

async function recentHasNoHistory(page, label) {
  await page.evaluate(() => selectKnowledgeGraphDisplayMode('focus'));
  await settle(page);
  assert.equal(await page.locator('#knowledgeGraphHistoryTab').isVisible(), false, label + ': recent mode hides the history entry');
  assert.equal(await page.locator('#knowledgeGraphHistoryWrap').isVisible(), false, label + ': recent mode hides history content');
  assert.equal(await page.locator(cards).count(), 0, label + ': recent mode does not render hidden history cards');
}

async function seedConversations(page) {
  return page.evaluate(() => {
    const teaching = (category, point, difficulty='简单', type='判断题') => ({category,
      focus_points:[point],knowledge_points:[point],prerequisite_points:[],knowledge_path:[point],difficulty,question_type:type});
    const shared = '判断 p 与 q 的合取在什么情况下为真。';
    const generated = '证明命题 p 的双重否定与 p 等价。';
    const logical = teaching('命题逻辑','逻辑联结词');
    const sets = teaching('集合与关系','集合运算','中等','计算题');
    const top = {id:'history-top',name:'顶部对话 <b>TOP</b>.',nameSource:'user',createdAt:1,updatedAt:1,deletedMessageIds:{},learningQuestion:null,
      teaching:logical,messages:[
        {messageId:'top-manual',role:'user',text:shared,manualIsQuestion:true,questionTeaching:logical,createdAt:999},
        {messageId:'top-reply',role:'ai',text:'这是对合取条件的解释，不是新题。',createdAt:998},
        {messageId:'top-ocr',role:'user',text:'【题目文字】\n计算集合 A={1,2}, B={2,3} 的并集。',source:'ocr',ocrIsQuestion:true,questionTeaching:sets,createdAt:900},
        {messageId:'top-generated',role:'ai',text:generated,generatedQuestion:generated,
          generatedTeaching:teaching('命题逻辑','逻辑等价','困难','证明题'),createdAt:1},
        {messageId:'top-duplicate',role:'user',text:shared,manualIsQuestion:true,questionTeaching:logical},
        {messageId:'top-explicit-no',role:'user',text:'证明集合 A 的双重补等于 A。',manualIsQuestion:false,questionTeaching:sets},
        {messageId:'top-image-no',role:'user',text:'【题目文字】\n求函数 f 的复合。',source:'ocr',ocrIsQuestion:false},
        {messageId:'top-request',role:'user',text:'我要简单题',manualIsQuestion:true}
      ]};
    const empty = {id:'history-empty',name:'没有题目的中间对话',nameSource:'user',createdAt:8888,updatedAt:8888,deletedMessageIds:{},
      teaching:null,learningQuestion:null,messages:[{messageId:'empty-user',role:'user',text:'你好',manualIsQuestion:false},
        {messageId:'empty-ai',role:'ai',text:'你好，有什么需要帮助的？'}]};
    const lower = {id:'history-lower',name:'底部对话',nameSource:'user',createdAt:9999,updatedAt:9999,deletedMessageIds:{},learningQuestion:null,
      teaching:sets,messages:[
        {messageId:'lower-shared',role:'user',text:shared,manualIsQuestion:true,questionTeaching:logical,createdAt:9000},
        {messageId:'lower-follow-up',role:'user',text:'详细解释一下',manualIsQuestion:false,createdAt:5000},
        {messageId:'lower-later',role:'user',text:'列出集合 A={1,2} 的幂集。',manualIsQuestion:true,questionTeaching:sets,createdAt:2},
        {messageId:'lower-answer',role:'user',text:'这是学生的解答',manualIsQuestion:true,isRetestAnswer:true},
        {messageId:'lower-reply',role:'ai',text:'应当逐个检查这些子集'}
      ]};
    sessions=[top,empty,lower]; currentId=lower.id; deletedSessionIds=Object.create(null);
    renderAll();
    // Simulate a legacy generated-question record outside the current session.
    // Rendering an aggregate history must never "repair" it in place.
    delete top.messages[3].generatedExercise;
    const snapshot=JSON.stringify(sessions.map(session=>({id:session.id,messages:session.messages})));
    return {snapshot,conversationOrder:[top.id,empty.id,lower.id],names:[top.name,lower.name],
      questionIds:['top-manual','top-ocr','top-generated','lower-shared','lower-later']};
  });
}

async function checkCase(browser,width,language) {
  const label=width+'/'+language,mobile=width<=760;
  const context=await browser.newContext({viewport:{width,height:900},serviceWorkers:'block',
    ...(mobile?{isMobile:true,hasTouch:true}:{})});
  const page=await context.newPage(),errors=[],modelCalls=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/auth/me',route=>route.fulfill({contentType:'application/json',body:'{"configured":true,"authenticated":false}'}));
  await page.route(/\/(?:chat|analyze-questions|classify|conversation\/title|ocr)(?:\?|$)/,route=>{
    modelCalls.push(new URL(route.request().url()).pathname);return route.abort();
  });
  try {
    await page.goto(baseURL,{waitUntil:'networkidle'});
    await page.waitForFunction(()=>!accountVerificationOperation);
    const fixture=await seedConversations(page);
    await page.evaluate(value=>DMateI18n.setLanguage(value,false),language);
    const sidebarOrder=await page.locator('#sessions>.session').evaluateAll(nodes=>nodes.map(node=>node.dataset.sessionId));
    assert.deepEqual(sidebarOrder,fixture.conversationOrder,label+': fixture sidebar order intentionally contradicts timestamps');
    await openHistory(page);
    assert.equal(await page.locator('#knowledgeGraphHistoryTab').innerText(),language==='en'?'Question history (5)':'题目历史 (5)',
      label+': full mode counts all conversations, with only within-conversation duplicate removal');
    assert.deepEqual(await page.locator('#knowledgeGraphHistory .kg-history-conversation').evaluateAll(nodes=>nodes.map(node=>node.dataset.sessionId)),
      ['history-top','history-lower'],label+': nonempty groups follow the exact visible sidebar order');
    assert.deepEqual(await page.locator('#knowledgeGraphHistory .kg-history-conversation-title').allTextContents(),fixture.names,
      label+': custom conversation names remain literal user text');
    assert.equal(await page.locator('#knowledgeGraphHistory .kg-history-conversation-title b').count(),0,
      label+': custom title HTML is displayed as text');
    assert.deepEqual(await page.locator(cards).evaluateAll(nodes=>nodes.map(node=>node.dataset.messageId)),fixture.questionIds,
      label+': each conversation shows questions oldest to newest by message order');
    assert.deepEqual(await page.locator(cards+' .kg-history-number').allTextContents(),language==='en'
      ?['Question 1','Question 2','Question 3','Question 1','Question 2']:['第 1 题','第 2 题','第 3 题','第 1 题','第 2 题'],
      label+': per-conversation numbering restarts for each group');
    assert.match(await page.locator('.kg-history-item[data-message-id="top-manual"] .kg-history-preview').innerText(),/为真。$/,
      label+': question punctuation is protected user content');
    assert.equal(await page.evaluate(()=>window.__historyInjected),undefined,label+': no injected title markup executes');
    const snapshot=()=>page.evaluate(()=>JSON.stringify(sessions.map(session=>({id:session.id,messages:session.messages}))));
    assert.equal(await snapshot(),fixture.snapshot,label+': aggregate rendering does not mutate manual/OCR/legacy AI messages');
    assert.equal(await page.locator('#knowledgeGraphModal .graph-status-pill.current').count(),0,
      label+': full mode remains independent of the current question');

    await page.locator('.kg-history-item[data-message-id="top-generated"] [data-history-action="graph"]').click();
    await page.waitForFunction(()=>knowledgeGraphViewMode==='full'&&knowledgeGraphFilter==='命题逻辑'&&knowledgeGraphSelectedNodeId==='logic_equivalence');
    assert.equal(await page.evaluate(()=>currentId),'history-lower',label+': graph navigation does not switch the conversation');
    assert.equal(await page.locator('#knowledgeGraphDetail .graph-status-pill.current').count(),0,label+': history graph navigation adds no question marker');
    await recentHasNoHistory(page,label);
    assert.equal(await page.evaluate(()=>getCurrent().id),'history-lower',label+': recent mode still uses the actual current conversation');
    assert.equal(await snapshot(),fixture.snapshot,label+': graph/side-mode navigation does not rewrite questions');

    await openHistory(page);
    await page.locator('.kg-history-item[data-message-id="top-ocr"] [data-history-action="locate"]').click();
    await page.waitForFunction(()=>currentId==='history-top'&&document.getElementById('knowledgeGraphModal').classList.contains('hidden'));
    await page.locator('#chat [data-message-index="2"].history-locate-flash').waitFor();
    assert.match(await page.locator('#chat [data-message-index="2"]').innerText(),/计算集合 A=\{1,2\}/,
      label+': locate selects the source conversation and its exact OCR message');
    const locatedMessages=JSON.parse(await snapshot());
    // Opening the real chat may repair this legacy AI display marker. History
    // reads above must remain fully immutable; message content still must match.
    delete locatedMessages.find(session=>session.id==='history-top').messages[3].generatedExercise;
    assert.deepEqual(locatedMessages,JSON.parse(fixture.snapshot),label+': locating a source preserves question text, source, teaching and identity');

    await openHistory(page);
    const staleCard=await page.locator('.kg-history-item[data-message-id="top-ocr"] [data-history-action="locate"]').elementHandle();
    await page.evaluate(()=>{const session=sessions.find(session=>session.id==='history-top');
      const [moved]=session.messages.splice(2,1);session.messages.push(moved);renderKnowledgeGraph();});
    await staleCard.evaluate(button=>button.click());
    await page.waitForFunction(()=>document.getElementById('knowledgeGraphModal').classList.contains('hidden'));
    await page.locator('#chat [data-message-index="7"].history-locate-flash').waitFor();
    assert.match(await page.locator('#chat [data-message-index="7"]').innerText(),/计算集合 A=\{1,2\}/,
      label+': a captured card resolves stable message identity after message movement');

    await openHistory(page);
    const deletedCard=await page.locator('.kg-history-item[data-message-id="lower-later"] [data-history-action="locate"]').elementHandle();
    await page.evaluate(()=>{sessions.find(session=>session.id==='history-lower').messages=sessions.find(session=>session.id==='history-lower').messages.filter(message=>message.messageId!=='lower-later');renderKnowledgeGraph();});
    await deletedCard.evaluate(button=>button.click());
    assert.equal(await page.evaluate(()=>currentId),'history-top',label+': a stale card cannot locate a removed message');
    assert.equal(await page.locator('#knowledgeGraphModal').isVisible(),true,label+': removed-message action leaves the current UI intact');

    await openHistory(page);
    const editedGraphCard=await page.locator('.kg-history-item[data-message-id="lower-shared"] [data-history-action="graph"]').elementHandle();
    const editedLocateCard=await page.locator('.kg-history-item[data-message-id="lower-shared"] [data-history-action="locate"]').elementHandle();
    const beforeEditedAction=await page.evaluate(()=>({conversation:currentId,category:knowledgeGraphFilter,selected:knowledgeGraphSelectedNodeId}));
    await page.evaluate(()=>{sessions.find(session=>session.id==='history-lower').messages[0].text='判断 p 与 q 的析取在什么情况下为假。';renderKnowledgeGraph();});
    await editedGraphCard.evaluate(button=>button.click());
    await editedLocateCard.evaluate(button=>button.click());
    assert.deepEqual(await page.evaluate(()=>({conversation:currentId,category:knowledgeGraphFilter,selected:knowledgeGraphSelectedNodeId})),
      beforeEditedAction,label+': an edited same-ID question invalidates stale graph/source actions');
    assert.equal(await page.locator('#knowledgeGraphModal').isVisible(),true,label+': a stale edited-question action leaves the graph open');

    await openHistory(page);
    const oldOwnerCard=await page.locator('.kg-history-item[data-message-id="lower-shared"] [data-history-action="locate"]').elementHandle();
    await page.evaluate(()=>bumpCloudSyncContext());
    await oldOwnerCard.evaluate(button=>button.click());
    assert.equal(await page.evaluate(()=>currentId),'history-top',label+': an old context cannot navigate into another conversation');
    assert.equal(await page.locator('#knowledgeGraphModal').isVisible(),true,label+': stale account/context action keeps the current page');
    assert.deepEqual(modelCalls,[],label+': history rendering/navigation never calls a model');
    assert.deepEqual(errors,[],label+': no browser errors');
    console.log('PASS '+label+': all-conversation history ordering, strict question identity, raw names/content, full-only UI, graph/source actions and stale identity/context guards');
  } finally {await context.close();}
}

async function checkReplyRetention(browser) {
  const context=await browser.newContext({viewport:{width:1440,height:900},serviceWorkers:'block'});
  const page=await context.newPage(),errors=[],requests=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/auth/me',route=>route.fulfill({contentType:'application/json',body:'{"configured":true,"authenticated":false}'}));
  await page.route('**/analyze-questions',route=>route.fulfill({contentType:'application/json',body:'{"entries":[]}'}));
  await page.route('**/conversation/title',route=>route.fulfill({contentType:'application/json',body:'{}'}));
  await page.route('**/chat',route=>{requests.push(route);});
  try {
    await page.goto(baseURL,{waitUntil:'networkidle'});
    await page.waitForFunction(()=>!accountVerificationOperation);
    await seedConversations(page);
    await page.evaluate(()=>{
      getCurrent().messages.push({messageId:'history-generation-request',role:'user',text:'给我一道命题逻辑练习题',manualIsQuestion:false});
      window.historyReplyPromise=requestAiReply(getCurrent(),{completeImmediately:true});
    });
    for(let attempt=0;attempt<100&&requests.length<1;attempt++)await new Promise(resolve=>setTimeout(resolve,20));
    assert.equal(requests.length,1,'exactly one explicit generated-question request is pending');
    await openHistory(page);
    await page.evaluate(()=>setKnowledgeGraphFilter('函数'));
    await page.locator('#knowledgeGraphHistoryTab').click();
    assert.match(await page.locator('#knowledgeGraphHistoryTab').innerText(),/5/);
    const generated='证明对于任意命题 p，p 与 p 的合取和 p 等价。';
    const teaching={category:'命题逻辑',knowledge_points:['逻辑等价'],focus_points:['逻辑等价'],
      prerequisite_points:['逻辑联结词'],knowledge_path:['逻辑等价'],difficulty:'简单',question_type:'证明题'};
    await requests[0].fulfill({status:200,contentType:'text/event-stream',body:'event: final\ndata: '+JSON.stringify({
      reply:generated,generated_question:generated,generated_teaching:teaching})+'\n\n'});
    await page.waitForFunction(text=>getCurrent().messages.some(message=>message.generatedQuestion===text),generated);
    assert.equal((await page.evaluate(()=>window.historyReplyPromise)).status,'success','the real answer commit path completes');
    await page.waitForFunction(()=>document.getElementById('knowledgeGraphHistoryTab').textContent.includes('6'));
    assert.deepEqual(await page.evaluate(()=>({mode:knowledgeGraphViewMode,category:knowledgeGraphFilter})),
      {mode:'full',category:'函数'},'an incoming answer does not force full history into recent-question mode or change the selected module');
    assert.equal(await page.locator('#knowledgeGraphHistoryWrap').isVisible(),true,'the active question-history pane stays open');
    assert.equal(await page.locator(cards).count(),6,'a committed generated question refreshes the aggregate count');
    assert.equal(await page.locator(cards).last().getAttribute('data-session-id'),'history-lower','new questions stay in their sidebar conversation group');
    assert.match(await page.locator(cards).last().locator('.kg-history-preview').innerText(),/p 与 p 的合取和 p 等价/,
      'the generated question follows the older questions in its conversation');
    assert.equal(await page.locator('#knowledgeGraphModal .graph-status-pill.current').count(),0,'full history remains free of current-question decorations');
    assert.equal(requests.length,1,'history refresh does not repeat the model request');
    assert.deepEqual(errors,[],'incoming answer history checks have no browser errors');
    console.log('PASS incoming generated answer: full/history/filter remain selected and the new question appears in its conversation order');
  } finally {await context.close();}
}

(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.CHROMIUM_EXECUTABLE_PATH}:{})});
  try {for(const width of [1440,390])for(const language of ['zh-CN','en'])await checkCase(browser,width,language);await checkReplyRetention(browser);}
  finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
