/* Portable study backups. ZIP and all attachment processing stay on device. */
(() => {
  'use strict';
  const root = typeof window === 'undefined' ? globalThis : window;
  const encoder = new TextEncoder(), decoder = new TextDecoder('utf-8',{fatal:true});
  const MAX_ARCHIVE = 100 * 1024 * 1024, MAX_CONTENT = 64 * 1024 * 1024;
  const MAX_RECORD = 16 * 1024 * 1024, MAX_FILES = 4096;
  const marker = '$dmateBackup';
  const own = (value,key) => Object.prototype.hasOwnProperty.call(value,key);
  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  function fail(code = 'BACKUP_INVALID') {
    const messages = {
      BACKUP_INVALID:'备份包不完整、已损坏或内容格式不正确，原数据未更改',
      BACKUP_TOO_LARGE:'备份包内容超过支持的大小，原数据未更改',
      BACKUP_UNSUPPORTED:'不支持此备份格式或版本，请选择 DMate 导出的 ZIP 包'
    };
    throw Object.assign(new Error(messages[code]),{code});
  }
  function library() {
    if (!root.fflate?.zipSync || !root.fflate?.unzipSync || !root.crypto?.subtle) fail('BACKUP_UNSUPPORTED');
    return root.fflate;
  }
  async function digest(bytes) {
    if (!root.crypto?.subtle) fail('BACKUP_UNSUPPORTED');
    return [...new Uint8Array(await root.crypto.subtle.digest('SHA-256',bytes))]
      .map(value => value.toString(16).padStart(2,'0')).join('');
  }
  const validId = id => typeof id === 'string' && id.length > 0 && id.length <= 4096;
  function validateRows(rows,kind) {
    if (!Array.isArray(rows) || rows.length > 100000) fail('BACKUP_INVALID');
    const ids = new Set();
    for (const row of rows) {
      if (!object(row) || !validId(row.id) || ids.has(row.id)) fail();
      ids.add(row.id);
      if (kind === 'notes') {
        if (typeof row.title !== 'string' || typeof row.content !== 'string') fail();
      } else if (typeof row.statement !== 'string'
        || row.answer !== undefined && typeof row.answer !== 'string'
        || row.explanation !== undefined && typeof row.explanation !== 'string') fail();
    }
  }
  function validateGallery(gallery) {
    if (gallery === null) return;
    if (!object(gallery) || ![1,2].includes(gallery.version) || !Array.isArray(gallery.pages)) fail();
    const ids = new Set();
    let count = 0;
    for (const page of gallery.pages) {
      const graphs = page?.document?.graphs;
      if (!object(page) || !validId(page.id) || ids.has(page.id) || !Array.isArray(graphs) || !graphs.length
        || graphs.some(graph => !object(graph) || !Array.isArray(graph.vertices) || !Array.isArray(graph.edges))) fail();
      ids.add(page.id);
      count += graphs.length;
      if (count > 50) fail('BACKUP_TOO_LARGE');
    }
  }
  function validate(data) {
    if (!object(data)) fail();
    validateRows(data.notes,'notes'); validateRows(data.mistakes,'mistakes'); validateGallery(data.drawings);
  }
  function counts(data) {
    return {notes:data.notes.length,mistakes:data.mistakes.length,
      drawings:data.drawings?.pages.reduce((total,page) => total+page.document.graphs.length,0) || 0};
  }
  function checkTree(depth,budget) {
    if (depth > 64 || ++budget.nodes > 1000000) fail('BACKUP_TOO_LARGE');
  }

  // Normal records remain human-readable JSON. Reserve one key for typed
  // values, and escape user objects containing it so their meaning is unchanged.
  async function encodeValue(value,files,budget,depth = 0,ancestors = new Set()) {
    checkTree(depth,budget);
    if (value === undefined) return {[marker]:'undefined'};
    if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
    if (typeof value === 'number') {
      if (!Number.isFinite(value)) fail('BACKUP_UNSUPPORTED');
      return Object.is(value,-0) ? {[marker]:'negative-zero'} : value;
    }
    let bytes,kind;
    if (value instanceof Blob) {
      if (value.size > MAX_RECORD) fail('BACKUP_TOO_LARGE');
      bytes = new Uint8Array(await value.arrayBuffer()); kind = 'blob';
    } else if (value instanceof Uint8Array || value instanceof ArrayBuffer) {
      if (value.byteLength > MAX_RECORD) fail('BACKUP_TOO_LARGE');
      bytes = value instanceof Uint8Array ? value.slice() : new Uint8Array(value);
      kind = value instanceof Uint8Array ? 'bytes' : 'buffer';
    }
    if (bytes) {
      budget.binary += bytes.byteLength;
      if (bytes.byteLength > MAX_RECORD || budget.binary > MAX_CONTENT) fail('BACKUP_TOO_LARGE');
      const file = typeof root.File === 'function' && value instanceof root.File;
      const encoded = {[marker]:file ? 'file' : kind};
      if (files) {
        budget.files = (budget.files || 0)+1;
        if (budget.files > MAX_FILES-4) fail('BACKUP_TOO_LARGE');
        const path = 'attachments/'+String(budget.files).padStart(6,'0')+'.bin';
        files[path] = bytes; encoded.path = path;
      } else encoded.sha256 = await digest(bytes);
      if (value instanceof Blob) encoded.type = value.type;
      if (file) { encoded.name = value.name; encoded.lastModified = value.lastModified; }
      return encoded;
    }
    if (typeof value !== 'object' || ancestors.has(value) || Object.getOwnPropertySymbols(value).length) fail('BACKUP_UNSUPPORTED');
    const prototype = Object.getPrototypeOf(value);
    if (Array.isArray(value) ? prototype !== Array.prototype : prototype !== Object.prototype && prototype !== null) fail('BACKUP_UNSUPPORTED');
    ancestors.add(value);
    let result;
    if (Array.isArray(value)) {
      result = [];
      for (let i=0;i<value.length;i++) {
        const descriptor = Object.getOwnPropertyDescriptor(value,String(i));
        if (descriptor && !own(descriptor,'value')) fail('BACKUP_UNSUPPORTED');
        result.push(await encodeValue(descriptor?.value,files,budget,depth+1,ancestors));
      }
    } else {
      const entries = [];
      for (const key of Object.keys(value).sort()) {
        const descriptor = Object.getOwnPropertyDescriptor(value,key);
        if (!own(descriptor,'value')) fail('BACKUP_UNSUPPORTED');
        entries.push([key,await encodeValue(descriptor.value,files,budget,depth+1,ancestors)]);
      }
      result = own(value,marker) ? {[marker]:'object',entries} : Object.fromEntries(entries);
    }
    ancestors.delete(value);
    return result;
  }
  function decodeValue(value,files,used,budget,depth = 0) {
    checkTree(depth,budget);
    if (value === null || typeof value !== 'object') {
      if (typeof value === 'number' && !Number.isFinite(value)) fail();
      return value;
    }
    if (Array.isArray(value)) return value.map(item => decodeValue(item,files,used,budget,depth+1));
    if (!own(value,marker)) return Object.fromEntries(Object.entries(value)
      .map(([key,item]) => [key,decodeValue(item,files,used,budget,depth+1)]));
    const kind = value[marker];
    if (kind === 'undefined' || kind === 'negative-zero') {
      if (Object.keys(value).length !== 1) fail();
      return kind === 'undefined' ? undefined : -0;
    }
    if (kind === 'object') {
      if (Object.keys(value).length !== 2 || !Array.isArray(value.entries)) fail();
      const result = Object.create(null), keys = new Set();
      for (const entry of value.entries) {
        if (!Array.isArray(entry) || entry.length !== 2 || typeof entry[0] !== 'string' || keys.has(entry[0])) fail();
        keys.add(entry[0]); result[entry[0]] = decodeValue(entry[1],files,used,budget,depth+1);
      }
      return {...result};
    }
    if (!['blob','file','bytes','buffer'].includes(kind) || !/^attachments\/\d{6}\.bin$/.test(value.path || '')
      || !own(files,value.path)) fail();
    const expected = ['bytes','buffer'].includes(kind) ? [marker,'path']
      : kind === 'blob' ? [marker,'path','type'] : [marker,'path','type','name','lastModified'];
    if (Object.keys(value).length !== expected.length || expected.some(key => !own(value,key))) fail();
    if (['blob','file'].includes(kind) && typeof value.type !== 'string') fail();
    if (kind === 'file' && (typeof value.name !== 'string' || !Number.isFinite(value.lastModified))) fail();
    const bytes = files[value.path];
    if (bytes.byteLength > MAX_RECORD) fail('BACKUP_TOO_LARGE');
    budget.binary = (budget.binary || 0)+bytes.byteLength;
    if (budget.binary > MAX_CONTENT) fail('BACKUP_TOO_LARGE');
    used.add(value.path);
    if (kind === 'bytes') return bytes.slice();
    if (kind === 'buffer') return bytes.slice().buffer;
    if (kind === 'file' && typeof root.File === 'function') return new root.File([bytes],value.name,{type:value.type,lastModified:value.lastModified});
    return new Blob([bytes],{type:value.type});
  }
  async function fingerprint(value) {
    const encoded = await encodeValue(value,null,{nodes:0,binary:0});
    return digest(encoder.encode(JSON.stringify(encoded)));
  }
  const timeFields = new Set(['createdat','updatedat','answerupdatedat','analysisupdatedat','solutionupdatedat',
    'lastwrongat','correctedat','retestpassedat','lastretestat','timestamp','savedat','importedat','exportedat',
    'deletedat','answeredat','reviewedat','lastreviewedat','lastpracticedat','recognizedat']);
  function withoutMistakeTimes(value,depth = 0,tracking = false) {
    if (!value || typeof value !== 'object' || value instanceof Blob
      || value instanceof ArrayBuffer || ArrayBuffer.isView(value)) return value;
    if (Array.isArray(value)) return value.map(item => withoutMistakeTimes(item,depth+1,tracking));
    return Object.fromEntries(Object.entries(value).filter(([key]) => {
      const name = key.replace(/[_-]/g,'').toLowerCase();
      return !timeFields.has(name) && !((depth === 0 || tracking) && ['time','date','at'].includes(name));
    }).map(([key,item]) => [key,withoutMistakeTimes(item,depth+1,tracking || /retest|review|history/i.test(key))]));
  }
  async function binaryContent(value,path = [],result = []) {
    if (value instanceof Blob || value instanceof ArrayBuffer || ArrayBuffer.isView(value)) {
      const file = typeof root.File === 'function' && value instanceof root.File;
      result.push({path,value:file ? {name:value.name,data:new Blob([value],{type:value.type})} : value});
    } else if (value && typeof value === 'object') {
      for (const key of Object.keys(value).sort()) await binaryContent(value[key],[...path,key],result);
    }
    return result;
  }
  const asText = value => typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value);
  const byJSON = (left,right) => JSON.stringify(left).localeCompare(JSON.stringify(right));
  function graphContent(graph) {
    const vertices = graph.vertices.map((vertex,index) => ({id:String(vertex.id),index,value:{
      label:vertex.label == null ? null : String(vertex.label),
      display_label:vertex.label ? null : vertex.display_label || null,
      x:vertex.x ?? null,y:vertex.y ?? null
    }})).sort((a,b) => byJSON(a.value,b.value) || a.index-b.index);
    const ids = new Map(vertices.map((vertex,index) => [vertex.id,'v'+index]));
    const edges = graph.edges.map(edge => {
      let from = ids.get(String(edge.from)) ?? 'missing:'+String(edge.from);
      let to = ids.get(String(edge.to)) ?? 'missing:'+String(edge.to);
      const direction = edge.direction || (graph.directed === true ? 'forward' : graph.directed === false ? 'undirected' : 'unknown');
      let path = edge.path || null;
      if (direction === 'undirected' && from > to) { [from,to] = [to,from]; if (path) path = path.slice().reverse(); }
      return {from,to,direction,weight:edge.weight ?? null,edge_label:edge.edge_label ?? null,
        color:edge.color ?? null,style:edge.style ?? null,path,edge_label_is_explicit:edge.edge_label_is_explicit === true};
    }).sort(byJSON);
    return {name:graph.name || '',directed:graph.directed ?? null,weighted:graph.weighted ?? null,
      bbox:graph.bbox || null,region_polygon:graph.region_polygon || null,vertices:vertices.map(vertex => vertex.value),edges};
  }
  async function contentFingerprint(kind,value) {
    let content;
    if (kind === 'notes') content = {title:value.title,content:value.content};
    else if (kind === 'mistakes') {
      const reference = value.referenceAnswer;
      content = {statement:asText(value.statement || value.question || value.content),
        answer:asText(value.answer || (reference && typeof reference === 'object' ? reference.text || reference.answer || reference : reference)),
        explanation:asText(value.explanation || value.analysis || value.solution),
        note:asText(value.note || value.userNote),userAnswer:asText(value.userAnswer || value.studentAnswer),
        feedback:withoutMistakeTimes(value.feedback ?? null)};
    } else if (kind === 'drawings') {
      const model = root.DMateGraphEditorModel;
      const document = model ? model.ensureAnonymousLabels(model.importDocument(value.document)) : value.document;
      const graphs = await Promise.all(document.graphs.map(async graph => {
        const content = graphContent(graph);
        return {id:String(graph.id),content,key:await fingerprint(content)};
      }));
      const graphIds = new Map(graphs.map(graph => [graph.id,graph.key]));
      const context = Object.fromEntries(['legends','captions'].map(kind => [kind,(document.text_context?.[kind] || [])
        .map(row => ({text:row.text,graph_ids:(row.graph_ids || []).map(id => graphIds.get(String(id)) || 'missing:'+id).sort()})).sort(byJSON)]));
      content = {name:value.name || '',requirement:value.requirement || '',body_text:document.body_text || '',
        text_context:context,graphs:graphs.map(graph => graph.content).sort(byJSON)};
    } else fail('BACKUP_UNSUPPORTED');
    return fingerprint({content,attachments:await binaryContent(value)});
  }
  async function checkRecordSizes(data) {
    // Bound each record before the caller starts writing to encrypted storage.
    for (const row of [...data.notes,...data.mistakes,...(data.drawings ? [data.drawings] : [])]) {
      const budget = {nodes:0,binary:0};
      const encoded = await encodeValue(row,null,budget);
      if (encoder.encode(JSON.stringify(encoded)).length+budget.binary > MAX_RECORD) fail('BACKUP_TOO_LARGE');
    }
  }
  async function create(data) {
    const zip = library(); validate(data);
    data = {...data,mistakes:data.mistakes.map(row => withoutMistakeTimes(row))};
    await checkRecordSizes(data);
    const files = Object.create(null), budget = {nodes:0,binary:0};
    for (const key of ['notes','mistakes','drawings']) {
      files[key+'.json'] = encoder.encode(JSON.stringify(await encodeValue(data[key],files,budget)));
    }
    const entries = Object.entries(files);
    if (entries.length+1 > MAX_FILES || entries.reduce((sum,[,bytes]) => sum+bytes.length,0) > MAX_CONTENT) fail('BACKUP_TOO_LARGE');
    const integrity = Object.fromEntries(await Promise.all(entries.map(async ([path,bytes]) => [path,{size:bytes.length,sha256:await digest(bytes)}])));
    files['manifest.json'] = encoder.encode(JSON.stringify({format:'dmate-offline-backup',version:1,
      createdAt:new Date().toISOString(),counts:counts(data),files:integrity},null,2));
    if (Object.values(files).reduce((sum,bytes) => sum+bytes.length,0) > MAX_CONTENT) fail('BACKUP_TOO_LARGE');
    const bytes = zip.zipSync(files,{level:6});
    if (bytes.length > MAX_ARCHIVE) fail('BACKUP_TOO_LARGE');
    return new Blob([bytes],{type:'application/zip'});
  }
  async function read(file) {
    const zip = library();
    const size = file instanceof Blob ? file.size : file?.byteLength;
    if (!Number.isSafeInteger(size) || size < 22) fail();
    if (size > MAX_ARCHIVE) fail('BACKUP_TOO_LARGE');
    const bytes = file instanceof Blob ? new Uint8Array(await file.arrayBuffer())
      : file instanceof Uint8Array ? file : new Uint8Array(file);
    let files;
    const paths = new Set(); let total = 0;
    try {
      files = zip.unzipSync(bytes,{filter(entry) {
        if (paths.has(entry.name) || !/^(manifest|notes|mistakes|drawings)\.json$|^attachments\/\d{6}\.bin$/.test(entry.name)) fail();
        paths.add(entry.name); total += entry.originalSize;
        if (paths.size > MAX_FILES || !Number.isSafeInteger(entry.originalSize) || entry.originalSize < 0
          || !Number.isSafeInteger(entry.size) || entry.size < 0 || entry.size > size
          || entry.compression === 0 && entry.size !== entry.originalSize
          || total > MAX_CONTENT || entry.name === 'manifest.json' && entry.originalSize > 1024*1024
          || entry.name.startsWith('attachments/') && entry.originalSize > MAX_RECORD) fail('BACKUP_TOO_LARGE');
        if (![0,8].includes(entry.compression)) fail('BACKUP_UNSUPPORTED');
        return true;
      }});
    } catch (error) { if (error?.code?.startsWith?.('BACKUP_')) throw error; fail(); }
    const parse = path => {
      if (!own(files,path)) fail();
      try { return JSON.parse(decoder.decode(files[path])); } catch (_) { fail(); }
    };
    const manifest = parse('manifest.json');
    if (!object(manifest) || manifest.format !== 'dmate-offline-backup' || manifest.version !== 1) fail('BACKUP_UNSUPPORTED');
    if (!object(manifest.files) || !object(manifest.counts) || !['notes.json','mistakes.json','drawings.json'].every(path => own(manifest.files,path))) fail();
    const entries = Object.entries(manifest.files);
    if (entries.length+1 !== Object.keys(files).length) fail();
    for (const [path,metadata] of entries) {
      if (path === 'manifest.json' || !own(files,path) || !object(metadata) || metadata.size !== files[path].length
        || !/^[a-f0-9]{64}$/.test(metadata.sha256 || '') || await digest(files[path]) !== metadata.sha256) fail();
    }
    const used = new Set(), budget = {nodes:0};
    const result = Object.fromEntries(['notes','mistakes','drawings'].map(key => [key,decodeValue(parse(key+'.json'),files,used,budget)]));
    if (Object.keys(files).some(path => path.startsWith('attachments/') && !used.has(path))) fail();
    validate(result); await checkRecordSizes(result);
    const actual = counts(result);
    if (Object.keys(actual).some(key => manifest.counts[key] !== actual[key])) fail();
    return result;
  }
  root.DMateOfflineBackup = Object.freeze({create,read,fingerprint,contentFingerprint,withoutMistakeTimes});
})();
