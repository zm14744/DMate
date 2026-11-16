/* Full-page title summaries and stored-name protection without AI requests. */
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

(async () => {
    const browser = await chromium.launch({ headless: true,
        ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
    try { for (const width of [1440, 390]) await runCase(browser, width); }
    finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
