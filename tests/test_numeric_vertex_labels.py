"""Automatic numeric references stay separate from original labels and signatures."""
import copy

from graph_confirmation import (
    confirm_document, document_digest, register_recognition, resolve_confirmed_context,
)
from graph_presentation import prepare_graph_presentation
from graph_semantic_solver import _path_endpoints
from test_drawing_editor_controls import drawing_page
from test_semantic_chat_snapshot_frontend import run_js


def legacy_graph():
    return {'id': 'G1', 'name': '图', 'directed': False, 'weighted': False,
            'anon_next': 3,
            'vertices': [{'id': 'a', 'label': None, 'display_label': '①', 'x': .2, 'y': .3},
                         {'id': 'b', 'label': '1', 'x': .8, 'y': .3},
                         {'id': 'c', 'label': None, 'display_label': '②', 'x': .5, 'y': .8}],
            'edges': [{'id': 'e1', 'from': 'a', 'to': 'b', 'direction': 'undirected'},
                      {'id': 'e2', 'from': 'c', 'to': 'b', 'direction': 'undirected'}]}


def test_legacy_display_references_migrate_around_printed_numbers_without_changing_topology():
    graph = legacy_graph()
    edges = copy.deepcopy(graph['edges'])
    prepare_graph_presentation(graph)
    assert [v.get('display_label') for v in graph['vertices']] == ['3', None, '2']
    assert [v['label'] for v in graph['vertices']] == [None, '1', None]
    assert graph['edges'] == edges
    first = copy.deepcopy(graph)
    prepare_graph_presentation(graph)
    assert graph == first


def test_unsigned_legacy_confirmation_uses_same_numeric_references_in_signed_and_drawing_documents(monkeypatch, tmp_path):
    monkeypatch.setenv('DMATE_GRAPH_CONFIRMATION_DB', str(tmp_path / 'confirm.sqlite3'))
    original = {'body_text': '检查连接。', 'graphs': [legacy_graph()]}
    before = copy.deepcopy(original)
    register_recognition('owner', 'numeric-confirm', 'a' * 64)
    saved = confirm_document('owner', {'document': original, 'request_id': 'numeric-confirm',
                             'source_sha256': 'a' * 64, 'confirmed': True})
    assert original == before
    semantic = saved['semantic_context']['document']['graphs'][0]
    drawing = saved['drawing_document']['graphs'][0]
    assert [(v['id'], v['label'], v.get('display_label')) for v in semantic['vertices']] == [
        (v['id'], v['label'], v.get('display_label')) for v in drawing['vertices']]
    assert drawing['vertices'][0]['x'] == .2 and drawing['vertices'][0]['y'] == .3
    assert drawing['anon_next'] == semantic['anon_next']
    assert resolve_confirmed_context('owner', saved['semantic_context']) == saved['semantic_context']


def test_old_signed_snapshot_keeps_digest_and_both_old_and_visible_plain_endpoint_references(monkeypatch, tmp_path):
    monkeypatch.setenv('DMATE_GRAPH_CONFIRMATION_DB', str(tmp_path / 'legacy.sqlite3'))
    register_recognition('owner', 'legacy-confirm', 'b' * 64)
    # Issue a snapshot with the previous presentation behavior. It represents
    # an already stored signature, rather than a fresh document to migrate.
    with monkeypatch.context() as previous:
        previous.setattr('graph_presentation.prepare_graph_presentation', lambda graph: graph)
        saved = confirm_document('owner', {'document': {'body_text': '求最短路径。', 'graphs': [legacy_graph()]},
                'request_id': 'legacy-confirm', 'source_sha256': 'b' * 64, 'confirmed': True})
    context = copy.deepcopy(saved['semantic_context'])
    before = copy.deepcopy(context)
    assert run_js({'operation': 'sanitize', 'context': context}) == before
    digest = document_digest(context['document'])
    assert resolve_confirmed_context('owner', context) == before
    graph = context['document']['graphs'][0]
    assert _path_endpoints('从3到1的最短路径', graph) == ('a', 'b')
    assert _path_endpoints('从①到1的最短路径', graph) == ('a', 'b')
    assert _path_endpoints('从2到1的最短路径', graph) == ('c', 'b')
    assert context == before and document_digest(context['document']) == digest


def test_drawing_new_points_are_plain_numbers_and_property_close_has_no_text(drawing_page):
    page = drawing_page
    page.evaluate("editor.model.addVertex('G1','',.45,.25);editor.model.addVertex('G1','',.55,.75)")
    page.get_by_role('button', name='选择 / 移动', exact=True).click()
    graph = page.evaluate('editor.getDocument().graphs[0]')
    automatic = graph['vertices'][-2:]
    assert [v['label'] for v in automatic] == [None, None]
    assert [v['display_label'] for v in automatic] == ['1', '2']
    page.locator('[data-vertex-id="' + automatic[0]['id'] + '"] .dge-overlay-node-hit').click()
    assert page.get_by_label('当前顶点名称', exact=True).input_value() == '1'
    assert '临时编号' not in page.locator('.dge-selection-panel').inner_text()
    close = page.get_by_role('button', name='关闭属性', exact=True)
    assert close.text_content() == ''
    close.click()
    assert page.locator('.dge-selection-panel').count() == 0
