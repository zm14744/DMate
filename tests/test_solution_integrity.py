"""Regression of genuinely wrong 2026-10-20 university live answers."""
import unittest
from solution_integrity import (
    verify_exact_question, verify_finite_selection, verify_proposition_equivalence,
    verify_only_if_symbolization, verify_finite_relation, _prop_eval,
)

NJU = ("A、B、C、D中选2人出差。若A去，则C和D中至少去1人；"
       "B和C不能同时去；C去则D不去。共有多少种符合条件的选派？")
WRONG_REPLY = """AB不符合；AC符合；AD符合；BC不符合；BD符合；CD不符合。
结论共有4种：AC、AD、BD、CD。"""
LOGIC = "命题 (p→q) 与 (¬p∨q) 是否逻辑等价？"
WRONG_LOGIC = """题目有3小问：A=(p→q)∧(q→r), B=(p→r)，结论：不等价。"""
NJU_ONLY_IF = "命题p表示下雨，q表示带伞。将‘只有下雨我才带伞’符号化。"
SJTU_EQ = "在 A={1,2,3} 上定义 xRy 当且仅当 x+y ≠ 3。它是不是等价关系？请给出反例。"


class SolutionIntegrityTests(unittest.TestCase):
    def test_trip_corrects_conflicting_final_count(self):
        out=verify_exact_question(NJU,WRONG_REPLY)
        self.assertIsNotNone(out)
        self.assertIn("**3 种**",out)
        self.assertIn("AC、AD、BD",out)
        self.assertNotIn("CD",out)

    def test_trip_variant_recomputed_not_memorized(self):
        question=("A、B、C、D中选3人出差。若A去，则C和D中至少去1人；"
                  "B和C不能同时去；C去则D不去。共有多少种符合条件的选派？")
        self.assertIn("**1 种**",verify_finite_selection(question))
        self.assertIn("ABD",verify_finite_selection(question))

    def test_trip_extra_constraint_abstains(self):
        q=NJU.replace("共有多少种符合条件的选派？","另外B去则A不去。共有多少种符合条件的选派？")
        self.assertIsNone(verify_exact_question(q))

    def test_trip_no_hint_override(self):
        self.assertIsNone(verify_exact_question(NJU+"只给提示不要答案",WRONG_REPLY))

    def test_logic_corrects_invented_question(self):
        out=verify_exact_question("请直接给出最终答案并简要解释。"+LOGIC,WRONG_LOGIC)
        self.assertIsNotNone(out)
        self.assertIn("**逻辑等价**",out)
        self.assertNotIn("不逻辑等价",out)
        self.assertNotIn("r",out)

    def test_logic_witness_for_different_formulas(self):
        q="判断 (p→q) 与 (q→p) 是否逻辑等价？"
        out=verify_proposition_equivalence(q)
        self.assertIsNotNone(out)
        self.assertIn("不逻辑等价",out)
        self.assertIn("反例",out)

    def test_equiv_three_variables_and_nested(self):
        q="判断 (p→r)∨(q→r) 与 (p∧q)→r 是否逻辑等价？"
        self.assertIn("逻辑等价",verify_proposition_equivalence(q))
        self.assertNotIn("不逻辑等价",verify_proposition_equivalence(q))

    def test_logic_parser_covers_truth_table(self):
        self.assertEqual(_prop_eval("p→q",{"p":True,"q":False}),False)
        self.assertEqual(_prop_eval("¬p∨q",{"p":True,"q":False}),False)
        self.assertEqual(_prop_eval("(p→q)∧(q→r)",{"p":True,"q":True,"r":False}),False)

    def test_only_if_correct_and_no_invented_questions(self):
        out=verify_only_if_symbolization(NJU_ONLY_IF)
        self.assertIn(r"q\to p",out)
        self.assertIn(r"\neg p\to\neg q",out)
        self.assertNotIn("（2）",out)

    def test_relation_true_reflexive_and_symmetric_but_not_transitive(self):
        out=verify_finite_relation(SJTU_EQ)
        self.assertIn("不是等价关系",out)
        self.assertIn("自反性：成立",out)
        self.assertIn("对称性：成立",out)
        self.assertIn("传递性：不成立",out)
        self.assertIn("∉R",out)

    def test_original_nju_ocr_exact_but_model_returned_4(self):
        q=("【题目文字】\n第 6 题\n设 A, B 为有限集合。"
           "记 P(S) 为集合 S 的幂集，A ⊕ B 为 A 与 B 的对称差。"
           "已知 |A|=5，|P(B)|=512，|P(A ⊕ B)|=1024。"
           "求 |B|、|A∩B|、|A∪B|、|A\\B| 和 |B\\A|。"
           "\n【图形信息】\n\n【我的要求】\n只解第6题：求 |A∩B|，给出最终数值并说明计算依据。")
        out=verify_exact_question(q,"【答案】\n$|A\\cap B|=4$")
        self.assertIsNotNone(out)
        self.assertIn("|A∩B|=2",out)
        self.assertNotIn("=4",out)
        self.assertIn("512",out)
        self.assertIn("1024",out)
    def test_nju_set_other_cardinalities(self):
        q="已知 |A|=5, |P(B)|=512, |P(A△B)|=1024，求|A∩B|和|A∪B|。"
        answer=verify_exact_question(q)
        self.assertIn("|A∩B|=2",answer)
        self.assertIn("|A∪B|=12",answer)
    def test_set_numeric_variation_and_invalid_power_abstain(self):
        q="已知 |A|=3, |P(B)|=16, |P(A△B)|=8，求 |A∩B|。"
        out=verify_exact_question(q)
        self.assertIn("|A∩B|=2",out)
        self.assertIsNone(verify_exact_question(q.replace("16","15")))

    def test_unrelated_problems_not_rewritten(self):
        self.assertIsNone(verify_exact_question("求K5的度序列。"))
        self.assertIsNone(verify_exact_question("任意有限群G，请证明拉格朗日定理。"))
        self.assertIsNone(verify_exact_question("这张图片里有3道题：判断是否逻辑等价？"))

if __name__=="__main__":
    unittest.main()
