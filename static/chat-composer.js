(function (root) {
    'use strict';
    const instances = new WeakMap();
    function mount(options) {
        const input = options.input;
        if (!input) throw new Error('消息输入框未加载。');
        if (instances.has(input)) return instances.get(input);
        const win = input.ownerDocument.defaultView || root;
        const composer = input.closest('.input');
        let composing = false, commitUntil = 0, destroyed = false, previousWidth = -1;
        function refresh() {
            if (destroyed) return;
            const style = win.getComputedStyle(input);
            const line = Number.parseFloat(style.lineHeight) || 24;
            const padding = (Number.parseFloat(style.paddingTop) || 0) + (Number.parseFloat(style.paddingBottom) || 0);
            const minimum = Math.max(40, line + padding);
            const viewport = win.visualViewport?.height || win.innerHeight || 700;
            const maximum = Math.max(minimum, Math.min(line * 6 + padding, Math.max(96, viewport * .3)));
            input.style.setProperty('max-height', maximum + 'px', 'important');
            input.style.setProperty('height', 'auto', 'important');
            const measured = input.scrollHeight || minimum;
            const height = Math.max(minimum, Math.min(maximum, measured));
            input.style.setProperty('height', height + 'px', 'important');
            input.style.setProperty('overflow-y', measured > maximum + 1 ? 'auto' : 'hidden', 'important');
            composer?.classList.toggle('composer-expanded', height > minimum + 2);
        }
        const compositionStart = () => { composing = true; };
        const compositionEnd = () => { composing = false; commitUntil = Date.now() + 40; refresh(); };
        function keydown(event) {
            if (event.key !== 'Enter' || event.shiftKey || event.altKey || event.ctrlKey || event.metaKey
                || composing || event.isComposing || event.keyCode === 229 || Date.now() < commitUntil) return;
            // A mobile keyboard's Return inserts a new line. Desktop Enter
            // sends; Shift+Enter always remains available for a new line.
            if (win.matchMedia?.('(max-width:680px)').matches || win.matchMedia?.('(pointer:coarse)').matches) return;
            event.preventDefault();
            if (!input.disabled && !input.readOnly) options.onSend?.();
        }
        const widthObserver = typeof win.ResizeObserver === 'function' ? new win.ResizeObserver(() => {
            const width = input.clientWidth;
            if (width !== previousWidth) { previousWidth = width; refresh(); }
        }) : null;
        widthObserver?.observe(input);
        input.addEventListener('input', refresh);
        input.addEventListener('compositionstart', compositionStart);
        input.addEventListener('compositionend', compositionEnd);
        input.addEventListener('keydown', keydown);
        win.addEventListener('resize', refresh);
        win.visualViewport?.addEventListener('resize', refresh);
        const api = { refresh, destroy() {
            if (destroyed) return;
            destroyed = true; widthObserver?.disconnect();
            input.removeEventListener('input', refresh);
            input.removeEventListener('compositionstart', compositionStart);
            input.removeEventListener('compositionend', compositionEnd);
            input.removeEventListener('keydown', keydown);
            win.removeEventListener('resize', refresh);
            win.visualViewport?.removeEventListener('resize', refresh);
            instances.delete(input);
        } };
        instances.set(input, api); refresh();
        return api;
    }
    root.DMateChatComposer = { mount };
})(typeof window !== 'undefined' ? window : globalThis);
