"""Native tip reads change direction, never endpoints' identities or edge counts."""
import copy
import pytest
from PIL import Image,ImageDraw
from graph_schema import canonical_graph
from graph_qwen_arrows import prepare_arrows,apply_arrows,apply_native_arrows


def scene():
    image=Image.new('RGB',(500,300),'white');draw=ImageDraw.Draw(image)
    pairs=[((50,60),(230,60)),((300,250),(300,70))]
    graphs=[]
    for i,(a,b) in enumerate(pairs):
        draw.line([a,b],fill='black',width=3)
        for x,y in (a,b):draw.ellipse((x-11,y-11,x+11,y+11),fill='gray')
        graph=canonical_graph({'id':f'G{i}','directed':True,'weighted':False,
            'vertices':[{'id':key,'x':x/499,'y':y/299} for key,(x,y) in zip(('a','b'),(a,b))],
            'edges':[{'id':'stroke','from':'a','to':'b','direction':'unknown','style':'solid',
                      'path':[[a[0]/499,a[1]/299],[b[0]/499,b[1]/299]]}]})
        graph['node_position_evidence']=[{'source':'component_circle_inventory','vertex':key} for key in ('a','b')]
        graphs.append(graph)
    draw.polygon([(130,60),(155,48),(155,72)],fill='black')
    draw.polygon([(300,140),(288,165),(312,165)],fill='black')
    return image,graphs


def test_native_head_batch_reverses_only_the_actual_reverse_arrow():
    image,graphs=scene();before=copy.deepcopy(graphs);plan=prepare_arrows(image,graphs)
    assert plan is not None and len(plan['items'])==2
    response={'arrows':[{'key':item['key'],'tip':'left' if item['graph_index']==0 else 'up'} for item in plan['items']]}
    output,notes=apply_arrows(plan,response)
    assert not notes and graphs==before
    assert [(g['edges'][0]['from'],g['edges'][0]['to']) for g in output]==[('b','a'),('a','b')]
    assert all(len(g['edges'])==1 and g['edges'][0]['id']=='stroke' and g['edges'][0]['direction']=='forward' for g in output)
    assert output[0]['edges'][0]['path'][0]==before[0]['edges'][0]['path'][-1]
    assert output[0]['edges'][0]['evidence'][-1]['prior_direction']=='unknown'


@pytest.mark.parametrize('arrows',[
    [{'key':'A','tip':'left'}],
    [{'key':'A','tip':'left'},{'key':'A','tip':'up'}],
    [{'key':'A','tip':'left'},{'key':'B','tip':'invented'}],
])
def test_arrow_batch_requires_exact_scoped_keys_and_physical_tip_enum(arrows):
    image,graphs=scene();plan=prepare_arrows(image,graphs);before=copy.deepcopy(graphs)
    with pytest.raises(ValueError):apply_arrows(plan,{'arrows':arrows})
    assert graphs==before


def test_single_panel_heads_are_measured_and_weighted_panels_abstain():
    image,graphs=scene()
    plan=prepare_arrows(image,graphs[:1])
    assert plan is not None and len(plan["items"])==1
    output,weak=apply_native_arrows(plan)
    assert not weak and output[0]["edges"][0]["from"]=="b"
    graphs[0]['weighted']=True
    assert prepare_arrows(None,graphs) is None


def test_a_small_crossing_blob_does_not_compete_with_a_full_size_arrowhead():
    image,graphs=scene();draw=ImageDraw.Draw(image)
    draw.line((172,52,188,68),fill='black',width=5)
    draw.line((172,68,188,52),fill='black',width=5)
    plan=prepare_arrows(image,graphs)
    assert plan is not None
    first=next(item for item in plan['items'] if item['graph_index']==0)
    assert first['head_center'][0]<170


def test_native_triangle_asymmetry_resolves_direction_without_model_direction_words():
    image,graphs=scene();before=copy.deepcopy(graphs);plan=prepare_arrows(image,graphs)
    output,weak=apply_native_arrows(plan)
    assert not weak and graphs==before
    assert [(g['edges'][0]['from'],g['edges'][0]['to']) for g in output]==[('b','a'),('a','b')]
    assert all(g['edges'][0]['evidence'][-1]['source']=='native_arrow_head_axis_asymmetry' for g in output)


def test_a_weak_native_head_keeps_its_direction_open_for_local_review():
    image,graphs=scene();plan=prepare_arrows(image,graphs);plan['items'][0]['axis_resolved']=False
    output,weak=apply_native_arrows(plan)
    assert [item['key'] for item in weak]==[plan['items'][0]['key']]
    assert output[plan['items'][0]['graph_index']]['edges'][0]['direction']=='unknown'


def test_measurements_of_one_head_cannot_certify_two_different_edge_instances():
    from graph_qwen_arrows import _merge_head_scales
    item={'graph_index':0,'id':'first','head_center':[100,80],'axis_resolved':True,'axis_skew':.3}
    other={**item,'id':'second','head_center':[101,80]}
    large={'items':[item]};small={'items':[other]};before=copy.deepcopy((large,small))
    result=_merge_head_scales(large,small)
    assert len(result)==2 and all(not p['axis_resolved'] and p['shared_native_head_conflict'] for p in result)
    assert (large,small)==before


def test_contradicting_scales_keep_the_same_edge_unresolved():
    from graph_qwen_arrows import _merge_head_scales
    item={'graph_index':0,'id':'edge','head_center':[100,80],'axis_resolved':True,'axis_skew':.3}
    result=_merge_head_scales({'items':[item]},{'items':[{**item,'axis_skew':-.3}]})
    assert len(result)==1 and result[0]['id']=='edge'
    assert not result[0]['axis_resolved'] and result[0]['scale_direction_conflict']


def test_self_loop_does_not_block_other_heads_and_keeps_its_attributes():
    image,graphs=scene();loop=copy.deepcopy(graphs[0]['edges'][0]);loop.update(id='loop',to='a',edge_label='x',direction='forward')
    graphs[0]['edges'].append(loop);plan=prepare_arrows(image,graphs[:1]);output,weak=apply_native_arrows(plan)
    assert not weak and len(output[0]['edges'])==2
    assert output[0]['edges'][1]==loop


def test_small_arrow_touching_coloured_node_keeps_its_own_tip():
    image=Image.new('RGB',(300,160),'white');draw=ImageDraw.Draw(image)
    draw.line((50,70,230,70),fill='gray',width=1)
    draw.polygon([(222,70),(211,64),(211,76)],fill='black')
    for x in (50,230):draw.ellipse((x-8,62,x+8,78),fill='#5588bb')
    graph=canonical_graph({'id':'G','directed':True,'weighted':False,
        'vertices':[{'id':'a','x':50/299,'y':70/159},{'id':'b','x':230/299,'y':70/159}],
        'edges':[{'id':'e','from':'b','to':'a','direction':'forward','edge_label':'s',
                  'path':[[230/299,70/159],[50/299,70/159]]}]})
    graph['node_position_evidence']=[{'vertex':v['id'],'source':'native_circle','radius_pixels':8} for v in graph['vertices']]
    plan=prepare_arrows(image,[graph]);assert plan is not None
    output,weak=apply_native_arrows(plan)
    assert not weak and output[0]['edges'][0]['from']=='a'
    assert output[0]['edges'][0]['edge_label']=='s'


def test_open_wings_touching_hollow_node_resolve_the_tip_and_preserve_edge_name():
    from graph_qwen_open_arrows import prepare_open_arrows
    image=Image.new('RGB',(300,160),'white');draw=ImageDraw.Draw(image)
    draw.line((50,70,230,70),fill='black',width=2)
    draw.line([(209,64),(220,70),(209,76)],fill='black',width=2)
    for x in (50,230):draw.ellipse((x-8,62,x+8,78),fill='white',outline='black',width=3)
    graph=canonical_graph({'id':'G','directed':True,'weighted':False,
        'vertices':[{'id':'a','x':50/299,'y':70/159},{'id':'b','x':230/299,'y':70/159}],
        'edges':[{'id':'e','from':'b','to':'a','direction':'forward','edge_label':'s',
                  'path':[[230/299,70/159],[50/299,70/159]]}]})
    graph['node_position_evidence']=[{'vertex':v['id'],'radius_pixels':8,
        'source':'native_circle','marker_profile':'native_hollow_size_consensus'} for v in graph['vertices']]
    plan=prepare_open_arrows(image,[graph]);assert plan is not None
    output,weak=apply_native_arrows(plan)
    assert not weak and output[0]['edges'][0]['from']=='a'
    assert output[0]['edges'][0]['edge_label']=='s'
    assert output[0]['edges'][0]['evidence'][-1]['source']=='native_open_arrow_wings'


def test_weighted_native_crop_preserves_every_instance_and_uses_connected_taper():
    from graph_qwen_arrows import prepare_weighted_arrows
    image=Image.new('RGB',(501,201),(185,180,170));draw=ImageDraw.Draw(image)
    draw.line((50,100,450,100),fill='black',width=3)
    draw.polygon([(220,100),(250,92),(250,108)],fill='black')
    graph=canonical_graph({'id':'G','directed':True,'weighted':True,
        'vertices':[{'id':'a','x':.1,'y':.5},{'id':'b','x':.9,'y':.5}],
        'edges':[{'id':'physical','from':'a','to':'b','direction':'unknown','weight':7,
                  'path':[[.1,.5],[.9,.5]]}]})
    graph['node_position_evidence']=[{'vertex':k,'source':'measured','radius_pixels':11,
        'marker_profile':'native_hollow_size_consensus'} for k in ('a','b')]
    before=copy.deepcopy(graph);plan=prepare_weighted_arrows(image,[graph])
    assert graph==before and plan is not None
    assert [(p['id'],p['axis_resolved']) for p in plan['items']]==[('physical',True)]
    native,unresolved=apply_native_arrows(plan)
    assert not unresolved and native[0]['edges'][0]['from']=='b'
    assert native[0]['edges'][0]['evidence'][-1]['source']=='native_connected_ink_width_taper'
    result,notes=apply_arrows(plan,{'arrows':[{'key':plan['items'][0]['key'],'tip':'left'}]})
    assert not notes and len(result[0]['edges'])==1
    assert (result[0]['edges'][0]['from'],result[0]['edges'][0]['to'],result[0]['edges'][0]['weight'])==('b','a',7)
