"""Score frozen recognition by dimension; never call models or repair predictions.

The required selection JSON is a human scope declaration, for example::

  {"selection_basis":"predeclared", "images":[{"id":"sample", "sha256":"…",
    "common_clear":true, "panels":[{"reference_index":0,"prediction_index":0,
      "clear_direction_edges":"all", "clear_weight_edges":"all"}]}]}

Edge selectors use zero-based *expanded instance* indices. Omit a selector when
clarity has not been independently assessed; unknown predicted fields never
remove a clear reference instance from the denominator. Panel correspondence
is explicit, not selected by whichever prediction scores best. Anonymous node
correspondence is a bounded optimal structural mapping, reported as such.
Retrospective selections are diagnostics, never certified acceptance passes.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import itertools
import json
import math
from pathlib import Path
import sys
import re
import unicodedata

import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.benchmark_graph_first_pass import _visible_label, _weight


def ratio_metric(correct, expected, predicted, threshold):
    """Both precision and recall must pass; surplus guesses cannot buy a pass."""
    if expected == predicted == 0:
        return {"status": "not_applicable", "correct": 0, "expected": 0, "predicted": 0}
    precision = correct / predicted if predicted else 0.0
    recall = correct / expected if expected else 0.0
    return {"status": "pass" if precision >= threshold and recall >= threshold else "fail",
            "correct": correct, "expected": expected, "predicted": predicted,
            "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            "threshold": threshold}


def _inventory(graph, *, reference=False):
    vertices, edges = graph.get("vertices"), graph.get("edges")
    if not isinstance(vertices, list) or not isinstance(edges, list) or len(vertices) > 100:
        raise ValueError("invalid_vertex_or_edge_inventory")
    nodes = {}
    for row in vertices:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] or row["id"] in nodes:
            raise ValueError("invalid_or_duplicate_vertex_id")
        if "label" not in row:
            raise ValueError("missing_explicit_vertex_label")
        nodes[row["id"]] = _visible_label(row["label"])
    instances = []
    for index, row in enumerate(edges):
        if not isinstance(row, dict):
            raise ValueError("invalid_edge")
        count = row.get("multiplicity", 1)
        if type(count) is not int or not 1 <= count <= 300 or len(instances) + count > 300:
            raise ValueError("invalid_or_oversized_multiplicity")
        start, end, direction = row.get("from"), row.get("to"), row.get("direction", "unknown")
        if reference and (start not in nodes or end not in nodes or direction not in ("forward", "reverse", "undirected")):
            raise ValueError("invalid_reference_edge")
        if direction == "reverse":
            start, end, direction = end, start, "forward"
        weight = _weight(row.get("weight"))
        for ordinal in range(count):
            instances.append({"from": start, "to": end, "direction": direction,
                              "weight": weight, "edge_label": _visible_label(row.get("edge_label", row.get("label"))),
                              "source_index": index, "instance": ordinal,
                              "valid_endpoints": start in nodes and end in nodes})
    return nodes, instances


def _endpoint_key(edge):
    return tuple(sorted((edge["from"], edge["to"])))


def _direction_equal(gold, predicted):
    return gold["direction"] == predicted["direction"] and (
        gold["direction"] == "undirected" or
        (gold["from"], gold["to"]) == (predicted["from"], predicted["to"]))


def _weight_equal(gold, predicted):
    return gold["weight"] == predicted["weight"] and (
        gold["direction"] == "undirected" or _direction_equal(gold, predicted))


def _edge_pairs(expected, predicted, mapping):
    """One-to-one instances; choose direction then weight within parallel groups."""
    grouped_gold, grouped_pred = defaultdict(list), defaultdict(list)
    for i, edge in enumerate(expected):
        if edge["from"] in mapping and edge["to"] in mapping:
            projected = {**edge, "from": mapping[edge["from"]], "to": mapping[edge["to"]]}
            grouped_gold[_endpoint_key(projected)].append((i, projected))
    for j, edge in enumerate(predicted):
        if edge["valid_endpoints"]:
            grouped_pred[_endpoint_key(edge)].append((j, edge))
    pairs = []
    for key, gold in grouped_gold.items():
        actual = grouped_pred[key]
        if len(gold) == len(actual) == 1:
            pairs.append((gold[0][0], actual[0][0]))
            continue
        network = nx.Graph()
        # Cardinality first; integer coefficients keep secondary objectives
        # lexicographic across at most 300 edge instances.
        for i, a in gold:
            for j, b in actual:
                score = 1000000 * _direction_equal(a, b) + 1000 * _weight_equal(a, b) + (a["edge_label"] == b["edge_label"])
                network.add_edge(("g", i), ("p", j), weight=score)
        for a, b in nx.max_weight_matching(network, maxcardinality=True):
            if a[0] != "g":
                a, b = b, a
            pairs.append((a[1], b[1]))
    return sorted(pairs)


def _mapping(expected_nodes, predicted_nodes, expected_edges, predicted_edges, *, limit=100000):
    fixed = {}
    used = set()
    for folded in (False, True):
        left, right = defaultdict(list), defaultdict(list)
        for collection, target, excluded in ((expected_nodes, left, set(fixed)), (predicted_nodes, right, used)):
            for node, label in collection.items():
                if node not in excluded and isinstance(label, str):
                    target[label.casefold() if folded else label].append(node)
        for label in sorted(left):
            if len(left[label]) == len(right.get(label, [])) == 1:
                fixed[left[label][0]] = right[label][0]
                used.add(right[label][0])
    remaining = sorted(set(expected_nodes) - set(fixed))
    available = sorted(set(predicted_nodes) - used)
    count = min(len(remaining), len(available))
    combinations = math.comb(len(remaining), count) * math.perm(len(available), count)
    if combinations > limit:
        return {"status": "not_assessed", "reason": "mapping_search_limit", "candidate_mappings": combinations}
    best = None
    for subset in itertools.combinations(remaining, count):
        for assignment in itertools.permutations(available, count):
            current = {**fixed, **dict(zip(subset, assignment))}
            pairs = _edge_pairs(expected_edges, predicted_edges, current)
            projected = {i: {**edge, "from": current.get(edge["from"]), "to": current.get(edge["to"])}
                         for i, edge in enumerate(expected_edges)}
            score = (len(pairs), sum(_direction_equal(projected[i], predicted_edges[j]) for i, j in pairs),
                     sum(_weight_equal(projected[i], predicted_edges[j]) for i, j in pairs),
                     sum(expected_nodes[a] == predicted_nodes[b] for a, b in current.items()))
            if best is None or score > best[0]:
                best = score, current, pairs
    return {"status": "assessed", "method": "unique_label_anchors_then_bounded_structural_optimum",
            "anonymous_mapping_is_structural_upper_bound": bool(remaining),
            "candidate_mappings": combinations, "vertices": best[1], "edge_instances": best[2]}


def _selected_edges(scope, key, edges, predicate):
    selection = scope.get(key)
    if selection is None:
        return None
    eligible = {i for i, edge in enumerate(edges) if predicate(edge)}
    if selection == "all":
        return eligible
    if not isinstance(selection, list) or any(type(i) is not int or i not in eligible for i in selection):
        raise ValueError("invalid_human_clear_edge_selection:" + key)
    return set(selection)


def _kind(graph, edges):
    directions = {edge["direction"] for edge in edges}
    if directions - {"forward", "undirected"}:
        return "unknown"
    if not directions:
        return "directed" if graph.get("directed") is True else "undirected"
    derived = "mixed" if len(directions) > 1 else "directed" if "forward" in directions else "undirected"
    if (derived == "undirected" and graph.get("directed") is True or
            derived == "directed" and graph.get("directed") is False):
        return "inconsistent_declaration"
    return derived


def score_panel(reference, prediction, scope, *, mapping_limit=100000):
    gold_nodes, gold_edges = _inventory(reference, reference=True)
    try:
        actual_nodes, actual_edges = _inventory(prediction)
    except (ValueError, TypeError):
        return {"status": "fail", "reason": "invalid_prediction_inventory"}
    count = lambda a, b: {"status": "pass" if a == b else "fail", "expected": a, "predicted": b}
    result = {"vertex_count": count(len(gold_nodes), len(actual_nodes)),
              "edge_count": count(len(gold_edges), len(actual_edges)),
              "basic_type": {"status": "pass" if _kind(reference, gold_edges) == _kind(prediction, actual_edges) else "fail",
                             "expected": _kind(reference, gold_edges), "predicted": _kind(prediction, actual_edges)}}
    mapping = _mapping(gold_nodes, actual_nodes, gold_edges, actual_edges, limit=mapping_limit)
    result["mapping"] = mapping
    if mapping["status"] != "assessed":
        result.update({key: {"status": "not_assessed", "reason": "mapping_search_limit"}
                       for key in ("connections", "directions", "weights", "vertex_labels")})
        return result
    vertices, pairs = mapping["vertices"], mapping["edge_instances"]
    result["connections"] = ratio_metric(len(pairs), len(gold_edges), len(actual_edges), .9)
    variants = scope.get("vertex_label_variants", {})
    if not isinstance(variants, dict) or any(node not in gold_nodes or not isinstance(values, list) or not values
                                             for node, values in variants.items()):
        raise ValueError("invalid_independent_vertex_label_variants")
    result["vertex_labels"] = ratio_metric(sum(actual_nodes[b] in [_visible_label(v) for v in variants.get(a, [gold_nodes[a]])]
                                               for a, b in vertices.items()),
                                           len(gold_nodes), len(actual_nodes), .95)
    if variants:
        result["vertex_labels"]["explicit_reference_variant_vertices"] = sorted(variants)
    for name, selection, predicate, comparator in (
        ("directions", "clear_direction_edges", lambda e: e["direction"] == "forward", _direction_equal),
        ("weights", "clear_weight_edges", lambda e: e["weight"] is not None, _weight_equal),
    ):
        selected = _selected_edges(scope, selection, gold_edges, predicate)
        if selected is None:
            result[name] = {"status": "not_assessed", "reason": "missing_independent_clarity_scope"}
            continue
        # Predictions matched to explicitly excluded unclear reference edges
        # are excluded too. Unmatched extra claims remain false positives.
        excluded = {j for i, j in pairs if i not in selected and predicate(gold_edges[i])}
        predicted_count = sum(predicate(edge) or (name == "directions" and edge["direction"] == "unknown")
                              for j, edge in enumerate(actual_edges) if j not in excluded)
        correct = 0
        for i, j in pairs:
            if i in selected:
                edge = {**gold_edges[i], "from": vertices[gold_edges[i]["from"]], "to": vertices[gold_edges[i]["to"]]}
                correct += comparator(edge, actual_edges[j])
        result[name] = ratio_metric(correct, len(selected), predicted_count, .9)
    return result


def _compact_text(text):
    return "".join(unicodedata.normalize("NFKC", text).split())


def _item_present(item, text):
    accepted = item.get("accepted", item.get("variants", []))
    if item.get("literal") is not None:
        accepted = [item["literal"], *accepted]
    if not isinstance(accepted, list) or not accepted or any(not isinstance(s, str) or not s for s in accepted):
        raise ValueError("independent_text_item_requires_literal_or_variants")
    forbidden = item.get("forbidden", item.get("rejected", []))
    return any(_compact_text(value) in text for value in accepted) and not any(_compact_text(value) in text for value in forbidden)


def _question_metrics(body, reference, declaration):
    result = {"subquestion_count": {"status": "not_assessed", "reason": "requires_independent_subquestion_annotations"},
              "key_content": {"status": "not_assessed", "reason": "requires_independent_key_content_annotations"},
              "whole_body_literal_equal": isinstance(body, str) and isinstance(reference, str) and body == reference}
    if not isinstance(declaration, dict):
        return result
    observed = _compact_text(body) if isinstance(body, str) else ""
    questions = declaration.get("subquestions")
    counting = declaration.get("counting")
    if isinstance(questions, list) and counting in ("none", "single_request", "numbered_parentheses"):
        expected_ids = [str(row["id"]) for row in questions]
        if counting == "none":
            expected, actual = 0, int(bool(observed))
        elif counting == "single_request":
            expected = len(questions)
            # Nonempty text alone cannot establish that no request was added.
            # Exact independent body equality can establish a single request;
            # other unnumbered wording requires human question segmentation.
            literal = declaration.get("manual_text", declaration.get("body_text", reference))
            if observed and (not isinstance(literal, str) or observed != _compact_text(literal)):
                result["subquestion_count"] = {"status": "not_assessed", "expected": expected,
                                                "reason": "unsegmented_unnumbered_prediction"}
                actual = None
            else:
                actual = int(bool(observed))
        else:
            # Use only a human declaration that the source uses these explicit
            # markers. Duplicate or unexpected markers remain count failures.
            markers = re.findall(r"\((\d{1,2})\)", observed)
            expected, actual = len(expected_ids), len(markers)
        if actual is not None:
            result["subquestion_count"] = {"status": "pass" if expected == actual else "fail",
                                            "expected": expected, "predicted": actual, "method": counting}
        if counting == "numbered_parentheses":
            result["subquestion_count"]["expected_markers"] = expected_ids
            result["subquestion_count"]["observed_markers"] = markers
            if Counter(markers) != Counter(expected_ids):
                result["subquestion_count"]["status"] = "fail"
    if isinstance(questions, list) and questions and all(row.get("literal") or row.get("variants") for row in questions):
        result["subquestion_coverage"] = {"matched": sum(_item_present(row, observed) for row in questions),
                                            "expected": len(questions), "scope": "reference_item_coverage_not_question_count"}
    items = declaration.get("critical_items", declaration.get("key_items"))
    if isinstance(items, list):
        required = [item for item in items if item.get("required", True)]
        matched = [item["id"] for item in required if _item_present(item, observed)]
        result["key_content"] = {"status": "not_applicable" if not required else "pass" if len(matched) / len(required) >= .95 else "fail",
                                 "matched": len(matched), "expected": len(required), "matched_ids": matched,
                                 "coverage": len(matched) / len(required) if required else None,
                                 "threshold": .95, "scope": "independent_required_item_coverage_not_whole_text_accuracy"}
    return result


def score_image(reference, prediction, scope, *, browser_evidence=None, mapping_limit=100000):
    graphs = prediction.get("graph_display_data", prediction.get("graph_structures", []))
    if not isinstance(graphs, list):
        graphs = []
    expected = reference["graphs"]
    pairs = scope.get("panels", [])
    indices = [row.get("reference_index") for row in pairs]
    mapped = [row.get("prediction_index") for row in pairs if row.get("prediction_index") is not None]
    if any(type(index) is not int or index < 0 for index in mapped):
        raise ValueError("invalid_prediction_panel_index")
    if (any(type(index) is not int for index in indices)
            or sorted(indices) != list(range(len(expected))) or len(mapped) != len(set(mapped))):
        raise ValueError("manual_panel_correspondence_must_cover_each_reference_once")
    panels = []
    for row in pairs:
        index = row.get("prediction_index")
        missing = index is None or index >= len(graphs)
        observed = {"vertices": [], "edges": []} if missing else graphs[index]
        panel = {"reference_index": row["reference_index"], "prediction_index": index,
                 "panel_missing": missing,
                 **score_panel(expected[row["reference_index"]], observed, row, mapping_limit=mapping_limit)}
        if missing:
            # A frozen ordinal can be beyond a shorter actual inventory. This
            # is a missing-panel result, not an invalid evaluator declaration;
            # even a missing edgeless graph cannot pass its zero edge count.
            for name in ("vertex_count", "edge_count", "basic_type"):
                panel[name].update(status="fail", reason="missing_prediction_panel")
            panel["basic_type"]["predicted"] = "missing"
        panels.append(panel)
    body = prediction.get("text", prediction.get("body_text"))
    literal = reference.get("body_text", reference.get("question_text"))
    overrides = scope.get("reference_overrides", {})
    if not isinstance(overrides, dict) or set(overrides) - {"body_text"}:
        raise ValueError("unsupported_independent_reference_override")
    if "body_text" in overrides:
        if not isinstance(overrides["body_text"], str):
            raise ValueError("invalid_independent_body_reference")
        literal = overrides["body_text"]
    performance = {"status": "not_assessed", "reason": "no_browser_render_evidence"}
    if browser_evidence is not None:
        elapsed = browser_evidence.get("upload_through_editor_render_seconds")
        degraded = bool(prediction.get("service_warnings"))
        selected_complete = prediction.get("selected_tools_complete")
        if type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0:
            if elapsed > 120 or prediction.get("recognition_status") != "complete" or degraded or selected_complete is False:
                status = "fail"
            else:
                status = "pass" if selected_complete is True else "not_assessed"
            performance = {"status": status,
                           "seconds": elapsed, "target_seconds": 120,
                           "recognition_status": prediction.get("recognition_status"),
                           "local_tools_degraded": degraded,
                           "selected_tools_complete": selected_complete,
                           "scope": "actual_upload_through_editor_rendering"}
            if status == "not_assessed":
                performance["reason"] = "missing_explicit_selected_tool_completion_audit"
    return {"id": scope["id"], "common_clear": scope.get("common_clear") is True,
            "panel_count": {"status": "pass" if len(expected) == len(graphs) else "fail", "expected": len(expected), "predicted": len(graphs)},
            "extra_prediction_panels": sorted(set(range(len(graphs))) - set(mapped)), "panels": panels,
            "question": _question_metrics(body, literal, scope.get("question")),
            "performance": performance}


def summarize(images, selection_basis):
    eligible = [row for row in images if row["common_clear"]]
    panels = [panel for row in eligible for panel in row["panels"]]
    summary = {"selection_basis": selection_basis, "images": len(images), "common_clear_images": len(eligible),
               "certified_acceptance": False, "metrics": {}}
    for name, values in [("panel_count", [r["panel_count"] for r in eligible]),
                         *[(key, [p.get(key, {"status": "fail"}) for p in panels]) for key in ("vertex_count", "edge_count", "basic_type")],
                         ("performance", [r["performance"] for r in eligible])]:
        summary["metrics"][name] = {"passed": sum(v["status"] == "pass" for v in values), "total": len(values),
                                    "status": "fail" if any(v["status"] == "fail" for v in values) else
                                    "not_assessed" if not values or any(v["status"] == "not_assessed" for v in values) else "pass"}
    for name, threshold in (("connections", .9), ("directions", .9), ("weights", .9), ("vertex_labels", .95)):
        values = [p.get(name, {"status": "not_assessed"}) for p in panels]
        known = [v for v in values if "correct" in v]
        metric = ratio_metric(sum(v["correct"] for v in known), sum(v["expected"] for v in known), sum(v["predicted"] for v in known), threshold)
        metric["unassessed_panels"] = sum(v["status"] == "not_assessed" for v in values)
        if metric["unassessed_panels"] or any(r["extra_prediction_panels"] for r in eligible):
            metric["status"] = "not_assessed"
        summary["metrics"][name] = metric
    question_counts = [row["question"]["subquestion_count"] for row in eligible]
    summary["metrics"]["subquestion_count"] = {"passed": sum(row["status"] == "pass" for row in question_counts),
        "total": len(question_counts), "status": "not_assessed" if any(row["status"] == "not_assessed" for row in question_counts)
        else "pass" if question_counts and all(row["status"] == "pass" for row in question_counts) else "fail"}
    content = [row["question"]["key_content"] for row in eligible]
    known = [row for row in content if "matched" in row]
    matched, total = sum(row["matched"] for row in known), sum(row["expected"] for row in known)
    summary["metrics"]["key_item_coverage"] = {"status": "not_assessed" if len(known) != len(content) else "not_applicable" if not total else "pass" if matched / total >= .95 else "fail",
        "matched": matched, "expected": total, "coverage": matched / total if total else None,
        "scope": "coverage_not_whole_text_accuracy"}
    # Even structurally strong samples cannot establish the full requested
    # acceptance while text/subquestion references are absent.
    return summary


def evaluate_run(run, annotations, selection):
    references = {}
    for path in annotations:
        for row in json.loads(Path(path).read_text())["images"]:
            if row["id"] in references:
                raise ValueError("duplicate_reference_id")
            references[row["id"]] = row
    basis = selection.get("selection_basis")
    if basis not in ("predeclared", "retrospective_diagnostic"):
        raise ValueError("explicit_selection_basis_required")
    results, seen = [], set()
    for scope in selection["images"]:
        identifier = scope["id"]
        if identifier in seen or not identifier or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in identifier):
            raise ValueError("invalid_or_duplicate_sample_id")
        seen.add(identifier)
        reference = references[identifier]
        if reference.get("annotation_status") != "reviewed" and reference.get("annotation_complete") is not True:
            raise ValueError("independent_reference_not_reviewed:" + identifier)
        folder = Path(run) / identifier
        wrapper = json.loads((folder / "response.json").read_text())
        prediction = wrapper["prediction"]
        identity = prediction.get("source_sha256", wrapper.get("execution_evidence", {}).get("image_sha256"))
        if not scope.get("sha256") or identity != scope["sha256"] or identity != reference.get("sha256"):
            raise ValueError("original_image_identity_mismatch:" + identifier)
        raw = (folder / "first-response.bin").read_bytes()
        if json.loads(raw) != prediction:
            raise ValueError("frozen_response_mismatch:" + identifier)
        evidence = None
        if (folder / "result.json").is_file():
            evidence = json.loads((folder / "result.json").read_text())
        result = score_image(reference, prediction, scope, browser_evidence=evidence)
        result["first_response_sha256"] = hashlib.sha256(raw).hexdigest()
        results.append(result)
    return {"schema": "dmate.core-metrics/1", "scope": selection,
            "summary": summarize(results, basis), "images": results}


def markdown(report):
    lines = ["# 常见清晰图分项诊断", "", "选择方式：`" + report["summary"]["selection_basis"] + "`。仅计分冻结响应，不调用模型。",
             "", "本报告不证明完整硬指标验收通过：未提供独立标注的项目保持未评；关键片段覆盖率不代替全文准确率，回顾性选样不代替事先声明的验收集。",
             "", "| 项目 | 状态 | 计数/精度 |", "| --- | --- | --- |"]
    for name, metric in report["summary"]["metrics"].items():
        detail = f'{metric["passed"]}/{metric["total"]}' if "passed" in metric else (
            f'正确 {metric["correct"]}，参考 {metric["expected"]}，预测 {metric["predicted"]}；P={metric.get("precision", 0):.3f}，R={metric.get("recall", 0):.3f}' if "correct" in metric else "未评")
        lines.append(f'| {name} | {metric["status"]} | {detail} |')
    lines += ["", "匿名点使用同一个有界结构最优对应计算全部指标，属于结构匹配上界，不宣称已确定原像素中的逐点对应。标签大小写严格计分，近似标签只协助定位对应。重边、自环按独立实例一对一比较；未知方向/权重不从分母中删除。", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--annotations", nargs="+", required=True)
    parser.add_argument("--selection", required=True)
    parser.add_argument("--output", required=True, help="New private output prefix outside the repository")
    args = parser.parse_args(argv)
    prefix = Path(args.output).resolve()
    if prefix.is_relative_to(ROOT):
        raise ValueError("private_artifacts_must_be_outside_repository")
    report = evaluate_run(args.run, args.annotations, json.loads(Path(args.selection).read_text()))
    prefix.parent.mkdir(parents=True, exist_ok=True)
    for suffix, content in ((".json", json.dumps(report, ensure_ascii=False, indent=2) + "\n"), (".md", markdown(report))):
        with Path(str(prefix) + suffix).open("x", encoding="utf-8") as stream:
            stream.write(content)
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
