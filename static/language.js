/* DMate bilingual UI foundation.
 * Language is a device-local preference, independent of account/cloud data.
 * The initial dictionary covers the shell and appearance controls; additional
 * workspaces can be migrated incrementally without changing their behavior.
 */
(function (root) {
    'use strict';

    const ACCOUNT_KEY_PREFIX = 'dmate_ui_language_v1::';
    const LANGS = Object.freeze({ ZH: 'zh-CN', EN: 'en' });
    let account = { authenticated: false, username: '' };

    function accountLanguageKey() {
        return ACCOUNT_KEY_PREFIX + encodeURIComponent(account.username || '');
    }

    function readSavedLanguage() {
        if (!account.authenticated || !account.username) return LANGS.ZH;
        try {
            return localStorage.getItem(accountLanguageKey()) === LANGS.EN ? LANGS.EN : LANGS.ZH;
        } catch (_) {
            return LANGS.ZH;
        }
    }
    const DICT = {
        '外观': 'Appearance',
        '下载 DMate': 'Download DMate',
        '下载 DMate 桌面版': 'Download DMate Desktop',
        '登录 / 注册': 'Sign in / Register',
        '账号': 'Account',
        '关闭': 'Close',
        '背景预览': 'Background Preview',
        '显示模式': 'Display Mode',
        '跟随系统': 'System',
        '白色': 'Light',
        '黑色': 'Dark',
        '蓝色': 'Navy',
        '主题色': 'Accent Color',
        '文字大小': 'Text Size',
        '小': 'Small',
        '标准': 'Standard',
        '大': 'Large',
        '全局背景': 'Global Background',
        '无': 'None',
        '选择图片': 'Choose Image',
        '移除背景': 'Remove Background',
        '背景显示': 'Background Display',
        '填充': 'Fill',
        '适应': 'Fit',
        '背景遮罩': 'Background Overlay',
        '背景模糊': 'Background Blur',
        '界面面板透明度': 'Panel Opacity',
        '聊天气泡透明度': 'Chat Bubble Opacity',
        '更改会先预览，点击“确认”后才保存': 'Changes are previewed first. Select “Confirm” to save.',
        '恢复默认': 'Reset to Default',
        '确认': 'Confirm',
        '用户名或邮箱': 'Username or Email',
        '密码': 'Password',
        '登录': 'Sign In',
        '注册': 'Register',
        '忘记密码': 'Forgot Password',
        '未登录时不会保存信息': 'Information is not saved while signed out.',
        '注册账号': 'Create Account',
        '用户名': 'Username',
        '邮箱': 'Email',
        '取消': 'Cancel',
        '开始': 'Start',
        '节点详情': 'Node Details',
        '题目历史': 'Question History',
        '最近一题关联': 'Related to Recent Question',
        '全部知识': 'All Knowledge',
        '以图片形式复制': 'Copy as Image',
        '最近一题相关': 'Related to Recent Question',
        '点击左侧知识点查看它与其它知识点的直接关系': 'Select a concept on the left to view its direct relationships.',
        '知识图谱加载中…': 'Loading knowledge graph…',
        '语言 / Language': 'Language',
        '简体中文': 'Simplified Chinese',
        'English': 'English'
    };

    function getLanguage() {
        return current;
    }

    let current = LANGS.ZH;
    let applying = false;

    function translateTextNode(node) {
        if (!node || node.nodeType !== Node.TEXT_NODE) return;
        const source = node.nodeValue;
        const trimmed = source.trim();
        if (!trimmed || !Object.prototype.hasOwnProperty.call(DICT, trimmed)) return;
        const translated = DICT[trimmed];
        const leading = source.match(/^\s*/)?.[0] || '';
        const trailing = source.match(/\s*$/)?.[0] || '';
        node.nodeValue = leading + translated + trailing;
    }

    function translateTree(scope) {
        if (current !== LANGS.EN || !scope) return;
        const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
        const nodes = [];
        while (walker.nextNode()) nodes.push(walker.currentNode);
        nodes.forEach(translateTextNode);
        scope.querySelectorAll?.('[aria-label],[title],[placeholder]').forEach(el => {
            for (const attr of ['aria-label', 'title', 'placeholder']) {
                const value = el.getAttribute(attr);
                if (value && DICT[value]) el.setAttribute(attr, DICT[value]);
            }
        });
    }

    function setLanguage(language, persist) {
        current = language === LANGS.EN ? LANGS.EN : LANGS.ZH;
        if (persist !== false && account.authenticated && account.username) {
            try { localStorage.setItem(accountLanguageKey(), current); } catch (_) {}
        }
        document.documentElement.lang = current;
        document.documentElement.dataset.uiLanguage = current;
        document.querySelectorAll('[data-dmate-language]').forEach(button => {
            const active = button.dataset.dmateLanguage === current;
            button.classList.toggle('active', active);
            button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (current === LANGS.EN) {
            translateTree(document.body);
        } else if (persist !== false) {
            // Rebuild the source-language DOM only after an explicit user switch.
            root.location.reload();
        }
    }

    function handleAccountState(detail) {
        const next = {
            authenticated: detail?.authenticated === true,
            username: detail?.authenticated === true ? String(detail.username || '') : ''
        };
        const changed = next.authenticated !== account.authenticated || next.username !== account.username;
        if (!changed) return;
        account = next;
        // Guests always start in Chinese and never retain a language preference.
        // Signed-in users get a separate saved preference for their own account.
        setLanguage(readSavedLanguage(), false);
    }

    function bind() {
        root.addEventListener('dmate:account-state', event => handleAccountState(event.detail));
        document.querySelectorAll('[data-dmate-language]').forEach(button => {
            button.addEventListener('click', () => {
                const next = button.dataset.dmateLanguage;
                if (next === current) return;
                setLanguage(next, true);
            });
        });
        document.querySelectorAll('[data-i18n="languageTitle"]').forEach(node => {
            if (current === LANGS.EN) node.textContent = 'Language';
        });
        if (current === LANGS.EN) {
            translateTree(document.body);
            const observer = new MutationObserver(records => {
                if (applying) return;
                applying = true;
                for (const record of records) {
                    record.addedNodes.forEach(node => {
                        if (node.nodeType === Node.TEXT_NODE) translateTextNode(node);
                        else if (node.nodeType === Node.ELEMENT_NODE) translateTree(node);
                    });
                }
                applying = false;
            });
            observer.observe(document.body, { childList: true, subtree: true });
        }
        setLanguage(LANGS.ZH, false);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bind, { once: true });
    } else {
        bind();
    }

    root.DMateI18n = Object.freeze({
        getLanguage,
        setLanguage: language => setLanguage(language, true),
        isEnglish: () => current === LANGS.EN
    });
})(window);
