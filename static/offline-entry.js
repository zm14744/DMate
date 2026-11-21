(() => {
  "use strict";
  const button = document.getElementById("offlineWorkspaceBtn");
  const workerURL = new URL("/offline-service-worker.js",location.origin).href;
  const supportsWorker = "serviceWorker" in navigator && window.isSecureContext
    && !document.documentElement.hasAttribute("data-native-offline-bundle")
    && window.__DMATE_NATIVE_OFFLINE_AVAILABLE__ !== true;
  let opening = false, checking = false, checkAgain = false, preparation = null;
  function clearPreparationNotice() {
    document.getElementById("offlinePreparationStatus")?.remove();
  }
  function showPreparationNotice() {
    if (document.getElementById("offlinePreparationStatus")) return;
    const notice = document.createElement("div");
    notice.id = "offlinePreparationStatus";
    notice.className = "copy-toast";
    notice.setAttribute("role","status");
    notice.setAttribute("aria-live","polite");
    notice.style.maxWidth = "calc(100vw - 32px)";
    notice.textContent = window.DMateI18n?.t?.("离线资源尚未准备完成，请联网打开离线版后重试",
      "Offline resources are not ready. Reconnect and open offline mode, then retry.")
      || "离线资源尚未准备完成，请联网打开离线版后重试";
    document.body.append(notice);
  }
  async function shellIsCached() {
    if (!supportsWorker || !("caches" in window)) return false;
    try {
      const registration = await navigator.serviceWorker.getRegistration(location.origin + "/");
      if (registration?.active?.scriptURL !== workerURL) return false;
      const names = (await caches.keys()).filter(name => name.startsWith("dmate-offline-shell-"));
      for (const name of names) {
        const response = await (await caches.open(name)).match("/offline");
        const complete = await (await caches.open(name)).match("/__dmate_offline_ready__/"+name);
        if (response?.ok && complete?.ok) return true;
      }
    } catch (_) { /* A blocked cache must not turn a loaded page into a network error. */ }
    return false;
  }
  async function prepareOfflineResources() {
    if (!supportsWorker) return;
    if (!preparation) preparation = navigator.serviceWorker.register(workerURL,{scope:"/"})
      .then(registration => {
        if (navigator.onLine) {
          registration.active?.postMessage({type:"dmate:prepare-offline"});
          // Existing clients should discover the new release immediately;
          // a first install already has an installing worker and needs no
          // second update/download job competing with its initial preparation.
          if (registration.active && !registration.installing && !registration.waiting)
            void registration.update().catch(() => {});
        }
        return registration;
      }).catch(error => {
        console.warn("DMate 离线资源准备失败：",error);
        preparation = null;
      });
    return preparation;
  }
  async function automaticallyOpenOffline() {
    // New native hosts own their bundled fallback. Older clients still use the
    // browser cache path; a user-agent string alone is not a capability signal.
    if (!button || navigator.onLine || opening
      || window.__DMATE_NATIVE_OFFLINE_AVAILABLE__ === true) return;
    if (checking) { checkAgain = true; return; }
    checking = true;
    try {
      if (!await shellIsCached()) {
        if (!navigator.onLine) showPreparationNotice();
        return;
      }
      if (!navigator.onLine) await openOfflineWorkspace(true);
    } finally {
      checking = false;
      if (checkAgain) { checkAgain = false; void automaticallyOpenOffline(); }
    }
  }
  async function openOfflineWorkspace(automatic = false) {
    if (opening) return;
    opening = true;
    if (button) {
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
    }
    // Opening local mode never copies the signed-in account's cloud records.
    // ZIP export/import is the explicit transfer mechanism between the modes.
    void prepareOfflineResources();
    clearPreparationNotice();
    // Draft checkpoint listeners can run before navigation; pagehide remains
    // the final synchronous checkpoint for the existing conversation state.
    window.dispatchEvent(new CustomEvent("dmate:before-offline-navigation",{detail:{automatic}}));
    if (automatic && window.DMateAccountOcrDrafts?.flush) {
      let timer;
      try {
        await Promise.race([
          Promise.resolve().then(() => window.DMateAccountOcrDrafts.flush()).catch(() => {}),
          new Promise(resolve => { timer = setTimeout(resolve,750); })
        ]);
      } finally { clearTimeout(timer); }
    }
    if (automatic) window.location.replace("/offline");
    else window.location.assign("/offline");
  }
  if (button) {
    // Removing the native title also invalidates an already-held tooltip
    // through ui-tooltip's title observer. aria-label remains available.
    button.removeAttribute("title");
    button.addEventListener("click", () => { void openOfflineWorkspace(); });
  }
  window.addEventListener("pageshow", event => {
    if (!event.persisted) return;
    opening = false;
    if (button) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
    void automaticallyOpenOffline();
  });
  window.addEventListener("offline",() => { void automaticallyOpenOffline(); });
  window.addEventListener("online",() => {
    clearPreparationNotice();
    preparation = null;
    void prepareOfflineResources();
  });
  if (supportsWorker) {
    navigator.serviceWorker.addEventListener("controllerchange",() => { void automaticallyOpenOffline(); });
    navigator.serviceWorker.addEventListener("message",event => {
      if (event.source?.scriptURL === workerURL && event.data?.type === "dmate:offline-ready")
        void automaticallyOpenOffline();
    });
  }
  // Start before window.load: already-open pages can lose their connection
  // while other assets are still loading, and restored pages may start offline.
  void prepareOfflineResources();
  void automaticallyOpenOffline();
})();
