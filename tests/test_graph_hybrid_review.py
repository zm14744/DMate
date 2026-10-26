"""Routing/budget checks only, not image accuracy tests."""
import io
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image

from graph_hybrid_review import HybridReview, _ReviewBudget
from graph_staged import Budget, recognize_staged
from vision_provider import VisionError


def provider(**options):
    return SimpleNamespace(name='glm', model='glm-4.6v', thinking=False, retries=0, **options)


def job(**options):
    return {'graph_id':'G1', 'directed':True, 'weighted':False, 'multigraph':False,
            'candidates':[{'id':'e1','from':'a','to':'b','direction':'unknown',
                           'weight':None, 'evidence':[]}], **options}


def test_only_one_existing_review_slot_is_selected():
    router=HybridReview(provider())
    budget=Budget()
    assert router.select([job()],[],budget)
    assert not router.select([job()],[],budget)
    assert budget.remaining==7  # Selection itself is not a network request.


def test_clear_routes_and_oversized_jobs_stay_on_qwen():
    router=HybridReview(provider())
    assert not router.select([job(directed=False)],[],Budget())
    huge=job();huge['candidates']*=25
    assert not router.select([huge],[],Budget())
    assert router.used is False


def test_weight_and_parallel_uncertainty_can_trigger_review():
    assert HybridReview(provider()).select([job(directed=False,weighted=True)],[],Budget())
    assert HybridReview(provider()).select([job(directed=False,multigraph=True)],[],Budget())


def test_bounded_glm_call_consumes_the_same_parent_budget():
    parent=Budget(seconds=155,calls=1,call_seconds=45)
    child=_ReviewBudget(parent,25)
    assert 0<child.take()<=25
    assert parent.remaining==0
    assert child.metrics is parent.metrics
    with pytest.raises(TimeoutError):child.take()


@pytest.mark.parametrize('field,value',[('model','glm-4.6v-flash'),('thinking',True),('retries',1)])
def test_no_flash_thinking_or_retry_can_be_enabled_implicitly(field,value):
    p=provider();setattr(p,field,value)
    with pytest.raises(ValueError):HybridReview(p)


def test_failed_glm_review_is_not_retried_or_replaced_with_an_extra_qwen_call():
    primary_calls=[];review_calls=[]
    class Primary:
        name='qwen'
        def __call__(self,prompt,images,budget):
            budget.take();primary_calls.append(prompt)
            if len(primary_calls)==1:
                return {'graphs':[{'id':'G1','directed':True,'weighted':False,'multigraph':False,
                    'node_complete':True,'vertices':[{'id':'a','label':'a','x':.1,'y':.5},
                    {'id':'b','label':'b','x':.9,'y':.5}]}]}
            assert len(primary_calls)==2
            return {'edges':[{'id':'r1','graph_id':'G1','from':'a','to':'b',
                             'direction':'unknown','path':[[.1,.5],[.9,.5]]}],
                    'reads':[{'graph_id':'G1','vertex':v,'complete':True,'edge_ids':['r1']}
                             for v in ('a','b')]}
    class Reviewer:
        name='glm';model='glm-4.6v';thinking=False;retries=0
        def __call__(self,prompt,images,budget):
            budget.take();review_calls.append(prompt)
            raise VisionError('transport_failed')
    raw=io.BytesIO();Image.new('RGB',(100,100),'white').save(raw,format='PNG')
    budget=Budget()
    with patch('graph_staged.refine_node_positions',side_effect=lambda image,graphs,**kw:graphs), \
         patch('graph_line_tracer.attach_line_evidence',side_effect=lambda raw,result:result):
        result=recognize_staged(raw.getvalue(),provider=Primary(),budget=budget,
                                review_router=HybridReview(Reviewer()))
    assert len(primary_calls)==2 and len(review_calls)==1 and budget.remaining==4
    assert 'local_review_failed' in result['diagnostics']
    assert result['graphs'][0]['edges'][0]['direction']=='unknown'
    assert result['hybrid_review_events'][0]['routed'] is True


def test_report_keeps_failed_requests_and_does_not_turn_them_into_accuracy_errors(tmp_path):
    import json
    from scripts.benchmark_graph_hybrid import write_reports
    rows=[{'case_id':'original','condition':c,'status':'transport_failed','seconds':25.,
           'requests':[{'status':'transport_failed','seconds':25.,'error':'transport_failed'}],
           'metrics':{'status':'not_scored_operational_failure'}} for c in ('qwen','hybrid')]
    write_reports(tmp_path,rows,{'latency_target_ratio':1.2})
    report=json.loads((tmp_path/'comparison.json').read_text())
    assert report['paired_case_ids']==[]
    for c in ('qwen','hybrid'):
        assert report['all_attempts'][c]['accuracy']['scored']==0
        assert report['all_attempts'][c]['accuracy']['edge_set'] is None
        assert report['all_attempts'][c]['operations']['attempted_requests']==1
        assert report['all_attempts'][c]['operations']['mean_case_seconds']==25
