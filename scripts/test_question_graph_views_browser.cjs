/* Recent and selected-history questions share one cross-module graph model.
 * Account/model/OCR routes are mocked; tests never send paid requests.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const { expandGraphDetails } = require('./knowledge-graph-touch-fixtures.cjs');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const locate = '#knowledgeGraphLocateOriginal';

async function settle(page) {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}
async function openGraph(page, mode) {
  await page.evaluate(async mode => {
    if (document.getElementById('knowledgeGraphModal').classList.contains('hidden')) await openKnowledgeGraph();
    selectKnowledgeGraphDisplayMode(mode);
  }, mode);
  await settle(page);
}
async function openHistory(page) {
  await openGraph(page, 'history');
  await page.locator('#knowledgeGraphHistoryWrap').waitFor({state:'visible'});
}
async function snapshot(page) {
  return page.evaluate(() => {
    const context = getActiveKnowledgeContext(), nodes = knowledgeGraphDisplayedNodes(context);
    const ids = new Map(nodes.map(node => [node.name, node.id]));
    return {
      ids: nodes.map(node => node.id).sort(),
      edges: nodes.flatMap(node => node.prerequisites.filter(name => ids.has(name)).map(name => ids.get(name) + '>' + node.id)).sort(),
      purple: nodes.filter(node => knowledgeGraphNodeState(node.name, context).fill === '#5b21b6').map(node => node.id).sort(),
      categories: [...new Set(nodes.map(node => node.category))].sort()
    };
  });
}
async function assertLiveGraph(page, expected, label) {
  await settle(page);
  const drawn = await page.evaluate(() => {
    const canvas = document.getElementById('knowledgeGraphCanvas');
    const nodes = [...canvas.querySelectorAll('.kg-mobile-node,.kg-node-group')];
    return {
      ids:nodes.map(node => node.dataset.knowledgeNodeId).sort(),
      purple:nodes.filter(node => node.classList.contains('kg-mobile-node') ? node.style.backgroundColor === 'rgb(91, 33, 182)'
        : node.querySelector('rect')?.getAttribute('fill') === '#5b21b6').map(node => node.dataset.knowledgeNodeId).sort(),
      edges:canvas.querySelectorAll('.kg-mobile-edge,.kg-edge').length
    };
  });
  assert.deepEqual(drawn.ids,expected.ids,label+': real graph renders every involved cross-module node');
  assert.deepEqual(drawn.purple,expected.purple,label+': real graph retains purple question concepts');
  assert.equal(drawn.edges,expected.edges.length,label+': rendered links match the real knowledge relationships');
}
async function assertExports(page, expected, label) {
  const result = await page.evaluate(async () => {
    const target = buildKnowledgeGraphImageCopyTarget();
    if (!target) throw Error('Focused question must produce a copy target');
    const elements = [...target.querySelectorAll('.kg-mobile-node,.kg-node-group')];
    const clone = {
      ids: elements.map(node => node.dataset.knowledgeNodeId).sort(),
      purple: elements.filter(node => node.classList.contains('kg-mobile-node')
        ? node.style.backgroundColor === 'rgb(91, 33, 182)' : node.querySelector('rect')?.getAttribute('fill') === '#5b21b6')
        .map(node => node.dataset.knowledgeNodeId).sort()
    };
    target.remove();
    const fills = [], original = CanvasRenderingContext2D.prototype.fill;
    CanvasRenderingContext2D.prototype.fill = function (...args) { fills.push(this.fillStyle); return original.apply(this, args); };
    try {
      const blob = await renderKnowledgeGraphOffscreenPngBlob();
      return { clone, purpleFills: fills.filter(value => value === '#5b21b6').length, bytes: blob.size, type: blob.type };
    } finally { CanvasRenderingContext2D.prototype.fill = original; }
  });
  assert.deepEqual(result.clone.ids, expected.ids, label + ': copied graph has the same cross-module nodes');
  assert.deepEqual(result.clone.purple, expected.purple, label + ': copied graph preserves purple question concepts');
  assert.equal(result.purpleFills, expected.purple.length, label + ': real PNG painter preserves every purple concept');
  assert.equal(result.type, 'image/png'); assert.ok(result.bytes > 1000);
  assert.equal(await page.locator('#knowledgeGraphDetail .graph-status-pill.current').count(), 0,
    label + ': redundant related-question detail pill is absent');
  assert.equal(await page.locator('#knowledgeGraphDetail').getByText(/^(本题相关|Related to this question|Related to the selected question)$/).count(), 0);
}
async function assertLocatePlacement(page, label) {
  await settle(page);
  const layout = await page.evaluate(() => {
    const title = document.getElementById('knowledgeGraphDetailTitle');
    const button = document.getElementById('knowledgeGraphLocateOriginal');
    const range = document.createRange();
    range.selectNodeContents(title);
    const text = range.getBoundingClientRect(), action = button.getBoundingClientRect();
    const pane = title.closest('.knowledge-graph-side').getBoundingClientRect();
    return { text:{left:text.left,right:text.right,bottom:text.bottom,center:text.top+text.height/2},
      action:{left:action.left,right:action.right,top:action.top,center:action.top+action.height/2},
      pane:{left:pane.left,right:pane.right} };
  });
  if (page.viewportSize().width <= 760) {
    assert.ok(layout.action.top >= layout.text.bottom, label + ': the sheet places the source action below the title');
  } else {
    assert.ok(layout.action.left >= layout.text.right + 4,
      label + ': Go to original question is to the right of the concept title without overlap');
    assert.ok(Math.abs(layout.text.center - layout.action.center) <= 3,
      label + ': concept title and source action share one vertically centered header row');
  }
  assert.ok(layout.text.left >= layout.pane.left && layout.action.right <= layout.pane.right - 4,
    label + ': the title and source action fit inside the detail pane');
}
async function newPage(browser, width, language) {
  const context = await browser.newContext({viewport:{width,height:900},serviceWorkers:'block',
    ...(width <= 760 ? {isMobile:true,hasTouch:true} : {})});
  const page = await context.newPage(), errors = [], modelCalls = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/auth/me', route => route.fulfill({contentType:'application/json',body:'{"configured":true,"authenticated":false}'}));
  await page.route(/\/(?:chat|ocr(?:\/[^?]*)?|graph\/[^?]*|analyze-questions|classify|conversation\/title)(?:\?|$)/, route => {
    modelCalls.push(new URL(route.request().url()).pathname); return route.abort();
  });
  await page.goto(baseURL, {waitUntil:'networkidle'});
  await page.waitForFunction(() => !accountVerificationOperation);
  await page.evaluate(async language => {
    DMateI18n.setLanguage(language,false);
    await ensureKnowledgeGraphData();
    window.__graphTeachingFixture = (question, concepts, relationships = []) => {
      const points = concepts.map(value => findKnowledgeGraphNodeById(Array.isArray(value) ? value[0] : value).name);
      return {category:findKnowledgeGraphNodeByName(points[0])?.category || '待识别',
        knowledge_points:points,focus_points:points.slice(0,2),prerequisite_points:[],knowledge_path:[],
        question_graph:{version:1,classifier_revision:'catalog-semantic-v5',classification_status:'semantic',classification_source:'catalog_semantic',needs_review:false,sources:{question,solution:''},
          nodes:concepts.map(value => ({id:Array.isArray(value) ? value[0] : value,
            evidence:[{source:'question',quote:Array.isArray(value) ? value[1] : findKnowledgeGraphNodeById(value).name}]})),
          edges:relationships.map(([from,to,quote]) => ({from,to,evidence:[{source:'question',quote}]}))}};
    };
    window.__bindQuestionGraphFixtures = () => {
      for (const session of sessions) for (const item of getConversationQuestionHistory(session)) {
        const message = session.messages[item.index];
        const teaching = item.role === 'ai' ? message.generatedTeaching : message.questionTeaching;
        if (teaching?.question_graph) {
          teaching.question_graph.sources.question = item.text;
          const reference={sessionId:String(session.id),messageId:message.messageId||'',index:item.index,
            fingerprint:wrongQuestionFingerprint(item.text)};
          teaching.question_graph.sources.solution=knowledgeGraphQuestionContext(session,item,reference).reviewSolutionText||'';
        }
      }
    };
  }, language);
  return {context,page,errors,modelCalls};
}
async function seedCrossModule(page) {
  return page.evaluate(() => {
    const question = '先做集合运算，再依据集合运算的结果求复合函数，并依据集合运算的结果用容斥原理计数';
    const teaching = __graphTeachingFixture(question,['set_operation','function_composition','count_inclusion'],[
      ['set_operation','function_composition','依据集合运算的结果求复合函数'],
      ['set_operation','count_inclusion','依据集合运算的结果用容斥原理计数']]);
    const signed = (body,id) => ({document:{body_text:body,graphs:[]},question_text:body+'\n[canonical '+id+']',
      rendered_question_text:'【题目文字】\n'+body,source_sha256:'a'.repeat(64),document_sha256:'b'.repeat(64),
      confirmation_token:'fixture-token-'+id,revision:1,request_id:id,profile:'editable-v1'});
    const source = id => {
      const contexts = [signed(question,id+'-one'),signed('第二张图给出补充条件',id+'-two')];
      return {messageId:id,role:'user',source:'ocr',ocrIsQuestion:true,
        text:contexts.map((item,index)=>`【图片 ${index+1}】\n${item.rendered_question_text}`).join('\n\n')+'\n\n【我的要求】\n保留原定义',
        apiText:contexts.map((item,index)=>`【图片 ${index+1}】\n${item.question_text}`).join('\n\n'),semanticContexts:contexts,
        ocrGroup:{id:'confirmed-'+id,groupId:id,members:[{requestId:id+'-one',isQuestion:true},{requestId:id+'-two',isQuestion:false}]},
        questionTeaching:JSON.parse(JSON.stringify(teaching))};
    };
    const unrelated = __graphTeachingFixture('用数学归纳法证明自然数求和公式',['proof_induction']);
    sessions = [
      {id:'past-conversation',name:'历史集合与函数',nameSource:'user',deletedMessageIds:{},learningQuestion:null,teaching:unrelated,messages:[
        source('past-group'),{role:'ai',messageId:'past-explanation',text:'已说明集合与函数的条件',targetQuestionMessageId:'past-group'},
        {role:'user',messageId:'past-later',text:'用数学归纳法证明自然数求和公式',manualIsQuestion:true,questionTeaching:unrelated}]},
      {id:'current-conversation',name:'当前集合与函数',nameSource:'user',deletedMessageIds:{},learningQuestion:null,teaching,messages:[
        source('current-group'),{role:'ai',messageId:'current-explanation',text:'逐项核对定义',targetQuestionMessageId:'current-group'},
        {role:'user',messageId:'current-chat',text:'继续解释',manualIsQuestion:false}]}
    ];
    sessions.forEach((session, sessionIndex) => {
      session.createdAt = 1700000000000 + sessionIndex * 1000;
      session.messages.forEach((message, messageIndex) => {
        message.createdAt = session.createdAt + messageIndex + 1;
      });
    });
    currentId='current-conversation'; deletedSessionIds=Object.create(null); __bindQuestionGraphFixtures(); renderAll();
    return JSON.stringify(sessions);
  });
}
async function checkView(browser, width, language) {
  const label=width+'/'+language, {context,page,errors,modelCalls}=await newPage(browser,width,language);
  try {
    const original=await seedCrossModule(page);
    await openGraph(page,'focus');
    const recent=await snapshot(page);
    assert.deepEqual(recent.ids,['count_inclusion','function_composition','set_operation'],
      label+': exactly the three evidenced concepts are shown without adding a course bridge');
    assert.equal(recent.categories.length >= 3,true,label+': one question spans multiple modules without a category cutoff');
    assert.deepEqual(recent.edges,['set_operation>count_inclusion','set_operation>function_composition'],
      label+': the graph uses only the dependencies recorded for this actual question');
    for(const id of ['function_mapping','relation_cartesian','relation_equivalence','relation_closure','graph_tree'])
      assert.equal(recent.ids.includes(id),false,label+': an unrelated module branch is not dumped into the question graph');
    assert.deepEqual(recent.purple,['count_inclusion','function_composition','set_operation'],label+': all involved question concepts remain purple');
    await assertLiveGraph(page,recent,label+'/recent');
    await assertExports(page,recent,label+'/recent');
    await expandGraphDetails(page);
    assert.equal(await page.locator(locate).isVisible(),true,label+': recent details provide Go to original question');
    await assertLocatePlacement(page,label+'/recent');
    assert.equal(await page.locator('#knowledgeGraphHistoryTab').isVisible(),false);
    await page.locator(locate).click();
    await page.locator('#chat [data-message-index="0"].history-locate-flash').waitFor();
    assert.equal(await page.evaluate(()=>currentId),'current-conversation');

    await page.evaluate(()=>setKnowledgeGraphFilter('集合与关系'));
    await openHistory(page);
    await page.locator('.kg-history-item[data-message-id="past-group"] [data-history-action="graph"]').click();
    await page.waitForFunction(()=>knowledgeGraphScope==='history');
    const historic=await snapshot(page);
    assert.deepEqual(historic,recent,label+': selected history question uses exactly the recent graph presentation');
    assert.equal(await page.evaluate(()=>currentId),'current-conversation',label+': historical graph viewing leaves the current conversation intact');
    assert.equal(await page.evaluate(()=>document.getElementById('knowledgeGraphModal').dataset.graphView),'history',label+': historical question graph uses its independent cross-module presentation');
    await assertLiveGraph(page,historic,label+'/history');
    await assertExports(page,historic,label+'/history');
    assert.equal(await page.locator(locate).isVisible(),false,label+': historical details omit the recent-only source locator');
    assert.equal(await page.evaluate(()=>knowledgeGraphViewMode),'history',label+': a selected historical graph stays in the independent history mode');
    assert.equal(await page.locator('#knowledgeGraphSideTabs').isVisible(),true,label+': historical graph keeps the detail/history sidebar tabs');
    assert.equal(await page.evaluate(()=>JSON.stringify(sessions)),original,label+': graph/export preserve grouped OCR tokens, member flags, text and metadata');
    assert.equal(await page.locator('#knowledgeGraphDetail .graph-detail-term[data-knowledge-node-id="relation_cartesian"]').count(),0,
      label+': details do not leak a static course successor into the question graph');
    await expandGraphDetails(page);
    await page.locator('#knowledgeGraphDetail .graph-detail-term[data-knowledge-node-id="function_composition"]').click();
    await settle(page);
    const plain=await snapshot(page);
    assert.deepEqual(plain.ids,await page.evaluate(()=>knowledgeGraphVisibleNodes('函数').map(node=>node.id).sort()),
      label+': relation navigation leaves the focused canvas and displays the complete target module');
    assert.deepEqual(plain.purple,[],label+': full-module navigation removes the historical question highlights');
    assert.equal(await page.evaluate(()=>knowledgeGraphScope),'current',label+': relation navigation clears selected-history scope');
    assert.equal(await page.evaluate(()=>knowledgeGraphQuestionReference),null,label+': relation navigation clears the subject reference');
    assert.equal(await page.evaluate(()=>document.getElementById('knowledgeGraphModal').dataset.graphView),'full');
    assert.equal(await page.evaluate(()=>knowledgeGraphSelectedNodeId),'function_composition');
    await openHistory(page);
    await page.locator('.kg-history-item[data-message-id="past-group"] [data-history-action="graph"]').click();
    await page.evaluate(()=>{
      const session=sessions.find(session=>session.id==='past-conversation');
      session.messages.push(session.messages.shift()); renderKnowledgeGraph();
    });
    await openHistory(page);
    await page.locator('.kg-history-item[data-message-id="past-group"] [data-history-action="locate"]').click();
    await page.locator('#chat [data-message-index="2"].history-locate-flash').waitFor();
    assert.equal(await page.evaluate(()=>currentId),'past-conversation',label+': history-card locator switches to its source conversation');
    assert.match(await page.locator('#chat [data-message-index="2"]').innerText(),/复合函数/);
    const group=await page.evaluate(()=>getCurrent().messages.find(message=>message.messageId==='past-group').ocrGroup);
    assert.deepEqual(group.members,[{requestId:'past-group-one',isQuestion:true},{requestId:'past-group-two',isQuestion:false}],label+': locating grouped OCR preserves question/material identity');
    await openGraph(page,'full');
    assert.equal(await page.evaluate(()=>knowledgeGraphScope),'current',label+': All knowledge clears the selected-history scope');
    assert.deepEqual((await snapshot(page)).purple,[],label+': ordinary All knowledge stays neutral');
    assert.equal(await page.locator(locate).isVisible(),false,label+': ordinary All knowledge has no misleading question locator');
    assert.deepEqual(modelCalls,[],label+': browsing and locating never classify or recognize again');
    assert.deepEqual(errors,[],label+': no browser errors');
    console.log('PASS '+label+': recent/history cross-module model and purple exports match, related pill removed, grouped sources locate safely');
  } finally {await context.close();}
}
async function checkReferenceGuards(browser) {
  const {context,page,errors,modelCalls}=await newPage(browser,1440,'zh-CN');
  try {
    await page.evaluate(()=>{
      const a='用逻辑等价证明命题 p 的双重否定与 p 等价', b='用集合运算求集合 A 的补集';
      const ta=__graphTeachingFixture(a,['logic_equivalence']);
      const tb=__graphTeachingFixture(b,['set_operation']);
      sessions=[{id:'pointer',name:'指代题目',nameSource:'user',teaching:tb,learningQuestion:null,deletedMessageIds:{},messages:[
        {messageId:'pointer-a',role:'user',text:a,manualIsQuestion:true,questionTeaching:ta},
        {messageId:'pointer-b',role:'user',text:b,manualIsQuestion:true,questionTeaching:tb},
        {messageId:'pointer-nav',role:'user',text:'上一道题再讲一下',manualIsQuestion:false,targetQuestionFingerprint:wrongQuestionFingerprint(a)}]}];
      currentId='pointer';renderAll();
    });
    await openGraph(page,'focus');
    assert.deepEqual((await snapshot(page)).purple,['logic_equivalence'],'recent graph follows the active previous-question pointer');
    await page.locator(locate).click();
    await page.locator('#chat [data-message-index="0"].history-locate-flash').waitFor();
    await openHistory(page);
    const stale=await page.locator('.kg-history-item[data-message-id="pointer-a"] [data-history-action="locate"]').elementHandle();
    await page.locator('.kg-history-item[data-message-id="pointer-a"] [data-history-action="graph"]').click();
    await page.evaluate(()=>{getCurrent().messages[0].text='改成另一个不同的命题问题';renderKnowledgeGraph();});
    await stale.evaluate(button=>button.click());
    assert.equal(await page.locator('#knowledgeGraphModal').isVisible(),true,'edited selected question invalidates its captured locator');
    assert.equal((await page.locator('#knowledgeGraphCanvas').innerText()).trim(),'无','stale historical subject becomes empty instead of borrowing the latest question');
    assert.equal(await page.locator(locate).isVisible(),false);
    await page.evaluate(()=>{getCurrent().messages[0].text='用逻辑等价证明命题 p 的双重否定与 p 等价';});
    await openHistory(page);
    const deleted=await page.locator('.kg-history-item[data-message-id="pointer-a"] [data-history-action="locate"]').elementHandle();
    await page.locator('.kg-history-item[data-message-id="pointer-a"] [data-history-action="graph"]').click();
    await page.evaluate(()=>{window.__removedGraphQuestion=getCurrent().messages.shift();renderKnowledgeGraph();});
    await deleted.evaluate(button=>button.click());
    assert.equal(await page.locator('#knowledgeGraphModal').isVisible(),true,'deleted selected question invalidates its locator');
    assert.equal((await page.locator('#knowledgeGraphCanvas').innerText()).trim(),'无','deleted historical subject becomes empty without falling back to the latest question');
    assert.equal(await page.locator(locate).isVisible(),false);
    await page.evaluate(()=>getCurrent().messages.unshift(window.__removedGraphQuestion));
    await openHistory(page);
    const oldOwner=await page.locator('.kg-history-item[data-message-id="pointer-a"] [data-history-action="locate"]').elementHandle();
    await page.locator('.kg-history-item[data-message-id="pointer-a"] [data-history-action="graph"]').click();
    await page.evaluate(()=>bumpCloudSyncContext());
    await oldOwner.evaluate(button=>button.click());
    assert.equal(await page.locator('#knowledgeGraphModal').isVisible(),true,'old owner context cannot close graph or switch source');
    await page.evaluate(()=>renderKnowledgeGraph());
    assert.equal((await page.locator('#knowledgeGraphCanvas').innerText()).trim(),'无');
    await page.evaluate(()=>{
      const teaching=__graphTeachingFixture('分别说明集合运算与逻辑等价的定义',['set_operation','logic_equivalence']);
      sessions=[{id:'independent-concepts',name:'不同知识分支',nameSource:'user',teaching,learningQuestion:null,deletedMessageIds:{},
        messages:[{messageId:'independent-question',role:'user',text:'分别说明集合运算与逻辑等价的定义',manualIsQuestion:true,questionTeaching:teaching}]}];
      currentId='independent-concepts';renderAll();
    });
    await openGraph(page,'focus');
    const independent=await snapshot(page);
    const adjacent=new Map(independent.ids.map(id=>[id,[]]));
    for(const edge of independent.edges){const [a,b]=edge.split('>');adjacent.get(a).push(b);adjacent.get(b).push(a);}
    const reachable=new Set(['set_operation']),pending=['set_operation'];
    while(pending.length)for(const id of adjacent.get(pending.shift()))if(!reachable.has(id)){reachable.add(id);pending.push(id);}
    assert.ok(independent.ids.includes('logic_equivalence'),'independent involved concepts are still shown');
    assert.equal(reachable.has('logic_equivalence'),false,'unrelated course branches are not forced together with invented relationships');
    await assertLiveGraph(page,independent,'independent concepts');
    assert.deepEqual(modelCalls,[]); assert.deepEqual(errors,[]);
    console.log('PASS question references: previous-question pointer, independent involved concepts and stale edit/owner guards');
  } finally {await context.close();}
}
async function checkGeneratedQuestionSources(browser) {
  const {context,page,errors,modelCalls}=await newPage(browser,1440,'zh-CN');
  const reviews=[];
  try {
    await page.route('**/analyze-questions',route=>{
      reviews.push(route.request().postDataJSON());
      return route.fulfill({contentType:'application/json',body:'{"results":[]}'});
    });
    await page.evaluate(()=>{
      const question='先做集合运算，再处理函数 f 与 g 的复合';
      const answer='依据集合运算的结果计算复合函数';
      const teaching=__graphTeachingFixture(question,['set_operation']);
      teaching.question_graph.sources.solution=answer;
      teaching.question_graph.nodes.push({id:'function_composition',evidence:[{source:'solution',quote:'复合函数'}]});
      teaching.question_graph.edges.push({from:'set_operation',to:'function_composition',evidence:[{source:'solution',quote:answer}]});
      sessions=[{id:'generated-question',name:'生成题目',nameSource:'user',teaching,learningQuestion:null,deletedMessageIds:{},messages:[
        {messageId:'generation-request',role:'user',text:'出一道集合运算与函数复合的题目',manualIsQuestion:false},
        {messageId:'generated-source',role:'ai',text:'【题目】\n'+question,generatedExercise:true,generatedQuestion:question,
          generatedAnswer:answer,generatedTeaching:teaching}]}];
      currentId='generated-question';renderAll();
    });
    await openGraph(page,'focus');
    const expected={ids:['function_composition','set_operation'],purple:['function_composition','set_operation'],
      edges:['set_operation>function_composition']};
    const graph=await snapshot(page);
    assert.deepEqual(graph.ids,expected.ids,'a generated question can use its own saved answer as exact evidence');
    assert.deepEqual(graph.purple,expected.purple);assert.deepEqual(graph.edges,expected.edges);
    await assertExports(page,expected,'generated question');
    for(const english of [false,true]) {
      const source=await page.evaluate(english=>{
        const message=getCurrent().messages.find(message=>message.messageId==='generated-source');
        const explanation='逐一代入定义，核对函数的复合顺序';
        message.text=(english?'[Question]\n':'【题目】\n')+message.generatedQuestion
          +(english?'\n\n[Answer]\n':'\n\n【答案】\n')+message.generatedAnswer
          +(english?'\n\n[Explanation]\n\n':'\n\n【解析】\n\n')+explanation
          +(english?'\n\n[Topics]\n\n':'\n\n【涉及知识点】\n\n')+'容斥原理';
        message.generatedTeaching.question_graph.sources.solution=message.generatedAnswer+'\n\n'+explanation;
        renderKnowledgeGraph();
        return {actual:getKnowledgeGraphQuestionSubject().context.reviewSolutionText,
          expected:message.generatedAnswer+'\n\n'+explanation};
      },english);
      assert.equal(source.actual,source.expected,'generated registered sources include only the actual hidden answer and visible explanation, excluding the topics footer');
      assert.deepEqual((await snapshot(page)).ids,expected.ids,'a topics footer cannot contribute another involved concept');
    }
    assert.equal(reviews.length,0,'a correctly bound generated answer and explanation reuse the registered graph');
    await page.evaluate(()=>{
      const message=getCurrent().messages.find(message=>message.messageId==='generated-source');
      message.text='【题目】\n'+message.generatedQuestion;
      message.generatedAnswer='答案已修改，旧解答不再存在';
      renderKnowledgeGraph();
    });
    const changed=await snapshot(page);
    assert.deepEqual(changed.ids,['set_operation'],'replacing an answer keeps question facts but not its old solution-only method');
    assert.deepEqual(changed.purple,changed.ids);assert.deepEqual(changed.edges,[]);
    assert.equal(reviews.length,0,'changing an answer does not turn graph viewing into another recognition request');
    assert.deepEqual(modelCalls,[]);assert.deepEqual(errors,[]);
    console.log('PASS generated question sources: own answer supports relations, replaced answers cannot validate stale evidence');
  } finally {await context.close();}
}

async function checkQuestionSpecificTopology(browser, width) {
  const {context,page,errors,modelCalls}=await newPage(browser,width,'zh-CN');
  const cases=[
    {text:'进行集合运算，求 A 与 B 的交集',nodes:['set_operation'],edges:[]},
    {text:'分别解释函数与映射和复合函数，不建立推导关系',nodes:['function_mapping','function_composition'],edges:[]},
    {text:'依据函数与映射的定义构造复合函数',nodes:['function_mapping','function_composition'],edges:[['function_mapping','function_composition']]},
    {text:'先计算复合函数，再依据计算结果判断函数与映射的性质',nodes:['function_mapping','function_composition'],edges:[['function_composition','function_mapping']]},
    {text:'先用真值表确定真值，再据此证明逻辑等价',nodes:['logic_truth_table','logic_equivalence'],edges:[['logic_truth_table','logic_equivalence']]},
    {text:'利用量词规则把公式转换成前束范式',nodes:['predicate_quantifier','predicate_prenex'],edges:[['predicate_quantifier','predicate_prenex']]},
    {text:'先用数学归纳法证明计数公式，再用该公式计算排列与组合',nodes:['proof_induction','count_perm_comb'],edges:[['proof_induction','count_perm_comb']]},
    {text:'根据同余与模运算的结果求解中国剩余定理中的方程组',nodes:['number_congruence','number_inverse_crt'],edges:[['number_congruence','number_inverse_crt']]},
    {text:'依据带权图中各边的权重构造最小生成树',nodes:['graph_weighted','tree_mst'],edges:[['graph_weighted','tree_mst']]},
    {text:'分别分析群与子群以及环与域，不作相互推导',nodes:['algebra_group','algebra_ring_field'],edges:[]},
    {text:'根据初始条件求解线性齐次递推',nodes:['recurrence_initial','recurrence_homogeneous'],edges:[['recurrence_initial','recurrence_homogeneous']]}
  ];
  try {
    for (const [index,item] of cases.entries()) {
      await page.evaluate(item=>{
        const teaching=__graphTeachingFixture(item.text,item.nodes,item.edges.map(([from,to])=>[from,to,item.text]));
        sessions=[{id:'specific-'+item.index,name:'题目独立关系',nameSource:'user',teaching,learningQuestion:null,deletedMessageIds:{},
          messages:[{role:'user',messageId:'specific-source',text:item.text,manualIsQuestion:true,questionTeaching:teaching}]}];
        currentId='specific-'+item.index;renderAll();
      },{...item,index});
      await openGraph(page,'focus');
      const graph=await snapshot(page), expected={ids:[...item.nodes].sort(),purple:[...item.nodes].sort(),
        edges:item.edges.map(([from,to])=>from+'>'+to).sort()};
      assert.deepEqual(graph.ids,expected.ids,width+'/case'+index+': only this question’s evidenced nodes appear');
      assert.deepEqual(graph.purple,expected.purple,width+'/case'+index+': every involved module is purple');
      assert.deepEqual(graph.edges,expected.edges,width+'/case'+index+': dependencies belong to this question rather than the course');
      await assertLiveGraph(page,expected,width+'/case'+index);
      for (const id of item.nodes) {
        await page.evaluate(id=>selectKnowledgeGraphNode(id),id);
        const relations=await page.locator('#knowledgeGraphDetail .graph-detail-field').evaluateAll(fields=>fields.slice(0,2)
          .map(field=>[...field.querySelectorAll('[data-knowledge-node-id]')].map(node=>node.dataset.knowledgeNodeId).sort()));
        assert.deepEqual(relations,[item.edges.filter(([,to])=>to===id).map(([from])=>from).sort(),
          item.edges.filter(([from])=>from===id).map(([,to])=>to).sort()],
          width+'/case'+index+'/'+id+': detail prerequisites/successors match only this question’s directed edges');
      }
      if(index===3) await assertExports(page,expected,width+'/reverse dependency');
    }
    assert.deepEqual(modelCalls,[]);assert.deepEqual(errors,[]);
    console.log('PASS '+width+': '+cases.length+' question-specific graphs across logic, predicates, proofs, sets, functions, counting, number theory, recurrence, graphs and algebra');
  } finally {await context.close();}
}

async function checkRegisteredLegacySnapshot(browser) {
  const {context,page,errors,modelCalls}=await newPage(browser,1440,'zh-CN');
  try {
    await page.evaluate(()=>{
      const text='从若干对象中无序选取一组，有多少种不同选法';
      const old={category:'计数与组合',difficulty:'简单',knowledge_points:['排列与组合'],focus_points:['排列与组合'],
        prerequisite_points:['命题推理'],knowledge_path:['集合运算','函数与映射'],
        registered_snapshot:{version:1,question:text,difficulty:'简单',points:['排列与组合']}};
      sessions=[{id:'legacy',name:'旧题目',nameSource:'user',teaching:old,learningQuestion:null,deletedMessageIds:{},
        messages:[{messageId:'legacy-question',role:'user',text,manualIsQuestion:true,questionTeaching:old}]}];
      currentId='legacy';renderAll();
    });
    await openGraph(page,'focus');
    const expected={ids:['count_perm_comb'],purple:['count_perm_comb'],edges:[],categories:['计数与组合']};
    assert.deepEqual(await snapshot(page),expected,'already recognized implicit knowledge displays without inferring it again');
    await assertLiveGraph(page,expected,'registered legacy');
    await openGraph(page,'full');await openGraph(page,'focus');
    await page.evaluate(()=>{closeKnowledgeGraph();saveState();if(!loadState({guest:true}))throw Error('No saved snapshot');renderAll();});
    await openGraph(page,'focus');
    assert.deepEqual(await snapshot(page),expected,'the registered snapshot survives actual persistence without course-path expansion');
    await page.evaluate(()=>{getCurrent().messages[0].text='依据复合函数的计算结果判断函数与映射的性质';renderKnowledgeGraph();});
    assert.deepEqual((await snapshot(page)).ids,[],'edited full questions cannot reuse an old explicitly bound recognition');
    await page.evaluate(()=>{
      const message=getCurrent().messages[0];
      message.questionTeaching=__graphTeachingFixture(message.text,['function_composition','function_mapping'],
        [['function_composition','function_mapping',message.text]]);
      renderKnowledgeGraph();
    });
    assert.deepEqual((await snapshot(page)).ids,['function_composition','function_mapping']);
    assert.deepEqual((await snapshot(page)).edges,['function_composition>function_mapping']);
    assert.deepEqual(modelCalls,[]);assert.deepEqual(errors,[]);
    console.log('PASS registered legacy graph: implicit points, persistence and complete-question edit guards require no view-time recognition');
  } finally {await context.close();}
}

async function checkLongQuestionIdentity(browser) {
  const {context,page,errors,modelCalls}=await newPage(browser,1440,'zh-CN');
  const reviews=[];
  try {
    await page.route('**/analyze-questions',route=>{
      reviews.push(route.request().postDataJSON());
      return route.fulfill({contentType:'application/json',body:'{"results":[]}'});
    });
    const collision=await page.evaluate(()=>{
      const prefix='这是较长题干的公共背景条件，所有已给出的约束都需要保留以便完整核对。'.repeat(70);
      const a=prefix+'本题最后要求进行集合运算';
      const b=prefix+'本题最后要求求出复合函数';
      const solution='依据集合运算的结果，运用逻辑等价得到结论';
      const ta=__graphTeachingFixture(a,['set_operation']);
      const tb=__graphTeachingFixture(b,['function_composition']);
      for (const [teaching,core] of [[ta,'set_operation'],[tb,'function_composition']]) {
        teaching.question_graph.sources.solution=solution;
        teaching.question_graph.nodes.push({id:'logic_equivalence',evidence:[{source:'solution',quote:'逻辑等价'}]});
        teaching.question_graph.edges.push({from:core,to:'logic_equivalence',evidence:[{source:'solution',quote:solution}]});
      }
      sessions=[{id:'long-identity',name:'长题干独立身份',nameSource:'user',teaching:tb,learningQuestion:null,deletedMessageIds:{},messages:[
        {messageId:'long-a',role:'user',text:a,manualIsQuestion:true,questionTeaching:ta},
        {messageId:'long-b',role:'user',text:b,manualIsQuestion:true,questionTeaching:tb},
        {messageId:'long-solution',role:'ai',text:solution,targetQuestionMessageId:'long-a',
          targetQuestionFingerprint:wrongQuestionFingerprint(a)}]}];
      currentId='long-identity';renderAll();
      return {prefixLength:prefix.length,sameFingerprint:wrongQuestionFingerprint(a)===wrongQuestionFingerprint(b)};
    });
    assert.ok(collision.prefixLength>1600,'the fixtures differ only after the old fingerprint truncation boundary');
    assert.equal(collision.sameFingerprint,true,'the old legacy fingerprint actually collides for these distinct questions');
    const restored=await page.evaluate(()=>{
      saveState();
      const loaded=loadState({guest:true});
      return {loaded,target:getCurrent().messages.find(message=>message.messageId==='long-solution')?.targetQuestionMessageId};
    });
    assert.equal(restored.loaded,true,'the source-identity fixture survives an actual client-state save/load');
    assert.equal(restored.target,'long-a','client-state normalization preserves the stable answer target');
    await openGraph(page,'focus');
    assert.equal(await page.evaluate(()=>getKnowledgeGraphQuestionSubject().reference.messageId),'long-b',
      'the latest exact question is active despite its fingerprint matching the earlier question');
    const latest=await snapshot(page);
    assert.deepEqual(latest.ids,['function_composition'],'question facts remain visible but another question’s answer cannot contribute its method');
    assert.deepEqual(latest.purple,latest.ids);assert.deepEqual(latest.edges,[]);
    await openHistory(page);
    assert.equal(await page.locator('.kg-history-item').count(),2,'distinct full questions with the same long prefix both remain in history');
    for (const id of ['long-a','long-b']) assert.equal(await page.locator('.kg-history-item[data-message-id="'+id+'"]').count(),1);
    await page.locator('.kg-history-item[data-message-id="long-a"] [data-history-action="graph"]').click();
    const first=await snapshot(page);
    assert.deepEqual(first.ids,['logic_equivalence','set_operation'],'the actual stable target alone may use its corresponding solution');
    assert.deepEqual(first.purple,first.ids);assert.deepEqual(first.edges,['set_operation>logic_equivalence']);
    assert.equal(await page.evaluate(()=>getKnowledgeGraphQuestionSubject().context.solutionText),
      '依据集合运算的结果，运用逻辑等价得到结论');
    await page.evaluate(()=>{
      delete getCurrent().messages.find(message=>message.messageId==='long-solution').targetQuestionMessageId;
      renderKnowledgeGraph();
    });
    assert.deepEqual((await snapshot(page)).ids,['set_operation'],
      'an ambiguous legacy fingerprint cannot add the old solution method to the earlier question');
    await openHistory(page);
    await page.locator('.kg-history-item[data-message-id="long-b"] [data-history-action="graph"]').click();
    assert.deepEqual((await snapshot(page)).ids,['function_composition'],
      'the ambiguous legacy fingerprint cannot add another question’s method to the later question');
    assert.equal(await page.evaluate(()=>getKnowledgeGraphQuestionSubject().context.solutionText),'');
    const mathCollision=await page.evaluate(()=>{
      const a='逻辑等价：判断 p∧(q∨r)',b='逻辑等价：判断 (p∧q)∨r';
      const ta=__graphTeachingFixture(a,['logic_equivalence']),tb=__graphTeachingFixture(b,['logic_equivalence']);
      sessions=[{id:'symbol-identity',name:'数学符号独立身份',nameSource:'user',teaching:tb,learningQuestion:null,deletedMessageIds:{},messages:[
        {messageId:'intersection-question',role:'user',text:a,manualIsQuestion:true,questionTeaching:ta},
        {messageId:'union-question',role:'user',text:b,manualIsQuestion:true,questionTeaching:tb}]}];
      currentId='symbol-identity';renderAll();
      return wrongQuestionFingerprint(a)===wrongQuestionFingerprint(b);
    });
    assert.equal(mathCollision,true,'the old fingerprint also removes the mathematically significant grouping parentheses');
    await openHistory(page);
    assert.equal(await page.locator('.kg-history-item').count(),2,'different mathematical groupings do not collapse distinct exact questions');
    assert.equal(reviews.length,0,'unattested and ambiguous answer sources never cause a graph-view recognition request');
    assert.deepEqual(modelCalls,[]);assert.deepEqual(errors,[]);
    console.log('PASS question identity: long-prefix and mathematical-grouping collisions preserve history, active subject and stable answer ownership');
  } finally {await context.close();}
}

async function checkEqualSizeCache(browser) {
  const {context,page,errors,modelCalls}=await newPage(browser,1440,'zh-CN');
  try {
    await page.evaluate(async()=>{
      await ensureKnowledgeGraphData();
      const only=new Set(['set_operation','function_mapping']);
      knowledgeGraphData={...knowledgeGraphData,nodes:knowledgeGraphData.nodes.filter(node=>only.has(node.id))};
      const a='依据集合运算的结果判断函数与映射的性质';
      const b='依据函数与映射的结果进行集合运算';
      const ta=__graphTeachingFixture(a,['set_operation','function_mapping'],[['set_operation','function_mapping',a]]);
      const tb=__graphTeachingFixture(b,['set_operation','function_mapping'],[['function_mapping','set_operation',b]]);
      sessions=[{id:'cache',name:'缓存题目',nameSource:'user',learningQuestion:null,teaching:tb,deletedMessageIds:{},messages:[
        {messageId:'cache-a',role:'user',text:a,manualIsQuestion:true,questionTeaching:ta},
        {messageId:'cache-b',role:'user',text:b,manualIsQuestion:true,questionTeaching:tb}]}];
      currentId='cache';renderAll();
    });
    const read=async id=>{
      await openHistory(page);
      await page.locator('.kg-history-item[data-message-id="'+id+'"] [data-history-action="graph"]').click();
      return page.evaluate(async()=>{
        const blob=await prepareKnowledgeGraphPng();
        const bytes=await crypto.subtle.digest('SHA-256',await blob.arrayBuffer());
        return {key:knowledgeGraphCopyKey(),ids:knowledgeGraphDisplayedNodes().map(node=>node.id).sort(),
          hash:[...new Uint8Array(bytes)].map(value=>value.toString(16).padStart(2,'0')).join('')};
      });
    };
    const a=await read('cache-a'),b=await read('cache-b');
    assert.deepEqual(a.ids,b.ids,'equal-size subjects intentionally use the same two real graph nodes');
    assert.notEqual(a.key,b.key,'PNG cache identity includes the selected historical question and its specific dependencies');
    assert.notEqual(a.hash,b.hash,'actual cached PNG changes when the same purple concepts have opposite question-specific dependencies');
    assert.deepEqual(modelCalls,[]);assert.deepEqual(errors,[]);
    console.log('PASS question export cache: identical concepts with different question dependencies retain independent PNGs');
  } finally {await context.close();}
}



async function reviewedTeaching(page,item,id='count_perm_comb',reason='无序选择三人组成小组，需要使用组合计数') {
  return page.evaluate(({item,id,reason})=>{
    const teaching=__graphTeachingFixture(item.text,[[id,item.text]]);
    teaching.question_graph.sources.solution=item.solution||'';
    Object.assign(teaching.question_graph,{catalog_revision:'f'.repeat(64),reconciliation_source:'task_structure',
      task_structure_ids:[id],validation_issues:{unneeded_candidate:1}});
    teaching.question_graph.nodes[0].reason=reason;
    teaching.question_graph.nodes[0].origin='task_structure';
    teaching.question_graph.nodes[0].usage='assessed';
    return teaching;
  },{item,id,reason});
}







async function checkCompletedAnswerReusesInlineGraph(browser) {
  const question='从十二名学生中无序选出四人组成小组，有多少种不同选法';
  const answer='从12人中无序选择4人，共有495种选法';
  const {context,page,errors,modelCalls}=await newPage(browser,1440,'zh-CN');
  const reviews=[];
  try {
    await page.route('**/analyze-questions',route=>{
      reviews.push(route.request().postDataJSON());return route.abort();
    });
    const teaching=await reviewedTeaching(page,{text:question,solution:answer});
    await page.route('**/chat',route=>route.fulfill({contentType:'application/json',
      body:JSON.stringify({reply:answer,teaching})}));
    await page.evaluate(question=>{
      const teaching=__graphTeachingFixture(question,[]);
      sessions=[{id:'inline-answer',name:'随回答取得图谱',nameSource:'user',teaching,learningQuestion:null,
        deletedMessageIds:{},messages:[{messageId:'inline-question',role:'user',text:question,
          manualIsQuestion:true,questionTeaching:teaching}]}];
      currentId='inline-answer';renderAll();
    },question);
    const completed=await page.evaluate(()=>requestAiReply(getCurrent(),{completeImmediately:true}));
    assert.equal(completed.status,'success');
    assert.equal(reviews.length,0,'an already reviewed graph returned with the answer does not queue a second classification');
    const expected={ids:['count_perm_comb'],edges:[],purple:['count_perm_comb'],categories:['计数与组合']};
    await openGraph(page,'focus');
    assert.deepEqual(await snapshot(page),expected,'the completed answer graph is immediately available in the recent view');
    assert.equal(await page.evaluate(()=>getActiveKnowledgeContext().questionGraph.classification_status),'semantic');
    await assertLiveGraph(page,expected,'inline answer');
    await openHistory(page);
    await page.locator('.kg-history-item[data-message-id="inline-question"] [data-history-action="graph"]').click();
    assert.deepEqual(await snapshot(page),expected,'history uses the same already reviewed answer graph');
    await page.evaluate(()=>{
      closeKnowledgeGraph();saveState();
      if(!loadState({guest:true}))throw Error('The inline answer fixture did not survive storage');
      renderAll();
    });
    await openGraph(page,'focus');
    assert.deepEqual(await snapshot(page),expected,'reopening after actual state reload reuses the stored answer graph');
    await page.evaluate(()=>{
      const session=getCurrent(),message=session.messages[0];
      const local=__graphTeachingFixture(message.text,[]);
      Object.assign(local.question_graph,{classification_source:'local_structure',classification_status:'local',needs_review:true});
      attachTeachingSnapshotToLatestQuestion(session,local);
      renderKnowledgeGraph();
    });
    assert.deepEqual(await snapshot(page),expected,'a later local teaching snapshot cannot erase the reviewed answer graph');
    const nextAnswer='也可以先按顺序选出四人，再除去同一组四人的全部排列，结果仍为495';
    const nextTeaching=await reviewedTeaching(page,{text:question,solution:nextAnswer});
    await page.route('**/chat',route=>route.fulfill({contentType:'application/json',
      body:JSON.stringify({reply:nextAnswer,teaching:nextTeaching})}));
    await page.evaluate(()=>{
      const text='请用另一种方法，详细解释为什么选出的四人不考虑先后顺序';
      if(isShortLearningFollowUp(text))throw Error('The fixture must exercise a non-short follow-up');
      getCurrent().messages.push({role:'user',messageId:'inline-followup',text});renderAll();
    });
    const followUp=await page.evaluate(()=>requestAiReply(getCurrent(),{completeImmediately:true}));
    assert.equal(followUp.status,'success');
    assert.equal(await page.evaluate(()=>getCurrent().messages[0].questionTeaching.question_graph.sources.solution),nextAnswer,
      'an inline follow-up graph attaches directly to its existing question before graph viewing');
    assert.deepEqual(await snapshot(page),expected,'a completed follow-up immediately replaces its source-bound graph');
    assert.equal(reviews.length,0,'completion, follow-ups, recent/history switches, reopening and storage restoration make zero extra classification requests');
    assert.deepEqual(modelCalls,[]);assert.deepEqual(errors,[]);
    console.log('PASS inline answer graph: completion, follow-ups, history, reopen and persistence show the reviewed graph without another analysis request');
  } finally {await context.close();}
}

async function checkGeneratedAnswerReusesInlineGraph(browser) {
  const question='从九个不同的项目中无序选出两个，有多少种不同选法';
  const hiddenAnswer='共有36种不同选法';
  const explanation='无序选择两个项目，使用组合数计算得到36';
  const reply='【题目】\n'+question+'\n\n【解析】\n'+explanation+'\n\n【涉及知识点】\n排列与组合';
  const sourceSolution=hiddenAnswer+'\n\n'+explanation;
  const {context,page,errors,modelCalls}=await newPage(browser,1440,'zh-CN');
  const reviews=[];
  try {
    await page.route('**/analyze-questions',route=>{
      reviews.push(route.request().postDataJSON());return route.abort();
    });
    const teaching=await reviewedTeaching(page,{text:question,solution:sourceSolution});
    await page.route('**/chat',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({
      reply,generated_question:question,generated_answer:hiddenAnswer,generated_teaching:teaching,teaching,
      generated_exercise:true})}));
    await page.evaluate(()=>{
      sessions=[{id:'inline-generated',name:'出题时取得图谱',nameSource:'user',teaching:null,learningQuestion:null,
        deletedMessageIds:{},messages:[{messageId:'inline-request',role:'user',text:'出一道排列与组合题'}]}];
      currentId='inline-generated';renderAll();
    });
    const completed=await page.evaluate(()=>requestAiReply(getCurrent(),{completeImmediately:true}));
    assert.equal(completed.status,'success');
    assert.equal(reviews.length,0,'the generated question carries its reviewed graph without a second classification');
    await openGraph(page,'focus');
    const expected={ids:['count_perm_comb'],edges:[],purple:['count_perm_comb'],categories:['计数与组合']};
    assert.deepEqual(await snapshot(page),expected,'the generated question graph is immediately available');
    assert.equal(await page.evaluate(()=>getActiveKnowledgeContext().questionGraph.classification_status),'semantic');
    assert.equal(await page.evaluate(()=>getActiveKnowledgeContext().reviewSolutionText),sourceSolution,
      'generated inline evidence binds independently to the private answer plus visible explanation, excluding the topic footer');
    const generatedId=await page.evaluate(()=>getCurrent().messages.find(message=>message.generatedExercise).messageId);
    await openHistory(page);
    await page.locator('.kg-history-item[data-message-id="'+generatedId+'"] [data-history-action="graph"]').click();
    assert.deepEqual(await snapshot(page),expected);
    await page.evaluate(()=>{
      closeKnowledgeGraph();saveState();
      if(!loadState({guest:true}))throw Error('The generated inline fixture did not survive storage');
      renderAll();
    });
    await openGraph(page,'focus');
    assert.deepEqual(await snapshot(page),expected);
    assert.equal(reviews.length,0,'the generated graph stays immediately reusable across history, reopen and state restoration');
    assert.deepEqual(modelCalls,[]);assert.deepEqual(errors,[]);
    console.log('PASS inline generated graph: hidden answer and visible explanation are stored with an immediately reusable catalog graph');
  } finally {await context.close();}
}





async function checkLocalAnswerSnapshot(browser) {
  const question='从十名学生中无序选出三人组成小组，有多少种不同选法',answer='无序选择三人，共有120种';
  const {context,page,errors,modelCalls}=await newPage(browser,1440,'zh-CN');
  try {
    const teaching=await reviewedTeaching(page,{text:question,solution:answer});
    Object.assign(teaching,{difficulty:'简单',classification_source:'local_structure',classification_status:'local',needs_review:true});
    Object.assign(teaching.question_graph,{classifier_revision:'catalog-structure/2',classification_source:'local_structure',classification_status:'local',needs_review:true});
    await page.route('**/chat',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({reply:answer,teaching})}));
    await page.evaluate(question=>{
      const teaching=__graphTeachingFixture(question,[['count_perm_comb',question]]);teaching.difficulty='简单';
      sessions=[{id:'local-answer',name:'回答登记快照',nameSource:'user',teaching,learningQuestion:null,deletedMessageIds:{},
        messages:[{messageId:'local-question',role:'user',text:question,manualIsQuestion:true,questionTeaching:teaching}]}];
      currentId='local-answer';renderAll();
    },question);
    const completed=await page.evaluate(()=>requestAiReply(getCurrent(),{completeImmediately:true}));
    assert.equal(completed.status,'success');
    await openGraph(page,'focus');
    assert.deepEqual((await snapshot(page)).ids,['count_perm_comb']);
    const stored=await page.evaluate(()=>{
      closeKnowledgeGraph();saveState();const loaded=loadState({guest:true});renderAll();
      const graph=getCurrent().messages[0].questionTeaching.question_graph;
      return {loaded,status:graph.classification_status,needs:graph.needs_review,source:graph.classification_source,solution:graph.sources.solution};
    });
    assert.deepEqual(stored,{loaded:true,status:'local',needs:true,source:'local_structure',solution:answer},
      'viewing and saving preserve local recognition provenance instead of pretending a second semantic pass occurred');
    await openGraph(page,'focus');assert.deepEqual((await snapshot(page)).ids,['count_perm_comb']);
    assert.deepEqual(modelCalls,[]);assert.deepEqual(errors,[]);
    console.log('PASS local answer snapshot: existing answer registration supplies the graph immediately without a background review');
  } finally {await context.close();}
}

async function checkCurrentAnswerMethodEvidence(browser) {
  const question='证明命题 p∧q 与 q∧p 逻辑等价',a='用真值表验证逻辑等价',b='先求范式，再证明逻辑等价';
  const {context,page,errors,modelCalls}=await newPage(browser,1440,'zh-CN');
  try {
    await page.evaluate(({question,a})=>{
      const teaching=__graphTeachingFixture(question,[['logic_equivalence','逻辑等价']]);teaching.difficulty='简单';
      teaching.question_graph.sources.solution=a;
      teaching.question_graph.nodes.push({id:'logic_truth_table',usage:'used',evidence:[{source:'solution',quote:'真值表'}]});
      teaching.question_graph.edges.push({from:'logic_truth_table',to:'logic_equivalence',evidence:[{source:'solution',quote:a}]});
      sessions=[{id:'method-source',name:'实际解法来源',nameSource:'user',teaching,learningQuestion:null,deletedMessageIds:{},messages:[
        {messageId:'method-question',role:'user',text:question,manualIsQuestion:true,questionTeaching:teaching},
        {messageId:'method-a',role:'ai',text:a,targetQuestionMessageId:'method-question'}]}];
      currentId='method-source';renderAll();
    },{question,a});
    await openGraph(page,'focus');
    assert.deepEqual((await snapshot(page)).ids,['logic_equivalence','logic_truth_table']);
    await page.evaluate(b=>{getCurrent().messages.push({messageId:'method-b',role:'ai',text:b,targetQuestionMessageId:'method-question'});renderKnowledgeGraph();},b);
    assert.deepEqual((await snapshot(page)).ids,['logic_equivalence'],'known question facts remain immediate while stale answer methods lose their evidence');
    assert.deepEqual((await snapshot(page)).edges,[]);
    await page.evaluate(b=>{
      const message=getCurrent().messages[0],teaching=__graphTeachingFixture(message.text,[['logic_equivalence','逻辑等价']]);
      teaching.question_graph.sources.solution=b;
      Object.assign(teaching.question_graph,{classification_status:'local',classification_source:'local_structure',needs_review:true});
      teaching.question_graph.nodes.push({id:'logic_normal_form',usage:'used',evidence:[{source:'solution',quote:'求范式'}]});
      teaching.question_graph.edges.push({from:'logic_normal_form',to:'logic_equivalence',evidence:[{source:'solution',quote:b}]});
      message.questionTeaching=teaching;renderKnowledgeGraph();
    },b);
    assert.deepEqual((await snapshot(page)).ids,['logic_equivalence','logic_normal_form']);
    assert.deepEqual((await snapshot(page)).edges,['logic_normal_form>logic_equivalence']);
    assert.deepEqual(modelCalls,[]);assert.deepEqual(errors,[]);
    console.log('PASS current answer sources: stable question facts display while each saved method belongs to its actual answer');
  } finally {await context.close();}
}

(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.CHROMIUM_EXECUTABLE_PATH}:{})});
  try {for(const width of [1440,390])for(const language of ['zh-CN','en'])await checkView(browser,width,language);
    await checkReferenceGuards(browser);await checkEqualSizeCache(browser);await checkGeneratedQuestionSources(browser);
    for(const width of [1440,390])await checkQuestionSpecificTopology(browser,width);await checkRegisteredLegacySnapshot(browser);await checkLongQuestionIdentity(browser);
    await checkCompletedAnswerReusesInlineGraph(browser);await checkGeneratedAnswerReusesInlineGraph(browser);
    await checkLocalAnswerSnapshot(browser);await checkCurrentAnswerMethodEvidence(browser);}
  finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
