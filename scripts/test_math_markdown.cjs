'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../static/math-markdown.js'), 'utf8');
function pipeline(MathJax) {
    const warnings = [];
    const context = { MathJax, console: { warn: (...args) => warnings.push(args) } };
    vm.runInNewContext(source, context);
    return { ...context.DMateMathMarkdown, warnings };
}

test('explicit proof endings omit decorative squares in Unicode and TeX', () => {
    const { prepareAiDisplayText } = pipeline();
    for (const ending of [
        '□', '∎', '■', String.raw`\square`, String.raw`$\square$`,
        String.raw`$$\blacksquare$$`, String.raw`\(\square\)`, String.raw`\[\blacksquare\]`, String.raw`\(\Box\)`
    ]) {
        const proof = String.raw`因为 $n^2=2m+1$，其中 $m\in\mathbb{Z}$，所以 $n^2$ 为奇数。证毕。`;
        assert.equal(prepareAiDisplayText(proof + '\n' + ending), proof);
    }
    assert.equal(prepareAiDisplayText('Q.E.D. ∎'), 'Q.E.D.');
    assert.equal(prepareAiDisplayText('**证毕。** □'), '**证毕。**');
    assert.equal(prepareAiDisplayText('**证毕。 □**'), '**证毕。**');
});

test('squares in questions, formulas, inline code and fenced code remain intact', () => {
    const { prepareAiDisplayText } = pipeline();
    for (const value of [
        '在方框 □ 中填写数字。', String.raw`$x=\square$`,
        String.raw`图中的 $\square ABCD$ 是正方形。`,
        '`证毕。 □`', '```text\n证毕。 □\n```', '~~~text\n证毕。 □\n~~~'
    ]) assert.equal(prepareAiDisplayText(value), value);
});

test('cold startup is awaited even before typesetPromise has been installed', async () => {
    let ready;
    const engine = { startup: { promise: new Promise(resolve => { ready = resolve; }) } };
    const { renderMath } = pipeline(engine);
    const calls = [];
    const first = renderMath('first reply');
    await Promise.resolve();
    assert.equal(calls.length, 0);
    engine.typesetPromise = async targets => { calls.push(...targets); };
    ready();
    await first;
    assert.deepEqual(calls, ['first reply']);
});

test('history and stream typesets share a serial queue', async () => {
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    let active = 0, maximum = 0;
    const calls = [];
    const { renderMath } = pipeline({
        typesetPromise: async ([target]) => {
            maximum = Math.max(maximum, ++active);
            calls.push(target);
            if (target === 'history') await gate;
            active--;
        }
    });
    const history = renderMath('history'), preview = renderMath('preview');
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(calls, ['history']);
    release();
    await Promise.all([history, preview]);
    assert.deepEqual(calls, ['history', 'preview']);
    assert.equal(maximum, 1);
});

test('sync and async typesetting failures do not reject replies or poison later renders', async () => {
    const calls = [];
    const { renderMath, warnings } = pipeline({
        typesetPromise: ([target]) => {
            calls.push(target);
            if (target === 'sync') throw new Error('initialization failed');
            if (target === 'async') return Promise.reject(new Error('typesetting failed'));
            return Promise.resolve();
        }
    });
    await Promise.all([renderMath('sync'), renderMath('async'), renderMath('next reply')]);
    assert.deepEqual(calls, ['sync', 'async', 'next reply']);
    assert.equal(warnings.length, 2);
});
