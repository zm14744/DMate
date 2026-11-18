/* Verified-account image drafts keep their original Blob in IndexedDB. */
(function (root) {
    'use strict';
    const NAME = 'dmate-account-image-drafts-v1';
    let opening = null, tail = Promise.resolve();
    const key = (owner, sessionId, taskId) => JSON.stringify([owner, String(sessionId), taskId]);
    const sessionKey = (owner, sessionId) => JSON.stringify([owner, String(sessionId)]);
    function database() {
        if (!opening) opening = new Promise((resolve, reject) => {
            const request = root.indexedDB.open(NAME, 1);
            request.onupgradeneeded = () => {
                const db = request.result;
                for (const name of ['tasks', 'files']) {
                    const store = db.createObjectStore(name, {keyPath:'id'});
                    store.createIndex('owner', 'owner');
                    store.createIndex('session', 'session');
                }
                db.createObjectStore('owners', {keyPath:'owner'});
            };
            request.onsuccess = () => {
                request.result.onversionchange = () => { request.result.close(); opening = null; };
                resolve(request.result);
            };
            request.onerror = () => { opening = null; reject(request.error || new Error('无法打开图片草稿存储')); };
            request.onblocked = () => { opening = null; reject(new Error('图片草稿存储暂被其他页面占用')); };
        });
        return opening;
    }
    function operation(body) {
        const pending = tail.catch(() => {}).then(async () => {
            const db = await database();
            return new Promise((resolve, reject) => {
                const tx = db.transaction(['tasks', 'files', 'owners'], 'readwrite');
                let result = true;
                tx.oncomplete = () => resolve(result);
                tx.onerror = tx.onabort = () => reject(tx.error || new Error('图片草稿未能保存'));
                try { body(tx, value => { result = value; }); } catch (error) { tx.abort(); reject(error); }
            });
        });
        tail = pending;
        return pending;
    }
    function withOwner(tx, owner, generation, live, action, done) {
        const store = tx.objectStore('owners'), request = store.get(owner);
        request.onsuccess = () => {
            const current = Number(request.result?.generation || 1);
            if (live && !live() || generation != null && generation !== current) { done(false); return; }
            if (!request.result) store.put({owner, generation:current});
            action(current);
        };
    }
    function deleteOwnerRows(tx, owner) {
        for (const name of ['tasks', 'files']) {
            const cursor = tx.objectStore(name).index('owner').openCursor(owner);
            cursor.onsuccess = () => { const row = cursor.result; if (row) { row.delete(); row.continue(); } };
        }
    }
    root.DMateAccountImageDraftStore = Object.freeze({
        load(owner, live) {
            return operation((tx, done) => withOwner(tx, owner, null, live, generation => {
                const metadata = tx.objectStore('tasks').index('owner').getAll(owner);
                const originals = tx.objectStore('files').index('owner').getAll(owner);
                let rows, files;
                const finish = () => {
                    if (!rows || !files) return;
                    const byId = new Map(files.map(row => [row.id, row.file]));
                    done({generation, rows:rows.filter(row => !row.deleted && byId.has(row.id))
                        .map(row => ({...row.metadata, file:byId.get(row.id)}))});
                };
                metadata.onsuccess = () => { rows = metadata.result; finish(); };
                originals.onsuccess = () => { files = originals.result; finish(); };
            }, done));
        },
        save(owner, generation, rows, live) {
            return operation((tx, done) => withOwner(tx, owner, generation, live, () => {
                const tasks = tx.objectStore('tasks'), files = tx.objectStore('files');
                for (const row of rows) {
                    if (!(row.file instanceof Blob)) continue;
                    const id = key(owner, row.sessionId, row.id), session = sessionKey(owner, row.sessionId);
                    const existing = tasks.get(id);
                    existing.onsuccess = () => {
                        if (existing.result?.deleted || live && !live()
                            || Number(existing.result?.metadata?.userEditedAt || 0) > Number(row.userEditedAt || 0)) return;
                        const metadata = {...row}; delete metadata.file;
                        tasks.put({id, owner, session, metadata, updatedAt:Date.now()});
                        const original = files.getKey(id);
                        original.onsuccess = () => {
                            if (original.result === undefined && (!live || live()))
                                files.put({id, owner, session, file:row.file});
                        };
                    };
                }
            }, done));
        },
        remove(owner, generation, sessionId, taskIds, live) {
            return operation((tx, done) => withOwner(tx, owner, generation, live, () => {
                const tasks = tx.objectStore('tasks'), files = tx.objectStore('files');
                for (const taskId of taskIds) {
                    const id = key(owner, sessionId, taskId);
                    tasks.put({id, owner, session:sessionKey(owner, sessionId), deleted:true, updatedAt:Date.now()});
                    files.delete(id);
                }
            }, done));
        },
        removeSession(owner, generation, sessionId, live) {
            return operation((tx, done) => withOwner(tx, owner, generation, live, () => {
                const tasks = tx.objectStore('tasks'), files = tx.objectStore('files');
                const request = tasks.index('session').openCursor(sessionKey(owner, sessionId));
                request.onsuccess = () => {
                    const cursor = request.result; if (!cursor) return;
                    cursor.update({id:cursor.value.id, owner, session:sessionKey(owner, sessionId), deleted:true, updatedAt:Date.now()});
                    files.delete(cursor.value.id); cursor.continue();
                };
            }, done));
        },
        remapSession(owner, generation, previousId, nextId, live) {
            return operation((tx, done) => withOwner(tx, owner, generation, live, () => {
                const tasks = tx.objectStore('tasks'), files = tx.objectStore('files');
                const request = tasks.index('session').openCursor(sessionKey(owner, previousId));
                request.onsuccess = () => {
                    const cursor = request.result; if (!cursor) return;
                    const previous = cursor.value;
                    if (previous.deleted) { cursor.continue(); return; }
                    const metadata = {...previous.metadata, sessionId:nextId};
                    const id = key(owner, nextId, metadata.id), session = sessionKey(owner, nextId);
                    const replacement = tasks.get(id);
                    replacement.onsuccess = () => {
                        if (!replacement.result?.deleted && Number(replacement.result?.metadata?.userEditedAt || 0) <= Number(metadata.userEditedAt || 0)) {
                            tasks.put({id, owner, session, metadata, updatedAt:Date.now()});
                            const original = files.get(previous.id), target = files.getKey(id);
                            let source, present;
                            const copy = () => {
                                if (source === undefined || present === undefined) return;
                                if (source && !present) files.put({id, owner, session, file:source.file});
                                files.delete(previous.id);
                            };
                            original.onsuccess = () => { source = original.result || null; copy(); };
                            target.onsuccess = () => { present = target.result !== undefined; copy(); };
                        } else files.delete(previous.id);
                        tasks.put({id:previous.id, owner, session:sessionKey(owner, previousId), deleted:true, updatedAt:Date.now()});
                    };
                    cursor.continue();
                };
            }, done));
        },
        clearOwner(owner) {
            if (!owner) return Promise.resolve(true);
            return operation((tx, done) => withOwner(tx, owner, null, null, generation => {
                // Invalidate outstanding writers in every tab before removing data.
                tx.objectStore('owners').put({owner, generation:generation + 1});
                deleteOwnerRows(tx, owner);
            }, done));
        }
    });
})(window);
