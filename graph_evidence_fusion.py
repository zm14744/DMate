"""Conservative evidence fusion for pixel-verified and Qwen graph topology.

Never replace model edges with CV hypotheses. Compare only coordinate-aligned
simple undirected graphs when independent CV pixel detectors explicitly agree.
Differences are advisory and should be displayed as unresolved uncertainty.
"""
from __future__ import annotations

import math

MAX_GRAPHS = 8
MAX_NODES = 40
MAX_DIFFS = 6


def _points(graph):
    found = graph.get("vertices") or []
    if not 2 <= len(found) <= MAX_NODES:
        return None
    pts = []
    try:
        for v in found:
            x, y = float(v["x"]), float(v["y"])
            if not (math.isfinite(x) and math.isfinite(y)
                    and 0 <= x <= 1 and 0 <= y <= 1):
                return None
            pts.append((str(v["id"]), x, y))
    except (TypeError, ValueError, KeyError):
        return None
    if len(set(v[0] for v in pts)) != len(pts):
        return None
    return pts


def _mapping(pixel_nodes, model_nodes, tolerance=0.032):
    """Bijective greedy correspondence, with a second-best margin requirement."""
    if len(pixel_nodes) != len(model_nodes):
        return None
    distances = sorted(
        (math.hypot(px - vx, py - vy), pi, vi)
        for pi, (_, px, py) in enumerate(pixel_nodes)
        for vi, (_, vx, vy) in enumerate(model_nodes)
    )
    candidates = {}
    for distance, pi, vi in distances:
        if distance > tolerance:
            continue
        candidates.setdefault(pi, []).append((distance, vi))
    if len(candidates) != len(pixel_nodes):
        return None
    # Ambiguous nearly-overlapping vertices cannot be safely aligned.
    for options in candidates.values():
        if len(options) > 1 and options[1][0] - options[0][0] < 0.006:
            return None
    pixel_to_model, used = {}, set()
    for distance, pi, vi in distances:
        if distance > tolerance:
            break
        if pi not in pixel_to_model and vi not in used:
            pixel_to_model[pi] = vi
            used.add(vi)
    if len(pixel_to_model) != len(pixel_nodes):
        return None
    return {pixel_nodes[pi][0]: model_nodes[vi][0]
            for pi, vi in pixel_to_model.items()}


def _edges(graph, mapping=None):
    vertices = {str(v["id"]) for v in graph.get("vertices", [])
                if isinstance(v, dict) and v.get("id") is not None}
    pairs = set()
    for item in graph.get("edges") or []:
        if isinstance(item, dict):
            a, b = item.get("from", item.get("source")), item.get("to", item.get("target"))
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            a, b = item
        else:
            return None
        a, b = str(a), str(b)
        if a not in vertices or b not in vertices or a == b:
            return None
        if mapping is not None:
            a, b = mapping.get(a), mapping.get(b)
            if a is None or b is None:
                return None
        pair = tuple(sorted((a, b)))
        if pair in pairs:
            return None
        pairs.add(pair)
    return pairs


def _can_compare(pixel, vision):
    if (pixel.get("directed") is True or vision.get("directed") is not False
            or pixel.get("multigraph") is True or vision.get("multigraph") is not False):
        return False
    if pixel.get("detector_agreement") != "matching":
        return False
    if pixel.get("uncertain_edges"):
        return False
    if vision.get("uncertain_edges") or vision.get("complete") is not True:
        return False
    return True


def compare_pixel_vision(cv_result, vision_graphs):
    """Return bounded textual issues; do not alter either graph or manufacture edges.

    Current scope deliberately excludes multi-panel matching, directed graphs,
    missing coordinate tables, self-loops and disputed CV edges.
    """
    if not isinstance(cv_result, dict) or not isinstance(vision_graphs, list):
        return []
    cv_graphs = cv_result.get("graphs") or []
    if len(cv_graphs) != 1 or len(vision_graphs) != 1:
        return []
    pixel, vision = cv_graphs[0], vision_graphs[0]
    if not isinstance(pixel, dict) or not isinstance(vision, dict):
        return []
    if not _can_compare(pixel, vision):
        return []
    p_nodes, v_nodes = _points(pixel), _points(vision)
    if p_nodes is None or v_nodes is None:
        return []
    mapping = _mapping(p_nodes, v_nodes)
    if mapping is None:
        return []
    cv_edges = _edges(pixel, mapping)
    vl_edges = _edges(vision)
    if cv_edges is None or vl_edges is None:
        return []
    diff = sorted(cv_edges ^ vl_edges)
    if not diff:
        return []
    from_pixels = cv_edges - vl_edges
    from_model = vl_edges - cv_edges
    def brief(values):
        return "、".join(f"{a}-{b}" for a, b in sorted(values)[:MAX_DIFFS])
    parts = []
    if from_pixels:
        parts.append("像素检测存在而视觉模型未确认：" + brief(from_pixels))
    if from_model:
        parts.append("视觉模型存在而像素检测未确认：" + brief(from_model))
    return ["OpenCV 与 Qwen 逐边结果存在分歧（仅供复核，不能直接判定任一方错误）：" +
            "；".join(parts)]


__all__ = ["compare_pixel_vision"]
