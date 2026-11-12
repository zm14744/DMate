(function (root) {
    'use strict';

    const VERSION = '3.31.0';
    const SOURCES = [
        {
            url: 'https://cdn.jsdelivr.net/gh/siyuan-note/siyuan@be17ed1e0510bb6371cb8a162e16898a697fa118/app/stage/protyle/js/graphviz/viz.js',
            integrity: 'sha256-yeCzEPmIORDgHGYFS0i3/0vj2GlRQRFmNecrCvFSaS4='
        },
        {
            url: 'https://github.com/mdaines/viz-js/releases/download/release-viz-' + VERSION + '/viz-global.js',
            integrity: 'sha256-yeCzEPmIORDgHGYFS0i3/0vj2GlRQRFmNecrCvFSaS4='
        }
    ];
    let vizPromise = null;

    function loadViz() {
        if (root.Viz && typeof root.Viz.instance === 'function') return Promise.resolve(root.Viz);
        if (vizPromise) return vizPromise;
        vizPromise = new Promise((resolve, reject) => {
            const doc = root.document;
            if (!doc) { reject(new Error('当前环境无法加载数学布局引擎。')); return; }
            let index = 0;
            const next = () => {
                if (index >= SOURCES.length) {
                    vizPromise = null;
                    reject(new Error('数学自动布局组件暂时无法加载，请检查网络后重试。'));
                    return;
                }
                const script = doc.createElement('script');
                const source = SOURCES[index++];
                script.src = source.url;
                script.integrity = source.integrity;
                script.crossOrigin = 'anonymous';
                script.async = true;
                script.onload = () => {
                    if (root.Viz && typeof root.Viz.instance === 'function') resolve(root.Viz);
                    else { script.remove(); next(); }
                };
                script.onerror = () => { script.remove(); next(); };
                doc.head.appendChild(script);
            };
            next();
        });
        return vizPromise;
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
        for (const edge of graph.edges) {
            const labelParts = [];
            if (edge.edge_label != null && String(edge.edge_label).trim()) labelParts.push(String(edge.edge_label));
            if (edge.weight != null && String(edge.weight).trim()) labelParts.push(String(edge.weight));
            const attrs = labelParts.length ? ' [label=' + quote(labelParts.join(' · ')) + ']' : '';
            lines.push(quote(edge.from) + ' ' + connector + ' ' + quote(edge.to) + attrs + ';');
        }
        lines.push('}');
        return lines.join('\n');
    }

    function parsePlain(output) {
        if (typeof output !== 'string') throw new Error('数学布局引擎没有返回坐标。');
        const nodes = new Map();
        for (const line of output.split(/\r?\n/)) {
            if (!line.startsWith('node ')) continue;
            const match = /^node\s+(\S+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)/.exec(line);
            if (!match) continue;
            const x = Number(match[2]), y = Number(match[3]);
            if (Number.isFinite(x) && Number.isFinite(y)) nodes.set(match[1], [x, y]);
        }
        return nodes;
    }

    async function layoutDocument(document, kind, vizInstance) {
        const graph = graphFor(document);
        const viz = vizInstance || await (await loadViz()).instance();
        const engine = engineFor(kind, graph);
        const result = viz.render(buildDot(document, kind), {format: 'plain', engine});
        if (!result || result.status !== 'success') {
            const detail = Array.isArray(result && result.errors) ? result.errors.join('；') : '';
            throw new Error(detail || '数学图自动布局失败，请调整绘图要求。');
        }
        const positions = parsePlain(result.output);
        if (positions.size !== graph.vertices.length || graph.vertices.some(vertex => !positions.has(vertex.id))) {
            throw new Error('自动布局结果不完整，未能定位全部顶点。');
        }
        const points = [...positions.values()];
        const xs = points.map(point => point[0]), ys = points.map(point => point[1]);
        const minX = Math.min(...xs), maxX = Math.max(...xs);
        const minY = Math.min(...ys), maxY = Math.max(...ys);
        const rangeX = maxX - minX, rangeY = maxY - minY;
        const copy = JSON.parse(JSON.stringify(document));
        const target = copy.graphs[0];
        for (const vertex of target.vertices) {
            const point = positions.get(vertex.id);
            vertex.x = rangeX < 1e-8 ? 0.5 : 0.09 + (point[0] - minX) / rangeX * 0.82;
            vertex.y = rangeY < 1e-8 ? 0.5 : 0.09 + (maxY - point[1]) / rangeY * 0.82;
        }
        return {document: copy, engine};
    }

    async function generate(requirement, language, signal) {
        const response = await root.fetch('/drawing/generate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({requirement, language}),
            signal
        });
        let result;
        try { result = await response.json(); }
        catch (_) { throw new Error('数学图生成服务返回内容无效，请重试。'); }
        if (!response.ok || result.ok !== true || !result.document) {
            throw new Error(result.error || '数学图生成失败，请重试。');
        }
        const layout = await layoutDocument(result.document, result.kind);
        return {...result, document: layout.document, layout_engine: layout.engine};
    }

    const api = {loadViz, buildDot, parsePlain, layoutDocument, generate, engineFor};
    root.DMateMathDiagram = api;
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
