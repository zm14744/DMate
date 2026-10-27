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
from collections import Counter
from difflib import SequenceMatcher
from typing import TypedDict

from jsonschema import Draft202012Validator

from dmate_tool_registry import ToolContext, ToolRegistry, ToolSpec
from graph_agent_runtime import AgentBudget, AgentCancelled, RoleRunner
from graph_pipeline_version import AGENT_PIPELINE_VERSION
from graph_semantic_schema import normalize_semantic_document
from vision_provider import GLM_5V_TURBO_MODEL, VisionError, VisionProvider


PERFORMANCE_TARGET_SECONDS = 120

MAIN_PROMPT = r'''读取数学题原图，返回紧凑JSON题干和图结构，不解题，不输出解释或Markdown。
第一张总览决定独立子图数量；后续局部只是同一原图的放大窗口，不能重复计图。local_caption_grid是从原图彩色图注矩形测出的版面参考。如果存在多行多列图注，逐格核对对应的独立数学图，不得只返回第一幅；同一图的放大窗口不能重复计图。local_colored_graph_candidates是原像素中的彩色顶点与直线候选，必须对照原图核实端点，不得用图名或工具候选凑边。同图不连通分量不能仅因分开就拆图。多图时每图给相对完整原图0..1000的粗bbox，也可附对应layout_panel_ids；不要将每个局部窗口都填成整页bbox。坐标不要求精确。
先清点真实圆点、圆圈或明确顶点，包括孤立点，再沿实际连线读端点。普通交叉、箭头尖和文字不是顶点；边名不能变成节点。无印刷节点名则label=null；e_i也可能是真节点名，须按原图位置判别。local_visual_inventory中的同类圆点须逐个对照原图，可在顶点附marker_id绑定对应候选；若有候选以外的真实点，保留并只为该点附短visual_basis说明具体位置与可见依据。候选可能错漏，不能按候选数、题干、图名、度数或模板补删点边。
对于能够辨认的子图，请独立清点并给出visible_vertex_count和visible_edge_count，再与vertices、edges逐一核对；确实不能确定时填null并注明疑点。不能为了让两种计数相等而补删图结构，也不能直接把数组长度或工具候选数抄成视觉计数。只输出一份vertices和edges，不逐点逐边重复描述。
交叉处沿原笔画走，不换线；经过真实顶点才分成不同边。虚线的多个短划是一条边。每条无向边、有向边、自环、重边和反向弧各列一次。方向只按箭头尖确定，不能按编号或布局猜；看不清用unknown。
weighted必须是布尔值：只有实际边权才true，节点数字、节点编号、边名不算权重。已知存在但未读清的边权用null并列疑点。保留零、负数及π、√2、1/3等原始符号，不计算近似值。同一印刷项仅放对应的weight或edge_label，不能重复填写。保留必要颜色、虚线与点线；阴影、透印不能当新增线条。
body_text逐字保留全部可见题干、小问、公式、数学符号和图例；图内标签、图注放图结构。没有题干就用空字符串，不能根据图生成问题、补写“如图所示”等原图没有的话或猜裁切文字。只把具体仍看不清的内容列为uncertainties。
格式：{"body_text":"原文","graphs":[{"id":"G1","name":"图注或G1","directed":false,"weighted":false,"visible_vertex_count":2,"visible_edge_count":1,"vertices":[{"id":"a","label":"a"},{"id":"b","label":null}],"edges":[{"from":"a","to":"b","direction":"undirected","weight":null,"edge_label":null,"style":"solid"}]}],"uncertainties":[]}
direction为forward/undirected/unknown，forward表示from→to；style为solid/dashed/dotted/unknown，无特殊颜色可省略color。内部ID只需图内一致，边ID可省略。无图则graphs=[]。
uncertainties格式：{"scope":"body|graph|document","graph_id":"图问题填写","field":"vertices|edges|direction|weight|body_text等","message":"具体位置与疑点"}。图例可另存text_context.legends=[{"text":"原文","graph_ids":["G1"]}]，同时保留在body_text。'''

LOCAL_REVIEW_PROMPT = r'''你是数学图像的局部复核者。完整原图和所有局部视图来自同一张图。只检查targets明确指出的正文或数学子图，不解题。
draft是尚待用户确认的读取结果，工具候选和题意规则都是辅助，可能错误。沿原图确认目标图的顶点、连接、箭头、孤立点、自环、重边、权重，完整保留其必要标签/线型/颜色；不从常见图模板或度数反推图片。
local_marker_candidates是整张原图上的圆点候选，含位置、大小和置信度，也可能混入正文或字形。核对目标子图内形状、大小相近的清晰圆点与draft顶点是否逐一对应，尤其检查较大圆点旁的字母是否实际为边名；有数量差异时重新对照原图确认真实点和连接，不将整页候选总数或某一尺寸组的数量强制作为节点数。匿名真实点保留label=null，不能仅凭e_i等词形删除真正的节点名。
若issues指出计数冲突，先重新清点原图实际点与整条连线，不能只补颜色而保留未核实连接。若draft中有visible_vertex_count或visible_edge_count，请对目标子图重新独立清点并在返回的子图中提供这两个字段；不能确定时返回null并明确疑点，不能省略计数字段来消除原有冲突。local_visual_inventory中的圆点候选须逐个对照原图，可用marker_id绑定对应顶点；额外真实点允许保留并附短visual_basis定位依据，不能按候选数凑答案。只返回紧凑vertices/edges，可给独立视觉计数visible_vertex_count/visible_edge_count；仍不能确认则null并列疑点。保留weighted布尔值；方向和权重必须来自原图，不按全图类型补猜。
targets.document=true时必须对照整张原图及local_caption_grid逐格重读所有独立数学子图，不能只回传draft中已存在的一幅图；若确认有漏图，则按原图顺序补齐。否则只返回targets内已复核的完整子图，保留原graph.id。无需返回未请求的图。题干仅在targets.body=true时返回完整逐字body_text；不能新增原图不存在的问题或补全裁切文字。
返回格式：{"graphs":[{"id":"G1","name":"原图图注","vertices":[...],"edges":[...]}],"uncertainties":[]}。节点和边结构与主读取相同。已确认修正的问题不留在uncertainties；仍看不清时明确列出scope/graph_id/field/message，保留可用内容，不以空图抹掉整幅结构。仅内部ID或坐标差异不是识别疑点。'''


_IDENTIFIER = {'type': ['string', 'integer'], 'minLength': 1, 'maxLength': 160}
_DRAFT_SCHEMA = {
    'type': 'object', 'required': ['body_text', 'graphs'],
    'properties': {
        'body_text': {'type': 'string', 'maxLength': 262144},
        'graphs': {'type': 'array', 'maxItems': 64, 'items': {
            'type': 'object', 'required': ['vertices', 'edges'], 'properties': {
                'id': _IDENTIFIER,
                'weighted': {'type': 'boolean'},
                'visible_vertex_count': {'type': ['integer', 'null'], 'minimum': 0, 'maximum': 100},
                'visible_edge_count': {'type': ['integer', 'null'], 'minimum': 0, 'maximum': 300},
                'vertices': {'type': 'array', 'maxItems': 100, 'items': {
                    'type': 'object', 'properties': {'id': _IDENTIFIER,
                        'label': {'type': ['string', 'integer', 'number', 'null']}}}},
                'stroke_inventory': {'type': 'array', 'maxItems': 300, 'items': {
                    'type': 'object', 'required': ['id'], 'properties': {
                        'id': _IDENTIFIER, 'position': {'type': 'string', 'maxLength': 160}}}},
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
                return VisionProvider('qwen', thinking=False, retries=0, capture=self.capture)
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


def _stroke_inventory_issues(document):
    """Check observed-stroke bookkeeping, never synthesize missing edges."""
    issues = []
    for graph in document.get('graphs', []) if isinstance(document, dict) else []:
        if not isinstance(graph, dict) or not isinstance(graph.get('stroke_inventory'), list):
            continue
        inventory, edges = graph['stroke_inventory'], graph.get('edges', [])
        if not isinstance(edges, list):
            continue
        def ids(rows):
            return [str(row['id']) for row in rows if isinstance(row, dict)
                    and type(row.get('id')) in (str, int) and str(row['id']).strip()]
        stroke_ids, edge_ids = ids(inventory), ids(edges)
        duplicate_strokes = [key for key, count in Counter(stroke_ids).items() if count > 1]
        duplicate_edges = [key for key, count in Counter(edge_ids).items() if count > 1]
        missing = sorted(set(stroke_ids) - set(edge_ids))
        unlisted = sorted(set(edge_ids) - set(stroke_ids))
        if (missing or unlisted or duplicate_strokes or duplicate_edges
                or len(stroke_ids) != len(inventory) or len(edge_ids) != len(edges)):
            issues.append(_issue('stroke_inventory_mismatch',
                '已清点的可见笔画与边记录尚不能逐条对应，请对照原图核对漏列、重复或多列；不能按数量补删边。',
                scope='graph', graph_id=graph.get('id'), field='edges',
                inventoried_strokes=len(inventory), recorded_edges=len(edges),
                unmapped_stroke_ids=missing, unlisted_edge_ids=unlisted,
                duplicate_stroke_ids=duplicate_strokes, duplicate_edge_ids=duplicate_edges))
    return issues


def _caption_grid_issues(document, pixel_evidence):
    """Repeated colored caption windows may expose missing independent figures.

    The pixel tool finds caption rectangles, not mathematical graph identities.
    This creates a review requirement, never automatically invents a graph.
    """
    grid = pixel_evidence.get('grid') if isinstance(pixel_evidence, dict) else None
    if not isinstance(grid, dict) or grid.get('status') != 'regular_caption_grid':
        return []
    reported = len(document['graphs']) if (isinstance(document, dict)
        and isinstance(document.get('graphs'), list)) else 0
    observed = grid.get('minimum_captioned_panels')
    if type(observed) is not int or not 4 <= observed <= 16 or reported >= observed:
        return []
    return [_issue('captioned_panel_inventory_omission',
        f'原图检测到 {observed} 个规则排列的独立彩色图注位置，本次只返回 {reported} 幅图。'
        '请逐格核对图注上方的实际数学图，不能遗漏后标记为完整。',
        field='graphs', observed_caption_positions=observed, reported_graphs=reported,
        evidence_source='same_original_rgb_caption_rectangles')]


def _visual_count_issues(document):
    """Reread visually reported counts that disagree with the actual edge/node lists.

    These are consistency checks, NOT independent pixel truth. Missing legacy
    fields are tolerated; an explicit unknown count must stay pending. The
    model may be wrong in both its count and edge list, so an apparent match
    never certifies that the image was recognized correctly.
    """
    issues = []
    rows = document.get('graphs', []) if isinstance(document, dict) else []
    for index, graph in enumerate(rows) if isinstance(rows, list) else ():
        if not isinstance(graph, dict):
            continue
        graph_id = graph.get('id', f'G{index+1}')
        for field, collection, maximum, term in (
                ('visible_vertex_count', 'vertices', 100, '顶点'),
                ('visible_edge_count', 'edges', 300, '边')):
            if field not in graph:
                continue
            count = graph[field]
            listed = len(graph[collection]) if isinstance(graph.get(collection), list) else None
            if count is None:
                issues.append(_issue('visual_count_unresolved',
                    f'原图中的{term}数量未独立确定，请结合原图逐一核对。',
                    scope='graph', graph_id=graph_id, field=collection,
                    recorded_count=listed))
            elif type(count) is not int or not 0 <= count <= maximum:
                issues.append(_issue('visual_count_invalid',
                    f'{term}的独立视觉计数无效，需重新读取原图。',
                    scope='graph', graph_id=graph_id, field=collection,
                    recorded_count=listed))
            elif listed is not None and count != listed:
                issues.append(_issue('visual_count_mismatch',
                    f'原图独立读取的{term}数为 {count}，结构表却列出 {listed} 个，请重新读图核对，不能仅为凑数增删。',
                    scope='graph', graph_id=graph_id, field=collection,
                    visible_count=count, recorded_count=listed))
    return issues


def _validate_tool(arguments, *, context):
    from graph_semantic_tools import inspect_semantic_graphs
    from graph_semantic_pipeline import _required_visual_attribute_issues
    context.check_deadline()
    draft = context.data['draft']
    normalization_input = copy.deepcopy(draft)
    for graph in normalization_input.get('graphs', []) if isinstance(normalization_input, dict) else []:
        if not isinstance(graph, dict) or not isinstance(graph.get('edges'), list):
            continue
        has_arrows = graph.get('directed') is True or any(
            isinstance(edge, dict) and edge.get('direction') == 'forward' for edge in graph['edges'])
        if has_arrows:
            for edge in graph['edges']:
                if isinstance(edge, dict) and 'direction' not in edge:
                    # A graph-level directed flag does not tell us which end
                    # of this particular stroke carries the arrowhead.
                    edge['direction'] = 'unknown'
    normalized = normalize_semantic_document(normalization_input, reviewed=True)
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
    # Normalization omits located legends; retain their scope so a G2-only
    # legend cannot make otherwise cosmetic attributes mandatory in G1.
    visual_document = {**normalized, 'text_context': draft.get('text_context', {})
                       if isinstance(draft, dict) else {}}
    required_attributes = [issue for issue in _required_visual_attribute_issues(visual_document)
                           if issue['field'] in ('color', 'style')]
    # A page may compare weighted and unweighted diagrams. Only a located,
    # positive legend/caption makes a literal weight requirement graph-specific;
    # the explicit graph.weighted flag is handled below as well.
    context_rows = visual_document['text_context'] if isinstance(visual_document['text_context'], dict) else {}
    scoped_weights = {}
    for kind in ('legends', 'captions'):
        rows = context_rows.get(kind, [])
        scoped_weights[kind] = [row for row in rows if isinstance(row, dict)
            and isinstance(row.get('graph_ids'), list) and row['graph_ids']
            and not re.search(r'无权|非加权|未加权|\bunweighted\b|\b(?:not|non)\s*-?\s*weighted\b',
                              str(row.get('text', '')), re.I)] if isinstance(rows, list) else []
    required_attributes += [issue for issue in _required_visual_attribute_issues(
        {'body_text': '', 'graphs': normalized['graphs'], 'text_context': scoped_weights})
        if issue['field'] == 'weight']
    required_weight_graphs = {issue['graph_id'] for issue in required_attributes if issue['field'] == 'weight'}
    declared_weighted = {str(graph.get('id')) for graph in draft.get('graphs', [])
                        if isinstance(graph, dict) and graph.get('weighted') is True} if isinstance(draft, dict) else set()
    unknown_weights = []
    for graph in normalized['graphs']:
        if graph['id'] in required_weight_graphs:
            continue
        for edge in graph['edges']:
            weight = edge.get('weight')
            unknown = isinstance(weight, str) and weight.strip().lower() in (
                'unknown', 'uncertain', '未知', '不确定', '?', '？')
            if unknown or weight is None and graph['id'] in declared_weighted:
                unknown_weights.append(_issue('unknown_weight', '该边有待确认的权重，不能按已读清处理。',
                    scope='graph', graph_id=graph['id'], field='weight', edge_id=edge['id']))
    issues = (normalized['semantic_issues'] + schema_issues + inspected['issues']
              + required_attributes + unknown_weights + _stroke_inventory_issues(draft)
              + _visual_count_issues(draft)
              + _caption_grid_issues(draft, context.data.get('pixel_evidence')))
    if context.data.get('visual_inventory') is not None:
        from graph_visual_inventory import compare_visual_inventory
        issues += compare_visual_inventory(draft, context.data['visual_inventory'])['issues']
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


def _validate(draft, budget, phase, *, visual_inventory=None, pixel_evidence=None):
    result = {}
    context = ToolContext(source_sha256=budget.source_sha256,
        deadline_monotonic=min(time.monotonic()+10, budget.deadline),
        data={'draft': draft, 'budget': budget, 'result': result, 'visual_inventory': visual_inventory,
              'pixel_evidence': pixel_evidence})
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
    old_inventory = {str(graph.get('id')): graph['stroke_inventory']
                     for graph in previous.get('graphs', []) if isinstance(graph, dict)
                     and 'stroke_inventory' in graph}
    old_flags = {str(graph.get('id')): {key: graph[key] for key in ('directed', 'weighted')
                                       if type(graph.get(key)) is bool}
                 for graph in previous.get('graphs', []) if isinstance(graph, dict)}
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
        for key, value in old_flags.get(gid, {}).items():
            returned[gid].setdefault(key, value)
        # A targeted reread cannot erase an earlier visual-count disagreement
        # just by omitting the count fields. Keep the earlier observation only
        # when the number of listed instances remains unchanged. When the
        # reread changes cardinality but fails to state its independent count,
        # mark that count unresolved instead of silently certifying the edit.
        previous_graph = next((old for old in previous.get('graphs', [])
                               if isinstance(old, dict) and str(old.get('id')) == gid), None)
        if previous_graph is not None:
            for count_key, list_key in (('visible_vertex_count', 'vertices'),
                                        ('visible_edge_count', 'edges')):
                if count_key in previous_graph and count_key not in graph:
                    before = previous_graph.get(list_key)
                    after = graph.get(list_key)
                    unchanged = isinstance(before, list) and isinstance(after, list) and len(before) == len(after)
                    returned[gid][count_key] = copy.deepcopy(previous_graph[count_key]) if unchanged else None
        if 'stroke_inventory' not in graph and gid in old_inventory:
            # Dropping an existing checklist must not silently erase a real
            # mismatch. A corrected visual reread may replace the checklist.
            returned[gid]['stroke_inventory'] = copy.deepcopy(old_inventory[gid])
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
                    and row.get('field') in (None, 'vertices', 'edges', 'direction')
                    and row.get('kind') not in ('visual_marker_count_conflict', 'stroke_inventory_mismatch')]
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


def _selected_local_tools_complete(handles, audits):
    if not handles or len(handles) != len(audits):
        return False
    for handle, audit in zip(handles, audits):
        expected = {name for name in ('text', 'layout') if handle.policy.get(name)}
        if handle.policy.get('paths'):
            expected.add('geometry')
        stages = audit.get('stages', [])
        if (not expected.issubset({row.get('stage') for row in stages})
                or any(row.get('status') not in ('ok', 'not_needed') for row in stages)):
            return False
    return True


def _measure_marker_inventory(markers, quick, budget):
    from graph_visual_inventory import measure_visual_inventory
    try:
        return measure_visual_inventory(markers, quick, budget=budget)
    except (AgentCancelled, TimeoutError):
        raise
    except Exception as exc:
        budget.check()
        # A local evidence failure cannot discard a usable visual reading or
        # count as a completed performance run.
        return {'status': 'failed', 'source_sha256': budget.source_sha256,
                'panels': [], 'diagnostics': [type(exc).__name__], 'proposal_only': True,
                'tool_audit': [{'tool': 'image.visual_marker_inventory', 'status': 'failed',
                                'source_sha256': budget.source_sha256, 'executed': False}]}


def _marker_inventory_complete(evidence):
    audits = [row for row in evidence.get('tool_audit', [])
              if isinstance(row, dict) and row.get('tool') == 'image.visual_marker_inventory']
    return (evidence.get('status') == 'measured' and bool(audits)
            and all(row.get('executed') is True and row.get('status') in ('success', 'ok') for row in audits))


def _compact_visual_inventory(evidence):
    """Only pixel-supported groups help the main reader; omit tool bookkeeping."""
    result = {'proposal_only': True, 'image_accuracy_certified': False,
              'position_space': 'original_1000', 'panels': []}
    if evidence.get('status') != 'measured':
        return result
    for panel in evidence.get('panels', [])[:32]:
        if not isinstance(panel, dict) or panel.get('comparison_eligible') is not True:
            continue
        row = {key: copy.deepcopy(panel[key]) for key in ('region_id', 'bbox', 'candidate_count') if key in panel}
        row.update(proposal_only=True, markers=[])
        for marker in panel.get('markers', [])[:160]:
            if not isinstance(marker, dict):
                continue
            candidate = {key: copy.deepcopy(marker[key]) for key in ('id', 'position', 'radius_pixels') if key in marker}
            proof = marker.get('proof', {})
            candidate['pixel_support'] = {key: copy.deepcopy(proof[key]) for key in
                ('source', 'convex_hull_roundness', 'component_fill', 'component_pixels') if key in proof}
            row['markers'].append(candidate)
        result['panels'].append(row)
    return result


def _main_panel_views(quick):
    """Reuse up to four existing figure windows; keep the full-page anchor."""
    images = quick['images'][:1]
    descriptions = quick['view_descriptions'][:1]
    panel_ids = {row['id'] for row in quick.get('panels', [])
                 if isinstance(row, dict) and isinstance(row.get('id'), str)}
    metadata = quick.get('view_metadata', [])
    used_panels, used_images = set(), set(images)
    for index, image in enumerate(quick['images'][1:], 1):
        if len(images) >= 5:
            break
        meta = metadata[index] if index < len(metadata) else None
        region_id = meta.get('region_id') if isinstance(meta, dict) else None
        if region_id not in panel_ids or region_id in used_panels or image in used_images:
            continue
        images.append(image)
        descriptions.append(f'同一原图的局部窗口 {region_id}，对应总览中的相同内容，仅供放大阅读，'
                            '不是新增子图；不能按窗口数量计图，图的数量与边界仍以完整原图为准。')
        used_panels.add(region_id)
        used_images.add(image)
    return {'images': images, 'view_descriptions': descriptions}


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
    from graph_pixel_safety import (measure_image_pixel_evidence,
        create_grid_column_views, reconcile_anonymous_pixel_graphs)

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
    visual_inventory = _measure_marker_inventory(markers, quick, budget)
    pixel_evidence = {'grid': None, 'colored_graphs': [], 'advisory_only': True}
    try:
        measured = measure_image_pixel_evidence(raw)
        if measured.get('source_sha256') == source:
            pixel_evidence = measured
    except Exception as exc:
        budget.event('fast_pixel_evidence', 'unavailable', error_kind=type(exc).__name__)
    budget.check()
    views = {'images': quick['images'][:1], 'view_descriptions': quick['view_descriptions'][:1]}
    main_views = _main_panel_views(quick)
    if pixel_evidence.get('grid'):
        try:
            columns = create_grid_column_views(raw, pixel_evidence)
        except Exception as exc:
            columns = []
            budget.event('fast_grid_columns', 'unavailable', error_kind=type(exc).__name__)
        if columns:
            main_views = {'images': views['images'] + [c['image'] for c in columns],
                          'view_descriptions': views['view_descriptions']
                                               + [c['description'] for c in columns]}
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
    pixel_repairs = []
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
            {'image_views': main_views['view_descriptions'],
             'local_layout_candidates': quick.get('panels', [])[:32],
             'local_marker_candidates': markers.get('marker_candidates', [])[:120],
             'local_visual_inventory': _compact_visual_inventory(visual_inventory),
             'local_caption_grid': pixel_evidence.get('grid'),
             'local_colored_graph_candidates': pixel_evidence.get('colored_graphs', [])[:12],
             'local_ocr_candidates': hints['candidates'], 'local_ocr_policy': hints['policy']},
            main_views['images'], output_tokens=12000, response_identity=False,
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
        draft, corrections = reconcile_anonymous_pixel_graphs(state['draft'], pixel_evidence)
        pixel_repairs.extend(corrections)
        checked = _validate(draft, budget, 'initial',
                            visual_inventory=visual_inventory, pixel_evidence=pixel_evidence)
        checked['issues'] += _text_candidate_issues(draft, local_result.get('text', {}), quick)
        reference = _local_reference(checked['normalized'], budget)
        return {**state, **checked, 'draft': draft, 'reference': reference}

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
                 'local_marker_candidates': markers.get('marker_candidates', [])[:120],
                 'local_visual_inventory': visual_inventory,
                 'local_caption_grid': pixel_evidence.get('grid'),
                 'local_colored_graph_candidates': pixel_evidence.get('colored_graphs', [])[:12],
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
        # GLM can propose a change; independent pixel evidence still needs to
        # agree for clear anonymous colored-marker straight-line diagrams.
        draft, corrections = reconcile_anonymous_pixel_graphs(state['draft'], pixel_evidence)
        pixel_repairs.extend(corrections)
        checked = _validate(draft, budget, 'final',
                            visual_inventory=visual_inventory, pixel_evidence=pixel_evidence)
        checked['issues'] += _text_candidate_issues(draft, local_result.get('text', {}), quick)
        return {**state, **checked, 'draft': draft}

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
    local_tools_complete = (_selected_local_tools_complete(handles, local_audit)
                            and _marker_inventory_complete(visual_inventory))
    selected_tools_complete = local_tools_complete and state['validation'].get('status') == 'completed'
    resource_metrics = quick.get('resource_metrics', []) + local_result.get('resource_metrics', [])
    tools_public = _public_local_result(local_result)
    tools_public['layout'] = _public_local_result({'layout': local_result.get('layout') or quick})['layout']
    tools_public['markers'] = {'marker_candidates': copy.deepcopy(markers.get('marker_candidates', [])),
                               'diagnostics': copy.deepcopy(markers.get('diagnostics', []))}
    tools_public['visual_inventory'] = copy.deepcopy(visual_inventory)
    result.update(diagnostics=stages, remote_metrics=copy.deepcopy(budget.metrics),
        image_quality=copy.deepcopy(quick.get('diagnostics', {})),
        local_layout_result=copy.deepcopy((local_result.get('layout') or quick).get('layout', {})),
        local_text_result={key: copy.deepcopy(text[key]) for key in ('text', 'text_evidence') if key in text},
        local_resource_metrics=resource_metrics,
        confirmation_required=True, recognition_profile='fast-editable',
        local_tools_complete=local_tools_complete, selected_tools_complete=selected_tools_complete,
        service_warnings=([{'kind': 'local_tools_degraded',
            'message': '部分本地图像辅助工具未完成，已保留视觉识别结果，请核对后确认。'}]
            if not local_tools_complete else []),
        semantic_workflow={'version': AGENT_PIPELINE_VERSION, 'mode': 'fast_editable',
            'task_id': budget.task_id, 'source_sha256': source,
            'image_accuracy_certified': False, 'user_confirmation_required': True,
            'roles': copy.deepcopy(budget.events), 'role_counts': copy.deepcopy(budget.role_counts),
            'readings': readings, 'timings': timings, 'local_tools': tools_public,
            'local_scheduler': local_audit, 'local_tool_policy': local_policy,
            'local_review': state.get('local_review', {}),
            'pixel_evidence': {'grid': copy.deepcopy(pixel_evidence.get('grid')),
                               'colored_graphs': copy.deepcopy(pixel_evidence.get('colored_graphs', [])),
                               'repairs': copy.deepcopy(pixel_repairs),
                               'image_accuracy_certified': False},
            'question_reference': state.get('reference', {}),
            'final_validation': state['validation'],
            'tool_audit': quick.get('tool_audit', [])+markers.get('tool_audit', [])
                +visual_inventory.get('tool_audit', [])
                +local_result.get('tool_audit', [])+state['validation'].get('tool_audit', []),
            'performance': {'target_seconds': PERFORMANCE_TARGET_SECONDS,
                'recognition_seconds': round(time.monotonic()-started, 6),
                'scope': 'recognition_before_response_rendering',
                'local_tools_complete': local_tools_complete,
                'selected_tools_complete': selected_tools_complete,
                'completed': not issues and selected_tools_complete,
                'within_target': not issues and selected_tools_complete
                    and time.monotonic()-started <= PERFORMANCE_TARGET_SECONDS}})
    budget.local_tool_execution = tools_public
    if audit:
        result['stage_audit'] = {'responses': readings, 'observations': runner.observations}
    return result


__all__ = ['recognize_fast', 'configured_fast_budget', 'PERFORMANCE_TARGET_SECONDS']
