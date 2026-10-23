"""Missed strokes remain observations until original-ink guards accept them."""
import copy

import pytest
from PIL import Image, ImageDraw

from graph_glm_adapter import review_route_ink
from graph_qwen_review import receive_qwen_review
from graph_relation import recover_relations
from graph_schema import canonical_graph


def graph():
    return canonical_graph({'id':'G','directed':False,'weighted':False,
        'multigraph':True,'node_complete':True,'inventory_reviewed':True,
        'vertices':[{'id':'a','x':.15,'y':.5},{'id':'b','x':.85,'y':.5}], 'edges':[]})


def stroke(path, **extra):
    return {'from':'a','to':'b','direction':'undirected','weight':None,
            'edge_label':None,'style':'solid','path':path,**extra}


def test_qwen_can_recover_two_real_parallel_strokes_without_merging_ids():
    original=graph();before=copy.deepcopy(original)
    image=Image.new('RGB',(500,400),'white');draw=ImageDraw.Draw(image)
    routes=[[[.15,.5],[.85,.5]],[[.15,.5],[.4,.25],[.6,.25],[.85,.5]]]
    for path in routes:
        draw.line([(round(x*499),round(y*399)) for x,y in path],fill='black',width=3)
    revised,decisions,notes=receive_qwen_review(original,{},[stroke(p) for p in routes],review_route_ink(image))
    assert original==before
    assert notes==['qwen_review_strokes_added:2']
    result=recover_relations(revised,[],review=decisions)
    assert len(result['vertices'])==2 and len(result['edges'])==2
    assert len({e['id'] for e in result['edges']})==2
    assert all(e['status']=='accepted' for e in result['edges'])
    assert all(any(v.get('source')=='qwen_review_new_stroke' for v in e['evidence'])
               for e in result['edges'])


@pytest.mark.parametrize('extra', [{'from':['a']},{'to':'new_vertex'},
                                 {'direction':'reverse'},{'path':[[.1,.2],[float('nan'),.5]]}])
def test_invalid_qwen_addition_never_creates_a_vertex_or_edge(extra):
    g=graph();ink=review_route_ink(Image.new('RGB',(500,400),'white'))
    proposal={**stroke([[.15,.5],[.85,.5]]),**extra}
    actual,decisions,notes=receive_qwen_review(g,{},[proposal],ink)
    assert actual['vertices']==g['vertices'] and not actual['edges'] and not decisions
    assert any('rejected' in n for n in notes)


def test_visible_claim_without_real_ink_cannot_add_an_edge():
    ink=review_route_ink(Image.new('RGB',(500,400),'white'))
    actual,decisions,notes=receive_qwen_review(graph(),{},[stroke([[.15,.5],[.85,.5]],visible=True)],ink)
    assert not actual['edges'] and not decisions
    assert notes==['qwen_review_addition_rejected:ink_gap']


def test_ink_through_an_existing_vertex_is_not_a_single_edge():
    g=graph();g['vertices'].append({'id':'c','x':.5,'y':.5})
    image=Image.new('RGB',(500,400),'white');ImageDraw.Draw(image).line([(75,200),(425,200)],fill='black',width=3)
    actual,_,notes=receive_qwen_review(g,{},[stroke([[.15,.5],[.85,.5]])],review_route_ink(image))
    assert not actual['edges'] and notes==['qwen_review_addition_rejected:geometry']


def test_coarse_review_path_requires_unique_strong_trace_and_ink():
    image=Image.new('RGB',(500,400),'white')
    exact=[[.15,.5],[.4,.25],[.6,.25],[.85,.5]]
    observed=[[.15,.5],[.4,.267],[.6,.267],[.85,.5]]
    ImageDraw.Draw(image).line([(round(x*499),round(y*399)) for x,y in exact],fill='black',width=3)
    trace={'from':'a','to':'b','path':exact,'score':.95,'method':'measured_test_stroke'}
    ink=review_route_ink(image)
    g,decisions,notes=receive_qwen_review(graph(),{},[stroke(observed)],ink,traces=[trace])
    assert len(g['edges'])==1 and g['edges'][0]['path']==exact
    assert any(e['source']=='qwen_review_trace_binding' for e in g['edges'][0]['evidence'])
    # Two equally compatible candidates must never be used as a multiplicity
    # oracle or resolved by iteration order.
    g,_,notes=receive_qwen_review(graph(),{},[stroke(observed)],ink,traces=[trace,copy.deepcopy(trace)])
    assert not g['edges'] and notes==['qwen_review_addition_rejected:ink_gap']
    assert g['qwen_review_audit'][0]['status']=='rejected'


def test_multigraph_type_alone_does_not_duplicate_reciprocal_edge_reads():
    import io
    import json
    from unittest.mock import patch
    from graph_staged import recognize_staged, Budget
    image=io.BytesIO();Image.new('RGB',(300,200),'white').save(image,format='PNG')
    batches=[]
    def ask(prompt,images,budget):
        budget.take()
        if 'NODE 阶段' in prompt:
            return {'graphs':[{'id':'G','node_complete':True,'multigraph':True,
                'directed':False,'weighted':False,
                'vertices':[{'id':f'v{i}','x':i/6,'y':.5} for i in range(1,6)]}]}
        assert 'EDGE 阶段' in prompt
        jobs=json.loads(prompt[prompt.index('{"requests":'):])['requests']
        focus=jobs[0]['focus_vertices'];batches.append(focus)
        return {'reads':[{'graph_id':'G','vertex':v,'complete':True,'edges':[]} for v in focus]}
    with patch('graph_staged.refine_node_positions',side_effect=lambda image,g,**kw:g),patch(
            'graph_line_tracer.attach_line_evidence',side_effect=lambda raw,r:r):
        budget=Budget();result=recognize_staged(image.getvalue(),call=ask,budget=budget)
    assert batches==[['v1','v2','v3','v4','v5']]
    assert budget.remaining==5 and result['graphs'][0]['node_complete']
