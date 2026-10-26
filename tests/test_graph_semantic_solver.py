import copy
import json

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
