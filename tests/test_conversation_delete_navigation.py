"""Deleting the open conversation leaves the real empty view, across sync/reload."""
import os
from pathlib import Path
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=[(1360, 900), (390, 844)])
def conversation_page(request):
    chromium = os.environ.get('DMATE_BROWSER_EXECUTABLE') or shutil.which('chromium')
    if not chromium:
        pytest.skip('Chromium unavailable')
    pw = pytest.importorskip('playwright.sync_api')
    source = (ROOT / 'static/script.js').read_text()
    def block(start, end):
        a = source.index(start)
        return source[a:source.index(end, a + len(start))]
    with pw.sync_playwright() as runtime:
        browser = runtime.chromium.launch(executable_path=chromium, headless=True)
        page = browser.new_page(viewport={'width': request.param[0], 'height': request.param[1]})
        page.route('**/*', lambda route: route.fulfill(body='<html></html>', content_type='text/html'))
        page.goto('https://dmate.test/')
        page.set_content('<div id="sessions"></div><div id="chat"></div>')
        page.add_style_tag(content='#sessions .session{display:flex;gap:20px;height:50px}.del{width:40px;height:40px}')
        page.add_script_tag(content='''
          var sessions=[{id:'older',name:'较早对话',messages:[]},{id:'open',name:'当前对话',messages:[]}];
          var currentId='open',deletedSessionIds={},learningState={wrongQuestions:[]},busySessionIds=new Set();
          var STORAGE_KEY='navigation-test',typingTimer=null,confirmDelete=true,syncCount=0;
          var preserveChatScrollOnce=null,lastRenderedChatSessionId='open',forceChatBottomOnce=false;
          var cloudApplyingSnapshot=false,cloudLivePollEnabled=true,cloudLivePollInFlight=false;
          var cloudSyncContextVersion=1,cloudLivePollGeneration=1,cloudLocalChangeVersion=1;
          var cloudLivePollAbortController=null,cloudSyncCapacityRetryAt=0,cloudSyncTimer=0;
          var cloudAppliedPartHashes=null,accountState={authenticated:true,username:'test',syncing:false,revision:1};
          var remoteSnapshot=null;
          var getCurrent=()=>sessions.find(item=>String(item.id)===String(currentId));
          var shouldPersistClientState=()=>true,scheduleCloudSync=()=>syncCount++;
          var showAppConfirm=async()=>confirmDelete;
          var forceCompleteTyping=()=>{},persistRetestRecord=()=>false,saveLearningState=()=>{};
          var removeLearningEventsForSession=()=>{},sessionBusyKey=id=>String(id);
          var refreshUnnamedSessionNames=()=>{},isMobileAppShell=()=>innerWidth<681;
          var animateMobileConversationSwitch=()=>{},closeMobileShellDrawers=()=>{};
          var chatBottomDistance=()=>0,queueChatJumpControlsUpdate=()=>{},scrollChatToBottom=()=>{};
          var renderMath=async()=>{},refreshInputAvailability=()=>{},renderAccountUi=()=>{};
          var normalizeTeaching=x=>x||null,normalizeLearningQuestion=x=>x||null,normalizeRetestSession=x=>x||null;
          var sanitizeSemanticContext=()=>null,sanitizeSemanticContexts=()=>null;
          var readCloudSyncMeta=()=>({username:'test',dirty:false}),writeCloudSyncMeta=()=>{};
          var cloudUiEditInProgress=()=>false,isCloudSyncContextValid=()=>true;
          var normalizeCloudParts=x=>x,getCloudPartHashMap=()=>({}),computeChangedCloudParts=()=>['sessions'];
          var accountFetch=async url=>({response:{status:200},data:url.includes('revisionOnly')?{revision:2}:
            url.includes('manifestOnly')?{revision:2,parts:{sessions:{hash:'new'}}}:
              {revision:2,parts:{sessions:{hash:'new'}},data:remoteSnapshot}});
          var cloudMessageKey=m=>JSON.stringify([m.role,m.text]),mergeCloudMessage=(a,b)=>({...a,...b}),cloudHash=()=>'';
        ''' + '\n'.join([
            block('function normalizeDeletedSessionIds(', 'function markWrongQuestionDeleted('),
            block('function markSessionDeleted(', 'function collectCloudSnapshot('),
            block('function saveState()', 'function escapeRawHtml('),
            block('function renderChat()', '// -----------------------------\n// 会话列表'),
            block('let mobileSessionTapTimer', 'function uniqueTextList('),
            block('function mergeCloudSnapshots(', 'async function pushCloudSnapshot('),
            block('function applyCloudSnapshot(', 'function accountSyncText('),
            block('async function pullLatestCloudSnapshot()', 'function requestCloudLivePollNow('),
        ]) + '\nvar renderAll=()=>{renderSessions();renderChat();};renderAll();')
        yield page
        browser.close()


def delete(page, identifier):
    page.locator(f'[data-session-id="{identifier}"] button[aria-label="删除这个对话"]').click()


def test_delete_open_chat_keeps_other_chats_but_returns_empty_and_survives_reload(conversation_page):
    page = conversation_page
    delete(page, 'open')
    assert page.locator('#chat').inner_text() == '暂无对话'
    assert page.locator('.session.active').count() == 0
    assert page.evaluate('currentId') is None
    assert page.evaluate('sessions.map(s=>s.id)') == ['older']
    assert page.evaluate('Boolean(deletedSessionIds.open)') is True
    saved = page.evaluate('JSON.parse(localStorage.getItem(STORAGE_KEY))')
    assert saved['currentId'] is None
    assert [s['id'] for s in saved['sessions']] == ['older']
    page.evaluate("currentId='older';loadState();renderAll()")
    assert page.locator('#chat').inner_text() == '暂无对话'
    assert page.evaluate('currentId') is None


def test_delete_inactive_or_cancel_does_not_move_current(conversation_page):
    page = conversation_page
    page.evaluate('confirmDelete=false')
    delete(page, 'open')
    assert page.evaluate('currentId') == 'open'
    assert page.locator('.session').count() == 2
    page.evaluate('confirmDelete=true')
    delete(page, 'older')
    assert page.evaluate('currentId') == 'open'
    assert page.locator('.session.active').get_attribute('data-session-id') == 'open'
    assert page.evaluate('Boolean(deletedSessionIds.older)') is True


def test_cloud_conflict_preserves_empty_selection_and_deletion(conversation_page):
    page = conversation_page
    delete(page, 'open')
    result = page.evaluate('''()=>mergeCloudSnapshots({sessions:JSON.parse(localStorage.getItem(STORAGE_KEY))},
      {sessions:{sessions:[{id:'older',messages:[]},{id:'open',messages:[]}],currentId:'older'}})''')
    assert result['sessions']['currentId'] is None
    assert [s['id'] for s in result['sessions']['sessions']] == ['older']
    assert result['sessions']['deletedSessionIds']['open'] > 0


def test_live_cloud_poll_keeps_empty_local_view_instead_of_opening_remote_chat(conversation_page):
    page = conversation_page
    delete(page, 'open')
    page.evaluate("remoteSnapshot={sessions:{sessions:[{id:'older',name:'另端对话',messages:[]}],currentId:'older',deletedSessionIds:{open:Date.now()}}}")
    assert page.evaluate('pullLatestCloudSnapshot()') is True
    assert page.evaluate('currentId') is None
    assert page.locator('#chat').inner_text() == '暂无对话'
    assert page.locator('.session.active').count() == 0
    assert page.locator('.session').count() == 1
