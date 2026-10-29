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
    const sourceLabels = { manual: '手动输入', ocr: '图片 / 绘图题', ai: 'AI 出题' };
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
        return { questions: questionOrder, sources, pending, retest, passed, wrong, notes, knowledge: knowledgeRows,
            activity: activity.slice(0, 6), next: priorities[0] || null,
            studySessions: sessions.filter(session => list(session.questions).length).length,
            hasAnyRecord: Boolean(questions.length || wrong.length || notes.length || events.length) };
    }

    function render(container, snapshot, actions = {}) {
        const document = container.ownerDocument;
        const el = (tag, className, value) => {
            const node = document.createElement(tag);
            if (className) node.className = className;
            if (value !== undefined) node.textContent = value;
            return node;
        };
        const button = (label, callback, className = 'lr-link') => {
            const node = el('button', className, label);
            node.type = 'button';
            node.addEventListener('click', callback);
            return node;
        };
        const section = (title, subtitle, className = '') => {
            const node = el('section', 'lr-section ' + className);
            const head = el('div', 'lr-section-head');
            head.append(el('h3', '', title));
            if (subtitle) head.append(el('span', 'lr-section-meta', subtitle));
            node.append(head);
            return node;
        };
        const description = value => el('p', 'lr-description', value);
        const badge = (label, tone = '') => el('span', 'lr-badge ' + tone, label);
        const openWrong = item => actions.wrong?.(item?.id);
        const rootNode = el('div', 'lr-report');
        container.replaceChildren(rootNode);
        const hero = el('div', 'lr-hero');
        const heroText = el('div');
        heroText.append(el('span', 'lr-eyebrow', '学习概览'), el('h2', '', '从学习记录，找到下一步'),
            description('题目、错题和概念笔记，放在一起回顾。'));
        hero.append(heroText, badge('全部现存记录'));
        rootNode.append(hero);

        const metrics = el('div', 'lr-metrics');
        let questionsSection;
        const metricRows = [
            ['题目记录', snapshot.questions.length, '按对话内题干去重', () => questionsSection?.scrollIntoView({ block: 'start', behavior: 'smooth' })],
            ['待订正', snapshot.pending.length, '先重新做，再记录订正', () => openWrong(snapshot.pending[0])],
            ['待复测', snapshot.retest.length, '已订正，尚未通过复测', () => openWrong(snapshot.retest[0])],
            ['概念笔记', snapshot.notes.length, '已写下内容的概念', () => actions.notebook?.()]
        ];
        for (const [label, count, hint, callback] of metricRows) {
            const card = button('', callback, 'lr-metric');
            card.setAttribute('aria-label', label + ' ' + count + '，' + hint);
            card.append(el('span', 'lr-metric-label', label), el('strong', 'lr-metric-value', String(count)), el('span', 'lr-metric-hint', hint));
            metrics.append(card);
        }
        rootNode.append(metrics);

        if (!snapshot.hasAnyRecord) {
            const empty = section('还没有学习记录', '', 'lr-empty');
            empty.append(description('发送前将“题目”选为“是”，或在图片 / 绘图核对时保留题目标记。收录题目、整理错题或写下概念后，这里就会有可回顾的内容。'),
                button('开始记录概念', () => actions.notebook?.(), 'lr-primary'), button('返回对话', () => actions.close?.()));
            rootNode.append(empty);
            return;
        }

        const grid = el('div', 'lr-grid');
        const next = section('下一步', '从一件具体的事开始', 'lr-next');
        if (snapshot.next) {
            const item = snapshot.next;
            const pending = stateOf(item) === 'pending';
            next.append(badge(pending ? '优先订正' : '复测验证', pending ? 'lr-attention' : 'lr-accent'),
                el('h4', 'lr-next-title', pending ? '先把这道错题弄明白' : '再做一道，验证订正效果'),
                el('p', 'lr-question-preview', preview(item.question, 155)),
                description(item.lastRetestResult === 'wrong' ? '最近一次复测未通过，建议回看解题思路后重新订正。'
                    : pending ? '先独立重做，在错题本记录订正；完成后再用复测检验。' : '这道题已完成订正，可以到错题本开始一道同类复测。'),
                button('查看这道错题', () => openWrong(item), 'lr-primary'));
        } else if (snapshot.notes.length) {
            next.append(badge('概念回顾', 'lr-accent'), el('h4', 'lr-next-title', '把理解再写清楚一点'),
                description('当前没有待订正或待复测的错题。打开笔记本，用自己的话补充一个概念，检查定义和条件是否说得清楚。'),
                button('打开笔记本', () => actions.notebook?.(), 'lr-primary'));
        } else {
            next.append(badge('整理理解', 'lr-accent'), el('h4', 'lr-next-title', '把这次学到的内容留下来'),
                description('当前没有待处理的错题。挑一个学过的知识点，写下定义、易混条件或解题方法，留作下次回顾。'),
                button('记录概念笔记', () => actions.notebook?.(), 'lr-primary'));
        }
        grid.append(next);

        const progress = section('错题进度', snapshot.wrong.length + ' 道收录错题');
        const states = [[snapshot.pending, '待订正', 'lr-pending'], [snapshot.retest, '待复测', 'lr-retest'], [snapshot.passed, '已通过复测', 'lr-passed']];
        const bar = el('div', 'lr-progress-bar');
        bar.setAttribute('aria-label', states.map(([items, label]) => label + ' ' + items.length + ' 道').join('，'));
        for (const [items, , tone] of states) {
            if (!items.length) continue;
            const segment = el('span', tone);
            segment.style.flexGrow = String(items.length);
            bar.append(segment);
        }
        progress.append(bar);
        const legend = el('div', 'lr-progress-legend');
        for (const [items, label, tone] of states) {
            const row = el('div', 'lr-progress-row');
            row.append(el('i', tone), el('span', '', label), el('strong', '', String(items.length)));
            legend.append(row);
        }
        progress.append(legend, description(snapshot.wrong.length ? '订正是第一步，通过复测后再确认效果。' : '遇到需要回看的题目，可以从对话中“记为错题”。'),
            button('打开错题本', () => openWrong()));
        grid.append(progress);
        rootNode.append(grid);

        const tracking = section('知识追踪', snapshot.knowledge.length ? '已记录 ' + snapshot.knowledge.length + ' 个知识点' : '随学习记录逐步积累');
        if (!snapshot.knowledge.length) {
            tracking.append(description('题目分析或错题中出现知识点后，这里会展示对应记录。'));
        } else {
            tracking.append(description('优先回顾待订正和待复测的知识点，同时保留题目与讲解记录。'));
            const rows = el('div', 'lr-knowledge-list');
            for (const point of snapshot.knowledge.slice(0, 5)) {
                const row = el('div', 'lr-knowledge-row');
                const info = el('div', 'lr-knowledge-info');
                info.append(el('strong', '', point.name));
                const details = [];
                if (point.pending) details.push(point.pending + ' 道待订正');
                if (point.retest) details.push(point.retest + ' 道待复测');
                if (point.questions) details.push(point.questions + ' 条题目记录');
                if (point.support) details.push(point.support + ' 条讲解记录');
                else if (point.events) details.push(point.events + ' 条学习记录');
                if (point.passed) details.push(point.passed + ' 道通过复测');
                info.append(el('span', 'lr-row-detail', details.join(' · ')));
                row.append(info, badge(point.pending ? '待订正' : point.retest ? '待复测' : point.support ? '有讲解记录' : '已记录',
                    point.pending ? 'lr-attention' : point.retest ? 'lr-accent' : ''));
                rows.append(row);
            }
            tracking.append(rows);
        }
        tracking.append(button('查看知识图谱', () => actions.knowledge?.()));
        rootNode.append(tracking);

        questionsSection = section('题目档案', snapshot.studySessions + ' 个对话中的题目');
        questionsSection.id = 'learningReportQuestions';
        questionsSection.append(description('当前对话优先，同组多图按一题显示。AI 出题记录不代表已完成作答。'));
        if (snapshot.questions.length) {
            const filters = el('div', 'lr-filters');
            filters.setAttribute('aria-label', '题目来源筛选');
            const questionList = el('div', 'lr-question-list');
            let source = 'all', visible = 4;
            const more = button('查看更多题目', () => { visible += 6; drawQuestions(); });
            const drawQuestions = () => {
                const matching = snapshot.questions.filter(question => source === 'all' || question.sourceKind === source);
                questionList.replaceChildren();
                for (const question of matching.slice(0, visible)) {
                    const row = button('', () => actions.question?.(question), 'lr-question-row');
                    const meta = el('span', 'lr-question-meta');
                    meta.append(badge(sourceLabels[question.sourceKind]), el('span', 'lr-session-name', question.sessionName));
                    row.append(meta, el('span', 'lr-question-text', preview(question.text, 118)), el('span', 'lr-row-open', '查看原题 →'));
                    questionList.append(row);
                }
                if (!matching.length) questionList.append(description('这个来源还没有题目记录。'));
                more.hidden = matching.length <= visible;
                more.textContent = '查看更多题目（还有 ' + Math.max(0, matching.length - visible) + ' 条）';
                for (const child of filters.children) child.setAttribute('aria-pressed', String(child.dataset.source === source));
            };
            for (const [key, label, count] of [['all', '全部', snapshot.questions.length], ...Object.entries(sourceLabels).map(([key, label]) => [key, label, snapshot.sources[key]])]) {
                const filter = button(label + ' ' + count, () => { source = key; visible = 4; drawQuestions(); }, 'lr-filter');
                filter.dataset.source = key;
                filters.append(filter);
            }
            questionsSection.append(filters, questionList, more);
            drawQuestions();
        } else questionsSection.append(description('还没有标记为题目的记录。发送前将“题目”选为“是”，或在图片 / 绘图核对时确认题目标记。'));
        rootNode.append(questionsSection);

        const bottom = el('div', 'lr-grid lr-bottom-grid');
        const activity = section('最近活动', '按记录时间排序');
        if (!snapshot.activity.length) activity.append(description('还没有最近活动。已有题目仍可在题目档案中查看。'));
        const activityList = el('div', 'lr-activity-list');
        for (const item of snapshot.activity) {
            const row = button('', () => item.kind === 'wrong' ? actions.wrong?.(item.id)
                : item.kind === 'notebook' ? actions.notebook?.() : actions.session?.(item.sessionId), 'lr-activity-row');
            const info = el('span', 'lr-activity-info');
            info.append(el('strong', '', item.label), el('span', 'lr-row-detail', preview(item.detail, 65)));
            const date = el('time', 'lr-activity-time', new Date(item.at).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
                + ' ' + new Date(item.at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }));
            date.dateTime = new Date(item.at).toISOString();
            row.append(info, date);
            activityList.append(row);
        }
        activity.append(activityList);
        bottom.append(activity);
        const notebook = section('概念笔记', snapshot.notes.length + ' 个有内容的概念');
        if (!snapshot.notes.length) notebook.append(description('把定义、例子和易混条件写下来，方便下一次复习。'));
        for (const note of [...snapshot.notes].sort((a, b) => time(b.updatedAt) - time(a.updatedAt)).slice(0, 3)) {
            const row = el('div', 'lr-note-row');
            row.append(el('strong', '', text(note.title) || '未命名概念'), el('span', 'lr-row-detail', preview(note.content, 65) || '已记录概念名称，可继续补充理解。'));
            notebook.append(row);
        }
        notebook.append(button('打开笔记本', () => actions.notebook?.()));
        bottom.append(notebook);
        rootNode.append(bottom, el('p', 'lr-footnote', '报告依据当前保留的题目、错题、概念笔记和学习记录整理。'));
    }
    const api = { buildSnapshot, render };
    root.DMateLearningReport = api;
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
