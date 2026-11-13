(() => {
  "use strict";
  const button = document.getElementById("offlineWorkspaceBtn");
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
    if (button) {
      button.disabled = true;
      const label = button.querySelector(".dmate-ui-label");
      if (label) label.textContent = "准备中…";
    }
    await prepareCurrentAccountData();
    if ("serviceWorker" in navigator && window.isSecureContext) {
      try {
        await navigator.serviceWorker.register("/offline-service-worker.js", {scope:"/"});
        await Promise.race([
          navigator.serviceWorker.ready,
          new Promise((_, reject) => setTimeout(() => reject(new Error("离线资源准备超时")), 15000))
        ]);
      } catch (error) {
        console.warn("离线资源尚未完全准备：", error);
      }
    }
    window.location.assign("/offline");
  }
  if (button) {
    button.addEventListener("click", () => { void openOfflineWorkspace(); });
  }
  if (!("serviceWorker" in navigator) || !window.isSecureContext) {
    if (button) {
      button.title = "当前浏览器不支持离线缓存；仍可在线打开离线工作区";
    }
    return;
  }
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/offline-service-worker.js", {scope:"/"})
      .then(registration => registration.update().catch(() => {}))
      .catch(error => {
        console.warn("DMate 离线资源准备失败：", error);
        if (button) button.title = "离线缓存尚未准备成功，请稍后重试";
      });
  }, {once:true});
})();
