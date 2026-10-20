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

    def test_colored_ink_on_varied_backgrounds(self):
        # Includes blue/red/green/orange/yellow nodes and strokes, as well as
        # inverted dark schemes and pastel lines with low grayscale contrast.
        samples = [
            ((255, 255, 255), [(35, 84, 210), (205, 43, 57), (19, 155, 86), (185, 80, 150)],
             [(65, 120, 205), (35, 160, 108), (220, 96, 50), (35, 85, 178)]),
            ((25, 29, 44), [(235, 205, 65), (241, 115, 150), (105, 228, 225), (245, 242, 230)],
             [(220, 198, 92), (120, 220, 200), (234, 170, 190), (230, 233, 235)]),
            ((246, 244, 231), [(145, 43, 165), (18, 125, 203), (66, 106, 40), (200, 87, 14)],
             [(135, 70, 145), (48, 142, 211), (75, 130, 75), (200, 100, 65)]),
        ]
        for bg, nodes, lines in samples:
            with self.subTest(background=bg):
                image = Image.new("RGB", (1480, 720), bg)
                painter = ImageDraw.Draw(image)
                for index, edges in enumerate(EDGES):
                    points = [(30 + index*360 + x, 70 + y) for x, y in NODES]
                    for a, b in edges:
                        painter.line([points[a], points[b]], fill=lines[index], width=3)
                    for x, y in points:
                        painter.ellipse((x-8, y-8, x+8, y+8), fill=nodes[index])
                self.check_exact(image)


    def test_colored_slide_heading_does_not_damage_blurry_black_graphs(self):
        image = make_sheet().filter(ImageFilter.GaussianBlur(1.1))
        painter = ImageDraw.Draw(image)
        # A textbook slide may have a large colored heading above black dots.
        # Heading chroma must not force an unsuitable image-wide transform.
        painter.rectangle((25, 5, 280, 85), fill=(35, 42, 167))
        painter.rectangle((370, 5, 780, 85), fill=(43, 60, 175))
        self.check_exact(image)

    def test_hollow_node_graphs_do_not_claim_full_certainty(self):
        # Many public Graphviz diagrams use unfilled rings and arrows.
        # Partial visual evidence must not be advertised as exact topology.
        image = Image.new("RGB", (450, 450), "white")
        draw = ImageDraw.Draw(image)
        points = [(70, 80), (360, 80), (70, 360), (360, 360)]
        for i,j in [(0,1),(0,2),(1,3),(2,3)]:
            draw.line([points[i], points[j]], fill=(30, 30, 30), width=3)
        for x,y in points:
            draw.ellipse((x-18, y-18, x+18, y+18),
                         outline=(18, 18, 18), width=4)
        result = detect(image)
        self.assertTrue(all(g["confidence"] != "high" for g in result.get("graphs") or []))

    def test_petersen_10_vertex_nonplanar_crossings(self):
        # Canonical 10-vertex / 15-edge Petersen topology, drawn with many
        # crossings but NO dots at the crossings (public mathematical graph).
        import math
        image = Image.new("RGB", (820, 820), "white")
        draw = ImageDraw.Draw(image)
        outer = [(-math.pi/2+2*math.pi*i/5, 270) for i in range(5)]
        inner = [(-math.pi/2+2*math.pi*i/5, 125) for i in range(5)]
        pts = [(410+r*math.cos(a), 410+r*math.sin(a)) for a,r in outer+inner]
        segments = set()
        for i in range(5):
            segments.add(tuple(sorted((i,(i+1)%5))))
            segments.add(tuple(sorted((i,i+5))))
            segments.add(tuple(sorted((i+5,((i+2)%5)+5))))
        for a,b in sorted(segments):
            draw.line([pts[a],pts[b]],fill=(18,18,18),width=3)
        for x,y in pts:
            draw.ellipse((x-9,y-9,x+9,y+9),fill=(8,8,8))
        g = detect(image)["graphs"]
        self.assertEqual(len(g),1,g)
        self.assertEqual(len(g[0]["vertices"]),10,g)
        self.assertEqual(len(g[0]["edges"]),15,g)
        self.assertEqual(len(g[0]["uncertain_edges"]),0,g)

    def test_radial_15_node_irregular_layout(self):
        # More than 10 points, with no row of three vertices; current
        # recognition must not discard radial drawings at the row filter.
        import math
        image = Image.new("RGB",(920,920),"white")
        draw=ImageDraw.Draw(image)
        pts=[(460+330*math.cos((2*math.pi*i/15)+.15*i/15),
              460+330*math.sin((2*math.pi*i/15)+.15*i/15))
             for i in range(15)]
        for i in range(15):
            draw.line([pts[i],pts[(i+1)%15]],fill=(18,18,18),width=3)
        for x,y in pts:
            draw.ellipse((x-8,y-8,x+8,y+8),fill=(8,8,8))
        gs=detect(image)["graphs"]
        self.assertTrue(gs,"Radial source should yield one graph candidate")
        self.assertEqual(len(gs[0]["vertices"]),15,gs)
        self.assertGreaterEqual(len(gs[0]["edges"]),12,gs)

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
