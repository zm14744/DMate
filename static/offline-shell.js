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
  let lastDrawerTrigger = null;
  function updateDrawer() {
    const open = mobile.matches ? document.body.classList.contains('offline-nav-open')
      : document.documentElement.dataset.offlineSidebar !== 'collapsed';
    $('offlineSidebar').inert = !open;
    $('offlineNavBackdrop').hidden = !mobile.matches || !open;
    for (const id of ['offlineNavToggle','offlineDesktopSidebarToggle','offlineDesktopSidebarOpen']) {
      $(id).setAttribute('aria-expanded',String(open));
    }
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
    requestAnimationFrame(() => document.querySelector('.offline-nav-item.active')?.focus({preventScroll:true}));
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
    if (event.key === 'Escape' && document.body.classList.contains('offline-nav-open')) closeDrawer();
    if (event.key === 'Tab' && mobile.matches && document.body.classList.contains('offline-nav-open')) {
      const controls = [...$('offlineSidebar').querySelectorAll('button:not(:disabled),a[href]')].filter(node => node.getClientRects().length);
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  mobile.addEventListener('change',() => closeDrawer(false));
  updateDrawer();
  function syncPanelNavigation(event) {
    const panel = event?.detail?.panel;
    const active = [...document.querySelectorAll('.offline-nav-item[data-panel]')]
      .find(button => panel ? button.dataset.panel === panel : button.classList.contains('active'));
    const title = event?.detail?.title || active?.querySelector('span')?.textContent?.trim();
    if (title) $('offlineMobileTitle').textContent = title;
    document.querySelectorAll('.offline-nav-item[data-panel]').forEach(button => {
      button.setAttribute('aria-current',button.classList.contains('active') ? 'page' : 'false');
    });
  }
  window.addEventListener('dmate:offlinepanelchange',syncPanelNavigation);
  syncPanelNavigation();

  function openAppearance(event) {
    const trigger = event.currentTarget;
    closeDrawer(false);
    // A mobile drawer becomes inert when closed. Return focus to its visible
    // appearance entry; desktop retains the button that opened the settings.
    const returnTarget = mobile.matches ? $('offlineAppearanceToggle') : trigger;
    returnTarget?.focus({preventScroll:true});
    window.DMateOfflineAppearance?.open();
  }
  $('offlineAppearanceBtn').addEventListener('click',openAppearance);
  $('offlineAppearanceToggle').addEventListener('click',openAppearance);
})();
