"""Only actual periodic gaps certify an interrupted stroke."""
import cv2
import numpy as np
from graph_qwen_dashes import dash_support
from graph_qwen_geometry import connected_fine_ink


def test_repeated_native_dashes_have_a_certificate_without_filling_the_image():
    ink=np.zeros((101,501),dtype='uint8')
    for x in range(25,476,30):cv2.line(ink,(x,50),(min(x+18,475),50),255,3)
    before=ink.copy();proof=dash_support([[.05,.5],[.95,.5]],ink)
    assert proof and proof['style']=='dashed' and len(proof['native_gap_lengths'])>=3
    assert np.array_equal(ink,before)
    assert not connected_fine_ink([[.05,.5],[.95,.5]],ink)


def test_solid_line_or_one_long_empty_span_cannot_supply_a_dash_certificate():
    ink=np.zeros((101,501),dtype='uint8');cv2.line(ink,(25,50),(475,50),255,1)
    assert dash_support([[.05,.5],[.95,.5]],ink) is None
    assert connected_fine_ink([[.05,.5],[.95,.5]],ink)
    ink[:,200:300]=0
    assert dash_support([[.05,.5],[.95,.5]],ink) is None
    assert not connected_fine_ink([[.05,.5],[.95,.5]],ink)
