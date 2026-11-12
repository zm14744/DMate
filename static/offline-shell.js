/* The offline workspace uses the same Lucide artwork and navigation chrome. */
(() => {
  'use strict';
  const paths = {
    plus:'<path d="M12 5v14M5 12h14"/>',
    edit:'<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L9 17l-4 1 1-4Z"/>',
    trash:'<path d="M3 6h18M19 6l-1 14H6L5 6M9 6V3h6v3M10 10v7M14 10v7"/>',
    check:'<path d="m20 6-11 11-5-5"/>',
    save:'<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h12l4 4v12a2 2 0 0 1-2 2Z"/><path d="M17 21v-8H7v8M7 3v5h8"/>',
    eye:'<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/>',
    'book-open':'<path d="M12 7v14M3 18V3a1 1 0 0 1 1-1h2a6 6 0 0 1 6 3 6 6 0 0 1 6-3h2a1 1 0 0 1 1 1v15a1 1 0 0 1-1 1h-3a6 6 0 0 0-5 2 6 6 0 0 0-5-2H4a1 1 0 0 1-1-1Z"/>',
    'clipboard-list':'<rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2M12 11h4M12 16h4M8 11h.01M8 16h.01"/>',
    export:'<path d="M12 15V3"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/>',
    back:'<path d="m12 19-7-7 7-7M5 12h14"/>',
    search:'<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    'panel-left':'<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/>',
    settings:'<path d="M10 5H3M12 19H3M14 3v4M16 17v4M21 12h-9M21 19h-5M21 5h-7M8 10v4M8 12H3"/>'
  };
  window.DMateOfflineIcons = {
    create(name) {
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('class','dmate-lucide-icon');
      svg.setAttribute('viewBox','0 0 24 24');
      svg.setAttribute('aria-hidden','true');
      svg.setAttribute('focusable','false');
      svg.innerHTML = paths[name] || paths['book-open'];
      return svg;
    }
  };
  const $ = id => document.getElementById(id);
  const mobile = window.matchMedia('(max-width:1100px)');
  const moduleIds = {
    mistakes:'wrongBookModal', notes:'conceptNotebookDialog', drawing:'graphEditorDialog',
    graph:'knowledgeGraphModal', questions:'offlineQuestionsModal', concepts:'offlineConceptsModal',
    review:'learningReviewModal'
  };
  const moduleButtons = {
    mistakes:'wrongBookBtn', notes:'conceptNotebookBtn', drawing:'graphDrawingBtn',
    graph:'knowledgeGraphBtn', review:'learningReviewBtn'
  };
  const origins = new Map();
  const activeModules = new Set();
  let drawerTrigger = null;
  let composer = null;
  let mode = 'chat';
  let viewportFrame = 0;

  function toast(message) {
    let node = $('offlineToast');
    if (!node) {
      node = document.createElement('div'); node.id = 'offlineToast';
      node.className = 'offline-toast'; node.setAttribute('role','status');
      document.body.appendChild(node);
    }
    node.textContent = message; node.hidden = false;
    clearTimeout(toast.timer); toast.timer = setTimeout(() => { node.hidden = true; }, 3000);
  }
  function visible(element) {
    return Boolean(element?.isConnected && !element.closest('[inert]') && element.getClientRects().length);
  }
  function focus(element) { if (visible(element)) element.focus({preventScroll:true}); }
  function drawerPanel() {
    return document.body.classList.contains('mobile-left-open') ? $('conversationSidebar')
      : document.body.classList.contains('mobile-tools-open') ? $('learningToolsPanel') : null;
  }
  function refreshDrawers() {
    const sidebar = $('conversationSidebar'), tools = $('learningToolsPanel');
    const leftOpen = mobile.matches && document.body.classList.contains('mobile-left-open');
    const toolsOpen = mobile.matches && document.body.classList.contains('mobile-tools-open');
    if (mobile.matches) {
      if (sidebar) { if (!leftOpen && sidebar.contains(document.activeElement)) document.activeElement.blur(); sidebar.inert = !leftOpen; sidebar.setAttribute('aria-hidden',String(!leftOpen)); }
      if (tools) { if (!toolsOpen && tools.contains(document.activeElement)) document.activeElement.blur(); tools.inert = !toolsOpen; tools.setAttribute('aria-hidden',String(!toolsOpen)); }
    }
    const center = document.querySelector('.center');
    if (center) center.inert = leftOpen || toolsOpen;
    $('mobileNavBtn')?.setAttribute('aria-expanded',String(leftOpen));
    $('mobileToolsBtn')?.setAttribute('aria-expanded',String(toolsOpen));
    $('mobileShellBackdrop')?.setAttribute('aria-hidden',String(!(leftOpen || toolsOpen)));
  }
  function closeDrawers(restore = true) {
    const hadDrawer = Boolean(drawerPanel());
    document.body.classList.remove('mobile-left-open','mobile-tools-open');
    refreshDrawers();
    if (restore && mobile.matches && hadDrawer) focus(drawerTrigger || $('mobileToolsBtn'));
  }
  function openDrawer(kind, trigger) {
    if (!mobile.matches) return;
    const targetClass = kind === 'left' ? 'mobile-left-open' : 'mobile-tools-open';
    const wasOpen = document.body.classList.contains(targetClass);
    closeDrawers(false);
    if (wasOpen) return;
    drawerTrigger = trigger;
    document.body.classList.add(targetClass);
    refreshDrawers();
    const panel = drawerPanel();
    requestAnimationFrame(() => focus(panel?.querySelector('.mobile-drawer-close,button:not(:disabled)')));
  }
  function moduleOpen(node) {
    return node instanceof HTMLDialogElement ? node.open : Boolean(node && !node.classList.contains('hidden'));
  }
  function anyModuleOpen() { return Object.values(moduleIds).some(id => moduleOpen($(id))); }
  function finishClose(name, restore) {
    const node = $(moduleIds[name]);
    node?.setAttribute('aria-hidden','true');
    const previous = origins.get(name); origins.delete(name);
    const wasActive = activeModules.delete(name);
    if (wasActive) window.dispatchEvent(new CustomEvent('offline:module-close',{detail:{name}}));
    if (restore && !anyModuleOpen()) {
      const fallback = mobile.matches ? $('mobileToolsBtn') : $('desktopToolsBtn');
      focus(visible(previous) ? previous : fallback);
    }
  }
  function closeModule(name, restore = true) {
    const node = $(moduleIds[name]);
    if (!node) return false;
    if (name === 'notes' && node.open) {
      // The notebook owns its persistence guard and may refuse to close.
      if (!window.DMateOfflineWorkspace?.closeNotebook?.()) return false;
    } else if (node instanceof HTMLDialogElement) { if (node.open) node.close(); }
    else node.classList.add('hidden');
    finishClose(name,restore);
    return true;
  }
  function openModule(name, trigger = document.activeElement) {
    const node = $(moduleIds[name]);
    if (!node) return null;
    const wasOpen = moduleOpen(node);
    for (const other of Object.keys(moduleIds)) {
      if (other !== name && moduleOpen($(moduleIds[other])) && !closeModule(other,false)) return null;
    }
    if (!wasOpen) origins.set(name,visible(trigger) ? trigger : $(moduleButtons[name]));
    closeDrawers(false);
    node.setAttribute('aria-hidden','false');
    if (node instanceof HTMLDialogElement) { if (!node.open) node.showModal(); }
    else {
      node.classList.remove('hidden');
      const card = node.querySelector('.modal-card');
      card?.setAttribute('role','dialog'); card?.setAttribute('aria-modal','true');
    }
    activeModules.add(name);
    if (!wasOpen) {
      window.dispatchEvent(new CustomEvent('offline:module-open',{detail:{name}}));
      const heading = node.querySelector('.modal-head > div,.modal-head h2,.dcn-heading h2,.graph-editor-dialog-head h2');
      if (heading) { heading.tabIndex = -1; requestAnimationFrame(() => focus(heading)); }
    }
    return node;
  }
  window.DMateOfflineShell = {openModule,closeModule,closeDrawers,toast};

  $('mobileNavBtn')?.addEventListener('click',event => openDrawer('left',event.currentTarget));
  $('mobileToolsBtn')?.addEventListener('click',event => openDrawer('tools',event.currentTarget));
  $('mobileNavClose')?.addEventListener('click',() => closeDrawers());
  $('mobileToolsClose')?.addEventListener('click',() => closeDrawers());
  $('mobileShellBackdrop')?.addEventListener('click',() => closeDrawers());
  $('appearanceBtn')?.addEventListener('click',() => closeDrawers(false));
  document.addEventListener('keydown',event => {
    const panel = drawerPanel();
    if (event.key === 'Escape') {
      const topDialog = [...document.querySelectorAll('dialog[open]')].at(-1);
      if (topDialog) return; // Native dialog/confirmation owns its Escape key.
      const name = [...activeModules].reverse().find(name => moduleOpen($(moduleIds[name])));
      if (name) { event.preventDefault(); closeModule(name); return; }
      if (panel) { event.preventDefault(); closeDrawers(); }
    }
    if (event.key === 'Tab' && panel) {
      const controls = [...panel.querySelectorAll('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled)')].filter(visible);
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); focus(last); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); focus(first); }
    }
  });
  for (const [name,id] of Object.entries(moduleIds)) {
    const node = $(id);
    if (!node) continue;
    node.addEventListener('click',event => {
      // Notebook controls, backdrop and cancellation are component-owned.
      if (name === 'notes') return;
      const close = event.target.closest?.('.modal-close-dot,.dcn-close,.graph-editor-close-dot,[data-offline-close]');
      if (close && close.closest('dialog') === (node instanceof HTMLDialogElement ? node : null)) {
        closeModule(name); return;
      }
      if (event.target !== node) return;
      if (!(node instanceof HTMLDialogElement)) { closeModule(name); return; }
      const rect = node.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closeModule(name);
    });
    if (node instanceof HTMLDialogElement) {
      node.addEventListener('close',() => { if (!node.open && activeModules.has(name)) finishClose(name,true); });
    }
  }
  mobile.addEventListener('change',() => {
    closeDrawers(false); syncViewport();
    requestAnimationFrame(refreshDrawers);
  });
  // The shared desktop binder releases inert on mobile at DOMContentLoaded.
  // Reapply mobile drawer state after that binder and after breakpoint changes.
  window.addEventListener('load',refreshDrawers,{once:true});
  refreshDrawers();

  const input = $('text'), send = $('sendBtn');
  function refreshSend() {
    if (send) send.disabled = !input?.value.trim() || document.documentElement.dataset.offlineReady !== 'true';
  }
  function sendQuery() {
    const text = input?.value.trim();
    if (!text) return;
    if (document.documentElement.dataset.offlineReady !== 'true') { toast('正在准备本地学习资料，请稍后再试'); return; }
    window.dispatchEvent(new CustomEvent('offline:query',{detail:{text,mode}}));
    input.value = ''; composer?.refresh(); refreshSend();
  }
  if (input && window.DMateChatComposer?.mount) {
    composer = window.DMateChatComposer.mount({input,onSend:sendQuery});
    input.addEventListener('input',refreshSend);
    new MutationObserver(refreshSend).observe(document.documentElement,{attributes:true,attributeFilter:['data-offline-ready']});
  }
  window.handleSendOrStop = sendQuery;
  if (send) send.onclick = sendQuery;
  const modeControl = $('manualQuestionMode');
  try { mode = sessionStorage.getItem('dmate:offline:composer-mode:v1') === 'question' ? 'question' : 'chat'; } catch (_) {}
  function updateMode() {
    if (!modeControl) return;
    modeControl.dataset.mode = mode;
    modeControl.querySelectorAll('[data-manual-question]').forEach(button => button.setAttribute('aria-pressed',String((button.dataset.manualQuestion === 'yes') === (mode === 'question'))));
  }
  modeControl?.querySelectorAll('[data-manual-question]').forEach(button => button.addEventListener('click',() => {
    mode = button.dataset.manualQuestion === 'yes' ? 'question' : 'chat';
    try { sessionStorage.setItem('dmate:offline:composer-mode:v1',mode); } catch (_) {}
    updateMode();
  }));
  updateMode(); refreshSend();

  function newChat() {
    $('chat')?.replaceChildren();
    if (input) input.value = '';
    document.querySelector('.center')?.classList.add('chat-empty');
    if ($('mobileConversationTitle')) $('mobileConversationTitle').textContent = 'DMate';
    closeDrawers(false); composer?.refresh(); refreshSend();
    window.dispatchEvent(new CustomEvent('offline:new-chat'));
  }
  window.newChat = newChat;
  if ($('newChatBtn')) $('newChatBtn').onclick = newChat;
  const onlineRequired = () => toast('此功能需要联网，请返回在线版使用');
  for (const id of ['imageBtn','voiceInputBtn','downloadAppBtn','accountBtn']) if ($(id)) $(id).onclick = onlineRequired;
  const imageInput = $('imageInput');
  if (imageInput) { imageInput.disabled = true; imageInput.tabIndex = -1; imageInput.style.setProperty('pointer-events','none','important'); }
  input?.addEventListener('paste',event => {
    if ([...(event.clipboardData?.items || [])].some(item => item.type.startsWith('image/'))) { event.preventDefault(); onlineRequired(); }
  });
  document.querySelector('.center')?.addEventListener('dragover',event => {
    if (event.dataTransfer?.types.includes('Files')) event.preventDefault();
  });
  document.querySelector('.center')?.addEventListener('drop',event => {
    if (event.dataTransfer?.files.length) { event.preventDefault(); onlineRequired(); }
  });
  function syncViewport() {
    if (viewportFrame) cancelAnimationFrame(viewportFrame);
    viewportFrame = requestAnimationFrame(() => {
      viewportFrame = 0;
      const root = document.documentElement;
      if (!mobile.matches) {
        root.style.removeProperty('--app-visible-height'); root.style.removeProperty('--app-viewport-top');
        document.body.classList.remove('mobile-keyboard-open'); return;
      }
      const height = Math.max(1,Math.round(window.visualViewport?.height || innerHeight));
      const top = Math.max(0,Math.round(window.visualViewport?.offsetTop || 0));
      root.style.setProperty('--app-visible-height',height+'px'); root.style.setProperty('--app-viewport-top',top+'px');
      document.body.classList.toggle('mobile-keyboard-open',innerHeight-height-top>110);
    });
  }
  window.addEventListener('resize',syncViewport,{passive:true});
  window.visualViewport?.addEventListener('resize',syncViewport,{passive:true});
  window.visualViewport?.addEventListener('scroll',syncViewport,{passive:true});
  input?.addEventListener('focus',syncViewport); input?.addEventListener('blur',syncViewport);
  syncViewport();
})();
