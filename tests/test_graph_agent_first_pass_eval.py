"""Synthetic ledger counterexamples only; these tests call no model/API.

Passing a fabricated *unit fixture* exercises the comparator contract. It is
not a recognition result and never supplies an original-image certificate.
"""
from collections import Counter
from copy import deepcopy

import pytest

from graph_first_pass_eval import CURRENT_PIPELINE_VERSION, _run_evidence, evaluate_prediction
from graph_pipeline_version import AGENT_PIPELINE_VERSION, EVIDENCE_PIPELINE_VERSION


ROLES = ('page_vertices', 'body_text', 'connections', 'attributes', 'structure_review')
SOURCE = 'a'*64
TASK = 'unit-ledger-task'
EXECUTION = 'unit-ledger-execution'
BASE = 1792990800


def fixture():
    reference = {'id': 'synthetic', 'sha256': SOURCE, 'width': 100, 'height': 100,
        'question_text': '', 'question_text_complete': True,
        'graphs': [{'id': 'G1', 'name': 'G1', 'bbox': [.1, .1, .9, .9],
                    'annotation_complete': True, 'directed': True, 'weighted': True,
                    'vertices': [{'id': 'a', 'label': 'a', 'x': .2, 'y': .5},
                                 {'id': 'b', 'label': 'b', 'x': .8, 'y': .5}],
                    'edges': [{'id': 'e1', 'from': 'a', 'to': 'b', 'direction': 'forward',
                               'weight': 2, 'label': None, 'style': 'solid'}]}]}
    graph = deepcopy(reference['graphs'][0])
    graph.pop('annotation_complete')
    graph.update(complete=True, multigraph=False, node_complete=True, uncertain_edges=[],
                 schema_version='dmate.graph/1')
    graph['edges'][0].pop('label')
    graph['edges'][0].update(edge_label=None, multiplicity=1, status='accepted')
    remote, metrics, sends, events = [], [], [], []
    for index, role in enumerate(ROLES, 1):
        revision = max(0, index-2)
        row = {'provider': 'qwen', 'model': 'qwen3-vl-plus', 'returned_model': 'qwen3-vl-plus',
               'logical_call': 1, 'attempt': 1, 'agent_role': role, 'role_invocation': 1,
               'state_revision': revision, 'task_id': TASK, 'source_sha256': SOURCE,
               'send_sequence': index, 'http_status': 200, 'status': 200, 'finish_reason': 'stop',
               'prompt_sha256': f'{index:064x}', 'image_sha256': ['e'*64],
               'started_at_unix': BASE+index*3, 'seconds': 1.}
        remote.append(deepcopy(row))
        observed = {**row, 'execution_id': EXECUTION, 'transport_id': f'send-{index}'}
        metrics.append(observed)
        sends.append({**observed, 'method': 'POST', 'host': 'synthetic.invalid',
                      'request_body_sha256': f'{index+20:064x}', 'started_at_unix': row['started_at_unix']+.1})
        events.extend([
            {'role': role, 'status': 'started', 'revision': revision, 'invocation': 1,
             'request_digest': f'{index+30:064x}'},
            {'role': role, 'status': 'responded', 'revision': revision, 'invocation': 1,
             'response_digest': f'{index+40:064x}'},
        ])
    events.append({'role': 'structure_review', 'status': 'reviewed', 'verdict': 'accept',
                   'revision': 3, 'conflict_count': 0})
    tools = []
    for index, (name, role) in enumerate([
        ('image.local_evidence', 'page_vertices'), ('image.marker_grounding', 'page_vertices'),
        ('image.trace_candidates', 'connections'), ('graph.stroke_validation', 'connections'),
        ('image.review_views', 'body_text'), ('image.review_views', 'structure_review'),
        ('text.visual_reconciliation', 'structure_review'), ('graph.structure_audit', 'structure_review'),
    ]):
        tools.append({'call_id': f'tool-{index}', 'tool': name, 'tool_version': 'unit-v1',
                      'role': role, 'source_sha256': SOURCE, 'input_digest': f'{index+50:064x}',
                      'result_digest': f'{index+60:064x}', 'elapsed_seconds': .01,
                      'status': 'success', 'error_code': None, 'timeout_mode': 'cooperative',
                      'handler_started': True, 'handler_finished': True})
    workflow = {'engine': 'langgraph', 'version': AGENT_PIPELINE_VERSION,
                'task_id': TASK, 'source_sha256': SOURCE, 'provider_source': 'configured_live',
                'max_remote_calls': 14, 'actual_remote_sends': 5, 'role_sends': dict(Counter(ROLES)),
                'network_recoveries': 0, 'repair_rounds': 0, 'state_revision': 3,
                'events': events, 'tools': tools, 'remaining_conflicts': [], 'complete': True, 'seconds': 20.}
    prediction = {'graph_structures': [graph], 'graph_display_version': AGENT_PIPELINE_VERSION,
        'text': '', 'raw_ocr_text': '', 'recognition_status': 'complete', 'review': {'required': False},
        'diagnostics': {'agent_workflow': workflow, 'remote_metrics': remote, 'correction': {'status': 'empty'},
            'text_evidence': {'source': 'original_visual_transcription', 'complete': True,
                             'visual_body_complete': True, 'second_pass_reviewed': True,
                             'reconciliation': {'issues': [], 'second_pass_reviewed': True}}}}
    evidence = {'mode': 'local', 'is_live': True, 'document_requests': 1,
                'execution_id': EXECUTION, 'pipeline_contract': 'agent-tools', 'image_sha256': SOURCE,
                'request_started_at': '2026-10-26T05:00:00+00:00',
                'request_finished_at': '2026-10-26T05:02:00+00:00', 'source_unchanged': True,
                'source_snapshot': {'git_sha': 'b'*40, 'dirty': True, 'source_tree_sha256': 'c'*64},
                'model_attempts': metrics, 'text_model_attempts': [], 'transport_attempts': sends}
    synchronize(prediction, evidence)
    return reference, prediction, evidence


def synchronize(prediction, evidence):
    workflow = prediction['diagnostics']['agent_workflow']
    metrics = evidence['model_attempts']
    workflow['actual_remote_sends'] = len(metrics)
    workflow['role_sends'] = dict(Counter(row['agent_role'] for row in metrics))
    remote = []
    for index, row in enumerate(metrics, 1):
        row['send_sequence'] = index
        remote.append({k: deepcopy(v) for k, v in row.items() if k not in ('transport_id', 'execution_id')})
    prediction['diagnostics']['remote_metrics'] = remote
    for index, row in enumerate(workflow['events'], 1):
        row['sequence'] = index


def drop_role(prediction, evidence, role):
    evidence['model_attempts'] = [m for m in evidence['model_attempts'] if m['agent_role'] != role]
    evidence['transport_attempts'] = [m for m in evidence['transport_attempts'] if m.get('agent_role') != role]
    workflow = prediction['diagnostics']['agent_workflow']
    workflow['events'] = [e for e in workflow['events'] if e['role'] != role]
    synchronize(prediction, evidence)


def test_current_two_pass_version_uses_shared_v3_constant():
    assert CURRENT_PIPELINE_VERSION == EVIDENCE_PIPELINE_VERSION
    assert CURRENT_PIPELINE_VERSION != AGENT_PIPELINE_VERSION


def test_complete_role_transport_tool_ledger_satisfies_component_contract_only():
    reference, prediction, evidence = fixture()
    result = _run_evidence(evidence, reference, prediction)
    assert result['status'] == 'pass', result
    assert result['qwen_sends'] == 5 and result['task_id'] == TASK
    assessment = evaluate_prediction(reference, prediction, run_evidence=evidence)
    assert assessment['pipeline_status'] == 'pass'
    assert assessment['application_certified_passes'] == 0
    assert assessment['status'] == 'not_certified'


@pytest.mark.parametrize('change', [
    'injected', 'task', 'source', 'metric_source', 'counter', 'role_counter', 'raw_ledger',
    'transport_role', 'extra_send', 'two_uploads', 'synthetic', 'conflicts', 'incomplete',
    'version', 'contract', 'old_timestamp', 'hidden_attempt', 'partial_stream', 'stale_review', 'transport_exception',
])
def test_agent_claims_cannot_replace_bound_actual_execution(change):
    reference, prediction, evidence = fixture()
    workflow = prediction['diagnostics']['agent_workflow']
    if change == 'injected': workflow['provider_source'] = 'injected'
    elif change == 'task': evidence['model_attempts'][0]['task_id'] = 'other-task'
    elif change == 'source': workflow['source_sha256'] = 'd'*64
    elif change == 'metric_source': evidence['model_attempts'][0]['source_sha256'] = 'd'*64
    elif change == 'counter': workflow['actual_remote_sends'] = 4
    elif change == 'role_counter': workflow['role_sends']['connections'] = 2
    elif change == 'raw_ledger': prediction['diagnostics']['remote_metrics'][0]['prompt_sha256'] = 'f'*64
    elif change == 'transport_role': evidence['transport_attempts'][0]['agent_role'] = 'body_text'
    elif change == 'extra_send': evidence['transport_attempts'].append({**evidence['transport_attempts'][0], 'transport_id': 'hidden-send'})
    elif change == 'two_uploads': evidence['document_requests'] = 2
    elif change == 'synthetic': evidence['synthetic'] = True
    elif change == 'conflicts': workflow['remaining_conflicts'] = [{'id': 'edge-direction', 'target_role': 'attributes'}]
    elif change == 'incomplete': workflow['complete'] = False
    elif change == 'version': workflow['version'] = EVIDENCE_PIPELINE_VERSION
    elif change == 'contract': evidence['pipeline_contract'] = 'evidence-two-pass'
    elif change == 'old_timestamp': evidence['transport_attempts'][0]['started_at_unix'] -= 10000
    elif change == 'hidden_attempt': evidence['model_attempts'][0]['attempt'] = 2
    elif change == 'partial_stream': evidence['model_attempts'][0]['partial_stream'] = True
    elif change == 'stale_review': workflow['state_revision'] = 4
    elif change == 'transport_exception': evidence['transport_attempts'][0]['exception_type'] = 'ConnectionError'
    assert _run_evidence(evidence, reference, prediction)['status'] != 'pass'


@pytest.mark.parametrize('role', ROLES)
def test_every_required_role_must_have_an_actual_send(role):
    reference, prediction, evidence = fixture()
    drop_role(prediction, evidence, role)
    result = _run_evidence(evidence, reference, prediction)
    assert result['status'] != 'pass'
    assert 'required_agent_role_not_executed:'+role in result['missing_evidence']


def test_plain_graph_may_skip_attributes_only_with_explicit_reason():
    reference, prediction, evidence = fixture()
    graph = prediction['graph_structures'][0]
    graph.update(directed=False, weighted=False)
    graph['edges'][0].update(direction='undirected', weight=None)
    drop_role(prediction, evidence, 'attributes')
    result = _run_evidence(evidence, reference, prediction)
    assert 'optional_attribute_role_skip_not_explained' in result['missing_evidence']
    workflow = prediction['diagnostics']['agent_workflow']
    workflow['events'].insert(6, {'role': 'attributes', 'status': 'skipped',
        'reason': 'no_attribute_conflict_or_annotated_edges'})
    synchronize(prediction, evidence)
    assert _run_evidence(evidence, reference, prediction)['status'] == 'pass'


@pytest.mark.parametrize('change', ['source', 'role', 'digest', 'duplicate', 'failed', 'secret_field', 'missing'])
def test_tools_require_source_role_result_and_unique_call_evidence(change):
    reference, prediction, evidence = fixture()
    workflow = prediction['diagnostics']['agent_workflow']
    row = workflow['tools'][0]
    if change == 'source': row['source_sha256'] = 'd'*64
    elif change == 'role': row['role'] = 'solver'
    elif change == 'digest': row.pop('result_digest')
    elif change == 'duplicate': workflow['tools'][1]['call_id'] = row['call_id']
    elif change == 'failed': row.update(status='timeout', error_code='tool_timeout', result_digest=None)
    elif change == 'secret_field': row['authorization'] = 'must-not-be-in-audit'
    elif change == 'missing': workflow.pop('tools')
    assert _run_evidence(evidence, reference, prediction)['status'] != 'pass'


def add_network_recovery(prediction, evidence):
    workflow = prediction['diagnostics']['agent_workflow']
    first = evidence['model_attempts'][2]
    retry = deepcopy(first)
    first.update(status='transport_failed', finish_reason=None, partial_stream=True)
    retry.update(logical_call=2, transport_id='send-recovery', started_at_unix=first['started_at_unix']+1.1)
    evidence['model_attempts'].insert(3, retry)
    sent = deepcopy(evidence['transport_attempts'][2])
    sent.update(logical_call=2, transport_id='send-recovery', started_at_unix=retry['started_at_unix']+.1)
    evidence['transport_attempts'].insert(3, sent)
    workflow['network_recoveries'] = 1
    workflow['events'].insert(5, {'role': 'connections', 'status': 'network_recovery',
        'revision': 1, 'invocation': 1, 'error_kind': 'transport_failed', 'http_status': 200})
    synchronize(prediction, evidence)


def test_declared_bounded_network_recovery_keeps_failed_send_and_can_pass():
    reference, prediction, evidence = fixture()
    add_network_recovery(prediction, evidence)
    result = _run_evidence(evidence, reference, prediction)
    assert result['status'] == 'pass', result
    assert result['qwen_sends'] == 6


def test_recovery_cannot_hide_successful_resampling_or_missing_failed_attempt():
    reference, prediction, evidence = fixture()
    add_network_recovery(prediction, evidence)
    evidence['model_attempts'][2].update(status=200, finish_reason='stop', partial_stream=False)
    synchronize(prediction, evidence)
    result = _run_evidence(evidence, reference, prediction)
    assert 'agent_retry_after_non_transport_result' in result['issues']
    reference, prediction, evidence = fixture()
    add_network_recovery(prediction, evidence)
    workflow = prediction['diagnostics']['agent_workflow']
    workflow['events'] = [e for e in workflow['events'] if e['status'] != 'network_recovery']
    workflow['network_recoveries'] = 0
    synchronize(prediction, evidence)
    result = _run_evidence(evidence, reference, prediction)
    assert 'agent_retry_without_recovery_event' in result['issues']


def test_unexplained_second_role_invocation_is_not_first_upload_acceptance():
    reference, prediction, evidence = fixture()
    workflow = prediction['diagnostics']['agent_workflow']
    row = deepcopy(evidence['model_attempts'][2])
    row.update(role_invocation=2, state_revision=4, started_at_unix=BASE+25, transport_id='hidden-rerun')
    evidence['model_attempts'].append(row)
    send = deepcopy(evidence['transport_attempts'][2])
    send.update(role_invocation=2, state_revision=4, started_at_unix=BASE+25.1, transport_id='hidden-rerun')
    evidence['transport_attempts'].append(send)
    workflow['state_revision'] = 4
    workflow['events'].extend([
        {'role': 'connections', 'status': 'started', 'revision': 4, 'invocation': 2, 'request_digest': 'd'*64},
        {'role': 'connections', 'status': 'responded', 'revision': 4, 'invocation': 2, 'response_digest': 'e'*64},
    ])
    synchronize(prediction, evidence)
    result = _run_evidence(evidence, reference, prediction)
    assert 'agent_invocation_without_targeted_review' in result['issues']
    assert 'agent_final_review_is_stale' in result['issues']


def test_targeted_review_with_new_revision_and_final_independent_acceptance_is_allowed():
    reference, prediction, evidence = fixture()
    workflow = prediction['diagnostics']['agent_workflow']
    workflow['events'][-1].update(verdict='needs_review', conflict_count=1)
    workflow['events'].extend([
        {'role': 'coordinator', 'status': 'targeted_review', 'target_role': 'structure_review',
         'repair_round': 1, 'conflict_ids': ['source-conflict-1']},
        {'role': 'structure_review', 'status': 'started', 'revision': 4, 'invocation': 2,
         'request_digest': 'd'*64},
        {'role': 'structure_review', 'status': 'responded', 'revision': 4, 'invocation': 2,
         'response_digest': 'e'*64},
        {'role': 'structure_review', 'status': 'reviewed', 'verdict': 'accept',
         'revision': 4, 'conflict_count': 0},
    ])
    metric = deepcopy(evidence['model_attempts'][-1])
    metric.update(role_invocation=2, state_revision=4, started_at_unix=BASE+25, transport_id='targeted-send')
    sent = deepcopy(evidence['transport_attempts'][-1])
    sent.update(role_invocation=2, state_revision=4, started_at_unix=BASE+25.1, transport_id='targeted-send')
    evidence['model_attempts'].append(metric)
    evidence['transport_attempts'].append(sent)
    workflow.update(repair_rounds=1, state_revision=4)
    synchronize(prediction, evidence)
    result = _run_evidence(evidence, reference, prediction)
    assert result['status'] == 'pass', result


@pytest.mark.parametrize('change', ['event_role', 'metric_role', 'tool_role', 'edges_none'])
def test_malformed_agent_evidence_is_diagnosed_without_crashing(change):
    reference, prediction, evidence = fixture()
    workflow = prediction['diagnostics']['agent_workflow']
    if change == 'event_role': workflow['events'][0]['role'] = []
    elif change == 'metric_role': evidence['model_attempts'][0]['agent_role'] = {}
    elif change == 'tool_role': workflow['tools'][0]['role'] = []
    else: prediction['graph_structures'][0]['edges'] = None
    result = _run_evidence(evidence, reference, prediction)
    if change != 'edges_none':
        assert result['status'] != 'pass'


def test_agent_text_needs_independent_visual_reconciliation():
    reference, prediction, evidence = fixture()
    prediction['diagnostics']['text_evidence']['second_pass_reviewed'] = False
    result = evaluate_prediction(reference, prediction, run_evidence=evidence)
    assert result['dimensions']['text']['status'] == 'fail'


def test_http_agent_response_without_server_identity_is_not_certified():
    reference, prediction, evidence = fixture()
    evidence['mode'] = 'http'
    result = _run_evidence(evidence, reference, prediction)
    assert 'http_server_source_identity_unverified' in result['missing_evidence']
