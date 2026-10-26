"""Outer marker evidence must survive glyphs, eccentricity and noise bounds."""
import cv2
import numpy as np
import pytest

from graph_node_geometry import MAX_CONTOUR_PROPOSALS, estimate_marker_geometry
from graph_stroke_checks import StrokeEvidence
from image_evidence import analyze_document


def inventory(size, locations):
    return [{'id':name,'x':x/(size[0]-1),'y':y/(size[1]-1)} for name,x,y in locations]


@pytest.mark.parametrize('glyph,shift,angle', [('0',(4,-3),0),('1',(0,0),0),('2',(-4,3),18),('4',(3,4),-16),('6',(0,0),0)])
def test_outer_ellipse_wins_over_internal_numeric_glyph(glyph,shift,angle):
    image=np.full((240,460,3),255,np.uint8)
    centre=(95,120)
    cv2.ellipse(image,centre,(42,34),angle,0,360,(30,30,30),2,cv2.LINE_AA)
    cv2.putText(image,glyph,(84,128),cv2.FONT_HERSHEY_SIMPLEX,.65,(0,0,0),2,cv2.LINE_AA)
    cv2.circle(image,(355,120),25,(0,0,0),2)
    cv2.line(image,(138,120),(329,120),(0,0,0),2)
    image=cv2.GaussianBlur(image,(3,3),.6)
    nodes=inventory((460,240),[('a',centre[0]+shift[0],centre[1]+shift[1]),('b',355,120)])
    proof=StrokeEvidence(analyze_document(image_to_pil(image)))
    geometry=proof.marker_geometry(nodes[0],nodes)
    assert min(geometry['semiaxes_pixels'])>29
    assert max(geometry['semiaxes_pixels'])>37
    assert geometry['confidence']>.72
    assert geometry['kind']!='nested_outline_ambiguous'


def image_to_pil(image):
    from PIL import Image
    return Image.fromarray(image)


@pytest.mark.parametrize('radius', [3, 5, 7, 9])
def test_concentric_external_ring_is_not_swallowed_by_a_central_dot(radius):
    image=np.full((230,430,3),255,np.uint8)
    cv2.circle(image,(100,115),radius,(0,0,0),-1)
    cv2.circle(image,(100,115),38,(0,0,0),2)
    cv2.circle(image,(340,115),7,(0,0,0),-1)
    nodes=inventory((430,230),[('a',100,115),('b',340,115)])
    inspector=StrokeEvidence(analyze_document(image_to_pil(image)))
    geometry=inspector.marker_geometry(nodes[0],nodes)
    assert geometry['radius_pixels']<14
    assert geometry['kind']=='nested_outline_ambiguous'
    assert geometry['confidence']<=.5
    assert min(geometry['outer_alternative']['semiaxes_pixels'])>30


@pytest.mark.parametrize('scale', [.35, .45, .55, .65])
@pytest.mark.parametrize('thickness', [2, 3])
def test_small_bold_numeric_junction_is_not_an_independent_central_dot(scale, thickness):
    image=np.full((160,280,3),255,np.uint8)
    cv2.circle(image,(80,80),24,(0,0,0),2,cv2.LINE_AA)
    (width,height),_=cv2.getTextSize('4',cv2.FONT_HERSHEY_SIMPLEX,scale,thickness)
    cv2.putText(image,'4',(80-width//2,80+height//2),cv2.FONT_HERSHEY_SIMPLEX,
                scale,(0,0,0),thickness,cv2.LINE_AA)
    nodes=inventory((280,160),[('a',80,80),('b',240,80)])
    inspector=StrokeEvidence(analyze_document(image_to_pil(image)))
    geometry=inspector.marker_geometry(nodes[0],nodes)
    assert min(geometry['semiaxes_pixels'])>21
    assert geometry['kind']=='hollow_marker'
    assert geometry['boundary_clipped_by_image'] is False


@pytest.mark.parametrize('centre,other', [
    ((338,120),(90,120)), ((22,120),(270,120)),
    ((180,22),(180,200)), ((180,218),(180,40)),
])
def test_marker_cut_by_actual_image_border_uses_only_visible_arc(centre, other):
    image=np.full((240,360,3),255,np.uint8)
    cv2.circle(image,centre,44,(0,0,0),2,cv2.LINE_AA)
    nodes=inventory((360,240),[('a',*centre),('b',*other)])
    geometry=StrokeEvidence(analyze_document(image_to_pil(image))).marker_geometry(nodes[0],nodes)
    assert 40<min(geometry['semiaxes_pixels'])<49
    assert geometry['kind']=='hollow_marker'
    assert geometry['boundary_clipped_by_image'] is True
    assert .60<=geometry['boundary_visible_fraction']<.85
    assert geometry['boundary_support']>.85
    assert geometry['exterior_visible_fraction']<1.


@pytest.mark.parametrize('shape', ['line','short_arc','mostly_outside'])
def test_border_stroke_without_distributed_visible_ring_is_not_promoted(shape):
    image=np.full((240,360,3),255,np.uint8)
    centre=(338,120)
    if shape=='line':
        cv2.line(image,(338,35),(338,205),(0,0,0),2)
    elif shape=='short_arc':
        cv2.ellipse(image,centre,(44,44),0,90,270,(0,0,0),2,cv2.LINE_AA)
    else:
        centre=(8,8)
        cv2.circle(image,centre,44,(0,0,0),2,cv2.LINE_AA)
    nodes=inventory((360,240),[('a',*centre),('b',180,200)])
    geometry=StrokeEvidence(analyze_document(image_to_pil(image))).marker_geometry(nodes[0],nodes)
    assert geometry['kind']=='uncertain_disk'
    assert geometry['confidence']<=.25


def test_small_node_roi_does_not_make_unseen_outline_an_image_crop():
    image=np.full((260,400,3),255,np.uint8)
    cv2.circle(image,(180,130),58,(0,0,0),2,cv2.LINE_AA)
    # Nearby inventory point bounds fitting work; it does not crop the source.
    nodes=inventory((400,260),[('a',180,130),('b',250,130)])
    geometry=StrokeEvidence(analyze_document(image_to_pil(image))).marker_geometry(nodes[0],nodes)
    assert geometry['source']=='local_ink_fallback'
    assert geometry.get('boundary_clipped_by_image',False) is False
    assert geometry['confidence']==0.


def test_noise_contours_have_an_explicit_fitting_limit():
    ink=np.zeros((270,270),np.uint8)
    for x in range(8,263,7):
        for y in range(8,263,7):
            cv2.rectangle(ink,(x,y),(x+2,y+2),255,-1)
    distance=cv2.distanceTransform(np.uint8(ink==0),cv2.DIST_L2,3)
    nodes=inventory((270,270),[('a',135,135)])
    geometry=estimate_marker_geometry(ink,distance,nodes[0],nodes,(270,270))
    assert geometry['limits']['contours_seen']>MAX_CONTOUR_PROPOSALS
    assert geometry['limits']['contour_cap_reached']


def test_blank_fallback_is_explicitly_uncertain():
    image=np.full((100,160,3),255,np.uint8)
    nodes=inventory((160,100),[('a',40,50),('b',120,50)])
    inspector=StrokeEvidence(analyze_document(image_to_pil(image)))
    geometry=inspector.marker_geometry(nodes[0],nodes)
    assert geometry['confidence']==0
    assert geometry['source']=='local_ink_fallback'
    assert not inspector.vertex_supported(nodes[0],nodes)
