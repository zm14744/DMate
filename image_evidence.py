"""Bounded image preparation; auxiliary layers are never a graph ground truth.

Keep the decoded, white-composited original for every later pixel check. Masks
come from contrasts already present in the working image, not from sharpening,
inpainting, or a model-generated restoration. Low-contrast marks are retained
separately because a single photograph cannot always distinguish faint front
ink from show-through on the reverse of the sheet.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError


from image_upload_limits import MAX_IMAGE_PIXELS
DEFAULT_WORK_SIDE = 1600


@dataclass
class DocumentEvidence:
    """RGB originals and uint8 0/255 masks in an explicit working coordinate space.

    ``original`` is full resolution. All other images and masks have
    ``work_size == (width, height)``. ``scale_xy`` maps source pixel extents to
    working extents; pixel centres obey (x + .5) * scale - .5 when resampled.
    ``ink_mask`` contains strong ink and connected weak ink. Unconnected weak
    marks remain in ``uncertain_ink``. When there are only weak marks, ink_mask
    retains them and quality['low_contrast_only'] is True; that is not a claim
    that these marks are all front-side ink.
    """

    original: Image.Image
    working: Image.Image
    normalized: Image.Image
    sharpened: Image.Image
    ink_mask: np.ndarray
    strong_ink: np.ndarray
    uncertain_ink: np.ndarray
    work_size: tuple[int, int]
    scale_xy: tuple[float, float]
    quality: dict[str, Any]
    diagnostics: list[str]


def _pixel_limit(size: tuple[int, int], max_pixels: int) -> None:
    if isinstance(max_pixels, bool) or not isinstance(max_pixels, int) or max_pixels < 1:
        raise ValueError('max_pixels must be a positive integer')
    width, height = size
    if width < 1 or height < 1 or width * height > max_pixels:
        raise ValueError(f'image exceeds the {max_pixels} pixel limit')


def _flatten_image(image: Image.Image, max_pixels: int) -> tuple[Image.Image, dict[str, Any]]:
    _pixel_limit(image.size, max_pixels)
    source_mode = image.mode
    source_size = image.size
    orientation = image.getexif().get(274, 1)
    oriented = ImageOps.exif_transpose(image)
    alpha = oriented.mode in ('RGBA', 'LA', 'P', 'PA', 'RGBa', 'La') or 'transparency' in oriented.info
    if alpha:
        rgba = oriented.convert('RGBA')
        transparency_present = rgba.getextrema()[3][0] < 255
        background = Image.new('RGBA', rgba.size, (255, 255, 255, 255))
        result = Image.alpha_composite(background, rgba).convert('RGB')
    else:
        transparency_present = False
        result = oriented.convert('RGB').copy()
    return result, {
        'source_mode': source_mode,
        'source_size': list(source_size),
        'alpha_composited': alpha,
        'transparency_present': transparency_present,
        'exif_transposed': orientation in (2, 3, 4, 5, 6, 7, 8),
    }


def _decode(raw: bytes | bytearray | memoryview | Image.Image, max_pixels: int):
    if isinstance(raw, Image.Image):
        return _flatten_image(raw, max_pixels)
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise TypeError('expected image bytes or a PIL image')
    if not raw:
        raise ValueError('empty image')
    try:
        with Image.open(BytesIO(raw)) as opened:
            # Check dimensions before EXIF transpose/conversion decodes pixels.
            return _flatten_image(opened, max_pixels)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('invalid or unsupported image') from exc


def decode_document_image(raw, max_pixels: int = MAX_IMAGE_PIXELS) -> Image.Image:
    """Decode once, apply EXIF orientation, and composite transparency onto white."""
    return _decode(raw, max_pixels)[0]


def _background(rgb: np.ndarray) -> np.ndarray:
    """Estimate low-frequency paper behind narrow strokes, without editing ink."""
    height, width = rgb.shape[:2]
    short = min(height, width)
    if short < 5:
        return np.full_like(rgb, 255)
    # A rectangular closing is separable in OpenCV and bounded by working size.
    # Its result is only a background estimate; no closed stroke enters a mask.
    side = min(81, max(15, (int(short * .045) // 2) * 2 + 1))
    side = min(side, short if short % 2 else short - 1)
    bg = cv2.morphologyEx(rgb, cv2.MORPH_CLOSE, np.ones((side, side), np.uint8))
    bg = cv2.GaussianBlur(bg, (0, 0), sigmaX=max(1., side / 16.))
    return np.maximum(bg, rgb)


def _connected_weak(strong: np.ndarray, weak: np.ndarray) -> tuple[np.ndarray, bool]:
    if not np.any(strong):
        return np.zeros_like(strong), False
    count, labels = cv2.connectedComponents(weak.astype(np.uint8), connectivity=8)
    areas = np.bincount(labels.ravel(), minlength=count)
    seed_areas = np.bincount(labels[strong], minlength=count)
    selected = seed_areas > 0
    # A faint connected texture (for example a baked-in checkerboard) can touch
    # one real stroke and otherwise flood hysteresis across the whole page.
    # Preserve such marks as uncertain instead of upgrading all their pixels.
    limited = selected & (areas > np.maximum(seed_areas * 3, seed_areas + 32))
    selected[limited] = False
    selected[0] = False
    return selected[labels] | strong, bool(np.any(limited))


def _u8(mask: np.ndarray) -> np.ndarray:
    return mask.astype(np.uint8) * 255


def analyze_document(raw_or_pil, max_work_side: int = DEFAULT_WORK_SIDE,
                     max_pixels: int = MAX_IMAGE_PIXELS) -> DocumentEvidence:
    """Return bounded, auditable layers for colour, shade, weak ink, and blur.

    This function performs no OCR, remote inference, topology completion, or
    image-specific lookup. ``sharpened`` is presentation/candidate assistance
    only. In particular, it is never the source of the returned ink masks.
    """
    if isinstance(max_work_side, bool) or not isinstance(max_work_side, int) or max_work_side < 1:
        raise ValueError('max_work_side must be a positive integer')
    original, metadata = _decode(raw_or_pil, max_pixels)
    width, height = original.size
    factor = min(1., max_work_side / max(width, height))
    work_size = (max(1, round(width * factor)), max(1, round(height * factor)))
    working = (original.resize(work_size, Image.Resampling.LANCZOS)
               if work_size != original.size else original.copy())
    rgb = np.asarray(working, dtype=np.uint8)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    border = np.concatenate((gray[0], gray[-1], gray[:, 0], gray[:, -1]))
    dark_background = bool(np.percentile(gray, 50) < 90 and np.mean(border < 110) >= .65)
    paper = 255 - rgb if dark_background else rgb.copy()
    paper_gray = cv2.cvtColor(paper, cv2.COLOR_RGB2GRAY)
    bg = _background(paper)
    bg_gray = cv2.cvtColor(bg, cv2.COLOR_RGB2GRAY)
    gray_float = paper_gray.astype(np.float32)
    bg_float = bg_gray.astype(np.float32)
    darkness = np.maximum(bg_float - gray_float, 0.) / np.maximum(bg_float, 32.)

    # Local detail prevents a broad, smooth illumination ramp being classed as
    # a weak line simply because closing slightly overestimates its background.
    detail = np.maximum(cv2.GaussianBlur(gray_float, (0, 0), 2.5) - gray_float, 0.)
    lab = cv2.cvtColor(paper, cv2.COLOR_RGB2LAB).astype(np.float32)
    bg_lab = cv2.cvtColor(bg, cv2.COLOR_RGB2LAB).astype(np.float32)
    chroma = np.sqrt(np.sum((lab[:, :, 1:] - bg_lab[:, :, 1:]) ** 2, axis=2))
    saturation = cv2.cvtColor(paper, cv2.COLOR_RGB2HSV)[:, :, 1]
    channel_difference = np.max(bg.astype(np.float32) - paper.astype(np.float32), axis=2)
    channel_contrast = channel_difference / np.maximum(np.max(bg, axis=2), 32.)
    strong_color = (chroma >= 10.) & (channel_contrast >= .13) & (saturation >= 28)
    weak_color = (chroma >= 4.) & (channel_contrast >= .045) & (saturation >= 12)
    strong = (darkness >= .28) | strong_color
    weak = ((darkness >= .045) & ((detail >= 1.5) | (darkness >= .23))) | weak_color | strong
    trusted, weak_flood_limited = _connected_weak(strong, weak)
    uncertain = weak & ~trusted
    low_contrast_only = bool(np.any(weak) and not np.any(strong))
    if low_contrast_only:
        # An all-faint diagram must remain available, explicitly uncertain.
        trusted = weak.copy()

    background_range = float(np.percentile(bg_gray, 95) - np.percentile(bg_gray, 5))
    background_level = float(np.percentile(bg_gray, 85))
    channel_medians = np.median(bg.reshape(-1, 3), axis=0)
    tinted_background = bool(np.max(channel_medians) - np.min(channel_medians) > 14)
    normalize = bool(dark_background or background_range > 18 or background_level < 225 or tinted_background)
    if normalize:
        normalized_float = paper.astype(np.float32) * (255. / np.maximum(bg.astype(np.float32), 32.))
        # Saturated screen backgrounds may have a zero channel after polarity
        # reversal. Division by a floor alone would tint an empty background.
        neutral = gray_float * (255. / np.maximum(bg_float, 32.))
        normalized_float = np.where(bg < 32, neutral[:, :, None], normalized_float)
        normalized_array = np.rint(np.clip(normalized_float, 0, 255)).astype(np.uint8)
    else:
        # Clean diagrams retain their exact working RGB values.
        normalized_array = paper.copy()

    laplacian_variance = float(cv2.Laplacian(paper_gray, cv2.CV_32F).var())
    sx = cv2.Sobel(paper_gray, cv2.CV_32F, 1, 0, ksize=3)
    sy = cv2.Sobel(paper_gray, cv2.CV_32F, 0, 1, ksize=3)
    gradient_energy = float(np.mean(sx * sx + sy * sy))
    contrast_range = float(np.percentile(paper_gray, 99.9) - np.percentile(paper_gray, .1))
    ink_fraction = float(np.mean(trusted))
    blur_warning = bool(laplacian_variance < 60 and contrast_range > 16 and .0005 < ink_fraction < .5)
    if blur_warning:
        smooth = cv2.GaussianBlur(normalized_array, (0, 0), .8)
        sharpened_array = cv2.addWeighted(normalized_array, 1.35, smooth, -.35, 0)
    else:
        sharpened_array = normalized_array.copy()

    diagnostics = []
    if metadata['alpha_composited']:
        diagnostics.append('transparency_composited_on_white')
    if metadata['exif_transposed']:
        diagnostics.append('exif_orientation_applied')
    if work_size != original.size:
        diagnostics.append('working_image_downscaled_original_retained')
    if dark_background:
        diagnostics.append('dark_background_auxiliary_polarity_inverted')
    if normalize:
        diagnostics.append('paper_background_normalized_auxiliary_only')
    if np.any(uncertain):
        diagnostics.append('weak_ink_retained_separately')
    if weak_flood_limited:
        diagnostics.append('connected_weak_texture_kept_uncertain')
    if low_contrast_only:
        diagnostics.append('low_contrast_only_candidates_require_review')
    if blur_warning:
        diagnostics.append('possible_blur_auxiliary_sharpening_only')
    if not np.any(weak):
        diagnostics.append('no_local_ink_candidates')

    quality = {
        **metadata,
        'original_size': list(original.size),
        'work_size': list(work_size),
        'dark_background': dark_background,
        'background_range': round(background_range, 4),
        'background_level': round(background_level, 4),
        'background_normalized': normalize,
        'tinted_background': tinted_background,
        'laplacian_variance': round(laplacian_variance, 4),
        'gradient_energy': round(gradient_energy, 4),
        'contrast_range': round(contrast_range, 4),
        'possible_blur': blur_warning,
        'ink_fraction': round(ink_fraction, 6),
        'strong_ink_fraction': round(float(np.mean(strong)), 6),
        'uncertain_ink_fraction': round(float(np.mean(uncertain)), 6),
        'color_ink_fraction': round(float(np.mean(strong_color | weak_color)), 6),
        'low_contrast_only': low_contrast_only,
        'weak_flood_limited': weak_flood_limited,
        'mask_source': 'working_image_local_contrast_not_sharpened',
        'masks_are_candidates': True,
    }
    return DocumentEvidence(
        original=original,
        working=working,
        normalized=Image.fromarray(normalized_array),
        sharpened=Image.fromarray(sharpened_array),
        ink_mask=_u8(trusted),
        strong_ink=_u8(strong),
        uncertain_ink=_u8(uncertain),
        work_size=work_size,
        scale_xy=(work_size[0] / width, work_size[1] / height),
        quality=quality,
        diagnostics=diagnostics,
    )
