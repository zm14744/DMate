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


def _segment_projection(point, a, b):
    """Distance, projection and the oriented tangent of a polyline segment."""
    dx, dy = b[0]-a[0], b[1]-a[1]
    length_sq = dx*dx + dy*dy
    if length_sq < 1e-5:
        return float('inf'), 0.0, (0.0, 0.0)
    t = max(0.0, min(1.0, ((point[0]-a[0])*dx+(point[1]-a[1])*dy)/length_sq))
    distance = math.hypot(point[0]-a[0]-dx*t, point[1]-a[1]-dy*t)
    norm = math.sqrt(length_sq)
    return distance, t, (dx/norm, dy/norm)


def _interior_arrow_score(segments, coords, start, end, radius):
    """Locate wing pairs along an actual connector rather than only at its end."""
    if len(coords) < 2 or not segments:
        return 0.0
    route = list(coords)
    if math.dist(route[0], start) > math.dist(route[-1], start):
        route.reverse()
    lengths = [math.dist(a, b) for a, b in zip(route, route[1:])]
    total = sum(lengths)
    if total < max(25.0, radius*5):
        return 0.0
    tips = {}
    step = max(3, radius//2)
    for x1,y1,x2,y2 in segments:
        # Arrow apexes are often Hough segment endpoints on the ink stroke.
        for tip in ((x1,y1),(x2,y2)):
            if min(math.dist(tip, start), math.dist(tip,end)) < max(2.5*radius,9):
                continue
            advance = 0.0
            best = None
            for i,(a, b) in enumerate(zip(route, route[1:])):
                dist, t, tangent = _segment_projection(tip,a,b)
                progress=(advance+t*lengths[i])/total
                if 0.08 < progress < 0.92 and (best is None or dist < best[0]):
                    best = (dist,tangent)
                advance += lengths[i]
            if best is None or best[0] > max(4.5, radius*0.85):
                continue
            key=(round(tip[0]/step),round(tip[1]/step))
            if key not in tips or best[0] < tips[key][0]:
                tips[key]=(best[0],tip,best[1])
    # The sample budget bounds runtime on dense scanned pages.
    best_score = 0.0
    for _,tip,direction in sorted(tips.values(),key=lambda item:item[0])[:36]:
        best_score=max(best_score,_paired_wings(segments,tip,direction,radius))
        if best_score >= 0.78:
            break
    return best_score


def _filled_arrow_profile(mask, coords, radius):
    """Find a bilateral triangular taper along the observed connector.

    Filled lecture-slide arrows often yield only a long shaft in Hough, so
    paired short wings are absent. A crossing has two comparable shoulders;
    a filled arrow has an abrupt base and a longer narrowing tip. This remains
    advisory image evidence, never a topology/direction decision by itself.
    """
    from graph_relation import _samples
    h, w = mask.shape
    length = sum(math.dist(a,b) for a,b in zip(coords,coords[1:]))
    if length < 25: return None
    count = min(640,max(32,round(length)))
    points = np.asarray(_samples(coords,count))
    if len(points)<10: return None
    tangents = np.gradient(points,axis=0)
    norms=np.linalg.norm(tangents,axis=1)
    tangents=tangents/np.maximum(norms[:,None],1e-6)
    normals=np.column_stack((-tangents[:,1],tangents[:,0]))
    span=max(10,min(36,round(radius*3)))
    offsets=np.arange(-span,span+1)
    samples=np.rint(points[:,None,:]+normals[:,None,:]*offsets[None,:,None]).astype(int)
    valid=((samples[:,:,0]>=0)&(samples[:,:,0]<w)&(samples[:,:,1]>=0)&(samples[:,:,1]<h))
    bits=np.zeros(valid.shape,dtype=bool)
    bits[valid]=mask[samples[:,:,1][valid],samples[:,:,0][valid]]>0
    widths=[]; balance=[]
    for row in bits:
        choices=[j for j in range(max(0,span-3),min(len(row),span+4)) if row[j]]
        if not choices: widths.append(0);balance.append(0);continue
        center=min(choices,key=lambda j:abs(j-span));left=right=center
        while left>0 and row[left-1]: left-=1
        while right<len(row)-1 and row[right+1]: right+=1
        widths.append(right-left+1)
        balance.append(min(center-left,right-center)/max(1,right-left))
    widths=np.asarray(widths,dtype=float)
    margin=max(4,round(count*max(2*radius,8)/length))
    interior=widths[margin:count-margin]
    positive=interior[interior>0]
    if len(positive)<10: return None
    baseline=float(np.median(positive))
    high=widths>max(baseline+3,baseline*1.5)
    groups=np.flatnonzero(np.diff(np.r_[False,high,False])).reshape(-1,2)
    results=[]
    for start,stop in groups:
        if start<margin or stop>count-margin or not 4<=stop-start<=max(45,count*.35): continue
        peak=start+int(np.argmax(widths[start:stop]));height=widths[peak]
        if height<baseline+7 or balance[peak]<.18: continue
        left,right=peak-start+1,stop-peak
        if right>=5 and left<=max(3,right*.4):
            taper=widths[peak:stop];direction=1
        elif left>=5 and right<=max(3,left*.4):
            taper=widths[start:peak+1][::-1];direction=-1
        else: continue
        if np.mean(np.diff(taper)<=1)<.8 or taper[-1]>height-(height-baseline)*.45: continue
        results.append((direction,.80))
    directions={d for d,_ in results}
    if len(directions)!=1: return None
    return {'orientation':next(iter(directions)),'score':max(s for _,s in results),
            'method':'opencv_bilateral_filled_arrow_taper'}


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
    lines=[] if segments is None else [(float(ax+x1),float(ay+y1),float(bx+x1),float(by+y1))
           for ax,ay,bx,by in np.asarray(segments).reshape(-1,4)[:850]]
    for path in paths:
        a, b = str(path.get("from","")), str(path.get("to",""))
        if a not in vertices or b not in vertices or a == b:
            continue
        coords=[(p[0]*(w-1)-x1,p[1]*(h-1)-y1) for p in path.get('path',[])
                if isinstance(p,(list,tuple)) and len(p)==2]
        profile=_filled_arrow_profile(mask,coords,radius)
        if profile:
            starts_at_a=math.dist((coords[0][0]+x1,coords[0][1]+y1),vertices[a])<=math.dist(
                (coords[-1][0]+x1,coords[-1][1]+y1),vertices[a])
            forward=starts_at_a == (profile['orientation']==1)
            source,target=(a,b) if forward else (b,a)
            path['arrow_candidate']={'from':source,'to':target,'score':profile['score'],
                                     'method':profile['method'],'candidate_only':True}
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
            best = _interior_arrow_score(
                lines, coords, (sx,sy), (tx,ty), radius
            )
            # The near-rim detector remains for endpoint arrowheads.
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
