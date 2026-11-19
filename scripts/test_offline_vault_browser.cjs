/* Exercise the confidentiality API in a real browser, independently of the UI. */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');

let playwright;
try { playwright = require('playwright'); }
catch (error) {
  if (!process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES) throw error;
  playwright = require(path.join(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES, 'playwright'));
}

const browserName = process.env.DMATE_TEST_BROWSER || 'chromium';
assert.ok(['chromium', 'firefox', 'webkit'].includes(browserName), 'Choose a supported Playwright browser');
const sourcePath = path.join(__dirname, '..', 'static', 'offline-vault.js');
const source = fs.readFileSync(sourcePath);
const pageHTML = '<!doctype html><meta charset="utf-8"><title>Vault backend test</title>'
  + '<link rel="icon" href="data:,"><script src="/offline-vault.js"></script>';
const server = http.createServer((request, response) => {
  if (request.url === '/offline-vault.js') {
    response.writeHead(200, {'Content-Type': 'text/javascript; charset=utf-8', 'Cache-Control': 'no-store'});
    response.end(source);
  } else if (request.url === '/' || request.url === '/offline') {
    response.writeHead(200, {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'});
    response.end(pageHTML);
  } else {
    response.writeHead(404); response.end();
  }
});

// Installed before the production script. The module must not depend on a
// server or create a fallback plaintext copy in Web Storage.
function installHarness() {
  const blocked = [];
  const forbidden = name => function () {
    blocked.push(name);
    throw new Error('Forbidden backend side effect: ' + name);
  };
  for (const name of ['fetch', 'XMLHttpRequest', 'WebSocket', 'EventSource']) {
    Object.defineProperty(window, name, {configurable: true, value: forbidden(name)});
  }
  Object.defineProperty(navigator, 'sendBeacon', {configurable: true, value: forbidden('sendBeacon')});
  for (const name of ['localStorage', 'sessionStorage']) {
    Object.defineProperty(window, name, {configurable: true, get: forbidden(name)});
  }
  const originalDecrypt = crypto.subtle.decrypt.bind(crypto.subtle);
  crypto.subtle.decrypt = async (...args) => {
    if (window.__decryptGate) {
      const gate = window.__decryptGate;
      gate.started();
      await gate.released;
    }
    return originalDecrypt(...args);
  };

  function check(value, message) {
    if (!value) throw new Error(message);
  }
  async function expectCode(operation, expected) {
    try { await operation(); }
    catch (error) {
      const allowed = Array.isArray(expected) ? expected : [expected];
      check(allowed.includes(error.code), 'Expected ' + allowed.join('/') + ', got ' + error.code + ': ' + error.message);
      return error.code;
    }
    throw new Error('Operation unexpectedly succeeded; expected ' + expected);
  }
  async function expectRejected(operation) {
    try { await operation(); }
    catch (_) { return; }
    throw new Error('Operation unexpectedly succeeded');
  }
  function rawOperation(storeName, mode, action) {
    return new Promise((resolve, reject) => {
      const opening = indexedDB.open('dmate-offline-vault-v1', 1);
      opening.onerror = () => reject(opening.error);
      opening.onsuccess = () => {
        const db = opening.result;
        const transaction = db.transaction(storeName, mode);
        let request;
        try { request = action(transaction.objectStore(storeName)); }
        catch (error) { transaction.abort(); db.close(); reject(error); return; }
        transaction.oncomplete = () => { db.close(); resolve(request?.result); };
        transaction.onabort = transaction.onerror = () => {
          db.close(); reject(transaction.error || new Error('Raw test transaction failed'));
        };
      };
    });
  }
  window.test = {
    check, expectCode, expectRejected, blocked,
    get: (store, key) => rawOperation(store, 'readonly', objectStore => objectStore.get(key)),
    put: (store, value) => rawOperation(store, 'readwrite', objectStore => objectStore.put(value)),
    delete: (store, key) => rawOperation(store, 'readwrite', objectStore => objectStore.delete(key)),
    records: name => rawOperation('records', 'readonly', objectStore => objectStore.index('byVault').getAll(name)),
  };
}

function installNativeMock(mode) {
  const keys = new Map();
  const counts = {capabilities: 0, create: 0, encrypt: 0, decrypt: 0, delete: 0};
  const decode = value => Uint8Array.from(atob(value), character => character.charCodeAt(0));
  const encode = value => {
    const bytes = value instanceof Uint8Array ? value : new Uint8Array(value);
    let binary = '';
    for (let index = 0; index < bytes.length; index += 8192) {
      binary += String.fromCharCode(...bytes.subarray(index, index + 8192));
    }
    return btoa(binary);
  };
  window.__nativeCounts = counts;
  window.__nativeKeys = keys;
  window.DMateOfflineVaultDesktop = Object.freeze({
    async request(message) {
      counts[message.op]++;
      if (mode === 'unavailable') throw Object.assign(new Error('Keystore unavailable'), {code: 'KEYSTORE_UNAVAILABLE'});
      if (message.op === 'capabilities') return {version: 1, provider: 'desktop-keyring', protection: 'os-keystore', hardwareBacked: null};
      if (message.op === 'create') {
        const keyId = message.keyId;
        keys.set(keyId, await crypto.subtle.generateKey({name: 'AES-GCM', length: 256}, false, ['encrypt', 'decrypt']));
        return {keyId, hardwareBacked: null};
      }
      if (message.op === 'delete') { keys.delete(message.keyId); return {}; }
      const key = keys.get(message.keyId);
      if (!key) throw Object.assign(new Error('Native key missing'), {code: 'KEY_MISSING'});
      if (message.op === 'encrypt') {
        const iv = crypto.getRandomValues(new Uint8Array(12));
        const ciphertext = await crypto.subtle.encrypt({name: 'AES-GCM', iv, additionalData: decode(message.aad), tagLength: 128}, key, decode(message.plaintext));
        return {iv: encode(iv), ciphertext: encode(ciphertext)};
      }
      if (message.op === 'decrypt') {
        try {
          return {plaintext: encode(await crypto.subtle.decrypt({name: 'AES-GCM', iv: decode(message.iv), additionalData: decode(message.aad), tagLength: 128}, key, decode(message.ciphertext)))};
        } catch (_) {
          throw Object.assign(new Error('Native authentication failed'), {code: 'AUTHENTICATION_FAILED'});
        }
      }
      throw Object.assign(new Error('Unknown native operation'), {code: 'INVALID_ARGUMENT'});
    },
  });
}

let browser;
let passed = 0;
async function scenario(title, operation) {
  let timeout;
  try {
    await Promise.race([
      operation(),
      new Promise((_, reject) => { timeout = setTimeout(() => reject(new Error('Timed out: ' + title)), 60000); }),
    ]);
  } finally { clearTimeout(timeout); }
  passed++;
  console.log('PASS ' + title);
}

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const baseURL = 'http://127.0.0.1:' + server.address().port;
  const launchOptions = {headless: true};
  if (process.env.DMATE_BROWSER_EXECUTABLE) launchOptions.executablePath = process.env.DMATE_BROWSER_EXECUTABLE;
  browser = await playwright[browserName].launch(launchOptions);
  const context = await browser.newContext();
  await context.addInitScript(installHarness);
  const page = await context.newPage();
  await page.goto(baseURL);
  await page.waitForFunction(() => Boolean(window.DMateOfflineVault));

  await scenario('JSON and binary values survive encrypted persistence and reopen', async () => {
    await page.evaluate(async () => {
      const {check} = test;
      const vault = await DMateOfflineVault.open({name: 'test-roundtrip'});
      check(vault.name === 'test-roundtrip', 'The handle identifies its vault');
      const value = {text: 'DMATE_PRIVATE_CANARY_保密_∅', nested: [null, true, 17, {proof: '∀x ∃y'}]};
      const initial = await vault.write('notes', 'one', value, {expectedRevision: null});
      check(typeof initial.revision === 'string' && initial.revision.length > 0, 'Writes return an opaque revision');
      check(JSON.stringify((await vault.read('notes', 'one')).value) === JSON.stringify(value), 'JSON round trip');
      await vault.write('assets', 'blob', new Blob(['DMATE_PRIVATE_CANARY_BLOB'], {type: 'text/plain'}), {expectedRevision: null});
      const bytes = new Uint8Array([99, 1, 2, 3, 88]);
      await vault.write('assets', 'typed', bytes.subarray(1, 4), {expectedRevision: null});
      await vault.write('assets', 'buffer', new Uint8Array([4, 5, 6]).buffer, {expectedRevision: null});
      await vault.write('assets', 'empty', new Blob([]), {expectedRevision: null});
      await vault.write('assets', 'nested', {parts: [new Blob(['nested']), new Uint8Array([7, 8])]}, {expectedRevision: null});
      vault.close();
      const reopened = await DMateOfflineVault.open({name: 'test-roundtrip'});
      check((await reopened.read('notes', 'one')).revision === initial.revision, 'Reopen retains revisions');
      const blob = (await reopened.read('assets', 'blob')).value;
      check(blob instanceof Blob && blob.type === 'text/plain' && await blob.text() === 'DMATE_PRIVATE_CANARY_BLOB', 'Blob contents and type survive');
      const typed = (await reopened.read('assets', 'typed')).value;
      check(typed instanceof Uint8Array && String(typed) === '1,2,3', 'Only the typed-array view is serialized');
      const buffer = (await reopened.read('assets', 'buffer')).value;
      check(buffer instanceof ArrayBuffer && String(new Uint8Array(buffer)) === '4,5,6', 'ArrayBuffer survives');
      check((await reopened.read('assets', 'empty')).value.size === 0, 'Empty Blob survives');
      const nested = (await reopened.read('assets', 'nested')).value;
      check(nested.parts[0] instanceof Blob && await nested.parts[0].text() === 'nested'
        && nested.parts[1] instanceof Uint8Array && String(nested.parts[1]) === '7,8', 'Nested binary values retain their types');
      check((await reopened.list('assets')).length === 5, 'Collection lists preserve all records');
      check(await reopened.read('notes', 'missing') === null, 'A missing record is null');
      check(test.blocked.length === 0, 'No network or Web Storage calls occurred before reload');
      reopened.close();
    });
    await page.reload();
    await page.evaluate(async () => {
      const vault = await DMateOfflineVault.open({name: 'test-roundtrip'});
      test.check((await vault.read('notes', 'one')).value.text === 'DMATE_PRIVATE_CANARY_保密_∅', 'Actual document reload preserves keys and data');
      vault.close();
    });
  });

  await scenario('Stored payloads are ciphertext and browser keys cannot be exported', async () => {
    await page.evaluate(async () => {
      const {check} = test;
      const meta = await test.get('vaults', 'test-roundtrip');
      check(meta.provider === 'webcrypto' && meta.keyProtection === 'browser-managed', 'Web key protection is described honestly');
      check(meta.key instanceof CryptoKey && meta.key.extractable === false, 'The persisted key stays nonextractable');
      check(meta.key.algorithm.name === 'AES-GCM' && meta.key.algorithm.length === 256, 'The stored key is AES-256-GCM');
      await test.expectRejected(() => crypto.subtle.exportKey('raw', meta.key));
      const records = await test.records('test-roundtrip');
      const seenIVs = new Set();
      for (const row of records) {
        check(row.iv instanceof Uint8Array && row.iv.length === 12, 'Each record uses a 96-bit IV');
        check(row.ciphertext instanceof ArrayBuffer && row.ciphertext.byteLength >= 16, 'Ciphertext includes an authentication tag');
        check(!JSON.stringify(row).includes('DMATE_PRIVATE_CANARY'), 'No plaintext payload field is stored');
        check(!new TextDecoder().decode(row.ciphertext).includes('DMATE_PRIVATE_CANARY'), 'Stored bytes do not contain the canary');
        seenIVs.add(String(row.iv));
      }
      check(seenIVs.size === records.length, 'Independent writes receive different IVs');
      check(!JSON.stringify(meta).includes('DMATE_PRIVATE_CANARY'), 'Metadata contains no private payload');
    });
  });

  await scenario('Concurrent first opens and cross-page writes preserve one vault key', async () => {
    const other = await context.newPage();
    await other.goto(baseURL);
    const open = target => target.evaluate(async () => { window.raceVault = await DMateOfflineVault.open({name: 'test-race'}); });
    await Promise.all([open(page), open(other)]);
    const write = (target, value) => target.evaluate(async value => {
      try { return {ok: true, result: await raceVault.write('notes', 'shared', value, {expectedRevision: null}), value}; }
      catch (error) { return {ok: false, code: error.code}; }
    }, value);
    const outcomes = await Promise.all([write(page, 'first'), write(other, 'second')]);
    const winner = outcomes.find(outcome => outcome.ok);
    assert.equal(outcomes.filter(outcome => outcome.ok).length, 1, 'Exactly one create-only write wins');
    assert.equal(outcomes.find(outcome => !outcome.ok).code, 'CONFLICT');
    for (const target of [page, other]) {
      const saved = await target.evaluate(() => raceVault.read('notes', 'shared'));
      assert.equal(saved.value, winner.value);
      assert.equal(saved.revision, winner.result.revision);
    }
    assert.deepEqual(await other.evaluate(() => test.blocked), [], 'The second page made no network or Web Storage calls');
    await other.close();
    await page.evaluate(() => raceVault.close());
  });

  await scenario('Compare-and-swap and batches are atomic, including delete/recreate', async () => {
    await page.evaluate(async () => {
      const {check, expectCode} = test;
      const vault = await DMateOfflineVault.open({name: 'test-transactions'});
      const first = await vault.write('notes', 'one', 'original', {expectedRevision: null});
      await expectCode(() => vault.write('notes', 'one', 'wrong', {expectedRevision: null}), 'CONFLICT');
      await expectCode(() => vault.remove('notes', 'one', {expectedRevision: null}), 'CONFLICT');
      await expectCode(() => vault.batch([
        {type: 'put', collection: 'notes', id: 'new', value: 'must roll back', expectedRevision: null},
        {type: 'put', collection: 'notes', id: 'one', value: 'stale', expectedRevision: '0'.repeat(32)},
      ]), 'CONFLICT');
      check(await vault.read('notes', 'new') === null, 'A failed batch writes none of its records');
      check((await vault.read('notes', 'one')).value === 'original', 'Conflicts preserve the previous payload');
      const committed = await vault.batch([
        {type: 'put', collection: 'notes', id: 'two', value: 'second', expectedRevision: null},
        {type: 'delete', collection: 'notes', id: 'one', expectedRevision: first.revision},
      ]);
      check(committed.length === 2 && committed[0].revision && committed[1].revision === null, 'Batch reports each committed revision');
      check(await vault.read('notes', 'one') === null, 'The batch delete committed');
      const recreated = await vault.write('notes', 'one', 'recreated', {expectedRevision: null});
      check(recreated.revision !== first.revision, 'Recreation never reuses a previous revision');
      await expectCode(() => vault.write('notes', 'one', 'stale-aba', {expectedRevision: first.revision}), 'CONFLICT');
      await test.expectRejected(() => vault.write('notes', 'one', 'unguarded'));
      check((await vault.read('notes', 'one')).value === 'recreated', 'Missing expectedRevision does not silently overwrite');
      await vault.remove('notes', 'absent', {expectedRevision: null});
      vault.close();
    });
  });

  await scenario('Ciphertext changes and record/collection/vault swaps are rejected', async () => {
    await page.evaluate(async () => {
      const {expectCode} = test;
      const name = 'test-tamper';
      const vault = await DMateOfflineVault.open({name});
      await vault.write('notes', 'a', 'alpha', {expectedRevision: null});
      await vault.write('notes', 'b', 'bravo', {expectedRevision: null});
      const original = await test.get('records', [name, 'notes', 'a']);
      const other = await test.get('records', [name, 'notes', 'b']);
      const damaged = new Uint8Array(original.ciphertext.slice(0)); damaged[0] ^= 1;
      await test.put('records', {...original, ciphertext: damaged.buffer});
      await expectCode(() => vault.read('notes', 'a'), 'AUTHENTICATION_FAILED');
      await test.put('records', {...original, iv: other.iv, ciphertext: other.ciphertext});
      await expectCode(() => vault.read('notes', 'a'), 'AUTHENTICATION_FAILED');
      await test.put('records', {...original, collection: 'mistakes'});
      await expectCode(() => vault.read('mistakes', 'a'), 'AUTHENTICATION_FAILED');
      await test.put('records', original);
      const second = await DMateOfflineVault.open({name: 'test-other-vault'});
      await test.put('records', {...original, vault: 'test-other-vault'});
      await expectCode(() => second.read('notes', 'a'), 'AUTHENTICATION_FAILED');
      test.check((await vault.read('notes', 'a')).value === 'alpha', 'Restoring authentic ciphertext restores the record');
      second.close(); vault.close();
    });
  });

  await scenario('Missing keys and corrupted vault authentication never reset data', async () => {
    await page.evaluate(async () => {
      const name = 'test-key-loss';
      let vault = await DMateOfflineVault.open({name});
      await vault.write('notes', 'one', 'keep-this-ciphertext', {expectedRevision: null});
      vault.close();
      const meta = await test.get('vaults', name);
      const original = await test.get('records', [name, 'notes', 'one']);
      const missing = {...meta}; delete missing.key;
      await test.put('vaults', missing);
      await test.expectCode(() => DMateOfflineVault.open({name}), 'KEY_MISSING');
      test.check(!(await test.get('vaults', name)).key, 'The missing key is not silently regenerated');
      const remaining = await test.get('records', [name, 'notes', 'one']);
      test.check(String(new Uint8Array(remaining.ciphertext)) === String(new Uint8Array(original.ciphertext)), 'Key failure preserves ciphertext');
      await test.delete('vaults', name);
      await test.expectCode(() => DMateOfflineVault.open({name}), 'KEY_MISSING');
      test.check(await test.get('vaults', name) === undefined, 'Orphan ciphertext prevents new metadata creation');
      const broken = new Uint8Array(meta.check.ciphertext.slice(0)); broken[0] ^= 1;
      await test.put('vaults', {...meta, check: {...meta.check, ciphertext: broken.buffer}});
      await test.expectCode(() => DMateOfflineVault.open({name}), 'AUTHENTICATION_FAILED');
      await test.put('vaults', meta);
      vault = await DMateOfflineVault.open({name});
      test.check((await vault.read('notes', 'one')).value === 'keep-this-ciphertext', 'Failure does not destroy the recoverable original');
      vault.close();
    });
  });

  await scenario('Transaction aborts cannot report success or leave partial writes', async () => {
    await page.evaluate(async () => {
      const vault = await DMateOfflineVault.open({name: 'test-abort'});
      const originals = {};
      for (const method of ['put', 'add']) {
        originals[method] = IDBObjectStore.prototype[method];
        IDBObjectStore.prototype[method] = function (...args) {
          const request = originals[method].apply(this, args);
          if (this.name === 'records') {
            const transaction = this.transaction;
            request.addEventListener('success', () => transaction.abort(), {once: true});
          }
          return request;
        };
      }
      try {
        await test.expectRejected(() => vault.batch([
          {type: 'put', collection: 'notes', id: 'a', value: 'no commit', expectedRevision: null},
          {type: 'put', collection: 'notes', id: 'b', value: 'no partial commit', expectedRevision: null},
        ]));
      } finally {
        for (const method of Object.keys(originals)) IDBObjectStore.prototype[method] = originals[method];
      }
      test.check((await vault.list('notes')).length === 0, 'An aborted transaction committed no record');
      vault.close();
    });
  });

  await scenario('Closing rejects in-flight plaintext and future operations', async () => {
    await page.evaluate(async () => {
      const vault = await DMateOfflineVault.open({name: 'test-close'});
      await vault.write('notes', 'one', 'must not be returned after close', {expectedRevision: null});
      let started, release;
      const began = new Promise(resolve => { started = resolve; });
      window.__decryptGate = {started, released: new Promise(resolve => { release = resolve; })};
      const pending = vault.read('notes', 'one');
      const checked = test.expectCode(() => pending, 'CLOSED');
      await began;
      vault.close();
      release();
      try { await checked; }
      finally { delete window.__decryptGate; }
      await test.expectCode(() => vault.read('notes', 'one'), 'CLOSED');
      await test.expectCode(() => vault.list('notes'), 'CLOSED');
      await test.expectCode(() => vault.write('notes', 'two', 'closed', {expectedRevision: null}), 'CLOSED');
      await test.expectCode(() => vault.remove('notes', 'one', {expectedRevision: null}), 'CLOSED');
    });
  });

  await scenario('Destroy removes only its vault and prevents stale writers', async () => {
    await page.evaluate(async () => {
      const removed = await DMateOfflineVault.open({name:'test-destroy'});
      const stale = await DMateOfflineVault.open({name:'test-destroy'});
      const retained = await DMateOfflineVault.open({name:'test-retained'});
      await removed.write('notes', 'one', 'remove this guest record', {expectedRevision:null});
      await retained.write('notes', 'one', 'retain another vault', {expectedRevision:null});
      const original = await test.get('vaults', 'test-destroy');
      const changed = structuredClone(original); changed.check.revision = 'f'.repeat(original.check.revision.length);
      await test.put('vaults', changed);
      await test.expectRejected(() => removed.destroy());
      test.check((await test.records('test-destroy')).length === 1, 'Changed vault metadata prevents destructive cleanup');
      await test.put('vaults', original);
      await removed.destroy();
      await test.expectCode(() => removed.list('notes'), 'CLOSED');
      await test.expectRejected(() => stale.write('notes', 'two', 'cannot resurrect', {expectedRevision:null}));
      test.check((await retained.read('notes', 'one')).value === 'retain another vault', 'Destroy leaves other vaults intact');
      test.check(await test.get('vaults', 'test-destroy') === undefined, 'Guest key metadata is removed after commit');
      stale.close(); retained.close();
    });
  });

  await scenario('A strict OS-keystore requirement cannot fall back to browser keys', async () => {
    await page.evaluate(async () => {
      await test.expectCode(() => DMateOfflineVault.open({name: 'test-strict', requireProtection: 'os-keystore'}), 'PROTECTION_UNAVAILABLE');
      test.check(await test.get('vaults', 'test-strict') === undefined, 'A refused protection level does not create a weak vault');
      test.check(test.blocked.length === 0, 'No network or Web Storage calls occurred');
    });
  });

  await scenario('Native shells fail closed when the expected bridge is absent', async () => {
    const nativeContext = await browser.newContext({userAgent: 'DMateDesktop/1.0.2'});
    try {
      await nativeContext.addInitScript(installHarness);
      const nativePage = await nativeContext.newPage(); await nativePage.goto(baseURL + '/offline');
      await nativePage.evaluate(async () => {
        await test.expectCode(() => DMateOfflineVault.open({name: 'test-missing-bridge'}), 'NATIVE_UNAVAILABLE');
        test.check(test.blocked.length === 0, 'An absent bridge does not cause network/Storage fallback');
      });
    } finally { await nativeContext.close(); }
  });

  await scenario('A failing native keystore never creates a browser key as a fallback', async () => {
    const nativeContext = await browser.newContext({userAgent: 'DMateDesktop/1.0.2'});
    try {
      await nativeContext.addInitScript(installHarness);
      await nativeContext.addInitScript(installNativeMock, 'unavailable');
      const nativePage = await nativeContext.newPage(); await nativePage.goto(baseURL + '/offline');
      await nativePage.evaluate(async () => {
        await test.expectCode(() => DMateOfflineVault.open({name: 'test-native-unavailable'}), 'KEYSTORE_UNAVAILABLE');
        test.check(__nativeCounts.capabilities > 0, 'The native capability check was actually attempted');
        test.check(__nativeCounts.create === 0, 'No native key was created after capability failure');
        test.check(test.blocked.length === 0, 'A failed keystore does not invoke fallback side effects');
      });
    } finally { await nativeContext.close(); }
  });

  await scenario('Native bridge delegation persists ciphertext without a browser key', async () => {
    const nativeContext = await browser.newContext({userAgent: 'DMateDesktop/1.0.2'});
    try {
      await nativeContext.addInitScript(installHarness);
      await nativeContext.addInitScript(installNativeMock, 'working');
      const nativePage = await nativeContext.newPage(); await nativePage.goto(baseURL + '/offline');
      await nativePage.evaluate(async () => {
        const vault = await DMateOfflineVault.open({name: 'test-native', requireProtection: 'os-keystore'});
        await vault.write('notes', 'one', {text: 'native confidentiality'}, {expectedRevision: null});
        test.check((await vault.read('notes', 'one')).value.text === 'native confidentiality', 'Native provider encrypts and decrypts');
        const meta = await test.get('vaults', 'test-native');
        test.check(meta.provider === 'desktop-keyring' && meta.keyProtection === 'os-keystore', 'The provider is persisted');
        test.check(!Object.prototype.hasOwnProperty.call(meta, 'key'), 'Native metadata contains no browser CryptoKey');
        test.check(__nativeCounts.create === 1 && __nativeCounts.encrypt >= 2 && __nativeCounts.decrypt >= 1, 'Cryptographic work reached the bridge');
        // A supported large record must not overflow the base64 validator's
        // regular-expression stack or unexpectedly exceed the native envelope.
        const large = new Uint8Array(13 * 1024 * 1024); large.fill(83);
        await vault.write('assets', 'large', large, {expectedRevision: null});
        const decoded = (await vault.read('assets', 'large')).value;
        test.check(decoded instanceof Uint8Array && decoded.length === large.length
          && decoded.every(byte => byte === 83), 'Large native records round trip within the advertised limit');
        vault.close();
        __nativeKeys.clear();
        await test.expectCode(() => DMateOfflineVault.open({name: 'test-native'}), 'KEY_MISSING');
        test.check(__nativeCounts.create === 1, 'A missing native key is not silently replaced');
        test.check((await test.records('test-native')).length === 2, 'Native key loss preserves ciphertext');
        const cleanup = await DMateOfflineVault.open({name:'test-native-delete', requireProtection:'os-keystore'});
        await cleanup.write('notes', 'temporary', 'remove native guest data', {expectedRevision:null});
        const cleanupMeta = await test.get('vaults', 'test-native-delete');
        await cleanup.destroy();
        test.check(__nativeCounts.delete === 1 && !__nativeKeys.has(cleanupMeta.keyId), 'Native guest cleanup releases its key after deleting ciphertext');
        test.check((await test.records('test-native-delete')).length === 0 && !await test.get('vaults','test-native-delete'), 'Native cleanup commits metadata and records together');
        test.check(test.blocked.length === 0, 'Native storage performs no network or Web Storage side effects');
      });
    } finally { await nativeContext.close(); }
  });

  await context.close();
  console.log('Offline vault: ' + passed + ' scenarios passed in ' + browserName + '.');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
}).finally(async () => {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
});
