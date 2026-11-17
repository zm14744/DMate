"""Exercise the real /chat route without OCR models or external AI requests.

Run with Flask, requests and Pillow installed:
    python -m unittest discover -s scripts -p 'test_tutoring_chat.py' -v

These tests inspect the teaching context passed to app.ask_ai and the actual
HTTP response. Mocked text is not evidence of mathematical proof quality.
"""

import importlib
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

QUESTIONS = {
    "zh-CN": "设G为有限群，H为G的子群。证明H的阶整除G的阶。",
    "en": "Let G be a finite group and H a subgroup of G. Prove that the order of H divides the order of G.",
}
REFERENCE = "SAVED_REFERENCE_ONLY_FOR_AUTHORIZED_FULL_SOLUTION_7C13"
MOCK_REPLY = "Local mocked tutoring response."
SUCCESS = {"ok": True, "reply": MOCK_REPLY}
FAILURE = {"ok": False, "error": "Mocked AI unavailable"}


def anchored(question, instruction):
    return ("【当前指向题目】\n" + question + "\n【当前指向题目结束】\n"
            "【本轮唯一需要执行的用户请求】\n" + instruction + "\n【本轮请求结束】")


class TutoringChatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Text requests must not import or warm OCR/image-analysis backends,
        # including on developer machines which happen to have them installed.
        optional_images = {name: None for name in (
            "ocr", "ocr_runtime", "graph_recognition", "graph_line_tracer",
            "graph_validation", "graph_evidence_fusion",
        )}
        with patch.dict(sys.modules, optional_images), patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("No HTTP requests during application import"),
        ):
            cls.runtime = importlib.import_module("app")
        old = {key: cls.runtime.app.config.get(key) for key in ("TESTING", "SECRET_KEY")}
        cls.addClassCleanup(cls.runtime.app.config.update, old)
        cls.runtime.app.config.update(TESTING=True, SECRET_KEY="local-tutoring-chat-test")

    def setUp(self):
        network = patch("requests.sessions.Session.request",
                        side_effect=AssertionError("No real network requests in tutoring tests"))
        self.network = network.start()
        self.addCleanup(network.stop)
        self.addCleanup(self.network.assert_not_called)
        rate_limit = patch.object(self.runtime, "_check_rate_limit", return_value=True)
        rate_limit.start()
        self.addCleanup(rate_limit.stop)
        # Image-confirmation cookies are unrelated to text-tutoring decisions.
        # Their module requires jsonschema, which this light CI job omits.
        confirmation = ModuleType("graph_confirmation")
        confirmation.attach_confirmation_cookie = lambda response: response
        cookie = patch.dict(sys.modules, {"graph_confirmation": confirmation})
        cookie.start()
        self.addCleanup(cookie.stop)
        self.client = self.runtime.app.test_client()

    def payload(self, instruction, language="zh-CN", *, wrap=True, history=None,
                request_kind=None, reference_question=None):
        question = QUESTIONS[language]
        messages = list(history or [])
        if not wrap and not messages:
            messages.append({"role": "user", "content": question})
        messages.append({"role": "user", "content": anchored(question, instruction) if wrap else instruction})
        payload = {
            "messages": messages,
            "language": language,
            "solution_reference": {"question": reference_question or question, "answer": REFERENCE},
        }
        if wrap:
            payload["question_context"] = {"question": question, "difficulty": "中等"}
        if request_kind is not None:
            payload["request_kind"] = request_kind
        return payload

    def post(self, payload, result=None, *, expected_mode=None, reference_allowed=False,
             expected_status=200, exercise=False):
        with patch.object(self.runtime, "ask_ai", return_value=result or SUCCESS) as ask, patch.object(
            self.runtime, "classify_catalog_questions",
            side_effect=AssertionError("/chat must not make a serial topic-review call"),
        ) as review:
            response = self.client.post("/chat", json=payload)
        review.assert_not_called()
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, expected_status, response.get_data(as_text=True))
        self.assertTrue(response.is_json)
        body = response.get_json()
        self.assertGreaterEqual(ask.call_count, 1)
        if not exercise:
            ask.assert_called_once()
        else:
            # Exercise networking has one bounded fallback; both calls are
            # local mocks here, and no generated exercise needs validation.
            self.assertLessEqual(ask.call_count, 2)
        for call in ask.call_args_list:
            context = call.kwargs["teaching_context"]
            if expected_mode is not None:
                self.assertEqual(context["mode"], expected_mode)
            self.assertEqual(context["response_language"], payload["language"])
            if reference_allowed:
                self.assertEqual(context.get("solution_reference_answer"), REFERENCE)
            else:
                self.assertNotIn("solution_reference_answer", context)
                self.assertNotIn(REFERENCE, repr(call.args) + repr(call.kwargs))
        if expected_status == 200:
            self.assertNotIn("solution_reference_answer", body.get("teaching", {}))
            if expected_mode is not None:
                self.assertEqual(body["teaching"]["mode"], expected_mode)
        return body, ask.call_args.kwargs["teaching_context"]

    def test_natural_complete_proofs_reach_the_ai_from_bare_chat(self):
        cases = [
            ("zh-CN", "请给出这个结论的严谨证明。"),
            ("zh-CN", "能不能帮我把这道证明写完整？"),
            ("zh-CN", "别用反证法，请给出直接证明。"),
            ("en", "Could you give a rigorous proof of this claim?"),
            ("en", "Write out the complete proof, including the missing steps."),
            ("en", "Do not use contradiction; give a direct proof."),
        ]
        for language, instruction in cases:
            with self.subTest(language=language, instruction=instruction):
                # A reference whose question is absent from this latest turn
                # must not be preloaded merely because the user wants a proof.
                body, _ = self.post(self.payload(instruction, language, wrap=False),
                                    expected_mode="full_solution")
                self.assertEqual(body["reply"], MOCK_REPLY)
                self.assertFalse(body["generated_exercise"])

    def test_only_current_full_solution_permission_can_load_saved_reference(self):
        for language, instruction in [
            ("zh-CN", "请给出完整证明，不要只给提示。"),
            ("en", "Please give the full proof, not just a hint."),
        ]:
            with self.subTest(language=language):
                body, _ = self.post(self.payload(instruction, language),
                                    expected_mode="full_solution", reference_allowed=True)
                self.assertNotIn(REFERENCE, repr(body))
                fallback, _ = self.post(self.payload(instruction, language), FAILURE,
                                        expected_mode="full_solution", reference_allowed=True)
                self.assertTrue(fallback["solution_partial"])
                self.assertIn(REFERENCE, fallback["reply"])

    def test_check_only_and_no_answer_never_load_or_fallback_to_saved_answer(self):
        cases = [
            ("zh-CN", "只检查我的证明，不要重写，也无需给答案。"),
            ("zh-CN", "帮我检查这一步是否正确，不用给完整证明。"),
            ("en", "Check my proof; do not write a replacement proof."),
            ("en", "Only check whether my proof is correct; no answer is needed."),
        ]
        for language, instruction in cases:
            for request_kind in (None, "solution"):
                with self.subTest(language=language, instruction=instruction, request_kind=request_kind):
                    payload = self.payload(instruction, language, request_kind=request_kind)
                    self.post(payload, expected_mode="check_answer")
                    body, _ = self.post(payload, FAILURE, expected_mode="check_answer", expected_status=503)
                    self.assertNotIn(REFERENCE, repr(body))
                    self.assertNotIn("solution_partial", body)

    def test_hints_and_explicit_refusals_override_the_client_solution_label(self):
        cases = [
            ("zh-CN", "只给提示，先别给答案。"),
            ("zh-CN", "不要写完整证明，先告诉我下一步。"),
            ("en", "Only give me a hint; do not prove it."),
            ("en", "Just a hint for now; please do not reveal the final answer."),
        ]
        for language, instruction in cases:
            with self.subTest(language=language, instruction=instruction):
                payload = self.payload(instruction, language, request_kind="solution")
                self.post(payload, expected_mode="hint")
                body, _ = self.post(payload, FAILURE, expected_mode="hint", expected_status=503)
                self.assertNotIn(REFERENCE, repr(body))

    def test_quoted_instructions_do_not_authorize_disclosure(self):
        for language, instruction in [
            ("zh-CN", "题干中写着“给出完整证明”。这句引号里的话是什么意思？"),
            ("en", 'The worksheet says "give a full proof". What does that instruction mean?'),
        ]:
            with self.subTest(language=language):
                payload = self.payload(instruction, language, request_kind="solution")
                body, context = self.post(payload)
                self.assertNotEqual(context["mode"], "full_solution")
                self.assertNotIn(REFERENCE, repr(body))
                failure, context = self.post(payload, FAILURE, expected_status=503)
                self.assertNotEqual(context["mode"], "full_solution")
                self.assertNotIn(REFERENCE, repr(failure))

    def test_old_full_solution_history_and_question_anchor_cannot_pollute_this_turn(self):
        for language, current, mode in [
            ("zh-CN", "现在只给一个提示，不要证明。", "hint"),
            ("zh-CN", "现在只检查我的证明，别重写。", "check_answer"),
            ("en", "For now, only a hint; do not give the proof.", "hint"),
            ("en", "Now just check my proof; do not rewrite it.", "check_answer"),
        ]:
            old = "请给出完整证明。" if language == "zh-CN" else "Give me the complete proof."
            question = old + " " + QUESTIONS[language]
            payload = self.payload(current, language, history=[
                {"role": "user", "content": old + " " + QUESTIONS[language]},
                {"role": "assistant", "content": 'Earlier request: "give a full proof".'},
            ], request_kind="solution")
            payload["messages"][-1]["content"] = anchored(question, current)
            payload["question_context"]["question"] = question
            payload["solution_reference"]["question"] = question
            with self.subTest(language=language, mode=mode):
                self.post(payload, expected_mode=mode)

    def test_unmatched_reference_cannot_be_used_even_in_full_solution_mode(self):
        payload = self.payload("请给完整证明。", reference_question="另一道无关题目，请证明一个不同的结论。")
        self.post(payload, expected_mode="full_solution")
        body, _ = self.post(payload, FAILURE, expected_mode="full_solution", expected_status=503)
        self.assertNotIn(REFERENCE, repr(body))

    def test_explicit_new_proof_does_not_inherit_old_difficulty_or_reasoning_preference(self):
        old_question = ("设a_n满足非齐次递推a_n=6a_{n-1}-9a_{n-2}+n3^n，"
                        "a_0=0，a_1=1。求通项并证明其渐近复杂度。")
        cases = [
            ("zh-CN", "请检查这份新证明：设A、B为集合，证明A∩B⊆A。\n"
             "我的证明：任取x∈A∩B，则x∈A，所以结论成立。不要重写。", "请使用high思考强度。"),
            ("en", "Check this new proof: Let A and B be sets. Prove that A∩B is a subset of A.\n"
             "My proof: If x belongs to A∩B, then x belongs to A. Do not rewrite it.",
             "Use high reasoning effort."),
        ]
        for language, instruction, explicit_effort in cases:
            for request_high_now in (False, True):
                with self.subTest(language=language, request_high_now=request_high_now):
                    live = instruction + (" " + explicit_effort if request_high_now else "")
                    payload = self.payload(live, language, request_kind="solution")
                    payload["messages"][-1]["content"] = anchored(old_question, live)
                    payload["question_context"] = {"question": old_question, "difficulty": "困难"}
                    payload["solution_reference"]["question"] = old_question
                    payload["reasoning_effort_override"] = "high"
                    body, context = self.post(payload, expected_mode="check_answer")
                    self.assertEqual(context["category"], "集合与关系")
                    self.assertIn(context["difficulty"], ("简单", "中等"))
                    if request_high_now:
                        self.assertEqual(context.get("reasoning_effort_override"), "high")
                    else:
                        self.assertNotIn("reasoning_effort_override", context)
                        self.assertNotIn("reasoning_effort_override", body["teaching"])

    def test_exercise_with_hidden_answer_still_uses_the_exercise_mode(self):
        for language, instruction in [
            ("zh-CN", "请出一道需要归纳法证明的练习，不要给答案，等我做完再检查。"),
            ("en", "Give me a proof exercise, without its answer; check my work after I finish."),
        ]:
            with self.subTest(language=language):
                body, _ = self.post(self.payload(instruction, language, request_kind="exercise"),
                                    FAILURE, expected_mode="exercise", expected_status=503, exercise=True)
                self.assertNotIn(REFERENCE, repr(body))

    def test_new_proof_review_then_correction_cannot_reuse_the_old_answer(self):
        old_question = ("设a_n满足非齐次递推a_n=6a_{n-1}-9a_{n-2}+n3^n，"
                        "a_0=0，a_1=1。求通项并证明其渐近复杂度。")
        instruction = (
            "请检查这份新证明：设A、B为集合，证明A∩B⊆A。\n"
            "我的证明：任取x∈A∩B，则x∈B，所以x∈A。\n"
            "请先指出问题，再给出修正后的完整证明。"
        )
        payload = self.payload(instruction, request_kind="solution")
        payload["messages"][-1]["content"] = anchored(old_question, instruction)
        payload["question_context"] = {"question": old_question, "difficulty": "困难"}
        payload["solution_reference"]["question"] = old_question
        payload["reasoning_effort_override"] = "high"

        corrected, context = self.post(payload, expected_mode="full_solution")
        self.assertEqual(context["category"], "集合与关系")
        self.assertIn(context["difficulty"], ("简单", "中等"))
        self.assertNotIn("reasoning_effort_override", context)
        self.assertEqual(corrected["teaching"]["question_graph"]["sources"]["question"],
                         "设A、B为集合，证明A∩B⊆A。")
        self.assertNotIn(old_question, repr(corrected["teaching"]["question_graph"]))
        # Even the error path must not substitute an unrelated old solution
        # merely because a current, different proof permits a full correction.
        body, _ = self.post(payload, FAILURE, expected_mode="full_solution", expected_status=503)
        self.assertNotIn(REFERENCE, repr(body))
        self.assertNotIn("solution_partial", body)

    def test_question_graph_uses_the_final_guarded_reply_as_solution_evidence(self):
        final_reply = "由子群的陪集构造划分，再根据每个陪集的大小得到整除结论"
        with patch.object(self.runtime, "audit_explicit_count_answer", return_value=final_reply):
            body, _ = self.post(self.payload("只给一个提示，先不要完整证明。"),
                                expected_mode="hint")
        self.assertEqual(body["reply"], final_reply)
        self.assertEqual(body["teaching"]["question_graph"]["sources"], {
            "question": QUESTIONS["zh-CN"], "solution": final_reply,
        })
        self.assertNotIn(MOCK_REPLY, repr(body["teaching"]["question_graph"]))

    def test_question_graph_preserves_the_explicit_historical_question_source(self):
        other_question = "设集合A={1,2,3}，B={2,3,4}，求集合A与集合B的交集和并集。"
        for language in ("zh-CN", "en"):
            with self.subTest(language=language):
                payload = self.payload("只给一个提示，不要完整答案。", language, history=[
                    {"role": "user", "content": QUESTIONS[language]},
                    {"role": "assistant", "content": "An earlier response."},
                    {"role": "user", "content": other_question},
                    {"role": "assistant", "content": "A response to the later problem."},
                ])
                body, _ = self.post(payload)
                sources = body["teaching"]["question_graph"]["sources"]
                self.assertEqual(sources["question"], QUESTIONS[language])
                self.assertEqual(sources["solution"], body["reply"])
                self.assertNotIn(other_question, repr(sources))

    def test_generated_question_graph_uses_its_own_question_and_hidden_answer(self):
        question = "设集合A={1,2,3}，B={2,3,4}，求A∪B与A∩B。"
        answer = "A∪B={1,2,3,4}；A∩B={2,3}"
        generated = {"ok": True, "reply": "【题目】\n" + question
                     + "\n[[WRONGBOOK_ANSWER]]" + answer + "[[/WRONGBOOK_ANSWER]]"}
        body, _ = self.post({
            "language": "zh-CN", "request_kind": "exercise",
            "messages": [
                {"role": "user", "content": QUESTIONS["zh-CN"]},
                {"role": "assistant", "content": "之前的群论题已经讲解完成"},
                {"role": "user", "content": "请出一道集合运算练习题，不要给出答案"},
            ],
        }, generated, exercise=True)
        graph = body["generated_teaching"]["question_graph"]
        self.assertEqual(graph["sources"], {
            "question": body["generated_question"], "solution": body["generated_answer"],
        })
        self.assertEqual(body["generated_question"], question)
        self.assertEqual(body["generated_answer"], answer)
        self.assertNotIn(answer, body["reply"])
        self.assertNotIn(QUESTIONS["zh-CN"], repr(graph))

    def test_failed_full_solution_does_not_promote_the_saved_answer_to_graph_evidence(self):
        body, _ = self.post(self.payload("请给出完整证明。"), FAILURE,
                            expected_mode="full_solution", reference_allowed=True)
        self.assertTrue(body["solution_partial"])
        graph = body["teaching"]["question_graph"]
        self.assertEqual(graph["sources"].get("solution", ""), "")
        self.assertNotIn(REFERENCE, repr(graph))

    def test_history_analysis_uses_each_actual_solution_for_the_same_question(self):
        question = "请讨论真值表与逻辑等价"
        solutions = ["利用真值表证明逻辑等价", "利用逻辑等价计算真值表"]
        response = self.client.post("/analyze-questions", json={"questions": [
            {"key": str(index), "text": question, "solution": solution}
            for index, solution in enumerate(solutions)
        ]})
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        graphs = [item["teaching"]["question_graph"] for item in response.get_json()["results"]]
        for graph, solution in zip(graphs, solutions):
            self.assertEqual(graph["sources"], {"question": question, "solution": solution})
        self.assertEqual({node["id"] for node in graphs[0]["nodes"]},
                         {node["id"] for node in graphs[1]["nodes"]})
        edge_pairs = lambda graph: {(edge["from"], edge["to"]) for edge in graph["edges"]}
        self.assertEqual(edge_pairs(graphs[0]), {("logic_truth_table", "logic_equivalence")})
        self.assertEqual(edge_pairs(graphs[1]), {("logic_equivalence", "logic_truth_table")})

    def test_history_analysis_ignores_non_text_solutions_and_bounds_text(self):
        question = "请讨论真值表与逻辑等价"
        prefix = "x" * self.runtime.MAX_MESSAGE_CHARS
        response = self.client.post("/analyze-questions", json={"questions": [
            {"key": "absent", "text": question},
            {"key": "object", "text": question, "solution": {"text": "利用真值表证明逻辑等价"}},
            {"key": "array", "text": question, "solution": ["利用真值表证明逻辑等价"]},
            {"key": "long", "text": question, "solution": prefix + "利用真值表证明逻辑等价"},
        ]})
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        graphs = {item["key"]: item["teaching"]["question_graph"]
                  for item in response.get_json()["results"]}
        for key in ("absent", "object", "array"):
            self.assertEqual(graphs[key]["sources"]["solution"], "")
            self.assertEqual(graphs[key]["edges"], [])
        self.assertEqual(graphs["long"]["sources"]["solution"], prefix)
        self.assertEqual(graphs["long"]["edges"], [])

    def semantic_teaching(self, question, solution, node_id="count_perm_comb"):
        """A transport fixture, not an assertion about a real model's accuracy."""
        node = next(node for node in self.runtime.KNOWLEDGE_GRAPH_DATA["nodes"] if node["id"] == node_id)
        teaching = dict(self.runtime.analyze_question(question))
        teaching.update({"category": node["category"], "knowledge_points": [node["name"]],
                         "focus_points": [node["name"]], "related_categories": [],
                         "classification_revision": "catalog-semantic-v2",
                         "classification_source": "AI语义复核", "classification_status": "semantic",
                         "needs_review": False, "confidence": "中"})
        teaching["question_graph"] = {
            "version": 1, "sources": {"question": question, "solution": solution},
            "classifier_revision": "catalog-semantic-v2", "classification_status": "semantic",
            "classification_source": "catalog_semantic", "needs_review": False,
            "nodes": [{"id": node_id, "usage": "assessed", "reason": "根据完整数学任务归入现有目录",
                       "evidence": [{"source": "question", "quote": question[:100]}]}], "edges": [],
        }
        return teaching

    def test_local_batch_does_not_invoke_the_semantic_model(self):
        question = "从10名学生中选出3名组成小组，有多少种不同选法"
        with patch.object(self.runtime, "classify_catalog_questions",
                          side_effect=AssertionError("Local classification must not call a remote review")) as review:
            response = self.client.post("/analyze-questions", json={"questions": [{"key": "q", "text": question}]})
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        review.assert_not_called()
        self.assertEqual(response.get_json()["results"][0]["teaching"]["question_graph"]["sources"],
                         {"question": question, "solution": ""})

    def test_catalog_review_installs_the_validated_graph_without_rebuilding_local_rules(self):
        question = "从10名学生中选出3名组成小组，有多少种不同选法"
        solution = "无序选择三个人，得到120种"
        expected = self.semantic_teaching(question, solution)

        def classify(entries, *, allow_remote):
            self.assertTrue(allow_remote)
            self.assertEqual(len(entries), 1)
            row_id, actual_question, actual_solution, local = entries[0]
            self.assertEqual((actual_question, actual_solution), (question, solution))
            self.assertEqual(local["question_graph"]["sources"], expected["question_graph"]["sources"])
            return {row_id: expected}

        with patch.object(self.runtime, "classify_catalog_questions", side_effect=classify) as review:
            response = self.client.post("/analyze-questions", json={"semantic_fallback": True,
                "questions": [{"key": "client-key", "text": question, "solution": solution}]})
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        review.assert_called_once()
        result = response.get_json()["results"][0]
        self.assertEqual(result["key"], "client-key")
        self.assertEqual(result["teaching"], expected)
        self.assertEqual(result["teaching"]["knowledge_points"], ["排列与组合"])

    def test_catalog_review_uses_unique_rows_when_client_keys_are_missing_or_repeated(self):
        questions = ["从8人中选择3人", "判断f(x)=x²是否存在相同输出", "", "使用真值表验证逻辑等价", "研究欧拉图"]
        solutions = ["答案为56", "f(1)=f(-1)", "", "", ""]
        node_ids = ["count_perm_comb", "function_injection", None, "logic_equivalence", "graph_euler"]
        expected = {}

        def classify(entries, *, allow_remote):
            self.assertTrue(allow_remote)
            self.assertEqual(len(entries), 4)
            self.assertEqual(len({entry[0] for entry in entries}), 4)
            for row_id, question, solution, _local in entries:
                index = questions.index(question)
                self.assertEqual(solution, solutions[index])
                expected[row_id] = self.semantic_teaching(question, solution, node_ids[index])
            return expected

        with patch.object(self.runtime, "classify_catalog_questions", side_effect=classify):
            response = self.client.post("/analyze-questions", json={"semantic_fallback": True, "questions": [
                {"key": "repeated", "text": questions[0], "solution": solutions[0]},
                {"key": "repeated", "text": questions[1], "solution": solutions[1]},
                {"text": ""}, {"text": questions[3]}, questions[4],
            ]})
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        results = response.get_json()["results"]
        self.assertEqual([item["key"] for item in results], ["repeated", "repeated", "", "", ""])
        self.assertIsNone(results[2]["teaching"])
        for index in (0, 1, 3, 4):
            graph = results[index]["teaching"]["question_graph"]
            self.assertEqual(graph["sources"], {"question": questions[index], "solution": solutions[index]})
            self.assertEqual([node["id"] for node in graph["nodes"]], [node_ids[index]])

    def test_catalog_review_never_installs_foreign_sources_or_catalog_nodes(self):
        question, solution = "从10人中选出3人", "120"
        for defect in ("question", "solution", "unknown_node", "node_type", "edge_endpoint", "version"):
            invalid = self.semantic_teaching(question, solution)
            graph = invalid["question_graph"]
            if defect in ("question", "solution"):
                graph["sources"][defect] = "another problem's private source"
            elif defect == "unknown_node":
                graph["nodes"][0]["id"] = "invented-outside-catalog"
            elif defect == "node_type":
                graph["nodes"][0]["id"] = []
            elif defect == "edge_endpoint":
                graph["edges"] = [{"from": "count_perm_comb", "to": "number_gcd"}]
            else:
                graph["version"] = 99
            with self.subTest(defect=defect), patch.object(self.runtime, "classify_catalog_questions",
                    side_effect=lambda entries, **_kwargs: {entries[0][0]: invalid}):
                response = self.client.post("/analyze-questions", json={"semantic_fallback": True,
                    "questions": [{"text": question, "solution": solution}]})
                self.addCleanup(response.close)
                self.assertEqual(response.status_code, 200)
                result = response.get_json()["results"][0]["teaching"]
                self.assertEqual(result["classification_status"], "invalid")
                self.assertTrue(result["needs_review"])
                self.assertTrue(result["question_graph"]["needs_review"])
                self.assertEqual(result["question_graph"]["sources"], {"question": question, "solution": solution})
                self.assertNotIn("invented-outside-catalog", repr(result))
                self.assertNotIn("another problem's private source", repr(result))

    def test_catalog_review_failure_returns_explicit_unavailable_local_result(self):
        question = "证明p∧q与q∧p等价"
        for failure in (RuntimeError("review unavailable"), None):
            options = {"side_effect": failure} if isinstance(failure, Exception) else {"return_value": {}}
            with self.subTest(failure=type(failure).__name__), patch.object(self.runtime, "classify_catalog_questions", **options):
                response = self.client.post("/analyze-questions", json={"semantic_fallback": True,
                    "questions": [{"text": question}]})
                self.addCleanup(response.close)
                self.assertEqual(response.status_code, 200)
                result = response.get_json()["results"][0]["teaching"]
                self.assertEqual(result["classification_status"], "unavailable")
                self.assertTrue(result["needs_review"])
                self.assertEqual(result["question_graph"]["sources"], {"question": question, "solution": ""})

    def test_catalog_review_quota_preserves_local_result_and_exact_cached_semantic_result(self):
        question, solution = "从10人中选出3人", "120"
        for cached in (False, True):
            def classify(entries, *, allow_remote):
                self.assertFalse(allow_remote)
                row_id, q, answer, local = entries[0]
                return {row_id: self.semantic_teaching(q, answer) if cached else
                        self.runtime.local_catalog_classification(local, q, answer, status="disabled")}
            with self.subTest(cached=cached), patch.object(self.runtime, "_check_rate_limit", return_value=False), patch.object(
                    self.runtime, "classify_catalog_questions", side_effect=classify) as review:
                response = self.client.post("/analyze-questions", json={"semantic_fallback": True,
                    "questions": [{"text": question, "solution": solution}]})
                self.addCleanup(response.close)
                self.assertEqual(response.status_code, 200)
                review.assert_called_once()
                result = response.get_json()["results"][0]["teaching"]
                self.assertEqual(result["classification_status"], "semantic" if cached else "rate_limited")
                self.assertEqual(result["needs_review"], not cached)
                self.assertEqual(result["question_graph"]["sources"], {"question": question, "solution": solution})


if __name__ == "__main__":
    unittest.main(verbosity=2)
