#!/usr/bin/env python3
"""Publish the full-screen DMate Web Clip as a GitCode Release attachment."""

import argparse
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


API_ROOT = "https://api.gitcode.com/api/v5/repos/zm14744/DMate"
TAG = "v1.0.1"


def request_json(url, token, method="GET", body=None):
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    separator = "&" if "?" in url else "?"
    url = f"{url}{separator}{urlencode({'access_token': token})}"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=60) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else None
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitCode API {method} {url.split('?')[0]} failed: {exc.code} {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"GitCode API request failed: {exc.reason}") from exc


def get_release(token):
    return request_json(f"{API_ROOT}/releases/{TAG}", token)


def delete_asset(token, asset_id):
    url = f"{API_ROOT}/releases/{TAG}/attach_files/{quote(str(asset_id), safe='')}"
    request_json(url, token, method="DELETE")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("profile_path")
    parser.add_argument("--file-name", default="DMate-iPhone-iPad-fullscreen.mobileconfig")
    parser.add_argument("--remove-old-name", default="DMate-iPhone-iPad.mobileconfig")
    args = parser.parse_args()

    token = (os.environ.get("GITCODE_TOKEN") or "").strip()
    if not token:
        raise SystemExit("GITCODE_TOKEN is required")

    with open(args.profile_path, "rb") as handle:
        content = handle.read()

    if not content.startswith(b"<?xml") or b"FullScreen" not in content or b"<true/>" not in content:
        raise SystemExit("Refusing to upload a profile that does not contain FullScreen=true")

    release = get_release(token)
    assets = release.get("assets", []) if isinstance(release, dict) else []
    existing_new = [item for item in assets if item.get("name") == args.file_name]
    for item in existing_new:
        delete_asset(token, item.get("id"))

    upload_query = urlencode({"access_token": token, "file_name": args.file_name})
    upload_endpoint = f"{API_ROOT}/releases/{TAG}/upload_url?{upload_query}"
    req = Request(upload_endpoint, headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=60) as response:
            upload_info = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"Unable to obtain GitCode release upload URL: {exc}") from exc

    upload_url = upload_info.get("url")
    upload_headers = upload_info.get("headers")
    if not upload_url or not isinstance(upload_headers, dict):
        raise RuntimeError("GitCode returned an invalid pre-signed upload response")

    put_request = Request(
        upload_url,
        data=content,
        headers=upload_headers,
        method="PUT",
    )
    try:
        with urlopen(put_request, timeout=300) as response:
            response.read()
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"GitCode attachment upload failed: {exc}") from exc

    updated_release = get_release(token)
    updated_assets = updated_release.get("assets", []) if isinstance(updated_release, dict) else []
    uploaded = [item for item in updated_assets if item.get("name") == args.file_name]
    if not uploaded:
        raise RuntimeError("GitCode upload completed but the new release attachment was not visible")

    old_assets = [item for item in updated_assets if item.get("name") == args.remove_old_name]
    for item in old_assets:
        delete_asset(token, item.get("id"))

    print(f"Published GitCode release attachment: {args.file_name}")
    print(f"Size: {len(content)} bytes")
    print(f"Removed obsolete attachment count: {len(old_assets)}")


if __name__ == "__main__":
    main()
