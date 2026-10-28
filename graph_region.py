"""User-defined image ROIs, shared by manual graph and text selection.

Coordinates are in the EXIF-corrected original-image frame (0..1). All
unselected pixels are painted white BEFORE Paddle OCR receives the image.
No graph interpretation or language-model call is made in this module.
"""
from __future__ import annotations

import io
import math
from PIL import Image, ImageDraw

MAX_POINTS = 64
MIN_AREA = 0.00002


class RegionError(ValueError):
    pass


def validate_polygon(points):
    if (not isinstance(points, list) or len(points) < 3 or len(points) > MAX_POINTS):
        raise RegionError("请至少选择3个角点，最多64个。")
    validated = []
    for point in points:
        if not isinstance(point, list) or len(point) != 2:
            raise RegionError("选区顶点必须提供二维坐标。")
        if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1
               for v in point):
            raise RegionError("选区坐标必须位于原图内。")
        validated.append([float(point[0]), float(point[1])])
    signed = sum(
        validated[i][0] * validated[(i + 1) % len(validated)][1] -
        validated[(i + 1) % len(validated)][0] * validated[i][1]
        for i in range(len(validated))
    )
    if abs(signed) / 2 < MIN_AREA:
        raise RegionError("选区面积过小或轮廓无效，请重新选择。")
    return validated


def crop_region(raw: bytes, polygon, *, exclusions=None, _photo=None):
    """Return a masked PNG of ONLY the user-requested text area."""
    coords = validate_polygon(polygon)
    if exclusions is not None and (not isinstance(exclusions, list) or len(exclusions) > 64):
        raise RegionError("图形选区数量无效。")
    excluded = [validate_polygon(p) for p in (exclusions or [])]
    from image_evidence import decode_document_image
    try:
        photo = _photo if _photo is not None else decode_document_image(raw, max_pixels=24_000_000).convert("RGB")
    except (ValueError, TypeError, OSError) as exc:
        raise RegionError("原图无法读取，请重新选择图片。") from exc
    try:
        width, height = photo.size
        # Pillow crop bounds are conservative: never shave boundary glyphs.
        xs = [p[0] * width for p in coords]
        ys = [p[1] * height for p in coords]
        x0 = max(0, math.floor(min(xs)) - 2)
        y0 = max(0, math.floor(min(ys)) - 2)
        x1 = min(width, math.ceil(max(xs)) + 2)
        y1 = min(height, math.ceil(max(ys)) + 2)
        if x1 - x0 < 12 or y1 - y0 < 12:
            raise RegionError("文字区域太窄，请扩大选区。")
        clipped = photo.crop((x0, y0, x1, y1))
        try:
            mask = Image.new("L", clipped.size, 0)
            outline = [(x * width - x0, y * height - y0) for x, y in coords]
            ImageDraw.Draw(mask).polygon(outline, fill=255)
            for region in excluded:
                ImageDraw.Draw(mask).polygon([(x*width-x0, y*height-y0) for x,y in region], fill=0)
            white = Image.new("RGB", clipped.size, (255, 255, 255))
            white.paste(clipped, (0, 0), mask)
            buf = io.BytesIO()
            white.save(buf, format="PNG")
            return buf.getvalue()
        finally:
            clipped.close()
    finally:
        if _photo is None:
            photo.close()


def validate_text_regions(regions):
    """Frame IDs define reading order, independently of their page positions."""
    if not isinstance(regions, list) or not regions:
        raise RegionError('请先框选文字。')
    seen = set(); result = []
    for row in regions:
        if not isinstance(row, dict) or type(row.get('id')) is not int or not 0 < row['id'] <= 9007199254740991:
            raise RegionError('文字框编号无效。')
        if row['id'] in seen:
            raise RegionError('文字框编号重复。')
        seen.add(row['id'])
        result.append({'id': row['id'], 'polygon': validate_polygon(row.get('polygon'))})
    return sorted(result, key=lambda row: row['id'])
