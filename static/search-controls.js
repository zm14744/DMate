/* Shared search chrome. Existing components retain their own clear handlers. */
(() => {
    'use strict';
    const root = window, doc = document;
    if (root.DMateSearchControls) return;
    const records = new WeakMap();
    let nextId = 0;
    const text = (source, english) => root.DMateI18n?.t?.(source, english)
        ?? ((root.DMateI18n?.getLanguage?.() || doc.documentElement.dataset.uiLanguage) === 'en' ? english : source);
    const attribute = (node, name, value) => {
        if (node.getAttribute(name) !== value) node.setAttribute(name, value);
    };
    const searchIcon = () => {
        const icon = doc.createElementNS('http://www.w3.org/2000/svg', 'svg');
        icon.setAttribute('class', 'dmate-search-icon');
        icon.setAttribute('viewBox', '0 0 24 24');
        icon.setAttribute('aria-hidden', 'true');
        icon.setAttribute('focusable', 'false');
        icon.innerHTML = '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>';
        return icon;
    };
    const update = (input, record) => {
        const label = text('搜索', 'Search'), clear = text('清空搜索', 'Clear search');
        input.removeAttribute('placeholder');
        attribute(input, 'aria-label', label);
        attribute(record.button, 'aria-label', clear);
        attribute(record.button, 'title', clear);
        // wrong-book and notebook renderers already own visibility, focus,
        // and filtering. Do not attach a second business handler to those.
        if (!record.managed) return;
        const hidden = !input.value || input.type !== 'search';
        if (record.button.hidden !== hidden) record.button.hidden = hidden;
        const disabled = input.disabled || input.readOnly;
        if (record.button.disabled !== disabled) record.button.disabled = disabled;
    };
    const enhance = input => {
        if (!(input instanceof HTMLInputElement) || input.type !== 'search' || !input.parentElement) return;
        const existing = records.get(input);
        if (existing) { update(input, existing); return; }
        if (!input.id || doc.getElementById(input.id) !== input) {
            let id;
            do { id = 'dmate-search-input-' + (++nextId); } while (doc.getElementById(id));
            input.id = id;
        }
        let wrapper = input.closest('.dmate-search-wrap,.wrong-search-wrap,.dcn-search-wrap');
        if (!wrapper) {
            wrapper = doc.createElement('div');
            input.before(wrapper);
            wrapper.append(input);
        }
        wrapper.classList.add('dmate-search-wrap');
        wrapper.prepend(searchIcon());
        input.classList.add('dmate-search-input');
        let button = wrapper.querySelector('.wrong-search-clear,.dcn-search-clear,.dmate-search-clear');
        const managed = !button || button.dataset.dmateSearchManaged === 'true';
        if (!button) {
            button = doc.createElement('button');
            button.type = 'button';
            button.className = 'dmate-search-clear wrong-search-clear';
            button.dataset.dmateSearchManaged = 'true';
            wrapper.append(button);
        }
        button.classList.add('dmate-search-clear');
        attribute(button, 'data-search-clear-for', input.id);
        const record = {wrapper, button, managed};
        records.set(input, record);
        update(input, record);
    };
    const refresh = (scope = doc) => {
        if (!scope) return;
        if (scope.matches?.('input[type="search"]')) enhance(scope);
        scope.querySelectorAll?.('input[type="search"]').forEach(enhance);
    };
    root.DMateSearchControls = Object.freeze({refresh});

    doc.addEventListener('input', event => {
        if (event.target.matches?.('input[type="search"]')) enhance(event.target);
    });
    doc.addEventListener('click', event => {
        const button = event.target.closest?.('button[data-search-clear-for]');
        if (!button) return;
        const input = doc.getElementById(button.dataset.searchClearFor);
        const record = input && records.get(input);
        if (!record?.managed || record.button !== button || input.type !== 'search' || input.disabled || input.readOnly) return;
        event.preventDefault();
        if (input.value) {
            input.value = '';
            input.dispatchEvent(new Event('input', {bubbles:true}));
        }
        update(input, record);
        if (input.isConnected) input.focus({preventScroll:true});
    });
    root.addEventListener('dmate:languagechange', () => refresh());
    const start = () => {
        refresh();
        new MutationObserver(changes => {
            for (const change of changes) {
                if (change.type === 'attributes') {
                    const record = records.get(change.target);
                    if (change.target.matches?.('input[type="search"]')) enhance(change.target);
                    else if (record) update(change.target, record);
                } else for (const node of change.addedNodes) refresh(node);
            }
        }).observe(doc.body, {childList:true, subtree:true, attributes:true, attributeFilter:['type','disabled','readonly']});
    };
    if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', start, {once:true});
    else start();
})();
