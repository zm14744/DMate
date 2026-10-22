#!/usr/bin/env python3
"""Grade *real* DMate OCR JSON and actual Playwright modal output against human visual truth.

This script cannot simulate responses. It consumes only artifacts produced by
ocr_regression.py --mode live from verified original PNGs.
"""
import argparse
from collections import Counter
from itertools import permutations
import json
from pathlib import Path
import re
import unicodedata


def normalized(value):
    text = str(value or "").strip()
    for pair in (("\\(", ""), ("\\)", ""), ("_", ""), ("{", ""), ("}", "")):
        text = text.replace(*pair)
    text = text.translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789"))
    return unicodedata.normalize("NFKC", text).lower()


def read_edges(graph, labels=None):
    edges = Counter()
    for e in graph.get("edges", []):
        if not isinstance(e, dict):
            continue
        a, b = normalized(e.get("from")), normalized(e.get("to"))
        if labels:
            a, b = labels.get(a, a), labels.get(b, b)
        if not a or not b:
            continue
        key = tuple(sorted((a, b))) if graph.get("directed") is False else (a, b)
        multiplicity = e.get("multiplicity", 1)
        if not isinstance(multiplicity, int) or multiplicity < 1:
            multiplicity = 1
        edges[key] += multiplicity
    return edges


def equivalent_unlabeled(want, got):
    """Exact small-graph isomorphism including loops and parallel-edge counts."""
    wv = [normalized(v) for v in want["vertices"]]
    gv = [normalized(x.get("id") if isinstance(x, dict) else x)
          for x in got.get("vertices", [])]
    if len(wv) != len(gv) or len(set(gv)) != len(gv) or len(wv) > 8:
        return False
    we = read_edges(want)
    ge = read_edges(got)
    if sum(we.values()) != sum(ge.values()):
        return False
    wd = Counter(v for edge, multiplicity in we.items() for v in edge for _ in range(multiplicity))
    gd = Counter(v for edge, multiplicity in ge.items() for v in edge for _ in range(multiplicity))
    if sorted(wd.get(v, 0) for v in wv) != sorted(gd.get(v, 0) for v in gv):
        return False
    for perm in permutations(gv):
        mapping = dict(zip(gv, perm))
        if all(we.get(key, 0) == ge.get(tuple(sorted((mapping[key[0]], mapping[key[1]]))), 0)
               for key in we) and all(
                   ge.get(key, 0) == we.get(tuple(sorted((perm.index(key[0]) < len(wv) and wv[perm.index(key[0])], wv[perm.index(key[1])]))), 0)
                   for key in ge
               ):
            return True
    return False


def equivalent_unlabeled(want, got):
    wv = [normalized(v) for v in want["vertices"]]
    gv = [normalized(x.get("id") if isinstance(x, dict) else x)
          for x in got.get("vertices", [])]
    if len(wv) != len(gv) or len(set(gv)) != len(gv) or len(wv) > 8:
        return False
    we, ge = read_edges(want), read_edges(got)
    if sum(we.values()) != sum(ge.values()):
        return False
    expected_degrees = Counter()
    actual_degrees = Counter()
    for (a, b), count in we.items():
        expected_degrees[a] += count
        expected_degrees[b] += count
    for (a, b), count in ge.items():
        actual_degrees[a] += count
        actual_degrees[b] += count
    if sorted(expected_degrees[v] for v in wv) != sorted(actual_degrees[v] for v in gv):
        return False
    for candidate in permutations(gv):
        mapping = dict(zip(wv, candidate))
        remapped = Counter()
        for (a, b), count in we.items():
            remapped[tuple(sorted((mapping[a], mapping[b])))] += count
        if remapped == ge:
            return True
    return False


def position_sort(graphs):
    """Sort 2x2 or 3x2 textbook panels top-down and then left-right."""
    pos = []
    for graph in graphs:
        vv = graph.get("vertices") if isinstance(graph, dict) else []
        coords = [
            (v["x"], v["y"]) for v in vv
            if isinstance(v, dict) and isinstance(v.get("x"), (int, float))
            and isinstance(v.get("y"), (int, float))
        ]
        if not vv or len(coords) != len(vv):
            return graphs
        x = sum(p[0] for p in coords) / len(coords)
        y = sum(p[1] for p in coords) / len(coords)
        pos.append((x, y))
    # Sort by row; don't accidentally sort by y within the same row.
    ranks = sorted(enumerate(pos), key=lambda t: t[1][1])
    ordered_rows = []
    for idx, (x, y) in ranks:
        if not ordered_rows or y - ordered_rows[-1][0] > .14:
            ordered_rows.append((y, [(idx, x)]))
        else:
            ordered_rows[-1][1].append((idx, x))
    return [graphs[idx] for _, row in ordered_rows
            for idx, _ in sorted(row, key=lambda t: t[1])]


def judge_case(case, actual, capture):
    want = case.get("expected", {}).get("graphs", [])
    checks = []
    def check(label, expected, received, result=None):
        passed = (received == expected) if result is None else result
        checks.append({"name": label, "result": "PASS" if passed else "FAIL",
                       "expected": expected, "actual": received})
    if not isinstance(actual, list) or not actual:
        return [{"name": "structured_graph_data", "result": "UNVERIFIED",
                 "expected": f"{len(want)} exact graphs",
                 "actual": "DMate did not expose a vetted graph_display_data; inspect captured /ocr visual_text and popup."}]
    ordered = position_sort(actual)
    check("graph_count", len(want), len(ordered))
    for i, w in enumerate(want):
        prefix = f"panel_{i+1}_{w['id']}"
        if i >= len(ordered):
            checks.append({"name": prefix, "result": "FAIL", "expected": "graph present", "actual": "missing"})
            continue
        g = ordered[i]
        got_vertices = g.get("vertices", [])
        expected_vertices = w.get("vertices", [])
        check(prefix + ".vertices", len(expected_vertices), len(got_vertices))
        check(prefix + ".edges_total", len(w["edges"]), sum(read_edges(g).values()))
        for kind in ("directed", "weighted", "multigraph"):
            check(prefix + "." + kind, w[kind], g.get(kind))
        if w["match_mode"] == "isomorphic":
            check(prefix + ".topology", w["family"], "actual edge topology",
                  equivalent_unlabeled(w, g))
        else:
            vlabel = sorted(normalized(v) for v in expected_vertices)
            actual_label = sorted(normalized(x.get("id") if isinstance(x, dict) else x)
                                  for x in got_vertices)
            check(prefix + ".vertex_names", vlabel, actual_label)
            check(prefix + ".edges_and_multiplicity",
                  [[*edge, count] for edge, count in sorted(read_edges(w).items())],
                  [[*edge, count] for edge, count in sorted(read_edges(g).items())],
                  read_edges(w) == read_edges(g))
        if g.get("complete") is not True or g.get("uncertain_edges"):
            checks.append({"name": prefix + ".completeness", "result": "UNVERIFIED",
                           "expected": "complete edge list", "actual": {
                               "complete": g.get("complete"),
                               "uncertain_edges": g.get("uncertain_edges")}})
    return checks


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cases", required=True)
    p.add_argument("--results", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    reference = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    run = json.loads((Path(args.results) / "report.json").read_text(encoding="utf-8"))
    by_id = {c.get("id"): c for c in run.get("cases", [])}
    rows = []
    for case in reference["cases"]:
        case_id = case["id"]
        capture = by_id.get(case_id, {})
        path = Path(args.results) / f"{case_id}-ocr-response.json"
        response = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        got = response.get("graph_display_data")
        checks = judge_case(case, got, capture)
        print("\n" + "=" * 72)
        print("REAL_ORIGINAL_IMAGE", case_id, "source_sha256", case["source_sha256"], flush=True)
        print("INDEPENDENT_GOLD", case["manual_vision_note"], flush=True)
        print("DMATE_HTTP", capture.get("ocr_http_status"), "OPERATIONAL_OK",
              capture.get("operational_ok"), flush=True)
        print("DMATE_TEXT", str(response.get("text") or "")[:3500], flush=True)
        print("DMATE_VISUAL_TEXT", str(response.get("visual_text") or "")[:10000], flush=True)
        print("DMATE_GRAPH_DATA", json.dumps(got, ensure_ascii=False)[:16000], flush=True)
        print("DMATE_RENDERED_POPUP", json.dumps(capture.get("rendered"), ensure_ascii=False)[:16000], flush=True)
        print("CHECKS", json.dumps(checks, ensure_ascii=False)[:16000], flush=True)
        result = ("OPERATION_ERROR" if not capture.get("operational_ok") else
                  "FAIL" if any(x["result"] == "FAIL" for x in checks) else
                  "UNVERIFIED" if any(x["result"] == "UNVERIFIED" for x in checks) else "PASS")
        print("FINAL_CASE_STATUS", case_id, result, flush=True)
        rows.append({"id": case_id, "status": result, "checks": checks,
                     "real_response": path.name if path.is_file() else None,
                     "rendered": capture.get("rendered"),
                     "operational_error": capture.get("operational_error"),
                     "manual_truth": case["manual_vision_note"]})
    summary = {"cases": rows, "all_pass": all(x["status"] == "PASS" for x in rows),
               "note": "Real original PNG -> real site Playwright -> /ocr JSON + real popup. Unverified is NOT a pass."}
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    (out/"independent-comparison.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# DMate OUC two original-image verification", "",
             "Raw /ocr responses and browser screenshots are in the same artifact.", ""]
    for row in rows:
        lines += [f"## {row['id']}: {row['status']}", "",
                  f"Independent truth: {row['manual_truth']}", "",
                  "| Item | Status | Expected | Actual |",
                  "|---|---|---|---|"]
        for c in row["checks"]:
            lines.append("| {name} | {result} | {expected} | {actual} |".format(**{
                key: str(c.get(key, "")).replace("|", "/").replace("\n", " ")[:350]
                for key in ("name", "result", "expected", "actual")}))
        lines.append("")
    (out/"independent-comparison.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    return 0 if summary["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
