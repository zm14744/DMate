/* Inline editing only owns the draft view; its caller owns message history. */
(function (root) {
    'use strict';

    const uiText = (source, english) => root.DMateI18n?.t?.(source, english) ?? source;

    function mount(options) {
        const host = options?.host;
        if (!host?.ownerDocument) throw new Error('Message editor host is missing');
        const doc = host.ownerDocument, win = doc.defaultView || root;
        const maxCharacters = Number.isInteger(options.maxCharacters) && options.maxCharacters > 0
            ? options.maxCharacters : 20000;
        let destroyed = false, composing = false, submitting = false, frame = 0, failure = '', commitUntil = 0;
        const editor = doc.createElement('div');
        editor.className = 'chat-message-edit';
        editor.setAttribute('data-chat-message-edit', '');

        const input = doc.createElement('textarea');
        input.className = 'chat-message-edit-input';
        input.rows = 3;
        input.value = typeof options.value === 'string' ? options.value : '';
        input.setAttribute('aria-label', uiText('重新编辑消息', 'Edit message'));
        input.setAttribute('data-i18n-content', '');

        const error = doc.createElement('p');
        error.className = 'chat-message-edit-error';
        error.setAttribute('role', 'status');
        error.hidden = true;

        const actions = doc.createElement('div');
        actions.className = 'chat-message-edit-actions';
        actions.setAttribute('data-i18n-ui', '');
        const cancel = doc.createElement('button');
        cancel.type = 'button';
        cancel.className = 'chat-message-edit-cancel';
        cancel.textContent = uiText('取消', 'Cancel');
        const send = doc.createElement('button');
        send.type = 'button';
        send.className = 'chat-message-edit-send';
        send.textContent = uiText('发送', 'Send');
        actions.append(cancel, send);
        editor.append(input, error, actions);
        host.replaceChildren(editor);

        const selection = () => ({ start:input.selectionStart, end:input.selectionEnd,
            direction:input.selectionDirection || 'none' });
        const overLimit = () => Array.from(input.value).length > maxCharacters;
        function sync() {
            if (destroyed) return;
            const invalid = overLimit();
            send.disabled = submitting || invalid || !input.value.trim();
            cancel.disabled = submitting;
            send.setAttribute('aria-busy', String(submitting));
            input.setAttribute('aria-invalid', String(invalid));
            error.hidden = !invalid && !failure;
            error.textContent = invalid ? uiText(
                `单条文字消息最多 ${maxCharacters} 字符`,
                `Messages can contain at most ${maxCharacters.toLocaleString('en-US')} characters`
            ) : failure;
        }
        function resize() {
            if (destroyed || !input.isConnected) return;
            input.style.height = 'auto';
            input.style.height = input.scrollHeight + 'px';
        }
        function changed() {
            failure = '';
            sync();
            resize();
            options.onChange?.(input.value, selection());
        }
        async function submit() {
            if (destroyed || submitting || composing || overLimit() || !input.value.trim()) return;
            failure = '';
            submitting = true;
            sync();
            try {
                await options.onSubmit?.(input.value.trim());
            } catch (cause) {
                if (!destroyed) {
                    failure = cause?.message || uiText('无法发送修改，请重试', 'The edit could not be sent, please try again');
                    options.onError?.(cause);
                }
            } finally {
                if (!destroyed) { submitting = false; sync(); }
            }
        }
        input.addEventListener('input', changed);
        input.addEventListener('select', () => options.onSelectionChange?.(selection()));
        input.addEventListener('compositionstart', () => { composing = true; });
        input.addEventListener('compositionend', () => {
            composing = false;
            commitUntil = Date.now() + 40;
            changed();
        });
        input.addEventListener('keydown', event => {
            if (event.isComposing || composing || event.keyCode === 229) return;
            if (event.key === 'Enter' && !event.shiftKey && !event.altKey && !event.ctrlKey && !event.metaKey
                && Date.now() >= commitUntil) {
                event.preventDefault();
                event.stopPropagation();
                void submit();
            } else if (event.key === 'Escape' && !submitting) {
                event.preventDefault();
                event.stopPropagation();
                options.onCancel?.();
            }
        });
        cancel.addEventListener('click', () => { if (!submitting) options.onCancel?.(); });
        send.addEventListener('click', () => { void submit(); });
        const viewportResize = () => resize();
        win.addEventListener('resize', viewportResize);
        win.visualViewport?.addEventListener('resize', viewportResize);
        sync();
        frame = win.requestAnimationFrame(resize);
        root.DMateI18n?.translate?.(actions);

        return {
            element:editor, textarea:input, cancelButton:cancel, submitButton:send,
            focus(range) {
                if (destroyed) return;
                resize();
                input.focus({ preventScroll:true });
                const start = Number.isInteger(range?.start) ? range.start : input.value.length;
                const end = Number.isInteger(range?.end) ? range.end : start;
                input.setSelectionRange(start, end, range?.direction || 'none');
            },
            destroy() {
                if (destroyed) return;
                destroyed = true;
                win.cancelAnimationFrame(frame);
                win.removeEventListener('resize', viewportResize);
                win.visualViewport?.removeEventListener('resize', viewportResize);
                editor.remove();
            }
        };
    }

    root.DMateChatMessageEdit = Object.freeze({ mount });
})(typeof window === 'undefined' ? globalThis : window);
