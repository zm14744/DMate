"""Conservative arrowhead evidence for directed graph screenshots.

Detect paired backward wings near one endpoint of a traced stroke. A marked
vertex rim alone is not an arrowhead. All results remain unconfirmed hints.
"""
from __future__ import annotations

import math

import cv2
import numpy as np


def _paired_wings(segments, tip, direction, scale):
    ux, uy = direction
    left, right = [], []
    join_dist = max(5.5, min(10.0, scale * 0.85))
    min_wing = max(4.0, scale * 0.38)
    max_wing = max(18.0, scale * 2.7)
    for ax, ay, bx, by in segments:
        for px, py, qx, qy in ((ax, ay, bx, by), (bx, by, ax, ay)):
            near = math.hypot(px - tip[0], py - tip[1])
            if near > join_dist:
                continue
            vx, vy = qx - px, qy - py
            length = math.hypot(vx, vy)
            if not min_wing <= length <= max_wing:
                continue
            backward = -(vx * ux + vy * uy)
            lateral = vx * uy - vy * ux
            if not (backward > 2.5 and 0.28 < abs(lateral)/length < 0.96):
                continue
            if not (0.2 < backward / length < 0.94):
                continue
            value = (1 - near / (join_dist+1)) * min(length/max(min_wing,1), 2)
            (left if lateral < 0 else right).append((value, (px, py)))
    if not left or not right:
        return 0.0
    for l_score, l_point in left:
        for r_score, r_point in right:
            if math.dist(l_point, r_point) <= max(8.5, join_dist * 1.5):
                return min(1.0, 0.42 + 0.18 * min(l_score, r_score))
    return 0.0


def _endpoint_tangent(path, node, default):
    if len(path) < 3:
        return default
    coords = []
    for value in path:
        if isinstance(value, (list, tuple)) and len(value) == 2:
            try:
                coords.append((float(value[0]), float(value[1])))
            except (TypeError, ValueError):
                pass
    if len(coords) < 3:
        return default
    start_near = math.dist(coords[0], node) < math.dist(coords[-1], node)
    if start_near:
        near, far = coords[0], coords[min(2, len(coords)-1)]
    else:
        near, far = coords[-1], coords[max(0, len(coords)-3)]
    vx, vy = near[0]-far[0], near[1]-far[1]
    length = math.hypot(vx, vy)
    return (vx/length, vy/length) if length > 5 else default


def annotate_arrow_candidates(rgb, graph, paths, radius):
    """Add geometric arrow hints to line candidates; never alter actual edges."""
    if not paths or not graph.get("vertices"):
        return paths
    h, w = rgb.shape[:2]
    vertices = {}
    for item in graph["vertices"]:
        try:
            if item.get("x") is None or item.get("y") is None:
                continue
            vertices[str(item["id"])] = (
                float(item["x"])*(w-1), float(item["y"])*(h-1)
            )
        except (TypeError, ValueError, KeyError):
            continue
    if len(vertices) < 2:
        return paths
    # Crop around this mathematical graph: captions and adjacent diagrams
    # must not create arrowheads, nor should each panel scan the whole page.
    border = max(32, round(radius*5))
    x1 = max(0, int(min(x for x,y in vertices.values()))-border)
    x2 = min(w, int(max(x for x,y in vertices.values()))+border+1)
    y1 = max(0, int(min(y for x,y in vertices.values()))-border)
    y2 = min(h, int(max(y for x,y in vertices.values()))+border+1)
    if x2-x1 < 20 or y2-y1 < 20:
        return paths
    from graph_line_tracer import _foreground
    mask = _foreground(rgb[y1:y2, x1:x2])
    for x,y in vertices.values():
        cv2.circle(mask, (round(x)-x1,round(y)-y1),
                   max(3,round(radius*1.18)),0,-1)
    segments=cv2.HoughLinesP(
        cv2.Canny(mask,50,145),1,np.pi/360,threshold=7,
        minLineLength=max(4,round(radius*.45)),maxLineGap=3,
    )
    if segments is None:
        return paths
    lines=[(float(ax+x1),float(ay+y1),float(bx+x1),float(by+y1))
           for ax,ay,bx,by in segments[:,0][:850]]
    for path in paths:
        a, b = str(path.get("from","")), str(path.get("to",""))
        if a not in vertices or b not in vertices or a == b:
            continue
        scores = {}
        for source, target in ((a,b), (b,a)):
            sx, sy = vertices[source]
            tx, ty = vertices[target]
            distance = math.hypot(tx-sx, ty-sy)
            if distance < 4*radius:
                continue
            direction = ((tx-sx)/distance, (ty-sy)/distance)
            coords = [
                (p[0]*(w-1), p[1]*(h-1))
                for p in path.get("path", [])
                if isinstance(p, (tuple,list)) and len(p) == 2
            ]
            direction = _endpoint_tangent(coords, (tx,ty), direction)
            best = 0.0
            for d in np.linspace(max(radius*1.15,4),
                                 radius+max(6,radius*.9), 8):
                tip = (tx-d*direction[0], ty-d*direction[1])
                best = max(best, _paired_wings(lines, tip, direction, radius))
            scores[(source,target)] = best
        if not scores:
            continue
        ranked = sorted(scores.items(), key=lambda row:row[1], reverse=True)
        leading, score = ranked[0]
        other = ranked[1][1] if len(ranked)>1 else 0
        if score >= .49 and score-other >= .12:
            path["arrow_candidate"] = {
                "from": leading[0], "to": leading[1],
                "score": round(score,3),
                "method": "opencv_paired_arrowhead_wings",
                "candidate_only": True,
            }
        elif score >= .49 and other >= .49:
            path["arrow_ambiguous"] = True
    return paths


__all__ = ["annotate_arrow_candidates"]
