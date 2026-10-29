"""Qwen image admission and transport limits, separate from preview sizing.

Aliyun Model Studio's vision guide (2026-10-29) allows Qwen3.8 originals up
to 20 MB, but its OpenAI-compatible image Data URI must ALSO fit in 20 MB.
Use decimal bytes so the advertised limit never exceeds either interpretation.
Source bytes remain untouched; only an oversized model sending copy is encoded
as JPEG, preserving every source pixel position and the full image dimensions.

https://help.aliyun.com/zh/model-studio/vision#image-limit
"""
from __future__ import annotations

import base64
import io

MAX_IMAGE_BYTES = 20_000_000
MAX_IMAGE_PIXELS = 7680 * 4320
MAX_QWEN_IMAGE_DATA_URI_BYTES = 20_000_000


def encode_qwen_image(image):
    """Prefer lossless PNG; bound Base64 bytes without shrinking the picture."""
    def encoded(format_name, mime, **options):
        with io.BytesIO() as stream:
            image.save(stream, format=format_name, **options)
            prefix = 'data:' + mime + ';base64,'
            # Check the exact Base64 expansion BEFORE allocating a huge string.
            if len(prefix) + 4 * ((stream.tell() + 2) // 3) > MAX_QWEN_IMAGE_DATA_URI_BYTES:
                return None
            return prefix + base64.b64encode(stream.getvalue()).decode('ascii')

    png = encoded('PNG', 'image/png')
    if png is not None:
        return png
    del png
    # PNG can be much larger than the uploaded JPEG. Encoding the sending copy
    # avoids rejecting a valid large original or silently sending an invalid URI.
    # Descending quality is a bounded fallback; no image resizing/cropping occurs.
    for quality in (95, 90, 85, 80, 70, 60, 50, 40, 30, 20, 10):
        jpeg = encoded('JPEG', 'image/jpeg', quality=quality, subsampling=0)
        if jpeg is not None:
            return jpeg
    raise ValueError('image cannot fit the model image transport limit')
