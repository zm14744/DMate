"""Real pixel drawings for the lightweight arrowhead detector (no OCR/VLM)."""
import unittest
import cv2
import numpy as np
from graph_arrow_evidence import annotate_arrow_candidates


class PixelArrowImageTests(unittest.TestCase):
    def make_image(self, direction=None):
        image=np.full((150,260,3),255,dtype=np.uint8)
        cv2.line(image,(30,70),(230,70),(0,0,0),2)
        cv2.circle(image,(30,70),5,(0,0,0),2)
        cv2.circle(image,(230,70),5,(0,0,0),2)
        if direction == "right":
            cv2.line(image,(135,70),(120,60),(0,0,0),2)
            cv2.line(image,(135,70),(120,80),(0,0,0),2)
        elif direction == "left":
            cv2.line(image,(125,70),(140,60),(0,0,0),2)
            cv2.line(image,(125,70),(140,80),(0,0,0),2)
        graph={"id":"G1","vertices":[
            {"id":"a","x":30/259,"y":70/149},
            {"id":"b","x":230/259,"y":70/149}]}
        path=[{"from":"a","to":"b",
               "path":[[30/259,70/149],[230/259,70/149]]}]
        return image,graph,path

    def test_real_pixels_forward_arrow_midway(self):
        im,graph,paths=self.make_image("right")
        annotate_arrow_candidates(im,graph,paths,8)
        self.assertEqual(
            (paths[0].get("arrow_candidate") or {}).get("to"),"b",
            "Mid-edge arrowhead must point to vertex b")

    def test_real_pixels_reverse_arrow_midway(self):
        im,graph,paths=self.make_image("left")
        annotate_arrow_candidates(im,graph,paths,8)
        self.assertEqual(
            (paths[0].get("arrow_candidate") or {}).get("to"),"a",
            "Mid-edge arrowhead must point to vertex a")

    def test_plain_pixel_line_is_not_a_directed_edge(self):
        im,graph,paths=self.make_image()
        annotate_arrow_candidates(im,graph,paths,8)
        self.assertFalse(paths[0].get("arrow_candidate"))


if __name__=="__main__":
    unittest.main()
