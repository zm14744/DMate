"""Native hollow inventories preserve larger holes and disconnected marks."""
from PIL import Image,ImageDraw
from graph_qwen_ring_markers import ring_markers
from graph_qwen_geometry import connected_ring_markers


def test_large_holes_and_a_disconnected_circle_keep_the_same_pixel_scale():
    image=Image.new('RGB',(500,300),'white');draw=ImageDraw.Draw(image)
    draw.polygon([(70,70),(260,70),(260,230),(70,230)],outline='black',width=3)
    expected=[(70,70),(260,70),(260,230),(70,230),(400,140)]
    for x,y in expected:draw.ellipse((x-16,y-16,x+16,y+16),fill='white',outline='black',width=4)
    # These genuine holes exceed the old 300 square-pixel cap.
    assert not connected_ring_markers(image)
    points=ring_markers(image)
    assert len(points)==5 and sum(p['isolated_circle_candidate'] for p in points)==1
    assert all(min((p['x']*499-x)**2+(p['y']*299-y)**2 for p in points)<2 for x,y in expected)


def test_solid_disks_and_unmarked_crossings_do_not_create_hollow_markers():
    image=Image.new('RGB',(400,240),'white');draw=ImageDraw.Draw(image)
    draw.line((50,50,350,200),fill='black',width=3);draw.line((50,200,350,50),fill='black',width=3)
    for x,y in [(50,50),(350,50),(50,200),(350,200)]:draw.ellipse((x-14,y-14,x+14,y+14),fill='black')
    assert not ring_markers(image)


def test_pale_sphere_interiors_are_not_hollow_markers():
    image=Image.new('RGB',(400,240),'white');draw=ImageDraw.Draw(image)
    draw.rectangle((70,60,300,180),outline='black',width=3)
    for x,y in [(70,60),(300,60),(70,180),(300,180)]:
        draw.ellipse((x-15,y-15,x+15,y+15),fill=(225,225,225),outline='black',width=3)
    assert not ring_markers(image)


def test_endpoint_ring_laps_do_not_create_a_second_stroke_instance():
    import numpy as np
    from graph_schema import canonical_graph
    from graph_qwen_geometry import trim_native_rim_paths,coalesce_ink_routes
    image=Image.new('L',(201,301),0);draw=ImageDraw.Draw(image)
    draw.line((100,50,100,250),fill=255,width=3)
    for y in (50,250):draw.ellipse((85,y-15,115,y+15),fill=0,outline=255,width=3)
    graph=canonical_graph({'id':'G','vertices':[{'id':'a','x':.5,'y':50/300},{'id':'b','x':.5,'y':250/300}]})
    graph['node_position_evidence']=[{'vertex':v['id'],'radius_pixels':15,'marker_profile':'native_hollow_size_consensus'} for v in graph['vertices']]
    observed=[[100,65],[110,60],[115,50],[110,40],[100,35],[90,40],[85,50],[90,60],[100,65],[100,235]]
    traces=[{'from':'a','to':'b','method':'opencv_skeleton_tangent_trace','score':.8,'path':[[x/200,y/300] for x,y in observed]},
            {'from':'a','to':'b','method':'opencv_hough_rim_endpoint','score':.9,'path':[[.5,66/300],[.5,234/300]]}]
    assert len(coalesce_ink_routes(traces,np.asarray(image)))==2
    trimmed=trim_native_rim_paths(traces,graph,image.size)
    assert trimmed[0]['native_rim_observed_path']==traces[0]['path']
    assert len(coalesce_ink_routes(trimmed,np.asarray(image)))==1
