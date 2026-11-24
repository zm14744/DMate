/* Independent history mode lists live conversation questions by first appearance.
 * All model/account paths are mocked; no paid requests or cloud writes occur.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const { expandGraphDetails } = require('./knowledge-graph-touch-fixtures.cjs');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const cards = '#knowledgeGraphHistory .kg-history-item';

async function settle(page) {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function openHistory(page) {
  await page.evaluate(async () => {
    if (document.getElementById('knowledgeGraphModal').classList.contains('hidden')) await openKnowledgeGraph();
    selectKnowledgeGraphDisplayMode('history');
  });
  await page.locator('#knowledgeGraphHistoryWrap').waitFor({state:'visible'});
  await settle(page);
}

async function checkFirstMathPaint(page) {
  const url = '**/tex-svg.js';
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  await page.route(url, async route => { await gate; await route.continue(); });
  try {
    await page.evaluate(() => {
      sessions[0].messages.push({messageId:'first-history-math', role:'user',
        text:'求集合 $A \\cup B$ 的大小。', manualIsQuestion:true});
    });
    const requested = page.waitForRequest(url);
    await openHistory(page);
    await requested;
    const mathCard = page.locator(cards + '[data-message-id="first-history-math"]');
    const preview = mathCard.locator('.kg-history-preview');
    const plain = page.locator(cards + '[data-message-id="top-manual"] .kg-history-preview');
    for (let visit = 0; visit < 2; visit++) {
      if (visit) {
        await page.locator('#knowledgeGraphFocusBtn').click();
        await openHistory(page);
      }
      assert.equal(await preview.count(), 1);
      assert.equal(await preview.isVisible(), false, 'Raw TeX stays hidden until typesetting completes');
      assert.equal(await plain.isVisible(), true, 'Plain questions remain readable during the math download');
      await mathCard.locator('[data-history-action="locate"]').click({trial:true});
    }
    release();
    await preview.locator('mjx-container > svg').waitFor({state:'visible'});
    assert.doesNotMatch(await preview.innerText(), /\$|\\cup/);
  } finally {
    release();
    await page.unroute(url);
    await page.evaluate(() => {
      closeKnowledgeGraph();
      sessions[0].messages = sessions[0].messages.filter(message => message.messageId !== 'first-history-math');
    });
  }
}


async function assertModeControls(page,mode,label,recentAvailable=true) {
  const selectors={full:'#knowledgeGraphFocusBtn',focus:'#knowledgeGraphScopeBtn',history:'#knowledgeGraphHistoryBtn'};
  for(const [value,selector] of Object.entries(selectors)) {
    assert.equal(await page.locator(selector).isVisible(),value==='focus'?recentAvailable:true,
      label+': the '+value+' top-level mode follows actual question availability');
    assert.equal(await page.locator(selector).getAttribute('aria-pressed'),String(value===mode),
      label+': exactly the selected top-level mode is pressed');
  }
  assert.equal(await page.evaluate(()=>knowledgeGraphViewMode),mode,label+': the mode state matches the toolbar');
}

async function fullHasNoHistory(page,label,recentAvailable=true) {
  await page.evaluate(()=>selectKnowledgeGraphDisplayMode('full'));
  await settle(page);
  await assertModeControls(page,'full',label,recentAvailable);
  assert.equal(await page.locator('#knowledgeGraphSideTabs').isVisible(),false,label+': full mode has no sidebar mode tabs');
  await expandGraphDetails(page);
  assert.equal(await page.locator('#knowledgeGraphDetailWrap').isVisible(),true,label+': full mode shows only node details');
  assert.equal(await page.locator('#knowledgeGraphHistoryWrap').isVisible(),false,label+': full mode does not show the history list');
  assert.equal(await page.locator(cards).count(),0,label+': full mode does not leave hidden history cards behind');
  assert.equal(await page.locator('#knowledgeGraphLocateOriginal').count(),0,label+': full mode has no question-specific source locator');
}

async function recentHasNoHistory(page, label) {
  await page.evaluate(() => selectKnowledgeGraphDisplayMode('focus'));
  await settle(page);
  await assertModeControls(page,'focus',label);
  assert.equal(await page.locator('#knowledgeGraphSideTabs').isVisible(),false,label+': recent mode has no sidebar mode tabs');
  await expandGraphDetails(page);
  assert.equal(await page.locator('#knowledgeGraphDetailWrap').isVisible(),true,label+': recent mode shows node details');
  assert.equal(await page.locator('#knowledgeGraphHistoryTab').isVisible(), false, label + ': recent mode hides the history entry');
  assert.equal(await page.locator('#knowledgeGraphHistoryWrap').isVisible(), false, label + ': recent mode hides history content');
  assert.equal(await page.locator(cards).count(), 0, label + ': recent mode does not render hidden history cards');
}

async function seedConversations(page) {
  return page.evaluate(() => {
    const teaching = (category, point, question, id, quote, difficulty='简单', type='判断题') => ({category,
      focus_points:[point],knowledge_points:[point],prerequisite_points:[],knowledge_path:[point],difficulty,question_type:type,
      question_graph:{version:1,classifier_revision:'catalog-semantic-v5',classification_status:'semantic',classification_source:'catalog_semantic',needs_review:false,sources:{question,solution:''},nodes:[{id,evidence:[{source:'question',quote}]}],edges:[]}});
    const shared = '判断 p 与 q 的合取在什么情况下为真。';
    const generated = '证明命题 p 的双重否定与 p 等价。';
    const ocrQuestion = '## 离散数学习题\n\n2. 计算集合 A={1,2}, B={2,3} 的并集。\n(1) 写出并集。\n(2) 判断 2.5 是否属于并集。\n3. 再求交集。';
    const powerQuestion = '1. 列出集合 A={1,2} 的幂集。\n2. 写出幂集的大小。';
    const logical = teaching('命题逻辑','逻辑联结词',shared,'logic_connectives','合取');
    const sets = teaching('集合与关系','集合运算',ocrQuestion,'set_operation','并集','中等','计算题');
    const top = {id:'history-top',name:'顶部对话 <b>TOP</b>.',nameSource:'user',createdAt:1,updatedAt:1,deletedMessageIds:{},learningQuestion:null,
      teaching:logical,messages:[
        {messageId:'top-manual',role:'user',text:shared,manualIsQuestion:true,questionTeaching:logical,createdAt:999},
        {messageId:'top-reply',role:'ai',text:'这是对合取条件的解释，不是新题。',createdAt:998},
        {messageId:'top-ocr',role:'user',text:'【题目文字】\n'+ocrQuestion,source:'ocr',ocrIsQuestion:true,questionTeaching:sets,createdAt:900},
        {messageId:'top-generated',role:'ai',text:generated,generatedQuestion:generated,
          generatedTeaching:teaching('命题逻辑','逻辑等价',generated,'logic_equivalence','双重否定','困难','证明题'),createdAt:1},
        {messageId:'top-duplicate',role:'user',text:shared,manualIsQuestion:true,questionTeaching:logical,createdAt:1200},
        {messageId:'top-explicit-no',role:'user',text:'证明集合 A 的双重补等于 A。',manualIsQuestion:false,questionTeaching:sets,createdAt:1300},
        {messageId:'top-image-no',role:'user',text:'【题目文字】\n求函数 f 的复合。',source:'ocr',ocrIsQuestion:false,createdAt:1400},
        {messageId:'top-request',role:'user',text:'我要简单题',manualIsQuestion:true,createdAt:1500}
      ]};
    const empty = {id:'history-empty',name:'没有题目的中间对话',nameSource:'user',createdAt:8888,updatedAt:8888,deletedMessageIds:{},
      teaching:null,learningQuestion:null,messages:[{messageId:'empty-user',role:'user',text:'你好',manualIsQuestion:false,createdAt:8888},
        {messageId:'empty-ai',role:'ai',text:'你好，有什么需要帮助的？',createdAt:8889}]};
    const lower = {id:'history-lower',name:'底部对话',nameSource:'user',createdAt:9999,updatedAt:9999,deletedMessageIds:{},learningQuestion:null,
      teaching:sets,messages:[
        {messageId:'lower-shared',role:'user',text:shared,manualIsQuestion:true,questionTeaching:logical,createdAt:9000},
        {messageId:'lower-follow-up',role:'user',text:'详细解释一下',manualIsQuestion:false,createdAt:5000},
        {messageId:'lower-later',role:'user',text:powerQuestion,manualIsQuestion:true,
          questionTeaching:teaching('集合与关系','集合运算',powerQuestion,'set_operation','幂集','中等','计算题'),createdAt:2},
        {messageId:'lower-answer',role:'user',text:'这是学生的解答',manualIsQuestion:true,isRetestAnswer:true,createdAt:9001},
        {messageId:'lower-reply',role:'ai',text:'应当逐个检查这些子集',createdAt:9002}
      ]};
    sessions=[top,empty,lower]; currentId=lower.id; deletedSessionIds=Object.create(null);
    // Completed semantic fixtures bind their review to each question's actual
    // latest answer rather than sharing one question-only snapshot across rows.
    for(const session of sessions) {
      const byIndex=new Map(getConversationQuestionHistory(session).map(item=>[item.index,item]));
      let owner=null;
      for(const [index,message] of session.messages.entries()) {
        const item=byIndex.get(index);
        if(item) {
          const field=item.role==='ai'?'generatedTeaching':'questionTeaching';
          message[field]=JSON.parse(JSON.stringify(message[field]));
          owner=message[field]?.question_graph;
          if(owner)owner.sources.solution=item.role==='ai'?String(message.generatedAnswer||''):'';
        } else if(message.role==='ai'&&!message.generatedExercise&&owner)owner.sources.solution=message.text;
      }
    }
    renderAll();
    // Simulate a legacy generated-question record outside the current session.
    // Rendering an aggregate history must never "repair" it in place.
    delete top.messages[3].generatedExercise;
    const snapshot=JSON.stringify(sessions.map(session=>({id:session.id,messages:session.messages})));
    return {snapshot,conversationOrder:[top.id,empty.id,lower.id],names:[top.name,lower.name],
      questionIds:['top-generated','lower-later','top-ocr','top-manual','top-duplicate','lower-shared']};
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
    if (width === 1440 && language === 'zh-CN') await checkFirstMathPaint(page);
    await page.evaluate(value=>DMateI18n.setLanguage(value,false),language);
    const sidebarOrder=await page.locator('#sessions>.session').evaluateAll(nodes=>nodes.map(node=>node.dataset.sessionId));
    assert.deepEqual(sidebarOrder,fixture.conversationOrder,label+': fixture sidebar order intentionally contradicts timestamps');
    await page.evaluate(async()=>openKnowledgeGraph());
    await fullHasNoHistory(page,label+'/all knowledge');
    await openHistory(page);
    await assertModeControls(page,'history',label+'/history list');
    assert.equal(await page.locator('#knowledgeGraphSideTabs').isVisible(),true,label+': only history mode exposes detail/history tabs');
    if (mobile) {
      const reachable = await page.locator('#knowledgeGraphSideTabs button').evaluateAll(buttons => buttons.every(button => {
        const rect = button.getBoundingClientRect();
        return button.contains(document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2));
      }));
      assert.ok(reachable, label + ': the graph empty state does not cover the tabs');
    }
    assert.equal(await page.locator(cards+' .kg-history-points').count(),0,label+': history previews omit topic subtitles');
    const checkInlineList = async () => {
      assert.equal(await page.locator('#knowledgeGraphCanvas').isVisible(), false, label+': the mobile list has no canvas above it');
      assert.ok(await page.locator('#knowledgeGraphHistory').evaluate(list => {
        const tabs = document.getElementById('knowledgeGraphSideTabs');
        const pane = list.closest('.knowledge-graph-side');
        const bounds = list.getBoundingClientRect(), toolbar = tabs.parentElement.getBoundingClientRect();
        const layout = pane.parentElement.getBoundingClientRect();
        return tabs.parentElement.matches('.graph-toolbar') && getComputedStyle(pane).position !== 'absolute'
          && Math.abs(bounds.top - toolbar.bottom) <= 1 && Math.abs(bounds.bottom - layout.bottom) <= 1;
      }), label+': the inline mobile list fills the area immediately below the toolbar');
    };
    if (mobile) await checkInlineList();
    await page.locator('#knowledgeGraphDetailTab').click();
    const selectPrompt = language === 'en' ? 'Select a question' : '请选择题目';
    assert.equal(await page.locator('#knowledgeGraphCanvas').innerText(), selectPrompt,
      label+': historical detail waits for a question selection');
    const selectIcon = page.locator('#knowledgeGraphCanvas > .kg-empty-state svg');
    assert.equal(await selectIcon.isVisible(), true, label+': the selection prompt includes the graph icon');
    const artwork = svg => svg.innerHTML;
    assert.equal(await selectIcon.evaluate(artwork), await page.locator('#knowledgeGraphBtn > svg').evaluate(artwork),
      label+': the prompt reuses the navigation graph icon');
    const positioned = await selectIcon.evaluate(svg => {
      const box = svg.getBoundingClientRect();
      return box.height >= 40 && box.bottom <= svg.nextElementSibling.getBoundingClientRect().top;
    });
    assert.ok(positioned, label+': the enlarged decorative icon sits above the prompt');
    assert.equal(await page.locator('#knowledgeGraphDetailWrap').isVisible(),!mobile,label+': only desktop shows a separate empty detail pane');
    if (!mobile) assert.equal(await page.locator('#knowledgeGraphDetail').innerText(),language === 'en' ? 'No nodes yet' : '暂无节点');
    assert.equal(await page.locator('#knowledgeGraphDetail svg').count(),0,label+': empty details contain no icon');
    assert.equal(await page.locator('#knowledgeGraphSideTabs').isVisible(),true,label+': empty historical details keep both sidebar tabs accessible');
    assert.deepEqual(await page.evaluate(()=>knowledgeGraphDisplayedNodes().map(node=>node.id)),[],label+': unselected historical details never fall back to a full course graph');
    assert.equal(await page.locator('#knowledgeGraphLocateOriginal').count(),0,label+': an unselected historical detail has no source locator');
    await page.locator('#knowledgeGraphHistoryTab').click();
    assert.equal(await page.locator('#knowledgeGraphHistoryWrap').isVisible(),true,label+': the sidebar returns to the historical list before a selection');
    assert.equal(await page.locator('#knowledgeGraphHistoryTab').innerText(),language==='en'?'Past questions (6)':'历史题目 (6)',
      label+': every separate question message remains in history, including identical question text');
    assert.equal(await page.locator('#knowledgeGraphHistory .kg-history-conversation-title').count(),0,
      label+': conversation titles do not appear in the flat question list');
    assert.deepEqual(await page.locator(cards).evaluateAll(nodes=>nodes.map(node=>node.dataset.messageId)),fixture.questionIds,
      label+': questions from all conversations interleave by their own first-appearance times');
    assert.equal(await page.locator(cards+' .kg-history-number').count(),0,
      label+': the flat list has no per-conversation question numbers');
    assert.equal(await page.locator('#knowledgeGraphHistory time,#knowledgeGraphHistory [datetime],#knowledgeGraphHistory .kg-history-time').count(),0,
      label+': ordering timestamps are not rendered');
    assert.match(await page.locator('.kg-history-item[data-message-id="top-manual"] .kg-history-preview').innerText(),/为真。$/,
      label+': question punctuation is protected user content');
    const ocrPreview = page.locator('.kg-history-item[data-message-id="top-ocr"] .kg-history-preview');
    assert.match(await ocrPreview.innerText(), /^计算集合[\s\S]*\(1\) 写出并集。[\s\S]*\(2\) 判断 2\.5 是否属于并集。\s+再求交集。$/);
    assert.equal(await ocrPreview.locator('h2,ol').count(), 0, label+': the worksheet heading and outer list marker are omitted');
    assert.equal(await page.locator('.kg-history-item[data-message-id="lower-later"] .kg-history-preview ol li').count(), 2,
      label+': an authored numbered list without a worksheet heading keeps both items');
    assert.equal(await page.evaluate(()=>window.__historyInjected),undefined,label+': no injected title markup executes');
    const snapshot=()=>page.evaluate(()=>JSON.stringify(sessions.map(session=>({id:session.id,messages:session.messages}))));
    assert.equal(await snapshot(),fixture.snapshot,label+': aggregate rendering does not mutate manual/OCR/legacy AI messages');
    assert.equal(await page.locator('#knowledgeGraphModal .graph-status-pill.current').count(),0,
      label+': history list remains independent of the current question');

    await page.locator('.kg-history-item[data-message-id="top-generated"] [data-history-action="graph"]').click();
    await page.waitForFunction(()=>knowledgeGraphViewMode==='history'&&knowledgeGraphScope==='history'&&knowledgeGraphSelectedNodeId==='logic_equivalence');
    assert.equal(await page.evaluate(()=>currentId),'history-lower',label+': graph navigation does not switch the conversation');
    await assertModeControls(page,'history',label+'/historical detail');
    await expandGraphDetails(page);
    assert.equal(await page.locator('#knowledgeGraphDetailWrap').isVisible(),true,label+': selecting a past graph opens historical node details');
    assert.equal(await page.locator('#knowledgeGraphHistoryWrap').isVisible(),false,label+': the historical list yields to its selected details');
    assert.equal(await page.locator('#knowledgeGraphLocateOriginal').count(),0,label+': historical node details have no recent-only source locator');
    assert.equal(await page.locator('.kg-section-title').innerText(),language==='en'?'Historical question connections':'历史题目关联',
      label+': the selected graph is explicitly labelled as a historical question');
    assert.equal(await page.locator('#knowledgeGraphDetail .graph-status-pill.current').count(),0,label+': history graph navigation omits the redundant detail pill');
    assert.deepEqual(await page.evaluate(()=>knowledgeGraphDisplayedNodes().map(node=>({id:node.id,prerequisites:node.prerequisites}))),
      [{id:'logic_equivalence',prerequisites:[]}],label+': history graph includes only the question concept without fixed course prerequisites');
    assert.equal(await page.evaluate(()=>knowledgeGraphNodeState('逻辑等价',getActiveKnowledgeContext()).fill),'#5b21b6',
      label+': history graph retains the selected question concepts in purple');
    await page.locator('#knowledgeGraphHistoryTab').click();
    assert.equal(await page.locator('#knowledgeGraphHistoryWrap').isVisible(),true,label+': the history sidebar tab returns to the list without changing top-level mode');
    if (mobile) await checkInlineList();
    await assertModeControls(page,'history',label+'/return to historical list');
    await page.locator('#knowledgeGraphDetailTab').click();
    assert.equal(await page.locator('#knowledgeGraphDetailTitle').isVisible(),true,label+': revisiting details shows the selected node title');
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
    console.log('PASS '+label+': chronological flat history, strict question identity, title/number-free content, graph/source actions and stale identity/context guards');
  } finally {await context.close();}
}

async function checkModeTransitions(browser,width) {
  const label=width+'/mode transitions',mobile=width<=760;
  const context=await browser.newContext({viewport:{width,height:900},serviceWorkers:'block',
    ...(mobile?{isMobile:true,hasTouch:true}:{})});
  const page=await context.newPage(),errors=[],modelCalls=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/auth/me',route=>route.fulfill({contentType:'application/json',body:'{"configured":true,"authenticated":false}'}));
  await page.route(/\/(?:chat|analyze-questions|classify|conversation\/title|ocr)(?:\?|$)/,route=>{
    modelCalls.push(new URL(route.request().url()).pathname);return route.abort();
  });
  const switchConversation=async id=>{
    await page.evaluate(()=>closeKnowledgeGraph());
    await page.locator('#sessions>.session[data-session-id="'+id+'"] [data-session-name]').evaluate(node=>node.click());
    await page.waitForFunction(id=>String(currentId)===id,id);
    assert.equal(await page.evaluate(()=>String(getCurrent().id)),id,label+': the real sidebar handler selects '+id);
    await page.evaluate(() => openKnowledgeGraph());
    await settle(page);
  };
  const enterHome=async()=>{
    await page.evaluate(()=>{closeKnowledgeGraph();currentId=null;renderAll();});
    await page.evaluate(async()=>openKnowledgeGraph());
    await settle(page);
  };
  try {
    await page.goto(baseURL,{waitUntil:'networkidle'});
    await page.waitForFunction(()=>!accountVerificationOperation);
    await page.evaluate(async()=>openKnowledgeGraph());
    await assertModeControls(page,'full',label+'/initial home',false);
    assert.equal(await page.evaluate(()=>getCurrent()),null,label+': the initial centered-composer home has no current conversation');
    await page.evaluate(()=>closeKnowledgeGraph());
    await seedConversations(page);
    await page.evaluate(()=>{
      sessions.push({id:'existing-blank',name:'已有空对话',nameSource:'user',messages:[],teaching:null,learningQuestion:null,deletedMessageIds:{}});
      renderAll();
    });
    await page.evaluate(async()=>openKnowledgeGraph());
    await recentHasNoHistory(page,label+'/recent');
    await expandGraphDetails(page);
    assert.equal(await page.locator('#knowledgeGraphLocateOriginal').isVisible(),true,label+': recent details retain source navigation');
    await switchConversation('history-top');
    await assertModeControls(page,'focus',label+'/switch nonempty while recent');
    await openHistory(page);
    await page.locator('.kg-history-item[data-message-id="top-ocr"] [data-history-action="graph"]').click();
    assert.equal(await page.locator('#knowledgeGraphLocateOriginal').count(),0,label+': history details omit the source locator');
    const subject=await page.evaluate(()=>knowledgeGraphQuestionReference.messageId);
    await page.evaluate(()=>closeKnowledgeGraph());
    await page.evaluate(async()=>openKnowledgeGraph());
    await assertModeControls(page,'history',label+'/reopen historical detail');
    assert.equal(await page.evaluate(()=>knowledgeGraphQuestionReference.messageId),subject,label+': reopening preserves the selected historical question');
    await expandGraphDetails(page);
    assert.equal(await page.locator('#knowledgeGraphDetailWrap').isVisible(),true,label+': reopening preserves the historical detail pane');
    await switchConversation('history-lower');
    await assertModeControls(page,'history',label+'/switch nonempty while history');
    await switchConversation('existing-blank');
    await assertModeControls(page,'history',label+'/existing empty conversation',false);
    await enterHome();
    await assertModeControls(page,'full',label+'/return home resets full',false);
    assert.equal(await page.evaluate(()=>knowledgeGraphQuestionReference),null,label+': entering home clears the selected historical subject');
    await fullHasNoHistory(page,label+'/home full details',false);
    await page.evaluate(()=>{selectKnowledgeGraphDisplayMode('focus');renderAll();});
    await assertModeControls(page,'full',label+'/home cannot select unavailable recent mode',false);
    await page.evaluate(()=>closeKnowledgeGraph());
    await page.evaluate(async()=>openKnowledgeGraph());
    await assertModeControls(page,'full',label+'/closing graph returns to centered home',false);
    await switchConversation('history-lower');
    await assertModeControls(page,'full',label+'/leave home after closing graph');
    await recentHasNoHistory(page,label+'/recent before second home entry');
    await enterHome();
    await assertModeControls(page,'full',label+'/second home entry',false);
    assert.deepEqual(modelCalls,[],label+': mode transitions require no model or classification calls');
    assert.deepEqual(errors,[],label+': mode transitions have no browser errors');
    console.log('PASS '+label+': three independent top modes, home reset, existing-conversation preservation and history reopen');
  } finally {await context.close();}
}

async function checkChronologyAndConversationDeletion(browser,width) {
  const label=width+'/chronology and deletion',mobile=width<=760;
  const context=await browser.newContext({viewport:{width,height:900},serviceWorkers:'block',
    ...(mobile?{isMobile:true,hasTouch:true}:{})});
  const page=await context.newPage(),errors=[],modelCalls=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/auth/me',route=>route.fulfill({contentType:'application/json',body:'{"configured":true,"authenticated":false}'}));
  await page.route(/\/(?:chat|analyze-questions|classify|conversation\/title|ocr)(?:\?|$)/,route=>{
    modelCalls.push(new URL(route.request().url()).pathname);return route.abort();
  });
  const order=()=>page.locator(cards).evaluateAll(nodes=>nodes.map(node=>node.dataset.messageId));
  const removeConversation=async id=>{
    await page.locator('#sessions>.session[data-session-id="'+id+'"] .del').evaluate(button=>button.click());
    await page.locator('#appConfirmModal').waitFor({state:'visible'});
    await page.locator('#appConfirmConfirm').click();
    await page.waitForFunction(id=>!sessions.some(session=>String(session.id)===id),id);
    await settle(page);
  };
  try {
    await page.goto(baseURL,{waitUntil:'networkidle'});
    await page.waitForFunction(()=>!accountVerificationOperation);
    await page.evaluate(()=>{
      const base=Date.UTC(2026,10,18,2,0);
      const message=(id,offset)=>{
        const text='求集合 A={1,2,'+(offset+100)+'} 与 B={2,3} 的交集';
        return {messageId:id,role:'user',text,manualIsQuestion:true,createdAt:base+offset,
          questionTeaching:{category:'集合与关系',difficulty:'简单',knowledge_points:['集合运算'],focus_points:['集合运算'],
            question_graph:{version:1,sources:{question:text,solution:''},
              nodes:[{id:'set_operation',evidence:[{source:'question',quote:'交集'}]}],edges:[]}}};
      };
      const session=(id,title,messages,offset)=>({id,name:title,nameSource:'user',createdAt:base-offset,
        updatedAt:base+offset,deletedMessageIds:{},learningQuestion:null,messages});
      sessions=[session('chrono-a','Alpha conversation title',[message('a-early',10),message('a-tombstone',15),message('a-late',50)],100),
        session('chrono-b','Beta conversation title',[message('b-first',20),message('b-second',40)],200),
        session('chrono-c','Gamma conversation title',[message('c-middle',30)],300),
        session('chrono-removed','Removed conversation title',[message('removed-question',5)],400)];
      sessions[0].deletedMessageIds['a-tombstone']=base+1000;
      deletedSessionIds=Object.assign(Object.create(null),{'chrono-removed':base+1000});
      currentId='chrono-a';
      // A retained wrong-book entry is independent of its deleted chat. It is
      // deliberately present to ensure history never uses it as a fallback.
      learningState=normalizeLearningState({version:9,events:[],wrongQuestions:[{id:'retained-wrong-b',
        question:sessions[1].messages[0].text,sessionId:'chrono-b',createdAt:base,updatedAt:base,
        difficulty:'简单',category:'集合与关系',knowledgePoints:['集合运算'],focusPoints:['集合运算'],
        referenceAnswer:'{2}',answer:'{2}',corrected:false}]});
      window.__chronologyBase=base;
      window.__chronologyMessage=message;
      renderAll();
    });
    await openHistory(page);
    assert.deepEqual(await order(),['a-early','b-first','c-middle','b-second','a-late'],
      label+': message creation time globally interleaves live questions and excludes both tombstone kinds');
    assert.equal(await page.locator('#knowledgeGraphHistory .kg-history-conversation-title,#knowledgeGraphHistory .kg-history-number,#knowledgeGraphHistory time,#knowledgeGraphHistory [datetime]').count(),0,
      label+': title, numbering and time widgets are absent');
    const text=await page.locator('#knowledgeGraphHistory').innerText();
    assert.doesNotMatch(text,/Alpha conversation title|Beta conversation title|Gamma conversation title|Removed conversation title|2026-11-18|2026\/11\/18/,
      label+': neither conversation headings nor ordering dates appear as text');

    await page.evaluate(()=>{
      sessions.reverse();
      const first=sessions.find(session=>session.id==='chrono-a');
      first.name='Renamed conversation title';first.updatedAt=__chronologyBase+999999;
      first.messages[0].updatedAt=__chronologyBase+999999;
      renderAll();renderKnowledgeGraph();
    });
    assert.deepEqual(await order(),['a-early','b-first','c-middle','b-second','a-late'],
      label+': sidebar movement, renaming and edits do not move an existing question');
    await page.evaluate(()=>{
      sessions.find(session=>session.id==='chrono-a').messages.push(__chronologyMessage('a-synced-middle',25));
      renderKnowledgeGraph();
    });
    assert.deepEqual(await order(),['a-early','b-first','a-synced-middle','c-middle','b-second','a-late'],
      label+': a newly received older question is inserted by its original appearance, not append or session order');
    await page.evaluate(()=>{
      sessions.find(session=>session.id==='chrono-a').messages.push(__chronologyMessage('a-tie',25));
      sessions.find(session=>session.id==='chrono-b').messages.push(__chronologyMessage('b-tie',25));
      renderKnowledgeGraph();
    });
    const tiedOrder=['a-early','b-first','a-synced-middle','a-tie','b-tie','c-middle','b-second','a-late'];
    assert.deepEqual(await order(),tiedOrder,label+': equal timestamps retain separate messages with stable source identity');
    await page.evaluate(()=>{sessions.reverse();renderAll();renderKnowledgeGraph();});
    assert.deepEqual(await order(),tiedOrder,label+': equal-time ordering does not depend on the sidebar order');

    const stale=await page.locator('.kg-history-item[data-message-id="b-first"] [data-history-action="locate"]').elementHandle();
    await removeConversation('chrono-b');
    assert.equal(await page.locator('#knowledgeGraphModal').isVisible(),true,label+': deleting a different conversation leaves history open');
    assert.deepEqual(await order(),['a-early','a-synced-middle','a-tie','c-middle','a-late'],
      label+': the real delete handler removes all of that conversation\'s questions immediately');
    assert.equal(await page.locator('#knowledgeGraphHistoryTab').innerText(),'历史题目 (5)',label+': deletion updates the visible count');
    assert.equal(await page.evaluate(()=>learningState.wrongQuestions.length),1,label+': retained wrong-book data does not recreate deleted chat history');
    await stale.evaluate(button=>button.click());
    assert.equal(await page.evaluate(()=>currentId),'chrono-a',label+': an old removed-conversation action cannot navigate');

    await page.locator('.kg-history-item[data-message-id="c-middle"] [data-history-action="graph"]').click();
    assert.deepEqual(await page.evaluate(()=>knowledgeGraphDisplayedNodes().map(node=>node.id)),['set_operation']);
    await removeConversation('chrono-c');
    assert.equal(await page.evaluate(()=>getKnowledgeGraphQuestionSubject()),null,
      label+': deleting the selected graph\'s conversation invalidates the displayed question source');
    assert.deepEqual(await page.evaluate(()=>knowledgeGraphDisplayedNodes().map(node=>node.id)),[],
      label+': a deleted selected question leaves no purple graph behind');
    await page.locator('#knowledgeGraphHistoryTab').click();
    assert.deepEqual(await order(),['a-early','a-synced-middle','a-tie','a-late']);
    assert.equal(await page.locator('#knowledgeGraphHistoryTab').innerText(),'历史题目 (4)');
    const restored=await page.evaluate(()=>{
      const session=sessions.find(item=>item.id==='chrono-a');
      const index=session.messages.findIndex(message=>message.messageId==='a-late');
      const original=session.messages[index],edited=editedUserMessage(original,original.text);
      edited.messageId=original.messageId;
      // A cloud copy's estimated clock cannot replace the actual first
      // appearance, even when the content has been edited on another device.
      session.messages[index]=mergeCloudMessage({...edited,createdAt:__chronologyBase+1,createdAtEstimated:true},edited);
      session.messages.splice(session.messages.findIndex(message=>message.messageId==='a-early'),1);
      const legacy={id:'old-record-without-clock',messages:[{role:'user',text:'求两个集合的交集'}]};
      const first=questionMessageAppearedAt(legacy,legacy.messages[0],0),now=Date.now;
      let legacyStable;
      try {Date.now=()=>now()+999999999;legacyStable=first===questionMessageAppearedAt(legacy,legacy.messages[0],0);}
      finally {Date.now=now;}
      saveState();sessions=[];currentId=null;
      const loaded=loadState({guest:true});renderAll();
      return {loaded,legacyStable};
    });
    assert.deepEqual(restored,{loaded:true,legacyStable:true},label+': old missing clocks remain stable rather than acquiring render time');
    await openHistory(page);
    assert.deepEqual(await order(),['a-synced-middle','a-tie','a-late'],
      label+': saved first-appearance order survives edits, prior-message deletion, cloud clock recovery and actual save/load');
    assert.deepEqual(modelCalls,[],label+': ordering and deletion require no identification or answer request');
    assert.deepEqual(errors,[],label+': no browser errors');
    console.log('PASS '+label+': global question time order, hidden titles/numbers/time and live conversation deletion');
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
    await page.evaluate(()=>setKnowledgeGraphFilter('函数'));
    await openHistory(page);
    assert.match(await page.locator('#knowledgeGraphHistoryTab').innerText(),/6/);
    const generated='证明对于任意命题 p，p 与 p 的合取和 p 等价。';
    const teaching={category:'命题逻辑',knowledge_points:['逻辑等价'],focus_points:['逻辑等价'],
      prerequisite_points:[],knowledge_path:['逻辑等价'],difficulty:'简单',question_type:'证明题',
      question_graph:{version:1,classifier_revision:'catalog-semantic-v5',classification_status:'semantic',classification_source:'catalog_semantic',needs_review:false,sources:{question:generated,solution:''},nodes:[
        {id:'logic_connectives',evidence:[{source:'question',quote:'合取'}]},
        {id:'logic_equivalence',evidence:[{source:'question',quote:'等价'}]}],edges:[]}};
    await requests[0].fulfill({status:200,contentType:'text/event-stream',body:'event: final\ndata: '+JSON.stringify({
      reply:generated,generated_question:generated,generated_teaching:teaching})+'\n\n'});
    await page.waitForFunction(text=>getCurrent().messages.some(message=>message.generatedQuestion===text),generated);
    assert.equal((await page.evaluate(()=>window.historyReplyPromise)).status,'success','the real answer commit path completes');
    await page.waitForFunction(()=>document.getElementById('knowledgeGraphHistoryTab').textContent.includes('7'));
    assert.deepEqual(await page.evaluate(()=>({mode:knowledgeGraphViewMode,category:knowledgeGraphFilter})),
      {mode:'history',category:'函数'},'an incoming answer preserves independent history mode and the remembered module filter');
    assert.equal(await page.locator('#knowledgeGraphHistoryWrap').isVisible(),true,'the active question-history pane stays open');
    assert.equal(await page.locator(cards).count(),7,'a committed generated question refreshes the aggregate count');
    assert.equal(await page.locator(cards).last().getAttribute('data-session-id'),'history-lower','new questions retain their original conversation identity');
    assert.match(await page.locator(cards).last().locator('.kg-history-preview').innerText(),/p 与 p 的合取和 p 等价/,
      'the generated question follows older questions across all conversations');
    assert.equal(await page.locator('#knowledgeGraphModal .graph-status-pill.current').count(),0,'the history list remains free of current-question decorations');
    assert.equal(requests.length,1,'history refresh does not repeat the model request');
    assert.deepEqual(errors,[],'incoming answer history checks have no browser errors');
    console.log('PASS incoming generated answer: independent history and remembered filter remain selected and the new question appears by first-appearance time');
  } finally {await context.close();}
}

(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.CHROMIUM_EXECUTABLE_PATH}:{})});
  try {for(const width of [1440,390])for(const language of ['zh-CN','en'])await checkCase(browser,width,language);for(const width of [1440,390])await checkModeTransitions(browser,width);for(const width of [1440,390])await checkChronologyAndConversationDeletion(browser,width);await checkReplyRetention(browser);}
  finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
