/* Prioritize one existing encrypted appearance record; never run migrations. */
(() => {
  'use strict';
  const bootstrap = window.DMateAppearanceBootstrap;
  if (!bootstrap || bootstrap.scope !== 'offline' || !window.DMateOfflineVault) return;
  bootstrap.restoreOffline((async () => {
    const exists = await new Promise(resolve => {
      const opening = indexedDB.open('dmate-offline-vault-v1',1);
      opening.onupgradeneeded = () => opening.transaction.abort();
      opening.onerror = () => resolve(false);
      opening.onsuccess = () => {
        const db = opening.result;
        if (!db.objectStoreNames.contains('vaults')) {db.close();resolve(false);return;}
        const tx = db.transaction('vaults'), request = tx.objectStore('vaults').get('device-workspace-v1');
        let found = false;request.onsuccess = () => {found = Boolean(request.result);};
        tx.oncomplete = () => {db.close();resolve(found);};tx.onabort = tx.onerror = () => {db.close();resolve(false);};
      };
    });
    if (!exists) return null;
    const vault = await DMateOfflineVault.open({name:'device-workspace-v1'});
    try {
      const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode('appearance')))]
        .map(byte => byte.toString(16).padStart(2,'0')).join('');
      const saved = await vault.read('settings','r-'+hash);
      return saved?.value?.owner === 'device-local' && saved.value.row?.id === 'appearance' ? saved.value.row : null;
    } finally {vault.close();}
  })());
})();
