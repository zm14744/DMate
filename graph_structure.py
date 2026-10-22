"""Bounded, topology-aware candidate path evidence for Qwen.

The traces are pixel hypotheses, never certified edges. Spend the prompt budget
on paths absent from the existing CV edge table, then on confirmed paths; rotate
across panels so one dense diagram cannot hide later diagrams.
"""
from __future__ import annotations

import json
import math


def _pair(edge):
    if isinstance(edge, dict):
        a, b = edge.get("from", edge.get("source")), edge.get("to", edge.get("target"))
    elif isinstance(edge, (list, tuple)) and len(edge) == 2:
        a, b = edge
    else:
        return None
    if a is None or b is None:
        return None
    return tuple(sorted((str(a), str(b))))


def compact_line_evidence(cv_result, *, max_graphs=8, max_per_graph=18, max_chars=3000):
    """Return small JSON-safe hypotheses, prioritizing new edges on all panels."""
    if not isinstance(cv_result, dict):
        return []
    raw_graphs = cv_result.get("graphs") or []
    confirmed = {}
    for graph in raw_graphs:
        if isinstance(graph, dict):
            confirmed[str(graph.get("id", ""))] = {
                pair for edge in graph.get("edges") or []
                if (pair := _pair(edge)) is not None
            }

    panels = []
    for panel in (cv_result.get("line_path_evidence") or [])[:max_graphs]:
        if not isinstance(panel, dict):
            continue
        graph_id = str(panel.get("id") or "")
        items = []
        seen = set()
        for trace in panel.get("paths") or []:
            if not isinstance(trace, dict):
                continue
            pair = _pair(trace)
            if pair is None:
                continue
            # The tracer can preserve multiple truly distinct strokes with
            # identical endpoints. Only skip duplicate path variants.
            variant = trace.get("path_variant", 0)
            try:
                variant = max(0, min(5, int(variant)))
            except (ValueError, TypeError):
                variant = 0
            unique = (pair, variant)
            if unique in seen:
                continue
            seen.add(unique)
            try:
                score = float(trace.get("score", 0))
            except (TypeError, ValueError, OverflowError):
                continue
            if not math.isfinite(score):
                continue
            coords = []
            for point in trace.get("path") or []:
                if not isinstance(point, (list, tuple)) or len(point) != 2:
                    continue
                try:
                    x, y = float(point[0]), float(point[1])
                except (TypeError, ValueError):
                    continue
                if math.isfinite(x) and math.isfinite(y) and 0 <= x <= 1 and 0 <= y <= 1:
                    coords.append([round(x, 4), round(y, 4)])
            if len(coords) > 6:
                coords = [coords[round(i * (len(coords) - 1) / 5)] for i in range(6)]
            novel = pair not in confirmed.get(graph_id, set())
            items.append((not novel, -score, {
                "from": pair[0], "to": pair[1],
                "path_variant": variant,
                "path_samples": coords,
                "pixel_score": round(score, 3),
                "new_candidate": novel,
                "candidate_only": True,
            }))
        items.sort(key=lambda row: (row[0], row[1]))
        if items:
            panels.append({"id": graph_id, "items": [row[2] for row in items[:max_per_graph]]})

    result = [{"id": panel["id"], "paths": []} for panel in panels]
    if not result or len(json.dumps(result, ensure_ascii=False)) > max_chars:
        return []
    # Round-robin provides coverage when four or six independent diagrams share
    # one request. Never silently spend the whole budget on the first graph.
    for index in range(max_per_graph):
        for position, panel in enumerate(panels):
            if index >= len(panel["items"]):
                continue
            trial = [{"id": entry["id"], "paths": entry["paths"][:]} for entry in result]
            trial[position]["paths"].append(panel["items"][index])
            if len(json.dumps(trial, ensure_ascii=False)) <= max_chars:
                result = trial
    return [panel for panel in result if panel["paths"]]


__all__ = ["compact_line_evidence"]
