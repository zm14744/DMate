/* The offline workspace uses the same Lucide artwork and navigation chrome. */
(() => {
  'use strict';
  const paths = {
    plus:'<path d="M12 5v14M5 12h14"/>',
    edit:'<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L9 17l-4 1 1-4Z"/>',
    'square-pen':'<path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M16 3a2.121 2.121 0 0 1 3 3l-9 9-4 1 1-4Z"/>',
    trash:'<path d="M3 6h18M19 6l-1 14H6L5 6M9 6V3h6v3M10 10v7M14 10v7"/>',
    check:'<path d="m20 6-11 11-5-5"/>',
    save:'<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h12l4 4v12a2 2 0 0 1-2 2Z"/><path d="M17 21v-8H7v8M7 3v5h8"/>',
    eye:'<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/>',
    'eye-off':'<path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 1-1.444 2.49"/><path d="M14.084 14.158a3 3 0 0 1-4.242-4.242"/><path d="M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 4.446-5.143"/><path d="m2 2 20 20"/>',
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
  const interfaceState = window.DMateOfflineInterfaceState;
  const initialInterface = interfaceState?.read() || {hidden:true};
  const privacyButtons = [...document.querySelectorAll('[data-offline-privacy]')];
  const privacyCover = $('offlinePrivacyCover'), privacyRestore = $('offlinePrivacyRestore');
  const privacyMotion = window.DMateOfflinePrivacyMotion?.create(privacyCover);
  const layout = document.querySelector('.offline-layout');
  let privacyReturnFocus = null, layoutWasInert = false;
  let interfaceHidden = false;
  let introPlaying = false, introMotionComplete = false, introRun = 0;
  window.DMateI18n?.register({'隐藏界面':'Hide interface','显示界面':'Show interface','DMate 防窥界面':'DMate privacy screen'});
  function syncPrivacyControls() {
    for (const control of [...privacyButtons,privacyRestore]) {
      const restoring = control === privacyRestore;
      const action = restoring ? '显示界面' : '隐藏界面';
      const label = window.DMateI18n?.t(action) || action;
      const iconName = restoring ? 'eye' : 'eye-off';
      control.setAttribute('aria-label',label);
      if (!restoring) control.setAttribute('title',label);
      control.dataset.privacyState = interfaceHidden ? 'hidden' : 'visible';
      const icon = window.DMateOfflineIcons.create(iconName);
      // Header icons inherit the sidebar control's 22/24px size and 2px stroke.
      icon.removeAttribute('class');
      icon.dataset.icon = iconName;
      control.replaceChildren(icon);
    }
  }
  function focusPrivacyCover() {
    (introPlaying ? privacyCover : privacyRestore).focus({preventScroll:true});
  }
  function completeIntro() {
    if (introPlaying && introMotionComplete
      && !document.documentElement.hasAttribute('data-offline-interface-pending')) showInterface();
  }
  function hideInterface(trigger,autoplay = false) {
    if (interfaceHidden && !autoplay) return;
    const wasHidden = interfaceHidden;
    const run = ++introRun;
    introPlaying = autoplay;
    introMotionComplete = false;
    privacyRestore.hidden = autoplay;
    privacyCover.toggleAttribute('data-offline-intro',autoplay);
    privacyReturnFocus = trigger;
    if (!privacyCover.open) privacyCover.showModal();
    interfaceHidden = true;
    if (!wasHidden) layoutWasInert = layout.inert;
    layout.inert = true;
    document.body.classList.add('offline-content-hidden');
    interfaceState?.update({hidden:true});
    syncPrivacyControls();
    focusPrivacyCover();
    const playback = privacyMotion?.play();
    if (autoplay) Promise.resolve(playback).then(() => {
      // Paint the completed logo before entering the fully restored workspace.
      requestAnimationFrame(() => {
        if (!introPlaying || run !== introRun) return;
        introMotionComplete = true;
        completeIntro();
      });
    });
  }
  function showInterface() {
    if (!interfaceHidden) return;
    interfaceHidden = false;
    introPlaying = false;
    introRun++;
    privacyMotion?.finish();
    document.body.classList.remove('offline-content-hidden');
    interfaceState?.update({hidden:false});
    layout.inert = layoutWasInert;
    if (privacyCover.open) privacyCover.close();
    privacyRestore.hidden = false;
    privacyCover.removeAttribute('data-offline-intro');
    updateDrawer();
    syncPrivacyControls();
    // An existing modal remains open behind the cover and retains its own focus.
    if (!document.querySelector('dialog:modal')) {
      const previous = privacyReturnFocus;
      const usable = previous?.isConnected && previous.getClientRects().length
        && !previous.closest('[inert]') && getComputedStyle(previous).visibility !== 'hidden';
      const fallback = mobile.matches
        ? $(document.body.classList.contains('offline-nav-open') ? 'offlineDrawerPrivacyToggle' : 'offlineMobilePrivacyToggle')
        : $('offlineDesktopPrivacyToggle');
      (usable ? previous : fallback).focus({preventScroll:true});
    }
    privacyReturnFocus = null;
  }
  privacyButtons.forEach(control => control.addEventListener('click',() => hideInterface(control)));
  privacyRestore.addEventListener('click',showInterface);
  privacyCover.addEventListener('cancel',event => event.preventDefault());
  privacyCover.addEventListener('close',() => {
    if (interfaceHidden && !privacyCover.open) showInterface();
  });
  // Async notices may enter the top layer while hidden. Keep their state behind
  // the cover, then let the user handle them after choosing the eye button.
  new MutationObserver(records => {
    if (!interfaceHidden || !privacyCover.open) return;
    const newerModal = records.some(({target}) => target !== privacyCover
      && target instanceof HTMLDialogElement && target.open && target.matches(':modal'));
    if (newerModal) {
      privacyCover.close(); privacyCover.showModal();
      focusPrivacyCover();
    }
  }).observe(document.body,{subtree:true,attributes:true,attributeFilter:['open']});
  // Initialization restores the selected panel and drafts before removing this
  // flag, including the failure path that leaves return-online reachable.
  new MutationObserver(completeIntro).observe(document.documentElement,
    {attributes:true,attributeFilter:['data-offline-interface-pending']});
  window.addEventListener('pageshow',event => { if (event.persisted) hideInterface(undefined,true); });
  window.addEventListener('dmate:languagechange',syncPrivacyControls);
  syncPrivacyControls();
  let lastDrawerTrigger = null;
  function updateDrawer() {
    const open = mobile.matches ? document.body.classList.contains('offline-nav-open')
      : document.documentElement.dataset.offlineSidebar !== 'collapsed';
    $('offlineSidebar').inert = !open;
    // Keep the mobile backdrop mounted so a closing transition can finish.
    $('offlineNavBackdrop').hidden = !mobile.matches;
    $('offlineNavBackdrop').setAttribute('aria-hidden',String(!mobile.matches || !open));
    for (const id of ['offlineNavToggle','offlineDesktopSidebarToggle','offlineDesktopSidebarOpen']) {
      $(id).setAttribute('aria-expanded',String(open));
    }
    interfaceState?.update({desktopCollapsed:document.documentElement.dataset.offlineSidebar === 'collapsed',
      mobileOpen:document.body.classList.contains('offline-nav-open')});
  }
  function closeDrawer(restore = true) {
    document.body.classList.remove('offline-nav-open');
    updateDrawer();
    if (restore && mobile.matches) (lastDrawerTrigger || $('offlineNavToggle')).focus({preventScroll:true});
  }
  $('offlineNavToggle').addEventListener('click', () => {
    lastDrawerTrigger = $('offlineNavToggle');
    document.body.classList.add('offline-nav-open');
    updateDrawer();
    requestAnimationFrame(() => {
      if (!interfaceHidden) document.querySelector('.offline-nav-item.active')?.focus({preventScroll:true});
    });
  });
  $('offlineNavClose').addEventListener('click',() => closeDrawer());
  $('offlineNavBackdrop').addEventListener('click',() => closeDrawer());
  $('offlineDesktopSidebarToggle').addEventListener('click',() => {
    document.documentElement.dataset.offlineSidebar = 'collapsed';
    updateDrawer();
    $('offlineDesktopSidebarOpen').focus({preventScroll:true});
  });
  $('offlineDesktopSidebarOpen').addEventListener('click',() => {
    delete document.documentElement.dataset.offlineSidebar;
    updateDrawer();
    $('offlineDesktopSidebarToggle').focus({preventScroll:true});
  });
  document.querySelectorAll('.offline-nav-item[data-panel]').forEach(button => button.addEventListener('click',() => closeDrawer(false)));
  document.addEventListener('keydown',event => {
    if (interfaceHidden) return;
    if (event.key === 'Escape' && document.body.classList.contains('offline-nav-open')) closeDrawer();
    if (event.key === 'Tab' && mobile.matches && document.body.classList.contains('offline-nav-open')) {
      const controls = [...$('offlineSidebar').querySelectorAll('button:not(:disabled),a[href]')]
        .filter(node => node.getClientRects().length && !node.closest('[inert]') && getComputedStyle(node).visibility !== 'hidden');
      const first = controls[0], last = controls.at(-1);
      if (!first) return;
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  mobile.addEventListener('change',() => {
    const restorePrivacyFocus = document.activeElement?.matches('[data-offline-privacy]');
    closeDrawer(false);
    if (interfaceHidden) focusPrivacyCover();
    else if (restorePrivacyFocus) $(mobile.matches ? 'offlineMobilePrivacyToggle' : 'offlineDesktopPrivacyToggle').focus({preventScroll:true});
  });
  if (initialInterface.desktopCollapsed) document.documentElement.dataset.offlineSidebar = 'collapsed';
  if (initialInterface.mobileOpen && mobile.matches) document.body.classList.add('offline-nav-open');
  updateDrawer();
  hideInterface(undefined,true);
  requestAnimationFrame(() => requestAnimationFrame(() => document.body.classList.add('offline-shell-ready')));
  function syncPanelNavigation() {
    document.querySelectorAll('.offline-nav-item[data-panel]').forEach(button => {
      button.setAttribute('aria-current',button.classList.contains('active') ? 'page' : 'false');
    });
  }
  window.addEventListener('dmate:offlinepanelchange',syncPanelNavigation);
  syncPanelNavigation();

  function openAppearance(event) {
    const trigger = event.currentTarget;
    closeDrawer(false);
    // The closed mobile drawer is inert, so restore focus to its visible opener.
    // Desktop retains the appearance button that opened the settings.
    const returnTarget = mobile.matches ? $('offlineNavToggle') : trigger;
    returnTarget?.focus({preventScroll:true});
    window.DMateOfflineAppearance?.open();
  }
  $('offlineAppearanceBtn').addEventListener('click',openAppearance);
})();
