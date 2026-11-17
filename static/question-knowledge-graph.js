/* A question graph contains only concepts and relations evidenced by that question. */
(function (root) {
    'use strict';

    function build(allNodes, context = {}) {
        const empty = () => ({nodes:[], edges:[], seedIds:[], connectorIds:[], components:[]});
        const graph = context?.questionGraph;
        if (!graph || graph.version !== 1 || !Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) return empty();

        const nodes = [], byId = new Map(), names = new Set();
        for (const node of Array.isArray(allNodes) ? allNodes : []) {
            if (!node || typeof node.id !== 'string' || !node.id
                || typeof node.name !== 'string' || !node.name
                || byId.has(node.id) || names.has(node.name)) continue;
            nodes.push(node); byId.set(node.id, node); names.add(node.name);
        }
        // Source text is supplied by the bound question/answer, never by the
        // graph's own claimed sources. Old course-derived tags are not evidence.
        const sourceText = {
            question:typeof context?.questionText === 'string' ? context.questionText : '',
            solution:typeof context?.solutionText === 'string' ? context.solutionText : ''
        };
        const evidenced = records => Array.isArray(records) && records.some(record =>
            record && (record.source === 'question' || record.source === 'solution')
            && typeof record.quote === 'string' && record.quote.trim()
            && sourceText[record.source].includes(record.quote));
        const selected = new Set(graph.nodes.filter(record => record && byId.has(record.id)
            && evidenced(record.evidence)).map(record => record.id));
        if (!selected.size) return empty();

        const order = new Map(nodes.map((node, index) => [node.id, index]));
        const edges = [], seenEdges = new Map();
        for (const edge of graph.edges) {
            if (!edge || edge.from === edge.to || !selected.has(edge.from) || !selected.has(edge.to)
                || !evidenced(edge.evidence)) continue;
            if (!seenEdges.has(edge.from)) seenEdges.set(edge.from, new Set());
            if (seenEdges.get(edge.from).has(edge.to)) continue;
            seenEdges.get(edge.from).add(edge.to);
            edges.push({from:edge.from, to:edge.to});
        }
        edges.sort((a, b) => order.get(a.from) - order.get(b.from) || order.get(a.to) - order.get(b.to));

        const incoming = new Map([...selected].map(id => [id, []]));
        const parent = new Map([...selected].map(id => [id, id]));
        const find = id => {
            let current = id;
            while (parent.get(current) !== current) current = parent.get(current);
            while (id !== current) { const previous = parent.get(id); parent.set(id, current); id = previous; }
            return current;
        };
        for (const edge of edges) {
            incoming.get(edge.to).push(byId.get(edge.from).name);
            const previous = find(edge.from), next = find(edge.to);
            if (previous !== next) parent.set(next, previous);
        }
        const selectedNodes = nodes.filter(node => selected.has(node.id));
        const components = new Map();
        for (const node of selectedNodes) {
            const key = find(node.id);
            if (!components.has(key)) components.set(key, []);
            components.get(key).push(node.id);
        }
        return {
            // Every renderer, sidebar and export receives this question's
            // relationships, including when both concepts share a course edge.
            nodes:selectedNodes.map(node => ({...node, prerequisites:incoming.get(node.id)})),
            edges,
            seedIds:selectedNodes.map(node => node.id),
            connectorIds:[],
            components:[...components.values()]
        };
    }

    const api = Object.freeze({build});
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    root.DMateQuestionKnowledgeGraph = api;
})(typeof window === 'undefined' ? globalThis : window);
