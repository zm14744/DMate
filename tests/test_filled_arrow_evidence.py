"""Synthetic pixel mechanisms, independent of private original-image scores."""
import cv2
import numpy as np

from graph_arrow_evidence import _filled_arrow_profile
from graph_relation import recover_relations


def mask(direction=1):
    result=np.zeros((120,260),dtype=np.uint8)
    cv2.line(result,(20,60),(240,60),255,3)
    points=[(142,60),(119,48),(119,72)] if direction==1 else [(119,60),(142,48),(142,72)]
    cv2.fillPoly(result,[np.array(points)],255)
    return result


def test_middle_filled_arrow_taper_reads_both_directions():
    for direction in (1,-1):
        actual=_filled_arrow_profile(mask(direction),[(20,60),(240,60)],8)
        assert actual and actual['orientation']==direction


def test_reversed_path_does_not_reverse_the_physical_arrow():
    actual=_filled_arrow_profile(mask(1),[(240,60),(20,60)],8)
    assert actual and actual['orientation']==-1


def test_crossing_and_uniform_thick_stroke_are_not_arrowheads():
    for crossing in (False,True):
        ink=np.zeros((120,260),dtype=np.uint8)
        cv2.line(ink,(20,60),(240,60),255,7)
        if crossing:cv2.line(ink,(80,10),(180,110),255,5)
        assert _filled_arrow_profile(ink,[(20,60),(240,60)],8) is None


def test_visual_review_cannot_silently_overwrite_opposite_arrow_pixels():
    g={'id':'G','directed':True,'weighted':False,'multigraph':False,
       'vertices':[{'id':'a','x':.1,'y':.5},{'id':'b','x':.9,'y':.5}],
       'edges':[{'id':'e','from':'a','to':'b','direction':'forward',
                 'path':[[.1,.5],[.9,.5]]}]}
    traces=[{'from':'a','to':'b','path':[[.1,.5],[.9,.5]],'score':1.,
             'arrow_candidate':{'from':'b','to':'a','score':.8,'candidate_only':True}}]
    result=recover_relations(g,traces,review={'e':{'visible':True,'direction':'forward'}})
    assert result['edges'][0]['direction']=='unknown'
    assert result['edges'][0]['status']=='pending' and not result['complete']
    assert any(e['source']=='direction_conflict' for e in result['edges'][0]['evidence'])
