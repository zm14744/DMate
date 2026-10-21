#!/usr/bin/env python3
"""Strict MIT 6.042J 2005 PS4 P3 pixel graph topology regression.

The source is the unchanged official graph figure. Vertex labels are a separate
Vision/OCR task; this test checks the actual *unlabelled* eight-dot, nine-edge
graph is isomorphic to the human verified letter-labelled diagram.
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

URL="https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-fall-2005/587366ef0ee07f57ed41715559224224_ps4.pdf"
GOLD_EDGES=["AB","BC","BH","CD","CE","DE","EF","EH","FG"]


def cropped_original():
    response=requests.get(URL,timeout=(12,55))
    response.raise_for_status()
    if not response.content.startswith(b"%PDF"):
        raise RuntimeError("MIT source is not a PDF")
    pdf=fitz.open(stream=response.content,filetype="pdf")
    pix=pdf[1].get_pixmap(matrix=fitz.Matrix(2.6,2.6),alpha=False)
    im=Image.frombytes("RGB",(pix.width,pix.height),pix.samples)
    x0,y0,x1,y1=(.19,.065,.82,.29)
    crop=im.crop((
        int(x0*im.width),int(y0*im.height),
        int(x1*im.width),int(y1*im.height)
    ))
    output=io.BytesIO()
    crop.save(output,format="PNG")
    return output.getvalue()


def same_graph_unlabelled(graph):
    vertices=graph.get("vertices") or []
    if len(vertices)!=8 or len(graph.get("edges") or [])!=9:
        return False
    index={v["id"]:i for i,v in enumerate(vertices)}
    edges={
        tuple(sorted((index[u],index[v])))
        for u,v in graph["edges"]
    }
    golden={
        tuple(sorted(("ABCDEFGH".index(edge[0]),
                      "ABCDEFGH".index(edge[1]))))
        for edge in GOLD_EDGES
    }
    deg=lambda edges: sorted(sum(k in edge for edge in edges) for k in range(8))
    if len(edges)!=9 or deg(edges)!=deg(golden):
        return False
    for perm in itertools.permutations(range(8)):
        if {
            tuple(sorted((perm[i],perm[j])))
            for i,j in edges
        }==golden:
            return True
    return False


def main():
    image=cropped_original()
    Path("mit_ps4_original_graph.png").write_bytes(image)
    result=recognize_graphs(
        image,text_hint="graph problem eight vertices diameter colour"
    )
    graphs=result.get("graphs") or []
    summary={
        "source":URL,
        "original_graph_count":1,
        "found":len(graphs),
        "vertices":[len(g.get("vertices") or []) for g in graphs],
        "edges":[len(g.get("edges") or []) for g in graphs],
        "detector":result.get("detector"),
        "topology_matches_original_gold":(
            len(graphs)==1 and same_graph_unlabelled(graphs[0])
        )
    }
    print("MIT_PS4_ORIGINAL_PIXEL_GRAPH",json.dumps(summary,ensure_ascii=False),flush=True)
    Path("mit_ps4_graph_result.json").write_text(json.dumps(
        {"summary":summary,"graph_structures":graphs},ensure_ascii=False,indent=2
    ))
    assert summary["topology_matches_original_gold"], summary
    assert result.get("detector")=="black_disk_chord_pixel", summary


if __name__=="__main__":
    main()
