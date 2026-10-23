"""Qwen-only review of missed strokes, grounded in original image ink.

Uses the existing geometry guards; no extra provider, topology template, degree
completion, remote request or additional review budget is introduced.
"""
from __future__ import annotations
import copy
from graph_schema import canonical_graph, path_points
from graph_relation import _wrong_path_endpoints, _intermediate_nodes, route_overlap
from graph_glm_adapter import _ink_support, receive_review_routes

MAX_ADDITIONS = 8

REVIEW_HINT = '''
Qwen逐笔画复核：先看原图中各端点对之间的真实笔画，不把候选数量当正确重数。
候选可能遗漏外侧弧线、平行直线、自环、虚线；同一线的不同近似路径也可能重复。
若visible=true但候选path明显不准，可在decision中补充path和style；path必须沿真实整条线，
使用完整原图归一化坐标，首尾严格取固定顶点坐标，弯曲线采样中段（最多8点）。
若在原图明确看到候选表完全漏掉的独立笔画，在本图的additional_edges列表逐条提出：
{"from":"已有顶点ID","to":"已有顶点ID","direction":"forward|undirected|unknown",
"weight":null,"edge_label":null,"path":[[0.1,0.2],[0.2,0.3]],"style":"solid"}。
这是字段形状示例，不是图片答案；不能添加顶点、跨图连线或照抄示例坐标。
每条新增笔画都要有独立可见的完整path，最多8条；没有遗漏则additional_edges=[]。
方向的forward仍以该条from→to为准，曲线不能用端点直线代替。
系统会独立检查真实墨迹、路径端点、途中顶点和重复线迹；只报visible不能跳过检查。
无法沿原图确认的线不添加，inventory_complete=false。不要按图名或数学性质补边。
'''


def receive_qwen_review(graph, decisions, additions, ink, *, traces=()):
    """Accept only existing endpoints and independently supported full paths.

    Returned decisions address new internal IDs, so a response cannot overwrite
    an old edge's identity. RELATE still rejects intersected vertices, shared
    strokes, unresolved direction/weight, and duplicate proposals afterwards.
    """
    graph = receive_review_routes(graph, decisions, ink, source='qwen')
    decisions = copy.deepcopy(decisions)
    diagnostics = []
    if additions is None:
        return graph, decisions, diagnostics
    if not isinstance(additions, list):
        return graph, decisions, ['qwen_review_additions_invalid']
    if len(additions) > MAX_ADDITIONS:
        diagnostics.append('qwen_review_additions_truncated')
    ids = {v['id'] for v in graph['vertices']}
    edge_ids = {e['id'] for e in graph['edges']} | set(decisions)
    accepted = 0
    audit=graph.setdefault('qwen_review_audit',[])
    for raw in additions[:MAX_ADDITIONS]:
        if (not isinstance(raw, dict) or not isinstance(raw.get('from'), str)
                or not isinstance(raw.get('to'), str) or raw['from'] not in ids
                or raw['to'] not in ids or len(graph['edges']) >= 96):
            diagnostics.append('qwen_review_addition_rejected:inventory')
            continue
        route = path_points(raw.get('path'))
        direction = raw.get('direction')
        if not route or len(route) > 8 or direction not in ('forward', 'undirected', 'unknown'):
            diagnostics.append('qwen_review_addition_rejected:contract')
            continue
        candidate = {**raw, 'path': route}
        if (_wrong_path_endpoints(candidate, graph['vertices'], tolerance=.02)
                or _intermediate_nodes(route, candidate, graph['vertices'])):
            diagnostics.append('qwen_review_addition_rejected:geometry')
            continue
        proof = _ink_support(route, ink, raw.get('style'), source='qwen')
        binding=None
        if proof is None:
            # A coarse VLM polyline is not fabricated ink. Bind it only when
            # exactly ONE strong existing trace follows the same corridor and
            # joins the same known endpoints. Ambiguous parallel traces remain
            # unresolved, and RELATE still deduplicates shared strokes.
            choices=[]
            for trace in traces[:96]:
                path=path_points(trace.get('path'))
                if (not path or {trace.get('from'),trace.get('to')}!={raw['from'],raw['to']}
                        or trace.get('score',0)<.8):
                    continue
                traced={**candidate,'path':path}
                if (_wrong_path_endpoints(traced,graph['vertices'],tolerance=.02)
                        or _intermediate_nodes(path,traced,graph['vertices'])):
                    continue
                if route_overlap(route,path,tolerance=.025)>=.85:
                    choices.append((path,trace))
            if len(choices)==1:
                path,trace=choices[0]
                proof=_ink_support(path,ink,raw.get('style'),source='qwen')
                if proof is not None:
                    binding={'source':'qwen_review_trace_binding','observed_path':copy.deepcopy(route),
                             'trace_method':trace.get('method'),'trace_score':trace.get('score')}
                    route=path
        if proof is None:
            diagnostics.append('qwen_review_addition_rejected:ink_gap')
            audit.append({'status':'rejected','reason':'ink_gap','from':raw['from'],
                          'to':raw['to'],'path':copy.deepcopy(route)})
            continue
        # Visible ink does not establish a second stroke. Existing VLM paths
        # can be offset from the measured rim/center line; keep one identity
        # when both full routes occupy the same endpoint-compatible corridor.
        duplicate = next((edge for edge in graph['edges']
                          if {edge.get('from'), edge.get('to')} == {raw['from'], raw['to']}
                          and path_points(edge.get('path'))
                          and route_overlap(route, path_points(edge['path']), tolerance=.025) >= .85), None)
        if duplicate is not None:
            diagnostics.append('qwen_review_addition_rejected:duplicate_stroke')
            audit.append({'status':'rejected','reason':'duplicate_stroke',
                          'existing_id':duplicate['id'],'from':raw['from'],
                          'to':raw['to'],'path':copy.deepcopy(route)})
            continue
        n = 1
        while f'qwen_review_{n}' in edge_ids:
            n += 1
        eid = f'qwen_review_{n}'
        edge_ids.add(eid)
        candidate.update(id=eid, path=route, status='pending', evidence=[
            {'source': 'qwen_review_new_stroke', **proof}])
        if binding is not None:candidate['evidence'].append(binding)
        graph['edges'].append(candidate)
        decisions[eid] = {**copy.deepcopy(raw), 'id': eid, 'visible': True}
        audit.append({'status':'received','id':eid,'from':raw['from'],'to':raw['to'],
                      'path':copy.deepcopy(route),'proof':proof})
        accepted += 1
    if accepted:
        diagnostics.append(f'qwen_review_strokes_added:{accepted}')
    return canonical_graph(graph), decisions, diagnostics
