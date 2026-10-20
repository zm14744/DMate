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
    r"(?:有向边|弧|边的方向)\s*(?:为|包括|是)?[：:]",
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
