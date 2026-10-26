"""Align observed Hough boundaries without merging neighbouring ink ridges."""
import math

import cv2
import numpy as np
import pytest
from PIL import Image

import graph_line_tracer as tracer
from graph_stroke_checks import StrokeEvidence
from image_evidence import analyze_document


def line_diagram(angle=0):
    size=(640,420)
    image=np.full((size[1],size[0],3),255,np.uint8)
    axis=np.asarray([math.cos(math.radians(angle)),math.sin(math.radians(angle))])
    centre=np.asarray([320.,210.]);first=np.rint(centre-axis*210);second=np.rint(centre+axis*210)
    axis=second-first;axis/=np.linalg.norm(axis);normal=np.asarray([-axis[1],axis[0]])
    cv2.line(image,tuple(first.astype(int)),tuple(second.astype(int)),(0,0,0),1,cv2.LINE_8)
    for point in (first,second):
        cv2.circle(image,tuple(point.astype(int)),30,(255,255,255),-1)
        cv2.circle(image,tuple(point.astype(int)),30,(0,0,0),1)
    local=[('a',*first),('b',*second)]
    graph={'id':'G','vertices':[{'id':name,'x':float(x/(size[0]-1)),'y':float(y/(size[1]-1))}
                               for name,x,y in local],'edges':[]}
    seed=np.rint(np.r_[first+axis*35-normal*2,second-axis*35-normal*2]).astype(np.int32)
    return image,graph,local,seed


def with_centres(edge,graph):
    return {**edge,'style':'solid','path':[[graph['vertices'][0]['x'],graph['vertices'][0]['y']]]+
            edge['path']+[[graph['vertices'][1]['x'],graph['vertices'][1]['y']]]}


@pytest.mark.parametrize('angle',[0,-6,27])
def test_hough_boundary_moves_to_observed_thin_stroke_before_original_check(monkeypatch,angle):
    image,graph,local,seed=line_diagram(angle)
    height,width=image.shape[:2]
    inspector=StrokeEvidence(analyze_document(Image.fromarray(image)))
    original={'from':'a','to':'b','path':[[float(seed[k]/(width-1)),float(seed[k+1]/(height-1))]
                                        for k in (0,2)]}
    assert not inspector.inspect(with_centres(original,graph),graph)['supported']
    monkeypatch.setattr(tracer.cv2,'HoughLinesP',lambda *args,**kwargs:seed.reshape(1,1,4))
    edges=tracer._hough_endpoint_candidates(image,local,0,0,13,width,height,node_radii={'a':30,'b':30})
    assert len(edges)==1
    aligned=edges[0]['connector_evidence']['ridge_alignment']
    assert aligned['applied']
    proof=inspector.inspect(with_centres(edges[0],graph),graph)
    assert proof['supported'] and proof['coverage']>=.95


def parallel_diagram():
    size=(600,240);image=np.full((size[1],size[0],3),255,np.uint8)
    local=[('a',60,120),('b',540,120)]
    # A lighter line and a darker neighbour are distinct instances.
    cv2.line(image,(60,118),(540,118),(140,140,140),1)
    cv2.line(image,(60,122),(540,122),(0,0,0),1)
    for _,x,y in local:
        cv2.circle(image,(x,y),22,(255,255,255),-1)
        cv2.circle(image,(x,y),22,(0,0,0),1)
    graph={'id':'G','vertices':[{'id':name,'x':x/(size[0]-1),'y':y/(size[1]-1)} for name,x,y in local],'edges':[]}
    return image,graph,local


def test_parallel_thin_ridges_keep_their_own_paths_even_if_one_is_darker(monkeypatch):
    image,graph,local=parallel_diagram()
    seeds=np.asarray([[[86,117,514,117]],[[86,123,514,123]]],np.int32)
    monkeypatch.setattr(tracer.cv2,'HoughLinesP',lambda *args,**kwargs:seeds)
    edges=tracer._hough_endpoint_candidates(image,local,0,0,13,600,240,node_radii={'a':22,'b':22})
    assert len(edges)==2
    levels=sorted(float(np.mean(np.asarray(edge['path'])[:,1]))*239 for edge in edges)
    assert levels==pytest.approx([118,122],abs=.3)
    inspector=StrokeEvidence(analyze_document(Image.fromarray(image)))
    edges=[with_centres(edge,graph) for edge in edges]
    assert all(inspector.inspect(edge,graph)['supported'] for edge in edges)
    assert not inspector.duplicate(*edges,graph=graph)


def test_white_gap_between_equally_close_parallel_lines_is_not_assigned_a_ridge(monkeypatch):
    image,graph,local=parallel_diagram()
    seed=np.asarray([[[86,120,514,120]]],np.int32)
    monkeypatch.setattr(tracer.cv2,'HoughLinesP',lambda *args,**kwargs:seed)
    edges=tracer._hough_endpoint_candidates(image,local,0,0,13,600,240,node_radii={'a':22,'b':22})
    assert len(edges)==1
    alignment=edges[0]['connector_evidence']['ridge_alignment']
    assert not alignment['applied'] and alignment['ambiguous_sections']>0
    inspector=StrokeEvidence(analyze_document(Image.fromarray(image)))
    assert not inspector.inspect(with_centres(edges[0],graph),graph)['supported']


def test_alignment_cannot_hop_between_disjoint_offset_fragments():
    mask=np.zeros((160,520),np.uint8)
    cv2.line(mask,(40,70),(248,70),255,1)
    cv2.line(mask,(272,76),(480,76),255,1)
    first,second,measurement=tracer._hough_ridge_alignment(mask,(40,70),(480,76))
    assert not measurement['applied']
    assert first==pytest.approx([40,70]) and second==pytest.approx([480,76])


def test_optional_alignment_preserves_a_measured_small_terminal_attachment(monkeypatch):
    # The visible body and an offset terminal tip belong to one connector.
    # Its Canny boundary reaches the small marker; translating the whole
    # line to the body centre would make the extended ray miss that marker.
    image=np.full((160,520,3),255,np.uint8)
    cv2.line(image,(60,80),(435,80),(0,0,0),3)
    cv2.fillPoly(image,[np.asarray([[435,74],[450,73],[435,86]],np.int32)],(0,0,0))
    local=[('a',60,80),('b',450,73)]
    for _,x,y in local:cv2.circle(image,(x,y),4,(0,0,0),-1)
    graph={'id':'G','vertices':[{'id':name,'x':x/519,'y':y/159} for name,x,y in local],'edges':[]}
    seed=np.asarray([[[66,78,435,78]]],np.int32)
    monkeypatch.setattr(tracer.cv2,'HoughLinesP',lambda *args,**kwargs:seed)
    edges=tracer._hough_endpoint_candidates(image,local,0,0,4,520,160,node_radii={'a':4,'b':4})
    assert len(edges)==1 and (edges[0]['from'],edges[0]['to'])==('a','b')
    alignment=edges[0]['connector_evidence']['ridge_alignment']
    assert not alignment['applied'] and alignment['fallback_to_original_route']
    assert alignment['reason']=='aligned_route_lost_original_attachment'
    inspector=StrokeEvidence(analyze_document(Image.fromarray(image)))
    assert inspector.inspect(with_centres(edges[0],graph),graph)['supported']
