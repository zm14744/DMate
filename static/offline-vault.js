/* DMate offline confidentiality core. No UI, network, cloud sync or plaintext fallback.
 * Integration and threat model: docs/OFFLINE_CONFIDENTIALITY.md.
 */
(function (root) {
  "use strict";

  const DATABASE = "dmate-offline-vault-v1";
  const FORMAT = 1;
  const MAX_BYTES = 16 * 1024 * 1024;
  const MAX_BATCH_BYTES = 32 * 1024 * 1024;
  const MAX_BATCH = 128;
  const encoder = new TextEncoder();
  const decoder = new TextDecoder("utf-8", {fatal: true});
  const hexPattern = /^[0-9a-f]{32}$/;
  const namePattern = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/;
  const collectionPattern = /^[a-z][a-z0-9_-]{0,63}$/;
  const idPattern = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$/;
  const messages = Object.freeze({
    INVALID_ARGUMENT: "Invalid vault argument.",
    UNSUPPORTED_VALUE: "The value is not a supported JSON or binary value.",
    TOO_LARGE: "The encrypted record or batch exceeds the size limit.",
    ENVIRONMENT_UNSUPPORTED: "Secure Web Crypto and IndexedDB are required.",
    NATIVE_UNAVAILABLE: "This native client does not provide the offline vault bridge.",
    PROTECTION_UNAVAILABLE: "The required key protection is unavailable.",
    PROTECTION_MISMATCH: "This vault belongs to a different key provider.",
    KEYSTORE_UNAVAILABLE: "The system key store is unavailable or locked.",
    KEY_MISSING: "The vault key is missing; existing data has not been reset.",
    KEY_EXISTS: "The key already exists and has not been replaced.",
    AUTHENTICATION_FAILED: "The encrypted data could not be authenticated.",
    ENCRYPTION_FAILED: "The data could not be encrypted.",
    STORAGE_UNAVAILABLE: "The encrypted database is unavailable.",
    STORAGE_BLOCKED: "Close other versions of this database and retry.",
    STORAGE_FAILED: "The encrypted transaction did not complete.",
    QUOTA_EXCEEDED: "There is not enough space to save the encrypted data.",
    FORMAT_UNSUPPORTED: "The vault format is invalid or unsupported.",
    CONFLICT: "The record changed; read the current revision before saving.",
    CLOSED: "The vault has been closed.",
    NATIVE_TIMEOUT: "The system key operation timed out.",
    BUSY: "The system key provider is busy; retry the operation."
  });

  class VaultError extends Error {
    constructor(code) {
      super(messages[code] || messages.STORAGE_FAILED);
      this.name = "VaultError";
      this.code = Object.hasOwn(messages, code) ? code : "STORAGE_FAILED";
    }
  }
  const fail = code => { throw new VaultError(code); };
  function safeError(error, fallback = "STORAGE_FAILED") {
    if (error instanceof VaultError) return error;
    if (error?.name === "QuotaExceededError") return new VaultError("QUOTA_EXCEEDED");
    // Never forward native error messages, record contents, filenames or key material.
    if (Object.hasOwn(messages, error?.code)) return new VaultError(error.code);
    return new VaultError(fallback);
  }
  function randomId() {
    return Array.from(root.crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, "0")).join("");
  }
  function bytes(value) {
    if (value instanceof Uint8Array) return value;
    if (value instanceof ArrayBuffer) return new Uint8Array(value);
    fail("FORMAT_UNSUPPORTED");
  }
  function sameBytes(a, b) {
    const x = bytes(a), y = bytes(b);
    if (x.byteLength !== y.byteLength) return false;
    let difference = 0;
    for (let i = 0; i < x.byteLength; i++) difference |= x[i] ^ y[i];
    return difference === 0;
  }
  function base64(value) {
    const input = bytes(value), parts = [];
    for (let offset = 0; offset < input.length; offset += 8192) {
      parts.push(String.fromCharCode(...input.subarray(offset, offset + 8192)));
    }
    return root.btoa(parts.join(""));
  }
  function unbase64(value, maxBytes) {
    if (typeof value !== "string" || value.length > 4 * Math.ceil(maxBytes / 3)
      || value.length % 4 !== 0 || /[^A-Za-z0-9+/=]/.test(value)) fail("FORMAT_UNSUPPORTED");
    const padding = value.indexOf("=");
    if (padding !== -1 && (padding < value.length - 2 || !/^={1,2}$/.test(value.slice(padding)))) fail("FORMAT_UNSUPPORTED");
    let raw;
    try { raw = root.atob(value); } catch (_) { fail("FORMAT_UNSUPPORTED"); }
    if (raw.length > maxBytes) fail("TOO_LARGE");
    return Uint8Array.from(raw, character => character.charCodeAt(0));
  }

  // A tagged, length-delimited container keeps nested Blob types/names inside the
  // ciphertext. It does not interpret user object properties as codec directives.
  async function encode(value) {
    const binary = [], sources = [], ancestors = new Set();
    let binarySize = 0, textSize = 0, nodes = 0;
    function binaryPart(part) {
      binarySize += part instanceof Blob ? part.size : part.byteLength;
      if (binarySize > MAX_BYTES) fail("TOO_LARGE");
      const index = binary.length;
      binary.push(null);
      if (part instanceof Blob) sources.push({index, blob: part});
      else binary[index] = bytes(part).slice();
      return index;
    }
    function visit(item, depth) {
      if (++nodes > 200000 || depth > 64) fail("TOO_LARGE");
      if (item === null) return ["null"];
      if (item === undefined) return ["undefined"];
      if (typeof item === "string") {
        textSize += item.length; if (textSize + binarySize > MAX_BYTES) fail("TOO_LARGE");
        return ["string", item];
      }
      if (typeof item === "boolean") return ["boolean", item];
      if (typeof item === "number") {
        if (!Number.isFinite(item)) fail("UNSUPPORTED_VALUE");
        return ["number", Object.is(item, -0) ? "-0" : item];
      }
      if (item instanceof Blob) {
        const file = typeof root.File === "function" && item instanceof root.File;
        return [file ? "file" : "blob", binaryPart(item), item.type, file ? item.name : "", file ? item.lastModified : 0];
      }
      if (item instanceof ArrayBuffer) return ["buffer", binaryPart(item)];
      if (item instanceof Uint8Array) return ["bytes", binaryPart(item)];
      if (typeof item !== "object" || ancestors.has(item)) fail("UNSUPPORTED_VALUE");
      const prototype = Object.getPrototypeOf(item);
      if (Array.isArray(item) ? prototype !== Array.prototype : prototype !== Object.prototype && prototype !== null) fail("UNSUPPORTED_VALUE");
      if (Object.getOwnPropertySymbols(item).length) fail("UNSUPPORTED_VALUE");
      ancestors.add(item);
      let result;
      if (Array.isArray(item)) {
        if (item.length > 200000) fail("TOO_LARGE");
        const children = [];
        for (let i = 0; i < item.length; i++) {
          const descriptor = Object.getOwnPropertyDescriptor(item, String(i));
          if (descriptor && !Object.hasOwn(descriptor, "value")) fail("UNSUPPORTED_VALUE");
          children.push(visit(descriptor?.value, depth + 1));
        }
        result = ["array", children];
      }
      else result = ["object", Object.keys(item).map(key => {
        textSize += key.length; if (textSize + binarySize > MAX_BYTES) fail("TOO_LARGE");
        const descriptor = Object.getOwnPropertyDescriptor(item, key);
        if (!Object.hasOwn(descriptor, "value")) fail("UNSUPPORTED_VALUE");
        return [key, visit(descriptor.value, depth + 1)];
      })];
      ancestors.delete(item);
      return result;
    }
    let output;
    try {
      const tree = visit(value, 0);
      // Validate the whole tree before reading Blob bytes. Sequential reads also
      // ensure no late promise can retain plaintext after a failed encoding.
      for (const source of sources) binary[source.index] = new Uint8Array(await source.blob.arrayBuffer());
      const header = encoder.encode(JSON.stringify({version: 1, tree, lengths: binary.map(part => part.length)}));
      if (header.length + binarySize + 4 > MAX_BYTES) fail("TOO_LARGE");
      output = new Uint8Array(4 + header.length + binarySize);
      new DataView(output.buffer).setUint32(0, header.length, false);
      output.set(header, 4);
      let offset = 4 + header.length;
      for (const part of binary) { output.set(part, offset); offset += part.length; }
      return output;
    } finally {
      // Best effort only; JavaScript strings, browser internals and returned values
      // cannot be reliably erased by a web application.
      for (const part of binary) part?.fill(0);
    }
  }

  function decode(input) {
    try {
      if (input.length < 4 || input.length > MAX_BYTES) fail("FORMAT_UNSUPPORTED");
      const length = new DataView(input.buffer, input.byteOffset, input.byteLength).getUint32(0, false);
      if (length > input.length - 4) fail("FORMAT_UNSUPPORTED");
      const header = JSON.parse(decoder.decode(input.subarray(4, 4 + length)));
      if (header.version !== 1 || !Array.isArray(header.lengths)) fail("FORMAT_UNSUPPORTED");
      let offset = 4 + length, nodes = 0;
      const binary = header.lengths.map(size => {
        if (!Number.isSafeInteger(size) || size < 0 || size > input.length - offset) fail("FORMAT_UNSUPPORTED");
        const part = input.subarray(offset, offset + size); offset += size; return part;
      });
      if (offset !== input.length) fail("FORMAT_UNSUPPORTED");
      function visit(item, depth) {
        if (++nodes > 200000 || depth > 64 || !Array.isArray(item)) fail("FORMAT_UNSUPPORTED");
        const [tag, value] = item;
        if (tag === "null" && item.length === 1) return null;
        if (tag === "undefined" && item.length === 1) return undefined;
        if ((tag === "string" || tag === "boolean") && typeof value === tag && item.length === 2) return value;
        if (tag === "number" && item.length === 2 && (value === "-0" || typeof value === "number" && Number.isFinite(value))) return value === "-0" ? -0 : value;
        if (tag === "array" && item.length === 2 && Array.isArray(value)) return value.map(child => visit(child, depth + 1));
        if (tag === "object" && item.length === 2 && Array.isArray(value)) {
          const result = {};
          for (const pair of value) {
            if (!Array.isArray(pair) || pair.length !== 2 || typeof pair[0] !== "string" || Object.hasOwn(result, pair[0])) fail("FORMAT_UNSUPPORTED");
            Object.defineProperty(result, pair[0], {value: visit(pair[1], depth + 1), writable: true, enumerable: true, configurable: true});
          }
          return result;
        }
        if (["buffer", "bytes", "blob", "file"].includes(tag) && Number.isInteger(value) && value >= 0 && value < binary.length) {
          if ((tag === "buffer" || tag === "bytes") && item.length === 2) {
            const copy = binary[value].slice(); return tag === "buffer" ? copy.buffer : copy;
          }
          if (item.length !== 5 || typeof item[2] !== "string" || typeof item[3] !== "string" || !Number.isFinite(item[4])) fail("FORMAT_UNSUPPORTED");
          if (tag === "blob") return new Blob([binary[value]], {type: item[2]});
          if (tag === "file" && typeof root.File === "function") return new root.File([binary[value]], item[3], {type: item[2], lastModified: item[4]});
        }
        fail("FORMAT_UNSUPPORTED");
      }
      return visit(header.tree, 0);
    } catch (error) { throw safeError(error, "FORMAT_UNSUPPORTED"); }
  }

  let androidTransport = null;
  function androidRequest(bridge) {
    if (androidTransport?.bridge === bridge) return androidTransport.request;
    const pending = new Map();
    bridge.onmessage = event => {
      let message;
      try { message = JSON.parse(event.data); } catch (_) { return; }
      const request = pending.get(message?.id);
      if (!request) return;
      pending.delete(message.id); root.clearTimeout(request.timer);
      if (message.ok === true) request.resolve(message.result);
      else request.reject(safeError(message.error, "KEYSTORE_UNAVAILABLE"));
    };
    const request = payload => new Promise((resolve, reject) => {
      const id = randomId();
      const timer = root.setTimeout(() => { pending.delete(id); reject(new VaultError("NATIVE_TIMEOUT")); }, 120000);
      pending.set(id, {resolve, reject, timer});
      try { bridge.postMessage(JSON.stringify({id, ...payload})); }
      catch (error) { pending.delete(id); root.clearTimeout(timer); reject(safeError(error, "NATIVE_UNAVAILABLE")); }
    });
    androidTransport = {bridge, request};
    return request;
  }
  async function selectProvider(requireProtection) {
    let request;
    if (typeof root.DMateOfflineVaultDesktop?.request === "function") {
      request = payload => Promise.resolve().then(() => root.DMateOfflineVaultDesktop.request(payload));
    } else if (typeof root.DMateOfflineVaultAndroid?.postMessage === "function") {
      request = androidRequest(root.DMateOfflineVaultAndroid);
    }
    if (request) {
      const call = async payload => {
        try { return await request(payload); } catch (error) { throw safeError(error, "KEYSTORE_UNAVAILABLE"); }
      };
      const capability = await call({op: "capabilities"});
      if (capability?.version !== 1 || capability.protection !== "os-keystore"
        || !["android-keystore", "desktop-keyring"].includes(capability.provider)) fail("PROTECTION_UNAVAILABLE");
      return {name: capability.provider, protection: "os-keystore", call};
    }
    // Older installed shells must be upgraded; their missing bridge must not
    // quietly turn a device-protected vault into a browser-key vault.
    if (/\bDMate(?:Android|Desktop)\//.test(root.navigator?.userAgent || "")) fail("NATIVE_UNAVAILABLE");
    if (requireProtection === "os-keystore") fail("PROTECTION_UNAVAILABLE");
    return {name: "webcrypto", protection: "browser-managed", call: null};
  }
  function validKey(key) {
    return key instanceof root.CryptoKey && key.type === "secret" && key.extractable === false
      && key.algorithm?.name === "AES-GCM" && key.algorithm.length === 256
      && key.usages.length === 2 && key.usages.includes("encrypt") && key.usages.includes("decrypt");
  }
  function validateMeta(meta, name, provider) {
    if (!meta) fail("KEY_MISSING");
    if (meta.format !== FORMAT || meta.name !== name || !hexPattern.test(meta.vaultId) || !hexPattern.test(meta.keyId)) fail("FORMAT_UNSUPPORTED");
    if (meta.provider !== provider.name || meta.keyProtection !== provider.protection) fail("PROTECTION_MISMATCH");
    if (meta.hardwareBacked !== null && typeof meta.hardwareBacked !== "boolean") fail("FORMAT_UNSUPPORTED");
    if (provider.name === "webcrypto" && !validKey(meta.key)) fail("KEY_MISSING");
    if (provider.name !== "webcrypto" && Object.hasOwn(meta, "key")) fail("FORMAT_UNSUPPORTED");
    validateEnvelope(meta.check);
  }
  function headerIdentity(meta) {
    return ["DMateOfflineVault", FORMAT, meta.name, meta.vaultId, meta.keyId, meta.provider, meta.keyProtection, meta.hardwareBacked];
  }
  const checkBytes = meta => encoder.encode(JSON.stringify(headerIdentity(meta)));
  const aad = (meta, collection, id, revision) => encoder.encode(JSON.stringify([
    ...headerIdentity(meta), collection, id, revision, "payload-v1"
  ]));
  function validateEnvelope(envelope) {
    if (!envelope || !hexPattern.test(envelope.revision) || bytes(envelope.iv).length !== 12
      || bytes(envelope.ciphertext).length < 16 || bytes(envelope.ciphertext).length > MAX_BYTES + 16) fail("FORMAT_UNSUPPORTED");
  }
  async function encrypt(provider, meta, plaintext, additionalData) {
    try {
      if (provider.call) {
        const result = await provider.call({op: "encrypt", keyId: meta.keyId, plaintext: base64(plaintext), aad: base64(additionalData)});
        const iv = unbase64(result?.iv, 12), ciphertext = unbase64(result?.ciphertext, MAX_BYTES + 16);
        if (iv.length !== 12 || ciphertext.length !== plaintext.length + 16) fail("FORMAT_UNSUPPORTED");
        return {iv, ciphertext: ciphertext.buffer};
      }
      const iv = root.crypto.getRandomValues(new Uint8Array(12));
      const ciphertext = await root.crypto.subtle.encrypt({name: "AES-GCM", iv, additionalData, tagLength: 128}, meta.key, plaintext);
      return {iv, ciphertext};
    } catch (error) { throw safeError(error, "ENCRYPTION_FAILED"); }
  }
  async function decrypt(provider, meta, envelope, additionalData) {
    validateEnvelope(envelope);
    try {
      if (provider.call) {
        const result = await provider.call({op: "decrypt", keyId: meta.keyId, iv: base64(envelope.iv),
          ciphertext: base64(envelope.ciphertext), aad: base64(additionalData)});
        const plaintext = unbase64(result?.plaintext, MAX_BYTES);
        if (plaintext.length !== bytes(envelope.ciphertext).length - 16) fail("AUTHENTICATION_FAILED");
        return plaintext;
      }
      return new Uint8Array(await root.crypto.subtle.decrypt({name: "AES-GCM", iv: bytes(envelope.iv), additionalData, tagLength: 128}, meta.key, envelope.ciphertext));
    } catch (error) { throw safeError(error, "AUTHENTICATION_FAILED"); }
  }
  async function verifyMeta(provider, meta) {
    const clear = await decrypt(provider, meta, meta.check, aad(meta, "_header", "_keycheck", meta.check.revision));
    try { if (!sameBytes(clear, checkBytes(meta))) fail("AUTHENTICATION_FAILED"); }
    finally { clear.fill(0); }
  }
  function matchMeta(current, expected, provider) {
    validateMeta(current, expected.name, provider);
    if (JSON.stringify(headerIdentity(current)) !== JSON.stringify(headerIdentity(expected))
      || current.check.revision !== expected.check.revision || !sameBytes(current.check.iv, expected.check.iv)
      || !sameBytes(current.check.ciphertext, expected.check.ciphertext)) fail("KEY_MISSING");
  }

  function openDatabase() {
    return new Promise((resolve, reject) => {
      let settled = false, request;
      try { request = root.indexedDB.open(DATABASE, FORMAT); }
      catch (_) { reject(new VaultError("STORAGE_UNAVAILABLE")); return; }
      request.onupgradeneeded = () => {
        const db = request.result;
        db.createObjectStore("vaults", {keyPath: "name"});
        const records = db.createObjectStore("records", {keyPath: ["vault", "collection", "id"]});
        records.createIndex("byVault", "vault");
        records.createIndex("byCollection", ["vault", "collection"]);
      };
      request.onblocked = () => { settled = true; reject(new VaultError("STORAGE_BLOCKED")); };
      request.onerror = () => { settled = true; reject(safeError(request.error, "STORAGE_UNAVAILABLE")); };
      request.onsuccess = () => {
        if (settled) { request.result.close(); return; }
        settled = true; resolve(request.result);
      };
    });
  }
  function transact(db, stores, mode, action, active = new Set(), ensureOpen = () => {}) {
    return new Promise((resolve, reject) => {
      let tx, output, error;
      try {
        ensureOpen();
        // Strict durability is a hint where supported, not a promise against
        // browser eviction or the loss of a device/system key store.
        try { tx = db.transaction(stores, mode, mode === "readwrite" ? {durability: "strict"} : {}); }
        catch (first) {
          if (!(first instanceof TypeError)) throw first;
          tx = db.transaction(stores, mode);
        }
      } catch (cause) { reject(safeError(cause, "STORAGE_UNAVAILABLE")); return; }
      active.add(tx);
      const abort = cause => {
        error = safeError(cause);
        try { tx.abort(); } catch (_) { active.delete(tx); reject(error); }
      };
      const guarded = callback => event => { try { callback(event); } catch (cause) { abort(cause); } };
      tx.oncomplete = () => {
        active.delete(tx);
        try { ensureOpen(); resolve(output); } catch (cause) { reject(safeError(cause)); }
      };
      tx.onabort = tx.onerror = () => {
        active.delete(tx);
        try { ensureOpen(); reject(error || safeError(tx.error)); }
        catch (cause) { reject(safeError(cause)); }
      };
      try { action(tx, value => { output = value; }, guarded, abort); }
      catch (cause) { abort(cause); }
    });
  }
  function readInitial(db, name) {
    return transact(db, ["vaults", "records"], "readonly", (tx, result, guard) => {
      const state = {}; result(state);
      tx.objectStore("vaults").get(name).onsuccess = guard(event => { state.meta = event.target.result; });
      tx.objectStore("records").index("byVault").count(name).onsuccess = guard(event => { state.count = event.target.result; });
    });
  }
  async function initialize(db, name, provider) {
    const state = await readInitial(db, name), existing = state.meta;
    if (existing) { validateMeta(existing, name, provider); await verifyMeta(provider, existing); return existing; }
    if (state.count) fail("KEY_MISSING");
    const candidate = {name, format: FORMAT, vaultId: randomId(), keyId: randomId(),
      provider: provider.name, keyProtection: provider.protection, hardwareBacked: null};
    let nativeCreated = false, installed = false;
    try {
      if (provider.call) {
        const result = await provider.call({op: "create", keyId: candidate.keyId});
        nativeCreated = true;
        if (result?.keyId !== candidate.keyId || result.hardwareBacked !== null && typeof result.hardwareBacked !== "boolean") fail("FORMAT_UNSUPPORTED");
        candidate.hardwareBacked = result.hardwareBacked;
      } else {
        candidate.key = await root.crypto.subtle.generateKey({name: "AES-GCM", length: 256}, false, ["encrypt", "decrypt"]);
      }
      const revision = randomId();
      candidate.check = {revision, ...await encrypt(provider, candidate, checkBytes(candidate), aad(candidate, "_header", "_keycheck", revision))};
      // Generation/encryption happen BEFORE the short transaction. This re-read
      // serializes concurrent first opens without overwriting the winning key.
      const selected = await transact(db, ["vaults", "records"], "readwrite", (tx, result, guard) => {
        tx.objectStore("vaults").get(name).onsuccess = guard(event => {
          if (event.target.result) { result(event.target.result); return; }
          tx.objectStore("records").index("byVault").count(name).onsuccess = guard(count => {
            if (count.target.result !== 0) fail("KEY_MISSING");
            tx.objectStore("vaults").add(candidate); result(candidate);
          });
        });
      });
      installed = selected.keyId === candidate.keyId;
      validateMeta(selected, name, provider);
      await verifyMeta(provider, selected);
      return selected;
    } finally {
      // An unused candidate is ours alone. Never delete a committed vault key,
      // including when verification subsequently fails because the OS is locked.
      if (nativeCreated && !installed) {
        try { await provider.call({op: "delete", keyId: candidate.keyId}); } catch (_) { /* At worst an unused OS key remains. */ }
      }
    }
  }

  function makeVault(db, initial, provider) {
    let closed = false;
    const active = new Set();
    const ensureOpen = () => { if (closed) fail("CLOSED"); };
    function close() {
      if (closed) return;
      closed = true;
      for (const tx of active) { try { tx.abort(); } catch (_) {} }
      active.clear(); db.close(); initial = null;
    }
    db.onversionchange = close;
    db.onclose = close;
    const run = (stores, mode, action) => transact(db, stores, mode, action, active, ensureOpen);
    function checkAddress(collection, id) {
      if (typeof collection !== "string" || !collectionPattern.test(collection)
        || typeof id !== "string" || !idPattern.test(id)) fail("INVALID_ARGUMENT");
    }
    async function snapshot(collection, id, all) {
      ensureOpen();
      if (all) { if (typeof collection !== "string" || !collectionPattern.test(collection)) fail("INVALID_ARGUMENT"); }
      else checkAddress(collection, id);
      const snapshot = await run(["vaults", "records"], "readonly", (tx, result, guard) => {
        const data = {}; result(data);
        tx.objectStore("vaults").get(initial.name).onsuccess = guard(event => { data.meta = event.target.result; });
        const records = tx.objectStore("records");
        const request = all ? records.index("byCollection").getAll([initial.name, collection]) : records.get([initial.name, collection, id]);
        request.onsuccess = guard(event => { data.records = all ? event.target.result : event.target.result ? [event.target.result] : []; });
      });
      ensureOpen();
      matchMeta(snapshot.meta, initial, provider);
      await verifyMeta(provider, snapshot.meta); ensureOpen();
      return snapshot;
    }
    async function readRows(collection, id, all) {
      const {meta, records} = await snapshot(collection, id, all), result = [];
      for (const row of records) {
        ensureOpen(); checkAddress(row.collection, row.id);
        if (row.vault !== initial.name || row.collection !== collection || !all && row.id !== id) fail("AUTHENTICATION_FAILED");
        const clear = await decrypt(provider, meta, row, aad(meta, collection, row.id, row.revision));
        try { ensureOpen(); result.push({id: row.id, revision: row.revision, value: decode(clear)}); }
        finally { clear.fill(0); }
      }
      ensureOpen(); return result;
    }
    async function batch(operations) {
      ensureOpen();
      if (!Array.isArray(operations) || operations.length === 0 || operations.length > MAX_BATCH) fail("INVALID_ARGUMENT");
      const addresses = new Set();
      const prepared = operations.map(operation => {
        if (!operation || !["put", "delete"].includes(operation.type)) fail("INVALID_ARGUMENT");
        const {collection, id, expectedRevision} = operation;
        checkAddress(collection, id);
        if (!Object.hasOwn(operation, "expectedRevision") || expectedRevision !== null
          && (typeof expectedRevision !== "string" || !hexPattern.test(expectedRevision))) fail("INVALID_ARGUMENT");
        const address = JSON.stringify([collection, id]);
        if (addresses.has(address)) fail("INVALID_ARGUMENT");
        addresses.add(address);
        return {type: operation.type, collection, id, expectedRevision, value: operation.value};
      });
      const meta = await run("vaults", "readonly", (tx, result, guard) => {
        tx.objectStore("vaults").get(initial.name).onsuccess = guard(event => result(event.target.result));
      });
      ensureOpen();
      matchMeta(meta, initial, provider); await verifyMeta(provider, meta); ensureOpen();
      let total = 0;
      for (const operation of prepared) {
        if (operation.type === "delete") continue;
        const clear = await encode(operation.value); delete operation.value;
        try {
          total += clear.length; if (total > MAX_BATCH_BYTES) fail("TOO_LARGE");
          ensureOpen();
          const revision = randomId();
          operation.row = {vault: initial.name, collection: operation.collection, id: operation.id, revision,
            ...await encrypt(provider, meta, clear, aad(meta, operation.collection, operation.id, revision))};
        } finally { clear.fill(0); }
        ensureOpen();
      }
      return run(["vaults", "records"], "readwrite", (tx, result, guard) => {
        tx.objectStore("vaults").get(initial.name).onsuccess = guard(event => {
          matchMeta(event.target.result, meta, provider);
          const records = tx.objectStore("records");
          let remaining = prepared.length;
          for (const operation of prepared) {
            records.get([initial.name, operation.collection, operation.id]).onsuccess = guard(read => {
              const current = read.target.result;
              if ((current ? current.revision : null) !== operation.expectedRevision) fail("CONFLICT");
              if (current) validateEnvelope(current);
              if (--remaining !== 0) return;
              // All revisions matched inside this transaction before any write.
              for (const op of prepared) {
                if (op.type === "put") records.put(op.row);
                else records.delete([initial.name, op.collection, op.id]);
              }
              result(prepared.map(op => ({collection: op.collection, id: op.id, revision: op.row?.revision || null})));
            });
          }
        });
      });
    }
    return Object.freeze({
      name: initial.name,
      capabilities: Object.freeze({version: FORMAT, provider: provider.name, keyProtection: provider.protection,
        hardwareBacked: initial.hardwareBacked, algorithm: "AES-256-GCM", requiresUserPassword: false, keyExportable: false}),
      async read(collection, id) {
        const rows = await readRows(collection, id, false);
        ensureOpen();
        return rows.length ? {value: rows[0].value, revision: rows[0].revision} : null;
      },
      list(collection) { return readRows(collection, undefined, true); },
      async write(collection, id, value, options) {
        if (!options || !Object.hasOwn(options, "expectedRevision")) fail("INVALID_ARGUMENT");
        const [result] = await batch([{type: "put", collection, id, value, expectedRevision: options.expectedRevision}]);
        ensureOpen();
        return {revision: result.revision};
      },
      async remove(collection, id, options) {
        if (!options || !Object.hasOwn(options, "expectedRevision")) fail("INVALID_ARGUMENT");
        await batch([{type: "delete", collection, id, expectedRevision: options.expectedRevision}]);
        ensureOpen();
      },
      batch, close
    });
  }

  async function open(options = {}) {
    if (!options || typeof options !== "object") fail("INVALID_ARGUMENT");
    const {name = "default", requireProtection} = options;
    if (typeof name !== "string" || !namePattern.test(name)
      || requireProtection !== undefined && !["browser-managed", "os-keystore"].includes(requireProtection)) fail("INVALID_ARGUMENT");
    if (!root.isSecureContext || !root.indexedDB || !root.crypto?.subtle || !root.crypto?.getRandomValues || !root.CryptoKey) fail("ENVIRONMENT_UNSUPPORTED");
    const provider = await selectProvider(requireProtection);
    const db = await openDatabase();
    // Also close connections if a version change occurs while initialization is
    // awaiting a system key prompt, before the public handle exists.
    let versionChanged = false;
    db.onversionchange = () => { versionChanged = true; db.close(); };
    try {
      const meta = await initialize(db, name, provider);
      if (versionChanged) fail("CLOSED");
      return makeVault(db, meta, provider);
    } catch (error) { db.close(); throw safeError(error); }
  }
  root.DMateOfflineVault = Object.freeze({version: FORMAT, open, VaultError,
    limits: Object.freeze({recordBytes: MAX_BYTES, batchBytes: MAX_BATCH_BYTES, batchRecords: MAX_BATCH})});
})(window);
