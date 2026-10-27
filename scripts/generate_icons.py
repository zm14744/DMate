#!/usr/bin/env python3
"""Generate DMate artwork directly from geometric paths at every output size.

No 192px PNG is upscaled to make 512px/ICO/ICNS assets. The pre-existing native
Android 192px image remains untouched and is retained at exactly native size.
"""
from __future__ import annotations

import io
import json
import shutil
import struct
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static" / "icons"
TAURI = ROOT / "desktop" / "src-tauri" / "icons"
MASTER = ROOT / "android" / "app" / "src" / "main" / "res" / "mipmap-xxxhdpi" / "ic_launcher.png"
VIEWBOX = 1254
STROKE = 13  # Original installed Android icon uses ~2px hairline at 192px
TAB_STROKE = 23  # Other browser tabs keep existing white hairline artwork.
SAFARI_TAB_STROKE = 78  # At 16–24 CSS px the black strokes must stay readable.
BLACK = (0, 0, 0, 255)
WHITE = (255, 255, 255, 255)

# The original DMate geometry. This is the ONE editable source of the lines.
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

# Search-result-specific faceted light hierarchy. The DMate vertex coordinates,
# path order and STROKE=13 are untouched. These very dark face fills make the
# existing white hairlines stand out on Bing's tiny desktop favicon.
BING_FACETS = [
    ([(252,300),(488,189),(748,140),(601,268),(302,352)], (22,30,43,255)),
    ([(252,300),(302,352),(263,686),(199,807),(165,589)], (13,21,33,255)),
    ([(601,268),(748,140),(1038,376),(1071,603),(790,524)], (27,37,54,255)),
    ([(302,352),(601,268),(790,524),(563,786),(263,686)], (20,31,47,255)),
    ([(263,686),(563,786),(690,1044),(456,1064),(199,807)], (14,24,38,255)),
    ([(790,524),(1071,603),(1012,914),(690,1044),(563,786)], (17,27,42,255)),
]
BING_STROKES = [
    (255,255,255,255), # outer silhouette
    (234,243,255,255), # upper inner geometry
    (183,204,226,255), # receding left
    (247,251,255,255), # prominent right ridge
    (218,231,246,255), # central diagonal
    (174,195,219,255), # receding lower structure
]


def path_d(points):
    return "M" + str(points[0][0]) + " " + str(points[0][1]) + " " + " ".join(
        f"L{x} {y}" for x, y in points[1:]
    )


def svg_mark(background=None, foreground="#fff", stroke=STROKE, corner_radius=0):
    """Fixed-color SVG: no prefers-color-scheme, CSS media query or masking."""
    paths = "\n    ".join(f'<path d="{path_d(points)}"/>' for points in PATHS)
    bg = ""
    if background is not None:
        radius = f' rx="{corner_radius}" ry="{corner_radius}"' if corner_radius else ""
        bg = f'<rect width="{VIEWBOX}" height="{VIEWBOX}"{radius} fill="{background}"/>'
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" '
        f'viewBox="0 0 {VIEWBOX} {VIEWBOX}" role="img" aria-label="DMate">\n'
        f'  {bg}\n'
        f'  <g fill="none" stroke="{foreground}" stroke-width="{stroke}" '
        f'stroke-linecap="round" stroke-linejoin="round">\n    {paths}\n  </g>\n</svg>\n'
    )


def draw_mark(size, background=BLACK, foreground=WHITE, stroke_units=STROKE,
              figure_scale=1.0, rounded=False, oversample_factor=None,
              facets=False, stroke_palette=None, coverage_gamma=None):
    """Rasterize vector coordinates directly at native size with supersampling.

    figure_scale modifies only geometric coordinates BEFORE rasterization.
    It never stretches or resamples an existing bitmap, and line width does
    not become thick/thin when a browser's launcher needs size compensation.
    """
    if size >= 128:
        oversample = 4
    elif oversample_factor is None:
        oversample = 8
    else:
        oversample = max(8, int(oversample_factor))
    side = size * oversample
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    if background is not None:
        if rounded:
            radius = round(190 * side / VIEWBOX)
            draw.rounded_rectangle((0, 0, side - 1, side - 1), radius=radius, fill=background)
        else:
            draw.rectangle((0, 0, side, side), fill=background)

    def coords(points):
        return [
            (round((VIEWBOX / 2 + (x - VIEWBOX / 2) * figure_scale) * side / VIEWBOX),
             round((VIEWBOX / 2 + (y - VIEWBOX / 2) * figure_scale) * side / VIEWBOX))
            for x, y in points
        ]

    # Facet fills are LEGACY v38/v39 ONLY. v40 passes the pure WHITE palette
    # to the antialias branch but must leave every face solid black.
    if facets and stroke_palette != [WHITE] * len(PATHS):
        for points, face_color in BING_FACETS:
            draw.polygon(coords(points), fill=face_color)
    line_width = max(1, round(stroke_units * side / VIEWBOX))
    if facets:
        # A 13-unit line occupies only ~0.17 source-independent pixels at 16px.
        # Correct its LANCZOS subpixel luminance after rasterization without
        # changing the vector stroke width or any original vertex coordinates.
        ink = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        pen = ImageDraw.Draw(ink)
        for index, points in enumerate(PATHS):
            color = stroke_palette[index] if stroke_palette is not None else foreground
            pen.line(coords(points), fill=color, width=line_width, joint="curve")
        reduced = ink.resize((size, size), Image.Resampling.LANCZOS)
        if size <= 32 or coverage_gamma is not None:
            exponent = (coverage_gamma if coverage_gamma is not None
                        else (0.53 if size <= 24 else 0.70))
            alpha = reduced.getchannel("A").point(
                lambda value: 0 if value < 12 else min(
                    255, round(255 * ((value / 255.0) ** exponent))
                )
            )
            reduced.putalpha(alpha)
        return Image.alpha_composite(
            canvas.resize((size, size), Image.Resampling.LANCZOS), reduced
        )
    for points in PATHS:
        draw.line(coords(points), fill=foreground, width=line_width, joint="curve")
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def save_png(image, path):
    image.save(path, "PNG", optimize=True)


def render_png_bytes(size, background=BLACK, figure_scale=1.0, stroke_units=STROKE,
                     foreground=WHITE, rounded=False, oversample_factor=None,
                     facets=False, stroke_palette=None):
    with io.BytesIO() as buffer:
        save_png(draw_mark(size, background=background, foreground=foreground,
                           figure_scale=figure_scale, stroke_units=stroke_units,
                           rounded=rounded, oversample_factor=oversample_factor,
                           facets=facets, stroke_palette=stroke_palette), buffer)
        return buffer.getvalue()


def save_ico(path, sizes, background=BLACK, stroke_units=STROKE, foreground=WHITE,
             rounded=False, figure_scale=1.0, figure_scale_by_size=None,
             oversample_factor=None, facets=False, stroke_palette=None):
    """Build ICO from independently vector-rendered PNGs at EACH exact size."""
    sizes = list(sizes)
    figure_scale_by_size = figure_scale_by_size or {}
    payloads = [
        render_png_bytes(size, background=background, foreground=foreground,
                         stroke_units=stroke_units, rounded=rounded,
                         figure_scale=figure_scale_by_size.get(size, figure_scale),
                         oversample_factor=oversample_factor, facets=facets,
                         stroke_palette=stroke_palette)
        for size in sizes
    ]
    offset = 6 + 16 * len(sizes)
    out = io.BytesIO()
    out.write(struct.pack("<HHH", 0, 1, len(sizes)))
    for size, data in zip(sizes, payloads):
        out.write(struct.pack("<BBBBHHII", size if size < 256 else 0,
                              size if size < 256 else 0, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    for data in payloads:
        out.write(data)
    path.write_bytes(out.getvalue())


def save_icns(path):
    """ICNS icon representations are drawn from vector paths, never upscaled."""
    representations = [
        (b"icp4", 16), (b"icp5", 32), (b"icp6", 64), (b"ic07", 128),
        (b"ic08", 256), (b"ic09", 512), (b"ic10", 1024),
        (b"ic11", 32), (b"ic12", 64), (b"ic13", 256), (b"ic14", 512),
    ]
    blocks = []
    for kind, size in representations:
        payload = render_png_bytes(size)
        blocks.append(kind + struct.pack(">I", len(payload) + 8) + payload)
    body = b"".join(blocks)
    path.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)


def main():
    STATIC.mkdir(parents=True, exist_ok=True)
    TAURI.mkdir(parents=True, exist_ok=True)
    with Image.open(MASTER) as original:
        assert original.size == (192, 192), "Original Android installed icon changed"

    # Social preview: render directly from vector geometry, not an enlarged bitmap.
    save_png(draw_mark(512), STATIC / "icon-512.png")

    # Direct path rendering: compensate for browsers' own app-icon crop/inset.
    # Line thickness stays fixed while the geometry size is adjusted.
    for browser, geometry_scale in (("edge", 0.95), ("fennec", 1.16)):
        for size in (32, 192):
            save_png(draw_mark(size, figure_scale=geometry_scale),
                     STATIC / f"android-{browser}-{size}-v21.png")

    for size, name in ((32, "mobile-favicon-32-v17.png"),
                       (192, "mobile-favicon-192-v17.png")):
        if size == 192:
            shutil.copyfile(MASTER, STATIC / name)
        else:
            save_png(draw_mark(size), STATIC / name)

    (STATIC / "dmate-mark.svg").write_text(svg_mark("#000"), encoding="utf-8")
    (STATIC / "dmate-transparent.svg").write_text(
        svg_mark(background=None, stroke=TAB_STROKE), encoding="utf-8"
    )

    # Keep the working light-mode black tile. In dark mode Safari can
    # paint a pale background over DARK-FILLED favicons; use TRANSPARENT
    # background with bright WHITE vector strokes instead. Fresh path versions
    # avoid WebKit's per-site favicon database persisting the old icon.
    for theme, background, foreground in (
        ("light", BLACK, WHITE),
        ("dark", None, WHITE),
    ):
        for size in (32, 64):
            save_png(
                draw_mark(size, background=background, foreground=foreground,
                          rounded=background is not None, stroke_units=SAFARI_TAB_STROKE),
                STATIC / f"dmate-safari-{theme}-v32-{size}.png"
            )
        save_ico(
            STATIC / f"dmate-safari-{theme}-v32.ico",
            (16, 32, 48, 64, 128),
            background=background, foreground=foreground,
            stroke_units=SAFARI_TAB_STROKE
        )

    # Preserve v34 exactly for Safari and existing browser tabs. The earlier
    # 78-unit strokes are deliberately NOT reused for the Bing/search favicon.
    # Each ICO size is rendered independently from the original geometry.
    save_png(draw_mark(64, background=BLACK, foreground=WHITE,
                       rounded=True, stroke_units=SAFARI_TAB_STROKE),
             STATIC / "dmate-site-v34-64.png")
    save_ico(STATIC / "dmate-site-v34.ico", (16, 24, 32, 48, 64, 128, 256),
             background=BLACK, foreground=WHITE,
             stroke_units=SAFARI_TAB_STROKE, rounded=True)

    # Bing/search branding: rounded BLACK tile, original thin WHITE geometry.
    # STROKE=13 is the original DMate line weight; never thicken it to 78.
    save_png(draw_mark(64, background=BLACK, foreground=WHITE,
                       rounded=True, stroke_units=STROKE),
             STATIC / "dmate-site-v35-64.png")
    save_ico(STATIC / "dmate-site-v35.ico", (16, 24, 32, 48, 64, 128, 256),
             background=BLACK, foreground=WHITE,
             stroke_units=STROKE, rounded=True)

    # Bing/search favicon v36: BLACK rounded tile and original WHITE hairlines.
    # Never increase STROKE; adjust only the geometry size at tiny resolutions.
    save_png(draw_mark(64, background=BLACK, foreground=WHITE,
                       rounded=True, stroke_units=STROKE, figure_scale=1.08),
             STATIC / "dmate-site-v36-64.png")
    save_ico(STATIC / "dmate-site-v36.ico",
             (16, 24, 32, 48, 64, 128, 256),
             background=BLACK, foreground=WHITE,
             stroke_units=STROKE, rounded=True,
             figure_scale=1.08,
             figure_scale_by_size={
                 16: 1.18, 24: 1.14, 32: 1.11, 48: 1.09,
                 64: 1.08, 128: 1.06, 256: 1.04,
             })

    # Bing/search favicon v37: preserve the exact original DMate mark and line width.
    # Higher supersampling improves subpixel hairline rendering; STROKE remains 13.
    save_png(draw_mark(64, background=BLACK, foreground=WHITE,
                       rounded=True, stroke_units=STROKE, figure_scale=1.08,
                       oversample_factor=16),
             STATIC / "dmate-site-v37-64.png")
    save_ico(STATIC / "dmate-site-v37.ico",
             (16, 24, 32, 48, 64, 128, 256),
             background=BLACK, foreground=WHITE,
             stroke_units=STROKE, rounded=True,
             figure_scale=1.08,
             figure_scale_by_size={
                 16: 1.18, 24: 1.14, 32: 1.11, 48: 1.09,
                 64: 1.08, 128: 1.06, 256: 1.04,
             },
             oversample_factor=16)

    # Search favicon v38 only: brighter leading ridges and distinct white/gray
    # line-depth hierarchy plus low-contrast facets; no thicker strokes. All
    # mobile/browser/app launch icons remain byte-identical to the old build.
    bing_scales = {16: 1.18, 24: 1.14, 32: 1.11, 48: 1.09,
                   64: 1.08, 128: 1.06, 256: 1.04}
    for size in (16, 32, 64):
        save_png(draw_mark(size, background=BLACK, rounded=True,
                           stroke_units=STROKE, figure_scale=bing_scales[size],
                           oversample_factor=16, facets=True,
                           stroke_palette=BING_STROKES),
                 STATIC / f"dmate-site-v38-{size}.png")
    save_ico(STATIC / "dmate-site-v38.ico",
             (16, 24, 32, 48, 64, 128, 256),
             background=BLACK, stroke_units=STROKE, rounded=True,
             figure_scale_by_size=bing_scales, oversample_factor=16,
             facets=True, stroke_palette=BING_STROKES)

    # v39 preserves v38's geometry/palette/facets, but lifts only the
    # anti-aliased subpixel brightness at 16/24/32px for desktop Bing SERP.
    for size in (16, 32, 64):
        save_png(draw_mark(size, background=BLACK, rounded=True,
                           stroke_units=STROKE, figure_scale=bing_scales[size],
                           oversample_factor=16, facets=True,
                           stroke_palette=BING_STROKES),
                 STATIC / f"dmate-site-v39-{size}.png")
    save_ico(STATIC / "dmate-site-v39.ico",
             (16, 24, 32, 48, 64, 128, 256),
             background=BLACK, stroke_units=STROKE, rounded=True,
             figure_scale_by_size=bing_scales, oversample_factor=16,
             facets=True, stroke_palette=BING_STROKES)

    # v40 — Bing DESKTOP search favicon ONLY.
    # Pure white original wireframe (#fff), and pure black interior/background.
    # No polygons, coloured facets, gradients, glow or thicker strokes.
    # The existing subpixel alpha correction is applied to 16/24/32px to
    # lift perceived brightness without changing the 13-unit vector width.
    for size in (16, 32, 64):
        save_png(draw_mark(size, background=BLACK, foreground=WHITE,
                           stroke_units=STROKE, rounded=True,
                           figure_scale=bing_scales[size], oversample_factor=16,
                           facets=True, stroke_palette=[WHITE] * len(PATHS),
                           ),
                 STATIC / f"dmate-site-v40-{size}.png")
    save_ico(STATIC / "dmate-site-v40.ico",
             (16, 24, 32, 48, 64, 128, 256),
             background=BLACK, foreground=WHITE,
             stroke_units=STROKE, rounded=True,
             figure_scale_by_size=bing_scales, oversample_factor=16,
             facets=True, stroke_palette=[WHITE] * len(PATHS))

    # Desktop WEBSITE sidebar/header brand. The shared dmate-mark.svg stroke
    # is 13/1254 * 38 = 0.39 CSS px at desktop size: in 1x rasterization
    # its #fff ink turns dim gray from subpixel coverage. Render independent
    # DPR=1/2/3 assets directly from the SAME geometry and SAME thin stroke,
    # then lift subpixel luminance only (not path width or black face fill).
    # Mobile sidebar/header remain on the original SVG. No favicon changes.
    brand_densities = ((1, 38, 0.55), (2, 76, 0.72), (3, 114, 0.83))
    for density, pixels, exponent in brand_densities:
        save_png(draw_mark(pixels, background=BLACK, foreground=WHITE,
                           stroke_units=STROKE, rounded=False,
                           oversample_factor=16, facets=True,
                           stroke_palette=[WHITE] * len(PATHS),
                           coverage_gamma=exponent),
                 STATIC / f"dmate-brand-desktop-v41-{pixels}.png")

    # iOS Safari uses the Apple touch icon for site bookmarks and Home Screen shortcuts.
    save_png(draw_mark(180), STATIC / "apple-touch-icon.png")
    for size, name in (
        (128, "windows-shortcut-128-v20.png"),
        (192, "windows-shortcut-192-v20.png"),
        (256, "windows-shortcut-256-v20.png"),
    ):
        save_png(draw_mark(size), STATIC / name)

    tauri_sizes = (
        (16, "icon-16.png"), (24, "icon-24.png"), (32, "32x32.png"),
        (48, "icon-48.png"), (64, "icon-64.png"), (128, "128x128.png"),
        (256, "128x128@2x.png"), (512, "icon.png"),
    )
    for size, name in tauri_sizes:
        save_png(draw_mark(size), TAURI / name)

    icon_sizes = (16, 24, 32, 48, 64, 128, 256)
    save_ico(TAURI / "icon.ico", icon_sizes)
    save_ico(STATIC / "windows-shortcut-black-v20.ico", icon_sizes)
    save_ico(STATIC / "favicon-app.ico", icon_sizes)
    save_icns(TAURI / "icon.icns")

    # Transparent white linework for browser tabs; application icons are generated separately.
    for size in (16, 32, 48, 128):
        save_png(draw_mark(size, background=None, stroke_units=TAB_STROKE),
                 STATIC / f"favicon-{size}.png")
    save_ico(STATIC / "favicon.ico", (16, 32, 48, 64, 128),
             background=None, stroke_units=TAB_STROKE)

    print(json.dumps({"status": "vector-only generation",
                      "mac_favicon": "light black tile/white lines; dark transparent white lines (PNG + ICO)",
                      "formats": ["SVG", "PNG", "ICO", "ICNS"],
                      "platforms": ["iOS Safari", "Android browser", "Windows", "macOS", "Linux"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
