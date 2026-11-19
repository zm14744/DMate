/* Short-lived encrypted navigation transport; business persistence belongs to
 * DMateOfflineVault. This module never requests native keys or uses a network.
 */
(function (root) {
  'use strict';
  const DATABASE = 'dmate-offline-handoff-v1', TOKEN_KEY = 'dmate_offline_handoff_token_v1';
  const FORMAT = 1, CHUNK_BYTES = 4 * 1024 * 1024, MAX_BYTES = 128 * 1024 * 1024;
  const TTL = 30 * 60 * 1000, MAX_STAGES = 32;
  const encoder = new TextEncoder(), decoder = new TextDecoder('utf-8', {fatal:true});
  const tokenPattern = /^[a-f0-9]{64}$/;
  let opening = null;
  const messages = {
    UNAVAILABLE:'离线交接存储不可用，请稍后重试',
    INVALID:'离线交接数据无法读取，原数据仍保留',
    MISSING:'离线交接已过期或不存在，请返回在线版重新打开',
    EXPIRED:'离线交接已过期，请返回在线版重新打开',
    OWNER_CHANGED:'账号或标签页已变化，请重新打开离线版',
    TOO_LARGE:'离线交接内容过大，请减少绘图后重试',
    FULL:'待完成的离线交接较多，请完成已有交接后重试',
    SAVE_FAILED:'离线交接未能保存，当前内容仍保留，请检查设备存储空间'
  };
  function fail(code) {
    throw Object.assign(new Error(messages[code] || messages.INVALID), {code:'HANDOFF_' + code});
  }
  const isHandoffError = error => typeof error?.code === 'string' && error.code.startsWith('HANDOFF_');
  function currentOwner() {
    if (root.DMateGuestSession?.getOwner) return String(root.DMateGuestSession.getOwner() || '');
    const data = root.document?.documentElement?.dataset;
    return data?.accountAuthenticated === '1' ? String(data.accountUsername || '') : '';
  }
  function tabIdentity() {
    if (!root.name) root.name = 'dmate-handoff-tab:' + randomToken();
    return String(root.name);
  }
  function randomToken() {
    return Array.from(root.crypto.getRandomValues(new Uint8Array(32)), value => value.toString(16).padStart(2,'0')).join('');
  }
  function ensureEnvironment() {
    if (!root.isSecureContext || !root.crypto?.subtle || !root.indexedDB || !root.CryptoKey) fail('UNAVAILABLE');
  }
  function checkCurrent(owner, tab, options) {
    if (currentOwner() !== owner || tabIdentity() !== tab || options?.isCurrent && !options.isCurrent()) fail('OWNER_CHANGED');
  }
  function database() {
    ensureEnvironment();
    if (!opening) opening = new Promise((resolve, reject) => {
      const request = root.indexedDB.open(DATABASE, 1);
      let blocked = false;
      request.onupgradeneeded = () => {
        const db = request.result;
        db.createObjectStore('stages', {keyPath:'token'});
        db.createObjectStore('chunks', {keyPath:['token','index']}).createIndex('token','token');
      };
      request.onblocked = () => { blocked = true; opening = null; reject(Object.assign(new Error(messages.UNAVAILABLE), {code:'HANDOFF_UNAVAILABLE'})); };
      request.onerror = () => { opening = null; reject(Object.assign(new Error(messages.UNAVAILABLE), {code:'HANDOFF_UNAVAILABLE'})); };
      request.onsuccess = () => {
        const db = request.result;
        if (blocked) { db.close(); return; }
        db.onversionchange = () => { db.close(); opening = null; };
        resolve(db);
      };
    });
    return opening;
  }
  async function transaction(mode, body) {
    const db = await database();
    return new Promise((resolve,reject) => {
      let result;
      const tx = db.transaction(['stages','chunks'],mode);
      const abort = error => {
        try { tx.abort(); } catch (_) {}
        reject(isHandoffError(error) ? error : Object.assign(new Error(messages.SAVE_FAILED), {code:'HANDOFF_SAVE_FAILED'}));
      };
      const guard = callback => (...args) => { try { callback(...args); } catch (error) { abort(error); } };
      tx.oncomplete = () => resolve(result);
      tx.onerror = tx.onabort = () => reject(Object.assign(new Error(messages.SAVE_FAILED), {code:'HANDOFF_SAVE_FAILED'}));
      try { body(tx, value => { result = value; }, guard); }
      catch (error) { abort(error); }
    });
  }
  const aad = (token,index) => encoder.encode(JSON.stringify(['dmate-offline-handoff',FORMAT,token,index]));
  async function encrypt(key,token,index,value) {
    const iv = root.crypto.getRandomValues(new Uint8Array(12));
    const ciphertext = await root.crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:aad(token,index)},key,value);
    return {iv,ciphertext};
  }
  async function decrypt(row,token,index,envelope) {
    if (!(row.key instanceof root.CryptoKey) || row.key.extractable || !envelope?.iv || !envelope?.ciphertext) fail('INVALID');
    try { return new Uint8Array(await root.crypto.subtle.decrypt({name:'AES-GCM',iv:envelope.iv,additionalData:aad(token,index)},row.key,envelope.ciphertext)); }
    catch (_) { fail('INVALID'); }
  }
  // JSON tags and binary lengths are themselves encrypted. Blob bytes are read
  // one chunk at a time and never encoded as a plaintext data URL.
  function encode(value) {
    const parts = [], ancestors = new Set();
    let binaryBytes = 0, textUnits = 0, nodes = 0;
    const part = blob => { binaryBytes += blob.size; if (binaryBytes > MAX_BYTES) fail('TOO_LARGE'); parts.push(blob); return parts.length - 1; };
    function visit(item,depth) {
      if (++nodes > 400000 || depth > 64) fail('TOO_LARGE');
      if (item === null) return ['null'];
      if (item === undefined) return ['undefined'];
      if (typeof item === 'string') { textUnits+=item.length; if(textUnits+binaryBytes>MAX_BYTES)fail('TOO_LARGE'); return ['string',item]; }
      if (typeof item === 'boolean') return ['boolean',item];
      if (typeof item === 'number' && Number.isFinite(item)) return ['number',Object.is(item,-0)?'-0':item];
      if (item instanceof Blob) {
        const file = root.File && item instanceof root.File;
        return [file?'file':'blob',part(item),item.type,file?item.name:'',file?item.lastModified:0];
      }
      if (item instanceof ArrayBuffer || item instanceof Uint8Array)
        return [item instanceof ArrayBuffer?'buffer':'bytes',part(new Blob([item]))];
      if (!item || typeof item !== 'object' || ancestors.has(item) || Object.getOwnPropertySymbols(item).length) fail('INVALID');
      const prototype = Object.getPrototypeOf(item);
      if (Array.isArray(item)?prototype!==Array.prototype:prototype!==Object.prototype&&prototype!==null) fail('INVALID');
      if (Array.isArray(item)&&item.length>400000) fail('TOO_LARGE');
      ancestors.add(item);
      const result = Array.isArray(item) ? ['array',Array.from({length:item.length},(_,i) => {
        const descriptor = Object.getOwnPropertyDescriptor(item,String(i));
        if (descriptor && !Object.hasOwn(descriptor,'value')) fail('INVALID');
        return visit(descriptor?.value,depth+1);
      })] : ['object',Object.keys(item).map(key => {
        textUnits+=key.length; if(textUnits+binaryBytes>MAX_BYTES)fail('TOO_LARGE');
        const descriptor = Object.getOwnPropertyDescriptor(item,key);
        if (!Object.hasOwn(descriptor,'value')) fail('INVALID');
        return [key,visit(descriptor.value,depth+1)];
      })];
      ancestors.delete(item); return result;
    }
    const tree = visit(value,0), header = encoder.encode(JSON.stringify({format:FORMAT,tree,lengths:parts.map(blob=>blob.size)}));
    if (header.length + binaryBytes + 4 > MAX_BYTES) fail('TOO_LARGE');
    const length = new Uint8Array(4); new DataView(length.buffer).setUint32(0,header.length,false);
    return new Blob([length,header,...parts]);
  }
  function decode(input) {
    try {
      if (input.length < 4 || input.length > MAX_BYTES) fail('INVALID');
      const length = new DataView(input.buffer,input.byteOffset,input.byteLength).getUint32(0,false);
      if (length > input.length - 4) fail('INVALID');
      const header = JSON.parse(decoder.decode(input.subarray(4,4+length)));
      if (header.format !== FORMAT || !Array.isArray(header.lengths)) fail('INVALID');
      let offset = 4 + length, nodes = 0;
      const binary = header.lengths.map(size => {
        if (!Number.isSafeInteger(size) || size < 0 || size > input.length-offset) fail('INVALID');
        const bytes = input.subarray(offset,offset+size); offset+=size; return bytes;
      });
      if (offset !== input.length) fail('INVALID');
      function visit(item,depth) {
        if (++nodes>400000 || depth>64 || !Array.isArray(item)) fail('INVALID');
        const [tag,value] = item;
        if (tag==='null'&&item.length===1) return null;
        if (tag==='undefined'&&item.length===1) return undefined;
        if (tag==='string'&&typeof value==='string'||tag==='boolean'&&typeof value==='boolean') return value;
        if (tag==='number'&&(value==='-0'||typeof value==='number'&&Number.isFinite(value))) return value==='-0'?-0:value;
        if (tag==='array'&&Array.isArray(value)) return value.map(child=>visit(child,depth+1));
        if (tag==='object'&&Array.isArray(value)) {
          const result = {};
          for (const pair of value) {
            if (!Array.isArray(pair)||pair.length!==2||typeof pair[0]!=='string'||Object.hasOwn(result,pair[0])) fail('INVALID');
            Object.defineProperty(result,pair[0],{value:visit(pair[1],depth+1),enumerable:true,writable:true,configurable:true});
          }
          return result;
        }
        if (!Number.isSafeInteger(value)||!binary[value]) fail('INVALID');
        if (tag==='blob') return new Blob([binary[value]],{type:item[2]});
        if (tag==='file') return new File([binary[value]],item[3],{type:item[2],lastModified:item[4]});
        if (tag==='buffer') return binary[value].slice().buffer;
        if (tag==='bytes') return binary[value].slice();
        fail('INVALID');
      }
      return visit(header.tree,0);
    } catch (error) { if (isHandoffError(error)) throw error; fail('INVALID'); }
  }
  async function stageRow(token) {
    if (!tokenPattern.test(token || '')) fail('MISSING');
    return transaction('readonly',(tx,done) => { const request=tx.objectStore('stages').get(token); request.onsuccess=()=>done(request.result); });
  }
  async function metadata(row) {
    if (!row || !tokenPattern.test(row.token)) fail('MISSING');
    const clear = await decrypt(row,row.token,'meta',row.meta);
    try {
      const value = JSON.parse(decoder.decode(clear));
      if (value.format!==FORMAT || typeof value.owner!=='string' || typeof value.tab!=='string'
        || !Number.isFinite(value.expires) || !Number.isSafeInteger(value.size) || value.size<4 || value.size>MAX_BYTES
        || value.chunks!==Math.ceil(value.size/CHUNK_BYTES)) fail('INVALID');
      return value;
    } catch (error) { if (isHandoffError(error)) throw error; fail('INVALID'); }
    finally { clear.fill(0); }
  }
  async function removeRaw(token) {
    return transaction('readwrite',(tx,done,guard) => {
      tx.objectStore('stages').delete(token);
      const request = tx.objectStore('chunks').index('token').openCursor(token);
      request.onsuccess = guard(() => { const cursor=request.result; if(cursor){cursor.delete();cursor.continue();} });
      done(true);
    });
  }
  async function cleanupExpired() {
    const rows = await transaction('readonly',(tx,done) => { const request=tx.objectStore('stages').getAll(); request.onsuccess=()=>done(request.result); });
    for (const row of rows) {
      let meta; try { meta=await metadata(row); } catch (_) { continue; }
      if (meta.expires<=Date.now()) await removeRaw(row.token);
    }
  }
  async function stage(value,options={}) {
    ensureEnvironment();
    const owner = String(value?.username || ''), tab=tabIdentity();
    checkCurrent(owner,tab,options);
    const payload = encode(value), token=randomToken();
    const key = await root.crypto.subtle.generateKey({name:'AES-GCM',length:256},false,['encrypt','decrypt']);
    const meta = {format:FORMAT,owner,tab,expires:Date.now()+TTL,size:payload.size,chunks:Math.ceil(payload.size/CHUNK_BYTES)};
    const chunks = [];
    for(let index=0;index<meta.chunks;index++) {
      checkCurrent(owner,tab,options);
      const clear=new Uint8Array(await payload.slice(index*CHUNK_BYTES,(index+1)*CHUNK_BYTES).arrayBuffer());
      try { chunks.push({token,index,...await encrypt(key,token,index,clear)}); }
      finally { clear.fill(0); }
    }
    const row={token,key,meta:await encrypt(key,token,'meta',encoder.encode(JSON.stringify(meta)))};
    checkCurrent(owner,tab,options);
    await cleanupExpired();
    await transaction('readwrite',(tx,done,guard) => {
      const request=tx.objectStore('stages').count();
      request.onsuccess=guard(()=>{
        if(request.result>=MAX_STAGES)fail('FULL');
        tx.objectStore('stages').add(row);
        for(const chunk of chunks)tx.objectStore('chunks').add(chunk);
        done(true);
      });
    });
    try {
      checkCurrent(owner,tab,options);
      const previous = pendingToken();
      root.sessionStorage.setItem(TOKEN_KEY,token);
      if (previous && previous!==token) void removeRaw(previous).catch(()=>{});
    } catch (error) { await removeRaw(token).catch(()=>{}); throw isHandoffError(error) ? error : Object.assign(new Error(messages.SAVE_FAILED),{code:'HANDOFF_SAVE_FAILED'}); }
    return token;
  }
  async function read(token,options={}) {
    ensureEnvironment();
    const owner=currentOwner(), tab=tabIdentity(), row=await stageRow(token), meta=await metadata(row);
    checkCurrent(owner,tab,options);
    if(meta.owner!==owner||meta.tab!==tab)fail('OWNER_CHANGED');
    if(meta.expires<=Date.now())fail('EXPIRED');
    const chunks=await transaction('readonly',(tx,done)=>{const request=tx.objectStore('chunks').index('token').getAll(token);request.onsuccess=()=>done(request.result);});
    if(chunks.length!==meta.chunks)fail('INVALID');
    chunks.sort((a,b)=>a.index-b.index);
    const output=new Uint8Array(meta.size);
    try {
      for(let index=0;index<chunks.length;index++) {
        if(chunks[index].index!==index)fail('INVALID');
        const clear=await decrypt(row,token,index,chunks[index]);
        try { if(clear.length!==Math.min(CHUNK_BYTES,meta.size-index*CHUNK_BYTES))fail('INVALID'); output.set(clear,index*CHUNK_BYTES); }
        finally { clear.fill(0); }
        checkCurrent(owner,tab,options);
      }
      const value=decode(output);
      if(value?.username!==owner)fail('OWNER_CHANGED');
      checkCurrent(owner,tab,options); return value;
    } finally { output.fill(0); }
  }
  async function ack(token) {
    const row=await stageRow(token);
    if(row){const meta=await metadata(row);if(meta.owner!==currentOwner()||meta.tab!==tabIdentity())fail('OWNER_CHANGED');}
    await removeRaw(token);
    try { if(pendingToken()===token)root.sessionStorage.removeItem(TOKEN_KEY); } catch (_) {}
    return true;
  }
  function pendingToken() {
    try { const value=root.sessionStorage.getItem(TOKEN_KEY); return tokenPattern.test(value||'')?value:null; }
    catch (_) { return null; }
  }
  root.DMateOfflineHandoff=Object.freeze({stage,read,ack,pendingToken});
}(window));
