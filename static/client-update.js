/* DMate installed-client update notification. The OS remains responsible for
   permission to install packages. A signed Tauri updater is intentionally not
   impersonated by this web-only compatibility layer. */
(function (root) {
    'use strict';

    const MANIFEST = '/static/client-updates.json';
    const CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000;
    const OFFICIAL_RELEASE_PREFIX = 'https://github.com/zm14744/DMate/releases/';
    let lastChecked = 0;
    let checking = false;

    function triplet(value) {
        const match = /^(?:v)?(\d+)\.(\d+)\.(\d+)$/.exec(String(value || ''));
        return match ? match.slice(1).map(Number) : null;
    }
    function compareVersions(a, b) {
        const va = triplet(a), vb = triplet(b);
        if (!va || !vb) return null;
        for (let i = 0; i < 3; i++) {
            if (va[i] !== vb[i]) return va[i] > vb[i] ? 1 : -1;
        }
        return 0;
    }
    function detectInstalledClient(ua, config, platform) {
        const agent = String(ua || '');
        const android = /DMateAndroid\/(\d+\.\d+\.\d+)/i.exec(agent);
        if (android && (config?.isAndroidApp !== false)) {
            return { kind:'android', platform:'android', version:android[1] };
        }
        const desktop = /DMateDesktop\/(\d+\.\d+\.\d+)/i.exec(agent);
        if (desktop && (config?.isDesktopApp !== false)) {
            let os = String(platform || '').toLowerCase();
            if (/windows|win/.test(os)) os = 'windows';
            else if (/mac|darwin/.test(os)) os = 'macos';
            else if (/linux/.test(os)) os = 'linux';
            else return null;
            return { kind:'desktop', platform:os, version:desktop[1] };
        }
        return null;
    }
    function selectPublishedUpdate(client, manifest) {
        if (!client || !manifest || manifest.schema !== 1) return null;
        const item = client.kind === 'android'
            ? manifest.android
            : manifest.desktop?.[client.platform];
        if (!item || item.published !== true ||
            compareVersions(item.version, client.version) !== 1 ||
            typeof item.url !== 'string' ||
            !item.url.startsWith(OFFICIAL_RELEASE_PREFIX)) return null;
        try {
            const url = new URL(item.url);
            if (url.protocol !== 'https:' || url.hostname !== 'github.com' ||
                !url.pathname.startsWith('/zm14744/DMate/releases/download/') ||
                url.username || url.password || url.search || url.hash) return null;
            const ext = client.kind === 'android' ? /\.apk$/i :
                client.platform === 'windows' ? /\.exe$/i :
                client.platform === 'macos' ? /\.dmg$/i : /\.(?:deb|AppImage)$/i;
            if (!ext.test(url.pathname)) return null;
        } catch (_err) {
            return null;
        }
        return { version:item.version, url:item.url, platform:client.platform };
    }
    function createButton(doc, label, handler, primary) {
        const button = doc.createElement('button');
        button.type = 'button';
        button.textContent = label;
        if (primary) button.className = 'dmate-update-primary';
        button.addEventListener('click', handler);
        return button;
    }
    function showNotice(client, update) {
        const doc = root.document;
        if (!doc?.body || doc.getElementById('dmateClientUpdateNotice')) return;
        const key = 'dmate-client-update-dismissed:' + client.platform + ':' + update.version;
        try { if (root.sessionStorage.getItem(key) === '1') return; } catch (_err) {}
        const box = doc.createElement('aside');
        box.id = 'dmateClientUpdateNotice';
        box.className = 'dmate-update-notice';
        box.setAttribute('role', 'status');
        box.setAttribute('aria-live', 'polite');
        const title = doc.createElement('h3');
        title.textContent = 'DMate 有新版本 ' + update.version;
        const description = doc.createElement('p');
        description.textContent = client.kind === 'android'
            ? '点击更新下载安装包，系统会要求确认安装。无需先卸载旧版。'
            : '点击更新获取新版安装包。系统可能要求确认安装。';
        const actions = doc.createElement('div');
        actions.className = 'dmate-update-actions';
        actions.append(
            createButton(doc, '稍后', () => {
                try { root.sessionStorage.setItem(key, '1'); } catch (_err) {}
                box.remove();
            }, false),
            createButton(doc, '下载更新', () => {
                if (client.kind === 'android') {
                    // Android's host WebView intercepts non-DMate navigation
                    // and opens the OS browser. Android verifies APK signatures.
                    root.location.assign(update.url);
                } else {
                    // Remote Tauri webviews may block popups; keep copyable link.
                    const opened = root.open(update.url, '_blank', 'noopener,noreferrer');
                    if (!opened) {
                        description.textContent = '如果未打开浏览器，请使用下方下载地址。';
                    }
                }
            }, true),
        );
        const link = doc.createElement('a');
        link.className = 'dmate-update-url';
        link.href = update.url;
        link.textContent = '下载地址';
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        box.append(title, description, actions, link);
        doc.body.append(box);
    }
    async function checkForUpdates() {
        if (!root.document || checking) return;
        const client = detectInstalledClient(
            root.navigator?.userAgent, root.DMATE_CLIENT_CONFIG,
            root.navigator?.platform
        );
        if (!client) return;
        if (Date.now() - lastChecked < CHECK_INTERVAL_MS) return;
        checking = true;
        lastChecked = Date.now();
        try {
            const response = await root.fetch(MANIFEST, { cache:'no-store', credentials:'same-origin' });
            if (!response.ok) return;
            const update = selectPublishedUpdate(client, await response.json());
            if (update) showNotice(client, update);
        } catch (_err) {
            // Offline use and blocked update checks must not break DMate.
        } finally {
            checking = false;
        }
    }
    const api = { compareVersions, detectInstalledClient, selectPublishedUpdate, checkForUpdates };
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    if (root.document) {
        if (root.document.readyState === 'loading') {
            root.document.addEventListener('DOMContentLoaded', checkForUpdates, { once:true });
        } else {
            void checkForUpdates();
        }
        root.document.addEventListener('visibilitychange', () => {
            if (!root.document.hidden) void checkForUpdates();
        });
        root.setInterval(() => void checkForUpdates(), CHECK_INTERVAL_MS);
    }
})(typeof window !== 'undefined' ? window : globalThis);
