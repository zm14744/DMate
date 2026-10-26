"""Semantic content survives adaptation without a pixel/coordinate contract."""
import copy
import json
import math

import pytest

from graph_schema import describe_graphs, display_graph
from graph_semantic_schema import (
    MAX_EDGES, MAX_GRAPHS, MAX_VERTICES, normalize_semantic_document,
)
from graph_validation import audit_graph_records


def document(**graph_updates):
    graph = {"id": "g", "name": "图甲", "directed": False,
             "vertices": [{"id": "a", "label": "v₁"}, {"id": "b", "label": "V_2"}],
             "edges": [{"id": "edge", "from": "a", "to": "b", "edge_label": "e₁"}]}
    graph.update(graph_updates)
    return {"body_text": "求 v₁ 到 V_2 的通路。", "graphs": [graph]}


def kinds(result):
    return {issue["kind"] for issue in result["semantic_issues"]}


def test_coordinate_free_review_is_renderable_without_old_pixel_requirements():
    result = normalize_semantic_document(document(), reviewed=True)
    graph = result["graphs"][0]
    assert result["complete"] and result["body_complete"] and graph["complete"]
    assert result["semantic_issues"] == []
    assert graph["directed"] is False and graph["weighted"] is False and graph["multigraph"] is False
    assert graph["edges"][0]["status"] == "accepted"
    assert graph["edges"][0]["path"] == []
    assert graph["vertices"][0]["x"] is None
    assert audit_graph_records(result["graphs"]) == []
    assert "v₁—V_2" in describe_graphs(result["graphs"])
    assert "边名 e₁" in describe_graphs(result["graphs"])
    assert display_graph(graph)["edges"][0]["edge_label"] == "e₁"


@pytest.mark.parametrize("reviewed", [False, 1, "true", None])
def test_only_caller_boolean_review_confirms_content(reviewed):
    payload = document()
    payload.update(complete=True, reviewed=True, body_complete=True)
    payload["graphs"][0].update(complete=True, status="accepted")
    payload["graphs"][0]["edges"][0]["status"] = "accepted"
    result = normalize_semantic_document(payload, reviewed=reviewed)
    assert not result["complete"] and not result["body_complete"]
    assert not result["graphs"][0]["complete"]
    assert result["graphs"][0]["edges"][0]["status"] == "pending"


def test_invalid_auxiliary_coordinates_paths_and_proofs_have_no_effect():
    clean = document()
    noisy = copy.deepcopy(clean)
    noisy["graphs"][0].update(bbox=[math.nan, -999, "x"], node_complete=False)
    noisy["graphs"][0]["vertices"][0].update(x=math.nan, y={"invalid": True}, marker_id="fake")
    noisy["graphs"][0]["edges"][0].update(path=["invalid"], candidate_id="fake", pixel_evidence=False)
    assert normalize_semantic_document(noisy, reviewed=True) == normalize_semantic_document(clean, reviewed=True)


def test_ids_generated_stably_and_exact_labels_keep_case_and_subscripts():
    payload = {"body_text": "", "graphs": [{"directed": True,
        "vertices": [{"label": "v₁"}, {"label": "V₁"}, {"label": "v_1"}],
        "edges": [{"from": "v₁", "to": "V₁", "weight": "√2", "edge_label": "e₁", "color": "红色", "style": "dashed"},
                  {"from": "V₁", "to": "v_1", "weight": "−1/2", "edge_label": "2", "color": "#0000ff", "style": "dotted"}]}]}
    before = copy.deepcopy(payload)
    result = normalize_semantic_document(payload, reviewed=True)
    assert result == normalize_semantic_document(payload, reviewed=True)
    assert payload == before
    graph = result["graphs"][0]
    assert graph["id"] == "G1" and graph["complete"]
    assert [v["label"] for v in graph["vertices"]] == ["v₁", "V₁", "v_1"]
    assert [(e["from"], e["to"]) for e in graph["edges"]] == [("v1", "v2"), ("v2", "v3")]
    assert [e["weight"] for e in graph["edges"]] == ["√2", "−1/2"]
    assert [e["edge_label"] for e in graph["edges"]] == ["e₁", "2"]
    assert [e["color"] for e in graph["edges"]] == ["红色", "#0000ff"]
    assert [e["style"] for e in graph["edges"]] == ["dashed", "dotted"]


def test_generated_ids_do_not_steal_a_unique_printed_label():
    payload = document(vertices=[{"label": "A"}, {"label": "v1"}],
                       edges=[{"from": "v1", "to": "A"}])
    graph = normalize_semantic_document(payload, reviewed=True)["graphs"][0]
    assert graph["complete"]
    assert (graph["edges"][0]["from"], graph["edges"][0]["to"]) == ("v2", "v1")


def test_explicit_ids_disambiguate_duplicate_visible_labels():
    payload = document(vertices=[{"id": "a", "label": "x"}, {"id": "b", "label": "x"}],
                       edges=[{"from": "a", "to": "b"}])
    assert normalize_semantic_document(payload, reviewed=True)["graphs"][0]["complete"]
    payload["graphs"][0]["edges"][0]["from"] = "x"
    result = normalize_semantic_document(payload, reviewed=True)
    assert "ambiguous_endpoint" in kinds(result)
    assert result["graphs"][0]["edges"] == []
    assert result["graphs"][0]["unresolved_edges"][0]["record"]["from"] == "x"


def test_duplicate_internal_ids_can_be_reassigned_but_ambiguous_references_cannot():
    payload = document(vertices=[{"id": "same", "label": "A"}, {"id": "same", "label": "B"}],
                       edges=[{"from": "A", "to": "B"}])
    result = normalize_semantic_document(payload, reviewed=True)
    assert result["graphs"][0]["complete"]
    assert len({v["id"] for v in result["graphs"][0]["vertices"]}) == 2
    payload["graphs"][0]["edges"][0]["from"] = "same"
    result = normalize_semantic_document(payload, reviewed=True)
    assert "ambiguous_endpoint" in kinds(result)
    assert not result["graphs"][0]["complete"]


def test_reserved_ids_are_not_taken_by_generated_ones_and_numeric_ids_work():
    payload = document(vertices=[{"label": "A"}, {"id": "v1", "label": "B"}, {"id": 7, "label": 7}],
                       edges=[{"from": "A", "to": "v1"}, {"from": "v1", "to": 7}])
    graph = normalize_semantic_document(payload, reviewed=True)["graphs"][0]
    assert graph["complete"]
    assert [v["id"] for v in graph["vertices"]] == ["v1_1", "v1", "7"]
    assert graph["edges"][1]["to"] == "7"


def test_invalid_edges_are_preserved_and_do_not_invent_nodes_or_crash_display():
    payload = document(edges=[{"id": "good", "from": "a", "to": "b"},
                              {"id": "bad", "from": "a", "to": "absent", "weight": "k"},
                              {"id": "missing", "from": "a"}, 3])
    result = normalize_semantic_document(payload, reviewed=True)
    graph = result["graphs"][0]
    assert not result["complete"] and not graph["complete"]
    assert len(graph["vertices"]) == 2 and len(graph["edges"]) == 1
    assert graph["edges"][0]["id"] == "good" and graph["edges"][0]["status"] == "accepted"
    assert len(graph["unresolved_edges"]) == 3
    assert graph["unresolved_edges"][0]["record"]["weight"] == "k"
    assert {"unknown_endpoint", "missing_endpoint", "invalid_edge"} <= kinds(result)
    issue = next(x for x in result["semantic_issues"] if x["kind"] == "unknown_endpoint")
    assert (issue["scope"], issue["graph_id"], issue["edge_id"], issue["endpoint"], issue["reference"]) == ("graph", "g", "bad", "to", "absent")
    assert "暂录1条" in describe_graphs(result["graphs"])


def test_parallel_edges_loops_isolates_and_reciprocal_arcs_are_preserved():
    payload = document(directed=True, multigraph=False,
        vertices=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"id": "isolated", "label": None}],
        edges=[{"id": "same", "from": "a", "to": "b"},
               {"id": "same", "from": "a", "to": "b"},
               {"from": "b", "to": "a"}, {"from": "a", "to": "a"}])
    graph = normalize_semantic_document(payload, reviewed=True)["graphs"][0]
    assert graph["complete"] and graph["multigraph"] is True
    assert len(graph["edges"]) == 4 and len({e["id"] for e in graph["edges"]}) == 4
    assert [e["parallel_count"] for e in graph["edges"]] == [2, 2, 1, 1]
    assert graph["vertices"][2]["isolated_confirmed"]
    assert graph["vertices"][2]["label"] is None
    assert audit_graph_records([graph]) == []
    reciprocal = normalize_semantic_document(document(directed=True, edges=[
        {"from": "a", "to": "b"}, {"from": "b", "to": "a"}]), reviewed=True)["graphs"][0]
    assert reciprocal["multigraph"] is False
    assert [e["parallel_count"] for e in reciprocal["edges"]] == [1, 1]


def test_edge_facts_override_redundant_type_flags_without_erasing_content():
    payload = document(directed=False, weighted=False, multigraph=False,
                       edges=[{"from": "a", "to": "b", "direction": "forward", "weight": "0"},
                              {"from": "a", "to": "b", "direction": "forward", "weight": 2}])
    result = normalize_semantic_document(payload, reviewed=True)
    graph = result["graphs"][0]
    assert result["semantic_issues"] == [] and graph["complete"]
    assert (graph["directed"], graph["weighted"], graph["multigraph"]) == (True, True, True)
    assert [e["weight"] for e in graph["edges"]] == ["0", 2]


def test_mixed_directions_and_partial_weights_can_be_fully_specified():
    payload = document(directed="unknown", weighted="unknown", edges=[
        {"from": "a", "to": "b", "direction": "forward", "weight": "x₁"},
        {"from": "b", "to": "a", "direction": "undirected", "weight": None}])
    result = normalize_semantic_document(payload, reviewed=True)
    graph = result["graphs"][0]
    assert result["complete"] and graph["complete"]
    assert graph["directed"] == "unknown" and graph["direction_mode"] == "mixed"
    assert graph["weighted"] is True
    assert [e["direction"] for e in graph["edges"]] == ["forward", "undirected"]
    assert [e["weight"] for e in graph["edges"]] == ["x₁", None]
    assert "v₁→V_2" in describe_graphs([graph]) and "V_2—v₁" in describe_graphs([graph])
    assert "混合图" in describe_graphs([graph]) and "方向未确定" not in describe_graphs([graph])
    assert display_graph(graph)["direction_mode"] == "mixed"


@pytest.mark.parametrize("style, normalized, rendered", [
    ("实线", "solid", "实线"), ("solid", "solid", "实线"),
    ("虚线", "dashed", "虚线"), ("dashed", "dashed", "虚线"),
    ("点线", "dotted", "点线"), ("dotted", "dotted", "点线"),
    (" DASHED ", "dashed", "虚线"),
])
def test_clear_style_synonyms_reach_existing_display(style, normalized, rendered):
    result = normalize_semantic_document(document(edges=[{"from": "a", "to": "b", "style": style}]), reviewed=True)
    graph = result["graphs"][0]
    assert graph["complete"] and graph["edges"][0]["style"] == normalized
    assert display_graph(graph)["edges"][0]["style"] == normalized
    assert rendered in describe_graphs([graph])


@pytest.mark.parametrize("direction", [None, "unknown", "reverse", ["forward"]])
def test_explicit_unknown_or_bad_directions_are_not_overridden_by_graph_type(direction):
    result = normalize_semantic_document(document(directed=True,
        edges=[{"from": "a", "to": "b", "direction": direction}]), reviewed=True)
    graph = result["graphs"][0]
    assert not graph["complete"] and "unknown_direction" in kinds(result)
    assert graph["edges"][0]["direction"] == "unknown"
    assert graph["edges"][0]["status"] == "pending"


def test_missing_direction_without_semantic_graph_type_does_not_guess():
    payload = document(directed="false")
    result = normalize_semantic_document(payload, reviewed=True)
    assert "unknown_direction" in kinds(result)
    assert result["graphs"][0]["directed"] == "unknown"


def test_unresolved_edge_cannot_disappear_from_graph_direction_inference():
    result = normalize_semantic_document(document(edges=[
        {"from": "a", "to": "b", "direction": "undirected"},
        {"from": "a", "to": "missing", "direction": "unknown"},
    ]), reviewed=True)
    assert result["graphs"][0]["directed"] == "unknown"
    assert "unknown_endpoint" in kinds(result) and "unknown_direction" in kinds(result)


@pytest.mark.parametrize("weight", [True, math.nan, math.inf, {"guess": 3}, [2]])
def test_invalid_weights_are_not_silently_erased_then_accepted(weight):
    payload = document(edges=[{"from": "a", "to": "b", "weight": weight}])
    result = normalize_semantic_document(payload, reviewed=True)
    assert "invalid_weight" in kinds(result)
    graph = result["graphs"][0]
    assert not graph["complete"] and graph["edges"][0]["status"] == "pending"
    assert graph["unresolved_edges"][0]["record"]["weight"] is not None
    json.dumps(result, allow_nan=False)


def test_body_uncertainty_does_not_invalidate_correct_graphs_and_graph_scope_is_local():
    payload = document()
    second = copy.deepcopy(payload["graphs"][0])
    second["id"] = "other"
    payload["graphs"].append(second)
    payload["uncertainties"] = [{"scope": "body", "kind": "unreadable_subscript", "message": "第三问下标不清楚。"}]
    result = normalize_semantic_document(payload, reviewed=True)
    assert not result["body_complete"] and not result["complete"]
    assert all(g["complete"] for g in result["graphs"])
    assert all(g["edges"][0]["status"] == "accepted" for g in result["graphs"])
    payload["uncertainties"] = [{"scope": "graph", "graph_id": "g", "message": "一条边权值模糊。"}]
    result = normalize_semantic_document(payload, reviewed=True)
    assert result["body_complete"]
    assert [g["complete"] for g in result["graphs"]] == [False, True]


def test_document_uncertainty_and_unknown_graph_scope_remain_visible():
    payload = document()
    payload["uncertainties"] = ["可能还有一个面板。"]
    result = normalize_semantic_document(payload, reviewed=True)
    assert not result["body_complete"] and not result["graphs"][0]["complete"]
    payload["uncertainties"] = {"scope": "graph", "graph_id": "missing", "message": "节点不清楚。"}
    result = normalize_semantic_document(payload, reviewed=True)
    assert "unresolved_uncertainty_scope" in kinds(result)
    assert result["semantic_issues"][0]["scope"] == "document"


def test_text_only_and_graph_only_are_valid_but_empty_and_missing_content_are_visible():
    text = "① 求 A 的逆矩阵。\n② 判断命题 p∧q。"
    result = normalize_semantic_document({"body_text": text, "graphs": []}, reviewed=True)
    assert result["complete"] and result["body_complete"] and result["graphs"] == []
    assert result["body_text"] == text
    only_graph = document()
    only_graph["body_text"] = ""
    assert normalize_semantic_document(only_graph, reviewed=True)["complete"]
    assert "empty_document" in kinds(normalize_semantic_document({"body_text": "", "graphs": []}, reviewed=True))
    assert "invalid_graph_inventory" in kinds(normalize_semantic_document({"body_text": text}, reviewed=True))
    missing_body = document()
    del missing_body["body_text"]
    result = normalize_semantic_document(missing_body, reviewed=True)
    assert not result["body_complete"] and result["graphs"][0]["complete"]


def test_resource_limits_are_explicit_and_cannot_claim_complete():
    vertices = [{"id": f"n{i}"} for i in range(MAX_VERTICES + 1)]
    payload = document(vertices=vertices, edges=[])
    result = normalize_semantic_document(payload, reviewed=True)
    assert "vertex_capacity_exceeded" in kinds(result)
    assert len(result["graphs"][0]["vertices"]) == MAX_VERTICES
    edges = [{"from": "a", "to": "b"} for _ in range(MAX_EDGES + 1)]
    result = normalize_semantic_document(document(edges=edges), reviewed=True)
    assert "edge_capacity_exceeded" in kinds(result)
    assert len(result["graphs"][0]["edges"]) == MAX_EDGES
    payload = document()
    payload["graphs"] = [dict(payload["graphs"][0], id=f"g{i}") for i in range(MAX_GRAPHS + 1)]
    result = normalize_semantic_document(payload, reviewed=True)
    assert "graph_capacity_exceeded" in kinds(result)
    assert len(result["graphs"]) == MAX_GRAPHS and not result["complete"]


def test_unreadable_values_are_retained_with_usable_content_and_safe_json():
    payload = document(vertices=[{"id": "a", "label": {"bad": True}}, {"id": "b", "label": "B"}],
                       edges=[{"from": "a", "to": "b", "edge_label": False, "color": ["red"], "style": 1}])
    result = normalize_semantic_document(payload, reviewed=True)
    assert {"invalid_vertex_label", "invalid_edge_label", "invalid_color", "invalid_style"} <= kinds(result)
    assert len(result["graphs"][0]["vertices"]) == 2 and len(result["graphs"][0]["edges"]) == 1
    assert result["graphs"][0]["unresolved_vertices"]
    json.dumps(result, allow_nan=False)


def test_visible_strings_are_not_silently_truncated_or_moved_to_weight():
    label, edge_label, weight = "V₁" * 40, "e_1" * 30, " x₁ + " * 20
    payload = document(vertices=[{"id": "a", "label": label}, {"id": "b", "label": None}],
                       edges=[{"from": "a", "to": "b", "edge_label": edge_label, "weight": weight,
                               "color": "深蓝" * 20, "style": "dash-dot"}])
    graph = normalize_semantic_document(payload, reviewed=True)["graphs"][0]
    assert graph["complete"] and graph["vertices"][0]["label"] == label
    assert graph["edges"][0]["edge_label"] == edge_label
    assert graph["edges"][0]["weight"] == weight
    assert graph["edges"][0]["color"] == "深蓝" * 20 and graph["edges"][0]["style"] == "dash-dot"


@pytest.mark.parametrize("payload", [None, [], "not an object", 1])
def test_invalid_documents_return_explicit_safe_partial_results(payload):
    result = normalize_semantic_document(payload, reviewed=True)
    assert kinds(result) == {"invalid_document"}
    assert not result["complete"] and not result["body_complete"]
    assert result["graphs"] == []
