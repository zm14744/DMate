"""Synthetic graph-image regression tests. No textbook/user image is committed."""
import io
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
from graph_recognition import recognize_graphs
from graph_recognition_v2 import _unexplained_ink_fraction
import numpy as np

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

    def test_tall_phone_screenshot_retains_small_graph_dots(self):
        # A real 931x2048 OCR-review screenshot of this same four-graph
        # problem lost nine of the 24 tiny black dots when the CPU detector
        # unconditionally reduced the long side to 1700px.
        # Recreate the resolution, graph positions and distracting glyph-like
        # dots without storing any user's private screenshot in the repository.
        canvas = Image.new("RGB", (931, 2048), "white")
        painter = ImageDraw.Draw(canvas)
        # Multiple headline rows have black circular glyph fragments.
        # They must not be merged into the actual three-row graph strip.
        for i in range(8):
            x = 65 + i*72
            painter.ellipse((x-4, 195, x+4, 203), fill=(16, 16, 16))
            painter.ellipse((x-4, 224, x+4, 232), fill=(16, 16, 16))
        points = [(0, 0), (120, 0), (0, 132), (120, 132),
                  (0, 264), (120, 264)]
        for index, edge_list in enumerate(EDGES):
            offset_x = (88, 281, 474, 667)[index]
            located = [(offset_x+x, 303+y) for x, y in points]
            for a, b in edge_list:
                painter.line((located[a], located[b]), fill=(30, 30, 30), width=2)
            for x, y in located:
                painter.ellipse((x-5, y-5, x+5, y+5), fill=(5, 5, 5))
        self.check_exact(canvas)

    def test_six_blue_outline_trees_from_separate_pixel_strokes(self):
        from graph_sparse_panels import recognize_blue_outline_panels
        canvas=Image.new("RGB",(907,566),"white")
        draw=ImageDraw.Draw(canvas)
        offsets=[(0,0),(256,0),(512,0),(0,254),(256,254),(512,254)]
        # Distinct six-vertex trees: no synthetic "five-edge shortcut" in
        # the detector, every graph has five independently drawn strokes.
        patterns=[
            [(0,1),(1,2),(2,3),(3,4),(4,5)],
            [(0,1),(1,2),(2,3),(3,4),(1,5)],
            [(0,1),(1,2),(2,3),(1,4),(4,5)],
            [(0,1),(1,2),(1,4),(4,5),(4,3)],
            [(0,1),(1,2),(1,4),(1,5),(4,3)],
            [(0,1),(1,2),(1,3),(1,4),(1,5)],
        ]
        local=[(108,110),(206,54),(304,110),
               (304,220),(206,272),(108,220)]
        for (x_off,y_off),pairs in zip(offsets,patterns):
            pts=[(x+x_off,y+y_off) for x,y in local]
            for a,b in pairs:
                draw.line((pts[a],pts[b]),fill=(163,179,203),width=2)
            for x,y in pts:
                draw.ellipse((x-3,y-3,x+3,y+3),outline=(95,118,159),width=1)
        raw=io.BytesIO()
        canvas.save(raw,format="PNG")
        outcome=recognize_blue_outline_panels(raw.getvalue())
        self.assertEqual(len(outcome["graphs"]),6,outcome)
        for graph in outcome["graphs"]:
            self.assertEqual(graph["vertex_count"],6,graph)
            self.assertEqual(graph["confirmed_edge_count"],5,graph)
            self.assertEqual(len(graph["adjacency_matrix"]),6)

    def test_resized_and_mildly_blurred(self):
        self.check_exact(make_sheet().resize((900, 438)))
        self.check_exact(make_sheet().filter(ImageFilter.GaussianBlur(1.1)))

    def test_actual_pixel_candidate_reconciles_wrong_g3(self):
        from graph_consistency import reconcile_vision_edges, analyze_labeled_graphs
        from test_graph_consistency import WRONG_G3
        cv_graphs = detect(make_sheet())["graphs"]
        self.assertEqual(len(cv_graphs), 4)
        self.assertTrue(all(g["confidence"] == "high" for g in cv_graphs), cv_graphs)
        corrected, issues = reconcile_vision_edges(WRONG_G3, cv_graphs)
        self.assertEqual(len(issues), 1, issues)
        graphs = analyze_labeled_graphs(corrected)
        self.assertEqual(set(graphs[3]["edges"]),
            {("a","b"),("a","c"),("a","d"),("b","e"),("c","f"),("d","e")})
        self.assertFalse(graphs[3]["tree"])

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

    def test_unexplained_curved_stroke_blocks_high_confidence(self):
        clean = Image.new("RGB", (420, 320), "white")
        draw = ImageDraw.Draw(clean)
        points = [(45, 55), (210, 55), (375, 55), (45, 265), (210, 265), (375, 265)]
        edges = [(0, 1), (1, 2), (0, 3), (3, 4), (4, 5)]
        for a, b in edges:
            draw.line((points[a], points[b]), fill=(18, 18, 18), width=3)
        group = []
        for x, y in points:
            draw.ellipse((x-8, y-8, x+8, y+8), fill=(8, 8, 8))
            group.append((x, y, 8, "gray"))
        box = (25, 35, 395, 285)
        clean_fraction = _unexplained_ink_fraction(
            np.asarray(clean.convert("L")), group, box, edges, 180
        )
        curved = clean.copy()
        ImageDraw.Draw(curved).line(
            [(45, 55), (80, 110), (120, 180), (210, 220), (300, 245), (375, 265)],
            fill=(18, 18, 18), width=3
        )
        curved_fraction = _unexplained_ink_fraction(
            np.asarray(curved.convert("L")), group, box, edges, 180
        )
        self.assertLess(clean_fraction, 0.08, clean_fraction)
        self.assertGreater(curved_fraction, clean_fraction + 0.05, curved_fraction)
        self.assertGreater(curved_fraction, 0.10, curved_fraction)

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
