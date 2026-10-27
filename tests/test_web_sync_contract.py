"""Cheap source regression for old client WebView/Service Worker upgrades."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RemoteWebSyncContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / 'app.py').read_text()
        cls.html = (ROOT / 'templates/index.html').read_text()
        cls.worker = (ROOT / 'static/legacy-worker-retire.js').read_text()
        cls.sync = (ROOT / 'static/web-sync.js').read_text()

    def test_legacy_worker_returns_unregistration_only(self):
        self.assertIn('@app.route("/service-worker.js")', self.app)
        self.assertIn('legacy-worker-retire.js', self.app)
        self.assertIn('self.registration.unregister()', self.worker)
        self.assertIn("caches.delete(key)", self.worker)
        self.assertNotIn("addEventListener('fetch'", self.worker)
        self.assertNotIn("serviceWorker.register(", self.html)

    def test_server_no_cache_and_runtime_asset_urls(self):
        self.assertIn('@app.route("/web-version")', self.app)
        self.assertIn('no_stale_web_application_assets', self.app)
        self.assertIn("'no-store, no-cache, must-revalidate'", self.app)
        self.assertIn('dmate_web_revision=', self.app)
        self.assertIn('window.DMATE_WEB_REVISION = {{ dmate_web_revision | tojson }};', self.html)
        for name in ['script.js', 'graph-editor-model.js', 'graph-editor-format.js',
                     'graph-editor-overlay.js', 'graph-editor.js', 'client-update.js',
                     'web-sync.js']:
            self.assertIn(f'/static/{name}?v={{{{ dmate_web_revision }}}}', self.html)

    def test_only_installed_client_auto_refreshes_when_idle(self):
        self.assertIn('hasUnsavedWork', self.sync)
        self.assertIn('dmate-old-worker-retired', self.sync)
        self.assertIn("root.location.replace", self.sync)
        self.assertIn("DMateAndroid", self.sync)
        self.assertIn("DMateDesktop", self.sync)


if __name__ == '__main__':
    unittest.main()
