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

MAX_SIDE = 1600
MAX_GRAPHS = 10
MAX_VERTICES = 30
MAX_TRACES_PER_GRAPH = 48
NEIGHBORS = tuple((dy, dx) for dy in range(-2, 3) for dx in range(-2, 3)
                  if 0 < dx * dx + dy * dy <= 5)


def _foreground(rgb):
    """Preserve both dark and saturated colour strokes on light pages."""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    if float(np.median(gray)) < 105:
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
    with Image.open(io.BytesIO(image_bytes)) as im:
        rgb = np.asarray(ImageOps.exif_transpose(im).convert('RGB'))
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
    if not 2 <= len(points) <= MAX_VERTICES or len(set(ids)) != len(ids):
        return []
    return points


def _unique_seeds(skel, points, vertex_index, radius):
    _, x0, y0 = points[vertex_index]
    h, w = skel.shape
    candidates = {}
    outer = max(4, radius + 5)
    for y in range(max(1, y0 - outer), min(h - 1, y0 + outer + 1)):
        for x in range(max(1, x0 - outer), min(w - 1, x0 + outer + 1)):
            if skel[y, x] != 255:
                continue
            distance = math.hypot(x - x0, y - y0)
            if not radius - 1 <= distance <= outer:
                continue
            sector = round(
                (math.atan2(y - y0, x - x0) + math.pi)
                / (2 * math.pi) * 24
            ) % 24
            err = abs(distance - radius - 1.0)
            if sector not in candidates or err < candidates[sector][0]:
                candidates[sector] = (err, (x, y))
    return [v[1] for _, v in sorted(candidates.items())]


def _follow(skel, points, source_i, start, radius, max_steps):
    """Trace ink while favouring tangent continuity at unmarked crossings."""
    _, sx, sy = points[source_i]
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
        if (len(path) >= max(16, 5 * radius)
                and max_excursion >= 2.8 * radius
                and source_distance <= radius + 4):
            return source_i, path, turns, ambiguity
        arrivals = [
            (math.hypot(cx - vx, cy - vy), i)
            for i, (_, vx, vy) in enumerate(points)
            if i != source_i
        ]
        if arrivals:
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


def _sample_path(path, width, height):
    selected = (
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


def _same_ink_route(candidate,existing,pointmap,width,height,radius):
    """Group reverse traversals but not distinct straight/curved strokes."""
    a=_route_signature(candidate,pointmap,width,height)
    b=_route_signature(existing,pointmap,width,height)
    return (len(a)==len(b)==9 and
            sorted(math.dist(x,y) for x,y in zip(a,b))[-3] <= max(5.5,radius*1.25))


def _straight_stroke_candidates(rgb, local, x_off, y_off, radius, full_w, full_h):
    """Independently propose only high-coverage straight strokes.

    A crossing alone cannot satisfy the coverage test. A confirmed node
    between two endpoints blocks an apparent long edge.
    """
    ink = _foreground(rgb) > 0
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
            crossing_node = False
            for k, (_, px, py) in enumerate(local):
                if k in (i, j):
                    continue
                t = ((px - ax) * dx + (py - ay) * dy) / (length * length)
                side = abs((px - ax) * dy - (py - ay) * dx) / length
                if 0.08 < t < 0.92 and side <= radius * 0.8:
                    crossing_node = True
                    break
            if crossing_node:
                continue
            samples = max(15, min(250, round(length * 0.9)))
            hits = 0
            missing_run = max_missing_run = 0
            for step in range(samples):
                t = 0.09 + 0.82 * (step + 0.5) / samples
                mx, my = ax + t * dx, ay + t * dy
                ux, uy = -dy / length, dx / length
                found = False
                for offset in (-3.0, -1.5, 0, 1.5, 3.0):
                    x, y = round(mx + offset * ux), round(my + offset * uy)
                    if 0 <= x < width and 0 <= y < height and ink[y, x]:
                        found = True
                        break
                hits += int(found)
                missing_run = 0 if found else missing_run + 1
                max_missing_run = max(max_missing_run, missing_run)
            coverage = hits / samples
            # Average ink coverage alone can connect unrelated aligned lines.
            # A long missing segment is evidence against an actual edge.
            largest_gap_px = max_missing_run * length / samples
            if coverage < 0.83 or largest_gap_px > max(6, min(16, length * 0.045)):
                continue
            candidates.append({
                'from': local[i][0], 'to': local[j][0],
                'path': [[round((ax + x_off) / max(full_w - 1, 1), 4),
                          round((ay + y_off) / max(full_h - 1, 1), 4)],
                         [round((bx + x_off) / max(full_w - 1, 1), 4),
                          round((by + y_off) / max(full_h - 1, 1), 4)]],
                'pixel_length': round(length),
                'score': round(coverage, 3),
                'needs_review': True,
                'method': 'opencv_straight_line_coverage',
            })
    return candidates


def _hough_endpoint_candidates(rgb, local, x_off, y_off, radius, full_w, full_h):
    """Match real visible Hough stroke endpoints to marked node *rims*.

    Center-to-center coverage fails for lines attached off-center to circles.
    This function never manufactures vertices or certified graph edges.
    """
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    if float(np.median(gray)) < 105:
        mask = _foreground(rgb)
    else:
        _, mask = cv2.threshold(gray, 216, 255, cv2.THRESH_BINARY_INV)
    edges = cv2.Canny(mask, 55, 145)
    segments = cv2.HoughLinesP(edges, 1, math.pi / 720, threshold=18,
                               minLineLength=24, maxLineGap=7)
    if segments is None:
        return []
    output = []
    for x1, y1, x2, y2 in segments[:, 0][:400]:
        length = math.hypot(float(x2-x1), float(y2-y1))
        if length < max(24, radius * 2.5):
            continue
        nearest = []
        for xx, yy in ((x1, y1), (x2, y2)):
            dist, number = min((math.hypot(float(xx)-vx, float(yy)-vy), i)
                               for i, (_, vx, vy) in enumerate(local))
            nearest.append((dist, number))
        (d1, i), (d2, j) = nearest
        if i == j or max(d1, d2) > max(9.0, radius * 1.45):
            continue
        center_distance = math.hypot(local[i][1]-local[j][1],local[i][2]-local[j][2])
        if length < 0.63 * center_distance:
            continue
        crosses_node = False
        for k,(_,vx,vy) in enumerate(local):
            if k in (i,j):
                continue
            projection = ((vx-x1)*(x2-x1)+(vy-y1)*(y2-y1))/(length*length)
            distance = abs((vx-x1)*(y2-y1)-(vy-y1)*(x2-x1))/length
            if 0.08 < projection < 0.92 and distance < radius*.83:
                crosses_node = True
                break
        if crosses_node:
            continue
        a,b=sorted((i,j))
        confidence = max(0.1, 0.92 - 0.20*(d1+d2)/max(2*radius,1))
        output.append({
            'from':local[a][0], 'to':local[b][0],
            'path':[[round((x1+x_off)/max(full_w-1,1),4),
                     round((y1+y_off)/max(full_h-1,1),4)],
                    [round((x2+x_off)/max(full_w-1,1),4),
                     round((y2+y_off)/max(full_h-1,1),4)]],
            'pixel_length':round(length), 'score':round(confidence,3),
            'needs_review':True, 'method':'opencv_hough_rim_endpoint',
        })
    return output


def _graph_candidates(rgb, graph):
    h, w = rgb.shape[:2]
    points = _vertices(graph, w, h)
    if not points:
        return []
    nearest = [
        min(math.hypot(x - a, y - b)
            for j, (_, a, b) in enumerate(points) if j != i)
        for i, (_, x, y) in enumerate(points)
    ]
    median_sep = float(np.median(nearest))
    radius = max(3, min(13, round(median_sep * 0.12)))
    # Small crops clipped real outer arcs and self-loops. Retain enough
    # space beyond the vertex hull without scanning the entire text page.
    margin = max(34, min(120, round(median_sep * 0.62)))
    min_x = max(0, min(p[1] for p in points) - margin)
    max_x = min(w, max(p[1] for p in points) + margin + 1)
    min_y = max(0, min(p[2] for p in points) - margin)
    max_y = min(h, max(p[2] for p in points) + margin + 1)
    if min(max_x - min_x, max_y - min_y) < 14:
        return []
    skel = _thin(_foreground(rgb[min_y:max_y, min_x:max_x]))
    local = [(label, x - min_x, y - min_y) for label, x, y in points]
    # Erase only already-detected vertex interiors, not line crossings.
    for _, x, y in local:
        cv2.circle(skel, (x, y), max(1, radius - 2), 0, -1)
    # Preserve genuinely different routes between the same pair of vertices.
    # Duplicate forward/reverse traces of one stroke must NOT become multiedges.
    path_variants = {}
    indices = {name: i for i, (name, _, _) in enumerate(local)}

    node_pixels = {name:(x,y) for name,x,y in points}

    def keep_candidate(candidate):
        pair = tuple(sorted((indices[candidate["from"]],
                             indices[candidate["to"]])))
        variants=path_variants.setdefault(pair,[])
        for index,old in enumerate(variants):
            if _same_ink_route(candidate,old,node_pixels,w,h,radius):
                if candidate["score"]>old["score"]: variants[index]=candidate
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
        for start in _unique_seeds(skel, local, source, radius):
            target, path, turns, ambiguity = _follow(
                skel, local, source, start, radius, max_steps
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
                    [(x + min_x, y + min_y) for x, y in path], w, h),
                'pixel_length': length,
                'straightness': round(separation / max(length, 1), 3),
                'score': round(score, 3),
                'needs_review': True,
                'method': ('opencv_skeleton_loop_trace'
                           if source == target else 'opencv_skeleton_tangent_trace'),
                'loop_candidate': source == target,
            }
            keep_candidate(candidate)

    for candidate in _straight_stroke_candidates(
            rgb[min_y:max_y, min_x:max_x], local, min_x, min_y,
            radius, w, h):
        keep_candidate(candidate)
    # A long edge can terminate on a circular node rim away from the line
    # joining the two node centers; Hough endpoints recover these cases.
    for candidate in _hough_endpoint_candidates(
            rgb[min_y:max_y, min_x:max_x], local, min_x, min_y,
            radius, w, h):
        keep_candidate(candidate)
    result = []
    for variants in path_variants.values():
        result.extend(variants)
    ordered = sorted(
        result, key=lambda x: (-x['score'], x['from'], x['to'])
    )[:MAX_TRACES_PER_GRAPH]
    variants = {}
    for entry in ordered:
        pair = tuple(sorted((entry['from'], entry['to'])))
        entry['path_variant'] = variants.get(pair, 0)
        variants[pair] = entry['path_variant'] + 1
    return ordered


def attach_line_evidence(image_bytes, cv_result):
    """Add trace evidence without modifying verified edges or node labels."""
    if not isinstance(cv_result, dict) or not cv_result.get('graphs'):
        return cv_result
    try:
        rgb = _decode(image_bytes)
        result = dict(cv_result)
        candidates = []
        for graph in (cv_result.get('graphs') or [])[:MAX_GRAPHS]:
            if not isinstance(graph, dict):
                continue
            traces = _graph_candidates(rgb, graph)
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
        return result
    except (ValueError, TypeError, cv2.error, OSError,
            KeyError, MemoryError) as exc:
        print(f'图路径追踪降级：{type(exc).__name__}')
        return cv_result


__all__ = ['attach_line_evidence']
