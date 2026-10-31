"""Choose at most one text-only auxiliary read without changing pixel geometry.

Image quality is a recovery hint, not evidence that a recognised word is right.
The first read always uses the original. Auxiliary reads still go through the
worker's conservative line merge and uncertainty handling.
"""
import math

import cv2
import numpy as np

PREPROCESS_VERSION = 'text-quality-v1'
ANALYSIS_SIDE = 512
CONFIDENT_LINE_SCORE = .96


def _small_gray(image):
    height, width = image.shape[:2]
    scale = min(1., ANALYSIS_SIDE / max(height, width))
    small = (cv2.resize(image, (max(1, round(width * scale)), max(1, round(height * scale))),
                        interpolation=cv2.INTER_AREA) if scale < 1 else image)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), scale


def _quality(image, items):
    gray, scale = _small_gray(image)
    low, median, high = np.percentile(gray, [.5, 50, 99.5])
    bright_fraction = float(np.mean(gray > median + 55))
    dark = bool(median < 100 and high - median > 55 and .003 < bright_fraction < .45)
    paper = cv2.bitwise_not(gray) if dark else gray
    low, high = np.percentile(paper, [.5, 99.5])
    contrast = float(high - low)
    foreground_fraction = float(np.mean(paper < max(0., high - max(12., contrast * .3))))
    # Cell percentiles describe broad paper shading while ignoring thin ink.
    backgrounds = [float(np.percentile(cell, 85))
                   for strip in np.array_split(paper, min(4, paper.shape[0]))
                   for cell in np.array_split(strip, min(4, paper.shape[1]), axis=1)]
    background_range = float(np.percentile(backgrounds, 90) - np.percentile(backgrounds, 10))
    laplacian = float(cv2.Laplacian(paper, cv2.CV_32F).var())
    ink_present = .001 < foreground_fraction < .45
    # A confident title does not imply that faint text elsewhere was detected.
    # Look only for source contrast outside padded first-pass line boxes; this
    # is a reason to recover, never a reason to erase or invent body text.
    side = min(31, max(3, int(min(paper.shape) * .08) | 1))
    background = cv2.morphologyEx(paper, cv2.MORPH_CLOSE,
                                  cv2.getStructuringElement(cv2.MORPH_RECT, (side, side)))
    delta = cv2.subtract(background, paper)
    read_mask = np.zeros(paper.shape, np.uint8)
    for item in items:
        box = item.get('box')
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            coords = [float(v) * scale for v in box]
            if not all(math.isfinite(v) for v in coords):
                continue
            x0, y0, x1, y1 = coords
            cv2.rectangle(read_mask, (math.floor(x0) - 2, math.floor(y0) - 2),
                          (math.ceil(x1) + 2, math.ceil(y1) + 2), 1, -1)
        except (TypeError, ValueError, OverflowError):
            continue
    weak_outside = (delta > 12) & (delta < 90) & (read_mask == 0)
    weak_fraction = float(np.mean(weak_outside))
    # A downscaled thumbnail can make genuinely sharp small print look blurry.
    # Restrict this hint to crops inspected close to their native resolution.
    blur = bool(scale >= .75 and contrast > 100 and ink_present and 4 < laplacian < 65)
    return {
        'analysis_size': [int(gray.shape[1]), int(gray.shape[0])],
        'contrast_range': round(contrast, 3),
        'background_range': round(background_range, 3),
        'foreground_fraction': round(foreground_fraction, 6),
        'laplacian_variance': round(laplacian, 3),
        'unread_weak_fraction': round(weak_fraction, 6),
        'dark_background': dark,
        'uneven_illumination': bool(background_range > 32 and ink_present),
        'low_contrast': bool(12 < contrast < 90 and ink_present),
        'blur_warning': blur,
        'unread_weak_ink': bool(np.count_nonzero(weak_outside) >= 12 and weak_fraction > .002),
    }


def plan_text_enhancement(image, items, *, math_risk=False):
    """Make a language-neutral recovery decision from scores and source pixels."""
    quality = _quality(image, items)
    scores = []
    for item in items:
        if not str(item.get('content') or '').strip():
            continue
        try:
            value = float(item.get('score', 0))
        except (ValueError, TypeError):
            value = 0.
        scores.append(value if math.isfinite(value) and 0 <= value <= 1 else 0.)
    reasons = []
    if not scores:
        reasons.append('empty_read')
    if math_risk:
        reasons.append('math_risk')
    if scores and min(scores) < CONFIDENT_LINE_SCORE:
        reasons.append('low_confidence')
    for flag in ('dark_background', 'uneven_illumination', 'low_contrast', 'blur_warning', 'unread_weak_ink'):
        if quality[flag]:
            reasons.append(flag)
    if not reasons:
        mode = 'none'
    elif quality['dark_background']:
        mode = 'dark_background'
    elif quality['blur_warning']:
        mode = 'mild_sharpen'
    else:
        mode = 'local_contrast'
    return {
        'version': PREPROCESS_VERSION,
        'mode': mode,
        'reasons': reasons,
        'line_count': len(scores),
        'minimum_score': round(min(scores), 6) if scores else None,
        'mean_score': round(sum(scores) / len(scores), 6) if scores else None,
        'quality': quality,
    }


def _contrast(image):
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    light, green, blue = cv2.split(lab)
    light = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8)).apply(light)
    return cv2.cvtColor(cv2.merge((light, green, blue)), cv2.COLOR_LAB2BGR)


def apply_text_enhancement(image, plan):
    """Return one same-size BGR variant; never threshold, rotate, or redraw ink."""
    mode = plan['mode']
    if mode == 'local_contrast':
        return _contrast(image)
    if mode == 'dark_background':
        return _contrast(cv2.bitwise_not(image))
    if mode == 'mild_sharpen':
        smooth = cv2.GaussianBlur(image, (0, 0), .8)
        return cv2.addWeighted(image, 1.35, smooth, -.35, 0)
    raise ValueError('unsupported_text_enhancement_mode')
