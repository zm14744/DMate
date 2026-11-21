#!/usr/bin/env python3
"""Exercise release decisions without GitHub credentials or Store mutations."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import check_snap_store_channel as store
import verify_release_checks as checks


SHA = "a" * 40


def run(identifier=10, path=checks.BUILD_WORKFLOW, **changes):
    result = {"id": identifier, "path": path, "head_branch": "main", "head_sha": SHA,
              "repository": {"full_name": checks.REPOSITORY},
              "head_repository": {"full_name": checks.REPOSITORY},
              "event": "workflow_dispatch", "status": "completed", "conclusion": "success"}
    result.update(changes)
    return result


class ReleaseChecksTest(unittest.TestCase):
    def test_latest_failure_cannot_be_hidden_by_an_older_success(self):
        path = checks.REQUIRED_WORKFLOWS[0]
        for status, conclusion in (("completed", "failure"), ("in_progress", None),
                                   ("completed", "cancelled"), ("queued", None)):
            with self.subTest(status=status, conclusion=conclusion), self.assertRaises(checks.VerificationError):
                checks.require_latest_success([
                    run(1, path), run(2, path, status=status, conclusion=conclusion)], path, SHA)

    def test_unrelated_workflow_commit_and_fork_success_do_not_satisfy_gate(self):
        path = checks.REQUIRED_WORKFLOWS[0]
        candidates = [run(1, checks.REQUIRED_WORKFLOWS[1]), run(2, path, head_sha="b" * 40),
                      run(3, path, head_repository={"full_name": "other/DMate"}),
                      run(4, path, event="pull_request")]
        with self.assertRaises(checks.VerificationError):
            checks.require_latest_success(candidates, path, SHA)

    def test_trusted_tag_run_can_test_the_identical_source_commit(self):
        path = checks.REQUIRED_WORKFLOWS[0]
        selected = checks.require_latest_success([run(3, path, head_branch="test-tag")], path, SHA)
        self.assertEqual(selected["id"], 3)

    def api(self, endpoint, *, paginate=False, smoke=True):
        if endpoint == "actions/runs/10":
            return run()
        for index, path in enumerate(checks.REQUIRED_WORKFLOWS):
            if endpoint.startswith(f"actions/workflows/{path.rsplit('/', 1)[-1]}/runs?"):
                self.assertIn("head_sha=" + SHA, endpoint)
                return [{"workflow_runs": [run(11 + index, path)]}]
        if endpoint.startswith("actions/runs/10/jobs?"):
            return [{"jobs": [{"conclusion": "success", "steps": [{
                "name": checks.PACKAGE_SMOKE_STEP,
                "conclusion": "success" if smoke else "skipped"}]}]}]
        self.fail("Unexpected GitHub endpoint: " + endpoint)

    def test_stable_checks_github_job_evidence(self):
        with patch.object(checks, "github_api", side_effect=self.api):
            self.assertEqual(checks.verify_build("10", stable=True)["head_sha"], SHA)

    def test_missing_packaged_smoke_is_not_accepted(self):
        with patch.object(checks, "github_api", side_effect=lambda endpoint, **kw: self.api(endpoint, smoke=False, **kw)):
            with self.assertRaisesRegex(checks.VerificationError, "smoke"):
                checks.verify_build("10", stable=True)

    def test_source_must_be_a_successful_main_snap_build(self):
        for changes in ({"head_branch": "feature"}, {"event": "pull_request"},
                        {"path": checks.REQUIRED_WORKFLOWS[0]}, {"conclusion": "failure"},
                        {"id": 11}, {"head_sha": "invalid"}):
            with self.subTest(changes=changes), patch.object(checks, "github_api", return_value=run(**changes)):
                with self.assertRaises(checks.VerificationError):
                    checks.verify_build("10")

    def test_non_stable_build_does_not_require_unrelated_test_runs(self):
        with patch.object(checks, "github_api", return_value=run()) as api:
            checks.verify_build("10")
            api.assert_called_once_with("actions/runs/10")


class StoreBytesTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.package = Path(temporary.name) / "dmate.snap"
        self.package.write_bytes(b"independent test snap bytes")
        self.digest = hashlib.sha3_384(self.package.read_bytes()).hexdigest()

    def entry(self, channel, revision=7, **changes):
        result = {"channel": {"name": "latest/" + channel, "track": "latest", "architecture": "amd64"},
                  "revision": revision, "download": {"sha3-384": self.digest}}
        result.update(changes)
        return result

    def test_same_bytes_in_target_are_idempotent(self):
        self.assertEqual(store.check_package(self.package, "stable", {
            "channel-map": [self.entry("edge"), self.entry("stable")]}), 7)

    def test_other_channel_same_bytes_require_promotion(self):
        with self.assertRaisesRegex(store.StoreCheckError, "promote-existing.*revision=7"):
            store.check_package(self.package, "stable", {"channel-map": [self.entry("edge")]})

    def test_promotion_must_match_selected_build_bytes(self):
        info = {"channel-map": [self.entry("edge")]}
        self.assertIsNone(store.check_package(self.package, "stable", info, revision=7))
        with self.assertRaisesRegex(store.StoreCheckError, "Cannot prove"):
            store.check_package(self.package, "stable", info, revision=8)

    def test_different_bytes_may_be_uploaded_even_if_version_is_unchanged(self):
        info = {"channel-map": [self.entry("stable", download={"sha3-384": "b" * 96})]}
        self.assertIsNone(store.check_package(self.package, "stable", info))

    def test_missing_or_malformed_store_response_fails_closed(self):
        for info in ({}, {"channel-map": {}}, {"channel-map": [None]},
                     {"channel-map": [self.entry("edge", revision=True)]}):
            with self.subTest(info=info), self.assertRaises(store.StoreCheckError):
                store.check_package(self.package, "stable", info)

    def test_unreleased_snap_can_be_uploaded(self):
        self.assertIsNone(store.check_package(self.package, "edge", {"channel-map": []}))


if __name__ == "__main__":
    unittest.main()
