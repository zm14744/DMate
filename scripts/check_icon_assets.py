#!/usr/bin/env python3
"""Guard against transparent Windows shortcuts and mismatched PWA/install icons."""
import json
from pathlib import Path
from PIL import Image, ImageChops

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

    # Browser tab stays a separate transparent white-line icon.
    assert rgba(ICONS / "favicon-32.png").getpixel((0, 0))[3] == 0

    manifest = json.loads((ROOT / "static" / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["scope"] == "/pwa/" and manifest["start_url"] == "/pwa/", (
        "Do not reintroduce normal website links launching the installed PWA"
    )
    for icon in manifest["icons"]:
        path = ROOT / icon["src"].split("?")[0].lstrip("/")
        assert path.is_file(), f"Missing PWA image: {path}"
    print("OK Windows icons, PWA icons, and tab favicon remain separated")


if __name__ == "__main__":
    main()
