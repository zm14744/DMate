"""Adapt reviewed, visible graph content to the existing display records.

Coordinates, routes, marker IDs and pixel proofs are not acceptance inputs.
An adapter can check references and preserve uncertainty; it cannot certify
agreement with an image. ``reviewed`` therefore belongs to the caller, never
to the model's JSON. The legacy ``canonical_graph`` completeness/type gates
are intentionally not reused: mixed directions and partially weighted graphs
can have fully specified per-edge semantics.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from graph_schema import SCHEMA_VERSION, parallel_key, unit, path_points
from graph_edge_labels import separate_graph_edge_labels


SEMANTIC_SCHEMA_VERSION = "dmate.semantic/1"
MAX_GRAPHS = 64
MAX_VERTICES = 100
MAX_EDGES = 300
MAX_UNCERTAINTIES = 256
_EDGE_FIELDS = ("id", "from", "to", "direction", "weight", "edge_label", "color", "style")
_MISSING = object()


def _identifier(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        value = str(value)
    if isinstance(value, str) and value.strip() and len(value.strip()) <= 64:
        return value.strip()
    return None


def _visible_text(value):
    """Keep case, subscripts, Unicode and numeric text; do not guess labels."""
    if value is None:
        return None
    if isinstance(value, str):
        return value if value.strip() else None
    if isinstance(value, bool):
        raise ValueError("boolean is not visible text")
    if isinstance(value, int) or (isinstance(value, float) and math.isfinite(value)):
        return str(value)
    raise ValueError("invalid visible text")


def _safe_value(value, depth=0):
    """Keep bounded, JSON-safe rejected semantics, without auxiliary images."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {"invalid_number": str(value)}
    if depth >= 3:
        return {"invalid_type": type(value).__name__}
    if isinstance(value, (list, tuple)):
        return [_safe_value(x, depth + 1) for x in value[:16]]
    if isinstance(value, dict):
        return {str(k): _safe_value(v, depth + 1) for k, v in list(value.items())[:16]}
    return {"invalid_type": type(value).__name__}


def _raw_edge(item):
    if not isinstance(item, dict):
        return _safe_value(item)
    return {key: _safe_value(item[key]) for key in _EDGE_FIELDS if key in item}


def _unique_id(preferred, prefix, index, used, reserved):
    if preferred is not None and preferred not in used:
        used.add(preferred)
        return preferred
    value = f"{prefix}{index}"
    suffix = 1
    while value in used or value in reserved:
        value = f"{prefix}{index}_{suffix}"
        suffix += 1
    used.add(value)
    return value


def _issue(issues, scope, kind, message, *, graph_id=None, **details):
    item = {"scope": scope, "kind": kind, "message": message}
    if graph_id is not None:
        item["graph_id"] = graph_id
    item.update(details)
    issues.append(item)
    return item


def _endpoint(value, aliases, labels, generated_aliases):
    if value is _MISSING or value is None:
        return None, "missing_endpoint"
    try:
        text = _visible_text(value)
    except ValueError:
        return None, "invalid_endpoint"
    if text is None:
        return None, "missing_endpoint"
    # An explicit ID takes precedence over a label. A duplicated source ID
    # remains ambiguous even after internal IDs have been made unique.
    matches = aliases.get(_identifier(value), [])
    if not matches:
        matches = labels.get(text, [])
    if not matches:
        matches = generated_aliases.get(_identifier(value), [])
    if len(matches) == 1:
        return matches[0], None
    return None, "ambiguous_endpoint" if matches else "unknown_endpoint"


def _normalize_graph(source, graph_id, issues, notes):
    graph = {
        "schema_version": SCHEMA_VERSION, "id": graph_id, "name": graph_id,
        "vertices": [], "edges": [], "uncertain_edges": [], "complete": False,
        "directed": "unknown", "weighted": "unknown", "multigraph": "unknown",
        "unresolved_edges": [], "unresolved_vertices": [],
    }
    try:
        graph["name"] = _visible_text(source.get("name")) or graph_id
    except ValueError:
        _issue(issues, "graph", "invalid_graph_name", "图名称不是可读文本。", graph_id=graph_id)
    box = source.get('bbox')
    if isinstance(source.get('visual_description'), str) and len(source['visual_description']) <= 800:
        graph['visual_description'] = source['visual_description']
    if (isinstance(box, list) and len(box) == 4 and all(unit(n) is not None for n in box)
            and unit(box[0]) < unit(box[2]) and unit(box[1]) < unit(box[3])):
        graph['bbox'] = [unit(n) for n in box]
    if isinstance(source.get('anon_next'), int) and not isinstance(source['anon_next'], bool) and 1 <= source['anon_next'] <= 10000:
        graph['anon_next'] = source['anon_next']
    raw_nodes = source.get("vertices")
    if not isinstance(raw_nodes, list):
        _issue(issues, "graph", "invalid_vertex_inventory", "vertices 必须是顶点列表。", graph_id=graph_id)
        raw_nodes = []
    elif not raw_nodes:
        _issue(issues, "graph", "empty_vertex_inventory", "此图没有列出任何顶点。", graph_id=graph_id)
    if len(raw_nodes) > MAX_VERTICES:
        _issue(issues, "graph", "vertex_capacity_exceeded", "顶点数量超出本次适配容量，未声称完整。",
               graph_id=graph_id, omitted_count=len(raw_nodes) - MAX_VERTICES)
    raw_nodes = raw_nodes[:MAX_VERTICES]
    reserved = {_identifier(v.get("id")) for v in raw_nodes if isinstance(v, dict)} - {None}
    used, aliases, labels = set(), defaultdict(list), defaultdict(list)
    generated_aliases = defaultdict(list)
    for index, item in enumerate(raw_nodes, 1):
        if not isinstance(item, dict):
            _issue(issues, "graph", "invalid_vertex", "顶点记录必须是对象。", graph_id=graph_id, source_index=index)
            graph["unresolved_vertices"].append({"source_index": index, "record": _safe_value(item)})
            continue
        original_id = _identifier(item.get("id"))
        vertex_id = _unique_id(original_id, "v", index, used, reserved)
        if original_id is not None:
            aliases[original_id].append(vertex_id)
        if original_id != vertex_id:
            generated_aliases[vertex_id].append(vertex_id)
        if original_id != vertex_id:
            notes.append({"kind": "vertex_id_assigned", "graph_id": graph_id,
                          "source_index": index, "vertex_id": vertex_id})
        try:
            label = _visible_text(item.get("label"))
        except ValueError:
            label = None
            _issue(issues, "graph", "invalid_vertex_label", "顶点标签不是可读文本。",
                   graph_id=graph_id, vertex_id=vertex_id)
            graph["unresolved_vertices"].append({"source_index": index, "vertex_id": vertex_id,
                                                "record": {"label": _safe_value(item.get("label"))}})
        vx, vy = unit(item.get('x')), unit(item.get('y'))
        vertex = {'id': vertex_id, 'label': label, 'x': vx, 'y': vy,
                  'isolated_confirmed': False}
        if isinstance(item.get('display_label'), str) and 0 < len(item['display_label']) <= 16:
            vertex['display_label'] = item['display_label']
        if isinstance(item.get('position_description'), str) and 0 < len(item['position_description']) <= 160:
            vertex['position_description'] = item['position_description']
        graph['vertices'].append(vertex)
        if label is not None:
            labels[label].append(vertex_id)
    raw_edges = source.get("edges")
    if not isinstance(raw_edges, list):
        _issue(issues, "graph", "invalid_edge_inventory", "edges 必须是边列表；没有边时使用空列表。", graph_id=graph_id)
        raw_edges = []
    if len(raw_edges) > MAX_EDGES:
        _issue(issues, "graph", "edge_capacity_exceeded", "边数量超出本次适配容量，未声称完整。",
               graph_id=graph_id, omitted_count=len(raw_edges) - MAX_EDGES)
    raw_edges = raw_edges[:MAX_EDGES]
    reserved_edges = {_identifier(e.get("id")) for e in raw_edges if isinstance(e, dict)} - {None}
    used_edges, observed_directions = set(), set()
    for index, item in enumerate(raw_edges, 1):
        preferred = _identifier(item.get("id")) if isinstance(item, dict) else None
        edge_id = _unique_id(preferred, "e", index, used_edges, reserved_edges)
        if not isinstance(item, dict):
            observed_directions.add("unknown")
            _issue(issues, "graph", "invalid_edge", "边记录必须是对象。", graph_id=graph_id, edge_id=edge_id)
            graph["unresolved_edges"].append({"id": edge_id, "source_index": index, "record": _raw_edge(item)})
            continue
        if preferred != edge_id:
            notes.append({"kind": "edge_id_assigned", "graph_id": graph_id,
                          "source_index": index, "edge_id": edge_id})
        start = len(issues)
        endpoints = {}
        for end in ("from", "to"):
            reference = item.get(end, _MISSING)
            endpoints[end], problem = _endpoint(reference, aliases, labels, generated_aliases)
            if problem:
                shown = None if reference is _MISSING else _safe_value(reference)
                _issue(issues, "graph", problem,
                       f"边 {edge_id} 的 {end} 端点不能唯一对应已列顶点：{str(shown)[:160]}。",
                       graph_id=graph_id, edge_id=edge_id, endpoint=end, reference=shown)
        direction = item.get("direction", _MISSING)
        if direction is _MISSING:
            declared = source.get("directed")
            direction = "forward" if declared is True else "undirected" if declared is False else "unknown"
        if direction not in ("forward", "undirected"):
            direction = "unknown"
            _issue(issues, "graph", "unknown_direction", f"边 {edge_id} 的方向尚未确定。",
                   graph_id=graph_id, edge_id=edge_id)
        observed_directions.add(direction)
        weight = item.get("weight")
        if (isinstance(weight, bool) or (weight is not None and not isinstance(weight, (str, int, float)))
                or (isinstance(weight, float) and not math.isfinite(weight))):
            _issue(issues, "graph", "invalid_weight", f"边 {edge_id} 的权值不是有限数值或文字。",
                   graph_id=graph_id, edge_id=edge_id)
            weight = None
        elif isinstance(weight, str) and not weight.strip():
            weight = None
        try:
            edge_label = _visible_text(item.get("edge_label"))
        except ValueError:
            edge_label = None
            _issue(issues, "graph", "invalid_edge_label", f"边 {edge_id} 的边名不是可读文本。",
                   graph_id=graph_id, edge_id=edge_id)
        attributes = {}
        for key in ("color", "style"):
            value = item.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                value = "unknown"
            elif not isinstance(value, str):
                _issue(issues, "graph", f"invalid_{key}", f"边 {edge_id} 的 {key} 不是文字。",
                       graph_id=graph_id, edge_id=edge_id)
                value = "unknown"
            if key == "style":
                value = {"实线": "solid", "solid": "solid", "虚线": "dashed", "dashed": "dashed",
                         "点线": "dotted", "dotted": "dotted"}.get(value.strip().lower(), value)
            attributes[key] = value
        if len(issues) != start:
            graph["unresolved_edges"].append({"id": edge_id, "source_index": index,
                                              "record": _raw_edge(item),
                                              "issue_kinds": [x["kind"] for x in issues[start:]]})
        if endpoints["from"] is None or endpoints["to"] is None:
            continue
        graph["edges"].append({"id": edge_id, **endpoints, "direction": direction,
                               "weight": weight, "edge_label": edge_label, **attributes,
                               "multiplicity": 1, "parallel_count": 1, "path": path_points(item.get('path')),
                               "status": "pending", "evidence": []})
        if isinstance(item.get('edge_label_is_explicit'), bool):
            graph['edges'][-1]['edge_label_is_explicit'] = item['edge_label_is_explicit']
    edges = graph["edges"]
    for change in separate_graph_edge_labels(graph):
        notes.append({**change, 'graph_id': graph_id})
    directions = observed_directions
    if directions == {"forward"}:
        graph["directed"] = True
    elif directions == {"undirected"}:
        graph["directed"] = False
    elif directions == {"forward", "undirected"}:
        graph["direction_mode"] = "mixed"
    elif not directions and isinstance(source.get("directed"), bool):
        graph["directed"] = source["directed"]
    graph["weighted"] = any(e["weight"] is not None for e in edges)
    counts = Counter(parallel_key(e) for e in edges)
    for edge in edges:
        edge["parallel_count"] = counts[parallel_key(edge)]
    known_counts = Counter(parallel_key(e) for e in edges if e["direction"] != "unknown")
    graph["multigraph"] = any(n > 1 for n in known_counts.values()) or any(e["from"] == e["to"] for e in edges)
    # Redundant graph flags cannot contradict or erase explicit edge content.
    # If unresolved records could affect a negative conclusion, keep unknown.
    if graph["unresolved_edges"]:
        if not graph["weighted"]:
            graph["weighted"] = "unknown"
        if not graph["multigraph"]:
            graph["multigraph"] = "unknown"
    for key in ("directed", "weighted", "multigraph"):
        if isinstance(source.get(key), bool) and source[key] != graph[key]:
            notes.append({"kind": "graph_type_derived", "graph_id": graph_id,
                          "field": key, "declared": source[key], "derived": graph[key]})
    from graph_presentation import prepare_graph_presentation
    return prepare_graph_presentation(graph)


def _uncertainties(value, graph_aliases, issues):
    if value is None:
        return
    if isinstance(value, (str, dict)):
        value = [value]
    if not isinstance(value, list):
        _issue(issues, "document", "invalid_uncertainties", "uncertainties 必须是文字或问题对象列表。")
        return
    if len(value) > MAX_UNCERTAINTIES:
        _issue(issues, "document", "uncertainty_capacity_exceeded", "未确定问题超出本次适配容量。",
               omitted_count=len(value) - MAX_UNCERTAINTIES)
    for item in value[:MAX_UNCERTAINTIES]:
        if isinstance(item, str) and item.strip():
            _issue(issues, "document", "model_uncertainty", item)
            continue
        if not isinstance(item, dict):
            _issue(issues, "document", "invalid_uncertainty", "未确定问题缺少可读说明。")
            continue
        message = item.get("message", item.get("reason", item.get("description")))
        if not isinstance(message, str) or not message.strip():
            _issue(issues, "document", "invalid_uncertainty", "未确定问题缺少可读说明。")
            continue
        scope = item.get("scope") if item.get("scope") in ("body", "graph", "document") else "document"
        kind = item.get("kind") if isinstance(item.get("kind"), str) and item["kind"].strip() else "model_uncertainty"
        graph_id = None
        if scope == "graph":
            matches = graph_aliases.get(_identifier(item.get("graph_id")), [])
            if len(matches) != 1:
                _issue(issues, "document", "unresolved_uncertainty_scope", message,
                       referenced_graph_id=_safe_value(item.get("graph_id")))
                continue
            graph_id = matches[0]
        _issue(issues, scope, kind, message, graph_id=graph_id)


def normalize_semantic_document(payload, *, reviewed=False):
    """Return display-compatible graphs, body text and scoped semantic issues.

    Required model fields are ``body_text`` (possibly ``""``), ``graphs`` and
    each graph's explicit ``vertices``/``edges`` lists. Node and edge IDs may
    be omitted. Edge endpoints must resolve to an ID or one exact label.
    Direction is per edge (``forward``/``undirected``/``unknown``); a missing
    direction may inherit an actual boolean graph ``directed`` field. Absent
    label/weight means no printed label/weight; ``uncertainties`` expresses
    unreadable content rather than fabricating a value.

    Rejected edge semantics remain in ``unresolved_edges`` and issues, while
    renderable edges always reference existing vertices. No node is invented
    to repair an invalid endpoint. Caller review plus local semantic validity
    controls acceptance; payload status/complete/evidence fields are ignored.
    """
    issues, notes, graphs, graph_aliases = [], [], [], defaultdict(list)
    body_text = ""
    if not isinstance(payload, dict):
        _issue(issues, "document", "invalid_document", "识别结果必须是对象。")
    else:
        if isinstance(payload.get("body_text"), str):
            body_text = payload["body_text"]
        else:
            _issue(issues, "body", "invalid_body_text", "body_text 必须是正文字符串；没有正文时使用空字符串。")
        sources = payload.get("graphs")
        if not isinstance(sources, list):
            _issue(issues, "document", "invalid_graph_inventory", "graphs 必须是图列表；纯正文时使用空列表。")
            sources = []
        if len(sources) > MAX_GRAPHS:
            _issue(issues, "document", "graph_capacity_exceeded", "图数量超出本次适配容量，未声称完整。",
                   omitted_count=len(sources) - MAX_GRAPHS)
        sources = sources[:MAX_GRAPHS]
        reserved = {_identifier(g.get("id")) for g in sources if isinstance(g, dict)} - {None}
        used = set()
        for index, source in enumerate(sources, 1):
            if not isinstance(source, dict):
                _issue(issues, "document", "invalid_graph", "图记录必须是对象。", source_index=index)
                continue
            original_id = _identifier(source.get("id"))
            graph_id = _unique_id(original_id, "G", index, used, reserved)
            graph_aliases[original_id or graph_id].append(graph_id)
            if original_id != graph_id:
                notes.append({"kind": "graph_id_assigned", "source_index": index, "graph_id": graph_id})
            graphs.append(_normalize_graph(source, graph_id, issues, notes))
        _uncertainties(payload.get("uncertainties"), graph_aliases, issues)
        if not graphs and not body_text.strip() and not issues:
            _issue(issues, "document", "empty_document", "没有可供显示的正文或图结构。")
    is_reviewed = reviewed is True
    document_issues = [x for x in issues if x["scope"] == "document"]
    for graph in graphs:
        graph_issues = [x for x in issues if x.get("graph_id") == graph["id"] and x["scope"] == "graph"]
        graph["semantic_issues"] = graph_issues
        graph["uncertain_edges"] = [x["message"] for x in graph_issues]
        graph["complete"] = is_reviewed and not document_issues and not graph_issues
        generic_graph_issues = any("edge_id" not in x for x in graph_issues)
        pending_ids = {x["edge_id"] for x in graph_issues if "edge_id" in x}
        for edge in graph["edges"]:
            accepted = is_reviewed and not document_issues and not generic_graph_issues and edge["id"] not in pending_ids
            edge["status"] = "accepted" if accepted else "pending"
        incident = {e[end] for e in graph["edges"] for end in ("from", "to")}
        for vertex in graph["vertices"]:
            vertex["isolated_confirmed"] = graph["complete"] and vertex["id"] not in incident
    body_complete = is_reviewed and not document_issues and not any(x["scope"] == "body" for x in issues)
    return {"semantic_schema_version": SEMANTIC_SCHEMA_VERSION,
            "graphs": graphs, "body_text": body_text, "body_complete": body_complete,
            "semantic_issues": issues, "normalization_notes": notes,
            "reviewed": is_reviewed, "complete": is_reviewed and not issues,
            "body_audit": {"second_pass_reviewed": is_reviewed, "semantic_issues": [
                x for x in issues if x["scope"] in ("body", "document")]},
            "diagnostics": [f"semantic:{x['scope']}:{x['kind']}:{x['message']}" for x in issues]}


__all__ = ["normalize_semantic_document", "SEMANTIC_SCHEMA_VERSION"]
