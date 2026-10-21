"""Regression for textbook six-dot edge endpoint OCR and tree reasoning.

The supplied graph facts are fully enumerated. No assumption is made that
correct edge counts alone prove the pixels have been read correctly.
"""
import unittest
from graph_consistency import (analyze_labeled_graphs,
                               summarize_tree_question,
                               reconcile_vision_edges)

CORRECT = """下列图中，哪些是树？
【图形信息】
图1（G1）：无向图，6个顶点，标签 a、b、c、d、e、f。边：a-c,b-c,c-d,c-f,e-f。
图2（G2）：无向图，6个顶点，标签 a、b、c、d、e、f。边：a-c,a-f,b-e,d-f,e-f。
图3（G3）：无向图，6个顶点，标签 a、b、c、d、e、f。边：a-b,a-c,a-d,b-e,c-f,d-e。
图4（G4）：无向图，6个顶点，标签 a、b、c、d、e、f。边：a-f,b-d,b-e,c-e。
【我的要求】直接告诉答案
"""
WRONG_G3 = CORRECT.replace(
    "a-b,a-c,a-d,b-e,c-f,d-e",
    "a-b,a-d,a-e,b-c,c-f,d-e",
)

class GraphConsistencyTests(unittest.TestCase):
    def test_all_four_structures_and_tree_answer(self):
        gs = analyze_labeled_graphs(CORRECT)
        self.assertEqual(list(sorted(gs)), [1,2,3,4])
        self.assertEqual([gs[i]["edge_count"] for i in (1,2,3,4)], [5,5,6,4])
        self.assertEqual([gs[i]["components"] for i in (1,2,3,4)], [1,1,1,2])
        self.assertEqual([gs[i]["tree"] for i in (1,2,3,4)], [True,True,False,False])
        summary = summarize_tree_question(CORRECT)
        self.assertIn("G2: 顶点6个、边5条、连通分量1个，是树", summary)
        self.assertIn("G4: 顶点6个、边4条、连通分量2个，不是树", summary)
        self.assertTrue(summary.endswith("G1、G2。"))

    def test_wrong_g3_edge_assignment_still_not_tree(self):
        gs=analyze_labeled_graphs(WRONG_G3)
        self.assertEqual(gs[3]["edge_count"],6)
        self.assertFalse(gs[3]["tree"])
        self.assertEqual(gs[3]["components"],1)
        self.assertEqual(summarize_tree_question(WRONG_G3).splitlines()[-1],
                         "因此是树的图：G1、G2。")

    def test_missing_label_or_isolated_vertex_not_guessed(self):
        bad="""下列图中，哪些是树？
图1（G1）：顶点6个，边：a-b,b-c,c-d。
图2（G2）：顶点a、b、c、d。边：a-b,b-c。"""
        self.assertEqual(list(analyze_labeled_graphs(bad)), [2])
        self.assertEqual(analyze_labeled_graphs(bad)[2]["components"], 2)
        self.assertFalse(analyze_labeled_graphs(bad)[2]["tree"])
        self.assertEqual(summarize_tree_question(bad),"")

    def test_multigraph_not_coerced_to_simple_tree(self):
        text="""哪些是树？图1（G1）：顶点 a、b、c。边：a-b,a-b,b-c。
图2（G2）：顶点 a、b、c。边：a-b,b-c。"""
        self.assertNotIn(1, analyze_labeled_graphs(text))
        self.assertEqual(summarize_tree_question(text),"")

    def test_vision_edges_reconciled_only_under_strict_grid(self):
        coords=[(.15,.1),(.8,.1),(.15,.48),(.8,.48),(.15,.91),(.8,.91)]
        graphs=[]
        pairs=[[(0,2),(1,2),(2,3),(2,5),(4,5)],
               [(0,2),(0,5),(1,4),(3,5),(4,5)],
               [(0,1),(0,2),(0,3),(1,4),(2,5),(3,4)],
               [(0,5),(1,3),(1,4),(2,4)]]
        for edges in pairs:
            graphs.append({"confidence":"high","uncertain_edges":[],
                 "vertices":[{"id":f"v{i+1}","x":x,"y":y}
                             for i,(x,y) in enumerate(coords)],
                 "edges":[[f"v{a+1}",f"v{b+1}"] for a,b in edges]})
        updated,warnings=reconcile_vision_edges(WRONG_G3,graphs)
        self.assertIn("图3（G3）",updated)
        self.assertIn("a-c",updated)
        self.assertIn("b-e",updated)
        self.assertNotIn("a-e",updated)
        self.assertNotIn("b-c,c-f",updated)
        self.assertEqual(len(warnings),1,warnings)
        self.assertIn("G3",warnings[0])
        self.assertEqual([s["tree"] for _,s in sorted(analyze_labeled_graphs(updated).items())],
                         [True,True,False,False])

    def test_real_four_graph_caption_and_duplicate_edge_are_pixel_corrected(self):
        # Actual failure format: 图 G2：... 边为：... ; the old parser
        # only understood 图2（G2）：... 边：... and never ran CV correction.
        cv_edges = [
            [(0, 2), (1, 2), (2, 3), (2, 5), (4, 5)],
            [(0, 2), (0, 5), (1, 4), (3, 5), (4, 5)],
            [(0, 1), (0, 2), (0, 3), (1, 4), (2, 5), (3, 4)],
            [(0, 5), (1, 3), (1, 4), (2, 4)]
        ]
        coords = [(.1, .1), (.8, .1), (.1, .48), (.8, .48),
                  (.1, .9), (.8, .9)]
        graphs = [
            {"confidence": "high", "uncertain_edges": [],
             "vertices": [{"id": f"v{i+1}", "x": x, "y": y}
                          for i, (x, y) in enumerate(coords)],
             "edges": [[f"v{a+1}", f"v{b+1}"] for a, b in edges]}
            for edges in cv_edges
        ]
        import re
        text = re.sub(r"图([1-4])（G[1-4]）", r"图 G\\1", CORRECT)
        text = text.replace("。边：", "。边为：")
        text = text.replace("a-c,a-f,b-e,d-f,e-f",
                            "a-c,a-f,b-e,b-f,d-f,e-f")
        text = text.replace("a-b,a-c,a-d,b-e,c-f,d-e",
                            "a-b,a-c,a-d,b-e,c-f,d-e,e-d")
        checked, warnings = reconcile_vision_edges(text, graphs)
        self.assertEqual(len(warnings), 2, warnings)
        actual = analyze_labeled_graphs(checked)
        self.assertEqual(set(actual), {1, 2, 3, 4})
        self.assertEqual([actual[i]["edge_count"] for i in range(1, 5)],
                         [5, 5, 6, 4])
        self.assertNotIn(("b", "f"), actual[2]["edges"])
        self.assertEqual(actual[3]["edges"].count(("d", "e")), 1)

    def test_partial_or_irregular_geometry_does_not_override_vision(self):
        base={"confidence":"partial","uncertain_edges":[],
             "vertices":[{"id":f"v{i+1}","x":i/7,"y":i/7} for i in range(6)],
             "edges":[["v1","v2"]]}
        result,warnings=reconcile_vision_edges(WRONG_G3,[base]*4)
        self.assertEqual(result,WRONG_G3)
        self.assertEqual(warnings,[])


if __name__=="__main__":
    unittest.main()
