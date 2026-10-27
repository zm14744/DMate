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
        const sha256 = client.kind === 'android'
            && typeof item.sha256 === 'string' && /^[a-fA-F0-9]{64}$/.test(item.sha256)
            ? item.sha256.toLowerCase() : null;
        return { version:item.version, url:item.url, sha256, platform:client.platform };
    }
    // Newer APKs have an origin-restricted native download bridge.
    // Older APKs still use the official browser-download path.
    function downloadInsideAndroid(update) {
        const bridge = root.DMateUpdate;
        if (!bridge?.postMessage || !update.sha256) return Promise.resolve(null);
        const id = 'native-update-' + Date.now() + '-' + Math.random().toString(36).slice(2);
        return new Promise(resolve => {
            let settled = false;
            let previous;
            let timer;
            const onMessage = event => {
                let response;
                try { response = JSON.parse(event.data); } catch (_err) { return; }
                if (response?.id === id) finish(response);
            };
            const chained = event => {
                onMessage(event);
                if (typeof previous === 'function') previous(event);
            };
            const finish = result => {
                if (settled) return;
                settled = true;
                clearTimeout(timer);
                bridge.removeEventListener?.('message', onMessage);
                if (bridge.onmessage === chained) bridge.onmessage = previous;
                resolve(result);
            };
            previous = bridge.onmessage;
            if (typeof bridge.addEventListener === 'function') {
                bridge.addEventListener('message', onMessage);
            } else bridge.onmessage = chained;
            timer = setTimeout(() => finish({ ok:false, message:'更新请求超时' }), 15000);
            try {
                bridge.postMessage(JSON.stringify({
                    id, url:update.url, version:update.version, sha256:update.sha256
                }));
            } catch (_err) {
                finish({ ok:false, message:'无法启动应用内下载' });
            }
        });
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
            createButton(doc, '下载更新', async () => {
                if (client.kind === 'android') {
                    if (root.DMateUpdate?.postMessage && update.sha256) {
                        description.textContent = '正在请求系统后台下载…';
                        const result = await downloadInsideAndroid(update);
                        description.textContent = String(result?.message ||
                            '应用内更新不可用，请使用下方官方链接');
                        return;
                    }
                    // Legacy APKs cannot gain a new native bridge via web code.
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
