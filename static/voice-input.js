(function (root) {
    'use strict';
    const SAMPLE_RATE = 16000;
    const MAX_SECONDS = 60;
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
        let position = 0, previous = null;
        return function (input) {
            const data = new Float32Array(input.length + (previous === null ? 0 : 1));
            let offset = 0;
            if (previous !== null) { data[0] = previous; offset = 1; }
            data.set(input, offset);
            const output = [];
            while (position < data.length - 1) {
                const index = Math.floor(position), fraction = position - index;
                const sample = Math.max(-1, Math.min(1, data[index] * (1 - fraction) + data[index + 1] * fraction));
                output.push(Math.round(sample * (sample < 0 ? 32768 : 32767)));
                position += step;
            }
            position -= Math.max(0, data.length - 1);
            previous = data.length ? data[data.length - 1] : previous;
            return Int16Array.from(output);
        };
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
        let state = 'idle', serial = 0, active = null, disposed = false;
        const contextKey = () => options.getContextKey ? options.getContextKey() : '';
        const busy = () => input.disabled || input.readOnly || Boolean(options.isBusy?.());
        const current = op => !disposed && active === op && op.serial === serial && op.contextKey === contextKey();

        button.type = 'button'; button.classList.add('voice-input-button'); button.innerHTML = ICON;
        if (status) { status.classList.add('voice-input-status'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite'); }
        function notice(message, cancellable = false) {
            if (!status) return;
            status.replaceChildren(document.createTextNode(message)); status.hidden = !message;
            if (cancellable) {
                const cancelButton = document.createElement('button'); cancelButton.type = 'button'; cancelButton.textContent = '取消';
                cancelButton.className = 'voice-input-cancel'; cancelButton.addEventListener('click', () => cancel()); status.append(cancelButton);
            }
        }
        function render(next) {
            const changed = state !== next;
            state = next; button.dataset.voiceState = state;
            button.setAttribute('aria-pressed', String(state === 'recording'));
            button.setAttribute('aria-busy', String(state === 'requesting' || state === 'transcribing'));
            const label = state === 'recording' ? '结束录音并识别' : state === 'transcribing' ? '正在识别语音' : state === 'requesting' ? '正在请求麦克风权限' : '语音输入';
            button.title = label; button.setAttribute('aria-label', label);
            button.disabled = state === 'requesting' || state === 'transcribing' || state === 'idle' && busy();
            if (changed) options.onStateChange?.(state);
        }
        function releaseCapture(op) {
            if (!op) return;
            clearTimeout(op.timer); clearInterval(op.contextTimer);
            if (op.captureReleased) return;
            if (op.stream) op.captureReleased = true;
            if (op.processor) op.processor.onaudioprocess = null;
            for (const node of [op.source, op.processor, op.mute]) { try { node?.disconnect(); } catch (_) { /* Already disconnected. */ } }
            for (const track of op.stream?.getTracks() || []) track.stop();
            if (op.audio && op.audio.state !== 'closed') Promise.resolve(op.audio.close()).catch(() => {});
        }
        function cancel(message = '已取消语音输入。') {
            serial++;
            const op = active; active = null;
            op?.controller?.abort(); releaseCapture(op);
            if (op) { op.chunks = []; op.count = 0; }
            if (!disposed) { render('idle'); notice(message); }
        }
        async function finish() {
            const op = active;
            if (!op || state !== 'recording') return;
            releaseCapture(op);
            if (!current(op) || busy()) { cancel('输入位置已改变，语音输入已取消。'); return; }
            if (op.count < SAMPLE_RATE * .25) { cancel('录音时间太短，请重新录音。'); return; }
            render('transcribing'); notice('正在识别语音…', true);
            op.controller = new AbortController();
            op.contextTimer = setInterval(() => { if (!current(op) || busy()) cancel('会话或输入状态已改变，语音输入已取消。'); }, 250);
            const timeout = setTimeout(() => op.controller.abort(), 75000);
            try {
                const body = new FormData(); body.append('audio', wavBlob(op.chunks, op.count), 'voice.wav');
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
                if (!text) throw new Error('未识别到语音，请重试。');
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
                active = null; render('idle');
                notice(error?.name === 'AbortError' ? '语音识别超时，请重试。' : error?.message || '语音识别网络异常，请重试。');
            } finally { clearTimeout(timeout); clearInterval(op.contextTimer); op.chunks = []; }
        }
        async function start() {
            if (state !== 'idle' || disposed) return;
            if (busy()) { notice('请等待当前操作完成后再使用语音输入。'); return; }
            if (!media?.getUserMedia || !Audio || win.isSecureContext === false) { notice('当前环境无法使用麦克风，请在 HTTPS 页面或支持录音的浏览器中打开。'); return; }
            const op = { serial: ++serial, contextKey: contextKey(), chunks: [], count: 0 };
            active = op; render('requesting'); notice('正在请求麦克风权限…', true);
            try {
                const stream = await media.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }, video: false });
                op.stream = stream;
                if (!current(op) || busy()) { releaseCapture(op); if (active === op) cancel('输入位置已改变，语音输入已取消。'); return; }
                // Use the device/browser rate; resample explicitly below.
                // Some Safari/Firefox devices reject a 16kHz capture context.
                op.audio = new Audio();
                await op.audio.resume();
                if (!current(op) || busy()) { releaseCapture(op); if (active === op) cancel('输入位置已改变，语音输入已取消。'); return; }
                op.source = op.audio.createMediaStreamSource(stream);
                op.processor = op.audio.createScriptProcessor(4096, 1, 1);
                op.mute = op.audio.createGain(); op.mute.gain.value = 0;
                const sample = pcmSampler(op.audio.sampleRate);
                op.processor.onaudioprocess = event => {
                    if (!current(op) || busy()) { cancel('会话或输入状态已改变，语音输入已取消。'); return; }
                    let pcm = sample(event.inputBuffer.getChannelData(0));
                    const remaining = Math.floor(SAMPLE_RATE * seconds) - op.count;
                    if (pcm.length > remaining) pcm = pcm.subarray(0, remaining);
                    if (pcm.length) { op.chunks.push(pcm); op.count += pcm.length; }
                    if (op.count >= SAMPLE_RATE * seconds) void finish();
                };
                op.source.connect(op.processor); op.processor.connect(op.mute); op.mute.connect(op.audio.destination);
                render('recording'); notice(`正在录音，再点麦克风结束（最多 ${seconds} 秒）。`, true);
                op.timer = setTimeout(() => void finish(), seconds * 1000);
                op.contextTimer = setInterval(() => { if (!current(op) || busy()) cancel('会话或输入状态已改变，语音输入已取消。'); }, 250);
            } catch (error) {
                releaseCapture(op);
                if (!current(op)) { if (active === op) cancel('会话已切换，语音输入已取消。'); return; }
                active = null; render('idle');
                notice(['NotAllowedError', 'SecurityError'].includes(error?.name) ? '麦克风权限被拒绝，请在浏览器设置中允许麦克风后重试。'
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
})(typeof window !== 'undefined' ? window : globalThis);
