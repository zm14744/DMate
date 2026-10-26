"""Coarse proposal spacing must not move a real thin arc off its pixels."""
import math

import cv2
import numpy as np
import pytest
from PIL import Image

from graph_line_tracer import _curved_stroke_candidates
from graph_stroke_checks import StrokeEvidence
from image_evidence import analyze_document


def curved_diagram(angle, *, opposite=True, erased=False):
    size=(620,440)
    image=np.full((size[1],size[0],3),255,np.uint8)
    axis=np.asarray([math.cos(math.radians(angle)),math.sin(math.radians(angle))])
    normal=np.asarray([-axis[1],axis[0]])
    centre=np.asarray([310.,220.]);a=centre-axis*190;b=centre+axis*190
    length=380.
    # Intentionally between neighbouring coarse amplitude-grid positions.
    amplitude=.045*length+5*7+3.2
    t=np.linspace(0,1,401)
    for sign in ((-1,1) if opposite else (1,)):
        points=a+t[:,None]*(b-a)+normal[None,:]*sign*amplitude*(4*t*(1-t))[:,None]
        cv2.polylines(image,[np.rint(points).astype(np.int32)],False,(0,0,0),1,cv2.LINE_AA)
    for point in (a,b):cv2.circle(image,tuple(np.rint(point).astype(int)),7,(0,0,0),-1)
    if erased:cv2.rectangle(image,(280,0),(340,size[1]-1),(255,255,255),-1)
    local=[('a',*a),('b',*b)]
    graph={'id':'G','vertices':[{'id':name,'x':float(x/(size[0]-1)),'y':float(y/(size[1]-1))}
                               for name,x,y in local],'edges':[]}
    return image,graph,local


@pytest.mark.parametrize('angle',[0,27,-34])
def test_subpixel_curve_fit_preserves_both_opposite_arcs(angle):
    image,graph,local=curved_diagram(angle)
    rows=_curved_stroke_candidates(image,local,0,0,13,image.shape[1],image.shape[0],
                                   node_radii={'a':8.,'b':8.})
    assert len(rows)==2
    inspector=StrokeEvidence(analyze_document(Image.fromarray(image)))
    for edge in rows:
        edge['path']=[[graph['vertices'][0]['x'],graph['vertices'][0]['y']]]+edge['path']+[
                      [graph['vertices'][1]['x'],graph['vertices'][1]['y']]]
        proof=inspector.inspect(edge,graph)
        assert proof['supported'] and proof['coverage']>=.90
        fit=edge['connector_evidence']['curve_fit']
        assert abs(fit['fitted_bend_pixels']-fit['initial_bend_pixels'])>0
        assert not fit['refinement_limited'] and fit['ridge_coverage']>=.90
    assert not inspector.duplicate(rows[0],rows[1],graph=graph)


def test_curve_fit_does_not_bridge_a_long_blank_middle():
    image,_,local=curved_diagram(0,opposite=False,erased=True)
    assert not _curved_stroke_candidates(image,local,0,0,13,image.shape[1],image.shape[0],
                                         node_radii={'a':8.,'b':8.})
