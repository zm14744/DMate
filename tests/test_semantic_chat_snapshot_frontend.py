"""Execute the actual JS snapshot/upload/request fragments with synthetic data.

No browser, OCR, model, or network is invoked. These are transport and storage
contracts, not an image-recognition or deployed-application certification.
"""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
PROGRAM = r"""
const fs = require('node:fs'), vm = require('node:vm');
const src = fs.readFileSync('static/script.js', 'utf8');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
function block(start, end) {
  const a=src.indexOf(start), b=src.indexOf(end,a+start.length);
  if(a<0||b<0) throw Error('missing actual source fragment '+start);
  return src.slice(a,b);
}
const requests=[], notices=[];
const sandbox={console, TextEncoder, AbortController, MAX_IMAGE_BYTES:8*1024*1024,
  STORAGE_KEY:'test', FALLBACK_API_CONTEXT_MESSAGES:6,
  sessions:[{id:'s',name:'synthetic',messages:[]}],currentId:'s',deletedSessionIds:{},
  ocrReviewInProgress:false,ocrRequestInFlight:false,ocrAbortController:null,ocrRequestId:'',
  FormData:class{append(){}},
  isCurrentSessionTyping:()=>false,isSessionBusy:()=>false,
  refreshInputAvailability:()=>{},saveState:()=>{},renderChat:()=>{},renderSessions:()=>{},renderInfo:()=>{},
  maybeAutoNameSession:()=>{},makeOcrRequestId:()=> 'synthetic-request',
  showCurrentError:x=>notices.push(x),showAssistantMessage:(s,x)=>notices.push(x),
  parseResponseJson:r=>r.json(),reviewRecognizedQuestion:async()=>input.reviewed,
  shouldPersistClientState:()=>true,normalizeDeletedSessionIds:x=>x||{},
  normalizeTeaching:x=>x||null,normalizeLearningQuestion:x=>x||null,normalizeRetestSession:x=>x||null,
  localStorage:{getItem:()=>JSON.stringify(input.stored)},
  cutQuestionAfterMetaSections:t=>String(t).split('【我的要求】')[0].trim(),
  looksLikeActualLearningProblem:m=>m?.manualIsQuestion===true||/^新题/.test(m?.text||''),
  isQuestionNavigationFollowUp:t=>/第一题|第二题|上一题/.test(t||''),
  isExerciseRequestText:t=>/出练习/.test(t||''),hasExplicitExerciseGenerationCue:t=>/出练习/.test(t||''),
  isContextualExerciseRequest:()=>false,resolveExerciseReference:()=>null,
  isShortLearningFollowUp:t=>/继续|为什么/.test(t||''),
  questionCandidateFingerprint:c=>c?.text||'',activeQuestionCandidateFromHistory:()=>null,
  currentQuestionCandidateFromLearningState:()=>null,
  fetch:async(url,options)=>{
    requests.push({url,body:url==='/chat'?JSON.parse(options.body):null});
    return {ok:true,json:async()=>url==='/ocr'?input.response:{}};
  }
};
sandbox.getCurrent=()=>sandbox.sessions.find(x=>x.id===sandbox.currentId);
vm.createContext(sandbox);
const fragments = [
  block('function sanitizeSemanticContext(', 'function saveState('),
  block('function extractOcrQuestionPayload(', 'function countTopLevelQuestionParts('),
  block('function buildTargetQuestionApiText(', 'async function parseResponseJson('),
  block('function mergeCloudMessage(', 'function cloudHash('),
  block('function loadState(', 'function escapeRawHtml('),
  block('async function handleImageSelected(', 'function isClearlyNonQuestionWrongBookText(')
];
const chat = block('        const apiMessages = buildApiMessages(session, requestTargetCandidate);',
                   '        const data = await parseResponseJson(response);');
fragments.push(`async function capturedExistingChat(session, requestTargetCandidate=null, options={}) {
 const latestIsExerciseRequest=!!options.exerciseRequest,latestIsRetestGeneration=!!options.retestGeneration;
 const activeRequest={controller:new AbortController()},asksForFullSolution=true;
 const solutionReference=undefined,questionContext=undefined,preferredEffort=undefined;
 const retestReferenceQuestion='',retestBeforeRequest=null,exerciseReference=null;
 ${chat}
 return response;
}`);
vm.runInContext(fragments.join('\n'),sandbox);
sandbox.requestAiReply=s=>sandbox.capturedExistingChat(s);
function ocrMessage(source='a', label='same') {
  const question='【题目文字】\n求'+label+'的度数\n\n【图形信息】\n'+label+'显示边表';
  const internal='【题目文字】\n求'+label+'的度数\n\n【图形信息】\n'+label+'内部完整边表';
  const data={graph_structures:input.graphs,diagnostics:{semantic_workflow:{source_sha256:source.repeat(64)}}};
  return {role:'user',source:'ocr',ocrIsQuestion:true,text:question,apiText:internal,
    semanticContext:sandbox.buildOcrSemanticContext(data,'求'+label+'的度数',question,internal)};
}
(async()=>{
 let result;
 if(input.operation==='upload') {
   await sandbox.handleImageSelected({target:{files:[{type:'image/png',size:100}],value:'selected'}});
   result={requests,messages:sandbox.sessions[0].messages,notices};
 } else if(input.operation==='sanitize') {
   result=sandbox.sanitizeSemanticContext(input.context,input.message??null);
 } else if(input.operation==='load') {
   result={loaded:sandbox.loadState(),sessions:sandbox.sessions};
 } else if(input.operation==='merge') {
   const left=ocrMessage(),right={...left};delete right.semanticContext;
   if(input.tamper) right.text='a different question';
   result=sandbox.mergeCloudMessage(left,right);
 } else if(input.operation==='select') {
   const first=ocrMessage('a','old'),second=ocrMessage('b','new');
   const messages=[first,{role:'ai',text:'old answer'},second,{role:'ai',text:'new answer'}];
   const index=input.targetIndex??0, selected=messages[index];
   let target={index,role:selected.role,source:selected.source||'',
     text:selected.semanticContext?.rendered_question_text||selected.text};
   const latest={role:'user',text:input.latestText||'继续解释',...input.latest};
   if(input.generatedTarget) {
     messages[3]={role:'ai',text:'新生成练习',generatedQuestion:'求另一题'};
     target={index:3,role:'ai',text:'求另一题'};
   }
   if(input.tamperTarget) target.text='unrelated target';
   messages.push(latest);
   const session={messages};
   if(input.historyOnly) {
     const api=[{role:'user',content:first.apiText},{role:'user',content:'unrelated current request'}];
     result=sandbox.semanticContextForRequest(session,target,api,{})??null;
   } else {
     await sandbox.capturedExistingChat(session,target,input.options||{});
     result=requests[0].body;
   }
 }
 process.stdout.write(JSON.stringify(result??null));
})().catch(e=>{console.error(e);process.exitCode=1;});
"""


def run_js(payload):
    if NODE is None:
        pytest.skip('Node unavailable; JS contract was not executed')
    process = subprocess.run([NODE, '-e', PROGRAM], cwd=ROOT,
                             input=json.dumps(payload, ensure_ascii=False), text=True,
                             capture_output=True, check=True)
    return json.loads(process.stdout)


def graphs():
    return [{'id': 'G1', 'name': 'Literal graph', 'directed': True, 'weighted': True,
             'multigraph': True, 'complete': True, 'bbox': [0, 0, 1, 1],
             'vertices': [{'id': 'a', 'label': 'v₂', 'x': .2, 'y': .4},
                          {'id': 'A', 'label': 'V₂', 'x': .8, 'y': .4},
                          {'id': 'isolated', 'label': None, 'isolated_confirmed': True}],
             'edges': [{'id': 'loop', 'from': 'a', 'to': 'a', 'direction': 'forward', 'weight': 0,
                        'edge_label': 'e₁', 'color': 'red', 'style': 'solid', 'status': 'accepted'},
                       {'id': 'p1', 'from': 'a', 'to': 'A', 'direction': 'forward', 'weight': '-5',
                        'edge_label': 'e₂', 'color': 'blue', 'style': 'dashed', 'status': 'accepted',
                        'multiplicity': 1, 'parallel_count': 2, 'path': [[.2, .4], [.8, .4]]},
                       {'id': 'p2', 'from': 'a', 'to': 'A', 'direction': 'forward', 'weight': 'x+1',
                        'edge_label': 'E₂', 'color': 'red', 'style': 'dotted', 'status': 'accepted',
                        'pixel_evidence': {'supported': True}},
                       {'id': 'reverse', 'from': 'A', 'to': 'a', 'direction': 'forward', 'weight': -2,
                        'edge_label': None, 'color': 'black', 'style': 'solid', 'status': 'pending'}]}]


def context():
    return {'document': {'body_text': '求度数', 'graphs': graphs(), 'private': 'drop'},
            'question_text': '【题目文字】\n求度数\n\n【图形信息】\n内部边表',
            'rendered_question_text': '求度数\n\n【图形信息】\n显示边表',
            'source_sha256': 'A'*64, 'private': 'drop'}


def response():
    return {'text': '求度数', 'visual_text': '内部边表', 'graph_structures': graphs(),
            'diagnostics': {'semantic_workflow': {'source_sha256': 'a'*64}}}


def reviewed():
    return {'text': '求度数', 'visualText': '显示边表', 'analysisVisualText': '内部边表',
            'userRequest': '完整解答', 'ocrIsQuestion': True}


def test_actual_upload_confirmation_saves_snapshot_and_existing_chat_sends_it_once():
    result = run_js({'operation': 'upload', 'response': response(), 'reviewed': reviewed()})
    assert [r['url'] for r in result['requests']] == ['/ocr', '/chat']
    assert len(result['messages']) == 1
    saved = result['messages'][0]['semanticContext']
    sent = result['requests'][1]['body']['semantic_context']
    assert sent == saved
    assert sent['question_text'] in result['requests'][1]['body']['messages'][-1]['content']
    assert sent['rendered_question_text'] == '求度数\n\n【图形信息】\n显示边表'
    assert [n['label'] for n in sent['document']['graphs'][0]['vertices']] == ['v₂', 'V₂', None]
    assert [(e['from'], e['to']) for e in sent['document']['graphs'][0]['edges']] == [
        ('a', 'a'), ('a', 'A'), ('a', 'A'), ('A', 'a')]
    assert [e['weight'] for e in sent['document']['graphs'][0]['edges']] == [0, '-5', 'x+1', -2]
    assert [e['edge_label'] for e in sent['document']['graphs'][0]['edges']] == ['e₁', 'e₂', 'E₂', None]


def test_actual_upload_cancel_neither_saves_snapshot_nor_calls_chat():
    result = run_js({'operation': 'upload', 'response': response(), 'reviewed': None})
    assert [r['url'] for r in result['requests']] == ['/ocr']
    assert result['messages'] == []


@pytest.mark.parametrize('index,sha', [(0, 'a'*64), (2, 'b'*64)])
def test_followup_uses_exact_target_message_not_last_ocr(index, sha):
    result = run_js({'operation': 'select', 'graphs': graphs(), 'targetIndex': index})
    assert result['semantic_context']['source_sha256'] == sha
    assert result['semantic_context']['rendered_question_text'] in result['messages'][-1]['content']


def test_explicit_question_navigation_still_works_when_input_mode_is_question():
    result = run_js({'operation': 'select', 'graphs': graphs(), 'targetIndex': 0,
                     'latestText': '上一题为什么', 'latest': {'manualIsQuestion': True,
                     'targetQuestionFingerprint': 'resolved-old-question'}})
    assert result['semantic_context']['source_sha256'] == 'a'*64
    assert 'old显示边表' in result['messages'][-1]['content']


@pytest.mark.parametrize('extra', [
    {'latest': {'manualIsQuestion': True}, 'latestText': '新题：求2+2'},
    {'latestText': '新题：求另一个图'},
    {'latestText': '出练习', 'options': {'exerciseRequest': True}},
    {'options': {'retestGeneration': True}},
    {'latest': {'isRetestPrompt': True}},
    {'latest': {'isRetestAnswer': True}},
    {'generatedTarget': True},
    {'tamperTarget': True},
])
def test_new_question_exercise_retest_or_unrelated_target_does_not_inherit_old_graph(extra):
    result = run_js({'operation': 'select', 'graphs': graphs(), **extra})
    assert 'semantic_context' not in result


def test_anchor_in_earlier_message_does_not_bind_unrelated_current_request():
    assert run_js({'operation': 'select', 'graphs': graphs(), 'historyOnly': True}) is None


def test_snapshot_whitelist_strips_auxiliary_fields_without_changing_instances():
    original = context()
    result = run_js({'operation': 'sanitize', 'context': original})
    assert result['source_sha256'] == 'a'*64
    assert set(result) == {'document', 'question_text', 'rendered_question_text', 'source_sha256'}
    assert set(result['document']) == {'body_text', 'graphs'}
    text = json.dumps(result)
    assert all(name not in text for name in ('bbox', 'path', 'pixel_evidence', 'private'))
    assert all('x' not in vertex and 'y' not in vertex for vertex in result['document']['graphs'][0]['vertices'])
    assert len(result['document']['graphs'][0]['edges']) == 4
    assert result['document']['graphs'][0]['edges'][-1]['status'] == 'pending'


@pytest.mark.parametrize('bad_sha', ['', 'g'*64, 'a'*63, 3, None])
def test_invalid_source_hash_cannot_be_persisted_or_sent(bad_sha):
    value = context(); value['source_sha256'] = bad_sha
    assert run_js({'operation': 'sanitize', 'context': value}) is None


@pytest.mark.parametrize('capacity', ['graphs', 'vertices', 'edges', 'bytes'])
def test_capacity_rejects_whole_snapshot_instead_of_truncating_a_graph(capacity):
    value = context()
    if capacity == 'graphs': value['document']['graphs'] *= 65
    if capacity == 'vertices': value['document']['graphs'][0]['vertices'] *= 34
    if capacity == 'edges': value['document']['graphs'][0]['edges'] *= 76
    if capacity == 'bytes':
        # All per-string and per-graph limits remain valid; UTF-8 byte bound is decisive.
        value['document']['graphs'] *= 60
        for graph in value['document']['graphs']:
            for edge in graph['edges']: edge['edge_label'] = '字'*256
    assert run_js({'operation': 'sanitize', 'context': value}) is None


def test_actual_session_load_keeps_sanitized_same_message_snapshot():
    value = context()
    message = {'role': 'user', 'source': 'ocr', 'ocrIsQuestion': True,
               'text': '【题目文字】\n求度数\n\n【图形信息】\n显示边表\n\n【我的要求】\n解题',
               'apiText': value['question_text'], 'semanticContext': value}
    result = run_js({'operation': 'load', 'stored': {'sessions': [{'id': 's', 'messages': [message]}], 'currentId': 's'}})
    assert result['loaded']
    stored = result['sessions'][0]['messages'][0]['semanticContext']
    assert stored['question_text'] == value['question_text']
    assert 'private' not in stored and 'private' not in stored['document']


def test_session_load_rejects_snapshot_attached_to_a_different_question():
    message = {'role': 'user', 'source': 'ocr', 'text': '不同题目',
               'apiText': '不同API文本', 'semanticContext': context()}
    result = run_js({'operation': 'load', 'stored': {'sessions': [{'id': 's', 'messages': [message]}], 'currentId': 's'}})
    assert 'semanticContext' not in result['sessions'][0]['messages'][0]


def test_old_device_merge_preserves_only_a_same_message_valid_snapshot():
    valid = run_js({'operation': 'merge', 'graphs': graphs()})
    invalid = run_js({'operation': 'merge', 'graphs': graphs(), 'tamper': True})
    assert valid['semanticContext']['source_sha256'] == 'a'*64
    assert 'semanticContext' not in invalid
