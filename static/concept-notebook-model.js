(function (root) {
    'use strict';
    const LIMITS = { notes: 100, title: 160, content: 6000, characters: 180000 };
    const copy = value => JSON.parse(JSON.stringify(value));
    const object = value => value && typeof value === 'object' && !Array.isArray(value);
    const identifier = value => typeof value === 'string' && value.length > 0 && value.length <= 80
        && /^[A-Za-z0-9_.:-]+$/.test(value) && !['__proto__', 'prototype', 'constructor'].includes(value);
    const timestamp = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
    const empty = () => ({ notes: [], deleted: {} });
    const contentKey = note => JSON.stringify([note.title, note.content]);
    function note(value) {
        if (!object(value) || !identifier(value.id) || typeof value.title !== 'string'
            || value.title.length > LIMITS.title || typeof value.content !== 'string'
            || value.content.length > LIMITS.content || !timestamp(value.updatedAt)) return null;
        return { id: value.id, title: value.title, content: value.content, updatedAt: value.updatedAt };
    }
    function hash(text) {
        let a = 2166136261, b = 2246822519;
        for (let i = 0; i < text.length; i++) {
            a = Math.imul(a ^ text.charCodeAt(i), 16777619);
            b = Math.imul(b ^ text.charCodeAt(i), 3266489917);
        }
        return (a >>> 0).toString(16).padStart(8, '0') + (b >>> 0).toString(16).padStart(8, '0');
    }
    function combine(states) {
        const deleted = {}, grouped = new Map(), byId = new Map();
        for (const state of states) {
            if (object(state?.deleted)) for (const [id, at] of Object.entries(state.deleted)) {
                if (identifier(id) && timestamp(at)) deleted[id] = Math.max(at, deleted[id] ?? 0);
            }
            if (Array.isArray(state?.notes)) for (const raw of state.notes) {
                const row = note(raw);
                if (!row) continue;
                if (!grouped.has(row.id)) grouped.set(row.id, []);
                grouped.get(row.id).push(row);
            }
        }
        const pendingConflicts = [];
        for (const id of [...grouped.keys()].sort()) {
            const rows = grouped.get(id).sort((a, b) => b.updatedAt - a.updatedAt
                || (contentKey(a) < contentKey(b) ? -1 : contentKey(a) > contentKey(b) ? 1 : 0));
            const newest = rows[0];
            // A deliberate newer edit/Undo beats an old deletion. Equal-time
            // deletion wins, so a stale device cannot resurrect a removed note.
            if (deleted[id] !== undefined && deleted[id] >= newest.updatedAt) continue;
            byId.set(id, newest);
            const seen = new Set([contentKey(newest)]);
            for (const row of rows.slice(1)) {
                const key = contentKey(row);
                if (row.updatedAt !== newest.updatedAt || seen.has(key)) continue;
                seen.add(key);
                pendingConflicts.push({ ...row, id: id.slice(0, 48) + '-sync-' + hash(id + '\n' + key) });
            }
        }
        // Same-time edits keep a deterministic winner AND a full-text copy.
        // Never cut a cross-device union to 100 rows or truncate original text.
        for (const row of pendingConflicts) {
            if (deleted[row.id] !== undefined && deleted[row.id] >= row.updatedAt) continue;
            const occupied = byId.get(row.id);
            if (!occupied || contentKey(occupied) === contentKey(row)) {
                if (!occupied || row.updatedAt > occupied.updatedAt) byId.set(row.id, row);
                continue;
            }
            let index = 2, id;
            do { id = row.id.slice(0, 70) + '-' + index++; }
            while (byId.has(id) && contentKey(byId.get(id)) !== contentKey(row));
            if (deleted[id] === undefined || deleted[id] < row.updatedAt) byId.set(id, { ...row, id });
        }
        return { notes: [...byId.values()].sort((a, b) => b.updatedAt - a.updatedAt
            || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)), deleted };
    }
    function normalize(value) { return combine([object(value) ? value : empty()]); }
    function merge(left, right) { return combine([left, right]); }
    function validate(value, options = {}) {
        if (!object(value) || !Array.isArray(value.notes) || !object(value.deleted))
            throw new Error('笔记数据格式无效，请重新打开笔记本。');
        const ids = new Set();
        for (const raw of value.notes) {
            const row = note(raw);
            if (!row || ids.has(row.id)) throw new Error('笔记内容或编号无效，请检查后重试。');
            ids.add(row.id);
        }
        for (const [id, at] of Object.entries(value.deleted)) {
            if (!identifier(id) || !timestamp(at)) throw new Error('笔记删除记录无效，请重新打开笔记本。');
        }
        if (!options.allowOverCapacity && value.notes.length > LIMITS.notes) throw new Error('笔记本最多保存100条概念，请先整理或删除一些笔记。');
        if (!options.allowOverCapacity && value.notes.reduce((total, row) => total + row.title.length + row.content.length, 0) > LIMITS.characters)
            throw new Error('笔记内容已超过18万字，请先整理或删除一些笔记。');
        return normalize(value);
    }
    const api = { LIMITS, empty, normalize, merge, validate, copy };
    root.DMateConceptNotebookModel = api;
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
