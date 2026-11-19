/* Injected by the native host before page scripts. This token is never stored. */
(() => {
    "use strict";
    const page = new URL(location.href);
    if (window !== window.top || page.origin !== "https://dmate.zeabur.app"
        || page.username || page.password
        || !["/offline", "/static/offline.html"].includes(page.pathname)) return;
    const bridgeToken = "__DMATE_OFFLINE_VAULT_TOKEN__";
    const invoke = window.__TAURI_INTERNALS__?.invoke;
    if (typeof invoke !== "function") return;
    const api = Object.freeze({
        async request(request) {
            try {
                return await invoke("dmate_offline_vault", {request, bridgeToken});
            } catch (error) {
                if (error && typeof error.code === "string" && typeof error.message === "string") throw error;
                // Tauri deserialization/permission diagnostics may echo inputs.
                // Do not pass arbitrary native errors into the application logs.
                throw {code:"NATIVE_UNAVAILABLE", message:"The native offline vault is unavailable"};
            }
        }
    });
    Object.defineProperty(window, "DMateOfflineVaultDesktop", {value:api, writable:false, configurable:false});
})();
