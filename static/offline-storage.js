/* Business records for the offline workspace. Values only persist through the vault. */
(function (root) {
  'use strict';
  const STORES = ['mistakes', 'notes', 'practice', 'settings', 'drawings'];
  const LEGACY = 'dmate-offline-workspace';
  const REF = 'offline-vault-ref';
  const LEASE = 'dmate-offline-guest:';
  const STAMP = 'dmate:offline-guest-last-seen:';
  const SCOPE = 'dmate:offline-guest-scope:';
  const leases = new Map();
  const encoder = new TextEncoder();
  const random = () => Array.from(root.crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('');
  const clone = value => root.structuredClone(value);
  const time = value => Number.isFinite(Number(value)) ? Number(value) : Date.parse(value) || 0;
  const error = code => Object.assign(new Error({CLOSED:'账号状态已变化，请重新打开离线页面',
    LEGACY_BLOCKED:'请关闭旧版离线页面后重试', CONFLICT:'本机内容已在另一页面修改，请重新打开后重试',
    TOO_LARGE:'本机资料超过加密保存限额，原资料已保留',
    STORAGE_FAILED:'本机加密资料未能保存，请保留当前页面后重试', INVALID_ARGUMENT:'本机资料格式无法读取'}[code] || '本机加密资料操作未能完成'), {code});
  async function address(id) {
    const digest = await root.crypto.subtle.digest('SHA-256', encoder.encode(String(id)));
    return 'r-' + Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('');
  }
  function sameShape(a, b) {
    return JSON.stringify(a, (_key, value) => value instanceof Blob
      ? {blob:true,size:value.size,type:value.type,name:value.name,lastModified:value.lastModified} : value)
      === JSON.stringify(b, (_key, value) => value instanceof Blob
        ? {blob:true,size:value.size,type:value.type,name:value.name,lastModified:value.lastModified} : value);
  }
  async function equal(a, b) {
    if (Object.is(a, b)) return true;
    if (a instanceof Blob || b instanceof Blob) {
      if (!(a instanceof Blob && b instanceof Blob) || !sameShape(a, b)) return false;
      return equal(new Uint8Array(await a.arrayBuffer()), new Uint8Array(await b.arrayBuffer()));
    }
    if (a instanceof ArrayBuffer) a = new Uint8Array(a);
    if (b instanceof ArrayBuffer) b = new Uint8Array(b);
    if (a instanceof Uint8Array || b instanceof Uint8Array) return a instanceof Uint8Array && b instanceof Uint8Array
      && a.length === b.length && a.every((v, i) => v === b[i]);
    if (!a || !b || typeof a !== 'object' || typeof b !== 'object' || Array.isArray(a) !== Array.isArray(b)) return false;
    const keys = Object.keys(a);
    if (keys.length !== Object.keys(b).length) return false;
    for (const key of keys) if (!Object.hasOwn(b, key) || !await equal(a[key], b[key])) return false;
    return true;
  }
  function legacyDatabase() {
    return new Promise((resolve, reject) => {
      let blocked = false;
      const request = root.indexedDB.open(LEGACY, 4);
      request.onupgradeneeded = () => {
        const db = request.result;
        for (const name of STORES.slice(0, 4)) if (!db.objectStoreNames.contains(name)) db.createObjectStore(name, {keyPath:'id'});
      };
      request.onblocked = () => { blocked = true; reject(error('LEGACY_BLOCKED')); };
      request.onerror = () => reject(error('STORAGE_FAILED'));
      request.onsuccess = () => {
        if (blocked) { request.result.close(); return; }
        request.result.onversionchange = () => request.result.close(); resolve(request.result);
      };
    });
  }
  function legacyOperation(db, stores, mode, action) {
    return new Promise((resolve, reject) => {
      let output;
      const tx = db.transaction(stores, mode);
      tx.oncomplete = () => resolve(output);
      tx.onerror = tx.onabort = () => reject(error('STORAGE_FAILED'));
      try { action(tx, value => { output = value; }); } catch (cause) { tx.abort(); reject(cause); }
    });
  }
  async function accountName(owner, live) {
    const directory = await root.DMateOfflineVault.open({name:'workspace-directory-v1'});
    try {
      for (let attempt = 0; attempt < 5; attempt++) {
        if (!live()) throw error('CLOSED');
        const index = await directory.read('directory', 'accounts');
        const rows = Array.isArray(index?.value?.accounts) ? index.value.accounts : [];
        const found = rows.find(row => row.owner === owner);
        if (found) return found.name;
        const name = 'account-' + random();
        try {
          await directory.write('directory', 'accounts', {accounts:[...rows, {owner, name}]}, {expectedRevision:index?.revision ?? null});
          if (!live()) throw error('CLOSED');
          return name;
        } catch (cause) { if (cause.code !== 'CONFLICT') throw cause; }
      }
      throw error('CONFLICT');
    } finally { directory.close(); }
  }
  function touch(name) {
    try { root.localStorage.setItem(STAMP + name, String(Date.now())); } catch (_) {}
  }
  function guestScope() {
    const launch = String(root.__DMATE_NATIVE_GUEST_SESSION__
      || /\bDMateGuestSession\/([A-Za-z0-9-]{16,80})\b/.exec(root.navigator?.userAgent || '')?.[1] || '');
    return String(root.name || '') + '|' + launch + '|';
  }
  async function guestLease(name) {
    let lease = leases.get(name);
    if (!lease) {
      lease = {count:0, release:() => {}, ready:Promise.resolve()}; leases.set(name, lease);
      if (root.navigator?.locks?.request) {
        lease.ready = new Promise(resolve => {
          const held = new Promise(done => { lease.release = done; });
          void root.navigator.locks.request(LEASE + name, {mode:'shared'}, async () => { resolve(); await held; }).catch(resolve);
        });
      }
    }
    lease.count++; touch(name);
    // The existing GuestSession document lease also protects a guest who
    // navigates back online while its offline handle is closed.
    try { root.localStorage.setItem(SCOPE + name, guestScope()); } catch (_) {}
    await lease.ready;
    return () => {
      if (--lease.count > 0) return;
      touch(name); lease.release(); leases.delete(name);
    };
  }
  root.addEventListener('pagehide', () => { for (const name of leases.keys()) touch(name); });
  async function collectGuests(current) {
    if (!root.navigator?.locks?.query) return;
    let db;
    try {
      const locks = await root.navigator.locks.query();
      const live = new Set((locks.held || []).map(row => row.name));
      const names = await new Promise((resolve, reject) => {
        const request = root.indexedDB.open('dmate-offline-vault-v1', 1);
        request.onerror = () => reject(request.error);
        request.onsuccess = () => {
          db = request.result;
          const tx = db.transaction('vaults', 'readonly'), read = tx.objectStore('vaults').getAllKeys();
          tx.oncomplete = () => resolve(read.result); tx.onerror = () => reject(tx.error);
        };
      });
      for (const name of names) {
        if (name === current || !/^guest-[a-f0-9]{32}$/.test(name) || live.has(LEASE + name) || leases.has(name)) continue;
        let last = 0, scope;
        try { last = Number(root.localStorage.getItem(STAMP + name)); scope = root.localStorage.getItem(SCOPE + name); } catch (_) { continue; }
        if (scope && live.has('dmate-guest-assets:' + scope)) continue;
        if (!last || last > Date.now() - 3600000) continue;
        try {
          await root.navigator.locks.request(LEASE + name, {mode:'exclusive', ifAvailable:true}, async lock => {
            if (!lock || leases.has(name) || Number(root.localStorage.getItem(STAMP + name)) > Date.now() - 3600000) return;
            const cleanup = async () => {
              const vault = await root.DMateOfflineVault.open({name});
              await vault.destroy(); root.localStorage.removeItem(STAMP + name); root.localStorage.removeItem(SCOPE + name);
            };
            if (scope) await root.navigator.locks.request('dmate-guest-assets:' + scope, {mode:'exclusive', ifAvailable:true}, lock => lock ? cleanup() : undefined);
            else await cleanup();
          });
        } catch (_) { /* Missing keys and unavailable providers never reset a vault. */ }
      }
    } catch (_) { /* Cleanup cannot block the active workspace. */ }
    finally { db?.close(); }
  }
  async function open(options = {}) {
    const owner = options.owner;
    if (typeof owner !== 'string' || typeof options.isCurrent !== 'function') throw error('INVALID_ARGUMENT');
    let closed = false, vault, legacy, destruction, releaseLease = () => {}, tail = Promise.resolve();
    const revisions = new Map();
    const live = () => !closed && options.isCurrent() && (!root.DMateGuestSession || root.DMateGuestSession.getOwner() === owner);
    const check = () => { if (!live()) throw error('CLOSED'); };
    const key = (store, id) => store + '\0' + id;
    const run = action => {
      const pending = tail.catch(() => {}).then(async () => { check(); const value = await action(); check(); return value; });
      tail = pending; return pending;
    };
    check();
    let name;
    try {
      if (owner) name = await accountName(owner, live);
      else {
        const ref = root.DMateGuestSession?.read(REF);
        name = /^guest-[a-f0-9]{32}$/.test(ref?.name || '') ? ref.name : 'guest-' + random();
        if (!root.DMateGuestSession?.write(REF, {name})) throw error('STORAGE_FAILED');
        releaseLease = await guestLease(name);
      }
      check();
      vault = await root.DMateOfflineVault.open({name}); check();
      void collectGuests(owner ? root.DMateGuestSession?.read(REF)?.name : name);
      const read = async (store, id) => {
        if (!STORES.includes(store)) throw error('INVALID_ARGUMENT');
        const saved = await vault.read(store, await address(id)); check();
        revisions.set(key(store, id), saved?.revision ?? null);
        if (!saved) return undefined;
        if (saved.value?.owner !== owner || saved.value?.row?.id !== id) throw error('STORAGE_FAILED');
        return clone(saved.value.row);
      };
      const list = async store => {
        if (!STORES.includes(store)) throw error('INVALID_ARGUMENT');
        const rows = await vault.list(store); check();
        for (const id of revisions.keys()) if (id.startsWith(store + '\0')) revisions.set(id, null);
        const result = [];
        for (const saved of rows) {
          if (saved.value?.owner !== owner || typeof saved.value?.row?.id !== 'string') throw error('STORAGE_FAILED');
          revisions.set(key(store, saved.value.row.id), saved.revision); result.push(clone(saved.value.row));
        }
        return result;
      };
      const commit = async operations => {
        const prepared = [];
        for (const op of operations) {
          const id = String(op.id ?? op.value?.id ?? '');
          if (!id || !STORES.includes(op.store) || !['put', 'delete'].includes(op.type)) throw error('INVALID_ARGUMENT');
          if (!revisions.has(key(op.store, id))) await read(op.store, id);
          prepared.push({type:op.type, collection:op.store, id:await address(id),
            expectedRevision:revisions.get(key(op.store, id)), ...(op.type === 'put' ? {value:{owner, row:clone({...op.value, id})}} : {}), logicalId:id});
        }
        check();
        const saved = await vault.batch(prepared.map(({logicalId, ...op}) => op)); check();
        saved.forEach((row, i) => revisions.set(key(prepared[i].collection, prepared[i].logicalId), row.revision));
      };
      // A retried migration never overwrites a newer encrypted edit.
      const migrate = async (store, row) => {
        check();
        const current = await read(store, row.id);
        if (current && time(current.updatedAt) >= time(row.updatedAt)) return current;
        await commit([{type:'put', store, value:row}]);
        const verified = await read(store, row.id);
        if (!await equal(verified, row)) throw error('STORAGE_FAILED');
        return verified;
      };
      const migrateGallery = async gallery => {
        const validate = value => {
          if (![1, 2].includes(value?.version) || !Array.isArray(value.pages)) throw error('STORAGE_FAILED');
          const ids = new Set(); let renderedPages = 0;
          for (const page of value.pages) {
            const graphs = page?.document?.graphs;
            if (typeof page?.id !== 'string' || !page.id || ids.has(page.id)
                || !Array.isArray(graphs) || !graphs.length
                || graphs.some(graph => !graph || typeof graph !== 'object'
                  || !Array.isArray(graph.vertices) || !Array.isArray(graph.edges))) throw error('STORAGE_FAILED');
            ids.add(page.id);
            // The drawing editor expands each legacy subgraph into a page.
            renderedPages += graphs.length;
            if (renderedPages > 50) throw error('TOO_LARGE');
          }
          return value;
        };
        const parse = raw => { let value; try { value = JSON.parse(raw); } catch (_) { throw error('STORAGE_FAILED'); } return validate(value); };
        const incoming = parse(gallery), current = await read('drawings', 'gallery');
        let row = {id:'gallery', gallery, updatedAt:0};
        if (current) {
          const existing = parse(current.gallery);
          if (await equal(existing, incoming)) return current;
          if (!Array.isArray(existing?.pages) || !Array.isArray(incoming?.pages)) throw error('CONFLICT');
          const pages = clone(existing.pages), byId = new Map();
          for (let i = 0; i < pages.length; i++) {
            if (typeof pages[i]?.id !== 'string' || byId.has(pages[i].id)) throw error('CONFLICT');
            byId.set(pages[i].id, i);
          }
          const seen = new Set(); let changed = false;
          for (const page of incoming.pages) {
            if (typeof page?.id !== 'string' || seen.has(page.id)) throw error('CONFLICT');
            seen.add(page.id);
            if (!byId.has(page.id)) {
              if (pages.length >= 50) throw error('TOO_LARGE');
              byId.set(page.id, pages.length); pages.push(clone(page)); changed = true; continue;
            }
            const index = byId.get(page.id), previous = pages[index], older = time(previous.updatedAt), newer = time(page.updatedAt);
            if (newer > older) { pages[index] = clone(page); changed = true; }
            else if (newer === older && !await equal(previous, page)) throw error('CONFLICT');
          }
          if (!changed) return current;
          validate({...existing, pages});
          row = {...current, gallery:JSON.stringify({...existing, pages}),
            updatedAt:Math.max(time(current.updatedAt), ...pages.map(page => time(page.updatedAt)))};
        }
        await commit([{type:'put', store:'drawings', value:row}]);
        const verified = await read('drawings', 'gallery');
        if (!await equal(verified, row)) throw error('STORAGE_FAILED');
        return verified;
      };
      if (typeof options.beforeMigration === 'function') await options.beforeMigration();
      legacy = await legacyDatabase(); check();
      const suffix = '::' + encodeURIComponent('account:' + owner);
      const sources = [], privateSections = ['offline-mistakes', 'offline-notes', 'offline-practice', 'offline-settings'];
      if (owner) {
        for (const store of STORES.slice(0, 4)) {
          const rows = await legacyOperation(legacy, store, 'readonly', (tx, done) => {
            const request = tx.objectStore(store).getAll(); request.onsuccess = () => done(request.result);
          }); check();
          for (const original of rows) if (typeof original.id === 'string' && original.id.endsWith(suffix)) {
            const row = {...original, id:original.id.slice(0, -suffix.length)};
            await migrate(store, row); sources.push({store, original});
          }
        }
        const appearanceKey = 'dmate:offline:appearance:v1' + suffix;
        const appearance = root.localStorage.getItem(appearanceKey);
        if (appearance) {
          const settings = JSON.parse(appearance), current = await read('settings', 'appearance');
          if (!current) await migrate('settings', {id:'appearance', settings, updatedAt:0});
        }
        const galleryKey = 'dmate:offline:drawing-gallery:v1' + suffix, gallery = root.localStorage.getItem(galleryKey);
        if (gallery) await migrateGallery(gallery);
        // The version-4 barrier closes old IndexedDB writers. Compare sources
        // again inside cleanup; unrelated accounts and unscoped rows stay intact.
        await legacyOperation(legacy, STORES.slice(0, 4), 'readwrite', tx => {
          for (const source of sources) {
            const store = tx.objectStore(source.store), request = store.get(source.original.id);
            request.onsuccess = () => { if (sameShape(request.result, source.original)) store.delete(source.original.id); };
          }
          tx.objectStore('settings').put({id:'vault-migrated:' + name, version:1});
        }); check();
        if (appearance && root.localStorage.getItem(appearanceKey) === appearance) root.localStorage.removeItem(appearanceKey);
        if (gallery && root.localStorage.getItem(galleryKey) === gallery) root.localStorage.removeItem(galleryKey);
      } else {
        for (const section of privateSections) {
          const rows = root.DMateGuestSession.read(section);
          if (!rows || typeof rows !== 'object') continue;
          const store = section.slice(8);
          for (const row of Object.values(rows)) if (row && typeof row.id === 'string') await migrate(store, row);
          check();
          if (!sameShape(root.DMateGuestSession.read(section), rows)) throw error('CONFLICT');
          if (!root.DMateGuestSession.remove(section)) throw error('STORAGE_FAILED');
        }
        const view = root.DMateGuestSession.read('offline-view');
        if (view) {
          await migrate('settings', {id:'view', ...view}); check();
          if (!sameShape(root.DMateGuestSession.read('offline-view'), view)) throw error('CONFLICT');
          if (!root.DMateGuestSession.remove('offline-view')) throw error('STORAGE_FAILED');
        }
        if (!options.preserveSharedGuestSource) {
          const drawingSource = root.DMateGuestSession.read('drawings'), gallery = drawingSource?.gallery;
          if (gallery) {
            await migrateGallery(gallery); check();
            if (!sameShape(root.DMateGuestSession.read('drawings'), drawingSource)) throw error('CONFLICT');
            if (!root.DMateGuestSession.remove('drawings')) throw error('STORAGE_FAILED');
          }
          const appearance = root.DMateGuestSession.read('appearance'), backgroundSource = root.DMateGuestSession.read('background');
          const backgroundBlob = await root.DMateGuestSession.readBlob('background');
          if (appearance || backgroundBlob) {
            await migrate('settings', {id:'appearance', settings:appearance || {}, ...(backgroundBlob ? {backgroundBlob} : {})}); check();
            if (!sameShape(root.DMateGuestSession.read('appearance'), appearance)
              || !sameShape(root.DMateGuestSession.read('background'), backgroundSource)) throw error('CONFLICT');
            if (!root.DMateGuestSession.remove('appearance') || !root.DMateGuestSession.remove('background')) throw error('STORAGE_FAILED');
          }
        }
      }
      legacy.close(); legacy = null;
      for (const store of STORES) await list(store);
      check();
      return Object.freeze({
        get:(store, id) => run(() => read(store, String(id))),
        all:store => run(() => list(store)),
        put:(store, row) => { const value = clone(row); return run(() => commit([{type:'put', store, value}])); },
        remove:(store, id) => run(() => commit([{type:'delete', store, id:String(id)}])),
        batch:operations => { const copy = clone(operations); return run(() => commit(copy)); },
        close() { if (closed) return; closed = true; releaseLease(); vault.close(); revisions.clear(); },
        destroyGuest() {
          if (owner) return Promise.reject(error('INVALID_ARGUMENT'));
          if (!destruction) destruction = (async () => {
            if (closed) {
              const retained = await root.DMateOfflineVault.open({name}); await retained.destroy();
            } else { closed = true; releaseLease(); await vault.destroy(); revisions.clear(); }
            if (root.DMateGuestSession?.read(REF)?.name === name) root.DMateGuestSession.remove(REF);
            try { root.localStorage.removeItem(STAMP + name); root.localStorage.removeItem(SCOPE + name); } catch (_) {}
          })().catch(cause => { destruction = null; throw cause; });
          return destruction;
        }
      });
    } catch (cause) { closed = true; legacy?.close(); releaseLease(); vault?.close(); throw cause; }
  }
  root.DMateOfflineStorage = Object.freeze({open});
}(window));
