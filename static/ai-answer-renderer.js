(function (root) {
    'use strict';
    // Every learning panel uses the shared sanitized Markdown/LaTeX pipeline.
    // Existing answer panels retain their own typography by default.
    let configured = {};
    let mathQueue = Promise.resolve();
    const renders = new WeakMap();
    const answerTypography = new WeakSet();

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
        const typography = options.typography || 'answer';
        const chat = typography === 'chat', inline = typography === 'inline';
        target.classList.add('dmate-ai-answer');
        // Keep semantic classes supplied by the caller. Only remove the
        // default answer class on mode changes when this renderer added it.
        if (!chat && !inline && !target.classList.contains('wrong-answer-inner')) {
            target.classList.add('wrong-answer-inner');
            answerTypography.add(target);
        } else if ((chat || inline) && answerTypography.has(target)) {
            target.classList.remove('wrong-answer-inner');
            answerTypography.delete(target);
        }
        if (target.dataset.dmateTypography === 'chat' && !chat) target.classList.remove('msg', 'ai', 'dmate-chat-answer');
        target.classList.toggle('dmate-inline-answer', inline);
        target.dataset.dmateTypography = typography;
        target.dataset.dmateRenderState = 'pending';
        try { root.MathJax?.typesetClear?.([target]); } catch (_) { /* A new panel may have no math yet. */ }
        let content = target;
        if (chat) {
            target.classList.add('msg', 'ai', 'dmate-chat-answer');
            const message = target.ownerDocument.createElement('div');
            message.className = 'msg-content';
            content = target.ownerDocument.createElement('div');
            content.className = 'ai-content math-pending';
            message.append(content);
            target.replaceChildren(message);
        }
        const source = String(value ?? '');
        try {
            if (typeof formatter !== 'function') throw new Error('Formatter unavailable');
            const html = formatter(source);
            if (typeof html !== 'string') throw new Error('Invalid formatted answer');
            if (inline) {
                const template = target.ownerDocument.createElement('template');
                template.innerHTML = html;
                const nodes = [...template.content.childNodes].filter(node => node.nodeType !== 3 || node.textContent.trim());
                if (nodes.length === 1 && nodes[0].nodeType === 1 && nodes[0].localName === 'p') {
                    target.replaceChildren(...nodes[0].childNodes);
                } else target.replaceChildren(template.content);
            } else content.innerHTML = html;
            target.classList.remove('dmate-ai-answer-plain');
        } catch (_) {
            // Late/unavailable page libraries retain the complete readable
            // answer; never insert raw model HTML as a fallback.
            content.textContent = source;
            target.classList.add('dmate-ai-answer-plain');
        }
        // MathJax operates on shared document state. Queue notebook sections
        // and drawing answers together instead of starting parallel typesets.
        operation.pending = mathQueue.catch(() => {}).then(async () => {
            if (!current() || !target.isConnected) return false;
            if (typeof typeset === 'function') await typeset(target);
            return current() && target.isConnected;
        }).catch(() => false).then(ready => {
            if (current()) {
                target.dataset.dmateRenderState = ready ? 'ready' : 'error';
                content.classList.remove('math-pending');
            }
            return ready;
        });
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
