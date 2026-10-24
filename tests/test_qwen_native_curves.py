"""Native curve identity survives the bounded canonical path protocol."""
import cv2
import numpy as np
from graph_qwen_native_curves import native_cubic_paths
from graph_schema import canonical_graph,path_points
from graph_relation import recover_relations


def test_native_cubic_is_bounded_and_survives_relation_selection():
    width,height=501,351;ink=np.zeros((height,width),dtype='uint8')
    points={'a':(100,70),'b':(400,70),'c':(100,290),'d':(400,290)}
    t=np.linspace(0,1,200)[:,None]
    curve=(1-t)**3*np.array(points['a'])+3*(1-t)**2*t*np.array([110,260])+3*(1-t)*t*t*np.array([280,290])+t**3*np.array(points['d'])
    cv2.polylines(ink,[np.rint(curve).astype('int32')],False,255,5)
    for x,y in points.values():cv2.circle(ink,(x,y),16,255,3)
    graph=canonical_graph({'id':'G','weighted':False,'directed':False,
        'vertices':[{'id':key,'x':x/(width-1),'y':y/(height-1)} for key,(x,y) in points.items()], 'edges':[]})
    graph['node_position_evidence']=[{'vertex':key,'radius_pixels':16} for key in points]
    graph['node_review']={'native_full_marker_rims':True}
    traces=native_cubic_paths(ink,graph,(width,height))
    assert traces and all(2<=len(p['path'])<=128 and path_points(p['path']) for p in traces)
    result=recover_relations(graph,traces)
    assert [(e['from'],e['to']) for e in result['edges']]==[('a','d')]


def test_native_curve_search_abstains_without_complete_measured_rims():
    assert native_cubic_paths(None,{'node_review':{}},(500,300))==[]
