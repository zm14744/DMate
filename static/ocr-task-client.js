/* Reattach source-bound uploads without repeating an active recognition. */
(function (root) {
    'use strict';
    const aborted = () => Object.assign(new Error('图片任务已取消'), {name:'AbortError'});
    function check(options) {
        if (options.signal?.aborted || options.isLive && !options.isLive()) throw aborted();
    }
    function pause(milliseconds, options) {
        check(options);
        return new Promise((resolve, reject) => {
            const finish = () => { options.signal?.removeEventListener('abort', cancel); resolve(); };
            const timer = setTimeout(finish, milliseconds);
            const cancel = () => { clearTimeout(timer); reject(aborted()); };
            options.signal?.addEventListener('abort', cancel, {once:true});
        });
    }
    async function read(response) {
        const data = await response.json();
        if (!data || typeof data !== 'object') throw new Error('图片任务响应不完整');
        return data;
    }
    function failure(data, status) {
        return Object.assign(new Error(data?.error || '图片识别未能完成，请稍后重试'), {status});
    }
    async function recognize(options) {
        let recovering = Boolean(options.recover), retries = 0;
        for (;;) {
            check(options);
            let response, data;
            try {
                if (recovering) {
                    const query = new URLSearchParams({request_id:options.id, source_sha256:options.sourceSha256});
                    response = await fetch('/ocr/status?' + query, {credentials:'same-origin',
                        cache:'no-store', signal:options.signal, headers:options.headers});
                } else {
                    const body = new FormData();
                    body.append('image', options.file);
                    body.append('request_id', options.id);
                    body.append('workflow', 'auto_graph');
                    response = await fetch('/ocr', {method:'POST', body, credentials:'same-origin',
                        signal:options.signal, headers:options.headers});
                }
                data = await read(response);
            } catch (error) {
                check(options);
                if (error.name === 'AbortError') throw error;
                recovering = true;
                await pause(Math.min(10000, 1000 * 2 ** Math.min(++retries, 4)), options);
                continue;
            }
            check(options);
            if (response.status === 429 || recovering && response.status >= 500) {
                recovering = true;
                await pause(5000, options);
                continue;
            }
            if (!response.ok) throw failure(data, response.status);
            if (recovering) {
                if (data.request_id !== options.id || data.source_sha256 !== options.sourceSha256)
                    throw new Error('图片恢复结果与原图不匹配');
                if (data.status === 'missing') { recovering = false; continue; }
                if (data.status === 'cancelled') return {cancelled:true};
                if (data.status === 'completed' || data.status === 'failed') {
                    if (!data.result || typeof data.result !== 'object') throw failure(data, data.http_status);
                    if (Number(data.http_status || 200) >= 400) throw failure(data.result, data.http_status);
                    return data.result;
                }
                if (data.status !== 'processing') throw new Error('图片任务状态无法读取');
            } else if (response.status !== 202 && data.status !== 'processing') return data;
            recovering = true;
            retries = 0;
            await pause(Math.max(1000, Math.min(10000, Number(data.retry_after || 2) * 1000)), options);
        }
    }
    async function bindSource(options) {
        check(options);
        const body = new FormData();
        body.append('image', options.file);
        body.append('request_id', options.id);
        body.append('source_sha256', options.sourceSha256);
        const response = await fetch('/graph/source', {method:'POST', body, credentials:'same-origin',
            signal:options.signal, headers:options.headers});
        const data = await read(response);
        check(options);
        if (!response.ok || !data.ok) throw failure(data, response.status);
        if (data.request_id !== options.id || data.source_sha256 !== options.sourceSha256)
            throw new Error('原图恢复结果与图片任务不匹配');
        return data;
    }
    root.DMateOcrTaskClient = Object.freeze({recognize, bindSource});
}(window));
