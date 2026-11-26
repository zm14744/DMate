/* Native controls own scrolling; mouse hover is native, touch/fallback paint is local. */
(() => {
    'use strict';
    if (window.__dmateScrollbarsInstalled) return;
    window.__dmateScrollbarsInstalled = true;

    const attribute = 'data-dmate-scroll-active';
    const touchAttribute = 'data-dmate-scroll-touch';
    const hideDelay = 900;
    const states = new WeakMap();
    const visible = new Set();
    const drags = new Map();
    const fallback = CSS.supports('-moz-appearance:none')
        || !CSS.supports('selector(::-webkit-scrollbar-thumb:vertical)');
    if (fallback) document.documentElement.setAttribute('data-dmate-scroll-fallback', '');
    let refreshThumb = () => {};
    let disposeThumb = () => {};
    let hovered = null;
    let lastPointer = null;
    let touchInput = false;

    const stateFor = (element, snapshot = false) => {
        let state = states.get(element);
        if (!state) {
            state = { timer:0, axis:null, hoverAxis:null, dragAxis:null, inputAxis:null, inputAt:0,
                left:snapshot ? element.scrollLeft : 0, top:snapshot ? element.scrollTop : 0 };
            states.set(element, state);
        }
        return state;
    };
    // Existing panes can already be scrolled when the utility loads. Newly
    // inserted panes start at zero so same-task programmatic scrolls are seen.
    const snapshotTree = (root, snapshot) => {
        if (root instanceof Element) stateFor(root, snapshot);
        root.querySelectorAll?.('*').forEach(element => stateFor(element, snapshot));
    };
    snapshotTree(document, true);
    new MutationObserver(records => {
        for (const record of records) for (const node of record.addedNodes) snapshotTree(node, false);
        if (fallback) for (const element of visible) refreshThumb(element);
    }).observe(document, { childList:true, subtree:true });

    const hide = element => {
        const state = stateFor(element);
        window.clearTimeout(state.timer);
        state.timer = 0;
        state.axis = null;
        state.hoverAxis = null;
        if (hovered?.element === element) hovered = null;
        element.removeAttribute(attribute);
        element.removeAttribute(touchAttribute);
        visible.delete(element);
        disposeThumb(element);
    };
    const paint = (element, axis, touch = false) => {
        const state = stateFor(element);
        state.axis = axis;
        element.toggleAttribute(touchAttribute, touch);
        if (element.getAttribute(attribute) !== axis) element.setAttribute(attribute, axis);
        visible.add(element);
        refreshThumb(element);
    };
    const scheduleHide = element => {
        const state = stateFor(element);
        window.clearTimeout(state.timer);
        state.timer = 0;
        if (state.dragAxis || state.hoverAxis === state.axis) return;
        state.timer = window.setTimeout(() => {
            if (state.hoverAxis) paint(element, state.hoverAxis);
            else hide(element);
        }, hideDelay);
    };
    const inputAxis = (x, y) => Math.abs(x) > Math.abs(y) ? 'x' : y ? 'y' : x ? 'x' : null;
    const useMouseInput = () => {
        touchInput = false;
        for (const element of visible) if (element.hasAttribute(touchAttribute)) hide(element);
    };
    const primeInput = (target, axis = null) => {
        for (let element = target; element instanceof Element; element = element.parentElement) {
            const state = stateFor(element, true);
            state.left = element.scrollLeft;
            state.top = element.scrollTop;
            state.inputAxis = axis;
            state.inputAt = Date.now();
        }
    };
    document.addEventListener('wheel', event => {
        useMouseInput();
        primeInput(event.target, inputAxis(event.deltaX, event.deltaY));
    }, { capture:true, passive:true });
    document.addEventListener('keydown', event => {
        useMouseInput();
        const axis = ['ArrowLeft','ArrowRight'].includes(event.key) ? 'x'
            : ['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' '].includes(event.key) ? 'y' : null;
        if (axis) primeInput(event.target, axis);
    }, { capture:true });
    document.addEventListener('scroll', event => {
        const element = event.target === document ? document.scrollingElement : event.target;
        if (!(element instanceof Element)) return;
        const state = stateFor(element);
        const dx = element.scrollLeft - state.left, dy = element.scrollTop - state.top;
        state.left = element.scrollLeft;
        state.top = element.scrollTop;
        const axis = state.dragAxis || inputAxis(dx, dy)
            || (Date.now() - state.inputAt < 200 ? state.inputAxis : null);
        if (axis && touchInput) {
            paint(element, axis, true);
            scheduleHide(element);
        } else if (fallback && state.dragAxis) {
            paint(element, state.dragAxis);
        } else if (fallback && state.hoverAxis) {
            const hit = lastPointer && scrollbarAxis(element, lastPointer);
            if (hit) { state.hoverAxis = hit; paint(element, hit); }
            else hide(element);
        }
        if (fallback) for (const other of visible) if (other !== element) refreshThumb(other);
    }, { capture:true, passive:true });

    const geometry = element => {
        const root = element === document.scrollingElement;
        if (element.scrollWidth <= element.clientWidth && element.scrollHeight <= element.clientHeight) return null;
        const style = window.getComputedStyle(element);
        if (style.scrollbarWidth === 'none'
            || (CSS.supports('selector(::-webkit-scrollbar)')
                && window.getComputedStyle(element, '::-webkit-scrollbar').display === 'none')) return null;
        const rect = root ? {left:0, top:0, width:window.innerWidth, height:window.innerHeight}
            : element.getBoundingClientRect();
        if (!rect.width || !rect.height) return null;
        const border = name => root ? 0 : parseFloat(style[name]) || 0;
        const width = root ? window.innerWidth : element.offsetWidth;
        const height = root ? window.innerHeight : element.offsetHeight;
        const leftBorder = border('borderLeftWidth'), rightBorder = border('borderRightWidth');
        const topBorder = border('borderTopWidth'), bottomBorder = border('borderBottomWidth');
        const gutterY = width - element.clientWidth - leftBorder - rightBorder;
        const gutterX = height - element.clientHeight - topBorder - bottomBorder;
        const rtl = style.direction === 'rtl';
        return {rect, width, height, leftBorder, rightBorder, topBorder, bottomBorder, gutterX, gutterY, rtl,
            left:root ? rtl ? gutterY : 0 : element.clientLeft, top:root ? 0 : element.clientTop,
            x:element.scrollWidth > element.clientWidth && (root ? !['hidden','clip'].includes(style.overflowX) : ['auto','scroll'].includes(style.overflowX)),
            y:element.scrollHeight > element.clientHeight && (root ? !['hidden','clip'].includes(style.overflowY) : ['auto','scroll'].includes(style.overflowY))};
    };
    const thumbBounds = (element, axis, g = geometry(element)) => {
        if (!g || !g[axis]) return null;
        const sx = g.rect.width / g.width, sy = g.rect.height / g.height;
        const length = axis === 'x' ? element.clientWidth : element.clientHeight;
        const total = axis === 'x' ? element.scrollWidth : element.scrollHeight;
        const size = Math.min(length, Math.max(8, length * length / total));
        const offset = axis === 'x' ? element.scrollLeft : element.scrollTop;
        const progress = Math.max(0, Math.min(1,
            axis === 'x' && g.rtl ? 1 + offset / (total - length) : offset / (total - length)));
        const gutter = (axis === 'x' ? g.gutterX : g.gutterY) || 8;
        const thickness = Math.min(6, gutter);
        let x, y, width, height;
        if (axis === 'y') {
            x = g.rect.left + (g.rtl ? g.leftBorder + (gutter - thickness) / 2
                : g.width - g.rightBorder - gutter + (gutter - thickness) / 2) * sx;
            y = g.rect.top + (g.top + (length - size) * progress) * sy;
            width = thickness * sx; height = size * sy;
        } else {
            x = g.rect.left + (g.left + (length - size) * progress) * sx;
            y = g.rect.top + (g.height - g.bottomBorder - gutter + (gutter - thickness) / 2) * sy;
            width = size * sx; height = thickness * sy;
        }
        let left = Math.max(0, x), top = Math.max(0, y);
        let right = Math.min(window.innerWidth, x + width), bottom = Math.min(window.innerHeight, y + height);
        for (let parent = element.parentElement; parent; parent = parent.parentElement) {
            const css = getComputedStyle(parent), r = parent.getBoundingClientRect();
            const px = parent.offsetWidth ? r.width / parent.offsetWidth : 1;
            const py = parent.offsetHeight ? r.height / parent.offsetHeight : 1;
            if (css.overflowX !== 'visible') {
                left = Math.max(left, r.left + parent.clientLeft * px);
                right = Math.min(right, r.left + (parent.clientLeft + parent.clientWidth) * px);
            }
            if (css.overflowY !== 'visible') {
                top = Math.max(top, r.top + parent.clientTop * py);
                bottom = Math.min(bottom, r.top + (parent.clientTop + parent.clientHeight) * py);
            }
        }
        return right > left && bottom > top ? {left, top, right, bottom} : null;
    };
    const scrollbarAxis = (element, event) => {
        const g = geometry(element);
        if (!g) return null;
        for (const axis of ['x', 'y']) {
            const bounds = thumbBounds(element, axis, g);
            if (bounds && event.clientX >= bounds.left && event.clientX <= bounds.right
                    && event.clientY >= bounds.top && event.clientY <= bounds.bottom) return axis;
        }
        return null;
    };
    if (fallback) {
        const resize = new ResizeObserver(entries => {
            for (const entry of entries) if (visible.has(entry.target)) refreshThumb(entry.target);
        });
        disposeThumb = element => {
            const state = stateFor(element);
            resize.unobserve(element);
            state.watcher?.disconnect();
            state.watcher = null;
            state.thumb?.remove();
        };
        refreshThumb = element => {
            const state = stateFor(element), axis = state.axis;
            if (!axis) return;
            if (!element.isConnected || !element.getClientRects().length) { hide(element); return; }
            for (let parent = element; parent; parent = parent.parentElement) {
                const css = getComputedStyle(parent);
                if (css.visibility === 'hidden' || css.visibility === 'collapse' || css.opacity === '0') {
                    hide(element); return;
                }
            }
            const g = geometry(element);
            if (!g || !g[axis]) { state.thumb?.remove(); return; }
            const bounds = thumbBounds(element, axis, g);
            if (!bounds) { state.thumb?.remove(); return; }
            if (!touchInput && !state.dragAxis && (!lastPointer
                    || lastPointer.clientX < bounds.left || lastPointer.clientX > bounds.right
                    || lastPointer.clientY < bounds.top || lastPointer.clientY > bounds.bottom)) {
                hide(element); return;
            }
            const {left, top, right, bottom} = bounds;
            if (!state.thumb) {
                state.thumb = document.createElement('div');
                state.thumb.setAttribute('aria-hidden', 'true');
            }
            state.thumb.setAttribute('data-dmate-scroll-thumb', axis);
            const owner = element.closest('dialog[open]') || document.body;
            if (state.thumb.parentElement !== owner) owner.append(state.thumb);
            // Measure the fixed containing block, including a transformed
            // top-layer dialog, before mapping viewport coordinates into it.
            Object.assign(state.thumb.style, {left:'0px', top:'0px', width:'1px', height:'1px'});
            const origin = state.thumb.getBoundingClientRect();
            Object.assign(state.thumb.style, {
                left:((left - origin.left) / (origin.width || 1)) + 'px',
                top:((top - origin.top) / (origin.height || 1)) + 'px',
                width:((right - left) / (origin.width || 1)) + 'px',
                height:((bottom - top) / (origin.height || 1)) + 'px'
            });
            if (!state.watcher) {
                state.watcher = new MutationObserver(() => refreshThumb(element));
                for (let parent = element; parent; parent = parent.parentElement) {
                    state.watcher.observe(parent, {attributes:true, attributeFilter:['class','style','hidden','open']});
                }
                resize.observe(element);
            }
        };
        window.addEventListener('resize', () => {
            for (const element of visible) refreshThumb(element);
        }, {passive:true});
    }
    const pointerHit = event => {
        for (let element = event.target; element instanceof Element; element = element.parentElement) {
            const axis = scrollbarAxis(element, event);
            if (axis) return {element, axis};
        }
        return null;
    };
    const moveHover = hit => {
        if (hovered && (!hit || hit.element !== hovered.element || hit.axis !== hovered.axis)) {
            const old = hovered.element;
            stateFor(old).hoverAxis = null;
            if (visible.has(old) && !stateFor(old).dragAxis) hide(old);
        }
        hovered = hit;
        if (hit) {
            const state = stateFor(hit.element);
            state.hoverAxis = hit.axis;
            paint(hit.element, state.dragAxis || hit.axis);
            scheduleHide(hit.element);
        }
    };
    document.addEventListener('pointermove', event => {
        if (event.pointerType !== 'mouse') return;
        useMouseInput();
        if (!fallback) return;
        // Scroll-induced pointer events at the same coordinates must not let
        // a stationary hover override the direction that is actually scrolling.
        if (lastPointer && lastPointer.clientX === event.clientX && lastPointer.clientY === event.clientY) return;
        lastPointer = {clientX:event.clientX, clientY:event.clientY};
        moveHover(pointerHit(event));
    }, { capture:true, passive:true });
    document.addEventListener('pointerdown', event => {
        if (event.pointerType !== 'mouse') {
            moveHover(null);
            lastPointer = null;
            touchInput = true;
            primeInput(event.target);
            return;
        }
        useMouseInput();
        if (event.button !== 0 || !fallback) return;
        lastPointer = {clientX:event.clientX, clientY:event.clientY};
        primeInput(event.target);
        const hit = pointerHit(event);
        if (!hit) return;
        const state = stateFor(hit.element);
        state.dragAxis = hit.axis;
        drags.set(event.pointerId, hit);
        moveHover(hit);
    }, { capture:true, passive:true });
    const finishDrag = event => {
        const hit = drags.get(event.pointerId);
        if (!hit) return;
        drags.delete(event.pointerId);
        stateFor(hit.element).dragAxis = null;
        lastPointer = {clientX:event.clientX, clientY:event.clientY};
        const axis = scrollbarAxis(hit.element, event);
        if (axis) moveHover({element:hit.element, axis});
        else hide(hit.element);
    };
    document.addEventListener('pointerup', finishDrag, { capture:true, passive:true });
    document.addEventListener('pointercancel', finishDrag, { capture:true, passive:true });
    document.addEventListener('pointerout', event => {
        if (!event.relatedTarget) {
            lastPointer = null;
            moveHover(null);
        }
    }, { capture:true, passive:true });
    const reset = () => {
        for (const hit of drags.values()) stateFor(hit.element).dragAxis = null;
        drags.clear();
        if (hovered) stateFor(hovered.element).hoverAxis = null;
        hovered = null;
        lastPointer = null;
        touchInput = false;
        for (const element of visible) hide(element);
    };
    window.addEventListener('pagehide', reset);
    window.addEventListener('blur', reset);
    document.addEventListener('visibilitychange', () => { if (document.hidden) reset(); });
})();
