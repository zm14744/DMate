"""Graph labels in the detected panels must never become question text."""
from __future__ import annotations

import io
from PIL import Image, ImageDraw

from ocr_layout import separate_diagram_labels
from graph_layout_only import (TYPE_PROMPT, LAYOUT_AUDIT_PROMPT,
                               FOCUSED_TYPE_PROMPT, recognize_layout_only)


def _line(text, x1, y1, x2, y2, kind="text"):
    return {"content": text, "type": kind, "box": [x1, y1, x2, y2],
            "score": .99}


def _ocr(*items):
    return {"text": "\n".join(item["content"] for item in items),
            "front_text": "\n".join(item["content"] for item in items),
            "text_count": len(items),
            "resource_metrics": [{"stage": "text", "status": "ok"}],
            "text_evidence": {"image_size": [1000, 800],
                              "coordinate_space": "canonical_image_pixels",
                              "emitted_body": list(items)}}


def test_inside_vertex_names_and_edge_weights_are_not_question_text():
    data = _ocr(_line("求图G的最短路径", 40, 40, 340, 76),
                _line("（2）证明有关性质", 50, 720, 385, 758),
                _line("v1", 335, 280, 355, 306),
                _line("7", 440, 360, 453, 385),
                _line("e2", 540, 440, 565, 470))
    graphs = [{"bbox": [.26, .15, .78, .81]}]
    text, count, removed, available = separate_diagram_labels(data, graphs)
    assert text == "求图G的最短路径\n（2）证明有关性质"
    assert (count, removed, available) == (2, 3, True)


def test_adjacent_question_or_formula_is_not_deleted_by_partial_overlap():
    data = _ocr(_line("已知图G如下，求度数", 60, 120, 400, 155),
                _line("x+y=2", 190, 640, 460, 670, "formula"),
                _line("v4", 560, 300, 590, 326))
    graphs = [{"bbox": [.30, .10, .79, .7]}]
    text, count, removed, available = separate_diagram_labels(data, graphs)
    assert text == "已知图G如下，求度数\n$x+y=2$"
    assert (count, removed, available) == (2, 1, True)


def test_two_figures_and_unknown_panel_bounds_only_exclude_known_interiors():
    data = _ocr(_line("（1）说明", 35, 30, 200, 60),
                _line("A", 150, 360, 174, 388),
                _line("12", 720, 410, 746, 433),
                _line("图外说明", 425, 360, 505, 390))
    graphs = [{"bbox": [.08, .14, .35, .82]},
              {"bbox": [.62, .14, .91, .82]},
              {"directed": "unknown"}]
    text, count, removed, available = separate_diagram_labels(data, graphs)
    assert "A" not in text and "12" not in text
    assert text == "（1）说明\n图外说明"
    assert (count, removed, available) == (2, 2, True)


def test_missing_ocr_geometry_never_deletes_question_by_guessing_labels():
    source = {"front_text": "请判断G是否为树\nG", "text_count": 2}
    text, count, removed, available = separate_diagram_labels(
        source, [{"bbox": [.1, .1, .8, .9]}])
    assert text == source["front_text"]
    assert count == 2 and removed == 0 and not available


def test_initial_auto_graph_does_not_publish_graph_labels_in_document_body():
    # No paid API calls: one vision overview + inventory + focused type check.
    pic = Image.new("RGB", (900, 620), "white")
    draw = ImageDraw.Draw(pic)
    draw.line((150, 150, 710, 520), fill="black", width=4)
    draw.line((710, 150, 150, 520), fill="black", width=4)
    encoded = io.BytesIO()
    pic.save(encoded, "PNG")
    source = _ocr(_line("求图中所有顶点的度", 5, 12, 330, 45),
                  _line("v1", 170, 220, 200, 250),
                  _line("5", 430, 350, 450, 385))
    # OCR pixel coordinate space is the 1000x800 frame described by _ocr.
    def read_text(_raw, *, text_only=True):
        return source

    def qwen(prompt, _urls, _budget):
        if prompt == TYPE_PROMPT:
            return {"has_graph": True, "graphs": [{
                "name": "G", "bbox": [.11, .14, .81, .87],
                "directed": False, "weighted": True}]}
        if prompt == LAYOUT_AUDIT_PROMPT:
            return {"has_graph": True, "graphs": [
                {"name": "G", "bbox": [.11, .14, .81, .87]}]}
        if prompt == FOCUSED_TYPE_PROMPT:
            return {"figures": [{"image_index": 1,
                                 "directed": False, "weighted": True}]}
        raise AssertionError("Unexpected extra model call")

    result = recognize_layout_only(
        encoded.getvalue(), recognize_text=read_text, provider=qwen,
        budget=object())
    assert result["graph_structures"] and result["text"] == "求图中所有顶点的度"
    assert result["document"]["body_text"] == result["text"]
    assert result["raw_ocr_text"] == result["text"]
    assert result["text_count"] == 1
    assert result["diagnostics"]["diagram_text_items_excluded_from_question"] == 2
    assert result["graph_structures"][0]["vertices"] == []
    assert result["graph_structures"][0]["edges"] == []
