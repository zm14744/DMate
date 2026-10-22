"""Pixel geometry regression checks, not claims of end-to-end live OCR."""
import unittest

from graph_arrow_evidence import _interior_arrow_score
from graph_line_tracer import _same_ink_route


class MiddleOfEdgeArrowTests(unittest.TestCase):
    def setUp(self):
        self.start = (20.0, 50.0)
        self.end = (200.0, 50.0)
        self.path = [self.start, self.end]
        # One straight connector with an arrow in its interior, pointing right.
        self.stroke = [
            (20., 50., 200., 50.),
            (120., 50., 109., 41.),
            (120., 50., 109., 59.),
        ]

    def test_arrow_in_middle_detected_in_correct_direction(self):
        yes = _interior_arrow_score(
            self.stroke, self.path, self.start, self.end, radius=8)
        no = _interior_arrow_score(
            self.stroke, self.path, self.end, self.start, radius=8)
        self.assertGreaterEqual(yes, 0.49)
        self.assertLess(no, 0.49)

    def test_straight_edge_without_wings_is_not_arrow(self):
        score = _interior_arrow_score(
            [self.stroke[0]], self.path, self.start, self.end, radius=8)
        self.assertEqual(score, 0)

    def test_unmarked_crossing_is_not_automatically_an_arrow(self):
        segments = [
            (20., 50., 200., 50.),
            (120., 25., 120., 75.),
            (100., 30., 140., 70.),
        ]
        score = _interior_arrow_score(
            segments, self.path, self.start, self.end, radius=8)
        self.assertLess(score, 0.49)


class StrokeDeduplicationTests(unittest.TestCase):
    width, height = 240, 120
    pointmap = {"a": (20., 50.), "b": (200., 50.)}

    @classmethod
    def candidate(cls, coords):
        return {
            "from": "a", "to": "b",
            "path": [[x/(cls.width-1), y/(cls.height-1)]
                     for x,y in coords],
        }

    def same(self, first, second):
        return _same_ink_route(
            self.candidate(first), self.candidate(second),
            self.pointmap, self.width, self.height, radius=8)

    def test_reverse_trace_is_one_stroke(self):
        self.assertTrue(self.same(
            [(20.,50.), (110.,50.), (200.,50.)],
            [(200.,50.), (110.,50.), (20.,50.)]))

    def test_partial_hough_trace_is_not_second_parallel_edge(self):
        self.assertTrue(self.same(
            [(20.,50.), (110.,50.), (200.,50.)],
            [(60.,50.), (160.,50.)]))

    def test_distinct_outer_arc_is_not_deduplicated(self):
        self.assertFalse(self.same(
            [(20.,50.), (110.,50.), (200.,50.)],
            [(20.,50.), (60.,34.), (110.,27.), (160.,34.), (200.,50.)]))

    def test_parallel_edge_offset_is_not_deduplicated(self):
        self.assertFalse(self.same(
            [(20.,50.), (110.,50.), (200.,50.)],
            [(20.,50.), (60.,43.), (110.,43.), (160.,43.), (200.,50.)]))


if __name__ == "__main__":
    unittest.main()
