/* ZIP downloads use the system file picker in Android's WebView. */
(() => {
  'use strict';
  const tr = (source,english) => window.DMateI18n?.t?.(source,english) ?? source;
  async function save(blob,name) {
    const bridge = window.DMateFileSave;
    if (!bridge?.postMessage) {
      if (window.DMateGallery?.postMessage || /DMateAndroid\//i.test(navigator.userAgent))
        throw new Error(tr("请更新客户端和系统 WebView 后再导出 ZIP 备份", "Update the client and system WebView to export ZIP backups"));
      const url = URL.createObjectURL(blob), link = document.createElement('a');
      link.href = url; link.download = name; link.hidden = true;
      document.body.append(link);
      try { link.click(); } finally { link.remove(); setTimeout(() => URL.revokeObjectURL(url),60000); }
      return true;
    }
    return new Promise((resolve,reject) => {
      const id = 'backup-'+crypto.randomUUID();
      const previous = bridge.onmessage, events = typeof bridge.addEventListener === 'function';
      let finished = false;
      const finish = (error,saved) => {
        if (finished) return;
        finished = true; clearTimeout(timer);
        if (events) bridge.removeEventListener('message',listener);
        else if (bridge.onmessage === listener) bridge.onmessage = previous;
        if (error) reject(error); else resolve(saved);
      };
      const listener = event => {
        let response;
        try { response = JSON.parse(event.data); } catch (_) {}
        if (response?.type === 'dmate:file-save' && response.id === id) {
          if (response.cancelled) finish(null,false);
          else if (response.ok) finish(null,true);
          else finish(new Error(response.message || tr('ZIP 备份未能保存，请重试','The ZIP backup could not be saved; retry')));
        }
        if (!events && typeof previous === 'function') previous.call(bridge,event);
      };
      const timer = setTimeout(() => finish(new Error(tr('保存备份超时，请重试','Saving the backup timed out; retry'))),10*60*1000);
      if (events) bridge.addEventListener('message',listener); else bridge.onmessage = listener;
      const reader = new FileReader();
      reader.onerror = () => finish(new Error(tr('无法读取备份文件','The backup file could not be read')));
      reader.onload = () => {
        if (finished) return;
        const data = String(reader.result || '').split(',')[1];
        if (!data) return finish(new Error(tr('备份文件为空','The backup file is empty')));
        try { bridge.postMessage(JSON.stringify({id,name,mime:'application/zip',data})); }
        catch (_) { finish(new Error(tr('备份文件无法发送至客户端','The backup could not be sent to the client'))); }
      };
      try { reader.readAsDataURL(blob); }
      catch (_) { finish(new Error(tr('无法读取备份文件','The backup file could not be read'))); }
    });
  }
  window.DMateBackupDownload = Object.freeze({save});
})();
