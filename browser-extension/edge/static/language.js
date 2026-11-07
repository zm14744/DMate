/* Account-scoped, device-local UI language. Never translate learning content. */
(function (root) {
    'use strict';
    const ACCOUNT_KEY_PREFIX = 'dmate_ui_language_v1::';
    let account = {authenticated: false, username: ''};
    const exact = Object.assign(Object.create(null), root.DMateLanguageCatalog?.exact || {});
    const patterns = [...(root.DMateLanguageCatalog?.patterns || [])];
    const reverse = new Map(), textSources = new WeakMap(), attributeSources = new WeakMap();
    const attrs = ['aria-label', 'title', 'placeholder', 'alt'];
    const contentSelector = [
        '[data-i18n-content]', '[translate="no"]', '[contenteditable]:not([contenteditable="false"])',
        '.msg-content', '.ai-content', '.wrong-question', '.wrong-note-body',
        '.wrong-feedback-body', '.wrong-answer-inner', '.wrong-analysis-body',
        '.wrong-pdf-question', '.kg-history-preview', '.ocr-review-rendered',
        '.dcn-ai-result', '.dcn-result', '.dge-text-excerpt', '.dge-text-body',
        'mjx-container', 'math', 'code', 'pre', 'script', 'style', 'textarea'
    ].join(',');
    let current = 'zh-CN', bound = false;
    function accountLanguageKey() { return ACCOUNT_KEY_PREFIX + encodeURIComponent(account.username); }
    function readSavedLanguage() {
        if (!account.authenticated || !account.username) return 'zh-CN';
        try { return root.localStorage.getItem(accountLanguageKey()) === 'en' ? 'en' : 'zh-CN'; }
        catch (_) { return 'zh-CN'; }
    }
    function register(values, extraPatterns) {
        Object.assign(exact, values || {});
        for (const [zh, en] of Object.entries(values || {})) {
            if (typeof en === 'string' && zh.trim() && !Object.prototype.hasOwnProperty.call(exact, zh.trim())) exact[zh.trim()] = en.trim();
        }
        if (Array.isArray(extraPatterns)) patterns.push(...extraPatterns);
        reverse.clear();
        Object.entries(exact).forEach(([zh, en]) => {
            if (typeof en !== 'string') return;
            if (!reverse.has(en)) reverse.set(en, zh);
            if (!reverse.has(en.trim())) reverse.set(en.trim(), zh.trim());
        });
    }
    register({
        '界面语言 / Language': 'Language', '语言 / Language': 'Language',
        '简体中文': '简体中文', 'English': 'English',
        'DMate - 离散数学智能辅学系统': 'DMate - Discrete Mathematics Tutor'
    });
    if (root.DMateKnowledgeLanguage?.labels) register(root.DMateKnowledgeLanguage.labels);
    function english(source, override) {
        if (typeof override === 'string') return override;
        if (Object.prototype.hasOwnProperty.call(exact, source)) return exact[source];
        for (const [pattern, replacement] of patterns) {
            pattern.lastIndex = 0;
            if (pattern.test(source)) { pattern.lastIndex = 0; return source.replace(pattern, replacement); }
        }
        return source;
    }
    function t(source, translation) {
        const value = String(source ?? '');
        if (typeof translation === 'string' && exact[value] !== translation) register({[value]: translation});
        if (current !== 'en') return value;
        const result = english(value, translation);
        // Explicitly rendered parameterized labels must also round-trip when
        // the language changes, just like observer-translated source nodes.
        if (result !== value && !reverse.has(result)) register({[value]: result});
        return result;
    }
    function protectedContent(element) {
        if (!element?.closest) return false;
        if (element.closest('script,style,textarea,mjx-container,math,code,pre,[contenteditable]:not([contenteditable="false"])')) return true;
        const zone = element.closest('[data-i18n-content],[translate="no"],[data-i18n-ui]');
        if (zone) return !zone.hasAttribute('data-i18n-ui');
        return Boolean(element.closest(contentSelector));
    }
    function translatedValue(value, record, override) {
        const source = record && value === record.last ? record.source : (reverse.get(value) || value);
        return {source, last: current === 'en' ? english(source, override) : source};
    }
    function translateText(node) {
        if (!node || node.nodeType !== 3 || protectedContent(node.parentElement)) return;
        const raw = node.nodeValue, trimmed = raw.trim();
        if (!trimmed) return;
        const record = translatedValue(trimmed, textSources.get(node), node.parentElement?.dataset.i18nEn);
        record.last = record.last.trim();
        textSources.set(node, record);
        if (record.last !== trimmed) node.nodeValue = raw.slice(0, raw.indexOf(trimmed)) + record.last + raw.slice(raw.indexOf(trimmed) + trimmed.length);
    }
    function translateAttributes(element) {
        if (!element?.getAttribute) return;
        // A textarea's value is user content; its placeholder and accessibility
        // labels are interface text and can be translated independently.
        if (protectedContent(element)) {
            if (!element.matches('textarea:not([translate="no"]):not([data-i18n-content])')
                || element.parentElement?.closest('[data-i18n-content],[translate="no"]')) return;
        }
        const records = attributeSources.get(element) || new Map();
        for (const attr of attrs) {
            const value = element.getAttribute(attr);
            if (!value) continue;
            const record = translatedValue(value, records.get(attr));
            records.set(attr, record);
            if (record.last !== value) element.setAttribute(attr, record.last);
        }
        attributeSources.set(element, records);
    }
    function translate(scope) {
        if (!scope) return;
        if (scope.nodeType === 3) { translateText(scope); return; }
        if (scope.nodeType === 1) { translateAttributes(scope); if (protectedContent(scope)) return; }
        const walker = document.createTreeWalker(scope, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
            acceptNode(node) {
                if (node.nodeType === 1 && node.tagName === 'TEXTAREA') translateAttributes(node);
                return protectedContent(node.nodeType === 1 ? node : node.parentElement) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
            }
        });
        while (walker.nextNode()) {
            const node = walker.currentNode;
            if (node.nodeType === 3) translateText(node); else translateAttributes(node);
        }
    }
    function refreshLanguageControls() {
        document.documentElement.lang = current;
        document.documentElement.dataset.uiLanguage = current;
        document.title = t('DMate - 离散数学智能辅学系统');
        document.querySelectorAll('head meta[data-i18n-en]').forEach(element => {
            const records = attributeSources.get(element) || new Map();
            const value = element.getAttribute('content') || '';
            const record = translatedValue(value, records.get('content'), element.dataset.i18nEn);
            records.set('content', record);
            attributeSources.set(element, records);
            if (record.last !== value) element.setAttribute('content', record.last);
        });
        document.querySelectorAll('[data-dmate-language]').forEach(button => {
            const active = button.dataset.dmateLanguage === current;
            button.classList.toggle('active', active);
            button.setAttribute('aria-pressed', String(active));
        });
    }
    function setLanguage(language, persist = true) {
        const next = language === 'en' ? 'en' : 'zh-CN', previous = current;
        current = next;
        if (persist && account.authenticated && account.username) {
            try { root.localStorage.setItem(accountLanguageKey(), current); } catch (_) {}
        }
        refreshLanguageControls();
        translate(document.body);
        // In-place switching preserves drafts, streams, focus and cloud work.
        if (previous !== current) root.dispatchEvent(new CustomEvent('dmate:languagechange', {detail: {language: current, previous}}));
        translate(document.body);
        try {
            if (root.DMateLanguage?.postMessage) root.DMateLanguage.postMessage(JSON.stringify({language: current}));
            else root.DMateLanguage?.setLanguage?.(current);
        } catch (_) {}
    }
    function handleAccountState(detail) {
        const next = {
            authenticated: detail?.authenticated === true,
            username: detail?.authenticated === true ? String(detail.username || '') : ''
        };
        if (next.authenticated === account.authenticated && next.username === account.username) return;
        account = next;
        setLanguage(readSavedLanguage(), false);
    }
    root.addEventListener('dmate:account-state', event => handleAccountState(event.detail));
    function bind() {
        if (bound) return;
        bound = true;
        const html = document.documentElement;
        if (html.dataset.accountStateKnown === '1') handleAccountState({
            authenticated: html.dataset.accountAuthenticated === '1',
            username: html.dataset.accountUsername || ''
        });
        document.querySelectorAll('[data-dmate-language]').forEach(button => {
            button.addEventListener('click', () => setLanguage(button.dataset.dmateLanguage));
        });
        setLanguage(current, false);
        // Watch in both languages. Self-writes are idempotent; streaming/user
        // text is pruned. Never modify input values or business identifiers.
        new MutationObserver(records => {
            for (const record of records) {
                if (record.type === 'characterData') translateText(record.target);
                else if (record.type === 'attributes') translateAttributes(record.target);
                else record.addedNodes.forEach(translate);
            }
        }).observe(document.body, {childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: attrs});
    }
    root.DMateI18n = Object.freeze({getLanguage: () => current, isEnglish: () => current === 'en', setLanguage, t, register, translate});
    // Translate API errors too, without altering body, signal, credentials or
    // streaming semantics. Never send the language header to another origin.
    if (typeof root.fetch === 'function' && typeof root.Headers === 'function') {
        const originalFetch = root.fetch.bind(root);
        root.fetch = function (input, init) {
            let options = init;
            try {
                const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url, root.location.href);
                if (url.origin === root.location.origin && !/^\/(?:static\/|web-version(?:$|\?)|favicon|robots|sitemap)/.test(url.pathname)) {
                    const headers = new Headers(init?.headers ?? input?.headers);
                    if (!headers.has('X-DMate-Language')) headers.set('X-DMate-Language', current);
                    options = {...init, headers};
                }
            } catch (_) {}
            return originalFetch(input, options);
        };
    }
    refreshLanguageControls();
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind, {once: true});
    else bind();
})(window);
