"""Inline catalog metadata shares the answer call and stays out of public text."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ai
import classification_semantic
from answer_catalog import CATALOG_GRAPH_CLOSE, CATALOG_GRAPH_OPEN


QUESTION = "从十名学生中选出三名组成小组，有多少种不同选法"
PUBLIC = "选择的先后顺序不影响小组，使用组合计数"


def graph(identifier="count_perm_comb"):
    return {"nodes": [{"id": identifier, "usage": "assessed", "reason": "题目要求无序选择三个人",
                       "evidence": [{"source": "question", "quote": QUESTION}]}],
            "edges": [], "unresolved": ""}


def envelope(public=PUBLIC, value=None):
    return public + "\n" + CATALOG_GRAPH_OPEN + json.dumps(
        graph() if value is None else value, ensure_ascii=False) + CATALOG_GRAPH_CLOSE


def completion(content, finish="stop"):
    return {"ok": True, "content": content, "choice": {"finish_reason": finish},
            "provider_id": "fixture", "provider_name": "fixture", "model": "fixture"}


def context(**extra):
    return {"mode": "hint", "difficulty": "简单", "question_graph": {
        "sources": {"question": QUESTION, "solution": "不应被当作本次解答的旧内容"}}, **extra}


class AnswerCatalogStreamingTests(unittest.TestCase):
    def setUp(self):
        self.key = patch.object(ai, "DEEPSEEK_API_KEY", "local-test-placeholder")
        self.mock = patch.object(ai, "ASK_AI_MOCK", False)
        self.prompt = patch.object(classification_semantic, "catalog_answer_prompt", return_value="\nPRIVATE_CATALOG_POLICY\n")
        self.key.start()
        self.mock.start()
        self.policy = self.prompt.start()
        self.addCleanup(self.key.stop)
        self.addCleanup(self.mock.stop)
        self.addCleanup(self.prompt.stop)

    def invoke(self, transport, *, teaching=None, streamed=True):
        chunks = []
        with patch.object(ai, "_request_text_completion", side_effect=transport) as request:
            result = ai.ask_ai([{"role": "user", "content": "请讲解这道题"}],
                teaching_context=context() if teaching is None else teaching,
                on_delta=chunks.append if streamed else None)
        return result, chunks, request

    @staticmethod
    def stream_result(result, options):
        callback = options.get("on_delta")
        if callback:
            for character in result.get("content", ""):
                callback(character)
        return result

    def test_one_answer_call_returns_catalog_and_never_streams_the_private_suffix(self):
        captured = []
        def transport(messages, **options):
            captured.append(messages)
            return self.stream_result(completion(envelope()), options)
        result, chunks, request = self.invoke(transport)
        request.assert_called_once()
        self.assertTrue(result["ok"])
        self.assertEqual(result["reply"], PUBLIC)
        self.assertEqual(result["catalog_graph"], graph())
        self.assertEqual("".join(chunks), PUBLIC + "\n")
        self.assertIn("PRIVATE_CATALOG_POLICY", captured[0][0]["content"])
        self.assertIn(json.dumps({"question": QUESTION}, ensure_ascii=False), captured[0][0]["content"])
        self.assertNotIn("不应被当作本次解答的旧内容", captured[0][0]["content"])

    def test_general_conversation_does_not_add_the_catalog_prompt(self):
        result, chunks, request = self.invoke(lambda _messages, **options:
            self.stream_result(completion("这里是所需的简短说明"), options),
            teaching=context(context_scope="conversation"))
        self.policy.assert_not_called()
        request.assert_called_once()
        self.assertEqual(result["reply"], "这里是所需的简短说明")
        self.assertEqual("".join(chunks), result["reply"])
        self.assertNotIn("catalog_graph", result)

    def test_generated_question_keeps_hidden_answer_but_not_catalog_suffix(self):
        public = "【题目】\n从五人中选两人\n[[WRONGBOOK_ANSWER]]10[[/WRONGBOOK_ANSWER]]"
        result, _chunks, request = self.invoke(lambda _messages, **_options: completion(envelope(public)),
            teaching=context(mode="exercise"), streamed=False)
        request.assert_called_once()
        self.policy.assert_called_once()
        self.assertEqual(result["reply"], public)
        self.assertEqual(result["catalog_graph"], graph())
        self.assertNotIn("【本次图谱归类绑定的原始题干】", request.call_args.args[0][0]["content"])

    def test_malformed_suffix_is_shielded_before_math_format_detection(self):
        raw = PUBLIC + CATALOG_GRAPH_OPEN + '{"nodes": ["$$broken mathematical JSON'
        seen = []
        with patch.object(ai, "_looks_like_broken_math", side_effect=lambda value: seen.append(value) or False), \
                patch.object(ai, "_regenerate_broken_math_answer") as repair:
            result, chunks, request = self.invoke(lambda _messages, **options:
                self.stream_result(completion(raw), options))
        request.assert_called_once()
        repair.assert_not_called()
        self.assertEqual(seen, [PUBLIC])
        self.assertEqual(result["reply"], PUBLIC)
        self.assertNotIn("catalog_graph", result)
        self.assertEqual("".join(chunks), PUBLIC)

    def test_format_rewrite_uses_only_its_own_metadata(self):
        for rewritten_graph in (graph("count_basic"), None):
            with self.subTest(metadata=rewritten_graph is not None):
                responses = iter([completion(envelope("broken", graph())),
                    completion(envelope("fixed", rewritten_graph) if rewritten_graph else "fixed")])
                with patch.object(ai, "_looks_like_broken_math", side_effect=lambda text: text == "broken"), \
                        patch.object(ai, "_repair_common_latex_typos", side_effect=lambda text: text):
                    result, _chunks, request = self.invoke(lambda _messages, **_options: next(responses), streamed=False)
                self.assertEqual(request.call_count, 2, "only the existing format-repair retry is used")
                self.assertEqual(result["reply"], "fixed")
                if rewritten_graph is None:
                    self.assertNotIn("catalog_graph", result, "the old broken draft's metadata cannot survive a replacement")
                else:
                    self.assertEqual(result["catalog_graph"], rewritten_graph)

    def test_recovery_resets_the_failed_private_stream_state(self):
        calls = []
        def transport(_messages, **options):
            calls.append(1)
            if len(calls) == 1:
                options["on_delta"](CATALOG_GRAPH_OPEN + "unfinished")
                return {"ok": False, "empty_body": True}
            return self.stream_result(completion(envelope()), options)
        result, chunks, request = self.invoke(transport, teaching=context(mode="full_solution"))
        self.assertEqual(request.call_count, 2)
        self.assertEqual(result["reply"], PUBLIC)
        self.assertEqual("".join(chunks), PUBLIC + "\n")

    def test_ordinary_answer_truncation_keeps_its_existing_continuation(self):
        responses = iter([completion("第一部分", "length"), completion(envelope("第二部分"))])
        result, chunks, request = self.invoke(lambda _messages, **options:
            self.stream_result(next(responses), options))
        self.assertEqual(request.call_count, 2)
        self.assertEqual(result["reply"], "第一部分\n第二部分")
        self.assertEqual("".join(chunks), "第一部分\n第二部分\n")
        self.assertEqual(result["catalog_graph"], graph())

    def test_marker_split_at_answer_budget_remains_private_and_valid(self):
        marker_prefix = CATALOG_GRAPH_OPEN[:12]
        tail = CATALOG_GRAPH_OPEN[12:] + json.dumps(graph(), ensure_ascii=False) + CATALOG_GRAPH_CLOSE
        responses = iter([completion(PUBLIC + marker_prefix, "length"), completion(tail)])
        result, chunks, request = self.invoke(lambda _messages, **options:
            self.stream_result(next(responses), options))
        self.assertEqual(request.call_count, 2)
        self.assertEqual(result["reply"], PUBLIC)
        self.assertEqual("".join(chunks), PUBLIC)
        self.assertEqual(result["catalog_graph"], graph())

    def test_metadata_only_truncation_does_not_start_another_model_call(self):
        for mode, public in (("hint", PUBLIC), ("exercise", "【题目】\n从五人中选两人\n[[WRONGBOOK_ANSWER]]10[[/WRONGBOOK_ANSWER]]")):
            with self.subTest(mode=mode):
                raw = public + CATALOG_GRAPH_OPEN + '{"nodes":['
                result, chunks, request = self.invoke(lambda _messages, **options:
                    self.stream_result(completion(raw, "length"), options), teaching=context(mode=mode))
                request.assert_called_once()
                self.assertEqual(result["reply"], public)
                self.assertNotIn("catalog_graph", result)
                self.assertEqual("".join(chunks), public)

    def test_private_metadata_alone_cannot_be_a_completed_public_answer(self):
        result, chunks, request = self.invoke(lambda _messages, **options:
            self.stream_result(completion(envelope("")), options))
        request.assert_called_once()
        self.assertFalse(result["ok"])
        self.assertNotIn("catalog_graph", result)
        self.assertFalse("".join(chunks).strip())

    def test_readable_fallback_cannot_keep_a_failed_draft_graph(self):
        with patch.object(ai, "_looks_like_broken_math", return_value=True), \
                patch.object(ai, "_regenerate_broken_math_answer", return_value=None), \
                patch.object(ai, "_fallback_math_to_readable_text", return_value="可读的替代内容"):
            result, _chunks, request = self.invoke(lambda _messages, **_options: completion(envelope()), streamed=False)
        request.assert_called_once()
        self.assertEqual(result["reply"], "可读的替代内容")
        self.assertNotIn("catalog_graph", result)


if __name__ == "__main__":
    unittest.main()
