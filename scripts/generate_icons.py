#!/usr/bin/env python3
"""Generate crisp, platform-specific DMate icons from one geometric mark.

Windows/PWA icons use a transparent canvas with a white wireframe and a subtle
edge keyline. Browser favicons are rendered separately at their actual sizes.
Safari receives an adaptive light/dark SVG and matching Apple touch icons.
"""
from __future__ import annotations

import io
import json
import struct
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static" / "icons"
TAURI = ROOT / "desktop" / "src-tauri" / "icons"
VIEWBOX = 1254
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
    return f'M{points[0][0]} {points[0][1]} ' + " ".join(
        f"L{x} {y}" for x, y in points[1:]
    )


def svg_mark(background=None, foreground="#fff", stroke=34, shadow=False, adaptive=False):
    paths = "\n".join(f'<path d="{path_d(points)}"/>' for points in PATHS)
    if adaptive:
        return f'''<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 1254 1254" role="img" aria-label="DMate">
  <style>
    .icon-background {{ fill: #fff; }}
    .icon-lines {{ stroke: #111827; }}
    @media (prefers-color-scheme: dark) {{
      .icon-background {{ fill: #000; }}
      .icon-lines {{ stroke: #fff; }}
    }}
  </style>
  <rect class="icon-background" width="1254" height="1254"/>
  <g class="icon-lines" fill="none" stroke-width="40" stroke-linecap="round" stroke-linejoin="round">{paths}</g>
</svg>'''
    bg = "" if background is None else f'<rect width="1254" height="1254" fill="{background}"/>'
    shadow_group = ""
    if shadow:
        shadow_group = f'<g fill="none" stroke="#000" stroke-opacity="0.42" stroke-width="54" stroke-linecap="round" stroke-linejoin="round">{paths}</g>'
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 1254 1254">
  {bg}{shadow_group}
  <g fill="none" stroke="{foreground}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{paths}</g>
</svg>'''


def draw_mark(size, background=None, foreground=(255, 255, 255, 255),
              stroke_units=34, shadow=True):
    # 4x supersampling keeps diagonals and small-size line joins crisp.
    scale = 4
    side = size * scale
    image = Image.new("RGBA", (side, side), background or (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def scaled(points):
        return [(round(x * side / VIEWBOX), round(y * side / VIEWBOX)) for x, y in points]

    line_width = max(1, round(stroke_units * side / VIEWBOX))
    if shadow:
        shadow_width = max(line_width + 1, round((stroke_units + 20) * side / VIEWBOX))
        for points in PATHS:
            draw.line(scaled(points), fill=(0, 0, 0, 112), width=shadow_width, joint="curve")
    for points in PATHS:
        draw.line(scaled(points), fill=foreground, width=line_width, joint="curve")
    return image.resize((size, size), Image.Resampling.LANCZOS)


def save_png(image, path):
    # Indexed PNGs keep geometric assets small while retaining transparent pixels.
    image.quantize(colors=16, method=Image.Quantize.FASTOCTREE).save(path, optimize=True)


def save_ico(path):
    sizes = [16, 24, 32, 48, 64, 128, 256]
    file_map = {
        16: "icon-16.png", 24: "icon-24.png", 32: "32x32.png",
        48: "icon-48.png", 64: "icon-64.png", 128: "128x128.png",
        256: "128x128@2x.png",
    }
    payloads, entries = [], []
    offset = 6 + 16 * len(sizes)
    for size in sizes:
        image = Image.open(TAURI / file_map[size]).convert("RGBA")
        buf = io.BytesIO()
        image.save(buf, format="PNG", optimize=True)
        data = buf.getvalue()
        payloads.append(data)
        entries.append(struct.pack(
            "<BBBBHHII", 0 if size == 256 else size, 0 if size == 256 else size,
            0, 0, 1, 32, len(data), offset
        ))
        offset += len(data)
    with path.open("wb") as out:
        out.write(struct.pack("<HHH", 0, 1, len(sizes)))
        for entry in entries:
            out.write(entry)
        for payload in payloads:
            out.write(payload)


def main():
    STATIC.mkdir(parents=True, exist_ok=True)
    TAURI.mkdir(parents=True, exist_ok=True)

    # Transparent white mark: no black square is baked into Windows or PWA icons.
    transparent_svg = svg_mark(None, "#fff", 34, shadow=True)
    (STATIC / "dmate-mark.svg").write_text(transparent_svg, encoding="utf-8")
    (STATIC / "dmate-transparent.svg").write_text(transparent_svg, encoding="utf-8")

    for size, filename in [(192, "icon-192.png"), (512, "icon-512.png")]:
        save_png(draw_mark(size), STATIC / filename)
    # Keep the same geometry on Edge and Fennec instead of shipping different symbols.
    save_png(draw_mark(512), STATIC / "icon-maskable-512.png")

    tauri_sizes = [
        (16, "icon-16.png"), (24, "icon-24.png"), (32, "32x32.png"),
        (48, "icon-48.png"), (64, "icon-64.png"), (128, "128x128.png"),
        (256, "128x128@2x.png"), (512, "icon.png"),
    ]
    for size, filename in tauri_sizes:
        save_png(draw_mark(size), TAURI / filename)
    save_ico(TAURI / "icon.ico")

    # macOS desktop app icon: a clean light tile with dark geometry.
    mac_native = draw_mark(512, background=(255, 255, 255, 255),
                           foreground=(17, 24, 39, 255), stroke_units=40, shadow=False)
    try:
        mac_native.save(TAURI / "icon.icns", format="ICNS")
    except Exception:
        # Web/Safari icons remain generated even if an environment lacks ICNS encoding.
        pass

    # Dedicated favicon files are rendered at target size, not scaled down from 192 px.
    for size, filename, stroke in [
        (16, "favicon-16.png", 65), (32, "favicon-32.png", 44),
        (48, "favicon-48.png", 36), (128, "favicon-128.png", 30),
    ]:
        mark = draw_mark(size, background=(0, 0, 0, 255),
                         foreground=(255, 255, 255, 255),
                         stroke_units=stroke, shadow=False)
        save_png(mark, STATIC / filename)

    (STATIC / "dmate-favicon-mac.svg").write_text(
        svg_mark("#fff", "#111827", 40, shadow=False, adaptive=True), encoding="utf-8"
    )
    save_png(draw_mark(180, background=(255, 255, 255, 255),
                       foreground=(17, 24, 39, 255), stroke_units=32, shadow=False),
             STATIC / "apple-touch-mac-light.png")
    save_png(draw_mark(180, background=(0, 0, 0, 255),
                       foreground=(255, 255, 255, 255), stroke_units=32, shadow=False),
             STATIC / "apple-touch-mac-dark.png")

    summary = {}
    for path in [
        STATIC / "icon-192.png", STATIC / "icon-512.png", STATIC / "icon-maskable-512.png",
        STATIC / "favicon-16.png", STATIC / "favicon-32.png", STATIC / "favicon-48.png",
        STATIC / "favicon-128.png", STATIC / "dmate-favicon-mac.svg",
        STATIC / "apple-touch-mac-light.png", STATIC / "apple-touch-mac-dark.png",
        TAURI / "32x32.png", TAURI / "128x128.png", TAURI / "128x128@2x.png",
        TAURI / "icon.png", TAURI / "icon.ico", TAURI / "icon.icns",
    ]:
        if path.exists():
            summary[str(path.relative_to(ROOT))] = {"bytes": path.stat().st_size}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
