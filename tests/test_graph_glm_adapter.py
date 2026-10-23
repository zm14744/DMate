"""Evidence-contract regressions, not claims of real OCR accuracy."""
import copy
import pytest
from graph_glm_adapter import bind_pixel_routes, receive_review_routes, partial_marker_anchors, compact_review_job, unpack_reviews
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


def test_partial_anchors_move_only_close_unambiguous_existing_vertices():
    vertices=[{'id':'a','x':.1,'y':.5},{'id':'b','x':.8,'y':.8}]
    before=copy.deepcopy(vertices)
    assert partial_marker_anchors(vertices,[(.11,.5),(.4,.3)])=={0:0}
    assert vertices==before


@pytest.mark.parametrize('vertices,points',[
    ([{'x':.1,'y':.5}],[(.09,.5),(.11,.5)]),
    ([{'x':.1,'y':.5},{'x':.11,'y':.5}],[(.105,.5)]),
    ([{'x':.1,'y':.5}],[(.2,.5)]),
])
def test_partial_anchors_reject_ambiguous_or_large_coordinate_changes(vertices,points):
    assert partial_marker_anchors(vertices,points)=={}


def test_compact_review_keeps_pixel_arrow_proof_and_explicit_geometry():
    candidate=edge(path=[])
    candidate['evidence']=[{'source':'node_read','vertex':'a'},
                           {'source':'arrow_pixels','from':'a','to':'b','score':.9}]
    g=graph([candidate]);g['bbox']=[0,0,1,1]
    job=compact_review_job(g,[candidate],(801,201))
    assert job['geometry']['original_size']==[801,201]
    assert job['geometry']['coordinate_space']=='original_image_normalized'
    assert job['candidates'][0]['needs_path']
    assert job['candidates'][0]['evidence']==[candidate['evidence'][1]]
    assert candidate['evidence'][0]['source']=='node_read'


def test_flat_review_ids_are_scoped_to_their_actual_panels():
    raw={'decisions':[{'graph_id':'G1','id':'e1','visible':True},
                      {'graph_id':'G2','id':'e1','visible':False}],
         'completed_graph_ids':['G2']}
    groups={g['graph_id']:g for g in unpack_reviews(raw)}
    assert groups['G1']['decisions'][0]['visible'] is True
    assert groups['G2']['decisions'][0]['visible'] is False
    assert not groups['G1']['inventory_complete'] and groups['G2']['inventory_complete']


def test_unscoped_flat_decision_cannot_be_assigned_to_a_multi_panel_job():
    raw={'decisions':[{'id':'e1','visible':True}]}
    assert unpack_reviews(raw)==[]
    assert unpack_reviews(raw,single_graph_id='G1')[0]['graph_id']=='G1'


def test_nested_legacy_reviews_remain_compatible_without_answer_mutation():
    raw={'graphs':[{'graph_id':'G1','decisions':[],'inventory_complete':False}]}
    assert unpack_reviews(raw)==raw['graphs']
