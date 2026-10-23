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


def test_single_panel_and_weighted_panels_remain_outside_the_arrow_batch_profile():
    _,graphs=scene()
    assert prepare_arrows(None,graphs[:1]) is None
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
