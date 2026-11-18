"""Question registration returns graph data with its difficulty and labels.

These source/transport checks make no provider requests. Browser tests cover
the separate rule that displaying an existing snapshot makes no new requests.
"""

import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from teaching import analyze_question


QUESTION = "设 A={1,2,3}，B={2,3,4}，求 A∩B"


class QuestionSnapshotContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch("requests.sessions.Session.request", side_effect=AssertionError("No startup network")):
            cls.runtime = importlib.import_module("app")
        old_config = {key: cls.runtime.app.config.get(key) for key in ("TESTING", "SECRET_KEY")}
        cls.addClassCleanup(cls.runtime.app.config.update, old_config)
        cls.runtime.app.config.update(TESTING=True, SECRET_KEY="question-snapshot-contract")
        cls.catalog = {node["id"]: node for node in cls.runtime.KNOWLEDGE_GRAPH_DATA["nodes"]}

    def setUp(self):
        self.network = patch("requests.sessions.Session.request", side_effect=AssertionError("No provider requests"))
        network = self.network.start()
        self.addCleanup(self.network.stop)
        self.addCleanup(network.assert_not_called)
        self.rate = patch.object(self.runtime, "_check_rate_limit", return_value=True)
        self.rate.start()
        self.addCleanup(self.rate.stop)
        self.client = self.runtime.app.test_client()

    def assert_snapshot(self, teaching, question, solution=""):
        self.assertIn(teaching["difficulty"], {"简单", "中等", "困难"})
        graph = teaching["question_graph"]
        self.assertEqual(graph["version"], 1)
        self.assertEqual(graph["sources"], {"question": question, "solution": solution})
        ids = {node["id"] for node in graph["nodes"]}
        self.assertTrue(ids, "This recognized registration sample already has graph nodes")
        self.assertLessEqual(ids, self.catalog.keys())
        names = {self.catalog[identifier]["name"] for identifier in ids}
        labels = set(teaching["knowledge_points"] + teaching["related_knowledge_points"])
        self.assertEqual(labels, names, "The displayed labels and graph come from the same recognition result")
        self.assertLessEqual(set(teaching["focus_points"]), names)
        for node in graph["nodes"]:
            self.assertTrue(any(record["quote"] and record["quote"] in graph["sources"][record["source"]]
                                for record in node["evidence"]))
        for edge in graph["edges"]:
            self.assertIn(edge["from"], ids)
            self.assertIn(edge["to"], ids)
        return graph

    def test_local_registration_already_contains_graph_with_its_difficulty(self):
        result = analyze_question(QUESTION)
        graph = self.assert_snapshot(result, QUESTION)
        self.assertEqual(graph["classification_source"], "local_structure")
        self.assertEqual({node["id"] for node in graph["nodes"]}, {"set_operation"})

    def test_manual_registration_endpoint_requires_no_answer_or_semantic_pass(self):
        with patch.object(self.runtime, "analyze_question", wraps=analyze_question) as recognize, patch.object(
            self.runtime, "ask_ai", side_effect=AssertionError("Registration does not generate an answer")
        ), patch.object(self.runtime, "classify_catalog_questions", side_effect=AssertionError("No extra semantic pass")):
            response = self.client.post("/analyze-questions", json={"questions": [{"key": "manual", "text": QUESTION}]})
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        recognize.assert_called_once_with(QUESTION)
        item = response.get_json()["results"][0]
        self.assertEqual(item["key"], "manual")
        self.assert_snapshot(item["teaching"], QUESTION)

    def test_chat_final_reply_keeps_the_same_question_snapshot_without_inline_metadata(self):
        with patch.object(self.runtime, "ask_ai", return_value={"ok": True, "reply": "交集为 {2,3}"}) as answer, patch.object(
            self.runtime, "classify_catalog_questions", side_effect=AssertionError("No follow-up classification")
        ):
            response = self.client.post("/chat", json={"language": "zh-CN", "messages": [{"role": "user", "content": QUESTION}]})
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        answer.assert_called_once()
        body = response.get_json()
        self.assert_snapshot(body["teaching"], QUESTION, body["reply"])

    def test_confirmed_image_text_uses_the_original_question_not_its_request_wrapper(self):
        message = ("【当前指向题目】\n" + QUESTION + "\n【当前指向题目结束】\n"
                   "【本轮唯一需要执行的用户请求】\n给出解题提示\n【本轮请求结束】")
        with patch.object(self.runtime, "ask_ai", return_value={"ok": True, "reply": "先找出同时属于 A 和 B 的元素"}) as answer, patch.object(
            self.runtime, "classify_catalog_questions", side_effect=AssertionError("No follow-up image-topic classification")
        ):
            response = self.client.post("/chat", json={"language": "zh-CN",
                "question_context": {"question": QUESTION, "difficulty": "简单"},
                "messages": [{"role": "user", "content": message}]})
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        answer.assert_called_once()
        body = response.get_json()
        self.assert_snapshot(body["teaching"], QUESTION, body["reply"])

    def test_generated_question_returns_its_own_graph_and_hidden_answer_together(self):
        reply = "【题目】\n" + QUESTION + "\n[[WRONGBOOK_ANSWER]]\n{2,3}\n[[/WRONGBOOK_ANSWER]]"
        with patch.object(self.runtime, "ask_ai", return_value={"ok": True, "reply": reply}) as answer, patch.object(
            self.runtime, "classify_catalog_questions", side_effect=AssertionError("No second generation-topic call")
        ):
            response = self.client.post("/chat", json={"language": "zh-CN", "messages": [
                {"role": "user", "content": "出一道简单的集合运算题，只求两个集合的交集"}]})
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        answer.assert_called_once()
        body = response.get_json()
        self.assertTrue(body["generated_exercise"])
        self.assert_snapshot(body["generated_teaching"], body["generated_question"], body["generated_answer"])
        self.assertNotIn("WRONGBOOK_ANSWER", body["reply"])
        self.assertNotIn(body["generated_answer"], body["reply"])


if __name__ == "__main__":
    unittest.main()
