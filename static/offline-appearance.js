/* The offline shell uses the online appearance controls and visual settings.
 * Persistence belongs to offline.js; this controller owns preview and rollback.
 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const text = value => window.DMateI18n?.t?.(value) ?? value;
  const defaults = Object.freeze({ mode:'system', accent:'blue', fontSize:'standard',
    backgroundFit:'cover', mask:35, blur:0, panelOpacity:100, bubbleOpacity:100 });
  const accents = {
    blue:['#3b82f6','59,130,246','#2563eb','#1d4ed8','#60a5fa','#93c5fd'],
    purple:['#8b5cf6','139,92,246','#7c3aed','#6d28d9','#a78bfa','#c4b5fd'],
    teal:['#14b8a6','20,184,166','#0d9488','#0f766e','#5eead4','#99f6e4']
  };
  const clamp = (value, min, max, fallback) => Number.isFinite(Number(value))
    ? Math.min(max, Math.max(min, Number(value))) : fallback;
  function normalize(value) {
    const source = value && typeof value === 'object' ? value : {};
    return {
      mode:['system','light','dark','navy'].includes(source.mode) ? source.mode : defaults.mode,
      accent:Object.hasOwn(accents, source.accent) ? source.accent : defaults.accent,
      fontSize:['small','standard','large'].includes(source.fontSize) ? source.fontSize : defaults.fontSize,
      backgroundFit:['cover','contain'].includes(source.backgroundFit) ? source.backgroundFit : defaults.backgroundFit,
      mask:clamp(source.mask,0,70,defaults.mask), blur:clamp(source.blur,0,12,defaults.blur),
      panelOpacity:clamp(source.panelOpacity,75,100,defaults.panelOpacity),
      bubbleOpacity:clamp(source.bubbleOpacity,60,100,defaults.bubbleOpacity)
    };
  }
  let committed = normalize(), committedBlob = null, settings = normalize();
  let visualBlob = null, backgroundURL = '', backgroundMode = 'unchanged';
  let opened = false, pending = false, processing = false, imageEpoch = 0, previousFocus = null;
  const modalHint = () => $('appearanceModal')?.querySelector('.appearance-apply-hint');

  function resolvedTheme() {
    if (settings.mode !== 'system') return settings.mode;
    const native = window.__DMATE_NATIVE_SYSTEM_THEME__;
    if (native === 'light' || native === 'dark') return native;
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  function syncControls() {
    for (const [attribute, value] of [['mode',settings.mode],['accent',settings.accent],
      ['font',settings.fontSize],['fit',settings.backgroundFit]]) {
      document.querySelectorAll('[data-appearance-' + attribute + ']').forEach(button => {
        const active = button.getAttribute('data-appearance-' + attribute) === value;
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', String(active));
      });
    }
    for (const [name, value, suffix] of [['Mask',settings.mask,'%'],['Blur',settings.blur,'px'],
      ['Panel',settings.panelOpacity,'%'],['Bubble',settings.bubbleOpacity,'%']]) {
      if ($('appearance' + name + 'Range')) $('appearance' + name + 'Range').value = String(value);
      if ($('appearance' + name + 'Value')) $('appearance' + name + 'Value').textContent = value + suffix;
    }
    const preview = $('appearanceBackgroundPreview');
    if (preview) {
      preview.dataset.hasBackground = String(Boolean(backgroundURL));
      preview.textContent = backgroundURL ? '' : text('无');
      preview.style.setProperty('background-image', backgroundURL ? 'url("' + backgroundURL + '")' : 'none', 'important');
      if (backgroundURL) {
        preview.style.setProperty('background-size','cover','important');
        preview.style.setProperty('background-position','center','important');
        preview.style.setProperty('background-repeat','no-repeat','important');
        preview.tabIndex = 0; preview.setAttribute('role','button');
        preview.setAttribute('aria-label',text('查看当前背景大图'));
      } else {
        preview.removeAttribute('tabindex'); preview.removeAttribute('role'); preview.removeAttribute('aria-label');
      }
    }
    if ($('appearanceBackgroundRemove')) $('appearanceBackgroundRemove').disabled = pending || !backgroundURL;
    if ($('appearanceDone')) $('appearanceDone').disabled = pending || processing;
    if ($('appearanceReset')) $('appearanceReset').disabled = pending;
    if ($('appearanceClose')) $('appearanceClose').disabled = pending;
    if ($('appearanceBackgroundUpload')) $('appearanceBackgroundUpload').disabled = pending || processing;
    $('appearanceModal')?.setAttribute('aria-busy',String(pending || processing));
  }
  function paint() {
    const root = document.documentElement, body = document.body;
    const theme = resolvedTheme(), accent = accents[settings.accent], alpha = settings.panelOpacity / 100;
    root.dataset.appearanceTheme = body.dataset.appearanceTheme = theme;
    root.style.colorScheme = body.style.colorScheme = theme === 'light' ? 'only light' : 'dark';
    document.querySelector('meta[name="color-scheme"]')?.setAttribute('content',theme === 'light' ? 'only light' : 'dark');
    document.querySelector('meta[name="supported-color-schemes"]')?.setAttribute('content',theme === 'light' ? 'light' : 'dark');
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content',theme === 'light' ? '#f8fafc' : theme === 'navy' ? '#0f172a' : '#171717');
    const values = {
      '--accent':accent[0], '--accent-rgb':accent[1], '--accent-deep':accent[2],
      '--accent-deeper':accent[3], '--accent-soft':accent[4], '--accent-pale':accent[5],
      '--accent-bg':'rgba(' + accent[1] + ',.22)', '--panel-alpha':alpha,
      '--workspace-alpha':Math.max(.08,Math.min(.18,alpha*.14)),
      '--shell-alpha':Math.max(.30,Math.min(.48,alpha*.44)),
      '--composer-alpha':Math.max(.38,Math.min(.58,alpha*.52)),
      '--bubble-alpha':settings.bubbleOpacity/100,
      '--font-scale':settings.fontSize === 'small' ? .92 : settings.fontSize === 'large' ? 1.08 : 1,
      '--background-mask-alpha':settings.mask/100, '--background-blur':settings.blur + 'px',
      '--background-size':settings.backgroundFit
    };
    for (const [key,value] of Object.entries(values)) root.style.setProperty(key,String(value));
    syncControls();
  }
  function background(blob) {
    const next = blob instanceof Blob && blob.size ? blob : null;
    if (next !== visualBlob) {
      if (backgroundURL) URL.revokeObjectURL(backgroundURL);
      visualBlob = next; backgroundURL = next ? URL.createObjectURL(next) : '';
    }
    if ($('appearanceBackgroundLayer')) $('appearanceBackgroundLayer').style.backgroundImage = backgroundURL ? 'url("' + backgroundURL + '")' : 'none';
    document.body.classList.toggle('has-custom-background',Boolean(backgroundURL));
    syncControls();
  }
  function closeViewer() {
    const viewer = $('appearanceBackgroundViewer');
    viewer?.classList.add('hidden'); viewer?.setAttribute('aria-hidden','true');
    $('appearanceBackgroundViewerImage')?.removeAttribute('src');
  }
  function openViewer() {
    if (!backgroundURL || !$('appearanceBackgroundViewerImage')) return;
    $('appearanceBackgroundViewerImage').src = backgroundURL;
    $('appearanceBackgroundViewer')?.classList.remove('hidden');
    $('appearanceBackgroundViewer')?.setAttribute('aria-hidden','false');
    $('appearanceBackgroundViewerClose')?.focus({preventScroll:true});
  }
  function hideModal() {
    closeViewer(); opened = false; imageEpoch++; processing = false;
    $('appearanceModal')?.classList.add('hidden'); $('appearanceModal')?.setAttribute('aria-hidden','true');
    if (previousFocus?.isConnected) previousFocus.focus({preventScroll:true});
    previousFocus = null;
  }
  function open() {
    if (!$('appearanceModal') || opened) return;
    previousFocus = document.activeElement; opened = true; pending = false; processing = false;
    settings = {...committed}; backgroundMode = 'unchanged'; background(committedBlob); paint();
    if (modalHint()) modalHint().textContent = text('更改会先预览，点击“确认”后才保存');
    const modal = $('appearanceModal');
    modal.classList.remove('hidden'); modal.setAttribute('aria-hidden','false');
    modal.setAttribute('role','dialog'); modal.setAttribute('aria-modal','true');
    const heading = modal.querySelector('.modal-head > div');
    if (heading) { heading.tabIndex = -1; heading.focus({preventScroll:true}); }
  }
  function close() {
    if (!opened || pending) return;
    settings = {...committed}; backgroundMode = 'unchanged'; background(committedBlob); paint(); hideModal();
  }
  function apply(value, blob = null) {
    committed = normalize(value); committedBlob = blob instanceof Blob && blob.size ? blob : null;
    settings = {...committed}; backgroundMode = 'unchanged';
    const wasSaving = pending; pending = false; processing = false; imageEpoch++;
    background(committedBlob); paint();
    if (wasSaving) hideModal();
  }
  async function notice(message) {
    if (window.DMateDeleteConfirm?.request && $('appearanceModal')) {
      await window.DMateDeleteConfirm.request($('appearanceModal'), {title:'外观提示',body:message,noticeOnly:true});
    } else if (modalHint()) modalHint().textContent = message;
  }
  function fail(error) {
    if (!pending) return;
    pending = false; syncControls();
    void notice(error?.message || text('外观保存失败，请重试'));
  }
  function commit() {
    if (!opened || pending || processing) return;
    pending = true; syncControls();
    const detail = {settings:{...settings}};
    if (backgroundMode === 'set') detail.backgroundBlob = visualBlob;
    else if (backgroundMode === 'remove') detail.removeBackground = true;
    window.dispatchEvent(new CustomEvent('offline:appearance-change',{detail}));
  }
  function removeBackground() {
    if (pending) return;
    imageEpoch++; processing = false; closeViewer(); backgroundMode = 'remove'; background(null);
  }
  function reset() {
    if (pending) return;
    settings = {...defaults}; removeBackground(); paint();
  }
  async function prepareImage(file) {
    if (!(file instanceof Blob) || !['image/jpeg','image/png','image/webp'].includes(file.type)
      || file.size > 15*1024*1024) throw new Error('Unsupported background image');
    const url = URL.createObjectURL(file), image = new Image();
    try {
      await new Promise((resolve,reject) => { image.onload = resolve; image.onerror = reject; image.src = url; });
      const width = image.naturalWidth, height = image.naturalHeight;
      if (!width || !height) throw new Error('Invalid background image');
      const ratio = Math.min(1,1920/Math.max(width,height)), canvas = document.createElement('canvas');
      canvas.width = Math.max(1,Math.round(width*ratio)); canvas.height = Math.max(1,Math.round(height*ratio));
      const context = canvas.getContext('2d',{alpha:true});
      if (!context) throw new Error('Canvas unavailable');
      context.drawImage(image,0,0,canvas.width,canvas.height);
      const converted = await new Promise(resolve => canvas.toBlob(resolve,'image/webp',.88));
      return converted instanceof Blob && converted.size ? converted : file;
    } finally { URL.revokeObjectURL(url); }
  }
  async function selectBackground(event) {
    const file = event.target.files?.[0]; event.target.value = '';
    if (!file || pending) return;
    const epoch = ++imageEpoch; processing = true; syncControls();
    try {
      const blob = await prepareImage(file);
      if (!opened || epoch !== imageEpoch) return;
      backgroundMode = 'set'; background(blob);
    } catch (_) {
      if (opened && epoch === imageEpoch) await notice(text('背景图片处理失败，请换一张 JPG、PNG 或 WebP 图片'));
    } finally { if (epoch === imageEpoch) { processing = false; syncControls(); } }
  }
  const listen = (id,type,handler) => $(id)?.addEventListener(type,handler);
  function bind() {
    listen('appearanceBtn','click',open); listen('appearanceClose','click',close);
    listen('appearanceDone','click',commit); listen('appearanceReset','click',reset);
    listen('appearanceBackgroundUpload','click',() => $('appearanceBackgroundInput')?.click());
    listen('appearanceBackgroundRemove','click',removeBackground);
    listen('appearanceBackgroundInput','change',selectBackground);
    listen('appearanceBackgroundPreview','click',openViewer);
    listen('appearanceBackgroundPreview','keydown',event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openViewer(); }
    });
    listen('appearanceBackgroundViewerClose','click',closeViewer);
    listen('appearanceBackgroundViewer','click',event => { if (event.target === $('appearanceBackgroundViewer')) closeViewer(); });
    listen('appearanceModal','click',event => { if (event.target === $('appearanceModal')) close(); });
    for (const [attribute,key] of [['mode','mode'],['accent','accent'],['font','fontSize'],['fit','backgroundFit']]) {
      document.querySelectorAll('[data-appearance-' + attribute + ']').forEach(button => button.addEventListener('click',() => {
        if (!opened || pending) return;
        settings = normalize({...settings,[key]:button.getAttribute('data-appearance-' + attribute)}); paint();
      }));
    }
    for (const [name,key] of [['Mask','mask'],['Blur','blur'],['Panel','panelOpacity'],['Bubble','bubbleOpacity']]) {
      listen('appearance' + name + 'Range','input',event => {
        if (!opened || pending) return;
        settings = normalize({...settings,[key]:Number(event.target.value)}); paint();
      });
    }
    document.addEventListener('keydown',event => {
      if (!opened) return;
      // Shared notices use a native modal above this appearance overlay and
      // keep their own Escape/Tab handling until the notice is dismissed.
      if (event.target.closest?.('dialog[open]')) return;
      const viewer = $('appearanceBackgroundViewer');
      if (event.key === 'Escape') {
        event.preventDefault(); event.stopPropagation();
        if (viewer && !viewer.classList.contains('hidden')) closeViewer(); else close();
      } else if (event.key === 'Tab') {
        const owner = viewer && !viewer.classList.contains('hidden') ? viewer : $('appearanceModal');
        const controls = [...owner.querySelectorAll('button:not(:disabled),input:not(:disabled),[tabindex="0"]')]
          .filter(node => node.getClientRects().length && !node.hidden);
        if (!controls.length) return;
        const index = controls.indexOf(document.activeElement);
        if (event.shiftKey && index <= 0) { event.preventDefault(); controls.at(-1).focus(); }
        else if (!event.shiftKey && (index === -1 || index === controls.length-1)) { event.preventDefault(); controls[0].focus(); }
      }
    },true);
    const systemChange = () => { if (settings.mode === 'system') paint(); };
    const media = window.matchMedia?.('(prefers-color-scheme: dark)');
    if (media?.addEventListener) media.addEventListener('change',systemChange); else media?.addListener?.(systemChange);
    window.addEventListener('dmate:native-system-theme',systemChange);
    window.addEventListener('pageshow',systemChange); window.addEventListener('focus',systemChange);
    document.addEventListener('visibilitychange',() => { if (!document.hidden) systemChange(); });
    window.addEventListener('offline:appearance-applied',event => {
      if (pending) apply(event.detail?.settings || settings, backgroundMode === 'remove' ? null : visualBlob);
    });
    window.addEventListener('offline:appearance-error',event => fail(event.detail?.error || event.detail));
  }
  window.DMateOfflineAppearance = {apply,normalize,open,close,commit,fail,
    getSettings:() => ({...committed}), getBackground:() => committedBlob};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',bind,{once:true}); else bind();
})();
