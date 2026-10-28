"""Graph labels in the detected panels must never become question text."""
from __future__ import annotations

import io
from PIL import Image, ImageDraw

from ocr_layout import include_figure_captions, separate_diagram_labels
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



def test_graph_caption_below_is_included_in_figure_box_but_not_question():
    data = _ocr(_line("判断下列图是否同构", 42, 40, 340, 76),
                _line("v₁", 275, 300, 308, 327),
                _line("G₁", 335, 491, 373, 520),
                _line("（2）求各顶点的度", 45, 570, 350, 602))
    source = [{"id": "G1", "name": "图 1", "bbox": [.18,.16,.60,.60],
               "directed": False, "weighted": False, "vertices": [], "edges": []}]
    enhanced, attached = include_figure_captions(data, source)
    assert attached == 1
    assert enhanced[0]["name"] == "G₁"
    assert enhanced[0]["bbox"][3] >= .652
    assert source[0]["bbox"][3] == .60  # Never mutate incoming geometry.
    body, kept, excluded, evidence = separate_diagram_labels(data, enhanced)
    assert evidence and (kept, excluded) == (2, 2)
    assert body == "判断下列图是否同构\n（2）求各顶点的度"
    assert enhanced[0]["vertices"] == enhanced[0]["edges"] == []


def test_caption_letters_and_names_below_side_by_side_panels_stay_separate():
    data = _ocr(_line("请分别计算下图的度数", 10, 15, 425, 48),
                _line("(a)", 185, 492, 225, 516),
                _line("彼得森图", 690, 491, 774, 518),
                _line("求顶点的度数", 140, 605, 400, 637))
    panels = [{"id": "G1", "name": "图 1", "bbox": [.06,.16,.43,.60]},
              {"id": "G2", "name": "图 2", "bbox": [.55,.16,.94,.60]}]
    included, count = include_figure_captions(data, panels)
    assert count == 2
    assert [g["name"] for g in included] == ["(a)", "彼得森图"]
    assert included[0]["bbox"][2] < .5
    assert included[1]["bbox"][0] > .5
    assert included[0]["bbox"][3] >= .646
    assert included[1]["bbox"][3] >= .648
    body, kept, excluded, evidence = separate_diagram_labels(data, included)
    assert evidence and (kept, excluded) == (2, 2)
    assert body == "请分别计算下图的度数\n求顶点的度数"


def test_top_caption_belongs_to_graph_without_absorbing_question_instructions():
    data = _ocr(_line("图 3", 450, 101, 492, 127),
                _line("已知此图有四个顶点", 160, 42, 478, 72),
                _line("证明该图是二分图", 130, 600, 380, 636))
    panels = [{"id": "G1", "name": "图 1", "bbox": [.28,.17,.70,.66]}]
    included, attached = include_figure_captions(data, panels)
    assert attached == 1
    assert included[0]["bbox"][1] <= .125
    body, kept, excluded, _ = separate_diagram_labels(data, included)
    assert body == "已知此图有四个顶点\n证明该图是二分图"
    assert (kept, excluded) == (2, 1)


def test_question_line_and_far_short_text_never_expand_a_figure_frame():
    data = _ocr(_line("（2）求图G的最短路", 180, 491, 450, 528),
                _line("图", 350, 680, 373, 705),
                _line("已知图G具有如下性质", 120, 89, 520, 123))
    panels = [{"id": "G1", "name": "G", "bbox": [.18,.16,.60,.60]}]
    included, attached = include_figure_captions(data, panels)
    assert attached == 0
    assert included[0]["bbox"] == panels[0]["bbox"]
    body, kept, removed, _ = separate_diagram_labels(data, included)
    assert (kept, removed) == (3, 0)
    assert "（2）求图G的最短路" in body


def test_caption_already_inside_model_box_still_can_name_figure():
    data = _ocr(_line("G", 333, 486, 360, 515))
    # The model already captured the caption; do not pull unrelated lines in.
    figure = [{"id": "G1", "name": "图 1", "bbox": [.18,.16,.60,.70]}]
    included, attached = include_figure_captions(data, figure)
    assert attached == 1
    assert included[0]["name"] == "G"
    assert included[0]["bbox"][3] == .70


def test_figure_caption_integrates_into_initial_upload_result_without_new_ai():
    picture = Image.new("RGB", (900, 620), "white")
    ink = ImageDraw.Draw(picture)
    ink.line((200, 140, 620, 460), fill="black", width=4)
    ink.line((620, 140, 200, 460), fill="black", width=4)
    stream = io.BytesIO()
    picture.save(stream, "PNG")
    data = _ocr(_line("试求下图的度数", 40, 35, 310, 65),
                _line("v₂", 270, 220, 306, 245),
                _line("(a)", 360, 590, 396, 610),
                _line("（1）说明你的结论", 10, 708, 400, 739))
    def text_reader(_raw, *, text_only=True):
        return data
    def qwen(prompt, _images, _budget):
        if prompt == TYPE_PROMPT:
            return {"has_graph": True, "graphs": [
                {"name": "图 1", "bbox": [.20,.17,.65,.70],
                 "directed": False, "weighted": False}]}
        if prompt == LAYOUT_AUDIT_PROMPT:
            return {"has_graph": True, "graphs": [
                {"name": "图 1", "bbox": [.20,.17,.65,.70]}]}
        if prompt == FOCUSED_TYPE_PROMPT:
            return {"figures": [{"image_index": 1,
                                 "directed": False, "weighted": False}]}
        raise AssertionError("Only existing overview, inventory and focused read allowed")
    result = recognize_layout_only(stream.getvalue(), recognize_text=text_reader,
                                   provider=qwen, budget=object())
    assert result["text"] == "试求下图的度数\n（1）说明你的结论"
    assert result["document"]["body_text"] == result["text"]
    graph = result["graph_structures"][0]
    assert graph["bbox"][3] >= .764
    assert graph["name"] == "(a)"
    assert result["diagnostics"]["graph_captions_attached"] == 1
    assert result["diagnostics"]["diagram_text_items_excluded_from_question"] == 2
    assert graph["vertices"] == graph["edges"] == []
