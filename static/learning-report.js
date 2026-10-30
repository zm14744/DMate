(function (root) {
    'use strict';
    const list = value => Array.isArray(value) ? value : [];
    const text = value => typeof value === 'string' ? value.trim() : '';
    const points = value => [...new Set(list(value).map(text).filter(value => value && !['待识别', '暂未识别'].includes(value)))];
    const time = value => Number.isFinite(Number(value)) && Number(value) > 0 && Number(value) <= 8640000000000000 ? Number(value) : 0;
    const preview = (value, limit = 100) => {
        const clean = text(value).replace(/\s+/g, ' ');
        return clean.length > limit ? clean.slice(0, limit) + '…' : clean;
    };
    const stateOf = item => item.retestPassed ? 'passed' : item.corrected ? 'retest' : 'pending';
    const sourceOf = item => item.role === 'ai' ? 'ai' : item.source === 'ocr' ? 'ocr' : 'manual';
    const eventLabels = { seen: '学习知识点', support: '讲解记录', wrong: '答错记录', correct: '答对记录', reviewed: '订正记录' };

    function buildSnapshot(options = {}) {
        const sessions = list(options.sessions);
        const learning = options.learning || {};
        const live = new Map(sessions.map(session => [String(session.id), session]));
        const events = list(learning.events).filter(event => event && event.sessionId != null
            && live.has(String(event.sessionId)) && eventLabels[event.type] && points(event.points).length);
        const wrong = list(learning.wrongQuestions).filter(item => item && text(item.question));
        const notes = list(options.notebook?.notes).filter(note => note && (text(note.title) || text(note.content)));
        const questions = sessions.flatMap(session => list(session.questions).map(question => ({
            ...question, sessionId: session.id, sessionName: text(session.name) || '未命名对话', sourceKind: sourceOf(question)
        })));
        const knowledge = new Map();
        const pointRecord = name => {
            if (!knowledge.has(name)) knowledge.set(name, { name, questions: 0, events: 0, support: 0, pending: 0, retest: 0, passed: 0, updatedAt: 0 });
            return knowledge.get(name);
        };
        for (const question of questions) {
            for (const name of points([...list(question.knowledgePoints), ...list(question.teaching?.knowledge_points), ...list(question.teaching?.focus_points)])) {
                pointRecord(name).questions++;
            }
        }
        for (const event of events) {
            for (const name of points(event.points)) {
                const row = pointRecord(name);
                row.events++;
                if (event.type === 'support') row.support++;
                row.updatedAt = Math.max(row.updatedAt, time(event.createdAt));
            }
        }
        for (const item of wrong) {
            for (const name of points([...list(item.focusPoints), ...list(item.knowledgePoints)])) {
                const row = pointRecord(name);
                row[stateOf(item)]++;
                row.updatedAt = Math.max(row.updatedAt, time(item.updatedAt));
            }
        }
        const knowledgeRows = [...knowledge.values()].sort((a, b) => b.pending - a.pending || b.retest - a.retest
            || b.support - a.support || b.updatedAt - a.updatedAt || b.questions - a.questions || a.name.localeCompare(b.name, 'zh-CN'));
        const pending = wrong.filter(item => stateOf(item) === 'pending');
        const retest = wrong.filter(item => stateOf(item) === 'retest');
        const passed = wrong.filter(item => stateOf(item) === 'passed');
        const priorities = [...pending, ...retest].sort((a, b) => Number(b.lastRetestResult === 'wrong') - Number(a.lastRetestResult === 'wrong')
            || Number(stateOf(a) === 'retest') - Number(stateOf(b) === 'retest') || time(b.updatedAt) - time(a.updatedAt));
        const activity = [];
        // Event timestamps belong to study events, never to untimed messages.
        // Consecutive same-kind records for a session are combined for readability.
        const bundles = new Map();
        for (const event of [...events].sort((a, b) => time(b.createdAt) - time(a.createdAt))) {
            const at = time(event.createdAt);
            if (!at) continue;
            const key = String(event.sessionId) + ':' + event.type;
            let entry = bundles.get(key);
            if (!entry || entry.at - at > 60000) {
                entry = { kind: 'session', label: eventLabels[event.type], detail: '', at, sessionId: event.sessionId, names: [] };
                bundles.set(key, entry);
                activity.push(entry);
            }
            entry.names = points([...entry.names, ...points(event.points)]);
            entry.detail = entry.names.join('、');
        }
        for (const item of wrong) {
            const at = Math.max(time(item.createdAt), time(item.correctedAt), time(item.lastRetestAt), time(item.retestPassedAt));
            if (!at) continue;
            const label = at === time(item.lastRetestAt) && item.lastRetestResult === 'wrong' ? '复测未通过'
                : at === time(item.retestPassedAt) ? '通过复测'
                    : at === time(item.correctedAt) ? '完成订正' : '收录错题';
            activity.push({ kind: 'wrong', id: item.id, label, detail: item.question, at });
        }
        for (const note of notes) {
            if (time(note.updatedAt)) activity.push({ kind: 'notebook', label: '更新概念笔记', detail: text(note.title) || preview(note.content, 55), at: time(note.updatedAt) });
        }
        activity.sort((a, b) => b.at - a.at);
        const sources = { manual: 0, ocr: 0, ai: 0 };
        for (const question of questions) sources[question.sourceKind]++;
        // There is no timestamp on historical questions. Keep the current
        // conversation first and name the ordering explicitly in the UI.
        const questionOrder = [...questions].reverse().sort((a, b) => Number(String(b.sessionId) === String(options.currentSessionId))
            - Number(String(a.sessionId) === String(options.currentSessionId)));
        const recentPoints = points([
            ...[...events].sort((a, b) => time(b.createdAt) - time(a.createdAt)).flatMap(event => list(event.points)),
            ...questionOrder.flatMap(question => [...list(question.knowledgePoints), ...list(question.teaching?.knowledge_points), ...list(question.teaching?.focus_points)]),
            ...knowledgeRows.map(point => point.name)
        ]).slice(0, 3);
        return { questions: questionOrder, sources, pending, retest, passed, wrong, notes, knowledge: knowledgeRows, recentPoints,
            activity: activity.slice(0, 6), next: priorities[0] || null,
            studySessions: sessions.filter(session => list(session.questions).length).length,
            hasAnyRecord: Boolean(questions.length || wrong.length || notes.length || events.length) };
    }

    function reviewSections(snapshot) {
        const quoted = values => values.map(value => '“' + value + '”').join('、');
        const recent = points(snapshot.recentPoints).slice(0, 3);
        const notes = [...list(snapshot.notes)].sort((a, b) => time(b.updatedAt) - time(a.updatedAt));
        const item = snapshot.next;
        const itemPoints = item ? points([...list(item.focusPoints), ...list(item.knowledgePoints)]) : [];
        const target = itemPoints.length ? quoted(itemPoints.slice(0, 2)) : '这道错题';
        let study, revisit, next;

        if (recent.length) {
            study = recent.length === 1 ? '最近的学习记录主要围绕' + quoted(recent) + '展开。'
                : '最近的学习记录中出现了' + quoted(recent) + '等内容。';
        } else if (notes.length) {
            const titles = notes.map(note => text(note.title)).filter(Boolean).slice(0, 3);
            study = titles.length ? '最近整理的概念笔记包括' + quoted(titles) + '。'
                : '已经记录了一些概念笔记，可以继续整理其中的定义、例子和疑问。';
        } else if (snapshot.hasAnyRecord) {
            study = '已经留下了一些题目或错题记录，可以结合原题和自己的解题过程继续回顾。';
        } else {
            study = '目前还没有可回顾的学习记录。记录一道题、整理错题或写下概念笔记后，这里会显示相关内容。';
        }

        if (item?.lastRetestResult === 'wrong') {
            revisit = target + '最近一次复测未通过，可以回看原题和订正思路，再检查容易遗漏的条件。';
        } else if (item && stateOf(item) === 'pending') {
            revisit = target + '还没有完成订正，可以先回看题目条件和自己的解题过程。';
        } else if (item) {
            revisit = target + '已经有订正记录，但目前还没有通过复测。';
        } else if (list(snapshot.wrong).length && list(snapshot.passed).length === list(snapshot.wrong).length) {
            revisit = '目前收录的错题都已有通过复测的记录，可以隔一段时间再回看其中的易错条件。';
        } else if (notes.length) {
            const title = text(notes[0].title);
            revisit = (title ? '可以再看看“' + title + '”中的定义、例子和适用条件，' : '可以再看看已有概念笔记中的定义、例子和适用条件，')
                + '检查能否用自己的话说明。';
        } else if (recent.length) {
            revisit = '可以再看看' + quoted(recent.slice(0, 2)) + '的定义和使用条件，并对照原题检查自己的理解。';
        } else {
            revisit = '目前还没有待订正或待复测的记录。遇到值得回看的题目时，可以加入错题本并记录原因。';
        }

        if (item && stateOf(item) === 'pending') {
            next = '如果想继续，可以从还没有完成订正的题里挑一道，先独立重做，再记录订正。';
        } else if (item) {
            next = '如果想继续，可以从已经订正但还没有通过复测的题里挑一道，再测一次。';
        } else if (notes.length) {
            next = '如果想继续，可以打开一条概念笔记补充例子，或选择两个概念比较它们之间的联系。';
        } else if (recent.length) {
            next = '如果想继续，可以围绕' + quoted(recent.slice(0, 1)) + '做一道练习，或把定义和易错点记成笔记。';
        } else if (snapshot.hasAnyRecord) {
            next = '如果想继续，可以回到一道已有题目，检查关键条件，并把需要回看的部分整理到错题本或笔记本。';
        } else {
            next = '可以先从一个想学的概念开始提问；希望把输入收录为一道题时，在发送前将“题目”设为“是”。';
        }
        return [['最近学习', study], ['值得再看看', revisit], ['接下来可以做', next]];
    }

    function render(container, snapshot) {
        const document = container.ownerDocument;
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
