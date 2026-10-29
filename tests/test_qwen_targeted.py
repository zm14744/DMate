"""Safety and routing contracts, independent of private accuracy references."""
import base64
import copy
import hashlib
import io
import json
from unittest.mock import Mock

import pytest
from PIL import Image

import graph_qwen_targeted as pipeline
from graph_agent_runtime import AgentBudget, AgentCancelled
from graph_qwen_targeted_review import plan_reviews, merge_source_review, source_jobs
from vision_provider import QWEN38_FLASH_MODEL, VisionError, VisionProvider
from test_ocr_application_contract import application


def graph():
    return {'id': 'G1', 'directed': True, 'weighted': False, 'bbox': [0, 0, 1, 1],
            'vertices': [{'id': vid, 'label': vid, 'x': x, 'y': .5}
                         for vid, x in [('a', .1), ('b', .5), ('c', .9)]],
            'edges': [{'id': 'old', 'from': 'a', 'to': 'b', 'direction': 'forward',
                       'weight': None, 'edge_label': None}]}


def pixels():
    with Image.new('RGB', (80, 60), 'white') as image:
        out = io.BytesIO(); image.save(out, format='PNG'); return out.getvalue()


def evidence(g):
    return {'graphs': [g], 'line_path_evidence': [{'id': 'G1', 'paths': [
        {'from': 'a', 'to': 'c', 'score': .91, 'path': [[.1, .5], [.9, .5]]}]}]}


def reply(*, flow_a='out', flow_c='in', weight=None):
    return {'graphs': [{'graph_id': 'G1', 'reads': [
        {'source_id': 'a', 'complete': True, 'edges': [
            {'to': 'c', 'flow': flow_a, 'weight': weight, 'edge_label': None}]},
        {'source_id': 'c', 'complete': True, 'edges': [
            {'to': 'a', 'flow': flow_c, 'weight': weight, 'edge_label': None}]}]}]}


def test_candidate_only_nominates_and_does_not_leak_direction_to_reader():
    g = graph(); g['directed'] = False; g['edges'][0]['direction'] = 'undirected'
    ev = evidence(g)
    ev['line_path_evidence'][0]['paths'].append({'from': 'a', 'to': 'b', 'score': .9,
        'arrow_candidate': {'from': 'b', 'to': 'a', 'score': .81}})
    plans = plan_reviews([g], ev)
    assert plans[0]['target_pairs'] == [['a', 'b'], ['a', 'c']]
    assert plans[0]['type_dispute'] is True
    jobs = source_jobs([g], plans)
    assert not {'directed', 'edges', 'arrow_candidate'} & jobs[0].keys()
    assert g['edges'] == graph()['edges'][:0] + [dict(graph()['edges'][0], direction='undirected')]


def test_single_false_positive_below_threshold_does_not_call_reader():
    g = graph(); ev = evidence(g); ev['line_path_evidence'][0]['paths'][0]['score'] = .4
    assert plan_reviews([g], ev) == []


def test_rough_unbound_positions_can_nominate_a_weak_stroke_without_accepting_it():
    g = graph(); ev = evidence(g)
    ev['line_path_evidence'][0]['paths'][0]['score'] = .6
    assert plan_reviews([g], ev) == []
    g['marker_grounding'] = {'untrusted_vertices': [
        {'vertex': 'c', 'reason': 'no_reliable_local_marker'}]}
    plans = plan_reviews([g], ev)
    assert plans[0]['missing_pairs'] == [['a', 'c']]
    assert g['edges'] == graph()['edges']


def test_only_two_endpoint_agreement_adds_one_stroke_and_preserves_identities():
    g = graph(); plans = plan_reviews([g], evidence(g))
    updated, issues, changes = merge_source_review([g], plans, reply(weight=0))
    assert issues == [] and len(changes) == 1
    assert updated[0]['vertices'] == g['vertices']
    assert updated[0]['edges'][0] == g['edges'][0]
    assert updated[0]['edges'][1] == {'id': 'r1', 'from': 'a', 'to': 'c',
        'direction': 'forward', 'weight': 0, 'edge_label': None}
    assert len(g['edges']) == 1  # snapshots never mutate


def test_both_readers_can_reject_a_spurious_path_without_adding_or_warning():
    g = graph(); result = reply()
    for row in result['graphs'][0]['reads']: row['edges'] = []
    updated, issues, changes = merge_source_review([g], plan_reviews([g], evidence(g)), result)
    assert updated == [g] and issues == changes == []


@pytest.mark.parametrize('mode', ['reverse', 'unknown', 'one_absent', 'incomplete', 'invalid_weight'])
def test_disagreement_or_unknown_never_becomes_a_confirmed_new_edge(mode):
    g = graph(); result = reply()
    rows = result['graphs'][0]['reads']
    if mode == 'reverse': rows[1]['edges'][0]['flow'] = 'out'
    if mode == 'unknown': rows[0]['edges'][0]['flow'] = 'unknown'
    if mode == 'one_absent': rows[0]['edges'] = []
    if mode == 'incomplete': rows[1]['complete'] = False
    if mode == 'invalid_weight': rows[0]['edges'][0]['weight'] = {'code': 'not a scalar'}
    updated, issues, changes = merge_source_review([g], plan_reviews([g], evidence(g)), result)
    assert updated == [g] and issues and changes == []


def test_unrequested_or_duplicate_sources_are_rejected_as_a_whole():
    g = graph(); plans = plan_reviews([g], evidence(g)); result = reply()
    result['graphs'][0]['reads'].append(copy.deepcopy(result['graphs'][0]['reads'][0]))
    with pytest.raises(ValueError, match='source_mismatch'):
        merge_source_review([g], plans, result)


def test_disputed_type_does_not_fall_back_to_confirmed_undirected():
    g = graph(); g['directed'] = False; g['edges'][0]['direction'] = 'undirected'
    ev = {'line_path_evidence': [{'id': 'G1', 'paths': [
        {'from': 'a', 'to': 'b', 'score': .9,
         'arrow_candidate': {'from': 'a', 'to': 'b', 'score': .8}}]}]}
    result = {'graphs': [{'graph_id': 'G1', 'reads': []}]}
    updated, issues, _ = merge_source_review([g], plan_reviews([g], ev), result)
    assert updated[0]['edges'][0]['direction'] == 'unknown'
    assert updated[0]['directed'] is None and issues


def test_decimal_spelling_equivalence_allows_weight_binding_not_formula_solving():
    g = graph(); result = reply(weight=6)
    result['graphs'][0]['reads'][1]['edges'][0]['weight'] = '6.0'
    updated, issues, _ = merge_source_review([g], plan_reviews([g], evidence(g)), result)
    assert issues == [] and updated[0]['edges'][1]['weight'] == 6
    result['graphs'][0]['reads'][1]['edges'][0]['weight'] = '3+3'
    assert merge_source_review([g], plan_reviews([g], evidence(g)), result)[1]


@pytest.mark.parametrize('problem', ['endpoint', 'node_id', 'edge_id', 'nonfinite'])
def test_schema_never_silently_drops_malformed_graph_facts(problem):
    g = graph()
    if problem == 'endpoint': g['edges'][0]['to'] = 'missing'
    if problem == 'node_id': g['vertices'][1]['id'] = 'a'
    if problem == 'edge_id': g['edges'].append(copy.deepcopy(g['edges'][0]))
    if problem == 'nonfinite': g['vertices'][0]['x'] = float('nan')
    with pytest.raises(ValueError): pipeline.validate_draft({'graphs': [g]})


def test_missing_display_edge_ids_do_not_collide_with_later_explicit_ids():
    g=graph();g['edges']=[{'from':'a','to':'b','direction':'forward'},
                         {'id':'e1','from':'b','to':'c','direction':'forward'}]
    pipeline.validate_draft({'graphs':[g]})
    assert len({e['id'] for e in g['edges']})==2
    assert g['edges'][1]['id']=='e1' and len(g['edges'])==2


def fake_model(document, metrics):
    def read(prompt, images, budget):
        budget.take()
        budget.metrics.append({'model': QWEN38_FLASH_MODEL, 'thinking': True})
        metrics.append((prompt, images))
        return copy.deepcopy(document)
    return read


def test_pipeline_returns_text_and_graph_in_the_same_read_without_extra_ocr(monkeypatch):
    g = graph(); seen = []
    monkeypatch.setattr(pipeline, '_candidates', lambda args, *, context: {
        'graphs': context.data['graphs'], 'line_path_evidence': []})
    forbidden = Mock(side_effect=AssertionError('no review without evidence'))
    result = pipeline.recognize_qwen_targeted(pixels(), provider=fake_model(
        {'graphs': [g], 'body_text': '求从 a 到 b 的最短路径。'}, seen), review_provider=forbidden)
    assert len(seen) == 1 and len(seen[0][1]) == 1
    assert result['text'] == result['document']['body_text'] == '求从 a 到 b 的最短路径。'
    assert result['diagnostics']['text_ocr_calls'] == 0
    assert result['document']['graphs'][0]['edges'] == g['edges']
    assert result['diagnostics']['validation']['networkx'] == 'passed'
    assert result['diagnostics']['validation']['graphs'][0]['isolated_vertices'] == ['c']
    assert result['recognition_status'] == 'complete'
    assert result['diagnostics']['performance']['browser_render_included'] is False
    forbidden.assert_not_called()


def test_full_chain_scopes_review_and_binds_crops_to_original(monkeypatch):
    g = graph(); seen = []
    monkeypatch.setattr(pipeline, '_candidates', lambda args, *, context: evidence(context.data['graphs'][0]))
    result = pipeline.recognize_qwen_targeted(pixels(), provider=fake_model({'graphs': [g]}, seen),
                                              review_provider=fake_model(reply(), seen))
    assert result['recognition_status'] == 'complete'
    assert len(seen) == 2 and len(seen[1][1]) == 3
    assert seen[0][1][0] == seen[1][1][0]  # same original overview
    assert len(result['document']['graphs'][0]['edges']) == 2
    audits = result['diagnostics']['tool_audit']
    assert all(r['status'] == 'success' for r in audits)
    assert {r['source_sha256'] for r in audits} == {hashlib.sha256(pixels()).hexdigest()}
    assert {r['tool'] for r in audits} == {'image.qwen_path_questions',
        'image.qwen_source_views', 'graph.qwen_final_check'}


@pytest.mark.parametrize('connected', [True, False])
def test_two_regions_merge_only_after_a_cross_stroke_is_read_at_both_ends(monkeypatch, connected):
    left = graph()
    right = {'id': 'G2', 'name': None, 'directed': True, 'weighted': False,
             'bbox': [.5, 0, 1, 1], 'vertices': [
                 {'id': 'd', 'label': 'd', 'x': .6, 'y': .3},
                 {'id': 'e', 'label': 'e', 'x': .8, 'y': .3}],
             'edges': [{'id': 'old', 'from': 'd', 'to': 'e', 'direction': 'forward', 'weight': None}]}
    def local(args, *, context):
        graphs = context.data['graphs']; combined, owners = pipeline._combined_context(graphs)
        return {'graphs': graphs, 'line_path_evidence': [], 'cross_region_context': {
            'graph': combined, 'owners': owners,
            'paths': [{'from': 'b', 'to': 'd', 'score': .95, 'path': [[.5,.5],[.6,.3]]}]}}
    monkeypatch.setattr(pipeline, '_candidates', local)
    rows = [{'source_id': 'b', 'complete': True, 'edges': [
        {'to': 'd', 'flow': 'out', 'weight': None}] if connected else []},
        {'source_id': 'd', 'complete': True, 'edges': [
        {'to': 'b', 'flow': 'in', 'weight': None}] if connected else []}]
    result = pipeline.recognize_qwen_targeted(pixels(),
        provider=fake_model({'graphs': [left, right]}, []),
        review_provider=fake_model({'graphs': [{'graph_id': 'cross_region_review', 'reads': rows}]}, []))
    graphs = result['document']['graphs']
    assert len(graphs) == (1 if connected else 2)
    if connected:
        assert len(graphs[0]['vertices']) == 5 and len(graphs[0]['edges']) == 3
        assert {v['label'] for v in graphs[0]['vertices']} == {'a','b','c','d','e'}
        assert any(e['from']=='b' and e['to']=='d' for e in graphs[0]['edges'])
        assert graphs[0]['id']=='G1'
    else:
        # Presentation references/positions are enriched before any review;
        # a rejected cross stroke must retain that exact draft and topology.
        assert graphs == pipeline.validate_draft({'graphs': copy.deepcopy([left, right])})['graphs']


def test_two_weak_arrow_locations_trigger_type_review_without_supplying_direction():
    g = graph(); g['directed'] = False; g['edges'][0]['direction'] = 'undirected'
    g['edges'].append({'id': 'bc', 'from': 'b', 'to': 'c', 'direction': 'undirected'})
    def path(a,b):return {'from': a, 'to': b, 'score': .9,
                        'arrow_candidate': {'from': b, 'to': a, 'score': .55}}
    ev = {'line_path_evidence': [{'id':'G1', 'paths': [path('a','b')]}]}
    assert plan_reviews([g],ev)==[]
    ev['line_path_evidence'][0]['paths'].append(path('b','c'))
    plans=plan_reviews([g],ev)
    assert plans[0]['type_dispute'] is True
    assert 'arrow_candidate' not in json.dumps(source_jobs([g],plans))


def test_repeated_undirected_answer_keeps_pixel_arrow_disagreement_visible():
    g=graph();g['directed']=False;g['edges'][0]['direction']='undirected'
    ev={'line_path_evidence':[{'id':'G1','paths':[{'from':'a','to':'b','score':1,
         'arrow_candidate':{'from':'a','to':'b','score':.8}}]}]}
    rows=[{'source_id':a,'complete':True,'edges':[{'to':b,'flow':'undirected'}]}
          for a,b in [('a','b'),('b','a')]]
    updated,issues,_=merge_source_review([g],plan_reviews([g],ev),
        {'graphs':[{'graph_id':'G1','reads':rows}]})
    assert updated[0]['directed'] is None
    assert updated[0]['edges'][0]['direction']=='unknown'
    assert any(i['kind']=='arrow_type_unresolved' for i in issues)


@pytest.mark.parametrize('failure', [VisionError('transport_failed'), VisionError('truncated_output'),
                                     TimeoutError(), ValueError('invalid review')])
def test_failed_necessary_review_keeps_draft_but_cannot_claim_success(failure, monkeypatch):
    g = graph(); seen = []
    monkeypatch.setattr(pipeline, '_candidates', lambda args, *, context: evidence(context.data['graphs'][0]))
    result = pipeline.recognize_qwen_targeted(pixels(), provider=fake_model({'graphs': [g]}, seen),
                                              review_provider=Mock(side_effect=failure))
    assert result['document']['graphs'] == pipeline.validate_draft({'graphs': copy.deepcopy([g])})['graphs']
    assert result['recognition_status'] == 'partial' and result['review']['required']
    assert result['diagnostics']['performance']['complete_within_target'] is False
    assert result['diagnostics']['validation']['json_schema'] == 'passed'


def test_parallel_edges_loops_and_isolates_survive_final_networkx_check(monkeypatch):
    g = graph(); g['edges'].extend([dict(g['edges'][0], id='parallel'),
                                  dict(g['edges'][0], id='loop', **{'to': 'a'})])
    monkeypatch.setattr(pipeline, '_candidates', lambda args, *, context: {
        'graphs': context.data['graphs'], 'line_path_evidence': []})
    result = pipeline.recognize_qwen_targeted(pixels(), provider=fake_model({'graphs': [g]}, []))
    assert result['diagnostics']['validation']['graphs'][0] == {
        'graph_id': 'G1', 'vertices': 3, 'edges': 3, 'isolated_vertices': ['c']}


def test_cancellation_is_not_downgraded_to_partial():
    remote = Mock()
    with pytest.raises(AgentCancelled):
        pipeline.recognize_qwen_targeted(pixels(), provider=remote, cancelled=lambda: True)
    remote.assert_not_called()


def test_text_only_scan_preserves_all_subquestions_without_starting_review(monkeypatch):
    monkeypatch.setattr(pipeline, '_candidates', lambda args, *, context: {
        'graphs': [], 'line_path_evidence': []})
    body='设集合 A={1,2}。（1）求幂集。（2）证明 A 不为空集。'
    reviewer=Mock(side_effect=AssertionError('text-only image needs no graph review'))
    result=pipeline.recognize_qwen_targeted(pixels(),provider=fake_model({'graphs':[],'body_text':body},[]),review_provider=reviewer)
    assert result['text']==body and result['document']['body_text']==body
    assert result['recognition_status']=='complete'
    reviewer.assert_not_called()


def test_local_adapter_shares_unit_bounds_and_serializes_native_cv_values(monkeypatch):
    import numpy as np
    import graph_marker_grounding
    import graph_line_tracer
    from dmate_tool_registry import ToolContext
    g = graph()
    def grounding(raw, graphs):
        assert graphs[0]['bbox'] == [0, 0, 1, 1]
        output = copy.deepcopy(graphs)
        output[0]['marker_grounding'] = {'checked': np.bool_(True), 'size': (80, 60)}
        return output
    monkeypatch.setattr(graph_marker_grounding, 'ground_nodes', grounding)
    monkeypatch.setattr(graph_line_tracer, 'attach_line_evidence', lambda raw, value, **k: {
        **value, 'line_path_evidence': [{'id': 'G1', 'paths': [
            {'from': 'a', 'to': 'c', 'score': np.float64(.9)}]}]})
    raw = pixels()
    result = pipeline._registry().call('image.qwen_path_questions', {}, role='semantic_review',
        context=ToolContext(source_sha256=hashlib.sha256(raw).hexdigest(),
            data={'raw': raw, 'graphs': [g], 'budget': AgentBudget(seconds=20)}))
    assert result['ok'] is True
    assert result['result']['graphs'][0]['marker_grounding'] == {'checked': True, 'size': [80, 60]}
    assert result['result']['graphs'][0]['edges'] == g['edges']


def test_auto_upload_routes_to_editable_qwen_without_text_or_legacy_ocr(application, monkeypatch, tmp_path):
    module, client, _ = application
    monkeypatch.setenv('DMATE_GRAPH_CONFIRMATION_DB', str(tmp_path/'tasks.sqlite3'))
    seen = []
    def recognition(raw, **kwargs):
        seen.append((raw, kwargs))
        return {'workflow_profile': 'qwen_targeted', 'text': '',
                'document': {'body_text': '', 'graphs': [graph()]}, 'recognition_status': 'complete'}
    monkeypatch.setattr(pipeline, 'recognize_qwen_targeted', recognition)
    assert client.get('/graph/session').status_code == 200
    result = client.post('/ocr', data={'image': (io.BytesIO(pixels()), 'diagram.png'),
        'workflow': 'auto_graph', 'request_id': 'qwen-upload'} )
    assert result.status_code == 200
    value = result.get_json()
    assert value['document']['graphs'][0]['edges'] == graph()['edges']
    assert value['source_sha256'] == hashlib.sha256(pixels()).hexdigest()
    assert value['text'] == '' and value['request_id'] == 'qwen-upload'
    assert len(seen) == 1 and callable(seen[0][1]['cancelled'])


def test_main_model_fault_is_http_failure_and_releases_upload_slot(application, monkeypatch, tmp_path):
    from graph_upload_tasks import UPLOAD_TASKS
    _, client, _ = application
    monkeypatch.setenv('DMATE_GRAPH_CONFIRMATION_DB', str(tmp_path/'tasks.sqlite3'))
    monkeypatch.setattr(pipeline, 'recognize_qwen_targeted', Mock(side_effect=VisionError('transport_failed')))
    assert client.get('/graph/session').status_code == 200
    before = UPLOAD_TASKS.active_count()
    result = client.post('/ocr', data={'image': (io.BytesIO(pixels()), 'diagram.png'),
        'workflow': 'auto_graph', 'request_id': 'qwen-fault'})
    assert result.status_code == 503 and result.get_json()['recognition_status'] == 'failed'
    assert UPLOAD_TASKS.active_count() == before


@pytest.mark.parametrize('returned,valid', [(QWEN38_FLASH_MODEL, True),
    (QWEN38_FLASH_MODEL+'-20261001', True), ('qwen3-vl-plus', False), (None, False)])
def test_qwen38_requires_actual_model_identity_and_explicit_thinking(monkeypatch, returned, valid):
    import ai
    monkeypatch.setattr(ai, 'API_KEY', 'fixture-only')
    transport = Mock(return_value=(200, '', {'model': returned, 'choices': [
        {'message': {'content': '```json\n{"graphs":[]}\n```'}, 'finish_reason': 'stop'}]}))
    provider = VisionProvider('qwen', model=QWEN38_FLASH_MODEL, thinking=True, transport=transport)
    url = 'data:image/png;base64,'+base64.b64encode(pixels()).decode()
    budget = AgentBudget(seconds=10, calls=1)
    if valid: assert provider('json', [url], budget) == {'graphs': []}
    else:
        with pytest.raises(VisionError, match='model_identity_unverified' if returned is None else 'model_mismatch'):
            provider('json', [url], budget)
    payload = transport.call_args.args[0]
    assert payload['model'] == QWEN38_FLASH_MODEL and payload['enable_thinking'] is True
    assert 'response_format' not in payload and transport.call_count == 1
