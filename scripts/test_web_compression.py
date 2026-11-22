"""Check the representations used for the first navigation and its public assets."""
import gzip
from html.parser import HTMLParser
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


class PageScripts(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.deferred = []
        self.asynchronous = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and "src" in attrs:
            if "defer" in attrs:
                self.deferred.append(attrs["src"])
            if "async" in attrs:
                self.asynchronous.append(attrs["src"])


class WebCompressionTests(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()

    def fetch(self, path, encoding, method="GET", **headers):
        response = self.client.open(path, method=method, buffered=True,
                                    headers={"Accept-Encoding": encoding, **headers})
        self.addCleanup(response.close)
        return response

    def test_navigation_keeps_per_request_identity_and_cache_policy(self):
        for user in ({"username": "account-a"}, {"username": "account-b"}, None):
            with self.subTest(user=user), patch.object(app, "_current_auth_user", return_value=user):
                plain = self.fetch("/", "identity")
                encoded = self.fetch("/", "br, gzip")
                self.assertEqual(gzip.decompress(encoded.data), plain.data)
                owner = user["username"] if user else ""
                self.assertIn(f'data-owner="{owner}"'.encode(), plain.data)
                self.assertIn("no-store", encoded.cache_control)
                self.assertIn("User-Agent", encoded.vary)
                self.assertIn("Accept-Encoding", encoded.vary)
        for path in ("/offline", "/static/offline.html"):
            plain = self.fetch(path, "gzip;q=0")
            encoded = self.fetch(path, "gzip")
            self.assertEqual(gzip.decompress(encoded.data), plain.data)
            self.assertIn("no-store", encoded.cache_control)
            self.assertIn("Accept-Encoding", plain.vary)
        self.assertNotIn("Content-Encoding", self.fetch("/web-version", "gzip").headers)
        self.assertEqual(self.fetch("/", "gzip", method="OPTIONS").data, b"")

    def test_grouped_scripts_preserve_deferred_order_in_every_client(self):
        revision = app._RUNTIME_SOURCE["manifest_sha256"]
        groups = {f"/static/online/{name}.js?v={revision}": sources
                  for name, sources in app._ONLINE_SCRIPT_GROUPS.items()}
        members = {f"/static/{name}" for sources in groups.values() for name in sources}
        for ua in ("Mozilla/5.0", "DMateAndroid/1.0", "DMateDesktop/1.0"):
            with self.subTest(user_agent=ua):
                html = self.fetch("/", "identity", **{"User-Agent": ua}).get_data(as_text=True)
                scripts = PageScripts(html)
                urls = scripts.deferred
                self.assertCountEqual([url for url in urls if url.startswith("/static/online/")], groups)
                paths = [urlsplit(url).path for url in urls]
                self.assertTrue(members.isdisjoint(paths), "Grouped modules would execute twice")
                ordered = ("/static/online/workspace.js", "/static/script.js",
                           "/static/online/controls.js", "/static/web-sync.js",
                           "/static/offline-handoff.js")
                self.assertEqual([path for path in paths if path in ordered], list(ordered))
                self.assertEqual("/static/client-update.js" in paths, ua.startswith("DMate"))
                entry = f"/static/offline-entry.js?v={revision}"
                self.assertEqual(scripts.asynchronous.count(entry), 1)
                self.assertNotIn("/static/offline-entry.js", paths)
                entry_position = html.index(f'src="{entry}"')
                self.assertLess(html.index('id="offlineWorkspaceBtn"'), entry_position)
                self.assertLess(entry_position, html.index('src="/static/online/workspace.js?'))

    def test_groups_contain_original_sources_and_offline_keeps_individual_urls(self):
        folder = Path(app.app.static_folder)
        offline = PageScripts(self.fetch("/offline", "identity").get_data(as_text=True)).deferred
        self.assertFalse(any(url.startswith("/static/online/") for url in offline))
        members = set()
        for name, sources in app._ONLINE_SCRIPT_GROUPS.items():
            path = f"/static/online/{name}.js"
            with self.subTest(group=name):
                response = self.fetch(path, "identity")
                original = b"\n;\n".join((folder / source).read_bytes() for source in sources)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, original)
                self.assertIn("javascript", response.mimetype)
                members.update(f"/static/{source}" for source in sources)
        shared = [url for url in offline if urlsplit(url).path in members]
        self.assertIn("/static/graph-editor-overlay.js", [urlsplit(url).path for url in shared])
        for url in shared:
            with self.subTest(offline=url):
                self.assertEqual(self.fetch(url, "identity").data,
                                 (folder / Path(urlsplit(url).path).name).read_bytes())
        self.assertEqual(self.fetch("/static/online/script.js", "gzip").status_code, 404)

    def test_static_cache_validators_and_ranges(self):
        revision = app._RUNTIME_SOURCE["manifest_sha256"]
        for name in ("script.js", "chat-composer.css", "online/workspace.js", "online/controls.js"):
            path = f"/static/{name}?v={revision}"
            plain = self.fetch(path, "identity;q=1, gzip;q=0.5")
            encoded = self.fetch(path, "gzip")
            self.assertEqual(encoded.headers["Content-Encoding"], "gzip")
            self.assertEqual(gzip.decompress(encoded.data), plain.data)
            self.assertLess(len(encoded.data), len(plain.data))
            self.assertIn("immutable", encoded.cache_control)
            self.assertIn("Accept-Encoding", plain.vary)
            head = self.fetch(path, "gzip", method="HEAD")
            self.assertEqual(head.data, b"")
            self.assertEqual(head.content_length, len(encoded.data))
            etag = encoded.headers["ETag"]
            self.assertNotEqual(etag, plain.headers["ETag"])
            self.assertEqual(self.fetch(path, "gzip", **{"If-None-Match": etag}).status_code, 304)
            self.assertEqual(self.fetch(path, "identity", **{"If-None-Match": etag}).status_code, 200)
            partial = self.fetch(path, "gzip", Range="bytes=0-7")
            self.assertEqual(partial.status_code, 206)
            self.assertNotIn("Content-Encoding", partial.headers)
            self.assertEqual(partial.data, plain.data[:8])
            for other_version in ("", "?v=stale"):
                self.assertIn("no-store", self.fetch(f"/static/{name}{other_version}", "gzip").cache_control)
        self.assertEqual(self.fetch("/static/../static/script.js", "gzip").status_code, 404)
        fflate = self.fetch("/static/vendor/fflate-0.8.2/fflate.min.js", "gzip")
        self.assertEqual(fflate.status_code, 200)
        self.assertIn("immutable", fflate.cache_control)


if __name__ == "__main__":
    unittest.main()
