(() => {
  "use strict";
  const button = document.getElementById("offlineWorkspaceBtn");
  if (button) {
    button.addEventListener("click", () => {
      window.location.assign("/offline");
    });
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