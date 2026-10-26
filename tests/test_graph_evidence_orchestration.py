"""Integration checks for the new two-request contract; no live model calls."""
from unittest.mock import patch

import pytest

from graph_evidence_pipeline import VERSION
from graph_schema import canonical_graph
from graph_staged import Budget
from ocr_nextgen import recognize_graph_document
from vision_provider import VisionProvider


def complete_graph():
    return canonical_graph({'id':'G1','name':'G1','directed':False,'weighted':False,
        'multigraph':False,'complete':True,'vertices':[
            {'id':'a','label':'a','x':.2,'y':.5}, {'id':'b','label':'b','x':.8,'y':.5}],
        'edges':[{'id':'e1','from':'a','to':'b','direction':'undirected','style':'solid',
                  'status':'accepted','path':[[.2,.5],[.8,.5]]}]})


def result(body='', complete=True):
    return {'graphs':[complete_graph()], 'diagnostics':[], 'body_text':body,
            'body_complete':complete,'remote_metrics':[]}


def test_default_engine_failure_keeps_two_call_budget_and_never_falls_back():
    def failed(*args, **kwargs):
        budget=kwargs['budget']
        assert budget.remaining==2
        budget.take()
        budget.metrics.append({'status':'transport_failed','attempt':1})
        raise RuntimeError('transport_failed')
    with patch('graph_evidence_pipeline.recognize_evidence',side_effect=failed) as current, \
            patch('graph_qwen_simple.recognize_simple') as previous, \
            patch('ocr_nextgen.recognize_staged') as staged:
        actual=recognize_graph_document(b'original',{})
    assert current.call_count==1 and previous.call_count==0 and staged.call_count==0
    assert actual['graph_display_version']==VERSION
    assert actual['recognition_status']=='failed' and actual['review']['required']
    assert len(actual['diagnostics']['remote_metrics'])==1


def test_complete_graph_cannot_hide_incomplete_body_text():
    with patch('graph_evidence_pipeline.recognize_evidence',return_value=result(complete=False)), \
            patch('ocr_nextgen.correct_text',return_value=('',{'status':'empty'})):
        actual=recognize_graph_document(b'original',{})
    assert actual['graph_structures'][0]['complete']
    assert actual['recognition_status']=='partial' and actual['review']['required']
    assert not actual['diagnostics']['text_evidence']['complete']
    assert any('题干' in reason for reason in actual['review']['reasons'])


def test_missing_text_correction_is_visible_and_original_transcription_is_kept():
    with patch('graph_evidence_pipeline.recognize_evidence',return_value=result('求顶点 a 的度数。')), \
            patch('ocr_nextgen.correct_text',side_effect=lambda text:(text,{'status':'unavailable'})):
        actual=recognize_graph_document(b'original',{'text':'Cl >0'})
    assert actual['text']=='求顶点 a 的度数。'
    assert actual['diagnostics']['text_evidence']['paddle_text']=='Cl >0'
    assert actual['recognition_status']=='partial' and actual['review']['required']


def test_explicit_empty_body_needs_no_paid_text_correction():
    with patch('graph_evidence_pipeline.recognize_evidence',return_value=result()):
        actual=recognize_graph_document(b'original',{})
    assert actual['text']=='' and actual['recognition_status']=='complete'
    assert actual['review']=={'required':False,'reasons':[]}
    assert actual['diagnostics']['correction']['status']=='empty'


def test_text_service_exception_preserves_graph_and_partial_text():
    with patch('graph_evidence_pipeline.recognize_evidence',return_value=result('求度数。')), \
            patch('ocr_nextgen.correct_text',side_effect=TimeoutError('synthetic timeout')):
        actual=recognize_graph_document(b'original',{})
    assert actual['graph_structures'][0]['complete']
    assert actual['text']=='求度数。' and actual['recognition_status']=='partial'
    assert actual['diagnostics']['correction']['failure_kind']=='TimeoutError'


def test_dense_page_output_allowance_does_not_add_request_or_retry(monkeypatch):
    import ai
    monkeypatch.setattr(ai,'API_KEY','offline-test-only')
    monkeypatch.setattr(ai,'VISION_ENABLED',True)
    observed=[]
    def transport(payload,*args,**kwargs):
        observed.append(payload)
        return 200,'',{'model':'qwen3-vl-plus','choices':[
            {'message':{'content':'{"graphs":[]}'},'finish_reason':'stop'}]}
    provider=VisionProvider('qwen',transport=transport)
    budget=Budget(calls=2)
    budget.output_tokens=12000
    assert provider('Return JSON',[],budget)=={'graphs':[]}
    assert len(observed)==1 and observed[0]['max_tokens']==12000
    assert budget.remaining==1 and budget.metrics[0]['max_output_tokens']==12000


@pytest.mark.parametrize('value',[True,0,32768,16385,'12000'])
def test_invalid_output_budget_fails_before_transport(monkeypatch,value):
    monkeypatch.setattr('ai.API_KEY','offline-test-only')
    monkeypatch.setattr('ai.VISION_ENABLED',True)
    transport=pytest.fail
    provider=VisionProvider('qwen',transport=transport)
    budget=Budget(calls=2)
    budget.output_tokens=value
    with pytest.raises(ValueError,match='invalid_bounded_output_budget'):
        provider('Return JSON',[],budget)
    assert budget.remaining==2


def test_local_candidate_budget_limits_survive_main_pipeline_and_schema(monkeypatch):
    from PIL import Image
    from image_evidence import analyze_document
    from graph_evidence_pipeline import collect_candidates
    limits=[{'kind':'curve_template_node_limit','nodes':15,'limit':14,'skipped':True},
            {'kind':'curve_refinement_budget','refinement_limit_reached_pairs':[['a','b']],
             'route_limit_reached_pairs':[],'pair_refinement_limit':24}]
    monkeypatch.setattr('graph_line_tracer.attach_line_evidence',lambda *a,**k:{
        'line_path_evidence':[], 'line_trace_diagnostics':[{'id':'G1','diagnostics':limits}]})
    graph=complete_graph()
    candidates,notes=collect_candidates(analyze_document(Image.new('RGB',(300,200),'white')),[graph])
    assert candidates=={'G1':[]}
    assert any('curve_template_node_limit:G1' in note for note in notes)
    assert any('curve_refinement_budget:G1' in note for note in notes)
    saved=canonical_graph(graph)
    assert saved['candidate_trace_diagnostics']==limits
    limits[0]['nodes']=999
    assert saved['candidate_trace_diagnostics'][0]['nodes']==15
