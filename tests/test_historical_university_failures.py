"""Historical UNIVERSITY problem regressions from actual DMate live failures.

These are behavioral invariants; a green unit suite is not evidence that
an OCR picture was recognized correctly. Original picture end-to-end tests
remain separate and are explicitly attributed to source universities.
"""
import unittest
from unittest.mock import patch

from graph_answer_integrity import (
    FLAG, review_directed_graphs, review_single_undirected_graph,
    detect_count_inconsistency, protect_uncertain_graph_answer,
    is_scanned_graph_solution_request,
)
from graph_integrity import exact_isomorphism


class HistoricalUniversityFailureTests(unittest.TestCase):
    def test_mit_real_original_graph_cannot_gain_crossing_edges(self):
        # Original MIT A-H image independent manual edges, 9 not 10 or 11.
        primary=("图1无向图，共8个顶点。边集合："
                 "A-B、A-C、B-C、B-H、C-D、C-E、D-E、E-F、E-H、F-G。")
        correct=[["A","B"],["B","C"],["B","H"],["C","D"],["C","E"],
                 ["D","E"],["E","F"],["E","H"],["F","G"]]
        visual,issues,ok=review_single_undirected_graph(primary,[{
            "index":1,"directed":False,"vertices":list("ABCDEFGH"),
            "edges":correct,"complete":True
        }])
        self.assertFalse(ok)
        self.assertIn(FLAG,visual)
        self.assertTrue(issues)

    def test_nju_separated_directed_components_not_merged(self):
        first=("图(1)：有向图，顶点a、b，有向边为：a→b。\n"
               "图(2)：有向图，顶点a、b、c、d，有向边为：a→b、b→c、c→d。")
        second=[
            {"index":1,"directed":True,"vertices":["a","b"],
             "edges":[["a","b"]],"complete":True},
            {"index":2,"directed":True,"vertices":["a","b","c","d"],
             "edges":[["a","b"],["c","d"]],"complete":True},
        ]
        visual,issues,ok=review_directed_graphs(first,second)
        self.assertFalse(ok)
        self.assertIn(FLAG,visual)

    def test_sjtu_uncertain_euler_arrows_must_not_be_guessed(self):
        text=("【题目文字】\n判断欧拉回路\n【图形信息】\n"+FLAG
              +"\n方向无法确认\n【我的要求】\n三个有向图哪些存在欧拉回路？")
        result=protect_uncertain_graph_answer(text,"(a)是欧拉图，其他不是")
        self.assertIsNotNone(result)
        self.assertNotIn("其他不是",result)

    def test_stanford_uncertain_six_trees_do_not_generate_another_problem(self):
        text=("【题目文字】\n六个六顶点树图\n【图形信息】\n"+FLAG
              +"\n【我的要求】\n判断有几棵不同构的六顶点树")
        self.assertTrue(is_scanned_graph_solution_request(text))
        answer=protect_uncertain_graph_answer(text,"【题目】给出两棵树【答案】2")
        self.assertIsNotNone(answer)
        self.assertNotIn("【题目】",answer)

    def test_hkust_petersen_15_edges_must_have_15_unique_pairs(self):
        txt="边集（共15条）："+"、".join(f"G1_v{i}-G1_v{i+1}" for i in range(1,22))
        self.assertIsNotNone(detect_count_inconsistency(txt))

    def test_cornell_isomorphism_official_edge_sets(self):
        # Cornell 2016 final Q10 both 5 vertices / 9 edges: actual confirmed.
        left={"vertices":list("abcde"),"edges":[
            ["a","b"],["a","c"],["a","d"],["a","e"],
            ["b","c"],["b","d"],["b","e"],["c","d"],["d","e"]]}
        right={"vertices":list("vwxyz"),"edges":[
            ["v","w"],["v","x"],["v","y"],["v","z"],
            ["w","y"],["w","z"],["x","y"],["x","z"],["y","z"]]}
        mapping=exact_isomorphism(left,right)
        self.assertIsInstance(mapping,dict)
        self.assertEqual(len(mapping),5)

    def test_unsw_different_isomorphism_graphs_not_falsely_equated(self):
        left={"vertices":list("abcdef"),"edges":[
            ["a","b"],["b","e"],["b","c"],["b","d"],
            ["e","d"],["d","c"],["c","f"]]}
        right={"vertices":list("xyztuv"),"edges":[
            ["x","y"],["y","z"],["y","t"],["z","t"],
            ["t","u"],["z","v"]]}
        self.assertIsNone(exact_isomorphism(left,right))

    def test_india_k4_crossing_point_not_fifth_vertex(self):
        from graph_integrity import exact_isomorphism
        x={"vertices":list("abcd"),"edges":[
            ["a","b"],["a","c"],["a","d"],["b","c"],["b","d"],["c","d"]]}
        y={"vertices":list("wxyz"),"edges":[
            ["w","x"],["w","y"],["w","z"],["x","y"],["x","z"],["y","z"]]}
        self.assertIsInstance(exact_isomorphism(x,y),dict)

    def test_mit_logic_equivalence_is_not_a_new_question(self):
        from teaching import looks_like_exercise_request
        self.assertFalse(looks_like_exercise_request(
            "请直接给出最终答案并简要解释。命题 (p→q) 与 (¬p∨q) 是否逻辑等价？"))

    def test_nju_set_count_is_two_not_four(self):
        from solution_integrity import verify_exact_question
        text=(r"已知 |P(B)|=512，|P(A\triangle B)|=1024，"
              r"|A|=5。求 |A\cap B|，请给出完整答案。")
        result=verify_exact_question(text,"答案：4")
        self.assertIsNotNone(result)
        self.assertRegex(result,r"(?<!\d)2(?!\d)")

    def test_chat_endpoint_handles_existing_university_questions(self):
        import app
        flask=app.app.test_client()
        for question in (
            "请直接给出最终答案并简要解释。命题 (p→q) 与 (¬p∨q) 是否逻辑等价？",
            "请回答：路径 P5 有几条边？",
        ):
            with self.subTest(question=question),\
                    patch.object(app,"_check_rate_limit",return_value=True),\
                    patch.object(app,"ask_ai",return_value={
                        "ok":True,"reply":"问题已经解答，最终结果如下。"
                    }):
                result=flask.post("/chat",json={
                    "messages":[{"role":"user","content":question}]
                })
                self.assertNotEqual(result.status_code,500,result.get_data(as_text=True)[:450])
                self.assertTrue(result.is_json)

if __name__=="__main__":
    unittest.main()
