#!/usr/bin/env python3
"""Guard against transparent Windows shortcuts and mismatched PWA/install icons."""
import json
from pathlib import Path
from PIL import Image, ImageChops, ImageOps

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "static" / "icons"
DESKTOP = ROOT / "desktop" / "src-tauri" / "icons"
MASTER = ROOT / "android/app/src/main/res/mipmap-xxxhdpi/ic_launcher.png"


def rgba(file):
    with Image.open(file) as im:
        return im.convert("RGBA")


def verify_master_copy(file, size, master):
    image = rgba(file)
    assert image.size == (size, size), f"{file}: wrong pixel dimensions"
    desired = master.resize((size, size), Image.Resampling.LANCZOS)
    assert ImageChops.difference(image, desired).getbbox() is None, (
        f"{file}: does not match original DMate installed app icon"
    )
    print("OK", file.relative_to(ROOT))


def main():
    master = rgba(MASTER)
    assert master.size == (192, 192), "Android installed-app icon changed shape"
    for filename, size in (
        ("icon-192-app-v20.png", 192),
        ("icon-512-app-v20.png", 512),
        ("windows-shortcut-128-v20.png", 128),
        ("windows-shortcut-192-v20.png", 192),
        ("windows-shortcut-256-v20.png", 256),
    ):
        verify_master_copy(ICONS / filename, size, master)
    verify_master_copy(DESKTOP / "icon.png", 512, master)

    with Image.open(ICONS / "windows-shortcut-black-v20.ico") as ico:
        required = {(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)}
        assert required.issubset(ico.ico.sizes()), "Windows shortcut ICO is missing sizes"

    # Verify the compensated linework, not an enlarged/padded full black tile.
    def ink_box(filename):
        im = rgba(ICONS / filename)
        return ImageOps.grayscale(im.convert("RGB")).point(
            lambda value: 255 if value >= 100 else 0
        ).getbbox()

    master_box = ImageOps.grayscale(master.convert("RGB")).point(
        lambda value: 255 if value >= 100 else 0
    ).getbbox()
    for name in ("edge", "fennec"):
        for size in (32, 192, 512):
            file = ICONS / f"android-{name}-{size}-v21.png"
            assert rgba(file).size == (size, size), file
            assert rgba(file).getpixel((0, 0))[3] == 255, file
    edge_box = ink_box("android-edge-192-v21.png")
    fennec_box = ink_box("android-fennec-192-v21.png")
    assert (edge_box[2] - edge_box[0]) < (master_box[2] - master_box[0]), "Edge lines must be smaller"
    assert (fennec_box[2] - fennec_box[0]) > (master_box[2] - master_box[0]), "Fennec lines must be larger"

    # Website browser tab stays a separate transparent thin-line icon.
    assert 'stroke-width="23"' in (ICONS / "dmate-transparent.svg").read_text()
    mac_svg = (ICONS / "dmate-favicon-mac.svg").read_text()
    assert '<rect' not in mac_svg, "Mac favicon must not bake in a white background"
    assert 'stroke-width="23"' in mac_svg
    assert not (ICONS / "dmate-favicon-mac-light.svg").exists()

    assert rgba(ICONS / "favicon-32.png").getpixel((0, 0))[3] == 0

    manifest = json.loads((ROOT / "static" / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["scope"] == "/pwa/" and manifest["start_url"] == "/pwa/", (
        "Do not reintroduce normal website links launching the installed PWA"
    )
    for icon in manifest["icons"]:
        path = ROOT / icon["src"].split("?")[0].lstrip("/")
        assert path.is_file(), f"Missing PWA image: {path}"
    assert len(manifest["icons"]) == 2 and all(
        icon["purpose"] == "any" for icon in manifest["icons"]
    ), "Do not bring back maskable / double-cropped launcher icons"
    mobile_manifest = json.loads((ROOT / "static" / "manifest-mobile.webmanifest").read_text(encoding="utf-8"))
    assert mobile_manifest["scope"] == "/", "QQ/Quark menu must retain homepage scope"
    index_html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'dmate-win-tab-v21' in index_html
    assert "windows-shortcut-128-v20.png\">" not in index_html, "Large black tile cannot be browser favicon"
    print("OK Android launcher compensation, thin Windows tabs, adaptive Mac, and compatible PWA scopes")


if __name__ == "__main__":
    main()
