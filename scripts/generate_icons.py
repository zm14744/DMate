#!/usr/bin/env python3
"""Generate consistent, high-resolution DMate app icons and browser favicons."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps

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


def svg_mark(background=None, foreground="#fff", stroke=32, adaptive=False):
    paths = "\n    ".join(f'<path d="{path_d(points)}"/>' for points in PATHS)
    if adaptive:
        return f'''<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 1254 1254" role="img" aria-label="DMate">
  <style>
    .icon-lines {{ stroke: #111827; }}
    @media (prefers-color-scheme: dark) {{
      .icon-lines {{ stroke: #fff; }}
    }}
  </style>
  <g class="icon-lines" fill="none" stroke-width="23" stroke-linecap="round" stroke-linejoin="round">
    {paths}
  </g>
</svg>'''
    bg = "" if background is None else f'<rect width="1254" height="1254" fill="{background}"/>'
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 1254 1254">
  {bg}
  <g fill="none" stroke="{foreground}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">
    {paths}
  </g>
</svg>'''


def draw_mark(size, background=None, foreground=(255, 255, 255, 255),
              stroke_units=23, shadow=False, figure_scale=1.0):
    """Render the reference app icon with its original medium-weight wireframe."""
    scale = 4
    side = size * scale
    fill = background if background is not None else (0, 0, 0, 0)
    image = Image.new("RGBA", (side, side), fill)
    draw = ImageDraw.Draw(image)

    def scaled(points):
        return [(round((VIEWBOX / 2 + (x - VIEWBOX / 2) * figure_scale) * side / VIEWBOX),
                 round((VIEWBOX / 2 + (y - VIEWBOX / 2) * figure_scale) * side / VIEWBOX))
                for x, y in points]

    line_width = max(1, round(stroke_units * figure_scale * side / VIEWBOX))
    if shadow:
        shadow_width = max(line_width + 1, round((stroke_units + 20) * side / VIEWBOX))
        for points in PATHS:
            draw.line(scaled(points), fill=(0, 0, 0, 112), width=shadow_width, joint="curve")
    for points in PATHS:
        draw.line(scaled(points), fill=foreground, width=line_width, joint="curve")
    return image.resize((size, size), Image.Resampling.LANCZOS)


def compensated_android_icon(size, figure_scale, master):
    """Keep the exact native icon's black tile and stroke shapes; compensate
    for launchers that magnify (Edge) or inset (Firefox/Fennec) the linework.
    Scaling occurs *inside* the tile, never by padding a complete square icon.
    """
    reference = master.resize((size, size), Image.Resampling.LANCZOS)
    ink_mask = ImageOps.grayscale(reference.convert("RGB"))
    ink = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    ink.putalpha(ink_mask)
    scaled_side = round(size * figure_scale)
    resized_ink = ink.resize((scaled_side, scaled_side), Image.Resampling.LANCZOS)
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 255))
    if scaled_side <= size:
        offset = (size - scaled_side) // 2
        tile.alpha_composite(resized_ink, (offset, offset))
    else:
        offset = (scaled_side - size) // 2
        tile.alpha_composite(resized_ink.crop((offset, offset, offset + size, offset + size)))
    return tile


def save_png(image, path):
    # Preserve RGBA transparency and antialiasing; avoid palette quantization blur.
    image.save(path, format="PNG", optimize=True)


def save_ico(source_path, target_path, sizes):
    source = Image.open(source_path).convert("RGBA")
    source.save(target_path, format="ICO", sizes=sizes)


def main():
    STATIC.mkdir(parents=True, exist_ok=True)
    TAURI.mkdir(parents=True, exist_ok=True)

    # The installed Android app artwork is the single master for all platforms.
    # Never redraw or independently pad PWA geometry: Android launchers scale
    # maskable icons and will otherwise change their apparent line width.
    master_path = ROOT / "android/app/src/main/res/mipmap-xxxhdpi/ic_launcher.png"
    with Image.open(master_path) as source:
        canonical_icon = source.convert("RGBA")
    if canonical_icon.size != (192, 192):
        raise RuntimeError("Expected 192x192 installed-app icon")

    def from_installed_icon(size):
        if size == 192:
            return canonical_icon.copy()
        return canonical_icon.resize((size, size), Image.Resampling.LANCZOS)

    for size, filename in [
        (192, "icon-192.png"), (512, "icon-512.png"),
        (192, "icon-192-unified-v16.png"), (512, "icon-512-unified-v16.png"),
    ]:
        if size == 192:
            # Byte-identical to the shipped Android installed-app launcher PNG.
            shutil.copyfile(master_path, STATIC / filename)
        else:
            save_png(from_installed_icon(size), STATIC / filename)

    # Per-browser Android PWA illustrations. Native APK itself remains unchanged.
    # Browser launcher masks, not a new icon design, cause the screenshot's
    # Edge icon to be too large and Fennec's too small.
    for browser, figure_scale in (("edge", 0.95), ("fennec", 1.16)):
        for size in (32, 192, 512):
            save_png(compensated_android_icon(size, figure_scale, canonical_icon),
                     STATIC / f"android-{browser}-{size}-v21.png")

    # Some Android browsers create desktop shortcuts from favicon rather than
    # the Web Manifest. Give them opaque versions of the SAME installed-app icon.
    for size, filename in [(32, "mobile-favicon-32-v17.png"),
                           (192, "mobile-favicon-192-v17.png")]:
        save_png(from_installed_icon(size), STATIC / filename)

    (STATIC / "dmate-mark.svg").write_text(
        svg_mark("#000", "#fff", 23), encoding="utf-8"
    )
    # Transparent white linework for browser tabs; no black square is baked in.
    (STATIC / "dmate-transparent.svg").write_text(
        svg_mark(None, "#fff", 23), encoding="utf-8"
    )

    # Tauri desktop assets match the PWA artwork at every size.
    tauri_sizes = [
        (16, "icon-16.png"), (24, "icon-24.png"), (32, "32x32.png"),
        (48, "icon-48.png"), (64, "icon-64.png"), (128, "128x128.png"),
        (256, "128x128@2x.png"), (512, "icon.png"),
    ]
    for size, filename in tauri_sizes:
        save_png(from_installed_icon(size), TAURI / filename)
    save_ico(TAURI / "icon.png", TAURI / "icon.ico", [
        (16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)
    ])
    try:
        Image.open(TAURI / "icon.png").save(TAURI / "icon.icns", format="ICNS")
    except Exception as exc:
        raise RuntimeError(f"Failed to generate macOS ICNS icon: {exc}") from exc

    # Windows/browser favicon: white geometry on true transparency.
    for size, filename in [
        (16, "favicon-16.png"), (32, "favicon-32.png"),
        (48, "favicon-48.png"), (128, "favicon-128.png"),
    ]:
        save_png(draw_mark(size, background=None, foreground=(255, 255, 255, 255),
                           stroke_units=23, shadow=False), STATIC / filename)
    save_ico(STATIC / "favicon-128.png", STATIC / "favicon.ico", [
        (16, 16), (32, 32), (48, 48), (64, 64), (128, 128)
    ])

    # Separate opaque app shortcut icon: black tile + white wireframe.
    save_ico(STATIC / "icon-512.png", STATIC / "favicon-app.ico", [
        (16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)
    ])
    # Windows Start/PWA/desktop shell icons: NEVER use transparent tab favicon.
    for size, filename in [
        (128, "windows-shortcut-128-v20.png"),
        (192, "windows-shortcut-192-v20.png"),
        (256, "windows-shortcut-256-v20.png"),
    ]:
        save_png(from_installed_icon(size), STATIC / filename)
    save_ico(STATIC / "icon-512.png", STATIC / "windows-shortcut-black-v20.ico", [
        (16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)
    ])
    # New filenames make installed browser apps re-request the corrected art.
    for size, filename in [
        (192, "icon-192-app-v20.png"), (512, "icon-512-app-v20.png")
    ]:
        save_png(from_installed_icon(size), STATIC / filename)


    # Safari *tab* needs adaptive linework with no baked-in white/black tile.
    # Installed Apple PWA keeps exactly the Android master black app artwork.
    (STATIC / "dmate-favicon-mac.svg").write_text(
        svg_mark(adaptive=True), encoding="utf-8"
    )
    save_png(from_installed_icon(180), STATIC / "apple-touch-icon.png")
    summary = {}
    for path in [
        STATIC / "icon-192.png", STATIC / "icon-512.png",
        STATIC / "icon-192-unified-v16.png", STATIC / "icon-512-unified-v16.png",
        STATIC / "apple-touch-icon.png",
        STATIC / "mobile-favicon-32-v17.png", STATIC / "mobile-favicon-192-v17.png",
        STATIC / "favicon-16.png", STATIC / "favicon-32.png", STATIC / "favicon-48.png",
        STATIC / "favicon-128.png", STATIC / "favicon.ico", STATIC / "favicon-app.ico",
        STATIC / "windows-shortcut-128-v20.png", STATIC / "windows-shortcut-192-v20.png",
        STATIC / "windows-shortcut-256-v20.png", STATIC / "windows-shortcut-black-v20.ico",
        STATIC / "icon-192-app-v20.png", STATIC / "icon-512-app-v20.png",
        STATIC / "dmate-favicon-mac.svg",
        *[STATIC / f"android-{browser}-{size}-v21.png"
          for browser in ("edge", "fennec") for size in (32, 192, 512)],
        TAURI / "32x32.png", TAURI / "128x128.png", TAURI / "128x128@2x.png",
        TAURI / "icon.png", TAURI / "icon.ico", TAURI / "icon.icns",
    ]:
        if path.exists():
            summary[str(path.relative_to(ROOT))] = {"bytes": path.stat().st_size}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
