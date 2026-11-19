/* The online sidebar exports the same portable ZIP that offline mode imports. */
(() => {
  'use strict';
  const button = document.getElementById('exportDataBtn');
  if (!button) return;
  const tr = (value,english) => window.DMateI18n?.t?.(value,english) ?? value;
  const text = value => typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value);
  let exporting = false;
  button.addEventListener('click',() => { void exportData(); });
  async function exportData() {
    if (exporting) return;
    exporting = true;
    button.disabled = true;
    button.setAttribute('aria-busy','true');
    try {
      const bridge = window.DMateOfflineBridge, backup = window.DMateOfflineBackup;
      if (!bridge?.snapshot || !bridge.context || !bridge.isCurrent || !backup?.create || !window.DMateBackupDownload?.save)
        throw new Error(tr('备份组件尚未加载，请刷新后重试','Reload to load the backup component'));
      const context = bridge.context();
      const requireCurrent = () => {
        if (!bridge.isCurrent(context)) throw new Error(tr('账号状态已变化，导出已取消','The account changed; export was cancelled'));
      };
      const snapshot = await bridge.snapshot();
      requireCurrent();
      const notes = Array.isArray(snapshot.notes) ? snapshot.notes : [];
      const mistakes = (Array.isArray(snapshot.wrongQuestions) ? snapshot.wrongQuestions : []).map(item => {
        const reference = item.referenceAnswer;
        const answer = item.answer || (reference && typeof reference === 'object'
          ? reference.text || reference.answer || reference : reference);
        return {...item,statement:text(item.statement || item.question),
          answer:text(answer),explanation:text(item.explanation || item.analysis || item.solution),
          title:text(item.title || item.category || item.question),status:item.corrected ? 'resolved' : item.status || 'pending'};
      });
      const drawings = typeof snapshot.drawings === 'string' ? JSON.parse(snapshot.drawings)
        : Array.isArray(snapshot.drawings) ? {version:2,activeId:snapshot.drawings[0]?.id || '',pages:snapshot.drawings}
          : snapshot.drawings || null;
      const blob = await backup.create({notes,mistakes,drawings});
      requireCurrent();
      const name = 'DMate-'+new Date().toISOString().replace(/[:.]/g,'-')+'.zip';
      if (await window.DMateBackupDownload.save(blob,name) === false) return;
      window.showCopyToast?.(tr('已导出 ZIP 备份','ZIP backup exported'));
    } catch (error) {
      window.showCopyToast?.(error?.message || tr('导出未完成，请重试','Export failed; please retry'));
    } finally {
      exporting = false;
      button.disabled = false;
      button.removeAttribute('aria-busy');
    }
  }
})();
