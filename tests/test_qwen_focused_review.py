"""Regression: a Qwen REVIEW unknown used to leave its close-up slot unused."""
import copy
import io
import json
from unittest.mock import patch

import pytest
from PIL import Image

from graph_staged import Budget, recognize_staged


@pytest.mark.parametrize('weighted,first_direction,first_weight,final_direction,final_weight', [
    (False, 'unknown', None, 'reverse', None),
    (True, 'forward', None, 'forward', 6),
    (False, 'unknown', None, 'unknown', None),
])
def test_unresolved_qwen_attribute_gets_bounded_original_closeup(
        weighted, first_direction, first_weight, final_direction, final_weight):
    image=io.BytesIO();Image.new('RGB',(600,400),'white').save(image,format='PNG')
    nodes=[{'id':'a','label':'A','x':.25,'y':.4},
           {'id':'b','label':'B','x':.75,'y':.4}]
    path=[[.25,.4],[.75,.4]]
    calls=[]
    def ask(prompt,images,budget):
        budget.take();calls.append((prompt,copy.deepcopy(images)))
        if 'NODE 阶段' in prompt:
            return {'graphs':[{'id':'G1','directed':True,'weighted':weighted,
                'multigraph':False,'node_complete':True,'vertices':nodes}]}
        if 'EDGE 阶段' in prompt:
            return {'edges':[{'id':'r1','graph_id':'G1','from':'a','to':'b',
                             'direction':'forward','path':path,'weight':None}],
                    'reads':[{'graph_id':'G1','vertex':v,'complete':True,'edge_ids':['r1']}
                             for v in ('a','b')]}
        if len(calls)==3:
            return {'graphs':[{'graph_id':'G1','inventory_complete':False,'decisions':[
                {'id':'e1','visible':True,'direction':first_direction,'weight':first_weight}]}]}
        assert len(calls)==4
        payload=json.loads(prompt[prompt.index('{"graph_id":'):])
        candidate=payload['candidates'][0]
        assert (candidate['id'],candidate['from'],candidate['to'])==('e1','a','b')
        # Same uploaded scene and a smaller view, never a generated answer map.
        import base64
        with Image.open(io.BytesIO(base64.b64decode(images[1].split(',',1)[1]))) as crop:
            assert crop.width<600 and crop.height<400
        return {'decisions':[{'id':'e1','visible':True,'direction':final_direction,
                              'weight':final_weight}]}
    with patch('graph_line_tracer.attach_line_evidence',side_effect=lambda raw,result:result):
        budget=Budget()
        result=recognize_staged(image.getvalue(),call=ask,budget=budget)
    assert len(calls)==4 and budget.remaining==3
    edge=result['graphs'][0]['edges'][0]
    assert edge['id']=='e1' and len(result['graphs'][0]['vertices'])==2
    if final_direction=='reverse':
        assert (edge['from'],edge['to'],edge['direction'])==('b','a','forward')
    elif final_direction=='unknown':
        assert edge['direction']=='unknown' and edge['status']=='pending'
    else:
        assert edge['weight']==final_weight and edge['direction']=='forward'


@pytest.mark.parametrize('fail_grounding',[False,True])
def test_qwen_marker_grounding_preserves_labels_and_never_certifies_failure(fail_grounding):
    from vision_provider import VisionError
    source=io.BytesIO();Image.new('RGB',(300,200),'white').save(source,format='PNG')
    vertices=[{'id':'a','label':'A','x':.2,'y':.2},
              {'id':'b','label':'B','x':.5,'y':.5},
              {'id':'c','label':'C','x':.8,'y':.8}]
    def align(image,graphs,*,candidate_sink=None,partial=False):
        assert partial is True
        if candidate_sink is not None:
            candidate_sink.extend([{'x':.2,'y':.2},{'x':.5,'y':.5},{'x':.8,'y':.2}])
        graphs[0]['node_position_evidence']=[{'vertex':'a'},{'vertex':'b'}]
        return graphs
    calls=[]
    def ask(prompt,images,budget):
        budget.take();calls.append(prompt)
        if '圆点ID坐标复核' in prompt:
            if fail_grounding:raise VisionError('transport_failed')
            return {'assignments':[{'graph_id':'G','vertex_id':v,'marker_id':f'm{i}'}
                                   for i,v in enumerate(['a','b','c'],1)]}
        if 'NODE 阶段' in prompt:
            return {'graphs':[{'id':'G','bbox':[0,0,1,1],'directed':False,
                'weighted':False,'multigraph':False,'node_complete':True,'vertices':vertices}]}
        assert 'EDGE 阶段' in prompt
        return {'reads':[{'graph_id':'G','vertex':v,'complete':True,'edges':[]} for v in ['a','b','c']]}
    with patch('graph_staged.refine_node_positions',side_effect=align),patch(
            'graph_line_tracer.attach_line_evidence',side_effect=lambda raw,r:r):
        result=recognize_staged(source.getvalue(),call=ask)
    g=result['graphs'][0]
    assert [v['label'] for v in g['vertices']]==['A','B','C'] and len(calls)==3
    if fail_grounding:
        assert not g['node_complete'] and g['vertices'][2]['y']==.8
        assert 'qwen_marker_grounding_failed' in result['diagnostics']
    else:
        assert g['vertices'][2]['y']==.2 and g['node_complete']
        assert g['node_position_evidence'][2]['source']=='qwen_marker_id_grounding'
