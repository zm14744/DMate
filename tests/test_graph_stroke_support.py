"""Original-pixel proof must respect actual node sizes and faint evidence."""
import io
from unittest.mock import patch

from PIL import Image, ImageDraw

from graph_evidence_pipeline import collect_candidates
from graph_schema import canonical_graph
from graph_stroke_checks import StrokeEvidence
from image_evidence import analyze_document


def diagram(radius_a=50,radius_b=70):
    image=Image.new('RGB',(601,301),'white')
    draw=ImageDraw.Draw(image)
    draw.line((100+radius_a,150,500-radius_b,150),fill='black',width=3)
    for x,r in ((100,radius_a),(500,radius_b)):
        draw.ellipse((x-r,150-r,x+r,150+r),outline='black',width=3)
    graph=canonical_graph({'id':'G','name':'G','bbox':[0,0,1,1],
        'directed':False,'weighted':False,'multigraph':False,
        'vertices':[{'id':'a','x':100/600,'y':.5},{'id':'b','x':500/600,'y':.5}], 'edges':[]})
    return image,graph


def test_large_hollow_node_interiors_are_not_missing_edge_strokes():
    image,graph=diagram()
    inspector=StrokeEvidence(analyze_document(image))
    assert 47<=inspector.marker_radius(graph['vertices'][0],graph['vertices'])<=52
    assert 67<=inspector.marker_radius(graph['vertices'][1],graph['vertices'])<=72
    proof=inspector.inspect({'from':'a','to':'b','path':[[100/600,.5],[500/600,.5]],'style':'solid'},graph)
    assert proof['supported'] and proof['coverage']>.98


def test_skeleton_rim_paths_are_normalized_without_ignoring_external_gaps():
    image,graph=diagram(7,7)
    raw_route={'from':'a','to':'b','path':[[485/600,.5],[115/600,.5]],'style':'solid'}
    seen=[]
    def traced(raw,request,**kwargs):
        seen.append(request['graphs'][0]['measured_marker_radii'])
        return {'line_path_evidence':[{'id':'G','paths':[raw_route]}]}
    with patch('graph_line_tracer.attach_line_evidence',side_effect=traced):
        rows,_=collect_candidates(analyze_document(image),[graph])
    edge=rows['G'][0]
    assert edge['path'][0]==[100/600,.5] and edge['path'][-1]==[500/600,.5]
    assert edge['pixel_evidence']['supported'] and set(seen[0])=={'a','b'}
    # Endpoints are unchanged, but deleting an actual mid-edge section must
    # still defeat the original-pixel check after normalizing attachments.
    ImageDraw.Draw(image).rectangle((260,140,340,160),fill='white')
    with patch('graph_line_tracer.attach_line_evidence',side_effect=traced):
        rows,_=collect_candidates(analyze_document(image),[graph])
    assert not rows['G'][0]['pixel_evidence']['supported']


def test_claimed_vertex_on_blank_image_is_not_pixel_supported():
    _,graph=diagram()
    inspector=StrokeEvidence(analyze_document(Image.new('RGB',(601,301),'white')))
    assert not inspector.vertex_supported(graph['vertices'][0],graph['vertices'])
