/* Start Flask first. Exercise the actual transcript/composer layout without AI. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const base = process.env.DMATE_TEST_BASE_URL || 'http://127.0.0.1:5000';
const near = (a, b, message, tolerance = 2) =>
    assert.ok(Math.abs(a - b) <= tolerance, message + ': ' + a + ' / ' + b);
const settle = page => page.evaluate(async () => {
    await Promise.all(document.getAnimations().filter(animation =>
        animation.effect?.getComputedTiming().iterations !== Infinity)
        .map(animation => animation.finished.catch(() => {})));
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
});

async function state(page) {
    return page.evaluate(() => {
        const center = document.querySelector('.center'), chat = document.getElementById('chat');
        const wrap = center.querySelector('.input-wrap'), capsule = wrap.querySelector('.input');
        const ai = chat.querySelector('.msg.ai'), actions = ai.querySelector('.msg-actions');
        const rect = node => {
            const r = node.getBoundingClientRect();
            return { left:r.left, top:r.top, right:r.right, bottom:r.bottom, width:r.width, height:r.height };
        };
        const css = getComputedStyle(ai), actionStyle = getComputedStyle(actions);
        const fade = getComputedStyle(wrap, '::before');
        return { center:rect(center), chat:rect(chat), wrap:rect(wrap), capsule:rect(capsule),
            ai:rect(ai), actions:rect(actions), scrollTop:chat.scrollTop,
            bottomDistance:chat.scrollHeight - chat.clientHeight - chat.scrollTop,
            surface:{ background:css.backgroundColor, image:css.backgroundImage,
                border:css.borderWidth, shadow:css.boxShadow },
            actionsStyle:{ align:actionStyle.justifyContent, border:actionStyle.borderTopWidth },
            footer:{ background:getComputedStyle(wrap).backgroundColor, image:fade.backgroundImage,
                pointerEvents:getComputedStyle(wrap).pointerEvents },
            userColor:getComputedStyle(chat.querySelector('.msg.user > .msg-bubble')).backgroundColor,
            capsuleColor:getComputedStyle(capsule).backgroundColor };
    });
}

async function runCase(browser, width, theme) {
    const mobile = width <= 1100;
    const context = await browser.newContext({ viewport:{width,height:900},
        isMobile:mobile, hasTouch:mobile, reducedMotion:'reduce', serviceWorkers:'block' });
    const page = await context.newPage(), errors = [];
    page.on('pageerror', error => errors.push(error.message));
    try {
        await page.route('**/chat', route => { throw new Error('Layout tests must not call AI'); });
        await page.goto(base, { waitUntil:'networkidle' });
        await page.evaluate(async theme => {
            appearanceSettings.mode = theme;
            applyAppearanceSettings({save:false});
            newChat();
            getCurrent().messages = [
                { role:'user', text:'保持这个用户气泡。' },
                { role:'ai', text:Array.from({length:60}, (_, index) =>
                    '第' + (index + 1) + '段：对话正文应能在输入区域下方继续滚动，最后一段仍可完整阅读。').join('\n\n') }
            ];
            renderChat();
            await renderMath(document.getElementById('chat'));
        }, theme);
        await settle(page);
        const initial = await state(page);
        assert.deepEqual(initial.surface, { background:'rgba(0, 0, 0, 0)', image:'none', border:'0px', shadow:'none' });
        assert.deepEqual(initial.actionsStyle, {align:'flex-start',border:'0px'});
        near(initial.actions.left, initial.ai.left, 'AI actions align with the start of its text');
        near(initial.chat.bottom, initial.center.bottom, 'The transcript extends to the screen bottom');
        assert.ok(initial.wrap.top < initial.chat.bottom, 'The composer overlays the transcript');
        assert.ok(initial.bottomDistance <= 2, 'A newly rendered long answer stays at the bottom');
        assert.ok(initial.actions.bottom < initial.wrap.top, 'The final action row is fully above the composer');
        assert.equal(initial.footer.background, 'rgba(0, 0, 0, 0)');
        assert.match(initial.footer.image, /linear-gradient/);
        assert.match(initial.footer.image, /0\.72/);
        assert.equal(initial.footer.pointerEvents, 'none');
        assert.equal(initial.userColor, initial.capsuleColor, 'User bubble keeps its composer surface');

        // A draft can grow while the reader is at the bottom or reviewing history.
        await page.locator('#text').fill('第一行\n第二行\n第三行\n第四行');
        await settle(page);
        const expanded = await state(page);
        assert.ok(expanded.capsule.height > initial.capsule.height, 'The fixture expands the real textarea');
        assert.ok(expanded.bottomDistance <= 2, 'Expanding the composer keeps a bottom reader at the bottom');
        assert.ok(expanded.actions.bottom < expanded.wrap.top, 'Expanded input does not cover the final actions');
        await page.locator('#chat').evaluate(chat => { chat.scrollTop -= 420; });
        const reading = await state(page);
        await page.locator('#text').fill('较短的草稿');
        await settle(page);
        const afterShrink = await state(page);
        near(afterShrink.scrollTop, reading.scrollTop, 'Resizing the composer preserves a scrolled-up reader');

        // The translucent region below the capsule does not swallow scrolling.
        const transparentHit = await page.evaluate(() => {
            const chat = document.getElementById('chat'), wrap = document.querySelector('.input-wrap');
            const r = wrap.getBoundingClientRect();
            const hit = document.elementFromPoint(innerWidth / 2, r.bottom - 4);
            return hit === chat || chat.contains(hit);
        });
        assert.equal(transparentHit, true, 'Transparent footer space lets the transcript receive pointer input');

        if (mobile) {
            await page.evaluate(() => {
                document.documentElement.style.setProperty('--app-visible-height', '620px');
                document.body.classList.add('mobile-keyboard-open');
                window.dispatchEvent(new Event('resize'));
            });
            await settle(page);
            const keyboard = await state(page);
            near(keyboard.wrap.bottom, keyboard.center.bottom, 'The floating composer follows the visible keyboard viewport');
            near(keyboard.capsule.height, afterShrink.capsule.height, 'Keyboard mode keeps capsule geometry');
        }

        // The upload workspace replaces the composer and retains normal flow.
        await page.evaluate(() => {
            document.querySelector('.input-wrap').hidden = true;
            const stage = document.getElementById('ocrUploadStage');
            stage.hidden = false;
            stage.style.height = '180px';
        });
        await settle(page);
        const upload = await page.evaluate(() => {
            const chat = document.getElementById('chat'), stage = document.getElementById('ocrUploadStage');
            return { bottom:chat.getBoundingClientRect().bottom, top:stage.getBoundingClientRect().top };
        });
        assert.ok(upload.bottom <= upload.top + 1, 'Image uploads reserve their own space without covering the transcript');
        assert.deepEqual(errors, []);
        console.log('PASS ' + width + '/' + theme + ': frameless answers, left actions, floating translucent footer, scroll/resize and upload layout');
    } finally { await context.close(); }
}

(async () => {
    const browser = await chromium.launch({ headless:true,
        ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath:process.env.CHROMIUM_EXECUTABLE_PATH } : {}) });
    try {
        for (const width of [1440,820,390]) for (const theme of ['light','dark','navy']) await runCase(browser,width,theme);
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
