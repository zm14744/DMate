"""Evidence-contract regressions, not claims of real OCR accuracy."""
import copy
import pytest
from graph_glm_adapter import bind_pixel_routes, receive_review_routes
from graph_staged import merge_node_reads
from graph_relation import recover_relations


def graph(edges):
    return {'id':'G1','directed':True,'weighted':False,'multigraph':True,
            'vertices':[{'id':'a','x':.1,'y':.5},{'id':'b','x':.9,'y':.5}],
            'edges':edges,'node_complete':True}


def edge(identity='e1',path=None):
    return {'id':identity,'from':'a','to':'b','direction':'forward',
            'path':[[.4,.5],[.6,.5]] if path is None else path,'evidence':[]}


def trace(path=None,**extra):
    return {'from':'a','to':'b','path':[[.1,.5],[.9,.5]] if path is None else path,
            'score':.96,'method':'test_pixel_trace',**extra}


def test_unique_partial_pixel_binding_recovers_full_route_and_preserves_semantics():
    original=graph([edge()]);before=copy.deepcopy(original)
    adapted=bind_pixel_routes(original,[trace()])
    assert original==before
    recovered=adapted['edges'][0]
    assert recovered['path']==[[.1,.5],[.9,.5]]
    assert recovered['evidence'][-1]['observed_path']==[[.4,.5],[.6,.5]]
    assert recovered['evidence'][-1]['fragment_coverage']==1
    baseline=recover_relations(original,[])
    assert baseline['relation_audit'][0]['endpoint_mismatch']
    result=recover_relations(adapted,[trace()],review={'e1':{'visible':True,'direction':'forward'}})
    assert len(result['edges'])==1 and result['edges'][0]['direction']=='forward'


@pytest.mark.parametrize('traces',[
    [trace(),trace()],  # two possible physical routes
    [trace(score=.79)],
    [trace(path=[[.1,.6],[.9,.6]])],  # unrelated pixels
    [trace(**{'from':'a','to':'c'})],
])
def test_ambiguous_weak_or_wrong_route_cannot_repair_fragment(traces):
    original=graph([edge()])
    assert bind_pixel_routes(original,traces)['edges'][0]['path']==original['edges'][0]['path']


def test_two_parallel_claims_cannot_both_consume_one_pixel_route():
    original=graph([edge('e1'),edge('e2')])
    adapted=bind_pixel_routes(original,[trace()])
    assert len(adapted['edges'])==2
    assert all(e['path']==[[.4,.5],[.6,.5]] for e in adapted['edges'])


def test_intermediate_real_vertex_still_blocks_repair():
    original=graph([edge()]);original['vertices'].append({'id':'c','x':.5,'y':.5})
    adapted=bind_pixel_routes(original,[trace()])
    assert adapted['edges'][0]['path']==original['edges'][0]['path']


def test_shared_observation_ids_deduplicate_references_not_parallel_instances():
    raws=[{**edge(f'r{i}',[]),'_observation_id':(0,'G1',f'r{i}')} for i in range(3)]
    reads=[{'vertex':v,'complete':True,'edges':copy.deepcopy(raws)} for v in ('a','b')]
    baseline=merge_node_reads(graph([]),reads)
    adapted=merge_node_reads(graph([]),reads,shared_observations=True)
    assert len(baseline['edges'])==6
    assert len(adapted['edges'])==3
    assert all({r['vertex'] for r in e['evidence']}=={'a','b'} for e in adapted['edges'])


def test_distinct_ids_in_same_batch_do_not_collapse_close_parallel_paths():
    raws=[{**edge('r1',[[.1,.5],[.9,.5]]),'_observation_id':(0,'G1','r1')},
          {**edge('r2',[[.1,.501],[.9,.501]]),'_observation_id':(0,'G1','r2')}]
    reads=[{'vertex':v,'complete':True,'edges':[r]} for v,r in zip(('a','b'),raws)]
    assert len(merge_node_reads(graph([]),reads,shared_observations=True)['edges'])==2


def test_review_can_supply_a_full_route_only_when_real_ink_supports_it():
    import numpy as np
    import cv2
    ink=np.zeros((201,401),dtype='uint8');cv2.line(ink,(40,100),(360,100),255,2)
    original=graph([edge(path=[])])
    decisions={'e1':{'visible':True,'direction':'forward','path':[[.1,.5],[.9,.5]]}}
    repaired=receive_review_routes(original,decisions,ink)
    assert repaired['edges'][0]['path']==[[.1,.5],[.9,.5]] and original['edges'][0]['path']==[]
    assert repaired['edges'][0]['evidence'][-1]['source']=='glm_review_route_verified'
    result=recover_relations(repaired,[],review=decisions)
    assert result['edges'][0]['status']=='accepted'
    # One long white gap cannot become a connector through visual confirmation.
    ink[:,170:230]=0
    rejected=receive_review_routes(original,decisions,ink)
    assert rejected['edges'][0]['path']==[]
    assert rejected['edges'][0]['evidence'][-1]['reason']=='ink_gap'


def test_review_cannot_create_an_edge_or_bypass_real_intermediate_vertices():
    import numpy as np
    ink=np.ones((201,401),dtype='uint8')*255
    original=graph([edge(path=[])]);original['vertices'].append({'id':'c','x':.5,'y':.5})
    decisions={'e1':{'visible':True,'path':[[.1,.5],[.9,.5]]},
               'new_id':{'visible':True,'path':[[.1,.5],[.9,.5]]}}
    result=receive_review_routes(original,decisions,ink)
    assert len(result['edges'])==1 and result['edges'][0]['path']==[]
    assert result['edges'][0]['evidence'][-1]['reason']=='geometry'


def test_review_route_sampling_uses_pixels_on_a_wide_non_square_image():
    import numpy as np
    import cv2
    ink=np.zeros((81,801),dtype='uint8')
    cv2.polylines(ink,[np.array([[80,40],[400,16],[720,40]])],False,255,2)
    decisions={'e1':{'visible':True,'path':[[.1,.5],[.5,.2],[.9,.5]]}}
    repaired=receive_review_routes(graph([edge(path=[])]),decisions,ink)
    assert repaired['edges'][0]['evidence'][-1]['source']=='glm_review_route_verified'
