(function (root) {
    'use strict';
    const LIMITS = { graphs: 64, vertices: 100, edges: 300, body: 23000 };
    const copy = value => JSON.parse(JSON.stringify(value));
    const scalar = value => typeof value === 'string' || (typeof value === 'number' && Number.isFinite(value));
    const id = value => scalar(value) ? String(value) : '';
    const text = value => scalar(value) ? String(value) : '';
    const unique = (prefix, records) => {
        const used = new Set(records.map(row => row.id));
        let next = 1;
        while (used.has(prefix + next)) next++;
        return prefix + next;
    };
    const ATTRS = ['weight', 'edge_label', 'color', 'style'];

    function importDocument(input) {
        const source = input && typeof input === 'object' ? input : {};
        const result = { body_text: text(source.body_text), graphs: [] };
        for (const raw of Array.isArray(source.graphs) ? source.graphs : []) {
            if (!raw || typeof raw !== 'object') continue;
            const graph = { id: id(raw.id) || unique('G', result.graphs), name: text(raw.name), vertices: [], edges: [] };
            if (result.graphs.some(row => row.id === graph.id)) graph.id = unique('G', result.graphs);
            const inputVertices = Array.isArray(raw.vertices) ? raw.vertices.filter(row => row && typeof row === 'object') : [];
            const oldCounts = new Map();
            inputVertices.forEach(row => oldCounts.set(id(row.id), (oldCounts.get(id(row.id)) || 0) + 1));
            const aliases = new Map();
            for (const rawVertex of inputVertices) {
                let vertexId = id(rawVertex.id) || unique('v', graph.vertices);
                if (graph.vertices.some(row => row.id === vertexId)) vertexId = unique('v', graph.vertices);
                graph.vertices.push({ id: vertexId, label: scalar(rawVertex.label) && text(rawVertex.label).trim() ? text(rawVertex.label) : null });
                if (id(rawVertex.id) && oldCounts.get(id(rawVertex.id)) === 1) aliases.set(id(rawVertex.id), vertexId);
            }
            for (const rawEdge of Array.isArray(raw.edges) ? raw.edges : []) {
                if (!rawEdge || typeof rawEdge !== 'object') continue;
                let edgeId = id(rawEdge.id) || unique('e', graph.edges);
                if (graph.edges.some(row => row.id === edgeId)) edgeId = unique('e', graph.edges);
                const endpoint = value => aliases.get(id(value)) || (oldCounts.has(id(value)) ? '' : id(value));
                const edge = { id: edgeId, from: endpoint(rawEdge.from), to: endpoint(rawEdge.to),
                    direction: ['forward', 'undirected', 'unknown'].includes(rawEdge.direction) ? rawEdge.direction
                        : raw.directed === true ? 'forward' : raw.directed === false ? 'undirected' : 'unknown' };
                for (const field of ATTRS) if (rawEdge[field] === null || scalar(rawEdge[field])) edge[field] = rawEdge[field];
                if (rawEdge.weight !== undefined && rawEdge.weight !== null && !scalar(rawEdge.weight)) edge.weight = 'unknown';
                graph.edges.push(edge);
            }
            result.graphs.push(graph);
        }
        if (source.text_context && typeof source.text_context === 'object') {
            const context = {};
            for (const field of ['legends', 'captions']) {
                context[field] = (Array.isArray(source.text_context[field]) ? source.text_context[field] : [])
                    .filter(row => row && typeof row.text === 'string')
                    .map(row => ({ text: row.text, graph_ids: Array.isArray(row.graph_ids) ? row.graph_ids.map(id) : [] }));
            }
            if (context.legends.length || context.captions.length) result.text_context = context;
        }
        return result;
    }

    function validateDocument(document) {
        const issues = [];
        if (!document || typeof document.body_text !== 'string' || !Array.isArray(document.graphs)) return ['题目结构无法读取。'];
        if (document.body_text.length > LIMITS.body) issues.push('题干过长，请精简至 23000 字以内。');
        if (!document.body_text.trim() && !document.graphs.length) issues.push('请至少填写题干或添加一幅图。');
        if (document.graphs.length > LIMITS.graphs) issues.push('子图数量超过 64 幅。');
        const graphIds = new Set();
        for (const [number, graph] of document.graphs.entries()) {
            const name = graph.name || '图 ' + (number + 1);
            if (!graph.id || graphIds.has(graph.id)) issues.push(name + '的编号重复或为空。');
            graphIds.add(graph.id);
            if (!graph.vertices.length) issues.push(name + '没有节点；请添加节点或删除这幅空图。');
            if (graph.vertices.length > LIMITS.vertices || graph.edges.length > LIMITS.edges) issues.push(name + '超出编辑范围（100 个节点、300 条边）。');
            const vertices = new Set(), edges = new Set();
            for (const vertex of graph.vertices) {
                if (!vertex.id || vertices.has(vertex.id)) issues.push(name + '有重复或缺失的节点编号。');
                vertices.add(vertex.id);
                if (vertex.label !== null && typeof vertex.label !== 'string') issues.push(name + '有无效节点标签。');
                if (text(vertex.label).length > 128) issues.push(name + '的节点标签超过 128 字。');
            }
            graph.edges.forEach((edge, index) => {
                const label = name + '第 ' + (index + 1) + ' 条边';
                if (!edge.id || edges.has(edge.id)) issues.push(label + '编号重复或为空。');
                edges.add(edge.id);
                if (!vertices.has(edge.from) || !vertices.has(edge.to)) issues.push(label + '需要选择有效的两个端点。');
                if (!['forward', 'undirected'].includes(edge.direction)) issues.push(label + '的方向尚未确认。');
                if (edge.weight !== undefined && edge.weight !== null && (!scalar(edge.weight) || /^(unknown|未知|不确定)$/i.test(text(edge.weight).trim()))) issues.push(label + '的权重尚未确认；无权重请留空。');
                for (const field of ATTRS) if (text(edge[field]).length > 128) issues.push(label + '的属性文字过长。');
            });
        }
        if (document.text_context) for (const field of ['legends', 'captions']) {
            for (const row of document.text_context[field] || []) {
                if (row.text.length > 2000) issues.push('图例或说明超过 2000 字。');
                if (row.graph_ids.some(gid => !graphIds.has(gid))) issues.push('图例或说明关联了不存在的子图，请重新选择归属。');
            }
        }
        return [...new Set(issues)];
    }

    function groupEdges(graph, individually) {
        const groups = new Map();
        for (const edge of graph.edges) {
            const endpoints = edge.direction === 'undirected' ? [edge.from, edge.to].sort() : [edge.from, edge.to];
            const key = individually ? edge.id : JSON.stringify([endpoints, edge.direction, ...ATTRS.map(field => edge[field] ?? null)]);
            if (!groups.has(key)) groups.set(key, []);
            groups.get(key).push(edge);
        }
        return [...groups.values()];
    }

    function createModel(input, initialDocument) {
        let state = importDocument(input);
        const initial = importDocument(initialDocument || input), history = [];
        const listeners = new Set();
        const getGraph = (draft, gid) => {
            const graph = draft.graphs.find(row => row.id === gid);
            if (!graph) throw new Error('找不到这幅子图。');
            return graph;
        };
        const publish = () => listeners.forEach(listener => listener(copy(state)));
        function change(operation) {
            const next = copy(state);
            operation(next);
            if (JSON.stringify(next) === JSON.stringify(state)) return;
            history.push(state);
            if (history.length > 40) history.shift();
            state = next;
            publish();
        }
        function remapContext(draft, before, after) {
            if (!draft.text_context) return;
            for (const rows of Object.values(draft.text_context)) for (const row of rows) {
                row.graph_ids = [...new Set(row.graph_ids.flatMap(gid => gid === before ? (after ? [after] : []) : [gid]))];
            }
        }
        const api = {
            getDocument: () => copy(state),
            validate: () => validateDocument(state),
            canUndo: () => history.length > 0,
            subscribe: listener => { listeners.add(listener); return () => listeners.delete(listener); },
            undo: () => { if (history.length) { state = history.pop(); publish(); } },
            reset: () => change(draft => { Object.keys(draft).forEach(key => delete draft[key]); Object.assign(draft, copy(initial)); }),
            setBody: value => change(draft => { draft.body_text = String(value); }),
            renameGraph: (gid, name) => change(draft => { getGraph(draft, gid).name = String(name); }),
            addGraph: () => {
                let gid;
                change(draft => { if (draft.graphs.length >= LIMITS.graphs) throw new Error('最多编辑 64 幅子图。');
                    gid = unique('G', draft.graphs); draft.graphs.push({ id: gid, name: '图 ' + (draft.graphs.length + 1), vertices: [], edges: [] }); });
                return gid;
            },
            deleteGraph: gid => change(draft => { getGraph(draft, gid); draft.graphs = draft.graphs.filter(row => row.id !== gid); }),
            addVertex: (gid, label) => {
                let vertexId;
                change(draft => { const graph = getGraph(draft, gid); if (graph.vertices.length >= LIMITS.vertices) throw new Error('每幅图最多 100 个节点。');
                    vertexId = unique('v', graph.vertices); graph.vertices.push({ id: vertexId, label: String(label || '').trim() || null }); });
                return vertexId;
            },
            renameVertex: (gid, vid, label) => change(draft => { const vertex = getGraph(draft, gid).vertices.find(row => row.id === vid);
                if (!vertex) throw new Error('找不到这个节点。'); vertex.label = String(label).trim() || null; }),
            deleteVertices: (gid, ids) => change(draft => { const graph = getGraph(draft, gid), selected = new Set(ids);
                graph.vertices = graph.vertices.filter(row => !selected.has(row.id));
                graph.edges = graph.edges.filter(row => !selected.has(row.from) && !selected.has(row.to)); }),
            addEdge: (gid, values) => {
                let edgeId;
                change(draft => { const graph = getGraph(draft, gid); if (graph.edges.length >= LIMITS.edges) throw new Error('每幅图最多 300 条边。');
                    edgeId = unique('e', graph.edges); graph.edges.push({ id: edgeId, from: values.from || '', to: values.to || '', direction: values.direction || 'undirected', weight: values.weight ?? null }); });
                return edgeId;
            },
            updateEdges: (gid, ids, field, value) => change(draft => {
                if (!['from', 'to', 'direction', ...ATTRS].includes(field)) throw new Error('无法修改这个字段。');
                const graph = getGraph(draft, gid), selected = new Set(ids);
                graph.edges.forEach(edge => { if (selected.has(edge.id)) edge[field] = value; });
            }),
            reverseEdges: (gid, ids) => change(draft => { const graph = getGraph(draft, gid);
                graph.edges.forEach(edge => { if (ids.includes(edge.id)) [edge.from, edge.to] = [edge.to, edge.from]; }); }),
            setEdgeCount: (gid, ids, count) => change(draft => {
                if (!Number.isInteger(count) || count < 1 || count > 50) throw new Error('相同边数量须为 1 到 50。');
                const graph = getGraph(draft, gid), selected = graph.edges.filter(row => ids.includes(row.id));
                if (!selected.length) throw new Error('找不到这条边。');
                if (graph.edges.length - selected.length + count > LIMITS.edges) throw new Error('每幅图最多 300 条边。');
                const removed = new Set(selected.slice(count).map(row => row.id));
                graph.edges = graph.edges.filter(row => !removed.has(row.id));
                for (let number = selected.length; number < count; number++) graph.edges.push({ ...copy(selected[0]), id: unique('e', graph.edges) });
            }),
            deleteEdges: (gid, ids) => change(draft => { const graph = getGraph(draft, gid); graph.edges = graph.edges.filter(row => !ids.includes(row.id)); }),
            moveVertices: (fromId, toId, ids) => change(draft => {
                if (fromId === toId) return;
                const from = getGraph(draft, fromId), to = getGraph(draft, toId), selected = new Set(ids);
                if (!selected.size) throw new Error('请先勾选要移动的节点。');
                if (from.edges.some(edge => selected.has(edge.from) !== selected.has(edge.to))) throw new Error('这些节点还有连接本图其他节点的边。请一并勾选相连节点，或先修改这些边。');
                const moving = from.vertices.filter(row => selected.has(row.id));
                if (to.vertices.length + moving.length > LIMITS.vertices) throw new Error('目标子图的节点数量超过 100。');
                const movingEdges = from.edges.filter(edge => selected.has(edge.from) && selected.has(edge.to));
                if (to.edges.length + movingEdges.length > LIMITS.edges) throw new Error('目标子图的边数量超过 300。');
                const mapping = new Map();
                for (const vertex of moving) { const vid = to.vertices.some(row => row.id === vertex.id) ? unique('v', to.vertices) : vertex.id;
                    mapping.set(vertex.id, vid); to.vertices.push({ ...vertex, id: vid }); }
                for (const edge of movingEdges) to.edges.push({ ...edge, id: to.edges.some(row => row.id === edge.id) ? unique('e', to.edges) : edge.id,
                    from: mapping.get(edge.from), to: mapping.get(edge.to) });
                from.vertices = from.vertices.filter(row => !selected.has(row.id));
                from.edges = from.edges.filter(edge => !selected.has(edge.from));
            }),
            moveEdges: (fromId, toId, ids, fromVertex, toVertex) => change(draft => {
                if (fromId === toId) throw new Error('请选择另一幅目标子图。');
                const from = getGraph(draft, fromId), to = getGraph(draft, toId);
                const valid = new Set(to.vertices.map(row => row.id));
                if (!valid.has(fromVertex) || !valid.has(toVertex)) throw new Error('请在目标子图中选择这条边的两个端点。');
                const moving = from.edges.filter(row => ids.includes(row.id));
                if (to.edges.length + moving.length > LIMITS.edges) throw new Error('目标子图的边数量超过 300。');
                for (const edge of moving) to.edges.push({ ...edge, id: to.edges.some(row => row.id === edge.id) ? unique('e', to.edges) : edge.id,
                    from: fromVertex, to: toVertex });
                from.edges = from.edges.filter(row => !ids.includes(row.id));
            }),
            mergeGraph: (fromId, toId) => {
                const from = state.graphs.find(row => row.id === fromId);
                if (!from || fromId === toId) throw new Error('请选择另一幅目标子图。');
                change(draft => {
                    const source = getGraph(draft, fromId), target = getGraph(draft, toId);
                    if (source.vertices.length + target.vertices.length > LIMITS.vertices || source.edges.length + target.edges.length > LIMITS.edges) throw new Error('合并后的图超过 100 个节点或 300 条边。');
                    const mapping = new Map();
                    for (const vertex of source.vertices) { const vid = target.vertices.some(row => row.id === vertex.id) ? unique('v', target.vertices) : vertex.id;
                        mapping.set(vertex.id, vid); target.vertices.push({ ...vertex, id: vid }); }
                    for (const edge of source.edges) target.edges.push({ ...edge, id: target.edges.some(row => row.id === edge.id) ? unique('e', target.edges) : edge.id,
                        from: mapping.get(edge.from) || '', to: mapping.get(edge.to) || '' });
                    draft.graphs = draft.graphs.filter(row => row.id !== fromId); remapContext(draft, fromId, toId);
                });
            },
            setContext: (kind, index, value) => change(draft => {
                if (!['legends', 'captions'].includes(kind)) throw new Error('说明类型无效。');
                draft.text_context ||= { legends: [], captions: [] };
                draft.text_context[kind] ||= [];
                if (value !== null && index >= 32) throw new Error('每种图例或说明最多添加 32 条。');
                if (value === null) draft.text_context[kind].splice(index, 1);
                else draft.text_context[kind][index] = { text: String(value.text), graph_ids: [...value.graph_ids] };
            })
        };
        return api;
    }

    let mountSequence = 0;
    function mount(container, options) {
        if (!container || !container.ownerDocument) throw new Error('编辑器需要有效的页面容器。');
        options ||= {};
        const dom = container.ownerDocument, model = createModel(options.document, options.initialDocument);
        const instance = 'dmate-editor-' + (++mountSequence), svgNS = 'http://www.w3.org/2000/svg';
        let currentGraph = model.getDocument().graphs[0]?.id, selectedNodes = new Set(), selectedEdge = null;
        let individually = false, saving = false, destroyed = false, acknowledged = false, notice = '', pendingDelete = '';
        let unsubscribe;
        const element = (tag, className, label) => { const node = dom.createElement(tag); if (className) node.className = className;
            if (label !== undefined) node.textContent = label; return node; };
        const svgElement = (tag, attributes, label) => { const node = dom.createElementNS(svgNS, tag);
            Object.entries(attributes || {}).forEach(([key, value]) => node.setAttribute(key, String(value)));
            if (label !== undefined) node.textContent = label; return node; };
        const button = (label, action, className) => { const node = element('button', className || '', label); node.type = 'button'; node.disabled = saving;
            node.addEventListener('click', () => act(action)); return node; };
        const input = (value, aria, action, type) => { const node = element('input'); node.type = type || 'text'; node.value = value ?? ''; node.setAttribute('aria-label', aria); node.disabled = saving;
            if (action) node.addEventListener('input', () => edit(() => action(node.value))); return node; };
        const select = (rows, value, aria, action) => { const node = element('select'); node.setAttribute('aria-label', aria); node.disabled = saving;
            rows.forEach(([key, label]) => { const option = element('option', '', label); option.value = key; node.append(option); }); node.value = value ?? '';
            if (rows.graphId) node.dataset.graphNodes = rows.graphId;
            if (action) node.addEventListener('change', () => edit(() => action(node.value))); return node; };
        const field = (label, control) => { const wrapper = element('label', 'dge-field'); wrapper.append(element('span', '', label), control); return wrapper; };
        function act(action) { if (saving || destroyed) return; notice = '';
            try { action(); } catch (error) { notice = error?.message || '无法完成这项修改。'; }
            render(); }
        function edit(action) { if (saving || destroyed) return; notice = '';
            try { action(); } catch (error) { notice = error?.message || '无法完成这项修改。'; }
            refreshDraftViews(); }
        function askDelete(key, message, action) {
            if (pendingDelete === key) { pendingDelete = ''; action(); }
            else { pendingDelete = key; notice = message + ' 再次点击删除可确认，也可用“撤销”恢复。'; }
        }
        const nodeOptions = graph => { const rows = [['', '请选择节点'], ...graph.vertices.map((vertex, index) => [vertex.id, vertex.label === null ? '未命名节点 ' + (index + 1) : vertex.label])]; rows.graphId = graph.id; return rows; };
        const graphOptions = (document, excluded) => [['', '选择目标子图'], ...document.graphs.filter(graph => graph.id !== excluded).map((graph, index) => [graph.id, graph.name || '图 ' + (index + 1)])];
        const weightValue = value => value.trim() === '' ? null : /^[-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?$/i.test(value.trim()) && Number.isFinite(Number(value)) ? Number(value) : value;

        function refreshDraftViews() {
            if (destroyed) return;
            const document = model.getDocument(), graph = document.graphs.find(row => row.id === currentGraph);
            const visual = container.querySelector('.dge-visual');
            if (visual && graph) { visual.querySelector('svg')?.remove(); visual.append(drawGraph(graph)); }
            const status = container.querySelector('.dge-status'); if (status) status.textContent = notice;
            const ack = container.querySelector('.dge-footer input[type=checkbox]'); if (ack) ack.checked = acknowledged;
            const undo = container.querySelector('[data-editor-undo]'); if (undo) undo.disabled = saving || !model.canUndo();
            for (const selector of container.querySelectorAll('select[data-graph-nodes]')) {
                const owner = document.graphs.find(row => row.id === selector.dataset.graphNodes);
                if (!owner) continue;
                const labels = new Map(nodeOptions(owner));
                for (const option of selector.options) if (labels.has(option.value)) option.textContent = labels.get(option.value);
            }
            const graphSelect = container.querySelector('select[aria-label="当前子图"]');
            if (graphSelect) for (const option of graphSelect.options) { const owner = document.graphs.find(row => row.id === option.value); if (owner) option.textContent = owner.name || owner.id; }
            if (graph) {
                const edgeHeading = container.querySelector('.dge-edge-panel > h3'); if (edgeHeading) edgeHeading.textContent = '边 · ' + graph.edges.length;
                for (const count of container.querySelectorAll('[data-node-incident]')) {
                    const amount = graph.edges.filter(edge => edge.from === count.dataset.nodeIncident || edge.to === count.dataset.nodeIncident).length;
                    count.textContent = amount ? amount + ' 条关联边' : '孤立点';
                }
            }
            renderValidation();
        }

        function renderValidation() {
            container.querySelector('.dge-validation')?.remove();
            const issues = model.validate(); if (!issues.length) return;
            const details = element('details', 'dge-validation'); details.open = true; details.append(element('summary', '', '确认前还需处理 ' + issues.length + ' 项'));
            const list = element('ul'); issues.forEach(message => list.append(element('li', '', message))); details.append(list);
            const footer = container.querySelector('.dge-footer'); footer ? container.insertBefore(details, footer) : container.append(details);
        }

        function drawGraph(graph) {
            const svg = svgElement('svg', { viewBox: '0 0 620 390', role: 'group', 'aria-label': (graph.name || '当前图') + '结构预览' });
            const markerId = instance + '-arrow', defs = svgElement('defs');
            const marker = svgElement('marker', { id: markerId, viewBox: '0 0 10 10', refX: 8, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' });
            marker.append(svgElement('path', { d: 'M 0 0 L 10 5 L 0 10 z', fill: 'context-stroke' })); defs.append(marker); svg.append(defs);
            const points = new Map();
            graph.vertices.forEach((vertex, index) => {
                const angle = -Math.PI / 2 + 2 * Math.PI * index / Math.max(1, graph.vertices.length);
                points.set(vertex.id, graph.vertices.length === 1 ? [310, 195] : [310 + 225 * Math.cos(angle), 200 + 105 * Math.sin(angle)]);
            });
            const pairs = new Map();
            graph.edges.forEach(edge => { const key = JSON.stringify([edge.from, edge.to].sort()); if (!pairs.has(key)) pairs.set(key, []); pairs.get(key).push(edge); });
            for (const edges of pairs.values()) edges.forEach((edge, index) => {
                const a = points.get(edge.from), b = points.get(edge.to); if (!a || !b) return;
                let path, tx, ty;
                if (edge.from === edge.to) { const spread = 32 + index * 18;
                    path = `M ${a[0] - 13} ${a[1] - 12} C ${a[0] - spread - 34} ${a[1] - spread - 50}, ${a[0] + spread + 34} ${a[1] - spread - 50}, ${a[0] + 13} ${a[1] - 12}`;
                    tx = a[0]; ty = a[1] - spread - 31;
                } else {
                    const dx = b[0] - a[0], dy = b[1] - a[1], length = Math.hypot(dx, dy) || 1;
                    const sign = edge.from < edge.to ? 1 : -1, offset = (index - (edges.length - 1) / 2) * 34 * sign;
                    const cx = (a[0] + b[0]) / 2 - dy / length * offset, cy = (a[1] + b[1]) / 2 + dx / length * offset;
                    const startLength = Math.hypot(cx - a[0], cy - a[1]) || 1, endLength = Math.hypot(b[0] - cx, b[1] - cy) || 1;
                    path = `M ${a[0] + (cx - a[0]) / startLength * 19} ${a[1] + (cy - a[1]) / startLength * 19} Q ${cx} ${cy}, ${b[0] - (b[0] - cx) / endLength * 21} ${b[1] - (b[1] - cy) / endLength * 21}`;
                    tx = (a[0] + b[0]) / 4 + cx / 2; ty = (a[1] + b[1]) / 4 + cy / 2 - 7;
                }
                const group = svgElement('g', { class: 'dge-visual-edge' + (selectedEdge === edge.id ? ' is-selected' : ''), tabindex: 0, role: 'button', 'aria-label': '选择边 ' + (edge.edge_label || (index + 1)) });
                const attrs = { d: path, fill: 'none', class: 'dge-edge-stroke' };
                if (edge.direction === 'forward') attrs['marker-end'] = 'url(#' + markerId + ')';
                if (edge.style === 'dashed') attrs['stroke-dasharray'] = '9 6';
                if (edge.style === 'dotted') attrs['stroke-dasharray'] = '2 5';
                const stroke = svgElement('path', attrs);
                const colors = { red: '#dc2626', blue: '#2563eb', green: '#15803d', purple: '#9333ea', orange: '#d97706', gray: '#64748b' };
                if (colors[edge.color]) stroke.style.stroke = colors[edge.color];
                group.append(svgElement('path', { d: path, class: 'dge-edge-hit', fill: 'none' }), stroke);
                const label = [edge.edge_label, edge.weight === null || edge.weight === undefined ? '' : text(edge.weight)].filter(value => value !== null && value !== '').join(' · ');
                if (label) { group.append(svgElement('title', {}, label)); group.append(svgElement('text', { x: tx, y: ty, class: 'dge-edge-label', 'text-anchor': 'middle' }, label.length > 24 ? label.slice(0, 23) + '…' : label)); }
                const choose = () => { selectedEdge = edge.id; render(); };
                group.addEventListener('click', choose); group.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(); } }); svg.append(group);
            });
            graph.vertices.forEach((vertex, index) => {
                const [x, y] = points.get(vertex.id), label = vertex.label ?? '未命名 ' + (index + 1);
                const group = svgElement('g', { class: 'dge-visual-node' + (selectedNodes.has(vertex.id) ? ' is-selected' : ''), tabindex: 0, role: 'button', 'aria-label': '选择节点 ' + label });
                group.append(svgElement('title', {}, label), svgElement('circle', { cx: x, cy: y, r: 18 }),
                    svgElement('text', { x, y: y + 5, 'text-anchor': 'middle' }, label.length > 12 ? label.slice(0, 11) + '…' : label));
                const choose = () => { selectedNodes.has(vertex.id) ? selectedNodes.delete(vertex.id) : selectedNodes.add(vertex.id); render(); };
                group.addEventListener('click', choose); group.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(); } }); svg.append(group);
            });
            return svg;
        }

        function renderContext(document, parent) {
            const details = element('details', 'dge-context');
            details.append(element('summary', '', '图例与说明'));
            for (const [kind, label] of [['legends', '图例'], ['captions', '说明']]) {
                (document.text_context?.[kind] || []).forEach((row, index) => {
                    const box = element('div', 'dge-context-row');
                    const area = element('textarea'); area.value = row.text; area.rows = 2; area.setAttribute('aria-label', label + ' ' + (index + 1)); area.disabled = saving;
                    area.addEventListener('input', () => edit(() => model.setContext(kind, index, { ...model.getDocument().text_context[kind][index], text: area.value })));
                    box.append(area);
                    const associations = element('div', 'dge-context-associations');
                    associations.append(element('span', 'dge-muted', '适用子图（未选表示整题）'));
                    document.graphs.forEach(graph => {
                        const choice = element('label'), check = element('input'); check.type = 'checkbox'; check.checked = row.graph_ids.includes(graph.id); check.disabled = saving;
                        check.addEventListener('change', () => act(() => { const current = model.getDocument().text_context[kind][index];
                            model.setContext(kind, index, { ...current, graph_ids: check.checked ? [...current.graph_ids, graph.id] : current.graph_ids.filter(gid => gid !== graph.id) }); }));
                        choice.append(check, dom.createTextNode(graph.name || graph.id)); associations.append(choice);
                    });
                    box.append(associations, button('适用整题', () => model.setContext(kind, index, { ...model.getDocument().text_context[kind][index], graph_ids: [] })),
                        button('删除' + label, () => model.setContext(kind, index, null), 'dge-danger')); details.append(box);
                });
                details.append(button('添加' + label, () => model.setContext(kind, document.text_context?.[kind]?.length || 0, { text: '', graph_ids: [] })));
            }
            parent.append(details);
        }

        function render() {
            if (destroyed) return;
            const document = model.getDocument();
            let graph = document.graphs.find(row => row.id === currentGraph) || document.graphs[0]; currentGraph = graph?.id;
            selectedNodes = new Set([...selectedNodes].filter(vid => graph?.vertices.some(row => row.id === vid)));
            if (!graph?.edges.some(edge => edge.id === selectedEdge)) selectedEdge = null;
            container.replaceChildren(); container.classList.add('dmate-graph-editor');
            const top = element('div', 'dge-topline');
            top.append(element('p', 'dge-muted', '先对照原图核对题干，再点击图中的节点或边进行修改。图的位置仅用于查看结构。'));
            const undo = button('撤销', () => { pendingDelete = ''; model.undo(); }); undo.dataset.editorUndo = 'true'; undo.disabled = saving || !model.canUndo();
            top.append(undo, button('恢复识别初稿', () => askDelete('reset', '将撤销本张图片的全部修改。', () => model.reset()))); container.append(top);
            const observations = (Array.isArray(options.issues) ? options.issues : [])
                .map(issue => typeof issue === 'string' ? issue : text(issue?.message)).filter(Boolean);
            if (observations.length) { const details = element('details', 'dge-observations'); details.open = true;
                details.append(element('summary', '', '识别时需留意'));
                const list = element('ul'); observations.slice(0, 64).forEach(message => list.append(element('li', '', message))); details.append(list); container.append(details); }
            const workspace = element('div', 'dge-workspace'), preview = element('section', 'dge-original');
            preview.append(element('h3', '', '原图'));
            if (typeof options.originalUrl === 'string' && /^(blob:|data:image\/(?:png|jpeg|webp|gif|avif|bmp);|https?:\/\/)/i.test(options.originalUrl)) {
                const image = element('img'); image.src = options.originalUrl; image.alt = '上传的原图，用于核对识别结果'; preview.append(image);
            } else preview.append(element('p', 'dge-muted', '原图预览暂不可用，可继续编辑结构。'));
            const visual = element('section', 'dge-visual'); visual.append(element('h3', '', '结构预览'));
            if (graph) visual.append(drawGraph(graph)); else visual.append(element('p', 'dge-empty', '当前没有子图，可添加图形，或只确认题干。'));
            workspace.append(preview, visual); container.append(workspace);
            const body = element('textarea', 'dge-body'); body.value = document.body_text; body.rows = 4; body.setAttribute('aria-label', '题干、全部小问与公式'); body.disabled = saving;
            body.addEventListener('input', () => edit(() => model.setBody(body.value)));
            container.append(field('题干、全部小问与公式', body)); renderContext(document, container);
            const toolbar = element('div', 'dge-toolbar');
            if (document.graphs.length) toolbar.append(field('当前子图', select(document.graphs.map((row, index) => [row.id, row.name || '图 ' + (index + 1)]), currentGraph, '当前子图', value => { currentGraph = value; selectedNodes.clear(); selectedEdge = null; pendingDelete = ''; render(); })));
            toolbar.append(button('添加子图', () => { currentGraph = model.addGraph(); selectedNodes.clear(); selectedEdge = null; }));
            if (graph) {
                toolbar.append(field('子图名称', input(graph.name, '子图名称', value => model.renameGraph(graph.id, value))));
                toolbar.append(button('删除子图', () => askDelete('graph:' + graph.id, '将删除这幅图的 ' + graph.vertices.length + ' 个节点和 ' + graph.edges.length + ' 条边。', () => model.deleteGraph(graph.id)), 'dge-danger'));
                if (document.graphs.length > 1) { const target = select(graphOptions(document, graph.id), '', '合并目标子图', null);
                    toolbar.append(field('合并子图', target), button('合并到所选图', () => { if (!target.value) throw new Error('请先选择合并目标。'); const targetId = target.value; model.mergeGraph(graph.id, targetId); currentGraph = targetId; })); }
            }
            container.append(toolbar);
            if (graph) {
                const panels = element('div', 'dge-edit-panels'), nodes = element('section', 'dge-node-panel'), edges = element('section', 'dge-edge-panel');
                nodes.append(element('h3', '', '节点 · ' + graph.vertices.length));
                const nodeList = element('div', 'dge-node-list');
                graph.vertices.forEach((vertex, index) => {
                    const row = element('div', 'dge-node-row' + (selectedNodes.has(vertex.id) ? ' is-selected' : ''));
                    const check = element('input'); check.type = 'checkbox'; check.checked = selectedNodes.has(vertex.id); check.disabled = saving;
                    check.setAttribute('aria-label', '选中节点 ' + (vertex.label ?? (index + 1)));
                    check.addEventListener('change', () => act(() => { check.checked ? selectedNodes.add(vertex.id) : selectedNodes.delete(vertex.id); }));
                    const label = input(vertex.label, '节点 ' + (index + 1) + ' 标签', value => model.renameVertex(graph.id, vertex.id, value)); label.placeholder = '未命名节点';
                    const incident = graph.edges.filter(edge => edge.from === vertex.id || edge.to === vertex.id).length;
                    const kind = element('span', 'dge-node-kind', incident ? incident + ' 条关联边' : '孤立点'); kind.dataset.nodeIncident = vertex.id;
                    row.append(check, label, kind); nodeList.append(row);
                });
                nodes.append(nodeList);
                const addLabel = input('', '新节点标签', null); addLabel.placeholder = '新节点标签（可留空）';
                const addRow = element('div', 'dge-inline'); addRow.append(addLabel, button('添加节点', () => model.addVertex(graph.id, addLabel.value))); nodes.append(addRow);
                nodes.append(button('全选节点', () => { selectedNodes = new Set(graph.vertices.map(vertex => vertex.id)); }), button('删除所选节点', () => {
                    if (!selectedNodes.size) throw new Error('请先勾选节点。');
                    const ids = [...selectedNodes], count = graph.edges.filter(edge => selectedNodes.has(edge.from) || selectedNodes.has(edge.to)).length;
                    askDelete('vertices:' + ids.join('|'), '将删除 ' + ids.length + ' 个节点及 ' + count + ' 条关联边。', () => { model.deleteVertices(graph.id, ids); selectedNodes.clear(); });
                }, 'dge-danger'));
                if (document.graphs.length > 1) { const target = select(graphOptions(document, graph.id), '', '节点移动目标', null);
                    nodes.append(field('节点归属', target), button('移动所选节点', () => { if (!target.value) throw new Error('请先选择目标子图。'); model.moveVertices(graph.id, target.value, [...selectedNodes]); selectedNodes.clear(); })); }
                edges.append(element('h3', '', '边 · ' + graph.edges.length));
                const separateLabel = element('label', 'dge-check'), separate = element('input'); separate.type = 'checkbox'; separate.checked = individually; separate.disabled = saving;
                separate.addEventListener('change', () => act(() => { individually = separate.checked; })); separateLabel.append(separate, dom.createTextNode('逐条编辑重边')); edges.append(separateLabel);
                const edgeList = element('div', 'dge-edge-list');
                groupEdges(graph, individually).forEach((group, index) => {
                    const edge = group[0], ids = group.map(row => row.id), row = element('div', 'dge-edge-row' + (ids.includes(selectedEdge) ? ' is-selected' : ''));
                    row.dataset.edgeId = edge.id;
                    row.append(button('边 ' + (index + 1), () => { selectedEdge = edge.id; }, 'dge-edge-select'));
                    row.append(field('起点', select(nodeOptions(graph), edge.from, '边 ' + (index + 1) + ' 起点', value => model.updateEdges(graph.id, ids, 'from', value))),
                        field('方向', select([['undirected', '无向 —'], ['forward', '有向 →'], ['unknown', '待确认 ?']], edge.direction, '边 ' + (index + 1) + ' 方向', value => model.updateEdges(graph.id, ids, 'direction', value))),
                        field('终点', select(nodeOptions(graph), edge.to, '边 ' + (index + 1) + ' 终点', value => model.updateEdges(graph.id, ids, 'to', value))),
                        field('权重', input(edge.weight, '边 ' + (index + 1) + ' 权重', value => model.updateEdges(graph.id, ids, 'weight', weightValue(value)))));
                    if (!individually) { const count = input(group.length, '边 ' + (index + 1) + ' 相同边数量', value => {
                            const beforeIds = new Set(model.getDocument().graphs.find(row => row.id === graph.id).edges.map(row => row.id));
                            model.setEdgeCount(graph.id, ids, Number(value));
                            const latest = model.getDocument().graphs.find(row => row.id === graph.id).edges;
                            ids.splice(0, ids.length, ...latest.filter(row => ids.includes(row.id) || !beforeIds.has(row.id)).map(row => row.id));
                        }, 'number'); count.min = '1'; count.max = '50'; count.required = true;
                        const quantity = field('相同边数量', count); quantity.append(button('应用数量', () => model.setEdgeCount(graph.id, ids, Number(count.value)))); row.append(quantity); }
                    row.append(button('交换端点 / 反向', () => model.reverseEdges(graph.id, ids)));
                    const attributes = element('details', 'dge-edge-attributes'); attributes.append(element('summary', '', '边名、线型与颜色'));
                    attributes.append(field('边名', input(edge.edge_label, '边 ' + (index + 1) + ' 边名', value => model.updateEdges(graph.id, ids, 'edge_label', value || null))),
                        field('线型', select([['', '未标特殊线型'], ['solid', '实线'], ['dashed', '虚线'], ['dotted', '点线'], ['unknown', '尚不确定']], edge.style ?? '', '边 ' + (index + 1) + ' 线型', value => model.updateEdges(graph.id, ids, 'style', value || null))),
                        field('颜色', input(edge.color, '边 ' + (index + 1) + ' 颜色', value => model.updateEdges(graph.id, ids, 'color', value || null))));
                    row.append(attributes, button('删除边', () => askDelete('edges:' + ids.join('|'), '将删除这组 ' + ids.length + ' 条边。', () => model.deleteEdges(graph.id, ids)), 'dge-danger')); edgeList.append(row);
                });
                edges.append(edgeList, button('添加边 / 自环', () => { const first = [...selectedNodes][0] || graph.vertices[0]?.id || '', second = [...selectedNodes][1] || graph.vertices[1]?.id || first;
                    selectedEdge = model.addEdge(graph.id, { from: first, to: second, direction: graph.edges.some(edge => edge.direction === 'forward') ? 'forward' : 'undirected' }); }));
                if (selectedEdge && document.graphs.length > 1) {
                    const move = element('details', 'dge-edge-move'); move.append(element('summary', '', '调整所选边的子图归属'));
                    const endpointFields = element('div', 'dge-inline'); let targetFrom, targetTo;
                    const target = select(graphOptions(document, graph.id), '', '边移动目标', null);
                    target.addEventListener('change', () => {
                        endpointFields.replaceChildren(); const destination = document.graphs.find(row => row.id === target.value); if (!destination) return;
                        targetFrom = select(nodeOptions(destination), '', '移动后起点', null); targetTo = select(nodeOptions(destination), '', '移动后终点', null);
                        endpointFields.append(field('目标图起点', targetFrom), field('目标图终点', targetTo));
                    });
                    move.append(target, endpointFields, button('移动这条边', () => model.moveEdges(graph.id, target.value, [selectedEdge], targetFrom?.value, targetTo?.value))); edges.append(move);
                }
                panels.append(nodes, edges); container.append(panels);
            }
            const status = element('div', 'dge-status'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite'); status.textContent = notice; container.append(status);
            renderValidation();
            const confirmRow = element('div', 'dge-footer'), ackLabel = element('label', 'dge-check'), ack = element('input'); ack.type = 'checkbox'; ack.checked = acknowledged; ack.disabled = saving;
            ack.addEventListener('change', () => { acknowledged = ack.checked; }); ackLabel.append(ack, dom.createTextNode('我已对照原图核对题干与各子图')); confirmRow.append(ackLabel);
            const actions = element('div', 'dge-actions'); actions.append(button('稍后继续', () => options.onCancel?.()));
            const confirm = button(saving ? '正在保存…' : '保存并确认', async () => {
                if ([...container.querySelectorAll('input[type=number]')].some(control => !control.checkValidity())) {
                    notice = '请填写有效的相同边数量（1 到 50）。'; refreshDraftViews(); return;
                }
                const problems = model.validate();
                if (problems.length) { notice = '请先处理上方标出的结构问题。'; render(); return; }
                if (!acknowledged) { notice = '请核对原图后勾选确认。'; render(); return; }
                if (typeof options.onConfirm !== 'function') { notice = '暂时无法保存，请稍后重试。'; render(); return; }
                saving = true; render();
                try { await options.onConfirm(model.getDocument()); }
                catch (error) { notice = error?.message || '保存失败，当前修改已保留。'; }
                finally { saving = false; if (!destroyed) render(); }
            }, 'dge-primary'); actions.append(confirm); confirmRow.append(actions); container.append(confirmRow);
        }
        unsubscribe = model.subscribe(document => { acknowledged = false; pendingDelete = ''; options.onChange?.(document); });
        render();
        return { getDocument: model.getDocument, validate: model.validate, model,
            destroy() { destroyed = true; unsubscribe(); container.replaceChildren(); container.classList.remove('dmate-graph-editor'); } };
    }
    const api = { mount, createModel, importDocument, validateDocument, groupEdges };
    root.DMateGraphEditor = api;
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
