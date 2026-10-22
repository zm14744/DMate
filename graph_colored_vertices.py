"""Optional OpenCV evidence for saturated-red circular graph vertices.

Works on original pixels without relying on a language-model edge list.
Strictly a candidate: colored punctuation or decorative circles may exist.
"""
import cv2
import numpy as np


def red_circle_panel_counts(image_bytes):
    if not isinstance(image_bytes, (bytes, bytearray)) or len(image_bytes) > 9_000_000:
        return []
    image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return []
    h, w = image.shape[:2]
    if w < 250 or h < 170:
        return []
    scale = min(1., 1600. / max(w, h))
    if scale < 1:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    h, w = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    color = cv2.inRange(hsv, (0, 145, 80), (12, 255, 255)) | cv2.inRange(
        hsv, (170, 145, 80), (179, 255, 255)
    )
    contours, _ = cv2.findContours(color, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    points = []
    min_size = max(8., 0.024 * h)
    max_size = min(85., 0.105 * h)
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)
        if not (min_size <= bw <= max_size and min_size <= bh <= max_size):
            continue
        if not (0.74 <= bw / max(1., bh) <= 1.30
                and 0.43 <= area / (bw * bh) <= 0.86):
            continue
        if area < 50 or area > 4400:
            continue
        points.append((x + bw / 2, y + bh / 2))
    if len(points) < 6 or len(points) > 96:
        return []
    points.sort()
    groups = []
    split = max(12., 0.06 * w)
    for point in points:
        if not groups or point[0] - groups[-1][-1][0] > split:
            groups.append([point])
        else:
            groups[-1].append(point)
    if not 2 <= len(groups) <= 8 or any(not 3 <= len(group) <= 18 for group in groups):
        return []
    return [
        {
            "x_center": round(sum(x for x, _ in group) / len(group) / w, 3),
            "vertex_count": len(group),
            "points": [[round(x/w,4), round(y/h,4)] for x,y in group],
        }
        for group in groups
    ]


__all__ = ["red_circle_panel_counts"]
