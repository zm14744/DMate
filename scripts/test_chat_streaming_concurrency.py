"""Local SSE transport regressions; no application models or network requests.

Run: python -m unittest discover -s scripts -p 'test_chat_streaming_concurrency.py' -v
"""

import json
from pathlib import Path
import sys
import threading
import unittest

from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chat_streaming import ChatStreamCancelled, stream_chat_response


class ChatStreamingConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.entered = {label: threading.Event() for label in ("A", "B")}
        self.release = {label: threading.Event() for label in ("A", "B")}
        self.finished = {label: threading.Event() for label in ("A", "B")}
        self.responses = []
        self.app = Flask(__name__)
        self.app.testing = True

        def handler(on_delta, cancelled):
            # Read through the copied Flask request context in each worker.
            label = request.get_json()["label"]
            self.entered[label].set()
            try:
                while not self.release[label].wait(0.01):
                    if cancelled():
                        raise ChatStreamCancelled()
                on_delta(label + "-delta")
                return jsonify(reply=label + "-answer")
            finally:
                self.finished[label].set()

        @self.app.post("/chat")
        def chat():
            return stream_chat_response(handler)

    def tearDown(self):
        for event in self.release.values():
            event.set()
        for response in self.responses:
            response.close()
        for label in ("A", "B"):
            if self.entered[label].is_set():
                self.assertTrue(self.finished[label].wait(3), label + " worker did not exit")

    def start_both(self):
        responses = {}
        for label in ("A", "B"):
            response = self.app.test_client().post("/chat", json={"label": label}, buffered=False)
            self.responses.append(response)
            self.assertEqual(response.status_code, 200)
            responses[label] = response
        for label in ("A", "B"):
            self.assertTrue(self.entered[label].wait(3), label + " handler did not enter")
            self.assertFalse(self.finished[label].is_set(), label + " finished before release")
        return responses

    def read_events(self, response):
        body = b"".join(response.response).decode("utf-8")
        return [(lines[0][7:], json.loads(lines[1][6:]))
                for block in body.split("\n\n")
                if (lines := block.splitlines()) and lines[0].startswith("event: ")]

    def test_both_requests_enter_and_finish_in_reverse_order_with_own_context(self):
        responses = self.start_both()
        self.release["B"].set()
        self.assertEqual(self.read_events(responses["B"]), [
            ("delta", {"text": "B-delta"}), ("final", {"reply": "B-answer"})])
        self.assertFalse(self.finished["A"].is_set(), "B must finish while A is still waiting")
        self.release["A"].set()
        self.assertEqual(self.read_events(responses["A"]), [
            ("delta", {"text": "A-delta"}), ("final", {"reply": "A-answer"})])

    def test_closing_one_request_cancels_only_its_worker(self):
        responses = self.start_both()
        responses["A"].close()
        self.assertTrue(self.finished["A"].wait(3), "closing A must stop A's worker")
        self.assertFalse(self.finished["B"].is_set(), "closing A must leave B running")
        self.release["B"].set()
        self.assertEqual(self.read_events(responses["B"]), [
            ("delta", {"text": "B-delta"}), ("final", {"reply": "B-answer"})])


if __name__ == "__main__":
    unittest.main()
