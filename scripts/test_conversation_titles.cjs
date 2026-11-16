'use strict';
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { runInNewContext } = require('node:vm');
const { test } = require('node:test');
const context = {};
runInNewContext(readFileSync(join(__dirname, '../static/conversation-titles.js'), 'utf8'), context);
const { summarize, legacyName } = context.DMateConversationTitles;

test('summarizes the mathematical subject and user intent rather than quoting the first line', () => {
    const examples = [
        ['请帮我比较单射和满射并举例说明，麻烦讲得简单一些。', '单射与满射比较'],
        ['你好，想请教一下。\n请解释欧拉回路和哈密顿回路的区别。', '欧拉与哈密顿回路比较'],
        ['题目：\n设整数 n 为奇数，证明 n 的平方也是奇数。', '奇数平方的奇偶性证明'],
        ['帮我看一下这道题\n【题目文字】请用数学归纳法证明下列恒等式。', '数学归纳法证明'],
        ['麻烦帮我计算两个集合的并集和交集。', '集合运算计算'],
        ['能不能给我出一道关于二部图的简单练习题？', '二部图练习'],
        ['如何用Dijkstra算法计算最短路径？', '最短路径计算'],
        ['解释最小生成树的性质。', '最小生成树解析'],
        ['请为图论制定一个复习计划。', '图论复习计划']
    ];
    for (const [text, title] of examples) {
        assert.equal(summarize(text).title, title, text);
        assert.equal(summarize(text).specificity, 2);
        assert.ok(Array.from(title).length <= 22);
    }
});

test('English topics retain English summaries and mathematical symbols are understood', () => {
    assert.equal(summarize('Please compare injective and surjective functions.').title, 'Injective and surjective functions comparison');
    assert.equal(summarize('Please prove by mathematical induction that this identity holds.').title, 'Mathematical induction proof');
    assert.equal(summarize('Explain why the truth table has these rows.').title, 'Truth tables explained');
    assert.equal(summarize(String.raw`解释 $\forall x\exists y$ 中两个符号的意思`).title, '量词解析');
});

test('never adds unrelated topics from arbitrary context; matching metadata can refine a vague request', () => {
    assert.equal(summarize('请来一道简单题。').title, '练习题');
    assert.equal(summarize('请来一道简单题。', { teaching: { focus_points: ['图同构'] } }).title, '图同构练习');
    assert.equal(summarize('解释真值表。', { teaching: { focus_points: ['生成树'] } }).title, '真值表解析');
    assert.equal(summarize('请来一道简单题。', { teaching: { focus_points: '错误数据' } }).title, '练习题');
    const unknown = summarize('请解释关于有限自动机的状态转换。');
    assert.equal(unknown.title, '学习交流');
    assert.ok(!unknown.title.includes('请解释'));
    assert.ok(!unknown.title.includes('图论'));
});

test('greetings and OCR filenames do not lock the title before useful content arrives', () => {
    for (const text of ['', '请帮我看看这道题', '我有个问题']) {
        assert.equal(summarize(text).useful, false, text);
        assert.equal(summarize(text).title, '新对话');
    }
    assert.equal(summarize('你好！').title, '初次交流');
    assert.equal(summarize('你好！').useful, false);
    assert.equal(summarize('Thank you.').title, 'Conversation and thanks');
    assert.equal(summarize('Thank you.').useful, false);
    assert.equal(summarize('IMG_1024.jpg', { source: 'ocr' }).title, '图片识题');
    assert.equal(summarize('[图片识题]\n【题目文字】\n求中国剩余定理的应用示例。', { source: 'ocr' }).title, '中国剩余定理解析');
});

test('a provider failure has a faithful fallback, never a copied imperative with a suffix', () => {
    assert.equal(summarize('给一个长文本检查渲染').title, '长文本渲染测试');
    const unknown = '给一个关于新的尚未识别主题的长篇说明';
    assert.equal(summarize(unknown).title, '学习交流');
    assert.notEqual(summarize(unknown).title, unknown + '讨论');
    assert.ok(context.DMateConversationTitles.legacySummary(unknown).title.includes('讨论'));
});

test('titles are bounded without splitting a surrogate pair, and old automatic names are recognizable', () => {
    const title = summarize('请解释关于' + '🧮'.repeat(40) + '的数据结构。').title;
    assert.ok(Array.from(title).length <= 22);
    assert.ok(!/[\uD800-\uDBFF]$/.test(title));
    assert.equal(legacyName('你好\n请解释欧拉回路与哈密顿回路的区别。', 'text'), '你好');
    assert.equal(legacyName('非常非常非常非常非常非常非常长的第一句。', 'text'), '非常非常非常非常非常非常非常长…');
});
