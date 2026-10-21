"""Offline regression tests for the Qwen-VL HTTP/JSON boundary."""
import json
import unittest
from unittest.mock import patch

import ai


class FakeStreamingResponse:
    status_code = 200
    ok = True
    text = ""

    def __init__(self, events):
        self.events = events
        self.closed = False

    def iter_lines(self, decode_unicode=True):
        yield from self.events

    def close(self):
        self.closed = True


class QwenVisionPipelineTests(unittest.TestCase):
    def test_sse_stream_reassembles_reasoning_and_final_content(self):
        response = FakeStreamingResponse([
            "data: " + json.dumps({"choices": [{"delta": {"reasoning_content": "check "}, "finish_reason": None}]}),
            "data: " + json.dumps({"choices": [{"delta": {"reasoning_content": "edges"}, "finish_reason": None}]}),
            "data: " + json.dumps({"choices": [{"delta": {"content": "{\\"corrected_text\\":"}, "finish_reason": None}]}),
            "data: " + json.dumps({"choices": [{"delta": {"content": "\\"题目\\",\\"visual_text\\":\\"\\",\\"has_visual_structure\\":false,\\"image_kind\\":\\"exercise\\",\\"uncertain_fields\\":[]}"}, "finish_reason": None}]}),
            "data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"completion_tokens": 42}}),
            "data: [DONE]",
        ])
        with patch("ai.requests.post", return_value=response) as post:
            status, body, result = ai._request_qwen_completion(
                {"model": ai.VISION_MODEL, "stream": False}, {"Authorization": "Bearer test"}
            )
        self.assertEqual(status, 200)
        self.assertEqual(body, "")
        self.assertEqual(result["choices"][0]["message"]["reasoning_content"], "check edges")
        self.assertEqual(result["choices"][0]["finish_reason"], "stop")
        self.assertEqual(result["usage"]["completion_tokens"], 42)
        self.assertTrue(response.closed)
        self.assertTrue(post.call_args.kwargs["stream"])
        self.assertTrue(post.call_args.kwargs["json"]["stream"])

    def test_balanced_json_ignores_braces_inside_strings_and_trailing_text(self):
        text = 'preface {"corrected_text":"literal } and { inside","visual_text":"","image_kind":"exercise"} trailing note'
        data = ai._extract_first_json_object(text)
        self.assertEqual(data["corrected_text"], "literal } and { inside")
        self.assertEqual(data["image_kind"], "exercise")

    def test_json_fence_is_supported(self):
        text = chr(96) * 3 + 'json\n{"graphs":[{"edges":[]}]}' + chr(96) * 3
        self.assertEqual(ai._extract_first_json_object(text), {"graphs": [{"edges": []}]})

    def test_vision_parser_rejects_truncated_or_wrong_types(self):
        self.assertIsNone(ai._extract_vision_json('{"corrected_text":"only half"'))
        self.assertIsNone(ai._extract_vision_json('{"corrected_text":12,"visual_text":""}'))
        good = ai._extract_vision_json(
            '{"corrected_text":"题干","visual_text":"图1：3个顶点","has_visual_structure":true,'
            '"image_kind":"exercise","uncertain_fields":[]}'
        )
        self.assertEqual(good["corrected_text"], "题干")
        self.assertTrue(good["has_visual_structure"])

    def test_opencv_hints_are_valid_bounded_json_not_mid_string_slices(self):
        graphs = [{
            "id": "G1", "vertex_count": 3,
            "vertices": [{"id": f"v{i}", "x": i / 10, "y": i / 20, "label": None} for i in range(1, 4)],
            "edges": [["v1", "v2"], ["v2", "v3"]],
            "uncertain_edges": [["v1", "v3"]],
            "confidence": "partial", "bbox": [0.1, 0.1, 0.9, 0.9],
        }]
        encoded = json.dumps(ai._compact_opencv_graph_hints(graphs), ensure_ascii=False)
        parsed = json.loads(encoded)
        self.assertLessEqual(len(encoded), 5000)
        self.assertEqual(parsed["graphs"][0]["vertices"][1]["id"], "v2")
        self.assertEqual(parsed["graphs"][0]["uncertain_edges"], [["v1", "v3"]])


if __name__ == "__main__":
    unittest.main()
