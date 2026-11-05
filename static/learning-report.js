(function (root) {
    'use strict';
    const guidance = root.DMateLearningReviewGuidance
        || (typeof module !== 'undefined' && module.exports ? require('./learning-review-guidance.js') : null);
    const list = value => Array.isArray(value) ? value : [];
    const text = value => typeof value === 'string' ? value.trim() : '';
    const points = value => [...new Set(list(value).map(text).filter(value => value && !['待识别', '暂未识别'].includes(value)))];
    const time = value => Number.isFinite(Number(value)) && Number(value) > 0 && Number(value) <= 8640000000000000 ? Number(value) : 0;
    const key = value => value == null ? '' : String(value);
    const preview = (value, limit = 45) => {
        // Review cards are plain-text summaries. Do not truncate a TeX fragment
        // into visible source code; full formulas remain in the original record.
        const clean = text(value)
            .replace(/```[\s\S]*?```/g, '（代码）')
            .replace(/\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$(?:\\[\s\S]|[^$\\])*\$/g, '（公式）')
            .replace(/\$[^$]*$|\\(?:\[|\()[\s\S]*$/, '（公式）')
            .replace(/\\[a-zA-Z]+(?:\{[^}]*\})?/g, '（公式）')
            .replace(/\s+/g, ' ');
        return clean.length > limit ? clean.slice(0, limit) + '…' : clean;
    };
    const quoted = values => values.map(value => '“' + preview(value) + '”').join('、');
    const detected = value => guidance ? guidance.topics(text(value)) : [];
    const recordPoints = (metadata, body) => {
        const labels = points(metadata);
        // Match the combined evidence in specificity order: a concrete topic
        // in the question must not lose to its broader stored category.
        return points([...detected([...labels, text(body)].join(' ')),
            ...labels.filter(value => !detected(value).length)]);
    };
    const eventTypes = new Set(['seen', 'support', 'wrong', 'correct', 'reviewed']);
    const noteName = note => preview(text(note.title) || note.content);
    const questionLabel = (record, kind = '题目') => {
        const snippet = preview(record.question || record.text);
        if (snippet.includes('（公式）')) return record.points.length
            ? '涉及' + quoted(record.points.slice(0, 1)) + '的' + kind : '含公式的' + kind;
        return kind + '“' + snippet + '”';
    };

    function retestStatus(item, sessions) {
        const selected = new Set(list(item.passedRetestSessionIds).map(key).filter(Boolean));
        const manual = selected.size > 0 || Number(item.manualRetestPassCount) > 0;
        const base = item.retestPassed ? 'passed' : item.corrected ? 'retest' : 'pending';
        const result = (state, failed = false, uncertain = false) => ({ state, failed, manual, uncertain });
        const attempts = new Map();
        for (const record of list(item.retestRecords)) {
            if (record && key(record.id)) attempts.set(key(record.id), { id: key(record.id), at: time(record.createdAt) });
        }
        for (const session of sessions) {
            if (!session.retest || key(session.retest.wrongQuestionId) !== key(item.id) || !key(session.id)) continue;
            const id = key(session.id), previous = attempts.get(id);
            attempts.set(id, { id, at: time(session.retest.startedAt) || previous?.at || 0, live: session.retest });
        }
        const namedId = key(item.lastRetestSessionId);
        const latest = [...attempts.values()].sort((a, b) => b.at - a.at
            || Number(b.id === namedId) - Number(a.id === namedId))[0];
        // A new retest changes the session ID before replacing the old verdict.
        if (namedId && !attempts.has(namedId)) return result(base, false, true);
        if (!latest) {
            if (manual && !item.lastRetestResult) return result('passed', false, selected.size === 0);
            return result(base, false, Boolean(item.lastRetestResult || manual));
        }
        const live = latest.live;
        let verdict = '';
        if (live?.stage === 'finished' && ['correct', 'wrong'].includes(live.result)) verdict = live.result;
        else if (!live && latest.id === namedId && latest.at && time(item.lastRetestAt) >= latest.at
            && ['correct', 'wrong'].includes(item.lastRetestResult)) verdict = item.lastRetestResult;
        if (selected.has(latest.id)) return result('passed', false, verdict === 'wrong' || live?.stage === 'checking');
        if (verdict === 'correct') return result('passed');
        if (verdict === 'wrong') return result(item.corrected ? 'retest' : 'pending', true);
        return result(base, false, true);
    }

    function drawingRecord(page) {
        if (!page || typeof page !== 'object' || !page.document || typeof page.document !== 'object') return null;
        const graphs = list(page.document.graphs).filter(graph => graph && typeof graph === 'object');
        const vertices = graphs.flatMap(graph => list(graph.vertices)).filter(vertex => vertex && typeof vertex === 'object');
        const edges = graphs.flatMap(graph => list(graph.edges)).filter(edge => edge && typeof edge === 'object');
        const body = text(page.document.body_text);
        if (!vertices.length && !edges.length && !body) return null;
        const topicPoints = detected([page.name, body, ...graphs.map(graph => graph.name)].filter(Boolean).join(' '));
        return {
            id: page.id, type: 'drawing', name: text(page.name) || '未命名绘图',
            at: time(page.updatedAt), vertexCount: vertices.length, edgeCount: edges.length,
            directedCount: edges.filter(edge => ['forward', 'backward', 'both'].includes(edge.direction)).length,
            weightedCount: edges.filter(edge => (typeof edge.weight === 'number' && Number.isFinite(edge.weight)) || text(edge.weight)).length,
            points: points([...topicPoints, ...(vertices.length || edges.length ? ['图的表示'] : [])]), body
        };
    }

    function discussionPoints(message) {
        if (!message || message.role !== 'user' || message.isError || message.isNotice) return [];
        const body = text(message.text);
        // Product requests and code are not evidence of studying mathematics.
        if (/(?:按钮|界面|上传|下载|同步|登录|主题颜色|背景颜色|字体|题目标记|渲染|页面|弹窗)/i.test(body)) return [];
        return detected(body);
    }

    function buildSnapshot(options = {}) {
        const sessions = list(options.sessions).filter(session => session && typeof session === 'object');
        const learning = options.learning || {};
        const questions = [], discussions = [], evidence = new Map(), livePoints = new Map();
        for (const session of sessions) {
            const formalIndexes = new Set(), records = [];
            for (const question of list(session.questions)) {
                if (!question || !text(question.text)) continue;
                formalIndexes.add(question.index);
                const record = { ...question, type: 'question', sessionId: session.id,
                    at: time(question.createdAt), points: recordPoints([
                        ...list(question.knowledgePoints), ...list(question.teaching?.knowledge_points),
                        ...list(question.teaching?.focus_points)
                    ], question.text) };
                questions.push(record);
                records.push(record);
            }
            list(session.messages).forEach((message, index) => {
                if (formalIndexes.has(index)) return;
                const topics = discussionPoints(message);
                if (!topics.length) return;
                const record = { type: 'discussion', sessionId: session.id, index,
                    text: text(message.text), points: topics, at: time(message.createdAt) };
                discussions.push(record);
                records.push(record);
            });
            evidence.set(key(session.id), records);
            livePoints.set(key(session.id), new Set(records.flatMap(record => record.points)));
        }
        // Legacy events lack message IDs. They can date a topic only while it
        // still has evidence in the same retained conversation.
        const eventTimes = new Map();
        for (const event of list(learning.events)) {
            if (!event || !eventTypes.has(event.type) || event.sessionId == null) continue;
            const id = key(event.sessionId), currentPoints = livePoints.get(id);
            if (!currentPoints?.size) continue;
            const dates = eventTimes.get(id) || new Map();
            for (const point of recordPoints(event.points, '')) {
                if (currentPoints.has(point)) dates.set(point, Math.max(dates.get(point) || 0, time(event.createdAt)));
            }
            eventTimes.set(id, dates);
        }
        for (const record of [...questions, ...discussions]) {
            const dates = eventTimes.get(key(record.sessionId));
            record.at = record.points.reduce((at, point) => Math.max(at, dates?.get(point) || 0), record.at);
        }
        const wrong = list(learning.wrongQuestions)
            .filter(item => item && text(item.question) && !learning.deletedWrongQuestionIds?.[key(item.id)])
            .map(item => ({ ...item, type: 'wrong', at: time(item.updatedAt) || time(item.createdAt),
                points: recordPoints([...list(item.focusPoints), ...list(item.knowledgePoints)], item.question),
                status: retestStatus(item, sessions) }));
        // The caller normalizes notebook tombstones and enforces drawing owner
        // boundaries. These copies never write review data back to the sources.
        const notes = list(options.notebook?.notes).filter(note => note && (text(note.title) || text(note.content)))
            .map(note => ({ ...note, type: 'note', at: time(note.updatedAt), points: detected(text(note.title) + ' ' + text(note.content)) }))
            .sort((a, b) => b.at - a.at);
        const drawings = list(options.drawings).map(drawingRecord).filter(Boolean).sort((a, b) => b.at - a.at);
        const chat = sessions.flatMap(session => (evidence.get(key(session.id)) || [])
            .slice().sort((a, b) => (a.index || 0) - (b.index || 0))).reverse();
        const sources = [...chat, ...wrong, ...notes, ...drawings].sort((a, b) => b.at - a.at);
        const pending = wrong.filter(item => item.status.state === 'pending');
        const retest = wrong.filter(item => item.status.state === 'retest');
        const passed = wrong.filter(item => item.status.state === 'passed');
        const priorities = [...pending, ...retest].sort((a, b) => Number(b.status.failed) - Number(a.status.failed)
            || Number(a.status.state === 'retest') - Number(b.status.state === 'retest') || b.at - a.at);
        return {
            questions, discussions, wrong, pending, retest, passed, notes, drawings, sources,
            recentPoints: points(sources.flatMap(record => record.points)).slice(0, 3),
            next: priorities[0] || null, target: priorities[0] || sources[0] || null,
            hasAnyRecord: Boolean(sources.length)
        };
    }

    function describeDrawing(drawing) {
        const label = '绘图“' + preview(drawing.name) + '”';
        if (!drawing.vertexCount && !drawing.edgeCount) return label + '保留了文字“' + preview(drawing.body) + '”。';
        return label + '记录了' + drawing.vertexCount + '个顶点、' + drawing.edgeCount + '条边'
            + (drawing.directedCount ? '，含有向边' : '') + (drawing.weightedCount ? '，含边权' : '') + '。';
    }

    function targetAdvice(target) {
        if (target.type === 'drawing' && target.points.every(point => point === '图的表示')) {
            if (target.edgeCount) return {
                action: '任选一个顶点，写出与它相连的顶点，再按固定顶点顺序填写邻接矩阵中对应的一行。',
                check: '逐条核对图中的边与矩阵项' + (target.directedCount ? '，有向边要区分从该点出发和指向该点' : '')
                    + (target.weightedCount ? '；先说明矩阵记录的是连边关系、边数还是权值，按约定填写' : '；若有重边或自环，先说明矩阵采用的约定') + '。'
            };
            if (target.vertexCount) return {
                action: target.vertexCount === 1
                    ? '写清现有顶点表示的对象，再说明是否需要另一个对象来表达关系。'
                    : '选两个顶点，写清各自表示的对象，以及是否存在要表达的关系。',
                check: '根据关系的定义决定是否连边，并说明理由；顶点靠得近不代表存在关系。'
            };
        }
        return guidance ? guidance.advice(target.points[0] || '') : {
            action: '先不看原文，用自己的话写出一个定义，再给一个例子。',
            check: '对照原文，逐项核对定义的条件是否满足。'
        };
    }

    function reviewSections(snapshot) {
        const study = [];
        const chat = snapshot.sources.filter(record => ['question', 'discussion'].includes(record.type));
        const chatPoints = points(chat.flatMap(record => record.points)).slice(0, 3);
        if (chat.length) study.push(chatPoints.length ? '对话中涉及' + quoted(chatPoints) + '。' : '对话中保留了可回看的题目。');
        const latestWrong = [...snapshot.wrong].sort((a, b) => b.at - a.at)[0];
        if (latestWrong) study.push('错题本中保留了' + questionLabel(latestWrong) + '。');
        const note = snapshot.notes[0];
        if (note) study.push('笔记“' + noteName(note) + '”' + (text(note.content) ? '记录了“' + preview(note.content) + '”。' : '目前只有标题。'));
        if (snapshot.drawings.length) study.push(describeDrawing(snapshot.drawings[0]));

        const target = snapshot.target;
        if (!target) return [['最近学习', study.join('') || '无'], ['值得再看看', '无'], ['接下来可以做', '无']];
        const advice = targetAdvice(target);
        let revisit = '', next = '';
        if (target.type === 'wrong') {
            const label = questionLabel(target, '错题'), status = target.status;
            if (status.failed) revisit = label + '最近一次复测未通过' + (status.manual ? '，历史中另有手动标记通过的记录' : '') + '。';
            else if (status.uncertain) revisit = label + (status.manual ? '有手动标记通过的记录；最近一次复测结果暂不能确定，可回看作答与标记核对。' : '的最近复测结果暂不能确定，可回看作答和反馈。');
            else if (status.state === 'pending') revisit = label + '尚未标记订正。';
            else if (status.state === 'retest') revisit = label + '已订正，尚无通过复测的记录。';
            else revisit = label + (status.manual ? '有手动标记通过的记录。' : '已有通过复测的记录。') + '可以换一个条件再检查能否独立完成。';
            if (status.uncertain) next = '先打开这条错题的复测记录，核对实际作答与通过标记。';
            else if (status.state === 'pending') next = '先不看答案，重做这条题。';
            else if (status.state === 'retest') next = '从这条已订正的题发起一次复测，先独立作答。';
            else next = '下次学习时做一道同主题的小变式，先独立作答。';
            next += advice.action + advice.check;
            if (status.state === 'pending' && !status.uncertain) next += '将改正的一步写进“我的笔记”，核对后再标记订正。';
            if (status.failed) next += '若仍无法起步，先看同类例题的一步，再合上重做。';
        } else if (target.type === 'note') {
            revisit = '笔记“' + noteName(target) + '”' + (text(target.content)
                ? '可以用来检查：不看原文时，能否解释定义并说明例子为何成立。' : '目前只有标题，可以先补上一句定义和一个例子。');
            next = (text(target.content) ? '先遮住笔记原文，' : '先在这条笔记中写下自己的理解。')
                + advice.action + advice.check + '再对照资料修正遗漏的条件。';
        } else if (target.type === 'drawing') {
            revisit = '绘图“' + preview(target.name) + '”可以用来检查图形、文字与数学定义能否对应起来。';
            next = advice.action + advice.check;
        } else {
            const label = target.type === 'question' ? questionLabel(target) : '对话中提到的' + quoted(target.points.slice(0, 1));
            revisit = label + '可以通过独立举例或重做，检查定义和条件是否用对。';
            next = advice.action + advice.check;
        }
        const relatedNote = snapshot.notes.find(item => item !== target && item.points.some(point => target.points.includes(point)));
        if (relatedNote && target.type !== 'note') next += '可对照笔记“' + noteName(relatedNote) + '”核对。';
        return [['最近学习', study.join('') || '无'], ['值得再看看', revisit || '无'], ['接下来可以做', next || '无']];
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
