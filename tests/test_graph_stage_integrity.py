"""Stage data and call allocation, without paid requests or image answers."""
import copy
import io
import json
from unittest.mock import patch

from PIL import Image, ImageDraw

from graph_staged import Budget, recognize_staged, refine_node_positions
from graph_relation import recover_relations
from graph_schema import canonical_graph


def png():
    out=io.BytesIO();Image.new('RGB',(320,200),'white').save(out,format='PNG')
    return out.getvalue()


def panel(n=18):
    return {'id':'G','bbox':[0,0,1,1],'node_complete':True,'directed':False,
            'weighted':False,'multigraph':False,
            'vertices':[{'id':f'v{i}','x':(i+1)/(n+1),'y':.5} for i in range(n)]}


def test_failed_edge_batch_does_not_abandon_later_vertices_or_retry():
    batches=[]
    def ask(prompt,images,budget):
        budget.take()
        if 'NODE 阶段' in prompt:return {'graphs':[panel()]}
        jobs=json.loads(prompt[prompt.index('{"requests":'):])['requests']
        vertices=jobs[0]['focus_vertices'];batches.append(vertices)
        if len(batches)==1:raise RuntimeError('transport_failed')
        return {'reads':[{'graph_id':'G','vertex':v,'complete':True,'edges':[]} for v in vertices]}
    with patch('graph_staged.refine_node_positions',side_effect=lambda im,g,**kw:g),patch(
            'graph_line_tracer.attach_line_evidence',side_effect=lambda raw,g:g):
        result=recognize_staged(png(),call=ask,audit=True)
    assert len(batches)==3 and len({v for batch in batches for v in batch})==18
    assert not result['graphs'][0]['node_complete']
    assert result['diagnostics']==['edge_read_failed:transport_failed']
    assert len([e for e in result['stage_audit'] if e['stage']=='EDGE.failed'])==1


def test_only_one_auxiliary_node_call_and_all_vertices_have_edge_slots():
    calls=[];focus=[]
    def align(im,graphs,*,candidate_sink=None,**kw):
        if candidate_sink is not None:
            candidate_sink.extend({'x':(i+1)/32,'y':.5} for i in range(26))
        return graphs
    def ask(prompt,images,budget):
        budget.take();calls.append(prompt)
        if 'NODE 阶段' in prompt:return {'graphs':[panel(25)]}
        jobs=json.loads(prompt[prompt.index('{"requests":'):])['requests']
        vertices=jobs[0]['focus_vertices'];focus.extend(vertices)
        return {'reads':[{'graph_id':'G','vertex':v,'complete':True,'edges':[]} for v in vertices]}
    with patch('graph_staged.refine_node_positions',side_effect=align),patch(
            'graph_line_tracer.attach_line_evidence',side_effect=lambda raw,g:g):
        result=recognize_staged(png(),call=ask)
    assert len([p for p in calls if 'NODE 阶段' in p])==2
    assert len(focus)==len(set(focus))==25
    assert 'edge_budget_exhausted' not in result['diagnostics']


def test_small_valid_black_disks_on_clean_paper_are_not_discarded():
    image=Image.new('RGB',(900,250),'white');draw=ImageDraw.Draw(image)
    vertices=[]
    for i in range(10):
        x=50+i*80;y=80 if i%2 else 170
        draw.ellipse((x-4,y-4,x+4,y+4),fill='black')
        vertices.append({'id':f'n{i}','x':x/899+.01,'y':y/249+.02})
    graph=canonical_graph({'id':'G','bbox':[0,0,1,1],'vertices':vertices})
    result=refine_node_positions(image,[graph],partial=True)[0]
    assert len(result['node_position_evidence'])==10
    assert all(abs(v['x']-(50+i*80)/899)<.004 for i,v in enumerate(result['vertices']))


def test_carried_pixel_candidate_does_not_gain_visual_confidence():
    g=canonical_graph({'id':'G','directed':False,'vertices':[
        {'id':'a','x':.1,'y':.5},{'id':'b','x':.9,'y':.5}],
        'edges':[{'id':'pixel_1','from':'a','to':'b','direction':'undirected',
                  'path':[[.1,.5],[.9,.5]],'evidence':[{'source':'pixels','score':1.}]}]})
    trace={'from':'a','to':'b','path':[[.1,.5],[.9,.5]],'score':1.}
    result=recover_relations(g,[trace])
    assert result['edges'][0]['status']=='pending'
    assert result['relation_audit'][0]['score']==.55


def test_review_path_correction_reaches_trace_id_without_duplicate_addition():
    image=Image.new('RGB',(320,200),'white');ImageDraw.Draw(image).line((64,100,256,100),fill='black',width=3)
    out=io.BytesIO();image.save(out,format='PNG');route=[[.2,.5],[.8,.5]]
    def ask(prompt,images,budget):
        budget.take()
        if 'NODE 阶段' in prompt:return {'graphs':[{'id':'G','directed':False,'weighted':False,'multigraph':False,
            'node_complete':True,'vertices':[{'id':'a','x':.2,'y':.5},{'id':'b','x':.8,'y':.5}]}]}
        if 'EDGE 阶段' in prompt:return {'reads':[{'graph_id':'G','vertex':v,'complete':True,'edges':[]} for v in ['a','b']]}
        return {'graphs':[{'graph_id':'G','decisions':[{'id':'pixel_1','visible':True,'direction':'undirected','path':route}],
                          'additional_edges':[{'from':'a','to':'b','direction':'undirected','path':route,'style':'solid'}]}]}
    def trace(raw,g):return {'line_path_evidence':[{'id':'G','paths':[{'from':'a','to':'b','path':route,'score':.95}]}]}
    with patch('graph_staged.refine_node_positions',side_effect=lambda im,g,**kw:g),patch(
            'graph_line_tracer.attach_line_evidence',side_effect=trace):
        result=recognize_staged(out.getvalue(),call=ask)
    edges=result['graphs'][0]['edges']
    assert len(edges)==1 and edges[0]['id']=='pixel_1' and edges[0]['status']=='accepted'
    assert any(x.get('source')=='qwen_review_route_verified' for x in edges[0]['evidence'])
    assert 'qwen_review_addition_rejected:duplicate_stroke' in result['diagnostics']
