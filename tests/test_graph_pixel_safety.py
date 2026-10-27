"""Offline, original-pixel regression checks for evidence used by fast OCR.

These fixtures are already public in the DMate repository. Pixel candidates
must be measured from the actual PNG bytes, not from an image-hash answer table.
A passing test does NOT certify Qwen image-recognition accuracy.
"""
import copy
from pathlib import Path

import networkx as nx
from test_graph_fast_pipeline import prepared

from graph_pixel_safety import (measure_image_pixel_evidence,
    create_grid_column_views, create_grid_panel_views, reconcile_anonymous_pixel_graphs)
from graph_fast_pipeline import _caption_grid_issues, _grid_dark_disk_issues


PUBLIC_ORIGINALS = Path(__file__).resolve().parent / "fixtures" / "original_ouc_20261021"


def _image(name):
    return (PUBLIC_ORIGINALS / name).read_bytes()


def _unlabeled_graph(index, count, endpoints):
    return {"id": f"G{index}", "directed": False, "weighted": False,
            "vertices": [{"id": f"v{i+1}", "label": None}
                         for i in range(count)],
            "edges": [{"id": f"e{j+1}", "from": f"v{a}", "to": f"v{b}",
                       "direction": "undirected", "style": "solid"}
                      for j, (a, b) in enumerate(endpoints)]}


def test_real_six_panel_original_has_repeatable_independent_caption_grid():
    raw = _image("181309.png")
    evidence = measure_image_pixel_evidence(raw)
    grid = evidence["grid"]
    assert grid and grid["status"] == "regular_caption_grid"
    assert (grid["rows"], grid["columns"], grid["minimum_captioned_panels"]) == (2, 3, 6)
    assert len(grid["panels"]) == 6
    assert evidence["colored_graphs"] == []
    assert evidence["image_accuracy_certified"] is False
    previews = create_grid_column_views(raw, evidence)
    assert len(previews) == 3
    assert all(x["image"].startswith("data:image/png;base64,") for x in previews)
    assert len(set(x["image"] for x in previews)) == 3
    assert all("两行" not in x["description"] for x in previews)  # precise, not invented hints


def test_six_panels_missing_five_requires_whole_document_review():
    evidence = measure_image_pixel_evidence(_image("181309.png"))
    draft = {"graphs": [{"id": "G1", "vertices": [{}], "edges": []}], "body_text": ""}
    issues = _caption_grid_issues(draft, evidence)
    assert len(issues) == 1
    assert issues[0]["scope"] == "document"
    assert issues[0]["kind"] == "captioned_panel_inventory_omission"
    assert issues[0]["observed_caption_positions"] == 6
    assert issues[0]["reported_graphs"] == 1
    draft["graphs"] = [dict(draft["graphs"][0], id=f"G{i}") for i in range(1, 7)]
    assert _caption_grid_issues(draft, evidence) == []


def test_real_four_panel_original_yields_actual_straight_strokes():
    evidence = measure_image_pixel_evidence(_image("180506.png"))
    assert evidence["grid"] is None
    panels = evidence["colored_graphs"]
    assert len(panels) == 4
    assert [(len(p["vertices"]), len(p["edges"])) for p in panels] == [
        (6, 5), (6, 6), (6, 10), (5, 10)]
    assert all(p["unambiguous"] and not p["borderline_pairs"] for p in panels)
    assert all(p["pixel_grounded"] and p["unlabeled_only"] for p in panels)
    for panel in panels:
        n = nx.Graph()
        n.add_nodes_from(v["id"] for v in panel["vertices"])
        n.add_edges_from((e["from"], e["to"]) for e in panel["edges"])
        assert n.number_of_nodes() == len(panel["vertices"])
        assert n.number_of_edges() == len(panel["edges"])
    # Second panel must have degree 2 for every one of its SIX vertices.
    h = nx.Graph()
    h.add_nodes_from(v["id"] for v in panels[1]["vertices"])
    h.add_edges_from((e["from"], e["to"]) for e in panels[1]["edges"])
    assert nx.is_connected(h)
    assert set(dict(h.degree()).values()) == {2}


def test_wrong_cycle_edges_are_repaired_from_pixels_not_from_figure_name():
    evidence = measure_image_pixel_evidence(_image("180506.png"))
    # The four graphs have exactly the cardinalities read from the pixels, but
    # G2 is a NON-cycle: one node incorrectly has degree zero.
    g1 = _unlabeled_graph(1, 6, [(1, 2), (1, 3), (1, 4), (1, 5), (1, 6)])
    g2 = _unlabeled_graph(2, 6, [(1, 5), (2, 5), (3, 5), (4, 5),
                                 (2, 3), (3, 4)])
    g3 = _unlabeled_graph(3, 6, [(1, 2), (1, 3), (1, 4), (1, 5), (1, 6),
                                 (2, 3), (3, 4), (4, 5), (5, 6), (6, 2)])
    g4 = _unlabeled_graph(4, 5, [(1, 2), (1, 3), (1, 4), (1, 5),
                                 (2, 3), (2, 4), (2, 5),
                                 (3, 4), (3, 5), (4, 5)])
    draft = {"body_text": "求各图的点连通度。", "graphs": [g1, g2, g3, g4],
             "uncertainties": []}
    fixed, repairs = reconcile_anonymous_pixel_graphs(draft, evidence)
    assert draft["graphs"][1] == g2  # preserve the input
    assert len(repairs) == 1 and repairs[0]["graph_id"] == "G2"
    assert fixed["graphs"][0] == g1
    assert fixed["graphs"][2] == g3
    assert fixed["graphs"][3] == g4
    h = nx.Graph()
    h.add_nodes_from(v["id"] for v in fixed["graphs"][1]["vertices"])
    h.add_edges_from((e["from"], e["to"]) for e in fixed["graphs"][1]["edges"])
    assert len(h) == 6 and h.number_of_edges() == 6
    assert nx.is_connected(h)
    assert set(dict(h.degree()).values()) == {2}
    assert repairs[0]["image_accuracy_certified"] is False


def test_no_pixel_repair_if_labels_or_weights_make_mapping_unsafe():
    evidence = measure_image_pixel_evidence(_image("180506.png"))
    g = _unlabeled_graph(1, 6, [(1, 2), (1, 3), (1, 4), (1, 5), (1, 6)])
    h = _unlabeled_graph(2, 6, [(1, 5), (2, 5), (3, 5), (4, 5), (2, 3), (3, 4)])
    f = _unlabeled_graph(3, 6, [(1, 2), (1, 3), (1, 4), (1, 5), (1, 6),
                                (2, 3), (3, 4), (4, 5), (5, 6), (6, 2)])
    k = _unlabeled_graph(4, 5, [(1, 2), (1, 3), (1, 4), (1, 5),
                                (2, 3), (2, 4), (2, 5),
                                (3, 4), (3, 5), (4, 5)])
    for variant in ("printed_vertex", "weighted", "parallel", "loop"):
        draft = {"body_text": "", "graphs": copy.deepcopy([g, h, f, k])}
        current = draft["graphs"][1]
        if variant == "printed_vertex":
            current["vertices"][0]["label"] = "A"
        elif variant == "weighted":
            current["edges"][0]["weight"] = 1
        elif variant == "parallel":
            current["edges"][0]["from"] = current["edges"][1]["from"]
        elif variant == "loop":
            current["edges"][0]["to"] = current["edges"][0]["from"]
        before = copy.deepcopy(draft)
        after, repairs = reconcile_anonymous_pixel_graphs(draft, evidence)
        assert repairs == []
        assert after == before


def test_six_public_figures_have_stable_filled_dark_vertices_and_straight_lower_bounds():
    evidence = measure_image_pixel_evidence(_image("181309.png"))
    rows = evidence["grid_dark_disks"]
    assert rows["status"] == "measured"
    assert rows["thresholds"] == [100, 130, 160]
    assert len(rows["panels"]) == 6
    assert [p["candidate_count"] for p in rows["panels"]] == [5, 5, 5, 4, 3, 4]
    assert [p["straight_edge_lower_bound"] for p in rows["panels"]] == [7, 6, 5, 5, 3, 5]
    assert all(p["status"] == "measured"
               and p["edge_count_is_exact"] is False
               and len(p["nodes"]) == p["candidate_count"]
               and len(p["straight_edge_candidates"]) == p["straight_edge_lower_bound"]
               for p in rows["panels"])
    assert rows["image_accuracy_certified"] is False


def test_black_pixel_inventory_flags_missing_edges_and_wrong_last_vertex_count():
    evidence = measure_image_pixel_evidence(_image("181309.png"))
    actual_nodes = [5, 5, 5, 4, 3, 5]  # Last panel was wrongly copied as G.
    actual_edges = [7, 6, 5, 4, 2, 7]  # Two missing straight strokes.
    graphs = [{"id": f"G{i+1}",
               "vertices": [{"id": f"v{j+1}"} for j in range(actual_nodes[i])],
               "edges": [{"id": f"e{j+1}"} for j in range(actual_edges[i])]}
              for i in range(6)]
    document = {"body_text": "", "graphs": graphs}
    snapshot = copy.deepcopy(document)
    issues = _grid_dark_disk_issues(document, evidence)
    assert document == snapshot
    assert {(row["graph_id"], row["field"], row["kind"]) for row in issues} == {
        ("G4", "edges", "pixel_straight_edge_lower_bound_conflict"),
        ("G5", "edges", "pixel_straight_edge_lower_bound_conflict"),
        ("G6", "vertices", "pixel_disk_vertex_count_conflict"),
    }
    # Five measured straight pairs in G6 do not disprove an additional
    # curved parallel edge. No generated relation or edge deletion is allowed.
    assert not any(row["graph_id"] == "G6" and row["field"] == "edges" for row in issues)
    assert _caption_grid_issues(document, evidence) == []


def test_dark_disk_inventory_is_inactive_without_a_strict_grid():
    sample = measure_image_pixel_evidence(_image("180506.png"))
    assert sample["grid"] is None
    assert sample["grid_dark_disks"] == {"status": "not_applicable", "panels": []}
    assert _grid_dark_disk_issues({"body_text": "", "graphs": []}, sample) == []



def test_original_rgb_targeted_crops_are_the_three_disputed_bottom_panels():
    """The visual-review provider must receive actual pixels, not model crops."""
    import base64
    import io
    from PIL import Image

    raw = _image("181309.png")
    evidence = measure_image_pixel_evidence(raw)
    zooms = create_grid_panel_views(raw, evidence, [3, 4, 5])
    assert len(zooms) == 3
    assert [row["region_id"] for row in zooms] == [
        "colored_caption_r2c1", "colored_caption_r2c2", "colored_caption_r2c3"]
    assert len({row["image"] for row in zooms}) == 3
    original = Image.open(io.BytesIO(raw)).convert("RGB")
    for crop in zooms:
        assert "原RGB" in crop["description"]
        assert crop["image"].startswith("data:image/png;base64,")
        pixels = base64.b64decode(crop["image"].split(",", 1)[1], validate=True)
        seen = Image.open(io.BytesIO(pixels)).convert("RGB")
        x0, y0, x1, y1 = crop["original_pixel_bbox"]
        assert seen.size == (x1-x0, y1-y0)
        assert seen.tobytes() == original.crop((x0, y0, x1, y1)).tobytes()


def test_targeted_crops_reject_ambiguous_or_incomplete_panel_inventory():
    raw = _image("181309.png")
    evidence = measure_image_pixel_evidence(raw)
    assert create_grid_panel_views(raw, evidence, [0, 0]) == []
    assert create_grid_panel_views(raw, evidence, [-1]) == []
    assert create_grid_panel_views(raw, evidence, [6]) == []
    assert create_grid_panel_views(raw, evidence, [0, 1, 2, 3, 4]) == []
    bad = copy.deepcopy(evidence)
    bad["grid"]["panels"][5]["bbox"] = [0, 0, 10000, 500]
    assert create_grid_panel_views(raw, bad, [5]) == []
    broken = copy.deepcopy(evidence)
    broken["grid"]["minimum_captioned_panels"] = 7
    assert create_grid_panel_views(raw, broken, [5]) == []


def test_fast_review_chooses_only_disputed_grid_panels(monkeypatch, prepared):
    from test_graph_fast_pipeline import Provider, Specialist, document
    import hashlib
    import graph_pixel_safety
    raw, run, _ = prepared
    baseline = document()
    initial = {"body_text": baseline["body_text"], "graphs": [], "uncertainties": []}
    for i in range(6):
        row = copy.deepcopy(baseline["graphs"][0])
        row["id"] = f"G{i+1}"
        row["name"] = f"G{i+1}"
        if i in (3, 4):
            row["visible_edge_count"] = len(row["edges"]) + 1
        elif i == 5:
            row["visible_vertex_count"] = len(row["vertices"]) + 1
        initial["graphs"].append(row)

    grids = []
    for row in range(2):
        for column in range(3):
            grids.append({"id": f"colored_caption_r{row+1}c{column+1}",
                          "bbox": [column * 333, row * 500,
                                   (column+1) * 333 if column < 2 else 1000,
                                   (row+1) * 500],
                          "row": row+1, "column": column+1})
    evidence = {"source_sha256": hashlib.sha256(raw).hexdigest(),
                "grid": {"status": "regular_caption_grid", "panels": grids,
                         "rows": 2, "columns": 3, "minimum_captioned_panels": 6,
                         "column_bounds": [0, 1/3, 2/3, 1]},
                "grid_dark_disks": {"status": "partial", "panels": [
                    {"status": "unstable", "region_id": g["id"]} for g in grids]},
                "colored_graphs": [], "advisory_only": True}
    monkeypatch.setattr(graph_pixel_safety, "measure_image_pixel_evidence",
                        lambda data: copy.deepcopy(evidence))
    review = {"graphs": copy.deepcopy(initial["graphs"][3:]),
              "uncertainties": []}
    specialist = Specialist(review)
    result, main = run(main=Provider(initial), specialist=specialist)
    assert len(main.requests) == len(specialist.requests) == 1
    assert specialist.requests[0]["targets"]["graph_ids"] == ["G4", "G5", "G6"]
    views = specialist.requests[0]["image_views"]
    assert len(views) == 4
    assert all("原RGB局部放大" in name for name in views[1:])
    assert [text.split("图注位置")[0][-2:] for text in views[1:]]  # three distinct locations
    assert result["semantic_workflow"]["local_review"]["view_strategy"] == (
        "original_overview_plus_disputed_grid_cells")
    assert result["semantic_workflow"]["local_review"]["image_count"] == 4
    assert len(result["graphs"]) == 6
