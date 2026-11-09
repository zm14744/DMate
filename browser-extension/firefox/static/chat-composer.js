(function (root) {
    'use strict';
    const instances = new WeakMap();

    const SYMBOL_GROUPS = [
        { id:'common', label:'常用', items:[
            ['∀','任意／全称量词'], ['∃','存在量词'], ['∈','属于'], ['∉','不属于'],
            ['⊆','子集或等于'], ['∪','并集'], ['∩','交集'], ['∅','空集'],
            ['¬','逻辑非'], ['∧','逻辑与'], ['∨','逻辑或'], ['→','蕴含／箭头'],
            ['↔','等价'], ['⇒','推出'], ['⇔','当且仅当'], ['≠','不等于'],
            ['≤','小于等于'], ['≥','大于等于']
        ]},
        { id:'logic', label:'逻辑', items:[
            ['¬','逻辑非'], ['∧','逻辑与'], ['∨','逻辑或'], ['⊕','异或'],
            ['→','蕴含'], ['↔','等价'], ['⇒','推出'], ['⇔','等价推出'],
            ['∀','全称量词'], ['∃','存在量词'], ['∄','不存在'], ['⊤','永真'],
            ['⊥','矛盾／假'], ['⊢','语法可证'], ['⊨','语义蕴含'], ['⊭','不语义蕴含']
        ]},
        { id:'sets', label:'集合', items:[
            ['∈','属于'], ['∉','不属于'], ['∋','包含元素'], ['∌','不包含元素'],
            ['⊆','子集或等于'], ['⊂','真子集'], ['⊇','超集或等于'], ['⊃','真超集'],
            ['∪','并集'], ['∩','交集'], ['∅','空集'], ['∖','集合差'],
            ['℘','幂集'], ['×','笛卡尔积'], ['∁','补集'], ['∴','所以']
        ]},
        { id:'relations', label:'关系', items:[
            ['=','等于'], ['≠','不等于'], ['≡','恒等／同余'], ['≢','不恒等'],
            ['≈','约等于'], ['∼','相似／等价关系'], ['≃','渐近相等'], ['<','小于'],
            ['≤','小于等于'], ['>','大于'], ['≥','大于等于'], ['≺','先于'],
            ['≼','不严格先于'], ['∥','平行'], ['⊥','垂直'], ['∘','关系复合']
        ]},
        { id:'graph', label:'图论', items:[
            ['G=(V,E)','图的表示'], ['V(G)','顶点集'], ['E(G)','边集'], ['deg(v)','顶点度'],
            ['d(v)','顶点度'], ['δ(G)','最小度'], ['Δ(G)','最大度'], ['Kₙ','完全图'],
            ['Cₙ','圈图'], ['Pₙ','路径图'], ['χ(G)','色数'], ['ω(G)','团数'],
            ['α(G)','独立数'], ['λ(G)','边连通度'], ['κ(G)','点连通度'], ['N(v)','邻域']
        ]},
        { id:'number', label:'数论', items:[
            ['ℕ','自然数集'], ['ℤ','整数集'], ['ℚ','有理数集'], ['ℝ','实数集'],
            ['ℂ','复数集'], ['∣','整除'], ['∤','不整除'], ['≡','同余'],
            ['mod','模运算'], ['gcd','最大公因数'], ['lcm','最小公倍数'], ['∞','无穷大'],
            ['√','平方根'], ['∑','求和'], ['∏','连乘'], ['∈','属于']
        ]},
        { id:'count', label:'计数', items:[
            ['∑','求和'], ['∏','连乘'], ['n!','阶乘'], ['C(n,k)','组合数'],
            ['P(n,k)','排列数'], ['⁰','上标零'], ['¹','上标一'], ['²','上标二'],
            ['³','上标三'], ['ⁿ','上标 n'], ['₀','下标零'], ['₁','下标一'],
            ['₂','下标二'], ['₃','下标三'], ['ₙ','下标 n'], ['…','省略号']
        ]},
        { id:'greek', label:'希腊字母', items:[
            ['α','alpha'], ['β','beta'], ['γ','gamma'], ['δ','delta'],
            ['ε','epsilon'], ['θ','theta'], ['λ','lambda'], ['μ','mu'],
            ['π','pi'], ['ρ','rho'], ['σ','sigma'], ['τ','tau'],
            ['φ','phi'], ['χ','chi'], ['ψ','psi'], ['ω','omega'],
            ['Γ','Gamma'], ['Δ','Delta'], ['Θ','Theta'], ['Λ','Lambda'],
            ['Π','Pi'], ['Σ','Sigma'], ['Φ','Phi'], ['Ω','Omega']
        ]}
    ];

    function mountSymbolKeyboard(input, win) {
        const doc = input.ownerDocument;
        const host = input.parentElement;
        if (!host || host.querySelector('.dmate-symbol-keyboard')) return null;

        const toggle = doc.createElement('button');
        toggle.type = 'button';
        toggle.className = 'dmate-symbol-keyboard';
        toggle.setAttribute('aria-label', '数学符号键盘');
        toggle.setAttribute('title', '数学符号');
        toggle.setAttribute('aria-expanded', 'false');
        toggle.setAttribute('aria-controls', 'dmate-symbol-panel');
        toggle.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2.8" y="5.2" width="18.4" height="13.6" rx="2.2"/><path d="M6.5 9h.01M10 9h.01M13.5 9h.01M17 9h.01M6.5 12.3h.01M10 12.3h.01M13.5 12.3h.01M17 12.3h.01M8.5 15.5h7"/></svg>';

        const panel = doc.createElement('div');
        panel.id = 'dmate-symbol-panel';
        panel.className = 'dmate-symbol-panel';
        panel.hidden = true;
        panel.setAttribute('role', 'dialog');
        panel.setAttribute('aria-label', '数学符号键盘');

        const header = doc.createElement('div');
        header.className = 'dmate-symbol-panel-head';
        const heading = doc.createElement('div');
        heading.className = 'dmate-symbol-panel-title';
        heading.textContent = '数学符号';
        const closeButton = doc.createElement('button');
        closeButton.type = 'button';
        closeButton.className = 'dmate-symbol-panel-close';
        closeButton.setAttribute('aria-label', '关闭符号键盘');
        closeButton.title = '关闭';
        closeButton.textContent = '×';
        header.append(heading, closeButton);

        const tabs = doc.createElement('div');
        tabs.className = 'dmate-symbol-tabs';
        tabs.setAttribute('role', 'tablist');
        tabs.setAttribute('aria-label', '符号分类');

        const grid = doc.createElement('div');
        grid.className = 'dmate-symbol-grid';
        grid.setAttribute('role', 'group');
        grid.setAttribute('aria-label', '可插入的数学符号');

        panel.append(header, tabs, grid);
        host.append(toggle, panel);

        let activeGroup = 'common';
        let opened = false;

        function focusSafely(element) {
            try { element?.focus({ preventScroll:true }); }
            catch (_error) { element?.focus?.(); }
        }

        function renderGroup() {
            tabs.replaceChildren();
            grid.replaceChildren();

            for (const group of SYMBOL_GROUPS) {
                const tab = doc.createElement('button');
                tab.type = 'button';
                tab.className = 'dmate-symbol-tab';
                tab.textContent = group.label;
                tab.dataset.symbolCategory = group.id;
                tab.setAttribute('role', 'tab');
                tab.setAttribute('aria-selected', String(group.id === activeGroup));
                tab.setAttribute('aria-pressed', String(group.id === activeGroup));
                tabs.appendChild(tab);
            }

            const selected = SYMBOL_GROUPS.find(group => group.id === activeGroup) || SYMBOL_GROUPS[0];
            for (const [value, label] of selected.items) {
                const key = doc.createElement('button');
                key.type = 'button';
                key.className = 'dmate-symbol-key';
                if (value.length > 3 || /[A-Za-z]/.test(value)) key.classList.add('is-text');
                key.textContent = value;
                key.dataset.symbolValue = value;
                key.title = label;
                key.setAttribute('aria-label', label + '：' + value);
                grid.appendChild(key);
            }
        }

        function setOpen(next, restoreFocus = false) {
            opened = Boolean(next);
            panel.hidden = !opened;
            toggle.setAttribute('aria-expanded', String(opened));
            if (opened) {
                renderGroup();
                const activeTab = tabs.querySelector('[data-symbol-category="' + activeGroup + '"]');
                focusSafely(activeTab);
            } else if (restoreFocus) {
                focusSafely(toggle);
            }
        }

        function insertSymbol(value) {
            if (input.disabled || input.readOnly) return;
            const start = Number.isInteger(input.selectionStart) ? input.selectionStart : input.value.length;
            const end = Number.isInteger(input.selectionEnd) ? input.selectionEnd : start;
            if (typeof input.setRangeText === 'function') {
                input.setRangeText(value, start, end, 'end');
            } else {
                input.value = input.value.slice(0, start) + value + input.value.slice(end);
                input.setSelectionRange(start + value.length, start + value.length);
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
                focusSafely(tabs.querySelector('[data-symbol-category="' + activeGroup + '"]'));
                return;
            }
            const key = event.target.closest?.('[data-symbol-value]');
            if (key && panel.contains(key)) insertSymbol(key.dataset.symbolValue || '');
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

        function onPanelMouseDown(event) {
            if (event.target.closest?.('button')) event.preventDefault();
        }

        function onToggleClick() { setOpen(!opened, opened); }
        function onToggleMouseDown(event) { event.preventDefault(); }
        function onCloseClick() { setOpen(false, true); }

        toggle.addEventListener('click', onToggleClick);
        toggle.addEventListener('mousedown', onToggleMouseDown);
        toggle.addEventListener('keydown', onEscape);
        closeButton.addEventListener('click', onCloseClick);
        panel.addEventListener('click', onPanelClick);
        panel.addEventListener('mousedown', onPanelMouseDown);
        panel.addEventListener('keydown', onEscape);
        input.addEventListener('keydown', onEscape);
        doc.addEventListener('pointerdown', onOutsidePointer);

        return {
            refresh() {
                toggle.disabled = Boolean(input.disabled || input.readOnly);
                if (toggle.disabled && opened) setOpen(false);
            },
            destroy() {
                toggle.removeEventListener('click', onToggleClick);
                toggle.removeEventListener('mousedown', onToggleMouseDown);
                toggle.removeEventListener('keydown', onEscape);
                closeButton.removeEventListener('click', onCloseClick);
                panel.removeEventListener('click', onPanelClick);
                panel.removeEventListener('mousedown', onPanelMouseDown);
                panel.removeEventListener('keydown', onEscape);
                input.removeEventListener('keydown', onEscape);
                doc.removeEventListener('pointerdown', onOutsidePointer);
                toggle.remove();
                panel.remove();
            }
        };
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
        const api = { refresh, destroy() {
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
    root.DMateChatComposer = { mount };
})(typeof window !== 'undefined' ? window : globalThis);
