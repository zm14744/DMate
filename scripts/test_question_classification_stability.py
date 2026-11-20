"""No-network regressions for durable, question-only classification snapshots."""
import concurrent.futures
import copy
import importlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import classification_semantic as semantic
import question_classification as registry
from teaching import _KNOWLEDGE_GRAPH, analyze_messages, analyze_question, enrich_question_graph

QUESTION = "请讨论真值表与逻辑等价"
CATALOG = _KNOWLEDGE_GRAPH["nodes"]


class QuestionClassificationStabilityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = str(Path(directory.name) / "questions.sqlite3")
        environment = patch.dict(os.environ, {"DMATE_QUESTION_CLASSIFICATION_DB": self.database})
        environment.start()
        self.addCleanup(environment.stop)

    def snapshot(self, question=QUESTION, factory=None):
        if factory is None:
            return analyze_question(question)["question_classification"]
        return registry.question_classification(question, CATALOG, factory)

    def test_same_question_is_independent_of_actual_answer_and_model_node_order(self):
        prior = analyze_question(QUESTION)
        expected = prior["question_classification"]
        catalog = semantic._catalog_snapshot()
        first = enrich_question_graph(prior, QUESTION, "利用真值表证明逻辑等价")
        second = enrich_question_graph(prior, QUESTION, "利用逻辑等价计算真值表")
        self.assertNotEqual(first["question_graph"]["sources"], second["question_graph"]["sources"])
        self.assertNotEqual(first["question_graph"]["edges"], second["question_graph"]["edges"])
        for local in (first, second):
            graph = copy.deepcopy(local["question_graph"])
            graph.update(classification_status="semantic", needs_review=False)
            for nodes in (graph["nodes"], list(reversed(graph["nodes"]))):
                graph["nodes"] = nodes
                reviewed = semantic._apply_catalog_graph(local, graph, catalog)
                self.assertEqual(reviewed["question_classification"], expected)
                self.assertEqual(reviewed["question_graph"]["sources"], local["question_graph"]["sources"])

    def test_cosmetic_whitespace_is_normalized_but_math_and_diagram_lines_are_not(self):
        first = self.snapshot("  请讨论真值表\t与逻辑等价  ")
        second = self.snapshot("请讨论真值表 与逻辑等价")
        self.assertEqual(first["question_sha256"], second["question_sha256"])
        self.assertEqual(first["node_ids"], second["node_ids"])
        samples = ["求 A∩B", "求 A∪B", "求 A₂", "求 A2", "矩阵 1 0\n0 1", "矩阵 1 0 0 1"]
        digests = [self.snapshot(text)["question_sha256"] for text in samples]
        self.assertEqual(len(digests), len(set(digests)), "Do not merge distinct mathematics or diagrams")

    def test_history_mode_and_image_request_wrappers_do_not_change_intrinsic_judgment(self):
        question = "设 A={1,2,3}，B={2,3,4}，求 A∩B"
        expected = self.snapshot(question)
        history = [{"role": "user", "content": "证明命题逻辑中的德摩根律"},
                   {"role": "assistant", "content": "可以用真值表。"},
                   {"role": "user", "content": question},
                   {"role": "assistant", "content": "先看交集。"}]
        for request in ("给我一个提示", "给出完整解答", "为什么这一步这样做", "请检查我的答案 A∩B={2,3}"):
            with self.subTest(request=request):
                actual = analyze_messages(history + [{"role": "user", "content": request}])["question_classification"]
                self.assertEqual(actual, expected)
        for marker, graph_marker in (("【题目文字】", "【图形信息】"), ("【题干与公式识别】", "【图形结构识别】")):
            for request in ("给出解题提示", "给出完整解答"):
                wrapper = marker + "\n" + question + "\n" + graph_marker + "\n无\n【我的要求】\n" + request
                actual = analyze_messages([{"role": "user", "content": wrapper}])["question_classification"]
                self.assertEqual(actual["question"], wrapper, "The response keeps its exact source for stale-snapshot checks")
                for key in set(expected) - {"question"}:
                    self.assertEqual(actual[key], expected[key], key)
        for tail in ("\n\n【图形信息】\n无", "\n  \t【图形信息】\n无"):
            unwrapped = self.snapshot(question + tail)
            self.assertEqual(unwrapped["question_sha256"], expected["question_sha256"])
        first = self.snapshot("【题目文字】\n判断图 G 是否连通\n【图形信息】\n顶点1,2，边1—2\n【我的要求】\n提示")
        second = self.snapshot("【题目文字】\n判断图 G 是否连通\n【图形信息】\n顶点1,2，无边\n【我的要求】\n提示")
        self.assertNotEqual(first["question_sha256"], second["question_sha256"])

    def test_restarts_and_cache_eviction_never_replace_a_registered_projection(self):
        expected = self.snapshot()
        with semantic._CATALOG_LOCK:
            semantic._CATALOG_CACHE.clear()
        failure = lambda _question: self.fail("An existing projection must not be inferred again")
        self.assertEqual(self.snapshot(factory=failure), expected)
        program = ("import json, teaching; "
                   "teaching._question_classification_projection=lambda question: "
                   "(_ for _ in ()).throw(AssertionError('Registered projection must survive restart')); "
                   "print(json.dumps(teaching.analyze_question(" + repr(QUESTION)
                   + ")[\"question_classification\"],ensure_ascii=False))")
        restarted = subprocess.run([sys.executable, "-c", program], cwd=ROOT, check=True,
                                   capture_output=True, text=True, env=os.environ.copy())
        self.assertEqual(json.loads(restarted.stdout), expected)

    def test_parallel_first_registration_is_atomic_and_does_not_store_question_or_answer(self):
        question = "私有题干，求秘密集合 A={78123,99421} 的子集数"
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(self.snapshot, [question] * 16))
        self.assertTrue(all(item == results[0] for item in results))
        raw = Path(self.database).read_bytes()
        self.assertNotIn(question.encode(), raw)
        self.assertNotIn(b"78123", raw)
        self.assertNotIn(b"99421", raw)
        with sqlite3.connect(self.database) as connection:
            rows = connection.execute("SELECT projection FROM question_classifications").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(json.loads(rows[0][0])), {"version", "node_ids", "focus_node_ids", "difficulty"})

    def test_user_scopes_do_not_share_their_registry_entry(self):
        first = {"node_ids": ["logic_truth_table"], "focus_node_ids": ["logic_truth_table"], "difficulty": "简单"}
        second = {"node_ids": ["logic_equivalence"], "focus_node_ids": ["logic_equivalence"], "difficulty": "困难"}
        with patch.object(registry, "_owner_scope", return_value="account-one"):
            saved = self.snapshot(factory=lambda _question: first)
        with patch.object(registry, "_owner_scope", return_value="account-two"):
            other = self.snapshot(factory=lambda _question: second)
        with patch.object(registry, "_owner_scope", return_value="account-one"):
            again = self.snapshot(factory=lambda _question: self.fail("First account must retain its judgment"))
        self.assertEqual(saved, again)
        self.assertNotEqual(saved["node_ids"], other["node_ids"])

    def test_signed_account_scope_survives_browser_changes_and_separates_guests(self):
        from flask import Flask, session
        app = Flask(__name__)
        app.secret_key = "stable-auth-key"
        scopes = []
        for cookie, account in (("a" * 64, 41), ("b" * 64, 41), ("a" * 64, 42),
                                ("a" * 64, None), ("b" * 64, None)):
            with app.test_request_context(headers={"Cookie": "dm_graph_owner=" + cookie}):
                if account is not None:
                    session["user_id"] = account
                scopes.append(registry._owner_scope())
        self.assertEqual(scopes[0], scopes[1])
        self.assertEqual(len(set(scopes)), 4)

    def test_unrecognized_question_does_not_borrow_another_graphs_nodes(self):
        recognized = self.snapshot()
        self.assertTrue(recognized["node_ids"])
        unknown = self.snapshot("见图片，回答这个问题")
        self.assertEqual(unknown["node_ids"], [])
        self.assertEqual(unknown["focus_points"], [])

    def test_endpoints_return_same_snapshot_for_registration_review_and_image_followup(self):
        with patch("requests.sessions.Session.request", side_effect=AssertionError("No provider requests")):
            runtime = importlib.import_module("app")
        with patch.object(runtime, "_check_rate_limit", return_value=True), patch.object(
            runtime, "ask_ai", return_value={"ok": True, "reply": "利用真值表证明逻辑等价"}
        ), patch.object(semantic, "_enabled", return_value=False):
            client = runtime.app.test_client()
            snapshots = []
            for review, answer in ((False, ""), (True, "利用真值表证明逻辑等价"),
                                   (True, "利用逻辑等价计算真值表")):
                response = client.post("/analyze-questions", json={"semantic_fallback": review,
                    "questions": [{"key": "q", "text": QUESTION, "solution": answer}]})
                self.addCleanup(response.close)
                self.assertEqual(response.status_code, 200)
                snapshots.append(response.get_json()["results"][0]["teaching"]["question_classification"])
            wrapper = ("【当前指向题目】\n" + QUESTION + "\n【当前指向题目结束】\n"
                       "【本轮唯一需要执行的用户请求】\n给出解题提示\n【本轮请求结束】")
            response = client.post("/chat", json={"question_context": {"question": QUESTION, "difficulty": "简单"},
                "messages": [{"role": "user", "content": wrapper}]})
            self.addCleanup(response.close)
            self.assertEqual(response.status_code, 200)
            snapshots.append(response.get_json()["teaching"]["question_classification"])
            self.assertTrue(all(item == snapshots[0] for item in snapshots))


if __name__ == "__main__":
    unittest.main()
