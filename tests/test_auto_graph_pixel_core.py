"""Offline synthetic + real-pixel checks for automatic per-panel graph evidence.

These tests exercise candidate generation only. Neither a passing test nor a
high CV score is a claim of 100% image recognition accuracy.
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from graph_pixel_safety import (_color_line_topology, _image, _trusted_stroke_mask,
                                measure_image_pixel_evidence)
from graph_semantic_schema import normalize_semantic_document


def _bitmap(image):
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _triangle(*, edge_rgb=(35, 100, 240), horizontal=False, shadow=False, ghost=False):
    image = Image.new("RGB", (480, 330), "white")
    draw = ImageDraw.Draw(image)
    a, b, c = (190, 75), (216, 240), (242, 75)
    if shadow:
        # Broad dark printing/sheet shadow — not a real top edge.
        draw.rectangle((0, 48, 479, 104), fill=(135, 135, 135))
    for p, q in ((a, b), (b, c)):
        draw.line((p, q), fill=edge_rgb, width=4)
    if horizontal:
        # Bright yellow has grayscale intensity much greater than 145;
        # an old hard grayscale threshold could not recognize this edge.
        draw.line((a, c), fill=(247, 232, 32), width=4)
    if ghost:
        draw.line((a, c), fill=(218, 218, 218), width=1)
    for x, y in (a, b, c):
        draw.ellipse((x-8, y-8, x+8, y+8), fill=(229, 29, 38))
    return image


def _pairs(rows):
    assert len(rows) == 1, rows
    ids = {n["id"]: (n["x"], n["y"]) for n in rows[0]["vertices"]}
    edges = rows[0]["edges"]
    assert len(ids) == 3
    return {frozenset((edge["from"], edge["to"])) for edge in edges}, edges, rows[0]


def test_bright_color_strokes_are_detected_without_dark_threshold():
    _, edges, panel = _pairs(_color_line_topology(np.asarray(_triangle(horizontal=True))))
    assert len(edges) == 3
    assert panel["unambiguous"] is True
    assert all(edge["minimum_section_support"] >= .72 for edge in edges)


def test_shade_and_faint_reverse_print_cannot_prove_a_missing_edge():
    image = _triangle(shadow=True, ghost=True)
    _, edges, panel = _pairs(_color_line_topology(np.asarray(image)))
    assert len(edges) == 2
    assert panel["unambiguous"] is True
    assert panel["pixel_grounded"] is True


def test_line_cannot_go_through_a_third_visited_vertex():
    image = Image.new("RGB", (480, 330), "white")
    draw = ImageDraw.Draw(image)
    a, b, c = (190, 70), (216, 160), (242, 250)
    draw.line((a, c), fill="black", width=4)
    for x, y in (a, b, c):
        draw.ellipse((x-8, y-8, x+8, y+8), fill=(229, 29, 38))
    _, edges, panel = _pairs(_color_line_topology(np.asarray(image)))
    assert len(edges) == 2
    assert panel["unambiguous"] is True


def test_original_transparency_does_not_become_black_background():
    image = Image.new("RGBA", (280, 220), (0, 0, 0, 0))
    ImageDraw.Draw(image).line((30, 110, 240, 110), fill=(10, 130, 240, 255), width=3)
    original, working = _image(_bitmap(image))
    assert original.getpixel((0, 0)) == (255, 255, 255)
    assert tuple(working[0, 0]) == (255, 255, 255)


def test_quality_is_audit_only_and_does_not_certify_shadows():
    measured = measure_image_pixel_evidence(_bitmap(_triangle(shadow=True)))
    quality = measured["pixel_mask_quality"]
    assert quality["source"] == "original_rgb_local_background_and_chroma"
    assert quality["not_automatic_graph_certificate"] is True
    assert measured["advisory_only"] and measured["image_accuracy_certified"] is False


def test_per_figure_direction_and_weight_not_page_wide():
    source = {"body_text":"", "graphs":[
        {"id":"G1","directed":False,"weighted":False,
         "vertices":[{"id":"a"},{"id":"b"}],
         "edges":[{"from":"a","to":"b","direction":"undirected"}]},
        {"id":"G2","directed":True,"weighted":True,
         "vertices":[{"id":"a"},{"id":"b"}],
         "edges":[{"from":"a","to":"b","direction":"forward","weight":0}]},
        {"id":"G3","directed":True,"weighted":False,
         "vertices":[{"id":"a"},{"id":"b"}],
         "edges":[{"from":"b","to":"a","direction":"unknown"}]}
    ]}
    result = normalize_semantic_document(source, reviewed=True)
    graphs = result["graphs"]
    assert [g["id"] for g in graphs] == ["G1", "G2", "G3"]
    assert graphs[0]["directed"] is False and graphs[0]["weighted"] is False
    assert graphs[1]["directed"] is True and graphs[1]["weighted"] is True
    assert graphs[1]["edges"][0]["weight"] == 0
    assert graphs[2]["directed"] == "unknown"
    assert any(issue["graph_id"] == "G3" for issue in result["semantic_issues"])


def test_public_four_diagram_color_evidence_remains_readable():
    data = Path(__file__).resolve().parent / "fixtures" / "original_ouc_20261021" / "180506.png"
    if not data.is_file():
        raise AssertionError("Existing public original was deleted")
    result = measure_image_pixel_evidence(data.read_bytes())
    observed = [(len(p["vertices"]), len(p["edges"])) for p in result["colored_graphs"]]
    if observed != [(6, 5), (6, 6), (6, 10), (5, 10)]:
        import cv2
        from graph_pixel_safety import _red_markers
        _, rgb = _image(data.read_bytes())
        old_mask = (cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY) < 145).astype(np.uint8)
        old_rows = _color_line_topology(rgb, trusted_ink=old_mask)
        for idx, (now, before) in enumerate(zip(result["colored_graphs"], old_rows)):
            old_edges = {tuple(sorted((e["from"], e["to"]))) for e in before["edges"]}
            new_edges = {tuple(sorted((e["from"], e["to"]))) for e in now["edges"]}
            print("PIXEL_DIAGNOSTIC", idx, "strict", len(new_edges),
                  "fixed_gray", len(old_edges), "missing_from_gray",
                  sorted(old_edges-new_edges), "mask_quality", result.get("pixel_mask_quality"))
    assert observed == [(6, 5), (6, 6), (6, 10), (5, 10)]
    assert all(p["unambiguous"] for p in result["colored_graphs"])
