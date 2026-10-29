(function (root) {
    'use strict';
    // The wrong-question book already owns Markdown sanitizing, LaTeX
    // protection and MathJax. All learning panels call those same functions.
    let configured = {};
    let mathQueue = Promise.resolve();
    const renders = new WeakMap();

    function configure(options = {}) {
        configured = {
            markdownToHtml: typeof options.markdownToHtml === 'function' ? options.markdownToHtml : undefined,
            renderMath: typeof options.renderMath === 'function' ? options.renderMath : undefined
        };
    }

    function render(target, value, options = {}) {
        if (!target || !target.ownerDocument) return Promise.resolve(false);
        const operation = {};
        renders.set(target, operation);
        const current = () => renders.get(target) === operation
            && (typeof options.isCurrent !== 'function' || options.isCurrent());
        if (!current()) return Promise.resolve(false);
        const formatter = options.markdownToHtml || configured.markdownToHtml || root.markdownToHtml;
        const typeset = options.renderMath || configured.renderMath || root.renderMath;
        target.classList.add('wrong-answer-inner', 'dmate-ai-answer');
        try { root.MathJax?.typesetClear?.([target]); } catch (_) { /* A new panel may have no math yet. */ }
        const source = String(value ?? '');
        try {
            if (typeof formatter !== 'function') throw new Error('Formatter unavailable');
            const html = formatter(source);
            if (typeof html !== 'string') throw new Error('Invalid formatted answer');
            target.innerHTML = html;
            target.classList.remove('dmate-ai-answer-plain');
        } catch (_) {
            // Late/unavailable page libraries retain the complete readable
            // answer; never insert raw model HTML as a fallback.
            target.textContent = source;
            target.classList.add('dmate-ai-answer-plain');
        }
        // MathJax operates on shared document state. Queue notebook sections
        // and drawing answers together instead of starting parallel typesets.
        operation.pending = mathQueue.catch(() => {}).then(async () => {
            if (!current() || !target.isConnected) return false;
            if (typeof typeset === 'function') await typeset(target);
            return current() && target.isConnected;
        }).catch(() => false);
        mathQueue = operation.pending;
        return operation.pending;
    }

    function clear(target) {
        if (!target) return;
        renders.delete(target);
        try { root.MathJax?.typesetClear?.([target]); } catch (_) {}
        target.replaceChildren();
    }

    root.DMateAIAnswer = {configure, render, clear};
})(typeof window !== 'undefined' ? window : globalThis);
