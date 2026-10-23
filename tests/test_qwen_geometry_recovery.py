"""Observed marker-frame failures and thin-curve evidence, all offline."""
import copy
import math

import numpy as np
from PIL import Image,ImageDraw

from graph_line_tracer import _sample_path
from graph_qwen_geometry import (anchor_inventory,connected_ring_markers,
    guard_local_decisions,exclude_unmeasured_proposals)
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
