#!/usr/bin/env python3
"""Check published Snap bytes before uploading or promoting an existing revision."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class StoreCheckError(Exception):
    pass


def matching_releases(package, info):
    digest = hashlib.sha3_384()
    with Path(package).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if not isinstance(info, dict) or not isinstance(info.get("channel-map"), list):
        raise StoreCheckError("The Snap Store response has no valid channel map; no publication is allowed.")
    matches = []
    for entry in info["channel-map"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("channel"), dict):
            raise StoreCheckError("The Snap Store returned invalid channel metadata.")
        details = entry.get("channel", {})
        if (details.get("architecture") == "amd64"
                and entry.get("download", {}).get("sha3-384") == digest.hexdigest()):
            revision = entry.get("revision")
            if type(revision) is not int or revision <= 0:
                raise StoreCheckError("The matching Snap has no valid Store revision.")
            matches.append({"revision": revision, "channel": details.get("name"),
                            "track": details.get("track")})
    return matches


def check_package(package, channel, info, revision=None):
    matches = matching_releases(package, info)
    if revision is not None and not any(item["revision"] == revision for item in matches):
        raise StoreCheckError(
            f"Cannot prove revision {revision} contains the selected build's bytes. "
            "Choose the matching build_run_id and a currently released revision; no promotion is allowed."
        )
    target = next((item for item in matches if item["track"] == "latest"
                   and item["channel"] in (channel, "latest/" + channel)), None)
    if target:
        return target["revision"]
    if matches and revision is None:
        item = matches[0]
        raise StoreCheckError(
            f"These exact bytes are already released as revision {item['revision']} "
            f"in {item['channel']}. Select promote-existing with revision={item['revision']} "
            "and the same build_run_id instead of uploading again."
        )
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("channel", choices=("edge", "beta", "candidate", "stable"))
    parser.add_argument("--revision", type=int,
                        help="Require this published revision to match the selected build before promotion")
    args = parser.parse_args()
    if args.revision is not None and args.revision <= 0:
        raise SystemExit("Revision must be a positive integer.")
    request = Request("https://api.snapcraft.io/v2/snaps/info/dmate", headers={
        "Snap-Device-Series": "16", "Snap-Device-Architecture": "amd64",
        "User-Agent": "DMate-Snap-publisher",
    })
    try:
        with urlopen(request, timeout=30) as response:
            info = json.load(response)
    except HTTPError as exc:
        if exc.code == 404:
            info = {"channel-map": []}
        else:
            raise SystemExit("Cannot check the Snap Store channel; retry publication later.") from None
    except (URLError, OSError, ValueError):
        raise SystemExit("Cannot check the Snap Store channel; retry publication later.") from None
    try:
        revision = check_package(args.package, args.channel, info, args.revision)
    except StoreCheckError as error:
        raise SystemExit(str(error)) from None
    print("already_released=" + ("true" if revision is not None else "false"))
    if revision is not None:
        print(f"revision={revision}")
        print(f"The exact Snap is already released to {args.channel} as revision {revision}; no upload is needed.", file=sys.stderr)


if __name__ == "__main__":
    main()
