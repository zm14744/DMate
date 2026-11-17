/* Sentence formatting belongs to dialog chrome, never the user's content. */
(function (root) {
    'use strict';
    const selectors = '#accountModal .account-panel-title,#accountModal .account-delete-title,'
        + '#accountModal .account-panel-copy,#accountModal .account-delete-copy,'
        + '#accountModal .account-hint,#accountModal .account-message,#accountModal .account-sync-state,'
        + '#appConfirmTitle,#appConfirmBody,.dmate-delete-confirm-title,.dmate-delete-confirm-body,'
        + '.dcn-confirm-head h3,.dcn-confirm-body,.appearance-apply-hint,.download-description,.wrong-picker-intro';

    function formatInstruction(value) {
        let text = String(value ?? '');
        text = text.replace(/。(?=\s*(?:\n|$))/g, '').replace(/。/g, '；');
        // Decimal points, versions, filenames, links, email and ellipses are
        // data punctuation. Only a standalone sentence period is removed.
        return text.replace(/(^|[^.])\.(?!\.)(?=\s|$)/g, (match, previous, offset, source) => {
            const point = offset + previous.length;
            const before = source.slice(0, point);
            const token = before.match(/\S+$/)?.[0] || '';
            if (/(?:https?:\/\/|www\.)\S*$|\S+@\S*$/i.test(before)
                || /^(?:e\.g|i\.e|vs|dr|mr|mrs|ms|etc)$/i.test(token)) return match;
            return previous + (/\S/.test(source.slice(point + 1)) ? ';' : '');
        });
    }

    // Register only the instruction currently being formatted. The language
    // observer can then round-trip its displayed punctuation without treating
    // a shortened English sentence as newly supplied user content.
    const aliases = new Map();
    const registered = new Set();
    for (const [source, translated] of Object.entries(root.DMateLanguageCatalog?.exact || {})) {
        const entry = [formatInstruction(source), formatInstruction(translated)];
        aliases.set(source, entry);
        aliases.set(translated, entry);
    }
    function instruction(value) {
        const text = String(value ?? '');
        const entry = aliases.get(text);
        if (entry && !registered.has(entry[0]) && root.DMateI18n?.register) {
            root.DMateI18n.register({ [entry[0]]:entry[1] });
            registered.add(entry[0]);
        }
        return formatInstruction(text);
    }

    function refresh(scope = document) {
        if (!scope?.querySelectorAll) return;
        const elements = [...(scope.matches?.(selectors) ? [scope] : []), ...scope.querySelectorAll(selectors)];
        for (const element of elements) {
            if (element.closest('[data-i18n-content],[translate="no"],textarea,input,[contenteditable="true"]')) continue;
            for (const node of element.childNodes) {
                if (node.nodeType !== 3) continue;
                const next = instruction(node.nodeValue);
                if (next !== node.nodeValue) node.nodeValue = next;
            }
        }
    }

    root.DMateModalText = Object.freeze({ instruction, refresh });
    const afterLanguage = () => root.setTimeout(() => refresh(), 0);
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', afterLanguage, { once:true });
    else afterLanguage();
    root.addEventListener('dmate:languagechange', afterLanguage);
})(typeof window === 'undefined' ? globalThis : window);
