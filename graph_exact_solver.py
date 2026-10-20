"""Deterministic final-answer verification for *verified* small graph diagrams.

A Vision model can hallucinate a complete subgraph from a crossing (real MIT
6.042J case: it invented A-C, B-D and color number 4 instead of 3). Given a
fully and independently checked finite adjacency list, exact BFS, coloring and
Euler/strong-connectivity calculations are safer than another language-model
guess.

Never derive a structure from a cropped/unconfirmed image, and never override
open-ended proof questions unrelated to an already verified graph.
"""
from __future__ import annotations
import itertools
import re
from collections import deque

from graph_answer_integrity import (
    FLAG, single_undirected_named_edges, detect_named_graph_degree_inconsistency,
)
from graph_integrity import OK_MARKER

_SINGLE_CERT="【图形边集已二次核对】"
_DIRECTED_CERT="【有向边已独立核对】"
_ARROW=re.compile(r"([A-Za-z])\s*(?:→|->|⇒)\s*([A-Za-z])")
_DHEADER=re.compile(
    r"图\s*[（(]\s*(\d+)\s*[）)]\s*【有向边已独立核对】"
    r"\s*顶点\s*[：:]\s*([A-Za-z、，,\s]+?)"
    r"\s*[；;]\s*边\s*[（(]\s*(\d+)\s*条\s*[）)]\s*[：:]\s*"
    r"([^\n。]+)",
)


def _active_request(text):
    s=str(text or "")
    if "【我的要求】" in s:
        return s.rsplit("【我的要求】",1)[-1].strip()
    return s


def _graph_section(text):
    s=str(text or "")
    if "【图形信息】" not in s:
        return ""
    return s.rsplit("【图形信息】",1)[-1].split("【我的要求】",1)[0].strip()


def _adjacency(vertices,edges,directed=False):
    adj={v:set() for v in vertices}
    for u,v in edges:
        if u not in adj or v not in adj:
            raise ValueError("invalid endpoint")
        adj[u].add(v)
        if not directed:adj[v].add(u)
    return adj


def _reachable(adj,root):
    seen={root}
    todo=[root]
    while todo:
        for v in adj[todo.pop()]:
            if v not in seen:
                seen.add(v)
                todo.append(v)
    return seen


def _undirected_stats(graph):
    vertices=sorted(graph["vertices"])
    edges=set(graph["edges"])
    if not 2<=len(vertices)<=12 or any(u==v for u,v in edges):
        return None
    adj=_adjacency(vertices,edges)
    connected=len(_reachable(adj,vertices[0]))==len(vertices)
    distances={}
    if connected:
        for source in vertices:
            dist={source:0}
            todo=deque([source])
            while todo:
                u=todo.popleft()
                for v in adj[u]:
                    if v not in dist:
                        dist[v]=dist[u]+1
                        todo.append(v)
            distances[source]=dist
    diameter=max((max(v.values()) for v in distances.values()),default=None)
    return {
        "vertices":vertices,"edges":edges,"adj":adj,
        "connected":connected,"diameter":diameter,
        "degrees":{v:len(adj[v]) for v in vertices},
    }


def _chromatic_number(stats):
    """Exact, bounded <=12-vertex backtracking, with a reproducible coloring."""
    if stats is None:
        return None
    adj=stats["adj"]
    order=sorted(stats["vertices"],key=lambda x:(-len(adj[x]),x))
    color={}
    def assign(pos,k):
        if pos==len(order):
            return dict(color)
        v=order[pos]
        forbidden={color[n] for n in adj[v] if n in color}
        # Colors are interchangeable. Only reuse an existing color or
        # introduce ONE new color at a time; without this symmetry pruning,
        # a 12-vertex complete graph can enumerate ~11! useless permutations.
        next_color=max(color.values(),default=-1)+1
        for c in range(min(k,next_color+1)):
            if c in forbidden:
                continue
            color[v]=c
            completed=assign(pos+1,k)
            if completed is not None:
                return completed
            del color[v]
        return None
    for k in range(1,len(order)+1):
        found=assign(0,k)
        if found is not None:
            return k,found
    return None


def _directed_graphs(visual_text):
    """Read only structured graphs endorsed by independent arrow comparison."""
    s=str(visual_text or "")
    matches=list(_DHEADER.finditer(s))
    if not matches:
        return None
    graphs={}
    for match in matches:
        idx=int(match.group(1))
        vertices=re.findall(r"[a-z]",match.group(2).lower())
        listed=int(match.group(3))
        arcs=[(u.lower(),v.lower()) for u,v in _ARROW.findall(match.group(4))]
        if (idx in graphs or len(vertices)!=len(set(vertices))
            or not vertices or len(arcs)!=listed or len(set(arcs))!=len(arcs)
            or any(u not in vertices or v not in vertices for u,v in arcs)):
            return None
        graphs[idx]=(vertices,arcs)
    return graphs


def _directed_connectivity(vertices,arcs):
    if not vertices:
        return None
    adj=_adjacency(vertices,arcs,True)
    reverse=_adjacency(vertices,[(v,u) for u,v in arcs],True)
    undirected=_adjacency(vertices,arcs,False)
    start=vertices[0]
    weak=len(_reachable(undirected,start))==len(vertices)
    strong=(len(_reachable(adj,start))==len(vertices)
            and len(_reachable(reverse,start))==len(vertices))
    return strong,weak


def solve_certified_graph(question, llm_reply=None):
    """Return a correct answer from certified edges, or None (do not override).

    The original OCR must be certified by two independent image-only reads.
    No "proof" is claimed for OCR image fidelity. For unknown/ambiguous
    image topology, the caller's existing fail-closed review still applies.
    """
    if not isinstance(question,str) or FLAG in question:
        return None
    section=_graph_section(question)
    if not section:
        return None
    request=_active_request(question)
    # Existing proof or generation workflows are untouched.
    if not request or re.search(
        r"(?:出|编|设计|生成|创作).{0,12}(?:一道|几道|题|练习)",request
    ):
        return None
    if (_DIRECTED_CERT in section
        and re.search(r"强连通|弱连通|strongly\s+connected|weakly\s+connected",request,re.I)):
        graphs=_directed_graphs(section)
        if graphs is None:
            return None
        lines=[]
        for i,(v,e) in sorted(graphs.items()):
            strong,weak=_directed_connectivity(v,e)
            verdict=("是强连通图" if strong else
                     "不是强连通图，但属于弱连通图" if weak else
                     "既不是强连通图，也不是弱连通图")
            lines.append(f"图({i})：{verdict}（{len(v)} 个顶点、{len(e)} 条有向边）。")
        return "根据独立逐箭头核对一致的原图边集，忽略箭头判断弱连通，再检查正反方向可达性：\n"+"\n".join(lines)
    if _SINGLE_CERT not in section and OK_MARKER not in section:
        return None
    if OK_MARKER in section and _SINGLE_CERT not in section:
        # A certified isomorphism pair needs its own exact isomorphism solver,
        # already implemented in graph_integrity.answer_graph_isomorphism.
        return None
    if detect_named_graph_degree_inconsistency(section):
        return None
    graph=single_undirected_named_edges(section)
    if graph is None:
        return None
    stats=_undirected_stats(graph)
    if not stats:
        return None
    diameter_question=bool(re.search(r"直径|diameter",request,re.I))
    chromatic_question=bool(re.search(r"色数|着色数|染色数|chromatic\s+number",request,re.I))
    euler_question=bool(re.search(r"欧拉图|欧拉回路|Eulerian|Euler\s+circuit",request,re.I))
    if not (diameter_question or chromatic_question or euler_question):
        return None
    lines=[f"已核对的无向图有 {len(stats['vertices'])} 个顶点、{len(stats['edges'])} 条边。"]
    if diameter_question:
        if stats["diameter"] is None:
            lines.append("图不连通，因此不存在有限的全图直径（按扩展距离约定则为无穷大）。")
        else:
            lines.append(f"逐顶点运行最短路广度优先搜索，所有顶点对最短路长度的最大值为 **{stats['diameter']}**，即图的直径。")
    if chromatic_question:
        result=_chromatic_number(stats)
        if result is None:
            return None
        number,colors=result
        colortable="、".join(f"{v}→{colors[v]+1}" for v in sorted(colors))
        lines.append(f"从 1 色开始逐一检验合法染色的最小值，得到色数 **{number}**。"
                     f"一种合法 {number} 染色为：{colortable}。")
    if euler_question:
        degrees=stats["degrees"]
        used={v for v in degrees if degrees[v]>0}
        edge_component=not used or len(_reachable(stats["adj"],min(used)) & used)==len(used)
        odd=sorted(v for v in degrees if degrees[v]%2)
        if edge_component and len(odd)==0:
            if stats["connected"]:
                lines.append("图连通且所有顶点度数均为偶数，因此是欧拉图，存在欧拉回路。")
            else:
                lines.append("所有非孤立顶点构成一个连通分量且度数为偶数，故存在覆盖全部边的欧拉闭迹；"
                             "但图含孤立顶点、整体不连通，按要求全图连通的定义不属于欧拉图。")
        elif edge_component and len(odd)==2:
            lines.append(f"奇度顶点为 {'、'.join(odd)}，恰有两个，只有欧拉通路而没有欧拉回路；因此不是欧拉图。")
        else:
            lines.append(f"奇度顶点：{'、'.join(odd) if odd else '无'}；"
                         "非孤立顶点不是单个连通分量，或奇度顶点数不为 0/2；因此没有欧拉回路。")
    return "\n".join(lines)
