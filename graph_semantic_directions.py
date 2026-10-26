"""Direction-only readings with stable edge-instance identities.

No coordinates, pixel proofs, graph invariants or reference answers are used.
Existing content survives malformed or incomplete responses.
"""
from __future__ import annotations

import copy
import json
from collections import Counter


DIRECTION_PROMPT = r'''你是独立的箭头方向复核者，只看原图中每条已有边的箭头尖实际朝向哪一个端点，不解题。
任务中的 endpoints 是无序端点；程序按ID排序，与当前方向无关。edge.id 只是已有边实例的内部标识，edge_label 才是印刷边名。
完整原图和重叠放大局部来自同一页面，不是新增子图。先沿这条实际弧线找到箭头尖，再判断其所指端点。
同一对端点可以有两条同向弧，也可以有反向弧；必须按不同 id 逐条读，不能根据对称版式或“应当互相相反”猜方向。
自环仍是同一条已有边，其 from 与 to 相同。平行边即使所有属性一样也不能合并，不新增、删去或改名边/点。
只返回方向，不改题干、节点、边名、权值、颜色、线型。每条请求中的边实例必须返回一次，graph.id 和 edge.id 原样使用。
读清时返回 from、to 和 direction="forward"；无法看清时只返回该 id 与 direction="unknown"，不能猜测或补边。
格式：{"graphs":[{"id":"G1","edges":[{"id":"edge_1","from":"a","to":"b","direction":"forward"}]}],"uncertainties":[]}。
uncertainties 仅写仍未确定的事项，可用 {"graph_id":"G1","edge_ids":["edge_1"],"message":"该箭头尖被遮挡"}，不要复述已改好的问题。'''


def _id(value):
    if type(value) is str and value.strip() and len(value) <= 160:
        return value
    if type(value) is int:
        return value
    return None


def _issue(kind, *, graph_id=None, edge_ids=None, message=None):
    result = {'scope': 'graph' if graph_id is not None else 'document', 'kind': kind,
              'message': message or '箭头方向尚未逐条核对完整，保留已有内容。'}
    if graph_id is not None:
        result['graph_id'] = graph_id
    if edge_ids:
        result['edge_ids'] = list(edge_ids)
    return result


def _pair(edge):
    a, b = _id(edge.get('from')), _id(edge.get('to'))
    return None if a is None or b is None else sorted((a, b), key=lambda value: json.dumps(value, ensure_ascii=False))


def _prepared(draft):
    document = copy.deepcopy(draft)
    if not isinstance(document, dict) or not isinstance(document.get('graphs'), list):
        raise ValueError('direction_draft_requires_graph_list')
    graphs, issues, generated = {}, [], []
    ids = Counter(_id(graph.get('id')) for graph in document['graphs'] if isinstance(graph, dict))
    for graph in document['graphs']:
        gid = _id(graph.get('id')) if isinstance(graph, dict) else None
        if gid is None or ids[gid] != 1:
            issues.append(_issue('invalid_or_duplicate_direction_graph', graph_id=gid))
            continue
        if not isinstance(graph.get('edges'), list) or not isinstance(graph.get('vertices'), list):
            issues.append(_issue('invalid_direction_graph_inventory', graph_id=gid))
            continue
        reserved = {_id(edge.get('id')) for edge in graph['edges'] if isinstance(edge, dict)} - {None}
        for index, edge in enumerate(graph['edges'], 1):
            if not isinstance(edge, dict):
                continue
            if _id(edge.get('id')) is None:
                eid, suffix = f'direction_edge_{index}', 1
                while eid in reserved:
                    eid = f'direction_edge_{index}_{suffix}'
                    suffix += 1
                edge['id'] = eid
                reserved.add(eid)
                generated.append({'graph_id': gid, 'edge_index': index-1, 'edge_id': eid})
        edge_ids = Counter(_id(edge.get('id')) for edge in graph['edges'] if isinstance(edge, dict))
        vertices = {_id(vertex.get('id')) for vertex in graph['vertices'] if isinstance(vertex, dict)} - {None}
        selected = {}
        for edge in graph['edges']:
            if not isinstance(edge, dict):
                issues.append(_issue('invalid_direction_edge', graph_id=gid))
                continue
            # Per-edge semantics win over a stale aggregate graph flag. A
            # known undirected edge in a mixed graph is not an arrow task.
            if (edge.get('direction') == 'undirected'
                    or graph.get('directed') is not True and edge.get('direction') not in ('forward', 'unknown')):
                continue
            eid, pair = edge['id'], _pair(edge)
            if edge_ids[eid] != 1:
                issues.append(_issue('duplicate_original_direction_edge_id', graph_id=gid, edge_ids=[eid]))
            elif pair is None or any(endpoint not in vertices for endpoint in pair):
                issues.append(_issue('invalid_original_direction_endpoints', graph_id=gid, edge_ids=[eid]))
            else:
                selected[eid] = edge
        if selected:
            graphs[gid] = (graph, selected)
    return document, graphs, issues, generated


def build_direction_task(draft):
    """Project unordered pairs and printed attributes, never current directions.

    Explicit IDs are unchanged. Missing edge IDs are assigned deterministically
    in the copy; apply_direction_reading uses exactly the same assignment.
    """
    _, graphs, _, _ = _prepared(draft)
    rows = []
    for gid, (graph, edges) in graphs.items():
        rows.append({'id': gid, 'name': copy.deepcopy(graph.get('name')),
            'vertices': [{key: copy.deepcopy(vertex[key]) for key in ('id', 'label', 'position') if key in vertex}
                         for vertex in graph['vertices'] if isinstance(vertex, dict)],
            'edges': [{'id': eid, 'endpoints': _pair(edge), **{key: copy.deepcopy(edge[key]) for key in
                ('edge_label', 'weight', 'color', 'style') if key in edge}} for eid, edge in edges.items()]})
    return {'graphs': rows}


def apply_direction_reading(draft, response):
    """Apply only validated instance directions; retain every other field."""
    document, graphs, issues, generated = _prepared(draft)
    audit = {'scope': 'existing_edge_directions_only', 'generated_edge_ids': generated,
             'requested_edges': sum(len(edges) for _, edges in graphs.values()),
             'confirmed_edges': [], 'changes': [], 'ignored_response_fields': []}

    def finish():
        audit.update(status='partial' if issues else 'applied', issue_count=len(issues),
                     all_requested_edges_confirmed=(not issues and len(audit['confirmed_edges']) == audit['requested_edges']))
        return {'document': document, 'issues': issues, 'audit': audit}

    if not isinstance(response, dict) or not isinstance(response.get('graphs'), list):
        issues.append(_issue('invalid_direction_response'))
        return finish()
    audit['ignored_response_fields'] += [key for key in response if key not in ('graphs', 'uncertainties')]
    rows = response['graphs']
    counts = Counter(_id(row.get('id')) for row in rows if isinstance(row, dict))
    seen_graphs = set()
    for row in rows:
        gid = _id(row.get('id')) if isinstance(row, dict) else None
        if gid not in graphs:
            issues.append(_issue('unexpected_direction_graph', graph_id=gid))
            continue
        if gid in seen_graphs:
            continue
        seen_graphs.add(gid)
        _, edges = graphs[gid]
        if counts[gid] != 1:
            issues.append(_issue('duplicate_direction_graph', graph_id=gid, edge_ids=edges))
            continue
        if not isinstance(row.get('edges'), list):
            issues.append(_issue('invalid_direction_edge_list', graph_id=gid, edge_ids=edges))
            continue
        extras = [key for key in row if key not in ('id', 'edges')]
        if extras:
            audit['ignored_response_fields'].append({'graph_id': gid, 'fields': extras})
        edge_rows = row['edges']
        edge_counts = Counter(_id(edge.get('id')) for edge in edge_rows if isinstance(edge, dict))
        seen_edges = set()
        for proposed in edge_rows:
            eid = _id(proposed.get('id')) if isinstance(proposed, dict) else None
            if eid not in edges:
                issues.append(_issue('unexpected_direction_edge', graph_id=gid, edge_ids=[eid] if eid is not None else None))
                continue
            if eid in seen_edges:
                continue
            seen_edges.add(eid)
            original = edges[eid]
            if edge_counts[eid] != 1:
                issues.append(_issue('duplicate_direction_edge', graph_id=gid, edge_ids=[eid]))
                continue
            direction = proposed.get('direction')
            if direction == 'unknown':
                pair = _pair(proposed)
                absent = proposed.get('from') is None and proposed.get('to') is None
                if not absent and pair != _pair(original):
                    issues.append(_issue('direction_endpoints_mismatch', graph_id=gid, edge_ids=[eid]))
                else:
                    issues.append(_issue('direction_uncertain', graph_id=gid, edge_ids=[eid],
                                         message='本条箭头仍看不清，保留已有方向草稿，不能当作已确认。'))
                continue
            if direction != 'forward':
                issues.append(_issue('invalid_direction_value', graph_id=gid, edge_ids=[eid]))
                continue
            if _pair(proposed) != _pair(original):
                issues.append(_issue('direction_endpoints_mismatch', graph_id=gid, edge_ids=[eid]))
                continue
            before = {key: original.get(key) for key in ('from', 'to', 'direction')}
            after = {key: proposed[key] for key in ('from', 'to', 'direction')}
            original.update(after)
            identity = {'graph_id': gid, 'edge_id': eid}
            audit['confirmed_edges'].append(identity)
            if before != after:
                audit['changes'].append({**identity, 'before': before, 'after': copy.deepcopy(after)})
            extras = [key for key in proposed if key not in ('id', 'from', 'to', 'direction')]
            if extras:
                audit['ignored_response_fields'].append({**identity, 'fields': extras})
        missing = [eid for eid in edges if eid not in seen_edges]
        if missing:
            issues.append(_issue('missing_direction_edges', graph_id=gid, edge_ids=missing))
    for gid, (_, edges) in graphs.items():
        if gid not in seen_graphs:
            issues.append(_issue('missing_direction_graph', graph_id=gid, edge_ids=edges))
    uncertainties = response.get('uncertainties', [])
    if not isinstance(uncertainties, list):
        issues.append(_issue('invalid_direction_uncertainties'))
    else:
        for uncertain in uncertainties:
            if isinstance(uncertain, str) and uncertain.strip():
                issues.append(_issue('direction_uncertain', message=uncertain[:500]))
            elif isinstance(uncertain, dict):
                gid, eids = _id(uncertain.get('graph_id')), uncertain.get('edge_ids', [])
                if gid not in graphs or not isinstance(eids, list) or any(_id(eid) not in graphs[gid][1] for eid in eids):
                    issues.append(_issue('invalid_direction_uncertainty_scope'))
                else:
                    message = uncertain.get('message')
                    issues.append(_issue('direction_uncertain', graph_id=gid, edge_ids=eids,
                        message=message[:500] if isinstance(message, str) and message.strip() else None))
            else:
                issues.append(_issue('invalid_direction_uncertainty'))
    return finish()


__all__ = ['DIRECTION_PROMPT', 'build_direction_task', 'apply_direction_reading']
