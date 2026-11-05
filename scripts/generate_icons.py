#!/usr/bin/env python3
"""Build every DMate icon from the same vector geometry, never from a PNG.

The brand SVG and browser tabs have optical line weights for their CSS sizes.
Native bitmap frames are rasterized independently; Android adaptive icons use
VectorDrawable paths. Historical versioned web assets remain available for old
cached pages but are no longer inputs to this generator.
"""
from __future__ import annotations

import io
import json
import math
import shutil
import struct
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static" / "icons"
TAURI = ROOT / "desktop" / "src-tauri" / "icons"
ANDROID = ROOT / "android" / "app" / "src" / "main" / "res"
VERSION = "v49"
VIEWBOX = 1254
STROKE = 13
BRAND_STROKE = 34  # About one CSS pixel at the existing 38px sidebar size.
TAB_STROKE = 80  # About one CSS pixel at a 16px browser tab, at any DPR.
ADAPTIVE_SCALE = 0.72
ADAPTIVE_STROKE = 20
BLACK = (0, 0, 0, 255)
WHITE = (255, 255, 255, 255)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
APP_SIZES = (16, 32, 64, 128, 180, 192, 256, 512, 1024)

# The original DMate silhouette and every internal edge, unchanged.
OUTER = [(252, 300), (488, 189), (748, 140), (1038, 376), (1071, 603),
         (1012, 914), (690, 1044), (456, 1064), (199, 807), (165, 589), (252, 300)]
INNER = [
    [(252, 300), (302, 352), (601, 268), (748, 140)],
    [(302, 352), (263, 686), (199, 807)],
    [(601, 268), (790, 524), (1071, 603)],
    [(790, 524), (563, 786), (263, 686)],
    [(563, 786), (690, 1044)],
]
PATHS = [OUTER, *INNER]


def path_d(points):
    return "M" + str(points[0][0]) + " " + str(points[0][1]) + " " + " ".join(
        f"L{x} {y}" for x, y in points[1:]
    )


def optical_stroke(size):
    """Keep tiny native frames bright instead of averaging a subpixel hairline."""
    return max(STROKE, 1.15 * VIEWBOX / size)


def svg_mark(background="#000", foreground="#fff", stroke=STROKE):
    background_element = (f'  <rect width="{VIEWBOX}" height="{VIEWBOX}" fill="{background}"/>\n'
                          if background is not None else "")
    paths = "\n    ".join(f'<path d="{path_d(points)}"/>' for points in PATHS)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" '
        f'viewBox="0 0 {VIEWBOX} {VIEWBOX}" role="img" aria-label="DMate">\n'
        f'{background_element}'
        f'  <g fill="none" stroke="{foreground}" stroke-width="{stroke}" '
        f'stroke-linecap="round" stroke-linejoin="round">\n    {paths}\n  </g>\n</svg>\n'
    )


def draw_mark(size, background=BLACK, foreground=WHITE, stroke_units=None, circle=False):
    """Rasterize paths at each native output size with supersampled round joins."""
    oversample = 16 if size < 128 else 4
    side = size * oversample
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    if background is not None:
        if circle:
            draw.ellipse((0, 0, side - 1, side - 1), fill=background)
        else:
            draw.rectangle((0, 0, side - 1, side - 1), fill=background)
    stroke_units = optical_stroke(size) if stroke_units is None else stroke_units
    width = max(1, round(stroke_units * side / VIEWBOX))
    radius = width / 2
    for path in PATHS:
        points = [(x * side / VIEWBOX, y * side / VIEWBOX) for x, y in path]
        draw.line(points, fill=foreground, width=width, joint="curve")
        # Match SVG/VectorDrawable's round ends and joins at sharp corners.
        for x, y in points:
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=foreground)
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def save_png(image, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG", optimize=True)


def png_bytes(size, **options):
    with io.BytesIO() as output:
        draw_mark(size, **options).save(output, "PNG", optimize=True)
        return output.getvalue()


def save_ico(path, **options):
    """ICO contains a separately rendered frame at every Windows shell size."""
    payloads = [png_bytes(size, **options) for size in ICO_SIZES]
    offset = 6 + 16 * len(ICO_SIZES)
    output = io.BytesIO()
    output.write(struct.pack("<HHH", 0, 1, len(ICO_SIZES)))
    for size, data in zip(ICO_SIZES, payloads):
        output.write(struct.pack("<BBBBHHII", size if size < 256 else 0,
                                 size if size < 256 else 0, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    for data in payloads:
        output.write(data)
    path.write_bytes(output.getvalue())


def save_icns(path):
    representations = [
        (b"icp4", 16), (b"icp5", 32), (b"icp6", 64), (b"ic07", 128),
        (b"ic08", 256), (b"ic09", 512), (b"ic10", 1024),
        (b"ic11", 32), (b"ic12", 64), (b"ic13", 256), (b"ic14", 512),
    ]
    blocks = []
    for kind, size in representations:
        payload = png_bytes(size)
        blocks.append(kind + struct.pack(">I", len(payload) + 8) + payload)
    body = b"".join(blocks)
    path.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)


def android_vector(foreground):
    paths = "\n".join(
        f'        <path android:fillColor="@android:color/transparent" '
        f'android:strokeColor="{foreground}" android:strokeWidth="{ADAPTIVE_STROKE}" '
        f'android:strokeLineCap="round" android:strokeLineJoin="round" '
        f'android:pathData="{path_d(points)}" />'
        for points in PATHS
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<vector xmlns:android="http://schemas.android.com/apk/res/android"\n'
        f'    android:width="108dp" android:height="108dp" android:viewportWidth="{VIEWBOX}" android:viewportHeight="{VIEWBOX}">\n'
        f'    <group android:pivotX="{VIEWBOX / 2:g}" android:pivotY="{VIEWBOX / 2:g}" '
        f'android:scaleX="{ADAPTIVE_SCALE}" android:scaleY="{ADAPTIVE_SCALE}">\n'
        f'{paths}\n    </group>\n</vector>\n'
    )


def generate_android():
    # The entire stroked mark stays inside Android's 66dp-diameter safe circle.
    farthest = max(math.hypot(x - VIEWBOX / 2, y - VIEWBOX / 2) for path in PATHS for x, y in path)
    assert (farthest + ADAPTIVE_STROKE / 2) * ADAPTIVE_SCALE * 108 / VIEWBOX < 33
    (ANDROID / "drawable").mkdir(parents=True, exist_ok=True)
    for name, color in (("dmate_foreground", "#FFFFFF"), ("dmate_monochrome", "#000000")):
        (ANDROID / "drawable" / f"{name}.xml").write_text(android_vector(color), encoding="utf-8")
    # Retire the generated bitmap with the same Android resource name.
    (ANDROID / "drawable-nodpi" / "dmate_foreground.png").unlink(missing_ok=True)
    for density, size in (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)):
        for name, circle in (("ic_launcher", False), ("ic_launcher_round", True)):
            save_png(draw_mark(size, stroke_units=optical_stroke(48), circle=circle),
                     ANDROID / f"mipmap-{density}" / f"{name}.png")
    for api in (26, 33):
        directory = ANDROID / f"mipmap-anydpi-v{api}"
        directory.mkdir(parents=True, exist_ok=True)
        monochrome = '    <monochrome android:drawable="@drawable/dmate_monochrome" />\n' if api >= 33 else ""
        contents = ('<?xml version="1.0" encoding="utf-8"?>\n'
                    '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
                    '    <background android:drawable="@color/launcher_black" />\n'
                    '    <foreground android:drawable="@drawable/dmate_foreground" />\n'
                    + monochrome + '</adaptive-icon>\n')
        for name in ("ic_launcher", "ic_launcher_round"):
            (directory / f"{name}.xml").write_text(contents, encoding="utf-8")


def main():
    STATIC.mkdir(parents=True, exist_ok=True)
    TAURI.mkdir(parents=True, exist_ok=True)
    (STATIC / "dmate-master.svg").write_text(svg_mark(), encoding="utf-8")
    (STATIC / f"dmate-brand-{VERSION}.svg").write_text(svg_mark(stroke=BRAND_STROKE), encoding="utf-8")
    for size in APP_SIZES:
        save_png(draw_mark(size), STATIC / f"dmate-app-{VERSION}-{size}.png")
    save_ico(STATIC / f"dmate-app-{VERSION}.ico")
    for tone, rgba, color in (("white", WHITE, "#fff"), ("black", BLACK, "#000")):
        base = f"dmate-tab-{tone}-{VERSION}"
        (STATIC / f"{base}.svg").write_text(svg_mark(None, color, TAB_STROKE), encoding="utf-8")
        for size in (16, 32, 48, 64, 128):
            save_png(draw_mark(size, background=None, foreground=rgba, stroke_units=TAB_STROKE),
                     STATIC / f"{base}-{size}.png")
        save_ico(STATIC / f"{base}.ico", background=None, foreground=rgba, stroke_units=TAB_STROKE)
    # Keep stable public aliases usable for old pages and direct icon requests.
    for source, target in (
        (f"dmate-brand-{VERSION}.svg", "dmate-mark.svg"),
        (f"dmate-tab-white-{VERSION}.svg", "dmate-transparent.svg"),
        (f"dmate-app-{VERSION}-180.png", "apple-touch-icon.png"),
        (f"dmate-app-{VERSION}-512.png", "icon-512.png"),
        (f"dmate-app-{VERSION}.ico", "favicon-app.ico"),
        (f"dmate-tab-white-{VERSION}.ico", "favicon.ico"),
    ):
        shutil.copyfile(STATIC / source, STATIC / target)
    for size in (16, 32, 48, 128):
        shutil.copyfile(STATIC / f"dmate-tab-white-{VERSION}-{size}.png", STATIC / f"favicon-{size}.png")
    for size, name in ((16, "icon-16.png"), (24, "icon-24.png"), (32, "32x32.png"),
                       (48, "icon-48.png"), (64, "icon-64.png"), (128, "128x128.png"),
                       (256, "128x128@2x.png"), (512, "icon.png"), (1024, "icon-1024.png")):
        save_png(draw_mark(size), TAURI / name)
    save_ico(TAURI / "icon.ico")
    save_icns(TAURI / "icon.icns")
    generate_android()
    print(json.dumps({"status": "generated", "version": VERSION, "source": "original vector paths",
                      "formats": ["SVG", "PNG", "ICO", "ICNS", "Android VectorDrawable"],
                      "max_bitmap_size": 1024, "android_adaptive_safe_circle_dp": 66,
                      "small_icons": "independent optical-size rendering"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
