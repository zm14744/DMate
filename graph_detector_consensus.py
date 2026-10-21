"""Conservative topology reconciliation between independent CPU pixel detectors.

The detectors use different geometric evidence and may enumerate identical
vertices in different orders.  Only *geometrically aligned* edges can be
compared.  A disagreement is uncertainty, never proof of an additional edge.
No model downloads, external calls, or new runtime dependencies.
"""
from __future__ import annotations

from copy import deepcopy
import math


def _vertices(graph):
    found = graph.get("vertices") or []
    try:
        result = [(str(v["id"]), float(v["x"]), float(v["y"])) for v in found]
    except (ValueError, TypeError, KeyError):
        return None
    if len(result) < 3 or len(set(v[0] for v in result)) != len(result):
        return None
    return result


def _match_vertices(first, second, *, tolerance=0.026):
    """Map each secondary vertex ID to a primary vertex ID using image positions."""
    a, b = _vertices(first), _vertices(second)
    if a is None or b is None or len(a) != len(b):
        return None
    distances = sorted(
        (math.hypot(x - u, y - v), first_id, second_id)
        for first_id, x, y in a for second_id, u, v in b
    )
    mapping, used = {}, set()
    for distance, primary_id, secondary_id in distances:
        if distance > tolerance:
            break
        if primary_id not in used and secondary_id not in mapping:
            mapping[secondary_id] = primary_id
            used.add(primary_id)
    return mapping if len(mapping) == len(a) else None


def _edge_set(graph, mapping=None, *, key="edges"):
    vertices = _vertices(graph)
    if vertices is None:
        return None
    ids = {v[0] for v in vertices}
    edges = set()
    for edge in graph.get(key) or []:
        if not isinstance(edge, (list, tuple)) or len(edge) != 2:
            return None
        a, b = str(edge[0]), str(edge[1])
        if a not in ids or b not in ids:
            return None
        if mapping is not None:
            a, b = mapping[a], mapping[b]
        edges.add(tuple(sorted((a, b))))
    return edges


def _same_picture(a, b):
    """Require substantial spatial overlap before interpreting node count conflicts."""
    try:
        x1, y1, x2, y2 = map(float, a["bbox"])
        u1, v1, u2, v2 = map(float, b["bbox"])
    except (KeyError, TypeError, ValueError):
        return False
    intersection = max(0., min(x2, u2) - max(x1, u1)) * max(
        0., min(y2, v2) - max(y1, v1)
    )
    area_a, area_b = (x2 - x1) * (y2 - y1), (u2 - u1) * (v2 - v1)
    return area_a > 0 and area_b > 0 and intersection / min(area_a, area_b) > .45


def _component_count(vertices, edges):
    ids = [str(vertex["id"]) for vertex in vertices]
    parent = {vertex: vertex for vertex in ids}

    def root(vertex):
        while parent[vertex] != vertex:
            parent[vertex] = parent[parent[vertex]]
            vertex = parent[vertex]
        return vertex

    for a, b in edges:
        parent[root(a)] = root(b)
    return len({root(vertex) for vertex in ids})


def _downgrade(source, message):
    result = deepcopy(source)
    graph = result["graphs"][0]
    graph["confidence"] = "partial"
    graph["detector_agreement"] = "disagreement"
    result["status"] = "partial"
    result["warning"] = (
        (result.get("warning") or "") + " " + message
    ).strip()
    return result


def reconcile_pixel_detectors(primary, secondary):
    """Use intersection of independently confirmed edges if both see the same graph.

    A multi-panel detection is never overwritten by a single-graph detector.
    If image coordinates cannot be matched, avoid fabricated correspondences.
    """
    graphs_a, graphs_b = primary.get("graphs") or [], secondary.get("graphs") or []
    if len(graphs_a) != 1 or len(graphs_b) != 1:
        return primary
    first, second = graphs_a[0], graphs_b[0]
    if first.get("directed") not in (None, "unknown", False):
        return primary
    if second.get("directed") not in (None, "unknown", False):
        return primary

    mapping = _match_vertices(first, second)
    if mapping is None:
        va, vb = _vertices(first), _vertices(second)
        if (va is not None and vb is not None and len(va) != len(vb)
                and _same_picture(first, second)):
            return _downgrade(
                primary, "OpenCV 两种检测方法识别的顶点数量不同，未确认完整图结构。"
            )
        return primary

    edges_a = _edge_set(first)
    edges_b = _edge_set(second, mapping)
    unknown_a = _edge_set(first, key="uncertain_edges")
    unknown_b = _edge_set(second, mapping, key="uncertain_edges")
    if any(x is None for x in (edges_a, edges_b, unknown_a, unknown_b)):
        return _downgrade(primary, "OpenCV 检测器边数据格式不一致，需要视觉复核。")
    if edges_a == edges_b and unknown_a == unknown_b == set():
        result = deepcopy(primary)
        result["graphs"][0]["detector_agreement"] = "matching"
        result["detector"] = "independent_pixel_detectors_agree"
        return result

    # Only edges independently confirmed by both methods remain 'confirmed'.
    common = edges_a & edges_b
    disputed = (edges_a ^ edges_b) | unknown_a | unknown_b
    disputed -= common
    result = _downgrade(
        primary, "OpenCV 原像素检测与实心点检测存在边集分歧，争议边交由 Vision 核对。"
    )
    graph = result["graphs"][0]
    vertex_order = [str(v["id"]) for v in graph["vertices"]]
    indexes = {vertex: i for i, vertex in enumerate(vertex_order)}
    edges = sorted(common, key=lambda e: (indexes[e[0]], indexes[e[1]]))
    graph["edges"] = [list(e) for e in edges]
    graph["confirmed_edge_count"] = len(edges)
    graph["uncertain_edges"] = [
        list(e) for e in sorted(disputed, key=lambda e: (indexes[e[0]], indexes[e[1]]))
    ]
    matrix = [[0] * len(vertex_order) for _ in vertex_order]
    for a, b in edges:
        matrix[indexes[a]][indexes[b]] = 1
        matrix[indexes[b]][indexes[a]] = 1
    graph["adjacency_matrix"] = matrix
    graph["component_count_of_confirmed_edges"] = _component_count(graph["vertices"], edges)
    result["detector"] = "independent_pixel_detectors_disagree"
    return result


__all__ = ["reconcile_pixel_detectors"]
