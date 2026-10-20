import unittest
from answer_context_guard import missing_previous_problem

class MissingContextTests(unittest.TestCase):
    def case(self,text):return [{"role":"user","content":text}]
    def test_missing_prior_bayes_data_never_guessed(self):
        q="在上一题的条件下，已知花死亡，朋友忘记浇花的条件概率是多少？请用最简分数。"
        self.assertTrue(missing_previous_problem(self.case(q)))
    def test_complete_current_bayes_problem_allowed(self):
        q="朋友忘记浇水概率0.3，不浇水枯死概率0.9，浇水枯死概率0.2。已知花死亡，求忘记浇花概率。"
        self.assertFalse(missing_previous_problem(self.case(q)))
    def test_normal_followup_has_real_history(self):
        q="在上一题的条件下求贝叶斯概率"
        self.assertFalse(missing_previous_problem([
            {"role":"user","content":"上一道题条件是P(A)=0.2"},
            {"role":"assistant","content":"已记录条件。"},
            {"role":"user","content":q}
        ]))
    def test_explicit_three_numbers_needs_no_previous_data(self):
        q="上一题给的概率为0.3，没浇水死亡率为0.9，浇水死亡率为0.2，求条件概率"
        self.assertFalse(missing_previous_problem(self.case(q)))
    def test_no_overblocking_unrelated_material(self):
        self.assertFalse(missing_previous_problem(self.case("求20本书选6本不相邻的方法数")))
if __name__=="__main__":unittest.main()
