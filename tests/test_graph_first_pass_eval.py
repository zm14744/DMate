"""Adversarial acceptance cases: equal counts must not conceal wrong graphs."""
from copy import deepcopy
import json

import pytest

from graph_first_pass_eval import CURRENT_PIPELINE_VERSION, FRONTEND_CHECKS, evaluate_prediction, load_annotations, prediction_digest, reference_issues
from scripts.benchmark_graph_first_pass import digest, main, same_source, validate_base_url


def reference():
    return {'id': 'original_1', 'sha256': 'a'*64, 'width': 1000, 'height': 600,
            'question_text': '求最短路', 'question_text_complete': True,
            'graphs': [{'id': 'gold', 'name': 'G', 'bbox': [.05, .05, .95, .95],
                        'annotation_complete': True, 'directed': True, 'weighted': True,
                        'vertices': [{'id': 'a', 'label': 'a', 'x': .1, 'y': .1},
                                     {'id': 'b', 'label': 'b', 'x': .9, 'y': .1},
                                     {'id': 'c', 'label': 'c', 'x': .9, 'y': .9},
                                     {'id': 'd', 'label': 'd', 'x': .1, 'y': .9}],
                        'edges': [{'id': 'ga', 'from': 'a', 'to': 'b', 'direction': 'forward', 'weight': 2, 'label': 'e1', 'style': 'solid'},
                                  {'id': 'gb', 'from': 'b', 'to': 'c', 'direction': 'forward', 'weight': 3, 'label': None, 'style': 'dashed'},
                                  {'id': 'gc', 'from': 'c', 'to': 'd', 'direction': 'forward', 'weight': 4, 'label': None, 'style': 'solid'}]}]}


def prediction(gold=None):
    gold = gold or reference()
    graphs = deepcopy(gold['graphs'])
    for graph in graphs:
        graph.update(schema_version='dmate.graph/1', complete=True, multigraph=False, node_complete=True)
        graph.pop('annotation_complete', None)
        for edge in graph['edges']:
            edge['edge_label'] = edge.pop('label', edge.get('edge_label'))
            edge.update(multiplicity=1, status='accepted')
    return {'graph_structures': graphs, 'text': gold.get('question_text', ''),
            'graph_display_version': CURRENT_PIPELINE_VERSION,
            'recognition_status': 'complete', 'review': {'required': False},
            'diagnostics': {'correction': {'status': 'ok'},
                            'text_evidence': {'source': 'original_visual_transcription',
                                             'complete': True, 'visual_body_complete': True,
                                             'second_pass_reviewed': True,
                                             'reconciliation': {'issues': [], 'second_pass_reviewed': True}}}}


def live():
    # These are synthetic ledger records for comparator unit tests only.
    # The real runner obtains send identities/hashes from PreparedRequest bytes.
    execution = 'synthetic-evaluation-unit'
    metrics, transports = [], []
    for number in (1, 2):
        common = {'provider': 'qwen', 'model': 'qwen3-vl-plus', 'logical_call': number,
                  'attempt': 1, 'execution_id': execution, 'http_status': 200,
                  'transport_id': execution+':send:'+str(number),
                  'prompt_sha256': str(number)*64, 'image_sha256': ['d'*64, 'e'*64]}
        metrics.append({**common, 'started_at_unix': 1792990800+number,
                        'status': 200, 'finish_reason': 'stop', 'returned_model': 'qwen3-vl-plus', 'seconds': .8})
        transports.append({**common, 'started_at_unix': 1792990800+number+.1,
                           'method': 'POST', 'host': 'example.test', 'request_body_sha256': str(number+2)*64})
    text_common = {'provider': 'text', 'model': 'deepseek-flash', 'logical_call': 1,
                   'attempt': 1, 'execution_id': execution, 'http_status': 200,
                   'transport_id': execution+':send:3'}
    text = {**text_common, 'started_at_unix': 1792990803, 'status': 200, 'finish_reason': 'stop', 'seconds': .8}
    transports.append({**text_common, 'started_at_unix': 1792990803.1,
                       'method': 'POST', 'host': 'example.test', 'request_body_sha256': 'f'*64})
    return {'is_live': True, 'mode': 'local', 'document_requests': 1,
            'execution_id': execution, 'pipeline_contract': 'evidence-two-pass',
            'image_sha256': 'a'*64, 'request_started_at': '2026-10-26T05:00:00+00:00',
            'request_finished_at': '2026-10-26T05:00:10+00:00',
            'source_unchanged': True,
            'source_snapshot': {'git_sha': 'b'*40, 'dirty': True, 'source_tree_sha256': 'c'*64},
            'model_attempts': metrics, 'text_model_attempts': [text], 'transport_attempts': transports}


def browser(actual=None, gold=None, run=None):
    actual, gold, run = actual or prediction(), gold or reference(), run or live()
    checks = [{'name': name, 'status': 'pass'} for name in FRONTEND_CHECKS]
    return {'schema_version': 2, 'status': 'pass', 'actual_browser': True, 'exact_edge_projection_checked': True,
            'kind': 'original_response', 'fixture_only': False,
            'contract': 'original_preview_and_text_cards',
            'image_sha256': gold['sha256'], 'prediction_sha256': prediction_digest(actual),
            'source_tree_sha256': run['source_snapshot']['source_tree_sha256'],
            'execution_id': run['execution_id'], 'source_snapshot': deepcopy(run['source_snapshot']),
            'source_unchanged': True, 'checks': checks,
            'views': [{'mode': mode, 'checks': [deepcopy(c) for c in checks
                        if c['name'] not in ('source_unchanged', 'network_isolation')]}
                      for mode in ('desktop', 'mobile')],
            'ocr_requests': 0, 'external_network_requests': 0, 'external_requests_blocked': 0,
            'first_response_file_sha256': 'e'*64,
            'artifact_sha256': {'/private/real-browser/dom.json': 'f'*64, '/private/real-browser/screen.png': 'd'*64},
            'artifact_paths': ['/private/real-browser/dom.json', '/private/real-browser/screen.png']}


def evaluate(gold, actual, **kwargs):
    evidence = kwargs.pop('run_evidence', live())
    return evaluate_prediction(gold, actual, run_evidence=evidence,
                               frontend_evidence=kwargs.pop('frontend_evidence', browser(actual, gold, evidence)), **kwargs)


def test_valid_raw_result_has_to_pass_all_gates():
    result = evaluate(reference(), prediction())
    assert result['status'] == result['structure_status'] == 'pass'


def test_same_counts_with_endpoint_exchange_fails():
    actual = prediction()
    actual['graph_structures'][0]['edges'][0]['to'] = 'd'
    result = evaluate(reference(), actual)
    assert result['status'] == 'fail'
    assert result['dimensions']['endpoints']['status'] == 'fail'


def test_arrow_reversal_fails_without_changing_endpoint_pair():
    actual = prediction()
    edge = actual['graph_structures'][0]['edges'][0]
    edge['from'], edge['to'] = edge['to'], edge['from']
    result = evaluate(reference(), actual)
    assert result['dimensions']['endpoints']['status'] == 'pass'
    assert result['dimensions']['directions']['status'] == 'fail'
    assert result['status'] == 'fail'


def test_multiple_edges_cannot_be_replaced_by_other_equal_count_edges():
    gold = reference()
    gold['graphs'][0]['edges'].append({**gold['graphs'][0]['edges'][0], 'id': 'parallel', 'weight': 8})
    actual = prediction(gold)
    actual['graph_structures'][0]['multigraph'] = True
    actual['graph_structures'][0]['edges'][-1].update(**{'from': 'c', 'to': 'd'})
    result = evaluate(gold, actual)
    assert result['dimensions']['multiplicity']['status'] == 'fail'
    assert result['status'] == 'fail'


def test_self_loop_loss_cannot_hide_behind_constant_edge_count():
    gold = reference()
    gold['graphs'][0]['edges'][0]['to'] = 'a'
    actual = prediction(gold)
    actual['graph_structures'][0]['multigraph'] = True
    actual['graph_structures'][0]['edges'][0]['to'] = 'b'
    result = evaluate(gold, actual)
    assert result['dimensions']['self_loops']['status'] == 'fail'


@pytest.mark.parametrize('field,value,dimension', [
    ('weight', 99, 'weights'), ('edge_label', 'wrong', 'edge_labels'), ('style', 'dotted', 'styles')])
def test_same_topology_still_checks_bound_attributes(field, value, dimension):
    actual = prediction()
    actual['graph_structures'][0]['edges'][0][field] = value
    result = evaluate(reference(), actual)
    assert result['dimensions'][dimension]['status'] == 'fail'
    assert result['status'] == 'fail'


def test_arbitrary_ids_and_list_order_are_not_graph_evidence():
    actual = prediction()
    graph = actual['graph_structures'][0]
    mapping = {'a': 'renamed_8', 'b': 'renamed_2', 'c': 'renamed_5', 'd': 'renamed_9'}
    graph['id'] = 'different_graph_id'
    for node in graph['vertices']:
        node['id'] = mapping[node['id']]
    graph['vertices'].reverse()
    for index, edge in enumerate(graph['edges']):
        edge.update(id=f'new_{index}', **{'from': mapping[edge['from']], 'to': mapping[edge['to']]})
    graph['edges'].reverse()
    assert evaluate(reference(), actual)['status'] == 'pass'


def two_panels():
    gold = reference()
    first, second = gold['graphs'][0], deepcopy(gold['graphs'][0])
    first.update(name='left', bbox=[0, 0, .45, 1])
    second.update(name='right', bbox=[.55, 0, 1, 1])
    for node in first['vertices']:
        node['x'] *= .4
    for node in second['vertices']:
        node['x'] = .6 + node['x']*.4
    gold['graphs'].append(second)
    return gold


def test_panel_reordering_is_allowed_but_cross_panel_endpoint_is_not():
    gold = two_panels()
    actual = prediction(gold)
    actual['graph_structures'].reverse()
    assert evaluate(gold, actual)['status'] == 'pass'
    actual['graph_structures'][0]['edges'][0]['to'] = 'left_only_node'
    result = evaluate(gold, actual)
    assert result['status'] == 'fail'
    assert result['dimensions']['schema']['status'] == 'fail'


def test_same_named_nodes_in_wrong_panel_do_not_match_by_label_alone():
    gold = two_panels()
    actual = prediction(gold)
    actual['graph_structures'][0]['vertices'], actual['graph_structures'][1]['vertices'] = (
        actual['graph_structures'][1]['vertices'], actual['graph_structures'][0]['vertices'])
    result = evaluate(gold, actual)
    assert result['dimensions']['vertices']['status'] == 'fail'


def test_two_full_page_boxes_do_not_certify_two_correctly_separated_panels():
    gold = two_panels()
    actual = prediction(gold)
    for graph in actual['graph_structures']:
        graph['bbox'] = [0, 0, 1, 1]
    result = evaluate(gold, actual)
    assert result['dimensions']['panels']['status'] == 'fail'


def test_unlabeled_nodes_are_matched_one_to_one_by_position():
    gold = reference()
    for node in gold['graphs'][0]['vertices']:
        node['label'] = None
    actual = prediction(gold)
    actual['graph_structures'][0]['vertices'].reverse()
    assert evaluate(gold, actual)['status'] == 'pass'
    actual['graph_structures'][0]['vertices'][0]['x'] = .9
    result = evaluate(gold, actual)
    assert result['dimensions']['vertices']['status'] == 'fail'


def test_unknown_fields_cannot_be_certified_by_complete_flag():
    actual = prediction()
    actual['graph_structures'][0]['edges'][0]['direction'] = 'unknown'
    result = evaluate(reference(), actual)
    assert result['dimensions']['completeness']['status'] == 'fail'
    assert result['status'] == 'fail'


def test_pending_evidence_with_complete_true_is_rejected():
    actual = prediction()
    actual['graph_structures'][0]['uncertain_edges'] = ['ambiguous_direction']
    result = evaluate(reference(), actual)
    assert result['dimensions']['completeness']['status'] == 'fail'


def test_partial_gold_and_missing_gold_are_not_certified():
    gold = reference()
    gold['graphs'][0]['annotation_complete'] = False
    gold['graphs'][0]['edges'][0]['weight'] = None
    assert evaluate(gold, prediction())['status'] == 'not_certified'
    assert evaluate(None, prediction())['status'] == 'not_certified'


def test_missing_coordinate_reference_is_not_certified():
    gold = reference()
    gold['graphs'][0]['vertices'][0].pop('x')
    assert evaluate(gold, prediction())['status'] == 'not_certified'


def test_missing_critical_prediction_fields_are_failure_not_default_values():
    actual = prediction()
    actual['graph_structures'][0]['edges'][0].pop('edge_label')
    result = evaluate(reference(), actual)
    assert result['dimensions']['schema']['status'] == 'fail'
    assert result['status'] == 'fail'
    assert evaluate(reference(), {})['status'] == 'fail'


def test_text_and_frontend_are_independent_certification_gates():
    result = evaluate(reference(), prediction(), frontend_evidence={'status': 'not_run'})
    assert result['structure_status'] == 'pass'
    assert result['dimensions']['frontend']['status'] == 'not_run'
    assert result['status'] == 'not_certified'
    actual = prediction()
    actual['text'] = '无关内容'
    assert evaluate(reference(), actual)['dimensions']['text']['status'] == 'fail'
    gold = reference()
    gold['question_text_complete'] = False
    assert evaluate(gold, prediction())['status'] == 'not_certified'


def test_model_retries_or_changed_source_invalidate_first_result_acceptance():
    evidence = live()
    evidence['model_attempts'][0]['attempt'] = 2
    assert evaluate(reference(), prediction(), run_evidence=evidence)['status'] == 'fail'
    evidence = live()
    evidence['document_requests'] = 2
    assert evaluate(reference(), prediction(), run_evidence=evidence)['status'] == 'fail'
    evidence = live()
    evidence['source_unchanged'] = False
    assert evaluate(reference(), prediction(), run_evidence=evidence)['status'] == 'fail'
    evidence = live()
    evidence['model_attempts'] = []
    assert evaluate(reference(), prediction(), run_evidence=evidence)['status'] == 'not_certified'


def test_old_cached_attempt_timestamps_do_not_prove_a_fresh_run():
    evidence = live()
    evidence['model_attempts'][0]['started_at_unix'] -= 86400
    result = evaluate(reference(), prediction(), run_evidence=evidence)
    assert result['dimensions']['run_evidence']['status'] == 'fail'


@pytest.mark.parametrize('count', [1, 3])
def test_complete_certificate_requires_exactly_two_successful_qwen_sends(count):
    evidence = live()
    if count == 1:
        evidence['model_attempts'].pop()
        evidence['transport_attempts'].pop(1)
    else:
        extra_metric = deepcopy(evidence['model_attempts'][-1])
        extra_send = deepcopy(evidence['transport_attempts'][1])
        for record in (extra_metric, extra_send):
            record.update(logical_call=3, transport_id='synthetic-extra-qwen')
        evidence['model_attempts'].append(extra_metric)
        evidence['transport_attempts'].insert(2, extra_send)
    result = evaluate(reference(), prediction(), run_evidence=evidence)
    assert result['dimensions']['run_evidence']['status'] == 'fail'
    assert result['status'] == 'fail'


@pytest.mark.parametrize('change', ['http_error', 'truncated', 'wrong_payload', 'wrong_image',
                                  'wrong_model', 'wrong_execution', 'one_send_two_metrics',
                                  'unscoped_third_send', 'text_in_qwen_ledger'])
def test_provider_claims_must_match_successful_actual_send_records(change):
    evidence = live()
    metric, sent = evidence['model_attempts'][1], evidence['transport_attempts'][1]
    if change == 'http_error':
        metric.update(http_status=500, status='http_error')
        sent['http_status'] = 500
    elif change == 'truncated':
        metric['finish_reason'] = 'length'
    elif change == 'wrong_payload':
        sent['prompt_sha256'] = '9'*64
    elif change == 'wrong_image':
        sent['image_sha256'] = ['9'*64]
    elif change == 'wrong_model':
        sent['model'] = 'different-vision-model'
    elif change == 'wrong_execution':
        sent['execution_id'] = 'different-document'
    elif change == 'one_send_two_metrics':
        metric['transport_id'] = evidence['model_attempts'][0]['transport_id']
    elif change == 'unscoped_third_send':
        evidence['transport_attempts'].append({**sent, 'transport_id': 'hidden-extra', 'provider': 'unscoped'})
    else:
        evidence['model_attempts'].append(evidence['text_model_attempts'].pop())
    result = evaluate(reference(), prediction(), run_evidence=evidence)
    assert result['dimensions']['run_evidence']['status'] == 'fail'


def test_missing_send_observation_cannot_be_replaced_by_provider_metrics():
    evidence = live()
    evidence.pop('transport_attempts')
    assert evaluate(reference(), prediction(), run_evidence=evidence)['status'] == 'not_certified'


def test_text_correction_has_a_separate_single_send_ledger():
    evidence = live()
    result = evaluate(reference(), prediction(), run_evidence=evidence)
    assert result['dimensions']['run_evidence']['qwen_sends'] == 2
    assert result['dimensions']['run_evidence']['text_sends'] == 1
    assert result['status'] == 'pass'
    evidence['text_model_attempts'] = []
    assert evaluate(reference(), prediction(), run_evidence=evidence)['status'] == 'not_certified'


def test_failed_first_call_can_stop_early_but_cannot_receive_complete_certificate():
    evidence, actual = live(), prediction()
    actual.update(recognition_status='failed', review={'required': True})
    evidence['model_attempts'] = evidence['model_attempts'][:1]
    evidence['transport_attempts'] = evidence['transport_attempts'][:1]
    evidence['text_model_attempts'] = []
    evidence['model_attempts'][0].update(status='http_error', http_status=500)
    evidence['transport_attempts'][0]['http_status'] = 500
    result = evaluate(reference(), actual, run_evidence=evidence)
    assert result['status'] == 'fail'
    assert 'qwen_two_send_budget_exceeded' not in result['dimensions']['run_evidence']['issues']


@pytest.mark.parametrize('change', ['missing_second', 'false_second', 'missing_reconciliation',
                                  'missing_issues', 'unknown_issues', 'unresolved_issue'])
def test_v2_text_requires_explicit_second_pass_and_empty_reconciliation_issues(change):
    actual = prediction()
    text = actual['diagnostics']['text_evidence']
    if change == 'missing_second':
        text.pop('second_pass_reviewed')
    elif change == 'false_second':
        text['second_pass_reviewed'] = False
    elif change == 'missing_reconciliation':
        text.pop('reconciliation')
    elif change == 'missing_issues':
        text['reconciliation'].pop('issues')
    elif change == 'unknown_issues':
        text['reconciliation']['issues'] = None
    else:
        text['reconciliation']['issues'] = ['critical_token_conflict']
    result = evaluate(reference(), actual)
    assert result['dimensions']['text']['status'] == 'fail'
    assert result['status'] == 'fail'


def test_old_pipeline_response_can_be_diagnosed_but_not_certified_as_current_v2():
    actual = prediction()
    actual['graph_display_version'] = '2026-10-26-evidence-two-pass-v1'
    result = evaluate(reference(), actual)
    assert result['structure_status'] == 'pass'
    assert result['status'] == 'not_certified'


def test_local_runner_links_actual_prepared_request_bytes_and_separate_text_call(monkeypatch):
    import io
    import base64
    from PIL import Image
    import requests
    import ai
    import ocr_runtime
    import ocr_nextgen
    import scripts.benchmark_graph_first_pass as runner
    from ocr_correction import correct_text
    from graph_staged import Budget
    monkeypatch.setattr(ai, 'API_KEY', 'synthetic-test-token')
    monkeypatch.setattr(ai, 'VISION_ENABLED', True)
    monkeypatch.setattr(ai, 'DEEPSEEK_API_KEY', 'synthetic-test-token')
    sent = []

    def fake_network(session, prepared, **kwargs):
        # This is the original Session.send under the observer: no network.
        payload = json.loads(prepared.body)
        sent.append(payload)
        response = requests.Response()
        response.status_code, response.url, response.encoding = 200, prepared.url, 'utf-8'
        content = json.dumps({'graphs': []}) if payload['model'] == 'qwen3-vl-plus' else json.dumps({'edits': []})
        result = {'model': payload['model'], 'choices': [{'message': {'content': content}, 'finish_reason': 'stop'}]}
        if payload.get('stream'):
            result['choices'][0]['delta'] = result['choices'][0].pop('message')
            response._content = ('data: '+json.dumps(result)+'\n\ndata: [DONE]\n\n').encode()
        else:
            response._content = json.dumps(result).encode()
        response._content_consumed = True
        return response

    monkeypatch.setattr(requests.sessions.Session, 'send', fake_network)
    monkeypatch.setattr(ocr_runtime, 'recognize_image', lambda raw: {'text': ''})
    data = io.BytesIO()
    Image.new('RGB', (2, 2), 'white').save(data, 'PNG')
    url = 'data:image/png;base64,'+base64.b64encode(data.getvalue()).decode()

    def fake_graph_orchestrator(raw, text, *, vision_provider):
        budget = Budget(calls=2)
        vision_provider('JSON node inventory', [url], budget)
        vision_provider('JSON complete topology', [url], budget)
        corrected, correction = correct_text('求最短路')
        result = prediction()
        result['text'] = corrected
        result['diagnostics']['correction'] = correction
        return result

    monkeypatch.setattr(ocr_nextgen, 'recognize_graph_document', fake_graph_orchestrator)
    result, evidence = runner.local_recognition(data.getvalue(), execution_id='synthetic-send-observer')
    assert result is not None, json.dumps(evidence, ensure_ascii=False)
    assert result['diagnostics']['correction']['status'] == 'ok'
    assert len(sent) == 3
    assert [r['provider'] for r in evidence['transport_attempts']] == ['qwen', 'qwen', 'text']
    assert len(evidence['model_attempts']) == 2 and len(evidence['text_model_attempts']) == 1
    for metric in evidence['model_attempts']:
        transport = next(row for row in evidence['transport_attempts'] if row['transport_id'] == metric['transport_id'])
        assert metric['prompt_sha256'] == transport['prompt_sha256']
        assert metric['image_sha256'] == transport['image_sha256']
        assert metric['http_status'] == metric['status'] == transport['http_status'] == 200
    assert evidence['text_model_attempts'][0]['transport_id'] == evidence['transport_attempts'][2]['transport_id']


def test_two_annotation_collections_and_duplicate_detection(tmp_path):
    gold = reference()
    a, b = tmp_path/'images.json', tmp_path/'records.json'
    a.write_text(json.dumps({'images': [gold]}))
    second = deepcopy(gold)
    second['image_id'] = 'second'
    second.pop('id')
    b.write_text(json.dumps({'records': [second]}))
    assert set(load_annotations([a, b])) == {'original_1', 'second'}
    b.write_text(json.dumps({'records': [gold]}))
    with pytest.raises(ValueError, match='Duplicate'):
        load_annotations([a, b])


def test_production_urls_and_credential_urls_cannot_be_used():
    for url in ['https://dmate.zeabur.app', 'http://127.0.0.1.example.com', 'http://user:secret@localhost', 'file:///tmp/server']:
        with pytest.raises(ValueError):
            validate_base_url(url)
    assert validate_base_url('http://127.0.0.1:5000/') == 'http://127.0.0.1:5000'


def test_check_only_never_calls_recognition_or_records_fake_pass(tmp_path, monkeypatch):
    from PIL import Image
    import scripts.benchmark_graph_first_pass as runner
    original = tmp_path/'original.png'
    Image.new('RGB', (20, 20), 'white').save(original)
    sha = digest(original.read_bytes())
    manifest = tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'images': [{'id': 'original_1', 'path': str(original), 'sha256': sha, 'width': 20, 'height': 20}]}))
    annotations = tmp_path/'annotations.json'
    gold = reference()
    gold['sha256'] = sha
    annotations.write_text(json.dumps({'images': [gold]}))
    def forbidden(*args, **kwargs):
        raise AssertionError('check-only must not execute a recognizer')
    monkeypatch.setattr(runner, 'local_recognition', forbidden)
    output = tmp_path/'private-output'
    status = main(['--manifest', str(manifest), '--annotations', str(annotations), '--local', '--check-only', '--output', str(output)])
    assert status in (0, 2)
    summary = json.loads((output/'summary.json').read_text())
    assert summary['actual_document_requests'] == summary['certified_passes'] == 0
    assert summary['frontend_rendering'] == 'not_run'
    with pytest.raises(SystemExit):
        main(['--manifest', str(manifest), '--annotations', str(annotations), '--local', '--check-only', '--output', str(output)])


def test_source_dirty_contents_are_frozen_separately_from_git_sha():
    a = {'git_sha': 'a'*40, 'dirty': True, 'source_tree_sha256': 'b'*64}
    b = {**a, 'source_tree_sha256': 'c'*64}
    assert not same_source(a, b)


def test_uncertain_slide_style_is_not_certified_even_when_prediction_copies_it():
    gold = reference()
    gold['graphs'][0]['issues'] = ['tiny arrowheads require independent adjudication']
    assert reference_issues(gold)
    assert evaluate(gold, prediction())['status'] == 'not_certified'


@pytest.mark.parametrize('change', ['missing', 'unknown', 'false', 'visual_false', 'body_unknown'])
def test_equal_transcription_does_not_override_unknown_text_evidence(change):
    actual = prediction()
    evidence = actual['diagnostics']['text_evidence']
    if change == 'missing':
        actual.pop('diagnostics')
    elif change == 'unknown':
        evidence['complete'] = 'unknown'
    elif change == 'false':
        evidence['complete'] = False
    elif change == 'visual_false':
        evidence['visual_body_complete'] = False
    else:
        actual['body_complete'] = None
    result = evaluate(reference(), actual)
    assert result['status'] == 'fail'
    assert result['dimensions']['text']['status'] == 'fail'
    assert result['dimensions']['completeness']['status'] == 'fail'


def test_review_required_cannot_be_hidden_by_complete_graphs_and_matching_text():
    actual = prediction()
    actual['review'] = {'required': True, 'reasons': ['文字尚未核对完整']}
    assert evaluate(reference(), actual)['dimensions']['completeness']['status'] == 'fail'
    actual.pop('review')
    assert evaluate(reference(), actual)['dimensions']['schema']['status'] == 'fail'


def test_internal_engine_graphs_are_not_the_public_result_contract():
    actual = prediction()
    actual['graphs'] = actual.pop('graph_structures')
    assert evaluate(reference(), actual)['dimensions']['schema']['status'] == 'fail'


def test_scalar_edge_multiplicity_does_not_replace_physical_card_instances():
    gold = reference()
    gold['graphs'][0]['edges'].append({**gold['graphs'][0]['edges'][0], 'id': 'parallel'})
    actual = prediction(gold)
    graph = actual['graph_structures'][0]
    graph['multigraph'] = True
    graph['edges'].pop()
    graph['edges'][0]['multiplicity'] = 2
    result = evaluate(gold, actual)
    assert result['dimensions']['endpoints']['status'] == 'pass'
    assert result['dimensions']['schema']['status'] == 'fail'
    assert result['status'] == 'fail'


def test_fixture_browser_pass_does_not_certify_real_images():
    evidence = {**browser(), 'kind': 'synthetic_contract', 'fixture_only': True}
    result = evaluate(reference(), prediction(), frontend_evidence=evidence)
    assert result['dimensions']['frontend']['status'] == 'not_certified'
    assert result['status'] == 'not_certified'


@pytest.mark.parametrize('field', ['image_sha256', 'prediction_sha256', 'source_tree_sha256', 'execution_id'])
def test_browser_result_is_bound_to_the_same_original_response_and_source(field):
    evidence = browser()
    evidence[field] = 'f'*64
    result = evaluate(reference(), prediction(), frontend_evidence=evidence)
    assert result['dimensions']['frontend']['status'] == 'fail'
    assert result['status'] == 'fail'


def test_unbound_browser_evidence_cannot_pass_by_setting_a_boolean():
    evidence = browser()
    evidence.pop('prediction_sha256')
    assert evaluate(reference(), prediction(), frontend_evidence=evidence)['status'] == 'not_certified'


@pytest.mark.parametrize('mutation', ['checks', 'mobile', 'network', 'source'])
def test_browser_certificate_requires_all_observed_items_and_both_views(mutation):
    evidence = browser()
    if mutation == 'checks':
        evidence['checks'] = []
    elif mutation == 'mobile':
        evidence['views'].pop()
    elif mutation == 'network':
        evidence['ocr_requests'] = 1
    else:
        evidence['source_snapshot']['dirty'] = False
    result = evaluate(reference(), prediction(), frontend_evidence=evidence)
    assert result['status'] != 'pass'
    assert result['dimensions']['frontend']['status'] != 'pass'


def test_superscript_in_question_is_not_collapsed_to_an_ordinary_digit():
    gold = reference()
    gold['question_text'] = '求 x²'
    actual = prediction(gold)
    actual['text'] = '求 x2'
    assert evaluate(gold, actual)['dimensions']['text']['status'] == 'fail'


def test_missing_edge_confirmation_is_not_a_complete_card():
    actual = prediction()
    actual['graph_structures'][0]['edges'][0].pop('status')
    assert evaluate(reference(), actual)['dimensions']['completeness']['status'] == 'fail'


def test_reverse_enum_cannot_pass_a_frontend_that_only_accepts_forward_direction():
    actual = prediction()
    edge = actual['graph_structures'][0]['edges'][0]
    edge.update(**{'from': 'b', 'to': 'a', 'direction': 'reverse'})
    result = evaluate(reference(), actual)
    assert result['dimensions']['directions']['status'] == 'pass'
    assert result['dimensions']['schema']['status'] == 'fail'


def test_opposite_arrows_do_not_imply_a_multigraph():
    gold = reference()
    gold['graphs'][0]['edges'].append({**gold['graphs'][0]['edges'][0], 'id': 'back', 'from': 'b', 'to': 'a'})
    actual = prediction(gold)
    assert actual['graph_structures'][0]['multigraph'] is False
    assert evaluate(gold, actual)['status'] == 'pass'


def test_conflicting_reference_completeness_cannot_be_certified():
    gold = reference()
    gold['graphs'][0].update(annotation_complete=False, topology_complete=True)
    assert evaluate(gold, prediction())['status'] == 'not_certified'


def test_missing_reference_text_completeness_is_not_inferred_from_matching_text():
    gold = reference()
    gold.pop('question_text_complete')
    result = evaluate(gold, prediction())
    assert result['structure_status'] == 'pass'
    assert result['dimensions']['text']['status'] == 'not_certified'
    assert result['status'] == 'not_certified'
