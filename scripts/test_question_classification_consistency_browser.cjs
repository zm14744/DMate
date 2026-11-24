/* Fixed problem metadata survives independent recognition paths and answers. */
'use strict';
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const question = '求集合 A={1,2} 与 B={2,3} 的交集，再从交集中选择一个元素';
const expected = {focus:['集合运算'],points:['集合运算','排列与组合'],ids:['count_perm_comb','set_operation']};

async function run(browser,width) {
  const context = await browser.newContext({viewport:{width,height:900},serviceWorkers:'block',
    ...(width < 760 ? {isMobile:true,hasTouch:true} : {})});
  const page = await context.newPage(), errors = [], calls = [];
  page.on('pageerror',error => errors.push(error.message));
  await page.route('**/auth/me',route => route.fulfill({contentType:'application/json',
    body:'{"configured":true,"authenticated":false}'}));
  await page.route(/\/(?:chat|ocr|classify|analyze-questions|conversation\/title)(?:\?|$)/,route => {
    calls.push(new URL(route.request().url()).pathname); return route.abort();
  });
  try {
    await page.goto(baseURL,{waitUntil:'networkidle'});
    await page.waitForFunction(() => typeof normalizeQuestionClassification === 'function' && !accountVerificationOperation);
    const result = await page.evaluate(async question => {
      await ensureKnowledgeGraphData();
      const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(question)))]
        .map(byte => byte.toString(16).padStart(2,'0')).join('');
      const fixed = {version:1,question,question_sha256:hash,catalog_revision:'fixture-catalog/1',
        category:'集合与关系',related_categories:['计数与组合'],knowledge_points:['集合运算'],
        related_knowledge_points:['排列与组合'],focus_points:['集合运算'],difficulty:'中等',
        node_ids:['set_operation','count_perm_comb'],focus_node_ids:['set_operation'],
        classification_source:'question_snapshot',classification_status:'fixed'};
      const teaching = (solution,reverse=false) => ({category:'计数与组合',related_categories:[],
        knowledge_points:['容斥原理'],related_knowledge_points:[],focus_points:['容斥原理'],difficulty:'困难',
        mode:'exercise',exercise_target_difficulty:'困难',question_classification:fixed,
        question_graph:{version:1,sources:{question,solution},classification_status:'semantic',
          classification_source:'catalog_semantic',classifier_revision:KNOWLEDGE_GRAPH_CLASSIFIER_REVISION,
          needs_review:false,nodes:[
            {id:'count_inclusion',usage:'used',evidence:[{source:'solution',quote:solution}]},
            {id:'set_operation',usage:'assessed',evidence:[{source:'question',quote:'交集'}]},
            {id:'count_perm_comb',usage:'assessed',evidence:[{source:'question',quote:'选择一个元素'}]}
          ].sort((a,b) => reverse ? b.id.localeCompare(a.id) : a.id.localeCompare(b.id)),edges:[]}});
      window.__fixedTeaching = teaching;
      const read = (value,text=question) => {
        const normalized = normalizeTeaching(value), registration = registeredQuestionSnapshot(normalized,text);
        const graph = DMateQuestionKnowledgeGraph.build(knowledgeGraphData.nodes,{questionText:text,
          questionGraph:normalized.question_graph,questionClassification:questionClassificationFor(normalized,text),
          registeredSnapshot:registration,solutionText:normalized.question_graph?.sources.solution || ''});
        return {focus:normalized.focus_points,points:registration?.points,ids:graph.nodes.map(node=>node.id).sort(),
          requestDifficulty:normalized.difficulty,requestMode:normalized.mode};
      };
      const variants = [teaching('方法一使用容斥原理'),teaching('方法二直接枚举',true)];
      const normalized = variants.map(value => read(value));
      const prior = {...teaching('已完成的答案'),question_classification:null};
      const merged = mergeQuestionTeaching(prior,{...teaching(''),question_graph:null},question);
      const mergedRead = read(merged);
      const matrix = {...fixed,question:'求矩阵\n1 0\n0 1 的秩'};
      const matrixDifferent = normalizeQuestionClassification(matrix,'求矩阵\n1 0 0 1 的秩');
      const cosmetic = normalizeQuestionClassification(matrix,' 求矩阵\r\n 1  0\r\n0  1 的秩 ');
      const foreign = normalizeQuestionClassification(fixed,'求整数12与18的最大公约数');
      const wrappers = [
        '【题目文字】\n'+question+'\n【图形信息】\n无\n【我的要求】\n给我提示',
        '【题干与公式识别】\n'+question+'\n【图形结构识别】\n无\n【我的要求】\n给我答案',
        question+'\n\n【图形信息】\n无',
        '【题目文字】'+question+'【图形信息】无【我的要求】提示'
      ].map(text => Boolean(normalizeQuestionClassification({...fixed,question:text},question)));
      const bareInline = normalizeQuestionClassification({...fixed,question:question+'【图形信息】无'},question);
      const graphQuestion = {...fixed,question:question+'\n【图形信息】\n顶点A连接B'};
      const differentGraph = normalizeQuestionClassification(graphQuestion,question+'\n【图形信息】\n顶点A连接C');
      const longPrefix='求下述集合的交集：'+('数学条件。'.repeat(6000));
      const differentTail = normalizeQuestionClassification({...fixed,question:longPrefix+'A={1}'},longPrefix+'A={2}');
      const sourceForeign = registeredQuestionSnapshot({...teaching(''),
        question_graph:{...teaching('').question_graph,sources:{question:'另一道不同题目',solution:''}}},question);
      sessions = ['text','ocr','ai'].map((source,index) => ({id:'fixed-'+source,name:source,nameSource:'user',
        messages: source==='ai' ? [
          {role:'user',messageId:'request-'+source,text:'出一道练习题',manualIsQuestion:false},
          {role:'ai',messageId:'problem-'+source,text:'【题目】\n'+question,generatedExercise:true,
            generatedQuestion:question,generatedAnswer:'{2}',generatedTeaching:variants[index%2]}
        ] : [{role:'user',messageId:'problem-'+source,source,
          text:source==='ocr' ? '【题目文字】\n'+question : question,
          ...(source==='ocr'?{ocrIsQuestion:true}:{manualIsQuestion:true}),questionTeaching:variants[index%2]}]
      }));
      currentId=sessions[0].id;deletedSessionIds=Object.create(null);learningState=createEmptyLearningState();
      const paths = [];
      for (const session of sessions) {
        const candidate = collectConversationQuestionCandidates(session).at(-1);
        applyQuestionCandidateAsCurrent(session,candidate);
        const saved = currentLearningQuestion(session,{category:'图论',knowledge_points:['欧拉图'],focus_points:['欧拉图']});
        const info = questionInfoFromChatMessage(session,candidate.index);
        const entry = addWrongQuestion({...info,referenceAnswer:'{2}',safeConfirmed:true},'','manual').entry;
        const stored = storeWrongQuestionGraphTeaching(entry,teaching('改用新的解题方法'),question,'改用新的解题方法');
        const wrongContext=wrongQuestionGraphContext(entry,null);
        const wrongGraph=DMateQuestionKnowledgeGraph.build(knowledgeGraphData.nodes,wrongContext);
        paths.push({source:session.name,focus:saved.focusPoints,points:info.recognitionSnapshot.points,
          wrongFocus:entry.focusPoints,wrongIds:wrongGraph.nodes.map(node=>node.id).sort(),stored});
      }
      const restored = normalizeLearningState(JSON.parse(JSON.stringify(learningState))).wrongQuestions.map(entry => {
        // An optional answer/graph can be cleared while its question's saved
        // classification remains available without another model request.
        entry.questionTeaching=null;entry.graphSolution='';
        const context=wrongQuestionGraphContext(entry,null);
        return {focus:entry.focusPoints,points:context.registeredSnapshot.points,
          ids:DMateQuestionKnowledgeGraph.build(knowledgeGraphData.nodes,context).nodes.map(node=>node.id).sort()};
      });
      renderAll();
      return {normalized,mergedRead,matrixDifferent,cosmetic:Boolean(cosmetic),foreign,sourceForeign,
        wrappers,bareInline,differentGraph,differentTail,paths,restored};
    },question);
    for (const value of [...result.normalized,result.mergedRead,...result.restored]) {
      assert.deepEqual(value.focus,expected.focus);assert.deepEqual(value.points,expected.points);
      assert.deepEqual(value.ids,expected.ids,'Answer-only methods cannot change a question’s assessed scope');
    }
    assert.equal(result.normalized[0].requestDifficulty,'困难','Explicit exercise target difficulty remains separate');
    assert.equal(result.normalized[0].requestMode,'exercise','Classification cannot change the requested tutoring mode');
    for(const value of result.paths) {
      assert.deepEqual(value.focus,expected.focus,value.source);assert.deepEqual(value.points,expected.points,value.source);
      assert.deepEqual(value.wrongFocus,expected.focus,value.source);assert.deepEqual(value.wrongIds,expected.ids,value.source);
      assert.equal(value.stored,true);
    }
    assert.equal(result.matrixDifferent,null,'Matrix line boundaries cannot reuse another question’s classification');
    assert.equal(result.cosmetic,true,'CRLF and cosmetic horizontal spacing keep the same question');
    assert.equal(result.foreign,null);assert.equal(result.sourceForeign,null,'A foreign answer graph cannot bind a local question snapshot');
    assert.deepEqual(result.wrappers,[true,true,true,true],'Known OCR presentation wrappers preserve the same complete question');
    assert.equal(result.bareInline,null,'Ordinary inline question text is not mistaken for an OCR protocol marker');
    assert.equal(result.differentGraph,null,'Actual graph conditions remain part of a question’s identity');
    assert.equal(result.differentTail,null,'Full source tails cannot be truncated when comparing question identity');
    for(const source of ['text','ocr','ai']) {
      await page.evaluate(async source => {
        closeKnowledgeGraph();currentId='fixed-'+source;renderAll();await openKnowledgeGraph();
        selectKnowledgeGraphDisplayMode('focus');
      },source);
      await page.locator('#knowledgeGraphCanvas .kg-mobile-node,#knowledgeGraphCanvas .kg-node-group').first().waitFor();
      const drawn=await page.locator('#knowledgeGraphCanvas .kg-mobile-node,#knowledgeGraphCanvas .kg-node-group')
        .evaluateAll(nodes=>nodes.map(node=>node.dataset.knowledgeNodeId).sort());
      assert.deepEqual(drawn,expected.ids,source+': actual renderer uses fixed scope');
      assert.match(await page.locator('#info').textContent(),/最近一题难点：集合运算/);
    }
    assert.deepEqual(errors,[]);assert.deepEqual(calls,[],'Viewing, saving and restoring fixed results needs no inference');
    console.log('PASS '+width+': manual/OCR/generated recognition, differing answers, history, wrong-book persistence, source binding and explicit exercise settings remain consistent');
  } finally {await context.close();}
}

(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH
    ?{executablePath:process.env.CHROMIUM_EXECUTABLE_PATH}: {})});
  try {for(const width of [390,1440])await run(browser,width);}
  finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
