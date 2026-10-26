"""Compare visible readings, with bounded evidence for a final image review.

This is a comparison of two observations, not an image validator. Defaults
are used only in temporary comparison keys; original readings are never
rewritten, and agreement does not prove either observation correct.
"""
from __future__ import annotations

import copy
import math
import re
import time
from collections import Counter
from decimal import Decimal, InvalidOperation

from graph_semantic_schema import normalize_semantic_document


MAX_EDGE_EXAMPLES = 6
MAX_VERTEX_EXAMPLES = 8
MAX_TEXT_EXCERPT = 320
MAX_ISOMORPHISM_STATES = 20000
MAX_ISOMORPHISM_SECONDS = .08
_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,4})?\Z")
_EDGE_FIELDS = ("id", "from", "to", "direction", "weight", "edge_label", "color", "style")


def _ordinary_color(value):
    """The renderer omits ordinary black/default color, never red/blue."""
    if value is None:
        return "ordinary"
    key = value.strip().lower() if isinstance(value, str) else value
    if key in ("", "unknown", "default", "ordinary", "black", "黑", "黑色", "#000", "#000000"):
        return "ordinary"
    return {"红": "red", "红色": "red", "蓝": "blue", "蓝色": "blue",
            "绿色": "green", "绿": "green"}.get(key, key)


def _weight(value):
    # No parsing of expressions, eval, sympify, or precision-losing rounding.
    if isinstance(value, bool):
        return ("literal", str(value))
    numeric = isinstance(value, int) or isinstance(value, float) and math.isfinite(value)
    text = str(value) if numeric else value.strip() if isinstance(value, str) else None
    if text is not None and len(text) <= 160 and _DECIMAL.fullmatch(text):
        try:
            number = Decimal(text)
            if number.is_finite():
                return ("number", number)
        except InvalidOperation:
            pass
    return ("literal", value)


def _attributes(edge):
    return (edge.get("direction"), _weight(edge.get("weight")),
            edge.get("edge_label"), _ordinary_color(edge.get("color")), edge.get("style"))


def _comparable(payload):
    value = copy.deepcopy(payload)
    if isinstance(value, dict) and isinstance(value.get("graphs"), list):
        for graph in value["graphs"]:
            if not isinstance(graph, dict) or not isinstance(graph.get("edges"), list):
                continue
            for edge in graph["edges"]:
                if isinstance(edge, dict) and edge.get("style") in (None, ""):
                    edge["style"] = "solid"
    return normalize_semantic_document(value)


def _edge_key(edge, node_tokens):
    a, b = node_tokens[edge["from"]], node_tokens[edge["to"]]
    if edge.get("direction") == "undirected":
        a, b = sorted((a, b))
    return (a, b, _attributes(edge))


def _direct_equal(old, new):
    """Fast equality for unchanged internal references; IDs are not evidence."""
    left = {v["id"]: v.get("label") for v in old.get("vertices", [])}
    right = {v["id"]: v.get("label") for v in new.get("vertices", [])}
    if left != right:
        return False
    tokens = {identifier: ("id", identifier) for identifier in left}
    return Counter(_edge_key(e, tokens) for e in old.get("edges", [])) == Counter(
        _edge_key(e, tokens) for e in new.get("edges", []))


class _ComparisonLimit(Exception):
    pass


def _isomorphic(old, new):
    """Match labels and full edge instances, including anonymous vertices.

    Return None if the explicitly bounded search is inconclusive. A hash or
    degree sequence alone is never sufficient to certify equality.
    """
    if len(old.get("vertices", [])) != len(new.get("vertices", [])):
        return False
    if len(old.get("edges", [])) != len(new.get("edges", [])):
        return False
    if Counter(v.get("label") for v in old.get("vertices", [])) != Counter(
            v.get("label") for v in new.get("vertices", [])):
        return False
    if Counter(_attributes(e) for e in old.get("edges", [])) != Counter(
            _attributes(e) for e in new.get("edges", [])):
        return False
    import networkx as nx

    def network(graph):
        result = nx.MultiDiGraph()
        for v in graph.get("vertices", []):
            result.add_node(v["id"], label=v.get("label"))
        for edge in graph.get("edges", []):
            a, b = edge["from"], edge["to"]
            result.add_edge(a, b, semantic=_attributes(edge))
            if edge.get("direction") == "undirected" and a != b:
                result.add_edge(b, a, semantic=_attributes(edge))
        return result

    class BoundedMatcher(nx.algorithms.isomorphism.MultiDiGraphMatcher):
        def __init__(self, *args, **kwargs):
            self.states = 0
            self.deadline = time.monotonic() + MAX_ISOMORPHISM_SECONDS
            super().__init__(*args, **kwargs)

        def semantic_feasibility(self, a, b):
            self.states += 1
            if self.states > MAX_ISOMORPHISM_STATES or time.monotonic() > self.deadline:
                raise _ComparisonLimit
            return super().semantic_feasibility(a, b)

    matcher = BoundedMatcher(network(old), network(new),
        node_match=lambda a, b: a.get("label") == b.get("label"),
        edge_match=lambda a, b: Counter(x["semantic"] for x in a.values()) ==
                               Counter(x["semantic"] for x in b.values()))
    try:
        return matcher.is_isomorphic()
    except _ComparisonLimit:
        return None


def _report_tokens(old, new):
    """A local correspondence for examples; not an assertion of image identity."""
    old_counts = Counter(v.get("label") for v in old.get("vertices", []))
    new_counts = Counter(v.get("label") for v in new.get("vertices", []))
    old_ids = {v["id"]: v.get("label") for v in old.get("vertices", [])}
    new_ids = {v["id"]: v.get("label") for v in new.get("vertices", [])}
    def tokens(graph, side):
        result = {}
        for v in graph.get("vertices", []):
            identifier, label = v["id"], v.get("label")
            if label is not None and old_counts[label] == new_counts[label] == 1:
                token = ("label", label)
            elif identifier in old_ids and identifier in new_ids and old_ids[identifier] == new_ids[identifier]:
                token = ("local_id", identifier)
            else:
                token = (side, identifier)
            result[identifier] = token
        return result
    return tokens(old, "previous"), tokens(new, "proposed")


def _edge_examples(graph, tokens, remaining):
    labels = {v["id"]: v.get("label") for v in graph.get("vertices", [])}
    output = []
    for edge in graph.get("edges", []):
        key = _edge_key(edge, tokens)
        if remaining[key] <= 0:
            continue
        remaining[key] -= 1
        row = {field: copy.deepcopy(edge.get(field)) for field in _EDGE_FIELDS}
        row["from_label"], row["to_label"] = labels.get(edge["from"]), labels.get(edge["to"])
        output.append(row)
        if len(output) >= MAX_EDGE_EXAMPLES:
            break
    return output


def _excerpt(text, other):
    # Compare without whitespace but retain exact original characters in the
    # excerpt, including case, subscripts, negations and numbers.
    indices = [i for i, ch in enumerate(text) if not ch.isspace()]
    folded = "".join(text[i] for i in indices)
    other_folded = "".join(other.split())
    prefix = 0
    for a, b in zip(folded, other_folded):
        if a != b:
            break
        prefix += 1
    point = indices[prefix] if prefix < len(indices) else len(text)
    start = max(0, point - 96)
    end = min(len(text), start + MAX_TEXT_EXCERPT)
    return {"text": text[start:end], "start": start, "end": end,
            "total_characters": len(text), "truncated": start > 0 or end < len(text)}


def _vertex_examples(vertices, other):
    remaining = Counter(v["label"] for v in vertices) - Counter(v["label"] for v in other)
    changed, unchanged = [], []
    for vertex in vertices:
        if remaining[vertex["label"]] > 0:
            changed.append(vertex)
            remaining[vertex["label"]] -= 1
        else:
            unchanged.append(vertex)
    return (changed + unchanged)[:MAX_VERTEX_EXAMPLES]


def meaningful_review_changes(previous, current):
    """Return bounded semantic differences for one original-image review.

    No coordinates, paths, proof metadata, graph properties or private
    references are used. Node/edge IDs may be renamed. Visible vertex labels,
    graph names, directions and joint edge attributes remain significant.
    Unknown style is distinct from solid; an ordinary default color has no
    special rendered color, while red/blue remain significant.
    """
    before, after = _comparable(previous), _comparable(current)
    changes = []
    old_text, new_text = before.get("body_text", ""), after.get("body_text", "")
    if "".join(old_text.split()) != "".join(new_text.split()):
        changes.append({"scope": "body", "kind": "independent_body_reading_changed",
            "message": "两次题干读法不同。请对原图核对以下实际文字片段，尤其数字、字母、下标和否定词；片段不是参考答案。",
            "previous_excerpt": _excerpt(old_text, new_text),
            "proposed_excerpt": _excerpt(new_text, old_text)})
    old_graphs = {g["id"]: g for g in before["graphs"]}
    new_graphs = {g["id"]: g for g in after["graphs"]}
    for gid in sorted(old_graphs.keys() | new_graphs.keys()):
        old, new = old_graphs.get(gid, {}), new_graphs.get(gid, {})
        equal = _direct_equal(old, new)
        comparison = True if equal else _isomorphic(old, new)
        if comparison is True and old.get("name") == new.get("name"):
            continue
        left_tokens, right_tokens = _report_tokens(old, new)
        left = Counter(_edge_key(e, left_tokens) for e in old.get("edges", []))
        right = Counter(_edge_key(e, right_tokens) for e in new.get("edges", []))
        removed, added = (Counter(), Counter()) if comparison is True else (left - right, right - left)
        previous_edges = _edge_examples(old, left_tokens, removed.copy())
        proposed_edges = _edge_examples(new, right_tokens, added.copy())
        previous_vertices = [{"id": v["id"], "label": v.get("label")}
                             for v in old.get("vertices", [])]
        proposed_vertices = [{"id": v["id"], "label": v.get("label")}
                             for v in new.get("vertices", [])]
        label_changed = Counter(v["label"] for v in previous_vertices) != Counter(
            v["label"] for v in proposed_vertices)
        previous_ids = sorted({e[end] for e in previous_edges for end in ("from", "to")})
        proposed_ids = sorted({e[end] for e in proposed_edges for end in ("from", "to")})
        issue = {"scope": "graph", "graph_id": gid,
            "kind": "independent_reading_changed" if comparison is not None else "independent_reading_comparison_inconclusive",
            "message": "以下是两次实际读法的局部差异，请对原图逐条核对端点、箭头和属性；不能按边数或常见图形选择答案。",
            "previous_name": old.get("name"), "proposed_name": new.get("name"),
            "removed_or_changed_instances": sum(removed.values()),
            "added_or_changed_instances": sum(added.values()),
            "previous_edges": previous_edges, "proposed_edges": proposed_edges,
            "previous_vertex_ids": previous_ids, "proposed_vertex_ids": proposed_ids,
            "vertex_ids": proposed_ids,
            "example_representation": "normalized_observed_records",
            "comparison_defaults_are_not_measurements": True,
            "examples_omitted": {"previous_edges": max(0, sum(removed.values()) - len(previous_edges)),
                                 "proposed_edges": max(0, sum(added.values()) - len(proposed_edges))},
            "comparison_status": "bounded_inconclusive" if comparison is None else "different_readings"}
        if label_changed:
            shown_old = _vertex_examples(previous_vertices, proposed_vertices)
            shown_new = _vertex_examples(proposed_vertices, previous_vertices)
            issue.update(previous_vertices=shown_old,
                         proposed_vertices=shown_new,
                         previous_vertex_count=len(previous_vertices), proposed_vertex_count=len(proposed_vertices))
            issue["examples_omitted"].update(previous_vertices=max(0, len(previous_vertices)-MAX_VERTEX_EXAMPLES),
                                             proposed_vertices=max(0, len(proposed_vertices)-MAX_VERTEX_EXAMPLES))
            issue["vertex_ids"] = sorted(set(proposed_ids) | {v["id"] for v in shown_new})
        changes.append(issue)
    return changes


__all__ = ["meaningful_review_changes"]
