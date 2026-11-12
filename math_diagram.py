"""Generate validated, editable mathematical diagrams for DMate.

The model interprets the request. Deterministic code constructs finite structures;
the browser-side Graphviz layout only supplies coordinates.
"""
from __future__ import annotations

import json
import math
import re
import threading

import networkx as nx
import requests
from jsonschema import Draft202012Validator

from server_i18n import localized, normalize_language


MAX_REQUIREMENT = 1500
MAX_RESPONSE = 24000
MAX_VERTICES = 80
MAX_EDGES = 240
_ACTIVE = threading.BoundedSemaphore(2)


class MathDiagramError(ValueError):
    def __init__(self, code, message, *, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


_PROMPT = """你是 DMate 的数学图结构解析器。你只负责把用户的自然语言绘图要求转换为结构化数学数据，不负责绘图，不输出 DOT、SVG、HTML、Markdown 或表格。

只允许以下四种 kind：
1. graph：图论中的普通图、有向图、带权图、树、完全图、二部图、路径、回路、连通结构、生成树等。
2. hasse：有限偏序集的哈斯图。vertices 给出元素，order_relations 给出用于定义偏序的严格小于关系边；只需给出能确定关系的边，程序会检查有向无环性并计算传递约简。
3. cyclic_cayley：循环群 Z_n 的 Cayley 图。只输出 modulus 和 generators，群元素及边由程序根据模 n 加法计算。
4. cyclic_subgroup_lattice：循环群 Z_n 的子群格。只输出 modulus，程序根据 n 的因数计算全部子群及包含关系。
5. ideal_lattice_zn：交换环 Z_n 的理想格。只输出 modulus，程序根据 n 的因数计算全部理想及包含关系。
6. zero_divisor_graph：交换环 Z_n 的零因子图。只输出 modulus，非零零因子及相邻关系由程序根据模 n 乘法计算。

不要生成集合韦恩图、简单集合包含示意图、映射示意图、任何运算表，也不要把纯定义或定理画成装饰性插图。若请求不属于上述类型，kind 使用 unsupported，并在 reason 中简短说明。

必须只返回一个 JSON 对象，字段如下：
{
  "kind": "graph | hasse | cyclic_cayley | zero_divisor_graph | unsupported",
  "title": "简短图名",
  "directed": false,
  "weighted": false,
  "vertices": [{"id":"v1","label":"A"}],
  "edges": [{"from":"v1","to":"v2","direction":"undirected","weight":null,"edge_label":null}],
  "order_relations": [["v1","v2"]],
  "modulus": 6,
  "generators": [1],
  "reason": ""
}
未使用的字段可以省略；如果输出 null，也只用于未使用的可选字段。

字段使用规则：
- graph：必须提供 vertices 和 edges。顶点 id 使用简短、唯一的 ASCII 标识符；label 是显示文字。每条边的 from/to 必须引用已声明的顶点。direction 只能是 forward 或 undirected。若 weighted=true，每条边必须提供 weight。不要猜测题目没有给出的顶点、边、方向或权值；若用户要求的是一个标准图族，可以按该图族的数学定义构造。
- hasse：必须提供 vertices 和 order_relations。关系对 [a,b] 表示 a 严格小于 b。不要加入自反关系。不要把可传递的关系误当成覆盖关系；程序会计算传递约简。
- cyclic_cayley：modulus 为 2 到 24 的整数，generators 是 Z_n 中能生成整个循环群的非零整数生成元。生成元按模 n 解释。
- cyclic_subgroup_lattice：modulus 为 2 到 30 的整数，表示加法群 Z_n。程序根据 n 的正因数生成子群，并按实际包含关系计算哈斯边。
- ideal_lattice_zn：modulus 为 2 到 30 的整数，表示交换环 Z_n。程序根据 n 的正因数生成全部理想，并按实际包含关系计算哈斯边。
- zero_divisor_graph：modulus 为 4 到 30 的合数，表示交换环 Z_n。程序会排除 0，并按 xy ≡ 0 (mod n) 计算不同非零零因子之间的边。
- 不允许附加解释文字。不要输出未经用户要求的其他图形。
- 若题目条件不足以唯一确定图结构，使用 unsupported，不要自行补造数学条件。"""


_MODEL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "title"],
    "properties": {
        "kind": {"enum": ["graph", "hasse", "cyclic_cayley", "cyclic_subgroup_lattice", "ideal_lattice_zn", "zero_divisor_graph", "unsupported"]},
        "title": {"type": "string", "minLength": 1, "maxLength": 80},
        "directed": {"type": ["boolean", "null"]},
        "weighted": {"type": ["boolean", "null"]},
        "vertices": {
            "type": ["array", "null"], "maxItems": MAX_VERTICES,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["id", "label"],
                "properties": {
                    "id": {"type": "string", "minLength": 1, "maxLength": 32},
                    "label": {"type": "string", "minLength": 1, "maxLength": 80},
                },
            },
        },
        "edges": {
            "type": ["array", "null"], "maxItems": MAX_EDGES,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["from", "to"],
                "properties": {
                    "from": {"type": "string", "minLength": 1, "maxLength": 32},
                    "to": {"type": "string", "minLength": 1, "maxLength": 32},
                    "direction": {"enum": ["forward", "undirected"]},
                    "weight": {"type": ["string", "number", "null"]},
                    "edge_label": {"type": ["string", "null"]},
                },
            },
        },
        "order_relations": {
            "type": ["array", "null"], "maxItems": 2000,
            "items": {
                "type": "array", "minItems": 2, "maxItems": 2,
                "items": {"type": "string", "minLength": 1, "maxLength": 32},
            },
        },
        "modulus": {"type": ["integer", "null"], "minimum": 2, "maximum": 30},
        "generators": {
            "type": ["array", "null"], "minItems": 1, "maxItems": 8,
            "items": {"type": "integer"},
        },
        "reason": {"type": ["string", "null"], "maxLength": 300},
    },
}
_MODEL_VALIDATOR = Draft202012Validator(_MODEL_SCHEMA)


_ERRORS_EN = {
    "请描述需要生成的数学图。": "Describe the mathematical diagram you want to generate.",
    "绘图要求不能超过1500字。": "The drawing request cannot exceed 1,500 characters.",
    "数学图生成服务繁忙，请稍后重试。": "The diagram generator is busy. Please try again later.",
    "数学图生成暂时不可用，请稍后重试。": "The diagram generator is temporarily unavailable.",
    "模型没有返回有效的数学图结构，请调整描述后重试。": "The model did not return a valid mathematical diagram. Refine the request and try again.",
    "该数学结构暂不支持自动生成。": "This mathematical structure is not supported yet.",
    "图形顶点编号重复或格式无效。": "Vertex IDs are duplicated or invalid.",
    "图形顶点标签无效。": "A vertex label is invalid.",
    "边引用了不存在的顶点。": "An edge references a missing vertex.",
    "边方向与图类型不一致。": "An edge direction conflicts with the graph type.",
    "带权图的每条边都必须提供权值。": "Every edge in a weighted graph must have a weight.",
    "图形超过当前原型的规模限制。": "The diagram exceeds this prototype's size limit.",
    "哈斯图关系包含自反关系或未知元素。": "The Hasse relation contains a reflexive pair or an unknown element.",
    "哈斯图关系存在有向环，不构成偏序结构。": "The Hasse relation contains a directed cycle and is not a partial order.",
    "生成元不能生成整个循环群。": "The supplied generators do not generate the whole cyclic group.",
    "循环群的生成元无效。": "The cyclic-group generators are invalid.",
    "Z_n 必须是合数，才能构造非零零因子图。": "Z_n must be composite to construct a nonzero zero-divisor graph.",
    "AI 返回内容不完整，请重试。": "The AI response was incomplete. Please try again.",
}


def _localize_error(error, language):
    error.message = localized(error.message, _ERRORS_EN.get(error.message, error.message), language)
    error.args = (error.message,)
    return error


def _normalize_request(payload):
    language = normalize_language(payload.get("language") if isinstance(payload, dict) else None)
    if not isinstance(payload, dict) or set(payload) - {"requirement", "language"}:
        raise MathDiagramError("invalid_math_diagram_request", "请描述需要生成的数学图。")
    requirement = payload.get("requirement")
    if not isinstance(requirement, str) or not requirement.strip():
        raise MathDiagramError("empty_math_diagram_request", "请描述需要生成的数学图。")
    if len(requirement) > MAX_REQUIREMENT:
        raise MathDiagramError("math_diagram_request_too_large", "绘图要求不能超过1500字。", status=413)
    return requirement.strip(), language


def _parse_model_result(response):
    if not isinstance(response, dict) or response.get("ok") is not True:
        raise MathDiagramError("math_diagram_unavailable", "数学图生成暂时不可用，请稍后重试。", status=503)
    choice = response.get("choice")
    if isinstance(choice, dict) and choice.get("finish_reason") == "length":
        raise MathDiagramError("math_diagram_truncated", "AI 返回内容不完整，请重试。", status=502)
    content = response.get("content")
    if not isinstance(content, str) or not content.strip() or len(content) > MAX_RESPONSE:
        raise MathDiagramError("invalid_math_diagram_response", "模型没有返回有效的数学图结构，请调整描述后重试。", status=502)
    try:
        value = json.loads(content)
    except (ValueError, TypeError) as exc:
        raise MathDiagramError("invalid_math_diagram_json", "模型没有返回有效的数学图结构，请调整描述后重试。", status=502) from exc
    if next(_MODEL_VALIDATOR.iter_errors(value), None):
        raise MathDiagramError("invalid_math_diagram_schema", "模型没有返回有效的数学图结构，请调整描述后重试。", status=502)
    return value


def _title(spec):
    title = spec.get("title")
    if not isinstance(title, str) or not title.strip():
        raise MathDiagramError("invalid_math_diagram_title", "模型没有返回有效的数学图结构，请调整描述后重试。", status=502)
    return title.strip()[:80]


def _vertices(spec):
    rows = spec.get("vertices")
    if not isinstance(rows, list) or not rows or len(rows) > MAX_VERTICES:
        raise MathDiagramError("invalid_math_diagram_vertices", "模型没有返回有效的数学图结构，请调整描述后重试。", status=502)
    vertices, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise MathDiagramError("invalid_math_diagram_vertices", "模型没有返回有效的数学图结构，请调整描述后重试。", status=502)
        vertex_id, label = row.get("id"), row.get("label")
        if not isinstance(vertex_id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", vertex_id) or vertex_id in seen:
            raise MathDiagramError("invalid_math_diagram_vertex_id", "图形顶点编号重复或格式无效。", status=502)
        if not isinstance(label, str) or not label.strip() or len(label) > 80 or any(ord(ch) < 32 for ch in label):
            raise MathDiagramError("invalid_math_diagram_vertex_label", "图形顶点标签无效。", status=502)
        seen.add(vertex_id)
        vertices.append({"id": vertex_id, "label": label.strip()})
    return vertices, seen


def _document(title, directed, weighted, vertices, edges):
    if len(vertices) > MAX_VERTICES or len(edges) > MAX_EDGES:
        raise MathDiagramError("math_diagram_too_large", "图形超过当前原型的规模限制。", status=413)
    return {
        "body_text": "",
        "graphs": [{
            "id": "G1",
            "name": title,
            "directed": bool(directed),
            "weighted": bool(weighted),
            "vertices": vertices,
            "edges": edges,
        }],
    }


def _build_graph(spec):
    vertices, vertex_ids = _vertices(spec)
    directed = spec.get("directed", False)
    weighted = spec.get("weighted", False)
    if not isinstance(directed, bool) or not isinstance(weighted, bool):
        raise MathDiagramError("invalid_math_diagram_type", "模型没有返回有效的数学图结构，请调整描述后重试。", status=502)
    rows = spec.get("edges")
    if not isinstance(rows, list) or len(rows) > MAX_EDGES:
        raise MathDiagramError("invalid_math_diagram_edges", "模型没有返回有效的数学图结构，请调整描述后重试。", status=502)
    edges = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict) or row.get("from") not in vertex_ids or row.get("to") not in vertex_ids:
            raise MathDiagramError("invalid_math_diagram_endpoint", "边引用了不存在的顶点。", status=502)
        direction = row.get("direction", "forward" if directed else "undirected")
        if direction not in ("forward", "undirected") or (directed and direction != "forward") or (not directed and direction != "undirected"):
            raise MathDiagramError("invalid_math_diagram_edge_direction", "边方向与图类型不一致。", status=502)
        edge = {"id": "e" + str(index), "from": row["from"], "to": row["to"], "direction": direction}
        weight = row.get("weight")
        if weighted:
            if isinstance(weight, bool) or not isinstance(weight, (str, int, float)) or isinstance(weight, float) and not math.isfinite(weight) or str(weight).strip() == "":
                raise MathDiagramError("missing_math_diagram_weight", "带权图的每条边都必须提供权值。", status=502)
            edge["weight"] = weight
        elif weight is not None:
            if isinstance(weight, bool) or not isinstance(weight, (str, int, float)) or isinstance(weight, float) and not math.isfinite(weight):
                raise MathDiagramError("invalid_math_diagram_weight", "模型没有返回有效的数学图结构，请调整描述后重试。", status=502)
            edge["weight"] = weight
        label = row.get("edge_label")
        if label is not None:
            if not isinstance(label, str) or len(label) > 80:
                raise MathDiagramError("invalid_math_diagram_edge_label", "模型没有返回有效的数学图结构，请调整描述后重试。", status=502)
            if label:
                edge["edge_label"] = label
        edges.append(edge)
    return _document(_title(spec), directed, weighted, vertices, edges), "graph"


def _build_hasse(spec):
    vertices, vertex_ids = _vertices(spec)
    relations = spec.get("order_relations")
    if not isinstance(relations, list) or len(relations) > 2000:
        raise MathDiagramError("invalid_hasse_relations", "模型没有返回有效的数学图结构，请调整描述后重试。", status=502)
    order = nx.DiGraph()
    order.add_nodes_from(vertex_ids)
    seen = set()
    for pair in relations:
        if not isinstance(pair, list) or len(pair) != 2:
            raise MathDiagramError("invalid_hasse_relation", "模型没有返回有效的数学图结构，请调整描述后重试。", status=502)
        lower, upper = pair
        if lower not in vertex_ids or upper not in vertex_ids or lower == upper:
            raise MathDiagramError("invalid_hasse_relation", "哈斯图关系包含自反关系或未知元素。", status=502)
        if (lower, upper) not in seen:
            order.add_edge(lower, upper)
            seen.add((lower, upper))
    if not nx.is_directed_acyclic_graph(order):
        raise MathDiagramError("invalid_hasse_order", "哈斯图关系存在有向环，不构成偏序结构。", status=422)
    # Whether the model supplied covers or all comparable pairs, the unique
    # transitive reduction of this DAG is the Hasse edge set.
    reduced = nx.transitive_reduction(order)
    edges = [
        {"id": "e" + str(index), "from": lower, "to": upper, "direction": "undirected"}
        for index, (lower, upper) in enumerate(sorted(reduced.edges()), 1)
    ]
    return _document(_title(spec), False, False, vertices, edges), "hasse"


def _build_cyclic_cayley(spec):
    modulus = spec.get("modulus")
    generators = spec.get("generators")
    if not isinstance(modulus, int) or isinstance(modulus, bool) or not 2 <= modulus <= 24:
        raise MathDiagramError("invalid_cyclic_modulus", "循环群的生成元无效。", status=502)
    if not isinstance(generators, list) or not generators or len(generators) > 8:
        raise MathDiagramError("invalid_cyclic_generators", "循环群的生成元无效。", status=502)
    normalized = []
    for value in generators:
        if not isinstance(value, int) or isinstance(value, bool):
            raise MathDiagramError("invalid_cyclic_generators", "循环群的生成元无效。", status=502)
        value %= modulus
        if value == 0 or value in normalized:
            raise MathDiagramError("invalid_cyclic_generators", "循环群的生成元无效。", status=502)
        normalized.append(value)
    if math.gcd(modulus, *normalized) != 1:
        raise MathDiagramError("cyclic_generators_do_not_generate", "生成元不能生成整个循环群。", status=422)
    vertices = [{"id": "v" + str(i), "label": str(i)} for i in range(modulus)]
    symmetric = all((-generator) % modulus in normalized for generator in normalized)
    edges, seen = [], set()
    for value in range(modulus):
        for generator in normalized:
            target = (value + generator) % modulus
            if symmetric:
                key = tuple(sorted((value, target)))
                if key in seen:
                    continue
                seen.add(key)
                edges.append({"id": "e" + str(len(edges) + 1), "from": "v" + str(key[0]),
                              "to": "v" + str(key[1]), "direction": "undirected"})
            else:
                edges.append({"id": "e" + str(len(edges) + 1), "from": "v" + str(value),
                              "to": "v" + str(target), "direction": "forward",
                              "edge_label": "+" + str(generator)})
    title = _title(spec)
    return _document(title, not symmetric, False, vertices, edges), "cyclic_cayley"


def _build_cyclic_lattice(spec, kind):
    modulus = spec.get("modulus")
    if not isinstance(modulus, int) or isinstance(modulus, bool) or not 2 <= modulus <= 30:
        raise MathDiagramError("invalid_lattice_modulus", "循环群或环的模数无效。", status=502)
    divisors = [value for value in range(1, modulus + 1) if modulus % value == 0]
    if kind == "cyclic_subgroup_lattice":
        vertices = [{"id": "d" + str(value), "label": "⟨" + str(value) + "⟩"} for value in divisors]
    else:
        vertices = [{"id": "d" + str(value), "label": "(" + str(value) + ")"} for value in divisors]
    relations = [
        ["d" + str(lower), "d" + str(upper)]
        for lower in divisors for upper in divisors
        if lower != upper and lower % upper == 0
    ]
    return _build_hasse({
        "title": _title(spec),
        "vertices": vertices,
        "order_relations": relations,
    })


def _build_zero_divisor_graph(spec):
    modulus = spec.get("modulus")
    if not isinstance(modulus, int) or isinstance(modulus, bool) or not 4 <= modulus <= 30 or all(modulus % p for p in range(2, int(math.sqrt(modulus)) + 1)):
        raise MathDiagramError("zero_divisor_modulus_not_composite", "Z_n 必须是合数，才能构造非零零因子图。", status=422)
    elements = [value for value in range(1, modulus) if math.gcd(value, modulus) > 1]
    vertices = [{"id": "v" + str(value), "label": str(value)} for value in elements]
    edges = []
    for index, left in enumerate(elements):
        for right in elements[index + 1:]:
            if (left * right) % modulus == 0:
                edges.append({"id": "e" + str(len(edges) + 1), "from": "v" + str(left),
                              "to": "v" + str(right), "direction": "undirected"})
    return _document(_title(spec), False, False, vertices, edges), "zero_divisor_graph"


def build_document(spec):
    kind = spec.get("kind")
    if kind == "unsupported":
        reason = str(spec.get("reason") or "").strip()
        message = reason[:300] if reason else "该数学结构暂不支持自动生成。"
        raise MathDiagramError("unsupported_math_diagram", message, status=422)
    if kind == "graph":
        return _build_graph(spec)
    if kind == "hasse":
        return _build_hasse(spec)
    if kind == "cyclic_cayley":
        return _build_cyclic_cayley(spec)
    if kind in ("cyclic_subgroup_lattice", "ideal_lattice_zn"):
        return _build_cyclic_lattice(spec, kind)
    if kind == "zero_divisor_graph":
        return _build_zero_divisor_graph(spec)
    raise MathDiagramError("unsupported_math_diagram", "该数学结构暂不支持自动生成。", status=422)


def generate_diagram(payload, *, completion=None):
    language = normalize_language(payload.get("language") if isinstance(payload, dict) else None)
    try:
        requirement, language = _normalize_request(payload)
        if not _ACTIVE.acquire(blocking=False):
            raise MathDiagramError("math_diagram_busy", "数学图生成服务繁忙，请稍后重试。", status=429)
        try:
            if completion is None:
                from ai import _request_text_completion
                completion = _request_text_completion
            try:
                response = completion(
                    [
                        {"role": "system", "content": _PROMPT},
                        {"role": "user", "content": requirement},
                    ],
                    retries=0,
                    reasoning_effort="none",
                    max_tokens=2500,
                    timeout=(8, 60),
                    response_format={"type": "json_object"},
                )
            except requests.Timeout as exc:
                raise MathDiagramError("math_diagram_timeout", "数学图生成暂时不可用，请稍后重试。", status=504) from exc
            except requests.RequestException as exc:
                raise MathDiagramError("math_diagram_connection_failed", "数学图生成暂时不可用，请稍后重试。", status=502) from exc
            spec = _parse_model_result(response)
            document, kind = build_document(spec)
            return {"ok": True, "kind": kind, "title": document["graphs"][0]["name"], "document": document}
        finally:
            _ACTIVE.release()
    except MathDiagramError as error:
        raise _localize_error(error, language)
