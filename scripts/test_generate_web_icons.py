"""Exercise the real icon CLI in isolated build roots, never the source tree."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


GENERATOR = Path(__file__).with_name("generate_icons.py")


class GenerateWebIconsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="dmate-web-icons-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.root = Path(cls.directory.name)
        cls.results = {}
        for name, args in (("all", []), ("web", ["--web-only"])):
            root = cls.root / name
            script = root / "scripts" / GENERATOR.name
            script.parent.mkdir(parents=True)
            shutil.copyfile(GENERATOR, script)
            result = subprocess.run([sys.executable, str(script), *args],
                                    check=True, capture_output=True, text=True)
            cls.results[name] = json.loads(result.stdout)

    def test_web_assets_match_default_generation_byte_for_byte(self):
        def assets(mode):
            root = self.root / mode / "static" / "icons"
            return {file.relative_to(root).as_posix(): file.read_bytes()
                    for file in root.rglob("*") if file.is_file()}
        all_assets, web_assets = assets("all"), assets("web")
        self.assertEqual(len(web_assets), 62)
        self.assertEqual(set(web_assets), set(all_assets))
        for name, data in all_assets.items():
            with self.subTest(asset=name):
                self.assertEqual(web_assets[name], data)
                self.assertEqual(data, (GENERATOR.parents[1] / "static" / "icons" / name).read_bytes())

    def test_web_build_has_no_native_outputs(self):
        root = self.root / "web"
        self.assertFalse((root / "android").exists())
        self.assertFalse((root / "desktop").exists())
        self.assertEqual(self.results["web"]["formats"], ["SVG", "PNG", "ICO"])
        self.assertNotIn("windows_ico_sizes", self.results["web"])
        self.assertNotIn("android_adaptive_safe_circle_dp", self.results["web"])

    def test_default_cli_retains_native_platforms(self):
        root = self.root / "all"
        icons = root / "desktop" / "src-tauri" / "icons"
        self.assertTrue((icons / "icon-64.png").is_file())
        self.assertTrue((icons / "icon.ico").is_file())
        self.assertTrue((icons / "icon.icns").is_file())
        android = root / "android" / "app" / "src" / "main" / "res"
        self.assertTrue((android / "drawable" / "dmate_foreground.xml").is_file())
        self.assertTrue((android / "mipmap-mdpi" / "ic_launcher.png").is_file())
        self.assertEqual(self.results["all"]["formats"],
                         ["SVG", "PNG", "ICO", "ICNS", "Android VectorDrawable"])
        self.assertEqual(self.results["all"]["android_adaptive_safe_circle_dp"], 66)


if __name__ == "__main__":
    unittest.main()
