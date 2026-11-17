"""Submission ZIPs preserve contents and ignore incidental checkout metadata."""
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock
import zipfile

from package_firefox_zip import package_directory, ZIP_DATE


class FirefoxZipTests(unittest.TestCase):
    def test_repeated_checkouts_produce_identical_archives(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for number, names in enumerate([["z.js", "nested/中文.txt", "a.sh"], ["a.sh", "nested/中文.txt", "z.js"]]):
                source = root / str(number)
                for name in names:
                    path = source / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(name + "\n", encoding="utf-8")
                    path.chmod(0o755 if name.endswith(".sh") else 0o600 if number else 0o644)
                    os.utime(path, (1000000000 + number * 1000000, 1000000000 + number * 1000000))
                package_directory(source, root / f"{number}.zip")
            self.assertEqual((root / "0.zip").read_bytes(), (root / "1.zip").read_bytes())
            with zipfile.ZipFile(root / "0.zip") as archive:
                self.assertEqual(archive.namelist(), ["a.sh", "nested/中文.txt", "z.js"])
                for info in archive.infolist():
                    self.assertEqual(info.date_time, ZIP_DATE)
                    self.assertEqual(archive.read(info).decode(), info.filename + "\n")
                    self.assertEqual(stat.S_IMODE(info.external_attr >> 16), 0o755 if info.filename.endswith(".sh") else 0o644)

    def test_content_changes_update_the_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "manifest.json").write_text('{"version":"1.0.4"}')
            package_directory(source, root / "addon.zip")
            previous = (root / "addon.zip").read_bytes()
            (source / "manifest.json").write_text('{"version":"1.0.5"}')
            package_directory(source, root / "addon.zip")
            self.assertNotEqual(previous, (root / "addon.zip").read_bytes())
            with zipfile.ZipFile(root / "addon.zip") as archive:
                self.assertIn(b"1.0.5", archive.read("manifest.json"))

    def test_unsafe_sources_and_self_inclusion_preserve_previous_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            output = root / "addon.zip"
            output.write_bytes(b"previous valid package")
            outside = root / "private.txt"
            outside.write_text("outside source")
            link = source / "outside.txt"
            link.symlink_to(outside)
            with self.assertRaises(ValueError):
                package_directory(source, output)
            self.assertEqual(output.read_bytes(), b"previous valid package")
            link.unlink()
            with self.assertRaises(ValueError):
                package_directory(source, source / "self.zip")
            (source / "ambiguous\\name.txt").write_text("portable paths only")
            with self.assertRaises(ValueError):
                package_directory(source, output)
            self.assertEqual(output.read_bytes(), b"previous valid package")

    def test_interrupted_read_does_not_publish_partial_package(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "manifest.json").write_text("{}")
            output = root / "addon.zip"
            output.write_bytes(b"previous valid package")
            with mock.patch.object(Path, "read_bytes", side_effect=OSError("unreadable input")):
                with self.assertRaises(OSError):
                    package_directory(source, output)
            self.assertEqual(output.read_bytes(), b"previous valid package")
            self.assertEqual(list(root.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
