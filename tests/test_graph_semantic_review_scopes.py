import copy

import pytest

from graph_semantic_pipeline import _scope_repair, _verification_issues


def document():
    return {'body_text': '原始题干', 'graphs': [
        {'id': 'G1', 'name': '(a)', 'vertices': [{'id': 'a'}, {'id': 'b'}],
         'edges': [{'id': 'e1', 'from': 'a', 'to': 'b', 'direction': 'forward', 'weight': 3},
                   {'id': 'e2', 'from': 'a', 'to': 'b', 'direction': 'forward', 'weight': 5}]},
        {'id': 'G2', 'name': '(b)', 'vertices': [{'id': 'v'}], 'edges': []}], 'uncertainties': []}


def test_readonly_verifier_never_supplies_document_replacement():
    original = document()
    response = {'issues': [], 'graphs': []}
    assert _verification_issues(response, original) == []
    assert original == document()
    with pytest.raises(ValueError, match='unreadable'):
        _verification_issues(document(), original)


def test_confirmed_and_withdrawn_observations_do_not_schedule_repairs():
    response = {'issues': [
        {'verdict': 'confirmed', 'scope': 'graph', 'graph_id': 'G1', 'field': 'edges', 'message': '无误'},
        {'verdict': 'withdrawn', 'scope': 'document', 'message': '复看后无有效差异'},
        {'verdict': 'change_required', 'scope': 'graph', 'graph_id': 'G1', 'field': 'weight',
         'edge_ids': ['e1'], 'message': '此边印刷权值需要重读'}]}
    result = _verification_issues(response, document())
    assert len(result) == 1 and result[0]['edge_ids'] == ['e1']


def test_nonempty_review_without_explicit_verdict_is_not_silently_actionable():
    with pytest.raises(ValueError, match='verdict'):
        _verification_issues({'issues': [
            {'scope': 'graph', 'graph_id': 'G1', 'field': 'edges', 'message': '无有效差异'}]}, document())


def test_edge_repair_preserves_isolated_vertices_labels_and_panel_name():
    old = document()
    old['graphs'][0]['vertices'].append({'id': 'isolated', 'label': 'V₅'})
    new = copy.deepcopy(old)
    new['graphs'][0]['vertices'] = [{'id': 'a', 'label': 'wrong'}, {'id': 'b'}]
    new['graphs'][0]['name'] = 'Wrong panel'
    new['graphs'][0]['edges'].pop()
    result, audit = _scope_repair(old, new, [
        {'scope': 'graph', 'graph_id': 'G1', 'field': 'edges', 'source_ids': ['a']}])
    assert result['graphs'][0]['vertices'] == old['graphs'][0]['vertices']
    assert result['graphs'][0]['name'] == old['graphs'][0]['name']
    assert result['graphs'][0]['edges'] == new['graphs'][0]['edges']
    assert audit['field_permissions'][0]['mode'] == 'edges_only'


def test_edge_repair_cannot_invent_an_unreported_node():
    old = document()
    new = copy.deepcopy(old)
    new['graphs'][0]['vertices'].append({'id': 'new'})
    new['graphs'][0]['edges'].append({'id': 'new_edge', 'from': 'a', 'to': 'new'})
    result, audit = _scope_repair(old, new, [
        {'scope': 'graph', 'graph_id': 'G1', 'field': 'edges'}])
    assert result['graphs'] == old['graphs']
    assert result['uncertainties']
    assert audit['field_permissions'][0]['unresolved_graph'] is True


def test_source_endpoint_disagreement_does_not_grant_node_replacement():
    old = document()
    old['graphs'][0]['vertices'].append({'id': 'isolated'})
    new = copy.deepcopy(old)
    new['graphs'][0]['vertices'].pop()
    new['graphs'][0]['edges'].pop()
    result, audit = _scope_repair(old, new, [
        {'scope': 'graph', 'graph_id': 'G1', 'kind': 'undirected_instance_mismatch',
         'message': '两端读取的实例数不一致'},
        {'scope': 'graph', 'graph_id': 'G1', 'field': 'edges', 'source_ids': ['a']}])
    assert result['graphs'][0]['vertices'] == old['graphs'][0]['vertices']
    assert result['graphs'][0]['edges'] == new['graphs'][0]['edges']
    assert audit['field_permissions'][0]['mode'] == 'edges_only'


def test_scoped_attribute_changes_only_named_field_on_named_edge():
    old = document()
    new = copy.deepcopy(old)
    new['body_text'] = '不应被换掉的题干'
    new['graphs'][0]['vertices'].append({'id': 'fake'})
    new['graphs'][0]['edges'][0].update(weight=7, color='red', **{'from': 'b', 'to': 'a'})
    new['graphs'][0]['edges'][1]['weight'] = 99
    new['graphs'][1]['edges'].append({'from': 'v', 'to': 'v'})
    result, audit = _scope_repair(old, new, [
        {'scope': 'graph', 'graph_id': 'G1', 'field': 'weight', 'edge_ids': ['e1']}])
    expected = document()
    expected['graphs'][0]['edges'][0]['weight'] = 7
    assert result == expected
    assert audit['field_permissions'][0]['mode'] == 'edge_fields'


def test_direction_scope_cannot_reconnect_an_edge():
    old = document()
    new = copy.deepcopy(old)
    new['graphs'][0]['edges'][0]['to'] = 'a'
    result, audit = _scope_repair(old, new, [
        {'scope': 'graph', 'graph_id': 'G1', 'field': 'direction', 'edge_ids': ['e1']}])
    assert result['graphs'] == old['graphs']
    assert result['uncertainties'][0]['edge_id'] == 'e1'
    assert audit['field_permissions'][0]['unresolved_edge_ids'] == ['e1']


def test_structure_repair_keeps_other_panels_and_body_byte_identical():
    old = document()
    new = copy.deepcopy(old)
    new['body_text'] = 'wrong'
    new['graphs'][0]['edges'].append({'id': 'e3', 'from': 'b', 'to': 'b', 'direction': 'forward'})
    new['graphs'][1]['vertices'] = []
    result, audit = _scope_repair(old, new, [
        {'scope': 'graph', 'graph_id': 'G1', 'field': 'edges', 'source_ids': ['b']}])
    assert result['graphs'][0]['edges'] == new['graphs'][0]['edges']
    assert result['graphs'][1] == old['graphs'][1]
    assert result['body_text'] == old['body_text']
    assert audit['retained_graph_ids'] == ['G2']


def test_missing_target_does_not_delete_panel_or_falsely_clear_issue():
    old = document()
    new = copy.deepcopy(old)
    new['graphs'] = new['graphs'][1:]
    result, audit = _scope_repair(old, new, [{'scope': 'graph', 'graph_id': 'G1', 'field': 'edges'}])
    assert result['graphs'] == old['graphs']
    assert result['uncertainties'][0]['graph_id'] == 'G1'
    assert audit['missing_graph_ids'] == ['G1']


def test_bad_review_scope_cannot_grant_unknown_graph_permission():
    with pytest.raises(ValueError, match='unknown_graph'):
        _verification_issues({'issues': [
            {'scope': 'graph', 'graph_id': 'other', 'message': '错误'}]}, document())


def test_direction_issue_without_edge_ids_still_cannot_change_structure_or_weights():
    old = document()
    new = copy.deepcopy(old)
    new['graphs'][0]['vertices'].append({'id': 'fake'})
    new['graphs'][0]['edges'][0].update({'from': 'b', 'to': 'a', 'weight': 900})
    new['graphs'][0]['edges'].append({'id': 'new', 'from': 'fake', 'to': 'a'})
    result, audit = _scope_repair(old, new, [
        {'scope': 'graph', 'graph_id': 'G1', 'field': 'direction'}])
    expected = document()
    expected['graphs'][0]['edges'][0].update({'from': 'b', 'to': 'a'})
    assert result == expected
    assert audit['field_permissions'][0]['mode'] == 'edge_fields'


def test_unknown_attribute_never_expands_permission_to_whole_panel():
    old = document()
    new = copy.deepcopy(old)
    new['graphs'][0]['edges'] = []
    result, audit = _scope_repair(old, new, [
        {'scope': 'graph', 'graph_id': 'G1', 'field': 'unsupported'}])
    assert result['graphs'] == old['graphs']
    assert result['uncertainties'] and audit['field_permissions'][0]['unresolved_graph']


def test_repair_clearing_body_cannot_skip_last_literal_read_when_small_is_unavailable(monkeypatch, tmp_path):
    from test_graph_semantic_pipeline import Reader, document as full_document, run, install_semantic_worker_fixtures
    from vision_provider import VisionProvider
    import graph_semantic_text
    install_semantic_worker_fixtures(monkeypatch, lock_root=tmp_path)
    monkeypatch.setattr(VisionProvider, 'available', lambda self: False)
    monkeypatch.setattr(graph_semantic_text, '_cache_readiness', lambda: {
        'status': 'dependency_unavailable', 'worker_started': False})
    empty_body = full_document()
    empty_body['body_text'] = ''
    reader = Reader({'semantic_review': {'issues': [
        {'scope': 'body', 'field': 'body_text', 'message': '题干末句需要重读'}]},
        'semantic_repair': empty_body})
    result = run(reader)
    assert any(request['role'] == 'semantic_body' for request in reader.requests)
    assert result['body_text'] == full_document()['body_text']
    assert result['semantic_workflow']['literal_body_checked'] is True
