(function (root) {
    'use strict';
    // Share one validated semantic model across SVG interaction and Node tests.
    const modelApi = root.DMateGraphEditorModel ||
        (typeof module !== 'undefined' && module.exports ? require('./graph-editor-model.js') : null);
    if (!modelApi) throw new Error('图结构编辑模块未加载。');
    const { createModel, importDocument, validateDocument, groupEdges, valueText: text } = modelApi;

    let mountSequence = 0;
    function mount(container, options) {
        if (!container || !container.ownerDocument) throw new Error('编辑器需要有效的页面容器。');
        options ||= {};
        const dom = container.ownerDocument;
        const useOverlay = typeof options.originalUrl === 'string' && /^((blob:)|(data:image\/)|(https?:\/\/))/i.test(options.originalUrl) && root.DMateGraphOverlay?.mount;
        const initialized = useOverlay && modelApi.ensureAnonymousLabels
            ? modelApi.ensureAnonymousLabels(options.document) : options.document;
        const initial = useOverlay && modelApi.ensureAnonymousLabels
            ? modelApi.ensureAnonymousLabels(options.initialDocument || options.document) : options.initialDocument;
        const model = createModel(initialized, initial);
        const instance = 'dmate-editor-' + (++mountSequence), svgNS = 'http://www.w3.org/2000/svg';
        let currentGraph = model.getDocument().graphs[0]?.id, selectedNodes = new Set(), selectedEdge = null;
        let individually = false, saving = false, destroyed = false, notice = '', pendingDelete = '';
        // "Is this a question?" is a per-upload choice, separate from graph data.
        let isQuestion = options.isQuestion !== false;
        let unsubscribe, overlay = null;
        const overlayState = { mode: 'select', zoom: 100, visible: true, start: null };
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
        const nodeOptions = graph => { const rows = [['', '请选择节点'], ...graph.vertices.map((vertex, index) => [vertex.id, vertex.label === null ? (vertex.display_label || '未命名节点 ' + (index + 1)) : vertex.label])]; rows.graphId = graph.id; return rows; };
        const graphOptions = (document, excluded) => [['', '选择目标子图'], ...document.graphs.filter(graph => graph.id !== excluded).map((graph, index) => [graph.id, graph.name || '图 ' + (index + 1)])];
        const weightValue = value => value.trim() === '' ? null : /^[-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?$/i.test(value.trim()) && Number.isFinite(Number(value)) ? Number(value) : value;

        function buildNodeRow(graph, vertex, index) {
            const row = element('div', 'dge-node-row' +
                (selectedNodes.has(vertex.id) ? ' is-selected' : ''));
            row.dataset.vertexId = vertex.id;
            const check = element('input'); check.type = 'checkbox';
            check.checked = selectedNodes.has(vertex.id); check.disabled = saving;
            check.setAttribute('aria-label', '选中节点 ' + (vertex.label ?? (index + 1)));
            check.addEventListener('change', () => act(() => {
                check.checked ? selectedNodes.add(vertex.id) : selectedNodes.delete(vertex.id);
            }));
            const label = input(vertex.label, '节点 ' + (index + 1) + ' 标签',
                value => model.renameVertex(graph.id, vertex.id, value));
            label.placeholder = '未命名节点';
            const incident = graph.edges.filter(edge =>
                edge.from === vertex.id || edge.to === vertex.id).length;
            const kind = element('span', 'dge-node-kind',
                incident ? incident + ' 条关联边' : '孤立点');
            kind.dataset.nodeIncident = vertex.id;
            row.append(check, label, kind);
            return row;
        }

        function refreshCanvasVertex() {
            // Pointer drawing changes only one node. Never detach the original
            // image, its scroll container or the dialog merely to append it.
            // Retain the zoom, pan position, active drawing mode and scroll.
            const document = model.getDocument();
            const graph = document.graphs.find(row => row.id === currentGraph);
            const panel = container.querySelector('.dge-node-panel');
            const list = panel?.querySelector('.dge-node-list');
            if (!graph || !overlay || !list) { render(); return; }
            refreshDraftViews();
            const heading = panel.querySelector('h3');
            if (heading) heading.textContent = '节点 · ' + graph.vertices.length;
            const present = new Set([...list.children].map(row => row.dataset.vertexId));
            graph.vertices.forEach((vertex, index) => {
                if (!present.has(vertex.id)) {
                    list.append(buildNodeRow(graph, vertex, index));
                    present.add(vertex.id);
                }
            });
            // The first node can create a review section that did not exist.
            if (graph.vertices.length && !container.querySelector('.dge-review-summary')) {
                const review = buildReview(graph, document);
                const body = container.querySelector('.dge-body')?.closest('.dge-field');
                if (review && body) container.insertBefore(review, body);
            }
        }

        function refreshDraftViews() {
            if (destroyed) return;
            const document = model.getDocument(), graph = document.graphs.find(row => row.id === currentGraph);
            const visual = container.querySelector('.dge-visual');
            if (visual && graph) { visual.querySelector('svg')?.remove(); visual.append(drawGraph(graph)); }
            overlay?.refresh();
            const oldReview = container.querySelector('.dge-review-summary');
            if (oldReview && graph) {
                const refreshed = buildReview(graph, document);
                if (refreshed) { refreshed.open = oldReview.open; oldReview.replaceWith(refreshed); }
            }
            const status = container.querySelector('.dge-status'); if (status) status.textContent = notice;
            const undo = container.querySelector('[data-editor-undo]'); if (undo) undo.disabled = saving || !model.canUndo();
            const redo = container.querySelector('[data-editor-redo]'); if (redo) redo.disabled = saving || !model.canRedo();
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
                const [x, y] = points.get(vertex.id), label = vertex.label ?? vertex.display_label ?? '未命名 ' + (index + 1);
                const group = svgElement('g', { class: 'dge-visual-node' + (selectedNodes.has(vertex.id) ? ' is-selected' : ''), tabindex: 0, role: 'button', 'aria-label': '选择节点 ' + label });
                group.append(svgElement('title', {}, label), svgElement('circle', { cx: x, cy: y, r: 18 }),
                    svgElement('text', { x, y: y + 5, 'text-anchor': 'middle' }, label.length > 12 ? label.slice(0, 11) + '…' : label));
                const choose = () => { selectedNodes.has(vertex.id) ? selectedNodes.delete(vertex.id) : selectedNodes.add(vertex.id); render(); };
                group.addEventListener('click', choose); group.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(); } }); svg.append(group);
            });
            return svg;
        }

        function buildReview(graph, document) {
            if (graph && root.DMateGraphFormat?.graphRows) {
                const data = root.DMateGraphFormat.graphRows(graph, document.graphs.indexOf(graph));
                const summary = element('details', 'dge-review-summary'); summary.open = true;
                summary.append(element('summary', '', '图形结构 · ' + graph.vertices.length + ' 点 / ' + graph.edges.length + ' 边'));
                const section = element('div', 'dge-review-content');
                section.append(element('p', 'dge-review-type', data.title + '    ' + data.type));
                section.append(element('p', '', '点：' + (data.vertices.join('、') || '无')));
                if (data.named.length) section.append(element('p', '', '边：' + data.named.join('、')));
                section.append(element('p', 'dge-review-subhead', '关系：'));
                if (!data.relations.length) section.append(element('p', '', '无'));
                for (const row of data.relations) {
                    const link = element('button', 'dge-review-relation', row.txt);
                    link.type = 'button';
                    if (row.id === selectedEdge) link.classList.add('is-selected');
                    link.addEventListener('click', () => act(() => { selectedEdge = row.id; selectedNodes.clear(); }));
                    section.append(link);
                }
                summary.append(section); return summary;
            }
            return null;
        }

        function buildSelectedProperties(graph) {
            const aside = element('aside', 'dge-selection-panel');
            if (!graph) return aside;
            const selectedNode = selectedNodes.size === 1
                ? graph.vertices.find(v => selectedNodes.has(v.id)) : null;
            const edge = graph.edges.find(e => e.id === selectedEdge);
            if (edge) {
                aside.append(element('h3', '', '边的属性'));
                const index = graph.edges.indexOf(edge) + 1, ids = [edge.id];
                const endpoints = nodeOptions(graph);
                aside.append(field('起点', select(endpoints, edge.from, '当前边起点',
                    value => model.updateEdges(graph.id, ids, 'from', value))));
                aside.append(field('终点', select(endpoints, edge.to, '当前边终点',
                    value => model.updateEdges(graph.id, ids, 'to', value))));
                aside.append(field('方向', select([['undirected','无向 —'], ['forward','有向 →'],
                    ['unknown','待核对 ?']], edge.direction, '当前边方向',
                    value => model.updateEdges(graph.id, ids, 'direction', value))));
                aside.append(button('反转方向', () => model.reverseEdges(graph.id, ids)));
                aside.append(field('权值', input(edge.weight, '当前边权值',
                    value => model.updateEdges(graph.id, ids, 'weight', weightValue(value)))));
                aside.append(field('边名', input(edge.edge_label, '当前边名称',
                    value => model.updateEdges(graph.id, ids, 'edge_label', value || null))));
                aside.append(button('删除这条边', () =>
                    askDelete('edges:' + edge.id, '将删除这一条边。', () =>
                        model.deleteEdges(graph.id, ids)), 'dge-danger'));
                const note = element('p', 'dge-muted', '每条重边都能独立修改 · 边 ' + index);
                aside.append(note);
            } else if (selectedNode) {
                aside.append(element('h3', '', '顶点的属性'));
                aside.append(field('名称', input(selectedNode.label, '当前顶点名称',
                    value => model.renameVertex(graph.id, selectedNode.id, value))));
                if (!selectedNode.label) aside.append(element('p', 'dge-muted',
                    '临时编号 ' + (selectedNode.display_label || '') + ' 仅用于核对原图'));
                aside.append(button('删除这个顶点', () => {
                    const incident = graph.edges.filter(e =>
                        e.from === selectedNode.id || e.to === selectedNode.id).length;
                    askDelete('vertex:' + selectedNode.id,
                        '会同时删除 ' + incident + ' 条关联边。', () => {
                            model.deleteVertices(graph.id, [selectedNode.id]);
                            selectedNodes.clear();
                        });
                }, 'dge-danger'));
            }
            return aside;
        }

        function questionChoice() {
            const row = element('div', 'dge-question-mode');
            row.setAttribute('role', 'radiogroup');
            row.setAttribute('aria-label', '识别内容是否为题目');
            row.append(element('span', 'dge-question-label', '题目'));
            for (const [label, flag] of [['是', true], ['否', false]]) {
                const option = element('label', 'dge-question-option');
                const radio = element('input');
                radio.type = 'radio';
                radio.name = instance + '-question';
                radio.value = flag ? 'question' : 'other';
                radio.checked = isQuestion === flag;
                radio.disabled = saving;
                radio.addEventListener('change', () => {
                    if (!radio.checked || saving || destroyed) return;
                    isQuestion = flag;
                    options.onQuestionChange?.(isQuestion);
                });
                option.append(radio, dom.createTextNode(label));
                row.append(option);
            }
            return row;
        }

        function render() {
            if (destroyed) return;
            // The editor may live in a scrollable dialog AND a scrollable
            // browser viewport. Swapping ancillary controls must not move
            // either one, even if the overlay is temporarily reparented.
            const scrollState = [];
            if (useOverlay && overlay) {
                let ancestor = container;
                while (ancestor) {
                    if (ancestor.scrollHeight > ancestor.clientHeight + 1 ||
                            ancestor.scrollWidth > ancestor.clientWidth + 1) {
                        scrollState.push([ancestor, ancestor.scrollTop, ancestor.scrollLeft]);
                    }
                    ancestor = ancestor.parentElement;
                }
                const rootScroller = dom.scrollingElement;
                if (rootScroller && !scrollState.some(entry => entry[0] === rootScroller))
                    scrollState.push([rootScroller, rootScroller.scrollTop, rootScroller.scrollLeft]);
            }
            const document = model.getDocument();
            let graph = document.graphs.find(row => row.id === currentGraph) || document.graphs[0]; currentGraph = graph?.id;
            selectedNodes = new Set([...selectedNodes].filter(vid => graph?.vertices.some(row => row.id === vid)));
            if (!graph?.edges.some(edge => edge.id === selectedEdge)) selectedEdge = null;
            // Keep the actual image and zoom/scroll when only controls change.
            // Pure-text images have no mathematical drawing area to prefill.
            const retainedOverlay = useOverlay && graph
                ? container.querySelector('.dge-overlay-host') : null;
            if (retainedOverlay) retainedOverlay.remove();
            else if (overlay) { overlay.destroy(); overlay = null; }
            container.replaceChildren(); container.classList.add('dmate-graph-editor');
            const top = element('div', 'dge-topline');
            // The toolbar already names its actions; keep the dialog compact.
            const undo = button('撤销', () => { pendingDelete = ''; model.undo(); }); undo.dataset.editorUndo = 'true'; undo.disabled = saving || !model.canUndo();
            const redo = button('重做', () => { pendingDelete = ''; model.redo(); });
            redo.dataset.editorRedo = 'true'; redo.disabled = saving || !model.canRedo();
            top.append(questionChoice(), undo, redo,
                button('清空修改', () => askDelete('reset', '将撤销本张图片的全部修改。', () => model.reset())));
            container.append(top);
            const observations = (Array.isArray(options.issues) ? options.issues : [])
                .map(issue => typeof issue === 'string' ? issue : text(issue?.message)).filter(Boolean);
            if (observations.length && !useOverlay) { const details = element('details', 'dge-observations'); details.open = true;
                details.append(element('summary', '', '识别时需留意'));
                const list = element('ul'); observations.slice(0, 64).forEach(message => list.append(element('li', '', message))); details.append(list); container.append(details); }
            const workspace = element('div', 'dge-workspace');
            if (useOverlay && graph) {
                const host = retainedOverlay || element('section', 'dge-overlay-host');
                workspace.append(host);
                container.append(workspace);
                if (!overlay) overlay = root.DMateGraphOverlay.mount(host, {
                    instance, originalUrl: options.originalUrl, model, state: overlayState,
                    graph: () => model.getDocument().graphs.find(row => row.id === currentGraph),
                    disabled: () => saving || destroyed,
                    edgeSelected: () => selectedEdge,
                    nodeSelected: () => selectedNodes,
                    selectEdge: id => { selectedEdge = id; selectedNodes.clear(); render(); },
                    selectNode: id => { selectedNodes = new Set([id]); selectedEdge = null; render(); },
                    changed: kind => {
                        if (kind === 'vertex') refreshCanvasVertex();
                        else if (kind === 'geometry') refreshDraftViews();
                        else render();
                    },
                    recognizeText: async polygon => {
                        if (typeof options.onRecognizeText !== 'function')
                            throw new Error('文字区域识别暂不可用，请手动输入。');
                        const text = await options.onRecognizeText(polygon);
                        if (typeof text === 'string' && text.trim()) {
                            const previous = model.getDocument().body_text;
                            model.setBody([previous.trimEnd(), text.trim()].filter(Boolean).join('\n'));
                            render();
                        }
                        return text;
                    },
                    recognizeGraphType: async (polygon, graphId) => {
                        if (typeof options.onRecognizeGraphType !== 'function')
                            throw new Error('当前无法自动判断箭头与权值');
                        const result = await options.onRecognizeGraphType(polygon);
                        // Another frame may have been drawn while the async read
                        // was underway. Never apply old metadata to new pixels.
                        const graph = model.getDocument().graphs.find(row => row.id === graphId);
                        if (!graph) return { stale: true };
                        const samePolygon = Array.isArray(graph.region_polygon)
                            && JSON.stringify(graph.region_polygon) === JSON.stringify(polygon);
                        const box = graph.bbox;
                        const xs = polygon.map(point => point[0]);
                        const ys = polygon.map(point => point[1]);
                        const sameBox = Array.isArray(box) && box.length === 4
                            && Math.abs(box[0] - Math.min(...xs)) < 1e-7
                            && Math.abs(box[1] - Math.min(...ys)) < 1e-7
                            && Math.abs(box[2] - Math.max(...xs)) < 1e-7
                            && Math.abs(box[3] - Math.max(...ys)) < 1e-7;
                        if ((!samePolygon && !sameBox) || graph.edges.length) return { stale: true };
                        if (typeof result?.directed === 'boolean')
                            model.setGraphType(graphId, 'directed', result.directed);
                        if (typeof result?.weighted === 'boolean')
                            model.setGraphType(graphId, 'weighted', result.weighted);
                        render();
                        return result;
                    }
                });
                else overlay.refresh();
                const properties = buildSelectedProperties(graph);
                if (properties.childElementCount) workspace.append(properties);
            } else {
                const preview = element('section', 'dge-original'); preview.append(element('h3', '', '原图'));
                if (typeof options.originalUrl === 'string') {
                    const image = element('img'); image.src = options.originalUrl;
                    image.alt = '上传的原图，用于核对识别结果'; preview.append(image);
                } else preview.append(element('p', 'dge-muted', '原图预览暂不可用，可继续编辑结构。'));
                if (graph) {
                    const visual = element('section', 'dge-visual');
                    visual.append(element('h3', '', '结构预览'), drawGraph(graph));
                    workspace.append(preview, visual);
                } else {
                    // No graph: show only the original image and OCR body.
                    workspace.append(preview);
                    workspace.classList.add('dge-text-only-workspace');
                }
                container.append(workspace);
            }
            const review = buildReview(graph, document);
            if (review && graph?.vertices?.length) container.append(review);
            const body = element('textarea', 'dge-body'); body.value = document.body_text; body.rows = 4; body.setAttribute('aria-label', '题干、全部小问与公式'); body.disabled = saving;
            body.addEventListener('input', () => edit(() => model.setBody(body.value)));
            container.append(field('题干、全部小问与公式', body));
            const toolbar = element('div', 'dge-toolbar');
            if (document.graphs.length) {
                toolbar.append(field('当前子图', select(document.graphs.map((row, index) => [row.id, row.name || '图 ' + (index + 1)]), currentGraph, '当前子图', value => { currentGraph = value; selectedNodes.clear(); selectedEdge = null; pendingDelete = ''; render(); })));
                // Metadata only. This summary is never converted into guessed
                // vertices, arrows, edge weights, or drawing paths.
                if (graph) {
                    const direction = graph.directed === true ? '有向图'
                        : graph.directed === false ? '无向图' : '方向待核对';
                    const weight = graph.weighted === true ? '带权图'
                        : graph.weighted === false ? '无权图' : '权值待核对';
                    toolbar.append(element('span', 'dge-detected-type', direction + ' · ' + weight));
                }
            }
            toolbar.append(button('添加子图', () => { currentGraph = model.addGraph(); selectedNodes.clear(); selectedEdge = null; }));
            if (graph) {
                toolbar.append(field('子图名称', input(graph.name, '子图名称', value => model.renameGraph(graph.id, value))));
                toolbar.append(button('删除子图', () => askDelete('graph:' + graph.id, '将删除这幅图的 ' + graph.vertices.length + ' 个节点和 ' + graph.edges.length + ' 条边。', () => model.deleteGraph(graph.id)), 'dge-danger'));
                if (document.graphs.length > 1) { const target = select(graphOptions(document, graph.id), '', '合并目标子图', null);
                    toolbar.append(field('合并子图', target), button('合并到所选图', () => { if (!target.value) throw new Error('请先选择合并目标。'); const targetId = target.value; model.mergeGraph(graph.id, targetId); currentGraph = targetId; })); }
            }
            container.insertBefore(toolbar, workspace);
            if (graph) {
                const panels = element('div', 'dge-edit-panels'), nodes = element('section', 'dge-node-panel'), edges = element('section', 'dge-edge-panel');
                nodes.append(element('h3', '', '节点 · ' + graph.vertices.length));
                const nodeList = element('div', 'dge-node-list');
                graph.vertices.forEach((vertex, index) => nodeList.append(buildNodeRow(graph, vertex, index)));

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
                panels.append(nodes, edges);
                if (useOverlay) {
                    const advanced = element('details', 'dge-advanced-panel');
                    advanced.append(element('summary', '',
                        '更多编辑选项 · 批量修改节点、重边及子图归属'));
                    advanced.append(panels);
                    container.append(advanced);
                } else container.append(panels);
            }
            const status = element('div', 'dge-status'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite'); status.textContent = notice; container.append(status);
            const confirmRow = element('div', 'dge-footer');
            // The dialog header contains the close button; footer is save only.
            const actions = element('div', 'dge-actions');
            const confirm = button(saving ? '正在保存…' : '保存并确认', async () => {
                if ([...container.querySelectorAll('input[type=number]')].some(control => !control.checkValidity())) {
                    notice = '请填写有效的相同边数量（1 到 50）。'; refreshDraftViews(); return;
                }
                const problems = model.validate();
                // The default draft may be empty; only show validation errors after Save is pressed.
                if (problems.length) { notice = problems[0]; render(); return; }
                if (typeof options.onConfirm !== 'function') { notice = '暂时无法保存，请稍后重试。'; render(); return; }
                saving = true; render();
                try { await options.onConfirm(model.getDocument(), isQuestion); }
                catch (error) { notice = error?.message || '保存失败，当前修改已保留。'; }
                finally { saving = false; if (!destroyed) render(); }
            }, 'dge-primary'); actions.append(confirm); confirmRow.append(actions); container.append(confirmRow);
            for (const [scroller, top, left] of scrollState) {
                scroller.scrollTop = top;
                scroller.scrollLeft = left;
            }
        }
        unsubscribe = model.subscribe(document => { pendingDelete = ''; options.onChange?.(document); });
        render();
        return { getDocument: model.getDocument, getIsQuestion: () => isQuestion,
            validate: model.validate, model,
            destroy() { destroyed = true; unsubscribe(); overlay?.destroy(); container.replaceChildren(); container.classList.remove('dmate-graph-editor'); } };
    }
    const api = { mount, createModel, importDocument, validateDocument, groupEdges };
    root.DMateGraphEditor = api;
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
