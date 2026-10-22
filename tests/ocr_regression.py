#!/usr/bin/env python3
"""DMate real-browser OCR capture and graph topology regression.

Default is a FREE mocked browser roundtrip. --mode live sends genuine /ocr
requests; --solve adds ONE paid /chat request per image. No login is used.
"""
import argparse
import hashlib
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time
import traceback
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from fixtures.generate_graph_ocr import generate


def canonical_edges(edges, directed):
    counts = Counter()
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        a = str(edge.get("from", "")).strip()
        b = str(edge.get("to", "")).strip()
        if not a or not b:
            continue
        if directed is False:
            a, b = sorted((a, b))
        count = edge.get("multiplicity", 1)
        if not isinstance(count, int) or count < 1 or count > 200:
            count = 1
        counts[(a, b)] += count
    return counts


def topology_comparison(actual_graphs, expected, question, visual):
    """Compare to independently prepared truth, not to model-generated text.

    For unlabeled classroom diagrams, T1..T3 and B1..B3 denote vertex positions.
    A full edge comparison is only possible when the model returned vertex
    coordinates; otherwise edge topology remains UNVERIFIED.
    """
    checks = []

    def check(name, condition, detail):
        checks.append({"check": name, "status": "passed" if condition else "failed", "detail": detail})

    def unverified(name, detail):
        checks.append({"check": name, "status": "unverified", "detail": detail})

    def norm(value):
        import unicodedata
        name = str(value or "").strip()
        name = name.replace("\\(", "").replace("\\)", "")
        name = name.replace("{", "").replace("}", "").replace("_", "")
        name = name.translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789"))
        return unicodedata.normalize("NFKC", name).casefold()

    for keyword in expected.get("question_contains", []):
        check("question_contains", keyword.casefold() in question.casefold(), keyword)
    for keyword in expected.get("visual_contains", []):
        check("visual_contains", keyword.casefold() in visual.casefold(), keyword)

    declared = expected.get("graphs")
    if not isinstance(declared, list):
        single = expected.get("graph")
        declared = [single] if isinstance(single, dict) else []
    if not declared:
        return checks
    if not isinstance(actual_graphs, list) or not actual_graphs:
        unverified("structured_graph", "No verified graph_display_data returned; actual visual_text needs independent manual review")
        return checks

    check("graph_count", len(actual_graphs) == len(declared),
          "expected=%s actual=%s" % (len(declared), len(actual_graphs)))
    used_ids = set()

    for index, expected_graph in enumerate(declared):
        if not isinstance(expected_graph, dict):
            unverified("reference_data", "Invalid ground-truth graph")
            continue
        graph_id = str(expected_graph.get("id", "")).strip()
        candidates = [(i, g) for i, g in enumerate(actual_graphs)
                      if isinstance(g, dict) and i not in used_ids
                      and (not graph_id or norm(g.get("id")) == norm(graph_id))]
        if not candidates and len(actual_graphs) == len(declared):
            candidates = [(index, actual_graphs[index])]
        if not candidates:
            check(graph_id + ".graph_id", False, "Expected graph %r was missing" % graph_id)
            continue
        actual_index, graph = candidates[0]
        used_ids.add(actual_index)
        prefix = (graph_id or str(index + 1)) + "."
        if graph_id:
            check(prefix + "graph_id", norm(graph.get("id")) == norm(graph_id),
                  "expected=%r actual=%r" % (graph_id, graph.get("id")))
        directed = expected_graph.get("directed")
        check(prefix + "directed", graph.get("directed") is directed,
              "expected=%r actual=%r" % (directed, graph.get("directed")))

        raw_vertices = graph.get("vertices") if isinstance(graph.get("vertices"), list) else []
        labels = [str(v.get("id", "")).strip() if isinstance(v, dict) else str(v).strip()
                  for v in raw_vertices]
        wanted = [str(v.get("id", "") if isinstance(v, dict) else v).strip()
                  for v in expected_graph.get("vertices", [])]
        check(prefix + "vertex_count", len(labels) == len(wanted),
              "expected=%d actual=%d" % (len(wanted), len(labels)))

        aliases = {norm(label): norm(label) for label in labels}
        if expected_graph.get("vertex_position_strategy") == "two_rows_three_columns":
            if len(raw_vertices) != 6 or any(
                    not isinstance(v, dict) or not isinstance(v.get("x"), (int, float))
                    or not isinstance(v.get("y"), (int, float)) for v in raw_vertices):
                unverified(prefix + "vertex_positions",
                           "Cannot map unlabeled vertices to T1..T3/B1..B3 without six numeric coordinate pairs")
                continue
            sorted_by_y = sorted(raw_vertices, key=lambda v: (v["y"], v["x"]))
            top = sorted(sorted_by_y[:3], key=lambda v: v["x"])
            bottom = sorted(sorted_by_y[3:], key=lambda v: v["x"])
            aliases = {norm(v["id"]): "t" + str(i + 1) for i, v in enumerate(top)}
            aliases.update({norm(v["id"]): "b" + str(i + 1) for i, v in enumerate(bottom)})
            # A horizontal separation is necessary, otherwise positional mapping is ambiguous.
            if max(v["y"] for v in top) >= min(v["y"] for v in bottom):
                unverified(prefix + "vertex_positions", "Top and bottom rows cannot be separated reliably")
                continue
        else:
            check(prefix + "vertices", sorted(norm(v) for v in labels) ==
                  sorted(norm(v) for v in wanted),
                  {"expected": wanted, "actual": labels})

        actual_edges = []
        for edge in graph.get("edges", []):
            if not isinstance(edge, dict):
                continue
            copy_edge = dict(edge)
            copy_edge["from"] = aliases.get(norm(edge.get("from")), norm(edge.get("from")))
            copy_edge["to"] = aliases.get(norm(edge.get("to")), norm(edge.get("to")))
            actual_edges.append(copy_edge)
        want_edges = [{**e, "from": norm(e.get("from")), "to": norm(e.get("to"))}
                      for e in expected_graph.get("edges", []) if isinstance(e, dict)]
        expected_counts = canonical_edges(want_edges, directed)
        observed_counts = canonical_edges(actual_edges, directed)
        display = lambda es: [{"from": a, "to": b, "count": count}
                              for (a, b), count in sorted(es.items())]
        check(prefix + "edges_and_multiplicity", expected_counts == observed_counts,
              {"expected": display(expected_counts), "actual": display(observed_counts)})

    return checks


def run_case(browser, case, url, image_path, output, mode, solve, timeout_seconds):
    context = browser.new_context(viewport={"width": 1440, "height": 900},
                                  locale="zh-CN", color_scheme="light")
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    cid = re.sub(r"[^A-Za-z0-9_-]", "_", str(case["id"]))[:80]
    record = {"id": cid, "source_image": image_path.name, "mode": mode,
              "steps": [], "comparisons": [], "page_errors": [], "http_errors": [],
              "screenshots": []}
    page.on("pageerror", lambda exc: record["page_errors"].append(str(exc)[:1200]))

    def shot(suffix):
        dest = output / (cid + "-" + suffix + ".png")
        page.screenshot(path=str(dest), full_page=False, animations="disabled", timeout=15000)
        record["screenshots"].append(dest.name)

    def mock_response(route):
        expected = case["expected"]
        graph = expected.get("graph", {})
        graphs = expected.get("graphs") or ([graph] if graph else [])
        payload = {"text": case.get("mock_text", "Exercise: " + cid),
                   "visual_text": case.get("mock_visual", "图形结构：请根据图判断所有顶点与边"),
                   "graph_display_data": graphs,
                   "vision_used": True, "warning": None}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(payload, ensure_ascii=False))

    if mode == "mock":
        page.route("**/ocr", mock_response)

    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        if response is None or response.status >= 400:
            raise AssertionError("Homepage HTTP %s" % (response.status if response else "none"))
        page.locator("#imageInput").wait_for(state="attached", timeout=20000)
        record["steps"].append("opened_homepage")
        t0 = time.monotonic()

        # Real DOM file selection; do not bypass the website's change handler.
        with page.expect_response(
            lambda r: urlsplit(r.url).path == "/ocr" and r.request.method == "POST",
            timeout=timeout_seconds*1000
        ) as waiter:
            page.locator("#imageInput").set_input_files(str(image_path))
        ocr_http = waiter.value
        record["ocr_http_status"] = ocr_http.status
        record["ocr_seconds"] = round(time.monotonic() - t0, 2)
        try:
            raw_response = ocr_http.json()
        except Exception:
            raw_response = {"error": "Non-JSON OCR response", "http_body": ocr_http.text()[:3000]}
        if not isinstance(raw_response, dict):
            raw_response = {"error": "Invalid OCR response shape"}
        # Only retain answer-relevant fields, not IP identifiers or auth data.
        data = {k: raw_response.get(k) for k in (
            "text", "visual_text", "graph_display_data", "graph_display_version",
            "graph_structures", "raw_ocr_text", "review", "text_count",
            "formula_count", "vision_used", "warning", "error", "cancelled"
        ) if k in raw_response}
        (output / (cid + "-ocr-response.json")).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        record["steps"].append("received_ocr_json")

        if not ocr_http.ok or data.get("error") or data.get("cancelled"):
            raise AssertionError("OCR HTTP %s: %s" % (ocr_http.status, data.get("error") or "cancelled"))

        dialog = page.locator("#ocrReviewDialog")
        dialog.wait_for(state="visible", timeout=25000)
        page.wait_for_timeout(750)  # allow MathJax rendering to settle
        question = page.locator("#ocrReviewQuestion").inner_text(timeout=10000).strip()
        visual = page.locator("#ocrReviewGraph").inner_text(timeout=10000).strip()
        record["rendered"] = {
            "question": question, "graph": visual,
            "mathjax_svg_count": page.locator("#ocrReviewDialog mjx-container svg").count(),
            "question_type": page.locator('input[name="ocrQuestionType"]:checked').input_value()
        }
        record["steps"].append("captured_actual_review_dialog")
        shot("ocr-review")

        if not (data.get("text") or data.get("visual_text")):
            raise AssertionError("OCR dialog opened but server returned no text or visual_text")
        if not (question or visual):
            raise AssertionError("OCR review is visually empty")
        record["comparisons"] = topology_comparison(
            data.get("graph_display_data"), case.get("expected", {}),
            str(data.get("text") or ""), str(data.get("visual_text") or ""))
        if solve:
            t0 = time.monotonic()
            # Confirmation is the user's real AI-solver route, not an API shortcut.
            with page.expect_response(
                lambda r: urlsplit(r.url).path == "/chat" and r.request.method == "POST",
                timeout=timeout_seconds*1000
            ) as answer_wait:
                page.locator("#ocrReviewConfirm").click()
            answer_http = answer_wait.value
            record["answer_http_status"] = answer_http.status
            record["answer_seconds"] = round(time.monotonic() - t0, 2)
            try:
                answer_json = answer_http.json()
            except Exception:
                answer_json = {"error": "Invalid /chat JSON", "text": answer_http.text()[:1000]}
            record["answer"] = {
                "reply": answer_json.get("reply", "") if isinstance(answer_json, dict) else "",
                "error": answer_json.get("error") if isinstance(answer_json, dict) else "Invalid response"
            }
            (output / (cid + "-answer.json")).write_text(
                json.dumps(record["answer"], ensure_ascii=False, indent=2), encoding="utf-8")
            if not answer_http.ok or not record["answer"]["reply"]:
                raise AssertionError("AI answer failed HTTP %s" % answer_http.status)
            page.wait_for_timeout(1200)
            shot("answer")
            record["steps"].append("captured_ai_answer")
        else:
            # Cancel safely: no paid solver and no unintended learning-history entry.
            page.locator("#ocrReviewCancel").click()
            dialog.wait_for(state="hidden", timeout=10000)
            record["steps"].append("cancelled_before_ai_solver")

    except Exception as exc:
        record["operational_error"] = str(exc)[:2500]
        record["traceback"] = traceback.format_exc()[-2500:]
        try:
            shot("failure")
        except Exception:
            pass
    finally:
        try:
            context.tracing.stop(path=str(output / (cid + "-trace.zip")))
        except Exception as exc:
            record["trace_error"] = str(exc)
        context.close()
    record["operational_ok"] = not bool(record.get("operational_error"))
    statuses = [c["status"] for c in record["comparisons"]]
    record["semantic_status"] = ("failed" if "failed" in statuses else
                                 "unverified" if "unverified" in statuses else
                                 "passed" if statuses else "not_configured")
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://dmate.zeabur.app/")
    parser.add_argument("--mode", choices=("mock", "live"), default="mock")
    parser.add_argument("--solve", action="store_true", help="Opt-in paid AI solving after each OCR result")
    parser.add_argument("--cases", default="tests/fixtures/graph_ocr_cases.json")
    parser.add_argument("--image-dir", default=".", help="Local directory with original images; not committed to GitHub")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--output", default="artifacts/ocr-regression")
    parser.add_argument("--strict", action="store_true", help="Fail workflow on semantic mismatch or missing verified graph")
    args = parser.parse_args()
    if urlsplit(args.url).scheme != "https":
        parser.error("Only HTTPS DMate URLs are allowed")
    if args.mode == "mock" and args.solve:
        parser.error("--solve is only valid with --mode live")
    if not 1 <= args.limit <= 20:
        parser.error("--limit must be 1..20")
    if args.solve and args.limit > 2:
        parser.error("AI solver capped at two cases per run")
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    generated = generate(out / "fixtures")
    for path in generated.values():
        # Preserve real input images alongside results, for reproducibility.
        pass
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"][:args.limit]
    report = {"mode": args.mode, "url": args.url,
              "started_at": datetime.now(timezone.utc).isoformat(), "cases": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for case in cases:
            image = case.get("image", "")
            image_key = Path(image).stem
            image_path = generated[image_key] if image == image_key + ".png" and image_key in generated else Path(args.image_dir) / image
            if not image_path.is_file():
                report["cases"].append({"id": case.get("id"), "operational_ok": False,
                                        "operational_error": "Fixture not found: " + str(image_path),
                                        "semantic_status": "not_configured"})
                continue
            expected_hash = str(case.get("source_sha256", "")).strip().lower()
            actual_hash = hashlib.sha256(image_path.read_bytes()).hexdigest()
            if expected_hash and actual_hash != expected_hash:
                report["cases"].append({
                    "id": case.get("id"), "operational_ok": False,
                    "operational_error": "Source image SHA256 mismatch: expected %s got %s" % (expected_hash, actual_hash),
                    "semantic_status": "not_configured"
                })
                continue
            result = run_case(browser, case, args.url, image_path, out, args.mode, args.solve, args.timeout)
            result["source_sha256"] = actual_hash
            report["cases"].append(result)
            print("[%s] HTTP=%s UI=%s topology=%s" %
                  (result["id"], result.get("ocr_http_status"), result["operational_ok"],
                   result["semantic_status"]), flush=True)
            if result.get("operational_error"):
                print("  " + result["operational_error"][:600], flush=True)
            for comp in result["comparisons"]:
                if comp["status"] != "passed":
                    print("  [%s] %s: %s" % (comp["status"], comp["check"], comp["detail"]), flush=True)
        browser.close()
    report["operational_ok"] = len(report["cases"]) == len(cases) and all(
        c.get("operational_ok") for c in report["cases"])
    report["semantic_passed"] = bool(report["cases"]) and all(
        c["semantic_status"] == "passed" for c in report["cases"])
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Report:", out / "report.json", flush=True)
    return 0 if report["operational_ok"] and (
        not args.strict or report["semantic_passed"]) else 1


if __name__ == "__main__":
    sys.exit(main())
