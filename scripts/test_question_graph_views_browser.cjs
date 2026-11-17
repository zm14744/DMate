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
async function openGraph(page, mode) {
  await page.evaluate(async mode => {
    if (document.getElementById('knowledgeGraphModal').classList.contains('hidden')) await openKnowledgeGraph();
    selectKnowledgeGraphDisplayMode(mode);
    setKnowledgeGraphFullscreenView(false);
  }, mode);
  await settle(page);
}
async function openHistory(page) {
  await openGraph(page, 'full');
  await page.locator('#knowledgeGraphHistoryTab').click();
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
  await page.evaluate(language => DMateI18n.setLanguage(language,false), language);
  return {context,page,errors,modelCalls};
}
async function seedCrossModule(page) {
  return page.evaluate(() => {
    const teaching = {category:'集合与关系',focus_points:['集合运算'],knowledge_points:['集合运算','复合函数','容斥原理'],
      prerequisite_points:[],knowledge_path:['集合运算','复合函数','容斥原理']};
    const signed = (body,id) => ({document:{body_text:body,graphs:[]},question_text:body+'\n[canonical '+id+']',
      rendered_question_text:'【题目文字】\n'+body,source_sha256:'a'.repeat(64),document_sha256:'b'.repeat(64),
      confirmation_token:'fixture-token-'+id,revision:1,request_id:id,profile:'editable-v1'});
    const source = id => {
      const contexts = [signed('已知集合 A、B 与函数 f、g，求复合函数并用容斥原理计数',id+'-one'),signed('第二张图给出补充条件',id+'-two')];
      return {messageId:id,role:'user',source:'ocr',ocrIsQuestion:true,
        text:contexts.map((item,index)=>`【图片 ${index+1}】\n${item.rendered_question_text}`).join('\n\n')+'\n\n【我的要求】\n保留原定义',
        apiText:contexts.map((item,index)=>`【图片 ${index+1}】\n${item.question_text}`).join('\n\n'),semanticContexts:contexts,
        ocrGroup:{id:'confirmed-'+id,groupId:id,members:[{requestId:id+'-one',isQuestion:true},{requestId:id+'-two',isQuestion:false}]},
        questionTeaching:JSON.parse(JSON.stringify(teaching))};
    };
    const unrelated = {category:'证明与归纳',knowledge_points:['数学归纳法'],focus_points:['数学归纳法']};
    sessions = [
      {id:'past-conversation',name:'历史集合与函数',nameSource:'user',deletedMessageIds:{},learningQuestion:null,teaching:unrelated,messages:[
        source('past-group'),{role:'ai',messageId:'past-explanation',text:'已说明集合与函数的条件'},
        {role:'user',messageId:'past-later',text:'用数学归纳法证明自然数求和公式',manualIsQuestion:true,questionTeaching:unrelated}]},
      {id:'current-conversation',name:'当前集合与函数',nameSource:'user',deletedMessageIds:{},learningQuestion:null,teaching,messages:[
        source('current-group'),{role:'ai',messageId:'current-explanation',text:'逐项核对定义'},
        {role:'user',messageId:'current-chat',text:'继续解释',manualIsQuestion:false}]}
    ];
    currentId='current-conversation'; deletedSessionIds=Object.create(null); renderAll();
    return JSON.stringify(sessions);
  });
}
async function checkView(browser, width, language) {
  const label=width+'/'+language, {context,page,errors,modelCalls}=await newPage(browser,width,language);
  try {
    const original=await seedCrossModule(page);
    await openGraph(page,'focus');
    const recent=await snapshot(page);
    for(const id of ['set_operation','function_mapping','function_composition','count_inclusion'])
      assert.ok(recent.ids.includes(id),label+': involved concepts and their real connecting node are included: '+id);
    assert.equal(recent.categories.length >= 3,true,label+': one question spans multiple modules without a category cutoff');
    assert.ok(recent.edges.includes('set_operation>function_mapping'));
    assert.ok(recent.edges.includes('function_mapping>function_composition'));
    assert.ok(recent.edges.includes('set_operation>count_inclusion'));
    for(const id of ['relation_equivalence','relation_closure','graph_tree'])
      assert.equal(recent.ids.includes(id),false,label+': an unrelated module branch is not dumped into the question graph');
    assert.deepEqual(recent.purple,['count_inclusion','function_composition','set_operation'],label+': all involved question concepts remain purple');
    await assertLiveGraph(page,width,recent,label+'/recent');
    await assertExports(page,recent,label+'/recent');
    assert.equal(await page.locator(locate).isVisible(),true,label+': recent details provide Go to original question');
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
    assert.equal(await page.evaluate(()=>document.getElementById('knowledgeGraphModal').dataset.graphView),'focus',label+': historical question graph is cross-module focused presentation');
    await assertLiveGraph(page,width,historic,label+'/history');
    await assertExports(page,historic,label+'/history');
    assert.equal(await page.locator(locate).isVisible(),true,label+': selected-history details provide source navigation');
    assert.equal(await page.evaluate(()=>JSON.stringify(sessions)),original,label+': graph/export preserve grouped OCR tokens, member flags, text and metadata');
    await page.locator('#knowledgeGraphDetail .graph-detail-term[data-knowledge-node-id="relation_cartesian"]').click();
    await settle(page);
    const plain=await snapshot(page);
    assert.deepEqual(plain.ids,await page.evaluate(()=>knowledgeGraphVisibleNodes('集合与关系').map(node=>node.id).sort()),
      label+': relation navigation leaves the focused canvas and displays the complete target module');
    assert.deepEqual(plain.purple,[],label+': full-module navigation removes the historical question highlights');
    assert.equal(await page.evaluate(()=>knowledgeGraphScope),'current',label+': relation navigation clears selected-history scope');
    assert.equal(await page.evaluate(()=>knowledgeGraphQuestionReference),null,label+': relation navigation clears the subject reference');
    assert.equal(await page.evaluate(()=>document.getElementById('knowledgeGraphModal').dataset.graphView),'full');
    assert.equal(await page.evaluate(()=>knowledgeGraphSelectedNodeId),'relation_cartesian');
    await openHistory(page);
    await page.locator('.kg-history-item[data-message-id="past-group"] [data-history-action="graph"]').click();
    if(width<=760&&await page.locator('.kg-mobile-viewport').count())await page.locator('.kg-mobile-expand').click();
    await page.evaluate(()=>{
      const session=sessions.find(session=>session.id==='past-conversation');
      session.messages.push(session.messages.shift()); renderKnowledgeGraph();
    });
    await page.locator(locate).click();
    await page.locator('#chat [data-message-index="2"].history-locate-flash').waitFor();
    assert.equal(await page.evaluate(()=>currentId),'past-conversation',label+': selected-history locator switches to its source conversation');
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
      const a='证明命题 p 的双重否定与 p 等价', b='求集合 A 的补集';
      const ta={category:'命题逻辑',knowledge_points:['逻辑等价'],focus_points:['逻辑等价']};
      const tb={category:'集合与关系',knowledge_points:['集合运算'],focus_points:['集合运算']};
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
    await page.locator('.kg-history-item[data-message-id="pointer-a"] [data-history-action="graph"]').click();
    const stale=await page.locator(locate).elementHandle();
    await page.evaluate(()=>{getCurrent().messages[0].text='改成另一个不同的命题问题';renderKnowledgeGraph();});
    await stale.evaluate(button=>button.click());
    assert.equal(await page.locator('#knowledgeGraphModal').isVisible(),true,'edited selected question invalidates its captured locator');
    assert.equal((await page.locator('#knowledgeGraphCanvas').innerText()).trim(),'无','stale historical subject becomes None instead of borrowing the latest question');
    assert.equal(await page.locator(locate).isVisible(),false);
    await page.evaluate(()=>{getCurrent().messages[0].text='证明命题 p 的双重否定与 p 等价';});
    await openHistory(page);
    await page.locator('.kg-history-item[data-message-id="pointer-a"] [data-history-action="graph"]').click();
    const deleted=await page.locator(locate).elementHandle();
    await page.evaluate(()=>{window.__removedGraphQuestion=getCurrent().messages.shift();renderKnowledgeGraph();});
    await deleted.evaluate(button=>button.click());
    assert.equal(await page.locator('#knowledgeGraphModal').isVisible(),true,'deleted selected question invalidates its locator');
    assert.equal((await page.locator('#knowledgeGraphCanvas').innerText()).trim(),'无','deleted historical subject does not fall back to the latest question');
    assert.equal(await page.locator(locate).isVisible(),false);
    await page.evaluate(()=>getCurrent().messages.unshift(window.__removedGraphQuestion));
    await openHistory(page);
    await page.locator('.kg-history-item[data-message-id="pointer-a"] [data-history-action="graph"]').click();
    const oldOwner=await page.locator(locate).elementHandle();
    await page.evaluate(()=>bumpCloudSyncContext());
    await oldOwner.evaluate(button=>button.click());
    assert.equal(await page.locator('#knowledgeGraphModal').isVisible(),true,'old owner context cannot close graph or switch source');
    await page.evaluate(()=>renderKnowledgeGraph());
    assert.equal((await page.locator('#knowledgeGraphCanvas').innerText()).trim(),'无');
    await page.evaluate(()=>{
      const text='计算集合 A 与 B 的并集，再求函数的复合';
      const teaching={category:'证明与归纳',focus_points:['数学归纳法'],knowledge_points:['数学归纳法']};
      sessions=[{id:'saved-snapshot',name:'旧版已保存题目',nameSource:'user',teaching:null,deletedMessageIds:{},
        learningQuestion:{text,category:'集合与关系',knowledgePoints:['集合运算','复合函数'],focusPoints:['集合运算'],source:'text',sessionId:'saved-snapshot',updatedAt:1},
        messages:[{messageId:'saved-question',role:'user',text,manualIsQuestion:true}]},
      {id:'unrelated-current',name:'另一段归纳法',nameSource:'user',teaching,learningQuestion:null,deletedMessageIds:{},
        messages:[{messageId:'unrelated-question',role:'user',text:'用归纳法证明求和公式',manualIsQuestion:true,questionTeaching:teaching}]}];
      currentId='saved-snapshot';renderAll();
    });
    await openGraph(page,'focus');
    const fallback=await snapshot(page);
    assert.ok(fallback.purple.includes('set_operation'),'recent subject can use its matching saved classification snapshot');
    await page.evaluate(()=>{currentId='unrelated-current';renderAll();});
    await openHistory(page);
    await page.locator('.kg-history-item[data-message-id="saved-question"] [data-history-action="graph"]').click();
    assert.deepEqual(await snapshot(page),fallback,'historical subject reuses its own saved snapshot and never borrows the current conversation');
    assert.equal(await page.evaluate(()=>currentId),'unrelated-current');
    await page.evaluate(()=>{
      const teaching={category:'集合与关系',focus_points:['集合运算','逻辑等价'],knowledge_points:['集合运算','逻辑等价']};
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
    console.log('PASS question references: previous-question pointer, saved fallback, real relationships and stale edit/owner guards');
  } finally {await context.close();}
}
async function checkEqualSizeCache(browser) {
  const {context,page,errors,modelCalls}=await newPage(browser,1440,'zh-CN');
  try {
    await page.evaluate(async()=>{
      await ensureKnowledgeGraphData();
      const only=new Set(['set_operation','function_mapping']);
      knowledgeGraphData={...knowledgeGraphData,nodes:knowledgeGraphData.nodes.filter(node=>only.has(node.id))};
      const teaching=name=>({category:name==='集合运算'?'集合与关系':'函数',knowledge_points:[name],focus_points:[name]});
      sessions=[{id:'cache',name:'缓存题目',nameSource:'user',learningQuestion:null,teaching:teaching('函数与映射'),deletedMessageIds:{},messages:[
        {messageId:'cache-a',role:'user',text:'计算集合 A 与 B 的交集',manualIsQuestion:true,questionTeaching:teaching('集合运算')},
        {messageId:'cache-b',role:'user',text:'判断函数 f 是否为单射',manualIsQuestion:true,questionTeaching:teaching('函数与映射')}]}];
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
    assert.notEqual(a.key,b.key,'PNG cache identity includes the selected historical question and highlighted concepts');
    assert.notEqual(a.hash,b.hash,'actual cached PNG changes when equal-size subjects highlight opposite nodes');
    assert.deepEqual(modelCalls,[]);assert.deepEqual(errors,[]);
    console.log('PASS question export cache: equal-size historical subjects retain independent purple PNGs');
  } finally {await context.close();}
}
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.CHROMIUM_EXECUTABLE_PATH}:{})});
  try {for(const width of [1440,390])for(const language of ['zh-CN','en'])await checkView(browser,width,language);
    await checkReferenceGuards(browser);await checkEqualSizeCache(browser);}
  finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
