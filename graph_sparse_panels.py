"""Pixel-based straight-edge recognition for aligned blue-outline graph panels.

Conservative auxiliary path: only regular multi-panel grids with small circular
endpoints and blue ink are eligible. Crossings are never new vertices; curved,
red/black, arrowed, and label-only drawings remain with the original Vision
pipeline. This is graph detection, not an answer template.
"""
from __future__ import annotations

import io
import math

import cv2
import numpy as np
from PIL import Image, ImageOps


def _panel_edges(rgb):
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    b, g, r = [bgr[:,:,index].astype(np.int16) for index in range(3)]
    # Stanford-style blue hairlines are distinguishable from black prose
    # ("Proof.", labels) elsewhere in the same panel.
    blue = (b - r > 12) & (b < 235) & (b > 40)
    if int(blue.sum()) < 90:
        return None
    mask = np.uint8(blue) * 255
    candidates = cv2.HoughLinesP(
        mask, 1, np.pi/360, threshold=17,
        minLineLength=max(28, min(rgb.shape[:2])//10),
        maxLineGap=9
    )
    if candidates is None:
        return None
    normalized = []
    for line in candidates[:,0]:
        points=np.asarray(line, dtype=float).reshape(2,2)
        delta=points[1]-points[0]
        length=float(np.linalg.norm(delta))
        if length < 28:
            continue
        vec=delta/length
        if vec[0] < 0 or (abs(vec[0]) < .001 and vec[1] < 0):
            vec=-vec
        norm=np.array([-vec[1], vec[0]])
        normalized.append({
            "vec":vec,
            "rho":float(points.mean(0)@norm),
            "lo":float(min(points@vec)),
            "hi":float(max(points@vec)),
            "points":points,
        })
    groups=[]
    for line in sorted(normalized,key=lambda item:-(item["hi"]-item["lo"])):
        for group in groups:
            basis=group["vec"]
            if abs(float(basis@line["vec"])) < .997:
                continue
            normal=np.array([-basis[1],basis[0]])
            if abs(float(line["points"].mean(0)@normal)-group["rho"]) > 3.4:
                continue
            lower=float(min(line["points"]@basis))
            upper=float(max(line["points"]@basis))
            if lower>group["hi"]+16 or upper<group["lo"]-16:
                continue
            group["lo"]=min(group["lo"],lower)
            group["hi"]=max(group["hi"],upper)
            break
        else:
            groups.append({
                "vec":line["vec"], "rho":line["rho"],
                "lo":line["lo"], "hi":line["hi"]
            })
    if not 2 <= len(groups) <= 20:
        return None

    # Circle candidates are found on raw greyscale so anti-aliased light-blue
    # rings are not lost when the color-only line mask is thresholded.
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    rings=cv2.HoughCircles(
        gray,cv2.HOUGH_GRADIENT,dp=1,
        minDist=max(19,min(rgb.shape[:2])//17),
        param1=28,param2=8,minRadius=2,maxRadius=5
    )
    if rings is None:
        return None
    circles=[np.asarray(circle[:2],dtype=float) for circle in rings[0]]
    if len(circles) > 45:
        return None
    endpoints=[]
    for group in groups:
        basis=group["vec"]
        normal=np.array([-basis[1],basis[0]])
        endpoints.append((
            basis*group["lo"]+normal*group["rho"],
            basis*group["hi"]+normal*group["rho"]
        ))
    # Remove unrelated circles in the printed text; an actual circular graph
    # vertex must lie at the tip of at least one separately traced blue stroke.
    located=[]
    for circle in circles:
        if any(min(float(np.linalg.norm(circle-end)) for end in segment) <= 12
               for segment in endpoints):
            located.append(circle)
    if not 3 <= len(located) <= 16:
        return None
    # Hough sometimes finds a pair of rings around one circle. Merge within
    # 5 px, but do not merge distinct vertices with different incident edges.
    deduped=[]
    for circle in sorted(located,key=lambda p:(p[1],p[0])):
        if not any(np.linalg.norm(circle-other)<5 for other in deduped):
            deduped.append(circle)
    located=deduped
    pairs=set()
    for start,end in endpoints:
        choices=[]
        for point in (start,end):
            distances=[float(np.linalg.norm(point-v)) for v in located]
            if not distances or min(distances)>12:
                return None
            choices.append(int(np.argmin(distances)))
        a,b=choices
        if a==b or tuple(sorted((a,b))) in pairs:
            return None
        pairs.add(tuple(sorted((a,b))))
    if len(pairs) != len(groups):
        return None
    # All visible circular endpoints and every straight line must match.
    # A curve/arrow/unmatched stroke yields no confident pixel graph.
    if len({v for pair in pairs for v in pair}) != len(located):
        return None
    return located,pairs


def recognize_blue_outline_panels(image_bytes):
    """Return a full six-panel drawing only when *every* figure is traceable.

    Normalized positions map back to the original unmodified image. A failed
    panel makes this entire optional detector abstain, never invent edges.
    """
    from ai import _diagram_grid_crops

    with Image.open(io.BytesIO(image_bytes)) as source:
        original=ImageOps.exif_transpose(source).convert("RGB")
    width,height=original.size
    if not (600 <= width <= 2400 and 380 <= height <= 1700):
        return {"graphs":[],"status":"unsupported","regions":[]}
    candidates=_diagram_grid_crops(original,individual=True,with_boxes=True)
    if len(candidates) != 6:
        return {"graphs":[],"status":"unsupported","regions":[]}
    graphs=[]
    regions=[]
    for index,(crop,box) in enumerate(candidates,1):
        detected=_panel_edges(np.asarray(crop))
        if detected is None:
            return {"graphs":[],"status":"partial","regions":[]}
        centers,edges=detected
        # Sort by location; IDs are per-panel *temporary*, never a/b/c labels.
        vertex_order=sorted(range(len(centers)),key=lambda i:(round(float(centers[i][1])/15),centers[i][0]))
        old_to_new={old:i for i,old in enumerate(vertex_order)}
        vertices=[
            {
                "id":f"v{i+1}",
                "x":round((box[0]+float(centers[old][0]))/width,5),
                "y":round((box[1]+float(centers[old][1]))/height,5),
                "label":None
            } for i,old in enumerate(vertex_order)
        ]
        normalized_edges=sorted({
            tuple(sorted((old_to_new[a],old_to_new[b])))
            for a,b in edges
        })
        matrix=[[0]*len(vertices) for _ in vertices]
        root=list(range(len(vertices)))
        def find(node):
            while root[node] != node:
                node=root[node]
            return node
        for a,b in normalized_edges:
            matrix[a][b]=matrix[b][a]=1
            root[find(a)]=find(b)
        components=len({find(i) for i in range(len(vertices))})
        region=(box[0]/width,box[1]/height,box[2]/width,box[3]/height)
        regions.append(region)
        graphs.append({
            "id":f"图{index}",
            "directed":"unknown",
            "vertices":vertices,
            "vertex_count":len(vertices),
            "edges":[[f"v{a+1}",f"v{b+1}"] for a,b in normalized_edges],
            "confirmed_edge_count":len(normalized_edges),
            "adjacency_matrix":matrix,
            "component_count_of_confirmed_edges":components,
            "uncertain_edges":[],
            "bbox":[round(v,5) for v in regions[-1]] if regions else [],
            # Pencil-thin circles and lines corroborate topology, but CV
            # alone cannot rule out overlays or all possible curved edges.
            "confidence":"partial",
        })
    return {"graphs":graphs,"status":"partial","regions":regions,
            "detector":"hough_blue_outline_panels"}


__all__=["recognize_blue_outline_panels"]
