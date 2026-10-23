"""Recovery references actual unique measurements; no coordinate fabrication."""
import copy
import pytest
from graph_qwen_marker_inventory import decode_marker_inventory


def response():
    return {'schema':'graph_markers_v1','graphs':[{'id':'G','name':'G',
        'directed':False,'weighted':False,'multigraph':True,'node_complete':True,
        'vertices':[['p1',None],['p2','b']],
        'edges':[['p1','p2','undirected',None,'first','solid'],
                 ['p1','p2','undirected',None,'second','solid']]}]}


def context():
    return {'markers':[{'id':'p1','x':.2,'y':.4},{'id':'p2','x':.8,'y':.6}]}


def test_exact_marker_references_keep_parallel_instances_without_synthesizing_paths():
    raw=response();before=copy.deepcopy(raw)
    graph=decode_marker_inventory(raw,context(),(500,300))[0]
    assert raw==before
    assert [(v['id'],v['x'],v['y']) for v in graph['vertices']]==[('p1',.2,.4),('p2',.8,.6)]
    assert [(e['id'],e['edge_label'],e['path']) for e in graph['edges']]==[
        ('e1','first',[]),('e2','second',[])]
    assert len(graph['node_position_evidence'])==2 and not graph['complete']


@pytest.mark.parametrize('change',[
    lambda r:r['graphs'][0]['vertices'][1].__setitem__(0,'p1'),
    lambda r:r['graphs'][0]['vertices'][1].__setitem__(0,'unmeasured'),
    lambda r:r['graphs'][0]['edges'][0].__setitem__(0,'absent'),
    lambda r:r['graphs'][0]['edges'][0].__setitem__(2,'reverse'),
    lambda r:r['graphs'].append({**copy.deepcopy(r['graphs'][0]),'id':'H'}),
])
def test_missing_duplicate_cross_panel_or_unscoped_references_are_rejected(change):
    raw=response();change(raw)
    with pytest.raises(ValueError):decode_marker_inventory(raw,context(),(500,300))


def test_omitted_anonymous_disk_requires_native_connection_to_one_selected_figure():
    from PIL import Image,ImageDraw
    from graph_qwen_marker_inventory import recover_component_markers
    image=Image.new('RGB',(400,300),'white');draw=ImageDraw.Draw(image)
    positions=[(50,100),(200,100),(125,200),(330,200)]
    draw.line([positions[0],positions[1],positions[2],positions[0]],fill='black',width=3)
    for x,y in positions:draw.ellipse((x-10,y-10,x+10,y+10),fill='red')
    points=[{'id':f'p{i+1}','x':x/399,'y':y/299} for i,(x,y) in enumerate(positions)]
    ctx={'markers':points,'strong_markers':points}
    raw=response();raw['graphs'][0]['vertices'][1][1]=None
    graphs=decode_marker_inventory(raw,ctx,image.size)
    graphs,notes=recover_component_markers(image,graphs,ctx)
    assert [v['id'] for v in graphs[0]['vertices']]==['p1','p2','p3']
    assert len(graphs[0]['edges'])==2 and not graphs[0]['node_complete']
    assert notes==['measured_component_node_recovery:G:p3']
    assert graphs[0]['bbox'][3]>200/299
