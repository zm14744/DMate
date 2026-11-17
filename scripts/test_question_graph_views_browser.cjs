/* Recent and selected-history questions share one cross-module graph model.
 * Account/model/OCR routes are mocked; tests never send paid requests.
 */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const locate = '#knowledgeGraphLocateOriginal';

async function settle(page) {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}
async function bounded(promise,label) {
  let timer;
  try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error(label)),10000);})]);}
  finally{clearTimeout(timer);}
}
async function openGraph(page, mode) {
  await page.evaluate(async mode => {
    if (document.getElementById('knowledgeGraphModal').classList.contains('hidden')) await openKnowledgeGraph();
    selectKnowledgeGraphDisplayMode(mode);
    setKnowledgeGraphFullscreenView(false);
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
async function assertLiveGraph(page, width, expected, label) {
  if (width <= 760 && !await page.locator('.kg-mobile-viewport').count()) await page.locator('.kg-mobile-expand').click();
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
  if (width <= 760) await page.locator('.kg-mobile-expand').click();
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
async function assertLocateBesideTitle(page, label) {
  await settle(page);
  const layout = await page.evaluate(() => {
    const title = document.getElementById('knowledgeGraphDetailTitle');
    const button = document.getElementById('knowledgeGraphLocateOriginal');
    const range = document.createRange();
    range.selectNodeContents(title);
    const text = range.getBoundingClientRect(), action = button.getBoundingClientRect();
    const pane = title.closest('.knowledge-graph-side').getBoundingClientRect();
    return { text:{left:text.left,right:text.right,center:text.top+text.height/2},
      action:{left:action.left,right:action.right,center:action.top+action.height/2},
      pane:{left:pane.left,right:pane.right} };
  });
  assert.ok(layout.action.left >= layout.text.right + 4,
    label + ': Go to original question is to the right of the concept title without overlap');
  assert.ok(Math.abs(layout.text.center - layout.action.center) <= 3,
    label + ': concept title and source action share one vertically centered header row');
  assert.ok(layout.text.left >= layout.pane.left && layout.action.right <= layout.pane.right - 4,
    label + ': the title/action row fits inside the detail pane');
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
    await assertLiveGraph(page,width,recent,label+'/recent');
    await assertExports(page,recent,label+'/recent');
    assert.equal(await page.locator(locate).isVisible(),true,label+': recent details provide Go to original question');
    await assertLocateBesideTitle(page,label+'/recent');
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
    await assertLiveGraph(page,width,historic,label+'/history');
    await assertExports(page,historic,label+'/history');
    assert.equal(await page.locator(locate).isVisible(),false,label+': historical details omit the recent-only source locator');
    assert.equal(await page.evaluate(()=>knowledgeGraphViewMode),'history',label+': a selected historical graph stays in the independent history mode');
    assert.equal(await page.locator('#knowledgeGraphSideTabs').isVisible(),true,label+': historical graph keeps the detail/history sidebar tabs');
    assert.equal(await page.evaluate(()=>JSON.stringify(sessions)),original,label+': graph/export preserve grouped OCR tokens, member flags, text and metadata');
    assert.equal(await page.locator('#knowledgeGraphDetail .graph-detail-term[data-knowledge-node-id="relation_cartesian"]').count(),0,
      label+': details do not leak a static course successor into the question graph');
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
    if(width<=760&&await page.locator('.kg-mobile-viewport').count())await page.locator('.kg-mobile-expand').click();
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
    assert.equal((await page.locator('#knowledgeGraphCanvas').innerText()).trim(),'请选择一道历史题目','stale historical subject returns to the history selection prompt instead of borrowing the latest question');
    assert.equal(await page.locator(locate).isVisible(),false);
    await page.evaluate(()=>{getCurrent().messages[0].text='用逻辑等价证明命题 p 的双重否定与 p 等价';});
    await openHistory(page);
    const deleted=await page.locator('.kg-history-item[data-message-id="pointer-a"] [data-history-action="locate"]').elementHandle();
    await page.locator('.kg-history-item[data-message-id="pointer-a"] [data-history-action="graph"]').click();
    await page.evaluate(()=>{window.__removedGraphQuestion=getCurrent().messages.shift();renderKnowledgeGraph();});
    await deleted.evaluate(button=>button.click());
    assert.equal(await page.locator('#knowledgeGraphModal').isVisible(),true,'deleted selected question invalidates its locator');
    assert.equal((await page.locator('#knowledgeGraphCanvas').innerText()).trim(),'请选择一道历史题目','deleted historical subject returns to the history selection prompt without falling back to the latest question');
    assert.equal(await page.locator(locate).isVisible(),false);
    await page.evaluate(()=>getCurrent().messages.unshift(window.__removedGraphQuestion));
    await openHistory(page);
    const oldOwner=await page.locator('.kg-history-item[data-message-id="pointer-a"] [data-history-action="locate"]').elementHandle();
    await page.locator('.kg-history-item[data-message-id="pointer-a"] [data-history-action="graph"]').click();
    await page.evaluate(()=>bumpCloudSyncContext());
    await oldOwner.evaluate(button=>button.click());
    assert.equal(await page.locator('#knowledgeGraphModal').isVisible(),true,'old owner context cannot close graph or switch source');
    await page.evaluate(()=>renderKnowledgeGraph());
    assert.equal((await page.locator('#knowledgeGraphCanvas').innerText()).trim(),'请选择一道历史题目');
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
    await assertLiveGraph(page,1440,independent,'independent concepts');
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
      assert.equal(source.actual,source.expected,'generated review input includes only its actual hidden answer and visible explanation, excluding the topics footer');
      assert.deepEqual((await snapshot(page)).ids,expected.ids,'a topics footer cannot contribute another involved concept');
    }
    assert.equal(reviews.length,0,'a correctly bound generated answer and explanation keep their completed semantic review');
    await page.evaluate(()=>{
      const message=getCurrent().messages.find(message=>message.messageId==='generated-source');
      message.text='【题目】\n'+message.generatedQuestion;
      message.generatedAnswer='答案已修改，旧解答不再存在';
      renderKnowledgeGraph();
    });
    const changed=await snapshot(page);
    assert.deepEqual(changed.ids,[],'a graph reviewed for a replaced generated answer stays hidden until its new answer is reviewed');
    assert.deepEqual(changed.purple,changed.ids);assert.deepEqual(changed.edges,[]);
    await page.waitForFunction(()=>{
      const operation=knowledgeGraphQuestionAnalyses.get(getCurrent().messages[1]);
      return operation&&operation.status!=='pending';
    });
    assert.equal(reviews.length,1,'replacing a generated answer invalidates its previous semantic review');
    assert.equal(reviews[0].questions[0].solution,'答案已修改，旧解答不再存在');
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
      await assertLiveGraph(page,width,expected,width+'/case'+index);
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

async function checkLegacyBackfill(browser) {
  const {context,page,errors,modelCalls}=await newPage(browser,1440,'zh-CN');
  const classifications=[];
  try {
    await page.route('**/analyze-questions',async route=>{
      const request=route.request().postDataJSON();
      classifications.push(...request.questions);
      const results=await page.evaluate(questions=>questions.map(item=>({key:item.key,
        teaching:__graphTeachingFixture(item.text,['set_operation'])})),request.questions);
      await route.fulfill({contentType:'application/json',body:JSON.stringify({results})});
    });
    await page.evaluate(()=>{
      const text='进行集合运算，计算 A 与 B 的并集';
      const old={category:'集合与关系',knowledge_points:['集合运算'],focus_points:['集合运算'],
        prerequisite_points:['命题推理'],knowledge_path:['集合运算','函数与映射']};
      sessions=[{id:'legacy',name:'旧题目',nameSource:'user',teaching:old,learningQuestion:null,deletedMessageIds:{},
        messages:[{messageId:'legacy-question',role:'user',text,manualIsQuestion:true,questionTeaching:old}]}];
      currentId='legacy';renderAll();
    });
    await openGraph(page,'focus');
    await page.waitForFunction(()=>knowledgeGraphDisplayedNodes().length===1);
    const graph=await snapshot(page);
    assert.deepEqual(graph.ids,['set_operation'],'legacy classification is refreshed from its own actual question');
    assert.deepEqual(graph.purple,['set_operation']);assert.deepEqual(graph.edges,[]);
    assert.equal(classifications.length,1,'one local backfill refreshes old metadata without a repeated classification loop');
    assert.equal(classifications[0].text,'进行集合运算，计算 A 与 B 的并集');
    await openGraph(page,'full');await openGraph(page,'focus');
    assert.equal(classifications.length,1,'the freshly evidenced graph is reused on reopening');
    assert.deepEqual(modelCalls,[]);assert.deepEqual(errors,[]);
    console.log('PASS legacy question graph: one source-bound backfill replaces flat tags and omits stale course paths');
  } finally {await context.close();}
}

async function checkDelayedBackfillGuards(browser) {
  const {context,page,errors,modelCalls}=await newPage(browser,1440,'zh-CN');
  try {
    for (const replaceQuestion of [false,true]) {
      let captured,release;
      const requestReady=new Promise(resolve=>{captured=resolve;});
      const allowResponse=new Promise(resolve=>{release=resolve;});
      await page.route('**/analyze-questions',async route=>{
        const request=route.request().postDataJSON();
        const results=await page.evaluate(questions=>questions.map(item=>({key:item.key,
          teaching:__graphTeachingFixture(item.text,['set_operation'])})),request.questions);
        captured(request);
        await allowResponse;
        await route.fulfill({contentType:'application/json',body:JSON.stringify({results})});
      });
      await page.evaluate(()=>{
        const text='进行集合运算，计算 A 与 B 的交集';
        const old={category:'集合与关系',knowledge_points:['集合运算'],focus_points:['集合运算']};
        sessions=[{id:'backfill-race',name:'异步题目分析',nameSource:'user',teaching:old,learningQuestion:null,deletedMessageIds:{},
          messages:[{messageId:'race-question',role:'user',text,manualIsQuestion:true,questionTeaching:old}]}];
        currentId='backfill-race';renderAll();
      });
      const opening=openGraph(page,'focus');
      await requestReady;
      await page.evaluate(replaceQuestion=>{
        const message=getCurrent().messages[0];
        window.__pendingQuestionGraph=knowledgeGraphQuestionAnalyses.get(message).promise;
        if (replaceQuestion) {
          message.text='依据复合函数的计算结果判断函数与映射的性质';
          message.questionTeaching=__graphTeachingFixture(message.text,['function_composition','function_mapping'],
            [['function_composition','function_mapping',message.text]]);
        } else {
          const solution='依据集合运算的结果求复合函数';
          const teaching=__graphTeachingFixture(message.text,['set_operation']);
          teaching.question_graph.sources.solution=solution;
          teaching.question_graph.nodes.push({id:'function_composition',evidence:[{source:'solution',quote:'复合函数'}]});
          teaching.question_graph.edges.push({from:'set_operation',to:'function_composition',evidence:[{source:'solution',quote:solution}]});
          message.questionTeaching=teaching;
          getCurrent().messages.push({messageId:'race-solution',role:'ai',text:solution});
        }
        window.__newQuestionGraph=JSON.stringify(message.questionTeaching.question_graph);
        renderKnowledgeGraph();
      },replaceQuestion);
      release();
      await opening;
      await page.evaluate(()=>window.__pendingQuestionGraph);
      await settle(page);
      assert.equal(await page.evaluate(()=>JSON.stringify(getCurrent().messages[0].questionTeaching.question_graph)),
        await page.evaluate(()=>window.__newQuestionGraph),replaceQuestion
          ? 'a delayed analysis cannot overwrite the graph of an edited question'
          : 'a delayed question-only analysis cannot overwrite newer solution-backed dependencies');
      const graph=await snapshot(page);
      assert.deepEqual(graph.ids,replaceQuestion?['function_composition','function_mapping']:['function_composition','set_operation']);
      assert.deepEqual(graph.purple,graph.ids,'the retained source-bound graph keeps all involved nodes purple');
      assert.deepEqual(graph.edges,[replaceQuestion?'function_composition>function_mapping':'set_operation>function_composition']);
      await page.unroute('**/analyze-questions');
    }
    assert.deepEqual(modelCalls,[]);assert.deepEqual(errors,[]);
    console.log('PASS delayed graph analyses: edited questions and newer solution-specific dependencies survive stale responses');
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
    assert.deepEqual(latest.ids,[],'a graph claiming another question’s answer is hidden rather than borrowing that answer');
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
    assert.deepEqual((await snapshot(page)).ids,[],
      'an ambiguous legacy fingerprint invalidates the old reviewed answer graph for the earlier question');
    await openHistory(page);
    await page.locator('.kg-history-item[data-message-id="long-b"] [data-history-action="graph"]').click();
    assert.deepEqual((await snapshot(page)).ids,[],
      'the same ambiguous legacy fingerprint cannot attest a reviewed graph for the later question either');
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
    assert.equal(reviews.length,2,'unattested and ambiguous answer sources request fresh source-bound reviews');
    assert.ok(reviews.every(request=>request.semantic_fallback===true&& !request.questions[0].solution),
      'reviews do not borrow a solution whose stable or legacy owner cannot be established');
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

async function seedUnreviewedQuestion(page, question, options = {}) {
  await page.evaluate(({question,options})=>{
    const teaching=__graphTeachingFixture(question,[]);
    Object.assign(teaching.question_graph,{classifier_revision:options.oldRevision?'keyword-v1':'catalog-semantic-v5',
      classification_status:'local',classification_source:'structural_rules',needs_review:true});
    teaching.question_graph.sources.solution=options.solution||'';
    sessions=[{id:'semantic-source',name:'逐题知识点复核',nameSource:'user',teaching,learningQuestion:null,
      deletedMessageIds:{},messages:[{messageId:'semantic-question',role:'user',text:question,
        manualIsQuestion:true,questionTeaching:teaching},...(options.solution?[{role:'ai',messageId:'semantic-answer',
          text:options.solution,targetQuestionMessageId:'semantic-question'}]:[])]}];
    currentId='semantic-source';deletedSessionIds=Object.create(null);renderAll();
  },{question,options});
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

async function checkSemanticKnowledgeReview(browser) {
  const question='从十名学生中无序选出三人组成小组，有多少种不同选法';
  const {context,page,errors,modelCalls}=await newPage(browser,1440,'zh-CN');
  const requests=[];
  let capturedSimple,releaseSimple;
  const simpleReady=new Promise(resolve=>{capturedSimple=resolve;});
  const simpleAllowed=new Promise(resolve=>{releaseSimple=resolve;});
  try {
    await page.route('**/analyze-questions',async route=>{
      const body=route.request().postDataJSON();requests.push(body);
      const item=body.questions[0],simple=item.text.includes('交集');
      const teaching=await reviewedTeaching(page,item,simple?'set_operation':'count_perm_comb',
        simple?'题目要求求两个集合的交集':'无序选择三人组成小组，需要使用组合计数');
      if(simple){capturedSimple();await simpleAllowed;}
      await route.fulfill({contentType:'application/json',body:JSON.stringify({results:[{key:body.questions[0].key,teaching}]})});
    });
    await seedUnreviewedQuestion(page,question,{oldRevision:true});
    await openGraph(page,'full');await openHistory(page);
    await settle(page);
    assert.equal(requests.length,0,'course browsing and the historical list do not trigger mass semantic reviews');
    await page.locator('.kg-history-item[data-message-id="semantic-question"] [data-history-action="graph"]').click();
    await page.waitForFunction(()=>getCurrent().messages[0].questionTeaching.question_graph.classification_status==='semantic');
    assert.equal(requests.length,1,'an existing empty graph with an old classifier revision is reviewed once');
    assert.equal(requests[0].semantic_fallback,true,'the graph explicitly requests bounded semantic review');
    assert.equal(requests[0].questions[0].text,question,'review receives the actual unnamed mathematical problem');
    assert.deepEqual((await snapshot(page)).ids,['count_perm_comb'],'the reviewed graph uses an existing catalog point without adding prerequisite neighbors');
    assert.deepEqual((await snapshot(page)).purple,['count_perm_comb']);
    const persisted=await page.evaluate(()=>{
      saveState();const loaded=loadState({guest:true});
      const graph=getCurrent().messages[0].questionTeaching.question_graph;
      return {loaded,revision:graph.classifier_revision,status:graph.classification_status,
        source:graph.classification_source,needs:graph.needs_review,reason:graph.nodes[0].reason,
        origin:graph.nodes[0].origin,usage:graph.nodes[0].usage,catalog:graph.catalog_revision,
        reconciliation:graph.reconciliation_source,structure:graph.task_structure_ids,issues:graph.validation_issues};
    });
    assert.deepEqual(persisted,{loaded:true,revision:'catalog-semantic-v5',status:'semantic',
      source:'catalog_semantic',needs:false,reason:'无序选择三人组成小组，需要使用组合计数',origin:'task_structure',usage:'assessed',
      catalog:'f'.repeat(64),reconciliation:'task_structure',structure:['count_perm_comb'],issues:{unneeded_candidate:1}},
    'semantic provenance, mathematical reason and task-structure reconciliation trace survive actual client normalization and storage');
    await openGraph(page,'focus');await openGraph(page,'history');await settle(page);
    assert.equal(requests.length,1,'a current reviewed graph is reused rather than reviewed on every page change');
    const simple='求 A={1,2} 与 B={2,3} 的交集';
    await seedUnreviewedQuestion(page,simple);
    await page.evaluate(()=>{
      const teaching=getCurrent().messages[0].questionTeaching;
      teaching.confidence='高';
      Object.assign(teaching.question_graph,{classification_status:'semantic',needs_review:false});
      teaching.question_graph.nodes=[{id:'count_inclusion',evidence:[{source:'question',quote:getCurrent().messages[0].text}]}];
    });
    await openGraph(page,'focus');
    await bounded(simpleReady,'A nonempty provisional graph did not request semantic review');
    assert.deepEqual((await snapshot(page)).ids,[],'an unreviewed high-confidence false local point is not drawn while semantic review is pending');
    assert.equal(await page.locator('#knowledgeGraphCanvas .kg-node-group,#knowledgeGraphCanvas .kg-mobile-node').count(),0,
      'provisional local guesses cannot appear as purple confirmed knowledge nodes');
    releaseSimple();
    await page.waitForFunction(()=>getCurrent().messages[0].questionTeaching.question_graph.classification_source==='catalog_semantic');
    assert.equal(requests.length,2,'a local graph is reviewed even when it claims semantic completion and high confidence');
    assert.equal(requests[1].semantic_fallback,true);
    assert.deepEqual((await snapshot(page)).ids,['set_operation'],'semantic review can remove a false local point instead of merely adding to existing local tags');
    assert.deepEqual(modelCalls,[]);assert.deepEqual(errors,[]);
    console.log('PASS semantic knowledge review: old empty metadata, unnamed problems, catalog-only results, provenance persistence and no list-wide reviews');
  } finally {releaseSimple();await context.close();}
}

async function checkReviewFailureIsNotCompletion(browser) {
  const {context,page,errors,modelCalls}=await newPage(browser,1440,'zh-CN');
  try {
    for(const unavailable of [true,false]) {
      const requests=[];
      await page.route('**/analyze-questions',async route=>{
        const body=route.request().postDataJSON();requests.push(body);
        if(!unavailable)return route.fulfill({status:429,contentType:'application/json',body:'{"error":"复核请求过于频繁"}'});
        const item=body.questions[0];
        const teaching=await page.evaluate(item=>{
          const result=__graphTeachingFixture(item.text,[]);
          Object.assign(result.question_graph,{classification_status:'unavailable',classification_source:'structural_rules',needs_review:true});
          return result;
        },item);
        return route.fulfill({contentType:'application/json',body:JSON.stringify({results:[{key:item.key,teaching}]})});
      });
      await seedUnreviewedQuestion(page,'从九名学生中选出两人组成小组，有多少种选法');
      await openGraph(page,'focus');
      await page.waitForFunction(()=>{
        const operation=knowledgeGraphQuestionAnalyses.get(getCurrent().messages[0]);
        return operation&&operation.status!=='pending';
      });
      await page.evaluate(()=>{for(let index=0;index<8;index++)renderKnowledgeGraph();});
      await settle(page);
      const graph=await page.evaluate(()=>getCurrent().messages[0].questionTeaching.question_graph);
      assert.notEqual(graph.classification_status,'semantic',(unavailable?'unconfigured':'rate-limited')+' review is not falsely recorded as semantic completion');
      assert.equal(graph.needs_review,true,'unavailable review remains eligible for a later valid attempt');
      assert.equal(requests.length,1,'repeated rendering does not create an unavailable/rate-limit request loop');
      assert.deepEqual((await snapshot(page)).ids,[],'failure does not invent a graph from unrelated course neighbors');
      await page.unroute('**/analyze-questions');
    }
    assert.deepEqual(modelCalls,[]);assert.deepEqual(errors,[]);
    console.log('PASS semantic review failures: missing configuration and rate limits stay incomplete without request storms');
  } finally {await context.close();}
}

async function checkCompletedAnswerStartsBackgroundReview(browser) {
  const question='从十名学生中无序选出三人组成小组，有多少种不同选法',answer='从10人中无序选择3人，共有120种选法';
  const {context,page,errors,modelCalls}=await newPage(browser,1440,'zh-CN');
  let captured,release;
  const requestReady=new Promise(resolve=>{captured=resolve;});
  const responseAllowed=new Promise(resolve=>{release=resolve;});
  try {
    await page.route('**/analyze-questions',async route=>{
      const body=route.request().postDataJSON();captured(body);await responseAllowed;
      const teaching=await reviewedTeaching(page,body.questions[0]);
      await route.fulfill({contentType:'application/json',body:JSON.stringify({results:[{key:body.questions[0].key,teaching}]})});
    });
    const local=await page.evaluate(({question,answer})=>{
      const teaching=__graphTeachingFixture(question,[]);
      Object.assign(teaching.question_graph,{classification_status:'local',classification_source:'structural_rules',needs_review:true});
      teaching.question_graph.sources.solution=answer;return teaching;
    },{question,answer});
    await page.route('**/chat',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({reply:answer,teaching:local})}));
    await page.evaluate(question=>{
      const teaching=__graphTeachingFixture(question,[]);
      sessions=[{id:'answer-review',name:'回答后复核',nameSource:'user',teaching,learningQuestion:null,deletedMessageIds:{},
        messages:[{messageId:'answer-review-question',role:'user',text:question,manualIsQuestion:true,questionTeaching:teaching}]}];
      currentId='answer-review';renderAll();
    },question);
    const sending=page.evaluate(()=>requestAiReply(getCurrent(),{completeImmediately:true}));
    const body=await bounded(requestReady,'A completed answer did not queue its semantic review');
    const completed=await Promise.race([sending,new Promise((_,reject)=>setTimeout(()=>reject(Error('The completed answer waited for semantic review')),5000))]);
    assert.equal(completed.status,'success','answer completion is independent of the held semantic response');
    assert.equal(body.semantic_fallback,true);
    assert.equal(body.questions[0].text,question);
    assert.equal(body.questions[0].solution,answer,'background review receives the actual newly committed answer');
    assert.equal(await page.evaluate(answer=>getCurrent().messages.some(message=>message.role==='ai'&&message.text===answer),answer),true);
    release();
    await page.waitForFunction(()=>getCurrent().messages[0].questionTeaching.question_graph.classification_status==='semantic');
    assert.deepEqual(errors,[]);assert.deepEqual(modelCalls,[]);
    console.log('PASS answer review: committed replies trigger source-bound review without waiting for another model response');
  } finally {release();await context.close();}
}

async function checkSemanticReviewRejectsOldSolution(browser) {
  const question='证明命题 p∧q 与 q∧p 逻辑等价',oldAnswer='先研究逻辑等价',newAnswer='用真值表验证逻辑等价';
  const {context,page,errors,modelCalls}=await newPage(browser,1440,'zh-CN');
  let captured,release;
  const requestReady=new Promise(resolve=>{captured=resolve;});
  const responseAllowed=new Promise(resolve=>{release=resolve;});
  try {
    await page.route('**/analyze-questions',async route=>{
      const body=route.request().postDataJSON();captured(body);
      const teaching=await reviewedTeaching(page,body.questions[0],'logic_equivalence','题目要求证明两个命题等价');
      await responseAllowed;
      await route.fulfill({contentType:'application/json',body:JSON.stringify({results:[{key:body.questions[0].key,teaching}]})});
    });
    await seedUnreviewedQuestion(page,question,{solution:oldAnswer});
    const opening=openGraph(page,'focus');
    const body=await bounded(requestReady,'An unreviewed solution graph did not queue its semantic review');
    assert.equal(body.questions[0].solution,oldAnswer);
    await page.evaluate(({question,newAnswer})=>{
      const session=getCurrent(),message=session.messages[0];
      window.__oldSemanticOperation=knowledgeGraphQuestionAnalyses.get(message).promise;
      session.messages.push({role:'ai',messageId:'new-reviewed-answer',text:newAnswer,targetQuestionMessageId:message.messageId});
      const solution=getKnowledgeGraphQuestionSubject().context.reviewSolutionText;
      const teaching=__graphTeachingFixture(question,[['logic_equivalence','逻辑等价']]);
      teaching.question_graph.sources.solution=solution;
      teaching.question_graph.nodes.push({id:'logic_truth_table',reason:'最新解答实际使用真值表',evidence:[{source:'solution',quote:'真值表'}]});
      teaching.question_graph.edges.push({from:'logic_truth_table',to:'logic_equivalence',evidence:[{source:'solution',quote:newAnswer}]});
      message.questionTeaching=teaching;
      window.__freshSolutionGraph=JSON.stringify(teaching.question_graph);renderKnowledgeGraph();
    },{question,newAnswer});
    release();await opening;await page.evaluate(()=>window.__oldSemanticOperation);await settle(page);
    assert.equal(await page.evaluate(()=>JSON.stringify(getCurrent().messages[0].questionTeaching.question_graph)),
      await page.evaluate(()=>window.__freshSolutionGraph),'review for an old answer cannot overwrite a newer solution-specific semantic graph');
    assert.deepEqual((await snapshot(page)).ids,['logic_equivalence','logic_truth_table']);
    assert.deepEqual((await snapshot(page)).edges,['logic_truth_table>logic_equivalence']);
    assert.deepEqual(modelCalls,[]);assert.deepEqual(errors,[]);
    console.log('PASS semantic review races: exact solution snapshots prevent old reviews from replacing newer answer dependencies');
  } finally {release();await context.close();}
}

async function checkNewAnswerHidesPreviousReview(browser) {
  const question='证明命题 p∧q 与 q∧p 逻辑等价',oldAnswer='先研究逻辑等价',newAnswer='用真值表验证逻辑等价';
  const {context,page,errors,modelCalls}=await newPage(browser,1440,'zh-CN');
  let captured,release;
  const requestReady=new Promise(resolve=>{captured=resolve;});
  const responseAllowed=new Promise(resolve=>{release=resolve;});
  try {
    await page.route('**/analyze-questions',async route=>{
      const body=route.request().postDataJSON();captured(body);await responseAllowed;
      const teaching=await reviewedTeaching(page,body.questions[0],'logic_equivalence','本题要求验证交换顺序后的逻辑等价');
      teaching.question_graph.nodes.push({id:'logic_truth_table',reason:'最新解答实际使用真值表',usage:'used',origin:'catalog_semantic',
        evidence:[{source:'solution',quote:'真值表'}]});
      teaching.question_graph.edges.push({from:'logic_truth_table',to:'logic_equivalence',reason:'用真值表验证等价',
        evidence:[{source:'solution',quote:newAnswer}]});
      await route.fulfill({contentType:'application/json',body:JSON.stringify({results:[{key:body.questions[0].key,teaching}]})});
    });
    await seedUnreviewedQuestion(page,question,{solution:oldAnswer});
    await page.evaluate(({question,oldAnswer})=>{
      const teaching=__graphTeachingFixture(question,[['logic_equivalence','逻辑等价']]);
      teaching.question_graph.sources.solution=oldAnswer;
      getCurrent().messages[0].questionTeaching=teaching;
    },{question,oldAnswer});
    await openGraph(page,'focus');
    assert.deepEqual((await snapshot(page)).ids,['logic_equivalence'],'the initial graph is bound to its actual reviewed answer');
    await page.evaluate(newAnswer=>{
      getCurrent().messages.push({role:'ai',messageId:'replacement-answer',text:newAnswer,targetQuestionMessageId:'semantic-question'});
      renderKnowledgeGraph();
    },newAnswer);
    const body=await bounded(requestReady,'A new actual answer did not invalidate and review the old answer graph');
    assert.equal(body.questions[0].solution,newAnswer,'only the latest actual answer is reviewed');
    assert.deepEqual((await snapshot(page)).ids,[],'the old A graph is not painted while answer B awaits review');
    assert.equal(await page.locator('#knowledgeGraphCanvas .kg-node-group,#knowledgeGraphCanvas .kg-mobile-node').count(),0,
      'no purple node from the previous answer remains in the pending graph');
    release();
    await page.waitForFunction(()=>getCurrent().messages[0].questionTeaching.question_graph.sources.solution===
      getKnowledgeGraphQuestionSubject().context.reviewSolutionText);
    assert.deepEqual((await snapshot(page)).ids,['logic_equivalence','logic_truth_table']);
    assert.deepEqual((await snapshot(page)).edges,['logic_truth_table>logic_equivalence']);
    assert.deepEqual(modelCalls,[]);assert.deepEqual(errors,[]);
    console.log('PASS answer revision display: previous reviewed graphs stay hidden until the latest actual answer is reviewed');
  } finally {release();await context.close();}
}
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.CHROMIUM_EXECUTABLE_PATH}:{})});
  try {for(const width of [1440,390])for(const language of ['zh-CN','en'])await checkView(browser,width,language);
    await checkReferenceGuards(browser);await checkEqualSizeCache(browser);await checkGeneratedQuestionSources(browser);
    for(const width of [1440,390])await checkQuestionSpecificTopology(browser,width);await checkLegacyBackfill(browser);await checkDelayedBackfillGuards(browser);await checkLongQuestionIdentity(browser);
    await checkSemanticKnowledgeReview(browser);await checkReviewFailureIsNotCompletion(browser);
    await checkCompletedAnswerStartsBackgroundReview(browser);await checkSemanticReviewRejectsOldSolution(browser);
    await checkNewAnswerHidesPreviousReview(browser);}
  finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
