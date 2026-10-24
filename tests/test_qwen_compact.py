"""A complete recovery obeys the same coordinate/identity boundary as inventory."""
import copy
import pytest
from graph_qwen_compact import expand_compact_inventory
from graph_qwen_coordinates import decode_inventory


def compact():
    return {'schema':'graph_compact_v1','coordinate_space':'original_1000','graphs':[{
        'id':'G','name':'G','bbox':[0,0,1000,1000],'directed':False,
        'weighted':False,'multigraph':False,'node_complete':True,
        'vertices':[['a',None,200,500,False],['b',None,800,500,False]],
        'edges':[['stroke','a','b','undirected',None,None,'solid',[[200,500],[800,500]]]]}]}


def test_complete_compact_inventory_preserves_instances_and_does_not_mutate_response():
    response=compact();before=copy.deepcopy(response)
    expanded=expand_compact_inventory(response)
    graph=decode_inventory(expanded)[0]
    assert response==before and graph['edges'][0]['id']=='stroke'
    assert graph['edges'][0]['path']==[[.2,.5],[.8,.5]]


@pytest.mark.parametrize('change',[
    lambda r:r['graphs'][0]['vertices'][0].__setitem__(2,1200),
    lambda r:r['graphs'][0]['vertices'][0].pop(),
    lambda r:r['graphs'][0]['edges'][0].__setitem__(2,'absent'),
    lambda r:r['graphs'][0]['edges'][0].__setitem__(7,[[200,500]]),
    lambda r:r.__setitem__('coordinate_space','pixels'),
])
def test_recovery_rejects_bad_units_columns_endpoints_and_incomplete_paths(change):
    response=compact();change(response)
    with pytest.raises(ValueError):expand_compact_inventory(response)


def test_failed_transport_is_not_retried_as_schema_recovery():
    import io
    from PIL import Image
    from graph_qwen_simple import recognize_simple
    from graph_staged import Budget
    from vision_provider import VisionError
    calls=[]
    class Remote:
        name='qwen';model='qwen3-vl-plus';retries=0
        def __call__(self,prompt,images,budget):
            budget.take();calls.append(prompt);raise VisionError('http_error',401)
    raw=io.BytesIO();Image.new('RGB',(200,200),'white').save(raw,format='PNG')
    with pytest.raises(VisionError):recognize_simple(raw.getvalue(),provider=Remote(),budget=Budget(calls=2))
    assert len(calls)==1


@pytest.mark.parametrize('failure',['coordinates','truncated_output'])
def test_protocol_failure_gets_one_fresh_complete_read_and_no_third_call(failure):
    import io
    from PIL import Image
    from graph_qwen_simple import recognize_simple
    from graph_staged import Budget
    from vision_provider import VisionError
    calls=[]
    class Remote:
        name='qwen';model='qwen3-vl-plus';retries=0
        def __call__(self,prompt,images,budget):
            budget.take();calls.append(prompt)
            if len(calls)==1:
                if failure=='truncated_output':raise VisionError(failure)
                result=expand_compact_inventory(compact())
                result['graphs'][0]['vertices'][0]['x']=1200
                return result
            assert len(calls)==2
            return compact()
    raw=io.BytesIO();Image.new('RGB',(200,200),'white').save(raw,format='PNG')
    result=recognize_simple(raw.getvalue(),provider=Remote(),budget=Budget(calls=2),audit=True)
    assert len(calls)==2 and result['calls_remaining']==0
    assert 'bounded_compact_inventory_recovery' in result['diagnostics']
    assert any(a['stage']=='INVENTORY.invalid' for a in result['stage_audit'])
