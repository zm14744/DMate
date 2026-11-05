#!/usr/bin/env python3
"""Publish one verified Android release under a new, immutable asset name.

GitHub is required. GitCode is published only when GITCODE_TOKEN is configured;
the report explicitly records a missing token as skipped, never as published.
Existing attachments are never deleted or replaced.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPOSITORY = "zm14744/DMate"
TAG = "v1.0.1"
VERSION_NAME = "1.0.3"
VERSION_CODE = "4"
PACKAGE_NAME = "app.dmate.client"
ASSET_NAME = f"DMate-Android-{VERSION_NAME}.apk"
SIGNER_SHA256 = "aecc4ea91621d6466c7db945a9a178498d5b3e1f78e5f19d81f6973f9229c776"
BUILD_WORKFLOW = ".github/workflows/build-android-release.yml"
GITHUB_API = f"https://api.github.com/repos/{REPOSITORY}"
GITCODE_API = f"https://api.gitcode.com/api/v5/repos/{REPOSITORY}"
DOWNLOAD_URLS = {
    "github": f"https://github.com/{REPOSITORY}/releases/download/{TAG}/{ASSET_NAME}",
    "gitcode": f"{GITCODE_API}/releases/{TAG}/attach_files/{ASSET_NAME}/download",
}
MAX_APK_BYTES = 128 * 1024 * 1024


class PublishError(Exception):
    """An error whose message is safe to print without credentials or URLs."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PublishError("Authenticated API/upload redirects are not allowed")


class PublicHttpsRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urlsplit(newurl)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise PublishError("Public download redirected to an invalid destination")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def request_bytes(request, label, *, public=False, limit=2 * 1024 * 1024):
    opener = build_opener(PublicHttpsRedirect() if public else NoRedirect())
    try:
        with opener.open(request, timeout=60) as response:
            content = response.read(limit + 1)
    except HTTPError as exc:
        # Neither response bodies nor exception reprs are safe: API responses
        # and signed-storage errors can echo tokens and pre-signed URLs.
        raise PublishError(f"{label} failed (HTTP {exc.code})") from None
    except (URLError, OSError, ValueError):
        raise PublishError(f"{label} failed (network or invalid response)") from None
    if len(content) > limit:
        raise PublishError(f"{label} exceeded the response-size limit")
    return content


def api_json(provider, endpoint, token):
    headers = {"Accept": "application/json", "User-Agent": "DMate-release-publisher"}
    if provider == "github":
        url = GITHUB_API + endpoint
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    else:
        separator = "&" if "?" in endpoint else "?"
        url = GITCODE_API + endpoint + separator + urlencode({"access_token": token})
    raw = request_bytes(Request(url, headers=headers), f"{provider} API")
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError):
        raise PublishError(f"{provider} API returned invalid JSON") from None


def run_checked(command, label):
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        raise PublishError(f"{label} could not run") from None
    if result.returncode:
        raise PublishError(f"{label} failed (exit {result.returncode})")
    return result.stdout


def verify_build(args, github_token):
    if not re.fullmatch(r"[1-9]\d*", args.build_run_id):
        raise PublishError("build_run_id must be a positive integer")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", args.expected_head_sha):
        raise PublishError("expected_head_sha must be a full 40-character commit SHA")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", args.expected_apk_sha256):
        raise PublishError("expected_apk_sha256 must be a 64-character SHA256")
    run = api_json("github", f"/actions/runs/{args.build_run_id}", github_token)
    if not isinstance(run, dict) or not (
        run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and run.get("head_sha", "").lower() == args.expected_head_sha.lower()
        and run.get("head_branch") == "main"
        and run.get("event") == "workflow_dispatch"
        and run.get("path") == BUILD_WORKFLOW
        and (run.get("repository") or {}).get("full_name") == REPOSITORY
        and (run.get("head_repository") or {}).get("full_name") == REPOSITORY
    ):
        raise PublishError("Source run is not the expected successful main-branch Android release build")
    artifacts = api_json("github", f"/actions/runs/{args.build_run_id}/artifacts", github_token)
    matches = [a for a in artifacts.get("artifacts", []) if a.get("name") == "DMate-release-apk"]
    if len(matches) != 1 or matches[0].get("expired"):
        raise PublishError("Source build must contain one unexpired DMate-release-apk artifact")


def get_releases(tokens):
    releases = {"github": api_json("github", f"/releases/tags/{TAG}", tokens["github"])}
    if tokens.get("gitcode"):
        releases["gitcode"] = api_json("gitcode", f"/releases/{TAG}", tokens["gitcode"])
    for provider, release in releases.items():
        if not isinstance(release, dict) or not isinstance(release.get("assets"), list):
            raise PublishError(f"{provider} release response has no valid asset list")
        if release.get("tag_name") != TAG:
            raise PublishError(f"{provider} returned the wrong release tag")
        if release.get("draft") or release.get("prerelease"):
            raise PublishError(f"{provider} target must be an existing public stable release")
    return releases


def verify_apk(args):
    apk = Path(args.apk)
    if not apk.is_file() or not 0 < apk.stat().st_size <= MAX_APK_BYTES:
        raise PublishError("APK file is missing, empty, or too large")
    metadata = run_checked([args.aapt, "dump", "badging", str(apk)], "APK metadata verification")
    package = re.search(r"^package: name='([^']+)' versionCode='([^']+)' versionName='([^']+)'", metadata, re.M)
    if not package or package.groups() != (PACKAGE_NAME, VERSION_CODE, VERSION_NAME):
        raise PublishError("APK must be app.dmate.client versionName 1.0.3 and versionCode 4")
    signature = run_checked(
        [args.apksigner, "verify", "--verbose", "--print-certs", str(apk)], "APK signature verification"
    )
    signers = re.findall(r"^Signer #\d+ certificate SHA-256 digest:\s*([0-9a-fA-F]+)\s*$", signature, re.M)
    if len(signers) != 1 or signers[0].lower() != SIGNER_SHA256:
        raise PublishError("APK signer does not match the existing DMate release certificate")
    content = apk.read_bytes()
    if hashlib.sha256(content).hexdigest() != args.expected_apk_sha256.lower():
        raise PublishError("APK SHA256 does not match the independently supplied expected hash")
    return content


def verify_public_download(provider, expected_hash):
    # Read the real public GET path, including bytes after HTTPS redirects;
    # no credential is attached and neither HEAD nor metadata is sufficient.
    for attempt in range(4):
        try:
            content = request_bytes(
                Request(DOWNLOAD_URLS[provider], headers={"User-Agent": "DMate-release-verifier"}),
                f"{provider} public APK download", public=True, limit=MAX_APK_BYTES,
            )
        except PublishError:
            if attempt == 3:
                raise
            time.sleep(2 ** (attempt + 1))
            continue
        if hashlib.sha256(content).hexdigest() != expected_hash:
            raise PublishError(f"{provider} public APK SHA256 mismatch; existing assets were not replaced")
        return


def existing_asset(provider, release, expected_hash):
    matches = [a for a in release["assets"] if a.get("name") == ASSET_NAME]
    if len(matches) > 1:
        raise PublishError(f"{provider} has ambiguous duplicate asset names")
    if matches:
        verify_public_download(provider, expected_hash)
        return True
    return False


def upload_github(content, release, token):
    release_id = release.get("id")
    if not isinstance(release_id, int) or release_id <= 0:
        raise PublishError("GitHub returned an invalid release ID")
    url = f"https://uploads.github.com/repos/{REPOSITORY}/releases/{release_id}/assets?{urlencode({'name': ASSET_NAME})}"
    request_bytes(Request(url, data=content, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/vnd.android.package-archive",
        "Accept": "application/vnd.github+json", "User-Agent": "DMate-release-publisher",
    }, method="POST"), "GitHub new-asset upload")


def upload_gitcode(content, token):
    info = api_json("gitcode", f"/releases/{TAG}/upload_url?{urlencode({'file_name': ASSET_NAME})}", token)
    if not isinstance(info, dict) or not isinstance(info.get("url"), str) or not isinstance(info.get("headers"), dict):
        raise PublishError("GitCode returned an invalid signed upload response")
    parts = urlsplit(info["url"])
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise PublishError("GitCode returned an invalid signed upload destination")
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in info["headers"].items()):
        raise PublishError("GitCode returned invalid upload headers")
    request_bytes(Request(info["url"], data=content, headers=info["headers"], method="PUT"), "GitCode new-asset upload")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "publish"))
    parser.add_argument("--build-run-id", required=True)
    parser.add_argument("--expected-head-sha", required=True)
    parser.add_argument("--expected-apk-sha256", required=True)
    parser.add_argument("--apk")
    parser.add_argument("--aapt")
    parser.add_argument("--apksigner")
    parser.add_argument("--report", default="android-publication.json")
    args = parser.parse_args()
    tokens = {"github": (os.environ.get("GH_TOKEN") or "").strip(), "gitcode": (os.environ.get("GITCODE_TOKEN") or "").strip()}
    if not tokens["github"]:
        raise PublishError("GH_TOKEN is required; no publication attempted")
    if not tokens["gitcode"]:
        print("GitCode: NOT PUBLISHED (GITCODE_TOKEN is not configured). GitHub-only publication is allowed.")
    verify_build(args, tokens["github"])
    releases = get_releases(tokens)
    if args.mode == "preflight":
        print("Verified source run, commit, artifact and available release credentials. No assets uploaded.")
        return
    if not all((args.apk, args.aapt, args.apksigner)):
        raise PublishError("publish requires --apk, --aapt and --apksigner")
    content = verify_apk(args)
    expected_hash = args.expected_apk_sha256.lower()
    # Check both providers before making changes: a conflicting name must never
    # be resolved by deleting, overwriting, or silently using a different file.
    existing = {p: existing_asset(p, r, expected_hash) for p, r in releases.items()}
    results = {"gitcode": {"status": "not_published", "reason": "GITCODE_TOKEN_not_configured"}} if not tokens["gitcode"] else {}
    for provider, release in releases.items():
        if not existing[provider]:
            if provider == "github":
                upload_github(content, release, tokens[provider])
            else:
                upload_gitcode(content, tokens[provider])
        verify_public_download(provider, expected_hash)
        results[provider] = {"status": "already_present_verified" if existing[provider] else "published_verified", "url": DOWNLOAD_URLS[provider]}
        print(f"{provider}: {results[provider]['status']} ({ASSET_NAME}, SHA256 {expected_hash})")
    report = {
        "status": "all_sources_verified" if tokens["gitcode"] else "github_verified_gitcode_not_published",
        "build_run_id": args.build_run_id, "source_commit": args.expected_head_sha.lower(),
        "file_name": ASSET_NAME, "version_name": VERSION_NAME, "version_code": int(VERSION_CODE),
        "size_bytes": len(content), "sha256": expected_hash, "signer_sha256": SIGNER_SHA256, "sources": results,
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"### Android {VERSION_NAME} publication\n\nAsset: `{ASSET_NAME}`\n\nSHA256: `{expected_hash}`\n\n")
            for provider, result in results.items():
                handle.write(f"- {provider}: **{result['status']}**" + (f" — {result['url']}" if "url" in result else " — GITCODE_TOKEN not configured; no GitCode publication") + "\n")


if __name__ == "__main__":
    try:
        main()
    except PublishError as exc:
        print(f"Publication failed: {exc}", file=sys.stderr)
        print("No attachments were deleted or replaced. Any completed upload is retained for safe retry; no final success report was produced.", file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        # Suppress raw exceptions: they can include tokens or signed URLs.
        print("Publication failed unexpectedly; no final success report was produced. Check the safe step diagnostics.", file=sys.stderr)
        raise SystemExit(1) from None
