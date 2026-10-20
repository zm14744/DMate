#!/usr/bin/env python3
"""Graph recognition benchmark using real third-party Graphviz drawings.

Sources: MIT-licensed rsms/graphviz examples plus public GitHub DOT examples.
We render the original DOT with Graphviz and extract node/edge counts from
Graphviz's -Tplain representation (ground truth independent of DMate).
No third-party artwork is committed to this repository. The network must work
for this optional benchmark; synthetic regressions remain fully offline.
"""
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import requests
from PIL import Image, ImageFilter, ImageOps, ImageEnhance
from graph_recognition import recognize_graphs

SOURCES=[
    # Real published Graphviz gallery examples; many intentionally outside
    # straight-line-simple-graph capability (arrows, loops, boxes, curves).
    ("rsms/graphviz","master","docs/examples/color-dots-graph.dot","multicolor undirected graph"),
    ("rsms/graphviz","master","docs/examples/color-dots.dot","15-node colored directed graph"),
    ("rsms/graphviz","master","docs/examples/kuratowski.dot","K3,3 and K5 in one figure"),
    ("rsms/graphviz","master","docs/examples/clusters.dot","directed clusters"),
    ("rsms/graphviz","master","docs/examples/data_structs.dot","record node shapes"),
    ("rsms/graphviz","master","docs/examples/fsm.dot","directed FSM with loops"),
    ("rsms/graphviz","master","docs/examples/lalr.dot","LALR parse states / table labels"),
    ("rsms/graphviz","master","docs/examples/prof.dot","call graph"),
    ("rsms/graphviz","master","docs/examples/projects.dot","project dependency graph"),
    ("rsms/graphviz","master","docs/examples/records.dot","record/diamond graph"),
    ("rsms/graphviz","master","docs/examples/switch.dot","dense colorful switch"),
    ("rsms/graphviz","master","docs/examples/unix.dot","UNIX family tree"),
    ("caseywatts/graphviz-tutorial","master","example.dot","clustered colored diagram"),
    ("caseywatts/graphviz-tutorial","master","database_record_example.dot","database record diagram"),
    ("pbosetti/gv2fsm","master","examples/sm.dot","FSM with self-loops")
]
# Source licensing: rsms/graphviz MIT, caseywatts/graphviz-tutorial and
# pbosetti/gv2fsm see upstream LICENSE. No copied source or images stored.

def fetch_source(session, owner, ref, path):
    url=f"https://raw.githubusercontent.com/{owner}/{ref}/{path}"
    r=session.get(url,timeout=(8,16))
    r.raise_for_status()
    if len(r.content)>70000:
        raise ValueError("oversized DOT input")
    return r.text,url

def normalize_dot(data):
    # Gallery snippets intentionally omit outer digraph { } for web demos.
    cleaned=data.lstrip()
    if not re.match(r"^(?:strict\s+)?(?:digraph|graph)\s+(?:[^\s{]+\s*)?\{",cleaned):
        kind="graph" if "--" in cleaned and "->" not in cleaned else "digraph"
        return f"{kind} G {{\n{data}\n}}\n"
    return data

def render(src,fmt):
    proc=subprocess.run(["dot",f"-T{fmt}"],input=src.encode("utf-8"),
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=32)
    if proc.returncode:
        raise ValueError("Graphviz: "+proc.stderr.decode("utf-8","replace")[-180:])
    return proc.stdout

def truth_from_plain(raw):
    count_nodes=count_edges=0
    for line in raw.decode("utf-8","replace").splitlines():
        if line.startswith("node "):count_nodes+=1
        if line.startswith("edge "):count_edges+=1
    return count_nodes,count_edges

def check_image(image):
    stream=io.BytesIO()
    image.save(stream,"PNG")
    result=recognize_graphs(stream.getvalue(),text_hint="图 顶点 边")
    gs=result.get("graphs") or []
    return {"graph_count":len(gs),
        "vertices":[len(g.get("vertices") or []) for g in gs],
        "edges":[len(g.get("edges") or []) for g in gs],
        "confidence":[g.get("confidence") for g in gs],
        "uncertain_edges":[len(g.get("uncertain_edges") or []) for g in gs]}

def run():
    session=requests.Session()
    session.headers["User-Agent"]="DMate-Graph-Benchmark/1.0 (+https://github.com/zm14744/DMate)"
    report=[]
    for pos,(owner,ref,path,style) in enumerate(SOURCES,1):
        item={"source":f"https://github.com/{owner}/blob/{ref}/{path}","style":style}
        print(f"[{pos}/{len(SOURCES)}] {path}",flush=True)
        try:
            src,url=fetch_source(session,owner,ref,path)
            src=normalize_dot(src)
            truth=truth_from_plain(render(src,"plain"))
            raster=render(src,"png")
            with Image.open(io.BytesIO(raster)) as im:
                full=ImageOps.exif_transpose(im).convert("RGB")
            if max(full.size)>1900:
                full.thumbnail((1900,1900),Image.Resampling.LANCZOS)
            item["truth"]={"vertices":truth[0],"edges":truth[1]}
            item["normal"]=check_image(full)
            # All input images originate from real published DOT examples.
            small=full.copy()
            if max(small.size)>620:
                small.thumbnail((620,620),Image.Resampling.LANCZOS)
            item["small_blurred"]=check_image(small.filter(ImageFilter.GaussianBlur(.8)))
            item["low_contrast"]=check_image(ImageEnhance.Contrast(full).enhance(.65))
            item["status"]="tested"
            # Ground truth count is valid for a *single detected whole graph*.
            result=item["normal"]
            item["exact_counts"]=bool(result["graph_count"]==1 and
                result["vertices"][0]==truth[0] and result["edges"][0]==truth[1])
            item["unsafe_high"]=bool(not item["exact_counts"] and
                "high" in result["confidence"])
        except Exception as e:
            item["status"]="failed"
            item["error"]=f"{type(e).__name__}: {str(e)[:260]}"
        report.append(item)
        print(json.dumps(item,ensure_ascii=False),flush=True)
    succeeded=[x for x in report if x["status"]=="tested"]
    summary={"sources":len(SOURCES),"tested":len(succeeded),
             "variants_tested":3*len(succeeded),
             "exact_counts_normal":sum(x.get("exact_counts",False) for x in succeeded),
             "unsafe_high":sum(x.get("unsafe_high",False) for x in succeeded),
             "failures":len(SOURCES)-len(succeeded),
             "note":"Pure OpenCV, not full online DeepSeek Vision; many graph styles intentionally unsupported."}
    print("GITHUB_DIAGRAM_SUMMARY "+json.dumps(summary,ensure_ascii=False),flush=True)
    step=os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step,"a",encoding="utf8") as out:
            out.write("## Graphviz public-image regression\n\n")
            out.write(f"Downloaded and rendered: {len(succeeded)}/{len(SOURCES)}; "
                      f"image variants: {3*len(succeeded)}; "
                      f"exact graph counts: {summary['exact_counts_normal']}/{len(succeeded)}; "
                      f"wrong high-confidence cases: {summary['unsafe_high']}.\n\n")
            out.write("OpenCV counts only; no end-to-end Vision inference.\n\n")
            out.write("| Real source | Ground-truth nodes/edges | Detected nodes/edges | Confidence | Exact |\n|---|---|---|---|---|\n")
            for row in report:
                counts=row.get("truth",{})
                actual=row.get("normal",{})
                out.write(f"| [{row['style']}]({row['source']}) "
                          f"| {counts.get('vertices','—')}/{counts.get('edges','—')} "
                          f"| {actual.get('vertices','—')}/{actual.get('edges','—')} "
                          f"| {actual.get('confidence','—')} | {row.get('exact_counts',False)} |\n")
    Path(os.environ.get("RUNNER_TEMP",".")).joinpath("public-dot-graph-report.json").write_text(
        json.dumps({"summary":summary,"report":report},ensure_ascii=False,indent=2),encoding="utf8")
    return 0 if len(succeeded)>=10 else 2

if __name__=="__main__":
    raise SystemExit(run())
