#!/usr/bin/env python3
"""Regressions: no theme-adaptive favicon, no bitmap-upscaled PWA/ICO/ICNS."""
import json
import struct
from pathlib import Path
from PIL import Image, ImageChops
from generate_icons import draw_mark, TAB_STROKE

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "static" / "icons"
DESKTOP = ROOT / "desktop" / "src-tauri" / "icons"
MASTER = ROOT / "android/app/src/main/res/mipmap-xxxhdpi/ic_launcher.png"


def rgba(path):
    with Image.open(path) as image:
        return image.convert("RGBA")


def matches_vector(path, size, **options):
    actual = rgba(path)
    expected = draw_mark(size, **options)
    assert actual.size == (size, size), f"Unexpected resolution: {path}"
    assert ImageChops.difference(actual.convert("RGB"), expected.convert("RGB")).getbbox() is None, (
        f"Not vector-rendered at native resolution: {path}"
    )


def check_ico(path, sizes):
    # Individual sizes inside ICO are real native-size PNG payloads.
    data = path.read_bytes()
    assert data[:4] == bytes([0, 0, 1, 0])
    count = struct.unpack_from("<H", data, 4)[0]
    found = set()
    for i in range(count):
        width, height, _, _, _, _, length, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
        size = width or 256
        assert (height or 256) == size
        with Image.open(__import__("io").BytesIO(data[offset:offset + length])) as bitmap:
            assert bitmap.size == (size, size)
        found.add(size)
    assert set(sizes).issubset(found), (path, found)


def main():
    with Image.open(MASTER) as master:
        assert master.size == (192, 192)
        for filename in ("icon-192.png", "icon-192-app-v20.png"):
            assert (ICONS / filename).read_bytes() == MASTER.read_bytes()

    for filename in ("icon-512.png", "icon-512-app-v20.png"):
        matches_vector(ICONS / filename, 512)

    for browser, factor in (("edge", 0.95), ("fennec", 1.16)):
        for size in (32, 192, 512):
            matches_vector(ICONS / f"android-{browser}-{size}-v21.png",
                           size, figure_scale=factor)

    # Android-only PWA maskable artwork must be black edge-to-edge, with
    # the white geometry inside the centered 80% safe circle. Prevent the
    # missing-maskable regression that caused white launcher frames.
    for size in (192, 512):
        maskable = ICONS / f"android-pwa-maskable-{size}-v24.png"
        matches_vector(maskable, size, figure_scale=0.82)
        pixels = rgba(maskable)
        for xy in ((0, 0), (size - 1, 0), (0, size - 1),
                   (size - 1, size - 1), (size // 2, 0)):
            assert pixels.getpixel(xy) == (0, 0, 0, 255), (
                f"{maskable}: Android launcher background cannot be white/transparent"
            )
        # No visible linework may escape the 80%-diameter centered circle.
        for x in range(size):
            for y in range(size):
                red, green, blue, _ = pixels.getpixel((x, y))
                if max(red, green, blue) > 48:
                    assert (x - (size - 1) / 2) ** 2 + (y - (size - 1) / 2) ** 2 <= (size * 0.4) ** 2, (
                        f"{maskable}: foreground outside adaptive safe zone"
                    )

    for size, filename in (
        (180, "apple-touch-icon.png"),
        (128, "windows-shortcut-128-v20.png"),
        (192, "windows-shortcut-192-v20.png"),
        (256, "windows-shortcut-256-v20.png"),
    ):
        matches_vector(ICONS / filename, size)

    for size, filename in (
        (16, "icon-16.png"), (24, "icon-24.png"), (32, "32x32.png"),
        (48, "icon-48.png"), (64, "icon-64.png"), (128, "128x128.png"),
        (256, "128x128@2x.png"), (512, "icon.png"),
    ):
        matches_vector(DESKTOP / filename, size)

    matches_vector(ICONS / "dmate-favicon-mac.png", 256, rounded=True, stroke_units=TAB_STROKE)
    mac_svg = (ICONS / "dmate-favicon-mac.svg").read_text(encoding="utf-8")
    assert '<rect width="1254" height="1254" rx="190" ry="190" fill="#000"/>' in mac_svg
    assert 'stroke="#fff"' in mac_svg and 'stroke-width="23"' in mac_svg
    assert "prefers-color-scheme" not in mac_svg and "<style" not in mac_svg
    assert "media=" not in mac_svg
    assert not (ICONS / "dmate-favicon-mac-light.svg").exists()
    assert rgba(ICONS / "favicon-32.png").getpixel((0, 0))[3] == 0

    check_ico(ICONS / "favicon.ico", (16, 32, 48, 64, 128))
    check_ico(ICONS / "windows-shortcut-black-v20.ico", (16, 24, 32, 48, 64, 128, 256))
    check_ico(DESKTOP / "icon.ico", (16, 24, 32, 48, 64, 128, 256))
    raw_icns = (DESKTOP / "icon.icns").read_bytes()
    assert raw_icns.startswith(b"icns")
    assert struct.unpack_from(">I", raw_icns, 4)[0] == len(raw_icns)

    for manifest_file in ("manifest.webmanifest", "manifest-mobile.webmanifest"):
        manifest = json.loads((ROOT / "static" / manifest_file).read_text(encoding="utf-8"))
        assert manifest["start_url"] == "/pwa/"
        assert len(manifest["icons"]) == 2
        for record in manifest["icons"]:
            assert record["purpose"] == "any"
            assert (ROOT / record["src"].split("?")[0].lstrip("/")).is_file()
    assert json.loads((ROOT / "static/manifest.webmanifest").read_text())["scope"] == "/pwa/"
    assert json.loads((ROOT / "static/manifest-mobile.webmanifest").read_text())["scope"] == "/"

    html = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    assert "dmate-favicon-mac.svg?v=dmate-fixed-v22" in html
    assert "dmate-favicon-mac.png?v=dmate-fixed-v22" in html
    assert "dmate-win-tab-v21" in html
    print("PASS vector sharpness + theme-invariant Safari + PWA + ICO + ICNS")


if __name__ == "__main__":
    main()
