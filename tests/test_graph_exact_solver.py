"""Independent real-university graph correctness regression (not token matching).

These use actual confirmed original MIT 2005 6.042J nine-edge diagram
and original NJU 2019 three directed figures. Also test perturbations so
the solver cannot memorize those university IDs or fixed answers.
"""
import unittest
from graph_exact_solver import solve_certified_graph
from graph_answer_integrity import FLAG

def img(question,edges,prefix="【图形边集已二次核对】",n=8):
    vs="ABCDEFGH"[:n]
    visual=f"{prefix}\n图1为无向简单图，共{n}个顶点：{','.join(vs)}。边集合：" + "、".join(f"{u}-{v}" for u,v in edges) + "。"
    return "【题目文字】\n请看这张原图。\n【图形信息】\n"+visual+"\n【我的要求】\n"+question

MIT_GOLD=["AB","BC","BH","CD","CE","DE","EF","EH","FG"]
NJU_CERT=(
    "图(1)【有向边已独立核对】 顶点：a、b、c、d、e；边(5条)："
    "a→b、c→b、c→d、e→b、e→a\n"
    "图(2)【有向边已独立核对】 顶点：a、b、c、d、e、f、g；边(6条)："
    "a→g、g→d、d→c、b→f、f→e、e→b\n"
    "图(3)【有向边已独立核对】 顶点：a、b、c、d、e；边(8条)："
    "a→b、a→d、e→a、e→b、e→d、b→d、b→c、c→d"
)

class ExactCertifiedGraphTests(unittest.TestCase):
    def test_mit_original_a_h_graph_corrects_wrong_4_and_4(self):
        q=img("请直接求图的直径和色数并解释。",MIT_GOLD)
        result=solve_certified_graph(q,"错误：直径为4，色数4")
        self.assertIsNotNone(result)
        self.assertIn("直径",result)
        self.assertIn("**5**",result)
        self.assertIn("色数 **3**",result)
        self.assertNotIn("色数 **4**",result)

    def test_mit_not_certified_does_not_override(self):
        question=img("求直径与色数",MIT_GOLD,prefix="")
        self.assertIsNone(solve_certified_graph(question,"直径4 色数4"))
        self.assertIsNone(solve_certified_graph(question+FLAG,"直径4 色数4"))

    def test_mit_swapped_edge_chromatic_is_recomputed(self):
        original=img("求直径和色数",MIT_GOLD)
        modified=img("求直径和色数",MIT_GOLD+["BD","BE","AC"])
        r1=solve_certified_graph(original)
        r2=solve_certified_graph(modified)
        self.assertIn("色数 **3**",r1)
        self.assertIn("色数 **4**",r2)

    def test_chromatic_five_cycle_is_three(self):
        edges=["AB","BC","CD","DE","EA"]
        q=img("求该图色数",edges,n=5)
        self.assertIn("色数 **3**",solve_certified_graph(q))

    def test_disconnected_diameter_not_fabricated(self):
        edges=["AB","CD","EF","GH"]
        q=img("求图的直径",edges,n=8)
        r=solve_certified_graph(q)
        self.assertIn("不连通",r)
        self.assertIn("不存在有限",r)

    def test_four_cycle_eulerian_and_3_path_not_eulerian(self):
        c4=img("该图是不是欧拉图，有没有欧拉回路？",
               ["AB","BC","CD","DA"],n=4)
        path=img("该图是否存在欧拉回路？",["AB","BC","CD"],n=4)
        self.assertIn("存在欧拉回路",solve_certified_graph(c4))
        self.assertIn("没有欧拉回路",solve_certified_graph(path))

    def test_nju_all_three_original_directed_structures(self):
        q=("【题目文字】\n判断图(1)(2)(3)是否强连通，如果不是再判断弱连通。\n"
           "【图形信息】\n"+NJU_CERT+
           "\n【我的要求】\n判断三幅有向图是否强连通、弱连通，给答案。")
        reply=solve_certified_graph(q,"旧答案：三幅图都弱连通")
        self.assertIn("图(1)：不是强连通图，但属于弱连通图",reply)
        self.assertIn("图(2)：既不是强连通图，也不是弱连通图",reply)
        self.assertIn("图(3)：不是强连通图，但属于弱连通图",reply)

    def test_nju_reverse_all_edges_makes_no_different_connectivity(self):
        modified=NJU_CERT.replace("图(2)","图(5)")
        q=("【题目文字】\n连通性\n【图形信息】\n"+modified+
           "\n【我的要求】\n判断弱连通性")
        out=solve_certified_graph(q)
        self.assertIn("图(5)：既不是强连通图，也不是弱连通图",out)

    def test_digraph_strong_cycle_correct(self):
        s="图(1)【有向边已独立核对】 顶点：a、b、c；边(3条)：a→b、b→c、c→a"
        q="【题目文字】\n请看图。\n【图形信息】\n"+s+"\n【我的要求】\n是否强连通？"
        self.assertIn("图(1)：是强连通图",solve_certified_graph(q))

    def test_missing_arrows_abstains(self):
        s="图(1)【有向边已独立核对】 顶点：a、b、c；边(4条)：a→b、b→c、c→a"
        q="【题目文字】\n判断连通性\n【图形信息】\n"+s+"\n【我的要求】\n判断是否强连通"
        self.assertIsNone(solve_certified_graph(q))

    def test_unrelated_algebra_question_not_overridden(self):
        q=img("求 2+2 的计算结果",MIT_GOLD)
        self.assertIsNone(solve_certified_graph(q))

    def test_unaudited_original_sjtu_does_not_create_euler_answer(self):
        q="【题目文字】\n判断三幅图哪些是欧拉图。\n【图形信息】\n"
        q+="图a、图b、图c的部分边尚未确认。\n【我的要求】\n给出欧拉回路判断"
        self.assertIsNone(solve_certified_graph(q))

if __name__=="__main__":
    unittest.main()
