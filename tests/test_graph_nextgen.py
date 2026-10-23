"""Mechanism tests; these are NOT real university-image accuracy claims."""
import copy
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
import pytest
from graph_schema import canonical_graph,display_graph
from graph_relation import recover_relations
from graph_staged import merge_node_reads
from ocr_layout import normalize_layout,partition_text
from ocr_correction import apply_evidence_edits
from ocr_runtime import run_worker


def graph(edges=None,nodes=None,**kw):
    return {'id':'G1','directed':False,'weighted':False,'multigraph':False,
            'vertices':nodes or [{'id':'a','label':'A','x':.1,'y':.5},
                                {'id':'b','label':'B','x':.9,'y':.5}],
            'edges':edges or [],**kw}


def edge(eid='e1',**kw):
    return {'id':eid,'from':'a','to':'b','direction':'undirected','path':[[.1,.5],[.9,.5]],**kw}


def trace(**kw): return {'from':'a','to':'b','path':[[.1,.5],[.9,.5]],'score':.95,**kw}


def test_same_weight_parallel_identity_survives_public_projection():
    g=canonical_graph(graph([edge('e1',weight=4),edge('e2',weight=4)],weighted=True,multigraph=True))
    p=display_graph(g)
    assert [e['id'] for e in p['edges']]==['e1','e2']
    assert all(e['parallel_count']==2 and e['multiplicity']==1 for e in p['edges'])
    assert 'x' not in p['vertices'][0] and 'path' not in p['edges'][0]
    assert p['vertices'][0]['label']=='A'


def test_reciprocal_reads_deduplicate_same_route_but_not_arc():
    e=edge(); arc=edge(path=[[.1,.5],[.5,.2],[.9,.5]])
    g=merge_node_reads(graph(),[{'vertex':'a','complete':True,'edges':[e,arc]},
                               {'vertex':'b','complete':True,'edges':[dict(e,**{'from':'b','to':'a'})]}])
    assert len(g['edges'])==2
    assert len(g['edges'][0]['evidence'])==2


def test_unknown_endpoint_never_creates_vertex():
    g=canonical_graph(graph([edge(**{'to':'ghost'})],complete=True))
    assert not g['edges'] and not g['complete'] and len(g['vertices'])==2


def test_pixel_evidence_can_add_missing_edge_but_only_after_visual_review():
    g=graph()
    candidate=recover_relations(g,[trace()])
    assert candidate['edges'][0]['status']=='pending'
    corrected=recover_relations(g,[trace()],review={'pixel_1':{'visible':True,'direction':'undirected'}})
    assert corrected['edges'][0]['status']=='accepted'
    assert not corrected['complete']  # no independent full inventory review


def test_global_shared_ink_reselection_after_new_evidence():
    g=graph([edge('wrong'),edge('right')])
    initial=recover_relations(g,[])
    changed=recover_relations(g,[],review={'right':{'visible':True,'direction':'undirected'}})
    assert len(initial['edges'])==2
    assert [e['id'] for e in changed['edges']]==['right']
    assert next(a for a in changed['relation_audit'] if a['id']=='wrong')['status']=='rejected'
    revised=recover_relations(g,[],review={'right':{'visible':False},'wrong':{'visible':True}})
    assert [e['id'] for e in revised['edges']]==['wrong']


def test_real_middle_node_blocks_bypass_without_inventing_split_edges():
    nodes=graph()['vertices']+[{'id':'m','x':.5,'y':.5,'label':'M'}]
    g=recover_relations(graph([edge()],nodes=nodes),[trace()],review={'e1':{'visible':True}})
    assert g['edges']==[]
    assert g['relation_audit'][0]['blocked_by_vertex']


def test_crossing_without_node_does_not_join_components():
    nodes=graph()['vertices']+[{'id':'c','x':.5,'y':.1},{'id':'d','x':.5,'y':.9}]
    g=recover_relations(graph([edge(),edge('e2',**{'from':'c','to':'d','path':[[.5,.1],[.5,.9]]})],nodes=nodes),[],
                        review={'e1':{'visible':True},'e2':{'visible':True}})
    assert len(g['edges'])==2 and len(g['vertices'])==4


def test_reverse_local_review_only_changes_one_parallel_edge():
    g=graph([edge('e1',direction='unknown'),edge('e2',path=[[.1,.5],[.5,.2],[.9,.5]],direction='unknown')],
            directed=True,multigraph=True)
    actual=recover_relations(g,[],review={'e1':{'visible':True,'direction':'forward'},
                                         'e2':{'visible':True,'direction':'reverse'}})
    assert [(e['from'],e['to']) for e in actual['edges']]==[('a','b'),('b','a')]


def test_unknown_arrow_and_weights_prevent_complete():
    g=graph([edge(direction='unknown')],directed=True,weighted=True,node_complete=True,inventory_reviewed=True)
    actual=recover_relations(g,[trace()],review={'e1':{'visible':True}})
    assert not actual['complete'] and actual['edges'][0]['status']=='pending'


def test_isolated_vertex_retained_with_disconnected_graph():
    nodes=graph()['vertices']+[{'id':'z','label':None,'x':.9,'y':.9,'isolated_confirmed':True}]
    actual=recover_relations(graph([edge()],nodes=nodes),[trace()])
    assert len(actual['vertices'])==3
    assert actual['vertices'][-1]['isolated_confirmed']


def test_layout_separates_body_formula_graph_and_noise_without_deletion():
    raw={'boxes':[{'label':'image','coordinate':[50,50,100,100],'score':.99},
                  {'label':'footer','coordinate':[0,90,40,100],'score':.9},
                  {'label':'display_formula','coordinate':[0,20,40,40],'score':.95}]}
    regions=normalize_layout([raw],100,100)
    items=[{'content':'求最短路','box':[0,0,40,15]}, {'content':'a','box':[60,60,70,70]},
           {'content':'42','box':[1,91,20,99]},{'content':'x+y','box':[0,20,30,35]}]
    result=partition_text(items,regions,100,100)
    assert [i['content'] for i in result['body']]==['求最短路','x+y']
    assert result['graph_labels'][0]['content']=='a' and result['noise'][0]['content']=='42'


def test_text_correction_cannot_change_math_or_insert_unanchored_content():
    text='求顶奌v1的度数3'
    assert apply_evidence_edits(text,[{'start':2,'end':3,'original':'奌','replacement':'点'}])=='求顶点v1的度数3'
    assert apply_evidence_edits(text,[{'start':3,'end':5,'original':'v1','replacement':'v2'}])==text
    assert apply_evidence_edits(text,[{'start':0,'end':1,'original':'错','replacement':'求'}])==text


def test_worker_timeout_terminates_without_blocking_web_process():
    with tempfile.TemporaryDirectory() as folder:
        with patch('ocr_runtime.cgroup_memory',return_value=None):
            result,metric=run_worker('test','unused',Path(folder)/'out.json',timeout=.15,
                                     command=[sys.executable,'-c','import time; time.sleep(5)'])
    assert result is None and metric['status']=='timeout' and metric['seconds']<3


def test_worker_memory_admission_never_launches_model():
    with patch('ocr_runtime.cgroup_memory',return_value=(3500*1024**2,4*1024**3)),patch('ocr_runtime.subprocess.Popen') as spawn:
        result,metric=run_worker('test','unused','unused')
    assert result is None and metric['status']=='memory_admission_rejected'
    spawn.assert_not_called()


def test_worker_native_failure_is_safe():
    with tempfile.TemporaryDirectory() as folder,patch('ocr_runtime.cgroup_memory',return_value=None):
        result,metric=run_worker('test','unused',Path(folder)/'out.json',
                                 command=[sys.executable,'-c','raise SystemExit(7)'])
    assert result is None and metric['status']=='worker_failed'


def test_six_panels_share_vertex_batch_budget_without_losing_last_panels():
    from graph_staged import recognize_staged
    source=Path(__file__).parent/'fixtures/original_ouc_20261021/181309.png'
    graphs=[graph(id=f'G{i}',node_complete=True) for i in range(1,7)]
    calls=[]
    def ask(prompt,images,budget):
        calls.append(prompt)
        if len(calls)==1: return {'graphs':graphs}
        jobs=json.loads(prompt[prompt.index('{"requests":'):])['requests']
        return {'reads':[{'graph_id':job['graph']['id'],'vertex':v,'complete':True,'edges':[]}
                         for job in jobs for v in job['focus_vertices']]}
    # This test exercises shared EDGE batching, not marker-ID grounding.
    with patch('graph_staged.refine_node_positions',side_effect=lambda image,graphs,**kw:graphs), \
         patch('graph_line_tracer.attach_line_evidence',side_effect=lambda raw,value:value):
        result=recognize_staged(source.read_bytes(),call=ask)
    assert len(calls)==3 and len(result['graphs'])==6
    assert all(g['node_complete'] for g in result['graphs'])
    assert all(not g['complete'] for g in result['graphs'])


def test_directed_edges_without_individual_direction_stay_unknown():
    e=edge();del e['direction']
    actual=canonical_graph(graph([e],directed=True))
    assert actual['edges'][0]['direction']=='unknown'


def test_dashed_line_is_a_candidate_not_gap_filled_topology():
    import cv2
    import numpy as np
    from graph_line_tracer import _straight_stroke_candidates
    image=np.full((100,260,3),255,dtype=np.uint8)
    for x in range(20,241,20): cv2.line(image,(x,50),(min(x+9,240),50),(0,0,0),2)
    paths=_straight_stroke_candidates(image,[('a',20,50),('b',240,50)],0,0,4,260,100)
    assert len(paths)==1 and paths[0]['style']=='dashed' and paths[0]['needs_review']
    image[:]=255
    cv2.line(image,(20,50),(70,50),(0,0,0),2);cv2.line(image,(190,50),(240,50),(0,0,0),2)
    assert not _straight_stroke_candidates(image,[('a',20,50),('b',240,50)],0,0,4,260,100)
