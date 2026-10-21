"""Regression tests for alignment-aware CPU graph-detector reconciliation.

They use synthetic per-detector topology and do not call cloud APIs.
"""
import io
import unittest
from unittest.mock import patch

from PIL import Image

from graph_detector_consensus import reconcile_pixel_detectors
from graph_recognition import recognize_graphs


def graph(labels, locations, edges, confidence="high"):
    vertices = [
        {"id": label, "x": x, "y": y, "label": None}
        for label, (x, y) in zip(labels, locations)
    ]
    matrix = [[0] * len(labels) for _ in labels]
    pairs = []
    for i, j in edges:
        matrix[i][j] = matrix[j][i] = 1
        pairs.append([labels[i], labels[j]])
    return {
        "id": "图1", "directed": "unknown", "vertices": vertices,
        "vertex_count": len(labels), "edges": pairs,
        "confirmed_edge_count": len(pairs), "adjacency_matrix": matrix,
        "component_count_of_confirmed_edges": 1,
        "uncertain_edges": [], "confidence": confidence,
        "bbox": [.10, .10, .82, .82]
    }


POINTS = [(.2, .2), (.7, .2), (.2, .7), (.7, .7)]


def result(g):
    return {"status": "detected", "graphs": [g], "regions": [g["bbox"]]}


class DetectorConsensusTests(unittest.TestCase):
    def test_same_edges_different_vertex_order_are_compared_geometrically(self):
        first = graph(["v1", "v2", "v3", "v4"], POINTS, [(0, 1), (0, 2), (1, 3)])
        order = [3, 2, 1, 0]
        reordered = [POINTS[i] for i in order]
        second = graph(["q1", "q2", "q3", "q4"], reordered,
                       [(3, 2), (3, 1), (2, 0)])
        got = reconcile_pixel_detectors(result(first), result(second))
        self.assertEqual(got["graphs"][0]["confidence"], "high")
        self.assertEqual(got["graphs"][0]["detector_agreement"], "matching")
        self.assertEqual(got["graphs"][0]["confirmed_edge_count"], 3)

    def test_disagreement_is_uncertain_not_false_confirmed_edge(self):
        first = graph(["v1", "v2", "v3", "v4"], POINTS,
                      [(0, 1), (0, 2), (1, 3)])
        second = graph(["a", "b", "c", "d"], POINTS,
                       [(0, 1), (0, 2), (2, 3)])
        got = reconcile_pixel_detectors(result(first), result(second))
        one = got["graphs"][0]
        self.assertEqual(got["status"], "partial")
        self.assertEqual(one["confidence"], "partial")
        self.assertEqual({tuple(e) for e in one["edges"]},
                         {("v1", "v2"), ("v1", "v3")})
        self.assertEqual({tuple(e) for e in one["uncertain_edges"]},
                         {("v2", "v4"), ("v3", "v4")})
        self.assertEqual(one["confirmed_edge_count"], 2)
        self.assertEqual(one["component_count_of_confirmed_edges"], 2)
        self.assertEqual(one["adjacency_matrix"][1][3], 0)

    def test_vertex_count_conflict_is_not_high_confidence(self):
        first = graph(["v1", "v2", "v3", "v4"], POINTS, [(0, 1), (1, 3)])
        second = graph(["a", "b", "c", "d", "e"],
                       POINTS + [(.45, .45)], [(0, 1), (1, 3)])
        got = reconcile_pixel_detectors(result(first), result(second))
        self.assertEqual(got["graphs"][0]["vertex_count"], 4)
        self.assertEqual(got["graphs"][0]["confidence"], "partial")
        self.assertIn("顶点数量不同", got["warning"])

    def test_distant_graph_is_never_merged(self):
        first = graph(["v1", "v2", "v3", "v4"], POINTS, [(0, 1)])
        far = [(.8, .8), (.95, .8), (.8, .95), (.95, .95)]
        second = graph(["a", "b", "c", "d"], far, [(0, 1)])
        got = reconcile_pixel_detectors(result(first), result(second))
        self.assertNotIn("detector_agreement", got["graphs"][0])

    def test_main_recognizer_reaches_second_detector_when_first_has_one(self):
        first = result(graph(["v1", "v2", "v3", "v4"], POINTS,
                             [(0, 1), (0, 2), (1, 3)]))
        second = result(graph(["a", "b", "c", "d"], POINTS,
                              [(0, 1), (0, 2), (2, 3)]))
        data = io.BytesIO()
        Image.new("RGB", (500, 500), "white").save(data, "PNG")
        with patch("graph_sparse_panels.recognize_blue_outline_panels",
                   return_value={"status": "unsupported", "graphs": [], "regions": []}), \
             patch("graph_recognition_v2.recognize_filled_graphs", return_value=first), \
             patch("graph_black_disks.recognize_black_disk_graph",
                   return_value=second) as fallback:
            got = recognize_graphs(data.getvalue(), text_hint="graph isomorphism")
        fallback.assert_called_once()
        self.assertEqual(got["status"], "partial")
        self.assertEqual(len(got["graphs"][0]["uncertain_edges"]), 2)

    def test_single_unverified_pixel_graph_is_not_promoted_to_high(self):
        first = result(graph(["v1", "v2", "v3", "v4"], POINTS,
                             [(0, 1), (0, 2), (1, 3)]))
        data = io.BytesIO()
        Image.new("RGB", (500, 500), "white").save(data, "PNG")
        with patch("graph_sparse_panels.recognize_blue_outline_panels",
                   return_value={"status": "unsupported", "graphs": [], "regions": []}), \
             patch("graph_recognition_v2.recognize_filled_graphs", return_value=first), \
             patch("graph_black_disks.recognize_black_disk_graph",
                   return_value={"status": "uncertain", "graphs": [], "regions": []}):
            got = recognize_graphs(data.getvalue(), text_hint="图论")
        self.assertEqual(got["status"], "partial")
        self.assertEqual(got["graphs"][0]["confidence"], "partial")
        self.assertEqual(got["graphs"][0]["detector_agreement"], "unverified")
        self.assertEqual(got["graphs"][0]["confirmed_edge_count"], 3)
        self.assertEqual(len(got["graphs"][0]["edges"]), 3)

    def test_multi_panel_keeps_existing_fast_path(self):
        first = result(graph(["v1", "v2", "v3", "v4"], POINTS, [(0, 1)]))
        first["graphs"].append(first["graphs"][0].copy())
        data = io.BytesIO()
        Image.new("RGB", (500, 500), "white").save(data, "PNG")
        with patch("graph_sparse_panels.recognize_blue_outline_panels",
                   return_value={"status": "unsupported", "graphs": [], "regions": []}), \
             patch("graph_recognition_v2.recognize_filled_graphs", return_value=first), \
             patch("graph_black_disks.recognize_black_disk_graph") as fallback:
            got = recognize_graphs(data.getvalue(), text_hint="图论")
        fallback.assert_not_called()
        self.assertEqual(len(got["graphs"]), 2)


if __name__ == "__main__":
    unittest.main()
