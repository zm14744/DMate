#!/usr/bin/env python3
"""Publish the verified 2026-11-06 desktop builds to GitHub only.

This manual release operation never rebuilds software, overwrites a new-version
asset, uploads to GitCode, or changes the Android attachment. Old desktop assets
are removed only after all replacement bytes have been downloaded and verified.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPO = "zm14744/DMate"
TAG = "v1.0.1"
ROOT = Path(__file__).resolve().parents[1]
NOTES = ROOT / "docs" / "releases" / "2026-11-06-desktop-1.0.2.md"
BUILDS = (
    (42204799873, "97d7ecc22e1d16e51337bbcf72ff7d2ddd8225fe", "DMate-windows"),
    (42205886089, "496b67d7d812113688b55514905314f83d70c384", "DMate-linux"),
    (42205889542, "496b67d7d812113688b55514905314f83d70c384", "DMate-macos-UNSIGNED-TEST-ONLY"),
)
FILES = {
    "DMate_1.0.2_x64-setup.exe": (2058539, "85aae11548c72174474523175a42f648e36c91f195a8ec72529fb047723fcbfb"),
    "DMate_1.0.2_amd64.deb": (2986562, "83a4d3a34d78c5ab9099c6cdf180ba5abf164e335796b95d30e67ba62c56b75f"),
    "DMate_1.0.2_amd64.AppImage": (81398264, "f4031a7b16206003a6c92f2ea1ef9ee81332d0d01390d72ba7a0e3e3152836ef"),
    "DMate_1.0.2_universal.dmg": (5808980, "ad838b92005dd4b82c9a28dd384f264fb419560e89cc3737e965bf43f0731da9"),
}
IOS = ("DMate-iPhone-iPad-fullscreen.mobileconfig", 36880,
       "357f40aa7d7ff3d5140ceff75fdcb8c8d618e6e9230dbc1d715fa68a4f0d5c2c")
OLD_FILES = (
    "DMate_1.0.0_x64-setup.exe", "DMate_1.0.0_amd64.deb",
    "DMate_1.0.0_amd64.AppImage", "DMate_1.0.0_universal.dmg",
)


class PublishError(Exception):
    """A safe error message without credentials or signed download URLs."""


def gh(*args):
    try:
        result = subprocess.run(["gh", *args], capture_output=True, text=True,
                                timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise PublishError("GitHub CLI operation failed or timed out") from None
    if result.returncode:
        raise PublishError(f"GitHub CLI {args[0]} operation failed (exit {result.returncode})")
    return result.stdout


def api(endpoint):
    try:
        return json.loads(gh("api", f"repos/{REPO}/{endpoint}"))
    except ValueError:
        raise PublishError("GitHub returned invalid JSON") from None


def release():
    item = api(f"releases/tags/{TAG}")
    if item.get("tag_name") != TAG or item.get("draft") or item.get("prerelease"):
        raise PublishError("Expected the existing public v1.0.1 release collection")
    return item


def asset_named(item, name):
    matches = [asset for asset in item.get("assets", []) if asset.get("name") == name]
    if len(matches) > 1:
        raise PublishError(f"Duplicate release attachment: {name}")
    return matches[0] if matches else None


def verify_file(path, size, digest):
    if not path.is_file() or path.is_symlink() or path.stat().st_size != size:
        raise PublishError(f"Wrong or missing file size: {path.name}")
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    if hasher.hexdigest() != digest:
        raise PublishError(f"SHA256 mismatch: {path.name}")


class HttpsOnlyRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urlsplit(newurl)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise PublishError("Public download attempted an invalid redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def verify_public(name, size, digest, directory):
    """Read the public attachment URL without credentials; do not trust metadata."""
    target = directory / name
    url = f"https://github.com/{REPO}/releases/download/{TAG}/{name}"
    for attempt in range(4):
        try:
            request = Request(url, headers={"User-Agent": "DMate-release-verifier"})
            opener = build_opener(HttpsOnlyRedirect())
            with opener.open(request, timeout=60) as response, target.open("wb") as output:
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > size:
                        raise PublishError(f"Public attachment exceeds expected size: {name}")
                    output.write(chunk)
            verify_file(target, size, digest)
            return
        except (HTTPError, URLError, OSError, PublishError):
            if attempt == 3:
                raise PublishError(f"Public download verification failed: {name}") from None
            time.sleep(2 ** (attempt + 1))


def verified_builds(directory):
    directory.mkdir(parents=True, exist_ok=True)
    for run_id, commit, artifact_name in BUILDS:
        run = api(f"actions/runs/{run_id}")
        if not (run.get("status") == "completed" and run.get("conclusion") == "success"
                and run.get("head_sha") == commit and run.get("head_branch") == "main"
                and run.get("event") == "workflow_dispatch"
                and run.get("path") == ".github/workflows/build-desktop.yml"
                and (run.get("repository") or {}).get("full_name") == REPO
                and (run.get("head_repository") or {}).get("full_name") == REPO):
            raise PublishError(f"Unexpected or unsuccessful source build: {run_id}")
        artifacts = api(f"actions/runs/{run_id}/artifacts")
        matches = [a for a in artifacts.get("artifacts", []) if a.get("name") == artifact_name]
        if len(matches) != 1 or matches[0].get("expired"):
            raise PublishError(f"Missing or expired verified artifact: {run_id}")
        gh("run", "download", str(run_id), "--repo", REPO, "--name", artifact_name,
           "--dir", str(directory / str(run_id)))
    found = {}
    for name, (size, digest) in FILES.items():
        paths = list(directory.rglob(name))
        if len(paths) != 1 or not paths[0].resolve().is_relative_to(directory.resolve()):
            raise PublishError(f"Expected exactly one verified artifact file: {name}")
        verify_file(paths[0], size, digest)
        found[name] = paths[0]
    return found


def publish():
    if (os.environ.get("GITHUB_REPOSITORY") != REPO
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or not os.environ.get("GH_TOKEN")):
        raise PublishError("Run this manual workflow on the repository main branch")
    if not NOTES.is_file():
        raise PublishError("The reviewed release notes are missing")
    with tempfile.TemporaryDirectory(prefix="dmate-desktop-release-") as temporary:
        directory = Path(temporary)
        local = verified_builds(directory / "artifacts")
        downloads = directory / "verified-downloads"
        downloads.mkdir()
        initial = release()
        # Existing immutable new-version files must match, never be clobbered.
        for name, (size, digest) in FILES.items():
            if asset_named(initial, name):
                verify_public(name, size, digest, downloads)
            else:
                gh("release", "upload", TAG, str(local[name]), "--repo", REPO)
            verify_public(name, size, digest, downloads)
            print(f"Verified GitHub attachment: {name}")
        # iOS is restored/published by its separate GitHub-only workflow. Do not
        # edit it here, and do not publish checksums or notes for old bytes.
        verify_public(*IOS, downloads)
        sums = directory / "SHA256SUMS.txt"
        entries = [(name, digest) for name, (_size, digest) in FILES.items()]
        entries.append((IOS[0], IOS[2]))
        sums.write_text("".join(f"{digest}  {name}\n" for name, digest in entries), encoding="utf-8")
        sums_size = sums.stat().st_size
        sums_digest = hashlib.sha256(sums.read_bytes()).hexdigest()
        if asset_named(release(), sums.name):
            verify_public(sums.name, sums_size, sums_digest, downloads)
        else:
            gh("release", "upload", TAG, str(sums), "--repo", REPO)
            verify_public(sums.name, sums_size, sums_digest, downloads)
        # Every replacement and the manifest have passed public byte checks.
        for name in OLD_FILES:
            if asset_named(release(), name):
                gh("release", "delete-asset", TAG, name, "--repo", REPO, "--yes")
                print(f"Removed replaced desktop attachment: {name}")
        gh("release", "edit", TAG, "--repo", REPO,
           "--title", "DMate — Desktop 1.0.2 / Android 1.0.3",
           "--notes-file", str(NOTES))
        final = release()
        if any(asset_named(final, name) for name in OLD_FILES):
            raise PublishError("An old desktop attachment is still present")
        print("GitHub desktop publication verified; GitCode and Android were not modified.")


if __name__ == "__main__":
    try:
        publish()
    except PublishError as exc:
        print(f"Release publication stopped: {exc}", file=sys.stderr)
        sys.exit(1)
