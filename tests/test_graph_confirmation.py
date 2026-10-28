"""Edited snapshots and real Flask/math boundaries; zero model/network calls."""
import copy
import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest

from graph_confirmation import (ConfirmationError, COOKIE_NAME, confirm_document,
    document_digest, register_recognition, resolve_confirmed_context, validate_document)
from test_ocr_application_contract import application


@pytest.fixture(autouse=True)
def private_registry(monkeypatch, tmp_path):
    monkeypatch.setenv('DMATE_GRAPH_CONFIRMATION_DB', str(tmp_path/'confirm.sqlite3'))


def document(weight=2, direction='undirected'):
    return {'body_text': '求从a到b的最短路径。', 'graphs': [{
        'id': 'G1', 'name': '(a)', 'vertices': [
            {'id': 'a', 'label': 'a'}, {'id': 'b', 'label': 'b'}, {'id': 'i', 'label': None}],
        'edges': [{'id': 'short', 'from': 'a', 'to': 'b', 'direction': direction, 'weight': weight},
                  {'id': 'long', 'from': 'a', 'to': 'b', 'direction': direction, 'weight': 9},
                  {'id': 'loop', 'from': 'b', 'to': 'b', 'direction': direction, 'weight': 0}]}]}


def confirm(owner='owner', request_id='task-1', sha='a'*64, value=None):
    register_recognition(owner, request_id, sha)
    return confirm_document(owner, {'request_id': request_id, 'source_sha256': sha,
                                    'document': value or document(), 'confirmed': True})


def test_confirmation_validates_and_preserves_actual_instances_and_isolated_vertex():
    result = confirm()
    graph = result['document']['graphs'][0]
    assert len(graph['edges']) == 3 and graph['multigraph'] is True
    assert graph['vertices'][-1]['isolated_confirmed'] is True
    assert graph['complete'] is True and all(e['status'] == 'accepted' for e in graph['edges'])
    assert any(a.get('library') == 'networkx' and a.get('executed') for a in result['validation']['tool_audit'])
    assert result['validation']['image_accuracy_certified'] is False
    assert resolve_confirmed_context('owner', result['semantic_context']) == result['semantic_context']


@pytest.mark.parametrize('mutation', ['endpoint', 'duplicate_node', 'duplicate_edge', 'duplicate_graph',
                                      'unknown_direction', 'aggregate', 'nonfinite', 'legend_target', 'pending'])
def test_invalid_edits_are_not_silently_repaired_or_confirmed(mutation):
    value = document()
    graph = value['graphs'][0]
    if mutation == 'endpoint': graph['edges'][0]['to'] = 'absent'
    elif mutation == 'duplicate_node': graph['vertices'].append(copy.deepcopy(graph['vertices'][0]))
    elif mutation == 'duplicate_edge': graph['edges'].append(copy.deepcopy(graph['edges'][0]))
    elif mutation == 'duplicate_graph': value['graphs'].append(copy.deepcopy(graph))
    elif mutation == 'unknown_direction': graph['edges'][0]['direction'] = 'unknown'
    elif mutation == 'aggregate': graph['edges'][0]['multiplicity'] = 3
    elif mutation == 'nonfinite': graph['edges'][0]['weight'] = float('nan')
    elif mutation == 'legend_target': value['text_context'] = {'legends': [{'text': '蓝边可行', 'graph_ids': ['G2']}]}
    else: graph['unresolved_edges'] = [{'record': {'from': 'a', 'to': 'unknown'}}]
    with pytest.raises(ConfirmationError):
        confirm(value=value)


def test_raw_image_task_must_be_registered_and_cannot_change_source():
    with pytest.raises(ConfirmationError, match='失效'):
        confirm_document('owner', {'request_id': 'missing', 'source_sha256': 'a'*64,
                                  'document': document(), 'confirmed': True})
    register_recognition('owner', 'task', 'a'*64)
    with pytest.raises(ConfirmationError, match='原图已改变'):
        register_recognition('owner', 'task', 'b'*64)


@pytest.mark.parametrize('change', ['weight', 'direction', 'body', 'anchor', 'token', 'task', 'source'])
def test_client_changes_require_reconfirmation(change):
    payload = copy.deepcopy(confirm()['semantic_context'])
    if change == 'weight': payload['document']['graphs'][0]['edges'][0]['weight'] = 8
    elif change == 'direction': payload['document']['graphs'][0]['edges'][0]['direction'] = 'forward'
    elif change == 'body': payload['document']['body_text'] = '另一道题'
    elif change == 'anchor': payload['question_text'] = '伪造文字'
    elif change == 'token': payload['confirmation_token'] = 'b'*64
    elif change == 'task': payload['request_id'] = 'another-task'
    else: payload['source_sha256'] = 'b'*64
    with pytest.raises(ConfirmationError):
        resolve_confirmed_context('owner', payload)


def test_new_revision_invalidates_old_token_but_other_images_remain_independent():
    old = confirm()['semantic_context']
    other = confirm(request_id='task-2', sha='b'*64)['semantic_context']
    current = confirm(value=document(weight=7, direction='forward'))['semantic_context']
    assert current['revision'] == 2
    with pytest.raises(ConfirmationError): resolve_confirmed_context('owner', old)
    with pytest.raises(ConfirmationError): resolve_confirmed_context('another-owner', current)
    assert resolve_confirmed_context('owner', other) == other
    assert resolve_confirmed_context('owner', current)['document']['graphs'][0]['edges'][0]['weight'] == 7


def test_no_token_legacy_context_cannot_bypass_new_registered_image_confirmation():
    legacy = {'source_sha256': 'a'*64, 'document': document(), 'question_text': '旧识别文本'}
    assert resolve_confirmed_context('owner', legacy) is None
    register_recognition('owner', 'task', 'a'*64)
    with pytest.raises(ConfirmationError) as failure:
        resolve_confirmed_context('owner', legacy)
    assert failure.value.code == 'confirmation_required'


def test_four_concurrent_confirmations_do_not_share_latest_snapshot():
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda i: confirm(request_id=f'task-{i}', sha=str(i)*64,
                                                  value=document(weight=i)), range(1, 5)))
    assert {r['semantic_context']['document']['graphs'][0]['edges'][0]['weight'] for r in results} == {1, 2, 3, 4}
    for result in results:
        assert resolve_confirmed_context('owner', result['semantic_context']) == result['semantic_context']


def register_for_client(module, client, request_id='task-1', sha='a'*64):
    assert client.get('/graph/session').status_code == 200
    cookie = client.get_cookie(COOKIE_NAME)
    assert cookie.http_only and cookie.same_site == 'Lax'
    owner = hashlib.sha256((cookie.value + ':guest').encode()).hexdigest()
    register_recognition(owner, request_id, sha)
    return owner


def route_confirm(client, value=None, request_id='task-1', sha='a'*64):
    response = client.post('/graph/confirm', json={'document': value or document(),
        'request_id': request_id, 'source_sha256': sha, 'confirmed': True})
    assert response.status_code == 200, response.get_json()
    return response.get_json()['semantic_context']


def chat_payload(context, action='请给出答案和解析'):
    return {'request_kind': 'solution', 'semantic_context': context, 'messages': [{
        'role': 'user', 'content': '【当前指向题目】\n'+context['question_text']+
        '\n【当前指向题目结束】\n【本轮唯一需要执行的用户请求】\n'+action+'\n【本轮请求结束】'}]}


def test_confirm_does_not_call_ai_and_solver_receives_final_edited_weights_and_direction(application, monkeypatch):
    module, client, _ = application
    captured = []
    def answer(messages, **kwargs):
        captured.append(copy.deepcopy(kwargs['teaching_context']['semantic_math']))
        return {'ok': True, 'reply': '根据已确认的图，最短路径长度为7。'}
    monkeypatch.setattr(module, 'ask_ai', answer)
    register_for_client(module, client)
    context = route_confirm(client, document(weight=7, direction='forward'))
    assert captured == []
    response = client.post('/chat', json=chat_payload(context))
    assert response.status_code == 200, response.get_json()
    assert len(captured) == 1 and captured[0]['user_confirmed'] is True
    facts = captured[0]['calculations'][0]['result']['facts']
    assert facts['distance'] == 7 and facts['edge_ids'] == ['short']
    assert captured[0]['document']['graphs'][0]['edges'][0]['direction'] == 'forward'
    assert response.get_json()['diagnostics']['semantic_math']['document_sha256'] == document_digest(context['document'])


def test_changed_or_cross_browser_snapshot_never_reaches_ai(application, monkeypatch):
    module, client, _ = application
    monkeypatch.setattr(module, 'ask_ai', lambda *a, **k: pytest.fail('Unconfirmed structure reached DeepSeek'))
    register_for_client(module, client)
    context = route_confirm(client)
    changed = copy.deepcopy(context)
    changed['document']['graphs'][0]['edges'][0]['weight'] = 100
    assert client.post('/chat', json=chat_payload(changed)).status_code == 409
    other_client = module.app.test_client()
    assert other_client.post('/chat', json=chat_payload(context)).status_code == 409
    wrong_question = chat_payload(context)
    wrong_question['messages'][-1]['content'] = '请解另一道题。'
    assert client.post('/chat', json=wrong_question).status_code == 409


def test_text_only_confirmation_and_plain_legacy_chat_both_work(application, monkeypatch):
    module, client, _ = application
    calls = []
    monkeypatch.setattr(module, 'ask_ai', lambda *a, **k: calls.append(k) or {'ok': True, 'reply': '可以从定义出发。'})
    register_for_client(module, client)
    context = route_confirm(client, {'body_text': '证明集合交运算满足交换律。', 'graphs': []})
    assert client.post('/chat', json=chat_payload(context)).status_code == 200
    assert calls[0]['teaching_context']['semantic_math']['document']['graphs'] == []
    assert client.post('/chat', json={'messages': [{'role': 'user', 'content': '什么是集合？'}]}).status_code == 200


def test_legacy_text_graph_postprocessors_cannot_override_confirmed_graph(application, monkeypatch):
    module, client, _ = application
    register_for_client(module, client)
    context = route_confirm(client)
    monkeypatch.setattr(module, 'ask_ai', lambda *a, **k: {'ok': True, 'reply': '依据用户确认的结构回答。'})
    for name in ('solve_certified_graph', 'answer_graph_isomorphism', 'summarize_tree_question', 'protect_uncertain_graph_answer'):
        monkeypatch.setattr(module, name, lambda *a, **k: pytest.fail('Old prose graph parser used'))
    assert client.post('/chat', json=chat_payload(context)).status_code == 200


def test_edit_during_ai_call_discards_reply_for_old_confirmation(application, monkeypatch):
    module, client, _ = application
    owner = register_for_client(module, client)
    context = route_confirm(client)
    def answer(*args, **kwargs):
        confirm_document(owner, {'document': document(weight=8), 'confirmed': True,
            'request_id': 'task-1', 'source_sha256': 'a'*64})
        return {'ok': True, 'reply': '旧图的答案不应显示。'}
    monkeypatch.setattr(module, 'ask_ai', answer)
    response = client.post('/chat', json=chat_payload(context))
    assert response.status_code == 409
    assert response.get_json()['code'] == 'confirmation_stale'
    assert 'reply' not in response.get_json()


def test_saved_reference_answer_cannot_override_an_edited_graph(application, monkeypatch):
    module, client, _ = application
    register_for_client(module, client)
    context = route_confirm(client, document(weight=7))
    captured = []
    monkeypatch.setattr(module, 'ask_ai', lambda *a, **k: captured.append(k['teaching_context'])
                        or {'ok': True, 'reply': '当前确认图的最短路径为7。'})
    payload = chat_payload(context)
    payload['solution_reference'] = {'question': context['question_text'], 'answer': '旧图结果为2。'}
    assert client.post('/chat', json=payload).status_code == 200
    assert 'solution_reference_answer' not in captured[0]
    assert captured[0]['semantic_math']['calculations'][0]['result']['facts']['distance'] == 7


def test_confirmed_adjacency_operations_pass_actual_sympy_results_to_ai(application, monkeypatch):
    module, client, _ = application
    captured = []
    monkeypatch.setattr(module, 'ask_ai', lambda *a, **k: captured.append(k['teaching_context']['semantic_math'])
                        or {'ok': True, 'reply': '按已确认的边实例进行矩阵计算。'})
    register_for_client(module, client)
    value = document()
    value['body_text'] = '按边实例数计算邻接矩阵的2次幂、秩和行列式。'
    context = route_confirm(client, value)
    assert client.post('/chat', json=chat_payload(context)).status_code == 200
    results = {r['request']['operation']: r['result'] for r in captured[0]['calculations']}
    assert results['adjacency_matrix_power']['facts']['matrix'] == [[4, 2, 0], [2, 5, 0], [0, 0, 0]]
    assert results['adjacency_matrix_rank']['facts']['rank'] == 2
    assert results['adjacency_matrix_determinant']['facts']['scalar'] == 0
    assert all(results[k]['status'] == 'computed' for k in results)
    assert any(a.get('tool') == 'math.matrix' and a.get('role') == 'solver'
               for a in captured[0]['tool_audit'])


@pytest.mark.parametrize('question', ['邻接矩阵A^2/3', '邻接矩阵A^{2}/3',
    '邻接矩阵A^2 + 3', '邻接矩阵A^22', '邻接矩阵A^n', '带权邻接矩阵的秩'])
def test_symbolic_bridge_does_not_guess_ambiguous_operands(question, monkeypatch):
    from graph_semantic_solver import confirmed_matrix_calculations
    context = {'status': 'bound', 'user_confirmed': True, 'document': document(),
               'calculations': [], 'tool_audit': [], 'source_sha256': 'a'*64}
    for edge in context['document']['graphs'][0]['edges']:
        edge['weight'] = None
    monkeypatch.setattr('graph_semantic_solver.prepare_semantic_math',
                        lambda *a, **k: pytest.fail('Ambiguous matrix convention reached tools'))
    assert confirmed_matrix_calculations(context, question) == context


def test_image_positions_paths_and_anonymous_ids_survive_confirm_and_reuse():
    value = document()
    graph = value["graphs"][0]
    graph["bbox"] = [.1, .1, .9, .9]
    graph["region_polygon"] = [[.1, .1], [.9, .1], [.8, .9], [.2, .8]]
    graph["anon_next"] = 4
    graph["vertices"][0].update(x=.2, y=.3)
    graph["vertices"][1].update(x=.8, y=.7)
    graph["vertices"][-1].update(x=.5, y=.2, display_label="③")
    graph["edges"][0]["path"] = [[.2, .3], [.5, .4], [.8, .7]]
    saved = confirm(value=value)
    final = saved["drawing_document"]["graphs"][0]
    assert "bbox" not in saved["document"]["graphs"][0]
    assert "path" not in saved["document"]["graphs"][0]["edges"][0]
    assert "bbox" not in saved["semantic_context"]["document"]["graphs"][0]
    assert final["bbox"] == [.1, .1, .9, .9]
    assert final["region_polygon"] == [[.1, .1], [.9, .1], [.8, .9], [.2, .8]]
    assert "region_polygon" not in saved["semantic_context"]["document"]["graphs"][0]
    assert final["anon_next"] == 4
    assert final["vertices"][-1]["label"] is None
    assert final["vertices"][-1]["display_label"] == "③"
    assert final["edges"][0]["path"] == [[.2, .3], [.5, .4], [.8, .7]]
    assert resolve_confirmed_context("owner", saved["semantic_context"]) == saved["semantic_context"]


@pytest.mark.parametrize("bad", ["point", "path", "bbox", "half_coordinate"])
def test_bad_geometry_is_rejected_instead_of_silently_erased(bad):
    value = document()
    graph = value["graphs"][0]
    if bad == "point":
        graph["vertices"][0].update(x=float("inf"), y=.3)
    elif bad == "path":
        graph["edges"][0]["path"] = [[.2, .3], [float("nan"), .5]]
    elif bad == "bbox":
        graph["bbox"] = [.9, .1, .1, .8]
    else:
        graph["vertices"][0]["x"] = .3
    with pytest.raises(ConfirmationError):
        confirm(value=value)


def test_unbounded_drawing_coordinates_survive_confirmation():
    value=document();value['graphs'][0]['vertices'][0].update(x=-3.5,y=4.25)
    value['graphs'][0]['edges'][0]['path']=[[-3.5,4.25],[2.5,-2.0]]
    result=confirm(value=value)["drawing_document"]
    assert result['graphs'][0]['vertices'][0]['x'] == -3.5
    assert result['graphs'][0]['edges'][0]['path'][1] == [2.5,-2.0]
