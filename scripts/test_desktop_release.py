"""Exercise publication recovery without calling GitHub or changing releases."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import publish_desktop_release as publisher


def fingerprint(data):
    return len(data), hashlib.sha256(data).hexdigest()


class ReleaseNotesTests(unittest.TestCase):
    def test_migrates_legacy_notes_and_preserves_store_section(self):
        reviewed = "Desktop release notes."
        store = "\n\n### Microsoft Store\nExisting Store instructions.\n"
        merged = publisher.merge_release_notes(reviewed + store, reviewed)
        self.assertTrue(merged.endswith(store))
        self.assertEqual(merged.count(reviewed), 1)
        self.assertEqual(publisher.merge_release_notes(merged, reviewed), merged)

    def test_updates_only_owned_block(self):
        original = publisher.merge_release_notes("Other product notes.\n", "Old desktop notes.")
        original += "\nStore notes added later.\n"
        result = publisher.merge_release_notes(original, "New desktop notes.")
        self.assertTrue(result.startswith("Other product notes.\n"))
        self.assertTrue(result.endswith("Store notes added later.\n"))
        self.assertNotIn("Old desktop notes.", result)

    def test_rejects_broken_or_repeated_markers(self):
        for current in (publisher.NOTES_START, publisher.NOTES_END,
                        publisher.NOTES_END + publisher.NOTES_START,
                        publisher.NOTES_START * 2 + publisher.NOTES_END):
            with self.subTest(current=current), self.assertRaises(publisher.PublishError):
                publisher.merge_release_notes(current, "Reviewed notes.")


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        notes = self.root / "reviewed.md"
        notes.write_text("Reviewed desktop notes.\n", encoding="utf-8")
        self.desktop = b"verified desktop bytes"
        self.profile = b"verified profile bytes"
        self.files = {"desktop-test.bin": fingerprint(self.desktop)}
        self.assets = {"desktop-test.bin": self.desktop, "profile-test.bin": self.profile}
        self.body = "Reviewed desktop notes.\n\nMicrosoft Store notes must survive.\n"
        self.operations = []
        replacements = {
            "FILES": self.files,
            "IOS": ("profile-test.bin", *fingerprint(self.profile)),
            "OLD_FILES": ("old-desktop-test.bin",),
            "NOTES": notes,
        }
        for name, value in replacements.items():
            context = patch.object(publisher, name, value)
            context.start()
            self.addCleanup(context.stop)
        context = patch.dict("os.environ", {
            "GITHUB_REPOSITORY": publisher.REPO,
            "GITHUB_REF": "refs/heads/main", "GH_TOKEN": "test-only-placeholder",
        })
        context.start()
        self.addCleanup(context.stop)
        for name, callback in (("release", self.release), ("gh", self.gh),
                               ("verify_public", self.verify_public)):
            context = patch.object(publisher, name, side_effect=callback)
            context.start()
            self.addCleanup(context.stop)

    def release(self):
        return {"body": self.body, "assets": [{"name": name} for name in self.assets]}

    def verify_public(self, name, size, digest, directory):
        if name not in self.assets:
            raise publisher.PublishError("Attachment is missing")
        path = directory / name
        path.write_bytes(self.assets[name])
        publisher.verify_file(path, size, digest)

    def gh(self, *args):
        self.operations.append(args)
        self.assertEqual(args[0], "release")
        if args[1] == "upload":
            path = Path(args[3])
            self.assertNotIn(path.name, self.assets, "Existing files must never be overwritten")
            self.assets[path.name] = path.read_bytes()
        elif args[1] == "delete-asset":
            self.assets.pop(args[3])
        elif args[1] == "edit":
            self.assertNotIn("--title", args, "A desktop retry must preserve the release title")
            self.body = Path(args[args.index("--notes-file") + 1]).read_text()
        else:
            self.fail(f"Unexpected mutation: {args[1]}")
        return ""

    def test_retries_after_artifact_expiry_using_verified_public_bytes(self):
        with patch.object(publisher, "verified_builds", side_effect=AssertionError("Expired artifacts must not be required")):
            publisher.publish()
            self.assertIn("Microsoft Store notes must survive.", self.body)
            self.operations.clear()
            publisher.publish()
        self.assertEqual(self.operations, [], "An identical retry should make no mutations")

    def test_resumes_partial_upload_without_replacing_existing_assets(self):
        del self.assets["desktop-test.bin"]
        source = self.root / "desktop-test.bin"
        source.write_bytes(self.desktop)
        with patch.object(publisher, "verified_builds", return_value={source.name: source}) as builds:
            publisher.publish()
        self.assertEqual(builds.call_args.args[1], [source.name])
        self.assertEqual(self.assets[source.name], self.desktop)
        self.assertEqual(sum(op[:2] == ("release", "upload") and Path(op[3]).name == source.name
                             for op in self.operations), 1)

    def test_changed_public_bytes_stop_before_any_mutation(self):
        self.assets["desktop-test.bin"] = b"unexpected binary"
        before = copy.deepcopy(self.assets)
        with self.assertRaises(publisher.PublishError):
            publisher.publish()
        self.assertEqual(self.operations, [])
        self.assertEqual(self.assets, before)

    def test_missing_source_artifact_stops_without_partial_publication(self):
        del self.assets["desktop-test.bin"]
        with patch.object(publisher, "verified_builds", side_effect=publisher.PublishError("Missing verified artifact")):
            with self.assertRaises(publisher.PublishError):
                publisher.publish()
        self.assertEqual(self.operations, [])

    def test_corrupt_existing_checksum_stops_before_upload_or_cleanup(self):
        self.assets["SHA256SUMS.txt"] = b"unexpected checksums"
        self.assets["old-desktop-test.bin"] = b"old bytes"
        with self.assertRaises(publisher.PublishError):
            publisher.publish()
        self.assertEqual(self.operations, [])

    def test_broken_note_markers_stop_before_cleanup(self):
        self.body = publisher.NOTES_START
        self.assets["old-desktop-test.bin"] = b"old bytes"
        with self.assertRaises(publisher.PublishError):
            publisher.publish()
        self.assertEqual(self.operations, [])


if __name__ == "__main__":
    unittest.main()
