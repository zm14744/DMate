import sys, unittest, math, itertools, fractions
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from university_answer_benchmark import validate_bank,gold,judge,extract,parse_number

class UniversityOracleTests(unittest.TestCase):
    def setUp(self):
        self.cases={c["id"]:c for c in validate_bank()}
    def test_gold_key_counts_independently(self):
        cs=self.cases
        self.assertEqual(gold(cs["MIT7-1b"]),math.comb(15,6))
        self.assertEqual(gold(cs["MIT7-2a"]),math.factorial(10)//(math.factorial(5)*2))
        self.assertEqual(gold(cs["MIT7-2g"]),sum(math.comb(15,k) for k in range(4)))
        self.assertEqual(gold(cs["MIT7-2h"]),sum(
            1 for i in range(1,301) if any(i%d==0 for d in (2,3,5))))
        self.assertEqual(gold(cs["B-4"]),
            math.comb(52,5)-math.comb(40,5)-12*math.comb(40,4))
        self.assertEqual(gold(cs["B-6"]),math.comb(103,3))
        self.assertEqual(gold(cs["V01"]),math.comb(13,5))
        self.assertEqual(gold(cs["V02"]),math.comb(9,4))
        self.assertEqual(gold(cs["V03"]),sum(
            1 for i in range(1,501) if any(i%d==0 for d in (2,3,5))))
        self.assertEqual(gold(cs["V04"]),math.comb(14,4))
        self.assertEqual(gold(cs["V05"]),math.comb(9,4))
        self.assertEqual(gold(cs["V10"]),fractions.Fraction(19,68))
        self.assertEqual(gold(cs["V11"]),next(
            x for x in range(31) if (17*x-5)%31==0))
        self.assertEqual(gold(cs["V12"]),math.comb(22,2))
        self.assertEqual(gold(cs["V19"]),2**(math.comb(4,2)+4))
    def test_never_grade_intermediate_correct_digit(self):
        c=self.cases["MIT7-1b"]
        verdict,v=judge(c,"中间有人写5005，但算完更正。\n【结果】5010")
        self.assertEqual(verdict,"ANSWER_WRONG")
    def test_no_missing_final_mark_faked_as_answer(self):
        c=self.cases["C-5d"]
        self.assertEqual(judge(c,"方差应该是24，理由是np(1-p)。")[0],
                         "FORMAT_UNSCORABLE")
    def test_wrong_boolean_not_confused_by_earlier_claim(self):
        c=self.cases["C-2a"]
        self.assertEqual(judge(c,"考虑真值条件，错误地推断为真。\n【结果】是")[0],
                         "ANSWER_WRONG")
    def test_exact_large_integer_and_fraction(self):
        c=self.cases["MIT7-2d"]
        self.assertEqual(judge(c,"【结果】26,075,972,546")[0],
                         "ANSWER_MATCH_NEEDS_PROOF_REVIEW")
        self.assertEqual(parse_number(r"\frac{27}{41}"),fractions.Fraction(27,41))
        self.assertEqual(parse_number("27/41"),fractions.Fraction(27,41))
    def test_correct_mathjax_final_fraction_is_valid(self):
        by=self.cases
        correct=r"【结果】\(\frac{27}{41}\)"
        self.assertEqual(judge(by["B-5b"],correct)[0],
                         "ANSWER_MATCH_NEEDS_PROOF_REVIEW")
        self.assertEqual(judge(by["B-5a"],r"【结果】\(\frac{41}{100}\)")[0],
                         "ANSWER_MATCH_NEEDS_PROOF_REVIEW")

    def test_no_unresolved_previous_question_in_standalone_bank(self):
        for c in self.cases.values():
            self.assertNotIn("上一题",c["question"],
              "A standalone test may not depend on previous API context: "+c["id"])

    def test_all_source_categories_disjoint(self):
        self.assertEqual(sum(c["category"]=="official_paraphrase"
                             for c in self.cases.values()),40)
        self.assertEqual(sum(c["category"]=="derived_variant"
                             for c in self.cases.values()),20)
if __name__=="__main__":unittest.main()
