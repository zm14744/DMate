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

        const sheet = document.createElement('dialog');
        sheet.className = 'dcn-mobile-sheet';
        const header = document.createElement('header');
        header.className = 'dcn-sheet-head';
        const handle = document.createElement('div');
        handle.className = 'dcn-sheet-handle';
        handle.setAttribute('aria-hidden', 'true');
        const grip = document.createElement('span');
        grip.className = 'dcn-sheet-grip';
        handle.append(grip);
        const dismiss = document.createElement('button');
        dismiss.type = 'button';
        dismiss.className = 'dcn-close dcn-sheet-close';
        header.append(handle, dismiss);
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
            const visibleHeight = viewport?.height || window.innerHeight;
            const offset = Math.max(0, window.innerHeight - visibleHeight - (viewport?.offsetTop || 0));
            sheet.style.setProperty('--dcn-sheet-visible-height', visibleHeight + 'px');
            sheet.style.setProperty('--dcn-sheet-keyboard-offset', offset + 'px');
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
            viewport?.removeEventListener('resize', fitViewport);
            viewport?.removeEventListener('scroll', fitViewport);
            window.removeEventListener('resize', fitViewport);
            previous.onClose?.();
            if (restoreFocus) focus(previous.returnFocus);
            return true;
        }

        function open(content, { label, returnFocus = document.activeElement, initialFocus, onClose } = {}) {
            if (!mobile.matches || !owner.isConnected || !owner.contains(content)) return false;
            if (current?.content === content) return true;
            close();
            const placeholder = document.createComment('notebook sheet content');
            content.before(placeholder);
            body.append(content);
            body.scrollTop = 0;
            current = { content, placeholder, returnFocus, onClose };
            sheet.setAttribute('aria-label', label);
            dismiss.setAttribute('aria-label', root.DMateI18n?.t?.('关闭', 'Close') || '关闭');
            fitViewport();
            sheet.showModal();
            viewport?.addEventListener('resize', fitViewport);
            viewport?.addEventListener('scroll', fitViewport);
            window.addEventListener('resize', fitViewport);
            focus(initialFocus || dismiss);
            return true;
        }

        const dismissSheet = () => close({ restoreFocus:true });
        dismiss.addEventListener('click', dismissSheet);
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
            drag = { id:event.pointerId, start:event.clientY };
            handle.setPointerCapture(event.pointerId);
        });
        handle.addEventListener('pointermove', event => {
            if (drag?.id !== event.pointerId) return;
            sheet.dataset.dcnSheetDragging = '';
            sheet.style.setProperty('--dcn-sheet-drag-offset', Math.max(0, event.clientY - drag.start) + 'px');
        });
        handle.addEventListener('pointerup', event => {
            if (drag?.id !== event.pointerId) return;
            if (event.clientY - drag.start > 48) dismissSheet();
            else endDrag();
        });
        for (const type of ['pointercancel', 'lostpointercapture']) {
            handle.addEventListener(type, event => { if (drag?.id === event.pointerId) endDrag(); });
        }
        const onBreakpoint = () => { if (!mobile.matches) close(); };
        mobile.addEventListener('change', onBreakpoint);

        const controller = {
            isMobile:() => mobile.matches,
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
