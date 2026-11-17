/* A question view contains recorded course relations, never invented links. */
(function (root) {
    'use strict';
    const MAX_CONNECTOR_EDGES = 3;

    function build(allNodes, context = {}) {
        const nodes = [], byName = new Map(), byId = new Map();
        for (const node of Array.isArray(allNodes) ? allNodes : []) {
            if (!node || typeof node.id !== 'string' || !node.id
                || typeof node.name !== 'string' || !node.name
                || byId.has(node.id) || byName.has(node.name)) continue;
            nodes.push(node); byName.set(node.name, node); byId.set(node.id, node);
        }
        const order = new Map(nodes.map((node, index) => [node.id, index]));
        const adjacent = new Map(nodes.map(node => [node.id, new Set()]));
        const prerequisites = new Map(nodes.map(node => [node.id, new Set()]));
        const edges = [];
        for (const node of nodes) {
            for (const name of Array.isArray(node.prerequisites) ? node.prerequisites : []) {
                const previous = byName.get(name);
                if (!previous || prerequisites.get(node.id).has(previous.id)) continue;
                prerequisites.get(node.id).add(previous.id);
                edges.push({from:previous.id, to:node.id});
                adjacent.get(previous.id).add(node.id);
                adjacent.get(node.id).add(previous.id);
            }
        }
        const neighbors = new Map([...adjacent].map(([id, values]) => [id,
            [...values].sort((a, b) => order.get(a) - order.get(b))]));
        const resolve = values => new Set((Array.isArray(values) ? values : [])
            .filter(value => typeof value === 'string')
            .map(value => byName.get(value.trim()) || byId.get(value.trim()))
            .filter(Boolean).map(node => node.id));
        const focus = resolve(context?.focusPoints), knowledge = resolve(context?.knowledgePoints);
        const seeds = new Set([...focus, ...knowledge, ...resolve(context?.relatedPoints),
            ...resolve(context?.knowledgePath), ...resolve(context?.prerequisitePoints)]);
        const seedIds = nodes.filter(node => seeds.has(node.id)).map(node => node.id);
        if (!seedIds.length) return {nodes:[], edges:[], seedIds:[], connectorIds:[], components:[]};
        const selected = new Set(seedIds);

        // One course step gives context without expanding an entire module.
        for (const id of seedIds) for (const previous of prerequisites.get(id)) selected.add(previous);
        const primary = focus.size ? focus : knowledge;
        for (const edge of edges) if (primary.has(edge.from)) selected.add(edge.to);

        // Shortest paths may use either direction while searching. The output
        // preserves each original prerequisite direction, including shared roots.
        const shortest = (start, target) => {
            const queue = [[start]], visited = new Set([start]);
            for (let index = 0; index < queue.length; index++) {
                const path = queue[index];
                if (path.length - 1 >= MAX_CONNECTOR_EDGES) continue;
                for (const next of neighbors.get(path[path.length - 1])) {
                    if (visited.has(next)) continue;
                    const extended = [...path, next];
                    if (next === target) return extended;
                    visited.add(next); queue.push(extended);
                }
            }
            return null;
        };
        const parent = new Map();
        const find = id => {
            if (!parent.has(id)) parent.set(id, id);
            let current = id;
            while (parent.get(current) !== current) current = parent.get(current);
            while (id !== current) { const previous = parent.get(id); parent.set(id, current); id = previous; }
            return current;
        };
        const join = (left, right) => {
            const a = find(left), b = find(right);
            if (a !== b) parent.set(b, a);
        };
        const joinSelected = () => {
            for (const edge of edges) if (selected.has(edge.from) && selected.has(edge.to)) join(edge.from, edge.to);
        };
        joinSelected();
        const paths = [];
        for (let left = 0; left < seedIds.length; left++) {
            for (let right = left + 1; right < seedIds.length; right++) {
                if (find(seedIds[left]) === find(seedIds[right])) continue;
                const path = shortest(seedIds[left], seedIds[right]);
                if (path) paths.push({left, right, path});
            }
        }
        paths.sort((a, b) => a.path.length - b.path.length || a.left - b.left || a.right - b.right);
        const connectors = new Set();
        for (const {path} of paths) {
            if (find(path[0]) === find(path[path.length - 1])) continue;
            for (const id of path) {
                if (!selected.has(id)) connectors.add(id);
                selected.add(id);
            }
            // Joining all present edges also connects a path's intermediate
            // node to any third relevant branch already shown in the question.
            joinSelected();
        }
        const components = new Map();
        for (const node of nodes) if (selected.has(node.id)) {
            const key = find(node.id);
            if (!components.has(key)) components.set(key, []);
            components.get(key).push(node.id);
        }
        return {
            nodes:nodes.filter(node => selected.has(node.id)),
            edges:edges.filter(edge => selected.has(edge.from) && selected.has(edge.to)),
            seedIds,
            connectorIds:nodes.filter(node => connectors.has(node.id)).map(node => node.id),
            components:[...components.values()]
        };
    }

    const api = Object.freeze({build, MAX_CONNECTOR_EDGES});
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    root.DMateQuestionKnowledgeGraph = api;
})(typeof window === 'undefined' ? globalThis : window);
