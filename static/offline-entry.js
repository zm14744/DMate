(() => {
  "use strict";
  const button = document.getElementById("offlineWorkspaceBtn");
  let opening = false;
  async function prepareCurrentAccountData() {
    const bridge = window.DMateOfflineBridge, handoff = window.DMateOfflineHandoff;
    if (!bridge?.snapshot || !handoff?.stage) throw new Error("离线数据接口尚未加载，请刷新后重试");
    const context = bridge.context?.();
    const owner = window.DMateGuestSession?.getOwner?.() || "";
    const isCurrent = () => (window.DMateGuestSession?.getOwner?.() || "") === owner
      && (!context || bridge.isCurrent?.(context) === true);
    const snapshot = await bridge.snapshot();
    if (!isCurrent()) throw new Error("账号状态已变化，请重新打开离线版");
    const pages = Array.isArray(snapshot.drawings) ? snapshot.drawings : [];
    const drawings = typeof snapshot.drawings === "string" ? snapshot.drawings
      : JSON.stringify({version:2,activeId:pages[0]?.id || "",pages});
    const token = await handoff.stage({
      username:snapshot.username || "",
      wrongQuestions:Array.isArray(snapshot.wrongQuestions) ? snapshot.wrongQuestions : [],
      notes:Array.isArray(snapshot.notes) ? snapshot.notes : [],
      appearance:snapshot.appearance || null,
      drawings
    }, {isCurrent});
    if (!isCurrent()) {
      await handoff.ack(token).catch(() => {});
      throw new Error("账号状态已变化，请重新打开离线版");
    }
    return token;
  }
  async function openOfflineWorkspace() {
    if (opening) return;
    opening = true;
    if (button) {
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
    }
    try { await prepareCurrentAccountData(); }
    catch (_error) {
      opening = false;
      if (button) {
        button.disabled = false;
        button.removeAttribute("aria-busy");
      }
      window.showCopyToast?.("离线内容未能安全保存，请稍后重试；当前页面内容仍保留");
      return;
    }
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
