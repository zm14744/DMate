#!/usr/bin/env python3
"""Copy the public offline workspace into an Android or desktop build."""

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import shutil
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "static" / "offline-service-worker.js"


def offline_assets():
    """Use the same dependency list as the browser's offline workspace."""
    match = re.search(r"\bconst PRECACHE = (\[[\s\S]*?\]);", WORKER.read_text(encoding="utf-8"))
    if not match:
        raise ValueError("The offline worker precache list is missing")
    assets = {}
    for url in json.loads(match.group(1)):
        path = urlsplit(url).path
        relative = PurePosixPath(path.lstrip("/"))
        if path == "/offline":
            assets[path] = (ROOT / "static" / "offline.html", PurePosixPath("offline.html"))
        elif path.startswith("/static/") and ".." not in relative.parts:
            assets[path] = (ROOT / relative, relative)
        else:
            raise ValueError(f"Unexpected offline asset path {path!r}")
    if "/offline" not in assets:
        raise ValueError("The offline workspace document is missing")
    assets["/static/offline.html"] = assets["/offline"]
    return assets


def stage(destination):
    assets = offline_assets()
    files = dict(assets.values())
    missing = [str(source.relative_to(ROOT)) for source in files if not source.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing offline resources: {', '.join(missing)}")
    for source, relative in files.items():
        output = destination / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        if relative == PurePosixPath("offline.html"):
            html = source.read_text(encoding="utf-8")
            output.write_text(html.replace("<html ", '<html data-native-offline-bundle="true" ', 1), encoding="utf-8")
        else:
            shutil.copyfile(source, output)
    # Native request handlers serve only these paths, regardless of any other
    # files left from an incremental build. Keep the list deterministic.
    (destination / "paths.txt").write_text("\n".join(sorted(assets)) + "\n", encoding="utf-8")
    return len(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True, help="Build output directory")
    args = parser.parse_args()
    print(f"Staged {stage(args.destination)} offline workspace files")


if __name__ == "__main__":
    main()
