#!/usr/bin/env python3
"""Preserve the favicon platform branches and artwork from a65f873.

Run from any directory: .venv/bin/python scripts/test_favicon_consistency.py
This checks the original differences; it does not require unified artwork.
"""

import hashlib
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import app  # noqa: E402 -- exercise the actual Flask routes

ICONS = ROOT / "static" / "icons"
# SHA256 values were read from git a65f873, never regenerated from artwork.
ORIGINAL_HASHES = {
    'dmate-tab-black-v52.ico': '8a6e2faf72711a91a4e6c8b0c6e510bc150564f6eba72ca5126a08452127a796',
    'dmate-tab-black-v52-64.png': '12c859918508d87e87b9fade10910177cc6d5c5a16dc2173cec53411e409c314',
    'dmate-tab-black-v52.svg': 'ded395407bce4e598248142a30a198e57af0e05d4132afced2c6ea4ac715e14d',
    'dmate-tab-white-v52.ico': '582d0d96ab94f0a630335ae031182f922b3682cf0e935aec9b7df717906ba1b6',
    'dmate-tab-white-v52-32.png': '09d4ee77289f53010977e484bb67abd66e9f360ac4eda8d08eabfea54ee961d1',
    'dmate-tab-white-v52.svg': '4f1e237ff0a693279a8a8117e14057d0c1f4792568c449fac723feda3fe591e2',
    'dmate-app-v52.ico': '766774641c25e69c38af71e16595d2c81a52620238e889dd5e5f13b7bb254ee9',
    'dmate-app-v52-32.png': '61eda6940ed062f6c0442affd8df8487ceb48392ef2187b896b7e6af11fdab9f',
    'dmate-app-v52-64.png': '09d22d5e7050108593793ddd3e71606159fc9aabc8e0d7182bdc4550a816fd08',
    'dmate-app-v52-180.png': '94abf6b45325fd590b5eb992350b3265d3a8a597e70c308dabe936e165260bfd',
    'dmate-app-v52-192.png': '21b38a2a6721c52d1f024295ff927bfe83fb0cee15f6cadfa79b99d413f99cab',
    'dmate-search-v53.ico': 'c136b3d8fa913b1df783f0a328ea01a34b6f3072dd01f96bdc70f3200136aa8f',
    'dmate-search-v53-16.png': '0a8ab1b9bb419e610d38c5fb5dffca328c6c0c66b42e3990365e446a8834d756',
    'dmate-search-v53-32.png': '454d47b37d59123e0bf64042221ec49ed0ddbb28ac447f603cacd7964cacda22',
    'dmate-search-v53-48.png': '5fa9743ee2eb8038309526538dbb3e5ce83c3cd651492900ca58bc74733ab7e3',
    'dmate-search-v53-64.png': 'e28e7615e19a1b6351a5cd494c4664b92bdf4223a2c3f6bcb9648e2aca54a67e',
    'dmate-search-v53-96.png': 'd618149c04a2104366ab9dcfa1828678e0e02e96d410d689ca2ad419d44b8b82',
    'dmate-search-v53-192.png': '8ced80983cdb8edadf576d566ce106e6362bbecc19eec3c892020bb866aa4379',
    'dmate-bing-v55.ico': 'a8cbc965c68b91e79eac11adc65b9595dfc5c13346d403ef74c9b49ef60cd009',
    'dmate-bing-v55-16.png': '4d9f1c1a1b2d0d78768a0279a0047394955c6ebc8f2a1838ebcaa1f6554a7221',
    'dmate-bing-v55-32.png': '4b32e7a6f9c86565188c3f453d3cfad572361df959d770e2b56c0dd3cb6577b8',
    'dmate-bing-v55-48.png': '0109e5533064a20a71e39400037ae94b4f1b70840acb0f92db91ad6b10c4da2c',
    'dmate-bing-v55-64.png': '1e3bf13d358cfa1b1a4943609a9a9bdc1f2b1d53f96870582c7fb22df65f876e',
    'dmate-bing-v55-96.png': '45671e657d279d32ea9277c3fa2c42b76d8e9621f663fa1122ee5667c9223a64',
    'dmate-bing-v55-192.png': '00f1e8df7312f7866a3210e21679bf09527b393233485936132aa162330ebaf6',
}

WINDOWS = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.2903.70"
MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
ANDROID = "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
LINUX = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def declared(base, png_sizes=(), svg=False, ico=True):
    links = []
    if ico:
        links.append((f"/static/icons/{base}.ico", "image/x-icon", None))
    links.extend((f"/static/icons/{base}-{size}.png", "image/png", f"{size}x{size}")
                 for size in png_sizes)
    if svg:
        links.append((f"/static/icons/{base}.svg", "image/svg+xml", "any"))
    return links


APP_TOUCH = "/static/icons/dmate-app-v52-180.png"
# Eight representative original branches, including both crawler families.
CASES = {
    "macOS Safari": (MAC, declared("dmate-tab-black-v52", [64], svg=True), APP_TOUCH),
    "Windows Edge": (WINDOWS, declared("dmate-tab-white-v52", [32], svg=True), APP_TOUCH),
    "desktop Firefox": ("Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
                        declared("dmate-tab-white-v52", [32], svg=True), APP_TOUCH),
    "Android browser": (ANDROID, declared("dmate-app-v52", [32, 192], ico=False), APP_TOUCH),
    "other browser": (LINUX, declared("dmate-app-v52", [64]), APP_TOUCH),
    "native desktop": ("DMateDesktop/1.0.2", declared("dmate-app-v52", [64]), APP_TOUCH),
    "Google crawler": ("Googlebot/2.1", declared("dmate-search-v53", [32, 48, 96, 192]),
                       "/static/icons/dmate-search-v53-192.png"),
    "Bing crawler": ("bingbot/2.0", declared("dmate-bing-v55", [32, 48, 96, 192]),
                     "/static/icons/dmate-bing-v55-192.png"),
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
        if self.in_head and tag == "link":
            attrs = dict(attrs)
            rel = set(attrs.get("rel", "").lower().split())
            if "icon" in rel:
                self.icons.append((attrs.get("href"), attrs.get("type"), attrs.get("sizes")))
            if "apple-touch-icon" in rel:
                self.apple_icons.append(attrs.get("href"))

    def handle_endtag(self, tag):
        if tag == "head":
            self.in_head = False


class OriginalPlatformFaviconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config.update(TESTING=True)
        cls.client = app.test_client()
        cls.assets = {name: (ICONS / name).read_bytes() for name in ORIGINAL_HASHES}

    def response(self, path, user_agent):
        response = self.client.get(path, headers={"User-Agent": user_agent})
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200, path)
        return response

    def test_original_asset_bytes_are_unchanged(self):
        for name, content in self.assets.items():
            with self.subTest(asset=name):
                self.assertEqual(hashlib.sha256(content).hexdigest(), ORIGINAL_HASHES[name])
                self.assertEqual(self.response("/static/icons/" + name, WINDOWS).get_data(), content)

    def test_online_keeps_original_platform_icon_branches(self):
        for name, (user_agent, icons, apple_icon) in CASES.items():
            with self.subTest(platform=name):
                head = HeadIcons(self.response("/", user_agent).get_data(as_text=True))
                self.assertEqual(head.icons, icons)
                self.assertEqual(head.apple_icons, [apple_icon])

    def test_offline_keeps_its_original_undeclared_favicon(self):
        for name, (user_agent, _, _) in CASES.items():
            with self.subTest(platform=name):
                head = HeadIcons(self.response("/offline", user_agent).get_data(as_text=True))
                self.assertEqual(head.icons, [])
                self.assertEqual(head.apple_icons, [])

    def test_root_fallback_keeps_original_google_and_shared_bing_artwork(self):
        routes = {"/favicon.ico": (".ico", "image/x-icon")}
        routes.update({f"/favicon-{size}.png": (f"-{size}.png", "image/png")
                       for size in (16, 32, 48, 64, 96, 192)})
        routes.update({path: ("-192.png", "image/png") for path in (
            "/favicon.png", "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png")})
        for name, (user_agent, _, _) in CASES.items():
            base = "dmate-search-v53" if name == "Google crawler" else "dmate-bing-v55"
            for path, (suffix, mime_type) in routes.items():
                with self.subTest(platform=name, path=path):
                    response = self.response(path, user_agent)
                    self.assertEqual(response.get_data(), self.assets[base + suffix])
                    self.assertEqual(response.mimetype, mime_type)
                    self.assertIn("User-Agent", response.vary)


if __name__ == "__main__":
    unittest.main(verbosity=2)
