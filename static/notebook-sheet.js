/* The notebook's mobile editor and analysis use the same native bottom sheet. */
(function (root) {
    'use strict';
    const mounted = new WeakMap();

    function mount(owner) {
        if (mounted.has(owner)) return mounted.get(owner);
        const document = owner.ownerDocument;
        const window = document.defaultView || root;
        const mobile = window.matchMedia('(max-width:760px)');
        const viewport = window.visualViewport;
        let current = null;
        let drag = null;
        let draggedHandle = false;

        const sheet = document.createElement('dialog');
        sheet.className = 'dcn-mobile-sheet';
        const header = document.createElement('header');
        header.className = 'dcn-sheet-head';
        const handle = document.createElement('button');
        handle.type = 'button';
        handle.className = 'dcn-sheet-handle';
        const grip = document.createElement('span');
        grip.className = 'dcn-sheet-grip';
        grip.setAttribute('aria-hidden', 'true');
        handle.append(grip);
        header.append(handle);
        const body = document.createElement('div');
        body.className = 'dcn-sheet-body';
        sheet.append(header, body);
        owner.append(sheet);
        owner.setAttribute('data-dcn-mobile-ready', '');

        function focus(target) {
            const node = typeof target === 'function' ? target() : target;
            if (node?.isConnected && !node.disabled) node.focus({ preventScroll:true });
        }

        function fitViewport() {
            const top = viewport?.offsetTop || 0;
            const bottom = Math.min(owner.getBoundingClientRect().bottom, top + (viewport?.height || window.innerHeight));
            sheet.style.setProperty('--dcn-sheet-visible-height', Math.max(0, bottom - top) + 'px');
            sheet.style.setProperty('--dcn-sheet-bottom-offset', Math.max(0, window.innerHeight - bottom) + 'px');
        }

        function endDrag() {
            if (!drag) return;
            const { id } = drag;
            drag = null;
            delete sheet.dataset.dcnSheetDragging;
            sheet.style.removeProperty('--dcn-sheet-drag-offset');
            if (handle.hasPointerCapture(id)) handle.releasePointerCapture(id);
        }

        function close({ restoreFocus = false } = {}) {
            if (!current) return false;
            const previous = current;
            current = null;
            endDrag();
            if (sheet.open) sheet.close();
            previous.placeholder.replaceWith(previous.content);
            body.replaceChildren();
            delete sheet.dataset.dcnSheetState;
            viewport?.removeEventListener('resize', fitViewport);
            viewport?.removeEventListener('scroll', fitViewport);
            window.removeEventListener('resize', fitViewport);
            previous.onClose?.();
            if (restoreFocus) focus(previous.returnFocus);
            return true;
        }

        const isPeeked = () => sheet.dataset.dcnSheetState === 'peek';

        function setPeek(peek, initialFocus) {
            if (!current) return false;
            endDrag();
            const wasOpen = sheet.open;
            sheet.dataset.dcnSheetState = peek ? 'peek' : 'expanded';
            body.hidden = peek;
            handle.setAttribute('aria-expanded', String(!peek));
            const source = peek ? '展开面板' : '收起面板';
            const english = peek ? 'Expand panel' : 'Collapse panel';
            handle.setAttribute('aria-label', root.DMateI18n?.t?.(source, english) || source);
            fitViewport();
            // Keep the editor as a non-modal floating layer. The notebook list
            // remains interactive underneath so another entry opens in one tap.
            if (!wasOpen) sheet.show();
            if (initialFocus) focus(initialFocus);
            else focus(handle);
            return true;
        }

        function open(content, { label, returnFocus = document.activeElement, initialFocus, onClose, peek = false } = {}) {
            if (!mobile.matches || !owner.isConnected || !owner.contains(content)) return false;
            if (current?.content === content) {
                current.returnFocus = returnFocus;
                current.onClose = onClose;
            } else {
                close();
                const placeholder = document.createComment('notebook sheet content');
                content.before(placeholder);
                body.append(content);
                body.scrollTop = 0;
                current = { content, placeholder, returnFocus, onClose };
                viewport?.addEventListener('resize', fitViewport);
                viewport?.addEventListener('scroll', fitViewport);
                window.addEventListener('resize', fitViewport);
            }
            sheet.setAttribute('aria-label', label);
            return setPeek(peek, initialFocus);
        }

        const dismissSheet = () => {
            if (!current) return false;
            return isPeeked() ? close({ restoreFocus:true }) : setPeek(true);
        };
        handle.addEventListener('click', event => {
            if (!draggedHandle || event.detail === 0) setPeek(!isPeeked());
        });
        handle.addEventListener('keydown', event => {
            if (event.key !== 'Escape' || !isPeeked()) return;
            event.preventDefault();
            event.stopPropagation();
            dismissSheet();
        });
        sheet.addEventListener('cancel', event => {
            event.preventDefault();
            event.stopPropagation();
            dismissSheet();
        });
        sheet.addEventListener('close', () => {
            if (!sheet.open) dismissSheet();
        });
        sheet.addEventListener('click', event => {
            if (event.target !== sheet) return;
            const box = sheet.getBoundingClientRect();
            if (event.clientX < box.left || event.clientX > box.right
                || event.clientY < box.top || event.clientY > box.bottom) dismissSheet();
        });
        handle.addEventListener('pointerdown', event => {
            if (drag || event.button !== 0) return;
            draggedHandle = false;
            drag = { id:event.pointerId, start:event.clientY };
            handle.setPointerCapture(event.pointerId);
        });
        handle.addEventListener('pointermove', event => {
            if (drag?.id !== event.pointerId) return;
            const delta = event.clientY - drag.start;
            if (Math.abs(delta) < 6 && !draggedHandle) return;
            draggedHandle = true;
            sheet.dataset.dcnSheetDragging = '';
            const offset = isPeeked() ? Math.min(0, delta) : Math.max(0, delta);
            sheet.style.setProperty('--dcn-sheet-drag-offset', offset + 'px');
        });
        handle.addEventListener('pointerup', event => {
            if (drag?.id !== event.pointerId) return;
            const delta = event.clientY - drag.start;
            if (isPeeked() ? delta < -32 : delta > 48) setPeek(!isPeeked());
            else endDrag();
        });
        for (const type of ['pointercancel', 'lostpointercapture']) {
            handle.addEventListener(type, event => { if (drag?.id === event.pointerId) endDrag(); });
        }
        const onBreakpoint = () => { if (!mobile.matches) close(); };
        mobile.addEventListener('change', onBreakpoint);

        const controller = {
            isMobile:() => mobile.matches,
            isPeeked,
            expand:() => isPeeked() && setPeek(false),
            collapse:() => !isPeeked() && setPeek(true),
            open, close,
            contains:content => current?.content === content,
            destroy() {
                close();
                mobile.removeEventListener('change', onBreakpoint);
                sheet.remove();
                owner.removeAttribute('data-dcn-mobile-ready');
                mounted.delete(owner);
            }
        };
        mounted.set(owner, controller);
        return controller;
    }

    root.DMateNotebookSheet = Object.freeze({ mount });
})(typeof window === 'undefined' ? globalThis : window);
