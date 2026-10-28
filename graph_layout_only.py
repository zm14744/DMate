"""Automatic accurate segmentation and bounded manual figure-type recognition.

Initial upload: high-detail Qwen overview, independent focused per-figure type
verification, and OCR in parallel, with no four-second ceiling. Manually framed
figure: one bounded Qwen type-only check, within four seconds including UI.
No stage predicts or draws a node, edge, endpoint, or path.
"""
from __future__ import annotations

import base64
import inspect
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import hashlib
import io
import math
import time

import cv2
import numpy as np
from PIL import Image

from image_evidence import decode_document_image


VERSION = "2026-10-28-accuracy-first-segmentation-v3"
MANUAL_SCAN_MAX_SECONDS = 3.4
# Only manual region type checks have a four-second limit. Automatic upload
# has its own generous server-side safety deadline, unrelated to the UI.
INITIAL_SCAN_MAX_SECONDS = 265.0
SCAN_MAX_SECONDS = MANUAL_SCAN_MAX_SECONDS  # Existing public manual-scan name
_SCAN_WORKERS = ThreadPoolExecutor(max_workers=8, thread_name_prefix="dmate-initial-figures")
_MANUAL_WORKERS = ThreadPoolExecutor(max_workers=8, thread_name_prefix="dmate-manual-types")
MAX_GRAPHS = 24

TYPE_PROMPT = """你是离散数学图片的版面分图及图类型读取器，不是图形绘制器。
只完成三件事：1）判断原图有无真实数学图形；2）仔细清点每幅独立子图并标出准确的整图范围与原图图名；3）分别判断每幅图有无边上的箭头以及真正的边权。宁可慢一点，也不得漏图或乱拆。
严禁识别或输出顶点列表、边列表、端点、连接关系、绘制路径；这些全部由用户自行描绘。
普通文字、公式、下划线、表格不是数学图；没有图就返回 graphs=[]。
仔细逐行、逐列观察图形：并列图、上下图、图a/图b/图1/图2应分开；单个图内部不连通的部分不能误拆；不要把图例、公式、表格、箭头文字或放大视图重复算成独立图。
边的弯曲、交叉、并行、重边、虚线、阴影、褪色和手绘线都不妨碍判断图形是否存在；不要尝试推断拓扑。
每幅图都使用整张原图相对坐标 [left,top,right,bottom]，每个坐标0到1。
directed：边或自环上能看到任何箭头尖端为true；确认没有箭头为false；看不清/边界裁断/混合情形为"unknown"。不能凭题干的“有向图”字样推断图片里有箭头。
weighted：确实有写在边旁、用于标示边权的数字或符号为true；确认没有边权为false；顶点数字、图名、顶点标签、边名、公式、下标、坐标轴刻度不算边权；拿不准为"unknown"。
尤其认真查看密集区域的小箭头、线段端部、弧线尖端以及边旁微小权值，不要把线条交叉点误认成箭头，也不要把顶点编号误认成权值。
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


class _VisionBudget:
    """Per-call visual budget; full upload does not inherit the manual cap."""

    def __init__(self, deadline, *, manual=False):
        self.deadline = deadline
        self.connect_seconds = 0.85 if manual else 7.0
        self.call_seconds = 3.2 if manual else 60.0
        self.output_tokens = 1024 if manual else 2048
        self.metrics = []

    def take(self):
        left = min(self.call_seconds, self.deadline - time.monotonic())
        if left <= 0:
            raise TimeoutError("figure_scan_deadline")
        return left


SELECTED_TYPE_PROMPT = """图像已经由用户框选为单独一幅图。严格只识别两个事实：边上是否有箭头，边旁是否有权值。
请仔细查看细线、小箭头尖端、弧线、环和重边。只要确实存在箭头就directed=true，确定全无才写false；不确定写"unknown"。
只要确实存在作为边权标注的数字或符号就weighted=true，确定全无才写false；顶点名称、顶点编号、普通边名、图注、公式不是边权。拿不准写"unknown"。
如果裁剪切掉了可能的箭头或权值，不要把看不见当作不存在。
禁止提取任何顶点、边、连接关系、箭头方向或绘制路径。仅输出JSON：
{"has_graph":true,"graphs":[{"name":"当前子图","bbox":[0,0,1,1],"directed":false,"weighted":false}],"uncertainties":[]}
"""


FOCUSED_TYPE_PROMPT = """下面按顺序提供了1到2张从原图单独裁出的数学图形，每张对应一幅子图。
请只复核每张图自身的两项属性，不能参考题干文字猜测：
1. directed：只要边/自环末端确有箭头尖端便是true；确实没有箭头才是false。交叉点、顶点、线尾误差不是箭头。
2. weighted：只有边旁用于表示边权的数字或符号才是true；顶点名称、序号、边名、角标、图例、公式不算权值。
逐条仔细查看密集/褪色细线、曲线及小字符；裁掉的边或模糊区域不要当作不存在。拿不准任一项就写"unknown"。
禁止绘制或列举顶点、边、连接关系、方向列表。必须一张图返回一条，顺序索引image_index从1开始，不得多报。
仅输出JSON：{"figures":[{"image_index":1,"directed":false,"weighted":true}]}
"""


DISPUTE_TYPE_PROMPT = """这是单独裁出的图。前两次读取对箭头或权值有分歧，请重新从当前像素独立核对。
不要根据“有向/无向、带权/不带权”的题目文字猜测。沿每条可见边和环确认是否真的有箭头尖端，
并区分贴边的权值和顶点名称/编号/普通边名。任何被裁断、被遮挡、模糊的区域不允许断言没有箭头或权值。
不列出边、顶点或生成绘图。仅输出JSON：
{"figures":[{"image_index":1,"directed":"unknown","weighted":"unknown"}]}
"""


def _provider_or_raise(provider):
    if provider is not None:
        return provider
    from vision_provider import VisionProvider
    candidate = VisionProvider("qwen", thinking=False, retries=0)
    if not candidate.available():
        raise RuntimeError("qwen_layout_unavailable")
    return candidate


def _image_url(image, *, manual=False, focused=False):
    # Initial segmentation needs full-page detail; independently enlarged crops
    # preserve tiny arrow tips and edge weights lost in whole-page thumbnails.
    side = 1400 if manual else 1900 if focused else 2200
    working = _scaled_image(image, side=side).convert("RGB")
    try:
        if manual:
            payload = io.BytesIO()
            working.save(payload, format="JPEG", quality=93, optimize=False)
            mime = "image/jpeg"
        else:
            lossless = io.BytesIO()
            working.save(lossless, format="PNG", compress_level=2)
            if lossless.tell() <= 2_000_000:
                payload, mime = lossless, "image/png"
            else:
                payload = io.BytesIO()
                working.save(payload, format="JPEG", quality=95, optimize=False)
                mime = "image/jpeg"
        return "data:" + mime + ";base64," + base64.b64encode(payload.getvalue()).decode("ascii")
    finally:
        working.close()


def _vision_layout(image, *, provider=None, budget=None, cancelled=None,
                   request_deadline=None, selected=False):
    _check_cancelled(cancelled)
    reader = _provider_or_raise(provider)
    if budget is None:
        budget = _VisionBudget(request_deadline or time.monotonic() +
                               (MANUAL_SCAN_MAX_SECONDS if selected else INITIAL_SCAN_MAX_SECONDS),
                               manual=selected)
    image_url = _image_url(image, manual=selected)
    _check_cancelled(cancelled)
    response = reader(SELECTED_TYPE_PROMPT if selected else TYPE_PROMPT,
                      [image_url], budget)
    _check_cancelled(cancelled)
    return _project_figures(response)


def _review_entries(reading, count):
    """Reject missing/duplicate/wrong-index checks rather than guessing."""
    rows = reading.get("figures") if isinstance(reading, dict) else None
    if not isinstance(rows, list):
        raise ValueError("figure_type_review_invalid")
    indexed = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        index = row.get("image_index")
        if type(index) is not int or not 1 <= index <= count or index in indexed:
            raise ValueError("figure_type_review_index_invalid")
        indexed[index] = {key: _typed(row.get(key))
                          for key in ("directed", "weighted")}
    return [indexed.get(i) for i in range(1, count + 1)]


def _figure_crop(image, box):
    width, height = image.size
    a, b, c, d = box
    # The overview bbox already has 2% label padding. Keep additional crop
    # padding small so neighbouring independent diagrams do not contaminate
    # directed/weighted judgments.
    pad_x, pad_y = (c - a) * .035, (d - b) * .035
    region = (max(0, math.floor((a - pad_x) * width)),
              max(0, math.floor((b - pad_y) * height)),
              min(width, math.ceil((c + pad_x) * width)),
              min(height, math.ceil((d + pad_y) * height)))
    if region[2] - region[0] < 8 or region[3] - region[1] < 8:
        raise ValueError("figure_crop_too_small")
    return image.crop(region)


def _verify_figures(image, figures, *, provider=None, cancelled=None, deadline=None):
    """Independent high-resolution crop checks; all paths stay metadata-only.

    A disagreement never silently becomes a confident yes/no. Only an
    independent targeted deciding read may resolve it; otherwise retain
    "unknown" for the user to check.
    """
    if not figures:
        return [], [], 0, 0
    reader = _provider_or_raise(provider)
    deadline = deadline or time.monotonic() + INITIAL_SCAN_MAX_SECONDS
    verified = [dict(row) for row in figures]
    issues = []
    calls, certified = 0, 0
    for offset in range(0, len(verified), 2):
        _check_cancelled(cancelled)
        images, entries = [], []
        for i in range(offset, min(offset + 2, len(verified))):
            figure = verified[i]
            if "bbox" not in figure:
                figure["directed"] = figure["weighted"] = "unknown"
                issues.append(f'{figure["name"]}没有可核对的子图边界，请手动框选')
                continue
            try:
                cropped = _figure_crop(image, figure["bbox"])
                try:
                    images.append(_image_url(cropped, focused=True))
                    entries.append(i)
                finally:
                    cropped.close()
            except (ValueError, OSError):
                figure["directed"] = figure["weighted"] = "unknown"
                issues.append(f'{figure["name"]}子图过小或裁剪失败，请手动核对')
        if not images:
            continue
        _check_cancelled(cancelled)
        try:
            calls += 1
            reviewed = reader(FOCUSED_TYPE_PROMPT, images,
                              _VisionBudget(deadline))
            _check_cancelled(cancelled)
            checks = _review_entries(reviewed, len(images))
        except LayoutOnlyCancelled:
            raise
        except Exception:
            checks = [None for _ in images]
            issues.append("局部图类型复核失败，无法确保箭头和边权判断可靠")
        for position, index in enumerate(entries):
            figure = verified[index]
            review = checks[position]
            if review is None:
                figure["directed"] = figure["weighted"] = "unknown"
                issues.append(f'{figure["name"]}缺少独立类型核对结果')
                continue
            pending = []
            for flag in ("directed", "weighted"):
                original = figure[flag]
                focused = review[flag]
                if original == focused and type(original) is bool:
                    certified += 1
                else:
                    pending.append(flag)
                    figure[flag] = "unknown"
            if not pending:
                continue
            # Only disagreements/uncertainties need a third, differently
            # worded read of the same original crop. Initial upload has time.
            final_check = None
            if time.monotonic() < deadline - 2:
                try:
                    calls += 1
                    followup = reader(DISPUTE_TYPE_PROMPT, [images[position]],
                                      _VisionBudget(deadline))
                    _check_cancelled(cancelled)
                    final_check = _review_entries(followup, 1)[0]
                except LayoutOnlyCancelled:
                    raise
                except Exception:
                    pass
            for flag in pending:
                initial = figures[index][flag]
                focused = review[flag]
                final = final_check[flag] if final_check else "unknown"
                if type(final) is bool and (final == initial or final == focused):
                    figure[flag] = final
                    certified += 1
                else:
                    issues.append(f'{figure["name"]}的{"箭头" if flag == "directed" else "边权"}多次复核仍存在分歧，请对照原图核对')
    return verified, list(dict.fromkeys(issues)), calls, certified

def _await_until(jobs, deadline, cancelled=None):
    """Never wait for an OCR/native/model worker after the request deadline."""
    pending = set(jobs.values())
    while pending and time.monotonic() < deadline:
        _check_cancelled(cancelled)
        _, pending = wait(pending, timeout=min(.04, max(0., deadline - time.monotonic())),
                          return_when=FIRST_COMPLETED)
    _check_cancelled(cancelled)
    for future in pending:
        future.cancel()
    return {name: future for name, future in jobs.items() if future.done()
            and not future.cancelled()}


def _fast_text_read(reader, raw, deadline):
    """Pass the tight timeout only to readers that actually support it."""
    signature = inspect.signature(reader)
    supports_timeout = ("timeout_seconds" in signature.parameters or any(
        param.kind == inspect.Parameter.VAR_KEYWORD
        for param in signature.parameters.values()))
    kwargs = {"text_only": True}
    if supports_timeout:
        kwargs["timeout_seconds"] = max(.1, deadline - time.monotonic() - .08)
    return reader(raw, **kwargs)


def recognize_layout_only(raw, *, recognize_text=None, provider=None, budget=None,
                          cancelled=None, request_deadline=None):
    """Concurrent OCR + figure-type read; no graph pre-drawing, max 3.4 s."""
    start = time.monotonic()
    deadline = min(start + SCAN_MAX_SECONDS, request_deadline or float("inf"))
    source = hashlib.sha256(raw).hexdigest()
    _check_cancelled(cancelled)
    image = decode_document_image(raw, max_pixels=16_000_000)
    try:
        hint = visual_preflight(image)
        _check_cancelled(cancelled)
        jobs = {}
        if recognize_text is not None and time.monotonic() < deadline:
            jobs["text"] = _SCAN_WORKERS.submit(_fast_text_read, recognize_text, raw, deadline)
        if hint["possible_graph"] and time.monotonic() < deadline:
            # Copy for the worker: the request may return while an upstream
            # socket is still being torn down; it must never use closed pixels.
            model_image = image.copy()

            def vision_job():
                try:
                    return _vision_layout(model_image, provider=provider,
                                          budget=budget, cancelled=cancelled,
                                          request_deadline=deadline)
                finally:
                    model_image.close()

            jobs["vision"] = _SCAN_WORKERS.submit(vision_job)

        done = _await_until(jobs, deadline, cancelled)
        _check_cancelled(cancelled)
        text_result = {}
        text_error = None
        if recognize_text is None:
            text_error = "文字识别服务暂不可用，请手动补充"
        elif "text" not in done:
            text_error = "文字识别未在4秒内完成，可手动补充文字"
        else:
            try:
                text_result = done["text"].result()
                if not isinstance(text_result, dict):
                    raise ValueError("text_worker_invalid_response")
                metrics = text_result.get("resource_metrics") or []
                if not any(row.get("stage") == "text" and row.get("status") == "ok"
                           for row in metrics if isinstance(row, dict)):
                    text_error = "文字识别没有完成，请核对或手动补充"
            except Exception:
                text_result = {}
                text_error = "文字识别暂不可用，请手动补充"

        text = str(text_result.get("front_text") or text_result.get("text") or "").strip()
        figures, issues = [], []
        vision_failed = False
        qwen_attempted = "vision" in jobs
        if hint["possible_graph"]:
            if "vision" not in done:
                vision_failed = True
                issues.append("图形分区或类型未在4秒内确定，请手动框选并选择图类型")
            else:
                try:
                    figures, issues = done["vision"].result()
                except LayoutOnlyCancelled:
                    raise
                except Exception:
                    vision_failed = True
                    issues = ["图形分区及类型识别未完成，请手动框选，未生成任何预绘图"]
            if not figures and not vision_failed:
                issues.append("原图存在几何候选，但未确认独立数学图，请核对")
        if text_error:
            issues.append(text_error)
        if not figures and not text and not issues:
            issues.append("图片中没有识别到可用的文字或数学图")
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
            "review": {"required": status != "complete", "reasons": issues[:8]},
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
                "deadline_hit": time.monotonic() >= deadline,
                "image_accuracy_certified": False,
            }
        }
    finally:
        image.close()


def recognize_selected_graph_type(raw, *, provider=None, budget=None,
                                  cancelled=None, request_deadline=None):
    """Re-scan only a user-selected figure for arrows/weights, not topology."""
    start = time.monotonic()
    deadline = min(start + SCAN_MAX_SECONDS, request_deadline or float("inf"))
    _check_cancelled(cancelled)
    image = decode_document_image(raw, max_pixels=16_000_000)

    def work():
        try:
            return _vision_layout(image, provider=provider, budget=budget,
                                  cancelled=cancelled, request_deadline=deadline,
                                  selected=True)
        finally:
            image.close()

    future = _SCAN_WORKERS.submit(work)
    finished = _await_until({"figure": future}, deadline, cancelled)
    result = {"directed": "unknown", "weighted": "unknown",
              "recognition_status": "partial", "warning": None,
              "elapsed_seconds": round(time.monotonic() - start, 3),
              "no_auto_draw": True}
    if "figure" not in finished:
        result["warning"] = "图类型识别超出4秒，保留原图与手动选择"
        return result
    try:
        figures, issues = finished["figure"].result()
        if len(figures) == 1:
            result["directed"] = figures[0]["directed"]
            result["weighted"] = figures[0]["weighted"]
            if (type(result["directed"]) is bool and
                    type(result["weighted"]) is bool):
                result["recognition_status"] = "complete"
        else:
            issues.append("选区包含多幅图或图形未被确认，请逐幅框选")
        result["warning"] = "；".join(issues[:4]) or None
    except Exception:
        result["warning"] = "选区的箭头或权值未能确定，请手动选择"
    result["elapsed_seconds"] = round(time.monotonic() - start, 3)
    return result


__all__ = ["recognize_layout_only", "visual_preflight", "_project_figures",
           "LayoutOnlyCancelled", "VERSION", "SCAN_MAX_SECONDS",
           "recognize_selected_graph_type"]
