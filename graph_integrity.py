"""Conservative graph topology auditing and exact labeled-graph isomorphism.

A matching checksum of AI transcriptions is not pixel-ground-truth. Never convert
a contested image edge into a definite mathematical conclusion.
"""
from collections import Counter
import re

HEADER = re.compile(r"图\s*([1-9]\d*)\s*(?:[（(][^（）()\n]{0,28}[）)])?\s*[:：]", re.I)
EDGE_START = re.compile(r"(?:边连接关系|边集合|边集|边包括|边为|边)\s*(?:为|包括)?\s*[:：]", re.I)
EDGE = re.compile(r"(?<![a-zA-Z])([a-z])\s*[-—–－−]\s*([a-z])(?![a-zA-Z])", re.I)
CURLY_EDGE = re.compile(r"\{\s*([a-z])\s*[,，]\s*([a-z])\s*\}", re.I)
VERTEX_SET = re.compile(
    r"顶点集合\s*[:：]\s*\{\s*([a-z](?:\s*[,，、]\s*[a-z]){1,15})\s*\}", re.I
)
VERTEX_START = re.compile(
    r"(?:顶点标签分别为|顶点标签为|顶点分别为|顶点为|标签分别为|标签为|标签|顶点)"
    r"\s*[:：]?\s*([a-z](?:\s*[,，、]\s*[a-z]){1,15})", re.I
)
FLAG = "【图形结构待核对】"
OK_MARKER = "【图形边集已二次核对】"
UNCERTAIN = re.compile(r"不确定|待核对|未确认|可能|仅确认|候选边|部分边|partial", re.I)


def _normal_edge(a, b):
    return tuple(sorted((a.lower(), b.lower())))


def parse_diagrams(text):
    """Parse explicit complete labeled edge lists from either format:
    图1（左图）：...顶点标签分别为a、b...。边连接关系为：a-b,...
    图1（G1）：...标签 a、b...。边：a-b,...
    No inferred isolated vertices or edges, no generic prose parsing.
    """
    text = str(text or "")
    matches = list(HEADER.finditer(text))
    result = {}
    for i, match in enumerate(matches):
        part = text[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)]
        if "有向图" in part[:40] or "无向图" not in part[:40]:
            continue
        v_match = VERTEX_START.search(part) or VERTEX_SET.search(part)
        e_match = EDGE_START.search(part)
        if not v_match or not e_match:
            continue
        labels = re.findall(r"[a-z]", v_match.group(1).lower())
        if len(labels) < 2 or len(set(labels)) != len(labels):
            continue
        edge_clause = re.split(r"[。；;\n（(]", part[e_match.end():], maxsplit=1)[0]
        pairs = [_normal_edge(a, b) for a, b in EDGE.findall(edge_clause)]
        pairs += [_normal_edge(a, b) for a, b in CURLY_EDGE.findall(edge_clause)]
        residue = CURLY_EDGE.sub("", EDGE.sub("", edge_clause))
        # Accept only commas/list separators, never guess what unexplained text means.
        if not pairs or re.search(r"[a-zA-Z0-9]", residue):
            continue
        if any(a not in labels or b not in labels for a, b in pairs):
            continue
        result[int(match.group(1))] = {"vertices": labels, "edges": pairs}
    return result


def _audit_dict(item):
    if not isinstance(item, dict) or item.get("complete") is not True:
        return None
    vertices = item.get("vertices")
    edges = item.get("edges")
    if (not isinstance(vertices, list) or not isinstance(edges, list) or
            not (2 <= len(vertices) <= 12) or len(set(vertices)) != len(vertices)):
        return None
    if any(not isinstance(x, str) or not re.fullmatch(r"[a-z]", x, re.I) for x in vertices):
        return None
    if len(edges) > 75:
        return None
    canonical = []
    for pair in edges:
        if (not isinstance(pair, (list, tuple)) or len(pair) != 2 or
                any(not isinstance(x, str) for x in pair)):
            return None
        a, b = pair[0].lower(), pair[1].lower()
        if a not in vertices or b not in vertices or a == b:
            return None
        canonical.append(_normal_edge(a, b))
    if len(set(canonical)) != len(canonical):  # unexpected multigraph
        return None
    return {"vertices": [x.lower() for x in vertices], "edges": canonical}


def review_graph_transcriptions(vision_text, audited_graphs):
    """Return (text, warnings, verified). Contested diagrams must not be solved.

    The audit model is independent and sees the image, not the first model's
    invented endpoints. Agreement means two transcriptions match, *not* a
    guarantee that the underlying pixels are read correctly.
    """
    primary = parse_diagrams(vision_text)
    if not isinstance(audited_graphs, list) or len(audited_graphs) < 2:
        return FLAG + "\n图形复核未得到完整的两个图及逐边列表，请检查原图后再作结论。", ["图形逐边核验尚未完成。"], False

    secondary = {}
    for index, row in enumerate(audited_graphs, 1):
        if not isinstance(row, dict) or row.get("directed") is not False:
            return FLAG + "\n存在图形类别或方向不明确的情况，暂不判断同构。", ["复核图形类别不确定。"], False
        idx = row.get("index", index)
        if not isinstance(idx, int):
            return FLAG + "\n无法对应不同图的顺序，暂不判断同构。", ["复核编号不完整。"], False
        parsed = _audit_dict(row)
        if parsed is None:
            return FLAG + "\n复核未确认全部端点或边，不能据不完整边集判断同构。", ["存在尚未确认的边连接。"], False
        secondary[idx] = parsed

    if set(primary) != set(secondary) or len(primary) != 2:
        return FLAG + "\n图形识别结果未能逐图核对，请确认每张图的顶点与边。", ["首次识别和复核的图形数量或格式不一致。"], False

    mismatches = []
    for number in sorted(primary):
        a, b = primary[number], secondary[number]
        if set(a["vertices"]) != set(b["vertices"]):
            mismatches.append(f"图{number}顶点标签")
        if Counter(a["edges"]) != Counter(b["edges"]):
            mismatches.append(f"图{number}边连接")
    if mismatches:
        # Preserve both transcriptions as *uncertain*, never silently pick one.
        # The caller supplies a distinct warning so the client can request review.
        detail = "、".join(mismatches)
        return (FLAG + f"\n原始识别与独立图形复核在{detail}存在冲突，请对照图片确认；"
                "暂不据此判断同构或计算度数。", [f"图形逐边复核冲突：{detail}。"], False)
    if UNCERTAIN.search(vision_text):
        return FLAG + "\n图形结构含不确定的连接，需要对照原图核实。", ["边集仍存在不确定信息。"], False
    # Do not retain prose degrees from Vision. The observed Cornell OCR once
    # listed nine edges while stating degrees inconsistent with those edges.
    # Keep only audited graph facts so the answer step cannot reuse hallucinated
    # degree summaries or confused line-shape commentary.
    standardized = []
    for no in sorted(secondary):
        row = secondary[no]
        verts = "、".join(row["vertices"])
        edges = "、".join("-".join(p) for p in sorted(row["edges"]))
        standardized.append(
            f"图{no}（G{no}）：无向图，顶点 {verts}。边：{edges}。"
        )
    return OK_MARKER + "\n" + "\n".join(standardized), [], True


def exact_isomorphism(left, right):
    """Return bijection dict, None for non-isomorphic graphs, 'unknown' for invalid.

    Uses adjacency/backtracking with exact degree constraints, no external graph
    library. Bounded to 12 vertices; avoids factorial enumeration of empty/K_n.
    """
    a = _audit_dict({"complete": True, **left})
    b = _audit_dict({"complete": True, **right})
    if a is None or b is None:
        return "unknown"
    va, vb = a["vertices"], b["vertices"]
    if len(va) != len(vb) or len(a["edges"]) != len(b["edges"]):
        return None
    ea, eb = set(a["edges"]), set(b["edges"])
    da = Counter(x for edge in ea for x in edge)
    db = Counter(x for edge in eb for x in edge)
    if sorted(da.get(x, 0) for x in va) != sorted(db.get(x, 0) for x in vb):
        return None
    av = {x: {y for y in va if y != x and _normal_edge(x, y) in ea} for x in va}
    bv = {x: {y for y in vb if y != x and _normal_edge(x, y) in eb} for x in vb}
    # Most constrained vertices first; adjacency checks prune candidate mappings.
    order = sorted(va, key=lambda x: (-len(av[x]), x))
    mapping, used = {}, set()
    def search(i):
        if i == len(order):
            return dict(mapping)
        x = order[i]
        for y in sorted(vb):
            if y in used or len(av[x]) != len(bv[y]):
                continue
            if any((u in av[x]) != (mapping[u] in bv[y]) for u in mapping):
                continue
            mapping[x] = y
            used.add(y)
            solution = search(i + 1)
            if solution is not None:
                return solution
            used.remove(y)
            del mapping[x]
        return None
    return search(0)


def answer_graph_isomorphism(user_text):
    """Deterministic answer when a fully confirmed graph edge list is present.

    Return '' for unrelated tasks, a careful hold for uncertain image graphs.
    """
    text = str(user_text or "")
    # Multi-part scanned exams may contain an isomorphism question in the
    # original printed page while the student is asking about another item.
    # Never hijack the explicit current request merely because Q10 says
    # "isomorphic" somewhere above Q11.
    graph_request = re.compile(r"同构|isomorph|团数|极大团|欧拉|哈密顿|连通|边集|度数|树", re.I)
    if "【我的要求】" in text:
        request = text.rsplit("【我的要求】", 1)[1]
        if not re.search(r"同构|isomorph|第\s*10\s*题|全部|所有|整张", request, re.I):
            if FLAG in text and graph_request.search(request):
                return ("当前图像的边连接关系仍有冲突，不能可靠计算该图的性质。"
                        "请先在识别核对界面确认图中所有边，再重新解题。")
            return ""
    if not re.search(r"同构|isomorph", text, re.I):
        return ""
    if FLAG in text:
        return ("目前无法可靠判断这两张图是否同构：图片的边连接关系在两次识别中存在冲突，"
                "直接计算度数或给出同构映射都可能产生错误答案。"
                "请在识别核对界面确认边，或上传只包含两张图的清晰截图后重试。")
    graphs = parse_diagrams(text)
    if len(graphs) != 2 or set(graphs) != {1, 2}:
        return ""
    # For an image-derived graph, only two independent transcriptions matched
    # may qualify. Explicitly typed complete graphs are treated as given facts.
    if "【图形信息】" in text and OK_MARKER not in text:
        return ""
    if UNCERTAIN.search(text) and OK_MARKER not in text:
        return ""
    iso = exact_isomorphism(graphs[1], graphs[2])
    if iso == "unknown":
        return ""
    if iso is None:
        return ("按题目列出的完整边集计算，两图不同构。"
                "已核对顶点数、边数、各顶点度数及全部可能的保邻接双射；"
                "不存在保持相邻关系的映射。"
                "（此结论仅针对识别后确认的边集，不能替代原图核对。）")
    mapping = "，".join(f"{k}↦{v}" for k, v in sorted(iso.items()))
    return ("按题目列出的完整边集验证，两图同构。\n"
            f"一个保邻接的双射为：{mapping}。\n"
            "将图1每条边的两个端点分别按上述映射替换，所得边集与图2完全相同。")
