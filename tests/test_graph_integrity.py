"""Regression tests for Cornell CS2800 2016 final Q10 and other graph tasks."""
import unittest
from graph_integrity import (
    parse_diagrams, exact_isomorphism, answer_graph_isomorphism,
    review_graph_transcriptions, FLAG, OK_MARKER,
)

GOLD = """Are the two graphs below isomorphic? 请判断是否同构并给出双射。
【图形信息】
图1（左图）：无向图，含5个顶点，顶点标签分别为a、b、c、d、e。边连接关系为：a-b, a-c, a-d, a-e, b-c, b-d, b-e, c-d, d-e。
图2（右图）：无向图，含5个顶点，顶点标签分别为v、w、x、y、z。边连接关系为：v-w, v-x, v-y, v-z, w-y, w-z, x-y, x-z, y-z。
"""
BAD = """Are the two graphs below isomorphic?
【图形信息】
图1（左图）：无向图，含5个顶点，顶点标签分别为a、b、c、d、e，位置分布为：a左下、b左上、c正上方、d右上、e右下。边连接关系为：a-b, b-c, c-d, d-e, a-e, b-d, a-d, c-a（注意：c-a为弧线边，与其他单边不同）。
图2（右图）：无向图，含5个顶点，顶点标签分别为v、w、x、y、z，位置分布为：v左下、w左上、x右下、y右上、z中央。边连接关系为：v-w, w-y, y-x, x-v, v-y, w-x, w-z, y-z, x-z, w-y（说明：w-y有两条边，一条为直线边，一条为从w上方绕过到y的弧线边）。
"""
AUDIT = [
    {"index": 1, "directed": False, "complete": True,
     "vertices": list("abcde"),
     "edges": [list(e) for e in ("ab", "ac", "ad", "ae", "bc", "bd", "be", "cd", "de")]},
    {"index": 2, "directed": False, "complete": True,
     "vertices": list("vwxyz"),
     "edges": [list(e) for e in ("vw", "vx", "vy", "vz", "wy", "wz", "xy", "xz", "yz")]},
]


class GraphIntegrityTests(unittest.TestCase):
    def test_cornell_original_full_graph_is_isomorphic(self):
        graphs = parse_diagrams(GOLD)
        self.assertEqual(set(graphs), {1, 2})
        self.assertEqual([len(graphs[n]["edges"]) for n in (1,2)], [9,9])
        mapping = exact_isomorphism(graphs[1], graphs[2])
        self.assertIsInstance(mapping, dict)
        self.assertEqual(set(mapping.values()), set("vwxyz"))
        left = {tuple(sorted([mapping[u],mapping[v]])) for u,v in graphs[1]["edges"]}
        right = {tuple(sorted(edge)) for edge in graphs[2]["edges"]}
        self.assertEqual(left,right)

    def test_false_edges_in_live_vision_are_detected(self):
        graphs = parse_diagrams(BAD)
        self.assertEqual(set(graphs), {1,2})
        self.assertEqual(len(graphs[1]["edges"]), 8)
        corrected, warnings, verified = review_graph_transcriptions(BAD, AUDIT)
        self.assertFalse(verified)
        self.assertIn(FLAG, corrected)
        self.assertTrue(warnings)
        self.assertIn("无法可靠判断", answer_graph_isomorphism(corrected + "\n请判断同构"))

    def test_matching_independent_edges_get_deterministic_correct_answer(self):
        corrected, warnings, verified = review_graph_transcriptions(GOLD.split("【图形信息】")[1], AUDIT)
        self.assertTrue(verified,(corrected,warnings))
        text = "下列两图是否同构？\n【图形信息】"+corrected
        answer=answer_graph_isomorphism(text)
        self.assertIn("两图同构",answer)
        self.assertIn("↦",answer)
        self.assertNotIn("不同构",answer)
        self.assertIn(OK_MARKER,corrected)

    def test_actual_live_curly_edge_notation_parses_and_is_flagged(self):
        live = """Are the two graphs below isomorphic?
【图形信息】
图1（左图）：无向图。顶点集合：{a, b, c, d, e}。顶点位置：c在上方。边集合：{b,c}, {c,d}, {b,d}, {b,e}, {a,d}, {a,e}, {a,b}, {d,e}, {a,c}。顶点度数：a:3。
图2（右图）：无向图。顶点集合：{v, w, x, y, z}。顶点位置：z在中心。边集合：{w,y}, {w,z}, {w,x}, {v,z}, {v,y}, {v,x}, {x,y}, {w,v}。顶点度数：v:4。
"""
        parsed=parse_diagrams(live)
        self.assertEqual(set(parsed),{1,2})
        self.assertEqual([len(parsed[i]["edges"]) for i in (1,2)],[9,8])
        text,warnings,verified=review_graph_transcriptions(live,AUDIT)
        self.assertFalse(verified)
        self.assertIn(FLAG,text)
        self.assertTrue(warnings)

    def test_verified_graph_has_no_untrusted_degree_prose(self):
        corrected,warnings,verified=review_graph_transcriptions(
            GOLD.split("【图形信息】")[1].replace("边连接关系为", "边连接关系为"),
            AUDIT
        )
        self.assertTrue(verified)
        self.assertNotIn("顶点度数",corrected)
        self.assertIn("图2（G2）",corrected)
        self.assertIn("v-y",corrected)

    def test_audit_incomplete_never_asserts_edges(self):
        for variant in (
            [dict(AUDIT[0],complete=False),AUDIT[1]],
            AUDIT[:1],
            [{**AUDIT[0],"directed":True},AUDIT[1]],
        ):
            corrected, warnings, verified = review_graph_transcriptions(GOLD,variant)
            self.assertFalse(verified)
            self.assertIn(FLAG,corrected)
            self.assertTrue(warnings)

    def test_identical_degrees_are_not_enough(self):
        # Two connected 3-regular graphs on six vertices:
        # K_{3,3} is bipartite, triangular prism has 3-cycles.
        left={"vertices":list("abcdef"),
              "edges":[list(e) for e in ("ad","ae","af","bd","be","bf","cd","ce","cf")]}
        right={"vertices":list("uvwxyz"),
               "edges":[list(e) for e in ("uv","vw","wu","xy","yz","zx","ux","vy","wz")]}
        self.assertIsNone(exact_isomorphism(left,right))

    def test_ordinary_non_graph_math_does_not_get_overridden(self):
        self.assertEqual(answer_graph_isomorphism("求解 18x≡7 mod 311"),"")
        self.assertEqual(answer_graph_isomorphism("图片中只有谓词公式"),"")
    def test_no_auto_decision_from_unverified_image(self):
        self.assertEqual(answer_graph_isomorphism(GOLD),"")
    def test_typed_graph_is_computable(self):
        raw=GOLD.replace("【图形信息】","【手工录入的完整边集】")
        self.assertIn("两图同构",answer_graph_isomorphism(raw))


if __name__ == "__main__":
    unittest.main()
