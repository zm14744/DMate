/* Full-page fallback titles plus nonblocking semantic naming and stale-result protection. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const baseURL = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';

async function runCase(browser, width) {
    const page = await browser.newPage({ viewport: { width, height: 900 }, serviceWorkers: 'block' });
    const errors = [], requests = [];
    page.on('pageerror', error => errors.push(error.message));
    for (const path of ['**/chat', '**/analyze-questions']) await page.route(path, route => {
        requests.push(route.request().url()); return route.abort();
    });
    try {
        await page.goto(baseURL, { waitUntil: 'networkidle' });
        const result = await page.evaluate(() => {
            const first = { role: 'user', text: '你好，我最近有点困惑。\n麻烦比较单射和满射并举例说明。' };
            const session = { id: 'summary-regression', name: '新对话', nameSource: 'default', messages: [first], retest: null };
            sessions = [session]; currentId = session.id; renderAll();
            const summary = session.name;
            const header = document.getElementById('desktopConversationTitle').textContent;
            const sidebar = document.querySelector('#sessions [data-session-name]').textContent;

            session.name = '这就是我选定的标题'; session.nameSource = 'user';
            first.questionTeaching = { focus_points: ['生成树'] }; renderSessions();
            const custom = session.name;

            session.name = DMateConversationTitles.legacyName(first.text, 'text'); session.nameSource = 'content';
            renderSessions(); const migrated = session.name;
            session.name = '别人的自定义名称'; renderSessions(); const staleProvenance = session.name;

            session.messages = [{ role: 'user', text: '你好' }, { role: 'user', text: '证明奇数的平方也是奇数。' }];
            session.name = '你好'; session.nameSource = 'content'; renderSessions(); const greetingMigration = session.name;

            const request = { role: 'user', text: '给我出一道简单题。' };
            session.messages = [request]; session.name = '新对话'; session.nameSource = 'default'; renderSessions();
            const generic = session.name;
            const followup = { role: 'user', text: '再解释一下。' }; session.messages.push(followup);
            const rejected = refineFirstSessionName(session, { focus_points: ['最短路'] }, followup);
            const afterUnrelated = session.name;
            const refined = refineFirstSessionName(session, { focus_points: ['最短路'] }, request);
            renderSessions(); const afterMatching = session.name;
            session.messages.push({ role: 'user', text: '接下来讲讲量词。' });
            session.teaching = { focus_points: ['量词'] }; renderSessions(); const stable = session.name;

            session.retest = { targetPoints: ['逻辑等价'] }; session.name = '复测：逻辑等价'; session.nameSource = 'retest';
            renderSessions(); const retest = session.name;
            return { summary, header, sidebar, custom, migrated, staleProvenance, greetingMigration,
                generic, rejected, afterUnrelated, refined, afterMatching, stable, retest };
        });
        assert.deepEqual(result, {
            summary: '单射与满射比较', header: '单射与满射比较', sidebar: '单射与满射比较',
            custom: '这就是我选定的标题', migrated: '单射与满射比较', staleProvenance: '别人的自定义名称',
            greetingMigration: '奇数平方的奇偶性证明', generic: '练习题', rejected: false,
            afterUnrelated: '练习题', refined: true, afterMatching: '最短路练习', stable: '最短路练习', retest: '复测：逻辑等价'
        });
        assert.deepEqual(requests, [], 'Naming must not call model endpoints');
        assert.deepEqual(errors, [], 'No browser errors');
        console.log('PASS ' + width + ': full-message summaries, header/sidebar sync, safe legacy migration, manual/retest protection and first-answer-only refinement');

        // A classifier can finish before the chat reply: the visible title must
        // update immediately through that real callback, without a reply render.
        await page.unroute('**/analyze-questions');
        await page.unroute('**/chat');
        let heldReply;
        await page.route('**/chat', route => { heldReply = route; });
        await page.route('**/analyze-questions', route => route.fulfill({ contentType: 'application/json',
            body: JSON.stringify({ results: [{ teaching: { category: '集合与关系', focus_points: ['集合运算'], knowledge_points: ['集合运算'], difficulty: '简单' } }] }) }));
        await page.evaluate(() => {
            newChat(); manualQuestionMode = true;
            document.getElementById('text').value = '计算 A∪B，其中 A={1,2}，B={2,3}。';
            send();
        });
        await page.waitForFunction(() => getCurrent().name === '集合运算计算');
        assert.equal(await page.locator('#desktopConversationTitle').textContent(), '集合运算计算');
        assert.equal(await page.locator('#sessions .session.active [data-session-name]').textContent(), '集合运算计算');
        assert.equal(await page.evaluate(() => getCurrent().messages.filter(message => message.role === 'ai').length), 0);
        await page.evaluate(() => stopCurrentAiReply());
        await heldReply?.abort().catch(() => {});
        assert.deepEqual(errors, [], 'Classifier-first naming causes no browser errors');
        console.log('PASS ' + width + ': matching classification refreshes visible titles before the AI reply arrives');
    } finally { await page.close(); }
}

async function runSemanticLifecycle(browser, width) {
    const page = await browser.newPage({ viewport:{ width, height:900 }, serviceWorkers:'block' });
    const errors = [], held = [], payloads = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/conversation/title', route => {
        payloads.push(route.request().postDataJSON()); held.push(route);
    });
    const next = async () => {
        for (let attempt = 0; attempt < 160 && !held.length; attempt++) await new Promise(resolve => setTimeout(resolve, 25));
        assert.ok(held.length, 'a semantic title request should arrive after a completed exchange');
        return held.shift();
    };
    const answer = (route, title, established = true) => route.fulfill({ contentType:'application/json',
        body:JSON.stringify({ ok:true, version:2, title, topic_established:established }) });
    try {
        await page.goto(baseURL, { waitUntil:'networkidle' });
        await page.evaluate(() => {
            sessions = [{ id:'semantic-render', name:'给一个长文本检查渲染讨论', nameSource:'content', retest:null,
                messages:[{ role:'user', text:'给一个长文本检查渲染', apiText:'HIDDEN REFERENCE MUST NOT LEAVE IN TITLE REQUEST' },
                    { role:'ai', text:'这是一段含公式、代码、表格的长文本，用于测试显示效果。' }] }];
            currentId = sessions[0].id; renderAll();
        });
        const first = await next();
        assert.equal(await page.evaluate(() => getCurrent().name), '长文本渲染测试', 'immediate fallback repairs the old copied name');
        assert.ok(!JSON.stringify(payloads[0]).includes('HIDDEN REFERENCE'), 'only visible chat text goes to the title endpoint');
        assert.deepEqual(payloads[0].messages.map(message => message.role), ['user', 'assistant']);
        await answer(first, '长文本公式排版测试');
        await page.waitForFunction(() => getCurrent()?.name === '长文本公式排版测试');
        assert.equal(await page.locator('#desktopConversationTitle').textContent(), '长文本公式排版测试');
        assert.equal(await page.locator('#sessions [data-session-name]').textContent(), '长文本公式排版测试');
        await page.evaluate(() => { for (let i=0; i<6; i++) renderSessions(); });
        await page.waitForTimeout(450);
        assert.equal(payloads.length, 1, 'repeated renders never regenerate an established title');

        const restored = await page.evaluate(() => {
            const before = { ...accountState };
            accountState.authenticated = true; accountState.username = 'title-persistence-test';
            cloudApplyingSnapshot = true;
            saveState(); const loaded = loadState();
            Object.assign(accountState, before); cloudApplyingSnapshot = false;
            renderSessions();
            return { loaded, summary:getCurrent().titleSummary, name:getCurrent().name };
        });
        assert.equal(restored.loaded, true);
        assert.equal(restored.summary.version, 2);
        assert.equal(restored.summary.title, restored.name);
        await page.waitForTimeout(450);
        assert.equal(payloads.length, 1, 'persisted semantic provenance avoids renaming on reload');

        const merged = await page.evaluate(() => {
            const semantic = { ...getCurrent() };
            const old = { ...semantic, name:'长文本渲染测试', nameSource:'content', titleSummary:null };
            const manual = { ...semantic, name:'这是我的自定义名字', nameSource:'user' };
            const legacy = { ...semantic, name:'旧版中保留的自选标题', nameSource:undefined };
            const snapshot = session => ({ sessions:{ sessions:[session], currentId:session.id }, learning:{} });
            const merge = (local, remote) => mergeCloudSnapshots(snapshot(local), snapshot(remote)).sessions.sessions[0];
            return { semantic:merge(old, semantic), remoteManual:merge(semantic, manual), localManual:merge(manual, semantic),
                remoteLegacy:merge(semantic, legacy), localLegacy:merge(legacy, semantic) };
        });
        assert.equal(merged.semantic.name, '长文本公式排版测试', 'an old local fallback does not erase a synced semantic name');
        assert.equal(merged.semantic.titleSummary.version, 2);
        for (const key of ['remoteManual', 'localManual']) {
            assert.equal(merged[key].name, '这是我的自定义名字', 'manual names beat automatic names on either side of sync');
            assert.equal(merged[key].nameSource, 'user');
            assert.equal(merged[key].titleSummary, null);
        }
        for (const key of ['remoteLegacy', 'localLegacy']) {
            assert.equal(merged[key].name, '旧版中保留的自选标题', 'a legacy name without provenance remains protected on either side of sync');
            assert.equal(merged[key].nameSource, undefined);
            assert.equal(merged[key].titleSummary, null);
        }

        await page.evaluate(() => {
            sessions = [{ id:'semantic-greeting', name:'新对话', nameSource:'default', retest:null,
                messages:[{ role:'user', text:'你好' }, { role:'ai', text:'你好，我可以帮助你学习离散数学。' }] }];
            currentId = sessions[0].id; renderAll();
        });
        await answer(await next(), '初次交流', false);
        await page.waitForFunction(() => getCurrent()?.titleSummary?.topicEstablished === false);
        await page.evaluate(() => {
            getCurrent().messages.push({ role:'user', text:'请比较循环群Z12中的子群包含关系。' },
                { role:'ai', text:'Z12的子群对应12的正因数，可以按包含关系画出子群格。' });
            renderSessions();
        });
        await answer(await next(), 'Z12子群格与包含关系');
        await page.waitForFunction(() => getCurrent()?.name === 'Z12子群格与包含关系');
        assert.ok(payloads[2].messages.some(message => message.content.includes('循环群Z12')));
        await page.evaluate(() => {
            getCurrent().messages.push({ role:'user', text:'再讲讲具体细节。' }, { role:'ai', text:'逐一分析这些子群。' });
            renderSessions();
        });
        await page.waitForTimeout(450);
        assert.equal(payloads.length, 3, 'normal followups keep a settled conversation name');

        await page.evaluate(() => {
            sessions = [{ id:'semantic-classification-race', name:'新对话', nameSource:'default', retest:null,
                messages:[{ role:'user', text:'给我出一道简单题。' }, { role:'ai', text:'下面是一道关于最短路的简单练习。' }] }];
            currentId = sessions[0].id; renderAll();
        });
        const beforeClassification = await next();
        assert.equal(await page.evaluate(() => {
            const message = getCurrent().messages[0];
            message.questionTeaching = { focus_points:['最短路'] };
            const changed = refineFirstSessionName(getCurrent(), message.questionTeaching, message);
            renderSessions(); return changed;
        }), true);
        const afterClassification = await next();
        await answer(beforeClassification, '已过时的粗略总结').catch(() => {});
        await answer(afterClassification, '最短路基础练习');
        await page.waitForFunction(() => getCurrent()?.name === '最短路基础练习');

        // A manual rename to exactly the same visible text still changes
        // provenance and must defeat an in-flight model response.
        await page.evaluate(() => {
            sessions = [{ id:'semantic-manual', name:'新对话', nameSource:'default', retest:null,
                messages:[{ role:'user', text:'能帮我理解这个例子吗？' }, { role:'ai', text:'这个例子展示了一个有限结构。' }] }];
            currentId = sessions[0].id; renderAll();
        });
        const manual = await next();
        const kept = await page.evaluate(() => {
            renameSession(getCurrent());
            const input = document.getElementById('sessionRenameInput');
            input.dispatchEvent(new Event('input', { bubbles:true }));
            document.getElementById('sessionRenameSave').click();
            return getCurrent().name;
        });
        await answer(manual, '不应覆盖手动名字');
        await page.waitForTimeout(150);
        assert.deepEqual(await page.evaluate(() => ({ name:getCurrent().name, source:getCurrent().nameSource,
            semantic:Boolean(getCurrent().titleSummary) })), { name:kept, source:'user', semantic:false });

        await page.evaluate(() => {
            sessions = [{ id:'semantic-deleted', name:'新对话', nameSource:'default', retest:null,
                messages:[{ role:'user', text:'解释这个有限结构。' }, { role:'ai', text:'这是一个具有有限元素的结构。' }] }];
            currentId = sessions[0].id; renderAll();
        });
        const deleted = await next();
        await page.evaluate(() => { sessions = []; currentId = null; renderAll(); });
        await answer(deleted, '已删除对话的迟到标题');
        await page.waitForTimeout(150);
        assert.equal(await page.evaluate(() => sessions.length), 0, 'a late title cannot revive a deleted conversation');

        await page.evaluate(() => {
            sessions = [{ id:'semantic-account', name:'新对话', nameSource:'default', retest:null,
                messages:[{ role:'user', text:'理解一个有限结构。' }, { role:'ai', text:'下面说明这个有限结构的元素。' }] }];
            currentId = sessions[0].id; renderAll();
        });
        const account = await next();
        await page.evaluate(() => { accountState.authenticated = true; accountState.username = 'different-account'; });
        await answer(account, '不应跨账号写入');
        await page.waitForTimeout(150);
        assert.equal(await page.evaluate(() => Boolean(getCurrent().titleSummary)), false);
        await page.evaluate(() => { accountState.authenticated = false; accountState.username = ''; });

        await page.evaluate(() => {
            sessions = [{ id:'semantic-failure', name:'新对话', nameSource:'default', retest:null,
                messages:[{ role:'user', text:'给一个长文本检查渲染' }, { role:'ai', text:'用于检查渲染的长文本。' }] }];
            currentId = sessions[0].id; renderAll();
        });
        const failed = await next();
        await failed.fulfill({ status:503, contentType:'application/json', body:'{"ok":false,"code":"title_unavailable"}' });
        await page.waitForTimeout(150);
        const count = payloads.length;
        await page.evaluate(() => { for(let i=0;i<6;i++) renderSessions(); });
        await page.waitForTimeout(450);
        assert.equal(payloads.length, count, 'provider failure has a cooldown rather than a render retry loop');
        assert.equal(await page.evaluate(() => getCurrent().name), '长文本渲染测试');
        assert.equal(await page.evaluate(() => getCurrent().messages.length), 2, 'title failure never adds an AI error message');
        assert.deepEqual(errors, []);
        console.log('PASS ' + width + ': semantic endpoint names sidebar/header, persists once, upgrades greetings, and rejects manual/deleted/account-stale results; outages preserve fallback');
    } finally { await page.close(); }
}

(async () => {
    const browser = await chromium.launch({ headless: true,
        ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
    try { for (const width of [1440, 390]) { await runCase(browser, width); await runSemanticLifecycle(browser, width); } }
    finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
