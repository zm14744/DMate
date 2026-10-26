"""Source-conditioned edge readings, with instance-aware endpoint reconciliation.

This module does not inspect gold, infer degrees, execute a model, or certify
image accuracy. Agreement is a useful reading check, not a proof of correctness.
"""
from __future__ import annotations

import copy
import math
import re
from collections import Counter, defaultdict
from decimal import Decimal

from graph_semantic_schema import MAX_EDGES, MAX_GRAPHS, MAX_VERTICES


SOURCE_READ_PROMPT = """只根据原图读取任务 source_ids 中每个源顶点的边。完整 vertices 清单只用于找点和引用端点；position/x/y 是粗略辅助，不能代替原图。不要猜测原图是否属于某种标准图，不用度数、连通性或预期边数补删边。
有向边只列从该源顶点出发的箭头；指向源顶点的入边不要在此源重复列出。无向边在两个端点各自的读取中都要列出。平行边逐条列出，即使属性相同也不能合成一条；每个自环在该源下列一次。没有出边或无向邻边时 edges=[]，不能省略此 source。
线型契约：未声明特殊线型、style 字段缺省或为 null，表示普通实线（solid）；虚线或点线必须明确写 dashed/dotted。若确实看不清线型，请显式写 unknown，不能用缺省表示看不清。
返回 {"sources":[{"id":"任务中真实源ID","edges":[{"to":"完整清单中的端点ID","direction":"forward或undirected","weight":null,"edge_label":null,"color":"原图颜色","style":"solid/dashed/dotted"}]}]}。印刷边名与权值分开。只填写原图可见内容，看不清用 unknown 并留给最终复核；不要填写候选ID、路径、证据框或正确答案。"""

_ATTRS = ("weight", "edge_label", "color", "style")
_UNKNOWN = {"unknown", "未知", "不确定", "不清楚", "uncertain"}
_COLORS = {"红": "red", "红色": "red", "蓝": "blue", "蓝色": "blue",
           "黑": "black", "黑色": "black", "白": "white", "白色": "white",
           "绿": "green", "绿色": "green", "黄": "yellow", "黄色": "yellow",
           "紫": "purple", "紫色": "purple", "橙": "orange", "橙色": "orange",
           "灰": "gray", "灰色": "gray", "grey": "gray"}
_STYLES = {"实线": "solid", "虚线": "dashed", "点线": "dotted"}


def _id(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        value = str(value)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _inventory(draft):
    if not isinstance(draft, dict) or not isinstance(draft.get("graphs"), list):
        raise ValueError("source_reading_invalid_graph_inventory")
    if len(draft["graphs"]) > MAX_GRAPHS:
        raise ValueError("source_reading_graph_capacity")
    document = copy.deepcopy(draft)
    graphs = {}
    for index, graph in enumerate(document["graphs"], 1):
        if not isinstance(graph, dict):
            raise ValueError("source_reading_invalid_graph")
        gid = _id(graph.get("id")) or f"G{index}"
        if gid in graphs:
            raise ValueError("source_reading_duplicate_graph_id")
        vertices = graph.get("vertices")
        if not isinstance(vertices, list) or len(vertices) > MAX_VERTICES:
            raise ValueError("source_reading_invalid_vertices")
        ids = set()
        reserved = {_id(v.get("id")) for v in vertices if isinstance(v, dict)} - {None}
        for number, vertex in enumerate(vertices, 1):
            if not isinstance(vertex, dict):
                raise ValueError("source_reading_invalid_vertex")
            vid = _id(vertex.get("id"))
            if vid is None:
                vid, suffix = f"v{number}", 1
                while vid in reserved or vid in ids:
                    vid = f"v{number}_{suffix}"
                    suffix += 1
            if vid in ids:
                raise ValueError("source_reading_duplicate_vertex_id")
            vertex["id"] = vid
            ids.add(vid)
        graph["id"] = gid
        graphs[gid] = graph
    return document, graphs


def source_batches(draft, max_sources=6):
    """Project each graph's full vertex inventory, never its initial edges."""
    if isinstance(max_sources, bool) or not isinstance(max_sources, int) or not 1 <= max_sources <= MAX_VERTICES:
        raise ValueError("source_reading_invalid_batch_size")
    _, graphs = _inventory(draft)
    batches = []
    for gid, graph in graphs.items():
        vertices = []
        for vertex in graph["vertices"]:
            record = {"id": vertex["id"]}
            for key in ("label", "position"):
                value = vertex.get(key)
                if value is None or isinstance(value, str):
                    if key in vertex:
                        record[key] = value
                elif key == "label" and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                    record[key] = value
            for key in ("x", "y"):
                value = vertex.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                    record[key] = value
            vertices.append(record)
        ids = [v["id"] for v in vertices]
        for start in range(0, len(ids), max_sources):
            batches.append({"graph_id": gid, "graph_name": graph.get("name") if isinstance(graph.get("name"), str) else gid,
                            "vertices": copy.deepcopy(vertices), "source_ids": ids[start:start + max_sources]})
    return batches


def _issue(issues, gid, kind, message, **details):
    result = {"scope": "graph", "graph_id": gid, "kind": kind, "message": message, **details}
    issues.append(result)
    return result


def _resolve(value, graph):
    reference = _id(value)
    ids = {v["id"] for v in graph["vertices"]}
    if reference in ids:
        return reference
    matches = [v["id"] for v in graph["vertices"] if v.get("label") is not None and v.get("label") == value]
    return matches[0] if len(matches) == 1 else None


def _attributes(raw):
    result, problems = {}, []
    for key in _ATTRS:
        if key not in raw:
            continue
        value = raw[key]
        if value is None:
            result[key] = None
            continue
        valid = (not isinstance(value, bool) and isinstance(value, (str, int, float))
                 and (not isinstance(value, float) or math.isfinite(value)))
        if not valid or (key in ("color", "style") and not isinstance(value, str)):
            result[key] = "unknown"
            problems.append(key)
            continue
        if isinstance(value, str):
            token = value.strip().lower()
            if token in _UNKNOWN:
                value = "unknown"
                problems.append(key)
            elif key == "color":
                value = _COLORS.get(token, token if token in {
                    "red", "blue", "black", "white", "green", "yellow", "purple", "orange", "gray"
                } else value)
            elif key == "style":
                value = _STYLES.get(token, token if token in {"solid", "dashed", "dotted"} else value)
        elif key == "edge_label":
            value = str(value)
        result[key] = value
    return result, problems


def _signature(edge):
    # Only clear decimal spellings are equivalent to JSON numbers. Arbitrary
    # expressions are never evaluated; the selected original value survives.
    values = []
    for key in _ATTRS:
        value = edge.get(key)
        if key == "style" and value is None:
            # This is a declared response default, not two observed style
            # measurements. Explicit unknown/dashed/dotted remain distinct.
            value = "solid"
        decimal_text = (isinstance(value, str) and len(value) <= 128
                        and re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", value.strip()))
        if key == "weight" and (isinstance(value, (int, float)) or decimal_text):
            values.append(("number", Decimal(str(value).strip())))
        else:
            values.append((type(value).__name__, value))
    return tuple(values)


def _pair(edge):
    return tuple(sorted((edge["from"], edge["to"])))


def _draft_edges(graph, issues):
    by_pair, unusable = defaultdict(list), []
    edges = graph.get("edges", [])
    if not isinstance(edges, list):
        _issue(issues, graph["id"], "invalid_draft_edges", "初稿边列表无效，须原图复核。")
        return by_pair, []
    for edge in edges[:MAX_EDGES]:
        if isinstance(edge, dict):
            a, b = _resolve(edge.get("from"), graph), _resolve(edge.get("to"), graph)
            if a is not None and b is not None:
                record = copy.deepcopy(edge)
                record.update({"from": a, "to": b})
                by_pair[_pair(record)].append(record)
                continue
        unusable.append(copy.deepcopy(edge))
    if unusable or len(edges) > MAX_EDGES:
        _issue(issues, graph["id"], "unresolved_draft_edges", "初稿仍有端点无效或超容量的边，不能默默删除。")
    # Preserve unresolved records for the semantic adapter's explicit issues.
    unusable.extend(copy.deepcopy(edges[MAX_EDGES:]))
    return by_pair, unusable


def merge_source_readings(draft, readings):
    """Merge independent outgoing lists, preserving unresolved pair drafts.

    A pair commits only when all relevant undirected instances agree in both
    endpoint readings. Conflicting pairs retain their complete draft list;
    without a draft, one observed side is retained, never the sum of both.
    All alternatives and the decision remain in source_audit. A source with
    no outgoing/undirected edges is a valid explicit empty reading.
    """
    document, graphs = _inventory(draft)
    if not isinstance(readings, list):
        raise ValueError("source_readings_must_be_list")
    issues, received, bad_sources = [], defaultdict(dict), defaultdict(set)
    observations = defaultdict(list)
    style_defaults = defaultdict(Counter)
    for batch_index, batch in enumerate(readings):
        if not isinstance(batch, dict) or _id(batch.get("graph_id")) not in graphs:
            gid = _id(batch.get("graph_id")) if isinstance(batch, dict) else None
            _issue(issues, gid or "unknown", "unknown_reading_graph", "读取结果未对应已列图，未合并。", batch_index=batch_index)
            continue
        gid, graph = _id(batch["graph_id"]), graphs[_id(batch["graph_id"]) ]
        valid_ids = {v["id"] for v in graph["vertices"]}
        assigned = batch.get("source_ids")
        if (not isinstance(assigned, list) or not assigned or any(_id(x) not in valid_ids for x in assigned)
                or len({_id(x) for x in assigned}) != len(assigned)):
            _issue(issues, gid, "invalid_source_scope", "批次源节点清单无效，未合并。", batch_index=batch_index)
            continue
        assigned = [_id(x) for x in assigned]
        response = batch.get("response")
        sources = response.get("sources") if isinstance(response, dict) else None
        if not isinstance(sources, list) or len(sources) > MAX_VERTICES:
            bad_sources[gid].update(assigned)
            _issue(issues, gid, "invalid_source_response", "该批次未返回可用 sources 列表。", source_ids=assigned)
            continue
        for source in sources:
            sid = _id(source.get("id")) if isinstance(source, dict) else None
            if sid not in assigned:
                _issue(issues, gid, "unexpected_source", "响应包含非本批次源节点，未采用其边。", source_id=sid)
                continue
            if sid in received[gid]:
                bad_sources[gid].add(sid)
                _issue(issues, gid, "duplicate_source_reading", "同一源节点被读取多次，不能选择或叠加结果。", source_id=sid)
                continue
            raw_edges = source.get("edges")
            received[gid][sid] = []
            if not isinstance(raw_edges, list) or len(raw_edges) > MAX_EDGES:
                bad_sources[gid].add(sid)
                _issue(issues, gid, "invalid_source_edges", "源节点边表无效或超容量。", source_id=sid)
                continue
            for edge_index, raw in enumerate(raw_edges):
                target = _resolve(raw.get("to"), graph) if isinstance(raw, dict) else None
                if target is None:
                    bad_sources[gid].add(sid)
                    _issue(issues, gid, "invalid_source_endpoint", "边端点未唯一对应本图顶点，保留初稿待复核。",
                           source_id=sid, edge_index=edge_index,
                           reference=str(raw.get("to"))[:160] if isinstance(raw, dict) else None)
                    continue
                attributes, unknown_fields = _attributes(raw)
                if raw.get("style") is None:
                    style_defaults[gid][sid] += 1
                direction = raw.get("direction")
                if direction not in ("forward", "undirected"):
                    direction = "unknown"
                    unknown_fields.append("direction")
                edge = {"from": sid, "to": target, "direction": direction, **attributes}
                received[gid][sid].append(edge)
                observations[gid].append(copy.deepcopy(edge))
                if unknown_fields:
                    _issue(issues, gid, "uncertain_source_attributes", "边的方向或属性仍未读清。",
                           source_id=sid, target_id=target, fields=unknown_fields)
                    edge["_unresolved"] = True
    audit = {"version": "semantic-source-readings/1", "graphs": [], "agreement_is_not_image_certification": True}
    for gid, graph in graphs.items():
        ids = [v["id"] for v in graph["vertices"]]
        missing = [sid for sid in ids if sid not in received[gid]]
        for sid in missing:
            bad_sources[gid].add(sid)
            _issue(issues, gid, "missing_source_reading", "此源节点没有独立边表，须最终视觉复核。", source_id=sid)
        old_pairs, unusable = _draft_edges(graph, issues)
        new_pairs = defaultdict(lambda: defaultdict(list))
        for sid in ids:
            for edge in received[gid].get(sid, []):
                new_pairs[_pair(edge)][sid].append(edge)
        pair_order = list(new_pairs) + [pair for pair in old_pairs if pair not in new_pairs]
        merged, pair_audit = [], []
        for pair in pair_order:
            a, b = pair
            sides = new_pairs[pair]
            left, right = sides.get(a, []), sides.get(b, [])
            unresolved = any(e.get("_unresolved") for side in sides.values() for e in side)
            blocked = a in bad_sources[gid] or b in bad_sources[gid]
            directed = [e for sid in pair if sid in sides for e in sides[sid] if e["direction"] == "forward"]
            if a == b:
                directed = [e for e in left if e["direction"] == "forward"]
                undirected = [e for e in left if e["direction"] == "undirected"]
                compatible = True
            else:
                undirected = [e for e in left if e["direction"] == "undirected"]
                opposite = [e for e in right if e["direction"] == "undirected"]
                counts_left, counts_right = Counter(map(_signature, undirected)), Counter(map(_signature, opposite))
                compatible = counts_left == counts_right
            if not blocked and not unresolved and compatible:
                selected = directed + undirected
                decision = "source_lists_agree" if selected else "absent_in_complete_source_readings"
            else:
                if not compatible:
                    _issue(issues, gid, "undirected_instance_mismatch",
                           "无向边两端读到的实例数量或属性不一致，未叠加为新平行边。",
                           vertex_ids=list(pair), left_count=len(undirected), right_count=len(opposite))
                if old_pairs.get(pair):
                    selected, decision = old_pairs[pair], "retained_draft_pair"
                else:
                    selected = left if len(left) >= len(right) else right
                    decision = "retained_one_side_candidates"
            clean = [{k: copy.deepcopy(v) for k, v in edge.items() if k != "_unresolved"} for edge in selected]
            merged.extend(clean)
            pair_audit.append({"vertex_ids": list(pair), "decision": decision,
                               "left_count": len(left), "right_count": len(right) if a != b else None,
                               "output_instances": len(clean), "confirmed_by_readings": not blocked and not unresolved and compatible,
                               "readings": [copy.deepcopy(e) for side in sides.values() for e in side]})
        merged.extend(unusable)
        graph["edges"] = merged
        # Stable identities only: preserve fallback IDs; never turn an ID into
        # an edge label and never deduplicate by endpoint identity.
        used = set()
        for index, edge in enumerate(merged, 1):
            if not isinstance(edge, dict):
                continue
            eid = _id(edge.get("id"))
            if eid is None or eid in used:
                eid = f"source_edge_{index}"
                while eid in used:
                    eid += "_"
            edge["id"] = eid
            used.add(eid)
        graph_issues = [x for x in issues if x.get("graph_id") == gid]
        audit["graphs"].append({"graph_id": gid, "required_source_ids": ids,
                                "received_source_ids": [sid for sid in ids if sid in received[gid]],
                                "missing_source_ids": missing, "invalid_source_ids": sorted(bad_sources[gid]),
                                "status": "needs_visual_review" if graph_issues else "readings_reconciled",
                                "style_default": {"rule": "missing_or_null_means_ordinary_solid",
                                                  "explicit_measurement": False,
                                                  "source_edge_counts": dict(style_defaults[gid])},
                                "pairs": pair_audit, "observations": observations[gid]})
    uncertainties = document.get("uncertainties", [])
    if not isinstance(uncertainties, list):
        uncertainties = [uncertainties] if uncertainties else []
    document["uncertainties"] = copy.deepcopy(uncertainties) + [copy.deepcopy(x) for x in issues if x["graph_id"] in graphs]
    return {"document": document, "issues": issues, "source_audit": audit}


__all__ = ["SOURCE_READ_PROMPT", "source_batches", "merge_source_readings"]
