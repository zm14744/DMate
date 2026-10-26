"""Connectors are instances: outlined arrows differ from parallel strokes."""
import math
import cv2
import numpy as np
import pytest
from PIL import Image

from graph_connector_geometry import outlined_arrow_candidates, same_outlined_instance, validate_outlined_arrow
from graph_line_tracer import _foreground, _hough_endpoint_candidates, _straight_stroke_candidates, _vertices
from graph_stroke_checks import StrokeEvidence
from image_evidence import analyze_document


def outline_diagram(angle=0, offsets=(0,), *, heads=True, shoulders=True):
    size=(600,420)
    image=np.full((size[1],size[0],3),255,np.uint8)
    radians=math.radians(angle)
    axis=np.asarray([math.cos(radians),math.sin(radians)])
    normal=np.asarray([-axis[1],axis[0]])
    origin=np.asarray([100.,210.]);target=origin+axis*390
    radius=50 if len(offsets)>1 else 32
    records=[]
    for shift in offsets:
        x=math.sqrt(radius*radius-shift*shift)
        tail=origin+axis*x+normal*shift
        tip=target-axis*x+normal*shift
        base=tip-axis*28
        half=4.5;wing=12.5
        wall=[(tail-normal*half,base-normal*half),(tail+normal*half,base+normal*half)]
        flanks=[(base-normal*wing,tip),(base+normal*wing,tip)]
        shoulder=[(wall[0][1],flanks[0][0]),(wall[1][1],flanks[1][0])]
        lines=list(wall)
        if heads:lines+=flanks
        if heads and shoulders:lines+=shoulder
        for line in lines:
            cv2.polylines(image,[np.rint(line).astype(np.int32)],False,(0,0,0),1,cv2.LINE_AA)
        records.append({'tip':tip,'base':base,'tail':tail,'shaft_boundaries':wall,
                        'head_flanks':flanks,'shoulders':shoulder})
    for point in (origin,target):
        cv2.circle(image,tuple(np.rint(point).astype(int)),radius,(0,0,0),2,cv2.LINE_AA)
    graph={'id':'G','bbox':[0,0,1,1],'vertices':[{'id':name,'x':float(p[0]/(size[0]-1)),'y':float(p[1]/(size[1]-1))}
                                             for name,p in [('a',origin),('b',target)]], 'edges':[]}
    return image,graph,records


def proposals(image,graph):
    document=analyze_document(Image.fromarray(image))
    inspector=StrokeEvidence(document)
    geometries={v['id']:inspector.marker_geometry(v,graph['vertices']) for v in graph['vertices']}
    radii={key:value['radius_pixels'] for key,value in geometries.items()}
    found=outlined_arrow_candidates(_foreground(np.asarray(document.normalized)),_vertices(graph,*document.work_size),
                                    geometries,radii,13,offset=(0,0),full_size=document.work_size)
    return document,inspector,geometries,found


@pytest.mark.parametrize('angle',[0,19,-23])
def test_outlined_arrow_has_original_boundary_support_with_white_centre(angle):
    image,graph,_=outline_diagram(angle)
    document,inspector,geometries,found=proposals(image,graph)
    assert len(found)==1
    candidate=found[0]
    proof=validate_outlined_arrow(candidate['connector_evidence'],candidate,document.work_size,
                                  inspector.distance,inspector.strong_distance,geometries,
                                  all_distance=inspector.all_distance)
    assert proof['valid'] and proof['head_vertex']=='b'
    candidate={**candidate,'path':[[graph['vertices'][0]['x'],graph['vertices'][0]['y']]]+candidate['path']+
                                [[graph['vertices'][1]['x'],graph['vertices'][1]['y']]]}
    supported=inspector.inspect(candidate,graph)
    assert supported['supported']
    assert supported['source']=='original_pixel_connector_boundaries'
    assert supported['centreline_coverage']<.5


@pytest.mark.parametrize('heads,shoulders',[(False,False),(True,False)])
def test_parallel_walls_without_a_complete_shared_head_are_not_one_arrow(heads,shoulders):
    image,graph,_=outline_diagram(heads=heads,shoulders=shoulders)
    *_,found=proposals(image,graph)
    assert not found


def test_two_independent_outlined_arrows_with_same_endpoints_remain_instances():
    image,graph,_=outline_diagram(offsets=(-15,15))
    document,inspector,geometries,found=proposals(image,graph)
    assert len(found)==2
    first,second=[row['connector_evidence'] for row in found]
    assert not same_outlined_instance(first,second,document.ink_mask,document.work_size)
    assert not inspector.duplicate(found[0],found[1],graph=graph)


def test_outline_metadata_cannot_support_another_parallel_instances_path():
    image,graph,records=outline_diagram(offsets=(-15,15))
    document=analyze_document(Image.fromarray(image));inspector=StrokeEvidence(document)
    # Use the exact measured raster contours here, isolating route binding
    # from the independent approximate candidate-fitting problem.
    size=np.asarray(document.work_size)-1
    found=[]
    for record in records:
        meta={'kind':'outlined_arrow','head_vertex':'b','tail_vertex':'a'}
        for key in ('shaft_boundaries','head_flanks','shoulders'):
            meta[key]=(np.rint(record[key])/size).tolist()
        path=[[graph['vertices'][0]['x'],graph['vertices'][0]['y']],
              (record['tail']/size).tolist(),(record['tip']/size).tolist(),
              [graph['vertices'][1]['x'],graph['vertices'][1]['y']]]
        found.append({'from':'a','to':'b','style':'solid','path':path,'connector_evidence':meta})
    for edge in found:
        proof=inspector.inspect(edge,graph)
        assert proof['supported'] and proof['connector_instance']['route_binding']['valid']
    swapped={**found[0],'path':found[1]['path']}
    proof=inspector.inspect(swapped,graph)
    assert not proof['supported']
    assert 'outline_route_instance_mismatch' in proof['reasons']


def test_removing_head_pixels_invalidates_a_previously_proposed_instance():
    image,graph,records=outline_diagram()
    document,_,_,found=proposals(image,graph)
    assert found
    cv2.circle(image,tuple(np.rint(records[0]['tip']).astype(int)),10,(255,255,255),-1)
    modified=analyze_document(Image.fromarray(image));inspector=StrokeEvidence(modified)
    geometry={v['id']:inspector.marker_geometry(v,graph['vertices']) for v in graph['vertices']}
    result=validate_outlined_arrow(found[0]['connector_evidence'],found[0],modified.work_size,
                                   inspector.distance,inspector.strong_distance,geometry,
                                   all_distance=inspector.all_distance)
    assert not result['valid']


def test_truncated_dash_interval_does_not_destroy_repeated_pattern():
    image=np.full((150,420,3),255,np.uint8)
    ink=np.zeros((150,420),np.uint8)
    # One short residual gap at the start, followed by full dash intervals.
    cv2.line(ink,(52,75),(56,75),255,2)
    for x in range(59,370,18):cv2.line(ink,(x,75),(min(x+11,368),75),255,2)
    rows=_straight_stroke_candidates(image,[('a',40,75),('b',380,75)],0,0,13,420,150,
                                     ink_mask=ink,node_radii={'a':10,'b':10})
    assert len(rows)==1 and rows[0]['style']=='dashed'
    assert rows[0]['connector_evidence']['complete_interior_gap_count']>=3


def test_hough_body_can_stop_before_a_filled_arrow_head_without_wrong_endpoint():
    image=np.full((170,400,3),255,np.uint8)
    cv2.line(image,(49,80),(327,80),(0,0,0),1)
    cv2.fillPoly(image,[np.array([(327,74),(342,80),(327,86)],np.int32)],(0,0,0))
    for centre in ((42,80),(350,80)):cv2.circle(image,centre,7,(0,0,0),1)
    rows=_hough_endpoint_candidates(image,[('a',42,80),('b',350,80)],0,0,7,400,170,
                                    node_radii={'a':7,'b':7})
    assert rows and all({row['from'],row['to']}=={'a','b'} for row in rows)


@pytest.mark.parametrize('reversed_direction,detour',[(False,None),(True,None),(False,'white'),
                                                    (False,'tail'),(False,'head')])
def test_pipeline_uses_measured_outline_and_rejects_a_reversed_head(reversed_direction,detour):
    """Fake review outputs cannot replace independently measured arrow geometry."""
    import copy
    import graph_evidence_pipeline as pipeline

    image,graph,_=outline_diagram(19)
    wire_graph={**copy.deepcopy(graph),'bbox':[0,0,1000,1000],
                'directed':True,'weighted':False,'multigraph':False,'node_complete':True}
    for vertex in wire_graph['vertices']:
        vertex.update(x=vertex['x']*1000,y=vertex['y']*1000,label=vertex['id'])
    graphs=pipeline.decode_nodes({'coordinate_space':'original_1000','panels_complete':True,
                                  'body_complete':True,'body_text':'','graphs':[wire_graph]})
    document=analyze_document(Image.fromarray(image))
    candidates,_=pipeline.collect_candidates(document,graphs)
    outlines=[row for row in candidates['G'] if row.get('connector_evidence',{}).get('kind')=='outlined_arrow']
    assert len(outlines)==1
    candidate=outlines[0]
    assert candidate['pixel_evidence']['supported']
    assert candidate['pixel_evidence']['source']=='original_pixel_connector_boundaries'
    measured=candidate['connector_evidence']
    source,target=measured['tail_vertex'],measured['head_vertex']
    if reversed_direction:source,target=target,source
    path=copy.deepcopy(candidate['path'])
    if source!=candidate['from']:path.reverse()
    if detour=='white':path=[path[0],[.33,.12],[.66,.12],path[-1]]
    if detour in ('tail','head'):
        scale=np.asarray(document.work_size)-1
        tail=np.mean(np.asarray(measured['shaft_boundaries'])[:,0],axis=0)*scale
        tip=np.mean(np.asarray(measured['head_flanks'])[:,1],axis=0)*scale
        axis=tip-tail;axis/=np.linalg.norm(axis)
        port=tail if detour=='tail' else tip
        excursion=(port+np.asarray([axis[1],-axis[0]])*96)/scale
        if detour=='tail':path=[path[0],(tail/scale).tolist(),excursion.tolist(),(tail/scale).tolist(),(tip/scale).tolist(),path[-1]]
        else:path=[path[0],(tail/scale).tolist(),(tip/scale).tolist(),excursion.tolist(),(tip/scale).tolist(),path[-1]]
    # Both cases contain forged metadata. The genuine measurement must win:
    # reversed fake geometry on a correct edge, or fake agreement on a bad edge.
    fake=copy.deepcopy(measured)
    fake.update(head_vertex=measured['tail_vertex'],tail_vertex=measured['head_vertex'])
    edge={'id':candidate['id'],'from':source,'to':target,'direction':'forward',
          'style':'solid','path':[[x*1000,y*1000] for x,y in path],
          'connector_evidence':fake}
    row={'id':'G','directed':True,'weighted':False,'multigraph':False,
         'node_inventory_confirmed':True,'inventory_complete':True,'edges':[edge],
         'reads':[{'vertex':v['id'],'complete':True,'edge_ids':[edge['id']]} for v in graphs[0]['vertices']],
         'candidate_verdicts':[[c['id'],c['id']==candidate['id']] for c in candidates['G']]}
    final,diagnostics=pipeline.apply_topology(
        {'coordinate_space':'original_1000','panels_complete':True,'graphs':[row]},
        graphs,candidates,document,panels_complete=True)
    actual=final[0]['edges'][0]
    if detour:
        assert actual['status']=='pending' and not final[0]['complete']
        assert any('outline_route_instance_mismatch' in proof.get('reasons',[]) for proof in actual['evidence'])
        return
    proof=next(proof for proof in actual['evidence']
               if proof.get('source')=='original_pixel_connector_boundaries')
    assert proof['supported']
    assert proof['connector_instance']['head_vertex']==measured['head_vertex']
    if reversed_direction:
        assert actual['status']=='pending' and not final[0]['complete']
        assert any('connector_direction_conflict:' in reason for reason in diagnostics)
    else:
        assert actual['status']=='accepted' and final[0]['complete']
        assert not diagnostics
