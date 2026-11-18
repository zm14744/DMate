/* Ordinary multiline fields share the composer's grow-then-scroll behavior. */
(() => {
    'use strict';
    const root = window, doc = document;
    if (root.DMateTextareaAutosize) return;
    const records = new Map(), queued = new Set();
    const valueProperty = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value');
    let frame = 0;
    const eligible = input => input instanceof HTMLTextAreaElement && !input.readOnly
        && !input.matches('#text,.chat-message-edit-input,[data-dmate-autosize="off"]');
    const number = value => Number.parseFloat(value) || 0;
    const size = input => {
        const record = records.get(input);
        if (!record || !eligible(input) || !input.isConnected || !input.getClientRects().length || !input.clientWidth) return;
        const scroll = input.scrollTop;
        // Read the field's own CSS limits, independently from our previous cap.
        if (record.maxHeight) input.style.setProperty('max-height', record.maxHeight, record.maxPriority);
        else input.style.removeProperty('max-height');
        const css = root.getComputedStyle(input), border = number(css.borderTopWidth) + number(css.borderBottomWidth);
        const minimum = number(css.minHeight) || (number(css.lineHeight) || number(css.fontSize) * 1.4)
            + number(css.paddingTop) + number(css.paddingBottom) + border;
        const maximum = Math.max(minimum, Math.min(360, (root.visualViewport?.height || root.innerHeight || 800) * .45,
            number(css.maxHeight) || Infinity));
        input.style.setProperty('height', '0px', 'important');
        const measured = input.scrollHeight + border;
        input.style.setProperty('max-height', maximum + 'px', 'important');
        input.style.setProperty('height', Math.max(minimum, Math.min(maximum, measured)) + 'px', 'important');
        input.style.setProperty('overflow-y', measured > maximum + 1 ? 'auto' : 'hidden', 'important');
        input.scrollTop = Math.min(scroll, Math.max(0, input.scrollHeight - input.clientHeight));
        record.width = input.clientWidth;
    };
    const schedule = input => {
        if (input) queued.add(input);
        if (frame) return;
        frame = root.requestAnimationFrame(() => {
            frame = 0;
            const fields = [...queued]; queued.clear();
            for (const field of fields) size(field);
        });
    };
    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(entries => {
        for (const {target} of entries) if (records.get(target)?.width !== target.clientWidth) schedule(target);
    }) : null;
    const enhance = input => {
        if (!input.isConnected || !eligible(input) || records.has(input)) return;
        const record = {maxHeight:input.style.getPropertyValue('max-height'),
            maxPriority:input.style.getPropertyPriority('max-height'), width:0};
        records.set(input, record);
        input.classList.add('dmate-textarea-autosize');
        // Local setters catch existing programmatic form fills without changing
        // native values, selection, input events, or the shared DOM prototype.
        if (!Object.hasOwn(input, 'value') && valueProperty?.get && valueProperty?.set) {
            record.get = function () { return valueProperty.get.call(this); };
            Object.defineProperty(input, 'value', {configurable:true, enumerable:valueProperty.enumerable,
                get:record.get, set(value) { valueProperty.set.call(this, value); schedule(this); }});
        }
        observer?.observe(input); schedule(input);
    };
    const refresh = (scope = doc) => {
        if (scope instanceof HTMLTextAreaElement) { enhance(scope); schedule(scope); return; }
        for (const input of scope?.querySelectorAll?.('textarea') || []) { enhance(input); schedule(input); }
    };
    const refreshAll = () => refresh();
    root.DMateTextareaAutosize = Object.freeze({refresh});
    doc.addEventListener('input', event => { if (eligible(event.target)) { enhance(event.target); size(event.target); } });
    doc.addEventListener('focusin', event => { if (eligible(event.target)) refresh(event.target); });
    root.addEventListener('resize', refreshAll);
    root.visualViewport?.addEventListener('resize', refreshAll);
    root.addEventListener('dmate:languagechange', refreshAll);
    const start = () => {
        refresh();
        new MutationObserver(changes => {
            for (const change of changes) {
                if (change.type === 'attributes') {
                    if (records.has(change.target) && ['style', 'class'].includes(change.attributeName)) continue;
                    refresh(change.target);
                } else for (const node of change.addedNodes) refresh(node);
            }
            for (const [input, record] of records) if (!input.isConnected) {
                observer?.unobserve(input); records.delete(input); queued.delete(input);
                if (record.get && Object.getOwnPropertyDescriptor(input, 'value')?.get === record.get) delete input.value;
                if (record.maxHeight) input.style.setProperty('max-height', record.maxHeight, record.maxPriority);
                else input.style.removeProperty('max-height');
            }
        }).observe(doc.documentElement, {childList:true, subtree:true, attributes:true,
            attributeFilter:['open','hidden','aria-hidden','style','class','readonly','data-ui-language','data-appearance-theme']});
        doc.fonts?.ready?.then(refreshAll);
        doc.fonts?.addEventListener?.('loadingdone', refreshAll);
    };
    if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', start, {once:true});
    else start();
})();
