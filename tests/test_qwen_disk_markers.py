"""Small native disk evidence must not promote bare line intersections."""
import math
from PIL import Image,ImageDraw
from graph_qwen_disk_markers import disk_markers,disk_first_context


def test_small_disks_survive_thin_edges_without_inventing_crossing_vertices():
    image=Image.new('RGB',(720,320),'white');draw=ImageDraw.Draw(image)
    expected=[]
    for left,right in ((60,260),(460,660)):
        points=[(left,70),(right,70),(left,260),(right,260)]
        draw.rectangle((left,70,right,260),outline='black',width=1)
        draw.line((points[0],points[3]),fill='black',width=1)
        draw.line((points[1],points[2]),fill='black',width=1)
        for x,y in points:draw.ellipse((x-5,y-5,x+5,y+5),fill='black')
        expected+=points
    points=disk_markers(image)
    assert len(points)==8
    assert all(min(math.hypot(p['x']*719-x,p['y']*319-y) for x,y in expected)<1 for p in points)
    context=disk_first_context(image)
    assert len(context['markers'])==8
    assert len({p['component'] for p in context['markers']})==2
    assert all(p['marker_profile']=='native_filled_disk' for p in context['markers'])
    # Another diagram in the same row has no confidently detected circles.
    # A first-read protocol limited to the eight IDs would hide that figure.
    draw.polygon([(310,90),(410,90),(360,250)],outline='black',width=1)
    assert disk_first_context(image) is None
