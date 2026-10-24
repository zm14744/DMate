"""Only actual periodic gaps certify an interrupted stroke."""
import cv2
import numpy as np
from graph_qwen_dashes import dash_support
from graph_qwen_geometry import connected_fine_ink


def test_repeated_native_dashes_have_a_certificate_without_filling_the_image():
    ink=np.zeros((101,501),dtype='uint8')
    for x in range(25,476,30):cv2.line(ink,(x,50),(min(x+18,475),50),255,3)
    before=ink.copy();proof=dash_support([[.05,.5],[.95,.5]],ink)
    assert proof and proof['style']=='dashed' and len(proof['native_gap_lengths'])>=3
    assert np.array_equal(ink,before)
    assert not connected_fine_ink([[.05,.5],[.95,.5]],ink)


def test_solid_line_or_one_long_empty_span_cannot_supply_a_dash_certificate():
    ink=np.zeros((101,501),dtype='uint8');cv2.line(ink,(25,50),(475,50),255,1)
    assert dash_support([[.05,.5],[.95,.5]],ink) is None
    assert connected_fine_ink([[.05,.5],[.95,.5]],ink)
    ink[:,200:300]=0
    assert dash_support([[.05,.5],[.95,.5]],ink) is None
    assert not connected_fine_ink([[.05,.5],[.95,.5]],ink)


def test_native_interrupted_stroke_search_is_independent_of_model_line_types():
    from graph_qwen_dashes import dashed_photo_paths
    from graph_schema import canonical_graph
    ink=np.zeros((301,501),dtype='uint8');points={'a':(50,50),'b':(450,50),'c':(50,250),'d':(450,250)}
    for x in range(50,451,30):cv2.line(ink,(x,50),(min(x+18,450),50),255,3)
    cv2.line(ink,(50,50),(50,250),255,3)
    for x,y in points.values():cv2.circle(ink,(x,y),8,255,2)
    graph=canonical_graph({'id':'G','directed':False,'weighted':True,
        'vertices':[{'id':key,'x':x/500,'y':y/300} for key,(x,y) in points.items()],
        'edges':[{'id':'ab','from':'a','to':'b','style':'solid','direction':'undirected','weight':7}]})
    graph['node_position_evidence']=[{'vertex':key,'radius_pixels':8,'marker_profile':'native_hollow_size_consensus'} for key in points]
    before=ink.copy();traces=dashed_photo_paths(ink,[graph],0,(501,301),[
        {'from':'a','to':'c','style':'solid','path':[[.1,1/6],[.1,5/6]]},
        {'from':'a','to':'b','style':'dashed','path':[[.1,1/6],[.9,1/6]]}])
    assert [(t['from'],t['to'],t['style']) for t in traces]==[('a','b','dashed')]
    assert np.array_equal(ink,before)
