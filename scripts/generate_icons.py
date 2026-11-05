#!/usr/bin/env python3
"""Build every DMate icon from the same vector geometry, never from a PNG.

All platforms use the same bright reference-inspired wireframe and stroke.
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
VERSION = "v52"
VIEWBOX = 256
STROKE = 4.5  # Shared reference weight; no separate thickening for tiny icons.
ADAPTIVE_SCALE = 0.72
BLACK = (0, 0, 0, 255)
WHITE = (255, 255, 255, 255)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
APP_SIZES = (16, 32, 48, 64, 96, 128, 180, 192, 256, 512, 1024)

# Vector reconstruction of the supplied white-wireframe reference. Keep the
# same connected polyhedron across platforms, including its generous margins.
OUTER = [(59, 73), (103, 48), (154, 39), (205, 84), (215, 129),
         (201, 188), (139, 215), (94, 217), (51, 170), (41, 126), (59, 73)]
INNER = [
    [(59, 73), (69, 82), (127, 66), (154, 39)],
    [(69, 82), (61, 145), (51, 170)],
    [(127, 66), (162, 116), (215, 129)],
    [(162, 116), (119, 165), (61, 145)],
    [(119, 165), (139, 215)],
]
PATHS = [OUTER, *INNER]


def path_d(points):
    return "M" + str(points[0][0]) + " " + str(points[0][1]) + " " + " ".join(
        f"L{x} {y}" for x, y in points[1:]
    )


def svg_mark(background="#000", foreground="#fff"):
    background_element = (f'  <rect width="{VIEWBOX}" height="{VIEWBOX}" fill="{background}"/>\n'
                          if background is not None else "")
    paths = "\n    ".join(f'<path d="{path_d(points)}"/>' for points in PATHS)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" '
        f'viewBox="0 0 {VIEWBOX} {VIEWBOX}" role="img" aria-label="DMate">\n'
        f'{background_element}'
        f'  <g fill="none" stroke="{foreground}" stroke-width="{STROKE}" '
        f'stroke-linecap="round" stroke-linejoin="round">\n    {paths}\n  </g>\n</svg>\n'
    )


def draw_mark(size, background=BLACK, foreground=WHITE, circle=False):
    """Supersample the shared line weight without minimum-width compensation."""
    oversample = max(4, math.ceil(1024 / size))
    side = size * oversample
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    if background is not None:
        if circle:
            draw.ellipse((0, 0, side - 1, side - 1), fill=background)
        else:
            draw.rectangle((0, 0, side - 1, side - 1), fill=background)
    width = round(STROKE * side / VIEWBOX)
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
        f'android:strokeColor="{foreground}" android:strokeWidth="{STROKE}" '
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
    assert (farthest + STROKE / 2) * ADAPTIVE_SCALE * 108 / VIEWBOX < 33
    (ANDROID / "drawable").mkdir(parents=True, exist_ok=True)
    for name, color in (("dmate_foreground", "#FFFFFF"), ("dmate_monochrome", "#000000")):
        (ANDROID / "drawable" / f"{name}.xml").write_text(android_vector(color), encoding="utf-8")
    # Retire the generated bitmap with the same Android resource name.
    (ANDROID / "drawable-nodpi" / "dmate_foreground.png").unlink(missing_ok=True)
    for density, size in (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)):
        for name, circle in (("ic_launcher", False), ("ic_launcher_round", True)):
            save_png(draw_mark(size, circle=circle),
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
    (STATIC / f"dmate-brand-{VERSION}.svg").write_text(svg_mark(), encoding="utf-8")
    for size in APP_SIZES:
        save_png(draw_mark(size), STATIC / f"dmate-app-{VERSION}-{size}.png")
    save_ico(STATIC / f"dmate-app-{VERSION}.ico")
    for tone, rgba, color in (("white", WHITE, "#fff"), ("black", BLACK, "#000")):
        base = f"dmate-tab-{tone}-{VERSION}"
        (STATIC / f"{base}.svg").write_text(svg_mark(None, color), encoding="utf-8")
        for size in (16, 32, 48, 64, 128):
            save_png(draw_mark(size, background=None, foreground=rgba),
                     STATIC / f"{base}-{size}.png")
        save_ico(STATIC / f"{base}.ico", background=None, foreground=rgba)
    # Keep stable public aliases usable for old pages and direct icon requests.
    for source, target in (
        (f"dmate-brand-{VERSION}.svg", "dmate-mark.svg"),
        (f"dmate-tab-white-{VERSION}.svg", "dmate-transparent.svg"),
        (f"dmate-app-{VERSION}-180.png", "apple-touch-icon.png"),
        (f"dmate-app-{VERSION}-512.png", "icon-512.png"),
        (f"dmate-app-{VERSION}.ico", "favicon-app.ico"),
        (f"dmate-app-{VERSION}.ico", "favicon.ico"),
        (f"dmate-app-{VERSION}-192.png", "favicon.png"),
    ):
        shutil.copyfile(STATIC / source, STATIC / target)
    # Generic favicon URLs may be discovered by search engines without the
    # browser-specific HTML. Always use the opaque brand here; transparent
    # tab variants remain available only under their explicit tab filenames.
    for size in (16, 32, 48, 64, 96, 128, 192):
        shutil.copyfile(STATIC / f"dmate-app-{VERSION}-{size}.png", STATIC / f"favicon-{size}.png")
    for size, name in ((16, "icon-16.png"), (24, "icon-24.png"), (32, "32x32.png"),
                       (48, "icon-48.png"), (64, "icon-64.png"), (128, "128x128.png"),
                       (256, "128x128@2x.png"), (512, "icon.png"), (1024, "icon-1024.png")):
        save_png(draw_mark(size), TAURI / name)
    save_ico(TAURI / "icon.ico")
    save_icns(TAURI / "icon.icns")
    generate_android()
    print(json.dumps({"status": "generated", "version": VERSION, "source": "reference-inspired vector paths",
                      "formats": ["SVG", "PNG", "ICO", "ICNS", "Android VectorDrawable"],
                      "max_bitmap_size": 1024, "android_adaptive_safe_circle_dp": 66,
                      "stroke_units": STROKE,
                      "small_icons": "shared moderate stroke, independently supersampled"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
