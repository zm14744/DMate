/* First-paint visuals contain no study data. Account wallpaper is read only
   for the identity already verified by the server that rendered this page. */
(() => {
  'use strict';
  const script = document.currentScript;
  const scope = script?.dataset.scope || 'online', owner = script?.dataset.owner || '';
  const offlineKey = 'dmate:offline:appearance-paint:v1';
  const defaults = {mode:'system',accent:'blue',backgroundFit:'cover',mask:35,blur:0,panelOpacity:100,bubbleOpacity:100};
  const accents = {
    blue:['#3b82f6','59,130,246','#2563eb','#1d4ed8','#60a5fa','#93c5fd'],
    purple:['#8b5cf6','139,92,246','#7c3aed','#6d28d9','#a78bfa','#c4b5fd'],
    teal:['#14b8a6','20,184,166','#0d9488','#0f766e','#5eead4','#99f6e4']
  };
  const number = (value,min,max,fallback) => Number.isFinite(Number(value)) ? Math.min(max,Math.max(min,Number(value))) : fallback;
  function normalize(value) {
    const source = value || {};
    return {mode:['system','light','dark','navy'].includes(source.mode) ? source.mode : defaults.mode,
      accent:Object.hasOwn(accents,source.accent) ? source.accent : defaults.accent,
      backgroundFit:['cover','contain'].includes(source.backgroundFit) ? source.backgroundFit : defaults.backgroundFit,
      mask:number(source.mask,0,70,35),blur:number(source.blur,0,12,0),
      panelOpacity:number(source.panelOpacity,75,100,100),bubbleOpacity:number(source.bubbleOpacity,60,100,100)};
  }
  const readJSON = (storage,key) => {try {return JSON.parse(storage.getItem(key) || 'null');} catch (_) {return null;}};
  const guest = window.DMateGuestSession;
  const meta = scope === 'online' && owner ? readJSON(localStorage,'discrete_math_ai_cloud_sync_v1') : null;
  let settings = normalize(scope === 'offline' ? readJSON(localStorage,offlineKey)
    : owner ? readJSON(localStorage,'discrete_math_ai_appearance_v1::'+encodeURIComponent(owner))
      || (meta?.username === owner ? readJSON(localStorage,'discrete_math_ai_appearance_v1') : null)
      : guest?.read('appearance'));
  let picture = null, epoch = 0, task = Promise.resolve();
  function paint() {
    const root = document.documentElement, body = document.body;
    const native = window.__DMATE_NATIVE_SYSTEM_THEME__;
    const theme = settings.mode !== 'system' ? settings.mode : ['light','dark'].includes(native) ? native
      : window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    root.dataset.appearanceTheme = theme;
    root.style.colorScheme = theme === 'light' ? 'only light' : 'dark';
    root.style.backgroundColor = {light:'#f5f5f7',dark:'#0d0d0d',navy:'#0f172a'}[theme];
    const accent = accents[settings.accent], alpha = settings.panelOpacity/100;
    const values = {'--accent':accent[0],'--accent-rgb':accent[1],'--accent-deep':accent[2],
      '--accent-deeper':accent[3],'--accent-soft':accent[4],'--accent-pale':accent[5],
      '--accent-bg':'rgba('+accent[1]+',.22)','--font-scale':1,
      '--panel-alpha':alpha,'--workspace-alpha':Math.max(.08,Math.min(.18,alpha*.14)),
      '--shell-alpha':Math.max(.30,Math.min(.48,alpha*.44)),'--composer-alpha':Math.max(.38,Math.min(.58,alpha*.52)),
      '--bubble-alpha':settings.bubbleOpacity/100,'--background-mask-alpha':settings.mask/100,
      '--background-blur':settings.blur+'px','--background-size':settings.backgroundFit};
    for (const [key,value] of Object.entries(values)) root.style.setProperty(key,String(value));
    if (body) {body.dataset.appearanceTheme = theme;body.style.colorScheme = root.style.colorScheme;}
    document.querySelector('meta[name="color-scheme"]')?.setAttribute('content',root.style.colorScheme);
    document.querySelector('meta[name="supported-color-schemes"]')?.setAttribute('content',theme === 'light' ? 'light' : 'dark');
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content',{light:'#f5f5f7',dark:'#171717',navy:'#0f172a'}[theme]);
    const layer = document.getElementById('appearanceBackgroundLayer');
    if (picture && layer && body) {layer.style.backgroundImage = 'url("'+picture.url+'")';body.classList.add('has-custom-background');}
  }
  const observer = new MutationObserver(() => {
    paint();
    if (document.body && document.getElementById('appearanceBackgroundLayer')) observer.disconnect();
  });
  observer.observe(document.documentElement,{childList:true,subtree:true});
  paint();
  async function decode(blob) {
    if (!(blob instanceof Blob) || !blob.size) return null;
    const url = URL.createObjectURL(blob), image = new Image();
    try {image.src = url;await image.decode();return {blob,url};}
    catch (_) {URL.revokeObjectURL(url);return null;}
  }
  function begin(load) {
    const generation = ++epoch;
    task = Promise.resolve(load).then(async value => {
      if (generation !== epoch) return;
      if (scope === 'offline' && value?.settings) {settings = normalize(value.settings);paint();}
      const decoded = await decode(value?.backgroundBlob ?? value);
      if (generation !== epoch) {if (decoded) URL.revokeObjectURL(decoded.url);return;}
      picture = decoded;paint();
    }).catch(() => {});
  }
  async function onlineBackground() {
    if (!owner) return guest?.readBlob('background');
    if (meta?.username !== owner) return null;
    return new Promise(resolve => {
      const opening = indexedDB.open('discrete_math_ai_appearance_assets_v1',1);
      opening.onupgradeneeded = () => {opening.transaction.abort();};
      opening.onerror = () => resolve(null);
      opening.onsuccess = () => {
        const db = opening.result;
        if (!db.objectStoreNames.contains('assets')) {db.close();resolve(null);return;}
        const tx = db.transaction('assets'), request = tx.objectStore('assets').get('global_background');
        let blob = null;request.onsuccess = () => {blob = request.result;};
        tx.oncomplete = () => {db.close();resolve(blob);};tx.onabort = tx.onerror = () => {db.close();resolve(null);};
      };
    });
  }
  function cancel() {epoch++;if (picture) URL.revokeObjectURL(picture.url);picture = null;observer.disconnect();}
  window.DMateAppearanceBootstrap = Object.freeze({scope,owner,get settings() {return {...settings};},
    restoreOffline:load => {if (scope === 'offline') begin(load);},
    rememberOffline:value => {if (scope === 'offline') {settings = normalize(value);try {localStorage.setItem(offlineKey,JSON.stringify(settings));} catch (_) {}}},
    async takePicture(blob) {
      await task;
      if (!picture) return null;
      if (blob && blob !== picture.blob) {
        if (blob.size !== picture.blob.size || blob.type !== picture.blob.type) {cancel();return null;}
        const hash = async value => [...new Uint8Array(await crypto.subtle.digest('SHA-256',await value.arrayBuffer()))].join(',');
        if (await hash(blob) !== await hash(picture.blob)) {cancel();return null;}
      }
      const result = picture;picture = null;epoch++;observer.disconnect();return result;
    },cancel});
  if (scope === 'online') begin(onlineBackground());
})();
