/* Registered knowledge and difficulty are one source-bound saved result. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const QUESTION = '求集合 A={1,2} 与 B={2,3} 的交集，再从交集中选择一个元素';

async function run(browser, width) {
  const context = await browser.newContext({viewport:{width,height:900},serviceWorkers:'block'});
  const page = await context.newPage(), errors = [], calls = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/auth/me', route => route.fulfill({contentType:'application/json',
    body:'{"configured":true,"authenticated":false}'}));
  await page.route(/\/(?:chat|conversation\/title|classify|analyze-questions|ocr)(?:\?|$)/, route => {
    calls.push(new URL(route.request().url()).pathname);
    return route.abort();
  });
  try {
    await page.goto(baseURL,{waitUntil:'networkidle'});
    await page.waitForFunction(() => typeof registeredQuestionSnapshot === 'function' && !accountVerificationOperation);
    const results = await page.evaluate(async question => {
      await ensureKnowledgeGraphData();
      const flat = {category:'集合与关系',difficulty:'简单',knowledge_points:['集合运算'],
        related_knowledge_points:['排列与组合'],focus_points:['集合运算'],
        prerequisite_points:['容斥原理'],knowledge_path:['函数与映射']};
      const makeEntry = (extra={}) => ({id:'snapshot-source',question,difficulty:'简单',
        category:'集合与关系',knowledgePoints:['集合运算','排列与组合'],focusPoints:['集合运算'],
        referenceAnswer:'{2}',answer:'{2}',analysis:'',corrected:false,createdAt:1,updatedAt:1,...extra});
      const read = entry => {
        const context = wrongQuestionGraphContext(entry,{kind:'wrong',id:entry.id,question:entry.question});
        const graph = DMateQuestionKnowledgeGraph.build(knowledgeGraphData.nodes, context);
        return {ids:graph.nodes.map(node=>node.id).sort(),edges:graph.edges,registration:context.registeredSnapshot};
      };
      const normalized = normalizeTeaching(flat);
      const entry = normalizeLearningState({wrongQuestions:[makeEntry()]}).wrongQuestions[0];
      const legacy = read(entry);
      const source = {version:1,sources:{question,solution:'用容斥原理核对'},
        classification_source:'local_structure',classification_status:'local',needs_review:true,
        nodes:[{id:'set_operation',evidence:[{source:'question',quote:'交集'}]},
          {id:'count_inclusion',evidence:[{source:'solution',quote:'容斥原理'}]}],edges:[]};
      const localTeaching = normalizeTeaching({...flat,related_knowledge_points:['容斥原理'],question_graph:source});
      const local = makeEntry();
      const storedLocal = storeWrongQuestionGraphTeaching(local,localTeaching,question,source.sources.solution);
      const localBefore = read(local);
      local.questionTeaching=null;local.graphSolution='';local.analysis='逐个检查元素，交集为 {2}';
      const retainedQuestionFacts = read(local);
      const catalog = knowledgeGraphData;
      knowledgeGraphData=null;
      const early = normalizeTeaching({...flat,related_knowledge_points:['容斥原理'],question_graph:source});
      knowledgeGraphData=catalog;
      const earlySnapshot = registeredQuestionSnapshot(early,question);
      const fullQuestion = question+'；设 f:A→A 为恒等映射，判断它是否为单射，并求复合映射 f∘f';
      const old = makeEntry({question:fullQuestion,recognitionSnapshot:{version:1,question:fullQuestion,difficulty:'困难',
        points:['集合运算','排列与组合','函数与映射','单射满射双射','复合函数'],excludedIds:[]}});
      const full = normalizeLearningState({wrongQuestions:[old]}).wrongQuestions[0];
      const preserved = read(full);
      const foreign = normalizeLearningState({wrongQuestions:[makeEntry({questionTeaching:{...flat,
        question_graph:{...source,sources:{question:'另一道需要求最大公约数的题',solution:''}}}})]}).wrongQuestions[0];
      const foreignGraph = read(foreign);
      const foreignSnapshot = registeredQuestionSnapshot({...flat,registered_snapshot:{version:1,
        question:'完全不同的题目',difficulty:'简单',points:['集合运算']}},question);
      const english = registeredQuestionSnapshot({...flat,knowledge_points:['Set Operations'],
        related_knowledge_points:['count_perm_comb','Unknown Course Point']},question);
      const heading = registeredQuestionSnapshot({...flat,registered_snapshot:{version:1,
        question:'【题目】\n'+question,difficulty:'简单',points:['集合运算','排列与组合']}},question);

      sessions=[{id:'snapshot-source-session',messages:[{role:'user',messageId:'source-question',
        text:question,manualIsQuestion:true,questionTeaching:flat},
        {role:'ai',messageId:'source-answer',text:'{2}',targetQuestionMessageId:'source-question'}]}];
      currentId=sessions[0].id;learningState=createEmptyLearningState();
      const info=questionInfoFromChatMessage(sessions[0],0);
      const added=addWrongQuestion({...info,referenceAnswer:'{2}',safeConfirmed:true},'','manual').entry;
      const copied=read(added);
      const saved=normalizeLearningState(JSON.parse(JSON.stringify(learningState))).wrongQuestions[0];
      const roundTrip=read(saved);
      currentWrongEditId=added.id;
      document.getElementById('wrongEditQuestion').value=question;
      document.getElementById('wrongEditNote').value='保留题目，只修改笔记';
      const beforeNote=JSON.stringify(added.recognitionSnapshot);
      saveWrongEdit();
      const notePreserved=JSON.stringify(added.recognitionSnapshot)===beforeNote;
      currentWrongEditId=added.id;
      document.getElementById('wrongEditQuestion').value='求整数 12 和 18 的最大公约数';
      saveWrongEdit();
      return {legacy,storedLocal,localBefore,retainedQuestionFacts,earlySnapshot,preserved,foreignGraph,
        foreignSnapshot,english,heading,copied,roundTrip,notePreserved,
        editCleared:added.recognitionSnapshot===null && added.difficulty==='' && added.knowledgePoints.length===0,
        noFabricatedGraph:entry.questionTeaching===null,normalizedFlat:normalized.registered_snapshot};
    },QUESTION);
    assert.deepEqual(results.legacy.ids,['count_perm_comb','set_operation']);
    assert.deepEqual(results.legacy.edges,[],'flat registered points do not manufacture course relations');
    assert.equal(results.noFabricatedGraph,true,'legacy registration has no invented quote-bearing graph');
    assert.equal(results.normalizedFlat,null,'unbound flat teaching is bound only by its owning question');
    assert.equal(results.storedLocal,true);
    assert.deepEqual(results.localBefore.ids,['count_inclusion','set_operation']);
    assert.deepEqual(results.retainedQuestionFacts.ids,['set_operation']);
    assert.ok(results.earlySnapshot.excludedIds.includes('count_inclusion'));
    assert.ok(!results.earlySnapshot.points.includes('容斥原理'));
    assert.deepEqual(results.preserved.ids,['count_perm_comb','function_composition','function_injection','function_mapping','set_operation']);
    assert.deepEqual(results.foreignGraph.ids,[],'explicit foreign question data cannot become a new registration');
    assert.equal(results.foreignSnapshot,null);
    assert.deepEqual(results.english.points,['集合运算','排列与组合']);
    assert.equal(results.heading.question,QUESTION);
    assert.deepEqual(results.copied.ids,['count_perm_comb','set_operation']);
    assert.deepEqual(results.roundTrip.ids,results.copied.ids);
    assert.equal(results.notePreserved,true);assert.equal(results.editCleared,true);
    assert.deepEqual(calls,[]);assert.deepEqual(errors,[]);
    console.log('PASS '+width+': local/legacy registration, full-point persistence, implicit names, method exclusions, exact source binding, copy/load and edit invalidation use no model request');
  } finally {await context.close();}
}

(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH
    ? {executablePath:process.env.CHROMIUM_EXECUTABLE_PATH}: {})});
  try {for(const width of [390,1440])await run(browser,width);}
  finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
