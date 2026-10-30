(function (root) {
    'use strict';
    const list = value => Array.isArray(value) ? value : [];
    const text = value => typeof value === 'string' ? value.trim() : '';
    const points = value => [...new Set(list(value).map(text).filter(value => value && !['待识别', '暂未识别'].includes(value)))];
    const time = value => Number.isFinite(Number(value)) && Number(value) > 0 && Number(value) <= 8640000000000000 ? Number(value) : 0;
    const preview = (value, limit = 45) => {
        const clean = text(value).replace(/\s+/g, ' ');
        return clean.length > limit ? clean.slice(0, limit) + '…' : clean;
    };
    const stateOf = item => item.retestPassed ? 'passed' : item.corrected ? 'retest' : 'pending';
    const eventTypes = new Set(['seen', 'support', 'wrong', 'correct', 'reviewed']);
    const quoted = values => values.map(value => '“' + value + '”').join('、');
    const noteName = note => text(note.title) || preview(note.content);

    function drawingRecord(page) {
        if (!page || typeof page !== 'object' || !page.document || typeof page.document !== 'object') return null;
        const graphs = list(page.document.graphs).filter(graph => graph && typeof graph === 'object');
        const vertices = graphs.flatMap(graph => list(graph.vertices)).filter(vertex => vertex && typeof vertex === 'object');
        const edges = graphs.flatMap(graph => list(graph.edges)).filter(edge => edge && typeof edge === 'object');
        const body = text(page.document.body_text);
        if (!vertices.length && !edges.length && !body) return null;
        return {
            id: page.id,
            name: text(page.name) || '未命名绘图',
            updatedAt: time(page.updatedAt),
            vertexCount: vertices.length,
            edgeCount: edges.length,
            directedCount: edges.filter(edge => edge.direction === 'forward').length,
            undirectedCount: edges.filter(edge => edge.direction === 'undirected').length,
            weightedCount: edges.filter(edge => (typeof edge.weight === 'number' && Number.isFinite(edge.weight)) || text(edge.weight)).length,
            body
        };
    }

    function buildSnapshot(options = {}) {
        const sessions = list(options.sessions).filter(session => session && typeof session === 'object');
        const live = new Set(sessions.map(session => String(session.id)));
        const learning = options.learning || {};
        const events = list(learning.events).filter(event => event && event.sessionId != null
            && live.has(String(event.sessionId)) && eventTypes.has(event.type) && points(event.points).length);
        const wrong = list(learning.wrongQuestions).filter(item => item && text(item.question));
        const notes = list(options.notebook?.notes).filter(note => note && (text(note.title) || text(note.content)))
            .sort((a, b) => time(b.updatedAt) - time(a.updatedAt));
        const drawings = list(options.drawings).map(drawingRecord).filter(Boolean).sort((a, b) => b.updatedAt - a.updatedAt);
        // Question histories are collected by the caller. Untimed questions
        // stay untimed; ordering them does not invent study dates.
        const questions = sessions.flatMap(session => list(session.questions).filter(question => question && text(question.text))
            .map(question => ({ ...question, sessionId: session.id })));
        const questionOrder = [...questions].reverse().sort((a, b) => Number(String(b.sessionId) === String(options.currentSessionId))
            - Number(String(a.sessionId) === String(options.currentSessionId)));
        const recentPoints = points([
            ...[...events].sort((a, b) => time(b.createdAt) - time(a.createdAt)).flatMap(event => list(event.points)),
            ...questionOrder.flatMap(question => [...list(question.knowledgePoints), ...list(question.teaching?.knowledge_points), ...list(question.teaching?.focus_points)]),
            ...[...wrong].sort((a, b) => time(b.updatedAt) - time(a.updatedAt)).flatMap(item => [...list(item.focusPoints), ...list(item.knowledgePoints)])
        ]).slice(0, 3);
        const pending = wrong.filter(item => stateOf(item) === 'pending');
        const retest = wrong.filter(item => stateOf(item) === 'retest');
        const passed = wrong.filter(item => stateOf(item) === 'passed');
        const priorities = [...pending, ...retest].sort((a, b) => Number(b.lastRetestResult === 'wrong') - Number(a.lastRetestResult === 'wrong')
            || Number(stateOf(a) === 'retest') - Number(stateOf(b) === 'retest') || time(b.updatedAt) - time(a.updatedAt));
        return {
            questions: questionOrder, wrong, pending, retest, passed, notes, drawings, recentPoints,
            next: priorities[0] || null,
            hasAnyRecord: Boolean(questions.length || wrong.length || notes.length || drawings.length || events.length)
        };
    }

    function describeDrawing(drawing) {
        const label = '绘图“' + preview(drawing.name) + '”';
        if (!drawing.vertexCount && !drawing.edgeCount) return label + '保留了文字“' + preview(drawing.body) + '”。';
        let description = label + '记录了' + drawing.vertexCount + '个顶点、' + drawing.edgeCount + '条边';
        const attributes = [];
        if (drawing.directedCount) attributes.push(drawing.directedCount + '条有向边');
        if (drawing.undirectedCount) attributes.push(drawing.undirectedCount + '条无向边');
        if (drawing.weightedCount) attributes.push(drawing.weightedCount + '条边带有权值');
        if (attributes.length) description += '，其中' + attributes.join('、');
        return description + '。';
    }

    function reviewSections(snapshot) {
        const recent = points(snapshot.recentPoints).slice(0, 3);
        const notes = list(snapshot.notes);
        const drawings = list(snapshot.drawings);
        const item = snapshot.next;
        const itemPoints = item ? points([...list(item.focusPoints), ...list(item.knowledgePoints)]) : [];
        const target = itemPoints.length ? quoted(itemPoints.slice(0, 2)) : '这道错题';
        const study = [], revisit = [], next = [];

        if (recent.length) {
            study.push(recent.length === 1 ? '现有学习记录主要涉及' + quoted(recent) + '。'
                : '学习记录中出现了' + quoted(recent) + '等内容。');
        } else if (list(snapshot.questions).length || list(snapshot.wrong).length) {
            const counts = [];
            if (list(snapshot.questions).length) counts.push(snapshot.questions.length + '道题目');
            if (list(snapshot.wrong).length) counts.push(snapshot.wrong.length + '条错题');
            study.push('现有记录中保留了' + counts.join('和') + '。');
        }
        // Every present source contributes; chat records must not hide notes
        // or drawings behind an exclusive fallback branch.
        for (const note of notes.slice(0, 2)) {
            const title = text(note.title), content = preview(note.content);
            study.push(title ? '概念笔记“' + title + '”' + (content ? '记录了“' + content + '”。' : '已保留。')
                : '概念笔记中记录了“' + content + '”。');
        }
        if (drawings.length) {
            study.push(...drawings.slice(0, 2).map(describeDrawing));
            if (drawings.length > 2) study.push('另外还有' + (drawings.length - 2) + '张有内容的绘图。');
        }

        if (item?.lastRetestResult === 'wrong') {
            revisit.push(target + '最近一次复测未通过，可以回看原题和订正思路。');
        } else if (item && stateOf(item) === 'pending') {
            revisit.push(target + '还没有完成订正，可以先回看题目条件和自己的解题过程。');
        } else if (item) {
            revisit.push(target + '已经有订正记录，但目前还没有通过复测。');
        } else if (list(snapshot.wrong).length && list(snapshot.passed).length === list(snapshot.wrong).length) {
            revisit.push('目前收录的错题都已有通过复测的记录。');
        } else if (recent.length) {
            revisit.push('可以再看看' + quoted(recent.slice(0, 2)) + '的定义和使用条件。');
        } else if (list(snapshot.questions).length) {
            revisit.push('可以回看已记录题目的条件和推导过程。');
        }
        if (notes.length) revisit.push('笔记' + quoted([noteName(notes[0])]) + '可以结合原文再检查定义、例子和适用条件。');
        if (drawings.length) {
            const drawing = drawings[0];
            const checks = ['端点'];
            if (drawing.directedCount || drawing.undirectedCount) checks.push('方向');
            if (drawing.weightedCount) checks.push('权值');
            revisit.push(drawing.edgeCount ? '可以对照绘图“' + preview(drawing.name) + '”检查边的' + checks.join('、') + '。'
                : drawing.vertexCount ? '可以回看绘图“' + preview(drawing.name) + '”中各顶点的位置和标签。'
                    : '可以回看绘图“' + preview(drawing.name) + '”中保留的文字内容。');
        }

        if (item && stateOf(item) === 'pending') {
            next.push('可以先从还没有完成订正的题里挑一道，独立重做后记录订正。');
        } else if (item) {
            next.push('可以从已经订正但还没有通过复测的题里挑一道，再测一次。');
        } else if (recent.length) {
            next.push('可以围绕' + quoted(recent.slice(0, 1)) + '再问一个具体问题，或做一道练习。');
        } else if (list(snapshot.questions).length) {
            next.push('可以回到一道已记录的题目，继续核对条件和解题过程。');
        }
        if (notes.length) next.push((next.length ? '也可以' : '可以') + (notes.length > 1 ? '选择已有的概念笔记比较联系，或补充具体例子。'
            : '在笔记' + quoted([noteName(notes[0])]) + '中补充一个具体例子。'));
        if (drawings.length) next.push((next.length ? '也可以' : '可以') + '继续编辑绘图“' + preview(drawings[0].name) + '”，需要保存图片时将它导出。');
        return [['最近学习', study.join('') || '无'], ['值得再看看', revisit.join('') || '无'], ['接下来可以做', next.join('') || '无']];
    }

    function render(container, snapshot) {
        const document = container.ownerDocument;
        if (!snapshot.hasAnyRecord) {
            const empty = document.createElement('div');
            empty.className = 'learning-review-empty';
            empty.textContent = '无';
            container.replaceChildren(empty);
            return;
        }
        const rootNode = document.createElement('div');
        rootNode.className = 'lr-review';
        for (const [title, description] of reviewSections(snapshot)) {
            const section = document.createElement('section');
            section.className = 'learning-review-section';
            const heading = document.createElement('h3');
            heading.className = 'learning-review-section-title';
            heading.textContent = title;
            const body = document.createElement('p');
            body.className = 'learning-review-section-text';
            body.textContent = description;
            section.append(heading, body);
            rootNode.append(section);
        }
        container.replaceChildren(rootNode);
    }
    const api = { buildSnapshot, render };
    root.DMateLearningReport = api;
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
