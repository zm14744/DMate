"""Regression tests: graph OCR cleanup preserves prose and raw graph evidence."""
import unittest

from graph_ocr_cleanup import clean_graph_question_text, ocr_is_label_dominated
from graph_validation import audit_graph_records


class GraphOcrCleanupTests(unittest.TestCase):
    def test_pure_vertex_dump_is_not_question_text(self):
        source = "a\nb\nc\nv1\nv2\ne3\n7"
        self.assertTrue(ocr_is_label_dominated(source))
        self.assertEqual(clean_graph_question_text(source, has_graph=True), "")

    def test_preserves_real_exercise_and_figure_caption(self):
        source = "课堂测试二：\n求该图的周长和围长\na\nb\nc\n图 11.18\nv1"
        cleaned = clean_graph_question_text(source, has_graph=True)
        self.assertIn("求该图的周长和围长", cleaned)
        self.assertIn("图 11.18", cleaned)
        self.assertNotIn("\na\n", cleaned)

    def test_non_graph_ocr_is_unchanged(self):
        source = "a\nb\nc\n数学题干"
        self.assertEqual(clean_graph_question_text(source, has_graph=False), source)

    def test_short_math_notes_not_removed(self):
        self.assertEqual(clean_graph_question_text("求 a 的值\na", has_graph=True),
                         "求 a 的值\na")

    def test_real_question_is_not_label_only(self):
        self.assertFalse(ocr_is_label_dominated(
            "判断下列图是否连通\na\nb\nv1\nv2"))


class WeightedGraphIntegrityTests(unittest.TestCase):
    @staticmethod
    def graph(weighted, weights):
        return {
            "id": "G1", "directed": False, "weighted": weighted,
            "multigraph": False, "complete": True,
            "vertices": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            "edges": [
                {"from": "a", "to": "b", "weight": weights[0]},
                {"from": "b", "to": "c", "weight": weights[1]},
            ],
        }

    def test_unweighted_graph_with_weight_values_is_flagged(self):
        issues = audit_graph_records([self.graph(False, [5, 3])])
        self.assertTrue(any("标记无权图" in x for x in issues))

    def test_weighted_graph_missing_weight_is_flagged(self):
        issues = audit_graph_records([self.graph(True, [5, None])])
        self.assertTrue(any("部分边缺少权值" in x for x in issues))

    def test_valid_weighted_graph_passes_consistency(self):
        self.assertEqual(audit_graph_records([self.graph(True, [5, 3])]), [])

    def test_valid_unweighted_graph_passes_consistency(self):
        self.assertEqual(audit_graph_records([self.graph(False, [None, None])]), [])


if __name__ == "__main__":
    unittest.main()
