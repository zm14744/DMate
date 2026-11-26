/* Keep the native scroll position, with draggable thumbs that have no clickable track. */
(function (root) {
    'use strict';

    function mount(viewport, surface) {
        const frame = viewport.parentElement;
        const document = viewport.ownerDocument;
        const window = document.defaultView || root;
        const events = new window.AbortController();
        let drag = null;
        let suppressClick = false;
        let pendingPaint = 0;

        const axes = [
            {name:'x', client:'clientWidth', content:'scrollWidth', scroll:'scrollLeft', pointer:'clientX', size:'width', start:'left'},
            {name:'y', client:'clientHeight', content:'scrollHeight', scroll:'scrollTop', pointer:'clientY', size:'height', start:'top'}
        ];

        function measure(axis, perpendicular) {
            const client = viewport[axis.client];
            const content = viewport[axis.content];
            const range = Math.max(0, content - client);
            const thickness = parseFloat(window.getComputedStyle(frame).getPropertyValue('--kg-desktop-thumb-size')) || 6;
            const track = Math.max(0, client - (viewport[perpendicular.content] > viewport[perpendicular.client] ? thickness : 0));
            const length = Math.min(track, Math.max(24, track * client / Math.max(1, content)));
            return {range, length, travel:track - length};
        }

        function paint() {
            pendingPaint = 0;
            for (const [index, axis] of axes.entries()) {
                const {range, length, travel} = measure(axis, axes[1 - index]);
                axis.thumb.hidden = viewport.dataset.kgReady !== 'true' || range === 0 || travel <= 0;
                if (axis.thumb.hidden) continue;
                const progress = Math.min(1, Math.max(0, viewport[axis.scroll] / range));
                axis.thumb.style[axis.size] = length + 'px';
                axis.thumb.style[axis.start] = (travel * progress) + 'px';
            }
        }

        function queuePaint() {
            if (!pendingPaint) pendingPaint = window.requestAnimationFrame(paint);
        }

        function endDrag(event) {
            if (!drag || (event?.pointerId != null && event.pointerId !== drag.id)) return;
            const previous = drag;
            drag = null;
            previous.target.removeAttribute('data-kg-dragging');
            if (previous.target.hasPointerCapture(previous.id)) previous.target.releasePointerCapture(previous.id);
            if (!previous.axis && previous.moved) suppressClick = true;
        }

        function startThumb(event, axis, perpendicular) {
            if (drag || event.button !== 0) return;
            viewport._kgBeginViewInteraction?.();
            const {range, travel} = measure(axis, perpendicular);
            if (range <= 0 || travel <= 0) return;
            const zoom = viewport.getBoundingClientRect()[axis.size] / viewport[axis.client];
            drag = {id:event.pointerId, target:axis.thumb, axis, origin:event[axis.pointer],
                scroll:viewport[axis.scroll], factor:range / (travel * (zoom || 1))};
            axis.thumb.setAttribute('data-kg-dragging', '');
            axis.thumb.setPointerCapture(event.pointerId);
            event.preventDefault();
        }

        function startPan(event) {
            suppressClick = false;
            if (drag || event.button !== 0 || event.pointerType !== 'mouse'
                || axes.every(axis => viewport[axis.content] <= viewport[axis.client])) return;
            drag = {id:event.pointerId, target:viewport, x:event.clientX, y:event.clientY,
                left:viewport.scrollLeft, top:viewport.scrollTop, moved:false};
        }

        function moveDrag(event) {
            if (!drag || event.pointerId !== drag.id) return;
            if (drag.axis) {
                const axis = drag.axis;
                viewport[axis.scroll] = drag.scroll + (event[axis.pointer] - drag.origin) * drag.factor;
            } else {
                const dx = event.clientX - drag.x;
                const dy = event.clientY - drag.y;
                if (!drag.moved) {
                    if (Math.hypot(dx, dy) < 5) return;
                    drag.moved = true;
                    viewport.setAttribute('data-kg-dragging', '');
                    viewport.setPointerCapture(event.pointerId);
                }
                const rect = viewport.getBoundingClientRect();
                viewport.scrollLeft = drag.left - dx * viewport.clientWidth / (rect.width || 1);
                viewport.scrollTop = drag.top - dy * viewport.clientHeight / (rect.height || 1);
            }
            event.preventDefault();
        }

        function scrollFromThumb(event) {
            if (event.ctrlKey) return;
            viewport._kgBeginViewInteraction?.();
            const delta = event.shiftKey && !event.deltaX ? [event.deltaY, 0] : [event.deltaX, event.deltaY];
            for (const [index, axis] of axes.entries()) {
                const multiplier = event.deltaMode === 2 ? viewport[axis.client] : event.deltaMode === 1 ? 16 : 1;
                viewport[axis.scroll] += delta[index] * multiplier;
            }
            event.preventDefault();
        }

        for (const [index, axis] of axes.entries()) {
            const thumb = document.createElement('div');
            thumb.className = 'kg-desktop-scroll-thumb';
            thumb.dataset.axis = axis.name;
            thumb.hidden = true;
            thumb.setAttribute('aria-hidden', 'true');
            axis.thumb = thumb;
            frame.append(thumb);
            thumb.addEventListener('pointerdown', event => startThumb(event, axis, axes[1 - index]), {signal:events.signal});
            thumb.addEventListener('wheel', scrollFromThumb, {signal:events.signal, passive:false});
        }

        const observer = new window.ResizeObserver(queuePaint);
        observer.observe(viewport);
        observer.observe(surface);
        viewport.addEventListener('scroll', queuePaint, {signal:events.signal, passive:true});
        viewport.addEventListener('pointerdown', startPan, {signal:events.signal});
        viewport.addEventListener('click', event => {
            if (!suppressClick || !event.detail) return;
            suppressClick = false;
            event.stopImmediatePropagation();
            event.preventDefault();
        }, {capture:true, signal:events.signal});
        window.addEventListener('pointermove', moveDrag, {signal:events.signal, passive:false});
        for (const type of ['pointerup', 'pointercancel', 'lostpointercapture', 'blur']) {
            window.addEventListener(type, endDrag, {signal:events.signal});
        }
        queuePaint();

        return () => {
            endDrag();
            events.abort();
            observer.disconnect();
            window.cancelAnimationFrame(pendingPaint);
            for (const axis of axes) axis.thumb.remove();
        };
    }

    root.DMateKnowledgeGraphDesktop = Object.freeze({mount});
})(typeof window === 'undefined' ? globalThis : window);
