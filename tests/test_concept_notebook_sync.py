"""Execute the notebook model and actual account/cloud state functions in Node."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
PROGRAM = r'''
const fs=require('fs'),vm=require('vm');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const source=fs.readFileSync('static/script.js','utf8');
function block(start,end){const a=source.indexOf(start);if(a<0)throw new Error(start);return source.slice(a,source.indexOf(end,a+start.length));}
const store=new Map(),calls={refresh:0,sync:0,writes:0,reads:0};
let failing=false;
const sandbox={console:{warn:()=>{}},Date,Math,JSON,Map,Set,Object,Number,String,Array,
 LEARNING_STORAGE_KEY:'learning',STORAGE_KEY:'sessions',CLOUD_BACKUP_KEY:'backup',APPEARANCE_STORAGE_KEY:'appearance',
 accountState:{authenticated:input.guest!==true,username:input.guest?'':'alice'},
 learningState:null,sessions:[],currentId:null,deletedSessionIds:{},cloudApplyingSnapshot:false,
 APPEARANCE_DEFAULTS:{},appearanceSettings:{},appearanceCommittedSettings:{},volatileCloudBackup:null,
 document:{activeElement:null,getElementById:id=>id==='conceptNotebookDialog'?{open:input.dialogOpen===true}:null},
 localStorage:{getItem:k=>{calls.reads++;return store.get(k)||null},setItem:(k,v)=>{if(failing)throw new Error('QuotaExceeded');calls.writes++;store.set(k,v)},removeItem:k=>store.delete(k)},
 normalizeDeletedWrongQuestionIds:x=>({...x}),normalizeDeletedSessionIds:x=>({...x}),
 sanitizeStoredWrongQuestionText:x=>x,isClearlyNonQuestionWrongBookText:()=>false,
 buildKnowledgeFromEvents:()=>({}),scheduleCloudSync:()=>calls.sync++,
 renderAccountUi:()=>{},renderAll:()=>{},refreshInputAvailability:()=>{},loadState:()=>{},
 clearAppearanceBackgroundVisual:()=>{},applyAppearanceSettings:()=>{},
 purgeGuestPersistentState:()=>store.clear(),
 cloudMessageKey:m=>JSON.stringify([m.role,m.text]),mergeCloudMessage:(a,b)=>({...a,...b}),cloudHash:()=> 'hash',
 window:{dmateConceptNotebook:{refresh:()=>calls.refresh++}}
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('static/concept-notebook-model.js','utf8'),sandbox);
const snippets=[
 block('function shouldPersistClientState()', 'function purgeGuestPersistentState()'),
 block('function createEmptyLearningState()', 'function normalizeLearningQuestion('),
 block('function normalizeLearningState(', 'function loadLearningState()'),
 block('function loadLearningState()', 'function emptyKnowledgeRecord()'),
 block('function collectCloudSnapshot()', 'function backupLocalSnapshot('),
 block('function applyCloudSnapshot(', 'function accountSyncText()'),
 block('function mergeCloudSnapshots(', 'async function pushCloudSnapshot('),
 block('function clearLoggedOutWorkspace()', 'function setAppConfirmOpen('),
 block('function cloudUiEditInProgress()', 'async function pullLatestCloudSnapshot()')
];
vm.runInContext(snippets.join('\n'),sandbox);
sandbox.learningState=sandbox.createEmptyLearningState();
const model=sandbox.window.DMateConceptNotebookModel;
let result;
if(input.operation==='model')result=model[input.method](...input.args);
else if(input.operation==='merge')result=sandbox.mergeCloudSnapshots(input.local,input.remote);
else if(input.operation==='merge_missing_model'){
 delete sandbox.window.DMateConceptNotebookModel;
 try{result=sandbox.mergeCloudSnapshots(input.local,input.remote)}catch(error){result={error:error.message}};
}
else if(input.operation==='apply'){
 sandbox.learningState=sandbox.normalizeLearningState(input.local);
 result={applied:sandbox.applyCloudSnapshot({learning:input.remote}),state:sandbox.learningState,calls};
}else if(input.operation==='save_reload'){
 sandbox.setConceptNotebookState(input.state);
 sandbox.learningState=sandbox.createEmptyLearningState();sandbox.loadLearningState();
 result={state:sandbox.learningState,snapshot:sandbox.collectCloudSnapshot(),calls};
}else if(input.operation==='failed_save'){
 failing=true;let error;
 try{sandbox.setConceptNotebookState(input.state)}catch(e){error=e.message}
 result={error,state:sandbox.learningState,calls};
}else if(input.operation==='guest'){
 store.set('learning',JSON.stringify({conceptNotebook:input.previous}));
 sandbox.loadLearningState();const loaded=JSON.parse(JSON.stringify(sandbox.learningState));
 sandbox.setConceptNotebookState(input.state);
 result={loaded,state:sandbox.learningState,calls};
}else if(input.operation==='reset'){
 sandbox.setConceptNotebookState(input.state);
 sandbox.accountState={authenticated:false,username:''};sandbox.clearLoggedOutWorkspace();
 sandbox.accountState={authenticated:true,username:'bob'};sandbox.loadLearningState();
 result={state:sandbox.learningState,calls,stored:[...store.keys()]};
}else if(input.operation==='reduce_overflow'){
 sandbox.learningState.conceptNotebook=model.normalize(input.state);
 sandbox.setConceptNotebookState(input.reduced);
 result=sandbox.learningState.conceptNotebook;
}else if(input.operation==='validate'){
 try{result={state:model.validate(input.state)}}catch(error){result={error:error.message}}
}else if(input.operation==='has_data')result=sandbox.snapshotHasUserData({learning:{conceptNotebook:input.state}});
else if(input.operation==='edit_lock')result=sandbox.cloudUiEditInProgress();
else if(input.operation==='missing_model'){
 sandbox.learningState=sandbox.normalizeLearningState(input.local);
 delete sandbox.window.DMateConceptNotebookModel;
 result={applied:sandbox.applyCloudSnapshot({learning:input.remote}),state:sandbox.learningState};
}
process.stdout.write(JSON.stringify(result));
'''


def run(payload):
    if not NODE:
        pytest.skip('Node is required to execute notebook sync contracts')
    result = subprocess.run([NODE, '-e', PROGRAM], input=json.dumps(payload, ensure_ascii=False),
                            text=True, capture_output=True, cwd=ROOT, check=True)
    return json.loads(result.stdout)


def note(identifier='n1', content='  集合中的关系\n\n保留原文  ', at=10, title='关系'):
    return {'id': identifier, 'title': title, 'content': content, 'updatedAt': at}


def state(*notes, deleted=None):
    return {'notes': list(notes), 'deleted': deleted or {}}


def test_logged_in_notes_roundtrip_original_text_into_learning_cache_and_cloud_snapshot():
    original = state(note())
    result = run({'operation': 'save_reload', 'state': original})
    assert result['state']['conceptNotebook'] == original
    assert result['snapshot']['learning']['conceptNotebook'] == original
    assert result['calls']['writes'] == 1 and result['calls']['sync'] == 1


def test_guest_never_reads_a_previous_account_cache_or_persists_notes():
    result = run({'operation': 'guest', 'guest': True, 'previous': state(note('alice')),
                  'state': state(note('guest'))})
    assert result['loaded']['conceptNotebook']['notes'] == []
    assert [row['id'] for row in result['state']['conceptNotebook']['notes']] == ['guest']
    assert result['calls']['reads'] == result['calls']['writes'] == 0


def test_logout_clears_notes_and_notebook_view_before_another_account_loads():
    result = run({'operation': 'reset', 'state': state(note('alice-private'))})
    assert result['state']['conceptNotebook']['notes'] == []
    assert result['stored'] == [] and result['calls']['refresh'] >= 1


def test_local_storage_failure_is_reported_while_memory_and_cloud_attempt_keep_latest_note():
    original = state(note())
    result = run({'operation': 'failed_save', 'state': original})
    assert '存储空间不足' in result['error']
    assert result['state']['conceptNotebook'] == original
    assert result['calls']['sync'] == 1


def test_cloud_merge_keeps_both_devices_new_notes_and_existing_chat_wrong_book():
    left = {'sessions': {'sessions': [{'id': 1, 'messages': [{'role': 'user', 'text': '本机聊天'}]}]},
            'learning': {'conceptNotebook': state(note('local')), 'wrongQuestions': [{'id': 'w1', 'question': '旧错题'}]}}
    right = {'sessions': {'sessions': [{'id': 2, 'messages': [{'role': 'user', 'text': '云端聊天'}]}]},
             'learning': {'conceptNotebook': state(note('remote')), 'events': [{'id': 'event', 'createdAt': 1}]}}
    result = run({'operation': 'merge', 'local': left, 'remote': right})
    assert {n['id'] for n in result['learning']['conceptNotebook']['notes']} == {'local', 'remote'}
    assert {s['id'] for s in result['sessions']['sessions']} == {1, 2}
    assert result['learning']['wrongQuestions'][0]['question'] == '旧错题'
    assert result['learning']['events'][0]['id'] == 'event'


def test_newer_deletion_wins_and_newer_undo_revives_without_stale_resurrection():
    deleted = state(deleted={'n1': 20})
    old = state(note(at=10))
    result = run({'operation': 'model', 'method': 'merge', 'args': [old, deleted]})
    assert result['notes'] == []
    undone = state(note(at=21))
    result = run({'operation': 'model', 'method': 'merge', 'args': [deleted, undone]})
    assert result['notes'] == undone['notes']
    assert run({'operation': 'model', 'method': 'merge', 'args': [result, old]})['notes'] == undone['notes']


def test_same_timestamp_conflict_keeps_deterministic_full_text_copy_and_valid_api_id():
    left, right = state(note(content='左边同时编辑', at=30)), state(note(content='右边同时编辑', at=30))
    a = run({'operation': 'model', 'method': 'merge', 'args': [left, right]})
    b = run({'operation': 'model', 'method': 'merge', 'args': [right, left]})
    assert a == b
    assert {row['content'] for row in a['notes']} == {'左边同时编辑', '右边同时编辑'}
    assert len({row['id'] for row in a['notes']}) == 2
    import re
    assert all(re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}', row['id']) for row in a['notes'])
    assert run({'operation': 'model', 'method': 'merge', 'args': [a, right]}) == a


def test_normalization_skips_bad_records_without_trimming_valid_original_text():
    original = note()
    result = run({'operation': 'model', 'method': 'normalize', 'args': [
        state(original, {'id': 'bad', 'title': 'x', 'content': ['invalid'], 'updatedAt': 1})]})
    assert result['notes'] == [original]


def test_cloud_apply_does_not_drop_local_notes_when_old_snapshot_omits_field():
    result = run({'operation': 'apply', 'local': {'conceptNotebook': state(note())},
                  'remote': {'version': 9, 'events': [], 'wrongQuestions': []}})
    assert result['applied'] is True
    assert result['state']['conceptNotebook']['notes'] == [note()]


def test_missing_model_never_overwrites_existing_notes_from_cloud():
    result = run({'operation': 'missing_model', 'local': {'conceptNotebook': state(note())},
                  'remote': {'version': 9, 'events': [], 'wrongQuestions': []}})
    assert result['applied'] is False
    assert result['state']['conceptNotebook']['notes'] == [note()]


def test_missing_model_cannot_upload_an_empty_notebook_during_conflict_merge():
    result = run({'operation': 'merge_missing_model', 'local': {'learning': {'conceptNotebook': state(note())}},
                  'remote': {'learning': {}}})
    assert '笔记同步组件未加载' in result['error']


def test_notebook_only_data_is_backed_up_and_open_editor_locks_background_pull():
    assert run({'operation': 'has_data', 'state': state(note())}) is True
    assert run({'operation': 'edit_lock', 'dialogOpen': True}) is True
    assert run({'operation': 'edit_lock', 'dialogOpen': False}) is False


def test_cross_device_union_is_not_silently_cut_at_local_edit_capacity():
    left = state(*(note('left' + str(i)) for i in range(60)))
    right = state(*(note('right' + str(i)) for i in range(60)))
    result = run({'operation': 'model', 'method': 'merge', 'args': [left, right]})
    assert len(result['notes']) == 120
    reduced = state(*result['notes'][1:], deleted={result['notes'][0]['id']: 20})
    assert len(run({'operation': 'reduce_overflow', 'state': result, 'reduced': reduced})['notes']) == 119


@pytest.mark.parametrize('invalid', [state(*(note('n' + str(i)) for i in range(101))),
                                    state(note(content='字' * 6001)),
                                    state(note(title='字' * 161)),
                                    state(*(note('n' + str(i), content='字' * 6000) for i in range(31)))])
def test_local_capacity_limits_reject_without_silent_truncation(invalid):
    assert 'error' in run({'operation': 'validate', 'state': invalid})
