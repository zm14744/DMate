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
        return None
    return ("这道题依赖图中的实际顶点和边，而当前图片的图形结构尚未核对完整。"
            "直接据此给出当前问题的确定结论，可能导致计算或推理错误。"
            "请先在识别核对界面确认每条边及箭头方向，或上传更清晰、"
            "只包含该图的截图；在核对完成前不能给出确定的数学结论。")
