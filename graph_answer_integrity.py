"""Fail-closed graph-image answer boundary and directed edge transcription audit.

Built from real 2026-10-20 university diagram regressions:
- Stanford's six six-vertex trees were OCR-uncertain, yet the AI invented an
  unrelated two-degree-three tree problem and confidently solved that instead.
- HKUST Petersen diagram hallucinated >20 explicit edges while saying 15.
- NJU directed diagrams had flipped arrows, yielding a WRONG weak-connectivity
  classification. A second, independently prompted read is mandatory for these
  graph images; disagreement means review, not a confident solved answer.

This does not change typed graph queries, unrelated text questions or tutoring
that does not depend on an uncertain graph diagram.
"""
from __future__ import annotations
import re
from collections import Counter

FLAG="【图形结构待核对】"

DIR_HEAD=re.compile(
    r"图\s*[（(]\s*(\d+)\s*[）)]\s*[：:].{0,200}?"
    r"(?:有向边|弧|边的方向|边)\s*(?:为|包括|是|有)?[：:]",
    re.S,
)
DIRECTIONAL_EDGE=re.compile(r"(?<![a-zA-Z0-9])([a-z])\s*(?:→|->|⇒)\s*([a-z])(?![a-zA-Z0-9])",re.I)
EDGE_DECL=re.compile(r"边集\s*[（(]\s*共\s*(\d+)\s*条\s*[）)]\s*[：:]",re.I)
G_PREFIX_EDGE=re.compile(r"(G\d+_v\d+)\s*[-—–]\s*(G\d+_v\d+)")
SENSITIVE=re.compile(
    r"(?:图同构|是否同构|同构|等价图|顶点|边数|边集|度数|度序列|"
    r"欧拉|哈密顿|生成树|树|图论|连通|弱连通|强连通|割点|桥|"
    r"平面图|色数|着色|最大团|团数|clique|graph|"
    r"vertices|edges|diameter|chromatic|planar|connected|"
    r"最短路|最小生成|邻接|匹配|绕圈|路径|回路|"
    r"第\s*[一二三四五六七八九十123456789]\s*图)",
    re.I,
)

def detect_count_inconsistency(visual_text):
    """Catch explicit contradiction in the SAME graph edge description.

    Ignore generic OCR where no declared cardinality/complete list exists.
    Specific failure in HKUST: 22 edge pairs follow '共15条' and some repeat.
    """
    s=str(visual_text or "")
    for m in EDGE_DECL.finditer(s):
        subsequent=s[m.end():]
        # A long free-form trailing paragraph isn't a complete edge list.
        # Require at least 3 explicit "G1_v1-G1_v2" style pairs, all belonging
        # to the same numbered graph as in the original transcription.
        pairs=G_PREFIX_EDGE.findall(subsequent[:2200])
        if not pairs:
            continue
        prefix=pairs[0][0].split("_v")[0]
        same=[(a,b) for a,b in pairs if a.startswith(prefix+"_") and b.startswith(prefix+"_")]
        if len(same)<3:continue
        declared=int(m.group(1))
        unique={tuple(sorted(pair)) for pair in same}
        # Count inconsistency must be significant; do not flag omission of
        # unrelated edges after a second diagram begins.
        if len(same)!=declared or len(unique)!=declared:
            return (f"图形文字自相矛盾：标称 {declared} 条边，实际列出 "
                    f"{len(same)} 组边（去重后 {len(unique)} 组）。"
                    "不能以标称数字代替逐边确认。")
    return None


def _primary_directed_graphs(text):
    """Parse exact edge lists per figure; '→' direction is significant."""
    s=str(text or "")
    matches=list(DIR_HEAD.finditer(s))
    graphs={}
    for i,m in enumerate(matches):
        idx=int(m.group(1))
        if idx in graphs:return None
        end=matches[i+1].start() if i+1<len(matches) else len(s)
        segment=s[m.end():end]
        # Before a second heading, unrelated prose may exist; allow only the
        # first line of the edge list.
        segment=segment.split("\n",1)[0]
        edges=[(a.lower(),b.lower()) for a,b in DIRECTIONAL_EDGE.findall(segment)]
        if not edges:return None
        if len(set(edges))!=len(edges):return None
        graphs[idx]=set(edges)
    return graphs or None


def review_directed_graphs(primary_text, independently_read):
    """Compare second full image-only arrow tracing to the original read.

    No arithmetic derived from ambiguous edges is accepted. A second visual
    model must give complete, directed graph lists with the SAME labeled
    vertices and exact oriented edges. Failure or mismatch -> human review.
    """
    primary=_primary_directed_graphs(primary_text)
    if not primary or not isinstance(independently_read,list):
        return FLAG+"\n原图的有向边未能完整逐条复核。",["有向图独立逐箭头复核不完整。"],False
    independent={}
    for record in independently_read:
        if not isinstance(record,dict) or record.get("complete") is not True or record.get("directed") is not True:
            return FLAG+"\n第二次识别未确认每条箭头的两个端点。",["有向图第二次识别不完整。"],False
        try:
            idx=int(record.get("index"))
            vertices=[str(v).lower().strip() for v in record.get("vertices",[])]
            raw_edges=record.get("edges")
            if not isinstance(raw_edges,list):raise ValueError()
            edges=[(str(a).lower().strip(),str(b).lower().strip()) for a,b in raw_edges]
        except (ValueError,TypeError,AttributeError):
            return FLAG+"\n第二次识别有格式错误。",["独立有向图复核格式不完整。"],False
        if not vertices or len(vertices)!=len(set(vertices)) or not edges or idx in independent:
            return FLAG+"\n第二次识别顶点或边未能确认。",["独立有向图顶点/边未确认。"],False
        if any(a not in vertices or b not in vertices for a,b in edges):
            return FLAG+"\n第二次识别边的端点不在顶点集中。",["独立图结构端点与顶点集不匹配。"],False
        if len(set(edges))!=len(edges):
            return FLAG+"\n第二次识别存在重复或不确定的有向边。",["独立图识别重复箭头。"],False
        independent[idx]=(set(vertices),set(edges))
    if set(primary)!=set(independent):
        return FLAG+"\n两次图片识别得到的图形数量不一致。",["两次独立识别图数不一致。"],False
    issues=[]
    verified=[]
    for idx in sorted(primary):
        vertices,edges=independent[idx]
        original=primary[idx]
        if original!=edges:
            issues.append(f"图{idx}有向边方向或连接不一致："
                          f"第一次{sorted(original)}，独立复核{sorted(edges)}")
        else:
            listing="、".join(f"{a}→{b}" for a,b in sorted(edges))
            verified.append(f"图({idx})【有向边已独立核对】 顶点："
                            + "、".join(sorted(vertices))
                            + f"；边({len(edges)}条)："+listing)
    if issues:
        return FLAG+"\n独立两次逐箭头转录不一致，无法可靠计算强连通或弱连通。",issues,False
    return "\n".join(verified),[],True




# A first-pass vision transcript can look plausible while containing invented
# crossing edges or repeated undirected edges. For 3+ labelled diagrams, audit
# each actual unordered edge pair, not only the vertex/edge totals.
_PANEL_HEADER = re.compile(
    r"(?mi)^\s*(?:(?:图\s*)?G\s*_?\{?([1-9]\d*)\}?|"
    r"图\s*([1-9]\d*)(?:\s*[（(][^）)\n]*[）)])?)\s*[：:]"
)
_PANEL_VERTICES = re.compile(
    r"顶点(?:集合|标签(?:分别)?)?\s*(?:为|是|分别为)?\s*[:：]?\s*"
    r"\{?\s*([a-zA-Z](?:\s*[,，、]\s*[a-zA-Z]){2,})", re.I
)
_PANEL_EDGE_START = re.compile(
    r"(?:边连接关系|边集合|边集|边为|边包括|边)\s*(?:为|包括)?\s*[:：]?", re.I
)
_PANEL_EDGE = re.compile(
    r"(?<![a-zA-Z0-9])([a-zA-Z])\s*[-—–－−]\s*([a-zA-Z])(?![a-zA-Z0-9])"
)


def parse_labeled_multi_panels(text):
    """Read explicitly written vertices and edges from 3+ labeled diagrams.

    Never infer edges from a diagram title, expected tree shape, or counts.
    Unknown/incomplete formatting returns {}, not fabricated graph records.
    """
    source = str(text or "")
    headers = list(_PANEL_HEADER.finditer(source))
    if not 3 <= len(headers) <= 8:
        return {}
    parsed = {}
    for pos, heading in enumerate(headers):
        index = int(heading.group(1) or heading.group(2))
        if index in parsed:
            return {}
        body = source[heading.end():headers[pos + 1].start() if pos + 1 < len(headers) else len(source)]
        vm = _PANEL_VERTICES.search(body)
        em = _PANEL_EDGE_START.search(body)
        if not vm or not em:
            return {}
        labels = [a.lower() for a in re.findall(r"[a-zA-Z]", vm.group(1))]
        edge_line = re.split(r"[。；;\n]", body[em.end():], maxsplit=1)[0]
        edges = [tuple(sorted((u.lower(), v.lower())))
                 for u, v in _PANEL_EDGE.findall(edge_line)]
        if len(labels) < 3 or len(set(labels)) != len(labels) or not edges:
            return {}
        raw_count = re.search(r"(?:共|共有|计)\s*(\d+)\s*条(?:边|无向边)", body)
        duplicate_edges = [edge for edge, count in Counter(edges).items() if count > 1]
        issues = []
        if duplicate_edges:
            issues.append(f"G{index} 重复列出无向边：" +
                          "、".join("-".join(p) for p in duplicate_edges))
        if any(u == v for u, v in edges):
            # A genuine self-loop must be explicitly depicted, not silently
            # erased; labeled simple-graph review cannot certify this case.
            issues.append(f"G{index} 含自环，需要核对原图")
        if any(u not in labels or v not in labels for u, v in edges):
            issues.append(f"G{index} 的边端点不在顶点表内")
        if raw_count and int(raw_count.group(1)) != len(set(edges)):
            issues.append(f"G{index} 宣称的边数与去重后的边集不一致")
        parsed[index] = {"vertices": labels, "edges": edges, "issues": issues}
    return parsed


def review_labeled_multi_panels(initial_text, audited_graphs):
    """Cross-check all labeled diagrams with independent image-only edges.

    Any disagreement is a review result, not a license to adopt whichever
    text yields a nicer tree/isomorphism answer.
    """
    original = str(initial_text or "").strip()
    primary = parse_labeled_multi_panels(original)
    if not primary:
        return FLAG + "\n多图边集格式或顶点标签不完整，无法逐图核验。\n" + original, [
            "首轮图结构无法解析成完整的逐图边集。"
        ], False
    issues = [issue for record in primary.values() for issue in record["issues"]]
    independent = {}
    if not isinstance(audited_graphs, list):
        audited_graphs = []
    for row in audited_graphs:
        if not isinstance(row, dict) or row.get("complete") is not True or row.get("directed") is not False:
            issues.append("独立复核存在未确认的图形或边方向")
            continue
        try:
            idx = int(row["index"])
            labels = [str(v).lower() for v in row["vertices"]]
            raw_edges = row["edges"]
            edges = [tuple(sorted((str(e[0]).lower(), str(e[1]).lower()))) for e in raw_edges
                     if isinstance(e, (tuple, list)) and len(e) == 2]
        except (ValueError, KeyError, TypeError):
            issues.append("独立复核缺少必要的图形结构")
            continue
        if (idx in independent or len(labels) < 3 or len(set(labels)) != len(labels)
                or len(edges) != len(raw_edges) or len(set(edges)) != len(edges)
                or any(a not in labels or b not in labels or a == b for a, b in edges)):
            issues.append(f"G{idx} 的独立边集无效或含重边")
            continue
        independent[idx] = {"vertices": labels, "edges": edges}
    if set(primary) != set(independent):
        issues.append("首次识别与独立复核的图形数量或编号不一致")
    for idx in sorted(set(primary) & set(independent)):
        before, after = primary[idx], independent[idx]
        if set(before["vertices"]) != set(after["vertices"]):
            issues.append(f"G{idx} 的顶点表与独立复核不一致")
        if Counter(before["edges"]) != Counter(after["edges"]):
            issues.append(f"G{idx} 的边连接与独立复核不一致")
    if issues:
        # Preserve the user's ability to edit what the model saw; however the
        # global uncertainty marker prevents downstream answers being certified.
        return (FLAG + "\n" + "；".join(dict.fromkeys(issues)) +
                "\n【首次识别候选，须对照原图校正】\n" + original), issues, False
    standardized = []
    for idx in sorted(independent):
        row = independent[idx]
        standardized.append(
            f"图{idx}（G{idx}）：无向图，顶点 " +
            "、".join(row["vertices"]) + "。边：" +
            "、".join("-".join(edge) for edge in sorted(row["edges"])) + "。"
        )
    return "【多图边集已二次核对】\n" + "\n".join(standardized), [], True


FIGURE_VERTEX_COUNT = re.compile(
    r"图\s*(\d+)\s*[（(][^\n]{0,95}?(?:有|含|共)?\s*(\d+)\s*个顶点",
    re.I
)


def review_multi_graph_counts(primary_text, independent_graphs):
    """Independently compare black-dot counts across >=3 separate diagrams."""
    match=FIGURE_VERTEX_COUNT.findall(str(primary_text or ""))
    first={int(i):int(n) for i,n in match}
    if len(match)<3 or len(first)!=len(match) or not isinstance(independent_graphs,list):
        return FLAG+"\n多图的逐图顶点数量未能独立确认。",["多个图形的顶点数没有得到双重确认。"],False
    second={}
    for g in independent_graphs:
        if not isinstance(g,dict) or g.get("complete") is not True:
            return FLAG+"\n部分图形的顶点仍不清楚。",["局部图顶点数独立复核不完整。"],False
        try:
            idx=int(g["index"])
            count=int(g["vertex_count"])
            edge_count=int(g["edge_count"])
        except (KeyError,TypeError,ValueError):
            return FLAG+"\n复核结果缺少必要数量。",["多图核验缺少顶点数或边数。"],False
        if idx in second or count<1 or count>100 or edge_count<0:
            return FLAG+"\n复核结果存在重复或无效的图形数量。",["多图复核结果格式无效。"],False
        second[idx]=(count,edge_count)
    if set(first)!=set(second):
        return FLAG+"\n首次识别与独立复核的图数不一致。",["多个图形的识别编号不一致。"],False
    issues=[f"图{i}顶点数不一致：首次识别{first[i]}，再次识别{second[i][0]}"
            for i in sorted(first) if first[i]!=second[i][0]]
    if issues:
        return FLAG+"\n两次独立图片识别的顶点数量存在冲突，不能可靠判断图的同构与树。",issues,False
    return primary_text,[],True



_NAMED_EDGE=re.compile(
    r"(?<![A-Za-z0-9])([A-Z])\s*[-—–]\s*([A-Z])(?![A-Za-z0-9])"
)
_NAMED_DEGREE=re.compile(
    r"(?<![A-Za-z0-9])([A-Z])\s*[:：]\s*(\d{1,2})(?!\d)"
)


def detect_named_graph_degree_inconsistency(vision_text):
    """Check literal OCR graph claims against the handshake lemma and edge list.

    The original MIT problem-set A-H image was read as ten edges (including
    nonexistent A-C), plus degrees A2 B3 C3 D2 E4 F2 G1 H2 whose sum is
    *odd*. A confidence assertion in prose cannot override arithmetic.
    This generic invariant catches the unsupported answer before solving.
    """
    text=str(vision_text or "")
    m=re.search(r"各顶点(?:的)?度数(?:分别)?为\s*[：:]\s*([^\n。]{8,450})",text)
    if not m:
        return None
    entries=_NAMED_DEGREE.findall(m.group(1))
    if len(entries)<3 or len({a for a,b in entries})!=len(entries):
        return None
    stated={a:int(b) for a,b in entries}
    summed=sum(stated.values())
    if summed%2:
        return (f"图结构转录不一致：列出的顶点度数之和为 {summed}（奇数）；"
                "无向图度数总和必为偶数，请逐边核对原图。")
    edge_clause=re.search(
        r"(?:连接关系[（(]边[）)]|连接关系|边集合|边集)\s*(?:为|是)?\s*[：:]\s*"
        r"([^\n。]{12,1500})",text
    )
    if not edge_clause:
        return None
    edges=_NAMED_EDGE.findall(edge_clause.group(1))
    if len(edges)<3 or any(a==b for a,b in edges):
        return None
    pairs={tuple(sorted(pair)) for pair in edges}
    if len(pairs)!=len(edges):
        return "图结构转录不一致：边列表重复，请核对是否为真正的重边。"
    actual={v:0 for v in stated}
    for u,v in pairs:
        if u not in actual or v not in actual:
            return "图结构转录不一致：边列表包含度数表以外的顶点。"
        actual[u]+=1
        actual[v]+=1
    discrepancies={v:(stated[v],actual[v]) for v in stated if stated[v]!=actual[v]}
    if discrepancies:
        return "图结构转录不一致：边表与顶点度数矛盾：" + repr(discrepancies) + "。"
    return None




_SINGLE_UPPER_EDGE=re.compile(
    r"(?<![A-Za-z0-9])([A-Z])\s*[-—–]\s*([A-Z])(?![A-Za-z0-9])"
    r"|\{\s*([A-Z])\s*[,，]\s*([A-Z])\s*\}"
)


def single_undirected_named_edges(vision_text):
    """Parse one labelled undirected graph as pairs without assuming completeness.

    Returns None if no *unambiguous single* graph edge listing can be found.
    User's literal A-H topology is never inferred from geometry or a known
    textbook exercise. Missing a second graph image is not evidence it is absent.
    """
    text=str(vision_text or "")
    if FLAG in text or "有向图" in text:
        return None
    if re.search(r"图\s*[（(]?\s*[2-9]\s*[）)]?\s*[（(:：]",text):
        return None
    match=re.search(
        r"(?:各顶点的连接关系[（(]边[）)]|各顶点的连接关系|"
        r"连接关系[（(]边[）)]|连接关系|边集合|边集)\s*(?:为|是)?\s*[：:]\s*"
        r"([^\n。]{10,1500})",
        text
    )
    if not match:
        return None
    segment=match.group(1)
    pairs=[]
    for item in _SINGLE_UPPER_EDGE.finditer(segment):
        a,b,c,d=item.groups()
        u,v=(a,b) if a else (c,d)
        if not u or not v or u==v:
            return None
        pairs.append(tuple(sorted((u,v))))
    if len(pairs)<1 or len(pairs)>75 or len(set(pairs))!=len(pairs):
        return None
    edge_endpoints=set(v for edge in pairs for v in edge)
    # Exact isolated vertices matter for diameter, trees and Euler graphs.
    # Only include them if the source explicitly lists each vertex. Do NOT
    # guess from '共8个顶点' when no labels were successfully transcribed.
    explicit=re.search(
        r"顶点(?:集合)?\s*[：:]\s*([A-Z](?:\s*[、，,]\s*[A-Z]){1,11})",
        text[:match.start()],re.I
    )
    vertices={v.upper() for v in re.findall(r"[A-Z]",explicit.group(1),re.I)} if explicit else edge_endpoints
    if not 2<=len(vertices)<=12 or not edge_endpoints.issubset(vertices):
        return None
    n=re.search(r"(?:共|包含|含|有)\s*(\d+)\s*个顶点",text[:match.start()])
    if n and int(n.group(1))!=len(vertices):
        return None
    return {"vertices":sorted(vertices),"edges":set(pairs)}


def review_single_undirected_graph(primary_text, independently_read):
    """Require two independently drawn full edge sets to match exactly.

    A second independent AI read still is not ground truth, but disagreement
    reveals an unsafe hallucination. Do not pick a convenient answer.
    """
    initial=single_undirected_named_edges(primary_text)
    if initial is None:
        return FLAG+"\n单幅图的初次边集未能完整解析。",["单图边集未经核实。"],False
    if not isinstance(independently_read,list) or len(independently_read)!=1:
        return FLAG+"\n第二次审图未得到恰好一张图。",["独立图数与初次结果不匹配。"],False
    row=independently_read[0]
    if not isinstance(row,dict) or row.get("complete") is not True or row.get("directed") is not False:
        return FLAG+"\n独立审图未确认全部连接端点。",["第二次图结构复核不完整。"],False
    try:
        vertices=[str(x).strip().upper() for x in row["vertices"]]
        listed=[tuple(sorted((str(u).upper(),str(v).upper()))) for u,v in row["edges"]]
    except (KeyError,TypeError,ValueError):
        return FLAG+"\n独立审图的顶点或边字段无效。",["第二次审图格式异常。"],False
    if (len(vertices)!=len(set(vertices)) or set(vertices)!=set(initial["vertices"])
        or len(listed)!=len(set(listed)) or any(u==v or u not in vertices or v not in vertices for u,v in listed)):
        return FLAG+"\n单图审图结果的顶点集合或边有效性不一致。",["顶点或边集二次复核不一致。"],False
    other=set(listed)
    if other!=initial["edges"]:
        missing=sorted(other-initial["edges"])
        extra=sorted(initial["edges"]-other)
        return (FLAG+"\n同一张图的两次独立逐边识别不一致，"
                f"首次识别独有边 {extra}；二次识别独有边 {missing}。"
                "在确认原图之前不能据此计算直径、色数或连通性。"), [
                    "单幅图原始识别与独立逐边复核存在冲突。"
                ],False
    # Both independent pixel reads agree on every explicitly listed edge.
    # This is not absolute image ground truth, but authorizes deterministic
    # calculations instead of another language-model guess.
    return "【图形边集已二次核对】\n"+str(primary_text),[],True



def is_scanned_graph_solution_request(user_content):
    """A scanned question to SOLVE must never be treated as 'generate a quiz'.

    A real Stanford six-tree upload was sent in 【题目文字】/【图形信息】
    wrappers. The exercise classifier incorrectly generated a different
    problem and even exposed its own hidden answer. Only an explicit new
    generation request within 【我的要求】 should enter the quiz generator.
    """
    text=str(user_content or "")
    if "【题目文字】" not in text or "【我的要求】" not in text:
        return False
    request=text.rsplit("【我的要求】",1)[-1].strip()
    if not request:
        return False
    if re.search(
        r"(?:出|编|设计|生成|创作|命制).{0,14}(?:题目|习题|练习|试题|题)"
        r"|(?:给我|来).{0,6}(?:一道|几道).{0,10}(?:题|练习)",
        request,re.I
    ):
        return False
    return bool(re.search(
        r"判断|求|计算|解答|证明|解析|识别|数出|是否|几棵|多少|"
        r"给出|写出|答案|同构|连通|着色|色数|直径|图",
        request,re.I
    ))


def protect_uncertain_graph_answer(question, reply):
    """Suppress an irrelevant or definitive LLM answer to unresolved image.

    The presence of FLAG alone is not sufficient: a mixed scan can contain
    a valid unrelated algebra question. Only graph-sensitive current requests
    are guarded. Important: never fabricate a new subproblem.
    """
    q=str(question or "")
    if FLAG not in q:
        return None
    request=q.rsplit("【我的要求】",1)[-1] if "【我的要求】" in q else q.rsplit("【当前指向题目】",1)[-1]
    if not SENSITIVE.search(request):
        # A real user may upload a directed graph, then simply press
        # "给出答案" or "直接解析" without repeating "graph"/"连通".
        # Previously this skipped the guard and could confidently solve
        # the wrong arrows. Only allow *generic current-image solving*;
        # an explicitly independent algebra/logic sub-question stays usable.
        if re.search(
            r"无关|独立小问|另[一个道]|只解.*(?:代数|集合|逻辑|数论|计数)|"
            r"非图形|不用看图|不依赖图",request,re.I
        ):
            return None
        if (len(request.strip()) > 64
            or not re.search(r"解答|求解|答案|解析|回答|结果|计算|讲解|说明",request)
            or re.search(r"代数|集合|逻辑|无关|独立|另一题|[0-9]\s*[+*/=]",request)):
            return None
    return ("这道题依赖图中的实际顶点和边，而当前图片的图形结构尚未核对完整。"
            "直接据此给出当前问题的确定结论，可能导致计算或推理错误。"
            "请先在识别核对界面确认每条边及箭头方向，或上传更清晰、"
            "只包含该图的截图；在核对完成前不能给出确定的数学结论。")
