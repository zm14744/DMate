"""Literal numerical glyphs bind to measured routes, never create instances."""
import copy
import pytest
from graph_schema import canonical_graph
from graph_qwen_weight_glyphs import apply_weight_glyphs


def plan():
    graph=canonical_graph({'id':'g','directed':False,'weighted':True,
        'vertices':[{'id':k,'x':x,'y':y} for k,x,y in [('a',.1,.3),('b',.9,.3),('c',.1,.8),('d',.9,.8)]],
        'edges':[{'id':'upper','from':'a','to':'b','direction':'undirected','weight':111,'path':[[.1,.3],[.9,.3]]},
                 {'id':'lower','from':'c','to':'d','direction':'undirected','weight':222,'path':[[.1,.8],[.9,.8]]}]})
    return {'graphs':[graph],'image_size':(401,201),'items':[
        {'key':key,'kind':'glyph','graph_index':0,'centre':[200,y],'glyph_height':20,'rect':[190,y-10,210,y+10]}
        for key,y in [('top',50),('bottom',150)]]}


def test_literal_numbers_bind_by_pixels_and_preserve_every_edge_identity():
    prepared=plan();before=copy.deepcopy(prepared)
    graphs,notes=apply_weight_glyphs(prepared,{'readings':[{'key':'bottom','text':'3.5'},{'key':'top','text':'12'}]})
    assert not notes and [e['weight'] for e in graphs[0]['edges']]==[12,3.5]
    assert [(e['id'],e['from'],e['to'],e['path']) for e in graphs[0]['edges']]==[
        (e['id'],e['from'],e['to'],e['path']) for e in before['graphs'][0]['edges']]
    assert prepared==before


def test_a_node_name_cannot_be_interpreted_as_a_numerical_weight():
    graphs,notes=apply_weight_glyphs(plan(),{'readings':[{'key':'top','text':'v2'},{'key':'bottom','text':4}]})
    assert graphs[0]['edges'][0]['weight']==111
    assert graphs[0]['edges'][1]['weight']==4
    assert 'weight_glyph_unbound:g:upper' in notes


@pytest.mark.parametrize('readings',[
    [{'key':'top','text':1},{'key':'top','text':2}],
    [{'key':'top','text':1}],
    [{'key':'top','text':True},{'key':'bottom','text':2}],
])
def test_incomplete_or_cross_bound_literal_reads_are_atomic(readings):
    prepared=plan();before=copy.deepcopy(prepared)
    with pytest.raises(ValueError):apply_weight_glyphs(prepared,{'readings':readings})
    assert prepared==before


def test_one_glyph_cannot_supply_two_separate_edge_instances():
    prepared=plan();prepared['graphs'][0]['edges'][1]['path']=[[.1,.3],[.9,.3]]
    prepared['items']=prepared['items'][:1]
    graphs,notes=apply_weight_glyphs(prepared,{'readings':[{'key':'top','text':7}]})
    assert [e['weight'] for e in graphs[0]['edges']]==[111,222]
    assert any('ambiguous' in x for x in notes)
