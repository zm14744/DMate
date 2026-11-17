"""Keep web startup independent of optional native image readers.

No models, provider calls or deployment credentials are needed. The first
check starts a fresh interpreter so prior test imports cannot mask eager work.
"""

import io
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class LightweightStartupTests(unittest.TestCase):
    def test_home_and_health_start_without_native_image_readers_or_network(self):
        source = r'''
import importlib.abc
import json
import sys
import time
from unittest.mock import patch
import requests

forbidden = {
    'cv2', 'numpy', 'paddle', 'paddleocr', 'paddlex', 'onnxruntime', 'torch',
    'graph_recognition', 'graph_line_tracer', 'graph_validation', 'graph_evidence_fusion',
}
class NoImageReaders(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in forbidden:
            raise AssertionError('Optional image reader imported during web startup: ' + fullname)

sys.meta_path.insert(0, NoImageReaders())
started = time.monotonic()
with patch('requests.sessions.Session.request', side_effect=AssertionError('Startup made a remote request')):
    import app
    app.app.config.update(TESTING=True)
    client = app.app.test_client()
    health = client.get('/health')
    ready = client.get('/ready')
    home = client.get('/')
    assert health.status_code == ready.status_code == home.status_code == 200
    assert health.get_json()['status'] == 'ok'
    assert ready.get_json()['graph_nextgen_enabled'] is True
    assert ready.get_json()['ocr_available'] is True
    assert ready.get_json()['ocr_ready'] is False
    assert not forbidden.intersection(sys.modules)
print(json.dumps({'seconds': round(time.monotonic() - started, 4), 'status': 'ok'}))
'''
        env = dict(os.environ, DMATE_GRAPH_NEXTGEN="1", DMATE_GRAPH_PIPELINE="agent-tools")
        completed = subprocess.run([sys.executable, "-c", source], cwd=ROOT, env=env,
                                   text=True, capture_output=True, timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        result = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertEqual(result["status"], "ok")

    def test_legacy_graph_upload_still_loads_its_optional_readers_when_needed(self):
        import app as runtime
        from PIL import Image

        pixel_graph = {"id": "G1", "vertices": [{"id": "A", "x": .2, "y": .5},
                                                {"id": "B", "x": .8, "y": .5}],
                       "edges": [["A", "B"]], "uncertain_edges": []}
        modules = {name: ModuleType(name) for name in (
            "graph_recognition", "graph_line_tracer", "graph_validation", "graph_evidence_fusion")}
        modules["graph_recognition"].recognize_graphs = Mock(return_value={
            "graphs": [pixel_graph], "status": "review_required", "regions": []})
        modules["graph_line_tracer"].attach_line_evidence = Mock(side_effect=lambda _raw, result: result)
        modules["graph_validation"].audit_graph_records = Mock(return_value=[])
        modules["graph_evidence_fusion"].compare_pixel_vision = Mock(return_value=[])
        modules["graph_evidence_fusion"].review_direction_and_multiplicity = Mock(return_value=[])
        confirmation = ModuleType("graph_confirmation")
        confirmation.confirmation_owner = lambda: "startup-test"
        confirmation.register_recognition = Mock()
        confirmation.attach_confirmation_cookie = lambda response: response
        confirmation.ConfirmationError = type("ConfirmationError", (Exception,), {})
        modules["graph_confirmation"] = confirmation
        image = io.BytesIO()
        Image.new("RGB", (32, 32), "white").save(image, format="PNG")
        image.seek(0)
        question = "图 G 的顶点 A 和 B 用一条边连接，求顶点 A 的度数"
        with patch.dict(sys.modules, modules), patch.object(runtime, "graph_nextgen_enabled", return_value=False), patch.object(
            runtime, "_check_rate_limit", return_value=True
        ), patch.object(runtime, "recognize_image", return_value={"text": question}), patch.object(
            runtime, "analyze_image_structure", return_value={"ok": True, "image_kind": "exercise",
                "corrected_text": question, "visual_text": "", "graph_data": []}
        ) as vision, patch("requests.sessions.Session.request", side_effect=AssertionError("No provider calls")):
            runtime.app.config.update(TESTING=True)
            response = runtime.app.test_client().post("/ocr", data={"image": (image, "graph.png")})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["graph_structures"], [pixel_graph])
        vision.assert_called_once()
        for module in modules.values():
            for value in vars(module).values():
                if isinstance(value, Mock):
                    value.assert_called_once()


if __name__ == "__main__":
    unittest.main()
