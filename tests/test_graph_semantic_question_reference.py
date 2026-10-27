"""Offline reference advice tests. All completion workers are synthetic."""
import copy
import json
import time
from dataclasses import dataclass

import pytest

from dmate_tool_registry import ToolContext, ToolRegistry
from graph_agent_runtime import AgentBudget
import graph_semantic_question_reference as qr


SHA = 'a' * 64


def document():
    return {'body_text': '(1)求v₁的度数。(2)沿蓝边从v₁到v₂。',
            'graphs': [{'id': 'G1', 'name': '(a)',
                        'vertices': [{'id': 'v1', 'label': 'v₁'}, {'id': 'v2', 'label': 'v₂'}],
                        'edges': [{'id': 'e1', 'from': 'v1', 'to': 'v2', 'color': 'blue'}]}],
            'text_context': {'legends': [{'text': '蓝色表示可选线路', 'graph_ids': ['G1']}]}}


def budget(**kwargs):
    return AgentBudget(seconds=30, calls=10, source_sha256=SHA, task_id='synthetic-question', **kwargs)


def advice(doc=None):
    text = (doc or document())['body_text']
    split = text.index('(2)')
    return {'subquestions': [
        {'id': 'q1', 'source_spans': [{'block_id': 'body', 'start': 0, 'end': split,
                                     'quote': text[:split]}], 'graph_ids': ['G1'], 'summary': '核对指定顶点'},
        {'id': 'q2', 'source_spans': [{'block_id': 'body', 'start': split, 'end': len(text),
                                     'quote': text[split:]}], 'graph_ids': ['G1'], 'summary': '核对蓝边和引用'}],
        'references': [], 'focus': [], 'unresolved': []}


@dataclass
class FakeCompletion:
    payload: object
    delay: float = 0.
    ok: bool = True
    truncated: bool = False

    def __call__(self, messages, **kwargs):
        # These assertions execute in the spawned worker. A ready result
        # therefore demonstrates the real transport options reached the seam.
        assert kwargs['retries'] == 0
        assert kwargs['reasoning_effort'] == 'none'
        assert kwargs['preferred_provider'] == 'deepseek'
        assert kwargs['response_format'] == {'type': 'json_object'}
        assert 0 < sum(kwargs['timeout']) <= qr.MAX_SECONDS + .1
        request = json.loads(messages[1]['content'])
        assert request['source_sha256'] == SHA
        assert request['role'] == qr.ROLE
        assert request['response_schema']['additionalProperties'] is False
        span_schema = request['response_schema']['properties']['subquestions']['items']['properties']['source_spans']['items']
        assert span_schema['required'] == ['block_id', 'quote']
        if kwargs['cancelled']():
            return {'ok': False}
        if self.delay:
            time.sleep(self.delay)
        print('PRIVATE_FAKE_TEXT_MUST_NOT_BE_LOGGED')
        return {'ok': self.ok, 'content': json.dumps(self.payload, ensure_ascii=False),
                'provider_id': 'deepseek', 'model': 'synthetic-only',
                'choice': {'finish_reason': 'length' if self.truncated else 'stop'}}


def bound_reference(doc=None):
    doc = doc or document()
    snap = qr._snapshot(doc, SHA)
    return {**qr._base(snap, budget()), **advice(doc), 'status': 'ready'}


def test_actual_spawn_is_source_bound_non_mutating_and_accounted(capsys):
    doc, ledger = document(), budget()
    original = copy.deepcopy(doc)
    result = qr.prepare_question_reference(doc, budget=ledger, completion=FakeCompletion(advice()))
    assert result['status'] == 'ready'
    assert doc == original
    assert result['advisory_only'] is True and result['cannot_drop_content'] is True
    assert result['non_authoritative'] is True
    assert len(result['subquestions']) == 2
    assert ledger.remaining == 9 and ledger.role_counts[qr.ROLE] == 1
    assert len(ledger.metrics) == 1
    metric = ledger.metrics[0]
    assert metric['provider'] == 'deepseek' and metric['request_attempted'] is True
    assert metric['source_sha256'] == SHA and metric['task_id'] == ledger.task_id
    assert metric['worker_reaped'] is True and metric['automatic_retry'] is False
    assert metric['independent_transport_evidence'] is False
    assert '蓝边' not in json.dumps(ledger.events + ledger.metrics, ensure_ascii=False)
    assert 'PRIVATE_FAKE' not in capsys.readouterr().out


def test_start_does_not_wait_for_remote_and_ready_is_copied():
    ledger = budget()
    started = time.monotonic()
    handle = qr.start_question_reference(document(), budget=ledger, completion=FakeCompletion(advice(), delay=.4))
    assert time.monotonic() - started < .8
    assert qr.get_ready_question_reference(handle) is None
    assert handle._done.wait(6)
    first = qr.get_ready_question_reference(handle)
    assert first['status'] == 'ready'
    first['subquestions'].clear()
    assert len(qr.get_ready_question_reference(handle)['subquestions']) == 2
    assert qr.close_question_reference(handle)



def test_worker_stop_reason_treats_unpublished_exitcode_after_deadline_as_timeout(monkeypatch):
    class Process:
        exitcode = None
    monkeypatch.setattr(qr.time, 'monotonic', lambda: 10.0)
    assert qr._worker_stop_reason(Process(), 9.0) == 'wall_timeout'
    Process.exitcode = 124
    assert qr._worker_stop_reason(Process(), 99.0) == 'wall_timeout'
    Process.exitcode = 1
    assert qr._worker_stop_reason(Process(), 9.0) == 'worker_failed'


def test_hard_wall_timeout_reaps_worker_and_releases_remote_slot(monkeypatch):
    monkeypatch.setattr(qr, 'MAX_SECONDS', .6)
    ledger = budget()
    started = time.monotonic()
    handle = qr.start_question_reference(document(), budget=ledger, completion=FakeCompletion(advice(), delay=20))
    assert handle._done.wait(3)
    result = qr.get_ready_question_reference(handle)
    assert time.monotonic() - started < 2.5
    assert result['status'] == 'local_only'
    assert result['reason'] == 'wall_timeout'
    assert not handle._process.is_alive()
    assert ledger.metrics[0]['worker_reaped'] is True
    assert ledger._remote_slots.acquire(blocking=False)
    assert ledger._remote_slots.acquire(blocking=False)
    ledger._remote_slots.release()
    ledger._remote_slots.release()


def test_close_stops_inflight_reference_without_waiting_for_completion():
    ledger = budget()
    handle = qr.start_question_reference(document(), budget=ledger, completion=FakeCompletion(advice(), delay=20))
    started = time.monotonic()
    assert qr.close_question_reference(handle)
    assert time.monotonic() - started < 1.3
    assert handle._done.wait(1)
    assert not handle._process.is_alive()
    assert qr.get_ready_question_reference(handle)['status'] != 'ready'


@pytest.mark.parametrize('change', ['quote', 'unicode_subscript', 'offset', 'unknown_graph', 'duplicate_id',
                                   'field_policy', 'replacement_graph'])
def test_bad_advice_cannot_become_a_policy_or_rewrite_content(change):
    value = advice()
    if change == 'quote':
        value['subquestions'][0]['source_spans'][0]['quote'] = '求欧拉图'
    elif change == 'unicode_subscript':
        span = value['subquestions'][0]['source_spans'][0]
        span['quote'] = span['quote'].replace('₁', '₂')
    elif change == 'offset':
        value['subquestions'][0]['source_spans'][0]['start'] = True
    elif change == 'unknown_graph':
        value['subquestions'][0]['graph_ids'] = ['G2']
    elif change == 'duplicate_id':
        value['subquestions'][1]['id'] = 'q1'
    elif change == 'field_policy':
        value['required'] = ['direction']
    else:
        value['graphs'] = []
    doc = document()
    with pytest.raises(Exception):
        qr._validate_advice(value, qr._snapshot(doc, SHA))
    assert doc == document()


@pytest.mark.parametrize('options,reason', [({'ok': False}, 'transport_failed'),
                                         ({'truncated': True}, 'truncated')])
def test_remote_failure_does_not_remove_local_reference_or_block_recognition(options, reason):
    result = qr.prepare_question_reference(document(), budget=budget(),
                                           completion=FakeCompletion(advice(), **options))
    assert result['status'] == 'local_only' and result['reason'] == reason
    assert result['subquestions'] == [] and result['focus'] == []
    assert result['local_hints']['rule_index_used'] is True


def test_invalid_remote_output_is_nonblocking_but_not_certified():
    result = qr.prepare_question_reference(document(), budget=budget(),
                                           completion=FakeCompletion({'graphs': []}))
    assert result['status'] == 'local_only' and result['reason'] == 'invalid_advice'
    assert result['subquestions'] == []
    assert result['metrics'][0]['response_received'] is True
    assert result['validation_audit']['code'] == 'schema_invalid'
    assert result['metrics'][0]['advice_validation'] == result['validation_audit']


def test_missing_credentials_does_not_spend_a_model_call(monkeypatch):
    import ai
    monkeypatch.setattr(ai, 'DEEPSEEK_API_KEY', '')
    ledger = budget()
    result = qr.prepare_question_reference(document(), budget=ledger)
    assert result['reason'] == 'deepseek_unavailable'
    assert ledger.remaining == 10 and ledger.metrics == []


def test_empty_question_does_not_request_a_completion():
    doc = document()
    doc['body_text'], doc['text_context'] = '', {}
    ledger = budget()
    result = qr.prepare_question_reference(doc, budget=ledger, completion=FakeCompletion(None))
    assert result['status'] == 'empty'
    assert ledger.remaining == 10 and ledger.metrics == []
    assert doc['graphs'][0]['edges'][0]['color'] == 'blue'


def test_legend_without_question_can_supply_non_authoritative_reference():
    doc = document()
    doc['body_text'] = ''
    value = {'subquestions': [], 'references': [], 'focus': [], 'unresolved': []}
    value['references'].append({'kind': 'legend', 'source_spans': [
        {'block_id': 'legend:1', 'start': 0, 'end': 9, 'quote': '蓝色表示可选线路'}],
        'graph_ids': ['G1'], 'description': '请对照图例核对颜色'})
    # End must be an exact Unicode offset, not a tokenizer/UTF-8 byte offset.
    value['references'][0]['source_spans'][0]['end'] = len('蓝色表示可选线路')
    result = qr.prepare_question_reference(doc, budget=budget(), completion=FakeCompletion(value))
    assert result['status'] == 'ready' and result['references'][0]['kind'] == 'legend'


def test_remote_slot_busy_leaves_main_model_budget_untouched():
    ledger = budget()
    ledger._remote_slots.acquire()
    ledger._remote_slots.acquire()
    try:
        result = qr.prepare_question_reference(document(), budget=ledger, completion=FakeCompletion(advice()))
    finally:
        ledger._remote_slots.release()
        ledger._remote_slots.release()
    assert result['reason'] == 'remote_slot_busy'
    assert ledger.remaining == 10 and ledger.metrics == []


def test_small_remaining_budget_is_reserved_for_full_image_reading():
    ledger = budget()
    ledger.remaining = 3
    result = qr.prepare_question_reference(document(), budget=ledger, completion=FakeCompletion(advice()))
    assert result['reason'] == 'main_calls_reserved'
    assert ledger.remaining == 3 and ledger.metrics == []


@pytest.mark.parametrize('change', ['body', 'label_case', 'node_id', 'graph_id', 'caption', 'legend', 'source'])
def test_changed_semantic_identity_invalidates_reference(change):
    doc = document()
    reference = bound_reference(doc)
    if change == 'body':
        doc['body_text'] = doc['body_text'].replace('v₁', 'v₃')
    elif change == 'label_case':
        doc['graphs'][0]['vertices'][0]['label'] = 'V₁'
    elif change == 'node_id':
        doc['graphs'][0]['vertices'][0]['id'] = 'new'
    elif change == 'graph_id':
        doc['graphs'][0]['id'] = 'G2'
    elif change == 'caption':
        doc['graphs'][0]['name'] = '(b)'
    elif change == 'legend':
        doc['text_context']['legends'][0]['text'] = '红色表示可选线路'
    else:
        doc['source_sha256'] = 'b' * 64
    assert qr.question_reference_for_document(reference, doc, source_sha256=SHA) is None


def test_geometry_edges_and_input_order_do_not_invalidate_reference():
    doc = document()
    reference = bound_reference(doc)
    doc['graphs'][0]['edges'] = []
    doc['graphs'][0]['bbox'] = [0, 0, 1000, 1000]
    doc['graphs'][0]['vertices'].reverse()
    doc['graphs'][0]['vertices'][0]['x'] = 600
    safe = qr.question_reference_for_document(reference, doc, source_sha256=SHA)
    assert safe is not None
    assert 'metrics' not in safe and 'tool_evidence' not in safe
    safe['subquestions'].clear()
    assert len(reference['subquestions']) == 2


def test_reference_cannot_use_its_own_source_hash_as_proof():
    doc = document()
    reference = bound_reference(doc)
    assert qr.question_reference_for_document(reference, doc) is None
    doc['source_sha256'] = SHA
    assert qr.question_reference_for_document(reference, doc) is not None


def test_model_side_control_keys_are_not_forwarded_even_in_signed_shape():
    doc = document()
    reference = bound_reference(doc)
    reference.update(field_policy={'optional': ['color']}, graphs=[], local_hints={'drop': 'G1'})
    safe = qr.question_reference_for_document(reference, doc, source_sha256=SHA)
    assert safe is not None
    assert not any(key in safe for key in ('field_policy', 'graphs'))
    assert safe['local_hints'] == {}
    reference['cannot_drop_content'] = False
    assert qr.question_reference_for_document(reference, doc, source_sha256=SHA) is None


def test_actual_registry_and_local_teaching_rules_are_used(monkeypatch):
    import teaching
    observed = []
    original_call = ToolRegistry.call
    original_teaching = teaching.analyze_question

    def call(self, name, arguments, **kwargs):
        observed.append((name, arguments, kwargs['role']))
        return original_call(self, name, arguments, **kwargs)

    def classify(text):
        observed.append(('teaching', len(text)))
        return original_teaching(text)

    monkeypatch.setattr(ToolRegistry, 'call', call)
    monkeypatch.setattr(teaching, 'analyze_question', classify)
    import ai
    monkeypatch.setattr(ai, 'DEEPSEEK_API_KEY', '')
    result = qr.prepare_question_reference(document(), budget=budget())
    assert observed[0] == ('text.question_reference_hints', {}, 'semantic_review')
    assert observed[1][0] == 'teaching'
    assert result['tool_evidence'][0]['status'] == 'success'
    assert 'quote' not in json.dumps(result['tool_evidence'])


def test_tool_role_and_schema_denial_are_real():
    registry = qr.register_question_reference_tools(ToolRegistry())
    context = ToolContext(source_sha256=SHA, data={'snapshot': qr._snapshot(document(), SHA)})
    assert registry.call('text.question_reference_hints', {}, role='connections', context=context)['status'] == 'denied'
    invalid = registry.call('text.question_reference_hints', {'drop': 'color'}, role='semantic_review', context=context)
    assert invalid['error']['code'] == 'invalid_arguments'


def test_formula_parser_is_scoped_syntax_only_and_never_evaluates_code():
    doc = document()
    doc['body_text'] = '对比 $n+1$ 和 $__import__("os")$，正文 x+y 不启动公式解析。'
    snapshot = qr._snapshot(doc, SHA)
    result = qr._local_hints({}, context=ToolContext(data={'snapshot': snapshot}))
    assert len(result['formula_hints']) == 2
    assert result['formula_hints'][0]['status'] == 'syntax_only'
    assert result['formula_hints'][0]['symbols'] == ['n']
    assert result['formula_hints'][1]['status'] == 'unsupported_syntax'
    assert 'answer' not in result


def test_capacity_and_bad_source_never_start_a_remote_call():
    for change in ('text', 'source'):
        doc, ledger = document(), budget()
        if change == 'text':
            doc['body_text'] = 'x' * (qr.MAX_TEXT + 1)
        else:
            doc['source_sha256'] = 'b' * 64
        result = qr.prepare_question_reference(doc, budget=ledger, completion=FakeCompletion(advice()))
        assert result['status'] == 'unavailable'
        assert ledger.remaining == 10 and ledger.metrics == []


def test_start_failure_records_reservation_without_claiming_a_request():
    ledger = budget()
    result = qr.prepare_question_reference(document(), budget=ledger, completion=lambda *a, **k: {})
    assert result['status'] == 'local_only' and result['reason'] == 'worker_start_failed'
    assert ledger.remaining == 9 and len(ledger.metrics) == 1
    assert ledger.metrics[0]['request_attempted'] is False
    assert ledger.metrics[0]['reserved_calls'] == 1
    assert ledger._remote_slots.acquire(blocking=False)
    assert ledger._remote_slots.acquire(blocking=False)
    ledger._remote_slots.release()
    ledger._remote_slots.release()


def test_local_only_reference_has_bounded_knowledge_hints(monkeypatch):
    import ai
    monkeypatch.setattr(ai, 'DEEPSEEK_API_KEY', '')
    doc = document()
    result = qr.prepare_question_reference(doc, budget=budget())
    safe = qr.question_reference_for_document(result, doc, source_sha256=SHA)
    assert safe is not None and safe['status'] == 'local_only'
    assert safe['local_hints']['rule_index_used'] is True
    assert 'tool_evidence' not in safe and 'metrics' not in safe


def single_quote_advice(quote, **offsets):
    return {'subquestions': [{'id': 'q1', 'source_spans': [
        {'block_id': 'body', 'quote': quote, **offsets}],
        'graph_ids': ['G1'], 'summary': '核对原文引用'}],
        'references': [], 'focus': [], 'unresolved': []}


@pytest.mark.parametrize('offsets', [{}, {'start': -1, 'end': 500},
                                   {'start': 0}, {'end': 1}])
def test_unique_unicode_quote_gets_program_computed_offsets_without_text_edits(offsets):
    doc = document()
    doc['body_text'] = '🔵第①问：求 v₃ 的度数；第②问：α₂≠α³。'
    quote = '求 v₃ 的度数'
    proposal = single_quote_advice(quote, **offsets)
    before = copy.deepcopy(proposal)
    canonical, audit = qr._canonicalize_advice(proposal, qr._snapshot(doc, SHA))
    span = canonical['subquestions'][0]['source_spans'][0]
    start = doc['body_text'].index(quote)
    assert span == {'block_id': 'body', 'quote': quote, 'start': start, 'end': start + len(quote)}
    assert start != len(doc['body_text'][:start].encode('utf-8'))
    assert proposal == before and doc['body_text'][span['start']:span['end']] == quote
    assert audit['normalized_spans'] == 1 and audit['validated_spans'] == 1
    assert quote not in json.dumps(audit, ensure_ascii=False)
    qr._VALIDATOR.validate(canonical)


def test_correct_legacy_offsets_are_preserved_including_repeated_quote():
    doc = document()
    doc['body_text'] = '求度数；求度数。'
    quote, start = '求度数', 4
    proposal = single_quote_advice(quote, start=start, end=start + len(quote))
    canonical, audit = qr._canonicalize_advice(proposal, qr._snapshot(doc, SHA))
    assert canonical == proposal
    assert audit['normalizations'] == [] and audit['normalized_spans'] == 0


@pytest.mark.parametrize('offsets', [{}, {'start': 1, 'end': 3}, {'start': 0}])
def test_repeated_quote_without_valid_full_offsets_is_never_assigned_first(offsets):
    doc = document()
    doc['body_text'] = '求度数；求度数。'
    with pytest.raises(qr.AdviceValidationError) as caught:
        qr._canonicalize_advice(single_quote_advice('求度数', **offsets), qr._snapshot(doc, SHA))
    assert caught.value.code == 'ambiguous_literal_quote'


def test_overlapping_quote_occurrences_are_ambiguous():
    doc = document()
    doc['body_text'] = 'aaaa'
    with pytest.raises(qr.AdviceValidationError, match='ambiguous_literal_quote'):
        qr._canonicalize_advice(single_quote_advice('aaa'), qr._snapshot(doc, SHA))


@pytest.mark.parametrize('quote', ['求v₅的度数', '求V₃的度数', '求v3的度数', '求v³的度数', '求 v₃ 的度数'])
def test_quote_matching_does_not_normalize_semantic_characters_or_spaces(quote):
    doc = document()
    doc['body_text'] = '求v₃的度数'
    with pytest.raises(qr.AdviceValidationError, match='literal_quote_not_found'):
        qr._canonicalize_advice(single_quote_advice(quote), qr._snapshot(doc, SHA))


@pytest.mark.parametrize('offsets', [{'start': True, 'end': 2}, {'start': None}, {'end': '3'}])
def test_malformed_offset_types_still_rejected_even_for_unique_quote(offsets):
    with pytest.raises(qr.ValidationError):
        qr._canonicalize_advice(single_quote_advice('(1)', **offsets), qr._snapshot(document(), SHA))


def test_canonical_consumer_does_not_relocate_or_complete_cached_spans():
    doc = document()
    reference = bound_reference(doc)
    span = reference['subquestions'][0]['source_spans'][0]
    span['start'] = 1
    assert qr.question_reference_for_document(reference, doc, source_sha256=SHA) is None
    del span['start']
    assert qr.question_reference_for_document(reference, doc, source_sha256=SHA) is None


def test_spawned_quote_only_response_produces_canonical_source_bound_reference():
    doc = document()
    quote = doc['body_text'][:doc['body_text'].index('(2)')]
    ledger = budget()
    result = qr.prepare_question_reference(doc, budget=ledger,
                                           completion=FakeCompletion(single_quote_advice(quote)))
    assert result['status'] == 'ready'
    assert result['subquestions'][0]['source_spans'][0]['end'] == len(quote)
    assert result['validation_audit']['normalizations'][0]['action'] == 'offsets_generated'
    assert ledger.remaining == 9 and len(ledger.metrics) == 1
    assert ledger.metrics[0]['request_attempted'] is True
    assert ledger.metrics[0]['response_received'] is True
    assert ledger.metrics[0]['worker_reaped'] is True
    assert qr.question_reference_for_document(result, doc, source_sha256=SHA) is not None


@pytest.mark.parametrize('change,code', [
    ('unknown_block', 'unknown_source_block'),
    ('unknown_graph', 'unknown_graph_reference'),
    ('fake_quote', 'literal_quote_not_found'),
    ('schema', 'schema_invalid'),
])
def test_remote_rejection_exposes_safe_specific_reason_without_private_values(change, code):
    proposal = single_quote_advice('(1)')
    item = proposal['subquestions'][0]
    private = 'PRIVATE_REJECTED_VALUE_DO_NOT_LOG'
    if change == 'unknown_block':
        item['source_spans'][0]['block_id'] = private
    elif change == 'unknown_graph':
        item['graph_ids'] = [private]
    elif change == 'fake_quote':
        item['source_spans'][0]['quote'] = private
    else:
        item[private] = private
    ledger = budget()
    result = qr.prepare_question_reference(document(), budget=ledger, completion=FakeCompletion(proposal))
    assert result['status'] == 'local_only' and result['reason'] == 'invalid_advice'
    assert result['validation_audit']['code'] == code
    assert result['subquestions'] == []
    audit = json.dumps({'audit': result['validation_audit'], 'metrics': ledger.metrics,
                        'events': ledger.events}, ensure_ascii=False)
    assert private not in audit and document()['body_text'] not in audit
    assert ledger.remaining == 9 and len(ledger.metrics) == 1
    assert ledger.metrics[0]['response_received'] is True


@dataclass
class InvalidJsonCompletion:
    def __call__(self, messages, **kwargs):
        assert kwargs['retries'] == 0
        assert not kwargs['cancelled']()
        return {'ok': True, 'content': '{PRIVATE_INVALID_JSON_MUST_NOT_LEAK',
                'choice': {'finish_reason': 'stop'}}


def test_json_syntax_failure_has_own_safe_code_and_does_not_trigger_retry():
    ledger = budget()
    result = qr.prepare_question_reference(document(), budget=ledger, completion=InvalidJsonCompletion())
    assert result['validation_audit'] == {'status': 'rejected', 'code': 'invalid_json',
                                          'path': [], 'character_position': 1}
    assert result['reason'] == 'invalid_advice' and len(ledger.metrics) == 1
    assert 'PRIVATE_INVALID_JSON' not in json.dumps(result, ensure_ascii=False)


def test_normalization_audit_is_bounded_and_contains_only_locations_and_actions():
    proposal = single_quote_advice('(1)')
    original = proposal['subquestions'][0]
    proposal['subquestions'] = [{**copy.deepcopy(original), 'id': f'q{i}'} for i in range(24)]
    canonical, audit = qr._canonicalize_advice(proposal, qr._snapshot(document(), SHA))
    assert len(canonical['subquestions']) == 24
    assert audit['normalized_spans'] == 24 and len(audit['normalizations']) == 12
    assert audit['normalizations_truncated'] is True
    assert all(set(row) == {'path', 'action'} for row in audit['normalizations'])


def test_relocated_reference_still_invalidates_on_body_catalog_or_source_change():
    doc = document()
    canonical, audit = qr._canonicalize_advice(single_quote_advice('v₁的度数', start=0, end=1),
                                             qr._snapshot(doc, SHA))
    result = {**qr._base(qr._snapshot(doc, SHA), budget()), **canonical,
              'status': 'ready', 'validation_audit': audit}
    handle = qr.QuestionReferenceHandle(result)
    handle._done.set()
    assert qr.get_ready_question_reference(handle, document=doc, source_sha256=SHA)['status'] == 'ready'
    for change in ('body', 'graph', 'source'):
        changed = copy.deepcopy(doc)
        if change == 'body':
            changed['body_text'] = changed['body_text'].replace('v₁', 'v₅')
        elif change == 'graph':
            changed['graphs'][0]['vertices'][0]['label'] = 'V₁'
        else:
            changed['source_sha256'] = 'b' * 64
        stale = qr.get_ready_question_reference(handle, document=changed, source_sha256=SHA)
        assert stale['status'] == 'stale' and stale['subquestions'] == []
        assert stale['validation_audit'] == audit
        assert qr.question_reference_for_document(result, changed, source_sha256=SHA) is None
