"""Shaded marker evidence must not turn small arrowheads into vertices."""
import numpy as np
from PIL import Image,ImageDraw
from graph_qwen_gradient_markers import gradient_markers


def test_shading_and_size_consensus_keep_disks_while_excluding_arrows_and_hollow_glyphs():
    rgb=np.full((260,640,3),255,dtype='uint8')
    yy,xx=np.mgrid[:260,:640]
    centers=[(60,90),(180,90),(300,90),(420,90)]
    for x,y in centers:
        circle=(xx-x)**2+(yy-y)**2<=22**2
        values=np.clip(130+(xx-x+yy-y)*3,20,229).astype('uint8')
        rgb[circle]=values[circle,None]
    image=Image.fromarray(rgb);draw=ImageDraw.Draw(image)
    draw.ellipse((515,68,559,112),fill='black')
    draw.ellipse((570,68,614,112),outline='black',width=3)
    draw.polygon([(100,170),(120,160),(112,184)],fill='black')
    points=gradient_markers(image)
    assert len(points)==5
    for x,y in centers+[(537,90)]:
        assert any(abs(p['x']*639-x)<3 and abs(p['y']*259-y)<3 for p in points)


def test_uniform_dark_marks_alone_do_not_enable_the_shaded_marker_profile():
    image=Image.new('RGB',(400,250),'white');draw=ImageDraw.Draw(image)
    for x in (50,150,250,350):draw.ellipse((x-20,80,x+20,120),fill='black')
    assert gradient_markers(image)==[]
