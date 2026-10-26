"""Comparison-only regressions; no image/model accuracy is certified here."""
import copy
import json

import pytest

import graph_semantic_changes as changes
from graph_semantic_changes import meaningful_review_changes


def document(edges=None, *, labels=("a", "b", "c")):
    return {"body_text": "③求v₅的度数。", "graphs": [{"id": "G1", "name": "(a)",
        "vertices": [{"id": str(i), "label": label} for i, label in enumerate(labels)],
        "edges": copy.deepcopy(edges if edges is not None else [
            {"from": "0", "to": "1", "direction": "forward", "weight": 1}])}]}


def edge(doc, index=0):
    return doc["graphs"][0]["edges"][index]


@pytest.mark.parametrize("default", [None, "", "unknown", "default", "ordinary"])
def test_ordinary_black_and_display_default_do_not_trigger_review(default):
    old, new = document(), document()
    edge(old).update(color="black", style="solid")
    edge(new)["color"] = default
    assert meaningful_review_changes(old, new) == []
    edge(new).pop("color")
    assert meaningful_review_changes(new, old) == []


@pytest.mark.parametrize("special", ["red", "blue", "green", "purple"])
def test_meaningful_color_is_not_swallowed_by_default(special):
    old, new = document(), document()
    edge(old)["color"] = special
    result = meaningful_review_changes(old, new)
    assert result[0]["removed_or_changed_instances"] == 1
    assert result[0]["previous_edges"][0]["color"] == special


@pytest.mark.parametrize("old_style,new_style,equal", [
    (None, "solid", True), (None, "实线", True), ("虚线", "dashed", True),
    ("点线", "dotted", True), ("unknown", "solid", False),
    (None, "dashed", False), (None, "dotted", False), ("dashed", "dotted", False)])
def test_style_default_and_explicit_unknown_are_distinct(old_style, new_style, equal):
    old, new = document(), document()
    edge(old)["style"], edge(new)["style"] = old_style, new_style
    assert (meaningful_review_changes(old, new) == []) is equal


@pytest.mark.parametrize("old_weight,new_weight,equal", [
    (1, "1.00", True), (0, "0", True), (-2.5, "-2.50", True),
    (1000, "1e3", True), ("12345678901234567890123456789", 12345678901234567890123456789, True),
    (0, None, False), (-1, 1, False), ("x", "X", False), ("x+1", "1+x", False),
    ("__import__('os').system('false')", "0", False)])
def test_numeric_literals_without_expression_execution(old_weight, new_weight, equal):
    old, new = document(), document()
    edge(old)["weight"], edge(new)["weight"] = old_weight, new_weight
    assert (meaningful_review_changes(old, new) == []) is equal


def rename(doc, names):
    result = copy.deepcopy(doc)
    for vertex in result["graphs"][0]["vertices"]:
        vertex["id"] = names[vertex["id"]]
    for e in result["graphs"][0]["edges"]:
        e["from"], e["to"] = names[e["from"]], names[e["to"]]
        e["id"] = "new-internal-edge-id"
    return result


@pytest.mark.parametrize("labels", [("a", "b", "c"), (None, None, None), ("a", "a", None)])
def test_internal_ids_reordering_and_geometry_have_no_visible_semantics(labels):
    old = document(labels=labels)
    new = rename(old, {"0": "z", "1": "x", "2": "y"})
    new["graphs"][0]["vertices"].reverse()
    for v in new["graphs"][0]["vertices"]:
        v.update(x="not a coordinate", y=float("nan"), position="somewhere else")
    assert meaningful_review_changes(old, new) == []


def test_joint_attributes_cannot_be_permuted_between_parallel_instances():
    old = document([
        {"from": "0", "to": "1", "direction": "forward", "weight": 1, "color": "red"},
        {"from": "0", "to": "1", "direction": "forward", "weight": 2, "color": "blue"}])
    new = copy.deepcopy(old)
    edge(new, 0)["color"], edge(new, 1)["color"] = "blue", "red"
    result = meaningful_review_changes(old, new)[0]
    assert result["removed_or_changed_instances"] == result["added_or_changed_instances"] == 2


def test_parallel_multiplicity_and_self_loops_are_not_set_deduplicated():
    old = document([
        {"from": "0", "to": "1", "direction": "undirected"},
        {"from": "0", "to": "1", "direction": "undirected"},
        {"from": "0", "to": "0", "direction": "forward"}])
    new = copy.deepcopy(old)
    new["graphs"][0]["edges"].pop(0)
    assert meaningful_review_changes(old, new)[0]["removed_or_changed_instances"] == 1
    new = copy.deepcopy(old)
    new["graphs"][0]["edges"].pop()
    assert meaningful_review_changes(old, new)[0]["previous_edges"][0]["from"] == "0"
    assert meaningful_review_changes(old, new)[0]["previous_edges"][0]["to"] == "0"


def test_opposite_directed_arcs_differ_and_have_actual_before_after_examples():
    old = document([
        {"from": "0", "to": "1", "direction": "forward", "edge_label": "e₂"},
        {"from": "0", "to": "1", "direction": "forward", "edge_label": "e₃"}])
    new = copy.deepcopy(old)
    edge(new, 1)["from"], edge(new, 1)["to"] = "1", "0"
    issue = meaningful_review_changes(old, new)[0]
    assert issue["previous_edges"][0]["edge_label"] == "e₃"
    assert issue["previous_edges"][0]["from_label"] == "a"
    assert issue["proposed_edges"][0]["from_label"] == "b"
    assert issue["vertex_ids"] == ["0", "1"]


def test_undirected_endpoint_order_is_equivalent_even_with_internal_id_changes():
    old = document([{"from": "0", "to": "1", "direction": "undirected", "color": "红色"}])
    new = rename(old, {"0": "z", "1": "x", "2": "y"})
    edge(new)["from"], edge(new)["to"], edge(new)["color"] = "x", "z", "red"
    assert meaningful_review_changes(old, new) == []


@pytest.mark.parametrize("label", ["v₃", "V₅", "v5"])
def test_visible_vertex_case_and_subscripts_remain_significant(label):
    old = document(labels=("v₅", "b", "c"))
    new = copy.deepcopy(old)
    new["graphs"][0]["vertices"][0]["label"] = label
    issue = meaningful_review_changes(old, new)[0]
    assert issue["previous_vertices"][0]["label"] == "v₅"
    assert issue["proposed_vertices"][0]["label"] == label


def test_printed_edge_names_and_graph_caption_remain_significant():
    old, new = document(), document()
    edge(old)["edge_label"], edge(new)["edge_label"] = "e₁", "e1"
    assert meaningful_review_changes(old, new)
    new = copy.deepcopy(old)
    new["graphs"][0]["name"] = "(b)"
    issue = meaningful_review_changes(old, new)[0]
    assert issue["previous_name"] == "(a)" and issue["proposed_name"] == "(b)"
    assert issue["removed_or_changed_instances"] == 0


def test_late_changed_label_is_not_hidden_by_vertex_example_cap():
    old = document(labels=tuple(f"label{i}" for i in range(20)))
    new = copy.deepcopy(old)
    new["graphs"][0]["vertices"][-1]["label"] = "changed"
    issue = meaningful_review_changes(old, new)[0]
    assert issue["previous_vertices"][0] == {"id": "19", "label": "label19"}
    assert issue["proposed_vertices"][0] == {"id": "19", "label": "changed"}
    assert "19" in issue["vertex_ids"]


def test_anonymous_same_degree_counts_do_not_certify_isomorphism():
    def graph_edges(pairs):
        return [{"from": str(a), "to": str(b), "direction": "undirected"} for a, b in pairs]
    cycle = document(graph_edges([(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 0)]), labels=(None,)*6)
    triangles = document(graph_edges([(0, 1), (1, 2), (2, 0), (3, 4), (4, 5), (5, 3)]), labels=(None,)*6)
    assert meaningful_review_changes(cycle, triangles)


def test_inconclusive_bounded_isomorphism_does_not_claim_equality(monkeypatch):
    old = document(labels=(None, None, None))
    new = rename(old, {"0": "x", "1": "y", "2": "z"})
    monkeypatch.setattr(changes, "MAX_ISOMORPHISM_STATES", 0)
    issue = meaningful_review_changes(old, new)[0]
    assert issue["comparison_status"] == "bounded_inconclusive"


def test_body_excerpt_locates_actual_subscript_difference_after_long_prefix():
    old, new = document(), document()
    old["body_text"] = "保持原文。"*150 + "③求v₅的度数。" + "末尾"*300
    new["body_text"] = old["body_text"].replace("v₅", "v₃")
    issue = meaningful_review_changes(old, new)[0]
    assert issue["scope"] == "body"
    assert "v₅" in issue["previous_excerpt"]["text"]
    assert "v₃" in issue["proposed_excerpt"]["text"]
    assert len(issue["previous_excerpt"]["text"]) <= changes.MAX_TEXT_EXCERPT
    assert issue["previous_excerpt"]["truncated"]
    new["body_text"] = "\n ".join(old["body_text"])
    assert meaningful_review_changes(old, new) == []


def test_examples_are_bounded_and_inputs_remain_unchanged():
    old = document([{"from": "0", "to": "1", "direction": "forward", "weight": i} for i in range(14)])
    new = copy.deepcopy(old)
    for e in new["graphs"][0]["edges"]:
        e["weight"] += 100
    saved = copy.deepcopy((old, new))
    issue = meaningful_review_changes(old, new)[0]
    assert len(issue["previous_edges"]) == changes.MAX_EDGE_EXAMPLES
    assert issue["examples_omitted"]["previous_edges"] == 8
    assert (old, new) == saved
    json.dumps(issue, ensure_ascii=False, allow_nan=False)


def test_multigraph_scopes_with_same_local_ids_do_not_mix():
    old = document()
    other = copy.deepcopy(old["graphs"][0]); other["id"] = "G2"; other["name"] = "(b)"
    old["graphs"].append(other)
    new = copy.deepcopy(old)
    new["graphs"][1]["edges"][0]["weight"] = 2
    assert [i["graph_id"] for i in meaningful_review_changes(old, new)] == ["G2"]
