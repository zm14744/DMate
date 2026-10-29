"""Image observations and unnamed references survive the real confirmation path."""
import copy
import hashlib

import pytest

from graph_confirmation import COOKIE_NAME, register_recognition, validate_document
from graph_presentation import prepare_graph_presentation
from graph_schema import canonical_graph, display_graph
from graph_semantic_solver import semantic_solver_context, semantic_math_prompt
from test_ocr_application_contract import application
from test_semantic_chat_snapshot_frontend import run_js


def unnamed(identifier='G1', description='左侧四个顶点围成菱形，中间有一条水平连线。'):
    return {'id': identifier, 'name': identifier, 'directed': False, 'weighted': False,
            'visual_description': description,
            'vertices': [{'id': 'top', 'label': None, 'x': .5, 'y': .1, 'position_description': '菱形最上方'},
                         {'id': 'left', 'label': None, 'x': .1, 'y': .5},
                         {'id': 'right', 'label': None, 'x': .9, 'y': .5},
                         {'id': 'bottom', 'label': None, 'x': .5, 'y': .9}],
            'edges': [{'id': str(i), 'from': a, 'to': b, 'direction': 'undirected'}
                      for i, (a, b) in enumerate([('top', 'left'), ('top', 'right'),
                                                ('left', 'right'), ('left', 'bottom'), ('right', 'bottom')])]}


def test_references_survive_reorder_without_becoming_original_names_or_changing_edges():
    graph = unnamed()
    before = copy.deepcopy(graph['edges'])
    prepare_graph_presentation(graph)
    references = {v['id']: v['display_label'] for v in graph['vertices']}
    graph['vertices'].reverse()
    prepare_graph_presentation(graph)
    assert {v['id']: v['display_label'] for v in graph['vertices']} == references
    assert all(v['label'] is None for v in graph['vertices'])
    assert graph['edges'] == before
    assert next(v for v in graph['vertices'] if v['id'] == 'top')['position_description'] == '菱形最上方'
    assert all(v['position_description'] for v in graph['vertices'])


def test_reference_assignment_avoids_printed_and_existing_number_collisions():
    graph = unnamed()
    graph['vertices'][0]['label'] = '①'
    graph['vertices'][1]['display_label'] = '①'
    graph['vertices'][2]['display_label'] = '⑤'
    graph['vertices'][3]['display_label'] = '⑤'
    prepare_graph_presentation(graph)
    names = [v.get('label') or v.get('display_label') for v in graph['vertices']]
    assert len(set(names)) == 4
    assert graph['vertices'][2]['display_label'] == '⑤'
    assert graph['vertices'][0]['label'] == '①'


def test_anonymous_references_are_consistent_in_canonical_public_and_semantic_documents():
    graph = unnamed()
    public = display_graph(canonical_graph(graph))
    document, _ = validate_document({'body_text': '判断两幅图是否同构。', 'graphs': [graph]})
    confirmed = document['graphs'][0]
    assert confirmed['visual_description'] == graph['visual_description']
    assert [(v['id'], v['label'], v['display_label'], v['position_description']) for v in public['vertices']] == [
        (v['id'], v['label'], v['display_label'], v['position_description']) for v in confirmed['vertices']]
    assert all('x' not in v and 'y' not in v for v in confirmed['vertices'])


@pytest.mark.parametrize('field,value', [('visual_description', 'x' * 801), ('position_description', 'x' * 161),
                                         ('display_label', 'x' * 17)])
def test_confirmation_rejects_oversized_observations(field, value):
    from graph_confirmation import ConfirmationError
    graph = unnamed()
    target = graph if field == 'visual_description' else graph['vertices'][0]
    target[field] = value
    with pytest.raises(ConfirmationError):
        validate_document({'body_text': '', 'graphs': [graph]})


def test_actual_confirmation_browser_storage_and_chat_keep_same_references(application, monkeypatch, tmp_path):
    module, client, _ = application
    monkeypatch.setenv('DMATE_GRAPH_CONFIRMATION_DB', str(tmp_path / 'refs.sqlite3'))
    client.get('/graph/session')
    owner = hashlib.sha256((client.get_cookie(COOKIE_NAME).value + ':guest').encode()).hexdigest()
    register_recognition(owner, 'unnamed-picture', 'b' * 64)
    original = {'body_text': '判断两幅图是否同构。', 'graphs': [unnamed(), unnamed('G2', '右侧顶点呈不同的布局，但保持同一份边记录。')]}
    response = client.post('/graph/confirm', json={'document': original, 'confirmed': True,
        'request_id': 'unnamed-picture', 'source_sha256': 'b' * 64})
    assert response.status_code == 200, response.get_json()
    saved = response.get_json()
    context = run_js({'operation': 'sanitize', 'context': saved['semantic_context']})
    # Keeping fields through browser storage is necessary for the signed digest.
    assert context['document'] == saved['semantic_context']['document']
    assert '不是原图标签' in context['question_text']
    assert original['graphs'][0]['visual_description'] in context['question_text']
    captured = []
    def answer(messages, **options):
        captured.append(options['teaching_context']['semantic_math'])
        return {'ok': True, 'reply': '依据已确认边表进行核对。'}
    monkeypatch.setattr(module, 'ask_ai', answer)
    result = client.post('/chat', json={'messages': [{'role': 'user', 'content': context['question_text']}],
        'semantic_context': context, 'request_kind': 'solution'})
    assert result.status_code == 200, result.get_json()
    expected = copy.deepcopy(saved['document'])
    for graph in expected['graphs']:
        graph.pop('anon_next', None)  # Only the editor needs the next-number counter.
    assert captured[0]['document'] == expected
    calculation = next(c for c in captured[0]['calculations'] if c['request']['operation'] == 'isomorphism')
    assert calculation['result']['facts']['isomorphic'] is True
    prompt = semantic_math_prompt(captured[0])
    assert '两图同号不代表同一顶点' in prompt
    assert '不是拓扑证明' in prompt


def snapshot(graphs, body='求最短路径。'):
    for graph in graphs:
        graph['complete'] = True
        prepare_graph_presentation(graph)
        for edge in graph['edges']:
            edge['status'] = 'accepted'
    return {'document': {'body_text': body, 'graphs': graphs}, 'source_sha256': 'a' * 64,
            'question_text': body, 'rendered_question_text': body}


def test_explicit_temporary_endpoint_request_only_runs_for_named_graph():
    data = snapshot([unnamed(), unnamed('G2')])
    result = semantic_solver_context(data, data['question_text'] + '\n图1：从①到②的最短路径。')
    paths = [r for r in result['calculations'] if r['request']['operation'] == 'shortest_path']
    assert len(paths) == 1 and paths[0]['request']['graph_id'] == 'G1'
    assert paths[0]['result']['status'] == 'computed'


def test_ambiguous_temporary_endpoint_request_does_not_guess_which_graph():
    data = snapshot([unnamed(), unnamed('G2')])
    result = semantic_solver_context(data, data['question_text'] + '\n从①到②的最短路径。')
    assert not result['calculations']


def test_isomorphism_request_requires_a_unique_pair_when_more_than_two_figures():
    data = snapshot([unnamed(), unnamed('G2'), unnamed('G3')], body='判断下列图是否同构。')
    assert not semantic_solver_context(data, data['question_text'])['calculations']
    result = semantic_solver_context(data, data['question_text'] + '\n判断图1与图3是否同构。')
    assert len(result['calculations']) == 1
    assert result['calculations'][0]['request'] == {'operation': 'isomorphism', 'graph_id': 'G1', 'other_graph_id': 'G3'}


def test_explicitly_missing_graph_is_not_substituted_with_only_available_graph():
    data = snapshot([unnamed()])
    result = semantic_solver_context(data, data['question_text'] + '\n图2从①到②的最短路径。')
    assert not result['calculations']


def test_current_request_can_defer_original_isomorphism_question():
    data = snapshot([unnamed(), unnamed('G2')], body='判断这两个图是否同构。')
    result = semantic_solver_context(data, data['question_text'] + '\n【我的要求】不要判断同构，只描述外观。')
    assert not result['calculations']


def test_independent_public_projection_detects_changed_appearance_or_reference():
    from scripts.verify_graph_first_pass_ui import public_projection_issues
    graph = canonical_graph(unnamed())
    prediction = {'graph_structures': [graph], 'graph_display_data': [display_graph(graph)]}
    assert not public_projection_issues(prediction)
    prediction['graph_display_data'][0]['visual_description'] = '被替换的画法'
    assert public_projection_issues(prediction) == ['canonical_public_projection_changed']
    prediction['graph_display_data'] = [display_graph(graph)]
    prediction['graph_display_data'][0]['vertices'][0]['display_label'] = '错误编号'
    assert public_projection_issues(prediction) == ['canonical_public_projection_changed']
