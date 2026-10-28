"""Regression for fast text-only OCR and figure-type recognition without drawing.

All images are synthetic. No network, paid models, OCR model loading or
claim of end-to-end image accuracy. The GitHub workflow runs these in CI.
"""
from __future__ import annotations

import io
import time

from PIL import Image, ImageDraw

from graph_layout_only import (TYPE_PROMPT, LAYOUT_AUDIT_PROMPT, FOCUSED_TYPE_PROMPT,
                               DISPUTE_TYPE_PROMPT, _project_figures,
                               recognize_layout_only, recognize_selected_graph_type,
                               visual_preflight)


def raw(image):
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def pure_text_image():
    image = Image.new("RGB", (660, 380), "white")
    draw = ImageDraw.Draw(image)
    for i in range(8):
        draw.text((25, 18 + i * 43),
                  "Example mathematical question 123: please explain the theorem.",
                  fill="black")
    return image


def diagrams_image():
    image = Image.new("RGB", (680, 400), "white")
    draw = ImageDraw.Draw(image)
    for x in (45, 370):
        nodes = [(x+45, 65), (x+240, 65), (x+140, 325)]
        draw.line((nodes[0], nodes[1]), fill="black", width=4)
        draw.line((nodes[1], nodes[2]), fill="black", width=4)
        draw.line((nodes[2], nodes[0]), fill="black", width=4)
        for a, b in nodes:
            draw.ellipse((a-8, b-8, a+8, b+8), fill="black")
    return image


def fast_text(_raw, *, text_only=False):
    assert text_only is True
    return {"text": "求图中顶点的度数", "front_text": "求图中顶点的度数",
            "text_count": 1, "resource_metrics": [
                {"stage": "layout", "status": "skipped"},
                {"stage": "text", "status": "ok"}]}


def test_no_graph_has_only_one_fast_text_worker_and_zero_vision_calls():
    image = pure_text_image()
    assert visual_preflight(image)["possible_graph"] is False

    def forbidden_vision(*_args):
        raise AssertionError("Text-only images must never use Qwen")

    result = recognize_layout_only(raw(image), recognize_text=fast_text,
                                   provider=forbidden_vision)
    assert result["recognition_status"] == "complete", result
    assert result["graph_structures"] == []
    assert result["document"]["graphs"] == []
    assert result["text"] == "求图中顶点的度数"
    assert result["diagnostics"]["route"] == "text_only"
    assert result["diagnostics"]["layout_model_calls"] == 0
    assert result["diagnostics"]["qwen_graph_calls"] == 0


def test_figures_have_individual_types_and_original_bounds_with_zero_drawing():
    picture = diagrams_image()
    assert visual_preflight(picture)["possible_graph"] is True
    submitted = []

    def qwen(prompt, images, budget):
        submitted.append((prompt, images, budget))
        if prompt == LAYOUT_AUDIT_PROMPT:
            return {"has_graph": True, "graphs": [
                {"name": "G", "bbox": [.05, .13, .47, .94]},
                {"name": "H", "bbox": [.53, .13, .96, .94]}]}
        if prompt == FOCUSED_TYPE_PROMPT:
            assert len(images) == 2
            return {"figures": [
                {"image_index": 1, "directed": False, "weighted": False},
                {"image_index": 2, "directed": True, "weighted": True}]}
        assert prompt == TYPE_PROMPT
        return {"has_graph": True, "graphs": [
            {"name": "G", "bbox": [.05, .13, .47, .94],
             "directed": False, "weighted": False,
             "vertices": [{"id": "guessed-node"}],
             "edges": [{"from": "guessed-node", "to": "other"}],
             "path": [[0, 0], [1, 1]]},
            {"name": "H", "bbox": [.53, .13, .96, .94],
             "directed": True, "weighted": True,
             "edges": [{"direction": "forward", "weight": 4}]}],
            "uncertainties": []}

    result = recognize_layout_only(raw(picture), recognize_text=fast_text,
                                   provider=qwen, budget=object())
    assert len(submitted) == 3
    assert "严禁识别或输出顶点列表" in submitted[0][0]
    assert submitted[0][1][0].startswith("data:image/png;base64,")
    assert submitted[1][0] == LAYOUT_AUDIT_PROMPT
    assert all(url.startswith("data:image/png;base64,") for url in submitted[2][1])
    assert result["diagnostics"]["layout_audit_calls"] == 1
    assert result["diagnostics"]["type_review_calls"] == 1
    assert result["diagnostics"]["independently_verified_type_fields"] == 4
    assert result["workflow_profile"] == "layout_only"
    assert result["recognition_status"] == "partial"
    assert result["diagnostics"]["route"] == "figure_type_only"
    assert result["diagnostics"]["layout_model_calls"] == 0
    assert len(result["document"]["graphs"]) == 2
    a, b = result["document"]["graphs"]
    assert (a["directed"], a["weighted"]) == (False, False)
    assert (b["directed"], b["weighted"]) == (True, True)
    assert a["bbox"][0] <= .05 and b["bbox"][2] >= .96
    assert all(g["vertices"] == [] and g["edges"] == [] for g in [a, b])
    assert all("path" not in g for g in [a, b])


def test_unknown_metadata_stays_unknown_and_no_bbox_is_invented():
    figs, issues = _project_figures({"has_graph": True, "graphs": [
        {"name": "不清楚", "directed": "unknown", "weighted": None,
         "vertices": [{"id": "bogus"}], "edges": [1]}]})
    assert figs == [{"id": "G1", "name": "不清楚", "directed": "unknown",
                     "weighted": "unknown", "vertices": [], "edges": []}]
    assert len(issues) >= 3
    assert not figs[0].get("bbox")


def test_graph_candidate_and_no_graph_disagreement_is_not_marked_complete():
    result = recognize_layout_only(raw(diagrams_image()), recognize_text=fast_text,
                                   provider=lambda *a: {"has_graph": False, "graphs": []},
                                   budget=object())
    assert result["recognition_status"] == "partial"
    assert result["graph_structures"] == []
    assert result["review"]["required"]


def test_qwen_failure_never_falls_back_to_fake_automatically_drawn_edges():
    def broken(*args):
        raise RuntimeError("synthetic model unavailable")
    result = recognize_layout_only(raw(diagrams_image()), recognize_text=fast_text,
                                   provider=broken, budget=object())
    assert result["recognition_status"] == "failed"
    assert result["graph_structures"] == []
    assert result["text"]
    assert result["review"]["required"]


def test_text_reader_can_be_unavailable_without_claiming_success():
    result = recognize_layout_only(raw(pure_text_image()), recognize_text=None,
                                   provider=lambda *args: {})
    assert result["recognition_status"] == "failed"
    assert result["diagnostics"]["qwen_graph_calls"] == 0


def test_ocr_runtime_text_only_skips_layout_process(monkeypatch):
    import ocr_runtime
    stages = []

    def worker(stage, image_path, output_path, *, layout_path=None, timeout=0, command=None):
        stages.append(stage)
        if stage == "layout":
            raise AssertionError("text_only must not initialize PP-DocLayoutV3")
        assert stage == "text" and layout_path
        import json
        from pathlib import Path
        info = json.loads(Path(layout_path).read_text())
        assert info["regions"] == [] and info["status"] == "not_run"
        return {"text": "整数论", "front_text": "整数论",
                "text_count": 1, "formula_count": 0,
                "text_evidence": {"body": [], "regions": []}}, {"stage":"text", "status":"ok"}

    monkeypatch.setattr(ocr_runtime, "run_worker", worker)
    result = ocr_runtime.recognize_image(raw(pure_text_image()), text_only=True)
    assert stages == ["text"]
    assert result["text_only_fast_path"] is True
    assert result["layout"]["status"] == "not_run"
    assert result["resource_metrics"][0]["status"] == "skipped"


def test_auto_graph_route_and_frontend_are_layout_only():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    server = (root / "app.py").read_text()
    client = (root / "static/script.js").read_text()
    graph_editor = (root / "static/graph-editor.js").read_text()
    assert 'request.form.get("workflow") == "auto_graph"' in server
    assert "recognize_layout_only(" in server
    assert 'formData.append("workflow", "auto_graph")' in client
    assert 'data?.workflow_profile === "layout_only"' in client
    assert "vertices: [], edges: []" in client
    assert 'if (useOverlay)' in graph_editor
    assert "dge-detected-type" in graph_editor
    assert all(s not in TYPE_PROMPT for s in ("枚举顶点", "追踪全部边", "按连通图补充"))


def test_public_university_graphs_are_not_silently_downgraded_to_text_only():
    """Real archived university diagrams should take the Qwen type-only route."""
    from pathlib import Path
    originals = Path(__file__).resolve().parent / "fixtures" / "original_ouc_20261021"
    for filename in ("180506.png", "181309.png"):
        source = originals / filename
        assert source.is_file(), filename
        with Image.open(source) as picture:
            result = visual_preflight(picture.convert("RGB"))
        assert result["possible_graph"], (filename, result)


def test_failed_qwen_is_counted_as_attempted_and_not_fabricated():
    def unavailable(*_args):
        raise RuntimeError("synthetic_Qwen_failure")
    result = recognize_layout_only(raw(diagrams_image()), recognize_text=fast_text,
                                   provider=unavailable, budget=object())
    assert result["recognition_status"] == "failed"
    assert result["diagnostics"]["qwen_graph_calls"] == 1
    assert result["graph_structures"] == []



def test_selected_graph_scans_only_arrows_and_weights_without_any_edges():
    calls = []
    def fake_qwen(prompt, images, budget):
        calls.append((prompt, images))
        return {"has_graph": True, "graphs": [{
            "name": "test", "bbox": [0, 0, 1, 1],
            "directed": True, "weighted": False,
            "vertices": [{"id": "do-not-copy"}],
            "edges": [{"from": "X", "to": "Y"}]}], "uncertainties": []}
    result = recognize_selected_graph_type(
        raw(diagrams_image()), provider=fake_qwen, budget=object())
    assert result["directed"] is True and result["weighted"] is False
    assert result["recognition_status"] == "complete"
    assert result["no_auto_draw"] is True
    assert "图像已经由用户框选" in calls[0][0]
    assert len(calls) == 1


def test_selected_type_scan_obeys_short_deadline_and_does_not_guess():
    def slow_qwen(*args):
        time.sleep(.35)
        return {"has_graph": True, "graphs": [{
            "directed": True, "weighted": True, "bbox": [0, 0, 1, 1]}]}
    started = time.monotonic()
    result = recognize_selected_graph_type(
        raw(diagrams_image()), provider=slow_qwen, budget=object(),
        request_deadline=time.monotonic() + .12)
    assert time.monotonic() - started < .3
    assert result["directed"] == "unknown"
    assert result["weighted"] == "unknown"
    assert result["recognition_status"] == "partial"


def test_only_manually_selected_figures_have_four_second_budget():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    client = (root / "static/script.js").read_text()
    server = (root / "app.py").read_text()
    overlay = (root / "static/graph-editor-overlay.js").read_text()
    assert "MANUAL_FIGURE_SCAN_MAX_MS = 4000" in client
    assert "OCR_SCAN_MAX_MS" not in client
    initial_handler = client.split("async function recognizeOcrTask(task) {", 1)[1].split(
        "function discardOcrTask", 1)[0]
    assert "setTimeout(" not in initial_handler
    assert "clearTimeout(timer)" not in initial_handler
    assert "request_deadline=recognition_deadline" in server
    assert "started_at + 3.6" not in server
    assert "discardOcrTask(task); // Immediate UI removal" in client
    assert 'task.state === "cancelled") return "已取消"' not in client
    assert "/graph/figure-type" in server and "/graph/figure-type" in client
    assert "scanFigureType(points,id)" in overlay
    assert "void scanFigureType(points,id)" in overlay
    assert "commitRegion([[box[0],box[1]]" in overlay
    assert 'options["timeout_seconds"] = 45.0' in server



def test_overview_and_crop_disagreement_requires_targeted_recheck():
    calls = []
    def qwen(prompt, images, budget):
        calls.append(prompt)
        if prompt == TYPE_PROMPT:
            return {"has_graph": True, "graphs": [{
                "name": "A", "bbox": [.05, .1, .94, .91],
                "directed": False, "weighted": True}], "uncertainties": []}
        if prompt == LAYOUT_AUDIT_PROMPT:
            return {"has_graph": True, "graphs": [
                {"name": "A", "bbox": [.05, .1, .94, .91]}]}
        if prompt == FOCUSED_TYPE_PROMPT:
            return {"figures": [{"image_index": 1,
                                 "directed": True, "weighted": False}]}
        assert prompt == DISPUTE_TYPE_PROMPT
        return {"figures": [{"image_index": 1,
                             "directed": True, "weighted": False}]}
    result = recognize_layout_only(raw(diagrams_image()), recognize_text=fast_text,
                                   provider=qwen, budget=object())
    graph = result["graph_structures"][0]
    assert (graph["directed"], graph["weighted"]) == (True, False)
    assert graph["vertices"] == graph["edges"] == []
    assert calls == [TYPE_PROMPT, LAYOUT_AUDIT_PROMPT, FOCUSED_TYPE_PROMPT, DISPUTE_TYPE_PROMPT]
    assert result["diagnostics"]["qwen_graph_calls"] == 4


def test_unresolved_arrows_and_edge_weights_are_not_confidently_guessed():
    def qwen(prompt, images, budget):
        if prompt == TYPE_PROMPT:
            return {"has_graph": True, "graphs": [{
                "name": "A", "bbox": [.05, .1, .94, .91],
                "directed": False, "weighted": False}], "uncertainties": []}
        if prompt == LAYOUT_AUDIT_PROMPT:
            return {"has_graph": True, "graphs": [
                {"name": "A", "bbox": [.05, .1, .94, .91]}]}
        if prompt == FOCUSED_TYPE_PROMPT:
            return {"figures": [{"image_index": 1,
                                 "directed": True, "weighted": True}]}
        return {"figures": [{"image_index": 1,
                             "directed": "unknown", "weighted": "unknown"}]}
    result = recognize_layout_only(raw(diagrams_image()), recognize_text=fast_text,
                                   provider=qwen, budget=object())
    fig = result["graph_structures"][0]
    assert fig["directed"] == fig["weighted"] == "unknown"
    assert all(not fig[field] for field in ("vertices", "edges"))
    assert "多次复核仍存在分歧" in result["warning"]


def test_focused_failure_preserves_regions_but_never_confident_types():
    def qwen(prompt, images, budget):
        if prompt == TYPE_PROMPT:
            return {"has_graph": True, "graphs": [
                {"name": "A", "bbox": [.02, .1, .9, .9],
                 "directed": True, "weighted": True}], "uncertainties": []}
        if prompt == LAYOUT_AUDIT_PROMPT:
            return {"has_graph": True, "graphs": [
                {"name": "A", "bbox": [.02, .1, .9, .9]}]}
        raise RuntimeError("vision unavailable")
    result = recognize_layout_only(raw(diagrams_image()), recognize_text=fast_text,
                                   provider=qwen, budget=object())
    assert len(result["graph_structures"]) == 1
    fig = result["graph_structures"][0]
    assert fig["bbox"] and fig["directed"] == "unknown" and fig["weighted"] == "unknown"
    assert result["recognition_status"] == "partial"
    assert result["diagnostics"]["type_review_calls"] == 1


def test_initial_slow_vision_is_not_cut_off_by_manual_four_second_timer():
    # No actual 4-second sleep in CI. A normal initial-upload budget must
    # admit the independent inventory and focused review without manual cap.
    from graph_layout_only import INITIAL_SCAN_MAX_SECONDS, MANUAL_SCAN_MAX_SECONDS
    assert INITIAL_SCAN_MAX_SECONDS >= 60
    assert MANUAL_SCAN_MAX_SECONDS < 4
    def qwen(prompt, images, budget):
        time.sleep(.07)
        if prompt == TYPE_PROMPT:
            return {"has_graph": True, "graphs": [{
                "name": "A", "bbox": [.03, .1, .91, .9],
                "directed": False, "weighted": False}]}
        if prompt == LAYOUT_AUDIT_PROMPT:
            return {"has_graph": True, "graphs": [
                {"name": "A", "bbox": [.03, .1, .91, .9]}]}
        return {"figures": [{"image_index": 1,
                             "directed": False, "weighted": False}]}
    start = time.monotonic()
    result = recognize_layout_only(raw(diagrams_image()), recognize_text=fast_text,
                                   provider=qwen, budget=object(),
                                   request_deadline=time.monotonic() + 30.0)
    assert time.monotonic() - start >= .19
    assert result["graph_structures"][0]["directed"] is False
    assert result["diagnostics"]["qwen_graph_calls"] == 3



def test_independent_inventory_recovers_missing_distinct_diagram_without_drawing():
    def qwen(prompt, images, budget):
        if prompt == TYPE_PROMPT:
            return {"has_graph": True, "graphs": [
                {"name": "G", "bbox": [.05, .13, .44, .90],
                 "directed": False, "weighted": False}]}
        if prompt == LAYOUT_AUDIT_PROMPT:
            return {"has_graph": True, "graphs": [
                {"name": "G", "bbox": [.05, .13, .44, .90]},
                {"name": "H", "bbox": [.52, .13, .94, .90]}]}
        if prompt == FOCUSED_TYPE_PROMPT:
            return {"figures": [
                {"image_index": 1, "directed": False, "weighted": False},
                {"image_index": 2, "directed": True, "weighted": True}]}
        return {"figures": [{"image_index": 1,
                             "directed": True, "weighted": True}]}
    result = recognize_layout_only(raw(diagrams_image()), recognize_text=fast_text,
                                   provider=qwen, budget=object())
    graphs = result["graph_structures"]
    assert len(graphs) == 2, graphs
    assert graphs[0]["name"] == "G"
    assert graphs[1]["name"] == "H"
    assert (graphs[1]["directed"], graphs[1]["weighted"]) == (True, True)
    assert all(g["vertices"] == [] and g["edges"] == [] for g in graphs)
    assert "补充" in result["warning"]
    assert result["diagnostics"]["layout_audit_calls"] == 1


def test_inventory_disagreement_never_deletes_first_pass_diagram():
    from graph_layout_only import _audit_inventory
    with diagrams_image() as photo:
        primary = [
            {"id": "G1", "name": "G", "bbox": [.05, .12, .44, .9],
             "directed": False, "weighted": True, "vertices": [], "edges": []},
            {"id": "G2", "name": "H", "bbox": [.52, .12, .94, .9],
             "directed": True, "weighted": False, "vertices": [], "edges": []}]
        kept, issues, calls = _audit_inventory(photo, primary, provider=lambda *a: {
            "has_graph": True, "graphs": [{"name": "G", "bbox": [.05, .12, .44, .9]}]})
    assert len(kept) == 2 and kept[1]["name"] == "H"
    assert any("分图数量" in issue for issue in issues)
    assert calls == 1


def test_graph_only_flow_never_starts_text_reader():
    calls=[]
    def text_reader(*args,**kwargs):
        calls.append(True)
        raise AssertionError('Graph-only workflow cannot start OCR')
    result=recognize_layout_only(raw(pure_text_image()),recognize_text=text_reader,include_text=False)
    assert calls==[]
    assert result['text']==''
    assert result['diagnostics']['text_worker_metrics']==[]
    assert result['diagnostics']['text_recognition_enabled'] is False
    assert not any('文字识别' in str(r) for r in result['review']['reasons'])
