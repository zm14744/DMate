"""University problem-solving requests must never route into practice generation.

A real MIT X06 logic equivalence benchmark received HTTP 502 from
_exercise_problem_complete() because "给出最终答案...命题" incorrectly matched
the broad 出...题 generator pattern. This checks general discrete-math tasks
and explicitly requested new exercises separately.
"""
import unittest
import ast
from pathlib import Path
from teaching import looks_like_exercise_request
from graph_answer_integrity import is_scanned_graph_solution_request


class UniversitySolutionIntentTests(unittest.TestCase):
    def test_mit_x06_logic_equivalence_is_existing_question(self):
        prompt=("请直接给出最终答案并简要解释。"
                "命题 (p→q) 与 (¬p∨q) 是否逻辑等价？")
        self.assertFalse(looks_like_exercise_request(prompt))

    def test_columbia_and_berkeley_solution_prompts_do_not_generate(self):
        for request in [
            "请直接给出最终答案并简要解释。用扩展欧几里得算法求 x,y 使 44x+17y=1。",
            "请直接给出最终答案并简要解释。集合 {1,2,3} 上共有多少个等价关系？",
            "判断命题 p→q 和 ¬p∨q 是否等价。",
            "直接给出答案，说明 K_{3,3} 是否有欧拉回路。",
            "请解答这道离散数学题并给出完整解析。",
        ]:
            self.assertFalse(looks_like_exercise_request(request),request)

    def test_real_practice_generation_requests_remain_supported(self):
        for request in [
            "给我出一道图论题",
            "请出一道离散数学题并给出答案",
            "再来一道难点的题",
            "生成两道逻辑等价判断练习",
            "给我一道题",
        ]:
            self.assertTrue(looks_like_exercise_request(request),request)

    def test_chat_user_text_initialized_before_request_kind_classification(self):
        # This caught a real production-wide HTML HTTP500, not an OCR error.
        # The current user question must be initialized on the ordinary route
        # even when the frontend sends NO question_context (usual REST calls).
        source=Path(__file__).resolve().parents[1].joinpath("app.py").read_text(encoding="utf-8")
        module=ast.parse(source)
        fn=next(x for x in module.body if isinstance(x,ast.FunctionDef) and x.name=="chat")
        direct={
            target.id:i
            for i,node in enumerate(fn.body)
            if isinstance(node,ast.Assign)
            for target in node.targets
            if isinstance(target,ast.Name)
            for _ in [0]
        }
        self.assertIn("current_user_content",direct)
        self.assertIn("server_detected_exercise",direct)
        self.assertLess(direct["current_user_content"],direct["server_detected_exercise"])

    def test_original_nju_image_not_quiz(self):
        text=("【题目文字】\n判断图是否有欧拉回路。\n"
              "【图形信息】\n图1的边集\n"
              "【我的要求】\n请直接给出答案，先判断欧拉图。")
        self.assertTrue(is_scanned_graph_solution_request(text))


if __name__=="__main__":
    unittest.main()
