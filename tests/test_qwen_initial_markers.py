"""Marker candidates are observations, never an assumed graph answer."""
import copy
import io

from PIL import Image,ImageDraw
import pytest

from graph_qwen_coordinates import decode_inventory
from graph_qwen_markers import marker_context,ground_selected_markers,needs_inventory_repair


def example():
    return {'coordinate_space':'original_1000','graphs':[{
        'id':'G','name':'G','bbox':[0,0,1000,1000],'directed':False,
        'weighted':False,'multigraph':False,'node_complete':True,
        'vertices':[{'id':'a','label':None,'x':200,'y':500,'marker_id':'p1'},
                    {'id':'b','label':None,'x':800,'y':500,'marker_id':'p2'}],
        'edges':[{'id':'edge','from':'a','to':'b','direction':'undirected',
                  'edge_label':'x','style':'solid','path':[[200,500],[800,500]]}]}]}


def test_hue_separation_proposes_round_nodes_touching_different_colored_edges():
    image=Image.new('RGB',(500,300),'white');draw=ImageDraw.Draw(image)
    centers=[(80,80),(250,80),(420,80),(80,220),(250,220),(420,220)]
    for x,y in centers:draw.ellipse((x-18,y-18,x+18,y+18),fill='#5486bb')
    draw.line([(80,80),(250,80),(420,80),(420,220),(250,220),(80,220)],fill='green',width=7)
    result=marker_context(image)
    assert result is not None
    for x,y in centers:
        assert any(abs(p['x']*499-x)<4 and abs(p['y']*299-y)<4 for p in result['markers'])
    # The caller still needs a model selection, rather than declaring every
    # candidate (which may include glyphs) a vertex.
    assert set(result)=={'markers','image','strong_markers'}


def test_explicit_marker_binding_keeps_labels_and_edge_instances():
    raw=example();graphs=decode_inventory(raw);original=copy.deepcopy(raw)
    selected=ground_selected_markers(graphs,raw,[{'id':'p1','x':.25,'y':.55},
        {'id':'p2','x':.85,'y':.6},{'id':'p3','x':.5,'y':.1}])
    assert raw==original
    g=selected[0]
    assert [(v['id'],v['label'],v['x'],v['y']) for v in g['vertices']]==[
        ('a',None,.25,.55),('b',None,.85,.6)]
    assert len(g['vertices'])==2 and len(g['edges'])==1
    assert g['edges'][0]['id']=='edge' and g['edges'][0]['edge_label']=='x'
    assert g['edges'][0]['path']==[[.25,.55],[.85,.6]]
    assert g['node_review']['observed_vertices'][0]['x']==.2


@pytest.mark.parametrize('replacement',['missing','p1',False])
def test_unknown_duplicate_or_invalid_marker_selection_is_rejected_atomically(replacement):
    raw=example();raw['graphs'][0]['vertices'][1]['marker_id']=replacement
    graphs=decode_inventory(raw);saved=copy.deepcopy(graphs)
    with pytest.raises(ValueError,match='invalid_initial_marker_selection'):
        ground_selected_markers(graphs,raw,[{'id':'p1','x':.2,'y':.5},{'id':'p2','x':.8,'y':.5}])
    assert graphs==saved


def test_unmatched_real_vertex_does_not_require_a_fabricated_marker():
    raw=example();raw['graphs'][0]['vertices'][1]['marker_id']=None
    graphs=ground_selected_markers(decode_inventory(raw),raw,[{'id':'p1','x':.25,'y':.55}])
    assert graphs[0]['vertices'][1]['x']==.8
    assert 'node_position_evidence' not in graphs[0]


def test_count_repair_does_not_spend_calls_on_consistent_directed_or_weighted_graphs():
    raw=example();g=decode_inventory(raw)[0]
    context={'strong_markers':[{'x':.1,'y':.1},{'x':.8,'y':.1},
                               {'x':.1,'y':.8},{'x':.8,'y':.8}]}
    assert needs_inventory_repair([g],context)
    for key in ('directed','weighted'):
        changed=copy.deepcopy(g);changed[key]=True
        assert not needs_inventory_repair([changed],context)
    assert not needs_inventory_repair([g,g],context)
    assert not needs_inventory_repair([g],{'strong_markers':[]})
    consistent=copy.deepcopy(g);consistent['vertices']*=2
    assert not needs_inventory_repair([consistent],context)


@pytest.mark.parametrize('bad_selection',[False,True])
def test_inventory_count_conflict_uses_second_call_for_all_nodes_and_edges_without_third_call(monkeypatch,bad_selection):
    from graph_qwen_simple import recognize_simple
    from graph_staged import Budget
    original=example()
    repaired=example();g=repaired['graphs'][0]
    g['vertices']=[{'id':str(i),'label':None,'x':x,'y':y,'marker_id':'p'+str(i+1)}
                   for i,(x,y) in enumerate(((200,200),(800,200),(200,800),(800,800)))]
    g['edges']=[{'id':'top','from':'0','to':'1','direction':'undirected',
                 'path':[[200,200],[800,200]],'style':'solid'}]
    if bad_selection:g['vertices'][1]['marker_id']='p1'
    markers=[{'id':'p'+str(i+1),'x':v['x']/1000,'y':v['y']/1000}
             for i,v in enumerate(g['vertices'])]
    image=Image.new('RGB',(400,400),'white');draw=ImageDraw.Draw(image)
    draw.line((80,80,320,80),fill='black',width=3)
    for p in markers:
        x,y=p['x']*399,p['y']*399;draw.ellipse((x-7,y-7,x+7,y+7),fill='black')
    context={'markers':markers,'strong_markers':markers,'image':image}
    monkeypatch.setattr('graph_qwen_markers.marker_context',lambda im:context)
    calls=[]
    class Remote:
        name='qwen';model='qwen3-vl-plus';retries=0
        def __call__(self,prompt,images,budget):
            budget.take();calls.append((prompt,len(images)))
            assert len(calls)<=2
            return copy.deepcopy(original if len(calls)==1 else repaired)
    raw=io.BytesIO();image.save(raw,format='PNG')
    result=recognize_simple(raw.getvalue(),provider=Remote(),budget=Budget(calls=2),audit=True)
    assert [n for _,n in calls]==[1,2] and result['calls_remaining']==0
    assert len(result['graphs'][0]['vertices'])==(2 if bad_selection else 4)
    assert any(e['stage']=='INVENTORY_REPAIR.response' for e in result['stage_audit'])
    assert ('inventory_repair_failed:ValueError' in result['diagnostics']) is bad_selection
