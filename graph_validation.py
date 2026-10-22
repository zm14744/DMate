"""Conservative mathematical graph consistency audit.

Mathematical invariants do not establish agreement with original image pixels.
Never infer, remove, or add edges from these checks.
"""
from __future__ import annotations


def audit_graph_records(graphs):
    """Return advisory review issues, preserving the source edge table."""
    if not isinstance(graphs, list):
        return ['图结构记录格式错误']
    issues = []
    try:
        import networkx as nx
    except ImportError:
        return ['图结构校验库未安装，无法执行数学一致性检查']
    for index, graph in enumerate(graphs[:12], 1):
        if not isinstance(graph, dict):
            issues.append(f'图{index}不是有效图结构')
            continue
        name = str(graph.get('id') or f'图{index}')
        vertices = graph.get('vertices') or []
        edges = graph.get('edges') or []
        ids = [str(v.get('id')) for v in vertices if isinstance(v, dict)]
        if len(set(ids)) != len(ids) or len(ids) != len(vertices):
            issues.append(f'{name}存在重复或无效顶点')
            continue
        directed = graph.get('directed') is True
        multi = graph.get('multigraph') is True
        cls = nx.MultiDiGraph if (directed and multi) else (
            nx.DiGraph if directed else nx.MultiGraph if multi else nx.Graph)
        actual = cls()
        actual.add_nodes_from(ids)
        seen = set()
        for edge in edges:
            if isinstance(edge, dict):
                u, v = str(edge.get('from')), str(edge.get('to'))
            elif isinstance(edge, (list, tuple)) and len(edge) == 2:
                u, v = str(edge[0]), str(edge[1])
            else:
                issues.append(f'{name}有无法解析的边')
                continue
            if u not in actual or v not in actual:
                issues.append(f'{name}边 {u}-{v} 引用了不存在的顶点')
                continue
            pair = (u, v) if directed else tuple(sorted((u, v)))
            if pair in seen and graph.get('multigraph') is False:
                issues.append(f'{name}声明为简单图，但有重复端点对 {u}-{v}')
            seen.add(pair)
            actual.add_edge(u, v)
        if graph.get('complete') is True and graph.get('uncertain_edges'):
            issues.append(f'{name}标记完整，却仍有待核对边')
        if graph.get('multigraph') is False and any(u == v for u, v in actual.edges()):
            issues.append(f'{name}声明为简单图，但存在自环')
        if isinstance(graph.get('vertex_count'), int) and graph['vertex_count'] != actual.number_of_nodes():
            issues.append(f'{name}顶点数与顶点表不一致')
        if isinstance(graph.get('confirmed_edge_count'), int) and graph['confirmed_edge_count'] != len(edges):
            issues.append(f'{name}边数与边表不一致')
    return list(dict.fromkeys(issues))[:15]


__all__ = ['audit_graph_records']
