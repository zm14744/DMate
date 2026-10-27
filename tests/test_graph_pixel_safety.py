"""Offline, original-pixel regression checks for evidence used by fast OCR.

These fixtures are already public in the DMate repository. Pixel candidates
must be measured from the actual PNG bytes, not from an image-hash answer table.
A passing test does NOT certify Qwen image-recognition accuracy.
"""
import copy
from pathlib import Path

import networkx as nx

from graph_pixel_safety import (measure_image_pixel_evidence,
    create_grid_column_views, reconcile_anonymous_pixel_graphs)
from graph_fast_pipeline import _caption_grid_issues


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
