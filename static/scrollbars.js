/* Native scrolling owns position and dragging; this module only reveals paint. */
(() => {
    'use strict';
    if (window.__dmateScrollbarsInstalled) return;
    window.__dmateScrollbarsInstalled = true;

    const attribute = 'data-dmate-scroll-active';
    const hideDelay = 900;
    const states = new WeakMap();
    const visible = new Set();
    const drags = new Map();

    const stateFor = element => {
        let state = states.get(element);
        if (!state) {
            state = { timer:0, dragging:0 };
            states.set(element, state);
        }
        return state;
    };
    const hide = element => {
        const state = states.get(element);
        if (state) {
            window.clearTimeout(state.timer);
            state.timer = 0;
        }
        element.removeAttribute(attribute);
        visible.delete(element);
    };
    const scheduleHide = element => {
        const state = stateFor(element);
        window.clearTimeout(state.timer);
        state.timer = 0;
        if (!state.dragging) state.timer = window.setTimeout(() => hide(element), hideDelay);
    };
    const reveal = element => {
        if (!visible.has(element)) {
            element.setAttribute(attribute, '');
            visible.add(element);
        }
        scheduleHide(element);
    };

    document.addEventListener('scroll', event => {
        const element = event.target === document
            ? document.scrollingElement : event.target;
        if (element instanceof Element) reveal(element);
    }, { capture:true, passive:true });

    // Retain a revealed thumb while the pointer holds its native scrollbar.
    // Pointer movement over content or a stationary hover never reveals one.
    const isScrollbarPoint = (element, event) => {
        const root = element === document.scrollingElement;
        const rect = root
            ? { left:0, top:0, width:window.innerWidth, height:window.innerHeight }
            : element.getBoundingClientRect();
        if (!rect.width || !rect.height) return false;
        const style = window.getComputedStyle(element);
        const borderLeft = root ? 0 : parseFloat(style.borderLeftWidth) || 0;
        const borderRight = root ? 0 : parseFloat(style.borderRightWidth) || 0;
        const borderTop = root ? 0 : parseFloat(style.borderTopWidth) || 0;
        const borderBottom = root ? 0 : parseFloat(style.borderBottomWidth) || 0;
        const width = root ? window.innerWidth : element.offsetWidth;
        const height = root ? window.innerHeight : element.offsetHeight;
        const x = (event.clientX - rect.left) * width / rect.width;
        const y = (event.clientY - rect.top) * height / rect.height;
        const left = root ? 0 : element.clientLeft;
        const top = root ? 0 : element.clientTop;
        const vertical = width - element.clientWidth - borderLeft - borderRight;
        const horizontal = height - element.clientHeight - borderTop - borderBottom;
        return (vertical > 0 && element.scrollHeight > element.clientHeight
                && y >= borderTop && y <= height - borderBottom
                && ((x >= borderLeft && x < left)
                    || (x >= left + element.clientWidth && x <= width - borderRight)))
            || (horizontal > 0 && element.scrollWidth > element.clientWidth
                && x >= borderLeft && x <= width - borderRight
                && ((y >= borderTop && y < top)
                    || (y >= top + element.clientHeight && y <= height - borderBottom)));
    };
    document.addEventListener('pointerdown', event => {
        if (event.pointerType !== 'mouse' || event.button !== 0) return;
        for (let element = event.target; element instanceof Element; element = element.parentElement) {
            if (!isScrollbarPoint(element, event)) continue;
            const state = stateFor(element);
            state.dragging += 1;
            window.clearTimeout(state.timer);
            state.timer = 0;
            drags.set(event.pointerId, element);
            break;
        }
    }, { capture:true, passive:true });

    const finishDrag = event => {
        const element = drags.get(event.pointerId);
        if (!element) return;
        drags.delete(event.pointerId);
        const state = stateFor(element);
        state.dragging = Math.max(0, state.dragging - 1);
        if (visible.has(element)) scheduleHide(element);
    };
    document.addEventListener('pointerup', finishDrag, { capture:true, passive:true });
    document.addEventListener('pointercancel', finishDrag, { capture:true, passive:true });
    const reset = () => {
        for (const element of drags.values()) stateFor(element).dragging = 0;
        drags.clear();
        for (const element of visible) hide(element);
    };
    window.addEventListener('pagehide', reset);
    window.addEventListener('blur', () => {
        for (const element of drags.values()) {
            stateFor(element).dragging = 0;
            if (visible.has(element)) scheduleHide(element);
        }
        drags.clear();
    });
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) reset();
    });
})();
