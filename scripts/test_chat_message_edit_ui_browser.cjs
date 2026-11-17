'use strict';
// Standalone inline editor checks; no Flask or model request is needed.
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');

(async () => {
    const browser = await chromium.launch({
        ...((process.env.CHROMIUM_EXECUTABLE_PATH || process.env.CHROMIUM_PATH)
            ? {executablePath:process.env.CHROMIUM_EXECUTABLE_PATH || process.env.CHROMIUM_PATH} : {}),
        headless:true, args:['--no-sandbox']
    });
    try {
        const page = await browser.newPage({ viewport:{width:390, height:844} });
        await page.setContent('<body data-appearance-theme="dark"><main id="chat"><div class="msg user"><div class="msg-bubble"></div></div></main></body>');
        await page.addStyleTag({content:`
            :root { --dm-selected-bg:#3d3d3d; --dm-selected-hover:#444; --text-primary:#eee; --text-muted:#999 }
            body { margin:0; background:#161616; color:#eee; font:16px/1.6 system-ui }
            #chat { width:calc(100vw - 32px); margin:16px }
            .msg.user { max-width:85%; margin-left:auto }
            .msg-bubble { box-sizing:border-box; padding:12px 18px; background:#303030; border-radius:18px }
        `});
        await page.addStyleTag({path:path.join(root, 'static/chat-message-edit.css')});
        // The shared theme loads last in the app and must keep the same filled style.
        await page.addStyleTag({path:path.join(root, 'static/button-themes.css')});
        await page.addScriptTag({path:path.join(root, 'static/chat-message-edit.js')});
        await page.evaluate(() => {
            window.submissions = []; window.cancels = 0; window.changes = [];
            window.view = DMateChatMessageEdit.mount({
                host:document.querySelector('.msg-bubble'), value:'  old question  ',
                onChange:(text, selection) => changes.push({text, selection}),
                onCancel:() => cancels++, onSubmit:text => submissions.push(text)
            });
            view.focus({start:2, end:5, direction:'forward'});
        });
        assert.deepEqual(await page.evaluate(() => [view.textarea.selectionStart, view.textarea.selectionEnd]), [2,5]);
        const styles = await page.evaluate(() => {
            const button = getComputedStyle(view.cancelButton), input = getComputedStyle(view.textarea);
            return {border:button.borderTopWidth, background:button.backgroundColor, font:input.fontSize};
        });
        assert.deepEqual(styles, {border:'0px', background:'rgb(61, 61, 61)', font:'16px'});

        await page.locator('textarea').fill('  revised question  ');
        await page.locator('textarea').press('End');
        await page.locator('textarea').press('Shift+Enter');
        assert.equal(await page.locator('textarea').inputValue(), '  revised question  \n');
        for (const modifier of ['Alt','Control','Meta']) {
            await page.locator('textarea').press(`${modifier}+Enter`);
        }
        assert.deepEqual(await page.evaluate(() => submissions), []);
        await page.locator('textarea').press('Enter');
        assert.deepEqual(await page.evaluate(() => submissions), ['revised question']);

        const ime = await page.evaluate(async () => {
            const input = view.textarea;
            const enter = extra => input.dispatchEvent(new KeyboardEvent('keydown', {
                key:'Enter', bubbles:true, cancelable:true, ...extra
            }));
            input.dispatchEvent(new CompositionEvent('compositionstart', {bubbles:true}));
            enter(); enter({keyCode:229}); enter({isComposing:true});
            input.dispatchEvent(new CompositionEvent('compositionend', {bubbles:true}));
            enter();
            const immediate = submissions.length;
            await new Promise(resolve => setTimeout(resolve, 55));
            enter();
            return {immediate, afterCommit:submissions.length};
        });
        assert.deepEqual(ime, {immediate:1, afterCommit:2}, 'IME commit Enter must not also send');
        await page.locator('textarea').press('Escape');
        assert.equal(await page.evaluate(() => cancels), 1);
        await page.locator('textarea').fill(' \n ');
        assert.equal(await page.locator('.chat-message-edit-send').isDisabled(), true);

        await page.evaluate(() => {
            view.destroy();
            view = DMateChatMessageEdit.mount({host:document.querySelector('.msg-bubble'), value:'😀😀',
                maxCharacters:2, onSubmit:() => { throw new Error('mock error'); }});
        });
        assert.equal(await page.locator('.chat-message-edit-send').isEnabled(), true);
        await page.locator('.chat-message-edit-send').click();
        assert.equal(await page.locator('.chat-message-edit-error').textContent(), 'mock error');
        assert.equal(await page.locator('.chat-message-edit-error').isVisible(), true);
        await page.locator('textarea').fill('abc');
        assert.equal(await page.locator('.chat-message-edit-send').isDisabled(), true);
        assert.equal(await page.locator('textarea').getAttribute('aria-invalid'), 'true');
        await page.locator('textarea').fill('ab');
        assert.equal(await page.locator('.chat-message-edit-error').isHidden(), true);
        for (const width of [390,1440]) {
            await page.setViewportSize({width, height:900});
            assert.equal(await page.evaluate(() => {
                const bubble = document.querySelector('.msg-bubble').getBoundingClientRect();
                const input = view.textarea.getBoundingClientRect();
                return input.left >= bubble.left && input.right <= bubble.right;
            }), true, `editor overflow at ${width}px`);
        }
        await page.evaluate(() => view.destroy());
        assert.equal(await page.locator('[data-chat-message-edit]').count(), 0);
        console.log('Chat message editor UI browser checks passed');
    } finally {
        await browser.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
