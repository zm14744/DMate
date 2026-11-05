#!/usr/bin/env python3
"""Generate the versioned DMate iPhone/iPad Web Clip release attachment."""

import argparse
import hashlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ios_webclip import build_ios_webclip_profile


DEFAULT_OUTPUT = ROOT / "dist" / "DMate-iPhone-iPad-fullscreen.mobileconfig"
ICON_PATH = ROOT / "static" / "icons" / "dmate-app-v50-512.png"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    content = build_ios_webclip_profile(ICON_PATH)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(content)

    print(f"Generated: {args.output}")
    print(f"Size: {len(content)} bytes")
    print(f"SHA-256: {hashlib.sha256(content).hexdigest()}")


if __name__ == "__main__":
    main()
