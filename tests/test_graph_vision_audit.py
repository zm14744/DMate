"""Mock-free production logic is covered elsewhere; this tests the Vision
provider boundary with deterministic mocked HTTP payloads (no billed API).
"""
import io
import json
import unittest
from unittest.mock import patch
from PIL import Image

import ai
from graph_integrity import review_graph_transcriptions, FLAG

GRAPH_RESPONSE = {
    "graphs": [
        {"index":1,"directed":False,"vertices":list("abcde"),
         "edges":[list(e) for e in ("ab","ac","ad","ae","bc","bd","be","cd","de")],
         "complete":True},
        {"index":2,"directed":False,"vertices":list("vwxyz"),
         "edges":[list(e) for e in ("vw","vx","vy","vz","wy","wz","xy","xz","yz")],
         "complete":True},
    ]
}

def sample_image():
    image = Image.new("RGB",(900,300),"white")
    output=io.BytesIO()
    image.save(output,format="PNG")
    return output.getvalue()


class _Response:
    def __init__(self, status, content=None):
        self.status_code=status
        self.ok=200 <= status < 300
        self.content=content
    def json(self):
        return {"choices":[{"message":{"content":json.dumps(self.content)}}]}

class GraphImageAuditBoundaryTests(unittest.TestCase):
    def test_specialized_image_read_is_separate_and_well_formed(self):
        received=[]
        def fake_post(url,headers,json,timeout):
            received.append(json)
            return _Response(200,GRAPH_RESPONSE)
        with patch.object(ai,"API_KEY","test_only_key"),patch.object(ai,"VISION_ENABLED",True),patch.object(ai.requests,"post",side_effect=fake_post):
            out=ai.verify_graph_image_independently(sample_image(),retries=0)
        self.assertTrue(out["ok"],out)
        self.assertEqual(len(out["graphs"]),2)
        self.assertEqual(len(received),1)
        payload=received[0]
        self.assertEqual(payload["model"], "qwen3-vl-235b-a22b-thinking")
        self.assertTrue(payload["enable_thinking"])
        self.assertNotIn("thinking", payload)
        self.assertEqual(payload["max_tokens"], ai.VISION_MAX_OUTPUT_TOKENS)
        contents=payload["messages"][0]["content"]
        self.assertEqual(sum(row["type"]=="image_url" for row in contents),3)
        self.assertIn("不得使用其他模型已经给出的边集", contents[0]["text"])

    def test_primary_vision_uses_qwen_without_changing_text_provider(self):
        sent = []
        url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        def fake_post(url_arg, headers, json, timeout):
            sent.append((url_arg, headers, json))
            return _Response(200, {
                "corrected_text": "判断该图是否为树",
                "visual_text": "图1：顶点 a、b；边：a-b。",
                "has_visual_structure": True,
                "image_kind": "exercise",
                "uncertain_fields": []
            })
        with patch.object(ai, "API_KEY", "qwen_test_key"), \
             patch.object(ai, "API_URL", url), \
             patch.object(ai, "VISION_ENABLED", True), \
             patch.object(ai.requests, "post", side_effect=fake_post):
            result = ai.analyze_image_structure(sample_image(), retries=0)
        self.assertTrue(result["ok"], result)
        self.assertEqual(sent[0][0], url)
        self.assertEqual(sent[0][1]["Authorization"], "Bearer qwen_test_key")
        self.assertEqual(sent[0][2]["model"], "qwen3-vl-235b-a22b-thinking")
        self.assertTrue(sent[0][2]["enable_thinking"])
        self.assertNotIn("thinking", sent[0][2])
        self.assertEqual(ai.VISION_MODEL, "qwen3-vl-235b-a22b-thinking")

    def test_vertical_original_two_graphs_are_both_zoomed(self):
        tall=Image.new("RGB",(330,570),"white")
        output=io.BytesIO()
        tall.save(output,format="PNG")
        packets=[]
        def fake_post(url,headers,json,timeout):
            packets.append(json)
            return _Response(200,GRAPH_RESPONSE)
        with patch.object(ai,"API_KEY","test_only_key"),patch.object(ai,"VISION_ENABLED",True),patch.object(ai.requests,"post",side_effect=fake_post):
            out=ai.verify_graph_image_independently(output.getvalue(),retries=0)
        self.assertTrue(out["ok"])
        frames=[item for item in packets[0]["messages"][0]["content"]
                if item["type"]=="image_url"]
        self.assertEqual(len(frames),3)

    def test_four_panel_independent_edge_audit_sends_separate_magnified_crops(self):
        packets = []
        original = Image.new("RGB", (1200, 480), "white")
        out = io.BytesIO()
        original.save(out, format="PNG")

        def fake_post(url, headers, json, timeout):
            packets.append(json)
            return _Response(200, {
                "graphs": [
                    {"index": i, "directed": False,
                     "vertices": list("abcdef"),
                     "edges": [["a", "c"], ["b", "e"]],
                     "complete": True}
                    for i in range(1, 5)
                ]
            })

        with patch.object(ai, "API_KEY", "test_only_key"), \
                patch.object(ai, "VISION_ENABLED", True), \
                patch.object(ai.requests, "post", side_effect=fake_post):
            result = ai.verify_graph_image_independently(
                out.getvalue(), retries=0, multi_edges=True, panel_count=4
            )
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["graphs"]), 4)
        content = packets[0]["messages"][0]["content"]
        self.assertEqual(sum(piece["type"] == "image_url" for piece in content), 5)
        self.assertIn("不能额外构造", content[0]["text"])

    def test_two_row_three_column_graphs_use_full_panel_crops(self):
        # The genuine Stanford tree source is a 907x566 3x2 graphic;
        # full-height thirds preserve the entire line structure while the
        # old arbitrary 60%-height crop cut across separate drawings.
        from PIL import ImageDraw
        image = Image.new("RGB", (907, 566), "white")
        draw = ImageDraw.Draw(image)
        for row_y in (80, 345):
            for col_x in (100, 355, 610):
                pts = [(col_x, row_y+40), (col_x+98, row_y),
                       (col_x+190, row_y+40), (col_x+190, row_y+150),
                       (col_x+98, row_y+185), (col_x, row_y+150)]
                for a, b in ((0,1),(1,2),(2,3),(3,4),(4,5)):
                    draw.line((*pts[a],*pts[b]), fill=(60,86,156), width=2)
                for x,y in pts:
                    draw.ellipse((x-3,y-3,x+3,y+3),fill=(44,68,117))
        strips = ai._diagram_grid_crops(image)
        self.assertEqual(len(strips), 3)
        self.assertTrue(all(crop.height == 566 for crop in strips))
        single = ai._diagram_grid_crops(image, individual=True)
        self.assertEqual(len(single), 6)
        self.assertTrue(all(crop.height < 400 for crop in single))
        raw = io.BytesIO()
        image.save(raw, format="PNG")
        prepared = ai._prepare_vision_images(
            raw.getvalue(), review_regions=[], graph_regions=[]
        )
        self.assertEqual(len(prepared), 4)
        sent = []
        def fake_post(url, headers, json, timeout):
            sent.append(json)
            return _Response(200, {
                "graphs": [
                    {"index": i, "vertex_count": 6,
                     "edge_count": 5, "complete": True}
                    for i in range(1, 7)
                ]
            })
        with patch.object(ai,"API_KEY","test_only_key"), \
                patch.object(ai,"VISION_ENABLED",True), \
                patch.object(ai.requests,"post",side_effect=fake_post):
            audited = ai.verify_graph_image_independently(
                raw.getvalue(), retries=0, count_only=True
            )
        self.assertTrue(audited["ok"])
        self.assertEqual(len(sent[0]["messages"][0]["content"]), 15)
        self.assertEqual(len(audited["graphs"]), 6)

    def test_service_failure_yields_no_provisional_graph(self):
        with patch.object(ai,"API_KEY","test_only_key"),patch.object(ai,"VISION_ENABLED",True),patch.object(ai.requests,"post",return_value=_Response(502)):
            out=ai.verify_graph_image_independently(sample_image(),retries=0)
        self.assertFalse(out["ok"])
        self.assertNotIn("graphs",out)
        graph, warnings,verified=review_graph_transcriptions("图1...图2...",None)
        self.assertFalse(verified)
        self.assertIn(FLAG,graph)


if __name__=="__main__":
    unittest.main()
