"""Generate validated, editable mathematical diagrams for DMate.

The model interprets the request. Deterministic code constructs finite structures;
the browser-side Graphviz layout only supplies coordinates.
"""
from __future__ import annotations

import json
import math
import re
import threading
import unicodedata

import networkx as nx
import requests
from jsonschema import Draft202012Validator

from server_i18n import localized, normalize_language


MAX_REQUIREMENT = 2000
MAX_RESPONSE = 40000
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

只允许以下六种 kind：
1. graph：图论中的普通图、有向图、带权图、树、完全图、二部图、路径、回路、连通结构、生成树等。
2. hasse：有限偏序集的哈斯图。vertices 给出元素，order_relations 给出用于定义偏序的严格小于关系边；只需给出能确定关系的边，程序会检查有向无环性并计算传递约简。
3. cyclic_cayley：循环群 Z_n 的 Cayley 图。只输出 modulus 和 generators，群元素及边由程序根据模 n 加法计算。
4. cyclic_subgroup_lattice：循环群 Z_n 的子群格。只输出 modulus，程序根据 n 的因数计算全部子群及包含关系。
5. ideal_lattice_zn：交换环 Z_n 的理想格。只输出 modulus，程序根据 n 的因数计算全部理想及包含关系。
6. zero_divisor_graph：交换环 Z_n 的零因子图。只输出 modulus，非零零因子及相邻关系由程序根据模 n 乘法计算。

不要生成集合韦恩图、简单集合包含示意图、映射示意图、任何运算表，也不要把纯定义或定理画成装饰性插图。若请求不属于上述类型，kind 使用 unsupported，并在 reason 中简短说明。

必须只返回一个 JSON 对象，字段如下：
{
  "kind": "graph | hasse | cyclic_cayley | cyclic_subgroup_lattice | ideal_lattice_zn | zero_divisor_graph | unsupported",
  "graph_family": "general | simple | complete | bipartite | complete_bipartite | tree | forest | path | cycle | regular | multigraph（仅 graph 使用）",
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
- graph：必须提供 graph_family、vertices 和 edges。顶点 id 使用简短、唯一的 ASCII 标识符；label 是显示文字。每条边的 from/to 必须引用已声明的顶点。direction 只能是 forward 或 undirected。若 weighted=true，每条边必须提供 weight；weighted=false 时不得输出权值。graph_family 必须准确描述图族，程序会对 simple、complete、bipartite、complete_bipartite、tree、forest、path、cycle、regular 做确定性校验。不要猜测题目没有给出的顶点、边、方向或权值；若用户要求的是一个标准图族，可以按该图族的数学定义构造。
- hasse：必须提供 vertices 和 order_relations。关系对 [a,b] 表示 a 严格小于 b。不要加入自反关系。不要把可传递的关系误当成覆盖关系；程序会计算传递约简。
- cyclic_cayley：modulus 为 2 到 24 的整数，generators 是 Z_n 中能生成整个循环群的非零整数生成元。生成元按模 n 解释。
- cyclic_subgroup_lattice：modulus 为 2 到 30 的整数，表示加法群 Z_n。程序根据 n 的正因数生成子群，并按实际包含关系计算哈斯边。
- ideal_lattice_zn：modulus 为 2 到 30 的整数，表示交换环 Z_n。程序根据 n 的正因数生成全部理想，并按实际包含关系计算哈斯边。
- zero_divisor_graph：modulus 为 4 到 30 的合数，表示交换环 Z_n。程序会排除 0，并按 xy ≡ 0 (mod n) 计算不同非零零因子之间的边。
- 不允许附加解释文字。不要输出未经用户要求的其他图形。
- 标题、顶点标签、边标签及 reason 应跟随用户描述所用的语言；保留数学符号与原始元素名称。
- 若题目条件不足以唯一确定图结构，使用 unsupported，不要自行补造数学条件。"""


_MODEL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "title"],
    "properties": {
        "kind": {"enum": ["graph", "hasse", "cyclic_cayley", "cyclic_subgroup_lattice", "ideal_lattice_zn", "zero_divisor_graph", "unsupported"]},
        "graph_family": {"enum": ["general", "simple", "complete", "bipartite", "complete_bipartite", "tree", "forest", "path", "cycle", "regular", "multigraph"]},
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
                    "weight": {"type": ["string", "number", "null"], "maxLength": 80},
                    "edge_label": {"type": ["string", "null"], "maxLength": 80},
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
    "绘图要求不能超过2000字。": "The drawing request cannot exceed 2,000 characters.",
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
    "图族结构与定义不符，请调整绘图要求。": "The generated graph does not satisfy its stated graph-family definition.",
    "生成的数学图不符合请求中明确指定的结构或参数，请重试。": "The generated diagram does not match the structure or parameters explicitly requested. Please try again.",
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
        raise MathDiagramError("math_diagram_request_too_large", "绘图要求不能超过2000字。", status=413)
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
    if not isinstance(title, str) or not title.strip() or len(title) > 80 or any(ord(ch) < 32 for ch in title):
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


def _validate_graph_family(family, directed, vertices, edges):
    allowed = {"general", "simple", "complete", "bipartite", "complete_bipartite",
               "tree", "forest", "path", "cycle", "regular", "multigraph"}
    if family not in allowed:
        raise MathDiagramError("invalid_graph_family", "模型没有返回有效的数学图结构，请调整描述后重试。", status=502)
    if family in {"general", "multigraph"}:
        return
    if family in {"complete", "bipartite", "complete_bipartite", "tree", "forest", "path", "cycle", "regular"} and directed:
        raise MathDiagramError("graph_family_mismatch", "图族结构与定义不符，请调整绘图要求。", status=502)

    graph = nx.DiGraph() if directed else nx.Graph()
    graph.add_nodes_from(vertex["id"] for vertex in vertices)
    seen = set()
    for edge in edges:
        pair = (edge["from"], edge["to"])
        key = pair if directed else tuple(sorted(pair))
        if pair[0] == pair[1] or key in seen:
            raise MathDiagramError("graph_family_mismatch", "图族结构与定义不符，请调整绘图要求。", status=502)
        seen.add(key)
        graph.add_edge(*pair)

    if family == "simple":
        return
    if family == "complete":
        count = len(vertices)
        if graph.number_of_edges() != count * (count - 1) // 2:
            raise MathDiagramError("graph_family_mismatch", "图族结构与定义不符，请调整绘图要求。", status=502)
    elif family == "bipartite":
        if not nx.is_bipartite(graph):
            raise MathDiagramError("graph_family_mismatch", "图族结构与定义不符，请调整绘图要求。", status=502)
    elif family == "complete_bipartite":
        if len(vertices) < 2 or not nx.is_connected(graph) or not nx.is_bipartite(graph):
            raise MathDiagramError("graph_family_mismatch", "图族结构与定义不符，请调整绘图要求。", status=502)
        coloring = nx.algorithms.bipartite.color(graph)
        left = sum(color == 0 for color in coloring.values())
        right = len(vertices) - left
        if not left or not right or graph.number_of_edges() != left * right:
            raise MathDiagramError("graph_family_mismatch", "图族结构与定义不符，请调整绘图要求。", status=502)
    elif family == "tree":
        if not nx.is_tree(graph):
            raise MathDiagramError("graph_family_mismatch", "图族结构与定义不符，请调整绘图要求。", status=502)
    elif family == "forest":
        if not nx.is_forest(graph):
            raise MathDiagramError("graph_family_mismatch", "图族结构与定义不符，请调整绘图要求。", status=502)
    elif family == "path":
        if len(vertices) < 2 or not nx.is_tree(graph) or max(dict(graph.degree()).values(), default=0) > 2:
            raise MathDiagramError("graph_family_mismatch", "图族结构与定义不符，请调整绘图要求。", status=502)
    elif family == "cycle":
        if len(vertices) < 3 or not nx.is_connected(graph) or any(degree != 2 for _, degree in graph.degree()):
            raise MathDiagramError("graph_family_mismatch", "图族结构与定义不符，请调整绘图要求。", status=502)
    elif family == "regular":
        degrees = {degree for _, degree in graph.degree()}
        if len(degrees) > 1:
            raise MathDiagramError("graph_family_mismatch", "图族结构与定义不符，请调整绘图要求。", status=502)


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
            if (isinstance(weight, bool) or not isinstance(weight, (str, int, float))
                    or isinstance(weight, float) and not math.isfinite(weight)
                    or str(weight).strip() == ""
                    or isinstance(weight, str) and (len(weight) > 80 or any(ord(ch) < 32 for ch in weight))):
                raise MathDiagramError("missing_math_diagram_weight", "带权图的每条边都必须提供权值。", status=502)
            edge["weight"] = weight
        elif weight is not None:
            raise MathDiagramError("unexpected_math_diagram_weight", "模型没有返回有效的数学图结构，请调整描述后重试。", status=502)
        label = row.get("edge_label")
        if label is not None:
            if not isinstance(label, str) or len(label) > 80 or any(ord(ch) < 32 for ch in label):
                raise MathDiagramError("invalid_math_diagram_edge_label", "模型没有返回有效的数学图结构，请调整描述后重试。", status=502)
            if label:
                edge["edge_label"] = label
        edges.append(edge)
    _validate_graph_family(spec.get("graph_family", "general"), directed, vertices, edges)
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


def build_document(spec, *, language="zh-CN"):
    kind = spec.get("kind")
    if kind == "unsupported":
        reason = str(spec.get("reason") or "").strip()
        message = (reason[:300] if reason and language != "en"
                   else "该数学结构暂不支持自动生成。")
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


_REQUEST_COUNT = r"(?:[0-9]+|[一二两三四五六七八九]?十[一二三四五六七八九]?|[一二两三四五六七八九])"
_REQUEST_FAMILIES = {
    "完全图": "complete", "complete graph": "complete",
    "树": "tree", "tree": "tree", "路径": "path", "path": "path",
    "回路": "cycle", "环": "cycle", "循环图": "cycle", "cycle": "cycle",
}
_REQUEST_ZN = r"Z\s*_?\s*(?:\{\s*([0-9]+)\s*\}|([0-9]+))"


def _request_count(value):
    if value.isascii() and value.isdecimal():
        return int(value)
    digits = {char: index for index, char in enumerate("零一二三四五六七八九")}
    digits["两"] = 2
    if "十" in value:
        tens, units = value.split("十")
        return digits.get(tens, 1) * 10 + digits.get(units, 0)
    return digits[value]


def _explicit_requirement_constraints(requirement):
    """Recognize only complete, simple requests, never keywords in free text.

    Full matches intentionally exclude edits, negations, comparisons and requests
    for several structures. Unrecognized wording still receives normal model
    schema/structure validation; it is not assigned an inferred constraint.
    """
    text = unicodedata.normalize("NFKC", requirement).strip()
    text = text.replace("$", "").replace(r"\(", "").replace(r"\)", "")
    text = re.sub(r"\s+", " ", text).strip(" .!。!！?？")
    text = re.sub(r"^(?:(?:请(?:你)?(?:帮我)?|帮我)?(?:画出?|绘制|生成))\s*", "", text)
    text = re.sub(r"^(?:一个|一幅|一张|一棵|一条)\s*", "", text)
    text = re.sub(r"^(?:please\s+)?(?:draw|generate|create|plot|show)(?:\s+me)?\s+", "", text, flags=re.I)
    text = re.sub(r"^(?:an?|the)\s+", "", text, flags=re.I)

    # Standard K_n and K_{m,n}; prefixes must agree with the notation.
    match = re.fullmatch(
        r"(?:(完全图|完全二部图|完全二分图|complete graph|complete bipartite graph)\s*)?"
        r"K\s*_?\s*(\{\s*[0-9]+\s*(?:,\s*[0-9]+\s*)?\}|[0-9]+\s*(?:,\s*[0-9]+)?)",
        text, flags=re.I,
    )
    if match:
        parts = tuple(int(part.strip()) for part in match[2].strip("{} ").split(","))
        prefix = (match[1] or "").lower()
        if len(parts) == 1 and prefix not in {"完全二部图", "完全二分图", "complete bipartite graph"}:
            return {"kind": "graph", "family": "complete", "vertices": parts[0]}
        if len(parts) == 2 and prefix not in {"完全图", "complete graph"}:
            return {"kind": "graph", "family": "complete_bipartite", "vertices": sum(parts), "parts": parts}
        return None

    match = re.fullmatch(
        rf"(?:有|具有|含有|含)?\s*({_REQUEST_COUNT})\s*个?\s*顶点\s*的?\s*(完全图|树|路径|回路|环|循环图)", text,
    )
    if match:
        return {"kind": "graph", "family": _REQUEST_FAMILIES[match[2]], "vertices": _request_count(match[1])}
    match = re.fullmatch(r"(complete graph|tree|path|cycle)\s+(?:on|with|having)\s+([0-9]+)\s+(?:vertices|nodes)", text, flags=re.I)
    if match:
        return {"kind": "graph", "family": _REQUEST_FAMILIES[match[1].lower()], "vertices": int(match[2])}
    match = re.fullmatch(r"([0-9]+)[ -]+(?:vertex|node)\s+(complete graph|tree|path|cycle)", text, flags=re.I)
    if match:
        return {"kind": "graph", "family": _REQUEST_FAMILIES[match[2].lower()], "vertices": int(match[1])}

    for kind, chinese, english, domain in (
        ("cyclic_cayley", r"(?:Cayley\s*图|凯莱图)", r"cayley graph", r"(?:循环群|群)"),
        ("cyclic_subgroup_lattice", "子群格", "subgroup lattice", r"(?:循环群|群)"),
        ("ideal_lattice_zn", "理想格", "ideal lattice", r"(?:交换环|环)"),
        ("zero_divisor_graph", "零因子图", r"zero[- ]divisor graph", r"(?:交换环|环)"),
    ):
        match = re.fullmatch(rf"(?:{domain}\s*)?{_REQUEST_ZN}\s*的?\s*{chinese}", text, flags=re.I)
        if not match:
            english_domain = r"(?:cyclic group|group)" if kind.startswith("cyclic_") else "ring"
            match = re.fullmatch(rf"{english}\s+of\s+(?:the\s+)?(?:{english_domain}\s+)?{_REQUEST_ZN}", text, flags=re.I)
        if match:
            return {"kind": kind, "modulus": int(match[1] or match[2])}
    return None


def _validate_requirement_constraints(requirement, spec, document):
    constraints = _explicit_requirement_constraints(requirement)
    if constraints is None:
        return

    def mismatch():
        raise MathDiagramError(
            "math_diagram_requirement_mismatch",
            "生成的数学图不符合请求中明确指定的结构或参数，请重试。", status=502,
        )

    if spec["kind"] != constraints["kind"]:
        mismatch()
    if "modulus" in constraints:
        if spec.get("modulus") != constraints["modulus"]:
            mismatch()
        return
    graph = document["graphs"][0]
    if len(graph["vertices"]) != constraints["vertices"]:
        mismatch()
    try:
        # Check the requested family against actual edges even if the model
        # reports graph_family='general' or another, weaker family.
        _validate_graph_family(constraints["family"], graph["directed"], graph["vertices"], graph["edges"])
    except MathDiagramError:
        mismatch()
    if "parts" in constraints:
        structure = nx.Graph()
        structure.add_nodes_from(vertex["id"] for vertex in graph["vertices"])
        structure.add_edges_from((edge["from"], edge["to"]) for edge in graph["edges"])
        coloring = nx.algorithms.bipartite.color(structure)
        left = sum(color == 0 for color in coloring.values())
        if sorted((left, len(coloring) - left)) != sorted(constraints["parts"]):
            mismatch()


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
                        {"role": "system", "content": _PROMPT + ("\n\n请使用英文标题、标签和 reason。" if language == "en" else "\n\n请使用简体中文标题、标签和 reason。")},
                        {"role": "user", "content": requirement},
                    ],
                    retries=0,
                    reasoning_effort="none",
                    max_tokens=5000,
                    timeout=(8, 60),
                    response_format={"type": "json_object"},
                )
            except requests.Timeout as exc:
                raise MathDiagramError("math_diagram_timeout", "数学图生成暂时不可用，请稍后重试。", status=504) from exc
            except requests.RequestException as exc:
                raise MathDiagramError("math_diagram_connection_failed", "数学图生成暂时不可用，请稍后重试。", status=502) from exc
            spec = _parse_model_result(response)
            document, kind = build_document(spec, language=language)
            _validate_requirement_constraints(requirement, spec, document)
            return {"ok": True, "kind": kind, "title": document["graphs"][0]["name"], "document": document}
        finally:
            _ACTIVE.release()
    except MathDiagramError as error:
        raise _localize_error(error, language)
