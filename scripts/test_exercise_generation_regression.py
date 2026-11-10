"""Regression tests for generated finite-relation practice questions.

Run: python -m unittest discover -s scripts -p 'test_exercise_generation_regression.py' -v
"""

import unittest
from pathlib import Path

from exercise_intent import classify_exercise_request
from exercise_relation_check import (
    is_routine_small_relation_question,
    verify_relation_closure_count,
)
from teaching import analyze_question


SCREENSHOT_RELATION = r"""设集合 \(A = \{1,2,3,4\}\)，\(A\) 上的二元关系
\(R = \{(1,2),(2,3),(3,4),(4,1)\}\)。

(1) 写出 \(R\) 的关系矩阵 \(M_R\)，并求复合关系 \(R^2=R\circ R\) 的关系矩阵 \(M_{R^2}\)；
(2) 判断 \(R\) 是否具有自反性、对称性、传递性，并说明理由；
(3) 求 \(R\) 的传递闭包 \(t(R)\) 所含的有序对个数。"""


class ExerciseGenerationRegressionTests(unittest.TestCase):
    def test_random_request_recognized_as_generation(self):
        result = classify_exercise_request("随便出一道题目")
        self.assertTrue(result["is_exercise"])
        self.assertTrue(result["explicit"])

    def test_screenshot_is_not_a_hard_structural_problem(self):
        self.assertTrue(is_routine_small_relation_question(SCREENSHOT_RELATION, 3))
        self.assertEqual(analyze_question(SCREENSHOT_RELATION)["difficulty"], "中等")

    def test_exact_transitive_closure_cardinality(self):
        self.assertIs(
            verify_relation_closure_count(
                SCREENSHOT_RELATION, "(1) 矩阵结果\n(2) 非自反、非对称、非传递\n(3) 16"
            ),
            True,
        )
        self.assertIs(
            verify_relation_closure_count(
                SCREENSHOT_RELATION, "(1) 矩阵结果\n(2) 非自反、非对称、非传递\n(3) 15"
            ),
            False,
        )

    def test_does_not_guess_unparseable_answer(self):
        self.assertIsNone(
            verify_relation_closure_count(SCREENSHOT_RELATION, "(3) t(R) = A×A")
        )
        self.assertIsNone(
            verify_relation_closure_count(
                "证明任意有限集合上的关系的传递闭包满足传递性。",
                "证毕",
            )
        )

    def test_rejects_pairs_outside_the_declared_universe(self):
        bad_question = SCREENSHOT_RELATION.replace("(4,1)", "(4,9)")
        self.assertIs(verify_relation_closure_count(
            bad_question, "(1) ...\n(2) ...\n(3) 16"
        ), False)

    def test_not_downrating_real_proof_or_optimization_tasks(self):
        advanced = SCREENSHOT_RELATION + "\n证明一般情形的上界并构造达到极值的关系。"
        self.assertFalse(is_routine_small_relation_question(advanced, 3))

    def test_server_consistency_guard_invokes_relation_verifier(self):
        app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("closure_consistency = verify_relation_closure_count(text, value)", app_source)
        self.assertIn("if closure_consistency is False:", app_source)


if __name__ == "__main__":
    unittest.main()
