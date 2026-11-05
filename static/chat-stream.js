(function (root) {
    'use strict';
    const SOURCE_LIMIT = 512 * 1024;
    const EVENT_LIMIT = 1024 * 1024;
    const encoder = new TextEncoder();
    const aborted = () => {
        const error = new Error('回答已停止');
        error.name = 'AbortError';
        return error;
    };
    const failure = (data, status) => {
        const error = new Error(data?.error || data?.message || '回答连接中断，请重试');
        error.data = data;
        error.status = Number(data?.status || status) || undefined;
        error.code = data?.code || data?.error_code;
        return error;
    };
    const checkSize = text => {
        if (encoder.encode(text).byteLength > SOURCE_LIMIT) {
            throw failure({ error:'回答内容过长，请拆分问题后重试', code:'stream_source_too_large' });
        }
    };

    async function read(response, options = {}) {
        const signal = options.signal;
        if (signal?.aborted) throw aborted();
        if (!response.headers?.get('content-type')?.includes('text/event-stream')) {
            let data;
            try { data = await response.json(); }
            catch (_) { throw failure({ error:'服务返回格式异常，请重试' }, response.status); }
            if (signal?.aborted) throw aborted();
            if (!response.ok || data?.error) throw failure(data, response.status);
            return data;
        }
        if (!response.ok || !response.body?.getReader) throw failure(null, response.status);
        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '', eventName = '', dataLines = [], eventLength = 0, sourceBytes = 0;
        const cancel = () => { void reader.cancel().catch(() => {}); };
        signal?.addEventListener('abort', cancel, { once:true });
        const dispatch = () => {
            if (signal?.aborted) throw aborted();
            const name = eventName || 'message';
            const raw = dataLines.join('\n');
            eventName = ''; dataLines = []; eventLength = 0;
            if (!raw) return null;
            let data;
            try { data = JSON.parse(raw); }
            catch (_) { throw failure({ error:'流式回答格式异常，请重试', code:'invalid_stream_event' }); }
            const type = name === 'message' ? data?.type : name;
            if (type === 'error') throw failure(data, response.status);
            if (type === 'delta') {
                if (typeof data?.text !== 'string') throw failure({ error:'流式回答格式异常', code:'invalid_stream_delta' });
                sourceBytes += encoder.encode(data.text).byteLength;
                if (sourceBytes > SOURCE_LIMIT) throw failure({ error:'回答内容过长，请拆分问题后重试', code:'stream_source_too_large' });
                if (signal?.aborted) throw aborted();
                if (data.text) options.onDelta?.(data.text);
            }
            if (type === 'final') {
                if (!data || typeof data.reply !== 'string' || !data.reply.trim() || data.error) {
                    throw failure(data || { error:'AI 服务没有返回有效回答' });
                }
                checkSize(data.reply);
                return data;
            }
            return null;
        };
        const line = value => {
            if (!value) return dispatch();
            if (value[0] === ':') return null;
            const colon = value.indexOf(':');
            const field = colon < 0 ? value : value.slice(0, colon);
            let contents = colon < 0 ? '' : value.slice(colon + 1);
            if (contents[0] === ' ') contents = contents.slice(1);
            if (field === 'event') eventName = contents;
            if (field === 'data') {
                eventLength += contents.length;
                if (eventLength > EVENT_LIMIT) throw failure({ error:'流式事件过大', code:'stream_event_too_large' });
                dataLines.push(contents);
            }
            return null;
        };
        try {
            while (true) {
                if (signal?.aborted) throw aborted();
                const chunk = await reader.read();
                if (signal?.aborted) throw aborted();
                buffer += decoder.decode(chunk.value, { stream:!chunk.done });
                if (buffer.length > EVENT_LIMIT) throw failure({ error:'流式事件过大', code:'stream_event_too_large' });
                while (true) {
                    const index = buffer.search(/[\r\n]/);
                    if (index < 0 || !chunk.done && buffer[index] === '\r' && index === buffer.length - 1) break;
                    const width = buffer[index] === '\r' && buffer[index + 1] === '\n' ? 2 : 1;
                    const final = line(buffer.slice(0, index));
                    buffer = buffer.slice(index + width);
                    if (final) return final;
                }
                if (chunk.done) {
                    if (buffer) line(buffer);
                    // An event is not complete until its blank separator.
                    throw failure({ error:'回答连接中断，未收到完整结果，请重试', code:'incomplete_stream' });
                }
            }
        } finally {
            signal?.removeEventListener('abort', cancel);
            try { await reader.cancel(); } catch (_) {}
            reader.releaseLock();
        }
    }

    function escaped(text, index) {
        let slashes = 0;
        while (index > 0 && text[--index] === '\\') slashes++;
        return slashes % 2 === 1;
    }
    function closing(text, delimiter, from) {
        let index = text.indexOf(delimiter, from);
        while (index >= 0 && escaped(text, index)) index = text.indexOf(delimiter, index + delimiter.length);
        return index;
    }

    // Do not send unfinished formatting to Markdown/MathJax. Completed opaque
    // spans also tell the block splitter where it must not cut a formula.
    function safeSource(source) {
        let cut = source.length;
        const spans = [];
        for (let index = 0; index < cut;) {
            const rest = source.slice(index);
            const startOfLine = index === 0 || source[index - 1] === '\n';
            const fence = startOfLine && /^( {0,3})(`{3,}|~{3,})/.exec(rest);
            if (fence) {
                const marker = fence[2];
                const pattern = new RegExp('^ {0,3}' + marker[0] + '{' + marker.length + ',}[ \\t]*$', 'gm');
                pattern.lastIndex = index + fence[0].length;
                const end = pattern.exec(source);
                if (!end) { cut = index; break; }
                spans.push([index, end.index + end[0].length]); index = end.index + end[0].length; continue;
            }
            let opener = '', ender = '';
            if (source.startsWith('\\(', index)) { opener = '\\('; ender = '\\)'; }
            else if (source.startsWith('\\[', index)) { opener = '\\['; ender = '\\]'; }
            else if (source[index] === '$' && !escaped(source, index)) {
                opener = source.startsWith('$$', index) ? '$$' : '$'; ender = opener;
            } else if (source[index] === '`') {
                opener = /^`+/.exec(rest)[0]; ender = opener;
            } else {
                const environment = /^\\begin\{([A-Za-z*]+)\}/.exec(rest);
                if (environment) { opener = environment[0]; ender = '\\end{' + environment[1] + '}'; }
            }
            if (opener) {
                const end = closing(source, ender, index + opener.length);
                if (end < 0) { cut = index; break; }
                spans.push([index, end + ender.length]); index = end + ender.length; continue;
            }
            if (source[index] === '\\') {
                if (index + 1 >= cut) { cut = index; break; }
                // Bare commands are not safe incremental formula fragments.
                // The canonical final formatter can repair a complete line.
                if (/[A-Za-z]/.test(source[index + 1])) { cut = source.lastIndexOf('\n', index) + 1; break; }
                index += 2; continue;
            }
            index++;
        }
        const stack = [];
        let spanIndex = 0;
        for (let index = 0; index < cut;) {
            while (spans[spanIndex] && index >= spans[spanIndex][1]) spanIndex++;
            if (spans[spanIndex] && index >= spans[spanIndex][0]) { index = spans[spanIndex][1]; continue; }
            const char = source[index];
            if (char === '\\') { index += 2; continue; }
            if (char === '[' || char === '!' && source[index + 1] === '[') {
                const begin = index, bracket = char === '!' ? index + 1 : index;
                const end = closing(source, ']', bracket + 1);
                if (end < 0 || end + 1 >= cut) { cut = begin; break; }
                if (source[end + 1] === '(') {
                    let depth = 1, finish = end + 2;
                    for (; finish < cut && depth; finish++) {
                        if (escaped(source, finish)) continue;
                        if (source[finish] === '(') depth++;
                        if (source[finish] === ')') depth--;
                    }
                    if (depth) { cut = begin; break; }
                    index = finish; continue;
                }
                index = end + 1; continue;
            }
            const emphasis = /^(\*{1,3}|_{1,3}|~~)/.exec(source.slice(index));
            if (emphasis) {
                const token = emphasis[0], before = source[index - 1] || '', after = source[index + token.length] || '';
                const top = stack[stack.length - 1];
                if (token[0] === '_' && /[\p{L}\p{N}]/u.test(before) && /[\p{L}\p{N}]/u.test(after)) {
                    index += token.length; continue;
                }
                if (top?.token === token && before && !/\s/.test(before)) stack.pop();
                else if (after && !/\s/.test(after)) stack.push({ token, index });
                else if (!after && !top) { cut = index; break; }
                index += token.length; continue;
            }
            index++;
        }
        if (stack.length) cut = Math.min(cut, stack[0].index);
        const lineStart = source.lastIndexOf('\n', cut - 1) + 1;
        if (/^ {0,3}(?:#{1,6}|>|[-+*]|\d+[.)])[ \t]*$/.test(source.slice(lineStart, cut))) cut = lineStart;
        return { text:source.slice(0, cut), spans:spans.filter(span => span[1] <= cut) };
    }

    function splitPreview(source) {
        const safe = safeSource(source.replace(/\r\n?/g, '\n'));
        let tokens;
        try { tokens = root.marked?.lexer?.(safe.text); } catch (_) {}
        if (!Array.isArray(tokens) || !tokens.length) return { stable:'', tail:safe.text };
        const stableTokens = tokens.slice(0, -1);
        let length = stableTokens.reduce((sum, token) => sum + (token.raw || '').length, 0);
        if (!safe.text.startsWith(stableTokens.map(token => token.raw || '').join(''))) length = 0;
        for (const [begin, end] of safe.spans) {
            if (begin < length && end > length) {
                let offset = 0;
                for (const token of stableTokens) {
                    const next = offset + (token.raw || '').length;
                    if (next > begin) { length = offset; break; }
                    offset = next;
                }
            }
        }
        let tail = safe.text.slice(length);
        const tailMask = tail.split('');
        for (const [begin,end] of safe.spans) {
            for (let index = Math.max(begin, length); index < end; index++) tailMask[index - length] = ' ';
        }
        if (tokens[tokens.length - 1]?.type === 'table' || tailMask.join('').includes('|')) tail = '';
        return { stable:safe.text.slice(0, length), tail };
    }

    function createPreview(options = {}) {
        let chat = options.chat;
        const doc = chat?.ownerDocument || root.document;
        let element = null, content = null, stable = null, tail = null;
        let source = '', sourceBytes = 0, committed = '', renderedKey = '';
        let timer = 0, running = false, dirty = false, disposed = false, finalizing = false, operation = 0;
        let chain = Promise.resolve();
        const current = () => !disposed && (!options.isCurrent || options.isCurrent());
        const visible = () => current() && (!options.canRender || options.canRender());
        const notify = () => { if (visible()) options.onRender?.(element); };
        const ensureElement = () => {
            if (!visible() || !chat) return false;
            if (!element) {
                element = doc.createElement('div'); element.className = 'msg ai tex2jax_ignore chat-stream-preview';
                element.setAttribute('aria-busy', 'true');
                const wrapper = doc.createElement('div'); wrapper.className = 'msg-content';
                content = doc.createElement('div'); content.className = 'ai-content';
                stable = doc.createElement('div'); stable.style.display = 'contents';
                tail = doc.createElement('div'); tail.style.display = 'contents';
                content.append(stable, tail); wrapper.append(content); element.append(wrapper);
            }
            if (element.parentElement !== chat) chat.appendChild(element);
            return true;
        };
        const stageContent = async (blocks, token) => {
            const stage = doc.createElement('div'); stage.className = 'msg ai reply-render-stage';
            stage.setAttribute('aria-hidden', 'true');
            stage.style.width = `${element.getBoundingClientRect().width}px`;
            stage.style.setProperty('max-width', 'none', 'important');
            const roots = blocks.map(text => {
                const node = doc.createElement('div'); node.className = 'ai-content';
                node.innerHTML = options.format(text); stage.appendChild(node); return node;
            });
            (chat.parentElement || doc.body).appendChild(stage);
            try {
                await options.typeset?.(stage);
                if (!visible() || token !== operation) return null;
                roots.forEach(node => node.remove());
                return roots;
            } finally {
                try { root.MathJax?.typesetClear?.([stage]); } catch (_) {}
                stage.remove();
            }
        };
        const schedule = () => {
            dirty = true;
            if (timer || running || finalizing || !visible()) return;
            timer = root.setTimeout(() => { timer = 0; void flush(); }, 120);
        };
        const flush = async () => {
            if (running || finalizing || !visible()) return;
            dirty = false;
            const split = splitPreview(source);
            if (!split.stable.startsWith(committed)) return;
            const fresh = split.stable.slice(committed.length);
            const key = split.stable + '\0' + split.tail;
            if (key === renderedKey || !(fresh + split.tail).trim() || !ensureElement()) return;
            running = true;
            const token = operation;
            chain = chain.catch(() => {}).then(async () => {
                const nodes = await stageContent([fresh, split.tail], token);
                if (!nodes || !visible() || finalizing) return;
                if (fresh) {
                    while (nodes[0].firstChild) stable.appendChild(nodes[0].firstChild);
                    committed = split.stable;
                }
                try { root.MathJax?.typesetClear?.([tail]); } catch (_) {}
                tail.replaceChildren(...nodes[1].childNodes);
                renderedKey = key;
                notify();
            }).catch(error => {
                if (current()) root.console?.warn?.('流式片段排版暂未完成：', error);
            }).finally(() => { running = false; if (dirty) schedule(); });
            await chain;
        };
        return {
            get element() { return element; },
            append(text) {
                if (!current() || finalizing || typeof text !== 'string' || !text) return;
                sourceBytes += encoder.encode(text).byteLength;
                if (sourceBytes > SOURCE_LIMIT) throw failure({ error:'回答内容过长，请拆分问题后重试', code:'stream_source_too_large' });
                source += text; schedule();
            },
            attach(nextChat) {
                if (nextChat) chat = nextChat;
                if (element && visible() && element.parentElement !== chat) chat.appendChild(element);
                if (source) schedule();
            },
            async finish(finalText) {
                if (!current()) return null;
                checkSize(String(finalText || ''));
                finalizing = true; operation++;
                if (timer) root.clearTimeout(timer);
                timer = 0; dirty = false;
                await chain;
                if (!ensureElement()) return null;
                const nodes = await stageContent([String(finalText || '')], operation);
                if (!nodes || !visible()) return null;
                try { root.MathJax?.typesetClear?.([content]); } catch (_) {}
                content.replaceWith(nodes[0]); content = nodes[0];
                element.setAttribute('aria-busy', 'false'); notify();
                return content;
            },
            dispose() {
                disposed = true; operation++;
                if (timer) root.clearTimeout(timer);
                timer = 0; source = ''; committed = ''; renderedKey = '';
                try { if (element) root.MathJax?.typesetClear?.([element]); } catch (_) {}
                element?.remove();
            }
        };
    }
    root.DMateChatStream = Object.freeze({ read, createPreview });
})(typeof window !== 'undefined' ? window : globalThis);
