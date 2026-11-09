/* Delegated, accessible tooltips for titled interface controls. */
(function (root) {
    'use strict';
    const controls = 'button,a,[role="button"],summary';
    const content = '.msg-content,.ai-content,.wrong-question,.wrong-note-body,.wrong-feedback-body,.wrong-answer-inner,.wrong-analysis-body,.wrong-pdf-question,.kg-history-preview,.ocr-review-rendered,.dcn-ai-result,.dcn-result,.dge-text-excerpt,.dge-text-body';
    const excluded = 'mjx-container,math,code,pre,textarea,script,style,[contenteditable]:not([contenteditable="false"])';
    const held = new Map();
    let hovered = null, focused = null, intent = null, dismissed = null;
    let tooltip = null, visible = null, timer = null;

    function controlFor(node) {
        const element = node?.nodeType === 1 ? node : node?.parentElement;
        const control = element?.closest?.(controls);
        if (!control || control.closest(excluded)) return null;
        const zone = control.closest('[data-i18n-content],[translate="no"],[data-i18n-ui]');
        if (zone ? !zone.hasAttribute('data-i18n-ui') : control.closest(content)) return null;
        return held.has(control) || control.getAttribute('title')?.trim() ? control : null;
    }

    function connectObserver() {
        for (const control of held.keys()) observer.observe(control, {attributes:true, attributeFilter:['title']});
    }

    function updateLabel(control, record) {
        if (record.label !== null) {
            if (control.getAttribute('aria-label') === record.label) {
                record.label = record.title || '';
                control.setAttribute('aria-label', record.label);
            } else record.label = null;
        } else if (!control.hasAttribute('aria-label') && !control.hasAttribute('aria-labelledby')
            && !control.textContent.trim() && !control.querySelector('img[alt]:not([alt=""])')) {
            // An icon whose title supplied its name must keep that name while
            // the native title is suppressed, including during the hover delay.
            record.label = record.title || '';
            control.setAttribute('aria-label', record.label);
        }
    }

    function receiveTitles(mutations) {
        const changed = new Set(mutations.map(mutation => mutation.target));
        observer.disconnect();
        for (const control of changed) {
            const record = held.get(control);
            if (!record) continue;
            record.title = control.getAttribute('title');
            control.setAttribute('title', '');
            updateLabel(control, record);
        }
        connectObserver();
        if (visible && changed.has(visible)) {
            const title = held.get(visible)?.title;
            if (title?.trim()) {
                tooltip.textContent = title;
                place(visible);
            } else hide();
        }
    }

    // Observe only the (at most two) hovered/focused controls. This preserves
    // concurrent state/language title updates without watching page content.
    const observer = new MutationObserver(receiveTitles);
    function flushTitles() {
        const mutations = observer.takeRecords();
        if (mutations.length) receiveTitles(mutations);
    }

    function syncHeld() {
        flushTitles();
        observer.disconnect();
        for (const [control, record] of held) {
            if (control === hovered || control === focused) continue;
            // A concurrent writer owns any value other than our empty title.
            if (control.getAttribute('title') === '') {
                if (record.title === null) control.removeAttribute('title');
                else control.setAttribute('title', record.title);
            }
            if (record.label !== null && control.getAttribute('aria-label') === record.label) control.removeAttribute('aria-label');
            held.delete(control);
        }
        for (const control of [hovered, focused]) {
            if (!control || held.has(control)) continue;
            const record = {title:control.getAttribute('title'), label:null};
            held.set(control, record);
            // An empty attribute also blocks an ancestor's inherited title.
            control.setAttribute('title', '');
            updateLabel(control, record);
        }
        connectObserver();
        if (intent !== hovered && intent !== focused) {
            intent = null;
            dismissed = null;
        }
    }

    function hide() {
        root.clearTimeout(timer);
        timer = null;
        if (visible && tooltip) {
            const descriptions = (visible.getAttribute('aria-describedby') || '').split(/\s+/).filter(id => id && id !== tooltip.id);
            if (descriptions.length) visible.setAttribute('aria-describedby', descriptions.join(' '));
            else visible.removeAttribute('aria-describedby');
        }
        visible = null;
        if (tooltip) tooltip.hidden = true;
    }

    function dismiss() {
        dismissed = intent;
        hide();
    }

    function getTooltip() {
        if (!tooltip) {
            tooltip = document.createElement('div');
            let id = 'dmate-ui-tooltip';
            while (document.getElementById(id)) id += '-next';
            tooltip.id = id;
            tooltip.className = 'dm-ui-tooltip';
            tooltip.setAttribute('role', 'tooltip');
            tooltip.setAttribute('translate', 'no');
            tooltip.hidden = true;
        }
        return tooltip;
    }

    function place(control) {
        const anchor = control.getBoundingClientRect();
        if (!control.isConnected || !anchor.width || !anchor.height) { hide(); return false; }
        const viewport = root.visualViewport;
        const leftEdge = (viewport?.offsetLeft || 0) + 12;
        const topEdge = (viewport?.offsetTop || 0) + 12;
        const width = viewport?.width || document.documentElement.clientWidth;
        const height = viewport?.height || document.documentElement.clientHeight;
        const rightEdge = leftEdge + width - 24;
        const bottomEdge = topEdge + height - 24;
        tooltip.style.maxWidth = Math.max(0, Math.min(320, width - 24)) + 'px';
        tooltip.style.maxHeight = Math.max(0, height - 24) + 'px';
        tooltip.style.left = '0px';
        tooltip.style.top = '0px';
        const box = tooltip.getBoundingClientRect();
        const left = Math.max(leftEdge, Math.min(anchor.left + (anchor.width - box.width) / 2, rightEdge - box.width));
        const above = anchor.top - box.height - 8;
        const preferredTop = above >= topEdge ? above : anchor.bottom + 8;
        const top = Math.max(topEdge, Math.min(preferredTop, bottomEdge - box.height));
        // Usually fixed coordinates equal viewport coordinates. Subtracting the
        // origin also handles a dialog that establishes a containing block.
        const scaleX = tooltip.offsetWidth ? box.width / tooltip.offsetWidth : 1;
        const scaleY = tooltip.offsetHeight ? box.height / tooltip.offsetHeight : 1;
        tooltip.style.left = (left - box.left) / (scaleX || 1) + 'px';
        tooltip.style.top = (top - box.top) / (scaleY || 1) + 'px';
        return true;
    }

    function show(control) {
        timer = null;
        flushTitles();
        if (intent !== control || dismissed === control || !held.has(control)) return;
        const title = held.get(control).title;
        if (!title?.trim()) return;
        const popup = getTooltip();
        // A body overlay cannot appear above a native modal's top layer.
        const host = control.closest('dialog[open]') || document.body;
        if (!host) return;
        if (popup.parentNode !== host) host.appendChild(popup);
        popup.textContent = title;
        popup.hidden = false;
        if (!place(control)) return;
        visible = control;
        const descriptions = (control.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
        if (!descriptions.includes(popup.id)) descriptions.push(popup.id);
        control.setAttribute('aria-describedby', descriptions.join(' '));
    }

    function schedule(control, delay) {
        if (intent !== control) dismissed = null;
        intent = control;
        if (visible === control) return;
        hide();
        if (!control || dismissed === control) return;
        if (delay) timer = root.setTimeout(() => show(control), delay);
        else show(control);
    }

    document.addEventListener('pointerover', event => {
        if (event.pointerType === 'touch') return;
        const control = controlFor(event.target);
        if (control === hovered) return;
        hovered = control;
        syncHeld();
        schedule(control, 360);
    }, {capture:true, passive:true});

    document.addEventListener('pointerout', event => {
        if (event.pointerType === 'touch' || !hovered || hovered.contains(event.relatedTarget)) return;
        if (!hovered.contains(event.target)) return;
        hovered = null;
        hide();
        syncHeld();
    }, {capture:true, passive:true});

    document.addEventListener('focusin', event => {
        const control = controlFor(event.target);
        if (control === focused) return;
        focused = control;
        syncHeld();
        if (control?.matches(':focus-visible')) schedule(control, 0);
        else hide();
    }, true);

    document.addEventListener('focusout', event => {
        if (!focused || focused.contains(event.relatedTarget)) return;
        if (!focused.contains(event.target)) return;
        focused = null;
        hide();
        syncHeld();
    }, true);

    document.addEventListener('pointerdown', dismiss, {capture:true, passive:true});
    document.addEventListener('click', dismiss, {capture:true, passive:true});
    document.addEventListener('keydown', event => { if (event.key === 'Escape') dismiss(); }, true);
    root.addEventListener('scroll', dismiss, {capture:true, passive:true});
    root.addEventListener('resize', dismiss, {passive:true});
    root.visualViewport?.addEventListener('resize', dismiss, {passive:true});
    root.visualViewport?.addEventListener('scroll', dismiss, {passive:true});
    root.addEventListener('blur', dismiss);
    document.addEventListener('visibilitychange', () => { if (document.hidden) dismiss(); });
    root.addEventListener('dmate:languagechange', () => {
        hide();
        flushTitles();
        observer.disconnect();
        for (const [control, record] of held) {
            if (control.getAttribute('title') !== '') continue;
            if (record.title === null) control.removeAttribute('title');
            else control.setAttribute('title', record.title);
            // The language pass skips our suppressed empty title. Restoring it
            // for this control's pass lets the existing catalog round-trip it.
            root.DMateI18n?.translate(control);
            record.title = control.getAttribute('title');
            // The language pass also translates our temporary icon label. Keep
            // ownership of that matching value so it can still be removed.
            if (record.label !== null && control.getAttribute('aria-label') === record.title) record.label = record.title;
            control.setAttribute('title', '');
            updateLabel(control, record);
        }
        connectObserver();
    });
})(window);
