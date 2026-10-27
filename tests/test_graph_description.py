"""The appearance service cannot silently overwrite the confirmed math graph."""
import copy
import hashlib
import json

import pytest

from graph_confirmation import COOKIE_NAME, register_recognition
from test_ocr_application_contract import application


@pytest.fixture(autouse=True)
def isolated_description_registry(monkeypatch, tmp_path):
    monkeypatch.setenv("DMATE_GRAPH_CONFIRMATION_DB", str(tmp_path / "graph-describe.sqlite3"))


def drawing():
    return {"body_text": "判断图的性质。", "graphs": [{
        "id": "G1", "name": "G1", "bbox": [.1, .1, .9, .9],
        "vertices": [{"id": "a", "label": "A", "x": .2, "y": .25},
                     {"id": "b", "label": None, "display_label": "①", "x": .8, "y": .75}],
        "edges": [{"id": "e1", "from": "a", "to": "b", "direction": "undirected",
                   "path": [[.2, .25], [.5, .45], [.8, .75]]}]
    }]}


def test_only_location_based_descriptions_and_no_question_answer():
    from graph_description import describe_confirmed_drawing, layout_summary
    payload = layout_summary(drawing())
    assert payload["graphs"][0]["placed_vertices"][0]["at"] == [.2, .25]
    assert "body_text" not in json.dumps(payload)
    seen = []
    def completion(messages, **kwargs):
        seen.append((messages, kwargs))
        return {"ok": True, "content": json.dumps({"graphs": [
            {"id": "G1", "description": "两个顶点位于斜对角位置，连线在中间略有弯折"},
            {"id": "G2", "description": "不应生成不存在的图"},
        ]}, ensure_ascii=False)}
    result = describe_confirmed_drawing(drawing(), completion=completion)
    assert result["status"] == "ok"
    assert list(result["descriptions"]) == ["G1"]
    assert len(seen) == 1 and seen[0][1]["retries"] == 0
    assert seen[0][1]["reasoning_effort"] == "none"
    assert "判断图的性质" not in seen[0][0][1]["content"]


def test_description_refuses_mathematical_answers_and_unlocated_figures():
    from graph_description import describe_confirmed_drawing
    unlocated = drawing()
    for node in unlocated["graphs"][0]["vertices"]:
        node.pop("x")
        node.pop("y")
    assert describe_confirmed_drawing(unlocated, completion=lambda *a, **k:
        pytest.fail("No-layout graph must not call DeepSeek"))["status"] == "no_layout"
    result = describe_confirmed_drawing(drawing(), completion=lambda *a, **k: {
        "ok": True, "content": json.dumps({"graphs": [
            {"id": "G1", "description": "因此两幅图同构，答案为是"},
        ]}, ensure_ascii=False)})
    assert result["status"] == "unavailable" and not result["descriptions"]


def test_description_route_requires_same_confirmed_graph_and_keeps_math_unchanged(application, monkeypatch):
    module, client, _ = application
    assert client.get("/graph/session").status_code == 200
    cookie = client.get_cookie(COOKIE_NAME)
    owner = hashlib.sha256((cookie.value + ":guest").encode()).hexdigest()
    register_recognition(owner, "picture1", "a" * 64)
    confirmed = client.post("/graph/confirm", json={
        "document": drawing(), "request_id": "picture1",
        "source_sha256": "a" * 64, "confirmed": True})
    assert confirmed.status_code == 200, confirmed.get_json()
    saved = confirmed.get_json()
    assert "x" not in saved["semantic_context"]["document"]["graphs"][0]["vertices"][0]
    assert saved["drawing_document"]["graphs"][0]["vertices"][0]["x"] == .2
    calls = []
    def fake_describe(record):
        calls.append(copy.deepcopy(record))
        return {"status": "ok", "descriptions": {"G1": "两个顶点呈对角线排列"}}
    monkeypatch.setattr("graph_description.describe_confirmed_drawing", fake_describe)
    package = {"semantic_context": saved["semantic_context"],
               "drawing_document": saved["drawing_document"]}
    good = client.post("/graph/describe", json=package)
    assert good.status_code == 200, good.get_json()
    assert len(calls) == 1
    tampered = copy.deepcopy(package)
    tampered["drawing_document"]["graphs"][0]["edges"][0]["from"] = "b"
    bad = client.post("/graph/describe", json=tampered)
    assert bad.status_code == 409 and len(calls) == 1
    without_confirmation = client.post("/graph/describe", json={"drawing_document": drawing()})
    assert without_confirmation.status_code == 409 and len(calls) == 1
