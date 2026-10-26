"""Attribute reads must retain the measured edge identities and fail atomically."""
import copy
import pytest
from graph_schema import canonical_graph
from graph_qwen_edge_text import apply_edge_text_inventory,prepare_edge_text_inventory


def prepared():
    graph=canonical_graph({'id':'G','directed':False,'weighted':False,
        'vertices':[{'id':'a','x':.2,'y':.3},{'id':'b','x':.8,'y':.3}],
        'edges':[{'id':'stroke','from':'a','to':'b','direction':'undirected',
                  'path':[[.2,.3],[.8,.3]],'style':'dashed'}]})
    return {'graphs':[graph],'items':[
        {'key':'A','kind':'vertex_label','id':'a','rect':[0,0,10,10]},
        {'key':'B','kind':'edge_label','id':'stroke','rect':[20,0,30,10]}]}


def test_text_changes_attributes_without_recreating_or_restyling_strokes():
    plan=prepared();before=copy.deepcopy(plan)
    result=apply_edge_text_inventory(plan,{'readings':[
        {'key':'B','text':' z '},{'key':'A','text':None}]})[0]
    assert plan==before
    assert result['vertices'][0]['label'] is None
    edge=result['edges'][0]
    assert (edge['id'],edge['from'],edge['to'],edge['style'],edge['edge_label'])==(
        'stroke','a','b','dashed','z')
    assert edge['path']==before['graphs'][0]['edges'][0]['path']
    assert edge['evidence'][-1]['region']==[20,0,30,10]


@pytest.mark.parametrize('readings',[
    [{'key':'A','text':None}],
    [{'key':'A','text':None},{'key':'A','text':'x'}],
    [{'key':'A','text':None},{'key':'C','text':'x'}],
    [{'key':'A','text':None},{'key':'B','text':12}],
])
def test_partial_duplicate_unknown_or_nonstrings_cannot_mutate_inventory(readings):
    plan=prepared();before=copy.deepcopy(plan)
    with pytest.raises(ValueError):apply_edge_text_inventory(plan,{'readings':readings})
    assert plan==before


def test_directed_weighted_and_multipanel_inputs_abstain_before_pixel_processing():
    graph=prepared()['graphs'][0]
    for key in ('directed','weighted'):
        other=copy.deepcopy(graph);other[key]=True
        assert prepare_edge_text_inventory(b'',None,[other]) is None
    assert prepare_edge_text_inventory(b'',None,[graph,graph]) is None


def test_lowered_script_can_match_lowercase_x_height_without_splitting_one_word():
    from PIL import Image,ImageDraw,ImageFont
    from graph_qwen_edge_text import _glyphs
    image=Image.new('RGB',(220,120),'white');draw=ImageDraw.Draw(image)
    draw.text((40,30),'e',font=ImageFont.truetype('DejaVuSans.ttf',34),fill='black',anchor='lt')
    draw.text((62,40),'3',font=ImageFont.truetype('DejaVuSans.ttf',26),fill='black',anchor='lt')
    ordinary=_glyphs(image,[0,0,1,1],[],join_scripts=True)
    repaired=_glyphs(image,[0,0,1,1],[],join_scripts=True,allow_equal_scripts=True)
    assert len(ordinary)==2
    assert len(repaired)==1 and repaired[0]['parts']==2
    assert repaired[0]['box'][0]<=ordinary[0]['box'][0]
    assert repaired[0]['box'][2]>=ordinary[1]['box'][2]


def test_equal_height_neighbour_on_the_same_baseline_is_not_a_lowered_script():
    from PIL import Image,ImageDraw,ImageFont
    from graph_qwen_edge_text import _glyphs
    image=Image.new('RGB',(220,120),'white');draw=ImageDraw.Draw(image)
    draw.text((40,30),'e',font=ImageFont.truetype('DejaVuSans.ttf',34),fill='black',anchor='lt')
    draw.text((62,30),'3',font=ImageFont.truetype('DejaVuSans.ttf',26),fill='black',anchor='lt')
    glyphs=_glyphs(image,[0,0,1,1],[],join_scripts=True,allow_equal_scripts=True)
    assert len(glyphs)==2 and all(g['parts']==1 for g in glyphs)
