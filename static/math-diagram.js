(function (root) {
    'use strict';

    const VERSION = '3.31.0';
    const SOURCE = {
        url: '/static/vendor/viz-js-' + VERSION + '/viz-global.js',
        integrity: 'sha256-yeCzEPmIORDgHGYFS0i3/0vj2GlRQRFmNecrCvFSaS4='
    };
    let vizPromise = null;
    let instancePromise = null;
    const ERRORS_EN = {
        '当前环境无法加载数学布局引擎。': 'The mathematical layout engine is unavailable in this environment.',
        '数学自动布局组件未能初始化，请刷新后重试。': 'The diagram layout engine could not initialize. Refresh and try again.',
        '数学自动布局组件暂时无法加载，请刷新后重试。': 'The diagram layout engine could not load. Refresh and try again.',
        '当前原型只接受一幅数学图。': 'Generate one mathematical diagram at a time.',
        '数学图结构为空或无法读取。': 'The mathematical diagram is empty or invalid.',
        '数学布局引擎没有返回坐标。': 'The layout engine did not return vertex positions.',
        '数学图自动布局失败，请调整绘图要求。': 'The diagram could not be laid out. Refine the request and try again.',
        '自动布局结果不完整，未能定位全部顶点。': 'The layout is incomplete: some vertices have no position.',
        '数学图生成服务返回内容无效，请重试。': 'The diagram generator returned an invalid response. Please try again.',
        '数学图生成失败，请重试。': 'The mathematical diagram could not be generated. Please try again.'
    };

    function localizedError(error, language) {
        if (error?.name !== 'AbortError' && String(language || '').toLowerCase().startsWith('en')
            && Object.prototype.hasOwnProperty.call(ERRORS_EN, error?.message)) error.message = ERRORS_EN[error.message];
        return error;
    }

    function loadViz() {
        if (root.Viz && typeof root.Viz.instance === 'function') return Promise.resolve(root.Viz);
        if (vizPromise) return vizPromise;
        vizPromise = new Promise((resolve, reject) => {
            const doc = root.document;
            if (!doc) { reject(new Error('当前环境无法加载数学布局引擎。')); return; }
            const script = doc.createElement('script');
            script.src = SOURCE.url;
            script.integrity = SOURCE.integrity;
            script.crossOrigin = 'anonymous';
            script.async = true;
            script.onload = () => {
                if (root.Viz && typeof root.Viz.instance === 'function') resolve(root.Viz);
                else {
                    script.remove();
                    vizPromise = null;
                    reject(new Error('数学自动布局组件未能初始化，请刷新后重试。'));
                }
            };
            script.onerror = () => {
                script.remove();
                vizPromise = null;
                reject(new Error('数学自动布局组件暂时无法加载，请刷新后重试。'));
            };
            doc.head.appendChild(script);
        });
        return vizPromise;
    }

    async function getVizInstance() {
        const Viz = await loadViz();
        if (!instancePromise) {
            instancePromise = Viz.instance().catch(error => {
                instancePromise = null;
                throw error;
            });
        }
        return instancePromise;
    }

    function abortError() {
        const error = new Error('数学图生成已取消。');
        error.name = 'AbortError';
        return error;
    }

    function quote(value) {
        return '"' + String(value == null ? '' : value)
            .replace(/\\/g, '\\\\')
            .replace(/"/g, '\\"')
            .replace(/\r/g, '')
            .replace(/\n/g, '\\n') + '"';
    }

    function graphFor(document) {
        if (!document || !Array.isArray(document.graphs) || document.graphs.length !== 1) {
            throw new Error('当前原型只接受一幅数学图。');
        }
        const graph = document.graphs[0];
        if (!graph || !Array.isArray(graph.vertices) || !Array.isArray(graph.edges) || !graph.vertices.length) {
            throw new Error('数学图结构为空或无法读取。');
        }
        return graph;
    }

    function engineFor(kind, graph) {
        if (kind === 'hasse') return 'dot';
        if (kind === 'cyclic_cayley') return 'circo';
        if (kind === 'zero_divisor_graph') return 'neato';
        return graph.directed ? 'dot' : 'neato';
    }

    function buildDot(document, kind) {
        const graph = graphFor(document);
        const directed = kind === 'hasse' || graph.directed === true;
        const keyword = directed ? 'digraph' : 'graph';
        const connector = directed ? '->' : '--';
        const lines = [
            keyword + ' DMate {',
            'graph [overlap=false, splines=true, nodesep=0.48, ranksep=0.68, pad=0.22, margin=0.12, bgcolor="transparent"];',
            'node [shape=circle, fixedsize=true, width=0.46, height=0.46, style="filled", fillcolor="#ffffff", color="#64748b", penwidth=1.25, fontname="Arial", fontsize=12, margin=0.03];',
            'edge [color="#64748b", penwidth=1.25, arrowsize=0.68, fontname="Arial", fontsize=10];'
        ];
        if (kind === 'hasse') {
            lines.push('graph [rankdir=BT];', 'edge [arrowhead=none];');
        } else if (directed) {
            lines.push('graph [rankdir=LR];');
        }
        for (const vertex of graph.vertices) {
            lines.push(quote(vertex.id) + ' [label=' + quote(vertex.label == null ? vertex.display_label : vertex.label) + '];');
        }
        for (const [index, edge] of graph.edges.entries()) {
            const labelParts = [];
            if (edge.edge_label != null && String(edge.edge_label).trim()) labelParts.push(String(edge.edge_label));
            if (edge.weight != null && String(edge.weight).trim()) labelParts.push(String(edge.weight));
            const attrs = ['id=' + quote(edge.id ?? 'layout-edge-' + index)];
            if (labelParts.length) attrs.push('label=' + quote(labelParts.join(' · ')));
            lines.push(quote(edge.from) + ' ' + connector + ' ' + quote(edge.to) + ' [' + attrs.join(', ') + '];');
        }
        lines.push('}');
        return lines.join('\n');
    }

    function parsePlain(output) {
        if (typeof output !== 'string') throw new Error('数学布局引擎没有返回坐标。');
        const nodes = new Map();
        for (const line of output.split(/\r?\n/)) {
            if (!line.startsWith('node ')) continue;
            const match = /^node\s+("(?:\\.|[^"\\])*"|\S+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)/.exec(line);
            if (!match) continue;
            const x = Number(match[2]), y = Number(match[3]);
            const id = match[1].startsWith('"')
                ? match[1].slice(1, -1).replace(/\\(["\\])/g, '$1') : match[1];
            if (Number.isFinite(x) && Number.isFinite(y)) nodes.set(id, [x, y]);
        }
        return nodes;
    }

    function parseLayout(output) {
        let layout;
        try { layout = JSON.parse(output); }
        catch (_) { throw new Error('数学布局引擎没有返回坐标。'); }
        const positions = new Map(), curves = new Map();
        for (const node of layout.objects || []) {
            const point = String(node.pos || '').split(',').map(Number);
            if (typeof node.name === 'string' && point.length === 2 && point.every(Number.isFinite)) positions.set(node.name, point);
        }
        for (const edge of layout.edges || []) {
            const paths = (edge._draw_ || []).filter(op => ['b', 'B'].includes(op.op)
                && Array.isArray(op.points) && op.points.length >= 4 && (op.points.length - 1) % 3 === 0
                && op.points.every(point => Array.isArray(point) && point.length === 2 && point.every(Number.isFinite)))
                .map(op => op.points);
            if (typeof edge.id === 'string' && paths.length) curves.set(edge.id, paths);
        }
        return {positions, curves};
    }

    function sampleCurves(curves, start, end) {
        const count = curves.reduce((total, curve) => total + (curve.length - 1) / 3, 0);
        const steps = Math.max(1, Math.min(12, Math.floor(124 / count)));
        const points = [start];
        for (const curve of curves) for (let i = 0; i + 3 < curve.length; i += 3) {
            for (let step = 0; step <= steps; step++) {
                const t = step / steps, u = 1 - t;
                points.push([0, 1].map(axis => u ** 3 * curve[i][axis] + 3 * u ** 2 * t * curve[i + 1][axis]
                    + 3 * u * t ** 2 * curve[i + 2][axis] + t ** 3 * curve[i + 3][axis]));
            }
        }
        points.push(end);
        // The existing editor/document schema accepts at most 128 path points.
        if (points.length <= 128) return points;
        return Array.from({length:128}, (_, i) => points[Math.round(i * (points.length - 1) / 127)]);
    }

    async function layoutDocument(document, kind, vizInstance, signal) {
        if (signal?.aborted) throw abortError();
        const graph = graphFor(document);
        const viz = vizInstance || await getVizInstance();
        if (signal?.aborted) throw abortError();
        const engine = engineFor(kind, graph);
        const result = viz.render(buildDot(document, kind), {format: 'json', engine});
        if (signal?.aborted) throw abortError();
        if (!result || result.status !== 'success') {
            const detail = Array.isArray(result && result.errors)
                ? result.errors.map(error => error && error.message ? error.message : String(error)).join('；') : '';
            throw new Error(detail || '数学图自动布局失败，请调整绘图要求。');
        }
        const {positions, curves} = parseLayout(result.output);
        if (positions.size !== graph.vertices.length || graph.vertices.some(vertex => !positions.has(vertex.id))) {
            throw new Error('自动布局结果不完整，未能定位全部顶点。');
        }
        const points = [...positions.values(), ...[...curves.values()].flat(2)];
        const xs = points.map(point => point[0]), ys = points.map(point => point[1]);
        const minX = Math.min(...xs), maxX = Math.max(...xs);
        const minY = Math.min(...ys), maxY = Math.max(...ys);
        const rangeX = maxX - minX, rangeY = maxY - minY;
        const copy = JSON.parse(JSON.stringify(document));
        const target = copy.graphs[0];
        const span = Math.max(rangeX, rangeY);
        const scale = span < 1e-8 ? 0 : 0.82 / span;
        const centerX = (minX + maxX) / 2, centerY = (minY + maxY) / 2;
        const normalize = point => scale ? [0.5 + (point[0] - centerX) * scale, 0.5 - (point[1] - centerY) * scale] : [0.5, 0.5];
        for (const vertex of target.vertices) {
            [vertex.x, vertex.y] = normalize(positions.get(vertex.id));
        }
        for (const [index, edge] of target.edges.entries()) {
            const path = curves.get(String(edge.id ?? 'layout-edge-' + index));
            if (path) edge.path = sampleCurves(path, positions.get(edge.from), positions.get(edge.to)).map(normalize);
        }
        return {document: copy, engine};
    }

    async function generate(requirement, language, signal) {
        try {
            if (signal?.aborted) throw abortError();
            const response = await root.fetch('/drawing/generate', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({requirement, language}),
                signal
            });
            let result;
            try { result = await response.json(); }
            catch (_) { throw new Error('数学图生成服务返回内容无效，请重试。'); }
            if (!result || typeof result !== 'object' || Array.isArray(result)) {
                throw new Error('数学图生成服务返回内容无效，请重试。');
            }
            if (!response.ok || result.ok !== true || !result.document) {
                throw new Error(result.error || '数学图生成失败，请重试。');
            }
            if (signal?.aborted) throw abortError();
            const layout = await layoutDocument(result.document, result.kind, undefined, signal);
            if (signal?.aborted) throw abortError();
            return {...result, document: layout.document, layout_engine: layout.engine};
        } catch (error) { throw localizedError(error, language); }
    }

    const api = {loadViz, buildDot, parsePlain, layoutDocument, generate, engineFor};
    root.DMateMathDiagram = api;
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
