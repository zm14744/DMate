/* Synchronize EXISTING DMate WebView/Tauri shells with live Zeabur code.
 * Only HTML/JS/CSS and server-side features update here. Android Java,
 * desktop Rust and other native code cannot be replaced by web cache.
 * No Service Worker is registered; no application/package installation.
 */
(function(root) {
    'use strict';

    const CHECK_INTERVAL_MS = 10 * 60 * 1000;
    const RETRY_GUARD_MS = 90 * 1000;
    const RETRY_KEY = 'dmate-remote-web-refresh-attempt-v1';
    const WEB_REVISION_ENDPOINT = '/web-version';
    const installedRevision = String(root.DMATE_WEB_REVISION || '');
    let lastChecked = 0;
    let inFlight = false;
    let pendingRevision = '';

    const isRevision = value => /^[a-f0-9]{64}$/i.test(String(value || ''));
    function isInstalledShell() {
        const config = root.DMATE_CLIENT_CONFIG || {};
        const ua = String(root.navigator?.userAgent || '');
        return config.isAndroidApp === true || config.isDesktopApp === true ||
            /DMateAndroid\/|DMateDesktop\//i.test(ua);
    }
    function hasUnsavedWork(doc) {
        if (!doc || doc.hidden) return true;
        const input = doc.getElementById?.('text');
        if (typeof input?.value === 'string' && input.value.trim()) return true;
        const panel = doc.getElementById?.('ocrTaskPanel');
        if (panel && !panel.hidden) return true;
        const wrap = doc.querySelector?.('.input-wrap');
        const mode = wrap?.dataset?.busyMode;
        if (mode && mode !== 'idle') return true;
        if (doc.querySelector?.('dialog[open], .modal:not(.hidden)')) return true;
        const active = doc.activeElement;
        if (active && /^(INPUT|TEXTAREA)$/i.test(active.tagName || '')
            && active !== input && String(active.value || '').trim()) return true;
        return false;
    }
    function tryRefresh(revision) {
        if (!isRevision(revision) || revision === installedRevision) return false;
        if (hasUnsavedWork(root.document)) {
            pendingRevision = revision;
            return false;
        }
        try {
            const previous = JSON.parse(root.sessionStorage?.getItem(RETRY_KEY) || '{}');
            if (previous.revision === revision &&
                Date.now() - Number(previous.at || 0) < RETRY_GUARD_MS) return false;
            root.sessionStorage?.setItem(RETRY_KEY, JSON.stringify({
                revision, at:Date.now()
            }));
        } catch (_error) {
            // Private mode may deny sessionStorage; the no-store HTTP headers
            // still make subsequent navigation fetch the live document.
        }
        pendingRevision = '';
        try {
            const url = new URL('/', root.location.origin);
            url.searchParams.set('dmate_web_revision', revision.slice(0, 16));
            root.location.replace(url.pathname + url.search);
            return true;
        } catch (_error) {
            return false;
        }
    }
    async function checkNow(force) {
        if (!isInstalledShell() || !isRevision(installedRevision)) return false;
        if (pendingRevision && tryRefresh(pendingRevision)) return true;
        if (inFlight || (!force && Date.now() - lastChecked < CHECK_INTERVAL_MS)) return false;
        inFlight = true;
        lastChecked = Date.now();
        try {
            const response = await root.fetch(
                WEB_REVISION_ENDPOINT + '?t=' + Date.now(),
                {cache:'no-store', credentials:'same-origin'}
            );
            if (!response.ok) return false;
            const body = await response.json();
            const revision = typeof body?.revision === 'string' ? body.revision : '';
            if (!isRevision(revision) || revision === installedRevision) return false;
            return tryRefresh(revision);
        } catch (_error) {
            // Disconnected devices keep the last working page without failure.
            return false;
        } finally {
            inFlight = false;
        }
    }
    const api = {isInstalledShell, hasUnsavedWork, checkNow};
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    if (!root.document) return;
    root.DMateWebSync = api;
    const launch = () => { void checkNow(true); };
    if (root.document.readyState === 'loading') {
        root.document.addEventListener('DOMContentLoaded', launch, {once:true});
    } else {
        launch();
    }
    root.document.addEventListener('visibilitychange', () => {
        if (!root.document.hidden) void checkNow(true);
    });
    root.addEventListener?.('focus', () => void checkNow(false));
    root.navigator?.serviceWorker?.addEventListener?.('message', event => {
        if (event.data?.type === 'dmate-old-worker-retired') void checkNow(true);
    });
    root.setInterval?.(() => void checkNow(false), CHECK_INTERVAL_MS);
})(typeof window !== 'undefined' ? window : globalThis);
