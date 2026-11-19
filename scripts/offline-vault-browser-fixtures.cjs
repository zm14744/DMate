'use strict';

// Capture the real workspace handle only inside test documents. Production
// pages do not expose a testing API or persist the decrypted probe data.
async function installStorageProbe(target) {
  await target.addInitScript(() => {
    let published;
    Object.defineProperty(window, 'DMateOfflineStorage', {
      configurable: true,
      get: () => published,
      set(api) {
        published = {...api, async open(options) {
          try {
            const original = await api.open(options);
            const handle = {};
            for (const key of Object.keys(original)) {
              const member = original[key];
              handle[key] = typeof member === 'function' ? member.bind(original) : member;
            }
            if (typeof original.put === 'function') handle.put = async (store, row) => {
              if (window.__failOfflineAppearanceSave && store === 'settings' && row.id === 'appearance') {
                throw new DOMException('Appearance write blocked for regression test', 'QuotaExceededError');
              }
              const result = await original.put(store, row);
              if (window.__holdNextOfflineNoteSave && store === 'notes') {
                window.__holdNextOfflineNoteSave = false;
                await new Promise(resolve => { window.__releaseOfflineNoteSave = resolve; });
              }
              return result;
            };
            window.__offlineTestStore = handle;
            return handle;
          } catch (error) {
            window.__offlineTestOpenError = {code:error?.code, message:error?.message};
            throw error;
          }
        }};
      }
    });
  });
}

async function records(page, collection) {
  return page.evaluate(collection => __offlineTestStore.all(collection), collection);
}

async function row(page, collection, id) {
  return page.evaluate(({collection,id}) => __offlineTestStore.get(collection,id), {collection,id});
}

// Automatic entry has no eye button. Wait for it, then use the real eye button
// only when a test has explicitly hidden the workspace.
async function revealInterface(page) {
  await page.waitForFunction(() => document.documentElement.dataset.offlineReady === 'true');
  await page.waitForFunction(() => {
    const cover = document.getElementById('offlinePrivacyCover');
    const eye = document.getElementById('offlinePrivacyRestore');
    return !cover.open || (eye.getClientRects().length && getComputedStyle(eye).visibility === 'visible');
  });
  if (await page.locator('#offlinePrivacyCover').evaluate(node => node.open)) {
    await page.locator('#offlinePrivacyRestore').click();
    await page.waitForFunction(() => !document.getElementById('offlinePrivacyCover').open);
  }
}

module.exports = {installStorageProbe, records, row, revealInterface};
