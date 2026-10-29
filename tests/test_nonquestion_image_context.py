"""Actual chat handler keeps supporting images out of question statistics.

Only transport, UI painting and knowledge-service boundaries are injected.
The real request handler, scoped API builder, signed-context selectors and
learning update function execute in Node. No model or network is called.
"""
import json
import subprocess

import pytest

from test_ocr_batch_frontend import signed
from test_semantic_chat_snapshot_frontend import ROOT, NODE


PROGRAM = r"""
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/script.js','utf8');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
function actual(name) {
  const expression=new RegExp('(?:async )?function '+name+'\\(');
  const match=expression.exec(source);
  if(!match)throw Error('Missing actual function: '+name);
  const following=source.slice(match.index+match[0].length);
  const next=/\n(?:async )?function [A-Za-z_$]/.exec(following);
  return source.slice(match.index,next?match.index+match[0].length+next.index:source.length);
}
const calls=[],events=[],classifications=[],applied=[],errors=[],notices=[],typing=[],wrong=[];
const originalTeaching={mode:'full_solution',knowledge_points:['A knowledge'],focus_points:[],
  related_knowledge_points:[],category:'A category',difficulty:'中等'};
const originalQuestion={text:'A original problem',source:'ocr',sessionId:'s'};
const session={id:'s',messages:input.messages,teaching:structuredClone(originalTeaching),
  learningQuestion:structuredClone(originalQuestion)};
const responseTeaching={mode:input.mode||'full_solution',knowledge_points:['B knowledge'],
  focus_points:[],related_knowledge_points:[],category:'B category',difficulty:'困难'};
const currentA=()=>({index:0,role:'user',source:'ocr',
  text:sandbox.ocrBatchQuestion(session.messages[0].semanticContexts,'rendered_question_text')});
const sandbox={console:{error:(...values)=>errors.push(values.map(String).join(' '))},
  TextEncoder,AbortController,structuredClone,Date,Map,Set,
  sessions:[session],currentId:'s',deletedSessionIds:{},activeAiRequests:new Map(),
  FALLBACK_API_CONTEXT_MESSAGES:6,learningState:{wrongQuestions:[]},
  normalizeRetestSession:()=>null,normalizeTeaching:value=>value||null,
  getLatestUserMessage:s=>[...s.messages].reverse().find(m=>m.role==='user'),
  sessionBusyKey:id=>String(id),setSessionBusy(){},
  cutQuestionAfterMetaSections:text=>String(text).split('【我的要求】')[0].trim(),
  isQuestionNavigationFollowUp:text=>/上一题|第一题/.test(text||''),
  isExerciseRequestText:text=>/出一道|给我出题/.test(text||''),
  hasExplicitExerciseGenerationCue:text=>/出一道|给我出题/.test(text||''),
  looksLikeActualLearningProblem:message=>message?.source==='ocr'
    ? message.ocrIsQuestion===true : message?.manualIsQuestion===true,
  isShortLearningFollowUp:text=>/继续|为什么|再解释/.test(text||''),
  isContextualExerciseRequest:()=>false,resolveExerciseReference:()=>null,
  resolveQuestionNavigationCandidate:()=>currentA(),findQuestionCandidateByFingerprint:()=>currentA(),
  questionNavigationFailureMessage:()=> 'No target',
  activeQuestionCandidateFromHistory:()=>currentA(),currentQuestionCandidateFromLearningState:()=>currentA(),
  candidateTeachingSnapshot:(s,c)=>c?.index===0?originalTeaching:null,
  analyzeSingleQuestionTeaching:async text=>{classifications.push(text);return responseTeaching;},
  applyQuestionCandidateAsCurrent:(s,c,t)=>{applied.push(c.index);s.learningQuestion={text:c.text};s.teaching=t;},
  wrongQuestionFingerprint:text=>String(text||''),
  sanitizeStoredWrongQuestionText:text=>String(text||'').trim(),
  extractQuestionOnlyFromMessage:message=>sandbox.extractOcrQuestionPayload(message.text),
  updateKnowledge:(points,type)=>events.push({type,points}),
  inferAnswerAssessment:()=>input.assessment||'correct',
  currentLearningQuestion:()=>session.learningQuestion,
  addWrongQuestion:value=>{wrong.push(value);return {countAsMistake:true};},
  wrongBookLearningPoints:()=>['A knowledge'],
  extractAiQuestionPayload:text=>text,
  recoverGeneratedQuestionFromAssistant:()=>'',
  processWrongQuestionRetestReply:()=>false,rollbackRetestAfterRequestFailure(){},
  showAssistantMessage:(s,text)=>notices.push(text),
  startTyping:(text,s)=>typing.push({text,sessionId:s.id}),
  saveState(){},saveLearningState(){},renderLearningSummary(){},renderInfo(){},renderChat(){},
  renderSessions(){},showCopyToast(){},fallbackHttpError:()=> 'HTTP error',
  document:{getElementById:()=>null},
  parseResponseJson:response=>response.json(),
  fetch:async(url,options)=>{
    calls.push({url,body:JSON.parse(options.body)});
    if(input.deleteDuringReply)sandbox.sessions=[];
    if(input.replaceDuringReply)session.messages.push({role:'user',text:'A newer user request'});
    return {ok:!input.httpError,status:input.httpError?500:200,json:async()=>({
      reply:input.emptyReply?'':'材料的解释',teaching:responseTeaching,
      ...(input.mode==='exercise'?{generated_question:'意外产生的新题',generated_exercise:true}:{}),
      ...(input.httpError?{error:'Expected service failure'}:{})})};
  }
};
vm.createContext(sandbox);
const names=['sanitizeSemanticContext','extractOcrQuestionPayload','ocrBatchQuestion',
  'sanitizeSemanticContexts','sanitizeOcrGroup','supportingOcrFollowUpCandidate',
  'semanticContextForRequest','buildTargetQuestionApiText','buildApiMessages',
  'questionCandidateFingerprint','isRecordableOcrQuestionMessage',
  'attachTeachingSnapshotToLatestQuestion','processLearningFromReply',
  'isHistorySystemMetaText','looksLikeFormalStudyQuestionForHistory','collectConversationQuestionCandidates',
  'addAssistantMessage','throwIfAiRequestCancelled','requestAiReply'];
vm.runInContext(names.map(actual).join('\n'),sandbox);
(async()=>{
  const statuses=[];
  for(const message of input.steps||[null]){
    if(message)session.messages.push(message);
    const options=input.normalTyping?{}:{completeImmediately:true,
      expectedUserMessage:sandbox.getLatestUserMessage(session)};
    statuses.push(await sandbox.requestAiReply(session,options));
  }
  const history=sandbox.collectConversationQuestionCandidates(session);
  process.stdout.write(JSON.stringify({calls,events,classifications,applied,errors,notices,typing,wrong,
    statuses,session,originalTeaching,originalQuestion,history}));
})().catch(error=>{process.stderr.write(String(error.stack));process.exitCode=1;});
"""


def image_message(numbers, *, flags=None):
    contexts = [signed(index) for index in numbers]
    flags = [False] * len(contexts) if flags is None else flags
    question = '\n\n'.join(f'【图片 {i}】\n'+context['question_text']
                            for i, context in enumerate(contexts, 1))
    rendered = '\n\n'.join(f'【图片 {i}】\n'+context['rendered_question_text']
                            for i, context in enumerate(contexts, 1))
    return {'role': 'user', 'source': 'ocr', 'ocrIsQuestion': any(flags),
            'text': rendered+'\n\n【我的要求】\n请解释这些图片',
            'apiText': '【当前指向题目】\n'+question+'\n【当前指向题目结束】\n请解释这些图片',
            'semanticContexts': contexts,
            'ocrGroup': {'id': '|'.join(c['request_id'] for c in contexts), 'groupId': '2',
                         'members': [{'requestId': c['request_id'], 'isQuestion': flag}
                                     for c, flag in zip(contexts, flags)]}}


def run(*, messages=None, **options):
    if NODE is None:
        pytest.skip('Node unavailable')
    payload = {'messages': messages or [image_message([1], flags=[True]),
                                       {'role': 'ai', 'text': 'A earlier answer'}, image_message([2, 3])],
               **options}
    process = subprocess.run([NODE, '-e', PROGRAM], cwd=ROOT, input=json.dumps(payload, ensure_ascii=False),
                             text=True, capture_output=True, check=True)
    result = json.loads(process.stdout)
    assert not result['errors'], result['errors']
    return result


def assert_a_unchanged(result):
    assert result['session']['teaching'] == result['originalTeaching']
    assert result['session']['learningQuestion'] == result['originalQuestion']
    assert result['session']['messages'][0].get('questionTeaching') is None
    assert result['events'] == result['wrong'] == result['applied'] == result['classifications'] == []
    assert [candidate['index'] for candidate in result['history']] == [0]


@pytest.mark.parametrize('mode,assessment', [('full_solution', 'correct'), ('check_answer', 'correct'),
                                            ('check_answer', 'wrong'), ('exercise', 'correct')])
def test_nonquestion_group_reply_cannot_change_question_a_or_learning_statistics(mode, assessment):
    result = run(mode=mode, assessment=assessment)
    assert result['statuses'] == [{'status': 'success'}]
    assert_a_unchanged(result)
    assert [c['request_id'] for c in result['calls'][0]['body']['semantic_contexts']] == ['picture-2', 'picture-3']
    reply = result['session']['messages'][-1]
    assert reply['role'] == 'ai' and reply['generatedQuestion'] == ''
    assert reply['generatedExercise'] is False


def test_two_successive_material_followups_keep_only_b_without_classifying_it_as_a_problem():
    result = run(steps=[None, {'role': 'user', 'text': '继续解释'},
                       {'role': 'user', 'text': '为什么这样呢'}])
    assert result['statuses'] == [{'status': 'success'}] * 3
    assert_a_unchanged(result)
    for call in result['calls']:
        assert call['url'] == '/chat'
        assert [c['request_id'] for c in call['body']['semantic_contexts']] == ['picture-2', 'picture-3']
        content = '\n'.join(message['content'] for message in call['body']['messages'])
        assert '第1张图片求度数' not in content and '第2张图片求度数' in content


def test_invalid_material_b_snapshot_blocks_even_a_second_followup_without_falling_back_to_a():
    material = image_message([2, 3])
    material['semanticContexts'][0].pop('confirmation_token')
    result = run(messages=[image_message([1], flags=[True]), {'role': 'ai', 'text': 'A earlier answer'},
                           material, {'role': 'ai', 'text': 'B earlier explanation'},
                           {'role': 'user', 'text': '继续解释'}, {'role': 'ai', 'text': 'B continuation'}],
                 steps=[{'role': 'user', 'text': '为什么这样呢'}])
    assert result['statuses'] == [{'status': 'error'}]
    assert result['calls'] == []
    assert_a_unchanged(result)
    assert len(result['notices']) == 1 and '确认' in result['notices'][0]


def test_explicit_navigation_then_followup_stays_with_question_a_instead_of_material_b():
    result = run(steps=[{'role': 'user', 'text': '上一题再解释'}, {'role': 'user', 'text': '继续解释'}])
    assert result['statuses'] == [{'status': 'success'}] * 2
    assert [[c['request_id'] for c in call['body']['semantic_contexts']]
            for call in result['calls']] == [['picture-1'], ['picture-1']]


def test_a_new_typed_problem_does_not_inherit_supporting_images():
    result = run(steps=[{'role': 'user', 'text': '新题：求集合交集', 'manualIsQuestion': True}])
    assert result['statuses'] == [{'status': 'success'}]
    assert 'semantic_contexts' not in result['calls'][0]['body']
    assert 'semantic_context' not in result['calls'][0]['body']


def test_mixed_group_is_one_recorded_problem_with_both_signed_documents():
    result = run(messages=[image_message([1], flags=[True]), image_message([2, 3], flags=[True, False])])
    assert result['statuses'] == [{'status': 'success'}]
    assert len([event for event in result['events'] if event['type'] == 'seen']) == 1
    assert len(result['calls'][0]['body']['semantic_contexts']) == 2
    assert result['session']['messages'][1]['questionTeaching']['category'] == 'B category'
    assert [candidate['index'] for candidate in result['history']] == [0, 1]


@pytest.mark.parametrize('failure', ['deleteDuringReply', 'replaceDuringReply'])
def test_cancelled_group_response_cannot_write_teaching_statistics_or_an_answer(failure):
    result = run(**{failure: True})
    assert result['statuses'] == [{'status': 'cancelled'}]
    assert_a_unchanged(result)
    assert not any(message.get('text') == '材料的解释' for message in result['session']['messages'])


def test_normal_chat_call_retains_typing_instead_of_queue_only_immediate_commit():
    result = run(normalTyping=True)
    assert result['statuses'] == [{'status': 'success'}]
    assert result['typing'] == [{'text': '材料的解释', 'sessionId': 's'}]
    assert result['session']['messages'][-1]['role'] == 'user'
