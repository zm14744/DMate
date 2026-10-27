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
    const unit = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;
    const point = value => Array.isArray(value) && value.length === 2 && value.every(unit);
    const validPath = value => Array.isArray(value) && value.length >= 2 && value.length <= 128 && value.every(point);
    const validBox = value => Array.isArray(value) && value.length === 4 && value.every(unit) && value[0] < value[2] && value[1] < value[3];
    const ring = number => number >= 1 && number <= 20 ? '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'[number - 1] : '未命名' + number;
    function ensureAnonymousLabels(input) {
        const draft = copy(input);
        for (const graph of draft.graphs || []) {
            const used = new Set((graph.vertices || []).map(v => v.label || v.display_label).filter(Boolean));
            let next = Math.max(1, Number.isInteger(graph.anon_next) ? graph.anon_next : 1);
            const circleNames = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳';
            for (const name of used) {
                const at = circleNames.indexOf(String(name));
                if (at >= 0 && String(name).length === 1) next = Math.max(next, at + 2);
                const match = /^未命名(\d+)$/.exec(String(name));
                if (match) next = Math.max(next, Number(match[1]) + 1);
            }
            for (const vertex of graph.vertices || []) {
                if (vertex.label || vertex.display_label) continue;
                let display;
                do { display = ring(next++); } while (used.has(display));
                vertex.display_label = display;
                used.add(display);
            }
            graph.anon_next = next;
        }
        return draft;
    }

    function importDocument(input) {
        const source = input && typeof input === 'object' ? input : {};
        const result = { body_text: text(source.body_text), graphs: [] };
        for (const raw of Array.isArray(source.graphs) ? source.graphs : []) {
            if (!raw || typeof raw !== 'object') continue;
            const graph = { id: id(raw.id) || unique('G', result.graphs), name: text(raw.name), vertices: [], edges: [] };
            if (typeof raw.directed === 'boolean') graph.directed = raw.directed;
            if (typeof raw.weighted === 'boolean') graph.weighted = raw.weighted;
            if (validBox(raw.bbox)) graph.bbox = [...raw.bbox];
            if (Number.isInteger(raw.anon_next) && raw.anon_next >= 1 && raw.anon_next <= 10000) graph.anon_next = raw.anon_next;
            if (result.graphs.some(row => row.id === graph.id)) graph.id = unique('G', result.graphs);
            const inputVertices = Array.isArray(raw.vertices) ? raw.vertices.filter(row => row && typeof row === 'object') : [];
            const oldCounts = new Map();
            inputVertices.forEach(row => oldCounts.set(id(row.id), (oldCounts.get(id(row.id)) || 0) + 1));
            const aliases = new Map();
            for (const rawVertex of inputVertices) {
                let vertexId = id(rawVertex.id) || unique('v', graph.vertices);
                if (graph.vertices.some(row => row.id === vertexId)) vertexId = unique('v', graph.vertices);
                const vertex = { id: vertexId, label: scalar(rawVertex.label) && text(rawVertex.label).trim() ? text(rawVertex.label) : null };
                if (unit(rawVertex.x) && unit(rawVertex.y)) { vertex.x = rawVertex.x; vertex.y = rawVertex.y; }
                if (typeof rawVertex.display_label === 'string' && rawVertex.display_label.length <= 16 && rawVertex.display_label) vertex.display_label = rawVertex.display_label;
                graph.vertices.push(vertex);
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
                if (validPath(rawEdge.path)) edge.path = rawEdge.path.map(row => [...row]);
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
            if (graph.bbox !== undefined && !validBox(graph.bbox)) issues.push(name + '的框选区域无效。');
            const vertices = new Set(), edges = new Set();
            for (const vertex of graph.vertices) {
                if (!vertex.id || vertices.has(vertex.id)) issues.push(name + '有重复或缺失的节点编号。');
                vertices.add(vertex.id);
                if (vertex.label !== null && typeof vertex.label !== 'string') issues.push(name + '有无效节点标签。');
                if (text(vertex.label).length > 128) issues.push(name + '的节点标签超过 128 字。');
                if ((vertex.x !== undefined || vertex.y !== undefined) && !(unit(vertex.x) && unit(vertex.y))) issues.push(name + '有无效顶点位置。');
            }
            graph.edges.forEach((edge, index) => {
                const label = name + '第 ' + (index + 1) + ' 条边';
                if (!edge.id || edges.has(edge.id)) issues.push(label + '编号重复或为空。');
                edges.add(edge.id);
                if (!vertices.has(edge.from) || !vertices.has(edge.to)) issues.push(label + '需要选择有效的两个端点。');
                if (!['forward', 'undirected'].includes(edge.direction)) issues.push(label + '的方向尚未确认。');
                if (edge.weight !== undefined && edge.weight !== null && (!scalar(edge.weight) || /^(unknown|未知|不确定)$/i.test(text(edge.weight).trim()))) issues.push(label + '的权重尚未确认；无权重请留空。');
                if (graph.weighted === true && (edge.weight === undefined || edge.weight === null || text(edge.weight).trim() === '')) issues.push(label + '缺少权值。');
                if (edge.path !== undefined && !validPath(edge.path)) issues.push(label + '的绘图路径无效。');
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
        const initial = importDocument(initialDocument || input), history = [], future = [];
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
            future.length = 0;
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
            canRedo: () => future.length > 0,
            subscribe: listener => { listeners.add(listener); return () => listeners.delete(listener); },
            undo: () => { if (history.length) { future.push(state); state = history.pop(); publish(); } },
            redo: () => { if (future.length) { history.push(state); state = future.pop(); publish(); } },
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
            addVertex: (gid, label, x, y) => {
                let vertexId;
                change(draft => { const graph = getGraph(draft, gid); if (graph.vertices.length >= LIMITS.vertices) throw new Error('每幅图最多 100 个节点。');
                    vertexId = unique('v', graph.vertices);
                    const vertex = { id: vertexId, label: String(label || '').trim() || null };
                    if (x !== undefined || y !== undefined) {
                        if (!unit(x) || !unit(y)) throw new Error('顶点位置必须位于原图内。');
                        vertex.x = x; vertex.y = y;
                    }
                    if (!vertex.label) {
                        let next = Math.max(1, graph.anon_next || 1);
                        const names = new Set(graph.vertices.map(v => v.label || v.display_label));
                        while (names.has(ring(next))) next++;
                        vertex.display_label = ring(next++);
                        graph.anon_next = next;
                    }
                    graph.vertices.push(vertex); });
                return vertexId;
            },
            renameVertex: (gid, vid, label) => change(draft => {
                const graph = getGraph(draft, gid), vertex = graph.vertices.find(row => row.id === vid);
                if (!vertex) throw new Error('找不到这个节点。');
                vertex.label = String(label).trim() || null;
                if (!vertex.label && !vertex.display_label) {
                    let next = Math.max(1, graph.anon_next || 1);
                    const used = new Set(graph.vertices.flatMap(v => [v.label, v.display_label]).filter(Boolean));
                    while (used.has(ring(next))) next++;
                    vertex.display_label = ring(next++);
                    graph.anon_next = next;
                }
            }),
            moveVertex: (gid, vid, x, y) => change(draft => {
                if (!unit(x) || !unit(y)) throw new Error('顶点位置必须位于原图内。');
                const graph = getGraph(draft, gid), vertex = graph.vertices.find(v => v.id === vid);
                if (!vertex) throw new Error('找不到这个节点。');
                const before = unit(vertex.x) && unit(vertex.y) ? [vertex.x, vertex.y] : null;
                vertex.x = x; vertex.y = y;
                for (const edge of graph.edges) if (validPath(edge.path)) {
                    if (edge.from === vid && edge.to === vid && before) {
                        edge.path = edge.path.map(p => [Math.min(1, Math.max(0, p[0] + x - before[0])), Math.min(1, Math.max(0, p[1] + y - before[1]))]);
                    } else {
                        if (edge.from === vid) edge.path[0] = [x, y];
                        if (edge.to === vid) edge.path[edge.path.length - 1] = [x, y];
                    }
                }
            }),
            setGraphBounds: (gid, bbox) => change(draft => {
                if (!validBox(bbox)) throw new Error('请框选有效的图形范围。');
                getGraph(draft, gid).bbox = [...bbox];
            }),
            setGraphType: (gid, type, enabled) => change(draft => {
                if (!['directed', 'weighted'].includes(type) || typeof enabled !== 'boolean') throw new Error('图形类型无效。');
                const graph = getGraph(draft, gid); graph[type] = enabled;
                if (type === 'directed') graph.edges.forEach(edge => { edge.direction = enabled ? 'forward' : 'undirected'; });
                if (type === 'weighted' && !enabled) graph.edges.forEach(edge => { edge.weight = null; });
            }),
            setEdgePath: (gid, eid, path) => change(draft => {
                if (path !== null && !validPath(path)) throw new Error('边的路径必须位于原图内。');
                const edge = getGraph(draft, gid).edges.find(e => e.id === eid);
                if (!edge) throw new Error('找不到这条边。');
                if (path === null) delete edge.path;
                else edge.path = path.map(row => [...row]);
            }),
            deleteVertices: (gid, ids) => change(draft => { const graph = getGraph(draft, gid), selected = new Set(ids);
                graph.vertices = graph.vertices.filter(row => !selected.has(row.id));
                graph.edges = graph.edges.filter(row => !selected.has(row.from) && !selected.has(row.to)); }),
            addEdge: (gid, values) => {
                let edgeId;
                change(draft => { const graph = getGraph(draft, gid); if (graph.edges.length >= LIMITS.edges) throw new Error('每幅图最多 300 条边。');
                    edgeId = unique('e', graph.edges);
                    const edge = { id: edgeId, from: values.from || '', to: values.to || '', direction: values.direction || 'undirected', weight: values.weight ?? null };
                    if (validPath(values.path)) edge.path = values.path.map(row => [...row]);
                    graph.edges.push(edge); });
                return edgeId;
            },
            updateEdges: (gid, ids, field, value) => change(draft => {
                if (!['from', 'to', 'direction', ...ATTRS].includes(field)) throw new Error('无法修改这个字段。');
                const graph = getGraph(draft, gid), selected = new Set(ids);
                graph.edges.forEach(edge => { if (selected.has(edge.id)) {
                    edge[field] = value;
                    if (field === 'from' || field === 'to') delete edge.path;
                } });
            }),
            reverseEdges: (gid, ids) => change(draft => { const graph = getGraph(draft, gid);
                graph.edges.forEach(edge => { if (ids.includes(edge.id)) {
                    [edge.from, edge.to] = [edge.to, edge.from];
                    if (validPath(edge.path)) edge.path.reverse();
                } }); }),
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

    // All semantic graph mutations and validation live here, without DOM access.
    const api = { createModel, importDocument, validateDocument, groupEdges,
        ensureAnonymousLabels, valueText: text };
    root.DMateGraphEditorModel = api;
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
