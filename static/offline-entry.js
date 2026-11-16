(() => {
  "use strict";
  const button = document.getElementById("offlineWorkspaceBtn");
  let opening = false;
  async function prepareCurrentAccountData() {
    try {
      let snapshot = window.DMateOfflineBridge?.snapshot ? await window.DMateOfflineBridge.snapshot() : null;
      if (!snapshot) {
        const root = document.documentElement;
        const username = root.dataset.accountAuthenticated === "1" ? root.dataset.accountUsername : "";
        let drawings = "";
        if (username) {
          const galleryKey = "dmate:graph-gallery:v1::" + encodeURIComponent("account:" + username);
          const drawingKey = "dmate:graph-drawing:v1";
          drawings = localStorage.getItem(galleryKey) || "";
          if (!drawings && localStorage.getItem(drawingKey + ":owner") === "account:" + username) {
            const legacy = localStorage.getItem(drawingKey);
            if (legacy) {
              try {
                const document = JSON.parse(legacy);
                drawings = JSON.stringify({version:1,pages:[{id:"legacy-local",name:document.graphs?.[0]?.name || "我的绘图",document,updatedAt:Date.now()}]});
              } catch (_) {}
            }
          }
        }
        snapshot = { username, drawings };
      }
      const pages = Array.isArray(snapshot.drawings) ? snapshot.drawings : [];
      const drawings = typeof snapshot.drawings === "string" ? snapshot.drawings
        : JSON.stringify({version:2,activeId:pages[0]?.id || "",pages});
      sessionStorage.setItem("dmate_offline_migration_v1", JSON.stringify({
        username: snapshot.username || "",
        drawings
      }));
    } catch (error) {
      console.warn("DMate 离线数据准备未完成：", error);
    }
  }
  async function openOfflineWorkspace() {
    if (opening) return;
    opening = true;
    if (button) {
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
    }
    await prepareCurrentAccountData();
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
