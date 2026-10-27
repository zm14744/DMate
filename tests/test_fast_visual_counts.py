"""Independent visual-count claims must never silently disappear during a local reread.

All samples are synthetic provider responses: these tests do not establish
that a photographed graph was visually read with the correct number of edges.
"""
import copy

import pytest

import graph_fast_pipeline as fast
from test_graph_fast_pipeline import Provider, Specialist, document, prepared


@pytest.mark.parametrize(("field", "list_name", "extra"), [
    ("visible_vertex_count", "vertices", 2),
    ("visible_edge_count", "edges", 4),
])
def test_model_visible_counts_trigger_scoped_review_only_when_mismatched(
        prepared, field, list_name, extra):
    _, run, _ = prepared
    initial = document()
    initial["graphs"][0][field] = extra
    reviewed = copy.deepcopy(initial["graphs"][0])
    if list_name == "vertices":
        reviewed["vertices"] = reviewed["vertices"][:2]
    else:
        reviewed["edges"].append({
            "id": "e4", "from": "b", "to": "z", "direction": "undirected",
            "style": "solid"
        })
    specialist = Specialist({"graphs": [reviewed], "uncertainties": []})
    result, main = run(Provider(initial), specialist)
    assert len(main.requests) == len(specialist.requests) == 1
    assert any(issue["kind"] == "visual_count_mismatch"
               and issue["field"] == list_name
               for issue in specialist.requests[0]["issues"])
    assert specialist.requests[0]["targets"]["graph_ids"] == ["G1"]
    assert result["graphs"][1]["complete"] is True
    assert result["graphs"][1]["edges"] == fast.normalize_semantic_document(
        document(), reviewed=True)["graphs"][1]["edges"]
    assert result["complete"] is True
    assert result["semantic_workflow"]["image_accuracy_certified"] is False


@pytest.mark.parametrize("count", [None, True, "3", -1, 101, 3.0])
def test_unresolved_or_invalid_visual_count_is_not_confident_success(count):
    original = document()
    original["graphs"][0]["visible_vertex_count"] = count
    issues = fast._visual_count_issues(original)
    assert len(issues) == 1
    expected = "visual_count_unresolved" if count is None else "visual_count_invalid"
    assert issues[0]["kind"] == expected
    assert issues[0]["field"] == "vertices"
    assert issues[0]["graph_id"] == "G1"


def test_matching_counts_are_only_consistency_not_pixel_accuracy(prepared):
    _, run, _ = prepared
    initial = document()
    for graph in initial["graphs"]:
        graph["visible_vertex_count"] = len(graph["vertices"])
        graph["visible_edge_count"] = len(graph["edges"])
    result, main = run(Provider(initial), Specialist(
        AssertionError("Matching model counts must not force a paid review")))
    assert len(main.requests) == 1
    assert result["complete"] is True
    assert result["semantic_workflow"]["image_accuracy_certified"] is False


def test_legacy_omitted_counts_stay_compatible():
    assert fast._visual_count_issues(document()) == []


def test_review_cannot_erase_mismatched_count_by_omitting_field():
    initial = document()
    initial["graphs"][0]["visible_vertex_count"] = 4
    proposed = copy.deepcopy(initial["graphs"][0])
    proposed.pop("visible_vertex_count")
    reviewed, pending = fast._merge_local_review(
        initial, {"graphs": [proposed], "uncertainties": []},
        {"graph_ids": ["G1"], "document": False, "body": False})
    assert not pending
    assert reviewed["graphs"][0]["visible_vertex_count"] == 4
    assert any(issue["kind"] == "visual_count_mismatch"
               for issue in fast._visual_count_issues(reviewed))


def test_recount_omission_after_changing_edge_number_remains_unresolved():
    initial = document()
    initial["graphs"][0]["visible_edge_count"] = 3
    proposed = copy.deepcopy(initial["graphs"][0])
    proposed.pop("visible_edge_count")
    proposed["edges"].pop()
    reviewed, pending = fast._merge_local_review(
        initial, {"graphs": [proposed], "uncertainties": []},
        {"graph_ids": ["G1"], "document": False, "body": False})
    assert not pending
    assert reviewed["graphs"][0]["visible_edge_count"] is None
    assert any(issue["kind"] == "visual_count_unresolved"
               for issue in fast._visual_count_issues(reviewed))


def test_count_issues_remain_scoped_to_the_correct_panel():
    original = document()
    original["graphs"][0]["visible_vertex_count"] = 4
    original["graphs"][1]["visible_edge_count"] = 1
    issues = fast._visual_count_issues(original)
    assert len(issues) == 1
    assert issues[0]["graph_id"] == "G1"
