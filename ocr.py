import io
import math
import os
import re
import threading
import time

import cv2
import numpy as np
from PIL import Image, ImageOps

# Zeabur 亚洲节点优先使用 BOS 模型源；
# 若外部环境已配置其他来源，则不覆盖。
os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "BOS")
os.environ.setdefault("FLAGS_use_mkldnn", "0")

from paddleocr import PaddleOCR
from ocr_text_engine import TEXT_DET_MODEL, TEXT_REC_MODEL, text_model_options

_formula_import_error = None
try:
    from paddleocr import FormulaRecognitionPipeline
except Exception as exc:
    # 公式模块导入失败时，仍允许普通文字 OCR 工作。
    FormulaRecognitionPipeline = None
    _formula_import_error = repr(exc)


FORMULA_MODEL = "PP-FormulaNet_plus-S"

MAX_IMAGE_SIDE = 2200
SMALL_IMAGE_SIDE = 1000
SMALL_IMAGE_TARGET_SIDE = 1400
MAX_UPSCALE = 3.0
# Only run native-resolution recovery for large images when the first pass
# suggests small/uncertain text. Four overlapping tiles is the hard CPU bound.
NATIVE_TILE_TRIGGER_SIDE = 2600
NATIVE_TILE_MAX_COUNT = 4
NATIVE_TILE_OVERLAP = 0.09
MIN_TEXT_SCORE = 0.45
FORMULA_RETRY_SECONDS = 300

_text_ocr = None
_formula_ocr = None

_formula_load_attempted = False
_formula_load_error = _formula_import_error
_formula_last_attempt = 0.0

_model_lock = threading.Lock()
_inference_lock = threading.Lock()


class OCRError(Exception):
    """OCR 对外统一使用中文错误。"""
    pass


def load_models():
    """
    加载 OCR 模型。

    普通文字模型是必需的：
    - 加载失败时直接抛出异常。

    公式模型是可降级的：
    - 导入失败时保持普通文字 OCR 可用；
    - 运行时加载失败后进入降级模式；
    - 对可能的临时网络/下载故障，5 分钟后允许再次尝试加载。
    """
    global _text_ocr
    global _formula_ocr
    global _formula_load_attempted
    global _formula_load_error
    global _formula_last_attempt

    # Isolated Small worker must never load a second layout/formula pipeline.
    if os.environ.get("DMATE_FORMULA_ENABLED", "1") == "0":
        global FormulaRecognitionPipeline
        FormulaRecognitionPipeline = None

    now = time.monotonic()

    if _text_ocr is not None and _formula_ocr is not None:
        return {
            "text_ready": True,
            "formula_ready": True,
        }

    if (
        _text_ocr is not None
        and _formula_load_attempted
        and FormulaRecognitionPipeline is None
    ):
        return {
            "text_ready": True,
            "formula_ready": False,
        }

    if (
        _text_ocr is not None
        and _formula_load_attempted
        and _formula_ocr is None
        and now - _formula_last_attempt < FORMULA_RETRY_SECONDS
    ):
        return {
            "text_ready": True,
            "formula_ready": False,
        }

    with _model_lock:
        if _text_ocr is None:
            options = text_model_options()
            print(f"正在加载 PP-OCRv6-small ({options['engine']}, CPU)...")
            _text_ocr = PaddleOCR(**options)
            print(f"PP-OCRv6-small ({options['engine']}, CPU) 加载完成")

        now = time.monotonic()
        should_try_formula = (
            _formula_ocr is None
            and FormulaRecognitionPipeline is not None
            and (
                not _formula_load_attempted
                or now - _formula_last_attempt >= FORMULA_RETRY_SECONDS
            )
        )

        if FormulaRecognitionPipeline is None:
            if not _formula_load_attempted:
                _formula_load_attempted = True
                _formula_last_attempt = now
                _formula_load_error = (
                    _formula_import_error
                    or "FormulaRecognitionPipeline 不可用"
                )
                print(
                    "PP-FormulaNet_plus-S 未能加载，"
                    f"已启用普通文字 OCR 降级：{_formula_load_error}"
                )

        elif should_try_formula:
            _formula_load_attempted = True
            _formula_last_attempt = now

            try:
                print("正在加载 PP-FormulaNet_plus-S...")
                _formula_ocr = FormulaRecognitionPipeline(
                    formula_recognition_model_name=FORMULA_MODEL,
                    formula_recognition_batch_size=1,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_layout_detection=True,
                    device="cpu",
                    enable_mkldnn=False,
                    cpu_threads=2,
                )
                _formula_load_error = None
                print("PP-FormulaNet_plus-S 加载完成")
            except Exception as exc:
                _formula_ocr = None
                _formula_load_error = repr(exc)
                print(
                    "PP-FormulaNet_plus-S 加载失败，"
                    f"已启用普通文字 OCR 降级：{repr(exc)}"
                )

    return {
        "text_ready": _text_ocr is not None,
        "formula_ready": _formula_ocr is not None,
    }


def _decode_image(image_data):
    """
    支持：
    - bytes / bytearray
    - Flask FileStorage（具有 read()）
    - numpy.ndarray
    """
    if isinstance(image_data, np.ndarray):
        image = image_data.copy()
    else:
        if hasattr(image_data, "read"):
            raw = image_data.read()
        elif isinstance(image_data, (bytes, bytearray)):
            raw = bytes(image_data)
        else:
            raise OCRError("无法读取该图片。")

        if not raw:
            raise OCRError("图片内容为空，请重新上传。")

        try:
            # 处理手机照片 EXIF 方向，再转换为 OpenCV BGR。
            pil_image = Image.open(io.BytesIO(raw))
            pil_image = ImageOps.exif_transpose(pil_image).convert("RGB")
            image = cv2.cvtColor(
                np.asarray(pil_image),
                cv2.COLOR_RGB2BGR
            )
        except Exception as exc:
            print(f"图片解码失败：{repr(exc)}")
            raise OCRError(
                "图片读取失败，请重新选择图片。"
            ) from None

    if image is None or image.size == 0:
        raise OCRError("图片读取失败，请重新选择图片。")

    return image


def _resize_if_needed(image):
    """
    小图最多放大三倍，帮助检测题干小字；大图限制最长边。
    不二值化、不锐化，保留上下标和图中的细线。放大不能恢复缺失细节。
    """
    height, width = image.shape[:2]
    longest = max(height, width)

    if SMALL_IMAGE_SIDE <= longest <= MAX_IMAGE_SIDE:
        return image

    if longest < SMALL_IMAGE_SIDE:
        scale = min(MAX_UPSCALE, SMALL_IMAGE_TARGET_SIDE / float(longest))
    else:
        scale = MAX_IMAGE_SIDE / float(longest)
    new_width = max(1, int(width * scale))
    new_height = max(1, int(height * scale))

    return cv2.resize(
        image,
        (new_width, new_height),
        interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA
    )


def _enhance_faded_photo(image):
    """仅在首轮文本证据不足时轻度提升局部对比度，不二值化损伤图线。"""
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    light, green, blue = cv2.split(lab)
    enhanced = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8)).apply(light)
    return cv2.cvtColor(cv2.merge((enhanced, green, blue)), cv2.COLOR_LAB2BGR)


def _enhance_soft_photo(image):
    """Mild unsharp mask for a failed OCR pass on blurred phone photographs.

    Never threshold or invent text; keep the original pass if OCR confidence
    does not improve.
    """
    blurred = cv2.GaussianBlur(image, (0, 0), 1.0)
    return cv2.addWeighted(image, 1.65, blurred, -.65, 0)


def _ocr_text_strength(items):
    """按可读中文和明确小问计分，过滤单纯顶点/边标签等图内噪声。"""
    lines = [str(item.get("content") or "") for item in items]
    useful = sum(min(len(re.findall(r"[\u4e00-\u9fff]", line)), 24) for line in lines)
    questions = sum(bool(re.match(r"^\s*[（(]\s*\d+\s*[）)]", line)) for line in lines)
    return useful + questions * 18


def _math_line_risk(items):
    """Detect weak mathematical labels even when most Chinese text was read well.

    A clear paragraph must not conceal an uncertain v_5/v_3 or e_6/e_8.
    """
    relevant = [
        item for item in items
        if re.search(r"(?:[vVeEＧG][₀-₉0-9]|[（(]\s*[1-9]\s*[）)]|长度|结点|顶点|回路|通路|矩阵)", str(item.get("content", "")))
    ]
    if not relevant:
        return False
    return any(float(item.get("score", 1.0)) < 0.93 for item in relevant)


def _merge_text_ocr_passes(original, variant):
    """Match OCR lines by geometry rather than replacing a full good pass.

    Require clearly stronger confidence before modifying mathematical tokens;
    an enhanced image alone is not evidence that its digits are correct.
    """
    if not original:
        return variant
    merged = [dict(item) for item in original]
    for candidate in variant:
        box = candidate.get("box")
        if not box:
            continue
        cx = (box[0] + box[2]) / 2
        cy = (box[1] + box[3]) / 2
        best_i, best_overlap = None, 0.0
        for i, old in enumerate(merged):
            old_box = old.get("box") or []
            if len(old_box) < 4:
                continue
            ox = (old_box[0] + old_box[2]) / 2
            oy = (old_box[1] + old_box[3]) / 2
            margin_y = max(10, (old_box[3]-old_box[1]) * 0.8)
            if abs(cy-oy) > margin_y or abs(cx-ox) > max(30, (old_box[2]-old_box[0])*0.65):
                continue
            overlap = _intersection_ratio(box, old_box)
            if overlap > best_overlap:
                best_i, best_overlap = i, overlap
        if best_i is None or best_overlap < 0.32:
            # Never append enhanced-only regions to a successful original pass:
            # small offsets can otherwise duplicate whole lines.
            continue
        old = merged[best_i]
        before, after = str(old.get("content", "")), str(candidate.get("content", ""))
        if before == after:
            continue
        math_change = bool(
            re.search(r"[vVeEＧG][₀-₉0-9]", before + after)
            or re.search(r"\d", before + after)
        )
        # Numeric changes are meaning-changing, and score alone cannot prove
        # that 3/5 (or 6/8) is correct. Leave them to original-vs-Vision review.
        if math_change:
            continue
        advantage = 0.12
        if float(candidate.get("score", 0)) >= float(old.get("score", 0)) + advantage:
            merged[best_i] = candidate
    return merged


def _ocr_tile_boxes(width, height):
    """Return at most four overlapping native-resolution regions for large pages.

    Whole-page downscaling protects memory, but can erase small subscripts and
    vertex/edge labels. This bounded fallback restores local detail only when
    the caller has already detected a reason to review the OCR.
    """
    width, height = int(width), int(height)
    if min(width, height) <= 0 or max(width, height) <= NATIVE_TILE_TRIGGER_SIDE:
        return []

    max_side = float(MAX_IMAGE_SIDE)
    if width > max_side * 1.15 and height > max_side * 1.15:
        columns, rows = 2, 2
    elif width >= height:
        columns = min(NATIVE_TILE_MAX_COUNT, max(2, int(math.ceil(width / (max_side * .92)))))
        rows = 1
    else:
        columns = 1
        rows = min(NATIVE_TILE_MAX_COUNT, max(2, int(math.ceil(height / (max_side * .92)))))

    def intervals(length, count):
        cell = length / float(count)
        overlap = cell * NATIVE_TILE_OVERLAP
        result = []
        for index in range(count):
            start = max(0, int(math.floor(index * cell - (overlap if index else 0))))
            end = min(length, int(math.ceil((index + 1) * cell + (overlap if index < count - 1 else 0))))
            if end > start:
                result.append((start, end))
        return result

    xs, ys = intervals(width, columns), intervals(height, rows)
    boxes = [(x1, y1, x2, y2) for y1, y2 in ys for x1, x2 in xs]
    return boxes[:NATIVE_TILE_MAX_COUNT]


def _native_tile_text_items(source_image, target_shape):
    """Recognize large-page tiles and map their boxes to the whole-page OCR scale."""
    source_height, source_width = source_image.shape[:2]
    target_height, target_width = target_shape[:2]
    output = []
    for x1, y1, x2, y2 in _ocr_tile_boxes(source_width, source_height):
        tile = source_image[y1:y2, x1:x2]
        if tile.size == 0:
            continue
        processed = _resize_if_needed(tile)
        local_items = _extract_text_items(processed)
        tile_scale_x = (x2 - x1) / float(max(1, processed.shape[1]))
        tile_scale_y = (y2 - y1) / float(max(1, processed.shape[0]))
        page_scale_x = target_width / float(max(1, source_width))
        page_scale_y = target_height / float(max(1, source_height))
        for item in local_items:
            box = item.get("box")
            if not box or len(box) != 4:
                continue
            mapped = [
                (x1 + float(box[0]) * tile_scale_x) * page_scale_x,
                (y1 + float(box[1]) * tile_scale_y) * page_scale_y,
                (x1 + float(box[2]) * tile_scale_x) * page_scale_x,
                (y1 + float(box[3]) * tile_scale_y) * page_scale_y,
            ]
            mapped[0] = max(0.0, min(float(target_width), mapped[0]))
            mapped[1] = max(0.0, min(float(target_height), mapped[1]))
            mapped[2] = max(mapped[0], min(float(target_width), mapped[2]))
            mapped[3] = max(mapped[1], min(float(target_height), mapped[3]))
            candidate = dict(item)
            candidate["box"] = mapped
            candidate["native_tile"] = True
            output.append(candidate)
    return output


def _box_iou(box_a, box_b):
    ax1, ay1, ax2, ay2 = map(float, box_a)
    bx1, by1, bx2, by2 = map(float, box_b)
    ix = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    iy = max(0.0, min(ay2, by2) - max(ay1, by1))
    intersection = ix * iy
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


def _merge_native_tile_items(original, candidates):
    """Add missed native-resolution text and conservatively reconcile duplicates.

    Unlike contrast/sharpen passes, native tiles contain real extra source
    pixels. A stronger tile read may replace a conflicting token, but a numeric
    or graph-label disagreement is surfaced as a warning for Vision/user review.
    """
    merged = [dict(item) for item in (original or [])]
    critical_conflict = False
    math_pattern = re.compile(r"(?:[vVeEＧG][₀-₉0-9]|[0-9]|[=<>≤≥∈∩∪∧∨→↔±×÷])")
    for candidate in candidates or []:
        content = re.sub(r"\s+", "", str(candidate.get("content") or ""))
        score = float(candidate.get("score", 0.0))
        box = candidate.get("box")
        if not content or not box or len(box) != 4 or score < 0.58:
            continue
        if len(content) == 1 and not re.search(r"[\u4e00-\u9fff0-9vVeE]", content):
            continue

        best_index, best_value = None, 0.0
        cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
        ch = max(1.0, box[3] - box[1])
        for index, old in enumerate(merged):
            old_box = old.get("box") or []
            if len(old_box) != 4:
                continue
            iou = _box_iou(box, old_box)
            ox, oy = (old_box[0] + old_box[2]) / 2.0, (old_box[1] + old_box[3]) / 2.0
            oh = max(1.0, old_box[3] - old_box[1])
            close = abs(cy - oy) <= max(9.0, .65 * max(ch, oh)) and abs(cx - ox) <= max(24.0, .55 * max(box[2]-box[0], old_box[2]-old_box[0]))
            value = max(iou, .30 if close else 0.0)
            if value > best_value:
                best_index, best_value = index, value

        candidate_copy = dict(candidate)
        candidate_copy["content"] = str(candidate.get("content") or "").strip()
        if best_index is None or best_value < .22:
            # Require a plausible full text token; ignore isolated dot/noise hits.
            if len(content) >= 2 or re.search(r"[\u4e00-\u9fff0-9]", content):
                merged.append(candidate_copy)
            continue

        old = merged[best_index]
        old_content = re.sub(r"\s+", "", str(old.get("content") or ""))
        old_score = float(old.get("score", 0.0))
        if content == old_content:
            if score > old_score:
                merged[best_index] = candidate_copy
            continue

        critical = bool(math_pattern.search(content + old_content))
        if critical:
            critical_conflict = True
        advantage = score - old_score
        if advantage >= (0.15 if critical else 0.10):
            merged[best_index] = candidate_copy
    return merged, critical_conflict


def _review_regions(text_items, image_width, image_height):
    """用文字坐标定位题干，供 Vision 查看放大的局部；不传识别出的字符。

    优先保留带小问编号的文字行，忽略散落的顶点/边标签。
    最多合为四个区域，坐标归一化到已经按 EXIF 转正的整张图片。
    """
    candidates = []
    for item in text_items:
        content = item.get("content", "")
        numbered = bool(re.match(r"^\s*(?:[（(]\s*\d{1,2}\s*[）)]|\d{1,2}[.．、])", content))
        chinese_count = len(re.findall(r"[\u4e00-\u9fff]", content))
        if numbered or chinese_count >= 6:
            candidates.append((numbered, item["box"]))
    numbered_boxes = [box for numbered, box in candidates if numbered]
    boxes = numbered_boxes or [box for _, box in candidates]
    boxes.sort(key=lambda box: (box[1], box[0]))
    if not boxes:
        return []

    # 多于四行时按阅读顺序分组，避免只看前四问而漏掉后面的题。
    group_size = max(1, (len(boxes) + 3) // 4)
    regions = []
    for start in range(0, len(boxes), group_size):
        group = boxes[start:start + group_size]
        x1 = min(box[0] for box in group)
        y1 = min(box[1] for box in group)
        x2 = max(box[2] for box in group)
        y2 = max(box[3] for box in group)
        padding = max(6.0, (y2 - y1) * 0.3)
        regions.append([
            max(0.0, (x1 - padding) / image_width),
            max(0.0, (y1 - padding) / image_height),
            min(1.0, (x2 + padding) / image_width),
            min(1.0, (y2 + padding) / image_height),
        ])
    return regions


def _result_json(result):
    """兼容 PaddleOCR Result 对象的 json 属性。"""
    payload = getattr(result, "json", None)

    if callable(payload):
        payload = payload()

    if not isinstance(payload, dict):
        return {}

    if isinstance(payload.get("res"), dict):
        return payload["res"]

    return payload


def _normalize_box(box):
    """统一为 [x1, y1, x2, y2]。"""
    try:
        arr = np.asarray(box, dtype=float).reshape(-1, 2)
        x1 = float(np.min(arr[:, 0]))
        y1 = float(np.min(arr[:, 1]))
        x2 = float(np.max(arr[:, 0]))
        y2 = float(np.max(arr[:, 1]))
        return [x1, y1, x2, y2]
    except Exception:
        try:
            values = np.asarray(box, dtype=float).reshape(-1)
            if len(values) >= 4:
                return [
                    float(values[0]),
                    float(values[1]),
                    float(values[2]),
                    float(values[3]),
                ]
        except Exception:
            pass

    return None


def _intersection_ratio(box_a, box_b):
    """
    计算 box_a 被 box_b 覆盖的比例，
    用于删除被公式区域覆盖的普通 OCR 结果。
    """
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b

    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)

    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)

    intersection = iw * ih
    area_a = max(1.0, (ax2 - ax1) * (ay2 - ay1))

    return intersection / area_a


def _extract_text_items(image):
    """提取 PP-OCRv6-small 的普通文字及坐标。"""
    output = _text_ocr.predict(
        image,
        text_rec_score_thresh=MIN_TEXT_SCORE,
    )

    items = []

    for result in output:
        data = _result_json(result)

        texts = data.get("rec_texts") or []
        scores = data.get("rec_scores")
        boxes = data.get("rec_boxes")

        if scores is None:
            scores = [1.0] * len(texts)
        if boxes is None:
            boxes = []

        scores = list(np.asarray(scores).reshape(-1))

        for index, text in enumerate(texts):
            text = str(text).strip()
            if not text:
                continue

            score = (
                float(scores[index])
                if index < len(scores)
                else 1.0
            )

            if score < MIN_TEXT_SCORE:
                continue

            if index >= len(boxes):
                continue

            box = _normalize_box(boxes[index])
            if box is None:
                continue

            items.append({
                "type": "text",
                "content": text,
                "box": box,
                "score": score,
            })

    return items


def _extract_formula_items(image):
    """提取 PP-FormulaNet_plus-S 的 LaTeX 公式及坐标。"""
    if _formula_ocr is None:
        return []

    output = _formula_ocr.predict(
        image,
        use_layout_detection=True,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
    )

    items = []

    for result in output:
        data = _result_json(result)

        for formula in data.get("formula_res_list") or []:
            latex = str(
                formula.get("rec_formula", "")
            ).strip()

            if not latex:
                continue

            box = _normalize_box(
                formula.get("dt_polys")
            )
            if box is None:
                continue

            items.append({
                "type": "formula",
                "content": latex,
                "box": box,
            })

    return items


def _remove_text_inside_formulas(text_items, formula_items):
    if not formula_items:
        return text_items

    formula_boxes = [
        item["box"] for item in formula_items
    ]
    kept = []

    for text_item in text_items:
        text_box = text_item["box"]

        covered = any(
            _intersection_ratio(
                text_box,
                formula_box
            ) >= 0.45
            for formula_box in formula_boxes
        )

        if not covered:
            kept.append(text_item)

    return kept


def _sort_reading_order(items):
    """
    根据识别框平均高度动态分行，
    适配不同分辨率和字号的单栏教材/试卷。
    """
    if not items:
        return []

    def center_y(item):
        box = item["box"]
        return (box[1] + box[3]) / 2.0

    def height(item):
        box = item["box"]
        return max(1.0, box[3] - box[1])

    rough = sorted(
        items,
        key=lambda item: (
            center_y(item),
            item["box"][0]
        )
    )

    avg_height = (
        sum(height(item) for item in rough)
        / len(rough)
    )
    line_threshold = max(
        8.0,
        avg_height * 0.55
    )

    lines = []

    for item in rough:
        cy = center_y(item)
        placed = False

        for line in lines:
            if (
                abs(cy - line["center_y"])
                <= line_threshold
            ):
                line["items"].append(item)
                line["center_y"] = (
                    sum(
                        center_y(x)
                        for x in line["items"]
                    )
                    / len(line["items"])
                )
                placed = True
                break

        if not placed:
            lines.append({
                "center_y": cy,
                "items": [item],
            })

    lines.sort(
        key=lambda line: line["center_y"]
    )

    ordered = []
    for line in lines:
        line["items"].sort(
            key=lambda item: item["box"][0]
        )
        ordered.extend(line["items"])

    return ordered


def _formula_to_markdown(latex, box, image_width):
    """
    较宽或复杂公式使用块公式，
    短公式使用行内公式。
    """
    width = max(
        0.0,
        box[2] - box[0]
    )

    is_complex = (
        width >= image_width * 0.45
        or "\\begin{" in latex
        or "\\\\" in latex
    )

    if is_complex:
        return f"$$\n{latex}\n$$"

    return f"${latex}$"


def _compose_markdown(items, image_width):
    if not items:
        return ""

    parts = []

    for item in _sort_reading_order(items):
        if item["type"] == "formula":
            content = _formula_to_markdown(
                item["content"],
                item["box"],
                image_width
            )
        else:
            content = item["content"]

        if content:
            parts.append(content)

    return "\n".join(parts).strip()


def _front_side_text_items(items, image):
    """Conservative photo bleed-through filter for a SECONDARY OCR text view.

    Evaluate the original (non-enhanced) grayscale pixels. Strong front-side
    printing is normally locally darker than faint reverse-side ink. Never
    mutate the normal OCR result and never process graph pixels with this mask.
    """
    if not items or image is None:
        return items
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    rows = []
    for item in items:
        if item.get("type") != "text":
            rows.append((item, None))
            continue
        try:
            x1,y1,x2,y2 = [int(round(float(v))) for v in item["box"]]
            x1=max(0,min(gray.shape[1]-1,x1))
            x2=max(0,min(gray.shape[1],x2))
            y1=max(0,min(gray.shape[0]-1,y1))
            y2=max(0,min(gray.shape[0],y2))
            patch=gray[y1:y2,x1:x2]
            if patch.size < 25:
                rows.append((item, None))
                continue
            contrast=float(np.percentile(patch,90)-np.percentile(patch,10))
            rows.append((item,contrast))
        except (TypeError,ValueError,KeyError):
            rows.append((item,None))
    strong=[c for item,c in rows if c is not None and c >= 32
            and float(item.get("score",0)) >= 0.62]
    # Do not apply when the image has no reliable readable front-side text.
    if len(strong) < 2:
        return items
    threshold=max(20.0,min(42.0,float(np.median(strong))*0.53))
    visible=[item for item,c in rows if
             c is None or c>=threshold or (
                 c>=threshold*0.72 and float(item.get("score",0)) >= 0.84)]
    # Do not silently erase an entire question from low-contrast photographs.
    return visible if len(visible)>=2 else items


def recognize_image(image_data):
    """
    OCR 主入口。

    返回：
        {
            "text": "Markdown + LaTeX",
            "text_count": 普通文字区域数量,
            "formula_count": 公式区域数量,
            "warning": 公式模块降级时的中文提示，否则为 None,
            "review_regions": 最多四个归一化题干区域，仅供服务端 Vision 使用
        }

    只负责识题，不调用 DeepSeek，也不生成答案。
    """
    # 普通文字模型失败时让异常继续抛给 app.py；
    # 公式模型失败由 load_models() 内部自动降级。
    load_models()

    source_image = _decode_image(image_data)
    image = _resize_if_needed(source_image)

    tile_conflicts = False
    try:
        with _inference_lock:
            text_items = _extract_text_items(image)
            # OCR can read the full paragraph yet confuse a tiny vertex index.
            # Assess local confidence/blur as well as global text completeness.
            strength = _ocr_text_strength(text_items)
            sample_width = min(720, image.shape[1])
            sampled = cv2.resize(
                image, (sample_width, max(1, round(image.shape[0] * sample_width / image.shape[1])))
            )
            blur_score = cv2.Laplacian(
                cv2.cvtColor(sampled, cv2.COLOR_BGR2GRAY), cv2.CV_64F
            ).var()
            has_math_indices = any(re.search(
                r"[vVeEＧG][₀-₉0-9]|长度|结点|顶点|回路|通路",
                str(item.get("content", ""))
            ) for item in text_items)
            needs_review = (
                strength < 28 or _math_line_risk(text_items)
                or (blur_score < 85 and has_math_indices)
            )
            if needs_review:
                # Exactly one additional contrast pass for useful but blurry text.
                try:
                    enhanced_items = _extract_text_items(_enhance_faded_photo(image))
                    text_items = _merge_text_ocr_passes(text_items, enhanced_items)
                except Exception as exc:
                    print(f"文字 OCR 对比度补救失败：{type(exc).__name__}")
                # Sharpen only very soft photos, bounded to one extra pass.
                if blur_score < 42 and (strength < 28 or has_math_indices):
                    try:
                        sharpened = _extract_text_items(_enhance_soft_photo(image))
                        text_items = _merge_text_ocr_passes(text_items, sharpened)
                    except Exception as exc:
                        print(f"模糊文字 OCR 补救失败：{type(exc).__name__}")

            # Recheck large originals at native resolution only when small or
            # mathematically sensitive text remains uncertain after the bounded
            # contrast/sharpen passes. Keep the standard full-page pass first.
            strength = _ocr_text_strength(text_items)
            relevant_heights = [
                max(1.0, float(item["box"][3] - item["box"][1]))
                for item in text_items
                if len(str(item.get("content") or "")) >= 2
                or re.search(r"[vVeEＧG][₀-₉0-9]|[0-9]", str(item.get("content") or ""))
            ]
            median_text_height = float(np.median(relevant_heights)) if relevant_heights else 99.0
            native_tile_needed = (
                max(source_image.shape[:2]) > NATIVE_TILE_TRIGGER_SIDE
                and (strength < 45 or _math_line_risk(text_items) or median_text_height < 13.0)
            )
            if native_tile_needed:
                try:
                    tile_items = _native_tile_text_items(source_image, image.shape)
                    text_items, tile_conflicts = _merge_native_tile_items(text_items, tile_items)
                    print(f"高分辨率 OCR 局部复核：{len(tile_items)} 个候选，关键符号冲突={tile_conflicts}")
                except Exception as exc:
                    print(f"高分辨率 OCR 局部复核失败：{type(exc).__name__}")

            formula_items = []
            formula_warning = None

            if _formula_ocr is None:
                formula_warning = (
                    "公式识别模块暂时不可用，"
                    "已使用普通文字识别，请检查数学公式。"
                )
            else:
                try:
                    formula_items = _extract_formula_items(
                        image
                    )
                except Exception as exc:
                    print(
                        "公式识别失败，"
                        f"已降级为普通文字 OCR：{repr(exc)}"
                    )
                    formula_warning = (
                        "部分数学公式未能自动识别，"
                        "请检查识别结果。"
                    )

        review_regions = _review_regions(text_items, image.shape[1], image.shape[0])
        text_items = _remove_text_inside_formulas(
            text_items,
            formula_items
        )

        all_items = text_items + formula_items

        text = _compose_markdown(
            all_items,
            image.shape[1]
        )
        # Independent OCR-only view: suppress faint back-page impressions
        # without changing the original OCR audit or graph recognition image.
        front_text = _compose_markdown(
            _front_side_text_items(text_items, image) + formula_items,
            image.shape[1]
        )

        if not text:
            raise OCRError(
                "没有识别到清晰的题目内容，"
                "请尝试重新拍摄或裁剪图片。"
            )

        warnings = []
        if formula_warning:
            warnings.append(formula_warning)
        if tile_conflicts:
            warnings.append("高分辨率局部识别与整图识别在数字或数学符号上存在差异，请核对。")

        return {
            "text": text,
            "front_text": front_text,
            "text_count": len(text_items),
            "formula_count": len(formula_items),
            "warning": "；".join(warnings) if warnings else None,
            "review_regions": review_regions,
        }

    except OCRError:
        raise

    except Exception as exc:
        print(f"OCR 识别异常：{repr(exc)}")
        raise OCRError(
            "题目识别暂时失败，请稍后重试。"
        ) from None
