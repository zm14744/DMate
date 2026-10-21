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
            "data: " + json.dumps({"choices": [{"delta": {"content": '{"corrected_text":'}, "finish_reason": None}]}),
            "data: " + json.dumps({"choices": [{"delta": {"content": '"题目","visual_text":"","has_visual_structure":false,"image_kind":"exercise","uncertain_fields":[]}'}, "finish_reason": None}]}),
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

    def test_analyze_uses_streaming_and_a_separate_reasoning_budget(self):
        image_bytes = b"\x89PNG\r\n\x1a\n" + b"test"
        model_output = json.dumps({
            "corrected_text": "题干",
            "visual_text": "",
            "has_visual_structure": False,
            "image_kind": "exercise",
            "uncertain_fields": [],
        }, ensure_ascii=False)
        normalized = {"choices": [{
            "message": {"content": model_output},
            "finish_reason": "stop",
        }]}
        with patch.object(ai, "API_KEY", "test-key"), \
             patch.object(ai, "_prepare_vision_images", return_value=["data:image/png;base64,AA=="]), \
             patch.object(ai, "_request_qwen_completion", return_value=(200, "", normalized)) as request:
            result = ai.analyze_image_structure(image_bytes, retries=0)
        self.assertTrue(result["ok"])
        payload = request.call_args.args[0]
        self.assertTrue(payload["stream"])
        self.assertTrue(payload["enable_thinking"])
        self.assertEqual(payload["thinking_budget"], ai.VISION_THINKING_BUDGET)
        self.assertLessEqual(payload["thinking_budget"], payload["max_tokens"] - 2048)
        self.assertEqual(payload["temperature"], 0.1)

    def test_structured_graph_data_preserves_loops_parallel_arcs_and_isolated_vertices(self):
        payload = {
            "corrected_text": "",
            "visual_text": "错误的自然语言描述：星形图，中心 x。",
            "has_visual_structure": True,
            "image_kind": "exercise",
            "uncertain_fields": [],
            "graph_data": [{
                "id": "G1",
                "directed": True,
                "weighted": False,
                "multigraph": True,
                "vertices": [
                    {"id": "a", "label": "a", "x": .1, "y": .2},
                    {"id": "b", "label": "b", "x": .5, "y": .4},
                    {"id": "c", "label": "c", "x": .8, "y": .8},
                ],
                "edges": [
                    {"from": "a", "to": "a", "edge_label": "e1", "weight": None},
                    {"from": "a", "to": "b", "edge_label": "e2", "weight": None},
                    {"from": "b", "to": "a", "edge_label": "e3", "weight": None},
                    {"from": "a", "to": "b", "edge_label": "e4", "weight": None},
                ],
                "uncertain_edges": [],
                "complete": True,
            }],
        }
        parsed = ai._extract_vision_json(json.dumps(payload, ensure_ascii=False))
        self.assertIsNotNone(parsed)
        visual = parsed["visual_text"]
        self.assertNotIn("星形图", visual)
        self.assertIn("a→a（自环", visual)
        self.assertEqual(visual.count("a→b"), 2)
        self.assertIn("b→a", visual)
        self.assertIn("孤立顶点：c", visual)
        self.assertIn("共 4 条边", visual)
        self.assertNotIn("【图形结构待核对】", visual)
        self.assertEqual(len(parsed["graph_data"][0]["edges"]), 4)

    def test_bad_edge_endpoint_is_demoted_to_uncertainty(self):
        payload = {
            "corrected_text": "",
            "visual_text": "模型称图中有 a-b。",
            "has_visual_structure": True,
            "image_kind": "exercise",
            "uncertain_fields": [],
            "graph_data": [{
                "id": "G1", "directed": False, "weighted": False,
                "multigraph": False,
                "vertices": [{"id": "a", "label": "a", "x": .2, "y": .2},
                             {"id": "b", "label": "b", "x": .8, "y": .8}],
                "edges": [{"from": "a", "to": "z", "edge_label": None, "weight": None}],
                "uncertain_edges": [], "complete": True,
            }],
        }
        parsed = ai._extract_vision_json(json.dumps(payload, ensure_ascii=False))
        self.assertIsNotNone(parsed)
        self.assertIn("【图形结构待核对】", parsed["visual_text"])
        self.assertIn("端点不在顶点表中", parsed["visual_text"])
        self.assertNotIn("a-b", parsed["visual_text"])
        self.assertFalse(parsed["graph_data"][0]["complete"])
        self.assertEqual(parsed["graph_data"][0]["edges"], [])

    def test_incomplete_graph_data_never_claims_total_edge_count(self):
        payload = {
            "corrected_text": "判断图的连通性",
            "visual_text": "",
            "has_visual_structure": True,
            "image_kind": "exercise",
            "uncertain_fields": [],
            "graph_data": [{
                "id": "G2", "directed": False, "weighted": False,
                "multigraph": False,
                "vertices": ["a", "b", "c"],
                "edges": [{"from": "a", "to": "b", "edge_label": None, "weight": None}],
                "uncertain_edges": ["b-c 的端点被遮挡"],
                "complete": False,
            }],
        }
        parsed = ai._extract_vision_json(json.dumps(payload, ensure_ascii=False))
        self.assertIsNotNone(parsed)
        self.assertIn("【图形结构待核对】", parsed["visual_text"])
        self.assertIn("当前已确认 1 条边；总边数待核对", parsed["visual_text"])
        self.assertNotIn("共 1 条边", parsed["visual_text"])

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
