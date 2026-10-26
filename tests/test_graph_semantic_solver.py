import copy
import json

import pytest

from graph_semantic_solver import semantic_solver_context, semantic_math_prompt
from test_ocr_application_contract import application


def payload(question='求从a到A的最短路径。'):
    graph = {'id': 'G1', 'name': '(a)', 'complete': True, 'directed': False,
             'vertices': [{'id': 'a', 'label': 'a'}, {'id': 'A', 'label': 'A'}, {'id': 'b', 'label': 'b'}],
             'edges': [{'id': 'parallel_1', 'from': 'a', 'to': 'A', 'direction': 'undirected', 'weight': 9},
                       {'id': 'parallel_2', 'from': 'a', 'to': 'A', 'direction': 'undirected', 'weight': 2},
                       {'id': 'next', 'from': 'A', 'to': 'b', 'direction': 'undirected', 'weight': 3}]}
    return {'source_sha256': 'a'*64, 'document': {'body_text': question, 'graphs': [graph]},
            'question_text': '【题目文字】\n'+question+'\n【图形信息】\n这是同一份图。',
            'rendered_question_text': question+'\n【图形信息】\n这是同一份图。'}


def test_same_question_uses_actual_weighted_path_and_distinct_uppercase_vertex():
    data = payload()
    old = copy.deepcopy(data)
    result = semantic_solver_context(data, '[图片识题]\n'+data['question_text'])
    assert result['status'] == 'bound'
    calculated = result['calculations'][0]
    assert calculated['request']['weighted'] is True
    assert calculated['result']['status'] == 'computed'
    assert calculated['result']['facts']['distance'] == 2
    assert calculated['result']['facts']['edge_ids'] == ['parallel_2']
    assert calculated['result']['facts']['vertex_ids'] == ['a', 'A']
    assert data == old
    assert result['image_accuracy_certified'] is False


def test_mst_runs_without_unsupported_path_only_argument():
    data = payload('求最小生成树及总权值。')
    result = semantic_solver_context(data, data['question_text'])
    calculated = result['calculations'][0]
    assert calculated['result']['status'] == 'computed'
    assert calculated['result']['facts']['total_weight'] == 5
    assert set(calculated['result']['facts']['edge_ids']) == {'parallel_2', 'next'}


def test_stale_or_exercise_context_runs_no_computation(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('stale graph computation')
    monkeypatch.setattr('graph_semantic_solver.inspect_semantic_graphs', forbidden)
    data = payload()
    assert semantic_solver_context(data, '新题：求集合的交集')['status'] == 'question_mismatch'
    assert semantic_solver_context(data, data['question_text'], active=False)['status'] == 'not_requested'


def test_followup_matches_display_anchor_but_not_historical_other_message():
    data = payload()
    result = semantic_solver_context(data, '【当前指向题目】\n'+data['rendered_question_text']+'\n【当前指向题目结束】\n给出解析')
    assert result['status'] == 'bound'
    assert semantic_solver_context(data, '上一题的答案是什么？')['status'] == 'question_mismatch'


def test_incomplete_or_symbolic_weight_is_not_silently_solved():
    data = payload()
    data['document']['graphs'][0]['complete'] = False
    result = semantic_solver_context(data, data['question_text'])
    assert result['calculations'][0]['result']['status'] == 'not_applicable'
    data['document']['graphs'][0]['complete'] = True
    data['document']['graphs'][0]['edges'][0]['weight'] = 'x'
    result = semantic_solver_context(data, data['question_text'])
    assert result['calculations'][0]['result']['issues'][0]['code'] == 'complete_numeric_weights_required'


def test_oversized_snapshot_does_not_truncate_into_a_different_graph():
    data = payload()
    data['document']['graphs'][0]['vertices'] *= 40
    assert semantic_solver_context(data, data['question_text'])['status'] == 'invalid_snapshot'


def test_exact_semantics_pass_to_deepseek_without_geometry_or_false_image_claim():
    data = payload()
    data['document']['graphs'][0]['vertices'][0]['x'] = 99
    data['document']['graphs'][0]['edges'][0]['path'] = [[1, 2]]
    result = semantic_solver_context(data, data['question_text'])
    prompt = semantic_math_prompt(result)
    assert 'parallel_1' in prompt and 'parallel_2' in prompt
    assert '"a"' in prompt and '"A"' in prompt
    assert '"path"' not in prompt and '"x"' not in prompt
    assert '不证明图片识别正确' in prompt and '不能因为内部有计算结果就泄露完整答案' in prompt
    json.dumps(result, ensure_ascii=False, allow_nan=False)


def test_chat_passes_bound_tools_to_ai_and_does_not_use_lossy_text_solver(application, monkeypatch):
    module, client, _ = application
    captured = []
    def answer(messages, **kwargs):
        captured.append(copy.deepcopy(kwargs['teaching_context']))
        return {'ok': True, 'reply': '最小生成树的总权值为5。'}
    def forbidden(*args, **kwargs):
        raise AssertionError('semantic graph must not be reparsed from old prose')
    monkeypatch.setattr(module, 'ask_ai', answer)
    monkeypatch.setattr(module, 'solve_certified_graph', forbidden)
    data = payload('求最小生成树及总权值。')
    response = client.post('/chat', json={
        'messages': [{'role': 'user', 'content': '[图片识题]\n'+data['question_text']+'\n请给出答案'}],
        'semantic_context': data, 'request_kind': 'solution'})
    assert response.status_code == 200
    assert captured[0]['semantic_math']['calculations'][0]['result']['facts']['total_weight'] == 5
    assert response.get_json()['diagnostics']['semantic_math']['status'] == 'bound'


def test_deepseek_request_contains_actual_tool_facts_without_an_extra_model_call(monkeypatch):
    import ai
    data = payload()
    context = semantic_solver_context(data, data['question_text'])
    requests = []
    def completion(messages, **kwargs):
        requests.append(copy.deepcopy(messages))
        return {'ok': True, 'content': '先比较两条平行边的权值。', 'choice': {'finish_reason': 'stop'}}
    monkeypatch.setattr(ai, 'ASK_AI_MOCK', False)
    monkeypatch.setattr(ai, 'DEEPSEEK_API_KEY', 'unused-fixture-credential')
    monkeypatch.setattr(ai, '_request_text_completion', completion)
    result = ai.ask_ai([{'role': 'user', 'content': data['question_text']+'只给提示'}],
                       teaching_context={'mode': 'hint', 'semantic_math': context})
    assert result['ok'] and len(requests) == 1
    assert 'parallel_2' in requests[0][0]['content'] and '"distance":2' in requests[0][0]['content']


def test_declared_weighted_graph_with_missing_weights_is_not_solved_by_edge_count():
    data = payload()
    graph = data['document']['graphs'][0]
    graph['weighted'] = True
    for edge in graph['edges']:
        edge['weight'] = None
    result = semantic_solver_context(data, data['question_text'])['calculations'][0]
    assert result['request']['weighted'] is True
    assert result['result']['issues'][0]['code'] == 'complete_numeric_weights_required'


def test_explicit_unweighted_question_can_use_counts_without_filling_missing_weights():
    data = payload('忽略权值，求从a到A按边数计算的最短路径。')
    graph = data['document']['graphs'][0]
    graph['weighted'] = True
    for edge in graph['edges']:
        edge['weight'] = None
    before = copy.deepcopy(data)
    result = semantic_solver_context(data, data['question_text'])['calculations'][0]
    assert result['request']['weighted'] is False
    assert result['result']['facts']['distance'] == 1
    assert data == before


@pytest.mark.parametrize('pending', ['unresolved_edges', 'unresolved_vertices', 'uncertain_edges', 'edge_status'])
def test_snapshot_projection_preserves_pending_graph_content(pending):
    data = payload()
    graph = data['document']['graphs'][0]
    if pending == 'edge_status':
        graph['edges'][0]['status'] = 'uncertain'
    else:
        graph[pending] = [{'reason': 'await source verification'}]
    result = semantic_solver_context(data, data['question_text'])
    assert result['calculations'][0]['result']['issues'][0]['code'] == 'incomplete_semantic_snapshot'
    if pending != 'edge_status':
        assert result['document']['graphs'][0][pending] == graph[pending]


def test_solver_dispatches_adjacency_walk_and_euler_from_literal_question_only():
    data = payload('按边实例数写邻接矩阵；求从a到b长度为2的通路条数；判断有无欧拉通路。')
    results = semantic_solver_context(data, data['question_text'])['calculations']
    facts = {row['request']['operation']: row['result']['facts'] for row in results}
    assert set(facts) == {'adjacency_matrix', 'walk_count', 'euler'}
    assert facts['adjacency_matrix']['matrix'] == [[0, 2, 0], [2, 0, 1], [0, 1, 0]]
    assert facts['walk_count']['count'] == 2
    assert facts['euler']['has_eulerian_trail'] and not facts['euler']['has_eulerian_circuit']


@pytest.mark.parametrize('question', [
    '求从a到b长度为2的简单通路条数。', '求从a到b长度为2的不重复顶点通路数量。',
    '求从a到b长度为k的通路条数。', '求从a到b长度为2.5的通路条数。',
    '求从a到b长度为2/3的通路条数。', '求从a到b长度为2n的通路条数。',
    '求从a到b长度为2 / 3的通路条数。', '求从a到b长度为2 × 3的通路条数。',
    '求从a到b长度为2 ^ 3的通路条数。', '求从a到b长度为2 的平方的通路条数。',
    '求从a到b长度为65的通路条数。', '求长度为2的通路条数。',
    '从a到A写出一条通路；求从A到b的通路数量。',
])
def test_unsupported_or_ambiguous_walk_question_does_not_become_unrestricted_walk_count(question):
    data = payload(question)
    result = semantic_solver_context(data, data['question_text'])
    assert not any(row['request']['operation'] == 'walk_count' for row in result['calculations'])


def test_shortest_path_endpoints_are_not_taken_from_a_different_subquestion():
    data = payload('从a到A写一条通路；求从A到b的最短路径。')
    request = semantic_solver_context(data, data['question_text'])['calculations'][0]['request']
    assert (request['source'], request['target']) == ('A', 'b')


def test_weighted_adjacency_question_is_not_given_an_unlabelled_count_matrix():
    data = payload('求带权邻接矩阵。')
    assert semantic_solver_context(data, data['question_text'])['calculations'] == []
    unweighted = payload('写出邻接矩阵。')
    for edge in unweighted['document']['graphs'][0]['edges']:
        edge['weight'] = None
    result = semantic_solver_context(unweighted, unweighted['question_text'])['calculations'][0]
    assert result['result']['facts']['entry_meaning'] == 'edge_instance_count'


def reference_for(data):
    from graph_semantic_question_reference import VERSION, _snapshot
    snapshot = _snapshot(data['document'], data['source_sha256'])
    return {'version': VERSION, 'status': 'ready', 'advisory_only': True,
            'non_authoritative': True, 'cannot_drop_content': True,
            **{key: snapshot[key] for key in ('source_sha256', 'text_digest', 'graph_catalog_digest')},
            'subquestions': [], 'references': [], 'focus': [], 'unresolved': []}


def test_actual_source_bound_reference_is_optional_prompt_advice_and_not_tool_arguments():
    data = payload()
    data['document']['text_context'] = {'legends': [{'text': '蓝色为另一条边', 'graph_ids': ['G1']}], 'captions': []}
    data['question_reference'] = reference_for(data)
    data['question_reference']['subquestions'] = [{
        'id': 'literal_1', 'source_spans': [{'block_id': 'body', 'start': 0,
            'end': len(data['document']['body_text']), 'quote': data['document']['body_text']}],
        'graph_ids': ['G1'], 'summary': '参考建议按边数计算，但该建议不得改变工具参数。'}]
    before = copy.deepcopy(data)
    result = semantic_solver_context(data, data['question_text'])
    assert result['question_reference']['advisory_only'] is True
    assert result['question_reference']['source_sha256'] == data['source_sha256']
    assert result['calculations'][0]['request']['weighted'] is True
    assert result['calculations'][0]['result']['facts']['distance'] == 2
    prompt = semantic_math_prompt(result)
    assert 'advisory_only' in prompt and '不能改变程序工具参数' in prompt
    assert data == before


@pytest.mark.parametrize('change', ['source', 'body', 'catalog', 'extra_policy', 'oversized', 'circular'])
def test_stale_or_invalid_optional_reference_never_invalidates_legacy_snapshot(change):
    data = payload()
    data['question_reference'] = reference_for(data)
    if change == 'source':
        data['question_reference']['source_sha256'] = 'b'*64
    elif change == 'body':
        data['document']['body_text'] += ' 新小问'
    elif change == 'catalog':
        data['document']['graphs'][0]['vertices'][0]['label'] = 'v₁'
    elif change == 'extra_policy':
        data['question_reference']['focus'] = [{'drop_all_edges': True}]
    elif change == 'oversized':
        data['question_reference']['unused'] = 'x'*300_000
    else:
        data['question_reference']['cycle'] = data['question_reference']
    result = semantic_solver_context(data, data['question_text'])
    assert result['status'] == 'bound' and 'question_reference' not in result
    assert result['calculations'][0]['result']['facts']['distance'] == 2


def test_optional_reference_module_failure_does_not_block_computation(monkeypatch):
    import graph_semantic_question_reference as reference
    data = payload()
    data['question_reference'] = reference_for(data)
    def unavailable(*args, **kwargs):
        raise RuntimeError('optional helper unavailable')
    monkeypatch.setattr(reference, 'question_reference_for_document', unavailable)
    result = semantic_solver_context(data, data['question_text'])
    assert result['status'] == 'bound' and 'question_reference' not in result
    assert result['calculations'][0]['result']['facts']['distance'] == 2


def test_formula_prose_is_not_evaluated_or_misrepresented_as_a_structured_sympy_input():
    data = payload('证明 p∧q 蕴含 p，并计算矩阵 [[1,2],[3,4]] 的逆。')
    result = semantic_solver_context(data, data['question_text'])
    assert result['status'] == 'bound' and result['calculations'] == []


@pytest.mark.parametrize('text_context', [
    'not a literal context', {'legends': [{'text': object()}]},
    {'captions': [{'text': 'x'*2001, 'graph_ids': ['G1']}]},
    {'legends': [{'text': 'a caption', 'graph_ids': ['missing_graph']}]},
    {'captions': [{'text': 'a caption'}]*33},
])
def test_bad_optional_text_context_only_drops_reference_not_usable_graph(text_context):
    data = payload()
    data['question_reference'] = reference_for(data)
    data['document']['text_context'] = text_context
    result = semantic_solver_context(data, data['question_text'])
    assert result['status'] == 'bound' and 'question_reference' not in result
    assert 'text_context' not in result['document']
    assert result['calculations'][0]['result']['facts']['distance'] == 2
