(function (root) {
    'use strict';
    const instances = new WeakMap();
    const conversationMotions = new WeakMap();
    const uiText = source => root.DMateI18n?.t?.(source) ?? source;

    const SYMBOL_GROUPS = [
        { id:'logic', label:'逻辑', items:[
            ["¬","逻辑非"], ["∧","合取"], ["∨","析取"], ["⊕","异或"],
            ["→","蕴含"], ["↔","等价"], ["⇒","推出"], ["⇔","等价推出"],
            ["∀","全称量词"], ["∃","存在量词"], ["∄","不存在"], ["⊤","永真"],
            ["⊥","矛盾／假"], ["⊢","语法可证"], ["⊨","语义蕴含"], ["⊭","不语义蕴含"],
            ["∴","所以"], ["∵","因为"]
        ]},
        { id:'sets', label:'集合', items:[
            ["∈","属于"], ["∉","不属于"], ["∋","包含元素"], ["∌","不包含元素"],
            ["⊆","子集或等于"], ["⊊","真子集"], ["⊂","子集（依教材约定）"], ["⊇","超集或等于"],
            ["⊋","真超集"], ["⊃","超集（依教材约定）"], ["∪","并集"], ["∩","交集"],
            ["∅","空集"], ["∖","集合差"], ["℘","幂集"], ["×","笛卡尔积"],
            ["∁","补集"], ["⊄","非子集"], ["⊈","非子集或等于"], ["∣","整除／集合关系符号"]
        ]},
        { id:'relations', label:'关系', items:[
            ["≠","不等于"], ["≡","恒等／同余"], ["≢","不恒等"], ["≈","约等于"],
            ["≉","不约等于"], ["∼","等价／相似关系"], ["≃","相似"], ["≤","小于等于"],
            ["≥","大于等于"], ["≪","远小于"], ["≫","远大于"], ["∝","正比于"],
            ["∥","平行"], ["⊥","垂直"], ["∘","关系复合"], ["≺","先于"],
            ["≼","不严格先于"]
        ]},
        { id:'number', label:'数论', items:[
            ["ℕ","自然数集"], ["ℤ","整数集"], ["ℚ","有理数集"], ["ℝ","实数集"],
            ["ℂ","复数集"], ["∣","整除"], ["∤","不整除"], ["≡","同余"],
            ["∞","无穷大"], ["⌊x⌋","向下取整"], ["⌈x⌉","向上取整"], ["√n","平方根"]
        ]},
        { id:'count', label:'计数', items:[
            ["⁰","上标 0"], ["¹","上标 1"], ["²","上标 2"], ["³","上标 3"],
            ["⁴","上标 4"], ["⁵","上标 5"], ["⁶","上标 6"], ["⁷","上标 7"],
            ["⁸","上标 8"], ["⁹","上标 9"], ["₀","下标 0"], ["₁","下标 1"],
            ["₂","下标 2"], ["₃","下标 3"], ["₄","下标 4"], ["₅","下标 5"],
            ["₆","下标 6"], ["₇","下标 7"], ["₈","下标 8"], ["₉","下标 9"],
            ["∑","求和"], ["∏","连乘"], ["ⁿ","上标 n"], ["ₙ","下标 n"],
            ["…","省略号"]
        ]},
        { id:'greek', label:'希腊', items:[
            ["α","小写阿尔法"], ["β","小写贝塔"], ["γ","小写伽马"], ["δ","小写德尔塔"],
            ["ε","小写艾普西龙"], ["ζ","小写泽塔"], ["η","小写伊塔"], ["θ","小写西塔"],
            ["ι","小写约塔"], ["κ","小写卡帕"], ["λ","小写拉姆达"], ["μ","小写缪"],
            ["ν","小写纽"], ["ξ","小写克西"], ["π","小写派"], ["ρ","小写柔"],
            ["σ","小写西格马"], ["τ","小写陶"], ["υ","小写宇普西龙"], ["φ","小写斐"],
            ["χ","小写希"], ["ψ","小写普西"], ["ω","小写欧米伽"], ["Γ","大写伽马"],
            ["Δ","大写德尔塔"], ["Θ","大写西塔"], ["Λ","大写拉姆达"], ["Π","大写派"],
            ["Σ","大写西格马"], ["Φ","大写斐"], ["Ψ","大写普西"], ["Ω","大写欧米伽"]
        ]},
    ];

    function mountSymbolKeyboard(input, win) {
        const doc = input.ownerDocument;
        const host = input.parentElement;
        if (!host || host.querySelector('.dmate-symbol-keyboard')) return null;

        function normalizeItem(item) {
            if (Array.isArray(item)) {
                return {
                    value:String(item[0] || ''),
                    label:String(item[1] || item[0] || '')
                };
            }
            return {
                value:String(item?.value || ''),
                label:String(item?.label || item?.value || '')
            };
        }

        const toggle = doc.createElement('button');
        toggle.type = 'button';
        toggle.className = 'dmate-symbol-keyboard';
        toggle.setAttribute('aria-label', uiText('数学符号键盘'));
        toggle.setAttribute('title', uiText('数学符号'));
        toggle.setAttribute('aria-expanded', 'false');
        toggle.setAttribute('aria-controls', 'dmate-symbol-panel');
        toggle.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2.8" y="5.2" width="18.4" height="13.6" rx="2.2"/><path d="M6.5 9h.01M10 9h.01M13.5 9h.01M17 9h.01M6.5 12.3h.01M10 12.3h.01M13.5 12.3h.01M17 12.3h.01M8.5 15.5h7"/></svg>';

        const panel = doc.createElement('div');
        panel.id = 'dmate-symbol-panel';
        panel.className = 'dmate-symbol-panel';
        panel.hidden = true;
        panel.setAttribute('role', 'dialog');
        panel.setAttribute('aria-label', uiText('数学符号键盘'));

        const header = doc.createElement('div');
        header.className = 'dmate-symbol-panel-head';
        const heading = doc.createElement('div');
        heading.className = 'dmate-symbol-panel-title';
        heading.textContent = uiText('数学符号');
        header.append(heading);

        const tabs = doc.createElement('div');
        tabs.className = 'dmate-symbol-tabs';
        tabs.setAttribute('role', 'tablist');
        tabs.setAttribute('aria-label', uiText('符号分类'));

        const grid = doc.createElement('div');
        grid.className = 'dmate-symbol-grid';
        grid.setAttribute('role', 'group');
        grid.setAttribute('aria-label', uiText('可插入的数学符号'));

        panel.append(header, tabs, grid);
        host.append(toggle);
        doc.body.append(panel);

        let activeGroup = 'logic';
        let opened = false;

        function translateSymbolKey(key) {
            const label = uiText(key.dataset.symbolLabel);
            // Write the canonical label again even while a tooltip owns an
            // empty native title; its observer updates the held hover label.
            key.setAttribute('title', label);
            const separator = root.DMateI18n?.isEnglish?.() ? ': ' : '：';
            key.setAttribute('aria-label', label + separator + key.dataset.symbolValue);
        }

        function refreshLanguage() {
            toggle.setAttribute('aria-label', uiText('数学符号键盘'));
            toggle.setAttribute('title', uiText('数学符号'));
            panel.setAttribute('aria-label', uiText('数学符号键盘'));
            heading.textContent = uiText('数学符号');
            tabs.setAttribute('aria-label', uiText('符号分类'));
            grid.setAttribute('aria-label', uiText('可插入的数学符号'));
            for (const tab of tabs.children) {
                const group = SYMBOL_GROUPS.find(item => item.id === tab.dataset.symbolCategory);
                if (group) tab.textContent = uiText(group.label);
            }
            for (const key of grid.querySelectorAll('[data-symbol-value]')) translateSymbolKey(key);
            const empty = grid.querySelector('.dmate-symbol-empty');
            if (empty) empty.textContent = uiText('该分类暂无符号。');
            // Translate in place: category, focus, scrolling, draft and caret
            // all stay owned by the existing controls.
            requestPanelPosition();
        }

        function focusSafely(element) {
            try { element?.focus({ preventScroll:true }); }
            catch (_error) { element?.focus?.(); }
        }

        function renderGroup() {
            tabs.replaceChildren();
            grid.replaceChildren();
            // Use the actual active conversation fill, so selected symbol tabs
            // match the sidebar in light, dark, and custom appearance themes.
            const activeSession = doc.querySelector('#sessions .session.active');
            const activeFill = activeSession ? win.getComputedStyle(activeSession).backgroundColor : '';
            if (activeFill && activeFill !== 'transparent' && activeFill !== 'rgba(0, 0, 0, 0)') {
                panel.style.setProperty('--dm-symbol-selected-bg', activeFill);
            } else {
                panel.style.removeProperty('--dm-symbol-selected-bg');
            }

            for (const group of SYMBOL_GROUPS) {
                const tab = doc.createElement('button');
                tab.type = 'button';
                tab.className = 'dmate-symbol-tab';
                tab.textContent = uiText(group.label);
                tab.dataset.symbolCategory = group.id;
                tab.setAttribute('role', 'tab');
                tab.setAttribute('aria-selected', String(group.id === activeGroup));
                tab.setAttribute('aria-pressed', String(group.id === activeGroup));
                tabs.appendChild(tab);
            }

            const selected = SYMBOL_GROUPS.find(group => group.id === activeGroup) || SYMBOL_GROUPS[0];
            const items = selected.items.map(normalizeItem).filter(item => item.value);
            if (!items.length) {
                const empty = doc.createElement('div');
                empty.className = 'dmate-symbol-empty';
                empty.textContent = uiText('该分类暂无符号。');
                grid.appendChild(empty);
                return;
            }

            for (const item of items) {
                const key = doc.createElement('button');
                key.type = 'button';
                key.className = 'dmate-symbol-key';
                if (item.value.length > 3 || /[A-Za-z]/.test(item.value)) key.classList.add('is-text');
                const glyph = doc.createElement('span');
                glyph.setAttribute('translate', 'no');
                glyph.textContent = item.value;
                key.append(glyph);
                key.dataset.symbolValue = item.value;
                key.dataset.symbolLabel = item.label;
                translateSymbolKey(key);
                grid.appendChild(key);
            }
        }

        // A body-level popover avoids overflow/transform clipping by the
        // desktop composer, Safari visual viewport and iPad split-view shell.
        function positionSymbolPanel() {
            if (!opened || panel.hidden) return;
            const viewport = win.visualViewport;
            const viewTop = viewport?.offsetTop || 0;
            const viewLeft = viewport?.offsetLeft || 0;
            const viewWidth = viewport?.width || win.innerWidth || 360;
            const viewHeight = viewport?.height || win.innerHeight || 600;
            const compact = win.matchMedia?.('(max-width:1100px)').matches ?? false;
            const phone = win.matchMedia?.('(max-width:680px)').matches ?? false;
            const width = Math.min(phone ? 312 : compact ? 340 : 360,
                Math.max(80, viewWidth - 20));
            const topbar = doc.querySelector('.mobile-topbar');
            const topbarBottom = compact && topbar
                && win.getComputedStyle(topbar).display !== 'none'
                ? topbar.getBoundingClientRect().bottom : 0;
            const topLimit = Math.max(viewTop + 10, topbarBottom + 8);
            const bottomLimit = viewTop + viewHeight - 10;
            const toggleBounds = toggle.getBoundingClientRect();
            const inputBounds = host.closest('.input')?.getBoundingClientRect()
                || toggleBounds;
            const above = Math.max(0, inputBounds.top - topLimit - 8);
            const below = Math.max(0, bottomLimit - inputBounds.bottom - 8);

            // Compact layouts prefer the space below the input when usable;
            // desktop browsers prefer above it. Both can fall back when
            // Safari toolbars, iPad multitasking or the keyboard move.
            const placeBelow = compact
                ? (below >= 150 || below > above)
                : (above < 160 && below > above);
            const available = placeBelow ? below : above;
            const maxHeight = Math.max(0, Math.min(compact ? 320 : 380, available));
            panel.style.setProperty('--dm-symbol-width', width + 'px');
            panel.style.setProperty('--dm-symbol-max-height', maxHeight + 'px');

            const measured = panel.getBoundingClientRect();
            const panelHeight = Math.min(measured.height, maxHeight);
            const rawTop = placeBelow
                ? inputBounds.bottom + 8 : inputBounds.top - panelHeight - 8;
            const top = Math.max(topLimit, Math.min(rawTop, bottomLimit - panelHeight));
            const rightLimit = viewLeft + viewWidth - width - 10;
            const left = Math.max(viewLeft + 10, Math.min(
                toggleBounds.right - width + 12, rightLimit
            ));
            panel.style.setProperty('--dm-symbol-left', Math.round(left) + 'px');
            panel.style.setProperty('--dm-symbol-top', Math.round(top) + 'px');
        }

        let positionFrame = 0;
        function requestPanelPosition(event) {
            if (!opened || (event?.target && panel.contains(event.target))) return;
            if (positionFrame) return;
            positionFrame = win.requestAnimationFrame(() => {
                positionFrame = 0;
                positionSymbolPanel();
            });
        }

        function setOpen(next, restoreFocus = false) {
            opened = Boolean(next);
            panel.hidden = !opened;
            toggle.setAttribute('aria-expanded', String(opened));
            if (opened) {
                renderGroup();
                positionSymbolPanel();
                const activeTab = tabs.querySelector('[data-symbol-category="' + activeGroup + '"]');
                focusSafely(activeTab);
            } else if (restoreFocus) {
                focusSafely(toggle);
            }
        }

        function insertSymbol(value) {
            if (input.disabled || input.readOnly || !value) return;
            const start = Number.isInteger(input.selectionStart) ? input.selectionStart : input.value.length;
            const end = Number.isInteger(input.selectionEnd) ? input.selectionEnd : start;

            if (typeof input.setRangeText === 'function') {
                input.setRangeText(value, start, end, 'end');
            } else {
                input.value = input.value.slice(0, start) + value + input.value.slice(end);
            }

            focusSafely(input);
            const caret = start + value.length;
            try { input.setSelectionRange(caret, caret); } catch (_error) {}

            let inputEvent;
            try {
                inputEvent = new win.InputEvent('input', {
                    bubbles:true,
                    inputType:'insertText',
                    data:value
                });
            } catch (_error) {
                inputEvent = new win.Event('input', { bubbles:true });
            }
            input.dispatchEvent(inputEvent);
        }

        function onPanelClick(event) {
            const tab = event.target.closest?.('[data-symbol-category]');
            if (tab && panel.contains(tab)) {
                activeGroup = tab.dataset.symbolCategory;
                renderGroup();
                positionSymbolPanel();
                focusSafely(tabs.querySelector('[data-symbol-category="' + activeGroup + '"]'));
                return;
            }
            const key = event.target.closest?.('[data-symbol-value]');
            if (key && panel.contains(key)) {
                insertSymbol(key.dataset.symbolValue || '');
            }
        }

        function onOutsidePointer(event) {
            if (!opened) return;
            if (panel.contains(event.target) || toggle.contains(event.target)) return;
            setOpen(false);
        }

        function onEscape(event) {
            if (event.key !== 'Escape' || !opened) return;
            event.preventDefault();
            event.stopPropagation();
            setOpen(false, true);
        }

        function onToggleClick() { setOpen(!opened, opened); }

        toggle.addEventListener('click', onToggleClick);
        toggle.addEventListener('keydown', onEscape);
        panel.addEventListener('click', onPanelClick);
        panel.addEventListener('keydown', onEscape);
        input.addEventListener('keydown', onEscape);
        doc.addEventListener('pointerdown', onOutsidePointer);
        win.addEventListener('resize', requestPanelPosition);
        win.visualViewport?.addEventListener('resize', requestPanelPosition);
        win.visualViewport?.addEventListener('scroll', requestPanelPosition);
        doc.addEventListener('scroll', requestPanelPosition, true);
        win.addEventListener('dmate:languagechange', refreshLanguage);

        return {
            refreshPosition: positionSymbolPanel,
            refresh() {
                toggle.disabled = Boolean(input.disabled || input.readOnly);
                if (toggle.disabled && opened) setOpen(false);
            },
            destroy() {
                toggle.removeEventListener('click', onToggleClick);
                toggle.removeEventListener('keydown', onEscape);
                panel.removeEventListener('click', onPanelClick);
                panel.removeEventListener('keydown', onEscape);
                input.removeEventListener('keydown', onEscape);
                doc.removeEventListener('pointerdown', onOutsidePointer);
                win.removeEventListener('resize', requestPanelPosition);
                win.visualViewport?.removeEventListener('resize', requestPanelPosition);
                win.visualViewport?.removeEventListener('scroll', requestPanelPosition);
                doc.removeEventListener('scroll', requestPanelPosition, true);
                win.removeEventListener('dmate:languagechange', refreshLanguage);
                if (positionFrame) win.cancelAnimationFrame(positionFrame);
                toggle.remove();
                panel.remove();
            }
        };
    }

    function transitionConversation(center, empty) {
        if (!center || center.classList.contains('chat-empty') === empty) return;
        const win = center.ownerDocument.defaultView || root;
        const capsule = center.querySelector(':scope > .input-wrap > .input');
        const mode = center.querySelector(':scope > .input-wrap > .manual-question-mode');
        const input = capsule?.querySelector('textarea');
        const targets = [capsule, mode].filter(node => node?.getClientRects().length);
        // Read the visible, possibly interrupted frame before releasing any
        // temporary styles. The textarea and its selection never move in DOM.
        const first = targets.map(node => node.getBoundingClientRect());
        conversationMotions.get(center)?.();
        center.classList.toggle('chat-empty', empty);
        const reduced = win.matchMedia?.('(prefers-reduced-motion:reduce)');
        if (!capsule || !targets.length || reduced?.matches) return;
        instances.get(input)?.refresh();
        const last = targets.map(node => node.getBoundingClientRect());
        if (last.some(rect => !rect.width || !rect.height)) return;
        if (first.every((rect, i) => Math.abs(rect.x-last[i].x) < .5
            && Math.abs(rect.y-last[i].y) < .5 && Math.abs(rect.width-last[i].width) < .5)) return;

        const saved = targets.map(node => ['width', 'translate'].map(property => ({
            property, value:node.style.getPropertyValue(property),
            priority:node.style.getPropertyPriority(property)
        })));
        const restore = (node, properties) => {
            for (const {property, value, priority} of properties) {
                if (value) node.style.setProperty(property, value, priority);
                else node.style.removeProperty(property);
            }
        };
        let frame = 0, stopped = false;
        const stop = () => {
            if (stopped) return;
            stopped = true;
            win.cancelAnimationFrame(frame);
            targets.forEach((node, i) => restore(node, saved[i]));
            reduced?.removeEventListener?.('change', stop);
            conversationMotions.delete(center);
            delete center.dataset.composerMotion;
            instances.get(input)?.refresh();
        };
        conversationMotions.set(center, stop);
        center.dataset.composerMotion = 'moving';
        reduced?.addEventListener?.('change', stop);
        // Match the sidebar's .22s cubic-bezier(.2,.8,.2,1). Solve its
        // x-coordinate instead of applying the bezier parameter as time.
        const ease = progress => {
            let low = 0, high = 1;
            for (let i = 0; i < 16; i++) {
                const t = (low+high)/2, inverse = 1-t;
                const x = .6*inverse*inverse*t + .6*inverse*t*t + t*t*t;
                if (x < progress) low = t; else high = t;
            }
            const t = (low+high)/2, inverse = 1-t;
            return 2.4*inverse*inverse*t + 3*inverse*t*t + t*t*t;
        };
        // Start the clock on the first painted frame. Rendering a large
        // conversation synchronously must not consume the movement unseen.
        let started = null;
        const tick = now => {
            if (stopped) return;
            if (!center.isConnected || capsule.closest('.input-wrap')?.hidden) { stop(); return; }
            if (now !== null && started === null) started = now;
            const progress = now === null ? 0 : Math.min(1, Math.max(0, (now-started)/220));
            if (progress >= 1) { stop(); return; }
            const remaining = progress ? 1-ease(progress) : 1;
            // Measure the live destination, so the existing sidebar grid
            // transition can continue underneath this vertical motion.
            targets.forEach((node, i) => restore(node, saved[i]));
            const natural = targets.map(node => node.getBoundingClientRect());
            targets.forEach((node, i) => {
                if (node === capsule) {
                    const width = natural[i].width + (first[i].width-last[i].width)*remaining;
                    node.style.setProperty('width', Math.max(1, width)+'px', 'important');
                }
            });
            targets.forEach((node, i) => {
                const rect = node.getBoundingClientRect();
                const x = natural[i].x+natural[i].width/2
                    + (first[i].x+first[i].width/2-last[i].x-last[i].width/2)*remaining;
                const y = natural[i].y+natural[i].height/2
                    + (first[i].y+first[i].height/2-last[i].y-last[i].height/2)*remaining;
                // Translation plus real width interpolation keeps font size,
                // caret geometry and mobile keyboard zoom unchanged.
                node.style.setProperty('translate', (x-rect.x-rect.width/2)+'px '
                    + (y-rect.y-rect.height/2)+'px', 'important');
            });
            instances.get(input)?.refreshPosition();
            frame = win.requestAnimationFrame(tick);
        };
        tick(null);
    }

    function mount(options) {
        const input = options.input;
        if (!input) throw new Error('消息输入框未加载。');
        if (instances.has(input)) return instances.get(input);
        const win = input.ownerDocument.defaultView || root;
        const composer = input.closest('.input');
        const symbolKeyboard = mountSymbolKeyboard(input, win);
        let composing = false, commitUntil = 0, destroyed = false, previousWidth = -1;
        function refresh() {
            if (destroyed) return;
            symbolKeyboard?.refresh();
            const style = win.getComputedStyle(input);
            const line = Number.parseFloat(style.lineHeight) || 24;
            const padding = (Number.parseFloat(style.paddingTop) || 0) + (Number.parseFloat(style.paddingBottom) || 0);
            const minimum = Math.max(Number.parseFloat(style.minHeight) || 0, line + padding);
            const viewport = win.visualViewport?.height || win.innerHeight || 700;
            const maximum = Math.max(minimum, Math.min(line * 6 + padding, Math.max(96, viewport * .3)));
            input.style.setProperty('max-height', maximum + 'px', 'important');
            input.style.setProperty('height', 'auto', 'important');
            const measured = input.scrollHeight || minimum;
            const height = Math.max(minimum, Math.min(maximum, measured));
            input.style.setProperty('height', height + 'px', 'important');
            input.style.setProperty('overflow-y', measured > maximum + 1 ? 'auto' : 'hidden', 'important');
            composer?.classList.toggle('composer-expanded', height > minimum + 2);
        }
        const compositionStart = () => { composing = true; };
        const compositionEnd = () => { composing = false; commitUntil = Date.now() + 40; refresh(); };
        function keydown(event) {
            if (event.key !== 'Enter' || event.shiftKey || event.altKey || event.ctrlKey || event.metaKey
                || composing || event.isComposing || event.keyCode === 229 || Date.now() < commitUntil) return;
            // A mobile keyboard's Return inserts a new line. Desktop Enter
            // sends; Shift+Enter always remains available for a new line.
            if (win.matchMedia?.('(max-width:680px)').matches || win.matchMedia?.('(pointer:coarse)').matches) return;
            event.preventDefault();
            if (!input.disabled && !input.readOnly) options.onSend?.();
        }
        const widthObserver = typeof win.ResizeObserver === 'function' ? new win.ResizeObserver(() => {
            const width = input.clientWidth;
            if (width !== previousWidth) { previousWidth = width; refresh(); }
        }) : null;
        widthObserver?.observe(input);
        input.addEventListener('input', refresh);
        input.addEventListener('compositionstart', compositionStart);
        input.addEventListener('compositionend', compositionEnd);
        input.addEventListener('keydown', keydown);
        win.addEventListener('resize', refresh);
        win.visualViewport?.addEventListener('resize', refresh);
        const api = { refresh, refreshPosition() { symbolKeyboard?.refreshPosition(); }, destroy() {
            if (destroyed) return;
            destroyed = true; widthObserver?.disconnect();
            symbolKeyboard?.destroy();
            input.removeEventListener('input', refresh);
            input.removeEventListener('compositionstart', compositionStart);
            input.removeEventListener('compositionend', compositionEnd);
            input.removeEventListener('keydown', keydown);
            win.removeEventListener('resize', refresh);
            win.visualViewport?.removeEventListener('resize', refresh);
            instances.delete(input);
        } };
        instances.set(input, api); refresh();
        return api;
    }
    root.DMateChatComposer = { mount, transitionConversation };
})(typeof window !== 'undefined' ? window : globalThis);
