"""Synthetic illumination tests, not textbook-original accuracy claims."""
import cv2
import numpy as np

from graph_line_tracer import _foreground, _same_ink_route


def test_brown_shadow_is_not_a_dense_graph_of_foreground_pixels():
    gradient=np.tile(np.linspace(115,190,300,dtype=np.uint8),(160,1))
    image=np.stack([gradient,gradient,gradient],axis=2)
    cv2.line(image,(30,80),(270,80),(25,25,25),3)
    ink=_foreground(image)>0
    assert ink[80,60:240].mean()>.95
    assert ink[:45].mean()<.02 and ink[115:].mean()<.02
    assert ink.mean()<.08


def test_faint_print_through_does_not_join_real_front_side_strokes():
    image=np.full((160,300,3),170,dtype=np.uint8)
    cv2.line(image,(30,60),(270,60),(130,130,130),2)
    cv2.line(image,(30,100),(270,100),(25,25,25),3)
    ink=_foreground(image)>0
    assert ink[100,60:240].mean()>.95
    assert ink[60,60:240].mean()<.05


def test_dark_screen_keeps_its_bright_connector():
    image=np.full((160,300,3),25,dtype=np.uint8)
    cv2.line(image,(30,80),(270,80),(240,240,240),3)
    ink=_foreground(image)>0
    assert ink[80,60:240].mean()>.95
    assert ink[:45].mean()<.01


def test_offset_detectors_on_one_thick_ink_ridge_are_one_candidate():
    ink=np.zeros((120,240),np.uint8)
    cv2.line(ink,(20,50),(200,50),255,13)
    first={'from':'a','to':'b','path':[[20/239,50/119],[200/239,50/119]]}
    second={'from':'a','to':'b','path':[[20/239,50/119],[110/239,55/119],[200/239,50/119]]}
    assert _same_ink_route(first,second,{'a':(20,50),'b':(200,50)},240,120,8,ink=ink)


def test_white_corridor_keeps_close_parallel_strokes_independent():
    ink=np.zeros((120,240),np.uint8)
    cv2.line(ink,(20,50),(200,50),255,1)
    cv2.polylines(ink,[np.array([[20,50],[60,57],[160,57],[200,50]])],False,255,1)
    first={'from':'a','to':'b','path':[[20/239,50/119],[200/239,50/119]]}
    second={'from':'a','to':'b','path':[[20/239,50/119],[60/239,57/119],[160/239,57/119],[200/239,50/119]]}
    assert not _same_ink_route(first,second,{'a':(20,50),'b':(200,50)},240,120,8,ink=ink)
