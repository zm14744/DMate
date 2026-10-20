"""Regression for previously observed *real* major-university graph-image faults.

No remote model is called. These tests verify fail-closed boundaries and
normalization logic; actual OCR accuracy is separately tested against originals
on the live deployment.
"""
import unittest

from graph_answer_integrity import (
    FLAG, detect_count_inconsistency, review_directed_graphs,
    protect_uncertain_graph_answer,
)

NJU_PRIMARY = (
    "图(1)：有向图，含5个顶点（a、b、c、d、e）。有向边为："
    "a→b，c→b，c→d，e→b，e→a。\n"
    "图(2)：有向图，含7个顶点（a、b、c、d、e、f、g）。有向边为："
    "a→b，a→g，b→d，d→c，g→f，f→e，e→d。\n"
    "图(3)：有向图，含5个顶点（a、b、c、d、e）。有向边为："
    "a→b，a→d，e→a，e→b，e→d，b→d，b→c，c→d。"
)
HKUST_PETERSEN = (
    "图1（无向简单图）：顶点共10个。边集（共15条）："
    + "、".join(
        "G1_v%s-G1_v%s" % (i,j)
        for i,j in [(1,9),(1,4),(1,2),(2,7),(2,8),(3,5),
                    (3,9),(3,1),(4,6),(4,10),(4,1),(5,6),
                    (5,7),(6,8),(7,1),(8,3),(9,10),(9,5),
                    (10,6),(10,8),(10,2),(2,5)]
    )
)
STANFORD_REQUEST = (
    "【题目文字】\n请看六顶点树的六幅不同图。\n"
    "【图形信息】\n"+FLAG+"\n图形识别结果未能逐图核对，请确认每张图的顶点与边。\n"
    "【我的要求】\n图中有几棵互不同构的六顶点树？"
)
STANFORD_WRONG_REPLY = (
    "设树有6个顶点，恰有2个顶点度为3，求叶子数。"
    "答案为4叶、2棵互不同构的树。"
)

def graph(idx, vertices, edges):
    return {"index":idx,"directed":True,"vertices":list(vertices),
            "edges":[list(e) for e in edges],"complete":True}


class UniversityGraphAnswerBoundaryTests(unittest.TestCase):
    def test_petersen_detects_22_pairs_versus_declared_15(self):
        err=detect_count_inconsistency(HKUST_PETERSEN)
        self.assertIsNotNone(err)
        self.assertIn("15",err)
        self.assertIn("22",err)

    def test_graph_count_matching_not_flagged(self):
        s="图1无向简单图：边集（共3条）：G1_v1-G1_v2、G1_v2-G1_v3、G1_v3-G1_v1"
        self.assertIsNone(detect_count_inconsistency(s))

    def test_unqualified_text_no_false_alarm(self):
        self.assertIsNone(detect_count_inconsistency("请数出本题图形中的全部边。"))

    def test_stanford_hallucinated_new_tree_problem_blocked(self):
        result=protect_uncertain_graph_answer(STANFORD_REQUEST,STANFORD_WRONG_REPLY)
        self.assertIsNotNone(result)
        self.assertIn("核对",result)
        self.assertNotIn("2棵",result)
        self.assertNotIn("4叶",result)

    def test_polyhedra_uncertain_does_not_invent_isomorphism(self):
        q=("【题目文字】\n识别正多面体\n【图形信息】\n"+FLAG
           +"\n【我的要求】\n请分别识别三张图，求各图的顶点数和边数。")
        result=protect_uncertain_graph_answer(q,"这两张图不是同构")
        self.assertIn("核对",result)
        self.assertNotIn("同构",result)

    def test_graph_flag_does_not_block_independent_algebra(self):
        q=("【题目文字】\n有一幅图和一个独立计算小问。"
           "\n【图形信息】\n"+FLAG
           +"\n【我的要求】\n只解无关的代数小问：2+2等于几？")
        self.assertIsNone(protect_uncertain_graph_answer(q,"4"))

    def test_confirmed_arrows_changed_nju_2_is_blocked(self):
        independent=[
            graph(1,"abcde",[("a","b"),("c","b"),("c","d"),("e","b"),("e","a")]),
            graph(2,"abcdefg",[("a","g"),("g","d"),("d","c"),
                                 ("b","f"),("f","e"),("e","b")]),
            graph(3,"abcde",[("a","b"),("a","d"),("e","a"),("e","b"),
                             ("e","d"),("b","d"),("b","c"),("c","d")]),
        ]
        text,issues,ok=review_directed_graphs(NJU_PRIMARY,independent)
        self.assertFalse(ok)
        self.assertIn(FLAG,text)
        self.assertTrue(any("图2" in issue for issue in issues))

    def test_directed_exact_agreement_normalized(self):
        t=("图(1)：有向图，含2个顶点（a、b）。有向边为：a→b。\n"
           "图(2)：有向图，含2个顶点（c、d）。有向边为：c→d。")
        data=[graph(1,"ab",[("a","b")]),graph(2,"cd",[("c","d")])]
        normalized,issues,ok=review_directed_graphs(t,data)
        self.assertTrue(ok)
        self.assertEqual(issues,[])
        self.assertIn("【有向边已独立核对】",normalized)
        self.assertIn("c→d",normalized)

    def test_directed_independent_incomplete_never_trusted(self):
        q="图(1)：有向图，含2个顶点a、b。有向边为：a→b。"
        data=[{"index":1,"directed":True,"vertices":["a","b"],
               "edges":[["a","b"]],"complete":False}]
        normalized,issues,ok=review_directed_graphs(q,data)
        self.assertFalse(ok)
        self.assertIn(FLAG,normalized)
        self.assertTrue(issues)

    def test_directed_duplicates_or_unknown_vertices_fail(self):
        q="图(1)：有向图，含2个顶点a、b。有向边为：a→b。"
        for edges in [[["a","b"],["a","b"]],[["a","x"]]]:
            normalized,issues,ok=review_directed_graphs(q,[{
                "index":1,"directed":True,"vertices":["a","b"],
                "edges":edges,"complete":True}])
            self.assertFalse(ok)
            self.assertIn(FLAG,normalized)

if __name__=="__main__":
    unittest.main()
