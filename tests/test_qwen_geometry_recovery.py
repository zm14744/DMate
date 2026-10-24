"""Observed marker-frame failures and thin-curve evidence, all offline."""
import copy
import math

import numpy as np
from PIL import Image,ImageDraw,ImageFont

from graph_line_tracer import _sample_path
from graph_qwen_geometry import (anchor_inventory,connected_ring_markers,
    guard_local_decisions,exclude_unmeasured_proposals,locate_missing_weight_regions,
    validate_curve_tangents)
from graph_schema import canonical_graph


def make_graph():
    g=canonical_graph({'id':'G','bbox':[0,0,.75,1], 'directed':False,
        'vertices':[{'id':'a','label':'a','x':.05,'y':.4},
                    {'id':'b','label':'b','x':.7,'y':.4}],
        'edges':[{'id':'ab','from':'a','to':'b','direction':'undirected',
                  'path':[[.05,.4],[.7,.4]],'evidence':[{'source':'qwen_image_read'}]}]})
    g['node_review']={'observed_vertices':copy.deepcopy(g['vertices'])}
    return g


def test_exact_separated_marker_inventory_recovers_out_of_bounds_vertex():
    g=make_graph()
    def refiner(image, graphs, *, candidate_sink=None, **kw):
        assert all('bbox' not in x for x in graphs)
        if candidate_sink is not None:
            candidate_sink.extend([{'x':.25,'y':.5},{'x':.9,'y':.5}])
        return graphs
    anchored=anchor_inventory(Image.new('RGB',(1000,500),'white'),[g],refiner=refiner)[0]
    assert [(v['x'],v['y']) for v in anchored['vertices']]==[(.25,.5),(.9,.5)]
    assert anchored['bbox'][2]>.9
    assert anchored['edges'][0]['id']=='ab'
    assert anchored['edges'][0]['path']==[[.25,.5],[.9,.5]]
    assert anchored['node_review']['observed_vertices'][0]['x']==.05
    assert all(e['source']!='node_read' for e in anchored['edges'][0]['evidence'])


def test_coordinate_free_edge_is_preserved_while_anchoring_its_vertices():
    graph=make_graph();graph['edges'][0]['path']=[]
    def measured(image,graphs,*,candidate_sink=None,**kw):
        if candidate_sink is not None:candidate_sink.extend([{'x':.25,'y':.5},{'x':.9,'y':.5}])
        return graphs
    result=anchor_inventory(Image.new('RGB',(1000,500),'white'),[graph],refiner=measured)[0]
    assert result['edges'][0]['id']=='ab' and result['edges'][0]['path']==[]
    assert [v['x'] for v in result['vertices']]==[.25,.9]


def test_equally_good_assignment_is_not_used_to_swap_node_labels():
    g=make_graph()
    g['vertices'][0].update(x=.5,y=.5)
    g['vertices'][1].update(x=.5,y=.5)
    def refiner(image, graphs, *, candidate_sink=None, **kw):
        if candidate_sink is not None:
            candidate_sink.extend([{'x':.49,'y':.5},{'x':.51,'y':.5}])
        return graphs
    result=anchor_inventory(Image.new('RGB',(1000,500),'white'),[g],refiner=refiner)[0]
    assert [v['x'] for v in result['vertices']]==[.5,.5]
    assert 'node_position_evidence' not in result


def test_figure_disk_inventory_excludes_large_heading_ink_and_keeps_isolate():
    image=Image.new('RGB',(1000,700),'white');draw=ImageDraw.Draw(image)
    points=[(200,300),(500,300),(800,300),(200,550),(500,550),(800,550)]
    draw.line(points[:3],fill='black',width=3)
    draw.line((points[0],points[3],points[4],points[1]),fill='black',width=3)
    for x,y in points:draw.ellipse((x-12,y-12,x+12,y+12),fill='black')
    for x in (150,450,750):draw.ellipse((x-25,65,x+25,115),fill='black')
    graph=canonical_graph({'id':'g','bbox':[.1,.35,.9,.9],
        'vertices':[{'id':str(i),'x':x/999,'y':y/699} for i,(x,y) in enumerate(points)]})
    graph['node_review']={}
    def abstain(image,graphs,**kw):return graphs
    result=anchor_inventory(image,[graph],refiner=abstain)[0]
    assert len(result['node_position_evidence'])==6
    assert all(p['source']=='circular_pixel_marker_global_unique' for p in result['node_position_evidence'])
    assert all(math.dist((v['x']*999,v['y']*699),p)<1 for v,p in zip(result['vertices'],points))


def test_dense_opt_in_preserves_thin_arc_which_ten_samples_cut_across():
    path=[(300+200*math.cos(t),240-200*math.sin(t)) for t in np.linspace(math.pi,0,1000)]
    legacy=_sample_path(path,600,300)
    dense=_sample_path(path,600,300,max_error=.6)
    assert len(legacy)==10 and 10<len(dense)<=128
    def error(polyline):
        line=np.asarray([[x*599,y*299] for x,y in polyline])
        start,end=line[:-1],line[1:]
        vector=end-start
        errors=[]
        for p in np.asarray(path):
            t=np.clip(np.sum((p-start)*vector,axis=1)/np.sum(vector*vector,axis=1),0,1)
            errors.append(np.min(np.linalg.norm(p-(start+t[:,None]*vector),axis=1)))
        return max(errors)
    assert error(dense)<1 and error(legacy)>3


def test_connected_hollow_markers_exclude_round_text_glyphs():
    im=Image.new('RGB',(400,220),'white');draw=ImageDraw.Draw(im)
    draw.rectangle((60,60,220,160),outline='black',width=3)
    for x,y in ((60,60),(220,60),(60,160),(220,160)):
        draw.ellipse((x-8,y-8,x+8,y+8),fill='white',outline='black',width=3)
    draw.text((300,50),'OOOOO',fill='black')
    points=connected_ring_markers(im)
    assert len(points)==4
    assert all(p['x']<.6 for p in points)


def measured_graph():
    g=canonical_graph({'id':'G','directed':False,'weighted':False,'multigraph':False,
        'vertices':[{'id':'a','x':.2,'y':.5},{'id':'b','x':.8,'y':.5}],
        'edges':[{'id':'real','from':'a','to':'b','direction':'undirected',
                  'path':[[.2,.5],[.8,.5]],'style':'solid',
                  'evidence':[{'source':'measured_route_binding'}]}]})
    g['node_position_evidence']=[{'vertex':v['id'],'source':'circular_pixel_marker_global_unique'} for v in g['vertices']]
    g['node_review']={}
    ink=np.zeros((201,401),dtype='uint8');ink[99:102,80:321]=255
    return g,ink


def test_style_certificate_rejects_dash_gaps_hidden_by_route_tolerance():
    import cv2
    from graph_qwen_geometry import strict_solid_ink
    path=[[.1,.5],[.9,.5]]
    solid=np.zeros((101,201),dtype='uint8');solid[49:52,20:181]=255
    dashed=solid.copy();dashed[:,98:102]=0
    assert strict_solid_ink(path,solid)
    distance=cv2.distanceTransform(np.uint8(dashed==0),cv2.DIST_L2,3)
    assert distance[50,20:181].max()<3.5
    assert not strict_solid_ink(path,dashed)


def test_denial_of_measured_stroke_remains_a_recorded_conflict():
    g,ink=measured_graph()
    decisions,notes=guard_local_decisions(g,{'real':{'visible':False,'direction':'forward'}},ink)
    assert 'visible' not in decisions['real'] and decisions['real']['direction']=='undirected'
    assert len(notes)==2 and len(g['edges'])==1
    assert any(e['source']=='qwen_geometry_conflict' for e in g['edges'][0]['evidence'])


def test_negative_visual_review_is_respected_without_independent_route_evidence():
    g,ink=measured_graph();g['edges'][0]['evidence']=[{'source':'qwen_image_read'}]
    decisions,notes=guard_local_decisions(g,{'real':{'visible':False}},ink)
    assert decisions['real']['visible'] is False and not notes


def test_review_polyline_keeps_measured_stroke_identity_during_relation_replay():
    from graph_qwen_review import receive_qwen_review
    from graph_relation import recover_relations
    g,ink=measured_graph()
    # Both polylines are supported by the thick original ink but their offset
    # exceeds RELATE's matching tolerance; replacing the path used to append
    # the same measured trace again as an independent parallel edge.
    ink[97:104,80:321]=255
    decision={'real':{'visible':True,'path':[[.2,.516],[.8,.516]]}}
    decisions,_=guard_local_decisions(g,decision,ink)
    observed=[p for p in g['edges'][0]['evidence'] if p['source']=='qwen_review_measured_path_retained']
    assert observed[0]['observed_path']==decision['real']['path']
    assert 'path' not in decisions['real']
    graph,decisions,_=receive_qwen_review(g,decisions,[],ink)
    traces=[{'from':'a','to':'b','path':[[.2,.5],[.8,.5]],'style':'solid','score':.95,'method':'measured'}]
    result=recover_relations(graph,traces,review=decisions)
    assert len(result['edges'])==1 and result['edges'][0]['id']=='real'


def test_review_path_without_independent_ink_keeps_its_correction():
    g,ink=measured_graph();g['edges'][0]['evidence']=[{'source':'qwen_image_read'}]
    correction={'real':{'visible':True,'path':[[.2,.5],[.8,.5]]}}
    decisions,notes=guard_local_decisions(g,correction,ink)
    assert decisions==correction and not notes


def test_continuous_ink_at_a_sharp_join_does_not_certify_a_synthetic_arc():
    import cv2
    from graph_glm_adapter import _ink_support
    ink=np.zeros((150,180),dtype='uint8')
    cv2.polylines(ink,[np.array([[50,104],[85,80],[120,104]])],False,255,3)
    xs=np.linspace(50,120,10)
    path=[[x/179,(104-22*(1-((x-85)/35)**2))/149] for x in xs]
    # Old continuity alone approved the two different straight strokes.
    assert _ink_support(path,ink,'solid',source='qwen') is not None
    traces,notes=validate_curve_tangents([{'from':'a','to':'b','path':path,
        'method':'opencv_curved_ink_template'}],ink)
    assert not traces and notes==['curve_tangent_rejected:a:b']


def test_tangent_validation_keeps_two_distinct_real_parallel_arcs():
    import cv2
    ink=np.zeros((220,400),dtype='uint8');traces=[]
    for height in (-45,45):
        xs=np.linspace(80,320,120)
        points=np.array([[x,110+height*(1-((x-200)/120)**2)] for x in xs])
        cv2.polylines(ink,[np.rint(points).astype(int)],False,255,3)
        traces.append({'from':'a','to':'b','path':[[x/399,y/219] for x,y in points[::10]],
                       'method':'opencv_curved_ink_template'})
    kept,notes=validate_curve_tangents(traces,ink)
    assert len(kept)==2 and not notes


def test_unsupported_proposal_is_audited_instead_of_becoming_a_public_edge():
    g,ink=measured_graph()
    invented=copy.deepcopy(g['edges'][0]);invented.update(id='unsupported',path=[[.2,.5],[.5,.1],[.8,.5]],
                                                      evidence=[{'source':'qwen_image_read'}])
    g['edges'].append(invented)
    result,notes=exclude_unmeasured_proposals(g,ink)
    assert [e['id'] for e in result['edges']]==['real']
    assert result['node_review']['unsupported_edge_proposals'][0]['proposal']['id']=='unsupported'
    assert notes==['unmeasured_visual_proposal:G:unsupported']


def test_same_continuous_ink_is_not_a_second_independent_instance():
    g,ink=measured_graph()
    duplicate=copy.deepcopy(g['edges'][0]);duplicate.update(id='duplicate',evidence=[{'source':'qwen_image_read'}])
    g['edges'].append(duplicate)
    result,notes=exclude_unmeasured_proposals(g,ink)
    assert [e['id'] for e in result['edges']]==['real']
    assert result['node_review']['unsupported_edge_proposals'][0]['reason']=='no_independent_measured_instance'


def test_missing_weight_crop_isolates_nearest_text_instead_of_neighbouring_value():
    from graph_qwen_simple import select_crop,review_job
    from graph_relation import recover_relations
    im=Image.new('RGB',(400,400),'white');draw=ImageDraw.Draw(im)
    draw.line((100,100,300,300),fill='black',width=3)
    font=ImageFont.load_default(size=28)
    draw.text((195,155),'2',fill='black',font=font)
    draw.text((195,260),'4',fill='black',font=font)
    g=canonical_graph({'id':'G','weighted':True,'directed':False,'bbox':[0,0,1,1],
        'vertices':[{'id':'a','x':.25,'y':.25},{'id':'b','x':.75,'y':.75}],
        'edges':[{'id':'edge','from':'a','to':'b','direction':'undirected',
                  'path':[[.25,.25],[.75,.75]],'weight':None,'style':'solid'}]})
    result=recover_relations(g,[])
    locate_missing_weight_regions(im,result)
    plan=select_crop(im.size,[g],[result])
    assert plan['reason']=='measured_weight_region'
    x,y,right,bottom=plan['rect']
    assert right-x<128 and bottom-y<128 and bottom<250
    job=review_job(g,result['_candidates'],plan['rect'],im.size,focus_id='edge')
    assert job['candidates'][0]['allowed_fields']==['weight']


def test_partial_marker_movement_rebases_edge_proposals_without_label_changes():
    from graph_qwen_geometry import _rebase_refined_paths
    before=[make_graph()];after=copy.deepcopy(before)
    after[0]['vertices'][0].update(x=.15,y=.45)
    result=_rebase_refined_paths(after,before)[0]
    assert result['edges'][0]['path']==[[.15,.45],[.7,.4]]
    assert [v['label'] for v in result['vertices']]==['a','b']
    assert result['edges'][0]['evidence'][-1]['observed_path']==[[.05,.4],[.7,.4]]


def test_common_ink_ridge_merges_detectors_but_not_white_separated_parallel_paths():
    import cv2
    from graph_qwen_geometry import coalesce_ink_routes
    ink=np.zeros((200,400),dtype='uint8')
    cv2.line(ink,(60,100),(340,100),255,7)
    cv2.line(ink,(60,112),(340,112),255,3)
    traces=[{'from':'a','to':'b','path':[[.15,y/199],[.85,y/199]],
             'score':score} for y,score in [(100,.99),(103,.5),(112,.9)]]
    result=coalesce_ink_routes(traces,ink)
    assert len(result)==2
    assert result[0]['score']==.99
    assert result[0]['same_ink_observations'][0]['score']==.5
    assert result[1]['path']==traces[2]['path']


def test_bound_rim_trace_does_not_reappear_as_new_edge_after_endpoint_extension():
    from graph_relation import recover_relations
    graph=make_graph();trace=[[.1,.43],[.65,.43]]
    graph['edges'][0]['path']=[[.05,.4]]+trace+[[.7,.4]]
    graph['edges'][0]['evidence'].append({'source':'measured_route_binding','trace_path':trace})
    result=recover_relations(graph,[{'from':'a','to':'b','path':trace,'score':.99}])
    assert len(result['edges'])==1 and result['edges'][0]['id']=='ab'


def test_trace_cannot_switch_lines_at_crossing_but_can_follow_a_real_corner():
    import cv2
    from graph_qwen_geometry import validate_trace_junctions
    trace={'from':'a','to':'b','method':'opencv_skeleton_tangent_trace',
           'path':[[50/299,50/299],[150/299,150/299],[50/299,250/299]]}
    corner=np.zeros((300,300),dtype='uint8')
    cv2.line(corner,(50,50),(150,150),255,3)
    cv2.line(corner,(150,150),(50,250),255,3)
    assert validate_trace_junctions([trace],corner)==([trace],[])
    crossing=corner.copy()
    cv2.line(crossing,(150,150),(250,250),255,3)
    cv2.line(crossing,(150,150),(250,50),255,3)
    kept,notes=validate_trace_junctions([trace],crossing)
    assert not kept and notes==['crossing_turn_rejected:a:b']


def test_filled_caption_ink_is_not_a_curved_stroke_even_with_perfect_tangent_coverage():
    ink=np.full((220,400),255,dtype='uint8')
    trace={'from':'a','to':'b','method':'opencv_curved_ink_template',
           'path':[[.2,.5],[.5,.7],[.8,.5]]}
    kept,notes=validate_curve_tangents([trace],ink)
    assert not kept and notes==['curve_filled_region_rejected:a:b']


def test_complete_solid_disk_inventory_overrides_noisy_glyph_candidates():
    im=Image.new('RGB',(600,400),'white');draw=ImageDraw.Draw(im)
    measured=[(100,100),(350,100),(100,300),(350,300)]
    draw.rectangle((100,100,350,300),outline='black',width=3)
    for x,y in measured:draw.ellipse((x-12,y-12,x+12,y+12),fill='black')
    draw.text((460,60),'OOO',fill='black')
    g=canonical_graph({'id':'G','bbox':[0,0,1,1],'node_review':{},'vertices':[{'id':str(i),'x':x/599*.8,'y':y/399*.8} for i,(x,y) in enumerate(measured)]})
    def noisy_refiner(image,graphs,*,candidate_sink=None,**kw):
        if candidate_sink is not None:candidate_sink.extend([{'x':.9,'y':.2}]*7)
        return graphs
    result=anchor_inventory(im,[g],refiner=noisy_refiner)[0]
    assert len(result['node_position_evidence'])==4
    assert all(math.hypot(v['x']*599-x,v['y']*399-y)<2 for v,(x,y) in zip(result['vertices'],measured))


def test_fitted_curve_cannot_round_two_already_measured_straight_strokes():
    im=Image.new('L',(301,201),0);draw=ImageDraw.Draw(im)
    draw.line([(40,40),(160,40),(160,160)],fill=255,width=3)
    ink=np.asarray(im)
    traces=[{'from':'a','to':'b','method':'opencv_straight_line_coverage','path':[[40/300,40/200],[160/300,40/200]]},
            {'from':'b','to':'c','method':'opencv_straight_line_coverage','path':[[160/300,40/200],[160/300,160/200]]},
            {'from':'a','to':'c','method':'opencv_curved_ink_template','path':[[40/300,40/200],[160/300,40/200],[160/300,160/200]]}]
    retained,notes=validate_curve_tangents(traces,ink)
    assert retained==traces[:2] and notes==['curve_explained_by_straight_ink:a:c']


def test_trace_cannot_pass_along_a_measured_intermediate_ring_rim():
    from graph_qwen_geometry import validate_trace_markers
    g=canonical_graph({'id':'G','vertices':[{'id':'a','x':.1,'y':.5},{'id':'b','x':.9,'y':.5},{'id':'c','x':.5,'y':.5}]})
    g['node_position_evidence']=[{'vertex':v['id'],'source':'measured_ring','radius_pixels':10} for v in g['vertices']]
    trace={'from':'a','to':'b','path':[[.1,.5],[.5,.545],[.9,.5]]}
    kept,notes=validate_trace_markers([trace],g,(201,201))
    assert not kept and notes==['native_marker_rim_crossed:a:b']
    g['node_position_evidence'][2]['radius_pixels']=None
    assert validate_trace_markers([trace],g,(201,201))[0]==[trace]


def protocol_recovery_scene():
    image=Image.new('RGB',(501,301),(185,180,170));draw=ImageDraw.Draw(image)
    points=[(100,60),(400,60),(250,240)]
    draw.line(points+[points[0]],fill='black',width=3)
    for x,y in points:draw.ellipse((x-12,y-12,x+12,y+12),fill=(185,180,170),outline='black',width=3)
    response={'coordinate_space':'original_1000','graphs':[{'id':'G','name':'G','bbox':[0,0,1000,1000],
        'directed':True,'weighted':True,'multigraph':False,'node_complete':True,
        'vertices':[{'id':str(i),'label':chr(97+i),'x':x*2.4,'y':y/300*1000} for i,(x,y) in enumerate(points)],
        'edges':[{'id':'ab','from':'0','to':'1','direction':'forward','weight':7,'style':'solid',
                  'path':[[240,200]]*10}]}]}
    return image,response


def test_bad_model_geometry_is_recovered_only_with_every_native_vertex():
    from graph_qwen_geometry import recover_native_inventory
    from graph_qwen_coordinates import decode_inventory
    import pytest
    image,response=protocol_recovery_scene();before=copy.deepcopy(response)
    with pytest.raises(ValueError):decode_inventory(response)
    graphs=recover_native_inventory(image,response)
    assert graphs is not None and response==before
    assert [(v['label'],round(v['x'],2),round(v['y'],2)) for v in graphs[0]['vertices']]==[
        ('a',.2,.2),('b',.8,.2),('c',.5,.8)]
    edge=graphs[0]['edges'][0]
    assert (edge['id'],edge['from'],edge['to'],edge['weight'],edge['path'])==('ab','0','1',7,[])
    assert all(p['source']=='circular_pixel_marker_global_unique' for p in graphs[0]['node_position_evidence'])


def test_native_geometry_recovery_cannot_hide_semantic_errors_or_missing_circles():
    from graph_qwen_geometry import recover_native_inventory
    image,response=protocol_recovery_scene();bad=copy.deepcopy(response)
    bad['graphs'][0]['edges'][0]['to']='invented'
    assert recover_native_inventory(image,bad) is None
    assert recover_native_inventory(Image.new('RGB',image.size,'white'),response) is None
