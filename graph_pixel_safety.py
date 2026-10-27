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


def measure_image_pixel_evidence(raw):
    """One CPU-only bounded snapshot; fail open without pretending success."""
    original, rgb = _image(raw)
    return {"source_sha256": hashlib.sha256(raw).hexdigest(),
            "grid": _colored_caption_grid(rgb),
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
           "reconcile_anonymous_pixel_graphs"]
