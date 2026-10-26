"""Conservative pixel-path evidence for node-link diagrams.

Traces are candidates, not confirmed graph edges. A line crossing is not a
mathematical vertex unless the graph detector has a vertex at that position.
"""
from __future__ import annotations

import io
import math

import cv2
import numpy as np
from PIL import Image, ImageOps

from graph_node_geometry import (boundary_distance, circle_geometry, contains_points,
                                 ray_entry, scaled_geometry)
from graph_connector_geometry import outlined_arrow_candidates, same_outlined_instance

MAX_SIDE = 1600
MAX_GRAPHS = 10
MAX_VERTICES = 30
MAX_TRACES_PER_GRAPH = 48
NEIGHBORS = tuple((dy, dx) for dy in range(-2, 3) for dx in range(-2, 3)
                  if 0 < dx * dx + dy * dy <= 5)


def _paper_gray(rgb):
    """Flatten illumination on mid-tone paper; preserve white/dark screens.

    Absolute gray<210 turns brown textbook photos almost entirely into ink.
    Dividing by a smooth illumination field separates dark front-side strokes
    from broad shadows and faint print-through without drawing any new lines.
    """
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    if not 105<=float(np.median(gray))<235:
        return None
    sigma=max(8,min(21,min(gray.shape)/20))
    background=cv2.GaussianBlur(gray,(0,0),sigma)
    return cv2.divide(gray,np.maximum(background,1),scale=255)


def _foreground(rgb):
    """Preserve both dark and saturated colour strokes on light pages."""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    paper=_paper_gray(rgb)
    if paper is not None:
        cutoff,_=cv2.threshold(paper,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
        ink=(paper<=min(180,cutoff)).astype('uint8')*255
    elif float(np.median(gray)) < 105:
        # White/coloured graph strokes on a dark teaching slide.
        ink = ((gray > 155) | ((hsv[:, :, 1] > 80) &
                               (hsv[:, :, 2] > 85))).astype('uint8') * 255
    else:
        ink = ((gray < 210) | ((hsv[:, :, 1] > 80) &
                               (hsv[:, :, 2] < 245))).astype('uint8') * 255
    components, labels, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    for k in range(1, components):
        if stats[k, cv2.CC_STAT_AREA] <= 2:
            ink[labels == k] = 0
    return ink


def _thin(ink):
    if hasattr(cv2, 'ximgproc') and hasattr(cv2.ximgproc, 'thinning'):
        return cv2.ximgproc.thinning(
            ink, thinningType=cv2.ximgproc.THINNING_GUOHALL)
    # OpenCV-only morphological skeleton fallback.
    eroded, result = ink.copy(), np.zeros_like(ink)
    kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    for _ in range(35):
        opened = cv2.morphologyEx(eroded, cv2.MORPH_OPEN, kernel)
        result = cv2.bitwise_or(result, cv2.subtract(eroded, opened))
        eroded = cv2.erode(eroded, kernel)
        if cv2.countNonZero(eroded) == 0:
            break
    return result


def _decode(image_bytes):
    from image_evidence import decode_document_image
    rgb = np.asarray(decode_document_image(image_bytes))
    height, width = rgb.shape[:2]
    scale = min(1.0, MAX_SIDE / max(width, height))
    if scale < 1.0:
        rgb = cv2.resize(
            rgb,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    return rgb


def _vertices(graph, width, height):
    points = []
    for v in graph.get('vertices', []):
        try:
            x, y = float(v['x']), float(v['y'])
            if not (math.isfinite(x) and math.isfinite(y)
                    and 0 <= x <= 1 and 0 <= y <= 1):
                return []
            points.append((str(v['id']),
                           round(x * (width - 1)),
                           round(y * (height - 1))))
        except (ValueError, TypeError, KeyError):
            return []
    ids = [v[0] for v in points]
    if not 1 <= len(points) <= MAX_VERTICES or len(set(ids)) != len(ids):
        return []
    return points


def _unique_seeds(skel, points, vertex_index, radius, *, sectors=24, geometry=None):
    _, x0, y0 = points[vertex_index]
    h, w = skel.shape
    candidates = {}
    outer = max(4, math.ceil(radius) + (10 if geometry else 5))
    if geometry:
        x0, y0 = geometry['center_pixels']
        outer = math.ceil(max(geometry['semiaxes_pixels']))+10
        left, right = max(1, math.floor(x0-outer)), min(w-1, math.ceil(x0+outer+1))
        top, bottom = max(1, math.floor(y0-outer)), min(h-1, math.ceil(y0+outer+1))
        yy, xx = np.nonzero(skel[top:bottom, left:right])
        coords = np.column_stack((xx+left, yy+top))
        distances = boundary_distance(coords, geometry)
        for (x, y), distance in zip(coords, distances):
            if not .3 <= distance <= 9.:
                continue
            band = int(distance > 4.5)
            sector = round((math.atan2(y-y0, x-x0)+math.pi)/(2*math.pi)*sectors) % sectors
            key = (band, sector)
            error = abs(distance-(6. if band else 2.))
            if key not in candidates or error < candidates[key][0]:
                candidates[key] = (error, (int(x), int(y)))
        return [value[1] for _, value in sorted(candidates.items())]
    for y in range(max(1, y0 - outer), min(h - 1, y0 + outer + 1)):
        for x in range(max(1, x0 - outer), min(w - 1, x0 + outer + 1)):
            if skel[y, x] != 255:
                continue
            distance = math.hypot(x - x0, y - y0)
            if not radius - 1 <= distance <= outer:
                continue
            sector = round(
                (math.atan2(y - y0, x - x0) + math.pi)
                / (2 * math.pi) * sectors
            ) % sectors
            err = abs(distance - radius - 1.0)
            if sector not in candidates or err < candidates[sector][0]:
                candidates[sector] = (err, (x, y))
    return [v[1] for _, v in sorted(candidates.items())]


def _follow(skel, points, source_i, start, radius, max_steps, *, node_radii=None, node_geometry=None):
    """Trace ink while favouring tangent continuity at unmarked crossings."""
    source_name, sx, sy = points[source_i]
    source_radius = node_radii.get(source_name, radius) if node_radii else radius
    previous, current = (sx, sy), start
    path, visited = [current], {current}
    turns, ambiguity = 0.0, 0
    max_excursion = 0.0
    for _ in range(max_steps):
        cx, cy = current
        source_distance = math.hypot(cx - sx, cy - sy)
        max_excursion = max(max_excursion, source_distance)
        # A circular node rim is not a self-loop. Only an external ink
        # excursion that returns to the marked node can suggest a loop.
        loop_steps = max(16, (3 if node_radii else 5) * source_radius)
        loop_excursion = (max(source_radius+8, source_radius*1.8)
                          if node_radii else 2.8*source_radius)
        if (len(path) >= loop_steps
                and max_excursion >= loop_excursion
                and source_distance <= source_radius + 4):
            return source_i, path, turns, ambiguity
        arrivals = [
            (math.hypot(cx - vx, cy - vy), i)
            for i, (_, vx, vy) in enumerate(points)
            if i != source_i
        ]
        if node_radii and len(path) >= 3:
            # A large target's rim can be reached before a closer small
            # target's centre. Test each target against its OWN footprint.
            reached = []
            for d, i in arrivals:
                geometry = (node_geometry or {}).get(points[i][0])
                gap = (float(boundary_distance(current, geometry)) if geometry else
                       d-node_radii.get(points[i][0], radius))
                if gap <= 4:
                    reached.append((gap, d, i))
            if reached:
                return min(reached)[2], path, turns, ambiguity
        elif arrivals:
            d, target = min(arrivals)
            if d <= radius + 4 and len(path) >= 3:
                return target, path, turns, ambiguity
        dx, dy = cx - previous[0], cy - previous[1]
        if len(path) >= 4:
            dx, dy = cx - path[-4][0], cy - path[-4][1]
        norm = math.hypot(dx, dy) or 1.0
        options = []
        for oy, ox in NEIGHBORS:
            px, py = cx + ox, cy + oy
            if py <= 0 or px <= 0 or py >= skel.shape[0] - 1 or px >= skel.shape[1] - 1:
                continue
            if (px, py) in visited or skel[py, px] == 0:
                continue
            # NEIGHBORS permits short two-pixel advances to traverse curves.
            # An advance must pass through at least one actual ink pixel:
            # do not teleport over a one-pixel white gap onto a crossing edge.
            if abs(ox) > 1 or abs(oy) > 1:
                ix, iy = (1 if ox > 0 else -1 if ox < 0 else 0), (
                    1 if oy > 0 else -1 if oy < 0 else 0
                )
                intermediate = ((cx+ix,cy+iy), (cx+ix,cy), (cx,cy+iy))
                if not any(
                    0 <= mx < skel.shape[1] and 0 <= my < skel.shape[0]
                    and skel[my,mx] != 0
                    for mx,my in intermediate
                ):
                    continue
            vx, vy = px - cx, py - cy
            cosine = (vx * dx + vy * dy) / (math.hypot(vx, vy) * norm)
            if cosine < -0.1:
                continue
            options.append((cosine, (px, py)))
        if not options:
            break
        options.sort(key=lambda item: item[0], reverse=True)
        best_cos, best = options[0]
        if len(options) >= 2 and options[1][0] > best_cos - 0.15:
            ambiguity += 1
        if best_cos < 0.2:
            ambiguity += 2
        turns += max(0.0, 1 - best_cos)
        previous, current = current, best
        visited.add(current)
        path.append(current)
    return None, path, turns, ambiguity


def _sample_path(path, width, height, *, max_error=None):
    if max_error is not None and len(path)>10:
        # Candidate-only option: ten uniform samples cut across thin exterior
        # arcs and then fail the independent ink check. Keep pixel geometry.
        points=np.asarray(path,dtype=np.float32).reshape((-1,1,2))
        selected=cv2.approxPolyDP(points,max_error,False).reshape((-1,2)).tolist()
        if len(selected)>128:return []  # Abstain instead of erasing geometry.
    else:selected = (
        path if len(path) <= 10
        else [path[round(i * (len(path) - 1) / 9)] for i in range(10)]
    )
    return [
        [round(x / max(width - 1, 1), 4),
         round(y / max(height - 1, 1), 4)]
        for x, y in selected
    ]



def _route_signature(candidate, pointmap, width, height):
    """Nine arc-length samples, oriented by the source vertex."""
    path = candidate.get("path") or []
    if len(path) < 2: return []
    try:
        coords = [(float(q[0])*(width-1), float(q[1])*(height-1)) for q in path]
    except (TypeError, ValueError, IndexError):
        return []
    source = pointmap.get(str(candidate.get("from")))
    if source is None: return []
    if math.dist(coords[0],source) > math.dist(coords[-1],source): coords.reverse()
    lengths = [0.0]
    for a,b in zip(coords,coords[1:]):
        lengths.append(lengths[-1]+math.dist(a,b))
    if lengths[-1]<4: return []
    samples=[]
    for t in [i/10 for i in range(1,10)]:
        distance=t*lengths[-1]
        for i in range(1,len(lengths)):
            if lengths[i]>=distance:
                ratio=(distance-lengths[i-1])/max(1e-5,lengths[i]-lengths[i-1])
                samples.append((
                    coords[i-1][0]*(1-ratio)+coords[i][0]*ratio,
                    coords[i-1][1]*(1-ratio)+coords[i][1]*ratio
                ))
                break
    return samples


def _route_polyline_pixels(candidate, width, height):
    try:
        return [(float(p[0])*(width-1), float(p[1])*(height-1))
                for p in candidate.get('path', [])]
    except (TypeError, ValueError, IndexError):
        return []


def _point_polyline_distance(point, line):
    best = float('inf')
    for a, b in zip(line, line[1:]):
        dx, dy = b[0]-a[0], b[1]-a[1]
        div = dx*dx+dy*dy
        if div <= 1e-6:
            continue
        t = max(0.0,min(1.0,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/div))
        best=min(best, math.hypot(point[0]-a[0]-t*dx,point[1]-a[1]-t*dy))
    return best


def _same_ink_route(candidate,existing,pointmap,width,height,radius,*,ink=None,offset=(0,0),node_geometry=None):
    """Deduplicate reverse/partial traces; do not merge nearby parallel strokes.

    A Hough segment may cover only the middle 70% of a skeleton trace. That
    is one stroke, not two parallel edges; normalized-length comparison alone
    misclassifies it as a second route. Conversely two genuine curved arcs
    may be close at their ends but have separate ink through the middle.
    """
    first_meta=candidate.get('connector_evidence') or {}
    second_meta=existing.get('connector_evidence') or {}
    first_outline=first_meta.get('kind')=='outlined_arrow'
    second_outline=second_meta.get('kind')=='outlined_arrow'
    if first_outline or second_outline:
        if first_outline and second_outline:
            return (same_outlined_instance(first_meta,second_meta,ink,(width,height),offset=offset)
                    if ink is not None else False)
        else:
            meta,other=(first_meta,existing) if first_outline else (second_meta,candidate)
            for side in range(2):
                wall=meta.get('shaft_boundaries',[])
                shoulders=meta.get('shoulders',[])
                flanks=meta.get('head_flanks',[])
                if min(len(wall),len(shoulders),len(flanks))!=2:return False
                path=[wall[side][0],wall[side][1],shoulders[side][1],flanks[side][1]]
                constituent={'from':candidate['from'],'to':candidate['to'],'path':path}
                if _same_ink_route(other,constituent,pointmap,width,height,radius,
                                   ink=ink,offset=offset,node_geometry=node_geometry):
                    return True
            return False
    if ink is not None:
        # Route identity is measured outside node bodies. Equal endpoints or
        # two nearby centrelines are not enough: a white corridor preserves
        # independent parallel arcs, even at small raster separation.
        def samples(entry):
            points=np.asarray(_route_polyline_pixels(entry,width,height),float)
            if len(points)<2:return np.empty((0,2))
            lengths=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(points,axis=0),axis=1))]
            if lengths[-1]<2:return np.empty((0,2))
            values=np.linspace(0.,lengths[-1],128)
            route=np.stack([np.interp(values,lengths,points[:,axis]) for axis in range(2)],axis=1)
            if node_geometry:
                keep=np.ones(len(route),bool)
                for name in {entry.get('from'),entry.get('to')}:
                    if name in node_geometry:
                        keep &= ~contains_points(route,node_geometry[name],margin=2.)
                route=route[keep]
            else:
                route=route[10:-10]
            route=route-np.asarray(offset)
            # Canny/Hough centres may be on a white neighbour of the same
            # ridge. Project only a tiny offset; actual ink pixels stay put.
            projected=[]
            for point in route:
                x,y=np.rint(point).astype(int)
                if 0<=x<ink.shape[1] and 0<=y<ink.shape[0] and ink[y,x]:
                    projected.append(point);continue
                lo_x,hi_x=max(0,x-2),min(ink.shape[1],x+3)
                lo_y,hi_y=max(0,y-2),min(ink.shape[0],y+3)
                yy,xx=np.nonzero(ink[lo_y:hi_y,lo_x:hi_x])
                if len(xx):
                    neighbours=np.column_stack([xx+lo_x,yy+lo_y])
                    nearest=neighbours[np.argmin(np.linalg.norm(neighbours-point,axis=1))]
                    projected.append(nearest if np.linalg.norm(nearest-point)<=2.4 else point)
                else:projected.append(point)
            return np.asarray(projected)
        a,b=samples(candidate),samples(existing)
        if min(len(a),len(b))<6:return False
        distances=np.linalg.norm(a[:,None,:]-b[None,:,:],axis=2)
        def corridor(source,target,dist):
            nearest=target[np.argmin(dist,axis=1)]
            bridge=source[:,None,:]+(nearest-source)[:,None,:]*np.linspace(0,1,13)[None,:,None]
            xy=np.rint(bridge).astype(int)
            valid=((xy[:,:,0]>=0)&(xy[:,:,0]<ink.shape[1])&
                   (xy[:,:,1]>=0)&(xy[:,:,1]<ink.shape[0]))
            x=np.clip(xy[:,:,0],0,ink.shape[1]-1);y=np.clip(xy[:,:,1],0,ink.shape[0]-1)
            fraction=np.mean((ink[y,x]>0)&valid,axis=1)
            return float(np.mean((np.min(dist,axis=1)<=12.)&(fraction>=.90)))
        forward,backward=corridor(a,b,distances),corridor(b,a,distances.T)
        return min(forward,backward)>=.88
    a=_route_signature(candidate,pointmap,width,height)
    b=_route_signature(existing,pointmap,width,height)
    gap=max(2.4,min(4.0,radius*0.48))
    if len(a)==len(b)==9:
        inner=[math.dist(x,y) for x,y in zip(a[2:7],b[2:7])]
        if max(inner)<=gap and sum(inner)/len(inner)<=gap*.75:
            return True
        if ink is not None and max(inner)<=max(12.,radius*1.7):
            # Arrowhead wings and thick node rims can displace a skeleton a
            # few pixels from the straight detector. They are one ink ridge.
            # Genuine close parallel strokes must retain a white corridor at
            # multiple interior cross-sections, not just near their endpoints.
            separated=0; inspected=0
            for q,z in zip(a[2:7],b[2:7]):
                distance=math.dist(q,z)
                if distance<2.5:continue
                samples=np.rint(np.linspace(q,z,max(5,round(distance*2)))).astype(int)
                samples[:,0]-=offset[0];samples[:,1]-=offset[1]
                valid=((samples[:,0]>=0)&(samples[:,0]<ink.shape[1])&
                       (samples[:,1]>=0)&(samples[:,1]<ink.shape[0]))
                if not valid.all():continue
                row=ink[samples[:,1],samples[:,0]]>0
                inspected+=1
                if float((~row).mean())>.40:separated+=1
            if inspected>=3 and separated<2:return True
    first=_route_polyline_pixels(candidate,width,height)
    second=_route_polyline_pixels(existing,width,height)
    if len(first)<2 or len(second)<2:
        return False
    def route_length(route):
        return sum(math.dist(x,y) for x,y in zip(route,route[1:]))
    short,long=sorted((first,second),key=route_length)
    distance=route_length(short)
    start=pointmap.get(str(candidate.get('from')))
    end=pointmap.get(str(candidate.get('to')))
    if start is None or end is None or distance < .55*math.dist(start,end):
        return False
    # Require a substantial common ink corridor, not shared endpoints.
    hits=0
    samples=0
    for a,b in zip(short,short[1:]):
        for t in (.25,.5,.75):
            q=(a[0]*(1-t)+b[0]*t,a[1]*(1-t)+b[1]*t)
            hits+=_point_polyline_distance(q,long)<=gap
            samples+=1
    return samples>=3 and hits/samples>=.88


def _straight_stroke_candidates(rgb, local, x_off, y_off, radius, full_w, full_h,*,ink_mask=None,node_radii=None):
    """Independently propose only high-coverage straight strokes.

    A crossing alone cannot satisfy the coverage test. A confirmed node
    between two endpoints blocks an apparent long edge.
    """
    ink = (_foreground(rgb) if ink_mask is None else ink_mask) > 0
    height, width = ink.shape
    candidates = []
    for i in range(len(local)):
        for j in range(i + 1, len(local)):
            _, ax, ay = local[i]
            _, bx, by = local[j]
            dx, dy = bx - ax, by - ay
            length = math.hypot(dx, dy)
            if length < 16:
                continue
            if node_radii:
                start = (node_radii.get(local[i][0], radius)+2)/length
                end = 1-(node_radii.get(local[j][0], radius)+2)/length
                if (end-start)*length < 6:
                    continue
                visible_length = (end-start)*length
            else:
                start, end, visible_length = .09, .91, length
            crossing_node = False
            for k, (name, px, py) in enumerate(local):
                if k in (i, j):
                    continue
                t = ((px - ax) * dx + (py - ay) * dy) / (length * length)
                side = abs((px - ax) * dy - (py - ay) * dx) / length
                crossing_radius = node_radii.get(name, radius) if node_radii else radius
                lo, hi = (start, end) if node_radii else (.08, .92)
                if lo < t < hi and side <= crossing_radius * 0.8:
                    crossing_node = True
                    break
            if crossing_node:
                continue
            samples = max(15, min(250, round(visible_length * 0.9)))
            hits = 0
            pattern = []
            offsets=(-3.0,-1.5,0.,1.5,3.0)
            offset_hits=[0]*len(offsets)
            missing_run = max_missing_run = 0
            for step in range(samples):
                t = (start + (end-start) * (step + 0.5) / samples if node_radii
                     else .09 + .82 * (step + .5) / samples)
                mx, my = ax + t * dx, ay + t * dy
                ux, uy = -dy / length, dx / length
                found = False
                for offset_index,offset in enumerate(offsets):
                    x, y = round(mx + offset * ux), round(my + offset * uy)
                    if 0 <= x < width and 0 <= y < height and ink[y, x]:
                        found = True
                        offset_hits[offset_index]+=1
                hits += int(found)
                pattern.append(found)
                missing_run = 0 if found else missing_run + 1
                max_missing_run = max(max_missing_run, missing_run)
            coverage = hits / samples
            # Average ink coverage alone can connect unrelated aligned lines.
            # A long missing segment is evidence against an actual edge.
            largest_gap_px = max_missing_run * visible_length / samples
            continuous = coverage >= .83 and largest_gap_px <= max(6,min(16,visible_length*.045))
            # Dashed paths need repeated bounded gaps, not one long white gap
            # between unrelated collinear strokes. Still only a candidate.
            runs=[]
            for hit in pattern:
                if runs and runs[-1][0] == hit: runs[-1][1] += 1
                else: runs.append([hit,1])
            gaps=[n for hit,n in runs[1:-1] if not hit]
            # A port crop can leave a short residual end gap. Complete
            # interior intervals establish cadence; the maximum gap remains
            # bounded so unrelated collinear fragments do not become edges.
            middle_gaps = gaps[1:-1] if len(gaps) >= 5 else gaps
            typical_gap = float(np.median(middle_gaps)) if middle_gaps else 0.
            consistent = (sum(.4*typical_gap <= n <= 2.5*typical_gap for n in middle_gaps)
                          >= max(3, math.ceil(len(middle_gaps)*.8))) if typical_gap else False
            dashed = (.40 <= coverage < .90 and len(gaps)>=3 and consistent and
                      max(gaps)<=max(2., 2.5*typical_gap) and
                      largest_gap_px<=min(20,visible_length*.13))
            if not continuous and not dashed:
                continue
            best_offset=max(range(len(offsets)),key=lambda k:(offset_hits[k],-abs(offsets[k])))
            shift=(offsets[best_offset] if node_radii and
                   offset_hits[best_offset]-offset_hits[2]>=samples*.12 else 0.)
            route_coverage=offset_hits[best_offset]/samples if node_radii else coverage
            proposal_score=(min(coverage,route_coverage+.02) if continuous else min(.80,coverage+.18))
            start_point=(ax+shift*ux,ay+shift*uy)
            end_point=(bx+shift*ux,by+shift*uy)
            candidates.append({
                'from': local[i][0], 'to': local[j][0],
                'path': [[round((start_point[0] + x_off) / max(full_w - 1, 1), 4),
                          round((start_point[1] + y_off) / max(full_h - 1, 1), 4)],
                         [round((end_point[0] + x_off) / max(full_w - 1, 1), 4),
                          round((end_point[1] + y_off) / max(full_h - 1, 1), 4)]],
                'pixel_length': round(length),
                'score': round(proposal_score, 3),
                'style': 'solid' if continuous else 'dashed',
                'needs_review': True,
                'method': 'opencv_straight_line_coverage',
                'connector_evidence': {'kind': 'stroke_chain',
                                       'gap_pattern': 'repeated_bounded' if dashed and not continuous else 'continuous',
                                       'complete_interior_gap_count': len(middle_gaps),
                                       'observed_ridge_offset_pixels': shift,
                                       'proposal_only': True},
            })
    return candidates


def _hough_endpoint_candidates(rgb, local, x_off, y_off, radius, full_w, full_h,*,gray_cutoff=216,ink_mask=None,node_radii=None,node_geometry=None):
    """Match real visible Hough stroke endpoints to marked node *rims*.

    Center-to-center coverage fails for lines attached off-center to circles.
    This function never manufactures vertices or certified graph edges.
    """
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    paper=_paper_gray(rgb)
    if ink_mask is not None:
        mask=ink_mask
    elif paper is not None:
        mask=_foreground(rgb)
    elif float(np.median(gray)) < 105:
        mask = _foreground(rgb)
    else:
        _, mask = cv2.threshold(gray, gray_cutoff, 255, cv2.THRESH_BINARY_INV)
    edges = cv2.Canny(mask, 55, 145)
    segments = cv2.HoughLinesP(edges, 1, math.pi / 720, threshold=18,
                               minLineLength=24, maxLineGap=7)
    if segments is None:
        return []
    distance_to_ink = cv2.distanceTransform(np.uint8(mask == 0), cv2.DIST_L2, 3)
    output = []
    for x1, y1, x2, y2 in np.asarray(segments).reshape(-1, 4)[:400]:
        length = math.hypot(float(x2-x1), float(y2-y1))
        if length < (24 if node_radii else max(24, radius * 2.5)):
            continue
        nearest = []
        route_ends = []
        axis = np.asarray([float(x2-x1), float(y2-y1)])/length
        for endpoint_index, (xx, yy) in enumerate(((x1, y1), (x2, y2))):
            if node_radii:
                choices = []
                for i, (name, vx, vy) in enumerate(local):
                    r = node_radii.get(name, radius)
                    distance = math.hypot(float(xx)-vx, float(yy)-vy)
                    geometry = (node_geometry or {}).get(name) or circle_geometry((vx, vy), r)
                    port = ray_entry((xx, yy), axis*(-1 if endpoint_index == 0 else 1), geometry, margin=2.)
                    if port is None:
                        continue
                    gap = float(np.linalg.norm(port-[xx, yy]))
                    if gap > max(12., min(32., r*2.+8.)):
                        continue
                    # A line body may end at an arrowhead base. Associate its
                    # end with a node only through an independently inked
                    # continuation and a ray/footprint intersection.
                    bridge = np.rint(np.linspace((xx, yy), port, max(4, math.ceil(gap)))).astype(int)
                    valid = ((bridge[:, 0] >= 0) & (bridge[:, 0] < mask.shape[1]) &
                             (bridge[:, 1] >= 0) & (bridge[:, 1] < mask.shape[0]))
                    if not valid.all() or np.mean(distance_to_ink[bridge[:, 1], bridge[:, 0]] <= 2.4) < .75:
                        continue
                    choices.append((gap, distance, i, port))
                if not choices:
                    break
                _, dist, number, port = min(choices, key=lambda row: row[:3])
                route_ends.append(port)
            else:
                dist, number = min((math.hypot(float(xx)-vx, float(yy)-vy), i)
                                   for i, (_, vx, vy) in enumerate(local))
                route_ends.append(np.asarray([xx, yy]))
            nearest.append((dist, number))
        if len(nearest) != 2:
            continue
        (d1, i), (d2, j) = nearest
        if i == j or (not node_radii and max(d1, d2) > max(9.0, radius * 1.45)):
            continue
        center_distance = math.hypot(local[i][1]-local[j][1],local[i][2]-local[j][2])
        r1 = node_radii.get(local[i][0], radius) if node_radii else radius
        r2 = node_radii.get(local[j][0], radius) if node_radii else radius
        visible_distance = max(12., center_distance-r1-r2) if node_radii else center_distance
        if length < 0.63 * visible_distance:
            continue
        crosses_node = False
        for k,(name,vx,vy) in enumerate(local):
            if k in (i,j):
                continue
            projection = ((vx-x1)*(x2-x1)+(vy-y1)*(y2-y1))/(length*length)
            distance = abs((vx-x1)*(y2-y1)-(vy-y1)*(x2-x1))/length
            crossing_radius = node_radii.get(name, radius) if node_radii else radius
            if 0.08 < projection < 0.92 and distance < crossing_radius*.83:
                crosses_node = True
                break
        if crosses_node:
            continue
        a,b=sorted((i,j))
        endpoint_error = abs(d1-r1)+abs(d2-r2) if node_radii else d1+d2
        confidence = max(0.1, 0.92 - 0.20*endpoint_error/max(r1+r2,1))
        output.append({
            'from':local[a][0], 'to':local[b][0],
            'path':[[round((float(p[0])+x_off)/max(full_w-1,1),4),
                     round((float(p[1])+y_off)/max(full_h-1,1),4)]
                    for p in (route_ends[0], (x1,y1), (x2,y2), route_ends[1])],
            'pixel_length':round(length), 'score':round(confidence,3),
            'needs_review':True, 'method':'opencv_hough_rim_endpoint',
            'connector_evidence': {'kind': 'stroke_chain', 'attachment': 'ink_to_footprint_ray',
                                   'proposal_only': True},
        })
    return output


def _corridor_hits(ink, xs, ys, ux, uy):
    """Out-of-image corridor samples contain no evidence (never wrap/clip)."""
    height, width = ink.shape
    hits = np.zeros(xs.shape, dtype=bool)
    for off in (-2., -1., 0., 1., 2.):
        xx = np.rint(xs + off * ux).astype(int)
        yy = np.rint(ys + off * uy).astype(int)
        valid = (xx >= 0) & (xx < width) & (yy >= 0) & (yy < height)
        hits[valid] |= ink[yy[valid], xx[valid]]
    return hits


def _curve_pattern(ink, xs, ys, outside, ux, uy):
    hits=_corridor_hits(ink,xs[outside],ys[outside],ux,uy)
    coverage=float(hits.mean())
    missing=np.flatnonzero(np.r_[True,hits,True])
    largest_run=int(max(np.diff(missing)-1,default=0))
    continuous=(coverage>=.87 and min(float(chunk.mean()) for chunk in np.array_split(hits,5))>=.75
                and largest_run<=max(5,round(.04*len(xs))))
    runs=[]
    for hit in hits:
        if runs and runs[-1][0]==bool(hit):runs[-1][1]+=1
        else:runs.append([bool(hit),1])
    gaps=[n for hit,n in runs[1:-1] if not hit]
    middle=gaps[1:-1] if len(gaps)>=5 else gaps
    typical=float(np.median(middle)) if middle else 0.
    curve_length=float(np.sum(np.hypot(np.diff(xs[outside]),np.diff(ys[outside]))))
    gap_pixels=largest_run*curve_length/max(1,len(hits))
    dashed=(.40<=coverage<.90 and len(gaps)>=3 and typical>0 and
            sum(.4*typical<=n<=2.5*typical for n in middle)>=max(3,math.ceil(len(middle)*.8)) and
            max(gaps)<=max(2.,2.5*typical) and gap_pixels<=min(20.,curve_length*.13) and
            min(float(chunk.mean()) for chunk in np.array_split(hits,5))>=.25)
    return coverage,continuous,dashed,middle


def _curved_stroke_candidates(rgb, local, x_off, y_off, radius, full_w, full_h,*,ink_mask=None,node_radii=None,node_geometry=None,diagnostics=None):
    """Detect an independently ink-backed arch between already known vertices.

    A contour may be almost semicircular; a straight Hough line has no chance
    of recovering it. Test semicircle, sine and quadratic arc profiles with
    both bend signs. This contributes evidence, NOT an accepted graph edge.
    """
    if len(local) > 14:
        if diagnostics is not None:
            diagnostics.append({'kind':'curve_template_node_limit','nodes':len(local),'limit':14,'skipped':True})
        return []
    ink = ((_foreground(rgb) if ink_mask is None else ink_mask) > 0)
    height, width = ink.shape
    output = []
    refinement_counts=[]
    capped_route_pairs=[]
    # A coarse amplitude grid may change phase with marker size. Rank a
    # bounded local fit by the actual ridge, not by a dilated corridor that
    # can score 1.0 while the returned centreline still misses the stroke.
    outside_distance=(cv2.distanceTransform(np.uint8(~ink),cv2.DIST_L2,3) if node_radii else None)
    inside_distance=(cv2.distanceTransform(np.uint8(ink),cv2.DIST_L2,3) if node_radii else None)

    def independently_separated_ink(first, second):
        # Two fitted curves separated by only a few pixels may represent
        # the SAME thick ink stroke. Preserve both only when a white corridor
        # genuinely separates two dark ridges at several interior positions.
        separated = 0
        for k in (3, 4, 5, 6):
            qa, qb = first['path'][k], second['path'][k]
            x1 = float(qa[0])*(full_w-1)-x_off
            y1 = float(qa[1])*(full_h-1)-y_off
            x2 = float(qb[0])*(full_w-1)-x_off
            y2 = float(qb[1])*(full_h-1)-y_off
            gap = math.hypot(x2-x1,y2-y1)
            if gap < 4.0:
                continue
            samples = []
            for t in np.linspace(0.,1.,max(7,round(gap*2))):
                xx,yy = round(x1+t*(x2-x1)),round(y1+t*(y2-y1))
                if not (0<=xx<width and 0<=yy<height):
                    break
                samples.append(bool(ink[yy,xx]))
            if len(samples)<7 or not samples[0] or not samples[-1]:
                continue
            longest=0
            streak=0
            for dark in samples:
                streak=0 if dark else streak+1
                longest=max(longest,streak)
            separated += int(longest>=2)
        return separated>=2

    for i in range(len(local)):
        for j in range(i+1, len(local)):
            _, ax, ay = local[i]
            _, bx, by = local[j]
            dx, dy = bx-ax, by-ay
            distance = math.hypot(dx, dy)
            if distance < max(45.0, 5.0*radius):
                continue
            first_radius = node_radii.get(local[i][0], radius) if node_radii else radius
            second_radius = node_radii.get(local[j][0], radius) if node_radii else radius
            ux, uy = -dy/distance, dx/distance
            # No candidate should be inferred if the supposed arc goes
            # through a *marked* intermediate vertex.
            ts = np.linspace(.045,.955,min(180,max(52,round(distance*.85))))
            base_x = ax + ts*dx
            base_y = ay + ts*dy
            best_routes = []
            refinement_count=0
            for sign in (-1,1):
                max_bend = min(.72*distance, max(width,height)*.63)
                step = max(3., min(7.,distance*.027))
                minimum_bend=(max(3.,min(radius,first_radius,second_radius)*.8,.045*distance)
                              if node_radii else max(2.0*radius,.115*distance))
                amplitudes = np.arange(minimum_bend,
                                       max_bend+step/2,step)
                for profile in ("elliptical", "quadratic", "sine"):
                    if profile == "elliptical":
                        shape = np.sqrt(np.maximum(0.,1.-(2.*ts-1.)**2))
                    elif profile == "quadratic":
                        shape = 4.*ts*(1.-ts)
                    else:
                        shape = np.sin(np.pi*ts)
                    for amplitude in amplitudes:
                        bend = sign * amplitude * shape
                        xs = base_x + ux*bend
                        ys = base_y + uy*bend
                        if (xs.min()<2 or ys.min()<2 or
                                xs.max()>=width-2 or ys.max()>=height-2):
                            continue
                        outside = (((xs-ax)**2+(ys-ay)**2 > (first_radius+2)**2) &
                                   ((xs-bx)**2+(ys-by)**2 > (second_radius+2)**2)
                                   if node_radii else np.ones(len(ts), bool))
                        if np.count_nonzero(outside) < 12:
                            continue
                        forbidden = False
                        for k,(name,vx,vy) in enumerate(local):
                            if k in (i,j):continue
                            d2 = (xs-vx)**2+(ys-vy)**2
                            crossing_radius = node_radii.get(name, radius) if node_radii else radius
                            if np.any(d2[(ts>.12)&(ts<.88)&outside]<(crossing_radius*.8)**2):
                                forbidden=True
                                break
                        if forbidden:
                            continue
                        coverage,continuous,dashed,middle=_curve_pattern(ink,xs,ys,outside,ux,uy)
                        if not continuous and not dashed:
                            if not node_radii or refinement_count>=24:
                                continue
                            # This only seeds a local fit. A thin rotated arc
                            # can lie halfway between coarse amplitudes and
                            # miss the narrow corridor entirely. Every fitted
                            # result must still pass the normal pattern gate.
                            xx=np.rint(xs[outside]).astype(int);yy=np.rint(ys[outside]).astype(int)
                            nearby=outside_distance[yy,xx]<=step/2+1.
                            if (float(nearby.mean())<.92 or
                                    min(float(chunk.mean()) for chunk in np.array_split(nearby,5))<.80):
                                continue
                        refinement={}
                        direct_coverage=coverage
                        if node_radii:
                            original_amplitude=amplitude
                            trials=(np.linspace(max(0.,amplitude-step/2),min(max_bend,amplitude+step/2),9)
                                    if refinement_count<24 else [amplitude])
                            limited=refinement_count>=24
                            refinement_count+=not limited
                            best_fit=None
                            for trial in trials:
                                tx=base_x+ux*sign*trial*shape;ty=base_y+uy*sign*trial*shape
                                if tx.min()<2 or ty.min()<2 or tx.max()>=width-2 or ty.max()>=height-2:continue
                                visible=(((tx-ax)**2+(ty-ay)**2>(first_radius+2)**2)&
                                         ((tx-bx)**2+(ty-by)**2>(second_radius+2)**2))
                                if np.count_nonzero(visible)<12:continue
                                if any(np.any(((tx-vx)**2+(ty-vy)**2)[(ts>.12)&(ts<.88)&visible]<
                                              (node_radii.get(name,radius)*.8)**2)
                                       for k,(name,vx,vy) in enumerate(local) if k not in (i,j)):continue
                                pattern=_curve_pattern(ink,tx,ty,visible,ux,uy)
                                if not pattern[1] and not pattern[2]:continue
                                xx=np.rint(tx[visible]).astype(int);yy=np.rint(ty[visible]).astype(int)
                                distances=outside_distance[yy,xx]
                                cost=float(np.mean(np.minimum(distances,3.))-.18*np.mean(np.minimum(inside_distance[yy,xx],3.)))
                                if best_fit is None or cost<best_fit[0]:
                                    best_fit=(cost,float(trial),pattern,float(np.mean(distances<=.96)))
                            if best_fit is not None:
                                fit_cost,amplitude,pattern,direct_coverage=best_fit
                                coverage,continuous,dashed,middle=pattern
                                refinement={'initial_bend_pixels':round(sign*original_amplitude,3),
                                            'fitted_bend_pixels':round(sign*amplitude,3),
                                            'ridge_coverage':round(direct_coverage,4),
                                            'fit_cost':round(fit_cost,4),'trial_cap':9,
                                            'pair_refinement_cap':24,'refinement_limited':limited}
                        if not continuous and not dashed:
                            continue
                        # Use a shorter initial point to anchor near a node
                        # rim, preserving the actually observed stroke shape.
                        path=[]
                        for t in np.linspace(0.025,.975,10):
                            if profile == "elliptical":
                                h=math.sqrt(max(0.,1.-(2.*t-1.)**2))
                            elif profile == "quadratic":
                                h=4.*t*(1.-t)
                            else:
                                h=math.sin(math.pi*t)
                            x=ax+t*dx+ux*sign*amplitude*h+x_off
                            y=ay+t*dy+uy*sign*amplitude*h+y_off
                            path.append([round(x/max(full_w-1,1),4),
                                         round(y/max(full_h-1,1),4)])
                        best_routes.append({
                            'from':local[i][0], 'to':local[j][0],
                            'path':path,'pixel_length':round(distance*(1+amplitude/distance)),
                            'score':round(direct_coverage if continuous else min(.80,direct_coverage+.18),3),'needs_review':True,
                            'method':'opencv_curved_ink_template',
                            'style':'solid' if continuous else 'dashed',
                            'connector_evidence': {'kind':'stroke_chain','gap_pattern':'continuous' if continuous else 'repeated_bounded',
                                                   'complete_interior_gap_count':len(middle),'proposal_only':True,
                                                   **({'curve_fit':refinement} if refinement else {})},
                            'bend':round(sign*amplitude,1),
                        })
            # Keep distinct ink corridors (parallel arches), not redundant
            # profile fits of a single arc.
            selected=[]
            for candidate in sorted(best_routes,key=lambda z:-z['score']):
                if not any(
                        (abs(candidate['bend']-old['bend'])<
                         max(5.,radius*.72) and
                         not independently_separated_ink(candidate,old))
                        or _same_ink_route(candidate,old,{
                            local[i][0]:(ax+x_off,ay+y_off),
                            local[j][0]:(bx+x_off,by+y_off)},
                            full_w,full_h,radius,ink=ink,offset=(x_off,y_off),
                            node_geometry=node_geometry)
                        for old in selected):
                    selected.append(candidate)
                if len(selected)>=4:
                    capped_route_pairs.append([local[i][0],local[j][0]])
                    break
            refinement_counts.append({'endpoints':[local[i][0],local[j][0]],'count':refinement_count})
            output.extend(selected)
    if diagnostics is not None and node_radii:
        diagnostics.append({'kind':'curve_refinement_budget','total_refined_hypotheses':sum(row['count'] for row in refinement_counts),
                            'maximum_pair_refinements':max((row['count'] for row in refinement_counts),default=0),
                            'pair_refinement_limit':24,'amplitude_trial_limit':9,
                            'refinement_limit_reached_pairs':[row['endpoints'] for row in refinement_counts if row['count']>=24],
                            'pair_route_limit':4,'route_limit_reached_pairs':capped_route_pairs})
    return output


def _graph_candidates(rgb, graph, *, dense_paths=False,consistent_paper=False,marker_scale=1.,diagnostics=None):
    h, w = rgb.shape[:2]
    points = _vertices(graph, w, h)
    if not points:
        return []
    nearest = [
        min((math.hypot(x - a, y - b)
            for j, (_, a, b) in enumerate(points) if j != i), default=80.0)
        for i, (_, x, y) in enumerate(points)
    ]
    median_sep = float(np.median(nearest))
    radius = max(3, min(13, round(median_sep * 0.12)))
    # Explicit evidence contract: radii are measured in the supplied image's
    # pixels, then scaled exactly once if _decode reduced that image. A missing
    # mapping retains the legacy path; no native-recovery flag is fabricated.
    measured_radii = {}
    measured_geometry = {}
    supplied_radii = graph.get('measured_marker_radii')
    if isinstance(supplied_radii, dict):
        for name, _, _ in points:
            value = supplied_radii.get(name)
            if (type(value) in (int, float) and math.isfinite(value)
                    and value > 0 and math.isfinite(marker_scale) and marker_scale > 0):
                scaled = value*marker_scale
                if scaled <= max(w, h):
                    measured_radii[name] = scaled
    supplied_geometry = graph.get('measured_marker_geometry')
    if isinstance(supplied_geometry, dict):
        for name, _, _ in points:
            entry = supplied_geometry.get(name)
            if not isinstance(entry, dict):
                continue
            try:
                centre = np.asarray(entry['center_pixels'], float)
                axes = np.asarray(entry['semiaxes_pixels'], float)
                values = np.r_[centre, axes, float(entry['angle_degrees']), float(entry['radius_pixels'])]
                if (centre.shape != (2,) or axes.shape != (2,) or not np.isfinite(values).all()
                        or min(axes) <= 0 or max(axes)*marker_scale > max(w,h)):
                    continue
                measured_geometry[name] = scaled_geometry(entry, marker_scale)
                measured_radii[name] = measured_geometry[name]['radius_pixels']
            except (TypeError, ValueError, KeyError):
                continue
    proof={p['vertex']:p for p in graph.get('node_position_evidence',[])}
    native_radii={}
    if graph.get('node_review',{}).get('native_disk_core_size_recovery') and len(proof)==len(points):
        native_radii={key:p['radius_pixels']*marker_scale for key,p in proof.items()}
        radius=round(float(np.median(list(native_radii.values()))))
    if (graph.get('directed') is False and graph.get('weighted') is False and len(points)>=4
            and len(proof)==len(points) and all(p.get('marker_profile')=='native_hollow_size_consensus'
            and p.get('radius_pixels',0)*marker_scale>=15 for p in proof.values())):
        from graph_qwen_ring_markers import native_rim_profile
        native_ink=_foreground(rgb)
        for node in graph['vertices']:
            p=proof[node['id']];r=p['radius_pixels']*marker_scale
            rim=native_rim_profile(native_ink,{**node,'radius_pixels':r})
            if rim and rim['relative_median_deviation']<=.15 and r<=rim['radius_pixels']<=r*2:
                p['native_external_rim']=rim;p['radius_pixels']=rim['radius_pixels']/marker_scale
                r=rim['radius_pixels']
            native_radii[node['id']]=r
        radius=round(float(np.median(list(native_radii.values()))))
        graph.setdefault('node_review',{})['native_full_marker_rims']=True
    # Small crops clipped real outer arcs and self-loops. Retain enough
    # space beyond the vertex hull without scanning the entire text page.
    margin = max(34, min(120, round(median_sep * 0.62)))
    min_x = max(0, min(p[1] for p in points) - margin)
    max_x = min(w, max(p[1] for p in points) + margin + 1)
    min_y = max(0, min(p[2] for p in points) - margin)
    max_y = min(h, max(p[2] for p in points) + margin + 1)
    # Explicit figure bounds retain outer arcs beyond the vertex hull. They
    # must contain all known vertices; components are not used for splitting.
    box = graph.get('bbox')
    if isinstance(box, list) and len(box) == 4:
        try:
            a,b,c,d = map(float,box)
            if (0 <= a < c <= 1 and 0 <= b < d <= 1 and
                    all(a <= x/max(w-1,1) <= c and b <= y/max(h-1,1) <= d for _,x,y in points)):
                min_x,min_y,max_x,max_y = int(a*w),int(b*h),min(w,math.ceil(c*w)),min(h,math.ceil(d*h))
        except (TypeError,ValueError):
            pass
    if min(max_x - min_x, max_y - min_y) < 14:
        return []
    photo_mask=(_foreground(rgb)[min_y:max_y,min_x:max_x]
                if consistent_paper and _paper_gray(rgb) is not None else None)
    ink_mask=photo_mask if photo_mask is not None else _foreground(rgb[min_y:max_y, min_x:max_x])
    skel = _thin(ink_mask)
    local = [(label, x - min_x, y - min_y) for label, x, y in points]
    local_geometry = {name: scaled_geometry(value, 1., offset=(min_x,min_y))
                      for name, value in measured_geometry.items()}
    # Erase only already-detected vertex interiors, not line crossings.
    for name, x, y in local:
        if name in local_geometry:
            geometry = local_geometry[name]
            cx,cy = geometry['center_pixels']
            reach = max(geometry['semiaxes_pixels'])+3
            left,top = max(0,math.floor(cx-reach)),max(0,math.floor(cy-reach))
            right,bottom = min(skel.shape[1],math.ceil(cx+reach+1)),min(skel.shape[0],math.ceil(cy+reach+1))
            yy,xx=np.mgrid[top:bottom,left:right]
            erase=contains_points(np.stack([xx,yy],axis=-1),geometry,margin=1.)
            skel[top:bottom,left:right][erase]=0
            continue
        clearance = (math.ceil(measured_radii[name])+1 if name in measured_radii else
                     math.ceil(native_radii[name])+1 if native_radii else max(1,radius-2))
        cv2.circle(skel, (x, y), clearance, 0, -1)
    # Preserve genuinely different routes between the same pair of vertices.
    # Duplicate forward/reverse traces of one stroke must NOT become multiedges.
    path_variants = {}
    indices = {name: i for i, (name, _, _) in enumerate(local)}

    node_pixels = {name:(x,y) for name,x,y in points}

    def keep_candidate(candidate):
        pair = tuple(sorted((indices[candidate["from"]],
                             indices[candidate["to"]])))
        variants=path_variants.setdefault(pair,[])
        if candidate.get('connector_evidence',{}).get('kind')=='outlined_arrow':
            for old in variants:
                if (old.get('connector_evidence',{}).get('kind')=='outlined_arrow' and old['score']>=candidate['score']
                        and _same_ink_route(candidate,old,node_pixels,w,h,radius,ink=ink_mask,
                                            offset=(min_x,min_y),node_geometry=measured_geometry or None)):
                    return
            variants[:]=[old for old in variants if not _same_ink_route(
                candidate,old,node_pixels,w,h,radius,ink=ink_mask,offset=(min_x,min_y),
                node_geometry=measured_geometry or None)]
            variants.append(candidate)
            return
        for index,old in enumerate(variants):
            if _same_ink_route(candidate,old,node_pixels,w,h,radius,ink=ink_mask,offset=(min_x,min_y),
                               node_geometry=measured_geometry or None):
                if (candidate["score"]>old["score"] and
                        old.get('connector_evidence',{}).get('kind')!='outlined_arrow'):
                    variants[index]=candidate
                return
        # Variants are candidate strokes, not certified multiplicity.
        if len(variants)<6:
            variants.append(candidate)
        else:
            weakest=min(range(len(variants)),key=lambda i:variants[i]["score"])
            if candidate["score"]>variants[weakest]["score"]:
                variants[weakest]=candidate

    max_steps = min(
        1600, max(50, round(2.4 * (max_x - min_x + max_y - min_y)))
    )
    for source in range(len(local)):
        source_radius = measured_radii.get(local[source][0], radius)
        sectors = max(24, min(128, round(2*math.pi*source_radius/4))) if measured_radii else 24
        for start in _unique_seeds(skel, local, source, source_radius, sectors=sectors,
                                   geometry=local_geometry.get(local[source][0])):
            target, path, turns, ambiguity = _follow(
                skel, local, source, start, radius, max_steps,
                node_radii=measured_radii or None, node_geometry=local_geometry or None
            )
            if target is None:
                continue
            a, b = sorted((source, target))
            separation = math.hypot(
                local[a][1] - local[b][1],
                local[a][2] - local[b][2],
            )
            length = len(path)
            if length < max(4, 0.35 * separation):
                continue
            score = max(
                0.0,
                1.0 - min(0.6, turns / max(length, 1))
                - min(0.5, ambiguity / max(length, 1)),
            )
            candidate = {
                'from': local[a][0],
                'to': local[b][0],
                'path': _sample_path(
                    [(x + min_x, y + min_y) for x, y in path], w, h,
                    max_error=.6 if dense_paths else None),
                'pixel_length': length,
                'straightness': round(separation / max(length, 1), 3),
                'score': round(score, 3),
                'needs_review': True,
                'method': ('opencv_skeleton_loop_trace'
                           if source == target else 'opencv_skeleton_tangent_trace'),
                'loop_candidate': source == target,
                'connector_evidence': {'kind': 'stroke_chain', 'source': 'skeleton_ports',
                                       'proposal_only': True},
            }
            if not candidate['path']:continue
            keep_candidate(candidate)

    for candidate in _straight_stroke_candidates(
            rgb[min_y:max_y, min_x:max_x], local, min_x, min_y,
            radius, w, h,ink_mask=photo_mask,node_radii=measured_radii or None):
        keep_candidate(candidate)
    # A long edge can terminate on a circular node rim away from the line
    # joining the two node centers; Hough endpoints recover these cases.
    for candidate in _hough_endpoint_candidates(
            rgb[min_y:max_y, min_x:max_x], local, min_x, min_y,
            radius, w, h,ink_mask=photo_mask,node_radii=measured_radii or None,
            node_geometry=local_geometry or None):
        keep_candidate(candidate)
    # Add paths around genuinely curved independent ink corridors, including
    # a straight+arc parallel pair which skeleton's greedy walker may miss.
    for candidate in _curved_stroke_candidates(
            rgb[min_y:max_y, min_x:max_x], local, min_x, min_y,
            radius, w, h,ink_mask=photo_mask,node_radii=measured_radii or None,
            node_geometry=measured_geometry or None,diagnostics=diagnostics):
        keep_candidate(candidate)
    if measured_geometry:
        for candidate in outlined_arrow_candidates(ink_mask,local,local_geometry,measured_radii,radius,
                                                   offset=(min_x,min_y),full_size=(w,h)):
            keep_candidate(candidate)
    result = []
    for variants in path_variants.values():
        result.extend(variants)
    if diagnostics is not None and len(result)>=MAX_TRACES_PER_GRAPH:
        diagnostics.append({'kind':'graph_candidate_limit','before_count':len(result),
                            'limit':MAX_TRACES_PER_GRAPH,'truncated':len(result)>MAX_TRACES_PER_GRAPH})
    ordered = sorted(
        result, key=lambda x: (-x['score'], x['from'], x['to'])
    )[:MAX_TRACES_PER_GRAPH]
    variants = {}
    for entry in ordered:
        pair = tuple(sorted((entry['from'], entry['to'])))
        entry['path_variant'] = variants.get(pair, 0)
        variants[pair] = entry['path_variant'] + 1
        if measured_geometry:
            points=np.asarray(_route_polyline_pixels(entry,w,h),float)
            if len(points)>=2:
                lengths=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(points,axis=0),axis=1))]
                if lengths[-1]>1:
                    samples=np.linspace(0.,lengths[-1],min(256,max(24,math.ceil(lengths[-1]/2.))))
                    points=np.stack([np.interp(samples,lengths,points[:,axis]) for axis in range(2)],axis=1)
                origin=np.asarray(node_pixels[entry['from']])
                if np.linalg.norm(points[0]-origin)>np.linalg.norm(points[-1]-origin):points=points[::-1]
                ports=[]
                for name,route in ((entry['from'],points),(entry['to'],points[::-1])):
                    geometry=measured_geometry.get(name)
                    if not geometry:continue
                    outside=np.flatnonzero(~contains_points(route,geometry,margin=1.))
                    if not len(outside):continue
                    k=int(outside[0]);point=route[k]
                    tangent=route[min(len(route)-1,k+1)]-point
                    norm=float(np.linalg.norm(tangent))
                    ports.append({'vertex':name,'point':[round(float(point[0]/max(w-1,1)),6),round(float(point[1]/max(h-1,1)),6)],
                                  'outward_tangent':[round(float(x/max(norm,1e-6)),5) for x in tangent],
                                  'footprint_confidence':geometry.get('confidence',0.),
                                  'footprint_source':geometry.get('source','measured')})
                entry['ports']=ports
    return ordered


def attach_line_evidence(image_bytes, cv_result, *, dense_paths=False,consistent_paper=False):
    """Add trace evidence without modifying verified edges or node labels."""
    if not isinstance(cv_result, dict) or not cv_result.get('graphs'):
        return cv_result
    try:
        rgb = _decode(image_bytes)
        with Image.open(io.BytesIO(image_bytes)) as source:
            native_size=ImageOps.exif_transpose(source).size
        marker_scale=min(rgb.shape[1]/native_size[0],rgb.shape[0]/native_size[1])
        result = dict(cv_result)
        candidates = []
        trace_diagnostics=[]
        for graph in (cv_result.get('graphs') or [])[:MAX_GRAPHS]:
            if not isinstance(graph, dict):
                continue
            limits=[]
            traces = _graph_candidates(rgb, graph,dense_paths=dense_paths,consistent_paper=consistent_paper,
                                       marker_scale=marker_scale,diagnostics=limits)
            if limits:trace_diagnostics.append({'id':str(graph.get('id','')),'diagnostics':limits})
            if traces:
                # The arrow result is evidence, not an accepted direction.
                try:
                    from graph_arrow_evidence import annotate_arrow_candidates
                    nodes = _vertices(graph, rgb.shape[1], rgb.shape[0])
                    if len(nodes) >= 2:
                        distances = [
                            min(math.hypot(x-xx,y-yy) for j,(_,xx,yy)
                                in enumerate(nodes) if j != i)
                            for i,(_,x,y) in enumerate(nodes)
                        ]
                        radius=max(3,min(13,round(float(np.median(distances))*.12)))
                        annotate_arrow_candidates(rgb,graph,traces,radius)
                except (ImportError,TypeError,ValueError,cv2.error) as arrow_exc:
                    print(f"箭头候选检测降级：{type(arrow_exc).__name__}")
                candidates.append({
                    'id': str(graph.get('id', '')),
                    'paths': traces,
                })
        if candidates:
            result['line_path_evidence'] = candidates
        if trace_diagnostics:
            result['line_trace_diagnostics']=trace_diagnostics
        return result
    except (ValueError, TypeError, cv2.error, OSError,
            KeyError, MemoryError) as exc:
        print(f'图路径追踪降级：{type(exc).__name__}')
        return cv_result


__all__ = ['attach_line_evidence']
