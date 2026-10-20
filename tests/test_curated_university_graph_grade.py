"""Truthfulness of university image benchmark scoring itself.

Previously correct keywords could hide Stanford/NJU/HKUST wrong answers.
These unit tests ensure clear wrong topology cannot earn a green verdict.
"""
import unittest
from curated_university_graph_images import verify_known_topology


class DiagramGoldVerdictTests(unittest.TestCase):
    def test_actual_wrong_nju_arrows(self):
        vision=("图(1)：有向图，含5个顶点。有向边为：a→b，c→b。\n"
                "图(2)：有向图，含7个顶点。有向边为：a→b，a→g，b→d，d→c，g→f。\n"
                "图(3)：有向图，含5个顶点。有向边为：a→b，b→c。")
        self.assertEqual(verify_known_topology("NJU_DIRECTED",vision,"三幅图全部弱连通"),
                         "OCR_WRONG_DIRECTED_EDGES")

    def test_nju_wrong_answer_even_if_edge_data_not_parseable(self):
        reply="| 图 | 强连通 | 弱连通 |\n| (2) | 否 | 是 |"
        self.assertEqual(verify_known_topology("NJU_DIRECTED","识别不完整",reply),
                         "CONFIRMED_WRONG_CONNECTIVITY")

    def test_stanford_actual_wrong_vertex_count(self):
        vision="图1（8个顶点）；图2（5个顶点）；图3（6个顶点）；图4（7个顶点）"
        self.assertEqual(verify_known_topology("STANFORD_TREE6",vision,"图3是唯一六顶点树"),
                         "OCR_WRONG_VERTEX_COUNT")

    def test_stanford_actual_wrong_solution(self):
        self.assertEqual(verify_known_topology("STANFORD_TREE6","","最终答案：只有 1 棵互不同构的树"),
                         "CONFIRMED_WRONG_TREE_COUNT")

    def test_hkust_22_versus_15(self):
        vision="图1：边集（共15条）："+"、".join(
            f"G1_v{i}-G1_v{i+1}" for i in range(1,23))
        self.assertEqual(verify_known_topology("HKUST_PETERSEN",vision,"10个顶点15条边"),
                         "OCR_CONTRADICTORY_EDGE_LIST")

    def test_mit_correct_edges_not_falsely_rejected(self):
        vision="无向图，边集合：{A,B},{B,C},{B,H},{C,D},{C,E},{D,E},{E,F},{E,H},{F,G}"
        self.assertEqual(verify_known_topology("MIT05_P3",vision,"直径=5，色数=3"),"")

    def test_mit_spurious_edge_is_not_a_pass(self):
        vision="无向图，边集合：{A,B},{B,C},{B,H},{C,D},{C,E},{D,E},{E,F},{E,H},{F,G},{A,H}"
        self.assertEqual(verify_known_topology("MIT05_P3",vision,"直径=5，色数=3"),
                         "OCR_WRONG_EDGE_LIST")


if __name__=="__main__":
    unittest.main()
