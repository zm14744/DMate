#!/usr/bin/env python3
"""Skip a repeated Snap upload only when the target channel has identical bytes."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def matching_revision(package, channel, info):
    digest = hashlib.sha3_384()
    with Path(package).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    for entry in info.get("channel-map", []):
        details = entry.get("channel", {})
        if (details.get("name") in (channel, "latest/" + channel)
                and details.get("track") == "latest"
                and details.get("architecture") == "amd64"
                and entry.get("download", {}).get("sha3-384") == digest.hexdigest()):
            revision = entry.get("revision")
            if isinstance(revision, int) and revision > 0:
                return revision
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("channel", choices=("edge", "beta", "candidate", "stable"))
    args = parser.parse_args()
    request = Request("https://api.snapcraft.io/v2/snaps/info/dmate", headers={
        "Snap-Device-Series": "16", "Snap-Device-Architecture": "amd64",
        "User-Agent": "DMate-Snap-publisher",
    })
    try:
        with urlopen(request, timeout=30) as response:
            info = json.load(response)
    except HTTPError as exc:
        if exc.code == 404:
            info = {}
        else:
            raise SystemExit("Cannot check the Snap Store channel; retry publication later.") from None
    except (URLError, OSError, ValueError):
        raise SystemExit("Cannot check the Snap Store channel; retry publication later.") from None
    revision = matching_revision(args.package, args.channel, info)
    print("already_released=" + ("true" if revision is not None else "false"))
    if revision is not None:
        print(f"revision={revision}")
        print(f"The exact Snap is already released to {args.channel} as revision {revision}; no upload is needed.", file=sys.stderr)


if __name__ == "__main__":
    main()
