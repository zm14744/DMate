"""Short, image-grounded readers for the content DMate actually renders.

Geometry and CPU tracing are optional aids, never acceptance requirements.
Every visual role receives the original image in a fresh model context. The
canonical result is shared by the review UI and solver; an incomplete review
retains useful content instead of replacing the document with an empty graph.
"""
from __future__ import annotations

import copy
import hashlib
import time
from typing import TypedDict

from graph_agent_runtime import AgentBudget, AgentCancelled, RoleRunner
from graph_pipeline_version import AGENT_PIPELINE_VERSION
from graph_semantic_schema import MAX_GRAPHS, normalize_semantic_document
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
直接返回你修正后的完整JSON文档。发现并修好的错误不放uncertainties；只留下仍无法从原图确定的内容。不需要复述修改日志，不需要逐边附证据。'''

REPAIR_PROMPT = REVIEW_PROMPT + r'''
这是同一次上传的最后一轮定向复核。重点检查remaining_issues指出的内容；原图优先，必要时修正节点清单，然后从涉及的源节点重读连边。
保留已经看清的其他题干和子图，返回完整文档。无法确认的局部继续注明，不删除整幅可用图，也不要为了满足某种图论性质加边或删边。'''


class SemanticRunner(RoleRunner):
    """Keep transport accounting while allowing one explicit visual specialist."""

    def _provider_for(self, role):
        if role != 'semantic_specialist':
            return super()._provider_for(role)
        from vision_provider import GLM_5V_TURBO_MODEL
        remote = self.provider.get(role) if isinstance(self.provider, dict) else None
        remote = remote or VisionProvider('glm', model=GLM_5V_TURBO_MODEL,
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


def _issue(kind, message):
    return {'scope': 'document', 'kind': kind, 'message': message}


def _draft_view(value):
    """Send content, without the old coordinates, paths or proof protocols."""
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
        graph['vertices'] = [{k: copy.deepcopy(v[k]) for k in ('id', 'label', 'position') if k in v}
                             for v in rows(row.get('vertices'))[:100] if isinstance(v, dict)]
        graph['edges'] = [{k: copy.deepcopy(e[k]) for k in
                          ('id', 'from', 'to', 'direction', 'weight', 'edge_label', 'color', 'style') if k in e}
                         for e in rows(row.get('edges'))[:300] if isinstance(e, dict)]
        result['graphs'].append(graph)
    if isinstance(value.get('uncertainties'), list):
        result['uncertainties'] = copy.deepcopy(value['uncertainties'][:40])
    return result


def _complex_document(draft, quality):
    graphs = draft.get('graphs', []) if isinstance(draft, dict) else []
    if not isinstance(graphs, list):
        return True
    return (len(graphs) >= 3 or quality.get('possible_blur') is True
            or any(isinstance(g, dict) and isinstance(g.get('edges'), list)
                   and len(g['edges']) >= 15 for g in graphs))


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
    responses, stages = [], []

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
        responses.append({'role': role, 'document': copy.deepcopy(result)})
        stages.append(role)
        return result

    def attempt(role, prompt, state, *, reviewed):
        try:
            draft = read(role, prompt, state.get('draft'),
                         state.get('normalized', {}).get('semantic_issues'))
            if not _readable_document(draft):
                raise ValueError('semantic_document_unreadable')
            previous = state.get('draft')
            if _has_content(previous) and not _has_content(draft):
                raise ValueError('semantic_review_removed_all_content')
            independently_reviewed = (reviewed and _readable_document(previous)
                and (_has_content(previous) or not _has_content(draft)))
            normalized = normalize_semantic_document(draft, reviewed=independently_reviewed)
            return {'draft': draft, 'normalized': normalized, 'reviewed': independently_reviewed,
                    'errors': []}
        except AgentCancelled:
            raise
        except (VisionError, ValueError, TimeoutError) as exc:
            kind = exc.kind if isinstance(exc, VisionError) else type(exc).__name__
            budget.event(role, 'content_unavailable', error_kind=kind)
            return {**state, 'errors': state.get('errors', []) + [
                _issue(kind, '本轮视觉复核未完成，已保留可读取的内容。')]}

    def extract(state):
        return attempt('semantic_extract', SEMANTIC_PROMPT, state, reviewed=False)

    def review(state):
        # Large or blurred pages can use the independently configured GLM
        # specialist. Absence/failure never disables the ordinary Qwen path.
        complex_page = _complex_document(state.get('draft', {}), views['image_quality'])
        specialist = complex_page and runner.specialist_available()
        if complex_page and not specialist:
            budget.event('semantic_specialist', 'skipped', reason='provider_not_available')
        if specialist:
            reviewed = attempt('semantic_specialist', REVIEW_PROMPT, state, reviewed=True)
            if reviewed.get('reviewed'):
                return reviewed
            state = reviewed
        return attempt('semantic_review', REVIEW_PROMPT, state, reviewed=True)

    def needs_repair(state):
        issues = state.get('normalized', {}).get('semantic_issues', [])
        if (not state.get('reviewed') or issues or state.get('errors')):
            if budget.remaining > 0 and budget.deadline-time.monotonic() >= 18:
                return 'repair'
        return 'done'

    def repair(state):
        return attempt('semantic_repair', REPAIR_PROMPT, state, reviewed=True)

    flow = StateGraph(_State)
    flow.add_node('extract', extract)
    flow.add_node('review', review)
    flow.add_node('repair', repair)
    flow.add_edge(START, 'extract')
    flow.add_edge('extract', 'review')
    flow.add_conditional_edges('review', needs_repair, {'repair': 'repair', 'done': END})
    flow.add_edge('repair', END)
    with tracing_context(enabled=False):
        state = flow.compile().invoke({'errors': [], 'reviewed': False})
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
    if not state.get('reviewed'):
        result['body_complete'] = False
        for graph in result['graphs']:
            graph['complete'] = False
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
        })
    if audit:
        result['stage_audit'] = {'responses': responses, 'observations': runner.observations}
    return result


__all__ = ['recognize_semantic', 'SemanticRunner']
