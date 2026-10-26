"""Short, image-grounded readers for the content DMate actually renders.

Geometry and CPU tracing are optional aids, never acceptance requirements.
Every visual role receives the original image in a fresh model context. The
canonical result is shared by the review UI and solver; an incomplete review
retains useful content instead of replacing the document with an empty graph.
"""
from __future__ import annotations

import copy
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TypedDict

from graph_agent_runtime import AgentBudget, AgentCancelled, RoleRunner
from graph_pipeline_version import AGENT_PIPELINE_VERSION
from graph_semantic_schema import MAX_GRAPHS, normalize_semantic_document
from graph_semantic_sources import SOURCE_READ_PROMPT, merge_source_readings, source_batches
from graph_semantic_changes import meaningful_review_changes
from vision_provider import VisionError, VisionProvider


SEMANTIC_PROMPT = r'''你是数学题图片的读取智能体。只转录图片内容，不解题，不按图名、度数、欧拉性质或常见模板补图。
任务是读清用户最终需要的题干、每幅独立子图、顶点和每一条边。内部坐标、线条路径、证据框、候选编号不需要输出。
先逐幅找齐真实顶点，再从每个顶点沿可见连线逐一找终点。箭头尖、文字笔画、普通交叉处不是额外顶点；有明确圆点/圆圈或图示定义才计点。不能漏掉孤立顶点。
一条无向边只记录一次；同一对端点有两条不同弧线时必须保留两条；反向弧、自环也分别保留。箭头决定from→to，不能从版式猜方向。
不同子图即使节点同名也保持独立；(a)、(b)、G₁等图注用于图名，不能当顶点。整个页面的局部放大图都是同一原图的视图，不能重复计图或计边。
逐条保留印刷边名(e₁等)、权值、实线/虚线/点线以及有意义的颜色。边名和权值不同，不要把e₁读成权值1。保留大小写、下标、负号、零、公式和小问编号。
题干body_text包含所有可见问题、小问和必要文字；节点/边标签放在图中，不重复混进题干。没有题干就用空字符串。
原图是内容与颜色的依据。辅助增强和本地OCR可能有错；透印、阴影不能凭增强图变成新边。模糊或裁切处只保留确实可见内容，并简短注明不确定项，不编造被裁掉的文字。
只返回一个紧凑JSON对象，不写说明、推理或Markdown。格式：
{"body_text":"原图题干", "graphs":[{"id":"G1","name":"原有图注或G1","directed":false,"vertices":[{"id":"a","label":"a"},{"id":"b","label":"b"}],"edges":[{"from":"a","to":"b","direction":"undirected","edge_label":"e₁","weight":3,"color":"red","style":"dashed"}]}],"uncertainties":[]}
graphs可以是空数组。vertices的id用于边引用；没有印刷标签的顶点label=null，按本幅从上到下、从左到右稳定编号v1、v2；可用position短语辅助区分，例如“左上”，无需坐标。边id可以省略，程序会补内部ID。
direction只用forward或undirected，无法看清箭头用unknown并注明不确定。style用solid/dashed/dotted；看不清则不填。无权值/无边名/无特殊颜色的字段可省略。weighted和multigraph可省略，程序根据边表整理。
uncertainties只放还未解决的内容问题，格式可为{"scope":"body|graph|document","graph_id":"G1","message":"具体看不清什么"}，不要因为没有坐标或内部字段产生不确定项。'''

REVIEW_PROMPT = SEMANTIC_PROMPT + r'''
你是独立视觉复核智能体。任务数据里的draft只是上一轮草稿，可能漏图、漏点、把箭头当点、漏边、反转箭头或误读文字，不能当答案照抄。
重新看原图，先核对每幅图的节点清单，再以每个节点为起点检查它连接的所有边及箭头。逐项比较题干中的字母/下标/否定词/数量与所有边的标签、权值、颜色、线型。
草稿边已经按源节点分别读取；仍须对原图复核，尤其是不同读取有分歧的边。沿线追到真实端点，不在交叉处换线；箭头以实际尖端为准。保留现有顶点ID与粗略位置以便对应同一点，只有原图确有错点/漏点才调整节点。
local_connection_candidates是OpenCV和sknw的实际局部线迹候选，请对照原图核查与草稿不同的端点、平行弧和箭头。候选可能包含文字、断线或交叉处误接；没有候选不能证明没有边，同一笔画的不同工具结果也不能当成多条边或独立投票。不要用工具的路径长度当印刷权值。
直接返回你修正后的完整JSON文档。发现并修好的错误不放uncertainties；只留下仍无法从原图确定的内容。不需要复述修改日志，不需要逐边附证据。'''

VERIFY_PROMPT = r'''你是独立的只读审核智能体。对照完整原图和局部原像素，核查draft中的题干、独立子图、顶点、逐条连边和属性。不要解题，不按图名、度数或常见图模板判断边。
draft已按源节点读边；它可能错，也可能正确。你的职责是明确指出有原图依据的内容差异，不能返回另一整份图或顺手重写已经正确的其他内容。
先核对各图的真实顶点，再沿每条线追踪端点，检查平行线、自环和孤立点；普通交叉、箭头尖和文字不是节点。指明错误的图和边。不要因为缺坐标、线迹、证明字段，或普通黑色字段缺省而报告错误。
任务中的local_connection_candidates、local_ocr_candidates来自实际本地工具，只帮助找位置与读文字。误检、断线、文字笔画、重复候选都可能存在；候选不是答案，缺候选不是缺边，路径长度不是印刷权值。不同工具对同一笔画的提议不能增加边数。
题干仅含原图实际印刷的正文及小问，不允许用图的结构描述替代正文。核对大小写、下标、数字、否定词和小问，图内标签与图注不混入正文。
只返回JSON：{"issues":[]}。没有发现差异时issues为空；有差异时每项为{"scope":"body|graph|document","graph_id":"仅graph时填写","field":"body_text|name|vertices|edges|direction|weight|edge_label|color|style","edge_ids":["现有边id，可省略"],"source_ids":["涉及的源点id，可省略"],"message":"具体可见差异及需要重读的局部"}。
漏图或分图错误才使用document；单幅图的问题必须使用graph和对应id。箭头、权值等单字段问题应注明field和edge_ids；缺边/错接注明edges及source_ids。未知字段不要猜id。只列实际仍有问题的部分，不为显得严格而制造分歧。不要输出graphs、完整修正文档、推理或Markdown。'''

INVENTORY_PROMPT = r'''只读取这张数学题图片的题干、独立子图和真实顶点清单，暂不读取边。
题干包含所有小问、数字、下标、否定词和公式；图内顶点/边标签不要重复放进题干。原图没有题干则body_text=""。裁切内容不能补写。
逐幅清点真实圆点/圆圈，不能把交叉、箭头尖、文字笔画当顶点，也不能漏掉孤立点。不同图注(a)/(b)/G₁属于不同子图；同图的非连通分量仍在同一图中。辅助局部视图都是同一张原图，不能重复计图。
有印刷标签的点原样保留，匿名点label=null；内部id在本图唯一。明确用标签或线端表示的数学顶点即使没有圆点也保留。匿名点按从上到下、从左到右编号，并用position简短描述所在行列/内外环/左右位置。可附x,y表示相对整张原图0..1000的粗略中心，帮助后续读边定位，不要求精确，坐标不影响内容验收。
每幅图建议附position说明其在整页的位置（如“上排中间”），以及可选bbox=[left,top,right,bottom]表示相对整张原图0..1000的宽松范围，包含外弧和图注，后续仅用于放大。不是图内局部坐标，不需要精确，不确定时可省略。图注里的“欧拉图”等结论不能用来反推顶点或连边。
如果能明确对应local_layout_candidates中的候选窗口，可附layout_panel_ids列出窗口id；窗口仅辅助局部放大，一个窗口可以包含多幅图，一幅图也可以对应多个窗口，不确定时省略。
任务中的local_layout_candidates来自实际版面工具，local_marker_candidates来自OpenCV原像素检测。先借助这些候选找到各图与圆点，再对原图核对：一个版面框可以含多幅图，一幅非连通图也可以含多个墨迹块；候选中的文字圆圈、交叉等必须排除。候选没找到的真实点仍可补入，不能把工具候选数量当成答案。
只返回紧凑JSON：{"body_text":"原图题干","graphs":[{"id":"G1","name":"原图图注或G1","vertices":[{"id":"v1","label":null,"position":"上方外环","x":500,"y":100}],"edges":[]}],"uncertainties":[]}。
graphs可以为空。每图edges必须为空，后续独立读边角色会读取连接，不能根据常见图形猜答案。颜色、阴影、透印以原图为准；只把仍无法读清的问题写入uncertainties，字段scope=body/graph/document，graph问题附graph_id。'''

BODY_PROMPT = r'''只逐字转录原图中图形外实际印刷的题干和所有小问，不解题，不解释或描述图结构。
不能根据节点、连线和权值生成“图中有……”“各图的边权分别为……”之类描述；图内标签、图注(a)/(b)和边权表不是题干。不得补写原图之外的文字。
所有局部图都是同一张原图的放大，不重复抄写。认真核对数字、字母、下标、否定词和每个小问。
没有题干就返回空字符串。顶部/底部文字被切掉时，只抄确实可见的残段，在uncertainties中注明裁切，不能把残句补成合理题目。
只输出JSON：{"body_text":"逐字原文或空字符串","uncertainties":[]}；未读清项为{"scope":"body","message":"具体未确定内容"}。不要输出graphs、推理或Markdown。'''

REPAIR_PROMPT = REVIEW_PROMPT + r'''
这是同一次上传的最后一轮定向复核。重点检查remaining_issues指出的内容；原图优先，必要时修正节点清单，然后从涉及的源节点重读连边。
有field和edge_ids的局部属性问题只修对应字段，保留图id和边id；单纯箭头问题不能改变端点集合、节点、权值或边名。
保留已经看清的其他题干和子图，返回完整文档。无法确认的局部继续注明，不删除整幅可用图，也不要为了满足某种图论性质加边或删边。'''


class SemanticRunner(RoleRunner):
    """Keep transport accounting while allowing one explicit visual specialist."""

    def _provider_for(self, role):
        if role not in ('semantic_specialist', 'semantic_edges_glm', 'semantic_edges_glm_fast',
                        'semantic_body_glm', 'semantic_directions_glm'):
            return super()._provider_for(role)
        from vision_provider import GLM_5V_TURBO_MODEL
        remote = self.provider.get(role) if isinstance(self.provider, dict) else None
        remote = remote or VisionProvider('glm', model=GLM_5V_TURBO_MODEL,
                                           thinking=role == 'semantic_edges_glm',
                                           retries=0, capture=self.capture)
        if (getattr(remote, 'name', None) != 'glm'
                or getattr(remote, 'model', None) != GLM_5V_TURBO_MODEL
                or getattr(remote, 'retries', 0) != 0):
            raise ValueError('semantic_specialist_requires_glm5v_without_hidden_retries')
        return remote

    def specialist_available(self):
        try:
            remote = self._provider_for('semantic_specialist')
            return not hasattr(remote, 'available') or remote.available()
        except (ImportError, ValueError):
            return False


class _State(TypedDict, total=False):
    draft: dict
    normalized: dict
    reviewed: bool
    errors: list
    content_read: bool
    source_audit: dict
    review_changes: list
    direction_audit: dict
    body_checked: bool
    geometry_issues: list
    repair_scope_audit: dict
    verification_issues: list
    program_issues: list
    body_review_required: bool


def _issue(kind, message):
    return {'scope': 'document', 'kind': kind, 'message': message}


def _draft_view(value):
    """Content and optional coarse location aids, without proof protocols."""
    if not isinstance(value, dict):
        return {}
    result = {'body_text': value.get('body_text', ''), 'graphs': []}
    def rows(field):
        return field if isinstance(field, list) else []
    for row in rows(value.get('graphs'))[:MAX_GRAPHS]:
        if not isinstance(row, dict):
            continue
        graph = {k: copy.deepcopy(row[k]) for k in
                 ('id', 'name', 'directed', 'weighted', 'multigraph', 'position', 'bbox', 'layout_panel_ids') if k in row}
        graph['vertices'] = [{k: copy.deepcopy(v[k]) for k in ('id', 'label', 'position', 'x', 'y') if k in v}
                             for v in rows(row.get('vertices'))[:100] if isinstance(v, dict)]
        graph['edges'] = [{k: copy.deepcopy(e[k]) for k in
                          ('id', 'from', 'to', 'direction', 'weight', 'edge_label', 'color', 'style') if k in e}
                         for e in rows(row.get('edges'))[:300] if isinstance(e, dict)]
        result['graphs'].append(graph)
    if isinstance(value.get('uncertainties'), list):
        result['uncertainties'] = copy.deepcopy(value['uncertainties'][:40])
    return result


def _has_vertices(draft):
    return any(isinstance(g, dict) and isinstance(g.get('vertices'), list) and g['vertices']
               for g in draft.get('graphs', [])) if _readable_document(draft) else False


def _review_changes(previous, current):
    # Retained for callers/tests of the V2 helper; the implementation is shared.
    return meaningful_review_changes(previous, current)


def _readable_document(value):
    # This is a small serialization boundary, not a visual proof protocol.
    # An empty/malformed response must not erase an earlier usable document.
    return (isinstance(value, dict) and isinstance(value.get('body_text'), str)
            and isinstance(value.get('graphs'), list))


def _has_content(value):
    if not _readable_document(value):
        return False
    return bool(value['body_text'].strip()) or any(
        isinstance(graph, dict) and isinstance(graph.get('vertices'), list)
        and any(isinstance(vertex, dict) for vertex in graph['vertices'])
        for graph in value['graphs'])


def _scope_repair(previous, proposed, issues):
    """A focused recheck cannot silently rewrite unaffected panels or text.

    A missing initial read or document-wide ambiguity still needs a complete
    reread. Otherwise only named panels and the explicitly disputed body may
    change. No geometric or expected-topology rule selects an answer here.
    """
    if (not _has_content(previous) or not isinstance(issues, list)
            or any(isinstance(row, dict) and row.get('scope') == 'document'
                   for row in issues)):
        return proposed, {'mode': 'whole_document_required'}
    graph_ids = {str(row['graph_id']) for row in issues
                 if isinstance(row, dict) and row.get('scope') == 'graph'
                 and row.get('graph_id') is not None}
    body_allowed = any(isinstance(row, dict) and row.get('scope') == 'body' for row in issues)
    # A generic graph uncertainty cannot be localised to an existing panel.
    if any(isinstance(row, dict) and row.get('scope') == 'graph'
           and row.get('graph_id') is None for row in issues):
        return proposed, {'mode': 'whole_graph_inventory_required'}
    result = copy.deepcopy(previous)
    proposed_graphs = {str(graph.get('id', '')): graph for graph in proposed.get('graphs', [])
                       if isinstance(graph, dict)}
    old_graph_ids = {str(graph.get('id', '')) for graph in previous.get('graphs', [])
                     if isinstance(graph, dict)}
    changed, retained, missing, field_audit = [], [], [], []
    rows = []
    for graph in previous.get('graphs', []):
        gid = str(graph.get('id', '')) if isinstance(graph, dict) else ''
        if gid in graph_ids and gid in proposed_graphs:
            local_issues = [row for row in issues if isinstance(row, dict)
                            and str(row.get('graph_id', '')) == gid]
            patched, permissions = _scope_graph_fields(graph, proposed_graphs[gid], local_issues)
            rows.append(patched)
            field_audit.append({'graph_id': gid, **permissions})
            changed.append(gid)
        else:
            rows.append(copy.deepcopy(graph))
            retained.append(gid)
            if gid in graph_ids:
                missing.append(gid)
    # A genuinely disputed added panel may be supplied; unrelated additions
    # never change a previously read page's panel inventory.
    for gid in graph_ids - old_graph_ids:
        if gid in proposed_graphs:
            rows.append(copy.deepcopy(proposed_graphs[gid]))
            changed.append(gid)
    result['graphs'] = rows
    if body_allowed:
        result['body_text'] = proposed.get('body_text', previous.get('body_text', ''))
    old_uncertainties = previous.get('uncertainties', [])
    kept = [copy.deepcopy(row) for row in old_uncertainties if not (
        isinstance(row, dict) and ((body_allowed and row.get('scope') == 'body')
            or (row.get('scope') == 'graph' and str(row.get('graph_id', '')) in changed)))] \
        if isinstance(old_uncertainties, list) else []
    for row in proposed.get('uncertainties', []) if isinstance(proposed.get('uncertainties'), list) else []:
        if (not isinstance(row, dict) or row.get('scope') == 'document'
                or (body_allowed and row.get('scope') == 'body')
                or str(row.get('graph_id', '')) in graph_ids):
            kept.append(copy.deepcopy(row))
    kept.extend({'scope': 'graph', 'graph_id': gid,
                 'message': '定向复核未返回该子图，已保留原有读法。'} for gid in missing)
    kept.extend({'scope': 'graph', 'graph_id': record['graph_id'],
                 'kind': 'scoped_attribute_unresolved', 'edge_id': eid,
                 'message': '局部属性复核未能对应原边，已保留其他已读内容。'}
                for record in field_audit for eid in record.get('unresolved_edge_ids', []))
    kept.extend({'scope': 'graph', 'graph_id': record['graph_id'],
                 'kind': 'scoped_attribute_unresolved',
                 'message': '局部复核未确定可修改字段，已保留原有图结构。'}
                for record in field_audit if record.get('unresolved_graph'))
    result['uncertainties'] = kept
    return result, {'mode': 'scoped_panels_and_body', 'allowed_graph_ids': sorted(graph_ids),
                    'body_allowed': body_allowed, 'updated_graph_ids': sorted(changed),
                    'retained_graph_ids': sorted(retained), 'missing_graph_ids': sorted(missing),
                    'field_permissions': field_audit}


def _scope_graph_fields(previous, proposed, issues):
    """Narrow attribute reviews cannot replace nodes or unrelated edges.

    Structural conflicts still allow the named panel to be reread. Stable edge
    IDs are an application identity, never an image-accuracy requirement.
    """
    kind_fields = {'unknown_direction': 'direction', 'invalid_weight': 'weight',
                   'invalid_edge_label': 'edge_label', 'invalid_color': 'color',
                   'invalid_style': 'style'}
    allowed = {}
    name_allowed = False
    for issue in issues:
        field = issue.get('field') or kind_fields.get(issue.get('kind'))
        if field == 'name':
            name_allowed = True
            continue
        edge_ids = issue.get('edge_ids')
        if edge_ids is None and issue.get('edge_id') is not None:
            edge_ids = [issue['edge_id']]
        if field in ('vertices', 'edges') or field is None:
            return copy.deepcopy(proposed), {'mode': 'panel_structure', 'reason': 'structural_or_unlocalized_issue'}
        if field not in ('direction', 'weight', 'edge_label', 'color', 'style'):
            return copy.deepcopy(previous), {'mode': 'no_attribute_permission', 'unresolved_graph': True}
        if not isinstance(edge_ids, list) or not edge_ids:
            # An arrow/weight reader may omit IDs. Its scope stays that one
            # attribute on the existing edges; absence of IDs never grants
            # permission to add vertices, reconnect or replace the panel.
            edge_ids = [edge.get('id') for edge in previous.get('edges', []) if isinstance(edge, dict)]
        for eid in edge_ids:
            allowed.setdefault(str(eid), set()).add(field)
    result = copy.deepcopy(previous)
    if name_allowed and 'name' in proposed:
        result['name'] = copy.deepcopy(proposed['name'])
    replacements = {str(edge.get('id')): edge for edge in proposed.get('edges', []) if isinstance(edge, dict)}
    changed, unresolved = [], []
    for edge in result.get('edges', []):
        if not isinstance(edge, dict):
            continue
        eid = str(edge.get('id'))
        fields = allowed.get(eid, set())
        if not fields:
            continue
        replacement = replacements.get(eid)
        if replacement is None:
            unresolved.append(eid)
            continue
        for field in fields:
            if field == 'direction':
                if sorted((str(edge.get('from')), str(edge.get('to')))) != sorted(
                        (str(replacement.get('from')), str(replacement.get('to')))):
                    unresolved.append(eid)
                    continue
                for key in ('from', 'to', 'direction'):
                    if key in replacement:
                        edge[key] = copy.deepcopy(replacement[key])
            elif field in replacement:
                edge[field] = copy.deepcopy(replacement[field])
            else:
                edge.pop(field, None)
        changed.append({'edge_id': eid, 'fields': sorted(fields)})
    # Unknown/relabelled IDs do not silently become a successful attribute edit.
    existing_ids = {str(e.get('id')) for e in previous.get('edges', []) if isinstance(e, dict)}
    unresolved.extend(sorted(set(allowed) - existing_ids))
    return result, {'mode': 'edge_fields', 'name_allowed': name_allowed,
                    'changed': changed, 'unresolved_edge_ids': sorted(set(unresolved))}


def _verification_issues(response, draft):
    if not isinstance(response, dict) or not isinstance(response.get('issues'), list):
        raise ValueError('semantic_verification_unreadable')
    if len(response['issues']) > 80:
        raise ValueError('semantic_verification_capacity')
    graph_ids = {str(g.get('id')) for g in draft.get('graphs', []) if isinstance(g, dict)}
    result = []
    for row in response['issues']:
        if (not isinstance(row, dict) or row.get('scope') not in ('body', 'graph', 'document')
                or not isinstance(row.get('message'), str) or not row['message'].strip()):
            raise ValueError('semantic_verification_invalid_issue')
        item = {k: copy.deepcopy(row[k]) for k in
                ('scope', 'graph_id', 'field', 'edge_ids', 'source_ids', 'message') if k in row}
        item['kind'] = 'visual_review_conflict'
        item['message'] = item['message'][:1000]
        if item['scope'] == 'graph' and str(item.get('graph_id', '')) not in graph_ids:
            raise ValueError('semantic_verification_unknown_graph')
        for key in ('edge_ids', 'source_ids'):
            if key in item and (not isinstance(item[key], list) or len(item[key]) > 100
                               or any(not isinstance(x, (str, int)) or isinstance(x, bool) for x in item[key])):
                raise ValueError('semantic_verification_invalid_ids')
        result.append(item)
    return result


def recognize_semantic(raw, *, layout=None, provider=None, budget=None, audit=False,
                       text_result=None, cancelled=None, task_id=None):
    from langgraph.graph import START, END, StateGraph
    from langsmith import tracing_context
    from graph_semantic_images import prepare_semantic_images
    from graph_semantic_layout import prepare_semantic_layout
    from graph_semantic_geometry import prepare_semantic_geometry
    from graph_semantic_text import prepare_semantic_text

    source_sha = hashlib.sha256(raw).hexdigest()
    budget = budget or AgentBudget.configured(source_sha256=source_sha,
                                               task_id=task_id, cancelled=cancelled)
    if budget.source_sha256 is not None and budget.source_sha256 != source_sha:
        raise ValueError('source_identity_mismatch')
    budget.source_sha256 = source_sha
    if cancelled is not None:
        budget.cancelled = cancelled
    budget.check(minimum=3)
    local_layout = prepare_semantic_layout(raw, budget=budget, layout=layout,
                                           run_layout=True, layout_timeout=18.0)
    budget.local_tool_execution = {'layout': {key: copy.deepcopy(local_layout[key]) for key in
        ('layout', 'panels', 'body_regions', 'diagnostics', 'resource_metrics') if key in local_layout}}
    initial_geometry = prepare_semantic_geometry(raw, budget=budget,
        layout=local_layout, document=local_layout.get('document'))
    budget.local_tool_execution['markers'] = {key: copy.deepcopy(initial_geometry[key]) for key in
        ('marker_candidates', 'diagnostics') if key in initial_geometry}
    local_text = prepare_semantic_text(raw, budget=budget, layout=local_layout,
        document=initial_geometry.get('document'), text_result=text_result)
    budget.local_tool_execution['text'] = {key: copy.deepcopy(local_text[key]) for key in
        ('text_hints', 'regions', 'diagnostics', 'resource_metrics') if key in local_text}
    geometry = initial_geometry
    views = prepare_semantic_images(raw, budget=budget, text_result=local_text, layout=layout)
    # Layout proposals actively choose source-pixel views, but never determine
    # how many mathematical graphs the page contains. Keep the full original.
    layout_images = local_layout.get('images', [])
    layout_descriptions = local_layout.get('view_descriptions', [])
    if len(layout_images) > 1 and len(layout_images) == len(layout_descriptions):
        images, descriptions = [views['images'][0]], [views['view_descriptions'][0]]
        for img, description in zip(layout_images[1:], layout_descriptions[1:]):
            if len(images) >= 5:
                break
            if img not in images:
                images.append(img)
                descriptions.append(description)
        # A shade-normalised view remains useful if the layout leaves room.
        if len(images) < 5 and views['image_quality'].get('normalization_view_included'):
            images.append(views['images'][-1])
            descriptions.append(views['view_descriptions'][-1])
        views['images'], views['view_descriptions'] = images, descriptions
        views['image_quality']['view_count'] = len(images)
        views['image_quality']['layout_views_included'] = True
    runner = SemanticRunner(budget, provider=provider, capture=audit)
    responses, stages, response_lock = [], [], threading.Lock()
    extra_view_audit = []
    program_audits = []
    specialist = runner.specialist_available()

    def text_hints(graph=None, *, body=False):
        # OCR positions select reading assistance only. Unlocated items remain
        # available, and the full original remains the final authority.
        box = graph.get('bbox') if isinstance(graph, dict) else None
        box = box if isinstance(box, (list, tuple)) and len(box) == 4 else None
        rows, characters = [], 0
        for row in local_text.get('text_hints', []):
            if not isinstance(row, dict):
                continue
            hint_box = row.get('bbox')
            if box and isinstance(hint_box, list) and len(hint_box) == 4:
                if (hint_box[2] < box[0] or hint_box[0] > box[2]
                        or hint_box[3] < box[1] or hint_box[1] > box[3]):
                    continue
            if body and row.get('role_hint') == 'graph_label':
                continue
            length = len(str(row.get('text', '')))
            if len(rows) >= 96 or characters+length > 8000:
                break
            rows.append(copy.deepcopy(row))
            characters += length
        return rows

    def remember(role, result, *, task=None):
        if task is None:
            record = {'role': role, 'document': _draft_view(result)}
        else:
            sources = result.get('sources', [])
            record = {'role': role, 'graph_id': task['graph_id'],
                      'source_ids': copy.deepcopy(task['source_ids']), 'sources': []}
            for source in sources[:100] if isinstance(sources, list) else []:
                if not isinstance(source, dict):
                    continue
                edges = source.get('edges', [])
                record['sources'].append({'id': source.get('id'), 'edges': [
                    {k: copy.deepcopy(e[k]) for k in ('to', 'direction', 'weight', 'edge_label', 'color', 'style') if k in e}
                    for e in (edges[:300] if isinstance(edges, list) else []) if isinstance(e, dict)]})
        with response_lock:
            responses.append(record)
            stages.append(role)

    def read(role, prompt, draft=None, issues=None, *, readonly=False):
        request = {'image_views': views['view_descriptions']}
        request['local_layout_candidates'] = {
            'panels': local_layout.get('panels', [])[:32],
            'body_regions': local_layout.get('body_regions', [])[:32],
            'candidate_only': True,
        }
        request['local_ocr_candidates'] = text_hints()
        if draft is None:
            request['local_marker_candidates'] = initial_geometry.get('marker_candidates', [])[:160]
        elif geometry.get('graphs'):
            request['local_connection_candidates'] = geometry['graphs'][:32]
        if draft is None:
            request['local_ocr_hint_may_be_wrong'] = views.get('local_text_hint', '')
        else:
            request['draft'] = _draft_view(draft)
        if issues:
            request['remaining_issues'] = issues[:30]
        if readonly:
            request['review_mode'] = 'read_only'
        budget.event(role, 'local_tool_hints_supplied',
            layout_panel_count=len(request['local_layout_candidates']['panels']),
            marker_candidate_count=len(request.get('local_marker_candidates', [])),
            connection_graph_count=len(request.get('local_connection_candidates', [])),
            text_candidate_count=len(request['local_ocr_candidates']))
        result = runner.call(role, prompt, request, views['images'],
                             revision=len(responses), output_tokens=10000,
                             response_identity=False)
        if readonly:
            with response_lock:
                responses.append({'role': role, 'review_mode': 'read_only',
                                  'issues': copy.deepcopy(result.get('issues', []))})
                stages.append(role)
        else:
            remember(role, result)
        return result

    def attempt(role, prompt, state, *, reviewed, inventory=False, final=False):
        try:
            remaining = (state.get('normalized', {}).get('semantic_issues', [])
                         + state.get('review_changes', []) + state.get('errors', [])
                         + state.get('verification_issues', []) + state.get('program_issues', []))
            draft = read(role, prompt, state.get('draft'),
                         remaining)
            if not _readable_document(draft):
                raise ValueError('semantic_document_unreadable')
            previous = state.get('draft')
            if _has_content(previous) and not _has_content(draft):
                raise ValueError('semantic_review_removed_all_content')
            scope_audit = state.get('repair_scope_audit', {})
            if final and state.get('reviewed'):
                draft, scope_audit = _scope_repair(previous, draft, remaining)
            if inventory:
                # The next role must actually read edges from pixels. Do not
                # leak an accidental first-stage edge proposal into its input.
                draft = copy.deepcopy(draft)
                for graph in draft['graphs']:
                    if isinstance(graph, dict):
                        graph['edges'] = []
            independently_reviewed = (reviewed and state.get('content_read', False)
                and _readable_document(previous)
                and (_has_content(previous) or not _has_content(draft)))
            normalized = normalize_semantic_document(draft, reviewed=independently_reviewed)
            changes = (meaningful_review_changes(previous, draft) if reviewed and independently_reviewed and not final
                       and not state.get('reviewed') else [])
            return {**state, 'draft': draft, 'normalized': normalized, 'reviewed': independently_reviewed,
                    'content_read': not _has_vertices(draft) if inventory else True,
                    'review_changes': changes, 'errors': [], 'verification_issues': [],
                    'body_review_required': (state.get('body_review_required', False)
                        or bool(draft.get('body_text', '').strip())
                        or any(row.get('scope') == 'body' for row in remaining)),
                    'repair_scope_audit': scope_audit}
        except AgentCancelled:
            raise
        except (VisionError, ValueError, TimeoutError) as exc:
            kind = exc.kind if isinstance(exc, VisionError) else type(exc).__name__
            budget.event(role, 'content_unavailable', error_kind=kind)
            return {**state, 'errors': state.get('errors', []) + [
                _issue(kind, '本轮视觉复核未完成，已保留可读取的内容。')]}

    def extract(state):
        return attempt('semantic_extract', INVENTORY_PROMPT, state, reviewed=False, inventory=True)

    def sources(state):
        nonlocal geometry
        draft = state.get('draft')
        if not _has_vertices(draft):
            return state
        from graph_semantic_panel_context import panel_context
        draft = copy.deepcopy(draft)
        for index, graph in enumerate(draft['graphs']):
            if isinstance(graph, dict):
                contextual = panel_context(graph, local_layout)
                draft['graphs'][index] = contextual['graph']
                extra_view_audit.append({'phase': 'layout_panel_association',
                    'graph_id': str(graph.get('id', f'G{index+1}')), **contextual['audit']})
        geometry = prepare_semantic_geometry(raw, draft=draft, budget=budget,
            layout=local_layout, document=initial_geometry.get('document'))
        budget.local_tool_execution['connections'] = {key: copy.deepcopy(geometry[key]) for key in
            ('graphs', 'issues', 'diagnostics') if key in geometry}
        try:
            batches = source_batches(draft, max_sources=6)
        except ValueError as exc:
            budget.event('semantic_edges', 'invalid_inventory', error_kind=str(exc))
            return {**state, 'errors': state.get('errors', []) + [
                _issue('source_inventory_unavailable', '节点清单尚有歧义，由完整视觉复核重新读取。')]}
        # Leave calls for independent review, a focused correction and bounded
        # transport recovery. Missing groups stay explicit in reconciliation.
        limit = max(0, budget.remaining - 4)
        selected = batches[:limit]
        reserve = min(70.0, max(0.0, (budget.deadline-time.monotonic()) * .35))
        from graph_semantic_arrow_views import prepare_panel_views
        graph_lookup = {str(g.get('id') or f'G{i}'): g for i, g in enumerate(draft['graphs'], 1)
                        if isinstance(g, dict)}
        scoped_views = {}
        for task in selected:
            gid = task['graph_id']
            if gid not in scoped_views:
                scoped_views[gid] = prepare_panel_views(raw, graph=graph_lookup.get(gid, {}),
                    overview_views=views, budget=budget)
                extra_view_audit.append({'phase': 'source_panel', 'graph_id': gid,
                    'tool_audit': scoped_views[gid].get('tool_audit', []),
                    'image_quality': scoped_views[gid].get('image_quality', {})})
            graph = graph_lookup.get(gid, {})
            if isinstance(graph.get('position'), str):
                task['panel_position'] = graph['position']
        # Multi-panel pages spent the entire source window on reasoning-only
        # streams in the real V2 run. Focus their pixels and use the same GLM
        # model without extended thinking; single dense graphs keep thinking.
        glm_source_role = 'semantic_edges_glm_fast' if len(draft['graphs']) >= 3 else 'semantic_edges_glm'

        def read_batch(item):
            index, task = item
            roles = [glm_source_role, 'semantic_edges'] if specialist else ['semantic_edges']
            for role in roles:
                try:
                    budget.check(minimum=reserve + 3)
                    focused = scoped_views[task['graph_id']]
                    candidates = next((row for row in geometry.get('graphs', [])
                        if str(row.get('graph_id', row.get('id', ''))) == str(task['graph_id'])), {})
                    budget.event(role, 'local_tool_hints_supplied', graph_id=task['graph_id'],
                        connection_candidate_count=len(candidates.get('candidates', [])))
                    result = runner.call(role, SOURCE_READ_PROMPT,
                        {'image_views': focused['view_descriptions'], 'task': task,
                         'local_connection_candidates': candidates,
                         'local_ocr_candidates': text_hints(graph_lookup.get(task['graph_id'])),
                         'candidate_only': True}, focused['images'],
                        revision=index+1, output_tokens=8000, response_identity=False,
                        reserve_seconds=reserve)
                    remember(role, result, task=task)
                    if not isinstance(result.get('sources'), list):
                        raise ValueError('source_response_unreadable')
                    return {**task, 'response': result}
                except AgentCancelled:
                    raise
                except (VisionError, ValueError, TimeoutError) as exc:
                    kind = exc.kind if isinstance(exc, VisionError) else type(exc).__name__
                    budget.event(role, 'content_unavailable', graph_id=task['graph_id'],
                                 source_ids=task['source_ids'], error_kind=kind)
            return {**task, 'response': {}}

        with ThreadPoolExecutor(max_workers=2, thread_name_prefix='semantic-source') as pool:
            readings = list(pool.map(read_batch, enumerate(selected)))
        merged = merge_source_readings(draft, readings)
        source_audit = merged['source_audit']
        covered = all(not g['missing_source_ids'] and not g['invalid_source_ids']
                      for g in source_audit['graphs'])
        return {**state, 'draft': merged['document'], 'source_audit': source_audit,
                'content_read': covered,
                'geometry_issues': copy.deepcopy(geometry.get('issues', [])),
                'normalized': normalize_semantic_document(merged['document'], reviewed=False)}

    def program_check(state):
        from graph_semantic_tools import inspect_semantic_graphs
        normalized = state.get('normalized')
        if not isinstance(normalized, dict):
            return state
        try:
            inspected = inspect_semantic_graphs(normalized, budget=budget)
        except AgentCancelled:
            raise
        except (ImportError, ValueError, TimeoutError) as exc:
            budget.event('semantic_program_check', 'tool_unavailable', error_kind=type(exc).__name__)
            return state
        program_audits.extend(copy.deepcopy(inspected.get('tool_audit', [])))
        budget.local_tool_execution['program'] = copy.deepcopy(inspected)
        return {**state, 'program_issues': copy.deepcopy(inspected.get('issues', []))}

    def review(state):
        # An incomplete source phase needs a complete reader to recover the
        # document. Otherwise the independent reviewer only identifies local
        # disagreements; it cannot replace already correct panels on its own.
        if not state.get('content_read') or not _has_content(state.get('draft')):
            return attempt('semantic_review', REVIEW_PROMPT, state, reviewed=True)
        try:
            remaining = (state.get('normalized', {}).get('semantic_issues', [])
                         + state.get('errors', []) + state.get('program_issues', []))
            response = read('semantic_review', VERIFY_PROMPT, state['draft'], remaining, readonly=True)
            findings = _verification_issues(response, state['draft'])
            return {**state, 'reviewed': True, 'verification_issues': findings,
                    'body_review_required': (state.get('body_review_required', False)
                        or any(row.get('scope') == 'body' for row in findings)),
                    'normalized': normalize_semantic_document(state['draft'], reviewed=True)}
        except AgentCancelled:
            raise
        except (VisionError, ValueError, TimeoutError) as exc:
            kind = exc.kind if isinstance(exc, VisionError) else type(exc).__name__
            budget.event('semantic_review', 'content_unavailable', error_kind=kind)
            return {**state, 'errors': state.get('errors', []) + [
                _issue(kind, '独立视觉审核尚未完成，已保留原有题干和图结构。')]}

    def needs_repair(state):
        issues = state.get('normalized', {}).get('semantic_issues', [])
        if (not state.get('reviewed') or issues or state.get('errors')
                or state.get('review_changes') or state.get('verification_issues') or state.get('program_issues')):
            if budget.remaining > 0 and budget.deadline-time.monotonic() >= 18:
                return 'repair'
        return 'done'

    def repair(state):
        role = 'semantic_specialist' if specialist else 'semantic_repair'
        return attempt(role, REPAIR_PROMPT, state, reviewed=True, final=True)

    def focused_checks(state):
        """Literal body OCR and arrow-only checks cannot rewrite graph content."""
        from graph_semantic_arrow_views import prepare_arrow_views
        from graph_semantic_directions import (DIRECTION_PROMPT, build_direction_task,
                                                apply_direction_reading)
        if not _has_content(state.get('draft')):
            return state
        draft = copy.deepcopy(state['draft'])
        direction_task = build_direction_task(draft)
        body_needed = (state.get('body_review_required', False) or bool(draft.get('body_text', '').strip())
                      or any(row.get('role_hint') == 'body' for row in local_text.get('text_hints', []))
                      or any(
            x.get('scope') == 'body' for x in state.get('normalized', {}).get('semantic_issues', []))
                      )
        jobs = []
        if body_needed:
            jobs.append(('body', BODY_PROMPT, {}))
        if direction_task.get('graphs'):
            jobs.append(('directions', DIRECTION_PROMPT, {'task': direction_task}))
        if not jobs:
            return state
        try:
            detail = prepare_arrow_views(raw, budget=budget)
        except AgentCancelled:
            raise
        except (TimeoutError, ValueError) as exc:
            budget.event('semantic_focused_checks', 'content_unavailable', error_kind=type(exc).__name__)
            return {**state, 'errors': state.get('errors', []) + [
                _issue('focused_review_unavailable', '题干或箭头的定向原图复核尚未完成，已保留原有读法。')]}
        extra_view_audit.append({'phase': 'focused_details',
            'tool_audit': detail.get('tool_audit', []), 'image_quality': detail.get('image_quality', {})})

        def dispatch(job):
            kind, prompt, task = job
            ordinary = 'semantic_' + kind
            roles = [ordinary + '_glm', ordinary] if specialist else [ordinary]
            for role in roles:
                try:
                    response = runner.call(role, prompt,
                        {'image_views': detail['view_descriptions'], **task,
                         **({'local_geometry_candidates': geometry.get('graphs', [])[:32]}
                            if kind == 'directions' else
                            {'local_body_regions': local_layout.get('body_regions', [])[:32],
                             'local_ocr_candidates': text_hints(body=True)})}, detail['images'],
                        revision=len(responses), output_tokens=5000, response_identity=False)
                    if kind == 'body':
                        if not isinstance(response.get('body_text'), str):
                            raise ValueError('literal_body_unreadable')
                        remember(role, {'body_text': response['body_text'], 'graphs': [],
                                        'uncertainties': response.get('uncertainties', [])})
                    else:
                        if not isinstance(response.get('graphs'), list):
                            raise ValueError('direction_response_unreadable')
                        record = {'role': role, 'direction_reading': {'graphs': []}}
                        for graph in response['graphs'][:MAX_GRAPHS]:
                            if not isinstance(graph, dict):
                                continue
                            edges = graph.get('edges', [])
                            record['direction_reading']['graphs'].append({'id': graph.get('id'),
                                'edges': [{key: copy.deepcopy(edge[key]) for key in
                                    ('id', 'from', 'to', 'direction') if key in edge}
                                    for edge in (edges[:300] if isinstance(edges, list) else [])
                                    if isinstance(edge, dict)]})
                        with response_lock:
                            responses.append(record)
                            stages.append(role)
                    return kind, response, None
                except AgentCancelled:
                    raise
                except (VisionError, ValueError, TimeoutError) as exc:
                    kind_error = exc.kind if isinstance(exc, VisionError) else type(exc).__name__
                    budget.event(role, 'content_unavailable', error_kind=kind_error)
            return kind, None, {'scope': 'body' if kind == 'body' else 'document',
                'kind': 'focused_' + kind + '_unavailable',
                'message': '逐字题干复核未完成。' if kind == 'body' else '箭头局部复核未完成，已保留原有连接。'}

        with ThreadPoolExecutor(max_workers=2, thread_name_prefix='semantic-detail') as pool:
            checked = list(pool.map(dispatch, jobs))
        errors = list(state.get('errors', []))
        changes = list(state.get('review_changes', []))
        direction_audit = {}
        body_checked = False
        for kind, response, error in checked:
            if error:
                errors.append(error)
                continue
            if kind == 'body':
                if not response['body_text'].strip() and not draft.get('graphs'):
                    errors.append({'scope': 'body', 'kind': 'literal_body_removed_all_content',
                                   'message': '逐字复核为空，已保留此前可读正文。'})
                    continue
                draft['body_text'] = response['body_text']
                old_uncertainties = draft.get('uncertainties', [])
                draft['uncertainties'] = [x for x in old_uncertainties
                    if not isinstance(x, dict) or x.get('scope') != 'body'] if isinstance(old_uncertainties, list) else []
                new_uncertainties = response.get('uncertainties', [])
                if isinstance(new_uncertainties, list):
                    for issue in new_uncertainties[:40]:
                        if isinstance(issue, str) and issue.strip():
                            draft['uncertainties'].append({'scope': 'body', 'message': issue})
                        elif isinstance(issue, dict) and isinstance(issue.get('message'), str):
                            draft['uncertainties'].append({'scope': 'body', 'message': issue['message']})
                changes = [x for x in changes if x.get('scope') != 'body']
                body_checked = True
            else:
                patched = apply_direction_reading(draft, response)
                draft = patched['document']
                direction_audit = patched.get('audit', {})
                # The direction adapter scopes each unresolved edge itself.
                errors.extend(patched.get('issues', []))
        return {**state, 'draft': draft,
                'normalized': normalize_semantic_document(draft, reviewed=state.get('reviewed', False)),
                'errors': errors, 'review_changes': changes,
                'direction_audit': direction_audit, 'body_checked': body_checked}

    flow = StateGraph(_State)
    flow.add_node('extract', extract)
    flow.add_node('sources', sources)
    flow.add_node('review', review)
    flow.add_node('program_check', program_check)
    flow.add_node('repair', repair)
    flow.add_node('focused_checks', focused_checks)
    flow.add_node('final_program_check', program_check)
    flow.add_edge(START, 'extract')
    flow.add_edge('extract', 'sources')
    flow.add_edge('sources', 'program_check')
    flow.add_edge('program_check', 'review')
    flow.add_conditional_edges('review', needs_repair, {'repair': 'repair', 'done': 'focused_checks'})
    flow.add_edge('repair', 'focused_checks')
    flow.add_edge('focused_checks', 'final_program_check')
    flow.add_edge('final_program_check', END)
    with tracing_context(enabled=False):
        state = flow.compile().invoke({'errors': [], 'reviewed': False, 'content_read': False})
    if budget.cancelled is not None and budget.cancelled():
        raise AgentCancelled('upload_cancelled')
    result = copy.deepcopy(state.get('normalized'))
    if not result:
        error = VisionError('semantic_visual_read_unavailable')
        if audit:
            error.graph_stage_audit = {'responses': responses, 'observations': runner.observations}
        raise error
    errors = state.get('errors', []) + state.get('verification_issues', []) + state.get('program_issues', [])
    if errors:
        result.setdefault('semantic_issues', []).extend(errors)
        if any(issue.get('scope') in ('body', 'document') for issue in errors):
            result['body_complete'] = False
        for graph in result['graphs']:
            if any(issue.get('scope') == 'document' or issue.get('graph_id') == graph['id'] for issue in errors):
                graph['complete'] = False
    if state.get('review_changes'):
        result.setdefault('semantic_issues', []).extend(state['review_changes'])
        if any(issue.get('scope') == 'body' for issue in state['review_changes']):
            result['body_complete'] = False
        for graph in result['graphs']:
            if any(issue.get('graph_id') == graph['id'] for issue in state['review_changes']):
                graph['complete'] = False
    if not state.get('reviewed'):
        result['body_complete'] = False
        for graph in result['graphs']:
            graph['complete'] = False
    result['complete'] = bool(state.get('reviewed') and result.get('body_complete')
        and all(graph.get('complete') for graph in result['graphs'])
        and not result.get('semantic_issues'))
    result.update(
        diagnostics=stages, remote_metrics=copy.deepcopy(budget.metrics),
        image_quality=views['image_quality'],
        body_audit={'second_pass_reviewed': state.get('reviewed') is True},
        local_layout_result=copy.deepcopy(local_layout.get('layout', {})),
        local_text_result={key: copy.deepcopy(local_text[key]) for key in ('text', 'text_evidence') if key in local_text},
        local_resource_metrics=copy.deepcopy(local_layout.get('resource_metrics', [])
                                             + local_text.get('resource_metrics', [])),
        semantic_workflow={
            'version': AGENT_PIPELINE_VERSION, 'acceptance_scope': 'rendered_semantics',
            'task_id': budget.task_id, 'source_sha256': source_sha,
            'reviewed': state.get('reviewed') is True,
            'roles': copy.deepcopy(budget.events),
            'tool_audit': (views['tool_audit'] + local_layout.get('tool_audit', [])
                           + local_text.get('tool_audit', [])
                           + initial_geometry.get('tool_audit', [])
                           + (geometry.get('tool_audit', []) if geometry is not initial_geometry else [])
                           + program_audits),
            'role_counts': copy.deepcopy(budget.role_counts),
            'geometry_required': False,
            'edge_strategy': 'node_inventory_then_source_conditioned_edges',
            'source_audit': copy.deepcopy(state.get('source_audit', {})),
            'direction_audit': copy.deepcopy(state.get('direction_audit', {})),
            'literal_body_checked': state.get('body_checked') is True,
            'view_audit': copy.deepcopy(extra_view_audit),
            'repair_scope': copy.deepcopy(state.get('repair_scope_audit', {})),
            'local_tools': {
                'layout': {key: copy.deepcopy(local_layout[key]) for key in
                    ('layout', 'panels', 'body_regions', 'diagnostics', 'resource_metrics')
                    if key in local_layout},
                'markers': {key: copy.deepcopy(initial_geometry[key]) for key in
                    ('marker_candidates', 'diagnostics') if key in initial_geometry},
                'text': {key: copy.deepcopy(local_text[key]) for key in
                    ('text_hints', 'regions', 'diagnostics', 'resource_metrics') if key in local_text},
                'connections': {key: copy.deepcopy(geometry[key]) for key in
                    ('graphs', 'issues', 'diagnostics') if key in geometry},
                'program': copy.deepcopy(budget.local_tool_execution.get('program', {})),
            },
            'readings': copy.deepcopy(responses),
        })
    if audit:
        result['stage_audit'] = {'responses': responses, 'observations': runner.observations}
    return result


__all__ = ['recognize_semantic', 'SemanticRunner']
