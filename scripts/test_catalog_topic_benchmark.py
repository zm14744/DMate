"""Local fallback and catalog benchmark protocol checks.

Run with the repository's Python environment::

    .venv/bin/python scripts/test_catalog_topic_benchmark.py
    .venv/bin/python scripts/test_catalog_topic_benchmark.py \
        --report /tmp/dmate-catalog-topic-report.json --report-only
    # Explicit operator evaluation; calls the configured actual model:
    .venv/bin/python scripts/test_catalog_topic_benchmark.py --semantic-live \
        --report /tmp/dmate-catalog-semantic-live-report.json

The fixture was annotated before running its questions against the classifier.
It is a deliberately varied regression set, not a population accuracy study.
Offline CI checks catalog/source binding, forbidden labels and honest review
status when the fast local fallback misses required content. Positive coverage
of supported local mathematical structures is checked separately by the local
structure tests. CI also replays captured actual semantic responses through
current task reconciliation and strictly checks the independent gold content;
that fixed-response regression makes no new API calls. Only the explicit
--semantic-live evaluation requests fresh model responses; it never runs by
default.
Unlisted extra labels remain visible for human review rather than silently
being counted as either correct or incorrect.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURE_PATH = ROOT / "scripts" / "fixtures" / "catalog_topic_benchmark.json"
CAPTURE_PATH = ROOT / "scripts" / "fixtures" / "catalog_semantic_captured_v4.json"
CATALOG_PATH = ROOT / "knowledge_graph.json"
SEMANTIC_BATCH_SIZE = 6
CLASSIFICATION_STATUSES = {
    "local", "semantic", "partial", "unknown", "disabled", "unavailable",
    "pending", "rate_limited", "deferred", "too_large", "invalid",
}


def load_fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def catalog_nodes():
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return {node["id"]: node for node in catalog["nodes"]}


def captured_graph_result(graph):
    """Adapt a captured/reconciled graph without inventing mathematical labels."""
    return {
        "question_graph": graph,
        "classification_source": "AI语义复核",
        "classification_status": graph.get("classification_status"),
        "classification_revision": graph.get("classifier_revision"),
        "needs_review": graph.get("needs_review"),
    }


def graph_protocol_issues(case, result, known_ids):
    """Validate provenance independently of whether all gold content was found."""
    issues = []
    if not isinstance(result, dict):
        return ["classification result is not an object"]
    graph = result.get("question_graph")
    if not isinstance(graph, dict):
        return ["question_graph is not an object"]
    if graph.get("version") != 1:
        issues.append("unsupported question_graph version")
    sources = {"question": case["question"], "solution": case.get("solution", "")}
    if graph.get("sources") != sources:
        issues.append("question_graph sources do not match the exact input pair")
    graph_source = graph.get("classification_source")
    result_source = result.get("classification_source")
    if graph_source == "local_structure":
        if result_source != "local_structure":
            issues.append("local graph has inconsistent result provenance")
    elif graph_source == "catalog_semantic":
        if not isinstance(result_source, str) or result_source not in {"catalog_semantic", "AI语义复核"}:
            issues.append("semantic graph has inconsistent result provenance")
    else:
        issues.append("unknown graph classification source")
    status = graph.get("classification_status")
    if not isinstance(status, str) or status not in CLASSIFICATION_STATUSES:
        issues.append("unknown classification status")
    if result.get("classification_status") != status:
        issues.append("graph and result classification statuses differ")
    for owner, payload in (("graph", graph), ("result", result)):
        if not isinstance(payload.get("needs_review"), bool):
            issues.append(owner + " needs_review is not an explicit boolean")
        elif status != "semantic" and payload["needs_review"] is not True:
            issues.append(owner + " nonsemantic result is not marked for review")
        elif status == "semantic" and payload["needs_review"] is not False:
            issues.append(owner + " semantic status contradicts its review flag")
    if graph.get("needs_review") != result.get("needs_review"):
        issues.append("graph and result review flags differ")
    if status == "semantic" and graph_source != "catalog_semantic":
        issues.append("local result is falsely labelled semantic")
    for owner, key, payload in (
        ("graph", "classifier_revision", graph),
        ("result", "classification_revision", result),
    ):
        if not isinstance(payload.get(key), str) or not payload[key].strip():
            issues.append(owner + " has no classifier revision")
    if graph.get("classifier_revision") != result.get("classification_revision"):
        issues.append("graph and result classifier revisions differ")

    def evidence_issues(record, owner):
        evidence = record.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            issues.append(owner + " has no source evidence")
            return
        for item in evidence:
            if not isinstance(item, dict):
                issues.append(owner + " has malformed source evidence")
                continue
            source, quote = item.get("source"), item.get("quote")
            if not isinstance(source, str) or source not in sources:
                issues.append(owner + " evidence names an unknown source")
            elif not isinstance(quote, str) or not quote.strip() or quote not in sources[source]:
                issues.append(owner + " evidence is not an exact nonempty input quote")

    nodes = graph.get("nodes")
    selected = set()
    if not isinstance(nodes, list):
        issues.append("graph nodes is not a list")
        nodes = []
    for node in nodes:
        if not isinstance(node, dict):
            issues.append("graph contains a malformed node")
            continue
        identifier = node.get("id")
        if not isinstance(identifier, str) or identifier not in known_ids:
            issues.append("graph contains a noncanonical node ID")
        elif identifier in selected:
            issues.append("graph contains a repeated node ID")
        else:
            selected.add(identifier)
        evidence_issues(node, "node " + str(identifier))
    edges = graph.get("edges")
    if not isinstance(edges, list):
        issues.append("graph edges is not a list")
        edges = []
    for edge in edges:
        if not isinstance(edge, dict):
            issues.append("graph contains a malformed edge")
            continue
        start, end = edge.get("from"), edge.get("to")
        if not isinstance(start, str) or not isinstance(end, str) \
                or start not in selected or end not in selected or start == end:
            issues.append("graph edge endpoints are not distinct selected nodes")
        evidence_issues(edge, "edge")
    return issues


def case_result(case, result):
    graph = result.get("question_graph", {})
    records = graph.get("nodes", []) if isinstance(graph, dict) else []
    actual_ids = sorted({
        node["id"] for node in records
        if isinstance(node, dict) and isinstance(node.get("id"), str)
    }) if isinstance(records, list) else []

    actual = set(actual_ids)
    required = set(case["expected_required_ids"])
    optional = set(case["permitted_optional_ids"])
    forbidden = set(case["forbidden_ids"])
    return {
        "id": case["id"],
        "modules": case["modules"],
        "difficulty": case["difficulty"],
        "question": case["question"],
        "topic_reason": case["topic_reason"],
        "expected_required_ids": sorted(required),
        "permitted_optional_ids": sorted(optional),
        "forbidden_ids": sorted(forbidden),
        "actual_ids": actual_ids,
        "missing_required_ids": sorted(required - actual),
        "present_forbidden_ids": sorted(forbidden & actual),
        "present_optional_ids": sorted(optional & actual),
        "unreviewed_extra_ids": sorted(actual - required - optional - forbidden),
        "classification_source": result.get("classification_source"),
        "classification_status": result.get("classification_status"),
        "classification_revision": result.get("classification_revision"),
        "needs_review": result.get("needs_review"),
        "protocol_issues": graph_protocol_issues(case, result, set(catalog_nodes())),
        "question_graph": graph,
    }


def run_case(case):
    # The default CI path is strictly local and cannot invoke a model transport.
    from teaching import analyze_question

    return case_result(case, analyze_question(case["question"]))


def run_semantic_live(cases):
    """Explicit operator-only actual-service evaluation; never called by CI."""
    from classification_semantic import classify_catalog_questions
    from teaching import analyze_question

    rows = []
    for start in range(0, len(cases), SEMANTIC_BATCH_SIZE):
        batch = cases[start:start + SEMANTIC_BATCH_SIZE]
        entries = [
            (case["id"], case["question"], case.get("solution", ""),
             analyze_question(case["question"]))
            for case in batch
        ]
        # Do not pass completion: the real configured transport is required.
        results = classify_catalog_questions(entries, allow_remote=True)
        for case in batch:
            result = results.get(case["id"])
            if not isinstance(result, dict):
                raise RuntimeError("Semantic service omitted case " + case["id"])
            rows.append(case_result(case, result))
    return rows


def build_report(*, semantic_live=False):
    fixture = load_fixture()
    rows = (run_semantic_live(fixture["cases"]) if semantic_live else
            [run_case(case) for case in fixture["cases"]])
    by_module = Counter(module for row in rows for module in row["modules"])
    return {
        "fixture": str(FIXTURE_PATH.relative_to(ROOT)),
        "fixture_sha256": hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest(),
        "evaluation_mode": "semantic_live" if semantic_live else "local_fallback",
        "semantic_batch_size": SEMANTIC_BATCH_SIZE if semantic_live else None,
        "scope": (
            "Hand-written mathematical regression cases over the existing "
            "catalog. Counts describe only this corpus and do not estimate "
            "population accuracy or guarantee recognition of arbitrary input."
        ),
        "annotation_policy": fixture["annotation_policy"],
        "summary": {
            "case_count": len(rows),
            "module_case_counts": dict(sorted(by_module.items())),
            "difficulty_case_counts": dict(sorted(Counter(
                row["difficulty"] for row in rows
            ).items())),
            "required_node_count": len({
                node_id
                for row in rows
                for node_id in row["expected_required_ids"]
            }),
            "cases_with_missing_required": sum(
                bool(row["missing_required_ids"]) for row in rows
            ),
            "cases_with_forbidden_labels": sum(
                bool(row["present_forbidden_ids"]) for row in rows
            ),
            "cases_with_unreviewed_extras": sum(
                bool(row["unreviewed_extra_ids"]) for row in rows
            ),
            "cases_with_no_nodes": sum(not row["actual_ids"] for row in rows),
            "cases_with_protocol_issues": sum(bool(row["protocol_issues"]) for row in rows),
            "classification_status_counts": dict(sorted(Counter(
                row["classification_status"] for row in rows
            ).items())),
            "cases_marked_for_review": sum(row["needs_review"] is True for row in rows),
        },
        "cases": rows,
    }


class CatalogTopicBenchmarkTests(unittest.TestCase):
    def test_independent_fixture_is_consistent_and_covers_all_modules(self):
        fixture = load_fixture()
        nodes = catalog_nodes()
        cases = fixture["cases"]
        self.assertGreaterEqual(len(cases), 30)
        self.assertLessEqual(len(cases), 45)
        self.assertEqual(len(cases), len({case["id"] for case in cases}))
        expected_modules = {node["category"] for node in nodes.values()}
        actual_modules = {module for case in cases for module in case["modules"]}
        self.assertEqual(actual_modules, expected_modules)
        for module in expected_modules:
            with self.subTest(module=module):
                self.assertEqual(
                    {case["difficulty"] for case in cases if module in case["modules"]},
                    {"simple", "hard"},
                )
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertTrue(case["question"].strip())
                self.assertTrue(case["topic_reason"].strip())
                self.assertTrue(case["modules"])
                required = set(case["expected_required_ids"])
                optional = set(case["permitted_optional_ids"])
                forbidden = set(case["forbidden_ids"])
                self.assertTrue(required)
                self.assertFalse(required & optional)
                self.assertFalse(required & forbidden)
                self.assertFalse(optional & forbidden)
                self.assertLessEqual(required | optional | forbidden, nodes.keys())
                for key in (
                    "expected_required_ids", "permitted_optional_ids", "forbidden_ids"
                ):
                    self.assertEqual(len(case[key]), len(set(case[key])))

    def test_local_fallback_is_source_bound_excludes_forbidden_and_reports_uncertainty(self):
        for case in load_fixture()["cases"]:
            with self.subTest(case=case["id"], difficulty=case["difficulty"]):
                row = run_case(case)
                problems = {
                    "present_forbidden_ids": row["present_forbidden_ids"],
                    "protocol_issues": row["protocol_issues"],
                    "unexpected_local_provenance": row["classification_source"] != "local_structure",
                    "false_complete": bool(row["missing_required_ids"]) and (
                        row["needs_review"] is not True or
                        row["classification_status"] == "semantic"
                    ),
                }
                self.assertFalse(
                    any(problems.values()),
                    json.dumps({
                        "id": row["id"],
                        "question": row["question"],
                        "actual_ids": row["actual_ids"],
                        "missing_required_ids": row["missing_required_ids"],
                        **problems,
                        "topic_reason": row["topic_reason"],
                    }, ensure_ascii=False),
                )

    def test_actual_captured_semantic_responses_reconcile_to_mathematical_gold_offline(self):
        """Replay real prior responses, not fresh calls or hand-built label mocks."""
        from classification_semantic import reconcile_catalog_graph

        fixture = json.loads(CAPTURE_PATH.read_text(encoding="utf-8"))
        provenance, captures = fixture["provenance"], fixture["captures"]
        self.assertEqual(fixture["schema_version"], 1)
        self.assertEqual(provenance["new_api_calls_for_fixture_creation"], 0)
        self.assertEqual(
            provenance["gold_fixture_sha256"],
            hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest(),
        )
        capture_bytes = json.dumps(
            captures, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(
            provenance["accepted_graphs_sha256"], hashlib.sha256(capture_bytes).hexdigest(),
        )
        self.assertEqual(len(provenance["source_capture_sha256"]), 64)
        gold = {case["id"]: case for case in load_fixture()["cases"]}
        self.assertEqual(len(captures), len(gold))
        self.assertEqual({item["id"] for item in captures}, set(gold))
        self.assertEqual(
            dict(Counter(item["question_graph"]["classification_status"] for item in captures)),
            provenance["captured_status_counts"],
        )
        raw_cases_with_missing_required = 0
        for item in captures:
            case, original = gold[item["id"]], item["question_graph"]
            with self.subTest(case=case["id"]):
                self.assertEqual(set(item), {"id", "question_graph"})
                self.assertEqual(original["classifier_revision"], provenance["model_prompt_revision"])
                # The fixture must stay raw: store no current-engine additions.
                self.assertNotIn("reconciliation_source", original)
                self.assertNotIn("task_structure_ids", original)
                original_row = case_result(case, captured_graph_result(original))
                self.assertFalse(original_row["protocol_issues"])
                self.assertFalse(original_row["present_forbidden_ids"])
                raw_cases_with_missing_required += bool(original_row["missing_required_ids"])
                reconciled = reconcile_catalog_graph(
                    original, case["question"], case.get("solution", ""),
                )
                self.assertIsInstance(reconciled, dict)
                row = case_result(case, captured_graph_result(reconciled))
                self.assertFalse(
                    row["missing_required_ids"] or row["present_forbidden_ids"] or row["protocol_issues"],
                    json.dumps({
                        "id": case["id"],
                        "missing_required_ids": row["missing_required_ids"],
                        "present_forbidden_ids": row["present_forbidden_ids"],
                        "protocol_issues": row["protocol_issues"],
                        "topic_reason": case["topic_reason"],
                    }, ensure_ascii=False),
                )
                # Added task facts cannot resolve the model's uncertainty.
                self.assertEqual(reconciled["classification_status"], original["classification_status"])
                self.assertEqual(reconciled["needs_review"], original["needs_review"])
                self.assertEqual(reconciled.get("unresolved"), original.get("unresolved"))
                if original["classification_status"] == "partial":
                    self.assertIs(reconciled["needs_review"], True)
        self.assertGreater(
            raw_cases_with_missing_required, 0,
            "Raw model captures must not be replaced with already reconciled final graphs.",
        )


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--report", type=Path, help="Write the full structured JSON report.")
    parser.add_argument(
        "--semantic-live", action="store_true",
        help="Explicitly call the configured actual model in batches of six and assert all required/forbidden labels; never enabled by CI.",
    )
    parser.add_argument(
        "--report-only", action="store_true",
        help="Write/report findings without running assertions; does not suppress test failures in normal mode.",
    )
    args, unittest_args = parser.parse_known_args()
    if args.semantic_live and (args.report_only or unittest_args):
        parser.error("--semantic-live is a strict evaluation and cannot be combined with --report-only or unittest arguments")
    if args.semantic_live or args.report or args.report_only:
        report = build_report(semantic_live=args.semantic_live)
        report_path = args.report
        if args.semantic_live and report_path is None:
            report_path = Path("/tmp/dmate-catalog-semantic-live-report.json")
        if report_path:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
        if args.semantic_live:
            failures = [
                {key: row[key] for key in (
                    "id", "classification_status", "missing_required_ids",
                    "present_forbidden_ids", "protocol_issues",
                )}
                for row in report["cases"]
                if row["missing_required_ids"] or row["present_forbidden_ids"]
                or row["protocol_issues"] or row["classification_status"] != "semantic"
            ]
            if failures:
                print(json.dumps({"semantic_evaluation_failures": failures}, ensure_ascii=False, indent=2))
            return int(bool(failures))
    if not args.report_only:
        unittest.main(argv=[sys.argv[0], *unittest_args])


if __name__ == "__main__":
    sys.exit(main())
