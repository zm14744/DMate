#!/usr/bin/env python3
"""Real Stanford Math 108 figure: 6 distinct six-node trees, no model mocks.

Fetches the original official PDF and crops its embedded graphic unchanged.
The oracle is graph topology (six trees, each 6 vertices/5 edges, six different
isomorphism classes), not whether an LLM says 'six'.
"""
from __future__ import annotations

import io
import itertools
import json
from pathlib import Path

import fitz
import requests
from PIL import Image
from graph_recognition import recognize_graphs

URL="https://web.stanford.edu/class/math108/files/hw1sol.pdf"
PAGE=2
BOX=(.25,.115,.82,.39)


def image_from_official_pdf():
    r=requests.get(URL,timeout=(10,50))
    r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        raise RuntimeError("Stanford source did not return a PDF")
    pdf=fitz.open(stream=r.content,filetype="pdf")
    pix=pdf[PAGE].get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
    full=Image.frombytes("RGB",(pix.width,pix.height),pix.samples)
    left,top,right,bottom=BOX
    crop=full.crop((int(left*pix.width),int(top*pix.height),
                    int(right*pix.width),int(bottom*pix.height)))
    stream=io.BytesIO()
    crop.save(stream,format="PNG")
    return stream.getvalue()


def adjacency(graph):
    vertices=graph.get("vertices") or []
    ids=[node["id"] for node in vertices]
    index={v:i for i,v in enumerate(ids)}
    edges=set()
    for a,b in graph.get("edges") or []:
        if a not in index or b not in index or a==b:
            raise AssertionError("invalid edge endpoint")
        edges.add(tuple(sorted((index[a],index[b]))))
    return len(ids),edges


def isomorphic(a,b):
    n,edges_a=adjacency(a)
    m,edges_b=adjacency(b)
    if n!=m or len(edges_a)!=len(edges_b):
        return False
    for perm in itertools.permutations(range(n)):
        transformed={tuple(sorted((perm[i],perm[j]))) for i,j in edges_a}
        if transformed==edges_b:
            return True
    return False


def main():
    original=image_from_official_pdf()
    Path("stanford_original_6trees.png").write_bytes(original)
    result=recognize_graphs(original, text_hint="六个无标号树图的完整图形结构")
    graphs=result.get("graphs") or []
    summary={
        "source":URL,
        "original_count":6,
        "found":len(graphs),
        "vertices":[len(g.get("vertices") or []) for g in graphs],
        "edges":[len(g.get("edges") or []) for g in graphs],
        "confidence":[g.get("confidence") for g in graphs],
        "detector":result.get("detector"),
        "pairwise_nonisomorphic":None,
    }
    if len(graphs)==6:
        summary["pairwise_nonisomorphic"]=all(
            not isomorphic(a,b)
            for a,b in itertools.combinations(graphs,2)
        )
    print("STANFORD_ORIGINAL_PIXEL_GRAPH",json.dumps(summary,ensure_ascii=False),flush=True)
    Path("stanford_original_graph_result.json").write_text(
        json.dumps({"summary":summary,"graphs":graphs},ensure_ascii=False,indent=2))
    assert result.get("detector")=="hough_blue_outline_panels", summary
    assert len(graphs)==6, summary
    assert summary["vertices"]==[6]*6, summary
    assert summary["edges"]==[5]*6, summary
    assert summary["pairwise_nonisomorphic"], summary


if __name__=="__main__":
    main()
