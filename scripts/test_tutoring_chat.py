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
        with patch.object(self.runtime, "ask_ai", return_value=result or SUCCESS) as ask:
            response = self.client.post("/chat", json=payload)
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

        _, context = self.post(payload, expected_mode="full_solution")
        self.assertEqual(context["category"], "集合与关系")
        self.assertIn(context["difficulty"], ("简单", "中等"))
        self.assertNotIn("reasoning_effort_override", context)
        # Even the error path must not substitute an unrelated old solution
        # merely because a current, different proof permits a full correction.
        body, _ = self.post(payload, FAILURE, expected_mode="full_solution", expected_status=503)
        self.assertNotIn(REFERENCE, repr(body))
        self.assertNotIn("solution_partial", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
