"""One visual reading, necessary local review, and an editable semantic result.

The performance target is measured, never implemented by pretending that a
timed-out model or unfinished validation succeeded. Local model work uses the
shared scheduler; the four independent visual requests do not hold its lease.
"""
from __future__ import annotations

import copy
import hashlib
import re
import time
import unicodedata
from difflib import SequenceMatcher
from typing import TypedDict

from jsonschema import Draft202012Validator

from dmate_tool_registry import ToolContext, ToolRegistry, ToolSpec
from graph_agent_runtime import AgentBudget, AgentCancelled, RoleRunner
from graph_pipeline_version import AGENT_PIPELINE_VERSION
from graph_semantic_schema import normalize_semantic_document
from vision_provider import GLM_5V_TURBO_MODEL, VisionError, VisionProvider


PERFORMANCE_TARGET_SECONDS = 120

MAIN_PROMPT = r'''读取这张数学题原图，输出可供用户核对和编辑的完整题干与图结构，不解题。
只依据原图实际内容；工具候选用于定位，可能漏读/误读，不能据候选数量、图名、度数或常见模板补删边。
先区分每幅独立数学子图，再读全真实顶点与标签（包括孤立点），沿每条实际连线找到两端点。普通交叉、箭头尖、文字笔画不是额外顶点。相连的两个局部仍是一幅图；同图的不连通分量不能仅因分开就拆成多图。所有辅助窗口都来自同一原图，不重复计图。
顶点清单按实际圆点/圆圈或明确端点建立，旁边的边名不能变成额外节点；没有印刷节点名的真实点保留label=null。e_i也可以是原图真正的节点名，必须按它与点/线的实际位置判别，不能只按词形删点。遇到没有节点标记的交叉，沿原来的连续笔画继续走，不能在交叉处换到另一条线，也不能把上下同列而无连线的点连接起来。
按箭头尖确定方向。有向边仅列一次；无向边仅列一次；每条重边、反向弧、自环分别保留。保留印刷权重，包括零、负数和符号。节点旁的字母属于节点，不能抄为边名；印刷边名(e₁等)与权重分开。
输出前逐幅对照原图核对每条线的实际两端和箭头，不能按节点编号递增、左右顺序或对称布局决定方向。符号权重如π、√2、1/3原样保留为字符串，不计算近似值。同一处印刷标注仅放在其实际对应的weight或edge_label字段，不重复复制；只有原图确有两处独立标注时才同时填写两个字段。
body_text逐字保留全部可见题干、小问、公式、数学符号和必要图例；图内标签与(a)/(b)图注放在图结构，不变成题干。不生成“如图所示”等原图没有的文字，不推测被裁掉的内容。没有题干用空字符串。
保留题目有用的颜色和虚线/点线区别。普通黑白印刷、白色粉笔、背景装饰、精确坐标与线条粗细不影响完成状态。阴影和背面透印不能当新增线条。只把具体仍看不清的内容列为uncertainties，供用户修改。
输出紧凑JSON，不输出解释或Markdown：
{"body_text":"原文", "graphs":[{"id":"G1","name":"原图图注或G1","directed":false,"bbox":[0,0,1000,1000],"vertices":[{"id":"a","label":"a"},{"id":"b","label":null}],"edges":[{"from":"a","to":"b","direction":"undirected","weight":null,"edge_label":null,"style":"solid"}]}],"uncertainties":[]}
direction为forward/undirected/unknown，forward表示from→to；无印刷标签的点label=null。内部ID可自行分配但图内引用一致；边ID和bbox可省略，bbox仅为相对完整原图0..1000的宽松位置提示。style为solid/dashed/dotted/unknown。无特殊颜色可省略color。没有图时graphs=[]。
uncertainties格式：{"scope":"body|graph|document","graph_id":"图问题填写","field":"vertices|edges|direction|weight|body_text等","message":"具体位置及未读清内容"}。必要图例可另存text_context.legends=[{"text":"原文","graph_ids":["G1"]}]，但不得从body_text中遗漏。'''

LOCAL_REVIEW_PROMPT = r'''你是数学图像的局部复核者。完整原图和所有局部视图来自同一张图。只检查targets明确指出的正文或数学子图，不解题。
draft是尚待用户确认的读取结果，工具候选和题意规则都是辅助，可能错误。沿原图确认目标图的顶点、连接、箭头、孤立点、自环、重边、权重，完整保留其必要标签/线型/颜色；不从常见图模板或度数反推图片。
只返回targets内已复核的完整子图，保留原graph.id。无需返回未请求的图。题干仅在targets.body=true时返回完整逐字body_text；不能新增原图不存在的问题或补全裁切文字。
返回格式：{"graphs":[{"id":"G1","name":"原图图注","vertices":[...],"edges":[...]}],"uncertainties":[]}。节点和边结构与主读取相同。已确认修正的问题不留在uncertainties；仍看不清时明确列出scope/graph_id/field/message，保留可用内容，不以空图抹掉整幅结构。仅内部ID或坐标差异不是识别疑点。'''


_IDENTIFIER = {'type': ['string', 'integer'], 'minLength': 1, 'maxLength': 160}
_DRAFT_SCHEMA = {
    'type': 'object', 'required': ['body_text', 'graphs'],
    'properties': {
        'body_text': {'type': 'string', 'maxLength': 262144},
        'graphs': {'type': 'array', 'maxItems': 64, 'items': {
            'type': 'object', 'required': ['vertices', 'edges'], 'properties': {
                'id': _IDENTIFIER,
                'vertices': {'type': 'array', 'maxItems': 100, 'items': {
                    'type': 'object', 'properties': {'id': _IDENTIFIER,
                        'label': {'type': ['string', 'integer', 'number', 'null']}}}},
                'edges': {'type': 'array', 'maxItems': 300, 'items': {
                    'type': 'object', 'required': ['from', 'to'], 'properties': {
                        'id': _IDENTIFIER, 'from': _IDENTIFIER, 'to': _IDENTIFIER,
                        'direction': {'enum': ['forward', 'undirected', 'unknown']},
                        'weight': {'type': ['string', 'integer', 'number', 'null']},
                        'edge_label': {'type': ['string', 'integer', 'number', 'null']}}}},
            }}},
        'uncertainties': {'type': 'array', 'maxItems': 128},
    },
}
_DRAFT_VALIDATOR = Draft202012Validator(_DRAFT_SCHEMA)


class _State(TypedDict, total=False):
    draft: dict
    normalized: dict
    issues: list
    validation: dict
    reference: dict
    local_review: dict


class FastRunner(RoleRunner):
    def _provider_for(self, role):
        if role == 'fast_main':
            supplied = self.provider.get(role) if isinstance(self.provider, dict) else self.provider
            if supplied is None:
                return VisionProvider('qwen', thinking=True, thinking_budget=1024,
                                      retries=0, capture=self.capture)
            # Explicit injected providers remain intact for controlled tests
            # and comparisons; the parent identity checks still apply.
            return super()._provider_for(role)
        if role != 'fast_local_review':
            return super()._provider_for(role)
        remote = self.provider.get(role) if isinstance(self.provider, dict) else None
        remote = remote or VisionProvider('glm', model=GLM_5V_TURBO_MODEL,
                                         thinking=False, retries=0, capture=self.capture)
        if (getattr(remote, 'name', None) != 'glm'
                or getattr(remote, 'model', None) != GLM_5V_TURBO_MODEL
                or getattr(remote, 'retries', 0) != 0):
            raise ValueError('fast_local_review_requires_glm5v')
        return remote

    def review_available(self):
        remote = self._provider_for('fast_local_review')
        return not hasattr(remote, 'available') or remote.available()


def configured_fast_budget(*, source_sha256=None, task_id=None, cancelled=None):
    # An operational fault ceiling is deliberately separate from the 120 s
    # performance target. A valid late result remains late; it is never cut
    # short or labelled fast to meet the acceptance metric.
    budget = AgentBudget(seconds=200, calls=2, call_seconds=75,
                         source_sha256=source_sha256, task_id=task_id, cancelled=cancelled)
    budget.max_network_recoveries = 0
    budget.max_json_format_recoveries = 0
    return budget


def _issue(kind, message, *, scope='document', graph_id=None, **details):
    return {'scope': scope, 'kind': kind, 'message': message,
            **({'graph_id': str(graph_id)} if graph_id is not None else {}), **details}


def _schema_issues(document):
    result = []
    for error in list(_DRAFT_VALIDATOR.iter_errors(document))[:48]:
        path = list(error.absolute_path)
        scope, gid = 'document', None
        if path and path[0] == 'body_text':
            scope = 'body'
        elif len(path) > 1 and path[0] == 'graphs' and isinstance(path[1], int):
            rows = document.get('graphs', []) if isinstance(document, dict) else []
            if path[1] < len(rows) and isinstance(rows[path[1]], dict):
                gid = rows[path[1]].get('id', f'G{path[1]+1}')
                scope = 'graph'
        result.append(_issue('json_schema_invalid', '识别结果中有字段尚不能组成有效结构，请核对修改。',
                             scope=scope, graph_id=gid, field=str(path[-1]) if path else None))
    return result


def _validate_tool(arguments, *, context):
    from graph_semantic_tools import inspect_semantic_graphs
    context.check_deadline()
    draft = context.data['draft']
    normalized = normalize_semantic_document(draft, reviewed=True)
    # Normalization intentionally keeps human messages small. Retain an
    # explicit model field hint for tool selection; never infer it from prose.
    declared = draft.get('uncertainties', []) if isinstance(draft, dict) else []
    for issue in normalized['semantic_issues']:
        if issue.get('kind') != 'model_uncertainty' or not isinstance(declared, list):
            continue
        matches = [row for row in declared if isinstance(row, dict)
            and row.get('scope') == issue.get('scope')
            and str(row.get('graph_id')) == str(issue.get('graph_id'))
            and row.get('message') == issue.get('message')]
        if len(matches) == 1 and matches[0].get('field') in (
                'body_text', 'vertices', 'edges', 'direction', 'weight', 'edge_label', 'style', 'color', 'name'):
            issue['field'] = matches[0]['field']
    schema_issues = _schema_issues(draft)
    inspected = inspect_semantic_graphs(normalized, budget=context.data['budget'])
    issues = normalized['semantic_issues'] + schema_issues + inspected['issues']
    context.data['result'].update(normalized=normalized, issues=issues,
        schema_valid=not schema_issues, program=inspected)
    return {'phase': arguments['phase'], 'schema_valid': not schema_issues,
            'issues': issues, 'summaries': inspected['summaries'],
            'tool_audit': inspected['tool_audit'], 'image_accuracy_certified': False}


def _validation_registry():
    return ToolRegistry().register(ToolSpec(
        name='graph.fast_validate', version=AGENT_PIPELINE_VERSION,
        description='Validate semantic fields with JSON Schema and inspect all graph instances with NetworkX.',
        input_schema={'type': 'object', 'required': ['phase'], 'additionalProperties': False,
                      'properties': {'phase': {'enum': ['initial', 'final']}}},
        output_schema={'type': 'object', 'required': ['schema_valid', 'issues', 'summaries'],
                       'properties': {'schema_valid': {'type': 'boolean'},
                                      'issues': {'type': 'array'}, 'summaries': {'type': 'array'}}},
        allowed_roles=frozenset({'semantic_review'}), timeout_seconds=10,
        source_required=True), _validate_tool)


def _validate(draft, budget, phase):
    result = {}
    context = ToolContext(source_sha256=budget.source_sha256,
        deadline_monotonic=min(time.monotonic()+10, budget.deadline),
        data={'draft': draft, 'budget': budget, 'result': result})
    envelope = _validation_registry().call('graph.fast_validate', {'phase': phase},
                                           role='semantic_review', context=context)
    if not envelope['ok']:
        budget.check()
        normalized = normalize_semantic_document(draft, reviewed=True)
        return {'normalized': normalized, 'issues': normalized['semantic_issues'] + [
            _issue('structure_validation_unavailable', '本次结构校验未完成，请核对后重新校验。')],
            'validation': {'phase': phase, 'status': 'failed', 'tool_audit': list(context.audit)}}
    return {'normalized': result['normalized'], 'issues': result['issues'],
            'validation': {**envelope['result'], 'status': 'completed',
                'tool_audit': envelope['result']['tool_audit']+list(context.audit)}}


def _local_reference(document, budget):
    # Only existing deterministic rules and bounded formula syntax are called.
    from graph_semantic_question_reference import _snapshot, register_question_reference_tools
    try:
        snapshot = _snapshot(document, budget.source_sha256)
        context = ToolContext(source_sha256=budget.source_sha256,
            deadline_monotonic=min(time.monotonic()+1, budget.deadline), data={'snapshot': snapshot})
        envelope = register_question_reference_tools(ToolRegistry()).call(
            'text.question_reference_hints', {}, role='semantic_extract', context=context)
        return {'status': 'local_only' if envelope['ok'] else 'unavailable',
                'advisory_only': True, 'remote_calls': 0,
                'local_hints': envelope.get('result', {}), 'tool_audit': list(context.audit)}
    except (ValueError, TypeError, TimeoutError):
        return {'status': 'unavailable', 'advisory_only': True, 'remote_calls': 0}


def _targets(draft, issues):
    ids = [str(g.get('id', f'G{i+1}')) for i, g in enumerate(draft.get('graphs', []))
           if isinstance(g, dict)]
    whole = any(row.get('scope') == 'document' for row in issues)
    return {'document': whole, 'body': whole or any(row.get('scope') == 'body' for row in issues),
            'graph_ids': ids if whole else list(dict.fromkeys(str(row['graph_id']) for row in issues
                if row.get('scope') == 'graph' and str(row.get('graph_id')) in ids))}


def _merge_local_review(previous, response, targets):
    """Replace only explicitly targeted panels/text; retain missing readings."""
    if not isinstance(response, dict) or not isinstance(response.get('graphs'), list):
        raise ValueError('local_review_invalid_document')
    result, returned, issues = copy.deepcopy(previous), {}, []
    allowed = set(targets['graph_ids'])
    whole = targets.get('document') is True
    for graph in response['graphs']:
        if not isinstance(graph, dict) or (not whole and str(graph.get('id')) not in allowed):
            continue
        gid = str(graph['id'])
        if gid in returned:
            raise ValueError('local_review_duplicate_graph')
        if not isinstance(graph.get('vertices'), list) or not isinstance(graph.get('edges'), list):
            continue
        returned[gid] = copy.deepcopy(graph)
    old_graphs = result.get('graphs', [])
    if whole and all(isinstance(graph, dict) and isinstance(graph.get('vertices'), list)
                     and isinstance(graph.get('edges'), list) for graph in response['graphs']):
        # A page-inventory dispute explicitly authorizes re-segmentation. This
        # is the sole scope that may add/remove independent mathematical panels.
        if returned or isinstance(response.get('body_text'), str) and response['body_text'].strip():
            result['graphs'] = list(returned.values())
            old_graphs = []
            allowed = set(returned)
    for index, graph in enumerate(old_graphs):
        gid = str(graph.get('id', f'G{index+1}'))
        if gid in returned:
            replacement = returned[gid]
            if graph.get('vertices') and not replacement['vertices']:
                issues.append(_issue('local_review_removed_content', '局部复核未保留可用顶点，请核对。',
                                     scope='graph', graph_id=gid))
                continue
            old_graphs[index] = replacement
    missing = allowed - set(returned)
    issues.extend(_issue('local_review_missing_graph', '该子图的局部复核未完成，已保留原读法。',
                         scope='graph', graph_id=gid) for gid in sorted(missing))
    body_read = targets['body'] and isinstance(response.get('body_text'), str)
    if body_read:
        result['body_text'] = response['body_text']
    elif targets['body']:
        issues.append(_issue('local_review_missing_body', '题干局部复核未完成，已保留可读正文。', scope='body'))
    old_uncertainties = previous.get('uncertainties', [])
    result['uncertainties'] = [copy.deepcopy(row) for row in old_uncertainties if not (
        isinstance(row, dict) and ((row.get('scope') == 'body' and body_read)
            or (row.get('scope') == 'graph' and str(row.get('graph_id')) in returned)
            or (row.get('scope') == 'document' and whole and body_read and not missing)))] \
        if isinstance(old_uncertainties, list) else []
    new_uncertainties = response.get('uncertainties')
    if not isinstance(new_uncertainties, list):
        issues.append(_issue('local_review_uncertainty_status_missing', '局部复核未明确剩余疑点。'))
    else:
        result['uncertainties'].extend(copy.deepcopy(new_uncertainties))
    return result, issues


def _complex_layout_needed(quick, markers):
    """Choose the heavy layout model only for observable CV ambiguity."""
    panels = quick.get('panels', [])
    boxes = [row.get('bbox') for row in panels if isinstance(row, dict)
             and isinstance(row.get('bbox'), list) and len(row['bbox']) == 4]
    if len(boxes) > 10:
        return True
    for index, a in enumerate(boxes):
        for b in boxes[index+1:]:
            shared = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
            smaller = min((a[2]-a[0])*(a[3]-a[1]), (b[2]-b[0])*(b[3]-b[1]))
            if smaller > 0 and shared/smaller > .65:
                return True
    return (not boxes and len(markers.get('marker_candidates', [])) >= 8
            and len(quick.get('body_regions', [])) >= 2)


def _path_policy(draft, issues):
    graph_issues = [row for row in issues if row.get('scope') == 'graph'
                    and row.get('field') in (None, 'vertices', 'edges', 'direction')]
    ids = {str(row.get('graph_id')) for row in graph_issues}
    graphs = [graph for graph in draft.get('graphs', []) if isinstance(graph, dict)
              and str(graph.get('id')) in ids]
    complex_paths = False
    for graph in graphs:
        pairs = [tuple(sorted((str(edge.get('from')), str(edge.get('to')))))
                 for edge in graph.get('edges', []) if isinstance(edge, dict)]
        complex_paths |= len(pairs) > len(set(pairs)) or len(pairs) > 2*len(graph.get('vertices', []))
    return {'text': False, 'layout': False, 'paths': bool(graphs), 'sknw': bool(graphs) and complex_paths}


def _public_local_result(value):
    """Keep diagnostics JSON-only; never expose PIL arrays or image payloads."""
    fields = {
        'text': ('text_hints', 'regions', 'text', 'text_evidence', 'diagnostics', 'resource_metrics'),
        'layout': ('panels', 'body_regions', 'layout', 'diagnostics', 'resource_metrics'),
        'geometry': ('graphs', 'issues', 'diagnostics', 'proposal_only', 'resource_metrics'),
    }
    return {name: {field: copy.deepcopy(value[name][field]) for field in selected
                   if field in value.get(name, {})}
            for name, selected in fields.items() if isinstance(value.get(name), dict)}


def _text_candidate_issues(draft, local_text, quick):
    """Flag concrete omitted prose, never turn OCR labels into a question.

    Text candidates cannot alter the transcription. The user or the scoped
    visual reader resolves a discrepancy against the original image.
    """
    from graph_semantic_hints import project_ocr_hints
    projected = project_ocr_hints(local_text, role='semantic_body', body_regions=quick.get('body_regions', []))
    originals = {row.get('id'): row for row in local_text.get('text_hints', [])
                 if isinstance(row, dict) and isinstance(row.get('id'), str)}
    def compact(text):
        value = unicodedata.normalize('NFKC', text)
        return ''.join(c for c in value if c.isalnum() or c in '=<>≤≥≠∈∉')
    body = compact(draft.get('body_text', ''))
    result = []
    for candidate in projected['candidates']:
        text = candidate['text']
        confidence = originals.get(candidate.get('id'), {}).get('confidence')
        if (not isinstance(confidence, (int, float)) or confidence < .9
                or len(text) < 8 or not candidate.get('bbox')
                or not re.search(r'求|证明|判断|计算|是否|图例|\b(?:find|prove|determine|legend)\b', text, re.I)):
            continue
        literal = compact(text)
        if not literal or literal in body:
            continue
        shared = SequenceMatcher(None, literal, body, autojunk=False).find_longest_match().size if body else 0
        if shared/len(literal) >= .7:
            continue
        result.append(_issue('body_candidate_not_transcribed', '本地文字候选中有题干或图例尚未与正文对应，请对照原图核对。',
            scope='body', field='body_text', candidate_text=text[:500], bbox=copy.deepcopy(candidate['bbox'])))
        if len(result) >= 4:
            break
    return result


def recognize_fast(raw, *, layout=None, provider=None, budget=None, audit=False,
                   text_result=None, cancelled=None, task_id=None, local_submit=None):
    from langgraph.graph import START, END, StateGraph
    from langsmith import tracing_context
    from graph_semantic_layout import prepare_semantic_layout
    from graph_semantic_geometry import prepare_semantic_geometry
    from graph_semantic_hints import project_ocr_hints, project_connection_hints

    started = time.monotonic()
    source = hashlib.sha256(raw).hexdigest()
    budget = budget or configured_fast_budget(source_sha256=source, task_id=task_id, cancelled=cancelled)
    if budget.source_sha256 not in (None, source):
        raise ValueError('source_identity_mismatch')
    budget.source_sha256 = source
    if cancelled is not None:
        budget.cancelled = cancelled
    budget.check()
    quick = prepare_semantic_layout(raw, budget=budget, layout=layout, run_layout=False)
    markers = prepare_semantic_geometry(raw, budget=budget, layout=quick)
    views = {'images': quick['images'][:1], 'view_descriptions': quick['view_descriptions'][:1]}
    if local_submit is None:
        from graph_local_scheduler import submit_local_bundle
        local_submit = submit_local_bundle
    local_policy = {'text': True, 'layout': _complex_layout_needed(quick, markers),
                    'paths': False, 'sknw': False}
    handle = local_submit(raw, budget=budget, quick_layout=quick, initial_geometry=markers,
                          policy=local_policy)
    handles = [handle]
    runner = FastRunner(budget, provider=provider, capture=audit)
    readings, timings = [], []
    stages = []
    local_result = {}
    extra_issues = []
    budget.local_tool_execution = {'layout': _public_local_result({'layout': quick})['layout'],
        'markers': {'marker_candidates': copy.deepcopy(markers.get('marker_candidates', []))}}

    def run_stage(name, function):
        def wrapped(state):
            tick = time.monotonic()
            stages.append(name)
            try:
                return function(state)
            finally:
                timings.append({'stage': name, 'seconds': round(time.monotonic()-tick, 6),
                                'finished_seconds': round(time.monotonic()-started, 6)})
        return wrapped

    def extract(state):
        available = handle.snapshot()
        text = available.get('text', {}) if isinstance(available, dict) else {}
        hints = project_ocr_hints(text, role='semantic_extract',
                                  body_regions=quick.get('body_regions', []),
                                  marker_candidates=markers.get('marker_candidates', []))
        response = runner.call('fast_main', MAIN_PROMPT,
            {'image_views': views['view_descriptions'],
             'local_layout_candidates': quick.get('panels', [])[:32],
             'local_marker_candidates': markers.get('marker_candidates', [])[:120],
             'local_ocr_candidates': hints['candidates'], 'local_ocr_policy': hints['policy']},
            views['images'], output_tokens=12000, response_identity=False,
            reserve_seconds=12)
        if not isinstance(response.get('graphs'), list) or not isinstance(response.get('body_text'), str):
            raise VisionError('main_document_unreadable')
        # Canonical graph IDs are useful to local scopes even when the model
        # omitted bookkeeping. Every visible value is left to normalization.
        for index, graph in enumerate(response['graphs'], 1):
            if isinstance(graph, dict) and graph.get('id') is None:
                graph['id'] = f'G{index}'
        readings.append({'role': 'fast_main', 'document': copy.deepcopy(response)})
        return {**state, 'draft': response}

    def local_tools(state):
        nonlocal local_result
        local_result = handle.result()
        budget.local_tool_execution.update(_public_local_result(local_result))
        return state

    def initial_check(state):
        checked = _validate(state['draft'], budget, 'initial')
        checked['issues'] += _text_candidate_issues(state['draft'], local_result.get('text', {}), quick)
        reference = _local_reference(checked['normalized'], budget)
        return {**state, **checked, 'reference': reference}

    def review(state):
        nonlocal local_result
        issues = state.get('issues', [])
        if not issues:
            return {**state, 'local_review': {'status': 'not_needed', 'model_calls': 0}}
        targets = _targets(state['draft'], issues)
        if not runner.review_available():
            return {**state, 'local_review': {'status': 'unavailable', 'reason': 'glm_not_configured',
                                             'model_calls': 0, 'targets': targets}}
        path_policy = _path_policy(state['draft'], issues)
        if path_policy['paths']:
            path_handle = local_submit(raw, budget=budget, quick_layout=local_result.get('layout') or quick,
                                       initial_geometry=markers, draft=state['draft'], policy=path_policy)
            handles.append(path_handle)
            path_result = path_handle.result()
            local_result['geometry'] = path_result.get('geometry', {})
            local_result.setdefault('resource_metrics', []).extend(path_result.get('resource_metrics', []))
            local_result.setdefault('tool_audit', []).extend(path_result.get('tool_audit', []))
        from graph_semantic_arrow_views import prepare_panel_views
        from graph_semantic_panel_context import panel_context
        review_views = copy.deepcopy(views)
        for graph in state['draft']['graphs']:
            if not isinstance(graph, dict) or str(graph.get('id')) not in targets['graph_ids']:
                continue
            contextual = panel_context(graph, local_result.get('layout') or quick)['graph']
            panel = prepare_panel_views(raw, graph=contextual, overview_views=views, budget=budget)
            if len(panel['images']) > 1 and len(review_views['images']) < 5:
                review_views['images'].append(panel['images'][1])
                review_views['view_descriptions'].append('待核对子图'+str(graph['id'])+'的原像素局部；'+panel['view_descriptions'][1])
        text = local_result.get('text', {})
        hints = project_ocr_hints(text, role='semantic_review', body_regions=quick.get('body_regions', []))
        try:
            response = runner.call('fast_local_review', LOCAL_REVIEW_PROMPT,
                {'targets': targets, 'issues': issues[:32],
                 'draft': {'body_text': state['draft']['body_text'], 'graphs': [
                     graph for graph in state['draft']['graphs'] if str(graph.get('id')) in targets['graph_ids']]},
                 'image_views': review_views['view_descriptions'],
                 'local_ocr_candidates': hints['candidates'],
                 'local_connection_candidates': project_connection_hints(local_result.get('geometry', {}).get('graphs', [])),
                 'question_reference': state.get('reference', {})},
                review_views['images'], output_tokens=8000, response_identity=False, reserve_seconds=8)
            readings.append({'role': 'fast_local_review', 'document': copy.deepcopy(response)})
            patched, pending = _merge_local_review(state['draft'], response, targets)
            extra_issues.extend(pending)
            return {**state, 'draft': patched, 'local_review': {'status': 'completed', 'model_calls': 1,
                                                             'targets': targets}}
        except AgentCancelled:
            raise
        except (VisionError, ValueError, TimeoutError) as exc:
            kind = exc.kind if isinstance(exc, VisionError) else type(exc).__name__
            message = '局部复核未完成，已保留可编辑结果和原有疑点。'
            if targets.get('document'):
                extra_issues.append(_issue('local_review_failed', message, reason=kind))
            else:
                extra_issues.extend(_issue('local_review_failed', message, scope='graph',
                    graph_id=gid, reason=kind) for gid in targets['graph_ids'])
                if targets['body']:
                    extra_issues.append(_issue('local_review_failed', message, scope='body', reason=kind))
            return {**state, 'local_review': {'status': 'failed', 'reason': kind, 'model_calls': 1,
                                             'targets': targets}}

    def final_check(state):
        # Always execute the final schema/NetworkX check, even when the main
        # reading is clean or the optional model is unavailable.
        checked = _validate(state['draft'], budget, 'final')
        checked['issues'] += _text_candidate_issues(state['draft'], local_result.get('text', {}), quick)
        return {**state, **checked}

    flow = StateGraph(_State)
    for name, handler in (('main_reading', extract), ('local_candidates', local_tools),
                          ('structure_check', initial_check), ('local_review', review),
                          ('final_validation', final_check)):
        flow.add_node(name, run_stage(name, handler))
    flow.add_edge(START, 'main_reading')
    flow.add_edge('main_reading', 'local_candidates')
    flow.add_edge('local_candidates', 'structure_check')
    flow.add_edge('structure_check', 'local_review')
    flow.add_edge('local_review', 'final_validation')
    flow.add_edge('final_validation', END)
    try:
        with tracing_context(enabled=False):
            state = flow.compile().invoke({})
    finally:
        # A selected worker is never abandoned and described as completed.
        for pending_handle in handles:
            closed = pending_handle.close()
            budget.local_tool_execution.update(_public_local_result(closed))
        budget.local_tool_execution['scheduler'] = [pending_handle.audit() for pending_handle in handles]
    result = copy.deepcopy(state['normalized'])
    issues = state['issues'] + extra_issues
    result['semantic_issues'] = issues
    for graph in result['graphs']:
        local = [row for row in issues if row.get('scope') == 'document' or str(row.get('graph_id')) == graph['id']]
        if local:
            graph['complete'] = False
            graph['semantic_issues'] = local
            for edge in graph['edges']:
                edge['status'] = 'pending'
    if any(row.get('scope') in ('body', 'document') for row in issues):
        result['body_complete'] = False
    result['complete'] = not issues
    result['body_audit'] = {'second_pass_reviewed': state.get('local_review', {}).get('status') == 'completed',
                            'reading_mode': 'main_visual_transcription', 'user_confirmation_required': True}
    if isinstance(state['draft'].get('text_context'), dict):
        result['text_context'] = copy.deepcopy(state['draft']['text_context'])
    text = local_result.get('text', {})
    local_audit = [pending_handle.audit() for pending_handle in handles]
    resource_metrics = quick.get('resource_metrics', []) + local_result.get('resource_metrics', [])
    tools_public = _public_local_result(local_result)
    tools_public['layout'] = _public_local_result({'layout': local_result.get('layout') or quick})['layout']
    tools_public['markers'] = {'marker_candidates': copy.deepcopy(markers.get('marker_candidates', [])),
                               'diagnostics': copy.deepcopy(markers.get('diagnostics', []))}
    result.update(diagnostics=stages, remote_metrics=copy.deepcopy(budget.metrics),
        image_quality=copy.deepcopy(quick.get('diagnostics', {})),
        local_layout_result=copy.deepcopy((local_result.get('layout') or quick).get('layout', {})),
        local_text_result={key: copy.deepcopy(text[key]) for key in ('text', 'text_evidence') if key in text},
        local_resource_metrics=resource_metrics,
        confirmation_required=True, recognition_profile='fast-editable',
        service_warnings=([{'kind': 'local_tools_degraded',
            'message': '部分本地图像辅助工具未完成，已保留视觉识别结果，请核对后确认。'}]
            if any(any(stage.get('status') not in ('ok', 'not_needed') for stage in item.get('stages', []))
                   for item in local_audit) else []),
        semantic_workflow={'version': AGENT_PIPELINE_VERSION, 'mode': 'fast_editable',
            'task_id': budget.task_id, 'source_sha256': source,
            'image_accuracy_certified': False, 'user_confirmation_required': True,
            'roles': copy.deepcopy(budget.events), 'role_counts': copy.deepcopy(budget.role_counts),
            'readings': readings, 'timings': timings, 'local_tools': tools_public,
            'local_scheduler': local_audit, 'local_tool_policy': local_policy,
            'local_review': state.get('local_review', {}),
            'question_reference': state.get('reference', {}),
            'final_validation': state['validation'],
            'tool_audit': quick.get('tool_audit', [])+markers.get('tool_audit', [])
                +local_result.get('tool_audit', [])+state['validation'].get('tool_audit', []),
            'performance': {'target_seconds': PERFORMANCE_TARGET_SECONDS,
                'recognition_seconds': round(time.monotonic()-started, 6),
                'scope': 'recognition_before_response_rendering',
                'within_target': time.monotonic()-started <= PERFORMANCE_TARGET_SECONDS}})
    budget.local_tool_execution = tools_public
    if audit:
        result['stage_audit'] = {'responses': readings, 'observations': runner.observations}
    return result


__all__ = ['recognize_fast', 'configured_fast_budget', 'PERFORMANCE_TARGET_SECONDS']
