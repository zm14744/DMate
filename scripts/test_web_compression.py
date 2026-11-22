"""Check the representations used for the first navigation and its public assets."""
import gzip
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


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

    def test_static_cache_validators_and_ranges(self):
        revision = app._RUNTIME_SOURCE["manifest_sha256"]
        for name in ("script.js", "chat-composer.css"):
            path = f"/static/{name}?v={revision}"
            plain = self.fetch(path, "identity;q=1, gzip;q=0.5")
            encoded = self.fetch(path, "gzip")
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
        self.assertEqual(self.fetch("/static/../static/script.js", "gzip").status_code, 404)
        for path in ("/static/script.js", "/static/script.js?v=stale"):
            self.assertIn("no-store", self.fetch(path, "gzip").cache_control)
        fflate = self.fetch("/static/vendor/fflate-0.8.2/fflate.min.js", "gzip")
        self.assertEqual(fflate.status_code, 200)
        self.assertIn("immutable", fflate.cache_control)


if __name__ == "__main__":
    unittest.main()
