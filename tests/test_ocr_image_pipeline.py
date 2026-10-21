"""CPU-only tests for bounded high-resolution OCR recovery helpers."""
import importlib
import sys
import types
import unittest
from unittest.mock import patch

import numpy as np


class _FakePaddleOCR:
    def __init__(self, *args, **kwargs):
        pass


class _FakeFormulaRecognitionPipeline:
    def __init__(self, *args, **kwargs):
        pass


fake_module = types.ModuleType("paddleocr")
fake_module.PaddleOCR = _FakePaddleOCR
fake_module.FormulaRecognitionPipeline = _FakeFormulaRecognitionPipeline
sys.modules["paddleocr"] = fake_module
sys.modules.pop("ocr", None)
ocr = importlib.import_module("ocr")


class OCRImagePipelineTests(unittest.TestCase):
    def test_large_panorama_gets_bounded_overlapping_tiles(self):
        boxes = ocr._ocr_tile_boxes(5000, 1500)
        self.assertEqual(len(boxes), 3)
        self.assertTrue(all(x2 > x1 and y2 > y1 for x1, y1, x2, y2 in boxes))
        self.assertGreater(boxes[0][2], boxes[1][0])
        self.assertGreater(boxes[1][2], boxes[2][0])

    def test_large_page_gets_at_most_four_tiles(self):
        boxes = ocr._ocr_tile_boxes(6000, 4000)
        self.assertEqual(len(boxes), 4)
        self.assertTrue(all(0 <= x1 < x2 <= 6000 and 0 <= y1 < y2 <= 4000
                            for x1, y1, x2, y2 in boxes))
        self.assertEqual(ocr._ocr_tile_boxes(2200, 1600), [])

    def test_native_tile_can_recover_missing_text_and_deduplicate_overlap(self):
        original = [
            {"type": "text", "content": "顶点集", "box": [10, 10, 70, 30], "score": .80},
        ]
        candidates = [
            {"type": "text", "content": "顶点集", "box": [11, 10, 71, 30], "score": .93, "native_tile": True},
            {"type": "text", "content": "边集", "box": [120, 10, 160, 30], "score": .91, "native_tile": True},
        ]
        merged, conflict = ocr._merge_native_tile_items(original, candidates)
        self.assertFalse(conflict)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["score"], .93)
        self.assertEqual(merged[1]["content"], "边集")

    def test_numeric_or_vertex_label_conflict_is_flagged(self):
        original = [
            {"type": "text", "content": "v3", "box": [10, 10, 36, 30], "score": .70},
        ]
        candidate = [
            {"type": "text", "content": "v5", "box": [10, 10, 36, 30], "score": .94, "native_tile": True},
        ]
        merged, conflict = ocr._merge_native_tile_items(original, candidate)
        self.assertTrue(conflict)
        self.assertEqual(merged[0]["content"], "v5")

    def test_native_tile_coordinates_map_back_to_resized_full_page(self):
        source = np.zeros((1500, 5000, 3), dtype=np.uint8)
        target_shape = (660, 2200, 3)
        candidate = {"type": "text", "content": "v1", "box": [100, 100, 140, 120], "score": .9}
        with patch.object(ocr, "_resize_if_needed", side_effect=lambda image: image), \
             unittest.mock.patch.object(ocr, "_extract_text_items", return_value=[candidate]):
            mapped = ocr._native_tile_text_items(source, target_shape)
        self.assertEqual(len(mapped), 3)
        self.assertTrue(all(0 <= item["box"][0] <= 2200 for item in mapped))
        self.assertTrue(all(0 <= item["box"][1] <= 660 for item in mapped))
        # The left tile origin is zero, and page scale is 2200/5000 = 0.44.
        self.assertAlmostEqual(mapped[0]["box"][0], 44.0, places=1)


if __name__ == "__main__":
    unittest.main()
