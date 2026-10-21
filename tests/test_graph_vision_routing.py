"""Focused unit tests for the graph-only Qwen vision routing path.

These tests do not call external APIs and do not claim end-to-end graph accuracy.
"""
import unittest

from ai import GRAPH_TOPOLOGY_PROMPT, VISION_MODEL, _is_graph_vision_task


class GraphVisionRoutingTests(unittest.TestCase):
    def test_chinese_tree_question_uses_graph_path(self):
        self.assertTrue(_is_graph_vision_task("判断下列图哪些是树", {}))

    def test_english_isomorphism_question_uses_graph_path(self):
        self.assertTrue(
            _is_graph_vision_task(
                "Determine whether the graphs are isomorphic", {}
            )
        )

    def test_english_directed_graph_question_uses_graph_path(self):
        self.assertTrue(
            _is_graph_vision_task(
                "Find strongly connected components of the directed graph", {}
            )
        )

    def test_nearly_textless_cv_graph_uses_graph_path(self):
        self.assertTrue(
            _is_graph_vision_task("", {"graphs": [{"id": "G1"}]})
        )

    def test_set_question_stays_on_general_vision_path(self):
        self.assertFalse(
            _is_graph_vision_task(
                "Let A be a subset of B. Find the union and intersection.", {}
            )
        )

    def test_long_geometry_question_does_not_route_on_cv_candidate_alone(self):
        self.assertFalse(
            _is_graph_vision_task(
                "In the figure below, calculate the angle at point A using the given lengths.",
                {"graphs": [{"id": "possible-false-positive"}]},
            )
        )

    def test_selected_vision_model_is_unchanged(self):
        self.assertEqual(VISION_MODEL, "qwen3-vl-plus")

    def test_graph_prompt_does_not_ask_for_duplicate_ocr(self):
        self.assertIn('"corrected_text": ""', GRAPH_TOPOLOGY_PROMPT)
        self.assertIn("不负责转录题干", GRAPH_TOPOLOGY_PROMPT)


if __name__ == "__main__":
    unittest.main()
