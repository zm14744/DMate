"""Observed marker-frame failures and thin-curve evidence, all offline."""
import copy
import math

import numpy as np
from PIL import Image

from graph_line_tracer import _sample_path
from graph_qwen_geometry import anchor_inventory
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
