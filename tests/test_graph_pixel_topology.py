"""Raster topology challenges: crossing without/with vertex and parallel arcs."""
import unittest
import cv2
import numpy as np
from graph_line_tracer import _graph_candidates


W=250
H=250


def vertex(label,x,y):
    return {"id":label,"x":x/(W-1),"y":y/(H-1)}


class PixelTopologyTests(unittest.TestCase):
    def base(self):
        return np.full((H,W,3),255,dtype=np.uint8)

    def evidence(self, image, points):
        for _,x,y in points:
            cv2.circle(image,(x,y),6,(0,0,0),-1)
        graph={"id":"G1","vertices":[vertex(name,x,y) for name,x,y in points]}
        return _graph_candidates(image,graph)

    def test_crossing_without_marker_does_not_connect_at_cross(self):
        im=self.base()
        cv2.line(im,(40,40),(210,210),(0,0,0),2)
        cv2.line(im,(40,210),(210,40),(0,0,0),2)
        cand=self.evidence(im,[
            ("a",40,40),("b",40,210),("c",210,40),("d",210,210)])
        detected={tuple(sorted((c["from"],c["to"]))) for c in cand if c["score"]>=.68}
        self.assertTrue({("a","d"),("b","c")}.issubset(detected),str(cand))
        self.assertTrue(detected.issubset({("a","d"),("b","c")}),
                        "Crossing changed topology: "+str(cand))

    def test_marked_center_breaks_both_lines_into_four_edges(self):
        im=self.base()
        cv2.line(im,(40,40),(210,210),(0,0,0),2)
        cv2.line(im,(40,210),(210,40),(0,0,0),2)
        cand=self.evidence(im,[
            ("a",40,40),("b",40,210),("c",210,40),("d",210,210),
            ("m",125,125)])
        detected={tuple(sorted((c["from"],c["to"]))) for c in cand if c["score"]>=.68}
        expected={("a","m"),("b","m"),("c","m"),("d","m")}
        self.assertTrue(expected.issubset(detected),str(cand))
        self.assertTrue(detected.issubset(expected),"Missing vertex split: "+str(cand))

    def test_straight_plus_outer_arc_are_two_independent_routes(self):
        im=self.base()
        cv2.line(im,(40,145),(210,145),(0,0,0),2)
        cv2.ellipse(im,(125,145),(85,60),0,180,360,(0,0,0),2)
        cand=self.evidence(im,[("a",40,145),("b",210,145)])
        routes=[c for c in cand if
                tuple(sorted((c["from"],c["to"])))==("a","b") and c["score"]>=.55]
        self.assertEqual(len(routes),2,"Exactly one straight and one arc should remain: "+str(cand))


if __name__=="__main__":
    unittest.main()
