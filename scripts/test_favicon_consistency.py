#!/usr/bin/env python3
"""Check browser-tab artwork through the real Flask routes, without a server.

Run from any directory: .venv/bin/python scripts/test_favicon_consistency.py
The hashes preserve the original opaque, black tile with white line artwork.
Application/Home Screen icons are deliberately a separate resource family.
"""

import hashlib
import io
import struct
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402 -- exercise the production Flask application


BASE = "dmate-favicon-original-v56"
ICONS = ROOT / "static" / "icons"
ORIGINAL_HASHES = {
    16: "4d9f1c1a1b2d0d78768a0279a0047394955c6ebc8f2a1838ebcaa1f6554a7221",
    32: "4b32e7a6f9c86565188c3f453d3cfad572361df959d770e2b56c0dd3cb6577b8",
    48: "0109e5533064a20a71e39400037ae94b4f1b70840acb0f92db91ad6b10c4da2c",
    64: "1e3bf13d358cfa1b1a4943609a9a9bdc1f2b1d53f96870582c7fb22df65f876e",
    96: "45671e657d279d32ea9277c3fa2c42b76d8e9621f663fa1122ee5667c9223a64",
    128: "ce276d9bce8dc8a3b981357995b9102b430f435ba9b587edc13299e7c3e0f24b",
    192: "00f1e8df7312f7866a3210e21679bf09527b393233485936132aa162330ebaf6",
}
ICO_HASH = "a8cbc965c68b91e79eac11adc65b9595dfc5c13346d403ef74c9b49ef60cd009"

WINDOWS = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
ANDROID = "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
IOS = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
LINUX = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
USER_AGENTS = {
    "no user agent": "",
    "Windows Chrome": WINDOWS,
    "Windows Edge": WINDOWS + " Edg/131.0.2903.70",
    "Windows Firefox": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "macOS Safari": MAC,
    "macOS Chrome": WINDOWS.replace("Windows NT 10.0; Win64; x64", "Macintosh; Intel Mac OS X 14_7"),
    "macOS Firefox": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.7; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Linux Chrome": LINUX,
    "Linux Firefox": "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "iPhone Safari": IOS,
    "iPad Safari": MAC + " Mobile/15E148",
    "iPhone Chrome": IOS.replace("Version/18.0", "CriOS/131.0.6778.73"),
    "Android Chrome": ANDROID,
    "Android Edge": ANDROID + " EdgA/131.0.2903.68",
    "Android Firefox": "Mozilla/5.0 (Android 15; Mobile; rv:133.0) Gecko/133.0 Firefox/133.0",
    "native Android": ANDROID + " DMateAndroid/1.0.3",
    "native desktop": "DMateDesktop/1.0.2",
    "native Windows": WINDOWS + " DMateDesktop/1.0.2",
    "native macOS": MAC + " DMateDesktop/1.0.2",
    "native Linux": LINUX + " DMateDesktop/1.0.2",
    "native iOS": IOS + " DMateNative/1.0.0",
    "Googlebot": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Google mobile": ANDROID + " (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Google Favicon": "Google Favicon",
    "GoogleOther": "GoogleOther/1.0",
    "Google inspection": "Google-InspectionTool/1.0",
    "Bingbot": "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    "Bing preview": "Mozilla/5.0 (Windows NT 10.0) BingPreview/1.0b",
    "Bing advertising": "adidxbot/2.0",
    "Microsoft preview": "MicrosoftPreview/2.0",
    "Microsoft bot": "msnbot/2.0b",
}


class HeadIcons(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.in_head = False
        self.icons = []
        self.apple_icons = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "head":
            self.in_head = True
        if not self.in_head or tag != "link":
            return
        attrs = dict(attrs)
        rel = set(attrs.get("rel", "").lower().split())
        if "icon" in rel:
            self.icons.append(attrs)
        if "apple-touch-icon" in rel:
            self.apple_icons.append(attrs)

    def handle_endtag(self, tag):
        if tag == "head":
            self.in_head = False


class FaviconConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config.update(TESTING=True)
        cls.client = app.test_client()
        cls.canonical = {
            size: (ICONS / f"{BASE}-{size}.png").read_bytes()
            for size in ORIGINAL_HASHES
        }
        cls.ico = (ICONS / f"{BASE}.ico").read_bytes()

    def response(self, path, user_agent):
        response = self.client.get(path, headers={"User-Agent": user_agent})
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200, path)
        return response

    def assert_icon_links(self, head):
        self.assertGreaterEqual(len(head.icons), 3)
        shortcut = [icon for icon in head.icons if "shortcut" in icon["rel"].split()]
        self.assertEqual(len(shortcut), 1)
        self.assertEqual(shortcut[0]["href"], f"/static/icons/{BASE}.ico")
        sizes = set()
        for icon in head.icons:
            self.assertNotIn("media", icon, "tab artwork must not change with system theme")
            self.assertNotIn("color", icon, "tab artwork must not be tinted by a mask icon")
            path = urlsplit(icon["href"]).path
            if path.endswith(".ico"):
                self.assertEqual(path, f"/static/icons/{BASE}.ico")
                self.assertIn(icon.get("type"), ("image/x-icon", "image/vnd.microsoft.icon"))
                continue
            self.assertEqual(icon.get("type"), "image/png")
            size = int(icon.get("sizes", "0x0").split("x")[0])
            self.assertIn(size, self.canonical)
            self.assertEqual(icon["sizes"], f"{size}x{size}")
            self.assertEqual(path, f"/static/icons/{BASE}-{size}.png")
            sizes.add(size)
        self.assertIn(32, sizes, "a native small PNG is required for browser tabs")

    def test_original_png_artwork_is_opaque_black_with_white_lines(self):
        for size, content in self.canonical.items():
            with self.subTest(size=size):
                self.assertEqual(hashlib.sha256(content).hexdigest(), ORIGINAL_HASHES[size])
                image = Image.open(io.BytesIO(content)).convert("RGBA")
                self.assertEqual(image.size, (size, size))
                self.assertEqual(image.getchannel("A").getextrema(), (255, 255))
                pixels = list(image.getdata())
                self.assertTrue(all(r == g == b for r, g, b, _ in pixels))
                # Native 16px antialiasing spreads the white strokes into nearby
                # pixels; the original still retains a substantial black tile.
                self.assertGreater(sum(r == 0 for r, _, _, _ in pixels), size * size // 4)
                self.assertTrue(any(r == 255 for r, _, _, _ in pixels))
                self.assertTrue(all(image.getpixel(point) == (0, 0, 0, 255) for point in (
                    (0, 0), (size - 1, 0), (0, size - 1), (size - 1, size - 1)
                )))

    def test_ico_keeps_the_exact_native_16_and_32_png_frames(self):
        self.assertEqual(hashlib.sha256(self.ico).hexdigest(), ICO_HASH)
        reserved, image_type, count = struct.unpack_from("<HHH", self.ico)
        self.assertEqual((reserved, image_type), (0, 1))
        frames = {}
        for index in range(count):
            width, height, _, _, _, _, length, offset = struct.unpack_from(
                "<BBBBHHII", self.ico, 6 + index * 16
            )
            self.assertLessEqual(offset + length, len(self.ico))
            frames[(width or 256, height or 256)] = self.ico[offset:offset + length]
        for size in (16, 32):
            self.assertEqual(frames[(size, size)], self.canonical[size])

    def test_all_platforms_and_indexers_get_identical_online_and_offline_head(self):
        baseline = None
        for name, user_agent in USER_AGENTS.items():
            with self.subTest(user_agent=name):
                online = HeadIcons(self.response("/", user_agent).get_data(as_text=True))
                offline = HeadIcons(self.response("/offline", user_agent).get_data(as_text=True))
                self.assert_icon_links(online)
                self.assert_icon_links(offline)
                baseline = online.icons if baseline is None else baseline
                self.assertEqual(online.icons, baseline)
                self.assertEqual(offline.icons, baseline)
                # Browser-tab unification must not replace the application icon.
                for head in (online, offline):
                    self.assertEqual(len(head.apple_icons), 1)
                    self.assertEqual(head.apple_icons[0]["href"], "/static/icons/dmate-app-v52-180.png")

    def test_root_fallback_routes_have_the_same_bytes_for_every_user_agent(self):
        routes = {"/favicon.ico": (self.ico, "image/x-icon")}
        routes.update({
            f"/favicon-{size}.png": (self.canonical[size], "image/png")
            for size in (16, 32, 48, 64, 96, 192)
        })
        routes["/favicon.png"] = (self.canonical[192], "image/png")
        for name, user_agent in USER_AGENTS.items():
            for path, (expected, mime_type) in routes.items():
                with self.subTest(user_agent=name, path=path):
                    response = self.response(path, user_agent)
                    self.assertEqual(response.get_data(), expected)
                    self.assertEqual(response.mimetype, mime_type)
                    self.assertNotIn("User-Agent", response.vary)

    def test_declared_static_resources_also_serve_the_canonical_bytes(self):
        head = HeadIcons(self.response("/", WINDOWS).get_data(as_text=True))
        self.assert_icon_links(head)
        paths = {icon["href"] for icon in head.icons}
        # Verify every supplied native PNG, including sizes not selected by head.
        paths.update(f"/static/icons/{BASE}-{size}.png" for size in self.canonical)
        for name, user_agent in USER_AGENTS.items():
            for path in sorted(paths):
                with self.subTest(user_agent=name, path=path):
                    if urlsplit(path).path.endswith(".ico"):
                        expected = self.ico
                    else:
                        size = int(urlsplit(path).path.rsplit("-", 1)[1].split(".")[0])
                        expected = self.canonical[size]
                    self.assertEqual(self.response(path, user_agent).get_data(), expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
