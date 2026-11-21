#!/usr/bin/env python3
"""Offline checks for Store bundle verification and safe publication retries."""
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

from windows_store_release import (BEGIN, END, REPORT, SUPPORT_FILES, VerificationError,
                                   digest_file, merge_notes, publication_plan, publish,
                                   validate_source_run, verify_bundle, verify_directory)


class StoreReleaseTests(unittest.TestCase):
    def test_notes_update_only_owned_block_and_repeat_is_noop(self):
        body = f"User introduction\n\n{BEGIN}\nold\n{END}\n\n### Desktop\nkeep me\n"
        updated = merge_notes(body, "### Store\nnew")
        self.assertEqual(updated, f"User introduction\n\n{BEGIN}\n### Store\nnew\n{END}\n\n### Desktop\nkeep me\n")
        self.assertEqual(merge_notes(updated, "### Store\nnew"), updated)

    def test_notes_adopt_only_exact_legacy_section(self):
        content = "### Microsoft Store submission packages\n\nExisting generated text."
        body = "Prefix\n\n" + content + "\n\n### Other\nKeep\n"
        updated = merge_notes(body, content)
        self.assertEqual(updated.count(content), 1)
        self.assertIn(BEGIN, updated)
        self.assertTrue(updated.endswith("\n\n### Other\nKeep\n"))

    def test_notes_reject_broken_or_duplicate_markers(self):
        for body in (BEGIN, END, END + BEGIN, BEGIN + END + BEGIN + END):
            with self.subTest(body=body), self.assertRaises(VerificationError):
                merge_notes(body, "content")

    def test_identical_existing_asset_is_verified_and_skipped(self):
        item = {"name": "package.msixbundle", "bytes": 20, "sha256": "a" * 64}
        with patch("windows_store_release.verify_remote") as remote:
            result = publication_plan(None, {"assets": [{"name": item["name"], "size": 20}]}, [item])
        self.assertEqual(result, [])
        remote.assert_called_once_with(None, item)

    def test_same_name_different_size_stops_before_upload_plan(self):
        files = [{"name": "missing.msixbundle", "bytes": 10}, {"name": "existing.msixbundle", "bytes": 20}]
        with self.assertRaises(VerificationError):
            publication_plan(None, {"assets": [{"name": "existing.msixbundle", "size": 21}]}, files)

    def test_same_size_different_bytes_stops(self):
        item = {"name": "package.msixbundle", "bytes": 20, "sha256": "a" * 64}
        with patch("windows_store_release.verify_remote", side_effect=VerificationError("different bytes")):
            with self.assertRaises(VerificationError):
                publication_plan(None, {"assets": [{"name": item["name"], "size": 20}]}, [item])

    def test_partial_upload_plans_only_missing_files(self):
        files = [{"name": "first.msixbundle", "bytes": 20}, {"name": "second.appxbundle", "bytes": 30}]
        with patch("windows_store_release.verify_remote"):
            result = publication_plan(None, {"assets": [{"name": "first.msixbundle", "size": 20}]}, files)
        self.assertEqual(result, files[1:])

    def source_run(self):
        return {"id": 42, "repository": {"full_name": "example/app"},
                "head_repository": {"full_name": "example/app"},
                "path": ".github/workflows/build-windows-store.yml", "head_branch": "main",
                "head_sha": "a" * 40, "event": "workflow_dispatch", "status": "completed", "conclusion": "failure"}

    def test_failed_publication_run_can_supply_original_artifact(self):
        validate_source_run(self.source_run(), "example/app", "42", "a" * 40)

    def test_unreviewed_retry_sources_are_rejected(self):
        for field, value in (("head_sha", "b" * 40), ("head_branch", "feature"),
                             ("path", "another-workflow.yml"), ("event", "pull_request"),
                             ("status", "in_progress"), ("conclusion", "cancelled"),
                             ("head_repository", None), ("head_repository", {"full_name": "fork/app"}),
                             ("repository", None)):
            run = self.source_run()
            run[field] = value
            with self.subTest(field=field), self.assertRaises(VerificationError):
                validate_source_run(run, "example/app", "42", "a" * 40)

    def bundle(self, path, *, outer_version="1.2.3.0", inner_version="1.2.3.0", executable=b"reviewed executable"):
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as archive:
            archive.writestr("AppxManifest.xml", f'<Package><Identity Name="DMate.DMate" Publisher="CN=test" Version="{inner_version}" ProcessorArchitecture="x64"/></Package>')
            archive.writestr("App/dmate-desktop.exe", executable)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("AppxMetadata/AppxBundleManifest.xml", f'<Bundle><Identity Name="DMate.DMate" Publisher="CN=test" Version="{outer_version}"/><Packages><Package Type="application" Architecture="x64" Version="1.2.3.0" FileName="app.msix"/></Packages></Bundle>')
            archive.writestr("app.msix", inner.getvalue())

    def test_bundle_checks_both_versions_and_real_executable_bytes(self):
        digest = hashlib.sha256(b"reviewed executable").hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "app.msixbundle"
            self.bundle(path)
            verify_bundle(path, "1.2.3.0", "CN=test", digest)
            for values in ({"outer_version": "2026.1121.1500.0"},
                           {"inner_version": "1.2.2.0"}, {"executable": b"changed"}):
                self.bundle(path, **values)
                with self.subTest(values=values), self.assertRaises(VerificationError):
                    verify_bundle(path, "1.2.3.0", "CN=test", digest)

    def artifact(self, directory):
        bundle = directory / "app.msixbundle"
        self.bundle(bundle)
        for name in SUPPORT_FILES:
            (directory / name).write_text("supporting material\n", encoding="utf-8")
        files = [{"name": path.name, "bytes": path.stat().st_size, "sha256": digest_file(path)}
                 for path in directory.iterdir()]
        next(item for item in files if item["name"] == bundle.name).update(
            package_version="1.2.3.0", bundle_version="1.2.3.0")
        args = SimpleNamespace(directory=directory, package=["app.msixbundle=1.2.3.0"],
                               source_hash="c" * 64, app_hash=hashlib.sha256(b"reviewed executable").hexdigest(),
                               publisher="CN=test", runtime_version="reviewed-runtime")
        report = {"schema_version": 2, "status": "package_integrity_passed",
                  "source_installer_sha256": args.source_hash, "source_executable_sha256": args.app_hash,
                  "publisher": args.publisher, "runtime_version": args.runtime_version, "files": files}
        (directory / REPORT).write_text(json.dumps(report), encoding="utf-8")
        return args, report

    def test_artifact_checks_report_hashes_and_rejects_old_unverified_reports(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            args, report = self.artifact(directory)
            self.assertEqual({item["name"] for item in verify_directory(args)},
                             {"app.msixbundle", REPORT} | SUPPORT_FILES)
            report["status"] = "passed"
            (directory / REPORT).write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaises(VerificationError):
                verify_directory(args)

    def test_unexpected_file_or_modified_bytes_stops_artifact_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            args, _ = self.artifact(directory)
            extra = directory / "not-reviewed.txt"
            extra.write_text("extra", encoding="utf-8")
            with self.assertRaises(VerificationError):
                verify_directory(args)
            extra.unlink()
            (directory / next(iter(SUPPORT_FILES))).write_text("changed", encoding="utf-8")
            with self.assertRaises(VerificationError):
                verify_directory(args)

    def test_publication_requires_actual_completed_install_smoke(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            args, report = self.artifact(directory)
            with self.assertRaises(VerificationError):
                verify_directory(args, require_install=True)
            report.update(installation_test="passed", upgrade_test="passed", install_smoke={
                "status": "passed", "cleanup": "passed", "runner": "github-hosted", "packages": [{
                    "name": "app.msixbundle", "version": "1.2.3.0", "window_observed": True,
                    "bundled_webview_observed": True, "observed_seconds": 10,
                }]})
            (directory / REPORT).write_text(json.dumps(report), encoding="utf-8")
            verify_directory(args, require_install=True)
            report["install_smoke"]["packages"][0]["bundled_webview_observed"] = False
            (directory / REPORT).write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaises(VerificationError):
                verify_directory(args, require_install=True)

    def test_existing_byte_conflict_prevents_every_remote_mutation(self):
        args = SimpleNamespace(directory=Path("unused"))
        file = {"name": "bundle", "bytes": 5}
        with tempfile.TemporaryDirectory() as temporary:
            args.notes_file = Path(temporary) / "notes.md"
            args.notes_file.write_text("### Store\nnotes", encoding="utf-8")
            with (patch("windows_store_release.verify_directory", return_value=[file]),
                  patch("windows_store_release.release", return_value={"assets": [{"name": "bundle", "size": 6}]}),
                  patch("windows_store_release.gh") as remote):
                with self.assertRaises(VerificationError):
                    publish(args)
                remote.assert_not_called()

    def test_all_published_and_matching_notes_is_remote_noop(self):
        args = SimpleNamespace(directory=Path("unused"))
        with tempfile.TemporaryDirectory() as temporary:
            args.notes_file = Path(temporary) / "notes.md"
            args.notes_file.write_text("### Store\nnotes", encoding="utf-8")
            body = merge_notes("Other content", "### Store\nnotes")
            with (patch("windows_store_release.verify_directory", return_value=[]),
                  patch("windows_store_release.release", return_value={"assets": [], "body": body}),
                  patch("windows_store_release.gh") as remote):
                publish(args)
                remote.assert_not_called()


if __name__ == "__main__":
    unittest.main()
