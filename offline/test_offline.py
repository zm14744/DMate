"""Standard-library tests for DMate Offline.

Run from repository root: python3 -m unittest discover -s offline -p 'test_*.py'
No Ollama installation or external network is required for these tests.
"""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dmate_offline as app


class FakeOllama(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path != "/api/tags":
            self.send_error(404)
            return
        result = json.dumps({"models": [{"name": "qwen3:4b"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(result)))
        self.end_headers()
        self.wfile.write(result)

    def do_POST(self):
        if self.path != "/api/chat":
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length"))))
        assert body["model"] == "qwen3:4b"
        assert body["think"] is None
        assert body["messages"][-1]["content"] == "证明偶数加偶数还是偶数"
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        self.wfile.write(
            b'{"message":{"content":"Let a=2m, "},"done":false}\n'
            b'{"message":{"content":"b=2n."},"done":false}\n'
            b'{"message":{"content":""},"done":true}\n')


class OfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        app.DATA_HOME = Path(cls.temp_dir.name)
        app.DB_FILE = app.DATA_HOME / "test.sqlite3"
        app.initialize()
        cls.fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
        cls.web = app.OfflineServer(("127.0.0.1", 0), app.Handler)
        cls.fake_thread = threading.Thread(target=cls.fake.serve_forever, daemon=True)
        cls.web_thread = threading.Thread(target=cls.web.serve_forever, daemon=True)
        cls.fake_thread.start()
        cls.web_thread.start()
        cls.env = patch.dict(os.environ, {
            "DMATE_OFFLINE_OLLAMA_PORT": str(cls.fake.server_port),
        })
        cls.env.start()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.fake.shutdown()
        cls.web.shutdown()
        cls.fake.server_close()
        cls.web.server_close()
        cls.temp_dir.cleanup()

    def setUp(self):
        with app.database() as con:
            con.execute("DELETE FROM messages")
            con.execute("DELETE FROM sessions")
            con.execute("DELETE FROM items")

    def send(self, method, path, body=None, token=True, host=None):
        con = http.client.HTTPConnection("127.0.0.1", self.web.server_port, timeout=6)
        headers = {
            "Host": host or "127.0.0.1:%d" % self.web.server_port,
            "Content-Type": "application/json",
        }
        if token:
            headers["X-DMate-Local"] = self.web.csrf_token
        con.request(method, path, body=json.dumps(body).encode() if body is not None else None,
                    headers=headers)
        response = con.getresponse()
        status = response.status
        raw = response.read()
        con.close()
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            payload = raw
        return status, payload

    def test_local_only_api(self):
        status, data = self.send("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        self.assertEqual(data["models"], ["qwen3:4b"])
        self.assertEqual(data["token"], self.web.csrf_token)
        status, _ = self.send("POST", "/api/sessions", {"title": "CSRF"}, token=False)
        self.assertEqual(status, 403)
        status, _ = self.send("GET", "/api/bootstrap", host="example.com")
        self.assertEqual(status, 403)

    def test_local_chat_and_persistence(self):
        status, data = self.send("POST", "/api/sessions", {"title": "数学"})
        self.assertEqual(status, 201)
        sid = data["id"]
        status, events = self.send("POST", "/api/chat", {
            "session_id": sid, "message": "证明偶数加偶数还是偶数", "model": "qwen3:4b",
        })
        self.assertEqual(status, 200)
        # The streaming endpoint returns NDJSON rather than JSON.
        text = events.decode("utf-8") if isinstance(events, bytes) else str(events)
        self.assertIn('"type": "delta"', text)
        self.assertIn('"type": "done"', text)
        status, data = self.send("GET", "/api/sessions/" + sid + "/messages")
        self.assertEqual(status, 200)
        self.assertEqual([m["role"] for m in data["messages"]], ["user", "assistant"])
        self.assertEqual(data["messages"][-1]["content"], "Let a=2m, b=2n.")

    def test_graph(self):
        result = app.graph_analysis({
            "vertices": "A,B,C", "edges": "A B\nB C", "start": "A",
        })
        self.assertTrue(result["is_tree"])
        self.assertEqual(result["bfs"], ["A", "B", "C"])
        self.assertEqual(result["adjacency_matrix"], [
            [0, 1, 0], [1, 0, 1], [0, 1, 0]
        ])
        directed = app.graph_analysis({
            "vertices": "A,B,C", "edges": "A B\nB C", "directed": True,
        })
        self.assertEqual(directed["degree"]["B"], {"out": 1, "in": 1})
        self.assertEqual(directed["components"], [["A", "B", "C"]])
        with self.assertRaises(ValueError):
            app.graph_analysis({"vertices": "", "edges": "A A"})

    def test_export_import_transaction(self):
        status, item = self.send("POST", "/api/items", {
            "kind": "mistake", "title": "错题", "content": "边数判断",
        })
        self.assertEqual(status, 201)
        status, backup = self.send("GET", "/api/export")
        self.assertEqual(status, 200)
        self.assertEqual(len(backup["items"]), 1)
        invalid = json.loads(json.dumps(backup))
        invalid["items"][0]["kind"] = "not_a_kind"
        status, _ = self.send("POST", "/api/import", {
            "confirm_replace": True, "backup": invalid,
        })
        self.assertEqual(status, 400)
        with app.database() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM items").fetchone()[0], 1)
        status, _ = self.send("POST", "/api/import", {
            "confirm_replace": True, "backup": backup,
        })
        self.assertEqual(status, 200)
        with app.database() as con:
            row = con.execute("SELECT title FROM items").fetchone()
            self.assertEqual(row[0], "错题")

    def test_image_rejection(self):
        with self.assertRaises(ValueError):
            app.validate_image("data:image/png;base64,bm90X2FuX2ltYWdl")
        self.assertIsNone(app.validate_image(None))


if __name__ == "__main__":
    unittest.main()
