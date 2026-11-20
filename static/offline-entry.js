(() => {
  "use strict";
  const button = document.getElementById("offlineWorkspaceBtn");
  let opening = false;
  async function openOfflineWorkspace() {
    if (opening) return;
    opening = true;
    if (button) {
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
    }
    // Opening local mode never copies the signed-in account's cloud records.
    // ZIP export/import is the explicit transfer mechanism between the modes.
    if ("serviceWorker" in navigator && window.isSecureContext) {
      try {
        // Cache installation continues across the navigation. Enter the real
        // workspace without showing a preparation screen or waiting for every
        // offline asset to finish downloading.
        void navigator.serviceWorker.register("/offline-service-worker.js", {scope:"/"})
          .catch(error => console.warn("离线资源尚未完全准备：", error));
      } catch (error) {
        console.warn("离线资源尚未完全准备：", error);
      }
    }
    window.location.assign("/offline");
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
  });
  if (!("serviceWorker" in navigator) || !window.isSecureContext) {
    return;
  }
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/offline-service-worker.js", {scope:"/"})
      .then(registration => registration.update().catch(() => {}))
      .catch(error => {
        console.warn("DMate 离线资源准备失败：", error);
      });
  }, {once:true});
})();
