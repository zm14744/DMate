"""Strict optional pixel evidence for common diagram layouts and colored-circle graphs.

Never use a filename, image hash, textbook answer, or a known graph family to
recover connections. All claims come from measurements of the supplied RGB.
Pixel evidence is advisory unless a conservative consistency gate permits an
anonymous, unweighted, straight-line colored-marker graph to be rebuilt.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import math

import cv2
import numpy as np
from PIL import Image

MAX_SIDE = 1800
MAX_NODES = 28


def _image(raw):
    with Image.open(io.BytesIO(raw)) as source:
        source.load()
        if source.width * source.height > 16_000_000:
            raise ValueError("pixel_evidence_image_too_large")
        original = source.convert("RGB")
    factor = min(1., MAX_SIDE / max(original.size))
    if factor < 1.:
        image = original.resize(
            (max(1, round(original.width * factor)), max(1, round(original.height * factor))),
            Image.Resampling.LANCZOS)
    else:
        image = original
    return original, np.asarray(image)


def _colored_caption_grid(rgb):
    """Recognize ONLY a repeated regular grid of filled rectangular captions.

    Colored rectangles are layout signals, not a mathematical graph inventory.
    Validate aligned columns and distinct rows before providing a lower-bound
    on separately captioned panels. This never infers edge connectivity.
    """
    height, width = rgb.shape[:2]
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    binary = ((hsv[:, :, 1] >= 120) & (hsv[:, :, 2] >= 105)).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    found = []
    for x, y, w, h, area in stats[1:]:
        if (w < max(24, width * .12) or h < max(9, height * .025)
                or w < h * 2 or w > h * 20 or h > height * .16
                or area / max(1, w*h) < .75):
            continue
        if y < height * .12:
            continue
        found.append((int(x), int(y), int(w), int(h)))
    if not 4 <= len(found) <= 16:
        return None
    found.sort(key=lambda box: (box[1] + box[3]/2, box[0]))
    rows = []
    for bar in found:
        cy = bar[1] + bar[3]/2
        if not rows or abs(cy - np.median([b[1] + b[3]/2 for b in rows[-1]])) > height * .085:
            rows.append([bar])
        else:
            rows[-1].append(bar)
    if not 2 <= len(rows) <= 4:
        return None
    columns = len(rows[0])
    if not 2 <= columns <= 4 or any(len(row) != columns for row in rows):
        return None
    for row in rows:
        row.sort(key=lambda b: b[0] + b[2]/2)
    centers = [[(b[0]+b[2]/2)/width for b in row] for row in rows]
    for col in range(columns):
        if max(c[col] for c in centers) - min(c[col] for c in centers) > .12:
            return None
    column_centers = [float(np.median([c[i] for c in centers])) for i in range(columns)]
    if any(column_centers[i+1]-column_centers[i] < .13
           for i in range(columns-1)):
        return None
    col_bounds = [0.] + [(column_centers[i]+column_centers[i+1])/2
                          for i in range(columns-1)] + [1.]
    # Colored captions are below their corresponding figure. The next row's
    # figures begin shortly after the previous row's caption bars finish;
    # splitting midway between caption ROW CENTERS would wrongly cut figures.
    row_bounds = [0.]
    for index in range(len(rows)-1):
        bottom = max(b[1]+b[3] for b in rows[index])
        next_top = min(b[1] for b in rows[index+1])
        # If captions overlap the next figure row, the grid is not reliable.
        if next_top - bottom < .04*height:
            return None
        row_bounds.append(min(1., (bottom + min(height*.04, (next_top-bottom)*.20))/height))
    row_bounds.append(1.)
    panels = []
    for ri, row in enumerate(rows):
        for ci, bar in enumerate(row):
            x0, x1 = col_bounds[ci], col_bounds[ci+1]
            y0, y1 = row_bounds[ri], row_bounds[ri+1]
            panels.append({"id": f"colored_caption_r{ri+1}c{ci+1}",
                           "row": ri+1, "column": ci+1,
                           "bbox": [round(x0*1000, 3), round(y0*1000, 3),
                                    round(x1*1000, 3), round(y1*1000, 3)],
                           "caption_rectangle": [int(v) for v in bar],
                           "source": "opencv_repeated_color_caption_rectangles",
                           "status": "layout_evidence_only"})
    return {"status": "regular_caption_grid", "rows": len(rows),
            "columns": columns, "caption_rectangles": len(found),
            "minimum_captioned_panels": len(panels),
            "panels": panels, "column_bounds": [round(x, 6) for x in col_bounds],
            "source": "same_original_rgb",
            "pixel_grounded": True, "not_graph_count_certificate": True}


def _red_markers(rgb):
    height, width = rgb.shape[:2]
    red, green, blue = [rgb[:, :, i].astype(np.int16) for i in range(3)]
    mask = ((red > 135) & (red > green * 1.40 + 32)
            & (red > blue * 1.40 + 32)).astype(np.uint8)
    _, _, stats, centers = cv2.connectedComponentsWithStats(mask, 8)
    points = []
    for (x, y, w, h, area), (cx, cy) in zip(stats[1:], centers[1:]):
        if (not 6 <= w <= max(50, width*.08) or
                not 6 <= h <= max(50, height*.12) or
                not .64 <= w/h <= 1.55 or
                area < 30 or area/(w*h) < .60):
            continue
        points.append({"x": float(cx), "y": float(cy),
                       "size": max(int(w), int(h)), "area": int(area)})
    if len(points) < 3 or len(points) > MAX_NODES * 5:
        return []
    sizes = np.array([p["size"] for p in points])
    common = float(np.median(sizes))
    points = [p for p in points if common*.64 <= p["size"] <= common*2.0]
    points.sort(key=lambda p: p["x"])
    groups = []
    for point in points:
        if not groups or point["x"]-groups[-1][-1]["x"] >= max(30, width*.061):
            groups.append([])
        groups[-1].append(point)
    groups = [group for group in groups if
              3 <= len(group) <= MAX_NODES and
              max(p["y"] for p in group)-min(p["y"] for p in group) > height*.07]
    if len(groups) > 12:
        return []
    return groups


def _color_line_topology(rgb):
    """Trace straight dark strokes between distinct saturated filled nodes.

    Curves, black nodes, and dense unresolved paths are NOT classified as
    negative edges. The result is a strict measured candidate, not an answer.
    """
    height, width = rgb.shape[:2]
    binary = (cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY) < 145).astype(np.uint8)
    result = []
    for index, group in enumerate(_red_markers(rgb), 1):
        nodes = sorted(group, key=lambda p: (p["y"], p["x"]))
        node_rows = [{"id": f"p{i+1}", "x": round(p["x"]/width*1000, 2),
                      "y": round(p["y"]/height*1000, 2),
                      "diameter": p["size"]} for i, p in enumerate(nodes)]
        edges, borderline = [], []
        median_diameter = float(np.median([p["size"] for p in nodes]))
        corridor = max(3, min(9, math.ceil(median_diameter*.44)))
        for i, a in enumerate(nodes):
            for j, b in enumerate(nodes[i+1:], i+1):
                dx, dy = b["x"]-a["x"], b["y"]-a["y"]
                length = math.hypot(dx, dy)
                if length < max(20., 1.8*median_diameter):
                    continue
                guard = max(a["size"], b["size"])*.50 + 2
                fractions = np.linspace(max(.0, min(.47, guard/length)),
                                        min(1., max(.53, 1-guard/length)),
                                        max(36, min(280, round(length))), dtype=np.float32)
                sx, sy = a["x"]+dx*fractions, a["y"]+dy*fractions
                perp_x, perp_y = -dy/length, dx/length
                votes = []
                for offset in range(-corridor, corridor+1):
                    px = np.clip(np.rint(sx+offset*perp_x).astype(np.int32), 0, width-1)
                    py = np.clip(np.rint(sy+offset*perp_y).astype(np.int32), 0, height-1)
                    votes.append(binary[py, px])
                support = float(np.max(votes, axis=0).mean())
                pair = {"from": f"p{i+1}", "to": f"p{j+1}",
                        "support": round(support, 3)}
                if support >= .87:
                    edges.append(pair)
                elif support >= .70:
                    borderline.append(pair)
        if not edges:
            continue
        result.append({"id": f"colored_group_{index}",
                       "source": "same_original_rgb_straight_stroke_sampling",
                       "pixel_grounded": True, "unlabeled_only": True,
                       "vertices": node_rows, "edges": edges,
                       "borderline_pairs": borderline,
                       "unambiguous": not borderline,
                       "bbox": [round(max(0.,min(p["x"] for p in nodes)/width-.04)*1000, 3),
                                round(max(0.,min(p["y"] for p in nodes)/height-.04)*1000, 3),
                                round(min(1.,max(p["x"] for p in nodes)/width+.04)*1000, 3),
                                round(min(1.,max(p["y"] for p in nodes)/height+.04)*1000, 3)]})
    return result


def _dark_disks_once(gray, *, level, kernel):
    """Find filled circular dark marks rather than thin text and ink strokes."""
    binary = np.uint8(gray < level) * 255
    opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel, kernel)))
    _, _, stats, centers = cv2.connectedComponentsWithStats(opened, 8)
    minimum = max(10, round(kernel * 1.1))
    maximum = min(70, round(kernel * 5.0))
    result = []
    for (x,y,w,h,area),(cx,cy) in zip(stats[1:], centers[1:]):
        if (not minimum <= w <= maximum or not minimum <= h <= maximum
                or area < max(55, kernel*kernel*.65)
                or not .55 <= w/h <= 1.75 or area/(w*h) < .60):
            continue
        result.append({'x': float(cx), 'y': float(cy), 'diameter': int(max(w,h))})
    return result


def _dark_line_candidates(gray, nodes):
    """High-coverage straight corridors are only a LOWER bound on real edges.

    Curves, parallel strokes, breaks, loops and dashed lines are not disproved
    by this tool. No edge is ever automatically added to a labelled diagram.
    """
    if len(nodes) > 12:
        return []
    height, width = gray.shape
    ink = (gray < 145).astype(np.uint8)
    links = []
    for i,a in enumerate(nodes):
        for j,b in enumerate(nodes[i+1:], i+1):
            dx,dy = b['x']-a['x'], b['y']-a['y']
            distance = math.hypot(dx,dy)
            guard = max(a['diameter'],b['diameter'])*.6+3
            if distance <= guard*2+8:
                continue
            # A path passing through a third marked node is NOT a direct edge.
            passes_node = False
            for k,other in enumerate(nodes):
                if k in (i,j):
                    continue
                along = ((other['x']-a['x'])*dx+(other['y']-a['y'])*dy)/(distance*distance)
                if .05 < along < .95:
                    cross = abs((other['x']-a['x'])*dy-(other['y']-a['y'])*dx)/distance
                    if cross < other['diameter']*.52+3:
                        passes_node = True
                        break
            if passes_node:
                continue
            t = np.linspace(guard/distance,1-guard/distance,
                            max(40,min(320,round(distance*1.2))))
            xx,yy = a['x']+dx*t,a['y']+dy*t
            nx,ny = -dy/distance, dx/distance
            strips = []
            for offset in (-2,-1,0,1,2):
                xi = np.clip(np.rint(xx+offset*nx).astype(np.int32),0,width-1)
                yi = np.clip(np.rint(yy+offset*ny).astype(np.int32),0,height-1)
                strips.append(ink[yi,xi])
            support = float(np.max(strips,axis=0).mean())
            if support >= .85:
                links.append({'from': f'disk_{i+1}','to':f'disk_{j+1}',
                              'support':round(support,3),
                              'source':'same_original_grayscale_straight_corridor'})
    return links


def _stable_dark_disks(rgb, grid):
    """Measure filled black nodes per strict grid panel at three thresholds.

    Positions must agree across all three independently thresholded rasters.
    Only such stable blobs generate scoped count/straight-stroke advisories.
    """
    if not isinstance(grid,dict) or grid.get('status') != 'regular_caption_grid':
        return {'status':'not_applicable','panels':[]}
    gray = cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    height,width = gray.shape
    kernel = max(7,min(13,round(max(width,height)/185)))
    if kernel%2 == 0:
        kernel += 1
    snapshots = {threshold:_dark_disks_once(gray,level=threshold,kernel=kernel)
                 for threshold in (100,130,160)}
    panels = []
    for row in grid.get('panels',[]):
        bounds = row.get('bbox')
        if not isinstance(bounds,list) or len(bounds)!=4:
            continue
        x0,y0,x1,y1 = [v/1000 for v in bounds]
        lists = {}
        for threshold, items in snapshots.items():
            candidates = [item for item in items if
                x0 <= item['x']/width < x1 and y0 <= item['y']/height < y1]
            # A single tiny glyph can survive the highest gray threshold
            # beside several equally sized true disk vertices. Remove ONLY a
            # unique extreme undersized outlier (<42% of the dominant median),
            # preserving genuinely varying node sizes for manual review.
            if len(candidates) >= 4:
                median = float(np.median([item['diameter'] for item in candidates]))
                tiny = [i for i,item in enumerate(candidates)
                        if item['diameter'] < median*.42]
                if (len(tiny) == 1 and all(
                        item['diameter'] >= median*.72
                        for i,item in enumerate(candidates) if i not in tiny)):
                    candidates.pop(tiny[0])
            candidates.sort(key=lambda p:(p['y'],p['x']))
            lists[threshold] = candidates
        points = lists[130]
        stable = 2 <= len(points) <= MAX_NODES
        if stable:
            for threshold in (100,160):
                found = lists[threshold]
                if len(found) != len(points):
                    stable = False
                    break
                unmatched = set(range(len(found)))
                for p in points:
                    valid = [index for index in unmatched if
                             math.hypot(p['x']-found[index]['x'],p['y']-found[index]['y'])
                             <= max(9,kernel*1.6)]
                    if len(valid) != 1:
                        stable = False
                        break
                    unmatched.remove(valid[0])
                if not stable:
                    break
        if not stable:
            panels.append({'region_id':row.get('id'), 'row':row.get('row'),
                           'column':row.get('column'), 'status':'unstable',
                           'advisory_only':True})
            continue
        links = _dark_line_candidates(gray,points)
        panels.append({'region_id':row.get('id'), 'row':row.get('row'),
                       'column':row.get('column'), 'status':'measured',
                       'candidate_count':len(points),
                       'nodes':[{'id':f'disk_{i+1}',
                                 'x':round(p['x']/width*1000,2),
                                 'y':round(p['y']/height*1000,2),
                                 'diameter_pixels':p['diameter']}
                                for i,p in enumerate(points)],
                       'straight_edge_candidates':links,
                       'straight_edge_lower_bound':len(links),
                       'edge_count_is_exact':False, 'advisory_only':True})
    status = 'measured' if len(panels)==grid['minimum_captioned_panels'] and all(
        panel['status']=='measured' for panel in panels) else 'partial'
    return {'status':status,'panels':panels, 'kernel':kernel,
            'thresholds':[100,130,160], 'source':'same_original_gray_pixels',
            'image_accuracy_certified':False}


def measure_image_pixel_evidence(raw):
    """One CPU-only bounded snapshot; fail open without pretending success."""
    original, rgb = _image(raw)
    grid = _colored_caption_grid(rgb)
    return {"source_sha256": hashlib.sha256(raw).hexdigest(),
            "grid": grid,
            "grid_dark_disks": _stable_dark_disks(rgb, grid),
            "colored_graphs": _color_line_topology(rgb),
            "source_size": list(original.size),
            "work_size": [int(rgb.shape[1]), int(rgb.shape[0])],
            "advisory_only": True, "image_accuracy_certified": False}


def create_grid_column_views(raw, evidence):
    """Supply 2-4 different column zooms, all from ONE original RGB image."""
    grid = evidence.get("grid") if isinstance(evidence, dict) else None
    if not isinstance(grid, dict) or grid.get("status") != "regular_caption_grid":
        return []
    original, _ = _image(raw)
    views = []
    width = original.width
    bounds = grid["column_bounds"]
    for ci in range(min(grid["columns"], 4)):
        left = max(0, int(math.floor(bounds[ci]*width)))
        right = min(width, int(math.ceil(bounds[ci+1]*width)))
        if right-left < width*.12:
            return []
        section = original.crop((left, 0, right, original.height))
        maximum = min(1., 1280/max(section.size),
                      math.sqrt(950_000/(section.width*section.height)))
        if maximum < 1.:
            section = section.resize((max(1,int(section.width*maximum)),
                                      max(1,int(section.height*maximum))),
                                     Image.Resampling.LANCZOS)
        stream = io.BytesIO()
        section.save(stream, format="PNG", compress_level=3)
        data = base64.b64encode(stream.getvalue()).decode("ascii")
        views.append({"image": "data:image/png;base64,"+data,
                      "description": f"同一原图的第{ci+1}列完整原像素放大，包含该列各行的图和图注；"
                                     f"全图为{grid['rows']}行×{grid['columns']}列。"
                                     "每幅独立图只能计一次，列放大不是新增图。"})
    return views


def create_grid_panel_views(raw, evidence, indices):
    """Zoom only the disputed mathematical panels from the ORIGINAL RGB.

    Indices are zero-based in full-page reading order. The caller must supply
    independently flagged graph indices; this never selects a "winning" crop
    by comparing to an expected result or invents a graph identity.
    """
    grid = evidence.get("grid") if isinstance(evidence, dict) else None
    if not isinstance(grid, dict) or grid.get("status") != "regular_caption_grid":
        return []
    rows = grid.get("panels")
    if (not isinstance(rows, list) or len(rows) != grid.get("minimum_captioned_panels")
            or not isinstance(indices, (list, tuple)) or not 1 <= len(indices) <= 4
            or any(type(index) is not int or index < 0 or index >= len(rows)
                   for index in indices) or len(set(indices)) != len(indices)):
        return []
    original, _ = _image(raw)
    width, height = original.size
    views = []
    for index in indices:
        panel = rows[index]
        box = panel.get("bbox") if isinstance(panel, dict) else None
        if (not isinstance(box, list) or len(box) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in box)):
            return []
        x0, y0, x1, y1 = [float(v) / 1000. for v in box]
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            return []
        left, top = max(0, int(math.floor(x0*width))), max(0, int(math.floor(y0*height)))
        right, bottom = min(width, int(math.ceil(x1*width))), min(height, int(math.ceil(y1*height)))
        if right-left < width*.10 or bottom-top < height*.12:
            return []
        cut = original.crop((left, top, right, bottom))
        maximum = min(1., 1280/max(cut.size), math.sqrt(950_000/(cut.width*cut.height)))
        if maximum < 1.:
            cut = cut.resize((max(1,int(cut.width*maximum)),
                              max(1,int(cut.height*maximum))), Image.Resampling.LANCZOS)
        stream = io.BytesIO()
        cut.save(stream, format="PNG", compress_level=3)
        views.append({
            "image": "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii"),
            "description": (f"完整原图中第{index+1}个图注位置的独立原RGB局部放大，"
                            f"位于第{panel.get('row')}行第{panel.get('column')}列；"
                            "用于核查这个位置的顶点、实际连线和箭头。"
                            "这不是新增图，不按图名或模型草稿推测原像素。"),
            "region_id": panel.get("id"),
            "original_pixel_bbox": [left, top, right, bottom]
        })
    return views


def reconcile_anonymous_pixel_graphs(draft, evidence):
    """High-confidence straight-line pixel edges may repair unlabeled graphs.

    No weights, printed vertex labels, parallel edges, loops, incomplete
    strokes, or mismatched visible counts can be reconstructed this way.
    IDs are retained from the visual model. Every replacement is audited;
    the caller must STILL expose human review and never certify the image.
    """
    from collections import Counter
    if not isinstance(draft, dict) or not isinstance(evidence, dict):
        return draft, []
    candidates = evidence.get("colored_graphs") or []
    graphs = draft.get("graphs", [])
    if (not isinstance(graphs, list) or len(graphs) != len(candidates)
            or not 1 <= len(graphs) <= 12):
        return draft, []
    reviewed, changes = copy.deepcopy(draft), []
    for index, (graph, group) in enumerate(zip(reviewed["graphs"], candidates)):
        if not isinstance(graph, dict) or not group.get("unambiguous"):
            continue
        vertices, edges = graph.get("vertices"), graph.get("edges")
        pv, pe = group["vertices"], group["edges"]
        if (not isinstance(vertices, list) or not isinstance(edges, list)
                or len(vertices) != len(pv) or len(edges) != len(pe)
                or len(vertices) < 3 or graph.get("directed") is True
                or any(v.get("label") not in (None, "") for v in vertices if isinstance(v,dict))
                or any(not isinstance(v, dict) or not isinstance(v.get("id"), (int,str)) for v in vertices)
                or any(not isinstance(e, dict) or e.get("weight") is not None
                       or e.get("edge_label") is not None or e.get("direction") not in ("undirected",None)
                       or e.get("style") not in (None,"solid","unknown")
                       for e in edges)
                or graph.get("stroke_inventory")):
            continue
        old_ids = [str(v["id"]) for v in vertices]
        if len(set(old_ids)) != len(old_ids):
            continue
        valid = set(old_ids)
        old_edges = [(str(e.get("from")),str(e.get("to"))) for e in edges]
        if any(u not in valid or v not in valid or u==v for u,v in old_edges):
            continue
        # Compare graph structure WITHOUT relying on arbitrary anonymous IDs.
        import networkx as nx
        observed = nx.Graph()
        observed.add_nodes_from(old_ids)
        observed.add_edges_from(old_edges)
        measured = nx.Graph()
        measured.add_nodes_from(v["id"] for v in pv)
        measured.add_edges_from((e["from"],e["to"]) for e in pe)
        if (len(observed.edges) != len(old_edges) or len(measured.edges) != len(pe)
                or nx.is_isomorphic(observed, measured)):
            continue
        # A change is justified only by a full independent straight-pixel
        # candidate of the SAME visible node and edge cardinality.
        id_map = {p["id"]: old_ids[j] for j,p in enumerate(pv)}
        for j, pixel_vertex in enumerate(pv):
            vertices[j]["x"], vertices[j]["y"] = pixel_vertex["x"], pixel_vertex["y"]
            vertices[j]["position"] = "original_1000"
        graph["edges"] = [{"id": f"pixel_e{n+1}", "from": id_map[e["from"]],
                            "to": id_map[e["to"]], "direction": "undirected",
                            "style": "solid"} for n, e in enumerate(pe)]
        changes.append({"graph_id": graph.get("id", f"G{index+1}"),
                        "method": "strict_rgb_colored_node_and_straight_line_reconciliation",
                        "vertices": len(pv), "edges": len(pe),
                        "image_accuracy_certified": False})
    return reviewed, changes


__all__ = ["measure_image_pixel_evidence", "create_grid_column_views",
           "create_grid_panel_views",
           "reconcile_anonymous_pixel_graphs"]
