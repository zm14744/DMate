"""Short, image-grounded readers for the content DMate actually renders.

Geometry and CPU tracing are optional aids, never acceptance requirements.
Every visual role receives the original image in a fresh model context. The
canonical result is shared by the review UI and solver; an incomplete review
retains useful content instead of replacing the document with an empty graph.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import TypedDict

from graph_agent_runtime import AgentBudget, AgentCancelled, RoleRunner
from graph_pipeline_version import AGENT_PIPELINE_VERSION
from graph_semantic_schema import MAX_GRAPHS, normalize_semantic_document
from graph_semantic_sources import SOURCE_READ_PROMPT, merge_source_readings, source_batches
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
直接返回你修正后的完整JSON文档。发现并修好的错误不放uncertainties；只留下仍无法从原图确定的内容。不需要复述修改日志，不需要逐边附证据。'''

INVENTORY_PROMPT = r'''只读取这张数学题图片的题干、独立子图和真实顶点清单，暂不读取边。
题干包含所有小问、数字、下标、否定词和公式；图内顶点/边标签不要重复放进题干。原图没有题干则body_text=""。裁切内容不能补写。
逐幅清点真实圆点/圆圈，不能把交叉、箭头尖、文字笔画当顶点，也不能漏掉孤立点。不同图注(a)/(b)/G₁属于不同子图；同图的非连通分量仍在同一图中。辅助局部视图都是同一张原图，不能重复计图。
有印刷标签的点原样保留，匿名点label=null；内部id在本图唯一。匿名点按从上到下、从左到右编号，并用position简短描述所在行列/内外环/左右位置。可附x,y表示相对整张原图0..1000的粗略中心，帮助后续读边定位，不要求精确，坐标不影响内容验收。
只返回紧凑JSON：{"body_text":"原图题干","graphs":[{"id":"G1","name":"原图图注或G1","vertices":[{"id":"v1","label":null,"position":"上方外环","x":500,"y":100}],"edges":[]}],"uncertainties":[]}。
graphs可以为空。每图edges必须为空，后续独立读边角色会读取连接，不能根据常见图形猜答案。颜色、阴影、透印以原图为准；只把仍无法读清的问题写入uncertainties，字段scope=body/graph/document，graph问题附graph_id。'''

REPAIR_PROMPT = REVIEW_PROMPT + r'''
这是同一次上传的最后一轮定向复核。重点检查remaining_issues指出的内容；原图优先，必要时修正节点清单，然后从涉及的源节点重读连边。
保留已经看清的其他题干和子图，返回完整文档。无法确认的局部继续注明，不删除整幅可用图，也不要为了满足某种图论性质加边或删边。'''


class SemanticRunner(RoleRunner):
    """Keep transport accounting while allowing one explicit visual specialist."""

    def _provider_for(self, role):
        if role not in ('semantic_specialist', 'semantic_edges_glm'):
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
                 ('id', 'name', 'directed', 'weighted', 'multigraph') if k in row}
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
    """A changed reading gets one focused check, never an automatic reversal."""
    def comparable(value):
        value = copy.deepcopy(value)
        if isinstance(value, dict) and isinstance(value.get('graphs'), list):
            for graph in value['graphs']:
                if not isinstance(graph, dict) or not isinstance(graph.get('edges'), list):
                    continue
                for edge in graph['edges']:
                    if isinstance(edge, dict) and edge.get('style') in (None, ''):
                        edge['style'] = 'solid'
        return normalize_semantic_document(value)
    before = comparable(previous)
    after = comparable(current)
    changes = []
    if ''.join(before.get('body_text', '').split()) != ''.join(after.get('body_text', '').split()):
        changes.append({'scope': 'body', 'kind': 'independent_body_reading_changed',
            'message': '节点盘点时的题干与独立整图复核题干不同，请按原图核对每个小问、数字、字母、下标和否定词。'})
    old_graphs = {g['id']: g for g in before['graphs']}
    new_graphs = {g['id']: g for g in after['graphs']}
    for gid in sorted(old_graphs.keys() | new_graphs.keys()):
        old, new = old_graphs.get(gid, {}), new_graphs.get(gid, {})
        def edge_bag(graph):
            records = []
            for edge in graph.get('edges', []):
                a, b = edge.get('from'), edge.get('to')
                direction = edge.get('direction')
                if direction == 'undirected':
                    a, b = sorted((str(a), str(b)))
                style = edge.get('style')
                records.append(json.dumps([a, b, direction, edge.get('weight'),
                    edge.get('edge_label'), edge.get('color'), style], ensure_ascii=False, sort_keys=True))
            return Counter(records)
        left, right = edge_bag(old), edge_bag(new)
        old_vertices = Counter((v['id'], v.get('label')) for v in old.get('vertices', []))
        new_vertices = Counter((v['id'], v.get('label')) for v in new.get('vertices', []))
        if left != right or old_vertices != new_vertices or old.get('name') != new.get('name'):
            changes.append({'scope': 'graph', 'graph_id': gid, 'kind': 'independent_reading_changed',
                'message': '逐源读边与整图复核存在不同读法，请按原图确认修改，不能按边数或常见图形选答案。',
                'removed_or_changed_instances': sum((left-right).values()),
                'added_or_changed_instances': sum((right-left).values())})
    return changes


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


def recognize_semantic(raw, *, layout=None, provider=None, budget=None, audit=False,
                       text_result=None, cancelled=None, task_id=None):
    from langgraph.graph import START, END, StateGraph
    from langsmith import tracing_context
    from graph_semantic_images import prepare_semantic_images

    source_sha = hashlib.sha256(raw).hexdigest()
    budget = budget or AgentBudget.configured(source_sha256=source_sha,
                                               task_id=task_id, cancelled=cancelled)
    if budget.source_sha256 is not None and budget.source_sha256 != source_sha:
        raise ValueError('source_identity_mismatch')
    budget.source_sha256 = source_sha
    if cancelled is not None:
        budget.cancelled = cancelled
    budget.check(minimum=3)
    views = prepare_semantic_images(raw, budget=budget, text_result=text_result, layout=layout)
    runner = SemanticRunner(budget, provider=provider, capture=audit)
    responses, stages, response_lock = [], [], threading.Lock()
    specialist = runner.specialist_available()

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

    def read(role, prompt, draft=None, issues=None):
        request = {'image_views': views['view_descriptions']}
        if draft is None:
            request['local_ocr_hint_may_be_wrong'] = views.get('local_text_hint', '')
        else:
            request['draft'] = _draft_view(draft)
        if issues:
            request['remaining_issues'] = issues[:30]
        result = runner.call(role, prompt, request, views['images'],
                             revision=len(responses), output_tokens=10000,
                             response_identity=False)
        remember(role, result)
        return result

    def attempt(role, prompt, state, *, reviewed, inventory=False, final=False):
        try:
            remaining = (state.get('normalized', {}).get('semantic_issues', [])
                         + state.get('review_changes', []))
            draft = read(role, prompt, state.get('draft'),
                         remaining)
            if not _readable_document(draft):
                raise ValueError('semantic_document_unreadable')
            previous = state.get('draft')
            if _has_content(previous) and not _has_content(draft):
                raise ValueError('semantic_review_removed_all_content')
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
            changes = (_review_changes(previous, draft) if reviewed and independently_reviewed and not final
                       and not state.get('reviewed') else [])
            return {**state, 'draft': draft, 'normalized': normalized, 'reviewed': independently_reviewed,
                    'content_read': not _has_vertices(draft) if inventory else True,
                    'review_changes': changes, 'errors': []}
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
        draft = state.get('draft')
        if not _has_vertices(draft):
            return state
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

        def read_batch(item):
            index, task = item
            roles = ['semantic_edges_glm', 'semantic_edges'] if specialist else ['semantic_edges']
            for role in roles:
                try:
                    budget.check(minimum=reserve + 3)
                    result = runner.call(role, SOURCE_READ_PROMPT,
                        {'image_views': views['view_descriptions'], 'task': task}, views['images'],
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
                'normalized': normalize_semantic_document(merged['document'], reviewed=False)}

    def review(state):
        # GLM reads small source groups; a fresh Qwen context checks the whole
        # document. Changed readings get one final original-image check.
        return attempt('semantic_review', REVIEW_PROMPT, state, reviewed=True)

    def needs_repair(state):
        issues = state.get('normalized', {}).get('semantic_issues', [])
        if (not state.get('reviewed') or issues or state.get('errors') or state.get('review_changes')):
            if budget.remaining > 0 and budget.deadline-time.monotonic() >= 18:
                return 'repair'
        return 'done'

    def repair(state):
        role = 'semantic_specialist' if specialist else 'semantic_repair'
        return attempt(role, REPAIR_PROMPT, state, reviewed=True, final=True)

    flow = StateGraph(_State)
    flow.add_node('extract', extract)
    flow.add_node('sources', sources)
    flow.add_node('review', review)
    flow.add_node('repair', repair)
    flow.add_edge(START, 'extract')
    flow.add_edge('extract', 'sources')
    flow.add_edge('sources', 'review')
    flow.add_conditional_edges('review', needs_repair, {'repair': 'repair', 'done': END})
    flow.add_edge('repair', END)
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
    errors = state.get('errors', [])
    if errors:
        result.setdefault('semantic_issues', []).extend(errors)
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
        semantic_workflow={
            'version': AGENT_PIPELINE_VERSION, 'acceptance_scope': 'rendered_semantics',
            'task_id': budget.task_id, 'source_sha256': source_sha,
            'reviewed': state.get('reviewed') is True,
            'roles': copy.deepcopy(budget.events), 'tool_audit': views['tool_audit'],
            'role_counts': copy.deepcopy(budget.role_counts),
            'geometry_required': False,
            'edge_strategy': 'node_inventory_then_source_conditioned_edges',
            'source_audit': copy.deepcopy(state.get('source_audit', {})),
            'readings': copy.deepcopy(responses),
        })
    if audit:
        result['stage_audit'] = {'responses': responses, 'observations': runner.observations}
    return result


__all__ = ['recognize_semantic', 'SemanticRunner']
