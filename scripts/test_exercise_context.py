"""Conversation-aware exercise intent, without model calls."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exercise_intent import classify_exercise_request, is_generic_continuation, resolve_exercise_request


def history(origin, middle, latest="再来一个"):
    messages = [{"role": "user", "content": origin}, {"role": "assistant", "content": "上一轮完整回答"}]
    for text in middle:
        messages.extend([{"role": "user", "content": text}, {"role": "assistant", "content": "更新后的回答"}])
    messages.append({"role": "user", "content": latest})
    return messages


class ExerciseContextTests(unittest.TestCase):
    def test_generic_continuation_recognizes_constraints_but_not_explicit_new_exercise(self):
        for text in ("再来一个", "再来一个，改用英文", "换一个", "Another one", "One more, use a table"):
            with self.subTest(text=text):
                self.assertTrue(is_generic_continuation(text))
        self.assertFalse(is_generic_continuation("再来一个，给我一道图论题"))
        self.assertFalse(is_generic_continuation("再来一道题"))

    def test_ordinary_task_survives_unlisted_intermediate_formatting_requests(self):
        for origin in ("请写一段公式渲染测试文本。", "什么是欧拉图？", "Please write a Python example."):
            for middle in (["请说详细一点"], ["用表格", "把第二段缩短"], ["能不能再具体些"]):
                with self.subTest(origin=origin, middle=middle):
                    self.assertFalse(resolve_exercise_request("再来一个", history(origin, middle))["is_exercise"])

    def test_real_exercise_survives_unlisted_intermediate_formatting_requests(self):
        for origin in ("出一道图论题", "设整数 n 为奇数，证明它的平方为奇数。"):
            for middle in (["请说详细一点"], ["用表格", "把第二段缩短"], ["能不能再具体些"]):
                with self.subTest(origin=origin, middle=middle):
                    result = resolve_exercise_request("再来一个", history(origin, middle))
                    self.assertTrue(result["is_exercise"])
                    self.assertFalse(result["explicit"])

    def test_explicit_later_task_replaces_an_older_exercise_context(self):
        messages = history("出一道图论题", ["请生成一段排版测试文字。", "用表格"])
        self.assertFalse(resolve_exercise_request("再来一个", messages)["is_exercise"])

    def test_explicit_exercise_commands_keep_their_existing_meaning(self):
        for text in ("给我一道困难的图论题", "再来一道题", "下一题", "Give me a proof exercise."):
            with self.subTest(text=text):
                self.assertEqual(resolve_exercise_request(text, history("请写一段文字", [])), classify_exercise_request(text))
        self.assertFalse(resolve_exercise_request("再来一个", [])["is_exercise"])


if __name__ == "__main__":
    unittest.main()
