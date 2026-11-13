'use strict';
// Run with Flask available at DMATE_TEST_BASE_URL (default localhost:5001).
// No chat/model request is made: real newChat/renderChat paths use local state.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const base = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5001';

async function sample(page, action) {
    return page.evaluate(async action => {
        const capsule = document.querySelector('.center > .input-wrap > .input');
        const mode = document.getElementById('manualQuestionMode');
        const text = document.getElementById('text');
        const panel = document.querySelector('.dmate-symbol-panel');
        const rect = node => {
            const r = node.getBoundingClientRect();
            return {x:r.x, y:r.y, width:r.width, height:r.height};
        };
        const snapshot = () => ({...rect(capsule), mode:rect(mode), time:performance.now()});
        const first = snapshot(), rows = [];
        if (action === 'new') newChat();
        else { currentId = null; renderChat(); }
        const sync = snapshot();
        await new Promise(resolve => {
            const started = performance.now();
            function tick(timestamp) {
                rows.push({...snapshot(), time:timestamp});
                if (performance.now()-started < 380) requestAnimationFrame(tick);
                else resolve();
            }
            requestAnimationFrame(tick);
        });
        return {first, sync, rows, sameText:text === document.getElementById('text'),
            samePanel:panel === document.querySelector('.dmate-symbol-panel'),
            draft:text.value, caret:[text.selectionStart,text.selectionEnd],
            focused:document.activeElement === text, font:getComputedStyle(text).fontSize,
            scale:visualViewport?.scale || 1,
            moving:document.querySelector('.center').hasAttribute('data-composer-motion'),
            temporary:{width:capsule.style.width, translate:capsule.style.translate, mode:mode.style.translate}};
    }, action);
}

function continuous(result, label) {
    for (const key of ['x','y','width','height']) {
        assert.ok(Math.abs(result.sync[key]-result.first[key]) < 2,
            `${label}: synchronous layout switch jumped ${key}`);
    }
    const end = result.rows.at(-1), distance = Math.abs(end.y-result.first.y);
    assert.ok(distance > 120, `${label}: fixture must move between center and bottom`);
    const intermediate = result.rows.filter(r => Math.abs(r.y-result.first.y) > 3 && Math.abs(r.y-end.y) > 3);
    assert.ok(intermediate.length >= 3, `${label}: movement needs several real painted intermediate positions`);
    const direction = Math.sign(end.y-result.first.y);
    for (let i=1; i<result.rows.length; i++) {
        const a=result.rows[i-1], b=result.rows[i];
        assert.ok(direction*(b.y-a.y) >= -2, `${label}: unexpected vertical reversal`);
        if (b.time-a.time < 35) {
            assert.ok(Math.abs(b.y-a.y) <= distance*5*(b.time-a.time)/220+5,
                    `${label}: frame moved faster than easing: ${JSON.stringify({a,b,distance})}`);
        }
    }
    assert.equal(result.sameText, true, label+': textarea replaced');
    assert.equal(result.samePanel, true, label+': symbol panel replaced');
    assert.equal(result.draft, 'A draft with ∀ and ∈', label+': draft lost');
    assert.deepEqual(result.caret, [2,7], label+': selection changed');
    assert.equal(result.focused, true, label+': layout stole focus');
    assert.equal(result.font, '16px', label+': input font size changed');
    assert.equal(result.scale, 1, label+': mobile viewport zoom changed');
    assert.equal(result.moving, false, label+': motion did not finish');
    assert.deepEqual(result.temporary, {width:'',translate:'',mode:''}, label+': temporary geometry leaked');
}

async function interrupted(page, desktop) {
    return page.evaluate(async desktop => {
        const box = () => {
            const r=document.querySelector('.center>.input-wrap>.input').getBoundingClientRect();
            return {x:r.x,y:r.y,width:r.width,height:r.height};
        };
        const frames = count => new Promise(resolve => {
            function next() { if (--count <= 0) resolve(); else requestAnimationFrame(next); }
            requestAnimationFrame(next);
        });
        const changes=[];
        currentId=null; renderChat();
        await frames(4);
        const first=box(); newChat(); changes.push([first,box()]);
        if (desktop) document.getElementById('desktopSidebarOpen').click();
        await frames(4);
        const second=box(); currentId=null; renderChat(); changes.push([second,box()]);
        await frames(3);
        const third=box(); newChat(); changes.push([third,box()]);
        if (desktop) document.getElementById('desktopSidebarToggle').click();
        await new Promise(resolve => setTimeout(resolve, 450));
        const final=box();
        return {changes,final,moving:document.querySelector('.center').hasAttribute('data-composer-motion'),
            empty:document.querySelector('.center').classList.contains('chat-empty'),
            style:document.querySelector('.center>.input-wrap>.input').style.cssText,
            font:getComputedStyle(document.getElementById('text')).fontSize};
    }, desktop);
}

(async () => {
    const browser=await chromium.launch({headless:true,
        executablePath:process.env.CHROMIUM_EXECUTABLE_PATH || undefined,
        args:['--no-sandbox']});
    let cases=0;
    try {
        for (const width of [1440,390]) for (const language of ['zh-CN','en']) {
            const context=await browser.newContext({viewport:{width,height:900},
                isMobile:width<500,hasTouch:width<500,serviceWorkers:'block'});
            try {
                const page=await context.newPage(), errors=[];
                page.on('pageerror', error => errors.push(error.message));
                let modelCalls=0;
                await page.route('**/chat', route => { modelCalls++; return route.abort(); });
                await page.goto(base,{waitUntil:'networkidle'});
                await page.waitForFunction(() => window.dmateChatComposer && window.DMateChatComposer.transitionConversation);
                await page.evaluate(language => {
                    window.DMateI18n.setLanguage(language,false);
                    currentId=null; renderChat();
                    const t=document.getElementById('text');
                    t.value='A draft with ∀ and ∈';t.dispatchEvent(new Event('input',{bubbles:true}));
                    document.querySelector('.dmate-symbol-keyboard').click();
                    t.focus({preventScroll:true}); t.setSelectionRange(2,7);
                },language);
                await page.waitForFunction(() => !document.querySelector('.center').hasAttribute('data-composer-motion'));
                if (width<500) {
                    const geometry=await page.evaluate(() => {
                        const t=document.getElementById('text'), capsule=t.closest('.input');
                        const before=capsule.getBoundingClientRect();
                        document.body.classList.add('mobile-keyboard-open');
                        const after=capsule.getBoundingClientRect();
                        return {before:[before.width,before.height],after:[after.width,after.height]};
                    });
                    assert.deepEqual(geometry.before,geometry.after,'keyboard class changed capsule size');
                }
                continuous(await sample(page,'new'), `${width}/${language}/new`);cases++;
                continuous(await sample(page,'home'), `${width}/${language}/home`);cases++;
                const rapid=await interrupted(page,width>1100);
                for (const [before,after] of rapid.changes) for (const key of ['x','y','width','height']) {
                    assert.ok(Math.abs(before[key]-after[key])<2, `interrupted ${width}/${language} jumped ${key}`);
                }
                assert.equal(rapid.moving,false);assert.equal(rapid.empty,false);
                assert.equal(rapid.font,'16px');
                assert.ok(!rapid.style.includes('translate')&&!rapid.style.includes('width'), 'interruption left styles');
                assert.ok(rapid.final.y>600);cases++;
                assert.equal(modelCalls,0);assert.deepEqual(errors,[]);
                await page.emulateMedia({reducedMotion:'reduce'});
                const reduced=await page.evaluate(() => {
                    currentId=null;renderChat();const home=document.querySelector('.input').getBoundingClientRect().y;
                    newChat();return {home,bottom:document.querySelector('.input').getBoundingClientRect().y,
                        moving:document.querySelector('.center').hasAttribute('data-composer-motion')};
                });
                assert.equal(reduced.moving,false);assert.ok(reduced.bottom-reduced.home>120);cases++;
                console.log(`PASS ${width}px ${language}: bidirectional frames, interruption/sidebar, reduced motion; draft/caret/DOM preserved`);
            } finally { await context.close(); }
        }
    } finally { await browser.close(); }
    console.log(`${cases} composer motion cases passed; no model requests.`);
})().catch(error => {console.error(error);process.exitCode=1;});
