/* DMate installed-client update notification. The OS remains responsible for
   permission to install packages. A signed Tauri updater is intentionally not
   impersonated by this web-only compatibility layer. */
(function (root) {
    'use strict';

    const MANIFEST = '/static/client-updates.json';
    const CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000;
    let lastChecked = 0;
    let checking = false;

    function triplet(value) {
        const match = /^(?:v)?(\d+)\.(\d+)\.(\d+)$/.exec(String(value || ''));
        const parts = match ? match.slice(1).map(Number) : null;
        return parts?.every(Number.isSafeInteger) ? parts : null;
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
            if (/mac|darwin/.test(os)) os = 'macos';
            else if (/windows|win/.test(os)) os = 'windows';
            else if (/linux/.test(os)) os = 'linux';
            else return null;
            return { kind:'desktop', platform:os, version:desktop[1] };
        }
        return null;
    }
    function releaseAsset(client, value) {
        // These release filenames are ASCII. Reject encoded or normalized path
        // tricks before URL parsing can discard dot segments or backslashes.
        if (typeof value !== 'string' || /[\u0000-\u0020\u007f%\\?#]/.test(value)
            || /(?:^|\/)\.{1,2}(?:\/|$)/.test(value)) return null;
        if (!/^https:\/\/(?:github\.com|api\.gitcode\.com)\//i.test(value)) return null;
        try {
            const url = new URL(value);
            if (url.protocol !== 'https:' || url.port || url.username || url.password
                || url.search || url.hash) return null;
            const match = url.hostname === 'github.com'
                ? /^\/zm14744\/DMate\/releases\/download\/(v?\d+\.\d+\.\d+)\/([A-Za-z0-9][A-Za-z0-9._-]*)$/.exec(url.pathname)
                : url.hostname === 'api.gitcode.com'
                    ? /^\/api\/v5\/repos\/zm14744\/DMate\/releases\/(v?\d+\.\d+\.\d+)\/attach_files\/([A-Za-z0-9][A-Za-z0-9._-]*)\/download$/.exec(url.pathname)
                    : null;
            if (!match || match[2].includes('..')) return null;
            const filenamePattern = client.kind === 'android'
                ? /^DMate-Android-(\d+\.\d+\.\d+)\.apk$/
                : client.platform === 'windows'
                    ? /^DMate_(\d+\.\d+\.\d+)_x64-setup\.exe$/
                    : client.platform === 'macos'
                        ? /^DMate_(\d+\.\d+\.\d+)_universal\.dmg$/
                        : client.platform === 'linux'
                            ? /^DMate_(\d+\.\d+\.\d+)_amd64\.(AppImage|deb)$/ : null;
            const filename = filenamePattern?.exec(match[2]);
            if (!filename) return null;
            const format = client.kind === 'android' ? 'APK'
                : client.platform === 'windows' ? 'EXE'
                    : client.platform === 'macos' ? 'DMG'
                        : filename[2] === 'deb' ? 'DEB' : 'AppImage';
            return { url:url.href, tag:match[1], filename:match[2],
                version:filename[1], format,
                source:url.hostname === 'github.com' ? 'github' : 'gitcode' };
        } catch (_err) {
            return null;
        }
    }
    function selectPublishedUpdate(client, manifest) {
        if (!client || !manifest || manifest.schema !== 1) return null;
        const item = client.kind === 'android'
            ? manifest.android
            : manifest.desktop?.[client.platform];
        if (!item || item.published !== true ||
            compareVersions(item.version, client.version) !== 1) return null;
        const version = String(item.version).replace(/^v/, '');
        // Sources can be published at different times. An older mirror must
        // not hide a ready release or offer an older installer as its update.
        function currentAsset(details) {
            const candidates = [details?.url, ...(Array.isArray(details?.fallbackUrls) ? details.fallbackUrls : [])];
            for (const value of candidates) {
                const asset = releaseAsset(client, value);
                if (asset?.version === version) return asset;
            }
            return null;
        }
        const primary = currentAsset(item);
        if (!primary) return null;
        // Mirrors must point to the very same file, while distinct Linux
        // formats are separate choices rather than interchangeable fallbacks.
        function packageFor(asset, details) {
            const seen = new Set([asset.url]);
            const fallbackUrls = [];
            for (const value of Array.isArray(details.fallbackUrls) ? details.fallbackUrls : []) {
                const mirror = releaseAsset(client, value);
                if (!mirror || mirror.filename !== asset.filename
                    || mirror.tag !== asset.tag || seen.has(mirror.url)) continue;
                seen.add(mirror.url);
                fallbackUrls.push(mirror.url);
            }
            return { format:asset.format, url:asset.url, fallbackUrls };
        }
        const packages = [packageFor(primary, item)];
        if (client.kind === 'desktop' && client.platform === 'linux') {
            const formats = new Set([primary.format]);
            for (const entry of Array.isArray(item.additionalPackages) ? item.additionalPackages : []) {
                const asset = currentAsset(entry);
                if (!asset || asset.version !== version || asset.tag !== primary.tag
                    || formats.has(asset.format)) continue;
                formats.add(asset.format);
                packages.push(packageFor(asset, entry));
            }
        }
        const fallbackUrls = packages[0].fallbackUrls;
        const sha256 = client.kind === 'android'
            && typeof item.sha256 === 'string' && /^[a-fA-F0-9]{64}$/.test(item.sha256)
            ? item.sha256.toLowerCase() : null;
        return { version:item.version, url:primary.url, fallbackUrls, sha256,
            platform:client.platform, packages,
            notarized:client.platform === 'macos' ? item.notarized : undefined };
    }
    const dismissed = new Set();
    let pendingUpdate = null;
    let pendingTimer = 0;

    function dismissalKey(client, update) {
        return 'dmate-client-update-dismissed:' + client.platform + ':' + update.version;
    }
    function wasDismissed(key) {
        if (dismissed.has(key)) return true;
        try { return root.sessionStorage?.getItem(key) === '1'; } catch (_error) { return false; }
    }
    function canShowNotice(doc) {
        if (!doc?.body || doc.hidden) return false;
        try {
            if (typeof root.dmateCanShowClientUpdate !== 'function'
                || !root.dmateCanShowClientUpdate()) return false;
        } catch (_error) { return false; }
        if (doc.querySelector('dialog[open], .modal:not(.hidden), .dmate-png-save-dialog')) return false;
        if (doc.body.classList.contains('mobile-left-open')
            || doc.body.classList.contains('mobile-tools-open')
            || doc.body.classList.contains('mobile-keyboard-open')) return false;
        const active = doc.activeElement;
        if (active?.isContentEditable) return false;
        if (active && /^(INPUT|TEXTAREA|SELECT)$/.test(active.tagName)
            && (active.tagName === 'SELECT' || String(active.value || '').trim())) return false;
        return true;
    }
    function uiText(chinese, english) {
        return root.DMateI18n?.t ? root.DMateI18n.t(chinese, english)
            : root.DMateI18n?.isEnglish?.() === true ? english : chinese;
    }
    function showNotice(client, update) {
        const doc = root.document;
        const key = dismissalKey(client, update);
        if (!doc?.body || wasDismissed(key) || doc.getElementById('dmateClientUpdateNotice')) return false;
        const previousFocus = doc.activeElement;
        const box = doc.createElement('dialog');
        box.id = 'dmateClientUpdateNotice';
        box.className = 'dmate-update-dialog';
        box.setAttribute('aria-labelledby', 'dmateClientUpdateTitle');
        box.setAttribute('aria-describedby', 'dmateClientUpdateDescription');
        const head = doc.createElement('div');
        head.className = 'modal-head';
        const title = doc.createElement('h2');
        title.id = 'dmateClientUpdateTitle';
        title.textContent = uiText('更新 DMate', 'Update DMate');
        const close = doc.createElement('button');
        close.className = 'modal-close-dot';
        close.type = 'button';
        close.title = uiText('关闭', 'Close');
        close.setAttribute('aria-label', uiText('关闭更新提醒', 'Close update reminder'));
        const body = doc.createElement('div');
        body.className = 'dmate-update-body';
        const description = doc.createElement('p');
        description.id = 'dmateClientUpdateDescription';
        description.textContent = uiText('发现新版本 ' + update.version + '，需要下载并安装新安装包。',
            'Version ' + update.version + ' is available. Download and install the new package to update.');
        body.append(description);
        if (client.platform === 'macos' && update.notarized === false) {
            const note = doc.createElement('p');
            note.className = 'download-description';
            note.textContent = uiText('macOS 安装包尚未经过 Apple 公证。',
                'The macOS installer has not been notarized by Apple.');
            body.append(note);
        }
        const packages = update.packages || [{ url:update.url, fallbackUrls:update.fallbackUrls }];
        let selectedPackage = packages[0];
        let picker = null;
        if (packages.length > 1) {
            const label = doc.createElement('label');
            label.className = 'dmate-update-format';
            label.textContent = uiText('安装包格式', 'Installer format');
            picker = doc.createElement('select');
            picker.setAttribute('aria-label', uiText('安装包格式', 'Installer format'));
            picker.dataset.dmateNativeSelect = 'true';
            for (const [index, item] of packages.entries()) {
                const option = doc.createElement('option');
                option.value = String(index);
                option.textContent = item.format;
                picker.append(option);
            }
            label.append(picker);
            body.append(label);
        }
        const hint = doc.createElement('p');
        hint.className = 'download-description';
        hint.textContent = uiText('选择下载源', 'Choose a download source');
        const links = doc.createElement('div');
        links.className = 'download-actions dmate-update-actions';
        const fallback = doc.createElement('div');
        fallback.className = 'dmate-update-fallback';
        fallback.hidden = true;
        const status = doc.createElement('p');
        status.setAttribute('role', 'status');
        const address = doc.createElement('input');
        address.type = 'text';
        address.readOnly = true;
        address.setAttribute('aria-label', uiText('新安装包下载地址', 'New installer download address'));
        address.addEventListener('click', () => address.select());
        const copy = doc.createElement('button');
        copy.type = 'button';
        copy.textContent = uiText('复制下载地址', 'Copy download link');
        copy.addEventListener('click', async () => {
            const value = address.value;
            let copied = false;
            try {
                if (root.navigator?.clipboard?.writeText) {
                    await root.navigator.clipboard.writeText(value);
                    copied = true;
                }
            } catch (_error) {}
            if (!box.isConnected || address.value !== value) return;
            if (!copied) {
                address.focus({ preventScroll:true });
                address.select();
                try { copied = Boolean(doc.execCommand?.('copy')); } catch (_error) {}
            }
            status.textContent = copied
                ? uiText('下载地址已复制，请在浏览器中打开。', 'The download link was copied. Open it in your browser.')
                : uiText('请手动选中下载地址，复制到浏览器中打开。', 'Select and copy the download link, then open it in your browser.');
        });
        fallback.append(status, address, copy);
        const renderLinks = () => {
            links.textContent = '';
            fallback.hidden = true;
            address.value = '';
            const urls = [selectedPackage.url, ...(selectedPackage.fallbackUrls || [])];
            for (const [host, label] of [['api.gitcode.com', 'GitCode'], ['github.com', 'GitHub']]) {
                const url = urls.find(value => new URL(value).hostname === host);
                if (!url) continue;
                const link = doc.createElement('a');
                link.href = url;
                link.textContent = label;
                link.rel = 'noopener noreferrer';
                if (links.childElementCount) link.className = 'secondary';
                if (client.kind === 'desktop') {
                    link.target = '_blank';
                    link.addEventListener('click', () => {
                        // Older Tauri shells may block new windows. Keep the
                        // workspace in place and provide a copyable address.
                        address.value = url;
                        status.textContent = uiText('如果没有开始下载，可复制地址到浏览器中打开。',
                            'If the download does not start, copy the link and open it in your browser.');
                        fallback.hidden = false;
                    });
                }
                // Android's native navigation handler opens external URLs in
                // the browser; do not invoke a nonexistent install bridge.
                links.append(link);
            }
        };
        picker?.addEventListener('change', () => {
            selectedPackage = packages[Number(picker.value)] || packages[0];
            renderLinks();
        });
        renderLinks();
        body.append(hint, links, fallback);
        head.append(title, close);
        box.append(head, body);
        let finished = false;
        let overlay = null;
        const finish = () => {
            if (finished) return;
            finished = true;
            dismissed.add(key);
            try { root.sessionStorage?.setItem(key, '1'); } catch (_error) {}
            if (box.open && typeof box.close === 'function') box.close();
            box.remove();
            overlay?.remove();
            root.requestAnimationFrame(() => {
                if (previousFocus?.isConnected && !previousFocus.disabled
                    && !doc.querySelector('dialog[open], .modal:not(.hidden), .dmate-png-save-dialog')) {
                    previousFocus.focus?.({ preventScroll:true });
                }
            });
        };
        close.addEventListener('click', finish);
        box.addEventListener('cancel', event => { event.preventDefault(); finish(); });
        box.addEventListener('close', finish);
        box.addEventListener('keydown', event => {
            if (event.key === 'Escape') {
                event.preventDefault(); event.stopPropagation(); finish();
            } else if (event.key === 'Tab') {
                const controls = [...box.querySelectorAll('button, a[href], select, input')]
                    .filter(node => !node.disabled && node.getClientRects().length);
                const first = controls[0], last = controls[controls.length - 1];
                if (event.shiftKey && doc.activeElement === first) {
                    event.preventDefault(); last?.focus();
                } else if (!event.shiftKey && doc.activeElement === last) {
                    event.preventDefault(); first?.focus();
                }
            }
        });
        box.addEventListener('pointerdown', event => {
            if (event.target !== box) return;
            const rect = box.getBoundingClientRect();
            if (event.clientX < rect.left || event.clientX > rect.right
                || event.clientY < rect.top || event.clientY > rect.bottom) finish();
        });
        doc.body.append(box);
        try {
            if (typeof box.showModal === 'function') box.showModal();
            else {
                overlay = doc.createElement('div');
                overlay.className = 'dmate-update-overlay';
                overlay.addEventListener('pointerdown', event => { if (event.target === overlay) finish(); });
                doc.body.append(overlay);
                overlay.append(box);
                box.setAttribute('open', '');
                box.setAttribute('role', 'dialog');
                box.setAttribute('aria-modal', 'true');
            }
            close.focus({ preventScroll:true });
            return true;
        } catch (_error) {
            box.remove(); overlay?.remove();
            return false;
        }
    }
    function tryPendingNotice() {
        if (pendingTimer) root.clearTimeout(pendingTimer);
        pendingTimer = 0;
        if (!pendingUpdate) return;
        const {client, update} = pendingUpdate;
        if (wasDismissed(dismissalKey(client, update))) {
            pendingUpdate = null;
            return;
        }
        if (canShowNotice(root.document) && showNotice(client, update)) {
            pendingUpdate = null;
        } else if (!root.document?.hidden) {
            pendingTimer = root.setTimeout(tryPendingNotice, 1500);
        }
    }
    async function checkForUpdates(force = false) {
        if (!root.document || checking) return;
        const client = detectInstalledClient(
            root.navigator?.userAgent, root.DMATE_CLIENT_CONFIG, root.navigator?.platform
        );
        if (!client) return;
        tryPendingNotice();
        if (!force && lastChecked && Date.now() - lastChecked < CHECK_INTERVAL_MS) return;
        checking = true;
        const controller = typeof root.AbortController === 'function' ? new root.AbortController() : null;
        const timer = controller ? root.setTimeout(() => controller.abort(), 10000) : 0;
        try {
            const response = await root.fetch(MANIFEST, {
                cache:'no-store', credentials:'same-origin', ...(controller ? { signal:controller.signal } : {})
            });
            if (!response.ok) return;
            const update = selectPublishedUpdate(client, await response.json());
            lastChecked = Date.now();
            pendingUpdate = update ? {client, update} : null;
            tryPendingNotice();
        } catch (_error) {
            // Offline checks never interrupt the workspace or show an error dialog.
        } finally {
            if (timer) root.clearTimeout(timer);
            checking = false;
        }
    }
    const api = { compareVersions, detectInstalledClient, selectPublishedUpdate, checkForUpdates };
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    if (!root.document) return;
    root.DMateClientUpdate = api;
    if (!detectInstalledClient(root.navigator?.userAgent, root.DMATE_CLIENT_CONFIG, root.navigator?.platform)) return;
    if (root.document.readyState === 'loading') {
        root.document.addEventListener('DOMContentLoaded', () => void checkForUpdates(), { once:true });
    } else {
        void checkForUpdates();
    }
    root.document.addEventListener('visibilitychange', () => {
        tryPendingNotice();
        if (!root.document.hidden) void checkForUpdates();
    });
    root.addEventListener?.('online', () => void checkForUpdates(true));
    root.addEventListener?.('pageshow', () => void checkForUpdates());
    root.addEventListener?.('focus', () => { tryPendingNotice(); void checkForUpdates(); });
    root.setInterval(() => void checkForUpdates(), CHECK_INTERVAL_MS);
})(typeof window !== 'undefined' ? window : globalThis);
