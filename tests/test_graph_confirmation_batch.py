"""Four source-bound edits become one chat request with scoped graph IDs."""
import copy
import hashlib

import pytest

from graph_confirmation import (COOKIE_NAME, ConfirmationError, confirm_document,
                                register_recognition)
from graph_confirmation_batch import batch_question_text, resolve_confirmed_batch
from test_ocr_application_contract import application


@pytest.fixture(autouse=True)
def private_batch_registry(monkeypatch, tmp_path):
    monkeypatch.setenv('DMATE_GRAPH_CONFIRMATION_DB', str(tmp_path / 'batch.sqlite3'))


def document(index):
    return {'body_text': '求各顶点的度数。', 'graphs': [{
        'id': 'G1', 'name': 'G1', 'vertices': [
            {'id': 'a', 'label': None, 'display_label': '①'},
            {'id': 'b', 'label': None, 'display_label': '②'}],
        'visual_description': '图片' + str(index) + '的原图外观',
        'edges': [{'id': 'same-edge', 'from': 'a', 'to': 'b', 'direction': 'undirected', 'weight': index}]}],
        'text_context': {'legends': [{'text': '本图红色边的权值为' + str(index), 'graph_ids': ['G1']}],
                         'captions': [{'text': '图片局部说明', 'graph_ids': []}]}}


def confirmed(owner='owner', count=4):
    result = []
    for index in range(1, count + 1):
        request_id, sha = 'image-task-' + str(index), str(index) * 64
        register_recognition(owner, request_id, sha)
        value = confirm_document(owner, {'document': document(index), 'confirmed': True,
            'request_id': request_id, 'source_sha256': sha})
        result.append(value['semantic_context'])
    return result


def browser_owner(client):
    client.get('/graph/session')
    return hashlib.sha256((client.get_cookie(COOKIE_NAME).value + ':guest').encode()).hexdigest()


def request_body(contexts, action='请把所有图片一起解答，并核验计算结果。'):
    question = batch_question_text(contexts)
    content = ('【当前指向题目】\n' + question + '\n【当前指向题目结束】\n'
               '【本轮唯一需要执行的用户请求】\n' + action + '\n【本轮请求结束】')
    return {'messages': [{'role': 'user', 'content': content}],
            'semantic_contexts': contexts, 'request_kind': 'solution'}


def test_batch_is_request_data_without_forging_individual_confirmation():
    contexts = confirmed()
    before = copy.deepcopy(contexts)
    batch = resolve_confirmed_batch('owner', contexts)
    assert contexts == before
    assert 'confirmation_token' not in batch
    assert batch['profile'] == 'confirmed-batch/1'
    assert batch['question_text'] == '\n\n'.join('【图片 ' + str(i) + '】\n' + c['question_text']
                                                 for i, c in enumerate(contexts, 1))
    assert batch['rendered_question_text'] == batch_question_text(contexts, 'rendered_question_text')
    graphs = batch['document']['graphs']
    assert [g['id'] for g in graphs] == ['image1_graph1', 'image2_graph1', 'image3_graph1', 'image4_graph1']
    assert [g['name'] for g in graphs] == ['图片' + str(i) + ' · G1' for i in range(1, 5)]
    for index, graph in enumerate(graphs, 1):
        assert graph['vertices'] == contexts[index - 1]['document']['graphs'][0]['vertices']
        assert graph['edges'] == contexts[index - 1]['document']['graphs'][0]['edges']
        assert graph['edges'][0]['id'] == 'same-edge'
        assert graph['edges'][0]['weight'] == index
    assert [row['graph_ids'] for row in batch['document']['text_context']['legends']] == [
        ['image1_graph1'], ['image2_graph1'], ['image3_graph1'], ['image4_graph1']]
    assert [s['request_id'] for s in batch['confirmed_sources']] == [c['request_id'] for c in contexts]


@pytest.mark.parametrize('value', [None, {}, [], [None], [None] * 5])
def test_batch_requires_one_to_four_real_confirmations(value):
    with pytest.raises(ConfirmationError):
        resolve_confirmed_batch('owner', value)


def test_duplicate_or_foreign_owner_context_is_rejected():
    contexts = confirmed(count=2)
    with pytest.raises(ConfirmationError, match='重复'):
        resolve_confirmed_batch('owner', [contexts[0], contexts[0]])
    with pytest.raises(ConfirmationError):
        resolve_confirmed_batch('different-owner', contexts)


def test_one_of_four_stale_confirmations_rejects_the_entire_batch():
    contexts = confirmed()
    confirm_document('owner', {'document': document(99), 'confirmed': True,
        'request_id': 'image-task-3', 'source_sha256': '3' * 64})
    with pytest.raises(ConfirmationError) as failure:
        resolve_confirmed_batch('owner', contexts)
    assert failure.value.code == 'confirmation_stale'


def test_reordering_images_changes_anchor_and_source_digest():
    contexts = confirmed(count=2)
    original = resolve_confirmed_batch('owner', contexts)
    reverse = resolve_confirmed_batch('owner', list(reversed(contexts)))
    assert original['source_sha256'] != reverse['source_sha256']
    assert original['question_text'] != reverse['question_text']
    assert original['document']['graphs'][0]['edges'][0]['weight'] == 1
    assert reverse['document']['graphs'][0]['edges'][0]['weight'] == 2


def test_four_images_reach_one_ai_call_with_all_confirmed_edge_instances(application, monkeypatch):
    module, client, _ = application
    contexts = confirmed(browser_owner(client))
    captured = []
    def answer(messages, **options):
        captured.append((copy.deepcopy(messages), copy.deepcopy(options['teaching_context']['semantic_math'])))
        return {'ok': True, 'reply': '按图片1至4分别解答。'}
    monkeypatch.setattr(module, 'ask_ai', answer)
    for name in ('solve_certified_graph', 'answer_graph_isomorphism', 'protect_uncertain_graph_answer'):
        monkeypatch.setattr(module, name, lambda *a, **k: pytest.fail('Legacy graph parser used'))
    response = client.post('/chat', json=request_body(contexts))
    assert response.status_code == 200, response.get_json()
    assert len(captured) == 1
    semantic = captured[0][1]
    assert semantic['status'] == 'bound' and semantic['user_confirmed'] is True
    graphs = semantic['document']['graphs']
    assert len(graphs) == 4 and len({g['id'] for g in graphs}) == 4
    assert [g['edges'][0]['weight'] for g in graphs] == [1, 2, 3, 4]
    assert [g['vertices'][0]['display_label'] for g in graphs] == ['1'] * 4
    assert all(r['result']['status'] == 'computed' for r in semantic['calculations'])
    assert {r['request']['graph_id'] for r in semantic['calculations']} == {g['id'] for g in graphs}
    assert response.get_json()['diagnostics']['semantic_math']['revision'] == [1, 1, 1, 1]


@pytest.mark.parametrize('mutation', ['stale', 'changed', 'wrong_anchor', 'cross_browser', 'mixed'])
def test_invalid_batch_never_reaches_ai(application, monkeypatch, mutation):
    module, client, _ = application
    owner = browser_owner(client)
    contexts = confirmed(owner)
    payload = request_body(contexts)
    if mutation == 'stale':
        confirm_document(owner, {'document': document(9), 'confirmed': True,
            'request_id': 'image-task-4', 'source_sha256': '4' * 64})
    elif mutation == 'changed':
        payload['semantic_contexts'][1]['document']['graphs'][0]['edges'][0]['weight'] = 99
    elif mutation == 'wrong_anchor':
        payload['messages'][-1]['content'] = '请解另外一张图片。'
    elif mutation == 'cross_browser':
        client = module.app.test_client()
    else:
        payload['semantic_context'] = contexts[0]
    monkeypatch.setattr(module, 'ask_ai', lambda *a, **k: pytest.fail('Invalid batch reached AI'))
    response = client.post('/chat', json=payload)
    assert response.status_code in (400, 409), response.get_json()
    assert 'reply' not in response.get_json()


def test_edit_while_ai_is_working_discards_reply_for_any_stale_member(application, monkeypatch):
    module, client, _ = application
    owner = browser_owner(client)
    contexts = confirmed(owner)
    def answer(*args, **options):
        confirm_document(owner, {'document': document(9), 'confirmed': True,
            'request_id': 'image-task-2', 'source_sha256': '2' * 64})
        return {'ok': True, 'reply': '这条旧结构回复不应显示。'}
    monkeypatch.setattr(module, 'ask_ai', answer)
    response = client.post('/chat', json=request_body(contexts))
    assert response.status_code == 409
    assert response.get_json()['code'] == 'confirmation_stale'
    assert 'reply' not in response.get_json()


def test_followup_binds_to_same_ordered_batch(application, monkeypatch):
    module, client, _ = application
    contexts = confirmed(browser_owner(client), count=2)
    captured = []
    monkeypatch.setattr(module, 'ask_ai', lambda *a, **k: captured.append(k['teaching_context']['semantic_math'])
                        or {'ok': True, 'reply': '继续解释同一批图。'})
    payload = request_body(contexts, '请解释上一步计算，只给提示。')
    assert client.post('/chat', json=payload).status_code == 200
    assert len(captured) == 1 and len(captured[0]['document']['graphs']) == 2


def test_picture_qualified_path_uses_the_requested_source_graph_only():
    from graph_semantic_solver import semantic_solver_context
    contexts = confirmed(count=2)
    batch = resolve_confirmed_batch('owner', contexts)
    result = semantic_solver_context(batch, batch['question_text'] + '\n图片2的图1从1到2的最短路径。')
    paths = [row for row in result['calculations'] if row['request']['operation'] == 'shortest_path']
    assert len(paths) == 1 and paths[0]['request']['graph_id'] == 'image2_graph1'
    assert paths[0]['result']['facts']['distance'] == 2
    assert result['document']['graphs'][1]['source_image_number'] == 2
    assert result['document']['graphs'][1]['source_graph_number'] == 1


@pytest.mark.parametrize('question', ['图1从1到2的最短路径。', 'G1从1到2的最短路径。',
                                     '图片9的图1从1到2的最短路径。'])
def test_unqualified_or_missing_image_path_does_not_guess_source(question):
    from graph_semantic_solver import semantic_solver_context
    contexts = confirmed(count=2)
    batch = resolve_confirmed_batch('owner', contexts)
    result = semantic_solver_context(batch, batch['question_text'] + '\n' + question)
    assert not [row for row in result['calculations'] if row['request']['operation'] == 'shortest_path']


def test_three_graph_isomorphism_selects_independently_qualified_source_pair():
    from graph_semantic_solver import semantic_solver_context
    contexts = confirmed(count=2)
    value = document(2)
    extra = copy.deepcopy(value['graphs'][0])
    extra.update(id='G2', name='G2')
    value['graphs'].append(extra)
    current = confirm_document('owner', {'document': value, 'confirmed': True,
        'request_id': 'image-task-2', 'source_sha256': '2' * 64})
    contexts[1] = current['semantic_context']
    batch = resolve_confirmed_batch('owner', contexts)
    result = semantic_solver_context(batch, batch['question_text'] + '\n图片1的G1与图片2的G2是否同构？')
    pairs = [row['request'] for row in result['calculations'] if row['request']['operation'] == 'isomorphism']
    assert pairs == [{'operation': 'isomorphism', 'graph_id': 'image1_graph1', 'other_graph_id': 'image2_graph2'}]


def test_missing_image_is_not_replaced_with_only_available_image():
    from graph_semantic_solver import semantic_solver_context
    batch = resolve_confirmed_batch('owner', confirmed(count=1))
    result = semantic_solver_context(batch, batch['question_text'] + '\n图片2从1到2的最短路径。')
    assert not [row for row in result['calculations'] if row['request']['operation'] == 'shortest_path']


def test_combined_text_over_limit_is_rejected_without_truncation():
    contexts = []
    for index in range(1, 5):
        request_id, sha = 'long-' + str(index), str(index) * 64
        register_recognition('owner', request_id, sha)
        value = confirm_document('owner', {'document': {'body_text': '条件' * 3100, 'graphs': []},
            'confirmed': True, 'request_id': request_id, 'source_sha256': sha})
        contexts.append(value['semantic_context'])
    with pytest.raises(ConfirmationError) as failure:
        resolve_confirmed_batch('owner', contexts)
    assert failure.value.code == 'confirmation_batch_too_large'
