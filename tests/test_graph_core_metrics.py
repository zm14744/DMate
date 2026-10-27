import json

import pytest

from scripts.score_graph_core_metrics import (
    evaluate_run, score_image, score_panel, summarize,
)


def graph(labels=("a", "b", "c"), edges=None):
    return {"vertices": [{"id": str(i), "label": label} for i, label in enumerate(labels)],
            "edges": edges if edges is not None else [edge("0", "1"), edge("1", "2")]}


def edge(a, b, direction="undirected", weight=None, **extra):
    return {"from": a, "to": b, "direction": direction, "weight": weight, **extra}


SCOPE = {"clear_direction_edges": "all", "clear_weight_edges": "all"}


def test_count_correct_does_not_hide_wrong_connections():
    expected = graph()
    actual = graph(edges=[edge("0", "1"), edge("0", "2")])
    result = score_panel(expected, actual, SCOPE)
    assert result["vertex_count"]["status"] == result["edge_count"]["status"] == "pass"
    assert result["connections"]["correct"] == 1
    assert result["connections"]["precision"] == result["connections"]["recall"] == .5


def test_extra_guessed_edges_cannot_inflate_accuracy():
    actual = graph(edges=[edge("0", "1"), edge("1", "2"), edge("0", "2")])
    result = score_panel(graph(), actual, SCOPE)
    assert result["connections"]["recall"] == 1
    assert result["connections"]["precision"] == pytest.approx(2 / 3)
    assert result["connections"]["status"] == "fail"


def test_self_loops_and_parallel_instances_each_count_once():
    expected = graph(edges=[edge("0", "0"), edge("0", "1", multiplicity=2)])
    actual = graph(edges=[edge("0", "0"), edge("0", "1"), edge("0", "1")])
    result = score_panel(expected, actual, SCOPE)
    assert result["edge_count"] == {"status": "pass", "expected": 3, "predicted": 3}
    assert result["connections"]["correct"] == 3


def test_case_differences_align_structure_but_are_label_errors():
    expected = graph(labels=("v1", "v2", "v3"))
    actual = graph(labels=("V₁", "V₂", "V₃"))
    result = score_panel(expected, actual, SCOPE)
    assert result["connections"]["correct"] == 2
    assert result["vertex_labels"]["correct"] == 0
    scoped = {**SCOPE, "vertex_label_variants": {"0": ["v1", "V1"]}}
    result = score_panel(expected, actual, scoped)
    assert result["vertex_labels"]["correct"] == 1


def test_subscript_display_equivalence_and_isolated_vertex_preserved():
    expected = graph(labels=("v_1", "v_{2}", None), edges=[edge("0", "1")])
    actual = graph(labels=("v₁", "v₂", None), edges=[edge("0", "1")])
    assert score_panel(expected, actual, SCOPE)["vertex_labels"]["correct"] == 3
    actual["vertices"].pop()
    result = score_panel(expected, actual, SCOPE)
    assert result["vertex_count"]["status"] == "fail"
    assert result["vertex_labels"]["recall"] == pytest.approx(2 / 3)


def test_unknown_and_reversed_directions_are_not_removed_from_denominator():
    expected = graph(edges=[edge("0", "1", "forward"), edge("1", "2", "forward")])
    actual = graph(edges=[edge("1", "0", "forward"), edge("1", "2", "unknown")])
    result = score_panel(expected, actual, SCOPE)
    assert result["connections"]["correct"] == 2
    assert result["directions"]["expected"] == result["directions"]["predicted"] == 2
    assert result["directions"]["correct"] == 0
    assert result["basic_type"]["status"] == "fail"


def test_weight_must_belong_to_correct_edge_and_direction():
    expected = graph(edges=[edge("0", "1", "forward", 0), edge("1", "0", "forward", "π")])
    actual = graph(edges=[edge("0", "1", "forward", "π"), edge("1", "0", "forward", 0)])
    result = score_panel(expected, actual, SCOPE)
    assert result["connections"]["correct"] == result["directions"]["correct"] == 2
    assert result["weights"]["correct"] == 0
    actual["edges"][0]["weight"] = None
    result = score_panel(expected, actual, SCOPE)
    assert result["weights"]["expected"] == 2
    assert result["weights"]["status"] == "fail"


def test_anonymous_mapping_is_one_consistent_mapping_for_all_fields():
    expected = graph((None, None, None), [edge("0", "1", "forward", 2), edge("1", "2", "forward", 3)])
    actual = graph((None, None, None), [edge("2", "0", "forward", 2), edge("0", "1", "forward", 3)])
    result = score_panel(expected, actual, SCOPE)
    assert result["mapping"]["vertices"] == {"0": "2", "1": "0", "2": "1"}
    assert result["mapping"]["anonymous_mapping_is_structural_upper_bound"] is True
    assert all(result[name]["correct"] == 2 for name in ("connections", "directions", "weights"))


def test_mapping_limit_never_turns_a_partial_search_into_a_pass():
    expected = graph((None,) * 9, [])
    result = score_panel(expected, expected, SCOPE, mapping_limit=100)
    assert result["vertex_count"]["status"] == "pass"
    assert result["connections"]["status"] == "not_assessed"


def test_independent_clarity_scope_controls_reference_denominator():
    expected = graph(edges=[edge("0", "1", "forward"), edge("1", "2", "forward")])
    actual = graph(edges=[edge("0", "1", "forward"), edge("1", "2", "unknown")])
    assert score_panel(expected, actual, {})["directions"]["status"] == "not_assessed"
    scoped = {**SCOPE, "clear_direction_edges": [0]}
    result = score_panel(expected, actual, scoped)
    assert result["directions"]["expected"] == result["directions"]["predicted"] == 1
    assert result["directions"]["status"] == "pass"
    with pytest.raises(ValueError, match="clear_edge_selection"):
        score_panel(expected, actual, {**SCOPE, "clear_direction_edges": [22]})


def image_scope(question=None):
    return {"id": "example", "common_clear": True,
            "panels": [{"reference_index": 0, "prediction_index": 0, **SCOPE}],
            **({"question": question} if question is not None else {})}


def test_panel_counts_do_not_cancel_each_others_missing_vertices():
    reference = {"graphs": [graph(), graph()]}
    prediction = {"graph_structures": [graph(("a", "b"), []), graph(("a", "b", "c", "d"), [])]}
    scope = {"id": "two", "common_clear": True, "panels": [
        {"reference_index": 0, "prediction_index": 0, **SCOPE},
        {"reference_index": 1, "prediction_index": 1, **SCOPE}]}
    result = score_image(reference, prediction, scope)
    assert result["panel_count"]["status"] == "pass"
    assert summarize([result], "predeclared")["metrics"]["vertex_count"] == {"passed": 0, "total": 2, "status": "fail"}


def test_uncertain_or_degraded_fast_response_is_not_a_performance_pass():
    reference, prediction = {"graphs": [graph()]}, {"graph_structures": [graph()], "recognition_status": "complete", "selected_tools_complete": True}
    evidence = {"upload_through_editor_render_seconds": 40}
    assert score_image(reference, prediction, image_scope(), browser_evidence=evidence)["performance"]["status"] == "pass"
    prediction["service_warnings"] = [{"kind": "local_tools_degraded"}]
    assert score_image(reference, prediction, image_scope(), browser_evidence=evidence)["performance"]["status"] == "fail"
    prediction.pop("service_warnings")
    prediction["recognition_status"] = "partial"
    assert score_image(reference, prediction, image_scope(), browser_evidence=evidence)["performance"]["status"] == "fail"


@pytest.mark.parametrize(("audit", "expected_status"), [(False, "fail"), (None, "not_assessed"), (1, "not_assessed"), ("true", "not_assessed")])
def test_performance_requires_explicit_true_tool_completion(audit, expected_status):
    prediction = {"graph_structures": [graph()], "recognition_status": "complete"}
    if audit is not None:
        prediction["selected_tools_complete"] = audit
    result = score_image({"graphs": [graph()]}, prediction, image_scope(),
                         browser_evidence={"upload_through_editor_render_seconds": 40})
    assert result["performance"]["status"] == expected_status
    assert summarize([result], "predeclared")["metrics"]["performance"]["status"] == expected_status


def test_old_degraded_capture_fails_even_without_new_tool_audit():
    prediction = {"graph_structures": [graph()], "recognition_status": "complete",
                  "service_warnings": [{"kind": "local_tools_degraded"}]}
    result = score_image({"graphs": [graph()]}, prediction, image_scope(),
                         browser_evidence={"upload_through_editor_render_seconds": 40})
    assert result["performance"]["status"] == "fail"


@pytest.mark.parametrize("prediction_index", [None, 1, 100])
def test_missing_predicted_panel_is_scored_without_aborting(prediction_index):
    scope = {"id": "missing", "common_clear": True, "panels": [
        {"reference_index": 0, "prediction_index": 0, **SCOPE},
        {"reference_index": 1, "prediction_index": prediction_index, **SCOPE}]}
    expected = {"graphs": [graph(), graph(("isolated",), [])]}
    result = score_image(expected, {"graph_structures": [graph()]}, scope)
    assert result["panel_count"]["status"] == "fail"
    missing = result["panels"][1]
    assert missing["panel_missing"] is True
    assert missing["vertex_count"]["predicted"] == missing["edge_count"]["predicted"] == 0
    assert all(missing[name]["status"] == "fail" for name in ("vertex_count", "edge_count", "basic_type"))
    assert missing["basic_type"]["predicted"] == "missing"
    assert result["panels"][0]["vertex_count"]["status"] == "pass"


@pytest.mark.parametrize("invalid_index", [-1, "1", True, []])
def test_invalid_panel_correspondence_still_rejected(invalid_index):
    scope = image_scope()
    scope["panels"][0]["prediction_index"] = invalid_index
    with pytest.raises(ValueError, match="invalid_prediction_panel_index"):
        score_image({"graphs": [graph()]}, {"graph_structures": []}, scope)


def test_text_missing_annotations_is_unassessed_not_a_fabricated_accuracy():
    result = score_image({"graphs": [graph()], "body_text": "求度数"},
                         {"graph_structures": [graph()], "text": "求度数"}, image_scope())
    assert result["question"]["whole_body_literal_equal"] is True
    assert result["question"]["subquestion_count"]["status"] == result["question"]["key_content"]["status"] == "not_assessed"


def test_numbered_questions_detect_duplicate_and_extra_markers_and_negation():
    declaration = {"counting": "numbered_parentheses", "subquestions": [{"id": "1"}, {"id": "2"}],
                   "critical_items": [{"id": "negative", "literal": "不是树", "forbidden": ["是树且连通"]}]}
    reference = {"graphs": [graph()], "body_text": "(1)不是树。(2)求度数。"}
    prediction = {"graph_structures": [graph()], "text": "（1）不是树。（2）求度数。"}
    result = score_image(reference, prediction, image_scope(declaration))
    assert result["question"]["subquestion_count"]["status"] == result["question"]["key_content"]["status"] == "pass"
    prediction["text"] += "(2)是树且连通"
    result = score_image(reference, prediction, image_scope(declaration))
    assert result["question"]["subquestion_count"]["status"] == result["question"]["key_content"]["status"] == "fail"


def test_nonempty_unsegmented_text_does_not_prove_single_question_count():
    declaration = {"counting": "single_request", "subquestions": [{"id": "1"}]}
    result = score_image({"graphs": [graph()], "body_text": "求度数。"},
                         {"graph_structures": [graph()], "text": "求度数。求最短路。"}, image_scope(declaration))
    assert result["question"]["subquestion_count"]["status"] == "not_assessed"


def test_independent_text_correction_does_not_use_stale_gold():
    scope = image_scope({"counting": "single_request", "manual_text": "写出v5到自身的回路。",
                         "subquestions": [{"id": "1"}]})
    scope["reference_overrides"] = {"body_text": "写出v5到自身的回路。"}
    result = score_image({"graphs": [graph()], "body_text": "写出v1到自身的回路。"},
                         {"graph_structures": [graph()], "text": "写出v5到自身的回路。"}, scope)
    assert result["question"]["whole_body_literal_equal"] is True
    assert result["question"]["subquestion_count"]["status"] == "pass"


def test_frozen_run_checks_original_and_response_bindings(tmp_path):
    original = "a" * 64
    scope = image_scope()
    scope["sha256"] = original
    scope_path = {"selection_basis": "retrospective_diagnostic", "images": [scope]}
    folder = tmp_path / "run" / "example"
    folder.mkdir(parents=True)
    prediction = {"source_sha256": original, "graph_structures": [graph()]}
    (folder / "response.json").write_text(json.dumps({"prediction": prediction}))
    (folder / "first-response.bin").write_text(json.dumps(prediction))
    annotations = tmp_path / "gold.json"
    annotations.write_text(json.dumps({"images": [{"id": "example", "sha256": original, "annotation_status": "reviewed", "graphs": [graph()]}]}))
    report = evaluate_run(folder.parent, [annotations], scope_path)
    assert report["summary"]["certified_acceptance"] is False
    scope["sha256"] = "b" * 64
    with pytest.raises(ValueError, match="original_image_identity"):
        evaluate_run(folder.parent, [annotations], scope_path)
    scope["sha256"] = original
    (folder / "first-response.bin").write_text("{}")
    with pytest.raises(ValueError, match="frozen_response_mismatch"):
        evaluate_run(folder.parent, [annotations], scope_path)


def test_diagnostic_images_cannot_raise_common_clear_scores():
    result = score_image({"graphs": [graph()]}, {"graph_structures": [graph()]}, image_scope())
    result["common_clear"] = False
    summary = summarize([result], "predeclared")
    assert summary["common_clear_images"] == 0
    assert summary["metrics"]["connections"]["status"] == "not_applicable"


def test_inconsistent_directed_declaration_cannot_pass_basic_type():
    expected, actual = graph(), graph()
    actual["directed"] = True
    assert score_panel(expected, actual, SCOPE)["basic_type"]["status"] == "fail"
