/* Guest data belongs to one tab/app launch: reload keeps it, a new tab does not. */
(function (root) {
    'use strict';
    const KEY = 'dmate:guest-tab:v1';
    const MAX_CHARS = 4 * 1024 * 1024;
    const launch = String(root.__DMATE_NATIVE_GUEST_SESSION__
        || /\bDMateGuestSession\/([A-Za-z0-9-]{16,80})\b/.exec(root.navigator?.userAgent || '')?.[1] || '');
    const prefix = 'dmate-guest-tab:';
    let tab = String(root.name || '');
    if (!tab.startsWith(prefix)) {
        tab = prefix + (root.crypto?.randomUUID?.() || Date.now().toString(36) + Math.random().toString(36).slice(2));
        root.name = tab;
    }
    const secret = () => {
        const bytes = new Uint8Array(32);
        if (root.crypto?.getRandomValues) root.crypto.getRandomValues(bytes);
        else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
        return btoa(String.fromCharCode(...bytes));
    };
    let state = {version:1, tab, launch, owner:'', secret:secret(), data:{}}, generation = 0;
    const clone = value => value == null ? value : JSON.parse(JSON.stringify(value));
    function store() {
        try {
            const raw = JSON.stringify(state);
            if (raw.length > MAX_CHARS) return false;
            root.sessionStorage.setItem(KEY, raw);
            return true;
        } catch (_) { return false; }
    }
    try {
        const saved = JSON.parse(root.sessionStorage.getItem(KEY) || 'null');
        if (saved?.version === 1 && saved.tab === tab && saved.launch === launch
            && typeof saved.owner === 'string' && typeof saved.secret === 'string' && saved.data && typeof saved.data === 'object'
            && !Array.isArray(saved.data)) state = saved;
        else {
            root.sessionStorage.removeItem('dmate_manual_question_mode_tab_v1');
            root.sessionStorage.removeItem('dmate_offline_migration_v1');
            store();
        }
    } catch (_) { store(); }
    function write(section, value) {
        if (state.owner || !/^[a-z][a-z0-9_-]{0,63}$/i.test(section)) return false;
        try {
            const next = {...state, data:{...state.data, [section]:clone(value)}};
            const previous = state;
            state = next;
            if (store()) return true;
            state = previous;
        } catch (_) {}
        return false;
    }
    const assetScope = tab + '|' + launch + '|';
    const leaseStampPrefix = 'dmate:guest-asset-last-seen:';
    let leaseStorageAvailable = true;
    function touchAssetLease() {
        if (!Object.values(state.data).some(value => value?.asset)) return;
        try { root.localStorage.setItem(leaseStampPrefix + assetScope, String(Date.now())); }
        catch (_) { leaseStorageAvailable = false; }
    }
    touchAssetLease();
    root.addEventListener('pagehide', touchAssetLease);
    function assetOperation(mode, operation) {
        return new Promise((resolve, reject) => {
            const opening = root.indexedDB.open('dmate-guest-tab-assets-v1', 1);
            opening.onupgradeneeded = () => opening.result.createObjectStore('assets', {keyPath:'id'});
            opening.onerror = () => reject(opening.error);
            opening.onsuccess = () => {
                const db = opening.result, tx = db.transaction('assets', mode), request = operation(tx.objectStore('assets'));
                let value;
                if (request) request.onsuccess = () => { value = request.result; };
                tx.oncomplete = () => { db.close(); resolve(value); };
                tx.onerror = tx.onabort = () => { const error = tx.error; db.close(); reject(error); };
            };
        });
    }
    const deleteAsset = id => assetOperation('readwrite', store => store.delete(id)).catch(() => {});
    // Web Locks survive a backgrounded page and release when its document ends.
    // Only remove old encrypted assets whose owning document holds no live lease.
    if (root.navigator?.locks?.request && root.navigator.locks.query && root.indexedDB) {
        const leasePrefix = 'dmate-guest-assets:';
        void root.navigator.locks.request(leasePrefix + assetScope, async () => {
            try {
                const locks = await root.navigator.locks.query();
                const live = new Set((locks.held || []).map(lock => lock.name).filter(name => name.startsWith(leasePrefix)).map(name => name.slice(leasePrefix.length)));
                await assetOperation('readwrite', store => {
                    const request = store.openCursor();
                    request.onsuccess = () => {
                        const cursor = request.result;
                        if (!cursor) return;
                        const row = cursor.value, parts = String(row.id || '').split('|');
                        const scope = parts.slice(0, 2).join('|') + '|';
                        let lastSeen = 0;
                        try { lastSeen = Number(root.localStorage.getItem(leaseStampPrefix + scope)); }
                        catch (_) { leaseStorageAvailable = false; }
                        // The synchronous pagehide stamp closes the lease gap
                        // between an unloading document and its reload.
                        if (leaseStorageAvailable && lastSeen > 0 && scope !== assetScope && !live.has(scope)
                            && lastSeen < Date.now() - 3600000 && Number(row.updatedAt) < Date.now() - 3600000) cursor.delete();
                        cursor.continue();
                    };
                });
            } catch (_) {}
            await new Promise(() => {});
        }).catch(() => {});
    }
    async function keyFor(encoded) {
        return root.crypto.subtle.importKey('raw', Uint8Array.from(atob(encoded), char => char.charCodeAt(0)), 'AES-GCM', false, ['encrypt','decrypt']);
    }
    function owner(username, reset = false) {
        const next = typeof username === 'string' ? username : '';
        if (!reset && state.owner === next) return;
        generation++;
        for (const value of Object.values(state.data)) if (value?.asset === true && value.id) void deleteAsset(value.id);
        state = {version:1, tab, launch, owner:next, secret:secret(), data:{}};
        if (!store()) {
            try { root.sessionStorage.removeItem(KEY); } catch (_) {}
        }
    }
    root.DMateGuestSession = Object.freeze({
        read(section) { return state.owner ? null : clone(state.data[section] ?? null); },
        write,
        remove(section) {
            if (state.owner) return false;
            const previous = state, value = state.data[section], data = {...state.data};
            delete data[section]; state = {...state, data};
            if (!store()) { state = previous; root.dispatchEvent(new Event('dmate:guest-save-failure')); return false; }
            if (value?.asset) void deleteAsset(value.id);
            return true;
        },
        sections() { return state.owner ? [] : Object.keys(state.data); },
        reset() { owner('', true); },
        setAccountOwner: owner,
        getOwner() { return state.owner; },
        beginGuest() { if (state.owner) owner(''); },
        async writeBlob(section, blob) {
            const epoch = generation;
            if (!(blob instanceof Blob)) return write(section, null);
            if (state.owner) return false;
            try {
                if (!root.crypto?.subtle || !root.indexedDB) {
                    const data = await new Promise((resolve, reject) => {
                        const reader = new FileReader();
                        reader.onload = () => resolve(reader.result);
                        reader.onerror = reject;
                        reader.readAsDataURL(blob);
                    });
                    return epoch === generation && !state.owner && write(section, {data, type:blob.type, name:blob.name || ''});
                }
                const key = await keyFor(state.secret), iv = root.crypto.getRandomValues(new Uint8Array(12));
                const cipher = await root.crypto.subtle.encrypt({name:'AES-GCM', iv}, key, await blob.arrayBuffer());
                if (epoch !== generation || state.owner) return false;
                const id = assetScope + section + '|' + (root.crypto.randomUUID?.() || Date.now() + '-' + Math.random());
                await assetOperation('readwrite', store => store.put({id, iv, cipher,
                    type:blob.type, name:blob.name || '', updatedAt:Date.now()}));
                if (epoch !== generation || state.owner) { void deleteAsset(id); return false; }
                const previous = state.data[section];
                if (!write(section, {asset:true, id, type:blob.type, name:blob.name || '', size:blob.size})) {
                    void deleteAsset(id); return false;
                }
                if (previous?.asset && previous.id !== id) void deleteAsset(previous.id);
                touchAssetLease();
                return true;
            } catch (_) { return false; }
        },
        async readBlob(section) {
            const raw = !state.owner && state.data[section];
            if (typeof raw?.data === 'string') {
                try {
                    const encoded = raw.data.slice(raw.data.indexOf(',') + 1);
                    return new Blob([Uint8Array.from(atob(encoded), char => char.charCodeAt(0))], {type:raw.type});
                } catch (_) { return null; }
            }
            if (!raw?.asset) return null;
            const epoch = generation;
            try {
                const row = await assetOperation('readonly', store => store.get(raw.id));
                if (!row || epoch !== generation || state.owner) return null;
                const key = await keyFor(state.secret);
                const bytes = await root.crypto.subtle.decrypt({name:'AES-GCM', iv:row.iv}, key, row.cipher);
                return epoch === generation && !state.owner ? new Blob([bytes], {type:row.type}) : null;
            } catch (_) { return null; }
        },
        drawingState(section) {
            const initial = this.read(section) || {};
            return new Proxy(initial, {set(target, key, value) {
                target[key] = value;
                if (key === 'gallery') {
                    target.gallerySaveFailed = !write(section, {gallery:value});
                    if (target.gallerySaveFailed) root.dispatchEvent(new Event('dmate:guest-save-failure'));
                }
                return true;
            }});
        }
    });
    root.addEventListener('dmate:guest-session-end', () => owner('', true));
    root.addEventListener('dmate:account-state', event => owner(event.detail?.authenticated ? String(event.detail.username || '') : ''));
})(window);
