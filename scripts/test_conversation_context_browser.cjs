/* Real request-payload regressions; /chat responses are local fixtures, not model calls. */
'use strict';
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const user = text => ({role:'user', text});
const ai = text => ({role:'ai', text});
const problem = text => ({role:'user',text,manualIsQuestion:true});
const textOf = messages => messages.map(message => message.content).join('\n');
(async()=>{
 const browser = await chromium.launch({headless:true,
  ...(process.env.CHROMIUM_EXECUTABLE_PATH ? {executablePath:process.env.CHROMIUM_EXECUTABLE_PATH} : {})});
 try {
  const page = await browser.newPage();
  const payloads = [];
  await page.route('**/chat', route => {
   payloads.push(route.request().postDataJSON());
   return route.fulfill({contentType:'text/event-stream',body:'event: final\ndata: '+JSON.stringify({reply:'已根据本轮要求继续。'})+'\n\n'});
  });
  await page.route('**/analyze-questions', route=>route.fulfill({contentType:'application/json',body:'{"entries":[]}'}));
  await page.goto(baseURL,{waitUntil:'networkidle'});
  const build = async (messages, navigate=false) => page.evaluate(({messages,navigate})=>{
   newChat(); const session=getCurrent(); session.messages=messages;
   let target=null;
   if(navigate){target=collectConversationQuestionCandidates(session)[0];session.messages.at(-1).targetQuestionFingerprint=questionCandidateFingerprint(target);}
   return {messages:buildApiMessages(session,target), exercise:isSessionExerciseRequest(session,messages.at(-1).text),
    fresh:looksLikeActualLearningProblem(messages.at(-1))};
  },{messages,navigate});
  const origin='请生成一段用于测试数学公式渲染的文字，覆盖行内与独立公式、矩阵和证明，所有部分用中文。TASK_ORIGIN';
  const explanation='第一段展示矩阵，第二段展示证明。ASSISTANT_EXPLANATION';
  for(const followup of ['再来一个','继续','按上面的要求再写一个','请说详细一点','能不能再具体些','用表格','把第二段缩短','再给我一个要求更多的版本','再来一个，改用英文']){
   const result=await build([user(origin),ai(explanation),user(followup)]);
   assert.equal(result.exercise,false,followup+' stays ordinary conversation');
   assert.equal(result.fresh,false,followup+' is not a new standalone problem');
   assert.ok(textOf(result.messages).includes('TASK_ORIGIN'),followup+' retains the original task');
   assert.ok(textOf(result.messages).includes('ASSISTANT_EXPLANATION'),followup+' retains the previous answer');
   assert.equal(result.messages.at(-1).content,followup);
  }
  await page.evaluate(async()=>{renderChat();return await requestAiReply(getCurrent());});
  assert.equal(payloads.at(-1).request_kind,'chat');
  assert.ok(textOf(payloads.at(-1).messages).includes('TASK_ORIGIN'));
  console.log('PASS ordinary generation, unlisted follow-ups and actual /chat payload preserve instructions and answer');

  const question='设整数 n 为奇数，证明 n 的平方也是奇数。QUESTION_ONE';
  const preference='以后都用中文，而且先只给提示。PERSISTENT_PREFERENCE';
  let result=await build([problem(question),ai('设 n=2k+1。FIRST_EXPLANATION'),user(preference),ai('这一步使用奇数的定义。LATEST_EXPLANATION'),user('这一步为什么')]);
  for(const marker of ['QUESTION_ONE','PERSISTENT_PREFERENCE','LATEST_EXPLANATION'])assert.ok(textOf(result.messages).includes(marker),marker);
  result=await build([problem(question),ai('取 n=2。OLD_DATA'),user('不对，n 应为3，不是2；撤销只给提示的要求，给完整解答。CORRECTION'),ai('已更正为3。CORRECTED_ANSWER'),user('继续')]);
  for(const marker of ['CORRECTION','CORRECTED_ANSWER'])assert.ok(textOf(result.messages).includes(marker),marker);
  for(const followup of ['证明这个结论','Prove this conclusion','改成英文']){
   result=await build([problem(question),ai('这里得到平方仍为奇数。CURRENT_CONCLUSION'),user(followup)]);
   assert.equal(result.fresh,false,followup+' does not reset the task');
   assert.ok(textOf(result.messages).includes('CURRENT_CONCLUSION'));
  }
  console.log('PASS mathematical follow-ups retain constraints, corrections and recent reasoning');

  const second='已知整数84和30，求它们的最大公约数。QUESTION_TWO';
  result=await build([user(preference),problem(question),ai('OLD_TOPIC_ANSWER'),problem(second)]);
  assert.ok(!textOf(result.messages).includes('QUESTION_ONE'));
  assert.ok(!textOf(result.messages).includes('OLD_TOPIC_ANSWER'));
  assert.ok(textOf(result.messages).includes('PERSISTENT_PREFERENCE'));
  result=await build([problem(question),ai('FIRST_TOPIC_ANSWER'),problem(second),ai('SECOND_TOPIC_ANSWER'),user('第一题')],true);
  assert.ok(textOf(result.messages).includes('QUESTION_ONE'));
  assert.ok(textOf(result.messages).includes('FIRST_TOPIC_ANSWER'));
  assert.ok(!textOf(result.messages).includes('QUESTION_TWO'));
  assert.ok(!textOf(result.messages).includes('SECOND_TOPIC_ANSWER'));
  console.log('PASS new problem and explicit navigation isolate unrelated problem threads');

  const history=[user(origin),ai(explanation),user(preference),ai('记录偏好。')];
  for(let index=0;index<42;index++)history.push(user('请说详细一点，第'+index+'轮补充。'),ai('第'+index+'轮的解释。LATEST_'+index));
  history.push(user('继续'));
  result=await build(history);
  for(const marker of ['TASK_ORIGIN','PERSISTENT_PREFERENCE','LATEST_41'])assert.ok(textOf(result.messages).includes(marker),marker);
  assert.ok(result.messages.length<=64);
  assert.ok(Array.from(textOf(result.messages)).length<=100000+64);
  const latest='继续，并保留这个完整用户请求。'+ '甲'.repeat(19980);
  result=await build([user(origin),ai('较长回答。'+ '乙'.repeat(60000)),user(latest)]);
  assert.equal(result.messages.at(-1).content,latest,'latest request is never truncated');
  assert.ok(textOf(result.messages).includes('中间部分已省略'),'older oversized answer has explicit omission marker');
  const crowded=[user('以后所有回答都用中文。OLD_GLOBAL_PREFERENCE'),ai('已记录。'),user(origin),ai(explanation)];
  for(let index=0;index<75;index++)crowded.push(user('请说详细一点，第'+index+'轮继续。'),ai('第'+index+'轮的解释。CROWDED_LATEST_'+index));
  crowded.push(user('继续，保留最新要求。CROWDED_LATEST_USER'));
  result=await build(crowded);
  for(const marker of ['OLD_GLOBAL_PREFERENCE','TASK_ORIGIN','CROWDED_LATEST_74','CROWDED_LATEST_USER'])assert.ok(textOf(result.messages).includes(marker),marker+' survives >70 rounds');
  assert.ok(result.messages.length<=64);
  const originLarge=origin+'甲'.repeat(18000);
  const correction='不对，撤销旧条件，使用新的输入数据。RECENT_CORRECTION'+'乙'.repeat(18000);
  const latestAnswer='按新的条件重新整理。RECENT_ASSISTANT'+'丙'.repeat(19000);
  const latestLarge='继续，只处理最新更正后的数据。LATEST_USER'+'丁'.repeat(19000);
  result=await build([user('以后都保持中文。GLOBAL_LARGE'+'戊'.repeat(18000)),ai('收到。'),
   user(originLarge),ai('EARLY_ASSISTANT'+'己'.repeat(19500)),
   user('以后所有公式都标明变量范围。LATER_PREFERENCE'+'庚'.repeat(18000)),ai('中间说明。'+'辛'.repeat(19500)),
   user(correction),ai(latestAnswer),user(latestLarge)]);
  assert.equal(result.messages.at(-1).content,latestLarge);
  assert.ok(result.messages.some(message=>message.content===correction),'recent correction has priority over early assistant text');
  assert.ok(result.messages.some(message=>message.content===latestAnswer),'latest assistant has priority near the character budget');
  assert.ok(textOf(result.messages).includes('TASK_ORIGIN'));
  assert.ok(!textOf(result.messages).includes('EARLY_ASSISTANT'),'the earliest assistant is not privileged over current context');
  assert.ok(Array.from(textOf(result.messages)).length<=100000+64);
  console.log('PASS long threads retain task origin/preferences/latest answer within finite message and character budgets');

  result=await build([user('什么是欧拉图？'),ai('欧拉图的概念说明。CONCEPT_TOPIC'),user('出一道题')]);
  assert.equal(result.exercise,true);
  assert.ok(textOf(result.messages).includes('CONCEPT_TOPIC'),'unthemed exercise retains the current concept');
  result=await build([user('什么是欧拉图？'),ai('一个示例。CONCEPT_EXAMPLE'),user('再来一个')]);
  assert.equal(result.exercise,false,'another example after a concept is not forced into exercise');
  result=await build([user('请生成一段排版测试文字。'),ai('渲染测试内容。'),user('再来一个')]);assert.equal(result.exercise,false);
  result=await build([user('出一道图论题'),ai('设 G 为有限树，证明 G 存在叶子。'),user('再来一个')]);assert.equal(result.exercise,true);
  for(const origin of ['请生成一段排版测试文字。','出一道图论题']){
   for(const format of ['请说详细一点','用表格','把第二段缩短']){
    result=await build([user(origin),ai('上一轮回答。'),user(format),ai('更新格式后的回答。'),user('再来一个')]);
    assert.equal(result.exercise,origin==='出一道图论题',origin+'/'+format+' retains the task source');
   }
  }
  result=await build([problem(question),ai('OLD_PROBLEM_ANSWER'),user(origin),ai(explanation),user('再来一个')]);
  assert.equal(result.exercise,false);
  assert.ok(!result.messages.at(-1).content.includes('【当前指向题目】'),'later ordinary task cancels the stale problem anchor');
  assert.ok(textOf(result.messages).includes('TASK_ORIGIN'));
  result=await build([user('出一道图论题，所有小问使用三段格式。EXERCISE_FORMAT'),
   {role:'ai',text:'设 G 为有限树，证明 G 存在叶子。',generatedQuestion:'设 G 为有限树，证明 G 存在叶子。'},user('再来一个')]);
  assert.ok(textOf(result.messages).includes('EXERCISE_FORMAT'),'generated-question context preserves the original generation constraints');
  console.log('PASS generic continuation is disambiguated from real exercise context');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
