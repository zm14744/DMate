"""Synthetic graph-image regression tests. No textbook/user image is committed."""
import io
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
from graph_recognition import recognize_graphs

NODES = [(30, 60), (240, 60), (30, 290), (240, 290), (30, 520), (240, 520)]
EDGES = [
    [(0, 2), (1, 2), (2, 3), (2, 5), (4, 5)],
    [(0, 2), (0, 5), (1, 4), (3, 5), (4, 5)],
    [(0, 1), (0, 2), (0, 3), (1, 4), (2, 5), (3, 4)],
    [(0, 5), (1, 3), (1, 4), (2, 4)],
]
EXPECTED = [
    {("v1", "v3"), ("v2", "v3"), ("v3", "v4"), ("v3", "v6"), ("v5", "v6")},
    {("v1", "v3"), ("v1", "v6"), ("v2", "v5"), ("v4", "v6"), ("v5", "v6")},
    {("v1", "v2"), ("v1", "v3"), ("v1", "v4"), ("v2", "v5"), ("v3", "v6"), ("v4", "v5")},
    {("v1", "v6"), ("v2", "v4"), ("v2", "v5"), ("v3", "v5")},
]


def make_sheet():
    canvas = Image.new("RGB", (1480, 720), "white")
    draw = ImageDraw.Draw(canvas)
    for index, edges in enumerate(EDGES):
        pts = [(30 + index * 360 + x, 70 + y) for x, y in NODES]
        for a, b in edges:
            draw.line([pts[a], pts[b]], fill=(15, 15, 15), width=3)
        for x, y in pts:
            draw.ellipse((x-8, y-8, x+8, y+8), fill=(12, 12, 12))
    return canvas


def detect(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return recognize_graphs(buffer.getvalue(), text_hint="下列图中哪些是树？")


class GraphRecognitionTests(unittest.TestCase):
    def check_exact(self, image):
        result = detect(image)
        graphs = result["graphs"]
        self.assertEqual(len(graphs), 4, result)
        self.assertEqual([g["vertex_count"] for g in graphs], [6, 6, 6, 6])
        self.assertEqual([g["confirmed_edge_count"] for g in graphs], [5, 5, 6, 4])
        self.assertEqual([g["component_count_of_confirmed_edges"] for g in graphs], [1, 1, 1, 2])
        for idx, g in enumerate(graphs):
            self.assertEqual({tuple(edge) for edge in g["edges"]}, EXPECTED[idx])
            self.assertFalse(g["uncertain_edges"])
        # Visual line crossings are NOT standalone vertices.
        self.assertEqual(sum(g["vertex_count"] for g in graphs), 24)

    def test_black_dots_four_graphs_and_crossings(self):
        self.check_exact(make_sheet())

    def test_resized_and_mildly_blurred(self):
        self.check_exact(make_sheet().resize((900, 438)))
        self.check_exact(make_sheet().filter(ImageFilter.GaussianBlur(1.1)))

    def test_low_contrast(self):
        self.check_exact(ImageEnhance.Contrast(make_sheet()).enhance(.5))

    def test_strong_blur_downgrades_not_invents(self):
        detected = detect(make_sheet().filter(ImageFilter.GaussianBlur(2.7)))
        self.assertTrue(all(g["confidence"] != "high" for g in detected["graphs"]))
        self.assertTrue(all(g["vertex_count"] <= 6 for g in detected["graphs"]))

    def test_no_vision_label_overwrite_regression(self):
        app = Path("app.py").read_text("utf-8")
        self.assertIn("if cv_graphs and not visual_text", app)
        self.assertIn('visual_text = "\\n\\n".join(readable)', app)
        prompt = Path("ai.py").read_text("utf-8")
        self.assertIn("交叉处转向", prompt)
        self.assertIn("临时编号，并非真实", prompt)
        self.assertIn("enhance_crop(crop)", prompt)


if __name__ == "__main__":
    unittest.main()
