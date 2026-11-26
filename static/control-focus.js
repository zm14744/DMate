/* Editable text fields can match :focus-visible after a pointer click. */
(() => {
    'use strict';
    const page = document.documentElement;
    const chooser = 'select,[role="combobox"],[aria-controls="mobileChoiceModal"],.mobile-select-trigger,.mobile-choice-option';
    const chooserKeys = new Set(['Enter',' ','ArrowDown','ArrowUp','ArrowLeft','ArrowRight','Home','End','PageUp','PageDown']);
    window.addEventListener('pointerdown', () => {
        page.dataset.dmateFocusInput = 'pointer';
    }, {capture:true, passive:true});
    window.addEventListener('keydown', event => {
        if (event.isComposing) return;
        if (event.key === 'Tab' || (chooserKeys.has(event.key) && event.target?.closest?.(chooser))) {
            delete page.dataset.dmateFocusInput;
        }
    }, true);
})();
