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
        self.assertEqual(payload["thinking"]["type"],"disabled")
        contents=payload["messages"][0]["content"]
        self.assertEqual(sum(row["type"]=="image_url" for row in contents),3)
        self.assertIn("不得使用其他模型已经给出的边集", contents[0]["text"])

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
