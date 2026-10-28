"""Fast image routing: pure text or diagram regions/types, never graph pre-drawing.

Only the original pixels are used to decide if a visual diagram might exist.
A single Qwen3-VL-Plus read identifies diagram count, bounds, direction and
weight per independent figure. Its output is deliberately projected down to
empty vertices/edges: *no* AI-produced node, edge or pen path is displayed.
Text-only images skip the diagram model and PP-DocLayoutV3 entirely.
"""
from __future__ import annotations

import base64
import hashlib
import io
import math
import time

import cv2
import numpy as np
from PIL import Image

from image_evidence import decode_document_image


VERSION = "2026-10-28-figure-metadata-only-v1"
MAX_GRAPHS = 24

TYPE_PROMPT = """你是离散数学图片的版面分图及图类型读取器，不是图形绘制器。
只完成三件事：1）判断原图有无真实数学图形；2）按完整原图找出每幅独立子图的范围与原有图名；3）独立确定每幅图有无箭头、有无印刷的边权。
严禁识别或输出顶点列表、边列表、端点、连接关系、绘制路径；这些全部由用户自行描绘。
普通文字、公式、下划线、表格不是数学图；没有图就返回 graphs=[]。
同一图即使不连通也不拆成多图；原图的放大视图也不能重复计数。
每幅图都使用整张原图相对坐标 [left,top,right,bottom]，每个坐标0到1。
directed：确定有向为true，确定无向为false，看不清为"unknown"。
weighted：确有边权为true，确定无边权为false；顶点数字、图名、边名、公式不算边权；不能确定为"unknown"。
如果有不清楚的箭头、边权或分图边界，不得猜测。保留对应子图并说明 uncertainties。
返回一个JSON对象，不解释，不输出Markdown：
{"has_graph":true,"graphs":[{"name":"原有图注或图1","bbox":[0.1,0.2,0.4,0.8],"directed":false,"weighted":false}],"uncertainties":[]}
无图时：{"has_graph":false,"graphs":[],"uncertainties":[]}
"""


class LayoutOnlyCancelled(RuntimeError):
    """User cancelled the source-bound upload."""


def _check_cancelled(cancelled):
    if cancelled is not None and cancelled():
        raise LayoutOnlyCancelled("upload_cancelled")


def _scaled_image(image: Image.Image, side=1100):
    factor = min(1.0, side / max(image.size))
    if factor == 1:
        return image.copy()
    size = tuple(max(1, round(n * factor)) for n in image.size)
    return image.resize(size, Image.Resampling.LANCZOS)


def visual_preflight(image: Image.Image):
    """Conservative and bounded CV diagram *presence* check, never topology.

    Paragraph glyphs rarely have persistent long strokes or three separate
    large round markers. Ambiguous evidence is escalated to Qwen instead of
    constructing a graph from CV nodes or edges. This is a route hint only.
    """
    scaled = _scaled_image(image, 960)
    rgb = np.asarray(scaled.convert("RGB"))
    height, width = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    # Ignore uniform dark/light paper background; edges come from gradients.
    contour = cv2.Canny(gray, 65, 160)
    long_threshold = max(27, int(min(height, width) * .095))
    found = cv2.HoughLinesP(contour, 1, np.pi / 180, threshold=21,
                            minLineLength=long_threshold, maxLineGap=4)
    segments = [] if found is None else found.reshape(-1, 4).tolist()
    # Text rules can be long horizontal lines: one line is not a graph.
    long_strokes = sum(1 for x1, y1, x2, y2 in segments
                       if math.hypot(x2 - x1, y2 - y1) >= long_threshold)
    # Real paragraphs form surprisingly long Hough "strokes" along repeated
    # glyph baselines. Require non-horizontal geometric paths unless distinct
    # round vertex markers are visible; all-horizontal text must remain fast.
    non_horizontal = sum(1 for x1, y1, x2, y2 in segments
                         if abs(y2 - y1) >= .17 * max(1, math.hypot(x2 - x1, y2 - y1)))
    colored = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    saturated = cv2.inRange(colored, (0, 105, 90), (179, 255, 255))
    count, _, stats, _ = cv2.connectedComponentsWithStats(saturated, 8)
    round_marks = 0
    for _, _, w, h, area in stats[1:]:
        if (7 <= w <= width * .12 and 7 <= h <= height * .12
                and .62 <= w / max(h, 1) <= 1.55
                and area >= 24 and area / (w * h) >= .53):
            round_marks += 1
    # Isolated large filled BLACK disks are common graph vertices. Tiny text
    # glyphs are deliberately excluded by the proportional diameter limit.
    dark_ink = (gray <= 105).astype(np.uint8)
    _, _, dark_stats, _ = cv2.connectedComponentsWithStats(dark_ink, 8)
    disk_threshold = max(10, int(min(height, width) * .028))
    dark_disks = sum(1 for _, _, w, h, area in dark_stats[1:]
                     if (disk_threshold <= w <= width * .1
                         and disk_threshold <= h <= height * .1
                         and .7 <= w / max(h, 1) <= 1.4
                         and area / max(1, w * h) >= .62))
    # Multiple distinct loops or isolated hollow markers also suggest a
    # diagram with few straight lines. This does NOT infer their connectivity.
    circles = 0
    if non_horizontal < 2 and round_marks < 3 and dark_disks < 2:
        search = cv2.HoughCircles(cv2.medianBlur(gray, 5),
                                 cv2.HOUGH_GRADIENT, dp=1.5, minDist=16,
                                 param1=90, param2=24,
                                 minRadius=max(5, int(min(height, width) * .012)),
                                 maxRadius=max(8, int(min(height, width) * .09)))
        circles = 0 if search is None else min(len(search[0]), 24)
    possible = (non_horizontal >= 2 or round_marks >= 3 or dark_disks >= 2
                or circles >= 3)
    return {"possible_graph": bool(possible),
            "long_stroke_count": min(long_strokes, 100),
            "non_horizontal_stroke_count": min(non_horizontal, 100),
            "colored_round_mark_count": min(round_marks, 100),
            "dark_disk_count": min(dark_disks, 100),
            "hollow_circle_count": circles,
            "is_graph_certificate": False}


def _bbox(value):
    if (not isinstance(value, list) or len(value) != 4
            or not all(type(n) in (int, float) and math.isfinite(n) for n in value)):
        return None
    a, b, c, d = map(float, value)
    if not (0 <= a < c <= 1 and 0 <= b < d <= 1):
        return None
    # Keep original frame coordinates and add modest padding so small labels
    # and arrowheads are not cut off. This does NOT draw or trace the region.
    pad_x, pad_y = (c - a) * .02, (d - b) * .02
    return [round(max(0, a - pad_x), 6), round(max(0, b - pad_y), 6),
            round(min(1, c + pad_x), 6), round(min(1, d + pad_y), 6)]


def _typed(value):
    return value if type(value) is bool else "unknown"


def _project_figures(reading):
    """Discard even malicious/hallucinated node/edge fields from the model."""
    if not isinstance(reading, dict) or not isinstance(reading.get("graphs"), list):
        raise ValueError("figure_metadata_missing")
    if len(reading["graphs"]) > MAX_GRAPHS:
        raise ValueError("figure_capacity_exceeded")
    if reading.get("has_graph") is False and reading["graphs"]:
        raise ValueError("figure_presence_conflict")
    figures = []
    questions = []
    for i, row in enumerate(reading["graphs"], 1):
        if not isinstance(row, dict):
            raise ValueError("invalid_figure_record")
        name = row.get("name")
        name = name.strip()[:80] if isinstance(name, str) and name.strip() else f"图 {i}"
        bounds = _bbox(row.get("bbox"))
        fig = {"id": f"G{i}", "name": name,
               "directed": _typed(row.get("directed")),
               "weighted": _typed(row.get("weighted")),
               "vertices": [], "edges": []}
        if bounds is not None:
            fig["bbox"] = bounds
        else:
            questions.append(f"{name}的分图边界未能确定，请对照原图框选")
        for field, title in (("directed", "方向"), ("weighted", "权值")):
            if fig[field] == "unknown":
                questions.append(f"{name}的{title}无法从原图确定，绘制时请核对")
        figures.append(fig)
    if len(figures) > 1 and any("bbox" not in fig for fig in figures):
        questions.append("存在多个子图但分区范围不完整，请核对分图")
    raw_issues = reading.get("uncertainties")
    if isinstance(raw_issues, list):
        questions.extend(str(x).strip()[:160] for x in raw_issues[:12] if isinstance(x, str) and x.strip())
    return figures, list(dict.fromkeys(questions))[:20]


def _vision_layout(image, *, provider=None, budget=None, cancelled=None):
    _check_cancelled(cancelled)
    if provider is None:
        from vision_provider import VisionProvider
        provider = VisionProvider("qwen", thinking=False, retries=0)
        if not provider.available():
            raise RuntimeError("qwen_layout_unavailable")
    if budget is None:
        from graph_agent_runtime import AgentBudget
        budget = AgentBudget(seconds=65, calls=1, call_seconds=55,
                             cancelled=cancelled)
        budget.output_tokens = 2048
    working = _scaled_image(image, side=1480)
    payload = io.BytesIO()
    working.save(payload, format="PNG", compress_level=3)
    url = "data:image/png;base64," + base64.b64encode(payload.getvalue()).decode("ascii")
    # One bounded Qwen3-VL-Plus call, with NO second visual agent and no
    # OpenCV/sknw topology recovery or automatic edge reconciliation.
    response = provider(TYPE_PROMPT, [url], budget)
    _check_cancelled(cancelled)
    return _project_figures(response)


def recognize_layout_only(raw, *, recognize_text=None, provider=None, budget=None,
                          cancelled=None, request_deadline=None):
    """One text worker, optional one Qwen metadata call; never pre-draw edges."""
    start = time.monotonic()
    source = hashlib.sha256(raw).hexdigest()
    _check_cancelled(cancelled)
    image = decode_document_image(raw, max_pixels=16_000_000)
    try:
        # CV only routes the request; it is never an AI graph prediction.
        hint = visual_preflight(image)
        _check_cancelled(cancelled)
        text_result = {}
        text_error = None
        if recognize_text is not None:
            try:
                # No PP-DocLayoutV3 or second picture/graph worker for OCR.
                text_result = recognize_text(raw, text_only=True)
                if not isinstance(text_result, dict):
                    raise ValueError("text_worker_invalid_response")
                metrics = text_result.get("resource_metrics") or []
                if not any(row.get("stage") == "text" and row.get("status") == "ok"
                           for row in metrics if isinstance(row, dict)):
                    text_error = "文字识别没有完成，请核对或手动补充"
            except LayoutOnlyCancelled:
                raise
            except Exception:
                text_error = "文字识别暂不可用，请手动补充"
        else:
            text_error = "文字识别服务暂不可用，请手动补充"
        _check_cancelled(cancelled)
        text = str(text_result.get("front_text") or text_result.get("text") or "").strip()
        figures = []
        issues = []
        vision_failed = False
        qwen_attempted = False
        if hint["possible_graph"]:
            if request_deadline is not None and request_deadline - time.monotonic() < 8:
                vision_failed = True
                issues.append("图形类型识别超时，未生成任何预绘图")
            else:
                try:
                    qwen_attempted = True
                    figures, issues = _vision_layout(image, provider=provider,
                                                       budget=budget, cancelled=cancelled)
                except LayoutOnlyCancelled:
                    raise
                except Exception:
                    vision_failed = True
                    issues = ["图形分区及类型识别未完成，未生成任何预绘图"]
            if not figures and not vision_failed:
                issues.append("原图存在几何候选，但视觉模型未确认独立数学图，建议核对")
        if text_error:
            issues.append(text_error)
        if not figures and not text and not issues:
            issues.append("图片中没有识别到可用的文字或数学图")
        # An unreadable diagram cannot masquerade as a successful text-only
        # result just because the adjacent exercise header was OCR'd.
        status = ("failed" if vision_failed or not text and not figures
                  else "partial" if figures or issues else "complete")
        return {
            "workflow_profile": "layout_only",
            "text": text,
            "raw_ocr_text": text,
            "text_count": int(text_result.get("text_count") or 0),
            "formula_count": 0,
            "graph_structures": figures,
            "graph_display_data": [],
            "document": {"body_text": text, "graphs": figures},
            "recognition_status": status,
            "review": {"required": status != "complete",
                       "reasons": issues[:8]},
            "warning": "；".join(issues[:5]) if issues else None,
            "diagnostics": {
                "workflow_profile": VERSION,
                "source_sha256": source,
                "route": "figure_type_only" if hint["possible_graph"] else "text_only",
                "preflight": hint,
                "no_auto_draw": True,
                "figure_count": len(figures),
                "qwen_graph_calls": int(qwen_attempted),
                "layout_model_calls": 0,
                "text_worker_metrics": text_result.get("resource_metrics", []),
                "duration_seconds": round(time.monotonic() - start, 3),
                "image_accuracy_certified": False,
            }
        }
    finally:
        image.close()


__all__ = ["recognize_layout_only", "visual_preflight", "_project_figures",
           "LayoutOnlyCancelled", "VERSION"]
