/* On mobile the graph's detail panel also acts as a bottom sheet. */
(function (root) {
    'use strict';
    const mounted = new WeakMap();

    function mount(host) {
        if (!host?.ownerDocument) throw new TypeError('Knowledge graph host is required');
        if (mounted.has(host)) return mounted.get(host);
        const document = host.ownerDocument, window = document.defaultView || root;
        const mobile = window.matchMedia('(max-width:760px)');
        let wrap = null, title = null, detail = null, drag = null, destroyed = false, observed = false;
        const handle = document.createElement('div');
        handle.className = 'kg-sheet-handle'; handle.hidden = true;
        handle.setAttribute('aria-hidden', 'true');
        const grip = document.createElement('span');
        grip.className = 'kg-sheet-grip'; handle.append(grip);
        const now = () => window.performance?.now?.() ?? Date.now();
        const state = () => host.dataset.kgSheet;
        const hidden = node => !node || Boolean(node.closest('[hidden],.hidden,[aria-hidden="true"]'));
        function eligible() {
            return !destroyed && host.isConnected && mobile.matches
                && host.classList.contains('graph-fullscreen-view') && !hidden(host)
                && wrap?.isConnected && !hidden(wrap) && !hidden(title) && detail?.isConnected
                && Boolean(host.querySelector('#knowledgeGraphCanvas .kg-mobile-node.selected, #knowledgeGraphCanvas .kg-node-group.selected'))
                && Boolean(title.textContent.trim())
                && window.getComputedStyle(host).display !== 'none'
                && window.getComputedStyle(host).visibility !== 'hidden';
        }
        function paint() {
            handle.hidden = !['peek', 'expanded'].includes(state());
        }
        function resetDrag() {
            const previous = drag; drag = null;
            delete host.dataset.kgSheetDragging;
            host.style.removeProperty('--kg-sheet-drag-height');
            if (previous) {
                try { previous.target.releasePointerCapture(previous.id); } catch (_) {}
            }
            return previous;
        }
        function close() {
            if (destroyed) return false;
            const handled = Boolean(state() || drag);
            resetDrag(); delete host.dataset.kgSheet; paint();
            return handled;
        }
        function setState(value) {
            if (value) host.dataset.kgSheet = value;
            else delete host.dataset.kgSheet;
            paint();
        }
        function pointerDown(event) {
            if (drag || event.button !== 0 || !state() || !eligible()) return;
            if (event.currentTarget === title
                && event.target.closest?.('a,button,input,select,textarea,[contenteditable="true"]')) return;
            const peekHeight = parseFloat(window.getComputedStyle(host).getPropertyValue('--kg-sheet-peek-height')) || 0;
            drag = { id:event.pointerId, target:event.currentTarget, state:state(),
                x:event.clientX, y:event.clientY, lastY:event.clientY, started:now(),
                height:(host.querySelector('.knowledge-graph-side') || wrap).getBoundingClientRect().height,
                peekHeight, moved:false };
            try { drag.target.setPointerCapture(event.pointerId); } catch (_) {}
        }
        function pointerMove(event) {
            if (!drag || event.pointerId !== drag.id) return;
            const delta = event.clientY - drag.y;
            drag.lastY = event.clientY;
            if (!drag.moved && (Math.abs(delta) < 6 || Math.abs(delta) <= Math.abs(event.clientX - drag.x))) return;
            drag.moved = true;
            const viewport = window.visualViewport?.height || window.innerHeight;
            const maximum = Math.min(host.getBoundingClientRect().height || viewport, viewport);
            const height = Math.max(drag.peekHeight, Math.min(maximum, drag.height - delta));
            host.dataset.kgSheetDragging = delta < 0 ? 'up' : 'down';
            host.style.setProperty('--kg-sheet-drag-height', Math.round(height) + 'px');
            if (event.cancelable) event.preventDefault();
        }
        function pointerEnd(event) {
            if (!drag || event.pointerId !== drag.id) return;
            const previous = resetDrag();
            if (!previous.moved) return;
            const delta = previous.lastY - previous.y;
            const swipe = Math.abs(delta) >= 32
                || Math.abs(delta) >= 16 && Math.abs(delta) / Math.max(1, now() - previous.started) >= .35;
            if (!eligible()) { close(); return; }
            if (!swipe) { setState(previous.state); return; }
            setState(delta < 0 ? 'expanded' : 'peek');
        }
        function pointerCancel(event) {
            if (!drag || event.pointerId !== drag.id) return;
            resetDrag();
        }
        function keydown(event) {
            if (event.key === 'Escape' && state() === 'expanded') {
                resetDrag();
                setState('peek');
                event.preventDefault(); event.stopPropagation();
            }
        }
        function listen(node, add) {
            if (!node) return;
            const method = add ? 'addEventListener' : 'removeEventListener';
            for (const [type, handler] of [['pointerdown', pointerDown], ['pointermove', pointerMove],
                ['pointerup', pointerEnd], ['pointercancel', pointerCancel],
                ['lostpointercapture', pointerCancel]]) node[method](type, handler);
        }
        const observer = typeof window.MutationObserver === 'function' ? new window.MutationObserver(sync) : null;
        function parts() {
            const nextWrap = host.querySelector('#knowledgeGraphDetailWrap');
            const nextTitle = nextWrap?.querySelector('#knowledgeGraphDetailTitle');
            const nextDetail = nextWrap?.querySelector('#knowledgeGraphDetail');
            if (observed && nextWrap === wrap && nextTitle === title && nextDetail === detail) return;
            resetDrag(); listen(title, false);
            wrap = nextWrap; title = nextTitle; detail = nextDetail;
            if (wrap && title) { title.before(handle); listen(title, true); }
            else handle.remove();
            observer?.disconnect();
            observed = true;
            const attributes = {attributes:true, attributeFilter:['class', 'hidden', 'aria-hidden']};
            observer?.observe(host, attributes);
            if (wrap) observer?.observe(wrap, {...attributes, childList:true});
            if (title) observer?.observe(title, {...attributes, childList:true, characterData:true, subtree:true});
        }
        function sync() {
            if (destroyed) return;
            parts();
            if (!eligible()) close();
            else if (!['peek', 'expanded'].includes(state())) setState('peek');
            else paint();
        }
        function open({keepExpanded = false} = {}) {
            if (destroyed) return false;
            parts();
            if (!eligible()) { close(); return false; }
            const expanded = keepExpanded && state() === 'expanded';
            detail.scrollTop = 0;
            resetDrag(); setState(expanded ? 'expanded' : 'peek');
            return true;
        }
        function resize() { resetDrag(); sync(); }
        function destroy() {
            if (destroyed) return;
            close(); destroyed = true; observer?.disconnect();
            listen(handle, false); listen(title, false); handle.remove();
            host.removeEventListener('keydown', keydown);
            window.removeEventListener('resize', resize);
            window.removeEventListener('dmate:languagechange', sync);
            if (mobile.removeEventListener) mobile.removeEventListener('change', resize);
            else mobile.removeListener?.(resize);
            mounted.delete(host);
        }
        const api = {open, close, sync, destroy};
        mounted.set(host, api); listen(handle, true); host.addEventListener('keydown', keydown);
        window.addEventListener('resize', resize, {passive:true});
        window.addEventListener('dmate:languagechange', sync);
        if (mobile.addEventListener) mobile.addEventListener('change', resize);
        else mobile.addListener?.(resize);
        sync();
        return api;
    }
    root.DMateKnowledgeGraphSheet = Object.freeze({mount});
})(typeof window === 'undefined' ? globalThis : window);
