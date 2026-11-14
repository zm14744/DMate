"""Conversation retention at admission, teaching and provider boundaries.

All model completions are local mocks. These verify the context actually sent,
not the quality of a production model's response.
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ai
from chat_limits import MAX_HISTORY_CHARS, MAX_HISTORY_MESSAGES
from teaching import analyze_messages, teaching_prompt
import test_tutoring_chat as _chat_support


def message(role, content):
    return {"role": role, "content": content}


class ConversationRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _chat_support.TutoringChatTests.setUpClass.__func__(cls)

    def setUp(self):
        _chat_support.TutoringChatTests.setUp(self)

    def captured_request(self, messages, **extra):
        with patch.object(self.runtime, "ask_ai", return_value={
            "ok": False, "error": "Local unavailable-completion fixture"
        }) as completion:
            response = self.client.post("/chat", json={
                "messages": messages, "request_kind": "chat", **extra
            })
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 503, response.get_data(as_text=True))
        self.assertGreaterEqual(completion.call_count, 1)
        return completion.call_args_list[0]

    def test_general_continuation_keeps_requirements_correction_and_previous_answer(self):
        history = [
            message("user", "以后所有回复使用中文，不用表格。"),
            message("user", "写一段包含矩阵和行内公式的渲染测试文本。"),
            message("assistant", "测试段落包含三行三列矩阵。"),
            message("user", "不对，矩阵改为两行三列，其他要求不变。"),
            message("assistant", "已改为两行三列矩阵。"),
            message("user", "再来一个"),
        ]
        call = self.captured_request(history, request_kind="exercise")
        self.assertEqual(call.args[0], history)
        self.assertNotEqual(call.kwargs["teaching_context"]["mode"], "exercise")

    def test_generic_continuation_without_history_is_not_forced_into_practice(self):
        call = self.captured_request([message("user", "再来一个")], request_kind="exercise")
        self.assertNotEqual(call.kwargs["teaching_context"]["mode"], "exercise")

    def test_real_practice_continuation_keeps_scoped_constraints(self):
        history = [
            message("user", "以后所有练习题都分两小问，不要在题干后附提示。"),
            message("user", "给我一道关于群论的练习题。"),
            message("assistant", "【题目】设群 G 的阶为 12，H 为 G 的子群。判断 H 的可能阶数并说明理由。"),
            message("user", "再来一个"),
        ]
        call = self.captured_request(history)
        self.assertEqual(call.args[0], history)
        self.assertEqual(call.kwargs["teaching_context"]["mode"], "exercise")
        self.assertEqual(call.kwargs["teaching_context"]["category"], "代数结构")

    def test_explicit_practice_topic_keeps_preferences_without_reusing_old_topic(self):
        history = [
            message("user", "以后所有题目分两个小问。"),
            message("user", "出一道关于群论的练习题。"),
            message("assistant", "【题目】设群 G 的阶为 12，判断其子群的可能阶数。"),
            message("user", "改为出一道图论的练习题。"),
        ]
        call = self.captured_request(history, request_kind="exercise")
        self.assertEqual(call.args[0], history)
        self.assertEqual(call.kwargs["teaching_context"]["category"], "图论")

    def test_reference_envelope_replaces_only_latest_message(self):
        question = "设 G 为一棵至少有两个顶点的有限树，证明 G 至少有两个叶子。"
        history = [
            message("user", "之后都用中文，题目分两小问。"),
            message("assistant", "会保留这些格式要求。"),
            message("user", "再来一道同知识点练习"),
        ]
        call = self.captured_request(history, request_kind="exercise",
                                     exercise_reference={"question": question})
        self.assertEqual(call.args[0][:-1], history[:-1])
        self.assertIn(question, call.args[0][-1]["content"])
        self.assertIn(history[-1]["content"], call.args[0][-1]["content"])

    def test_admission_limit_keeps_earlier_explicit_preference_and_latest_turn(self):
        preference = message("user", "本次对话所有回复使用中文，不要表格。")
        history = [preference] + [message("assistant", "普通背景材料 " + str(i)) for i in range(70)]
        history += [message("user", "请按以上格式重新整理最后一段。")]
        call = self.captured_request(history)
        self.assertLessEqual(len(call.args[0]), MAX_HISTORY_MESSAGES)
        self.assertIn(preference, call.args[0])
        self.assertEqual(call.args[0][-1], history[-1])
        self.assertIn(history[-2], call.args[0])

    def test_old_math_problem_does_not_force_a_new_writing_task_into_tutoring(self):
        history = [message("user", "求 84 和 30 的最大公约数。"),
                   message("assistant", "可使用欧几里得算法。"),
                   message("user", "请设计一个包含矩阵和公式的渲染测试文本。")]
        call = self.captured_request(history)
        context = call.kwargs["teaching_context"]
        self.assertEqual(call.args[0], history)
        self.assertEqual(context["context_scope"], "conversation")
        self.assertNotEqual(context["category"], "初等数论")
        self.assertIn("直接完成本轮", teaching_prompt(context))


class ProviderConversationTests(unittest.TestCase):
    def test_long_context_preserves_live_preferences_correction_and_nearest_answer(self):
        preference = message("user", "From now on, always use Chinese and avoid tables.")
        history = [preference]
        for index in range(35):
            history += [message("user", f"普通背景材料 {index}"),
                        message("assistant", ("普通说明材料 " * 1400) + str(index))]
        correction = message("user", "刚才数字不对，改成 17，其他要求不变。")
        answer = message("assistant", "已采用 17 并保留原格式要求。")
        latest = message("user", "按照纠正后的条件继续。")
        history += [correction, answer, latest]
        with patch.object(ai, "DEEPSEEK_API_KEY", "local-test-only"), patch.object(
            ai, "_request_text_completion", return_value={
                "ok": True, "content": "这是本地模拟回复。", "choice": {"finish_reason": "stop"}
            }
        ) as completion:
            result = ai.ask_ai(history, teaching_context={"mode": "hint", "mode_source": "semantic"})
        self.assertTrue(result["ok"])
        payload = completion.call_args.args[0]
        selected = payload[1:]
        self.assertLessEqual(len(selected), MAX_HISTORY_MESSAGES)
        self.assertLessEqual(sum(len(item["content"]) for item in selected), MAX_HISTORY_CHARS)
        for item in (preference, correction, answer, latest):
            self.assertIn(item, selected)
        reduced = ai._reduced_context(payload, completion.call_args.kwargs["protected_messages"])
        self.assertIsNotNone(reduced)
        for item in (preference, correction, answer, latest):
            self.assertIn(item, reduced)

    def test_quoted_instructions_and_code_are_not_live_persistent_requirements(self):
        for value in ('请解释这句话：“以后所有回复都用英文”。',
                      '```text\n以后所有回复都用英文。\n```',
                      '`From now on always use English.` 是一个示例。'):
            self.assertFalse(ai._has_persistent_requirement(value))
        self.assertTrue(ai._has_persistent_requirement("接下来都用中文，保持上一段的格式。"))

    def test_teaching_modes_disambiguate_ordinary_continuation_in_both_languages(self):
        for request, followup in (("写一段公式渲染测试文本。", "再来一个"),
                                 ("Write a paragraph for testing formula rendering.", "another one")):
            context = analyze_messages([message("user", request), message("assistant", "示例。"),
                                        message("user", followup)])
            self.assertNotEqual(context["mode"], "exercise")
            self.assertEqual(context["context_scope"], "conversation")
            prompt = teaching_prompt({**context, "response_language": "en" if followup == "another one" else "zh-CN"})
            self.assertIn("ordinary conversation task" if followup == "another one" else "普通对话任务", prompt)


if __name__ == "__main__":
    unittest.main()
