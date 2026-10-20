#!/usr/bin/env python3
"""Public real-world graph-diagram benchmark (source references, no copied fixtures).

All images are requested at test time from their original Wikimedia Commons
files. The URLs and known graph invariants are recorded below, not inferred
from the detector output. Source pages include the author and license.
This is a capability audit, not a claim that a partial detector solves every
directed, curved, labelled or multigraph diagram.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import statistics
import sys
import time
from urllib.parse import quote

import requests
from PIL import Image, ImageFilter, ImageOps
from graph_recognition import recognize_graphs


# Wikimedia filenames, drawing category and manually grounded simple graph
# invariants. Leave expected counts None when the screenshot contains multiple
# graphs, direction, parallel edges or loops unsuitable for straight-line CV.
# Public source: https://commons.wikimedia.org/wiki/File:<filename>
CASES = [
    ("Petersen_graph.svg", "planar-style circle-and-star", 10, 15),
    ("Petersen_graph_blue.svg", "blue nodes, star crossings", 10, 15),
    ("Petersen_graph_3-coloring.svg", "Petersen three-coloring", 10, 15),
    ("3-colouring_of_Petersen_graph.svg", "rearranged colored Petersen", 10, 15),
    ("Petersen_graph_3.svg", "Petersen alternative geometric layout", 10, 15),
    ("Petersen_graph_2.svg", "Petersen embedding / marked cycle", 10, 15),
    ("Cool_graph_Petersen.svg", "vertex-centered Petersen", 10, 15),
    ("Petersen-graph-factors.svg", "colored Petersen edge factors", 10, 15),
    ("Generalized_Petersen_9_2_edge_coloring.svg", "18-vertex edge coloring", 18, 27),
    ("4_diagrams_of_Petersen_graph.svg", "four layouts in one image", None, None),
    ("Petersen_graph_complement.svg", "complement of Petersen", None, None),
    ("Petersen_graph_total_coloring.png", "many-color graph", None, None),
    ("Undirected,_directed,_mixed,_multigraph.svg", "four graph types, arrows and loops", None, None),
    ("Graph_example_(Graph_theory).png", "thick red digraph, loops, multi-edges", None, None),
    ("Directed_graph_example.png", "rendered directed network", None, None),
    ("Directed_Graph_Example_1.png", "labeled directed network 1", None, None),
    ("Directed_Graph_Example_2.png", "labeled directed network 2", None, None),
    ("Directed-graph-6-vertices.png", "6-vertex directed network", None, None),
    ("Directedgraph_for_adjacencylist.svg", "small adjacency digraph", None, None),
    ("Example_of_simple_directed_graph.svg", "directed 3-vertex triangle", None, None),
    ("Example_of_a_Directed_Graph.svg", "DAG curved arrows", None, None),
    ("Example_directed_graph.svg", "colored directed graph", None, None),
    ("Directed_graph_example_el.svg", "foreign-language digraph", None, None),
    ("Example_of_simple_undirected_graph_1.svg", "four labeled vertices", None, None),
    ("Example_of_simple_undirected_graph_2.svg", "self-loop and parallel edges", None, None),
    ("Directed_Graph_Edge.svg", "isolated two-node arrow", None, None),
]


def commons_urls(filename):
    filename = filename.replace(" ", "_")
    hashed = hashlib.md5(filename.encode("utf-8")).hexdigest()
    path = f"https://upload.wikimedia.org/wikipedia/commons/{hashed[0]}/{hashed[:2]}/{quote(filename)}"
    if filename.lower().endswith(".svg"):
        # Rasterize from the source vector ourselves: no fragile thumb width URLs.
        return [path]
    return [path]


def download_image(session, filename, max_size=3_000_000):
    last_error = None
    for url in commons_urls(filename):
        try:
            with session.get(url, timeout=(8, 18), stream=True) as response:
                response.raise_for_status()
                chunks, count = [], 0
                for chunk in response.iter_content(32768):
                    count += len(chunk)
                    if count > max_size:
                        raise ValueError("remote image exceeds 3 MB")
                    chunks.append(chunk)
                raw = b"".join(chunks)
            if filename.endswith(".svg"):
                import cairosvg
                raw = cairosvg.svg2png(bytestring=raw, output_width=640)
            with Image.open(io.BytesIO(raw)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
            if image.width < 20 or image.height < 20:
                raise ValueError("image too small")
            return image, None
        except Exception as e:
            last_error = f"{type(e).__name__}: {str(e)[:120]}"
    return None, last_error


def run_detector(image):
    buf = io.BytesIO()
    image.save(buf, "PNG")
    result = recognize_graphs(buf.getvalue(), text_hint="图 顶点 边 连接")
    graphs = result.get("graphs") or []
    return {"graphs":len(graphs),
            "vertices":[len(g.get("vertices") or []) for g in graphs],
            "edges":[len(g.get("edges") or []) for g in graphs],
            "confidence":[g.get("confidence") for g in graphs],
            "uncertain":[len(g.get("uncertain_edges") or []) for g in graphs]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-downloaded", type=int, default=8)
    args = parser.parse_args()
    session = requests.Session()
    session.headers.update({"User-Agent":
        "DMate-Graph-Benchmark/1.0 (educational CI, github.com/zm14744/DMate)",
        "Accept": "image/*"})
    records=[]
    for index, (filename, style, expected_vertices, expected_edges) in enumerate(CASES,1):
        print(f"[{index}/{len(CASES)}] {filename}", flush=True)
        image, error = download_image(session, filename)
        record={"file":filename,"style":style,
                "source":f"https://commons.wikimedia.org/wiki/File:{quote(filename)}",
                "expected_vertices":expected_vertices,"expected_edges":expected_edges}
        if image is None:
            record.update(status="download_failed",error=error)
        else:
            try:
                original = run_detector(image)
                record.update(status="tested", original=original)
                if expected_vertices is not None:
                    record["known_graph_exact"] = (
                        len(original["vertices"]) == 1
                        and original["vertices"][0] == expected_vertices
                        and original["edges"][0] == expected_edges
                    )
                    # If complex layout fails, it should not pretend the CV
                    # output is independently sufficient to answer the question.
                    record["unsafe_high"] = (
                        not record["known_graph_exact"]
                        and any(v == "high" for v in original["confidence"])
                    )
                # Test a blurred/shrunken source subset to bound CI runtime.
                if index in {1,2,3,4,9,13,14,16,21,23}:
                    resize = image.copy()
                    if max(resize.size) > 560:
                        resize.thumbnail((560,560),Image.Resampling.LANCZOS)
                    record["small"] = run_detector(resize)
                    record["blurred"] = run_detector(image.filter(
                        ImageFilter.GaussianBlur(1.15)))
            except Exception as e:
                record.update(status="detector_error",error=f"{type(e).__name__}: {e}")
        records.append(record)
        print(json.dumps(record,ensure_ascii=False),flush=True)
    tested=[v for v in records if v["status"]=="tested"]
    exact=[v for v in tested if v.get("known_graph_exact") is not None]
    unsafe=[v for v in tested if v.get("unsafe_high")]
    summary={
        "sources":len(CASES),"downloaded_and_tested":len(tested),
        "download_failed":len([v for v in records if v["status"]=="download_failed"]),
        "detector_errors":len([v for v in records if v["status"]=="detector_error"]),
        "known_invariants_exact":sum(v["known_graph_exact"] for v in exact),
        "known_invariants_checked":len(exact),
        "potentially_unsafe_high_confidence":len(unsafe),
        "disclaimer":"OpenCV-only positional detector; not complete DeepSeek Vision OCR or solution accuracy.",
    }
    print("PUBLIC_BENCHMARK_SUMMARY "+json.dumps(summary,ensure_ascii=False),flush=True)
    report=Path(os.environ.get("RUNNER_TEMP", ".")) / "dmate-public-graph-benchmark.json"
    report.write_text(json.dumps({"summary":summary,"records":records},
                                 ensure_ascii=False,indent=2),encoding="utf-8")
    print("Report:",report)
    step_summary=os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary,"a",encoding="utf-8") as stream:
            stream.write("## Real-world Wikimedia graph benchmark\n\n")
            stream.write(f"Sources: {len(CASES)}; retrieved/tested: {len(tested)}; "
                         f"known-invariant exact: {summary['known_invariants_exact']}/{len(exact)}; "
                         f"unsafe high-confidence: {len(unsafe)}.\n\n")
            stream.write("This is OpenCV-only; directed and curved edges require Vision.\n\n")
            stream.write("| Drawing | Style | Nodes/edges found | Confidence | Ground truth |\n|---|---|---|---|---|\n")
            for r in records:
                o=r.get("original",{})
                edge=f"{o.get('vertices','—')}/{o.get('edges','—')}"
                expected=(f"{r['expected_vertices']}/{r['expected_edges']}"
                          if r["expected_vertices"] is not None else "type-only")
                stream.write(f"| [{r['file']}]({r['source']}) | {r['style']} "
                             f"| {edge} | {o.get('confidence','unavailable')} | {expected} |\n")
    if len(tested)<args.min_downloaded:
        print(f"Not enough source images downloadable: {len(tested)} < {args.min_downloaded}",file=sys.stderr)
        return 2
    if any(r["status"]=="detector_error" for r in records):
        return 3
    # Print unsafe cases visibly, but do not falsely claim that a pure-CV
    # detector must parse arbitrary multigraphs/arrows or all crowded drawings.
    if unsafe:
        print("UNSAFE HIGH-CONFIDENCE cases:",[v["file"] for v in unsafe])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
