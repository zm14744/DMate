/* Desktop navigation reuses the existing conversation and learning panels. */
(function (root) {
    'use strict';

    const document = root.document;

    function bind() {
        const html = document.documentElement;
        const sidebar = document.getElementById('conversationSidebar');
        const toolsPanel = document.getElementById('learningToolsPanel');
        const sidebarClose = document.getElementById('desktopSidebarToggle');
        const sidebarOpen = document.getElementById('desktopSidebarOpen');
        const toolsButton = document.getElementById('desktopToolsBtn');
        const media = root.matchMedia?.('(min-width:1101px)');
        if (!sidebar || !toolsPanel || !sidebarClose || !sidebarOpen || !toolsButton || !media) return;

        let desktop = media.matches;
        // Every visit starts with the same compact layout for guests and accounts.
        let sidebarCollapsed = true;
        let toolsOpen = false;
        let cancelScrollAnchor = () => {};

        function label(button, source) {
            const value = root.DMateI18n?.t(source) || source;
            button.setAttribute('aria-label', value);
            button.setAttribute('title', value);
        }

        function focus(button) {
            button.focus({preventScroll: true});
        }

        function setPanelHidden(panel, hidden) {
            // A tool's existing handler may already have focused its dialog.
            // Only release focus when it still belongs to the closing panel.
            if (hidden && panel.contains(document.activeElement)) document.activeElement.blur();
            panel.toggleAttribute('inert', desktop && hidden);
            if (desktop) panel.setAttribute('aria-hidden', String(hidden));
            else panel.removeAttribute('aria-hidden');
        }

        function refreshLabels() {
            sidebarClose.setAttribute('aria-expanded', String(!sidebarCollapsed));
            sidebarOpen.setAttribute('aria-expanded', String(!sidebarCollapsed));
            toolsButton.setAttribute('aria-expanded', String(desktop && toolsOpen));
            label(sidebarClose, '收起对话列表');
            label(sidebarOpen, '展开对话列表');
            label(toolsButton, desktop && toolsOpen ? '关闭学习工具' : '打开学习工具');
        }

        function renderSidebar(moveFocus = false) {
            html.dataset.desktopSidebar = sidebarCollapsed ? 'collapsed' : 'expanded';
            if (desktop && sidebarCollapsed && moveFocus) focus(sidebarOpen);
            setPanelHidden(sidebar, desktop && sidebarCollapsed);
            if (desktop && !sidebarCollapsed && moveFocus) focus(sidebarClose);
            refreshLabels();
        }

        function preserveChatPosition() {
            cancelScrollAnchor();
            const chat = document.getElementById('chat');
            if (!chat || !root.ResizeObserver) return;
            let width = chat.getBoundingClientRect().width;
            const viewport = chat.getBoundingClientRect();
            const atBottom = chat.scrollHeight - chat.clientHeight - chat.scrollTop <= 24;
            const anchor = atBottom ? null : Array.from(chat.querySelectorAll('.msg')).find(message => {
                const rect = message.getBoundingClientRect();
                return rect.bottom > viewport.top && rect.top < viewport.bottom;
            });
            if (!atBottom && !anchor) return;
            const offset = anchor ? anchor.getBoundingClientRect().top - viewport.top : 0;
            const cancel = () => {
                observer.disconnect();
                root.clearTimeout(timer);
                chat.removeEventListener('wheel', cancel);
                chat.removeEventListener('touchstart', cancel);
                document.removeEventListener('keydown', onScrollKey, true);
                if (cancelScrollAnchor === cancel) cancelScrollAnchor = () => {};
            };
            const onScrollKey = event => {
                if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' '].includes(event.key)
                    && !event.target.closest?.('input, textarea, select, [contenteditable]')) cancel();
            };
            const observer = new root.ResizeObserver(() => {
                const nextWidth = chat.getBoundingClientRect().width;
                if (Math.abs(nextWidth - width) < 0.1) return;
                width = nextWidth;
                if (atBottom) chat.scrollTop = chat.scrollHeight - chat.clientHeight;
                else if (chat.contains(anchor)) {
                    const delta = anchor.getBoundingClientRect().top - chat.getBoundingClientRect().top - offset;
                    if (Math.abs(delta) > 0.5) chat.scrollTop += delta;
                } else cancel();
            });
            const timer = root.setTimeout(cancel, 320);
            cancelScrollAnchor = cancel;
            chat.addEventListener('wheel', cancel, {passive: true});
            chat.addEventListener('touchstart', cancel, {passive: true});
            document.addEventListener('keydown', onScrollKey, true);
            observer.observe(chat);
        }

        function setSidebarCollapsed(collapsed) {
            if (!desktop || sidebarCollapsed === collapsed) return;
            preserveChatPosition();
            sidebarCollapsed = collapsed;
            renderSidebar(true);
        }

        function setToolsOpen(open, returnFocus = false) {
            toolsOpen = desktop && open;
            document.body.classList.toggle('desktop-tools-open', toolsOpen);
            if (returnFocus) focus(toolsButton);
            setPanelHidden(toolsPanel, desktop && !toolsOpen);
            refreshLabels();
        }

        sidebarClose.addEventListener('click', () => setSidebarCollapsed(true));
        sidebarOpen.addEventListener('click', () => setSidebarCollapsed(false));
        toolsButton.addEventListener('click', () => {
            if (desktop) setToolsOpen(!toolsOpen);
        });

        document.addEventListener('pointerdown', event => {
            if (!desktop || !toolsOpen) return;
            const path = event.composedPath();
            if (path.includes(toolsPanel) || path.includes(toolsButton)) return;
            setToolsOpen(false);
        }, true);

        document.addEventListener('keydown', event => {
            if (!desktop || !toolsOpen || event.key !== 'Escape') return;
            event.preventDefault();
            event.stopPropagation();
            setToolsOpen(false, true);
        }, true);

        // Register after the main script so its action can establish dialog
        // focus before the shared learning panel becomes inert.
        ['wrongBookBtn', 'conceptNotebookBtn', 'knowledgeGraphBtn', 'graphDrawingBtn', 'learningReviewBtn'].forEach(id => {
            document.getElementById(id)?.addEventListener('click', () => {
                if (desktop && toolsOpen) setToolsOpen(false);
            });
        });

        const onBreakpointChange = event => {
            cancelScrollAnchor();
            desktop = event.matches;
            renderSidebar();
            setToolsOpen(false);
        };
        if (media.addEventListener) media.addEventListener('change', onBreakpointChange);
        else media.addListener(onBreakpointChange);
        root.addEventListener('dmate:languagechange', refreshLabels);

        renderSidebar();
        setToolsOpen(false);
    }

    if (document.readyState === 'complete') bind();
    else document.addEventListener('DOMContentLoaded', bind, {once: true});
})(window);
