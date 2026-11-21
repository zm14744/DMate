/* Business records for the offline workspace. Values only persist through the vault. */
(function (root) {
  'use strict';
  const STORES = ['mistakes', 'notes', 'practice', 'settings', 'drawings'];
  const LEGACY = 'dmate-offline-workspace';
  const REF = 'offline-vault-ref';
  const LEASE = 'dmate-offline-guest:';
  const STAMP = 'dmate:offline-guest-last-seen:';
  const SCOPE = 'dmate:offline-guest-scope:';
  const DEVICE_VAULT = 'device-workspace-v1';
  const DEVICE_OWNER = 'device-local';
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
  async function storedVaultNames() {
    return new Promise((resolve,reject) => {
      const request = root.indexedDB.open('dmate-offline-vault-v1',1);
      request.onerror = () => reject(error('STORAGE_FAILED'));
      request.onsuccess = () => {
        const db = request.result, tx = db.transaction('vaults','readonly');
        const names = tx.objectStore('vaults').getAllKeys();
        tx.oncomplete = () => { db.close(); resolve(names.result); };
        tx.onerror = tx.onabort = () => { db.close(); reject(error('STORAGE_FAILED')); };
      };
    });
  }
  async function migrationFingerprint(value) {
    if (root.DMateOfflineBackup?.fingerprint) return root.DMateOfflineBackup.fingerprint(value);
    const visit = async item => {
      if (item instanceof Blob) return {blob:await visit(new Uint8Array(await item.arrayBuffer())),
        type:item.type,name:item.name,lastModified:item.lastModified};
      if (item instanceof ArrayBuffer) item = new Uint8Array(item);
      if (item instanceof Uint8Array) return {bytes:Array.from(item)};
      if (Array.isArray(item)) return Promise.all(item.map(visit));
      if (item && typeof item === 'object') {
        const entries = [];
        for (const key of Object.keys(item).sort()) entries.push([key,await visit(item[key])]);
        return Object.fromEntries(entries);
      }
      return item;
    };
    return address(JSON.stringify(await visit(value)));
  }
  async function migrateDeviceSources(options) {
    const migrate = () => migrateDeviceSourcesUnlocked(options);
    try {
      if (root.navigator?.locks?.request) await root.navigator.locks.request('dmate-offline-device-migration-v1',migrate);
      else await migrate();
    } catch (cause) {
      if (cause?.code === 'CLOSED') throw cause;
      options.warnings.push(cause?.code || 'STORAGE_FAILED');
    }
  }
  async function migrateDeviceSourcesUnlocked({read,list,commit,check,legacy,warnings}) {
    let local, gallery;
    const identity = async (store,row) => root.DMateOfflineBackup?.contentFingerprint
      && ['notes','mistakes','drawings'].includes(store)
      ? root.DMateOfflineBackup.contentFingerprint(store,row)
      : migrationFingerprint({...row,id:undefined});
    const byContent = {notes:new Set(),mistakes:new Set(),drawings:new Set()};
    const mistakeQuestions = new Map();
    const prepareLocal = async () => {
      if (local) return;
      // Most opens have no new legacy records. Do not decrypt and fingerprint
      // the entire current workspace merely to discover that migration is done.
      const current = Object.fromEntries(await Promise.all(STORES.map(async store =>
        [store,new Map((await list(store)).map(row => [row.id,row]))])));
      for (const values of Object.values(byContent)) values.clear();
      mistakeQuestions.clear();
      for (const store of ['notes','mistakes']) {
        const metadata = current.settings.get(store === 'notes' ? 'notebook-deletions' : 'mistake-deletions');
        for (const row of current[store].values()) if (!metadata?.deleted?.[row.id]
          || time(metadata.deleted[row.id]) < time(row.updatedAt)) {
          const hash = await identity(store,row);
          byContent[store].add(hash);
          if (store === 'mistakes' && !mistakeQuestions.has(hash)) mistakeQuestions.set(hash,row.id);
        }
      }
      // Establish the absent/present revision before planning a possible write.
      const currentGallery = await read('drawings','gallery');
      if (currentGallery) current.drawings.set('gallery',currentGallery);
      gallery = currentGallery?.gallery ? JSON.parse(currentGallery.gallery) : null;
      for (const page of gallery?.pages || []) byContent.drawings.add(await identity('drawings',page));
      local = current;
    };
    const copyRow = async (store,row,source,revision) => {
      check();
      if (!row || typeof row.id !== 'string') throw error('STORAGE_FAILED');
      if (store === 'notes' && (typeof row.title !== 'string' || typeof row.content !== 'string')
        || store === 'mistakes' && typeof row.statement !== 'string') throw error('STORAGE_FAILED');
      const markerId = 'device-migration:' + await address(source+'|'+store);
      let marker = await read('settings',markerId) || {id:markerId,records:{}};
      const sourceId = await address(row.id), signature = String(revision);
      if (marker.records?.[sourceId] === signature) return;
      if (store === 'settings') {
        const operations = [];
        let id, value;
        // Old views and appearance only need their matching target record.
        // Partition tombstones must never hide another partition's records.
        if (!['notebook-deletions','mistake-deletions'].includes(row.id)
          && !row.id.startsWith('vault-migrated:') && !row.id.startsWith('device-migration:')) {
          id = row.id === 'view' ? 'view:'+root.name : row.id;
          value = await read(store,id);
          if (!value) {
            value = {...row,id};
            operations.push({type:'put',store,expectAbsent:true,value});
          }
        }
        operations.push({type:'put',store:'settings',value:{...marker,records:{...marker.records,[sourceId]:signature}}});
        await commit(operations);
        if (value) local?.settings.set(id,value);
        return;
      }
      if (!local) {
        await prepareLocal();
        // Listing settings refreshes revision tokens. Re-read the matching
        // marker so its value and compare-and-swap precondition stay together.
        marker = await read('settings',markerId) || {id:markerId,records:{}};
        if (marker.records?.[sourceId] === signature) return;
      }
      const operations = [];
      if (store === 'drawings') {
        if (row.id !== 'gallery' || typeof row.gallery !== 'string') throw error('STORAGE_FAILED');
        const incoming = JSON.parse(row.gallery);
        if (![1,2].includes(incoming?.version) || !Array.isArray(incoming.pages)) throw error('STORAGE_FAILED');
        const pages = gallery?.pages?.slice() || [], ids = new Set(pages.map(page => page.id));
        let changed = false;
        for (const page of incoming.pages) {
          if (typeof page?.id !== 'string' || !Array.isArray(page.document?.graphs) || !page.document.graphs.length
            || page.document.graphs.some(graph => !Array.isArray(graph?.vertices) || !Array.isArray(graph?.edges))) throw error('STORAGE_FAILED');
          const hash = await identity('drawings',page);
          if (byContent.drawings.has(hash)) continue;
          let id = page.id;
          if (ids.has(id)) id = 'migrated-' + await migrationFingerprint({source,original:page.id,revision});
          pages.push({...page,id}); ids.add(id); byContent.drawings.add(hash); changed = true;
        }
        if (pages.reduce((count,page) => count+page.document.graphs.length,0) > 50) throw error('TOO_LARGE');
        if (changed) {
          gallery = {...incoming,...gallery,pages};
          const value = {id:'gallery',gallery:JSON.stringify(gallery),updatedAt:Date.now()};
          operations.push({type:'put',store,expectAbsent:!local.drawings.has('gallery'),value}); local.drawings.set('gallery',value);
        }
      } else {
        const hash = await identity(store,row);
        const matchingId = store === 'mistakes' && mistakeQuestions.get(hash);
        if (matchingId && root.DMateOfflineBackup?.mergeMistakes) {
          // A same-question record may contain another answer or annotation.
          // Keep it inside the existing question instead of dropping it or
          // creating another card. Refresh before merging so CAS protects edits
          // made by another page during the source migration.
          const current = await read(store,matchingId);
          if (!current || await identity(store,current) !== hash) throw error('CONFLICT');
          const merged = await root.DMateOfflineBackup.mergeMistakes(current,row);
          if (!await equal(current,merged)) operations.push({type:'put',store,value:merged});
          local[store].set(matchingId,merged);
        } else if (!byContent[store]?.has(hash)) {
          const metadata = local.settings.get(store === 'notes' ? 'notebook-deletions' : 'mistake-deletions');
          let id = row.id;
          if (local[store].has(id) || metadata?.deleted?.[id]) id = 'migrated-' + await migrationFingerprint({source,store,id,revision});
          while (metadata?.deleted?.[id] || local[store].has(id) && !await equal(local[store].get(id),{...row,id}))
            id = 'migrated-' + await migrationFingerprint({source,store,previous:id,revision,
              deletedAt:metadata?.deleted?.[id] || null,local:local[store].get(id) || null});
          const value = {...row,id};
          const concurrent = await read(store,id);
          if (concurrent && !await equal(concurrent,value)) throw error('CONFLICT');
          if (!concurrent) operations.push({type:'put',store,expectAbsent:true,value});
          local[store].set(id,value); byContent[store]?.add(hash);
          if (store === 'mistakes') mistakeQuestions.set(hash,id);
        }
      }
      operations.push({type:'put',store:'settings',value:{...marker,records:{...marker.records,[sourceId]:signature}}});
      await commit(operations);
    };
    const migrateEncrypted = async () => {
      for (const name of await storedVaultNames()) {
        if (!/^(?:account|guest)-[a-f0-9]{32}$/.test(name)) continue;
        let source;
        try {
          source = await root.DMateOfflineVault.open({name});
          const snapshots = Object.fromEntries(await Promise.all(STORES.map(async store => [store,await source.list(store)])));
          const metadata = new Map(snapshots.settings.map(saved => [saved.value?.row?.id,saved.value?.row]));
          for (const store of STORES) for (const saved of snapshots[store]) {
            const row = saved.value?.row;
            if (!row || typeof row.id !== 'string'
              || store === 'notes' && (typeof row.title !== 'string' || typeof row.content !== 'string')
              || store === 'mistakes' && typeof row.statement !== 'string') {
              warnings.push('STORAGE_FAILED'); continue;
            }
            const deleted = metadata.get(store === 'notes' ? 'notebook-deletions' : 'mistake-deletions')?.deleted?.[row.id];
            if (['notes','mistakes'].includes(store) && deleted && time(deleted) >= time(row.updatedAt)) continue;
            await copyRow(store,row,name,saved.revision);
          }
        } catch (cause) {
          if (cause?.code === 'CLOSED') throw cause;
          warnings.push(cause?.code || 'STORAGE_FAILED');
          if (['QUOTA_EXCEEDED','TOO_LARGE','CONFLICT'].includes(cause?.code)) return;
        } finally { source?.close(); }
      }
      // Older plaintext adapters are copied and verified before their source is
      // removed. The encrypted source vaults above always remain untouched.
      const legacySettings = await legacyOperation(legacy,'settings','readonly',(tx,done) => {
        const request = tx.objectStore('settings').getAll(); request.onsuccess = () => done(new Map(request.result.map(row => [row.id,row])));
      });
      for (const store of STORES.slice(0,4)) {
        const rows = await legacyOperation(legacy,store,'readonly',(tx,done) => {
          const request = tx.objectStore(store).getAll(); request.onsuccess = () => done(request.result);
        });
        for (const original of rows) {
          if (typeof original?.id !== 'string' || original.id.startsWith('vault-migrated:')) continue;
          if (store === 'notes' && (typeof original.title !== 'string' || typeof original.content !== 'string')
            || store === 'mistakes' && typeof original.statement !== 'string') {
            warnings.push('STORAGE_FAILED'); continue;
          }
          const split = original.id.lastIndexOf('::');
          let id = original.id;
          try { if (split >= 0 && decodeURIComponent(original.id.slice(split+2)).startsWith('account:')) id = original.id.slice(0,split); }
          catch (_) { /* An unscoped ID is itself user data. */ }
          const suffix = original.id.slice(id.length);
          const metadataId = store === 'notes' ? 'notebook-deletions' : 'mistake-deletions';
          const deleted = legacySettings.get(metadataId+suffix)?.deleted?.[id];
          if (['notes','mistakes'].includes(store) && deleted && time(deleted) >= time(original.updatedAt)) continue;
          // Keep source tombstones alongside any skipped legacy ghosts; they
          // must not be applied to another partition or removed before it.
          if (store === 'settings' && ['notebook-deletions','mistake-deletions'].includes(id)) continue;
          await copyRow(store,{...original,id},'legacy:'+original.id,await migrationFingerprint(original));
          await legacyOperation(legacy,store,'readwrite',tx => {
            const source = tx.objectStore(store), request = source.get(original.id);
            request.onsuccess = () => { if (sameShape(request.result,original)) source.delete(original.id); };
          });
        }
      }
      for (const key of Object.keys(root.localStorage)) {
        if (key.startsWith('dmate:offline:drawing-gallery:v1')) {
          const value = root.localStorage.getItem(key);
          await copyRow('drawings',{id:'gallery',gallery:value},'legacy:'+key,await address(value));
          if (root.localStorage.getItem(key) === value) root.localStorage.removeItem(key);
        } else if (key.startsWith('dmate:offline:appearance:v1')) {
          const value = root.localStorage.getItem(key);
          await copyRow('settings',{id:'appearance',settings:JSON.parse(value)},'legacy:'+key,await address(value));
          if (root.localStorage.getItem(key) === value) root.localStorage.removeItem(key);
        }
      }
      for (const store of STORES.slice(0,4)) {
        const rows = root.DMateGuestSession?.read('offline-'+store);
        if (!rows || typeof rows !== 'object') continue;
        for (const row of Object.values(rows)) if (typeof row?.id === 'string')
          await copyRow(store,row,'legacy-guest:'+store,await migrationFingerprint(row));
        if (sameShape(root.DMateGuestSession.read('offline-'+store),rows)) root.DMateGuestSession.remove('offline-'+store);
      }
    };
    await migrateEncrypted();
  }
  async function open(options = {}) {
    const device = options.scope === 'device';
    const owner = device ? DEVICE_OWNER : options.owner;
    if (typeof owner !== 'string' || typeof options.isCurrent !== 'function') throw error('INVALID_ARGUMENT');
    let closed = false, vault, legacy, destruction, releaseLease = () => {}, tail = Promise.resolve();
    const migrationWarnings = [];
    const revisions = new Map();
    const snapshots = new WeakMap();
    const live = () => !closed && options.isCurrent()
      && (device || !root.DMateGuestSession || root.DMateGuestSession.getOwner() === owner);
    const check = () => { if (!live()) throw error('CLOSED'); };
    const key = (store, id) => store + '\0' + id;
    const snapshot = (store, row, revision) => {
      const value = clone(row);
      snapshots.set(value,{store,id:value.id,revision});
      return value;
    };
    const revisionOf = (store, row) => {
      check();
      const saved = row && snapshots.get(row);
      if (!saved || saved.store !== store || saved.id !== row.id) throw error('INVALID_ARGUMENT');
      return saved.revision;
    };
    const run = action => {
      const pending = tail.catch(() => {}).then(async () => { check(); const value = await action(); check(); return value; });
      tail = pending; return pending;
    };
    check();
    let name;
    try {
      if (device) name = DEVICE_VAULT;
      else if (owner) name = await accountName(owner, live);
      else {
        const ref = root.DMateGuestSession?.read(REF);
        name = /^guest-[a-f0-9]{32}$/.test(ref?.name || '') ? ref.name : 'guest-' + random();
        if (!root.DMateGuestSession?.write(REF, {name})) throw error('STORAGE_FAILED');
        releaseLease = await guestLease(name);
      }
      check();
      vault = await root.DMateOfflineVault.open({name}); check();
      // Offline guest vaults from older versions are migration sources. Keep
      // them until their contents have been copied into device persistence.
      const read = async (store, id) => {
        if (!STORES.includes(store)) throw error('INVALID_ARGUMENT');
        const saved = await vault.read(store, await address(id)); check();
        revisions.set(key(store, id), saved?.revision ?? null);
        if (!saved) return undefined;
        if (saved.value?.owner !== owner || saved.value?.row?.id !== id) throw error('STORAGE_FAILED');
        return snapshot(store,saved.value.row,saved.revision);
      };
      const list = async store => {
        if (!STORES.includes(store)) throw error('INVALID_ARGUMENT');
        const rows = await vault.list(store); check();
        for (const id of revisions.keys()) if (id.startsWith(store + '\0')) revisions.set(id, null);
        const result = [];
        for (const saved of rows) {
          if (saved.value?.owner !== owner || typeof saved.value?.row?.id !== 'string') throw error('STORAGE_FAILED');
          revisions.set(key(store, saved.value.row.id), saved.revision);
          result.push(snapshot(store,saved.value.row,saved.revision));
        }
        return result;
      };
      const commit = async operations => {
        const prepared = [];
        for (const op of operations) {
          const id = String(op.id ?? op.value?.id ?? '');
          if (!id || !STORES.includes(op.store) || !['put', 'delete'].includes(op.type)) throw error('INVALID_ARGUMENT');
          // Read-modify-write callers can pin the revision of their actual
          // snapshot. A later UI read on this same handle must not advance an
          // older import plan's compare-and-swap precondition.
          const explicit = Object.hasOwn(op,'expectedRevision');
          if (!explicit && !revisions.has(key(op.store, id))) await read(op.store, id);
          const expectedRevision = explicit ? op.expectedRevision : revisions.get(key(op.store,id));
          if (expectedRevision !== null && typeof expectedRevision !== 'string') throw error('INVALID_ARGUMENT');
          if (op.expectAbsent && expectedRevision !== null) throw error('CONFLICT');
          prepared.push({type:op.type, collection:op.store, id:await address(id),
            expectedRevision, ...(op.type === 'put' ? {value:{owner, row:clone({...op.value, id})}} : {}), logicalId:id});
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
      if (device) {
        await migrateDeviceSources({read,list,commit,check,legacy,warnings:migrationWarnings});
      } else if (owner) {
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
      // Reads establish their own snapshot tokens; writes fetch a missing
      // token for the touched ID. Unopened panels need no eager decryption.
      check();
      return Object.freeze({
        migrationWarnings:Object.freeze(migrationWarnings.slice()),
        get:(store, id) => run(() => read(store, String(id))),
        all:store => run(() => list(store)),
        revisionOf,
        put:(store, row) => { const value = clone(row); return run(() => commit([{type:'put', store, value}])); },
        remove:(store, id) => run(() => commit([{type:'delete', store, id:String(id)}])),
        batch:operations => { const copy = clone(operations); return run(() => commit(copy)); },
        close() { if (closed) return; closed = true; releaseLease(); vault.close(); revisions.clear(); },
        destroyGuest() {
          if (device || owner) return Promise.reject(error('INVALID_ARGUMENT'));
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
