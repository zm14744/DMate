#!/usr/bin/env python3
"""Package Firefox submission files without checkout-time ZIP metadata."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import tempfile
import zipfile

ZIP_DATE = (1980, 1, 1, 0, 0, 0)


def package_directory(source: Path, destination: Path) -> int:
    source = Path(source)
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Package source must be a real directory")
    source = source.resolve()
    destination = Path(destination).resolve()
    if destination.is_relative_to(source):
        raise ValueError("Package output must be outside its source directory")

    files = []
    for entry in source.rglob("*"):
        if entry.is_symlink():
            raise ValueError("Package sources must not contain symbolic links")
        if entry.is_dir():
            continue
        if not entry.is_file():
            raise ValueError("Package sources must contain only regular files")
        name = entry.relative_to(source).as_posix()
        if "\\" in name:
            raise ValueError("Package paths must use portable directory separators")
        files.append((name, entry))

    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=destination.name + ".", suffix=".tmp", dir=destination.parent)
    os.close(descriptor)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, entry in sorted(files):
                info = zipfile.ZipInfo(name, ZIP_DATE)
                info.create_system = 3
                permissions = 0o755 if entry.stat().st_mode & stat.S_IXUSR else 0o644
                info.external_attr = (stat.S_IFREG | permissions) << 16
                archive.writestr(info, entry.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return len(files)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    count = package_directory(args.source, args.destination)
    print(f"Packaged {count} files ({args.destination.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
