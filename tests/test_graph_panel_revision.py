"""Panel corrections use explicit source identities, with no extra model call."""
import copy

from PIL import Image, ImageDraw
import pytest

from graph_evidence_pipeline import apply_topology, decode_nodes
from graph_evidence_pipeline import _footprint_json, _proposal_json
from graph_panel_revision import revise_panels, transfer_id
from graph_schema import canonical_graph
from image_evidence import analyze_document


def node(vid, x, y, source=None):
    value={'id':vid,'label':vid,'x':x,'y':y}
    if source is not None:value['source']=source
    return value


def panel(gid, nodes, bbox=None):
    return {'id':gid,'name':gid,'bbox':bbox or [0,0,1000,1000],
            'directed':False,'weighted':False,'multigraph':False,'node_complete':True,'vertices':nodes}


def decode(graphs):
    return decode_nodes({'coordinate_space':'original_1000','graphs':graphs})


def review(graph, edges):
    return {'id':graph['id'],'node_inventory_confirmed':True,'inventory_complete':True,
            'edges':edges,'candidate_verdicts':[[e['id'],True] for e in edges if not e['id'].startswith('new_')],
            'reads':[{'vertex':v['id'],'complete':True,'edge_ids':[e['id'] for e in edges
                      if v['id'] in (e['from'],e['to'])]} for v in graph['vertices']]}


def fixture():
    image=Image.new('RGB',(401,401),'white');draw=ImageDraw.Draw(image)
    for y in (100,300):
        draw.line((60,y,340,y),fill='black',width=3)
        for x in (60,340):draw.ellipse((x-5,y-5,x+5,y+5),fill='black')
    old=panel('G',[node('a',150,250),node('b',850,250),node('c',150,750),node('d',850,750)])
    upper=panel('panel_new_upper',[node('a',150,250,['G','a']),node('b',850,250,['G','b'])],[0,0,1000,450])
    lower=panel('panel_new_lower',[node('c',150,750,['G','c']),node('d',850,750,['G','d'])],[0,550,1000,1000])
    candidates={'G':[{'id':'px_1','from':'a','to':'b','path':[[.15,.25],[.85,.25]],
                      'pixel_evidence':{'supported':True}},
                     {'id':'px_2','from':'c','to':'d','path':[[.15,.75],[.85,.75]],
                      'pixel_evidence':{'supported':True}}]}
    revision={'reason':'Two separate labelled examples in the original image',
              'replaces':['G'],'graphs':[upper,lower]}
    rows=[]
    for new,c in zip((upper,lower),candidates['G']):
        e={**c,'id':transfer_id('G',c['id']),'path':[[x*1000,y*1000] for x,y in c['path']],
           'style':'solid','direction':'undirected'}
        rows.append(review(new,[e]))
    response={'coordinate_space':'original_1000','panels_complete':True,'panel_revision':revision,'graphs':rows}
    return image,old,candidates,response


def test_split_keeps_every_old_node_candidate_and_ink_source():
    image,old,candidates,response=fixture()
    actual,issues=apply_topology(response,decode([old]),candidates,analyze_document(image),panels_complete=False)
    assert not issues and len(actual)==2 and all(g['complete'] for g in actual)
    assert [len(g['edges']) for g in actual]==[1,1]
    assert actual[0]['edges'][0]['id']==transfer_id('G','px_1')
    assert actual[0]['edges'][0]['evidence'][1]['original_candidate']==['G','px_1']
    assert actual[0]['panel_revision_audit']['replaced_panels']==['G']


def test_split_cannot_silently_lose_old_node():
    _,old,candidates,response=fixture()
    response['panel_revision']['graphs'][1]['vertices'].pop()
    with pytest.raises(ValueError,match='source_nodes_unaccounted'):
        revise_panels(response,decode([old]),candidates,decode_nodes)


def test_cross_panel_candidate_needs_explicit_retirement():
    image,old,candidates,response=fixture()
    candidates['G'].append({'id':'px_cross','from':'a','to':'d','path':[[.15,.25],[.85,.75]]})
    with pytest.raises(ValueError,match='candidates_unaccounted'):
        revise_panels(response,decode([old]),candidates,decode_nodes)
    response['panel_revision']['retired_candidates']=[{'source':['G','px_cross'],'visible':None,
                                                      'reason':'The diagonal is visually uncertain'}]
    actual,issues=apply_topology(response,decode([old]),candidates,analyze_document(image),panels_complete=True)
    assert all(not g['complete'] for g in actual)
    assert any('unresolved_retired_candidate' in x for x in issues)


def test_merge_namespaces_colliding_old_ids_and_preserves_disconnected_parts():
    a=panel('A',[node('x',150,250),node('y',850,250)])
    b=panel('B',[node('x',150,750),node('y',850,750)])
    merged=panel('panel_new_merged',[node('ax',150,250,['A','x']),node('ay',850,250,['A','y']),
                                    node('bx',150,750,['B','x']),node('by',850,750,['B','y'])])
    candidates={gid:[{'id':'px_1','from':'x','to':'y'}] for gid in ('A','B')}
    response={'panel_revision':{'replaces':['A','B'],'graphs':[merged],
                               'reason':'One mathematical graph with two components'}}
    graphs,moved,issues,revised=revise_panels(response,decode([a,b]),candidates,decode_nodes)
    assert revised and not issues and len(graphs)==1
    assert {e['id'] for e in moved[merged['id']]}=={transfer_id('A','px_1'),transfer_id('B','px_1')}
    assert {(e['from'],e['to']) for e in moved[merged['id']]}=={('ax','ay'),('bx','by')}


def test_panel_transfer_remaps_connector_ports_and_direction_without_mutating_source():
    a=panel('A',[node('x',150,250),node('y',850,250)])
    merged=panel('panel_new_merged',[node('ax',150,250,['A','x']),node('ay',850,250,['A','y'])])
    candidate={'id':'px_1','from':'x','to':'y',
               'connector_evidence':{'head_vertex':'y','tail_vertex':'x','kind':'outlined_arrow'},
               'ports':[{'vertex':'x','point':[.15,.25]},{'vertex':'y','point':[.85,.25]}],
               'arrow_hint':{'from':'x','to':'y'}}
    candidates={'A':[candidate]}
    response={'panel_revision':{'replaces':['A'],'graphs':[merged],
                               'reason':'Original panel identity corrected'}}
    _,moved,issues,_=revise_panels(response,decode([a]),candidates,decode_nodes)
    assert not issues
    edge=moved[merged['id']][0]
    assert edge['connector_evidence']['head_vertex']=='ay'
    assert edge['connector_evidence']['tail_vertex']=='ax'
    assert [p['vertex'] for p in edge['ports']]==['ax','ay']
    assert edge['arrow_hint']=={'from':'ax','to':'ay'}
    assert candidate['connector_evidence']['head_vertex']=='y'
    candidate['connector_evidence']['head_vertex']='unmapped'
    with pytest.raises(ValueError,match='invalid_transferred_connector_endpoint'):
        revise_panels(response,decode([a]),candidates,decode_nodes)


def test_add_missing_panel_is_allowed_but_cannot_reuse_existing_id():
    _,old,candidates,response=fixture()
    fresh=copy.deepcopy(response['panel_revision']['graphs'][1])
    for v in fresh['vertices']:v.pop('source')
    response={'panel_revision':{'replaces':[],'graphs':[fresh],'reason':'A previously missed panel'}}
    graphs,moved,issues,revised=revise_panels(response,decode([old]),candidates,decode_nodes)
    assert len(graphs)==2 and candidates['G']==moved['G'] and not issues
    fresh['id']='G'
    with pytest.raises(ValueError,match='fresh_panel_id'):
        revise_panels(response,decode([old]),candidates,decode_nodes)


def test_reused_source_vertex_cannot_manufacture_two_nodes():
    _,old,candidates,response=fixture()
    response['panel_revision']['graphs'][1]['vertices'][0]['source']=['G','a']
    with pytest.raises(ValueError,match='reused_source_node'):
        revise_panels(response,decode([old]),candidates,decode_nodes)


def test_same_panel_bbox_can_expand_to_include_isolated_node():
    image=Image.new('RGB',(401,401),'white');draw=ImageDraw.Draw(image)
    draw.ellipse((355,195,365,205),fill='black')
    graph=panel('G',[node('v',900,500)],[0,0,800,1000])
    row=review(graph,[])
    row['panel_update']={'bbox':[0,0,1000,1000],'reason':'The isolated vertex belongs to this graph'}
    response={'coordinate_space':'original_1000','panels_complete':True,
              'panel_inventory_confirmed':True,'graphs':[row]}
    actual,issues=apply_topology(response,decode([graph]),{},analyze_document(image),panels_complete=False)
    assert not issues and actual[0]['complete'] and actual[0]['bbox']==[0,0,1,1]
    assert actual[0]['vertices'][0]['isolated_confirmed']


def test_opposite_arcs_do_not_inflate_parallel_count():
    source={'id':'G','directed':True,'weighted':False,'multigraph':True,
            'vertices':[{'id':'a'},{'id':'b'}],
            'edges':[{'id':'one','from':'a','to':'b','direction':'forward'},
                     {'id':'two','from':'b','to':'a','direction':'forward'},
                     {'id':'three','from':'a','to':'b','direction':'forward'}]}
    result=canonical_graph(source)
    assert [e['parallel_count'] for e in result['edges']]==[2,1,2]


def test_rotated_footprint_and_ports_use_full_image_coordinates():
    geometry={'center_pixels':[200,100],'semiaxes_pixels':[20,10],'angle_degrees':45,
              'confidence':.9,'kind':'hollow_marker','source':'test_pixels'}
    footprint=_footprint_json(geometry,(401,201))
    assert footprint['footprint_outline'][0]==pytest.approx([535.36,570.71],abs=.01)
    graph=decode([panel('G',[node('a',500,500),node('b',800,500)])])[0]
    graph['node_geometry_evidence']={'a':footprint}
    c={'id':'px_1','from':'a','to':'b','style':'solid','path':[[.5,.5],[.8,.5]],
       'pixel_evidence':{'coverage':1},'ports':[{'vertex':'a','point':[.55,.5],'footprint_confidence':.9}]}
    public=_proposal_json(graph,[c])
    assert public['vertices'][0]['footprint_outline']==footprint['footprint_outline']
    assert public['candidates'][0]['ports'][0]['point']==[550,500]
