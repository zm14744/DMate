(() => {
    "use strict";
    const home = "https://dmate.zeabur.app/";
    const offline = home + "offline";
    const page = new URL(location.href);
    if (window !== window.top || page.username || page.password) return;

    const isStartup = page.pathname === "/start" && !page.port && !page.search && !page.hash
        && ((page.protocol === "dmate-offline:" && page.hostname === "localhost")
            || (page.protocol === "http:" && page.hostname === "dmate-offline.localhost"));
    if (isStartup) {
        if (navigator.onLine === false) { location.replace(offline); return; }
        const probe = new AbortController();
        const timeout = setTimeout(() => probe.abort(), 3500);
        fetch(home + "web-version", {
            mode:"no-cors", credentials:"omit", cache:"no-store", redirect:"error", signal:probe.signal
        }).then(() => location.replace(onlineDestination()), () => location.replace(offline))
            .finally(() => clearTimeout(timeout));
        return;
    }

    function onlineDestination() {
        return navigator.onLine === false ? offline : home;
    }

    if (page.origin !== new URL(home).origin || page.searchParams.get("dmate_native_offline_unavailable") === "1") return;
    Object.defineProperty(window, "__DMATE_NATIVE_OFFLINE_AVAILABLE__", {value:true});
    if (page.pathname === "/offline" || page.pathname === "/static/offline.html") return;
    let switching = false;
    async function enterOffline() {
        if (switching) return;
        switching = true;
        window.dispatchEvent(new CustomEvent("dmate:before-offline-navigation", {detail:{automatic:true}}));
        if (window.DMateAccountOcrDrafts?.flush) {
            let timer;
            try {
                await Promise.race([
                    Promise.resolve().then(() => window.DMateAccountOcrDrafts.flush()).catch(() => {}),
                    new Promise(resolve => { timer = setTimeout(resolve, 750); })
                ]);
            } finally { clearTimeout(timer); }
        }
        if (navigator.onLine === false) location.replace(offline);
        else switching = false;
    }
    window.addEventListener("offline", enterOffline);
    if (navigator.onLine === false) enterOffline();
})();
