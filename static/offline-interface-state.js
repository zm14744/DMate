/* Non-private interface preferences belong to one live tab/app launch. */
(() => {
  'use strict';
  const key = 'dmate:offline-interface:v1';
  const tab = String(window.name || '');
  const launch = String(window.__DMATE_NATIVE_GUEST_SESSION__
    || /\bDMateGuestSession\/([A-Za-z0-9-]{16,80})\b/.exec(navigator.userAgent || '')?.[1] || '');
  const navigation = performance.getEntriesByType?.('navigation')?.[0]?.type;
  // A direct navigation in the same named tab also belongs to its live session.
  // Restored browser tabs use back_forward and must establish continuity again.
  let continuing = navigation === 'reload' || navigation === 'navigate'
    || (!navigation && [0,1].includes(performance.navigation?.type));
  try {
    const previous = new URL(document.referrer);
    continuing ||= previous.origin === location.origin
      && ['/', '/offline', '/static/offline.html'].includes(previous.pathname);
  } catch (_) {}
  let state = {version:1, tab, launch, hidden:true, desktopCollapsed:false, mobileOpen:false};
  try {
    const saved = JSON.parse(sessionStorage.getItem(key) || 'null');
    if (continuing && tab && saved?.version === 1 && saved.tab === tab && saved.launch === launch) {
      for (const field of ['hidden', 'desktopCollapsed', 'mobileOpen'])
        if (typeof saved[field] === 'boolean') state[field] = saved[field];
    }
  } catch (_) {}
  const persist = () => {
    try { sessionStorage.setItem(key, JSON.stringify(state)); } catch (_) {}
  };
  persist();
  window.DMateOfflineInterfaceState = Object.freeze({
    read:() => ({hidden:state.hidden, desktopCollapsed:state.desktopCollapsed, mobileOpen:state.mobileOpen}),
    update(patch = {}) {
      for (const field of ['hidden', 'desktopCollapsed', 'mobileOpen'])
        if (typeof patch[field] === 'boolean') state[field] = patch[field];
      persist();
    }
  });
})();
