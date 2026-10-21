#!/usr/bin/env python3
"""2026-10-21 original university graph-image topology recheck.

This benchmark does NOT infer image correctness from successful HTTP responses,
plausible answers, or a model's self-reported confidence. It stores original
image crops and all graph OCR output for independent pixel/edge auditing.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import io
import json
import re
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from global_graph_picture_benchmark import CASES as GLOBAL, fetch_pdf_image
from curated_university_graph_images import CASES as CURATED
from global_graph_image_benchmark import SOURCES as EXTRAS

EXPECTED_REVISION = "2026-10-21-pixel-preserving-multipanel-edge-v1"

# Assert a panel count only where the source's question and crop define it.
# Zero entries are deliberately NOT interpreted as one graph.
PANEL_COUNTS = {
    "CN_SJTU_EULER3": 3,
    "CN_NJU_EULER3": 2,
    "AU_UNSW_SIMPLE5": 5,
    "AU_UNSW_STAR4": 1,
    "AU_UNSW_BIP_A": 1,
    "AU_UNSW_BIP_B": 1,
    "AU_UNSW_ISO_A": 2,
    "AU_UNSW_ISO_B": 2,
    "JP_AIZU_ISO": 2,
    "US_CORNELL_ISO": 2,
    "MIT05_P3": 1,
    "MIT05_FOUR": 4,
    "STANFORD_TREE6": 6,
    "HKUST_PETERSEN": 1,
    "HKUST_POLY": 3,
    "INDIA_BITMESRA_ISO": 2,
    "NJU_DIRECTED": 3,
    "US_CORNELL_DFA": 1,
    "CN_NJU_DIRECTED": 3,
    "IN_BITMESRA_K4": 2,
    "US_MIT_GRAPH": 1,
}


def collect(batch):
    if batch == "global":
        return [dict(c, source_set="global_original_20261020") for c in GLOBAL]
    if batch == "curated":
        return [dict(c, source_set="curated_original_20261020") for c in CURATED]
    return [dict(c, source_set="supplementary_original_20261020") for c in EXTRAS]


def safe_json(response):
    try:
        return response.json()
    except Exception:
        return {"error": "Non-JSON HTTP response", "body": response.text[:700]}


def count_text_diagrams(text):
    """Conservative distinct caption count, NOT proof of correct splitting."""
    starts = set()
    for match in re.finditer(
        r"(?im)^\s*(?:(?:图\s*|G\s*_?\{?)([1-9]\d*)|"
        r"(?:Figure|Fig\.?)\s*([1-9]\d*))\b", str(text or "")
    ):
        starts.add(int(match.group(1) or match.group(2)))
    return sorted(starts)


def structure_evidence(output):
    blocks = output.get("graph_structures")
    if isinstance(blocks, dict):
        graphs = blocks.get("graphs")
    elif isinstance(blocks, list):
        graphs = blocks
    else:
        graphs = None
    if not isinstance(graphs, list):
        return {"count": None, "complete": False, "edge_counts": []}
    edge_counts = [
        len(g.get("edges") or []) if isinstance(g, dict) else None
        for g in graphs
    ]
    return {
        "count": len(graphs),
        "complete": bool(graphs) and all(
            isinstance(g, dict)
            and g.get("confidence") == "high"
            and not g.get("uncertain_edges")
            for g in graphs
        ),
        "edge_counts": edge_counts,
    }


def canonical_edge_check(source, visual):
    """Exact topology match ONLY for independently curated labeled edge lists."""
    gold = source.get("canonical")
    if not gold:
        return "NO_INDEPENDENT_EDGE_GOLD"
    from graph_integrity import parse_diagrams
    from collections import Counter
    expected = parse_diagrams(gold)
    observed = parse_diagrams(visual)
    if not expected or set(expected) != set(observed):
        return "EDGE_LIST_NOT_PARSEABLE"
    return (
        "EXACT_EDGE_GOLD_MATCH"
        if all(
            set(expected[i]["vertices"]) == set(observed[i]["vertices"])
            and Counter(expected[i]["edges"]) == Counter(observed[i]["edges"])
            for i in expected
        )
        else "EDGE_LIST_MISMATCH"
    )


def assess(row, output, http):
    if http != 200:
        return "OCR_HTTP_FAILED"
    visual = str(output.get("visual_text") or "")
    text = str(output.get("text") or "")
    if not visual.strip():
        return "NO_GRAPH_TRANSCRIPTION"
    if "【图形结构待核对】" in visual:
        return "GRAPH_UNCERTAIN_NOT_A_PASS"
    if "待核对" in visual or "未确认" in visual:
        return "GRAPH_UNCERTAIN_NOT_A_PASS"
    exact = row["edge_gold_verdict"]
    if exact == "EDGE_LIST_MISMATCH":
        return "EDGE_LIST_MISMATCH"
    if exact == "EXACT_EDGE_GOLD_MATCH":
        return "EXACT_EDGE_GOLD_MATCH"
    if row["expected_graph_count"] is not None:
        # Machine CV split counts are provisional, and prose captions alone
        # are NOT an exact topology oracle.
        seen = row["cv_evidence"]["count"]
        if seen is not None and seen != row["expected_graph_count"]:
            return "CV_PANEL_COUNT_MISMATCH"
        if seen is None:
            return "PANEL_SPLIT_UNVERIFIED"
    return "GRAPH_READ_EDGES_REQUIRE_GOLD"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", choices=["global", "curated", "extra"], required=True)
    ap.add_argument("--base", default="https://dmate.zeabur.app")
    ap.add_argument("--output", default="")
    ap.add_argument("--delay", type=float, default=8)
    ap.add_argument("--timeout", type=int, default=115)
    args = ap.parse_args()

    base = args.base.rstrip("/")
    out_dir = Path("graph_topology_originals") / args.batch
    out_dir.mkdir(parents=True, exist_ok=True)
    result_file = Path(args.output or f"graph_topology_{args.batch}.json")
    session = requests.Session()
    try:
        health_resp = session.get(base + "/health", timeout=15)
        health = safe_json(health_resp)
    except Exception as exc:
        health = {"error": repr(exc)}
    revision = health.get("graph_topology_revision")
    ready = {}
    try:
        ready = safe_json(session.get(base + "/ready", timeout=15))
    except Exception as exc:
        ready = {"error": repr(exc)}
    output = {
        "batch": args.batch,
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "health": health,
        "ready": ready,
        "expected_revision": EXPECTED_REVISION,
        "deployed_revision_verified": revision == EXPECTED_REVISION,
        "note": "Only exact edge gold matches are graph-topology passes. CV split is not exact graph correctness.",
        "cases": [],
    }
    rows = collect(args.batch)
    cache = {}
    for i, source in enumerate(rows):
        case_id = source["id"]
        row = {
            "id": case_id,
            "source_set": source["source_set"],
            "institution": source.get("institution") or source.get("uni") or source.get("country"),
            "source_url": source.get("url"),
            "page": source.get("page"),
            "crop": source.get("box"),
            "expected_graph_count": PANEL_COUNTS.get(case_id),
            "deployed_revision_verified": output["deployed_revision_verified"],
            "status": "NOT_RUN",
        }
        try:
            raw, dims = fetch_pdf_image(session, source, cache)
            (out_dir / (case_id + ".png")).write_bytes(raw)
            row["sha256"] = hashlib.sha256(raw).hexdigest()
            row["dimensions"] = dims
        except Exception as exc:
            row["status"] = "SOURCE_FAILED"
            row["source_error"] = repr(exc)
            output["cases"].append(row)
            result_file.write_text(json.dumps(output, ensure_ascii=False, indent=2))
            print("GRAPH_CASE", case_id, row["status"], flush=True)
            continue

        try:
            result = session.post(base + "/ocr",
                files={"image": (case_id + ".png", raw, "image/png")},
                timeout=(12, args.timeout))
            response = safe_json(result)
            row["ocr_http"] = result.status_code
            row["ocr"] = {
                k: response.get(k) for k in (
                    "text", "visual_text", "graph_structures", "review",
                    "warnings", "vision_used", "image_kind", "error",
                )
            }
            row["caption_numbers"] = count_text_diagrams(row["ocr"].get("visual_text"))
            row["cv_evidence"] = structure_evidence(response)
            row["edge_gold_verdict"] = canonical_edge_check(
                source, row["ocr"].get("visual_text")
            )
            row["status"] = assess(row, response, result.status_code)
        except Exception as exc:
            row["status"] = "OCR_REQUEST_FAILED"
            row["ocr_error"] = repr(exc)

        output["cases"].append(row)
        result_file.write_text(json.dumps(output, ensure_ascii=False, indent=2))
        print("GRAPH_CASE", case_id, row["status"],
              "CV_PANELS", row.get("cv_evidence", {}).get("count"),
              "EXPECTED_PANELS", row.get("expected_graph_count"),
              "EDGE_GOLD", row.get("edge_gold_verdict"), flush=True)
        if i < len(rows) - 1:
            time.sleep(max(0, args.delay))
    output["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    output["summary"] = dict(collections.Counter(
        r["status"] for r in output["cases"]
    ))
    result_file.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print("BATCH_SUMMARY", args.batch, output["summary"],
          "DEPLOYED_REVISION", output["deployed_revision_verified"], flush=True)
    # A successful run indicates evidence was collected, not accuracy.
    # Missing cases are always an execution failure.
    return 0 if len(output["cases"]) == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
