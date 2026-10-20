import unittest
from math_answer_guard import separate_selection_value,audit_explicit_count_answer

class MathAnswerGuardTests(unittest.TestCase):
    def test_mit_true_exam_nonaligned_20_6(self):
        q=("20本书按顺序排放，选择6本且任意两本不相邻，"
           "请直接给出答案并说明。最后一行必须写【结果】整数。")
        self.assertEqual(separate_selection_value(q),(20,6,5005))
        bad=("把选出的6本书间至少插5本，剩余9本分配。\n"
             "【结果】2002")
        corrected=audit_explicit_count_answer(q,bad)
        self.assertIn("【结果】5005",corrected)
        self.assertNotIn("2002",corrected)
    def test_image_english_two_subquestions_correction(self):
        q=("There are 20 books arranged in a row. (a) Show bijection "
           "between selecting 6 with no two adjacent and a 15-bit string. "
           "(b) How many choices? 请给出最终答案并证明。【结果】")
        out=audit_explicit_count_answer(q,"【结果】2002")
        self.assertIn("双射",out)
        self.assertIn("【结果】5005",out)
    def test_derived_change_parameter(self):
        q="有17本排列的书，选出5本，任意两本互不相邻。请给出最终答案。【结果】"
        self.assertIn("【结果】1287",audit_explicit_count_answer(q,"【结果】10"))
    def test_do_not_override_non_count_or_hint(self):
        wrong="【结果】2002"
        self.assertEqual(audit_explicit_count_answer(
            "从20本书选6本，但必须相邻。请给出答案。【结果】",wrong),wrong)
        self.assertEqual(audit_explicit_count_answer(
            "从20本书选6本且互不相邻。只给提示",wrong),wrong)
        self.assertEqual(audit_explicit_count_answer(
            "求RSA模21密码4，私钥指数5的明文。【结果】",wrong),wrong)
    def test_no_result_retains_hint(self):
        q="20本书中选6本，任意两本不相邻。请直接给出答案。"
        self.assertEqual(audit_explicit_count_answer(q,"想想隔板法"),"想想隔板法")
    def test_correct_answer_unchanged(self):
        q="从20本书选出6本不相邻，求多少种方法？"
        r="因为组合数C(15,6)=5005。\n【结果】5005"
        self.assertEqual(audit_explicit_count_answer(q,r),r)
    def test_mit_ocr_correct_bananarama_wrong_solution(self):
        question=("Problem 2. (a) In how many different ways can the letters "
                  "in the name of the popular 1980's band BANANARAMA "
                  "be arranged?\n【我的要求】只解(a)题，给出最终答案【结果】")
        wrong=("BANANARAMA一共有11个字母，其中5个A，2个N。\n"
               "答案为11!/(5!2!)=166320。\n【结果】166320")
        corrected=audit_explicit_count_answer(question,wrong)
        self.assertIn("共 10 个字母",corrected)
        self.assertIn("【结果】15120",corrected)
        self.assertNotIn("166320",corrected)
    def test_word_permutation_count_unrelated_guard(self):
        q="单词 MISSISSIPPI 的字母可形成多少种不同排列？请给出最终答案【结果】"
        correct=audit_explicit_count_answer(q,"【结果】34650")
        self.assertEqual(correct,"【结果】34650")
        bad=audit_explicit_count_answer(q,"【结果】39916800")
        self.assertIn("【结果】34650",bad)
        self.assertEqual(audit_explicit_count_answer(
            "4个顶点的图中字母 BANANARAMA 代表一个边名，求最小生成树【结果】",
            "【结果】999"),"【结果】999")
    def test_letter_permutation_ambiguous_remains_original(self):
        original="【结果】10"
        self.assertEqual(audit_explicit_count_answer(
            "比较单词 BANANA 和 BANANARAMA 这两个字符串的排列数【结果】",original),original)
        self.assertEqual(audit_explicit_count_answer(
            "单词BANANARAMA中相同的字母不得相邻，求排列数【结果】",original),original)

    def test_correct_final_but_false_letter_count_is_rewritten(self):
        q=("Problem 2 (a): letters in popular band BANANARAMA may "
           "be arranged in how many different ways? 请给出最终答案【结果】")
        false_proof=("BANANARAMA 共有 \(11\) 个字母，"
                     "所以 11! / (5! × 2!)=15120。\n【结果】15120")
        out=audit_explicit_count_answer(q,false_proof)
        self.assertIn("共 10 个字母",out)
        self.assertNotIn("11!",out)
        self.assertIn("【结果】15120",out)
    def test_scanned_exam_other_selected_part_must_not_be_overridden(self):
        q=("Problem 2 (a) rearrange the letters of BANANARAMA; "
           "(b) count paths in 3D grid.\n【我的要求】只解(b)题，给出最终答案【结果】")
        answer="【结果】123"
        self.assertEqual(audit_explicit_count_answer(q,answer),answer)
        books=("20本书选出6本互不相邻。"
               "(a) 证明选取与01串双射。(b)求选取总数。"
               "\n【我的要求】只解(a)题，给出最终答案【结果】")
        self.assertEqual(audit_explicit_count_answer(books,answer),answer)

    def test_normal_user_answers_without_benchmark_marker(self):
        books="从20本排列的书中选出6本，任意两本不相邻，求多少种选择？"
        result=audit_explicit_count_answer(
            books,"根据组合数得出结果。\n因此共有 **2002** 种方法。")
        self.assertIn("【结果】5005",result)
        letters=("BANANARAMA 的字母可进行多少种不同排列？"
                 "请直接给出最终答案。")
        result=audit_explicit_count_answer(
            letters,"共有10个字母，但错误算成11!。\n最终答案：**166320**。")
        self.assertIn("【结果】15120",result)
        self.assertNotIn("166320",result)
    def test_no_proof_digit_mining(self):
        q="从20本书选出6本且不相邻，求方案数。"
        only_intermediate=("使用组合数求解。\n"
                           "计算需要先知道15个位置如何选6个。\n"
                           "下一步继续计算。")
        self.assertEqual(audit_explicit_count_answer(q,only_intermediate),
                         only_intermediate)

    def test_zero_options(self):
        q="5本书按顺序放，选出4本且互不相邻，有多少种选择？"
        self.assertEqual(separate_selection_value(q),(5,4,0))
if __name__=="__main__":
    unittest.main()
