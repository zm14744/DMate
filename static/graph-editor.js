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
        const useOverlay = !options.structureOnly && typeof options.originalUrl === 'string' && /^((blob:)|(data:image\/)|(https?:\/\/))/i.test(options.originalUrl) && root.DMateGraphOverlay?.mount;
        const initialized = (useOverlay || options.previewOnly) && modelApi.ensureAnonymousLabels
            ? modelApi.ensureAnonymousLabels(options.document) : options.document;
        const initial = useOverlay && modelApi.ensureAnonymousLabels
            ? modelApi.ensureAnonymousLabels(options.initialDocument || options.document) : options.initialDocument;
        const model = createModel(initialized, initial);
        const instance = 'dmate-editor-' + (++mountSequence), svgNS = 'http://www.w3.org/2000/svg';
        const reviewKeys = new WeakMap();
        let previewSequence = 0, renderSequence = 0;
        let currentGraph = model.getDocument().graphs[0]?.id, selectedNodes = new Set(), selectedEdge = null, propertiesVisible = true;
        let selectedGraph=false;const panelState={};
        const closeFloatingPanels = () => {
            for (const key of Object.keys(panelState)) panelState[key] = false;
            for (const panel of container.querySelectorAll('.dge-floating-actions > details[data-panel-key]'))
                panel.open = false;
        };
        let individually = false, saving = false, destroyed = false, notice = '';
        // "Is this a question?" is a per-upload choice, separate from graph data.
        let isQuestion = options.isQuestion !== false;
        let unsubscribe, overlay = null, textOverlay = null, activeTab = 'image', textBusy = false, textTimer = null, refreshTextPanel = null, runTextQueue = null, recognitionEpoch = 0;
        const textState = options.textState || { mode: 'text_rect', zoom: 100, visible: true };
        let requirements = String(options.requirements || '');
        const hasDirection = graph => graph.directed === true || graph.directed !== false &&
            (!graph.edges.length || graph.edges.some(edge => edge.direction !== 'undirected'));
        const overlayState = { mode: 'select', zoom: 100, visible: true, start: null };
        const removeGraph=id=>{model.deleteGraph(id);selectedNodes.clear();selectedEdge=null;selectedGraph=false;
            overlayState.start=null;overlayState.polygonDraft=[];overlayState.textRegion=null;};
        const element = (tag, className, label) => { const node = dom.createElement(tag); if (className) node.className = className;
            if (label !== undefined) node.textContent = label; return node; };
        const svgElement = (tag, attributes, label) => { const node = dom.createElementNS(svgNS, tag);
            Object.entries(attributes || {}).forEach(([key, value]) => node.setAttribute(key, String(value)));
            if (label !== undefined) node.textContent = label; return node; };
        const button = (label, action, className) => { const node = element('button', className || '', label); node.type = 'button'; node.disabled = saving;
            node.addEventListener('click', event => { event.stopPropagation(); act(action); }); return node; };
        const historyButton = (label, paths, action) => {
            const node = button('', action, 'dge-history-arrow');
            node.setAttribute('aria-label', label); node.title = label;
            const icon = svgElement('svg', {viewBox:'0 0 24 24', width:24, height:24, fill:'none',
                stroke:'currentColor', 'stroke-width':1.8, 'stroke-linecap':'round', 'stroke-linejoin':'round',
                'aria-hidden':'true', focusable:'false'});
            for (const path of paths) icon.append(svgElement('path', {d:path}));
            node.append(icon); return node;
        };
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
            if (!graph || !overlay) { render(); return; }
            // Canvas editing deliberately has no bulk table. Adding a vertex
            // still updates its geometry, information and undo state in place.
            if (!list) { refreshDraftViews(); return; }
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
            const body = container.querySelector('.dge-text-body');
            if (body && dom.activeElement !== body) body.value = document.body_text;
            refreshReview(document);
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
            const svg = svgElement('svg', { viewBox: '0 0 620 390', role: options.previewOnly ? 'img' : 'group', 'aria-label': (graph.name || '当前图') + '结构预览' });
            const markerId = instance + '-arrow-' + (++previewSequence), defs = svgElement('defs');
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
                if (edge.direction === 'unknown') attrs['stroke-dasharray'] = '4 5';
                const stroke = svgElement('path', attrs);
                const colors = { red: '#dc2626', blue: '#2563eb', green: '#15803d', purple: '#9333ea', orange: '#d97706', gray: '#64748b' };
                if (colors[edge.color]) stroke.style.stroke = colors[edge.color];
                group.append(svgElement('path', { d: path, class: 'dge-edge-hit', fill: 'none' }), stroke);
                const label = [edge.edge_label, edge.weight === null || edge.weight === undefined ? '' : text(edge.weight)].filter(value => value !== null && value !== undefined && value !== '').join(' · ');
                if (label) { group.append(svgElement('title', {}, label)); group.append(svgElement('text', { x: tx, y: ty, class: 'dge-edge-label', 'text-anchor': 'middle' }, label.length > 24 ? label.slice(0, 23) + '…' : label)); }
                const choose = () => { propertiesVisible = true; selectedEdge = edge.id; render(); };
                if (!options.previewOnly) { group.addEventListener('click', choose); group.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(); } }); }
                else { group.removeAttribute('tabindex'); group.removeAttribute('role'); }
                svg.append(group);
            });
            graph.vertices.forEach((vertex, index) => {
                const [x, y] = points.get(vertex.id), label = vertex.label ?? vertex.display_label ?? '未命名 ' + (index + 1);
                const group = svgElement('g', { class: 'dge-visual-node' + (selectedNodes.has(vertex.id) ? ' is-selected' : ''), tabindex: 0, role: 'button', 'aria-label': '选择节点 ' + label });
                group.append(svgElement('title', {}, label), svgElement('circle', { cx: x, cy: y, r: 18 }),
                    svgElement('text', { x, y: y + 5, 'text-anchor': 'middle' }, label.length > 12 ? label.slice(0, 11) + '…' : label));
                const choose = () => { selectedNodes.has(vertex.id) ? selectedNodes.delete(vertex.id) : selectedNodes.add(vertex.id); render(); };
                if (!options.previewOnly) { group.addEventListener('click', choose); group.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(); } }); }
                else { group.removeAttribute('tabindex'); group.removeAttribute('role'); }
                svg.append(group);
            });
            return svg;
        }

        if (options.previewOnly) {
            container.replaceChildren();
            for (const graph of model.getDocument().graphs) {
                const section = element('section', 'dge-visual');
                section.append(element('h4', '', graph.name || graph.id), drawGraph(graph));
                container.append(section);
            }
            return {getDocument: model.getDocument, destroy() {container.replaceChildren();}};
        }

        function reviewKey(document) {
            return JSON.stringify(document.graphs.map((graph, index) => root.DMateGraphFormat.graphRows(graph, index)));
        }

        function refreshReview(document) {
            const review = container.querySelector('.dge-review-summary');
            if (!review || !root.DMateGraphFormat?.renderGraphInformation) return;
            const key = reviewKey(document);
            if (reviewKeys.get(review) === key) return;
            // Keep the popup, its scroll container and active property input.
            // Geometry-only changes do not alter this key or replace content.
            root.DMateGraphFormat.renderGraphInformation(review.querySelector('.dge-review-content'), document);
            reviewKeys.set(review, key);
        }

        function buildReview(graph, document) {
            if (!root.DMateGraphFormat?.renderGraphInformation) return null;
            const summary = element('section', 'dge-review-summary');
            reviewKeys.set(summary, reviewKey(document));
            summary.append(element('h3', '', '图形信息'));
            const content = element('div', 'dge-review-content');
            root.DMateGraphFormat.renderGraphInformation(content, document);
            summary.append(content);
            return summary;
        }

        function buildSelectedProperties(graph) {
            const aside = element('aside', 'dge-selection-panel');
            if (!graph || !propertiesVisible) return aside;
            const selectedNode = selectedNodes.size === 1
                ? graph.vertices.find(v => selectedNodes.has(v.id)) : null;
            const edge = graph.edges.find(e => e.id === selectedEdge);
            if (edge) {
                aside.append(element('h3', '', '边的属性'));
                const index = graph.edges.indexOf(edge) + 1, ids = [edge.id];
                const endpoints = nodeOptions(graph);
                aside.append(field(hasDirection(graph)?'起点':'端点一', select(endpoints, edge.from, hasDirection(graph)?'当前边起点':'当前边端点一',
                    value => model.updateEdges(graph.id, ids, 'from', value))));
                aside.append(field(hasDirection(graph)?'终点':'端点二', select(endpoints, edge.to, hasDirection(graph)?'当前边终点':'当前边端点二',
                    value => model.updateEdges(graph.id, ids, 'to', value))));
                if(hasDirection(graph)){aside.append(field('方向', select([['undirected','无向 —'], ['forward','有向 →'],
                    ['unknown','待核对 ?']], edge.direction, '当前边方向',
                    value => model.updateEdges(graph.id, ids, 'direction', value))));
                aside.append(button('反转方向', () => model.reverseEdges(graph.id, ids)));}
                if(graph.weighted!==false)aside.append(field('权值', input(edge.weight, '当前边权值',
                    value => model.updateEdges(graph.id, ids, 'weight', weightValue(value)))));
                aside.append(field('边名', input(edge.edge_label, '当前边名称',
                    value => model.updateEdges(graph.id, ids, 'edge_label', value || null))));
                aside.append(button('删除这条边', () => {
                    model.deleteEdges(graph.id, ids); selectedEdge = null;
                }, 'dge-danger'));
                const note = element('p', 'dge-muted', '每条重边都能独立修改 · 边 ' + index);
                aside.append(note);
            } else if (selectedNode) {
                aside.append(element('h3', '', '顶点的属性'));
                aside.append(field('名称', input(selectedNode.label ?? selectedNode.display_label, '当前顶点名称',
                    value => model.renameVertex(graph.id, selectedNode.id, value))));
                aside.append(button('删除这个顶点', () => {
                    model.deleteVertices(graph.id, [selectedNode.id]); selectedNodes.clear();
                }, 'dge-danger'));
            } else if(selectedGraph && !options.drawingOnly){
                aside.append(element('h3','','子图属性'));
                aside.append(field('名称',input(graph.name,'当前子图名称',v=>model.renameGraph(graph.id,v))));
                aside.append(element('p','dge-muted',(graph.directed===false?'无向':'有向或待核对')+' · '+(graph.weighted===false?'无权':'带权或待核对')));
                aside.append(button('删除子图',()=>removeGraph(graph.id),'dge-danger'));
            }
            if(aside.childElementCount){const close=button('',()=>{propertiesVisible=false;});close.classList.add('dge-panel-close');close.setAttribute('aria-label','关闭属性');close.title='关闭属性';aside.prepend(close);}
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

        function buildTextWorkspace() {
            const pane = element('section', 'dge-text-workspace');
            pane.setAttribute('role', 'tabpanel'); pane.id = instance + '-text-panel';
            pane.setAttribute('aria-labelledby', instance + '-text-tab');
            const host = element('section', 'dge-overlay-host dge-text-overlay-host'); pane.append(host);
            textState.regions ||= [];
            textState.nextId = textState.regions.reduce((next,r) => Math.max(next,r.id+1),textState.nextId || 1);
            for (const row of textState.regions) if (row.status === 'recognizing') row.status = 'queued';
            const rack = element('div', 'dge-floating-actions'); pane.append(rack);
            const panel = element('details', 'dge-float-panel dge-text-results'); panel.open = false;
            const content = element('div', 'dge-float-content');
            panel.append(element('summary', '', '文字识别结果'), content); rack.append(panel);
            const status = element('p', 'dge-text-status'); status.setAttribute('role', 'status');
            const list = element('div', 'dge-text-region-list');
            const body = element('textarea', 'dge-text-body'); body.rows = 5; body.maxLength = 23000;
            body.setAttribute('aria-label', '文字识别结果'); body.value = model.getDocument().body_text;
            body.placeholder = '连续框选文字后自动识别，结果按框编号汇总到这里。';
            body.addEventListener('input', () => { textState.manuallyEdited = true; edit(() => model.setBody(body.value)); refreshTextPanel(); });
            const assemble = () => textState.regions.filter(r => r.text?.trim()).map(r => r.text.trim()).join('\n\n');
            const applyResults = () => {
                const value = assemble();
                if (value.length > 23000) { textState.assemblyError = '汇总文字过长，请精简后保存。'; return; }
                textState.assemblyError = '';
                model.setBody(value); body.value = value; refreshDraftViews();
            };
            const apply = button('使用编号顺序的识别结果', () => { textState.manuallyEdited = false; applyResults(); });
            const schedule = () => {
                clearTimeout(textTimer);
                textTimer = setTimeout(() => { textTimer = null; void runTextQueue(); }, 550);
            };
            refreshTextPanel = () => {
                const rows = textState.regions;
                panel.querySelector('summary').textContent = '文字识别结果（' + rows.filter(r => r.status === 'done').length + '/' + rows.length + '）';
                const queued = rows.filter(r => r.status === 'queued').length;
                const failed = rows.filter(r => ['error','empty'].includes(r.status)).length;
                status.textContent = textBusy && rows.some(r=>r.status==='recognizing') ? '正在按编号识别，新增框会接着处理…'
                    : queued ? '已框选，准备按编号一次识别…'
                    : failed ? '部分文字框未识别完成，请查看对应编号并重试。'
                    : rows.length ? '已按框编号顺序汇总。' : '连续框选即可自动识别，支持多个文字框。';
                if (textState.assemblyError) status.textContent = textState.assemblyError;
                if (textState.manuallyEdited && rows.length) status.textContent += ' 已保留手动修改，可点击下方按钮重新汇总。';
                list.replaceChildren();
                const labels = {queued:'待识别',recognizing:'识别中',done:'已识别',empty:'未识别到文字',error:'识别失败'};
                for (const row of rows) {
                    const item = element('div', 'dge-text-region-row'); item.dataset.textRegionId = row.id;
                    item.append(element('strong', '', '文字框 ' + row.id + ' · ' + labels[row.status]));
                    if (row.error) item.append(element('p', 'dge-muted', row.error));
                    if (row.text) item.append(element('p', 'dge-text-excerpt', row.text));
                    if (['error','empty'].includes(row.status)) item.append(button('重试文字框 ' + row.id, () => {
                        row.status = 'queued'; row.error = ''; refreshTextPanel(); schedule();
                    }));
                    item.append(button('删除文字框 ' + row.id, () => {
                        textState.regions = textState.regions.filter(r => r !== row);
                        if (!textState.manuallyEdited && row.text) applyResults();
                        refreshTextPanel(); textOverlay?.refresh();
                    })); list.append(item);
                }
                apply.hidden = !textState.manuallyEdited || !rows.some(r => r.text?.trim());
                textOverlay?.refresh();
            };
            runTextQueue = async () => {
                if (destroyed || saving || textBusy) return;
                const batch = textState.regions.filter(r => r.status === 'queued').sort((a,b) => a.id-b.id);
                if (!batch.length) return;
                textBusy = true; batch.forEach(r => { r.status = 'recognizing'; }); refreshTextPanel();
                try {
                    if (typeof options.onRecognizeText !== 'function') throw new Error('文字识别暂不可用，可手动输入。');
                    const result = await options.onRecognizeText(batch.map(r => ({id:r.id, polygon:r.polygon.map(p => [...p])})));
                    if (destroyed) return;
                    const response = result?.regions;
                    if (!Array.isArray(response) || response.length !== batch.length ||
                        response.some((r,i) => r.id !== batch[i].id || typeof r.text !== 'string'))
                        throw new Error('文字识别返回的框编号不匹配，请重试。');
                    batch.forEach((row,i) => {
                        if (!textState.regions.includes(row)) return;
                        row.text = response[i].text; row.status = row.text.trim() ? 'done' : 'empty';
                        row.error = row.status === 'empty' ? '框内未检测到文字，可调整范围或重试。' : '';
                    });
                    if (!textState.manuallyEdited && textState.regions.some(r => r.text?.trim())) applyResults();
                } catch (error) {
                    if (!destroyed) for (const row of batch) if (textState.regions.includes(row)) {
                        row.status = 'error'; row.error = error?.message || '识别失败，请重试。';
                    }
                } finally {
                    textBusy = false;
                    if (!destroyed) { refreshTextPanel(); if (textState.regions.some(r => r.status === 'queued')) schedule(); }
                }
            };
            textOverlay = root.DMateGraphOverlay.mount(host, {
                instance: instance + '-text', originalUrl: options.originalUrl,
                state: textState, textOnly: true, model, graph: () => null,
                disabled: () => saving || destroyed,
                selectTextRegion: id => { textState.selectedId=id; panel.open=true; refreshTextPanel(); },
                resizeTextRegion: (id,points) => {
                    const previous=textState.regions.find(r=>r.id===id);
                    if(!previous)return;
                    textState.regions=textState.regions.map(r=>r.id===id?{...r,polygon:points.map(p=>[...p]),text:'',error:'',status:'queued'}:r);
                    if(!textState.manuallyEdited && previous.text)applyResults();
                    refreshTextPanel(); schedule();
                },
                selectionChanged: (points,irregular=false) => {
                    if (points) {
                        textState.regions.push({id:textState.nextId++, polygon:points.map(p => [...p]), irregular, status:'queued', text:''});
                        schedule();
                    } else {
                        const hadText = textState.regions.some(r => r.text?.trim());
                        textState.regions = []; clearTimeout(textTimer); textTimer = null;
                        if (!textState.manuallyEdited && hadText) applyResults();
                    }
                    refreshTextPanel();
                }
            });
            content.append(status, list, field('文字识别结果（可修改）', body), apply);
            const request = element('textarea', 'dge-text-requirements'); request.rows = 3; request.value = requirements; request.maxLength = 4000;
            request.setAttribute('aria-label', '手动输入要求（可选）'); request.placeholder = '例如：只解第（2）问，给出推导过程。';
            request.addEventListener('input', () => { requirements = request.value; options.onRequirementsChange?.(requirements); });
            content.append(field('手动输入要求（可选）', request));
            refreshTextPanel();
            if (textState.regions.some(r => r.status === 'queued')) schedule();
            return pane;
        }

        function render() {
            if (destroyed) return;
            // Native details.toggle is queued. Read the current DOM before
            // replacing it, rather than depending on that later event.
            for (const panel of container.querySelectorAll('.dge-floating-actions > details[data-panel-key]'))
                panelState[panel.dataset.panelKey] = panel.open;
            const renderVersion = ++renderSequence;
            // The editor may live in a scrollable dialog AND a scrollable
            // browser viewport. Swapping ancillary controls must not move
            // either one, even if the overlay is temporarily reparented.
            const scrollState = [];
            if (useOverlay && overlay) {
                const viewport=container.querySelector('.dge-overlay-viewport');
                if(viewport)scrollState.push([viewport,viewport.scrollTop,viewport.scrollLeft]);
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
            const retainedOverlay = useOverlay
                ? container.querySelector('.dge-overlay-host') : null;
            const retainedText = container.querySelector('.dge-text-workspace');
            if (retainedText) retainedText.remove();
            if (retainedOverlay) retainedOverlay.remove();
            else if (overlay) { overlay.destroy(); overlay = null; }
            container.replaceChildren(); container.classList.add('dmate-graph-editor');
            const top = element('div', 'dge-topline');
            // The toolbar already names its actions; keep the dialog compact.
            const undo = historyButton('撤销', ['M9 14 4 9l5-5', 'M4 9h10.5a6.5 6.5 0 0 1 0 13H11'], () => { model.undo(); });
            undo.dataset.editorUndo = 'true'; undo.disabled = saving || !model.canUndo();
            const redo = historyButton('重做', ['m15 14 5-5-5-5', 'M20 9H9.5a6.5 6.5 0 0 0 0 13H13'], () => { model.redo(); });
            redo.dataset.editorRedo = 'true'; redo.disabled = saving || !model.canRedo();
            if (!options.drawingOnly) top.append(questionChoice());
            top.append(undo, redo,
                button('清空', () => {
                    recognitionEpoch++; model.reset(); selectedNodes.clear(); selectedEdge=null; selectedGraph=false;
                    overlay?.resetInteraction(); textOverlay?.resetInteraction();
                    clearTimeout(textTimer); textTimer=null; textState.regions=[]; textState.nextId=1; textState.selectedId=null; textState.manuallyEdited=false; textState.assemblyError='';
                    refreshTextPanel?.();
                }));
            container.append(top);
            if (useOverlay && !options.drawingOnly) {
                const tabs = element('div', 'dge-tabs'); tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', '识别方式');
                for (const [key, label] of [['image', '图像识别'], ['text', '文字识别']]) {
                    const tab = button(label, () => { activeTab = key; }); tab.setAttribute('role', 'tab');
                    tab.id = instance + '-' + key + '-tab'; tab.setAttribute('aria-controls', instance + '-' + key + '-panel');
                    tab.setAttribute('aria-selected', String(activeTab === key));
                    tab.tabIndex = activeTab === key ? 0 : -1;
                    tab.addEventListener('keydown', event => {
                        if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
                        event.preventDefault(); activeTab = event.key === 'Home' ? 'image' : event.key === 'End' ? 'text' : activeTab === 'image' ? 'text' : 'image';
                        render(); container.querySelector('[aria-selected="true"]')?.focus();
                    });
                    tabs.append(tab);
                }
                container.append(tabs);
            }
            const observations = (Array.isArray(options.issues) ? options.issues : [])
                .map(issue => typeof issue === 'string' ? issue : text(issue?.message)).filter(Boolean);
            if (observations.length && !useOverlay) { const details = element('details', 'dge-observations'); details.open = true;
                details.append(element('summary', '', '识别时需留意'));
                const list = element('ul'); observations.slice(0, 64).forEach(message => list.append(element('li', '', message))); details.append(list); container.append(details); }
            const workspace = element('div', 'dge-workspace');
            if (useOverlay && !options.drawingOnly) { workspace.hidden = activeTab !== 'image'; workspace.id = instance + '-image-panel'; workspace.setAttribute('role', 'tabpanel'); workspace.setAttribute('aria-labelledby', instance + '-image-tab'); }
            if (useOverlay) {
                const host = retainedOverlay || element('section', 'dge-overlay-host');
                workspace.append(host);
                container.append(workspace);
                if (!overlay) overlay = root.DMateGraphOverlay.mount(host, {
                    instance, originalUrl: options.originalUrl, model, state: overlayState, drawingOnly: options.drawingOnly,
                    graph: () => model.getDocument().graphs.find(row => row.id === currentGraph),
                    createRegion: (points,polygon) => {
                        const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);
                        const bbox=[Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)];
                        const graphs=model.getDocument().graphs,blank=graphs.length===1&&graphs[0];
                        if(blank && !blank.vertices.length && !blank.edges.length && !blank.bbox && !blank.region_polygon){
                            currentGraph=blank.id;
                            if(polygon)model.setGraphPolygon(currentGraph,points);else model.setGraphBounds(currentGraph,bbox);
                        }else currentGraph=model.addGraph({bbox,...(polygon?{region_polygon:points}:{})});
                        selectedNodes.clear();selectedEdge=null;
                        return currentGraph;
                    },
                    resizeRegion: (id,points,polygon) => {
                        currentGraph=id; selectedNodes.clear(); selectedEdge=null; selectedGraph=true;
                        if(polygon)model.setGraphPolygon(id,points);
                        else {const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);model.setGraphBounds(id,[Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)]);}
                    },
                    disabled: () => saving || destroyed,
                    ensureGraph:()=>{if(!model.getDocument().graphs.length)currentGraph=model.addGraph();return currentGraph;},
                    selectGraph:id=>{closeFloatingPanels();propertiesVisible=true;currentGraph=id;selectedNodes.clear();selectedEdge=null;selectedGraph=true;render();},
                    clearSelection:()=>{selectedNodes.clear();selectedEdge=null;selectedGraph=false;render();},
                    edgeSelected: () => selectedEdge,
                    nodeSelected: () => selectedNodes,
                    selectEdge: id => { closeFloatingPanels();propertiesVisible=true;selectedGraph=false;selectedEdge = id; selectedNodes.clear(); render(); },
                    selectNode: id => { closeFloatingPanels();propertiesVisible=true;selectedGraph=false;selectedNodes = new Set([id]); selectedEdge = null; render(); },
                    changed: kind => {
                        if (kind === 'vertex') refreshCanvasVertex();
                        else if (kind === 'geometry') refreshDraftViews();
                        else render();
                    },
                    recognizeGraphType: async (polygon, graphId) => {
                        const epoch=recognitionEpoch;
                        if (typeof options.onRecognizeGraphType !== 'function')
                            throw new Error('当前无法自动判断箭头与权值');
                        const result = await options.onRecognizeGraphType(polygon);
                        if(epoch!==recognitionEpoch || destroyed)return {stale:true};
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
                if (graph && !options.structureOnly) {
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
            if (review) container.append(review);
            const toolbar = element('div', 'dge-toolbar');
            if (options.structureOnly && !graph) toolbar.append(button('添加图形结构', () => {
                currentGraph = model.addGraph();
            }));
            if (document.graphs.length && !options.drawingOnly) {
                toolbar.append(field('当前子图', select(document.graphs.map((row, index) => [row.id, row.name || '图 ' + (index + 1)]), currentGraph, '当前子图', value => { currentGraph = value; selectedNodes.clear(); selectedEdge = null; render(); })));
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
            if (graph) {
                if (!options.drawingOnly) toolbar.append(field('子图名称', input(graph.name, '子图名称', value => model.renameGraph(graph.id, value))));
                if (options.drawingOnly || options.structureOnly) {
                    const flags = key => typeof graph[key]==='boolean' ? graph[key]?'yes':'no' : 'unknown';
                    toolbar.append(field('图形方向', select([['no','无向'],['yes','有向']], flags('directed'), options.drawingOnly?'绘图方向':'图形方向', value => {if(value==='no'||value==='yes'){model.setGraphType(graph.id,'directed',value==='yes');render();}})));
                    toolbar.append(field('图形权值', select([['no','无权'],['yes','带权']], flags('weighted'), options.drawingOnly?'绘图权值':'图形权值', value => {if(value==='no'||value==='yes'){model.setGraphType(graph.id,'weighted',value==='yes');render();}})));
                }
            }
            container.insertBefore(toolbar, workspace);
            if (graph && !useOverlay) {
                const panels = element('div', 'dge-edit-panels'), nodes = element('section', 'dge-node-panel'), edges = element('section', 'dge-edge-panel');
                nodes.append(element('h3', '', '节点 · ' + graph.vertices.length));
                const nodeList = element('div', 'dge-node-list');
                graph.vertices.forEach((vertex, index) => nodeList.append(buildNodeRow(graph, vertex, index)));

                nodes.append(nodeList);
                const addLabel = input('', '新节点标签', null); addLabel.placeholder = '新节点标签（可留空）';
                const addRow = element('div', 'dge-inline'); addRow.append(addLabel, button('添加节点', () => model.addVertex(graph.id, addLabel.value))); nodes.append(addRow);
                nodes.append(button('全选节点', () => { selectedNodes = new Set(graph.vertices.map(vertex => vertex.id)); }), button('删除所选节点', () => {
                    if (!selectedNodes.size) throw new Error('请先勾选节点。');
                    model.deleteVertices(graph.id, [...selectedNodes]); selectedNodes.clear();
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
                    row.append(field(hasDirection(graph)?'起点':'端点一', select(nodeOptions(graph), edge.from, '边 ' + (index + 1) + (hasDirection(graph)?' 起点':' 端点一'), value => model.updateEdges(graph.id, ids, 'from', value))),
                        ...(!hasDirection(graph)?[]:[field('方向', select([['undirected', '无向 —'], ['forward', '有向 →'], ['unknown', '待确认 ?']], edge.direction, '边 ' + (index + 1) + ' 方向', value => model.updateEdges(graph.id, ids, 'direction', value)))]),
                        field(hasDirection(graph)?'终点':'端点二', select(nodeOptions(graph), edge.to, '边 ' + (index + 1) + (hasDirection(graph)?' 终点':' 端点二'), value => model.updateEdges(graph.id, ids, 'to', value))),
                        ...(graph.weighted===false?[]:[field('权重', input(edge.weight, '边 ' + (index + 1) + ' 权重', value => model.updateEdges(graph.id, ids, 'weight', weightValue(value))))]));
                    if (!individually) { const count = input(group.length, '边 ' + (index + 1) + ' 相同边数量', value => {
                            const beforeIds = new Set(model.getDocument().graphs.find(row => row.id === graph.id).edges.map(row => row.id));
                            model.setEdgeCount(graph.id, ids, Number(value));
                            const latest = model.getDocument().graphs.find(row => row.id === graph.id).edges;
                            ids.splice(0, ids.length, ...latest.filter(row => ids.includes(row.id) || !beforeIds.has(row.id)).map(row => row.id));
                        }, 'number'); count.min = '1'; count.max = '50'; count.required = true;
                        const quantity = field('相同边数量', count); quantity.append(button('应用数量', () => model.setEdgeCount(graph.id, ids, Number(count.value)))); row.append(quantity); }
                    if(hasDirection(graph))row.append(button('交换端点 / 反向', () => model.reverseEdges(graph.id, ids)));
                    const attributes = element('details', 'dge-edge-attributes'); attributes.append(element('summary', '', '边名、线型与颜色'));
                    attributes.append(field('边名', input(edge.edge_label, '边 ' + (index + 1) + ' 边名', value => model.updateEdges(graph.id, ids, 'edge_label', value || null))),
                        field('线型', select([['', '未标特殊线型'], ['solid', '实线'], ['dashed', '虚线'], ['dotted', '点线'], ['unknown', '尚不确定']], edge.style ?? '', '边 ' + (index + 1) + ' 线型', value => model.updateEdges(graph.id, ids, 'style', value || null))),
                        field('颜色', input(edge.color, '边 ' + (index + 1) + ' 颜色', value => model.updateEdges(graph.id, ids, 'color', value || null))));
                    row.append(attributes, button('删除边', () => model.deleteEdges(graph.id, ids), 'dge-danger')); edgeList.append(row);
                });
                edges.append(edgeList, button('添加边 / 自环', () => { const first = [...selectedNodes][0] || graph.vertices[0]?.id || '', second = [...selectedNodes][1] || graph.vertices[1]?.id || first;
                    selectedEdge = model.addEdge(graph.id, { from: first, to: second, direction: graph.edges.some(edge => edge.direction === 'forward') ? 'forward' : 'undirected' }); }));
                if (selectedEdge && document.graphs.length > 1) {
                    const move = element('details', 'dge-edge-move'); move.append(element('summary', '', '调整所选边的子图归属'));
                    const endpointFields = element('div', 'dge-inline'); let targetFrom, targetTo;
                    const target = select(graphOptions(document, graph.id), '', '边移动目标', null);
                    target.addEventListener('change', () => {
                        endpointFields.replaceChildren(); const destination = document.graphs.find(row => row.id === target.value); if (!destination) return;
                        const first = hasDirection(destination)?'起点':'端点一', second = hasDirection(destination)?'终点':'端点二';
                        targetFrom = select(nodeOptions(destination), '', '移动后' + first, null); targetTo = select(nodeOptions(destination), '', '移动后' + second, null);
                        endpointFields.append(field('目标图' + first, targetFrom), field('目标图' + second, targetTo));
                    });
                    move.append(target, endpointFields, button('移动这条边', () => model.moveEdges(graph.id, target.value, [selectedEdge], targetFrom?.value, targetTo?.value))); edges.append(move);
                }
                panels.append(nodes, edges);
                container.append(panels);
            }
            if(useOverlay){
                const rack=element('div','dge-floating-actions');workspace.append(rack);
                const floating=(node,title,key,position)=>{
                    if(!node)return;
                    const panel=element('details','dge-float-panel '+position);panel.dataset.panelKey=key;panel.open=Boolean(panelState[key]);
                    const content=element('div','dge-float-content');content.append(node);
                    const launcher=element('summary','',title);
                    const closeOtherPanels = () => {
                        for (const other of rack.children) if (other !== panel) {
                            other.open = false; panelState[other.dataset.panelKey] = false;
                        }
                    };
                    launcher.addEventListener('click', event => {
                        // Apply both intent and DOM state during the click.
                        // A select change can redraw before native toggle runs.
                        event.preventDefault(); event.stopPropagation();
                        if (saving || destroyed) return;
                        const nextOpen = !panel.open;
                        if (nextOpen) closeOtherPanels();
                        panelState[key] = nextOpen; panel.open = nextOpen;
                    });
                    panel.append(launcher,content);
                    panel.addEventListener('toggle', () => {
                        // Detached details can still deliver queued events.
                        // Their obsolete state must not close a new popover.
                        if (destroyed || renderVersion !== renderSequence || !panel.isConnected || !container.contains(panel)) return;
                        panelState[key] = panel.open;
                        if (panel.open) closeOtherPanels();
                    });rack.append(panel);
                };
                floating(toolbar,options.drawingOnly ? '绘图设置' : '子图管理','graphs','dge-float-graphs');
                if(review)floating(review,options.drawingOnly ? '图形信息' : '识别结果','results','dge-float-results');
                const textPane = retainedText || (activeTab === 'text' ? buildTextWorkspace() : null);
                if (textPane) {
                    textPane.hidden = activeTab !== 'text'; container.append(textPane);
                    const body = textPane.querySelector('.dge-text-body');
                    body.value = document.body_text; body.disabled = saving;
                    textPane.querySelector('.dge-text-requirements').disabled = saving;
                }
            }
            const status = element('div', 'dge-status'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite'); status.textContent = notice; container.append(status);
            if (!options.drawingOnly) {
                const confirmRow = element('div', 'dge-footer');
                // The dialog header contains the close button; footer is save only.
                const actions = element('div', 'dge-actions');
                const confirm = button(saving ? '正在保存…' : '保存并确认', async () => {
                    if (textState.regions?.some(r => ['queued','recognizing'].includes(r.status))) { notice = '文字正在识别，请等待完成后保存。'; refreshDraftViews(); return; }
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
            }
            for (const [scroller, top, left] of scrollState) {
                scroller.scrollTop = top;
                scroller.scrollLeft = left;
            }
        }
        unsubscribe = model.subscribe(document => { refreshReview(document); options.onChange?.(document); });
        render();
        return { getDocument: model.getDocument, getIsQuestion: () => isQuestion,
            validate: model.validate, model, refresh: refreshDraftViews, getDrawingSvg: () => overlay?.getDrawingSvg?.() || null,
            destroy() { destroyed = true; clearTimeout(textTimer); unsubscribe(); overlay?.destroy(); textOverlay?.destroy(); container.replaceChildren(); container.classList.remove('dmate-graph-editor'); } };
    }
    const api = { mount, createModel, importDocument, validateDocument, groupEdges };
    root.DMateGraphEditor = api;
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
