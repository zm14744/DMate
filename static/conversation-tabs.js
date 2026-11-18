/* Native conversation links, with an explicit, memory-only same-origin handoff. */
(function () {
    "use strict";
    const CHANNEL = "dmate-conversation-tabs-v1";
    const LIFETIME = 3 * 60 * 1000;
    const grants = new Map();
    const sessionTokens = new Map();
    const initialUrl = new URL(window.location.href);
    const requestedId = initialUrl.searchParams.get("conversation") || "";
    const requestedToken = initialUrl.searchParams.get("handoff") || "";
    let routeReady = false;
    let destinationInteracted = false;
    let channel = null;
    let responseHandler = null;
    try { channel = new BroadcastChannel(CHANNEL); } catch (_error) {}

    function context() {
        return { owner: accountState.authenticated ? accountState.username : "", version: cloudSyncContextVersion };
    }
    function ready() {
        return guestWorkspaceReady && accountState.configured !== null
            && !accountVerificationOperation && !accountVerificationPending
            && !cloudInitialSyncInFlight && !cloudInitialSyncPending;
    }
    function liveSession(id) {
        return !deletedSessionIds[String(id)] && sessions.find(item => String(item.id) === String(id));
    }
    function sameContext(left, right) {
        return left.owner === right.owner && left.version === right.version;
    }
    function randomToken() {
        return Array.from(crypto.getRandomValues(new Uint8Array(24)), byte => byte.toString(16).padStart(2, "0")).join("");
    }
    function linkFor(id) {
        const owner = context(), now = Date.now();
        let token = sessionTokens.get(id);
        const grant = grants.get(token);
        if (!grant || grant.expires <= now || !sameContext(grant.context, owner)) {
            if (token) grants.delete(token);
            token = randomToken();
            grants.set(token, { id, context: owner, expires: now + LIFETIME });
            sessionTokens.set(id, token);
        }
        const url = new URL(window.location.href);
        url.searchParams.set("conversation", id);
        url.searchParams.set("handoff", token);
        url.hash = "";
        return url.href;
    }
    function enhanceRows() {
        const ids = new Set(sessions.map(session => String(session.id))), owner = context(), now = Date.now();
        for (const [token, grant] of grants) {
            if (grant.expires <= now || !ids.has(grant.id) || !sameContext(grant.context, owner)) {
                grants.delete(token);
                if (sessionTokens.get(grant.id) === token) sessionTokens.delete(grant.id);
            }
        }
        for (const row of document.querySelectorAll("#sessions > [data-session-id]")) {
            const id = row.dataset.sessionId;
            let link = row.querySelector(".conversation-tab-link");
            if (!link) {
                const name = row.querySelector("[data-session-name]");
                if (!name) continue;
                link = document.createElement("a");
                link.className = "conversation-tab-link";
                link.target = "_blank";
                link.rel = "noopener";
                name.before(link);
                link.append(name);
                row.draggable = true;
                row.querySelector(".del")?.setAttribute("draggable", "false");
            }
            // Do not churn href attributes on every application render.
            const href = linkFor(id);
            if (link.href !== href) link.href = href;
        }
        if (routeReady && requestedId) {
            const url = new URL(window.location.href);
            url.searchParams.delete("handoff");
            if (currentId != null) url.searchParams.set("conversation", String(currentId));
            else url.searchParams.delete("conversation");
            if (url.href !== window.location.href) history.replaceState(history.state, "", url);
        }
    }
    function exportConversation(id) {
        const session = liveSession(id);
        if (!session) return null;
        const images = typeof exportConversationOcrTasks === "function" ? exportConversationOcrTasks(id) : [];
        return {
            session: JSON.parse(JSON.stringify(session)),
            draft: window.DMateConversationDrafts?.get(id) || null,
            images,
            running: busySessionIds.has(sessionBusyKey(id)) || isOcrBatchPreparing(id) || isOcrSendInProgress(id)
                || getSessionOcrTasks(id).some(image => image.state === "recognizing" || image.sending || image.confirming)
        };
    }
    if (channel) channel.onmessage = event => {
        const message = event.data;
        if (!message || typeof message !== "object") return;
        if (message.type === "response") {
            responseHandler?.(message);
            return;
        }
        if (message.type !== "request" || typeof message.nonce !== "string" || !ready()) return;
        const grant = grants.get(message.token), owner = context();
        if (!grant || grant.expires <= Date.now() || !sameContext(grant.context, owner)
            || grant.id !== message.id || message.owner !== owner.owner) return;
        const payload = exportConversation(grant.id);
        if (!payload || !sameContext(grant.context, context())) return;
        if (!grant.established) {
            grant.established = true;
            grant.expires = Date.now() + 6 * 60 * 1000;
        }
        try {
            channel.postMessage({ type: "response", token: message.token, nonce: message.nonce, owner: owner.owner, payload });
        } catch (_error) { /* A closed source page cannot transfer a snapshot. */ }
    };
    function receiveConversation() {
        if (!channel || !/^[a-f0-9]{48}$/.test(requestedToken)) return Promise.resolve(null);
        const nonce = randomToken(), owner = context();
        return new Promise(resolve => {
            let interval = 0;
            const finish = payload => {
                clearInterval(interval);
                clearTimeout(timeout);
                responseHandler = null;
                resolve(payload);
            };
            const timeout = setTimeout(() => finish(null), 6000);
            responseHandler = message => {
                if (message.token !== requestedToken || message.nonce !== nonce || message.owner !== owner.owner) return;
                finish(sameContext(owner, context()) ? message.payload : null);
            };
            const request = () => {
                if (!sameContext(owner, context())) { finish(null); return; }
                channel.postMessage({ type: "request", token: requestedToken, nonce, id: requestedId, owner: owner.owner });
            };
            interval = setInterval(request, 300);
            request();
        });
    }
    function importConversation(payload) {
        const incoming = payload?.session;
        if (!incoming || String(incoming.id) !== requestedId || !Array.isArray(incoming.messages)
            || deletedSessionIds[requestedId]) return false;
        const normalized = normalizeCloudSessionMessages(incoming);
        const existing = liveSession(requestedId);
        if (existing) {
            const previousSessions = [...sessions];
            const merged = mergeCloudSnapshots(
                { sessions: { sessions: [normalized] } },
                { sessions: { sessions: [existing] } }
            ).sessions.sessions;
            for (const session of merged) {
                const index = sessions.findIndex(item => String(item.id) === String(session.id));
                if (index >= 0) sessions[index] = session;
                else sessions.push(session);
            }
            preserveActiveCloudSessionIdentities(previousSessions);
        } else sessions.unshift(normalized);
        currentId = liveSession(requestedId).id;
        saveState();
        renderAll();
        if (payload.draft) window.DMateConversationDrafts?.set(currentId, payload.draft);
        if (typeof importConversationOcrTasks === "function") importConversationOcrTasks(currentId, payload.images, {replaceRestored:true});
        checkpointGuestDrafts();
        return true;
    }
    function imageSignature(row) {
        return JSON.stringify(row, (key, value) => key === "file" ? undefined : value);
    }
    function messageSignature(session) {
        return JSON.stringify({messages:session.messages.map(message => [message.messageId, message.role, message.text]),
            deleted:session.deletedMessageIds});
    }
    async function followSource(initial, owner) {
        const deadline = Date.now() + 6 * 60 * 1000;
        let pending = initial.running, sessionSignature = JSON.stringify(initial.session);
        let followMessages = true, messageBaseline = messageSignature(liveSession(requestedId));
        const imageSources = new Map((initial.images || []).map(row => [row.id, imageSignature(row)]));
        const imageBaselines = new Map((typeof exportConversationOcrTasks === "function"
            ? exportConversationOcrTasks(requestedId) : []).map(row => [row.id, imageSignature(row)]));
        while (pending && Date.now() < deadline && sameContext(owner, context()) && liveSession(requestedId)) {
            await new Promise(resolve => setTimeout(resolve, 1000));
            const payload = await receiveConversation();
            if (!payload || !sameContext(owner, context()) || !liveSession(requestedId)) return;
            pending = payload.running;
            let changed = false;
            const nextSignature = JSON.stringify(payload.session);
            const current = liveSession(requestedId);
            if (messageSignature(current) !== messageBaseline || activeAiRequests.has(sessionBusyKey(requestedId))) followMessages = false;
            if (followMessages && nextSignature !== sessionSignature && String(payload.session?.id) === requestedId) {
                const previousSessions = [...sessions], existing = liveSession(requestedId);
                const merged = mergeCloudSnapshots({ sessions: { sessions: [existing] } },
                    { sessions: { sessions: [normalizeCloudSessionMessages(payload.session)] } }).sessions.sessions;
                for (const session of merged) {
                    const index = sessions.findIndex(item => String(item.id) === String(session.id));
                    if (index >= 0) sessions[index] = session;
                    else sessions.push(session);
                }
                preserveActiveCloudSessionIdentities(previousSessions);
                sessionSignature = nextSignature;
                messageBaseline = messageSignature(liveSession(requestedId));
                changed = true;
            }
            if (typeof exportConversationOcrTasks === "function" && typeof importConversationOcrTasks === "function") {
                const targetImages = new Map(exportConversationOcrTasks(requestedId).map(row => [row.id, row]));
                for (const row of payload.images || []) {
                    const signature = imageSignature(row);
                    if (signature === imageSources.get(row.id)) continue;
                    imageSources.set(row.id, signature);
                    const target = targetImages.get(row.id);
                    if (!target || imageSignature(target) !== imageBaselines.get(row.id)) continue;
                    const old = ocrTasks.get(row.id);
                    if (!old || old.state === "recognizing" || old.sending || old.confirming || ocrEditorTaskId === old.id) continue;
                    ocrTasks.delete(row.id);
                    URL.revokeObjectURL(old.originalUrl);
                    importConversationOcrTasks(requestedId, [row]);
                    const imported = exportConversationOcrTasks(requestedId).find(item => item.id === row.id);
                    if (imported) imageBaselines.set(row.id, imageSignature(imported));
                    changed = true;
                }
                const sourceIds = new Set((payload.images || []).map(row => row.id));
                for (const id of imageSources.keys()) {
                    if (sourceIds.has(id)) continue;
                    imageSources.delete(id);
                    const target = targetImages.get(id), task = ocrTasks.get(id);
                    if (!target || !task || imageSignature(target) !== imageBaselines.get(id)
                        || task.state === "recognizing" || task.sending || task.confirming || ocrEditorTaskId === id) continue;
                    ocrTasks.delete(id);
                    URL.revokeObjectURL(task.originalUrl);
                    renderOcrTasks();
                    changed = true;
                }
            }
            if (changed) {
                saveState();
                renderAll();
                checkpointGuestDrafts();
            }
        }
    }
    async function openRequestedConversation() {
        if (!requestedId || requestedId.length > 160) { routeReady = true; return; }
        // Authentication must finish before any account-owned history can enter this page.
        const deadline = Date.now() + 30000;
        while (!ready() && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 100));
        if (!ready()) return;
        const owner = context();
        if (owner.owner && window.DMateAccountOcrDrafts?.ready) await window.DMateAccountOcrDrafts.ready();
        if (!sameContext(owner, context())) return;
        let opened = false;
        let followup = null;
        if (requestedToken) {
            const payload = await receiveConversation();
            if (destinationInteracted) opened = true;
            else if (payload && sameContext(owner, context())) {
                opened = importConversation(payload);
                if (opened && payload.running) followup = payload;
            }
        } else {
            const session = liveSession(requestedId);
            if (destinationInteracted) opened = true;
            else if (session) {
                currentId = session.id;
                saveState();
                renderAll();
                opened = true;
            }
        }
        if (!sameContext(owner, context())) return;
        const url = new URL(window.location.href);
        url.searchParams.delete("handoff");
        if (!opened) {
            url.searchParams.delete("conversation");
            showCopyToast("无法打开此对话，请从原标签页重新拖出");
        }
        history.replaceState(history.state, "", url);
        routeReady = true;
        enhanceRows();
        if (followup) void followSource(followup, owner);
    }
    document.addEventListener("dragstart", event => {
        const row = event.target.closest?.("#sessions > [data-session-id]");
        if (!row || event.target.closest("button") || !event.dataTransfer) return;
        const url = linkFor(row.dataset.sessionId);
        event.dataTransfer.clearData();
        event.dataTransfer.setData("text/uri-list", url);
        event.dataTransfer.setData("text/plain", url);
        event.dataTransfer.effectAllowed = "link";
    }, true);
    document.addEventListener("click", event => {
        const link = event.target.closest?.(".conversation-tab-link");
        if (!link) return;
        link.href = linkFor(link.closest("[data-session-id]").dataset.sessionId);
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
            // Let the native link open a new tab without selecting it in this page.
            event.stopPropagation();
        } else {
            event.preventDefault();
            if (event.target === link) link.querySelector("[data-session-name]")?.click();
        }
    }, true);
    for (const type of ["pointerdown", "contextmenu", "auxclick"]) document.addEventListener(type, event => {
        const row = event.target.closest?.("#sessions > [data-session-id]");
        if (!row || event.target.closest("button")) return;
        const link = row.querySelector(".conversation-tab-link");
        if (link) link.href = linkFor(row.dataset.sessionId);
    }, true);
    for (const type of ["pointerdown", "keydown", "input"]) document.addEventListener(type, event => {
        if (requestedId && !routeReady && event.isTrusted) destinationInteracted = true;
    }, true);
    window.addEventListener("dmate:account-state", enhanceRows);
    const clearGrants = () => { grants.clear(); sessionTokens.clear(); };
    window.addEventListener("dmate:guest-session-end", clearGrants);
    window.addEventListener("pagehide", clearGrants);
    function initialize() {
        const box = document.getElementById("sessions");
        if (box) new MutationObserver(enhanceRows).observe(box, { childList: true });
        enhanceRows();
        void openRequestedConversation();
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize, { once: true });
    else initialize();
}());
