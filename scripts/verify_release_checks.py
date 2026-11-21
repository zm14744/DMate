#!/usr/bin/env python3
"""Verify a Snap build's GitHub provenance and exact-commit stable release gates."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from urllib.parse import urlencode


REPOSITORY = "zm14744/DMate"
BUILD_WORKFLOW = ".github/workflows/build-snap.yml"
REQUIRED_WORKFLOWS = (
    ".github/workflows/test-offline-workspace.yml",
    ".github/workflows/test-offline-vault.yml",
)
PACKAGE_SMOKE_STEP = "Install and exercise the packaged Snap"


class VerificationError(Exception):
    pass


def github_api(endpoint, *, paginate=False):
    command = ["gh", "api", f"repos/{REPOSITORY}/{endpoint}"]
    if paginate:
        command += ["--paginate", "--slurp"]
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=120, check=False)
        if result.returncode:
            raise VerificationError("Cannot read the release checks from GitHub; no publication is allowed.")
        return json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise VerificationError("Cannot read the release checks from GitHub; no publication is allowed.") from None


def trusted_run(run, path, sha=None, *, require_main=True):
    return (
        isinstance(run, dict)
        and run.get("path") == path
        and (not require_main or run.get("head_branch") == "main")
        and (run.get("repository") or {}).get("full_name") == REPOSITORY
        and (run.get("head_repository") or {}).get("full_name") == REPOSITORY
        and run.get("event") in ("push", "workflow_dispatch")
        and re.fullmatch(r"[0-9a-f]{40}", str(run.get("head_sha", ""))) is not None
        and (sha is None or run.get("head_sha") == sha)
    )


def require_latest_success(runs, path, sha):
    # Include pending, failed and cancelled runs. A previous green run must not
    # hide the most recent attempt for the commit being released.
    candidates = [run for run in runs if trusted_run(run, path, sha, require_main=False)]
    if not candidates:
        raise VerificationError(
            f"Stable publication requires {path} to pass on source commit {sha}. "
            "No trusted run exists for that exact commit; run its workflow_dispatch first."
        )
    if any(type(run.get("id")) is not int or run["id"] <= 0 for run in candidates):
        raise VerificationError("GitHub returned an invalid test run identity.")
    latest = max(candidates, key=lambda run: run["id"])
    if latest.get("status") != "completed" or latest.get("conclusion") != "success":
        raise VerificationError(
            f"Stable publication blocked: latest {path} run {latest['id']} for {sha} "
            f"is {latest.get('status')}/{latest.get('conclusion')}."
        )
    return latest


def verify_build(run_id, *, stable=False):
    if not re.fullmatch(r"[1-9][0-9]*", str(run_id)):
        raise VerificationError("Enter a successful Build DMate Snap run ID in build_run_id.")
    run = github_api(f"actions/runs/{run_id}")
    if (not trusted_run(run, BUILD_WORKFLOW)
            or run.get("event") != "workflow_dispatch"
            or str(run.get("id")) != str(run_id)
            or run.get("status") != "completed" or run.get("conclusion") != "success"):
        raise VerificationError("The selected Snap source run is not a successful, trusted main build.")
    sha = run["head_sha"]
    if stable:
        for path in REQUIRED_WORKFLOWS:
            query = urlencode({"head_sha": sha, "per_page": 100})
            pages = github_api(f"actions/workflows/{path.rsplit('/', 1)[-1]}/runs?{query}", paginate=True)
            runs = [item for page in pages for item in page.get("workflow_runs", [])]
            require_latest_success(runs, path, sha)
        # Inspect GitHub's executed job steps, not a provenance JSON supplied
        # inside the artifact. Builds predating package-level checks fail closed.
        pages = github_api(f"actions/runs/{run_id}/jobs?filter=latest&per_page=100", paginate=True)
        jobs = [job for page in pages for job in page.get("jobs", [])]
        if not any(job.get("conclusion") == "success" and any(
                step.get("name") == PACKAGE_SMOKE_STEP and step.get("conclusion") == "success"
                for step in job.get("steps", [])) for job in jobs):
            raise VerificationError(
                "The selected source run has no successful packaged Snap installation/vault smoke check. "
                "Build and validate a new Snap before releasing it to stable."
            )
    return run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-run-id", required=True)
    parser.add_argument("--stable", action="store_true")
    args = parser.parse_args()
    try:
        run = verify_build(args.build_run_id, stable=args.stable)
    except VerificationError as error:
        raise SystemExit(str(error)) from None
    print(f"run_id={run['id']}")
    print(f"head_sha={run['head_sha']}")
    print(f"Verified source run {run['id']} at {run['head_sha']}", file=sys.stderr)


if __name__ == "__main__":
    main()
