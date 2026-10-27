"""Final pixel checks resolve only their own earlier pending fields, offline."""
import copy

import pytest

from graph_semantic_pipeline import _resolve_focused_issues
from test_graph_semantic_pipeline import (
    Reader, direction_response, document, install_semantic_worker_fixtures, run,
)
from vision_provider import VisionError, VisionProvider


@pytest.fixture(autouse=True)
def offline_workers(monkeypatch, tmp_path):
    install_semantic_worker_fixtures(monkeypatch, lock_root=tmp_path)
    monkeypatch.setattr(VisionProvider, 'available', lambda self: False)


def two_panels():
    value = document()
    value['graphs'].append({'id': 'G2', 'name': '(b)', 'directed': False,
        'vertices': [{'id': 'a', 'label': 'a'}, {'id': 'b', 'label': 'b'}],
        'edges': [{'from': 'a', 'to': 'b', 'direction': 'undirected'}]})
    return value


def disputed(field='body_text', *, edge_ids=None):
    row = {'scope': 'body' if field == 'body_text' else 'graph',
           'field': field, 'message': '仅指定字段需要复核'}
    if row['scope'] == 'graph':
        row['graph_id'] = 'G1'
    if edge_ids is not None:
        row['edge_ids'] = edge_ids
    return row


def pending_reader(issues, **outputs):
    return Reader({'semantic_review': {'issues': issues},
                   'semantic_repair': VisionError('invalid_output'), **outputs},
                  source_document=two_panels())


def test_successful_body_check_retires_failed_body_repair_and_verifier_finding():
    result = run(pending_reader([disputed()]))
    assert result['complete'] and result['body_complete']
    assert result['semantic_workflow']['literal_body_checked'] is True
    assert result['semantic_issues'] == []
    resolved = result['semantic_workflow']['focused_resolution_audit']
    assert {row['origin'] for row in resolved} == {'errors', 'verification_issues'}
    assert all(row['scope'] == 'body' and row['field'] == 'body_text' for row in resolved)
    # Historical failure events remain visible even though pending work cleared.
    assert any(row.get('error_kind') == 'invalid_output'
               for row in result['semantic_workflow']['roles'])


@pytest.mark.parametrize('empty_text', ['', ' \n\t'])
@pytest.mark.parametrize('prior_dispute', [False, True])
def test_empty_final_body_keeps_previously_read_text_pending_beside_valid_graphs(
        empty_text, prior_dispute):
    output = {'body_text': empty_text, 'uncertainties': []}
    reader = (pending_reader([disputed()], semantic_body=output) if prior_dispute
              else Reader({'semantic_body': output}, source_document=two_panels()))
    result = run(reader)
    assert result['body_text'] == two_panels()['body_text']
    assert not result['body_complete'] and not result['complete']
    assert all(graph['complete'] for graph in result['graphs'])
    assert result['semantic_workflow']['literal_body_checked'] is False
    assert result['semantic_workflow']['focused_resolution_audit'] == []
    assert any(issue.get('kind') == 'literal_body_removed_all_content'
               for issue in result['semantic_issues'])
    if prior_dispute:
        assert any(issue.get('kind') == 'visual_review_conflict'
                   for issue in result['semantic_issues'])


def test_consistently_empty_body_on_a_graph_only_page_remains_valid():
    whole = two_panels()
    whole['body_text'] = ''
    reader = Reader(source_document=whole)
    result = run(reader)
    assert result['body_text'] == '' and result['body_complete'] and result['complete']
    assert any(request['role'] == 'semantic_body' for request in reader.requests)
    assert result['semantic_workflow']['literal_body_checked'] is True


@pytest.mark.parametrize('final_reading', [
    {'body_text': '', 'uncertainties': []}, VisionError('invalid_output'),
])
def test_empty_repair_then_empty_or_failed_final_read_keeps_earlier_body_pending(final_reading):
    repaired = two_panels()
    repaired['body_text'] = ''
    reader = Reader({'semantic_review': {'issues': [disputed()]},
        'semantic_repair': repaired, 'semantic_body': final_reading},
        source_document=two_panels())
    result = run(reader)
    assert result['body_text'] == two_panels()['body_text']
    assert not result['body_complete'] and not result['complete']
    assert all(graph['complete'] for graph in result['graphs'])
    assert result['semantic_workflow']['focused_resolution_audit'] == []
    assert result['semantic_workflow']['literal_body_checked'] is False
    assert any(issue['scope'] == 'body' for issue in result['semantic_issues'])


def test_empty_final_read_preserves_latest_accepted_repair_text_exactly():
    repaired = two_panels()
    repaired['body_text'] = '（1）求 v₅ 的入度；\n（2）判断图 (b) 是否连通。'
    reader = Reader({'semantic_review': {'issues': [disputed()]},
        'semantic_repair': repaired,
        'semantic_body': {'body_text': '', 'uncertainties': []}},
        source_document=two_panels())
    result = run(reader)
    assert result['body_text'] == repaired['body_text']
    assert not result['body_complete'] and all(graph['complete'] for graph in result['graphs'])


def test_prior_upload_body_snapshot_cannot_populate_next_graph_only_upload():
    repaired = two_panels()
    repaired['body_text'] = ''
    first = run(Reader({'semantic_review': {'issues': [disputed()]},
        'semantic_repair': repaired, 'semantic_body': {'body_text': '', 'uncertainties': []}},
        source_document=two_panels()))
    assert first['body_text'] == two_panels()['body_text'] and not first['body_complete']
    second = run(Reader(source_document=repaired))
    assert second['body_text'] == '' and second['body_complete'] and second['complete']


@pytest.mark.parametrize('edge_ids', [None, ['source_edge_1']])
def test_confirmed_directions_retire_only_direction_repair_failures(edge_ids):
    result = run(pending_reader([disputed('direction', edge_ids=edge_ids)]))
    assert result['complete'] and result['body_complete']
    assert result['semantic_issues'] == []
    resolved = result['semantic_workflow']['focused_resolution_audit']
    assert len(resolved) == 2
    assert all(row['graph_id'] == 'G1' and row['field'] == 'direction' for row in resolved)


def test_body_success_does_not_resolve_other_panel_topology():
    result = run(pending_reader([disputed(), disputed('edges')]))
    assert result['body_complete']
    assert not result['graphs'][0]['complete']
    assert result['graphs'][1]['complete']
    assert result['semantic_issues']
    assert all(row['scope'] == 'graph' for row in result['semantic_issues'])


def test_direction_success_does_not_resolve_weight_or_combined_repair_failure():
    result = run(pending_reader([disputed('direction'), disputed('weight')]))
    assert result['body_complete'] and result['graphs'][1]['complete']
    assert not result['graphs'][0]['complete']
    assert not any(row.get('field') == 'direction' for row in result['semantic_issues'])
    assert any(row.get('field') == 'weight' for row in result['semantic_issues'])
    assert any(row.get('kind') == 'invalid_output' for row in result['semantic_issues'])


def test_new_body_uncertainty_prevents_retiring_old_body_finding():
    result = run(pending_reader([disputed()], semantic_body={
        'body_text': '原图中可读残句',
        'uncertainties': [{'scope': 'body', 'message': '句末仍被裁切'}]}))
    assert not result['body_complete']
    assert all(graph['complete'] for graph in result['graphs'])
    assert any(row.get('kind') == 'visual_review_conflict' for row in result['semantic_issues'])
    assert result['semantic_workflow']['focused_resolution_audit'] == []


@pytest.mark.parametrize('uncertainties', [None, {}, [None], [''],
    [{'scope': 'graph', 'message': '不是正文范围'}], [{'message': ''}]])
def test_malformed_body_uncertainty_cannot_clear_pending_body(uncertainties):
    result = run(pending_reader([disputed()], semantic_body={
        'body_text': '声称已经清楚的正文', 'uncertainties': uncertainties}))
    assert not result['body_complete']
    assert result['semantic_workflow']['literal_body_checked'] is False
    assert result['body_text'] == two_panels()['body_text']
    assert all(graph['complete'] for graph in result['graphs'])
    assert result['semantic_workflow']['focused_resolution_audit'] == []


def test_failed_direction_check_keeps_body_and_undirected_panel_complete():
    result = run(Reader({'semantic_directions': VisionError('invalid_output')},
                        source_document=two_panels()))
    assert result['body_complete']
    assert not result['graphs'][0]['complete'] and result['graphs'][1]['complete']
    failures = result['semantic_issues']
    assert len(failures) == 1
    assert failures[0]['scope'] == 'graph' and failures[0]['graph_id'] == 'G1'
    assert failures[0]['field'] == 'direction'
    assert failures[0]['edge_ids'] == ['source_edge_1', 'source_edge_2', 'source_edge_3']


@pytest.mark.parametrize('uncertain', ['unknown', 'conflicting_uncertainty', 'omitted'])
def test_unconfirmed_direction_instance_keeps_its_prior_issue(uncertain):
    def directions(request):
        response = direction_response(request['task'], two_panels())
        first = response['graphs'][0]['edges'][0]
        if uncertain == 'unknown':
            response['graphs'][0]['edges'][0] = {'id': first['id'], 'direction': 'unknown'}
        elif uncertain == 'omitted':
            response['graphs'][0]['edges'].pop(0)
        else:
            response['uncertainties'] = [{'graph_id': 'G1', 'edge_ids': [first['id']],
                                          'message': '同一实例仍未确认'}]
        return response
    result = run(pending_reader([disputed('direction', edge_ids=['source_edge_1'])],
                                semantic_directions=directions))
    assert result['body_complete'] and result['graphs'][1]['complete']
    assert not result['graphs'][0]['complete']
    assert any(row.get('kind') == 'visual_review_conflict' for row in result['semantic_issues'])
    assert result['semantic_workflow']['focused_resolution_audit'] == []


def test_partial_direction_confirmation_does_not_clear_graph_wide_claim():
    def directions(request):
        response = direction_response(request['task'], two_panels())
        response['graphs'][0]['edges'].pop()
        return response
    result = run(pending_reader([disputed('direction')], semantic_directions=directions))
    assert not result['graphs'][0]['complete']
    assert any(row.get('kind') == 'visual_review_conflict' for row in result['semantic_issues'])
    assert result['semantic_workflow']['focused_resolution_audit'] == []


def test_confirming_one_field_does_not_clear_unknown_scope_or_foreign_edge():
    rows = [
        {'scope': 'document', 'field': 'direction'},
        {'scope': 'graph', 'graph_id': 'G1', 'field': 'edges'},
        {'scope': 'graph', 'graph_id': 'G1', 'message': '未定位的图问题'},
        {'scope': 'graph', 'graph_id': 'G2', 'field': 'direction', 'edge_ids': ['e1']},
        {'scope': 'graph', 'graph_id': 'G1', 'field': 'direction', 'edge_ids': ['foreign']},
        {'scope': 'graph', 'graph_id': 'G1', 'field': 'direction', 'edge_ids': 'e1'},
        {'scope': 'graph', 'graph_id': [], 'field': 'direction'},
        {'scope': 'body', 'field': 'weight'},
    ]
    before = copy.deepcopy(rows)
    audit = []
    assert _resolve_focused_issues(rows, origin='test', audit=audit,
        body_confirmed=True, confirmed_directions={'G1': {'e1'}},
        whole_direction_graphs={'G1'}) == before
    assert rows == before and audit == []


def test_mixed_graph_direction_check_does_not_certify_unrequested_undirected_edges():
    whole = two_panels()
    whole['graphs'][0]['edges'].append({'from': 'b', 'to': 'c', 'direction': 'undirected'})
    reader = Reader({'semantic_review': {'issues': [disputed('direction')]},
        'semantic_repair': VisionError('invalid_output')}, source_document=whole)
    result = run(reader)
    assert not result['graphs'][0]['complete']
    assert result['body_complete'] and result['graphs'][1]['complete']
    assert any(row.get('kind') == 'visual_review_conflict' for row in result['semantic_issues'])
