import copy
import math

import pytest

from graph_semantic_schema import normalize_semantic_document
from graph_semantic_sources import SOURCE_READ_PROMPT, merge_source_readings, source_batches


def draft(edges=None, graph_id="G"):
    return {"body_text": "保持题干 v₁。", "graphs": [{"id": graph_id, "name": "图甲", "directed": False,
        "vertices": [{"id": "a", "label": "A", "position": "左上", "x": 120, "y": 200},
                     {"id": "b", "label": "B", "position": "右下"}, {"id": "c", "label": None}],
        "edges": copy.deepcopy(edges or [])}]}


def edge(to, direction="undirected", **attrs):
    return {"to": to, "direction": direction, **attrs}


def readings(a=None, b=None, c=None, gid="G"):
    return [{"graph_id": gid, "source_ids": ["a", "b", "c"], "response": {"sources": [
        {"id": "a", "edges": a or []}, {"id": "b", "edges": b or []}, {"id": "c", "edges": c or []}]}}]


def kinds(result):
    return {item["kind"] for item in result["issues"]}


def test_batches_have_all_nodes_each_time_but_never_initial_edges_or_private_metadata():
    value = draft([{"from": "a", "to": "b", "secret_answer": "not for reader"}])
    value["graphs"][0]["vertices"][0].update(evidence={"edges": ["secret"]}, path=[1, 2])
    before = copy.deepcopy(value)
    batches = source_batches(value, max_sources=2)
    assert [b["source_ids"] for b in batches] == [["a", "b"], ["c"]]
    assert all(len(b["vertices"]) == 3 for b in batches)
    assert all(set(b) == {"graph_id", "graph_name", "vertices", "source_ids"} for b in batches)
    assert batches[0]["vertices"][0] == {"id": "a", "label": "A", "position": "左上", "x": 120, "y": 200}
    assert "secret" not in str(batches) and "edges" not in str(batches)
    batches[0]["vertices"][0]["label"] = "changed"
    assert value == before and batches[1]["vertices"][0]["label"] == "A"


def test_missing_coordinates_are_valid_and_nonfinite_auxiliary_values_are_omitted():
    value = draft()
    value["graphs"][0]["vertices"][0].update(x=math.nan, y=True)
    projected = source_batches(value)[0]["vertices"]
    assert "x" not in projected[0] and "y" not in projected[0]
    assert projected[1]["id"] == "b" and projected[2]["label"] is None


@pytest.mark.parametrize("size", [True, 0, -1, 101, 1.5])
def test_invalid_batch_size_is_visible(size):
    with pytest.raises(ValueError, match="batch_size"):
        source_batches(draft(), size)


def test_sources_can_use_stable_generated_ids_without_inventing_printed_labels():
    value = {"body_text": "", "graphs": [{"vertices": [{"label": "X"}, {"label": None}], "edges": []}]}
    batch = source_batches(value)[0]
    assert batch["graph_id"] == "G1" and batch["source_ids"] == ["v1", "v2"]
    result = merge_source_readings(value, [{**batch, "response": {"sources": [
        {"id": "v1", "edges": [edge("v2")]}, {"id": "v2", "edges": [edge("v1")]}]}}])
    assert result["issues"] == []
    assert result["document"]["graphs"][0]["vertices"][1]["label"] is None


def test_undirected_opposite_reads_merge_one_instance_and_preserve_body_nodes():
    value = draft()
    before = copy.deepcopy(value)
    result = merge_source_readings(value, readings([edge("b")], [edge("a")]))
    graph = result["document"]["graphs"][0]
    assert result["issues"] == [] and len(graph["edges"]) == 1
    assert graph["vertices"] == value["graphs"][0]["vertices"]
    assert result["document"]["body_text"] == value["body_text"] and value == before
    assert result["source_audit"]["graphs"][0]["status"] == "readings_reconciled"


def test_parallel_instances_match_multisets_even_when_reverse_order_differs():
    result = merge_source_readings(draft(), readings(
        [edge("b", color="red", edge_label="e₁"), edge("b", color="blue", weight="x₁")],
        [edge("a", color="蓝色", weight="x₁"), edge("a", color="红色", edge_label="e₁")]))
    edges = result["document"]["graphs"][0]["edges"]
    assert result["issues"] == [] and len(edges) == 2
    assert len({e["id"] for e in edges}) == 2
    assert [e.get("color") for e in edges] == ["red", "blue"]
    assert edges[0]["edge_label"] == "e₁" and edges[1]["weight"] == "x₁"


def test_identical_parallel_edges_are_not_set_deduplicated():
    result = merge_source_readings(draft(), readings([edge("b"), edge("b")], [edge("a"), edge("a")]))
    assert result["issues"] == [] and len(result["document"]["graphs"][0]["edges"]) == 2
    normalized = normalize_semantic_document(result["document"], reviewed=True)
    assert normalized["graphs"][0]["multigraph"] is True


def test_self_loops_are_counted_once_per_observed_instance_not_twice():
    result = merge_source_readings(draft(), readings([edge("a"), edge("a", "forward"), edge("a", "forward")]))
    assert result["issues"] == [] and len(result["document"]["graphs"][0]["edges"]) == 3


def test_directed_edges_need_no_reverse_target_report_and_reciprocal_arcs_survive():
    result = merge_source_readings(draft(), readings([edge("b", "forward"), edge("b", "forward")]))
    assert result["issues"] == [] and len(result["document"]["graphs"][0]["edges"]) == 2
    result = merge_source_readings(draft(), readings([edge("b", "forward")], [edge("a", "forward")]))
    assert result["issues"] == []
    assert {(e["from"], e["to"]) for e in result["document"]["graphs"][0]["edges"]} == {("a", "b"), ("b", "a")}


def test_mixed_directed_and_undirected_edges_can_coexist_on_same_pair():
    result = merge_source_readings(draft(), readings(
        [edge("b", "forward"), edge("b")], [edge("a", "forward"), edge("a")]))
    assert result["issues"] == [] and len(result["document"]["graphs"][0]["edges"]) == 3


def test_count_mismatch_keeps_draft_pair_without_summing_observations():
    old = [{"id": "old", "from": "a", "to": "b", "direction": "undirected", "edge_label": "old label"}]
    result = merge_source_readings(draft(old), readings([edge("b"), edge("b")], [edge("a")]))
    assert "undirected_instance_mismatch" in kinds(result)
    assert result["document"]["graphs"][0]["edges"] == old
    pair = result["source_audit"]["graphs"][0]["pairs"][0]
    assert pair["decision"] == "retained_draft_pair" and not pair["confirmed_by_readings"]
    assert len(pair["readings"]) == 3
    assert not normalize_semantic_document(result["document"], reviewed=True)["graphs"][0]["complete"]


def test_conflict_without_draft_keeps_one_side_not_sum_or_intersection():
    result = merge_source_readings(draft(), readings([edge("b", color="red"), edge("b", color="red")], [edge("a", color="blue")]))
    assert "undirected_instance_mismatch" in kinds(result)
    assert len(result["document"]["graphs"][0]["edges"]) == 2
    assert result["source_audit"]["graphs"][0]["pairs"][0]["decision"] == "retained_one_side_candidates"


@pytest.mark.parametrize("attribute,left,right", [("weight", "2", "3"), ("edge_label", "e₁", "E₁"),
                                                    ("color", "red", "blue"), ("style", "solid", "dashed")])
def test_semantic_attribute_disagreements_are_not_hidden_by_matching_counts(attribute, left, right):
    result = merge_source_readings(draft(), readings([edge("b", **{attribute: left})], [edge("a", **{attribute: right})]))
    assert "undirected_instance_mismatch" in kinds(result)


def test_style_and_color_clear_aliases_match_but_unknown_is_never_confirmed():
    result = merge_source_readings(draft(), readings([edge("b", color="蓝色", style="虚线")], [edge("a", color="blue", style="DASHED")]))
    assert result["issues"] == []
    result = merge_source_readings(draft(), readings([edge("b", color="unknown")], [edge("a", color="unknown")]))
    assert "uncertain_source_attributes" in kinds(result)
    assert not result["source_audit"]["graphs"][0]["pairs"][0]["confirmed_by_readings"]


@pytest.mark.parametrize("default", [{}, {"style": None}])
def test_only_missing_or_null_style_matches_explicit_ordinary_solid(default):
    result = merge_source_readings(draft(), readings([edge("b", **default)], [edge("a", style="solid")]))
    assert result["issues"] == [] and len(result["document"]["graphs"][0]["edges"]) == 1
    audit = result["source_audit"]["graphs"][0]
    assert audit["pairs"][0]["confirmed_by_readings"]
    assert audit["style_default"] == {"rule": "missing_or_null_means_ordinary_solid",
                                      "explicit_measurement": False, "source_edge_counts": {"a": 1}}
    assert audit["observations"][0].get("style") is None
    assert audit["observations"][1]["style"] == "solid"


@pytest.mark.parametrize("explicit", ["dashed", "dotted", "unknown"])
@pytest.mark.parametrize("default", [{}, {"style": None}])
def test_default_style_does_not_confirm_special_or_explicit_unknown_style(default, explicit):
    result = merge_source_readings(draft(), readings([edge("b", **default)], [edge("a", style=explicit)]))
    assert "undirected_instance_mismatch" in kinds(result)
    assert not result["source_audit"]["graphs"][0]["pairs"][0]["confirmed_by_readings"]
    if explicit == "unknown":
        assert "uncertain_source_attributes" in kinds(result)


def test_clear_decimal_weight_spellings_match_without_rewriting_printed_value():
    result = merge_source_readings(draft(), readings([edge("b", weight="2.00")], [edge("a", weight=2)]))
    assert result["issues"] == []
    assert result["document"]["graphs"][0]["edges"][0]["weight"] == "2.00"
    result = merge_source_readings(draft(), readings([edge("b", weight="1+1")], [edge("a", weight=2)]))
    assert "undirected_instance_mismatch" in kinds(result)


def test_ambiguous_label_endpoint_is_reported_without_choosing_a_node():
    value = draft()
    value["graphs"][0]["vertices"][1]["label"] = "X"
    value["graphs"][0]["vertices"][2]["label"] = "X"
    result = merge_source_readings(value, readings([edge("X")]))
    assert "invalid_source_endpoint" in kinds(result)
    issue = next(x for x in result["issues"] if x["kind"] == "invalid_source_endpoint")
    assert issue["source_id"] == "a" and issue["reference"] == "X"


def test_missing_source_keeps_incident_draft_edges_and_only_marks_its_graph():
    old = [{"from": "a", "to": "b", "direction": "undirected"}]
    value = draft(old)
    value["graphs"].append(draft(graph_id="G2")["graphs"][0])
    partial = [{"graph_id": "G", "source_ids": ["a", "c"], "response": {"sources": [
        {"id": "a", "edges": [edge("b")]}, {"id": "c", "edges": []}]}}]
    result = merge_source_readings(value, partial + readings([edge("b")], [edge("a")], gid="G2"))
    assert "missing_source_reading" in kinds(result)
    assert len(result["document"]["graphs"][0]["edges"]) == 1
    normalized = normalize_semantic_document(result["document"], reviewed=True)
    assert [g["complete"] for g in normalized["graphs"]] == [False, True]


def test_same_vertex_ids_in_different_panels_never_cross_merge():
    value = draft()
    value["graphs"].append(draft(graph_id="G2")["graphs"][0])
    result = merge_source_readings(value, readings([edge("b")], [edge("a")]) + readings([edge("c")], c=[edge("a")], gid="G2"))
    assert result["issues"] == []
    assert [g["edges"][0]["to"] for g in result["document"]["graphs"]] == ["b", "c"]


def test_invalid_endpoint_and_duplicate_source_cannot_silently_replace_draft():
    old = [{"from": "a", "to": "b", "direction": "undirected"}]
    incoming = readings([edge("absent")], [edge("a")])
    incoming[0]["response"]["sources"].append({"id": "a", "edges": []})
    result = merge_source_readings(draft(old), incoming)
    assert {"invalid_source_endpoint", "duplicate_source_reading"} <= kinds(result)
    assert len(result["document"]["graphs"][0]["edges"]) == 1


def test_all_explicit_empty_sources_can_remove_old_edges_without_degree_reasoning():
    result = merge_source_readings(draft([{"from": "a", "to": "b", "direction": "undirected"}]), readings())
    assert result["issues"] == [] and result["document"]["graphs"][0]["edges"] == []
    assert len(result["document"]["graphs"][0]["vertices"]) == 3
    assert result["source_audit"]["graphs"][0]["pairs"][0]["decision"] == "absent_in_complete_source_readings"


def test_missing_edges_list_is_not_an_isolated_node_assertion():
    incoming = readings()
    del incoming[0]["response"]["sources"][0]["edges"]
    result = merge_source_readings(draft(), incoming)
    assert "invalid_source_edges" in kinds(result)


def test_instruction_asks_for_source_lists_without_template_or_degree_completion():
    assert "source_ids" in SOURCE_READ_PROMPT and "平行边逐条" in SOURCE_READ_PROMPT
    assert "不用度数" in SOURCE_READ_PROMPT and "自环" in SOURCE_READ_PROMPT
