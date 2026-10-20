#!/usr/bin/env python3
"""Regressions: stable favicons and vector-rendered website/desktop icons."""
import struct
import io
from pathlib import Path
from PIL import Image, ImageChops
from generate_icons import draw_mark, STROKE, TAB_STROKE, SAFARI_TAB_STROKE, WHITE, BLACK, BING_STROKES, BING_FACETS

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "static" / "icons"
DESKTOP = ROOT / "desktop" / "src-tauri" / "icons"


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
    matches_vector(ICONS / "icon-512.png", 512)

    for browser, factor in (("edge", 0.95), ("fennec", 1.16)):
        for size in (32, 192):
            matches_vector(ICONS / f"android-{browser}-{size}-v21.png",
                           size, figure_scale=factor)

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

    # Desktop website sidebar brand must have 1x, 2x and 3x independently
    # rasterized images; do not change mobile SVG nor Bing search favicon.
    for px, gamma in ((38, 0.55), (76, 0.72), (114, 0.83)):
        matches_vector(ICONS / f"dmate-brand-desktop-v41-{px}.png",
                       px, background=BLACK, foreground=WHITE,
                       stroke_units=STROKE, rounded=False,
                       oversample_factor=16, facets=True,
                       stroke_palette=[WHITE] * 6, coverage_gamma=gamma)
        with Image.open(ICONS / f"dmate-brand-desktop-v41-{px}.png") as image:
            rgb = image.convert("RGB")
            assert all(r == g == b for r, g, b in rgb.getdata()), "Brand mark must stay black and white"
            assert rgb.getpixel((px//2, px//2))[0] == 0, "Unfilled center must stay black"
        baseline = draw_mark(px, background=BLACK, foreground=WHITE,
                             stroke_units=STROKE, rounded=False,
                             oversample_factor=16, facets=True,
                             stroke_palette=[WHITE] * 6)
        assert sum(rgba(ICONS / f"dmate-brand-desktop-v41-{px}.png").convert("L").getdata()) > sum(baseline.convert("L").getdata()), (
            px, "Desktop brand must be visibly brighter than uncorrected hairlines"
        )
    template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'media="(min-width:1101px)"' in template
    assert 'src="/static/icons/dmate-mark.svg?v=dmate-v6-14"' in template, "Mobile keeps the original SVG"
    for px in (38, 76, 114):
        assert f"/static/icons/dmate-brand-desktop-v41-{px}.png" in template

    # macOS light mode preserves a black tile; dark mode uses no tile at all.
    for theme, background, foreground in (
        ("light", BLACK, WHITE), ("dark", None, WHITE)
    ):
        for size in (32, 64):
            path = ICONS / f"dmate-safari-{theme}-v32-{size}.png"
            actual = rgba(path)
            expected = draw_mark(
                size, background=background, foreground=foreground,
                rounded=background is not None, stroke_units=SAFARI_TAB_STROKE
            )
            assert ImageChops.difference(actual, expected).getbbox() is None, path
            if theme == "dark":
                assert actual.getpixel((size // 2, 0))[3] == 0, (
                    "Safari dark icon must not contain an opaque background")
                assert any(actual.getpixel((x, y))[3] > 180
                           for x in range(size // 6, size * 5 // 6)
                           for y in range(size // 6, size * 5 // 6)), (
                    "Safari dark white geometry missing")
            else:
                # Top center is background; inner geometry can cross y=size/16.
                assert actual.getpixel((size // 2, 0))[:3] == (0, 0, 0)
        check_ico(ICONS / f"dmate-safari-{theme}-v32.ico", (16, 32, 48, 64, 128))
    matches_vector(ICONS / "dmate-site-v34-64.png", 64, background=BLACK,
                   foreground=WHITE, rounded=True, stroke_units=SAFARI_TAB_STROKE)
    check_ico(ICONS / "dmate-site-v34.ico", (16, 24, 32, 48, 64, 128, 256))
    matches_vector(ICONS / "dmate-site-v35-64.png", 64, background=BLACK,
                   foreground=WHITE, rounded=True, stroke_units=STROKE)
    check_ico(ICONS / "dmate-site-v35.ico", (16, 24, 32, 48, 64, 128, 256))
    # v36 improves tiny Bing favicon recognition only through geometry scale;
    # compare every native-size ICO layer to the unchanged original stroke width.
    matches_vector(ICONS / "dmate-site-v36-64.png", 64, background=BLACK,
                   foreground=WHITE, rounded=True, stroke_units=STROKE,
                   figure_scale=1.08)
    check_ico(ICONS / "dmate-site-v36.ico", (16, 24, 32, 48, 64, 128, 256))
    ico_data = (ICONS / "dmate-site-v36.ico").read_bytes()
    scales = {16: 1.18, 24: 1.14, 32: 1.11, 48: 1.09,
              64: 1.08, 128: 1.06, 256: 1.04}
    for i in range(struct.unpack_from("<H", ico_data, 4)[0]):
        w, h, _, _, _, _, length, offset = struct.unpack_from("<BBBBHHII", ico_data, 6 + 16 * i)
        size = w or 256
        assert (h or 256) == size
        with Image.open(io.BytesIO(ico_data[offset:offset + length])) as layer:
            actual_layer = layer.convert("RGBA")
        expected_layer = draw_mark(size, background=BLACK, foreground=WHITE,
                                   rounded=True, stroke_units=STROKE,
                                   figure_scale=scales[size])
        assert ImageChops.difference(actual_layer, expected_layer).getbbox() is None, size
    # v37 uses the same original geometry/stroke but higher supersampling for small favicon layers.
    matches_vector(ICONS / "dmate-site-v37-64.png", 64, background=BLACK,
                   foreground=WHITE, rounded=True, stroke_units=STROKE,
                   figure_scale=1.08, oversample_factor=16)
    check_ico(ICONS / "dmate-site-v37.ico", (16, 24, 32, 48, 64, 128, 256))
    ico_data_v37 = (ICONS / "dmate-site-v37.ico").read_bytes()
    for i in range(struct.unpack_from("<H", ico_data_v37, 4)[0]):
        w, h, _, _, _, _, length, offset = struct.unpack_from("<BBBBHHII", ico_data_v37, 6 + 16 * i)
        size = w or 256
        assert (h or 256) == size
        with Image.open(io.BytesIO(ico_data_v37[offset:offset + length])) as layer:
            actual_layer = layer.convert("RGBA")
        expected_layer = draw_mark(size, background=BLACK, foreground=WHITE,
                                   rounded=True, stroke_units=STROKE,
                                   figure_scale=scales[size], oversample_factor=16)
        assert ImageChops.difference(actual_layer, expected_layer).getbbox() is None, ("v37", size)

    # Bing desktop favicon has the unchanged 13-unit path width with
    # explicitly different stroke brightness and subtle interior face shades.
    # Every ICO layer must match freshly vector-rendered pixels, not an upscale.
    assert STROKE == 13
    assert len(BING_STROKES) == len(BING_FACETS) == len((0,1,2,3,4,5))
    assert len({rgb[:3] for rgb in BING_STROKES}) >= 4
    v38scales = {16:1.18, 24:1.14, 32:1.11, 48:1.09,
                 64:1.08, 128:1.06, 256:1.04}
    for tiny in (16,32,64):
        matches_vector(ICONS / f"dmate-site-v38-{tiny}.png", tiny,
                       background=BLACK, rounded=True, stroke_units=STROKE,
                       figure_scale=v38scales[tiny], oversample_factor=16,
                       facets=True, stroke_palette=BING_STROKES)
    check_ico(ICONS / "dmate-site-v38.ico", (16,24,32,48,64,128,256))
    ico_v38 = (ICONS / "dmate-site-v38.ico").read_bytes()
    for i in range(struct.unpack_from("<H", ico_v38, 4)[0]):
        w,h,_,_,_,_,length,offset = struct.unpack_from("<BBBBHHII", ico_v38, 6+16*i)
        size = w or 256
        assert (h or 256) == size
        with Image.open(io.BytesIO(ico_v38[offset:offset+length])) as layer:
            observed = layer.convert("RGBA")
        expected = draw_mark(size, background=BLACK, stroke_units=STROKE,
                             rounded=True, figure_scale=v38scales[size],
                             oversample_factor=16, facets=True,
                             stroke_palette=BING_STROKES)
        assert ImageChops.difference(observed, expected).getbbox() is None, ("v38", size)

    # v39 further improves 16/24/32px antialias brightness, not line thickness.
    for tiny in (16,32,64):
        matches_vector(ICONS / f"dmate-site-v39-{tiny}.png", tiny,
                       background=BLACK, rounded=True, stroke_units=STROKE,
                       figure_scale=v38scales[tiny], oversample_factor=16,
                       facets=True, stroke_palette=BING_STROKES)
    check_ico(ICONS / "dmate-site-v39.ico", (16,24,32,48,64,128,256))
    ico_v39 = (ICONS / "dmate-site-v39.ico").read_bytes()
    for i in range(struct.unpack_from("<H", ico_v39, 4)[0]):
        w,h,_,_,_,_,length,offset = struct.unpack_from("<BBBBHHII", ico_v39, 6+16*i)
        size = w or 256
        assert (h or 256) == size
        with Image.open(io.BytesIO(ico_v39[offset:offset+length])) as layer:
            observed = layer.convert("RGBA")
        expected = draw_mark(size, background=BLACK, stroke_units=STROKE,
                             rounded=True, figure_scale=v38scales[size],
                             oversample_factor=16, facets=True,
                             stroke_palette=BING_STROKES)
        assert ImageChops.difference(observed, expected).getbbox() is None, ("v39", size)

    # v40 must NEVER color a polygon face. All non-transparent RGB values
    # are grayscale: black background/interior with only bright white edges.
    v40_palette = [WHITE] * 6
    for tiny in (16,32,64):
        matches_vector(ICONS / f"dmate-site-v40-{tiny}.png", tiny,
                       background=BLACK, foreground=WHITE, rounded=True,
                       stroke_units=STROKE, figure_scale=v38scales[tiny],
                       oversample_factor=16, facets=True,
                       stroke_palette=v40_palette)
    check_ico(ICONS / "dmate-site-v40.ico", (16,24,32,48,64,128,256))
    v40_ico = (ICONS / "dmate-site-v40.ico").read_bytes()
    for i in range(struct.unpack_from("<H", v40_ico, 4)[0]):
        w,h,_,_,_,_,length,offset = struct.unpack_from("<BBBBHHII", v40_ico, 6+16*i)
        size=w or 256
        assert (h or 256)==size
        with Image.open(io.BytesIO(v40_ico[offset:offset+length])) as layer:
            observed=layer.convert("RGBA")
        expected=draw_mark(size, background=BLACK, foreground=WHITE,
                           stroke_units=STROKE, rounded=True,
                           figure_scale=v38scales[size], oversample_factor=16,
                           facets=True, stroke_palette=v40_palette)
        assert ImageChops.difference(observed, expected).getbbox() is None, ("v40",size)
    for file in [ICONS / f"dmate-site-v40-{s}.png" for s in (16,32,64)]:
        with Image.open(file) as im:
            rgb=im.convert("RGB")
            assert all(r==g==b for r,g,b in rgb.getdata()), f"Colored faces found in {file}"
            size=im.size[0]
            # At 16px, anti-aliased white wireframe lines cover nearby pixels;
            # validate a truly interior pixel only in the 64px master.
            if size == 64:
                assert max(rgb.getpixel((size//2,size//2))) <= 8, ("Center is not black", file)
    assert STROKE == 13

    # Search favicon must stay thin, while the legacy Safari rendering is unchanged.
    assert ImageChops.difference(rgba(ICONS / "dmate-site-v35-64.png").convert("RGB"),
                                 rgba(ICONS / "dmate-site-v34-64.png").convert("RGB")).getbbox() is not None
    assert (ICONS / "dmate-site-v34-64.png").read_bytes() == (
        ICONS / "dmate-safari-light-v32-64.png").read_bytes()
    assert rgba(ICONS / "favicon-32.png").getpixel((0, 0))[3] == 0

    check_ico(ICONS / "favicon.ico", (16, 32, 48, 64, 128))
    check_ico(ICONS / "windows-shortcut-black-v20.ico", (16, 24, 32, 48, 64, 128, 256))
    check_ico(DESKTOP / "icon.ico", (16, 24, 32, 48, 64, 128, 256))
    for obsolete in (
        "icon-192.png", "icon-192-app-v20.png", "icon-512-app-v20.png",
        "android-pwa-maskable-192-v24.png", "android-pwa-maskable-512-v24.png",
        "android-edge-512-v21.png", "android-fennec-512-v21.png",
    ):
        assert not (ICONS / obsolete).exists(), f"Obsolete web-PWA asset remains: {obsolete}"
    raw_icns = (DESKTOP / "icon.icns").read_bytes()
    assert raw_icns.startswith(b"icns")
    assert struct.unpack_from(">I", raw_icns, 4)[0] == len(raw_icns)

    html = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    # Search bots get the same root-level branded favicon irrespective of their UA platform.
    app_text = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "is_search_crawler=is_search_crawler," in app_text
    assert '@app.route("/robots.txt")' in app_text
    assert '@app.route("/sitemap.xml")' in app_text
    robots_text = (ROOT / "static/robots.txt").read_text(encoding="utf-8")
    sitemap_text = (ROOT / "static/sitemap.xml").read_text(encoding="utf-8")
    assert "User-agent: *" in robots_text
    assert "Sitemap: https://dmate.zeabur.app/sitemap.xml" in robots_text
    from xml.etree import ElementTree
    root_sitemap = ElementTree.fromstring(sitemap_text)
    assert root_sitemap.tag.endswith("urlset")
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    assert [node.text for node in root_sitemap.findall(".//sm:loc", namespace)] == ["https://dmate.zeabur.app/"]
    assert '<link rel="canonical" href="https://dmate.zeabur.app/">' in html
    assert 'send_static_file("icons/dmate-site-v40.ico")' in app_text
    assert 'send_static_file("icons/dmate-site-v40-64.png")' in app_text
    assert 'send_static_file("icons/dmate-site-v40-32.png")' in app_text
    assert 'send_static_file("icons/dmate-site-v40-16.png")' in app_text
    assert '{% if is_search_crawler %}' in html
    assert '<link rel="icon" type="image/x-icon" href="/favicon.ico?v=dmate-bing-v40-20261020">' in html
    for pixel in (16,32,64):
        assert f'<link rel="icon" type="image/png" sizes="{pixel}x{pixel}" href="/favicon-{pixel}.png?v=dmate-bing-v40-20261020">' in html
    assert '<link id="dmateSafariFavicon" rel="icon" type="image/png" sizes="64x64" href="/static/icons/dmate-site-v36-64.png?v=dmate-safari-v36-20261019">' in html
    assert 'document.head.appendChild(icon)' not in html
    assert 'dmate-safari-" + theme' not in html
    assert '<link id="dmateAppleTouchIcon" rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">' in html
    assert "dmate-win-tab-v21" in html
    print("PASS stable branded Safari/Bing favicon, iOS Safari touch icon, Android/Windows/desktop icons")


if __name__ == "__main__":
    main()
