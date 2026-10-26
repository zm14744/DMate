"""An exterior ink arc is observed even when all its marked vertices align."""
import numpy as np
from PIL import Image,ImageDraw
from graph_schema import canonical_graph
from graph_qwen_boundary_paths import boundary_paths
from graph_glm_adapter import _ink_support


def test_native_exterior_arc_is_not_confused_with_the_split_baseline():
    image=Image.new('L',(361,241),0);draw=ImageDraw.Draw(image)
    draw.line((50,150,310,150),fill=255,width=3)
    draw.arc((50,20,310,280),180,360,fill=255,width=3)
    nodes=[('a',50),('b',180),('c',310)]
    for _,x in nodes:draw.ellipse((x-10,140,x+10,160),fill=0,outline=255,width=3)
    graph=canonical_graph({'id':'G','bbox':[0,0,1,1],'vertices':[{'id':key,'x':x/360,'y':150/240} for key,x in nodes]})
    graph['node_position_evidence']=[{'vertex':key,'radius_pixels':10,'marker_profile':'native_hollow_size_consensus'} for key,_ in nodes]
    paths=boundary_paths(np.asarray(image),graph,image.size)
    arcs=[p for p in paths if {p['from'],p['to']}=={'a','c'} and min(q[1] for q in p['path'])<.25]
    assert arcs and all(_ink_support(p['path'],np.asarray(image),'solid') is not None for p in arcs)
