#!/usr/bin/env python3
"""Verify and retry Store submission artifacts without rebuilding or replacing them."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

ARTIFACT = "DMate-Microsoft-Store-Packages"
REPORT = "DMate-Microsoft-Store-verification.json"
SUPPORT_FILES = {"DMate-Microsoft-Store-README.txt", "DMate-Microsoft-Store-SHA256SUMS.txt"}
WORKFLOW = ".github/workflows/build-windows-store.yml"
BEGIN = "<!-- DMATE-WINDOWS-STORE-BEGIN -->"
END = "<!-- DMATE-WINDOWS-STORE-END -->"


class VerificationError(Exception):
    pass


def gh(*arguments: str) -> str:
    try:
        result = subprocess.run(["gh", *arguments], capture_output=True, text=True,
                                timeout=900, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise VerificationError("GitHub CLI failed or timed out") from None
    if result.returncode:
        raise VerificationError(f"GitHub CLI {arguments[0]} failed; existing assets were not replaced")
    return result.stdout


def api(repository: str, endpoint: str):
    try:
        return json.loads(gh("api", f"repos/{repository}/{endpoint}"))
    except ValueError:
        raise VerificationError("GitHub returned invalid JSON") from None


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, item: dict) -> None:
    if not path.is_file() or path.is_symlink() or path.stat().st_size != item["bytes"]:
        raise VerificationError(f"Missing file or incorrect size: {path.name}")
    if digest_file(path) != item["sha256"]:
        raise VerificationError(f"SHA256 mismatch: {path.name}")


def xml_child(node, name):
    return next((child for child in node if child.tag.rsplit("}", 1)[-1] == name), None)


def verify_identity(node, version: str, publisher: str) -> None:
    if node is None or any(node.get(key) != value for key, value in {
        "Name": "DMate.DMate", "Publisher": publisher, "Version": version,
    }.items()):
        raise VerificationError("Store package identity or version mismatch")


def verify_bundle(path: Path, version: str, publisher: str, app_hash: str) -> None:
    """Check the outer bundle and its single x64 package, not its filename alone."""
    with zipfile.ZipFile(path) as bundle:
        manifest = ET.fromstring(bundle.read("AppxMetadata/AppxBundleManifest.xml"))
        verify_identity(xml_child(manifest, "Identity"), version, publisher)
        packages = xml_child(manifest, "Packages")
        if packages is None or len(packages) != 1:
            raise VerificationError("Expected exactly one application package in the Store bundle")
        entry = packages[0]
        filename = entry.get("FileName", "")
        if (entry.get("Version") != version or entry.get("Architecture") != "x64"
                or entry.get("Type") != "application" or not filename
                or "/" in filename or "\\" in filename):
            raise VerificationError("Unexpected package entry in the Store bundle")
        with bundle.open(filename) as inner_stream, zipfile.ZipFile(inner_stream) as inner:
            inner_manifest = ET.fromstring(inner.read("AppxManifest.xml"))
            identity = xml_child(inner_manifest, "Identity")
            verify_identity(identity, version, publisher)
            if identity.get("ProcessorArchitecture") != "x64":
                raise VerificationError("Expected an x64 Store application")
            digest = hashlib.sha256()
            with inner.open("App/dmate-desktop.exe") as executable:
                for chunk in iter(lambda: executable.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != app_hash:
                raise VerificationError("Packaged application SHA256 mismatch")


def read_report(directory: Path) -> dict:
    path = directory / REPORT
    if not path.is_file() or path.is_symlink():
        raise VerificationError("The verification report is missing")
    report = json.loads(path.read_text(encoding="utf-8-sig"))
    if (not isinstance(report, dict) or report.get("schema_version") != 2
            or report.get("status") != "package_integrity_passed"):
        raise VerificationError("Artifact lacks the current package-integrity verification report")
    return report


def require_install_smoke(report: dict, packages: dict[str, str]) -> None:
    smoke = report.get("install_smoke") or {}
    if (report.get("installation_test") != "passed" or report.get("upgrade_test") != "passed"
            or not isinstance(smoke, dict) or smoke.get("status") != "passed"
            or smoke.get("cleanup") != "passed" or smoke.get("runner") != "github-hosted"):
        raise VerificationError("Publication requires the hosted Windows installation, launch and upgrade smoke test")
    results = smoke.get("packages", [])
    if (not isinstance(results, list) or len(results) != len(packages)
            or not all(isinstance(item, dict) for item in results)
            or {item.get("name"): item.get("version") for item in results} != packages):
        raise VerificationError("Installation smoke results do not cover the configured packages")
    for item in results:
        if (item.get("window_observed") is not True or item.get("bundled_webview_observed") is not True
                or not isinstance(item.get("observed_seconds"), (int, float))
                or item["observed_seconds"] < 10):
            raise VerificationError("Installation smoke did not confirm a stable application window and bundled runtime")


def verify_directory(args, require_install: bool = False) -> list[dict]:
    directory = args.directory
    report = read_report(directory)
    expected = {"source_installer_sha256": args.source_hash,
                "source_executable_sha256": args.app_hash, "publisher": args.publisher,
                "runtime_version": args.runtime_version}
    if any(report.get(key) != value for key, value in expected.items()):
        raise VerificationError("Artifact does not match the configured Store source and runtime")
    packages = dict(item.rsplit("=", 1) for item in args.package)
    if require_install:
        require_install_smoke(report, packages)
    required = set(packages) | SUPPORT_FILES
    files = report.get("files", [])
    if (not isinstance(files, list) or len(files) != len(required)
            or not all(isinstance(item, dict) and isinstance(item.get("name"), str) for item in files)):
        raise VerificationError("Unexpected artifact file list")
    names = [item.get("name") for item in files]
    if len(set(names)) != len(names) or set(names) != required:
        raise VerificationError("Artifact names differ from the configured Store output")
    if {path.name for path in directory.iterdir()} != required | {REPORT}:
        raise VerificationError("Artifact directory contains missing or unexpected files")
    for item in files:
        name = item["name"]
        if Path(name).name != name or "/" in name or "\\" in name:
            raise VerificationError("Artifact contains an unsafe filename")
        if (not isinstance(item.get("bytes"), int) or item["bytes"] <= 0
                or not re.fullmatch(r"[0-9a-f]{64}", item.get("sha256", ""))):
            raise VerificationError("Artifact has invalid hash or size metadata")
        verify_file(directory / name, item)
        if name in packages:
            if (item.get("package_version") != packages[name]
                    or item.get("bundle_version") != packages[name]):
                raise VerificationError("Package and bundle versions differ in the report")
            verify_bundle(directory / name, packages[name], args.publisher, args.app_hash)
    report_path = directory / REPORT
    return [*files, {"name": REPORT, "bytes": report_path.stat().st_size,
                    "sha256": digest_file(report_path)}]


def validate_source_run(run: dict, repository: str, run_id: str, expected_sha: str) -> None:
    if (not re.fullmatch(r"[1-9][0-9]*", run_id)
            or not re.fullmatch(r"[0-9a-f]{40}", expected_sha)):
        raise VerificationError("Retry requires a positive run ID and the reviewed full source commit SHA")
    if (not isinstance(run, dict) or run.get("id") != int(run_id)
            or (run.get("repository") or {}).get("full_name") != repository
            or (run.get("head_repository") or {}).get("full_name") != repository
            or run.get("path") != WORKFLOW or run.get("head_branch") != "main"
            or run.get("head_sha") != expected_sha or run.get("event") != "workflow_dispatch"
            or run.get("status") != "completed" or run.get("conclusion") not in {"success", "failure"}):
        raise VerificationError("Retry source is not the reviewed completed main-branch Store workflow")


def restore(args) -> None:
    if (not re.fullmatch(r"[1-9][0-9]*", args.run_id)
            or not re.fullmatch(r"[0-9a-f]{40}", args.expected_head_sha)):
        raise VerificationError("Retry requires a positive run ID and the reviewed full source commit SHA")
    run = api(args.repository, f"actions/runs/{args.run_id}")
    validate_source_run(run, args.repository, args.run_id, args.expected_head_sha)
    artifacts = api(args.repository, f"actions/runs/{args.run_id}/artifacts?per_page=100")
    matches = [item for item in artifacts.get("artifacts", []) if item.get("name") == ARTIFACT]
    if len(matches) != 1 or matches[0].get("expired"):
        raise VerificationError("The original verified Store artifact is missing or expired; do not rebuild it as a retry")
    if args.directory.exists() and any(args.directory.iterdir()):
        raise VerificationError("Retry artifact destination must be empty")
    args.directory.mkdir(parents=True, exist_ok=True)
    gh("run", "download", args.run_id, "--repo", args.repository, "--name", ARTIFACT,
       "--dir", str(args.directory))
    report = read_report(args.directory)
    if (str(report.get("build_run_id")) != args.run_id
            or report.get("build_commit") != args.expected_head_sha):
        raise VerificationError("Artifact provenance does not match its reviewed source run")
    print("Restored the original Store artifact; the publish step will reverify every byte and manifest.")


def merge_notes(body: str, content: str) -> str:
    content = content.strip()
    block = f"{BEGIN}\n{content}\n{END}"
    if BEGIN in body or END in body:
        if body.count(BEGIN) != 1 or body.count(END) != 1 or body.index(BEGIN) > body.index(END):
            raise VerificationError("Store release-note markers are ambiguous; no notes were changed")
        return body[:body.index(BEGIN)] + block + body[body.index(END) + len(END):]
    # Adopt only an exact copy of the old generated section; preserve hand edits.
    if content and body.count(content) == 1:
        return body.replace(content, block, 1)
    separator = "" if not body or body.endswith("\n\n") else "\n" if body.endswith("\n") else "\n\n"
    return body + separator + block + "\n"


def release(args) -> dict:
    item = api(args.repository, f"releases/tags/{args.tag}")
    if item.get("tag_name") != args.tag or item.get("draft") or item.get("prerelease"):
        raise VerificationError("Expected the existing public stable release")
    return item


def verify_remote(args, item: dict) -> None:
    with tempfile.TemporaryDirectory(prefix="dmate-store-verify-") as temporary:
        gh("release", "download", args.tag, "--repo", args.repository,
           "--pattern", item["name"], "--dir", temporary)
        verify_file(Path(temporary) / item["name"], item)


def publication_plan(args, current: dict, files: list[dict]) -> list[dict]:
    """Finish all conflict checks before uploading any missing attachment."""
    missing = []
    for item in files:
        matches = [asset for asset in current.get("assets", []) if asset.get("name") == item["name"]]
        if len(matches) > 1:
            raise VerificationError(f"Duplicate release asset: {item['name']}")
        if not matches:
            missing.append(item)
            continue
        if matches[0].get("size") != item["bytes"]:
            raise VerificationError(f"Existing release asset differs; kept intact: {item['name']}")
        verify_remote(args, item)
        print(f"Existing identical asset verified; skipping: {item['name']}")
    return missing


def publish(args) -> None:
    files = verify_directory(args, require_install=True)
    current = release(args)
    content = args.notes_file.read_text(encoding="utf-8-sig")
    merge_notes(current.get("body") or "", content)  # Fail before uploads if markers are malformed.
    missing = publication_plan(args, current, files)
    for item in missing:
        gh("release", "upload", args.tag, str(args.directory / item["name"]), "--repo", args.repository)
        verify_remote(args, item)
    # Read again after uploads so other release sections are not taken from a stale snapshot.
    current = release(args)
    previous = current.get("body") or ""
    updated = merge_notes(previous, content)
    if updated != previous:
        with tempfile.TemporaryDirectory(prefix="dmate-store-notes-") as temporary:
            path = Path(temporary) / "notes.md"
            path.write_text(updated, encoding="utf-8")
            gh("release", "edit", args.tag, "--repo", args.repository, "--notes-file", str(path))
    print("Store integrity and Windows installation smoke verified; GitHub assets published. WACK and Partner Center certification remain separate.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    bundle = sub.add_parser("verify-bundle")
    bundle.add_argument("--bundle", type=Path, required=True)
    bundle.add_argument("--version", required=True)
    bundle.add_argument("--publisher", required=True)
    bundle.add_argument("--app-hash", required=True)
    retry = sub.add_parser("restore")
    retry.add_argument("--repository", required=True)
    retry.add_argument("--run-id", required=True)
    retry.add_argument("--expected-head-sha", required=True)
    retry.add_argument("--directory", type=Path, required=True)
    verify = sub.add_parser("verify-directory")
    upload = sub.add_parser("publish")
    for name in ("repository", "tag"):
        upload.add_argument(f"--{name}", required=True)
    for command in (verify, upload):
        for name in ("publisher", "source-hash", "app-hash", "runtime-version"):
            command.add_argument(f"--{name}", required=True)
        command.add_argument("--package", action="append", required=True)
        command.add_argument("--directory", type=Path, required=True)
    upload.add_argument("--notes-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "verify-bundle":
            verify_bundle(args.bundle, args.version, args.publisher, args.app_hash)
            print("Outer bundle and inner package identities, versions and application hash verified.")
        elif args.command == "restore":
            restore(args)
        elif args.command == "verify-directory":
            verify_directory(args)
            print("Store artifact integrity verified before installation smoke testing.")
        else:
            publish(args)
    except (VerificationError, OSError, ValueError, KeyError, TypeError, ET.ParseError, zipfile.BadZipFile) as error:
        message = str(error) if isinstance(error, VerificationError) else "Invalid or unreadable Store artifact"
        parser.exit(1, f"Store operation stopped: {message}\n")


if __name__ == "__main__":
    main()
