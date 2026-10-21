"""Deterministic sanity checks for labeled textbook graph diagrams.

Only use explicitly transcribed complete edge lists. Degree-sum is tautological
for any typed edge list; connectivity and cycles must be computed separately.
The optional grid mapping is restricted to a visibly regular 2 x 3 arrangement
of filled vertices. A mismatch without reliable pixel evidence is uncertainty,
not an invented correction.
"""
from __future__ import annotations

import re

SECTION = re.compile(
    r"(?:图\s*(?:G\s*_?\{?\s*([1-9]\d*)\}?|([1-9]\d*))"
    r"|(?<![a-zA-Z])G\s*_?\{?([1-9]\d*)\}?)"
    r"\s*(?:[（(][^）)\n]{0,28}[）)])?\s*[:：]", re.I
)
EDGE_FIELD = re.compile(
    r"(?:边集合|边集|边)\s*(?:为|包括)?\s*[:：]\s*([^\n。；;]+)", re.I
)
SINGLE_EDGE = re.compile(r"([a-z])\s*[-—–－−]\s*([a-z])", re.I)
VERTEX_TAGS = re.compile(r"(?:标签|顶点)\s*[:：]?\s*((?:[a-z]\s*[,，、\s]\s*){2,}[a-z])", re.I)


def _parts(text):
    matches = list(SECTION.finditer(str(text or "")))
    return [(int(next(g for g in m.groups() if g is not None)), m.end(), matches[i+1].start() if i+1 < len(matches) else len(text))
            for i, m in enumerate(matches)]


def _edges(piece):
    field = EDGE_FIELD.search(piece)
    if not field:
        return None
    raw = field.group(1)
    found = SINGLE_EDGE.findall(raw)
    # Reject prose masquerading as an edge list and unexplained residue.
    residue = SINGLE_EDGE.sub("", raw)
    if not found or re.search(r"[a-zA-Z]", residue):
        return None
    return [tuple(sorted((a.lower(), b.lower()))) for a, b in found]


def _vertices(piece, edges):
    label = VERTEX_TAGS.search(piece)
    if label:
        names = re.findall(r"[a-z]", label.group(1).lower())
        if len(names) == len(set(names)) and len(names) >= 2:
            return names
    # No count+labels: cannot infer isolated vertices from an edge list.
    return None


def analyze_labeled_graphs(text):
    """Extract complete, explicit diagrams without guessing unseen vertices."""
    output = {}
    for no, start, end in _parts(text):
        part = text[start:end]
        edges = _edges(part)
        if edges is None:
            continue
        vertices = _vertices(part, edges)
        if vertices is None or any(u not in vertices or v not in vertices for u, v in edges):
            continue
        if len(edges) != len(set(edges)) or any(u == v for u, v in edges):
            # Multigraphs/loops require a different model; not tree-eligible.
            continue
        components = _components(vertices, edges)
        output[no] = {
            "vertices": vertices, "edges": edges, "edge_count": len(edges),
            "components": components, "tree": components == 1 and len(edges) == len(vertices)-1,
        }
    return output


def _components(vertices, edges):
    parents = {v:v for v in vertices}
    def root(v):
        while parents[v] != v:
            parents[v] = parents[parents[v]]
            v = parents[v]
        return v
    for a, b in edges:
        parents[root(a)] = root(b)
    return len({root(v) for v in vertices})


def summarize_tree_question(text):
    if not re.search(r"(?:哪些|哪几个|哪一个|什么|是否|判断|是).{0,7}树|树.{0,6}(?:图|判断)", text):
        return ""
    diagrams = analyze_labeled_graphs(text)
    # Require at least two separately numbered, explicit, complete graphs.
    if len(diagrams) < 2:
        return ""
    lines = []
    trees = []
    for no, item in sorted(diagrams.items()):
        is_tree = item["tree"]
        if is_tree:
            trees.append(f"G{no}")
        lines.append(
            f"G{no}: 顶点{len(item['vertices'])}个、边{item['edge_count']}条、"
            f"连通分量{item['components']}个，{'是' if is_tree else '不是'}树。"
        )
    return "\n".join(lines) + "\n因此是树的图：" + ("、".join(trees) if trees else "没有") + "。"


def _two_column_three_row_labels(graph):
    vertices = graph.get("vertices") or []
    if (graph.get("confidence") != "high" or graph.get("uncertain_edges")
            or len(vertices) != 6):
        return None
    try:
        points = [(str(p["id"]), float(p["x"]), float(p["y"])) for p in vertices]
        if len({p[0] for p in points}) != 6:
            return None
        ordered = sorted(points, key=lambda p:p[2])
        rows = [sorted(ordered[i:i+2], key=lambda p:p[1]) for i in (0,2,4)]
        span_x = max(p[1] for p in points)-min(p[1] for p in points)
        span_y = max(p[2] for p in points)-min(p[2] for p in points)
        if span_x <= 0 or span_y <= 0:
            return None
        # Only a very clear 2-column by 3-row grid with a stable left/right
        # correspondence is eligible for automatic a..f labeling.
        if any(abs(row[0][2]-row[1][2]) > .12 * span_y for row in rows):
            return None
        if min((sum(p[2] for p in rows[i+1])/2 - sum(p[2] for p in rows[i])/2)
               for i in (0,1)) < .27 * span_y:
            return None
        if any(abs(row[0][1]-rows[0][0][1]) > .13 * span_x or
               abs(row[1][1]-rows[0][1][1]) > .13 * span_x for row in rows):
            return None
        if any(row[1][1]-row[0][1] < .7*span_x for row in rows):
            return None
        return {row[col][0]:chr(97+2*i+col)
                for i,row in enumerate(rows) for col in (0,1)}
    except (ValueError, TypeError, KeyError, IndexError):
        return None


def reconcile_vision_edges(visual_text, opencv_graphs):
    """Cross-check Vision edge endpoints against high-confidence pixel paths.

    Never fix a graph when its label placement is not the standard 2x3 layout
    or OCR has not explicitly named a,b,c,d,e,f in that diagram. Return a
    summary of mismatches for non-silent UI and manual review.
    """
    corrected = str(visual_text or "")
    if not corrected or not isinstance(opencv_graphs, list):
        return corrected, []
    warnings = []
    sections = _parts(corrected)
    for no, start, end in reversed(sections):
        if no < 1 or no > len(opencv_graphs):
            continue
        candidate = opencv_graphs[no-1]
        mapping = _two_column_three_row_labels(candidate)
        if not mapping:
            continue
        part = corrected[start:end]
        if set(_vertices(part, []) or []) != set("abcdef"):
            continue
        match = EDGE_FIELD.search(part)
        vision_edges = _edges(part)
        if match is None or vision_edges is None:
            continue
        cv_edges = candidate.get("edges") or []
        try:
            confirmed = {tuple(sorted((mapping[a], mapping[b])))
                         for a,b in cv_edges}
        except (KeyError, TypeError, ValueError):
            continue
        if len(confirmed) != len(cv_edges):
            continue
        seen = set(vision_edges)
        # A repeated undirected edge such as d-e plus e-d is still a
        # transcription error even when its UNIQUE set matches the pixels.
        # Never let a duplicate silently survive a perfect-set shortcut.
        if seen == confirmed and len(vision_edges) == len(seen):
            continue
        # Preserve the same labels but supply the geometrically confirmed
        # connections. Only this narrowly-checked six-dot case is correctable.
        normalized = "、".join(a+"-"+b for a,b in sorted(confirmed))
        corrected = (corrected[:start+match.start(1)] + normalized
                     + corrected[start+match.end(1):])
        warnings.append(f"G{no}：视觉模型的边端点与图像连续线段不一致，"
                        "已按严格两列三行顶点布局重新核对边集。")
    return corrected, warnings
