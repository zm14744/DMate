(function (root) {
    'use strict';
    const SAMPLE_RATE = 16000;
    const MAX_SECONDS = 60;
    const LEADING_PAD_SAMPLES = Math.round(SAMPLE_RATE * .15);
    const TRAILING_PAD_SAMPLES = Math.round(SAMPLE_RATE * .25);
    const TAIL_CAPTURE_MS = 350;
    const ICON = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/></svg>';

    function wavBlob(chunks, count) {
        const buffer = new ArrayBuffer(44 + count * 2), view = new DataView(buffer);
        const word = (offset, text) => { for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i)); };
        word(0, 'RIFF'); view.setUint32(4, 36 + count * 2, true); word(8, 'WAVE'); word(12, 'fmt ');
        view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
        view.setUint32(24, SAMPLE_RATE, true); view.setUint32(28, SAMPLE_RATE * 2, true);
        view.setUint16(32, 2, true); view.setUint16(34, 16, true); word(36, 'data'); view.setUint32(40, count * 2, true);
        let offset = 44;
        for (const chunk of chunks) for (const sample of chunk) { view.setInt16(offset, sample, true); offset += 2; }
        return new Blob([buffer], { type: 'audio/wav' });
    }

    // Keep one source sample between callbacks, so fractional sample-rate
    // conversion never restarts its phase at a browser audio-block boundary.
    function pcmSampler(sourceRate) {
        const step = sourceRate / SAMPLE_RATE;
        let samples = 0, emitted = 0, previous = null, ended = false;
        const pcm = sample => Math.round(Math.max(-1, Math.min(1, sample)) * (sample < 0 ? 32768 : 32767));
        const sample = function (input) {
            if (ended || !input.length) return new Int16Array(0);
            const begin = samples, end = begin + input.length - 1;
            const at = index => index < begin ? previous : input[index - begin];
            const output = [];
            // Use the global output index rather than restarting or rounding
            // phase in each browser callback. The first real sample is kept.
            while (emitted * step < end) {
                const position = emitted * step;
                const index = Math.floor(position), fraction = position - index;
                output.push(pcm(at(index) * (1 - fraction) + at(index + 1) * fraction));
                emitted++;
            }
            samples += input.length; previous = input[input.length - 1];
            return Int16Array.from(output);
        };
        sample.flush = () => {
            if (ended || previous === null) return new Int16Array(0);
            ended = true;
            const output = [];
            // Final fractional positions need no future microphone block.
            // Hold the last available sample, matching finite-signal padding.
            while (emitted * step < samples) { output.push(pcm(previous)); emitted++; }
            previous = null;
            return Int16Array.from(output);
        };
        return sample;
    }

    function mount(options) {
        const button = options.button, input = options.input, status = options.status;
        if (!button || !input) throw new Error('Voice input needs its microphone button and text field.');
        const document = button.ownerDocument;
        const win = document.defaultView || root;
        const media = options.mediaDevices || win.navigator.mediaDevices;
        const Audio = options.AudioContext || win.AudioContext || win.webkitAudioContext;
        const fetcher = options.fetch || win.fetch.bind(win);
        const seconds = Math.max(1, Math.min(MAX_SECONDS, Number(options.maxSeconds) || MAX_SECONDS));
        // Padding is part of the service's 60-second file limit, not extra
        // hidden duration. All captured samples, including stop grace, fit.
        const captureLimit = Math.floor(SAMPLE_RATE * seconds) - LEADING_PAD_SAMPLES - TRAILING_PAD_SAMPLES;
        let state = 'idle', serial = 0, active = null, disposed = false;
        const contextKey = () => options.getContextKey ? options.getContextKey() : '';
        const busy = () => input.disabled || input.readOnly || Boolean(options.isBusy?.());
        const current = op => !disposed && active === op && op.serial === serial && op.contextKey === contextKey();

        button.type = 'button'; button.classList.add('voice-input-button'); button.innerHTML = ICON;
        if (status) { status.classList.add('voice-input-status'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite'); }
        function notice(message) {
            if (!status) return;
            status.classList.remove('voice-input-error');
            status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
            status.replaceChildren(document.createTextNode(message)); status.hidden = !message;
        }
        function reportError(message) {
            notice(message);
            // Routine progress stays in the accessible live region only. The
            // host may use its existing error UI rather than add a second one
            // beneath the composer; standalone callers retain one error line.
            if (typeof options.onError === 'function') {
                try { options.onError(message); return; } catch (_) { /* Fall back to the local error line. */ }
            }
            if (status) {
                status.classList.add('voice-input-error');
                status.setAttribute('role', 'alert'); status.setAttribute('aria-live', 'assertive');
            }
        }
        function render(next) {
            const changed = state !== next;
            state = next; button.dataset.voiceState = state;
            button.setAttribute('aria-pressed', String(state === 'recording' || state === 'finishing'));
            button.setAttribute('aria-busy', String(['requesting', 'preparing', 'finishing', 'transcribing'].includes(state)));
            const label = state === 'recording' ? '结束录音并识别' : state === 'finishing' ? '正在收录尾音' : state === 'preparing' ? '正在启动麦克风' : state === 'transcribing' ? '正在识别语音' : state === 'requesting' ? '正在请求麦克风权限' : '语音输入';
            button.title = label; button.setAttribute('aria-label', label);
            button.disabled = ['requesting', 'preparing', 'finishing', 'transcribing'].includes(state) || state === 'idle' && busy();
            if (changed) options.onStateChange?.(state);
        }
        function releaseCapture(op) {
            if (!op) return;
            clearTimeout(op.timer); clearTimeout(op.readyTimer); clearTimeout(op.finishTimer); clearInterval(op.contextTimer);
            if (op.captureReleased) return;
            if (op.stream) op.captureReleased = true;
            if (op.processor) op.processor.onaudioprocess = null;
            for (const node of [op.source, op.processor, op.mute]) { try { node?.disconnect(); } catch (_) { /* Already disconnected. */ } }
            for (const track of op.stream?.getTracks() || []) track.stop();
            if (op.audio && op.audio.state !== 'closed') Promise.resolve(op.audio.close()).catch(() => {});
        }
        function cancel(message = '', error = false) {
            serial++;
            const op = active; active = null;
            op?.controller?.abort(); releaseCapture(op);
            if (op) { op.chunks = []; op.count = 0; }
            if (!disposed) { render('idle'); if (error) reportError(message); else notice(message); }
        }
        function appendPcm(op, pcm) {
            const remaining = captureLimit - op.count;
            if (pcm.length > remaining) pcm = pcm.subarray(0, remaining);
            if (pcm.length) { op.chunks.push(pcm); op.count += pcm.length; }
        }
        function finish() {
            const op = active;
            if (!op || state !== 'recording') return;
            clearTimeout(op.timer);
            render('finishing'); notice('正在收录尾音，请稍候…');
            // ScriptProcessor delivers blocks after they were recorded. Keep
            // capturing briefly after Stop so its pending tail is delivered.
            if (op.count >= captureLimit) void transcribe(op);
            else op.finishTimer = setTimeout(() => void transcribe(op), TAIL_CAPTURE_MS);
        }
        async function transcribe(op) {
            if (!current(op) || op.transcribing) return;
            op.transcribing = true;
            appendPcm(op, op.sample?.flush() || new Int16Array(0));
            releaseCapture(op);
            if (!current(op) || busy()) { cancel('输入位置已改变，语音输入已取消。'); return; }
            if (op.count < SAMPLE_RATE * .25) { cancel(); return; }
            render('transcribing'); notice('正在识别语音…');
            op.controller = new AbortController();
            op.contextTimer = setInterval(() => { if (!current(op) || busy()) cancel('会话或输入状态已改变，语音输入已取消。'); }, 250);
            const timeout = setTimeout(() => op.controller.abort(), 75000);
            try {
                const chunks = [new Int16Array(LEADING_PAD_SAMPLES), ...op.chunks, new Int16Array(TRAILING_PAD_SAMPLES)];
                const total = LEADING_PAD_SAMPLES + op.count + TRAILING_PAD_SAMPLES;
                const body = new FormData(); body.append('audio', wavBlob(chunks, total), 'voice.wav');
                op.chunks = [];
                const response = await fetcher(options.endpoint || '/voice/transcribe', {
                    method: 'POST', body, signal: op.controller.signal, credentials: 'same-origin'
                });
                let result;
                try { result = await response.json(); } catch (_) { throw new Error('语音识别响应异常，请重试。'); }
                if (!current(op)) { if (active === op) cancel('会话已切换，语音输入已取消。'); return; }
                if (!response.ok || result?.ok !== true) {
                    const message = typeof result?.error === 'string' ? result.error : result?.error?.message;
                    throw new Error(typeof message === 'string' ? message.slice(0, 500) : '语音识别失败，请重试。');
                }
                if (typeof result.text !== 'string' || result.text.length > 24000) throw new Error('语音识别响应异常，请重试。');
                const text = result.text.trim();
                if (!text) { cancel(); return; }
                if (busy()) { cancel('输入位置已改变，识别内容未写入。'); return; }
                const at = Math.max(0, Math.min(input.value.length, input.selectionStart ?? input.value.length));
                const before = input.value.slice(0, at), after = input.value.slice(at);
                const prefix = /[A-Za-z0-9]$/.test(before) && /^[A-Za-z0-9]/.test(text) ? ' ' : '';
                const suffix = /[A-Za-z0-9]$/.test(text) && /^[A-Za-z0-9]/.test(after) ? ' ' : '';
                // Dictation inserts; it never removes the user's current text.
                input.setRangeText(prefix + text + suffix, at, at, 'end');
                input.dispatchEvent(new win.Event('input', { bubbles: true }));
                input.focus({ preventScroll: true }); options.onText?.(text);
                active = null; render('idle'); notice('语音已转为文字，可修改后发送。');
            } catch (error) {
                if (!current(op)) { if (active === op) cancel('会话已切换，语音输入已取消。'); return; }
                // An attempt without a transcript simply ends dictation. Keep
                // service failures in the HTTP result; do not turn them into
                // chat messages, success text, or changes to the typed draft.
                cancel();
            } finally { clearTimeout(timeout); clearInterval(op.contextTimer); op.chunks = []; }
        }
        async function start() {
            if (state !== 'idle' || disposed) return;
            if (busy()) { notice('请等待当前操作完成后再使用语音输入。'); return; }
            if (!media?.getUserMedia || !Audio || win.isSecureContext === false) { reportError('当前环境无法使用麦克风，请在 HTTPS 页面或支持录音的浏览器中打开。'); return; }
            const op = { serial: ++serial, contextKey: contextKey(), chunks: [], count: 0 };
            active = op; render('requesting'); notice('正在请求麦克风权限…');
            try {
                const stream = await media.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }, video: false });
                op.stream = stream;
                if (!current(op) || busy()) { releaseCapture(op); if (active === op) cancel('输入位置已改变，语音输入已取消。'); return; }
                // Use the device/browser rate; resample explicitly below.
                // Some Safari/Firefox devices reject a 16kHz capture context.
                op.audio = new Audio();
                op.source = op.audio.createMediaStreamSource(stream);
                op.processor = op.audio.createScriptProcessor(1024, 1, 1);
                op.mute = op.audio.createGain(); op.mute.gain.value = 0;
                op.sample = pcmSampler(op.audio.sampleRate);
                op.processor.onaudioprocess = event => {
                    if (!current(op) || busy()) { cancel('会话或输入状态已改变，语音输入已取消。'); return; }
                    const input = event.inputBuffer.getChannelData(0);
                    if (!input.length) return;
                    appendPcm(op, op.sample(input));
                    if (!op.started) {
                        op.started = true; clearTimeout(op.readyTimer);
                        render('recording'); notice(`已开始录音，请说话；再点麦克风结束（单段最长 ${seconds} 秒）。`);
                        op.timer = setTimeout(finish, Math.max(0, (captureLimit - op.count) / SAMPLE_RATE * 1000 - TAIL_CAPTURE_MS));
                    }
                    if (op.count >= captureLimit) {
                        if (state === 'finishing') void transcribe(op);
                        else finish();
                    }
                };
                render('preparing'); notice('麦克风正在准备。');
                op.source.connect(op.processor); op.processor.connect(op.mute); op.mute.connect(op.audio.destination);
                op.contextTimer = setInterval(() => { if (!current(op) || busy()) cancel('会话或输入状态已改变，语音输入已取消。'); }, 250);
                op.readyTimer = setTimeout(() => { if (current(op) && !op.started) cancel('麦克风尚未开始采集，请检查设备后重试。', true); }, 10000);
                await op.audio.resume();
                if (!current(op) || busy()) { releaseCapture(op); if (active === op) cancel('输入位置已改变，语音输入已取消。'); return; }
            } catch (error) {
                releaseCapture(op);
                if (!current(op)) { if (active === op) cancel('会话已切换，语音输入已取消。'); return; }
                active = null; render('idle');
                reportError(['NotAllowedError', 'SecurityError'].includes(error?.name) ? '麦克风权限被拒绝，请在浏览器设置中允许麦克风后重试。'
                    : ['NotFoundError', 'DevicesNotFoundError'].includes(error?.name) ? '未找到可用的麦克风。' : '无法启动录音，请检查麦克风或重试。');
            }
        }
        const click = () => { if (state === 'recording') void finish(); else if (state === 'idle') void start(); };
        const escape = event => { if (event.key === 'Escape' && active) { event.preventDefault(); cancel(); } };
        const hidden = () => { if (document.hidden && active) cancel('页面已切换到后台，语音输入已取消。'); };
        const pagehide = () => { if (active) cancel('页面已关闭，语音输入已取消。'); };
        button.addEventListener('click', click); document.addEventListener('keydown', escape);
        document.addEventListener('visibilitychange', hidden); win.addEventListener('pagehide', pagehide);
        const observer = new win.MutationObserver(() => { if (active && busy()) cancel('输入状态已改变，语音输入已取消。'); else if (state === 'idle') render('idle'); });
        observer.observe(input, { attributes: true, attributeFilter: ['disabled', 'readonly'] });
        render('idle'); notice('');
        return {
            cancel, get state() { return state; }, refresh() { if (state === 'idle') render('idle'); else if (active && busy()) cancel('输入状态已改变，语音输入已取消。'); },
            dispose() {
                if (disposed) return; cancel(''); disposed = true; observer.disconnect();
                button.removeEventListener('click', click); document.removeEventListener('keydown', escape);
                document.removeEventListener('visibilitychange', hidden); win.removeEventListener('pagehide', pagehide);
            }
        };
    }
    root.DMateVoiceInput = { mount };
    if (typeof module !== 'undefined' && module.exports) module.exports = { mount, pcmSampler, wavBlob };
})(typeof window !== 'undefined' ? window : globalThis);
