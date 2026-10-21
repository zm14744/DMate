"""Supplemental CPU-only detector for straight textbook graphs with black filled vertices.

Only marked black dots are nodes. Crossing lines without dots are not nodes.
Produces positional topology candidates; it never guesses OCR labels or curved edges.
"""
from __future__ import annotations

import io
import math
from itertools import combinations

import cv2
import numpy as np
from PIL import Image, ImageOps

MAX_SIDE = 1700
MAX_GRAPHS = 12


def _contrast_gray(rgb):
    """Detect light/dark, chromatic and mixed-colour ink against a flat background.

    Unlike raw grayscale thresholding, yellow/blue strokes survive even when
    their grayscale intensity is close to the page. Dark-mode diagrams work
    without a special inversion branch. Never synthesize missing lines.
    """
    sample = rgb.reshape(-1, 3)[::max(1, rgb.shape[0]*rgb.shape[1]//45000)]
    background = np.median(sample, axis=0)
    delta = np.max(np.abs(rgb.astype(np.float32) - background[None, None, :]), axis=2)
    return (255 - np.minimum(255, delta * 2.2)).astype(np.uint8)


def _candidate_dots(gray, *, cutoff=105):
    """Opening removes thin strokes before identifying genuine filled disks."""
    h, w = gray.shape
    if min(h, w) < 45:
        return []
    kernel_size = 7 if max(h, w) >= 850 else 5
    mask = (gray < cutoff).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    n, labels, stats, centers = cv2.connectedComponentsWithStats(mask, 8)
    result = []
    max_diameter = max(18, min(42, int(max(h, w) * .035)))
    for idx in range(1, n):
        x, y, ww, hh, area = [int(z) for z in stats[idx]]
        if not (7 <= ww <= max_diameter and 7 <= hh <= max_diameter and area >= 30):
            continue
        if not (.68 <= ww / max(hh, 1) <= 1.38):
            continue
        if area / max(1, ww * hh) < .59:
            continue
        cx, cy = map(float, centers[idx])
        r = (ww + hh) / 4
        rad = max(2, int(min(ww, hh) * .22))
        crop = gray[max(0, int(cy)-rad):min(h, int(cy)+rad+1),
                    max(0, int(cx)-rad):min(w, int(cx)+rad+1)]
        if crop.size == 0 or float(np.median(crop)) >= 145:
            continue
        result.append((cx, cy, float(r), "black"))
    return result


def _select_figure_rows(dots):
    """Drop isolated round glyphs in headings, but keep lone-graph crops."""
    if len(dots) < 3:
        return []
    radii = sorted(v[2] for v in dots)
    size = float(np.median(radii[len(radii)//3:]))
    dots = [v for v in dots if .57*size <= v[2] <= 1.8*size]
    rows = []
    for v in sorted(dots, key=lambda p: p[1]):
        if not rows or abs(v[1]-float(np.median([q[1] for q in rows[-1]]))) > max(12, 1.45*size):
            rows.append([v])
        else:
            rows[-1].append(v)
    valid = [row for row in rows if len(row) >= 3]
    # In a screenshot of several 2-column/3-row graphs, each graph row
    # contains only two vertices, but the entire strip has >=4 on each
    # of THREE evenly spaced rows. Headlines often create many circular
    # glyphs; select the complete aligned ink triplet before splitting
    # panels. A generic "valid rows" filter included those glyphs and
    # merged the first three diagrams into one spurious 18+ node graph.
    # This strict strip detector is optional: uneven/curved layouts still
    # use the original generic detector below.
    if len(dots) >= 12:
        candidate_rows = [row for row in rows if len(row) >= 4]
        strongest = None
        for triple in combinations(candidate_rows, 3):
            y = [float(np.median([v[1] for v in row])) for row in triple]
            gap_a, gap_b = y[1]-y[0], y[2]-y[1]
            if min(gap_a, gap_b) < max(25, 5*size):
                continue
            if max(gap_a, gap_b)/min(gap_a, gap_b) > 1.38:
                continue
            minimum = min(len(row) for row in triple)
            maximum = max(len(row) for row in triple)
            if maximum > 1.4 * minimum:
                continue
            tolerance = max(10, 2.2*size)
            matched = sum(
                all(any(abs(node[0]-other[0]) < tolerance for other in row)
                    for row in triple[1:])
                for node in triple[0]
            )
            if matched < max(4, math.ceil(.65*minimum)):
                continue
            quality = (matched, minimum, sum(map(len, triple)))
            if strongest is None or quality > strongest[0]:
                strongest = (quality, triple)
        if strongest is not None:
            return [node for row in strongest[1] for node in row]
    # Three aligned dots in one row are a useful text-filter heuristic, NOT
    # a reason to discard the other 12 dots of a circular / Petersen drawing.
    # Keep the full geometric cloud when it is well spread on both axes.
    if 3 <= len(dots) <= 24:
        ys = [p[1] for p in dots]
        xs = [p[0] for p in dots]
        broad = (max(ys)-min(ys) > max(30, 4*size)
                 and max(xs)-min(xs) > max(30, 4*size))
        selected = sum(map(len, valid))
        if broad and selected < len(dots)*.9:
            return dots
    if not valid:
        return []
    return [v for row in valid for v in row]


def _split_boxes(nodes, gray):
    """Segment side-by-side drawings at columns without any connecting ink."""
    if len(nodes) < 3:
        return []
    h, w = gray.shape
    radius = float(np.median([p[2] for p in nodes]))
    ys = [p[1] for p in nodes]
    ymin = max(0, int(min(ys)-radius-4))
    ymax = min(h, int(max(ys)+radius+4))
    if ymax-ymin < 35:
        return []
    dark = gray[ymin:ymax] < 170
    density = (dark.sum(axis=0) > max(2, int((ymax-ymin)*.003))).astype(np.uint8)
    positions = sorted(nodes, key=lambda p: p[0])
    bins = []
    current = [positions[0]]
    for node in positions[1:]:
        prev = current[-1]
        start = max(0, int(prev[0]+prev[2]+2))
        end = min(w, int(node[0]-node[2]-2))
        split = False
        if end-start >= 18:
            longest = empty = 0
            for value in density[start:end]:
                empty = 0 if value else empty+1
                longest = max(longest, empty)
            split = longest >= max(18, 2.2*radius)
        if split:
            bins.append(current)
            current = []
        current.append(node)
    bins.append(current)
    found = []
    for group in bins:
        if len(group) < 3 or len(group) > 24:
            continue
        gys = [p[1] for p in group]
        if max(gys)-min(gys) < max(27, 3*radius):
            continue
        x1 = max(0, int(min(p[0]-p[2] for p in group)-12))
        x2 = min(w, int(max(p[0]+p[2] for p in group)+12))
        y1 = max(0, int(min(p[1]-p[2] for p in group)-12))
        y2 = min(h, int(max(p[1]+p[2] for p in group)+12))
        found.append((group, (x1, y1, x2, y2)))
    return found[:MAX_GRAPHS]


def _edge_score(gray, a, b, all_nodes, dark_cutoff=180):
    """Confirm an edge only if ink remains continuous on ONE vertex-to-vertex chord.

    A single ink crossing cannot pass the five-segment coverage test.
    """
    x1, y1, r1, _ = a
    x2, y2, r2, _ = b
    length = math.hypot(x2-x1, y2-y1)
    if length < max(20, r1+r2+5):
        return 0., 0., "too_short"
    vx, vy = (x2-x1)/length, (y2-y1)/length
    for c in all_nodes:
        if c is a or c is b:
            continue
        t = (c[0]-x1)*vx+(c[1]-y1)*vy
        off = abs((c[0]-x1)*vy-(c[1]-y1)*vx)
        if r1+3 < t < length-r2-3 and off < max(3, c[2]*.75):
            return 0., 0., "intermediate_vertex"
    start = max(4, r1+2)
    end = length-max(4, r2+2)
    if end-start < 10:
        return 0., 0., "too_short"
    num = min(430, max(32, int((end-start)/1.3)))
    ts = np.linspace(start, end, num)
    h, w = gray.shape
    best = (0., 0.)
    shifts = (-3., -1., 0., 1., 3.) if max(r1, r2) < 15 else (-4., -2., 0., 2., 4.)
    for sa in shifts:
        for sb in shifts:
            drift = sa+(sb-sa)*ts/length
            xx = x1+vx*ts-vy*drift
            yy = y1+vy*ts+vx*drift
            vals = []
            for off in (-1.3, 0., 1.3):
                xs = np.clip(np.rint(xx-off*vy).astype(int), 0, w-1)
                ys = np.clip(np.rint(yy+off*vx).astype(int), 0, h-1)
                vals.append(gray[ys, xs])
            occupied = (np.min(vals, axis=0) < dark_cutoff).astype(np.uint8)
            occupied = cv2.morphologyEx(occupied.reshape(1, -1), cv2.MORPH_CLOSE,
                                        np.ones((1, 3), np.uint8)).ravel() > 0
            coverage = float(occupied.mean())
            minimum = min(float(q.mean()) for q in np.array_split(occupied, 5))
            if (minimum, coverage) > (best[1], best[0]):
                best = (coverage, minimum)
    return best[0], best[1], ("solid" if best[0] >= .91 and best[1] >= .78 else
                             "uncertain" if best[0] >= .60 and best[1] >= .35 else "absent")


def _unexplained_ink_fraction(gray, group, box, edges, dark_cutoff):
    """Estimate ink outside detected vertex disks and confirmed straight edges."""
    x1, y1, x2, y2 = map(int, box)
    roi = gray[y1:y2, x1:x2]
    if roi.size == 0:
        return 1.0
    ink = roi < int(dark_cutoff)
    total_ink = int(np.count_nonzero(ink))
    if total_ink == 0:
        return 1.0
    covered = np.zeros(roi.shape, dtype=np.uint8)
    for node in group:
        x, y = int(round(node[0] - x1)), int(round(node[1] - y1))
        cv2.circle(covered, (x, y), max(3, int(round(node[2])) + 4), 255, -1)
    for i, j in edges:
        first, second = group[i], group[j]
        a = (int(round(first[0] - x1)), int(round(first[1] - y1)))
        b = (int(round(second[0] - x1)), int(round(second[1] - y1)))
        thickness = max(3, int(round(min(first[2], second[2]) * .55)))
        cv2.line(covered, a, b, 255, thickness)
    return int(np.count_nonzero(ink & (covered == 0))) / float(total_ink)


def _components(n, edges):
    roots = list(range(n))
    def find(i):
        while roots[i] != i:
            roots[i] = roots[roots[i]]
            i = roots[i]
        return i
    for a, b in edges:
        roots[find(a)] = find(b)
    return len({find(i) for i in range(n)})


def recognize_filled_graphs(image_bytes, *, text_hint="", allow_without_context=False):
    if not allow_without_context and not any(k in str(text_hint) for k in
            ("图", "顶点", "边", "树", "连通", "邻接", "路径", "欧拉", "哈密顿", "G1", "G2", "G3", "G4")):
        return {"status": "not_graph", "graphs": [], "regions": []}
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            img = ImageOps.exif_transpose(source).convert("RGB")
            # Enlarging a medium-resolution image to 1700px thickens its
            # incident strokes and merges black node disks with the edges.
            # Resize only genuinely tiny inputs; keep textbook scans near
            # native resolution to preserve endpoint geometry.
            longest = max(img.size)
            # Preserve small filled dots in tall mobile screenshots:
            # 931x2048 -> 773x1700 lost nine of 24 actual node markers.
            # A moderately tall 2MP page is safe at native resolution;
            # still bound genuinely enormous uploads to avoid CPU overload.
            native_page_safe = (
                longest <= 3200
                and img.width * img.height <= 3_500_000
                and min(img.size) <= 1500
            )
            scale = (min(2.0, 1100/longest) if longest < 700
                     else 1.0 if native_page_safe else MAX_SIDE/longest)
            if abs(scale-1.) > .025:
                img = img.resize((max(1, int(img.width*scale)),
                                  max(1, int(img.height*scale))), Image.Resampling.LANCZOS)
            rgb = np.asarray(img)
    except (OSError, ValueError):
        return {"status": "uncertain", "graphs": [], "regions": []}
    # Preserve the proven gray-scale detector for monochrome textbook images.
    # Contrast normalization widens antialiased monochrome strokes and can
    # swallow a circle into its incident lines in blurry photos. Activate it
    # only when chromatic ink or dark/inverted background requires it.
    raw_gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    rgb_i = rgb.astype(np.int16)
    chroma = rgb_i.max(axis=2) - rgb_i.min(axis=2)
    background = np.median(rgb_i.reshape(-1, 3)[::max(1, rgb.shape[0]*rgb.shape[1]//45000)], axis=0)
    deviation = np.max(np.abs(rgb_i - background[None, None, :]), axis=2)
    colored_pixels = (chroma > 35) & (deviation > 48)
    raw_dots = _select_figure_rows(_candidate_dots(raw_gray, cutoff=105))
    if len(raw_dots) >= 3:
        # A blue slide heading above a BLACK graph is not evidence that
        # the graph itself needs chromatic enhancement. Measure the ink
        # around the actual dots, not throughout the whole page.
        x1 = max(0, int(min(v[0]-v[2] for v in raw_dots)-15))
        x2 = min(rgb.shape[1], int(max(v[0]+v[2] for v in raw_dots)+16))
        y1 = max(0, int(min(v[1]-v[2] for v in raw_dots)-15))
        y2 = min(rgb.shape[0], int(max(v[1]+v[2] for v in raw_dots)+16))
        color_fraction = float(colored_pixels[y1:y2, x1:x2].mean()) if x2>x1 and y2>y1 else 0.
    else:
        color_fraction = float(colored_pixels.mean())
    use_color_contrast = color_fraction > .002 or float(np.median(raw_gray)) < 145
    gray = _contrast_gray(rgb) if use_color_contrast else raw_gray
    low = float(np.percentile(gray, 1))
    high = float(np.percentile(gray, 82))
    cutoff = int(np.clip(low+.24*(high-low), 105, 190))
    dots = _select_figure_rows(_candidate_dots(gray, cutoff=105))
    if len(dots) < 3 and cutoff > 110:
        dots = _select_figure_rows(_candidate_dots(gray, cutoff=cutoff))
    # Prefer node centers actually visible in the unmodified scan if
    # normalization causes some blurred circles to merge with their lines.
    if len(raw_dots) > len(dots) and float(np.median(raw_gray)) >= 145:
        dots = raw_dots
    if len(dots) < 3:
        return {"status": "uncertain", "graphs": [], "regions": []}
    boxes = _split_boxes(dots, gray)
    edge_cutoff = int(np.clip(low+.63*(high-low), 180, 225))
    sharpness = float(cv2.Laplacian(raw_gray, cv2.CV_64F).var())
    # Complex photograph backgrounds may produce fake ink. Downgrade them
    # instead of presenting an exact topology to the student.
    background_noise = float(np.median(np.abs(gray.astype(np.int16)-255)))
    graphs = []
    for group, box in boxes:
        if len(group) > 24:
            continue
        band = max(12, float(np.median([p[2] for p in group]))*1.7)
        rows = []
        for node in sorted(group, key=lambda p: p[1]):
            if not rows or node[1]-float(np.median([z[1] for z in rows[-1]])) > band:
                rows.append([node])
            else:
                rows[-1].append(node)
        group = [p for row in rows for p in sorted(row, key=lambda p: p[0])]
        edges, uncertain = [], []
        for i in range(len(group)):
            for j in range(i+1, len(group)):
                coverage, min_piece, status = _edge_score(
                    gray, group[i], group[j], group, dark_cutoff=edge_cutoff
                )
                if status == "solid":
                    edges.append((i, j))
                elif status == "uncertain":
                    uncertain.append((i, j))
        if len(edges) < 2 or len(group) < 4:
            continue
        vertex_list = [{"id": f"v{i+1}", "x": round(p[0]/gray.shape[1], 4),
                        "y": round(p[1]/gray.shape[0], 4), "label": None}
                       for i, p in enumerate(group)]
        matrix = [[0]*len(group) for _ in group]
        for i, j in edges:
            matrix[i][j] = matrix[j][i] = 1
        # Only clean simple straight-edge drawings can receive high confidence.
        # Curves, loops, arrows, labels or missed strokes remain unexplained ink.
        unexplained_ink = _unexplained_ink_fraction(
            gray, group, box, edges, edge_cutoff
        )
        complete = (
            5 <= len(group) <= 8 and not uncertain and len(edges) >= 2
            and sharpness >= 7 and background_noise < 22
            and unexplained_ink <= .10
        )
        graphs.append({"id": f"图{len(graphs)+1}", "directed": "unknown",
                       "vertices": vertex_list, "vertex_count": len(group),
                       "edges": [[f"v{i+1}", f"v{j+1}"] for i, j in edges],
                       "confirmed_edge_count": len(edges),
                       "adjacency_matrix": matrix,
                       "component_count_of_confirmed_edges": _components(len(group), edges),
                       "uncertain_edges": [[f"v{i+1}", f"v{j+1}"] for i, j in uncertain],
                       "confidence": "high" if complete else "partial",
                        "unexplained_ink_fraction": round(unexplained_ink, 3),
                       "bbox": [round(v/lim, 4) for v, lim in zip(
                           box, (gray.shape[1], gray.shape[0], gray.shape[1], gray.shape[0]))]})
    return {"status": "detected" if graphs else "uncertain", "graphs": graphs,
            "regions": [g["bbox"] for g in graphs],
            "warning": "仅依据实心顶点与连续直线确认候选边；交叉无实心顶点不构成连接；曲线、箭头、文字与不清楚的端点交由 Vision 复核。"}
