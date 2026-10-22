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
    for _ in range(max_steps):
        cx, cy = current
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
            coverage = hits / samples
            if coverage < 0.83:
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
    margin = max(16, round(median_sep * 0.33))
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
    best_by_pair = {}
    max_steps = min(
        1600, max(50, round(2.4 * (max_x - min_x + max_y - min_y)))
    )
    for source in range(len(local)):
        for start in _unique_seeds(skel, local, source, radius):
            target, path, turns, ambiguity = _follow(
                skel, local, source, start, radius, max_steps
            )
            if target is None or target == source:
                continue
            a, b = sorted((source, target))
            key = (a, b)
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
                'method': 'opencv_skeleton_tangent_trace',
            }
            if (key not in best_by_pair
                    or score > best_by_pair[key]['score']):
                best_by_pair[key] = candidate
    # Independent straight-line coverage complements broken skeleton routes.
    for candidate in _straight_stroke_candidates(
            rgb[min_y:max_y, min_x:max_x], local, min_x, min_y,
            radius, w, h):
        indexes = {name: i for i, (name, _, _) in enumerate(local)}
        key = tuple(sorted((indexes[candidate['from']],
                            indexes[candidate['to']])))
        if (key not in best_by_pair
                or candidate['score'] > best_by_pair[key]['score']):
            best_by_pair[key] = candidate
    return sorted(
        best_by_pair.values(),
        key=lambda x: (-x['score'], x['from'], x['to']),
    )[:MAX_TRACES_PER_GRAPH]


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
