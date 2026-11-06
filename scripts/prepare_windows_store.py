#!/usr/bin/env python3
"""Prepare the current DMate executable for two Microsoft Store package formats.

Windows SDK MakePRI and MakeAppx run separately in the Windows build workflow.
This preparation step never executes the input binaries or the runtime.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_icons import draw_mark

IDENTITY_NAME = "DMate.DMate"
PUBLISHER = "CN=F4B4F5DD-9B90-49AA-A3A9-C0B049718711"
FOUNDATION = "http://schemas.microsoft.com/appx/manifest/foundation/windows10"
UAP = "http://schemas.microsoft.com/appx/manifest/uap/windows10"
UAP10 = "http://schemas.microsoft.com/appx/manifest/uap/windows10/10"
RESCAP = "http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
VARIANTS = {"modern": ("1.0.3.0", "10.0.19041.0"),
            "classic": ("1.0.2.0", "10.0.17763.0")}
SCALES = (125, 150, 200, 400)
TARGET_SIZES = (16, 20, 24, 30, 32, 36, 40, 44, 48, 60, 64, 72, 80, 96, 128, 256)


def q(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


def create_manifest(directory: Path, variant: str) -> None:
    version, minimum = VARIANTS[variant]
    ET.register_namespace("", FOUNDATION)
    ET.register_namespace("uap", UAP)
    ET.register_namespace("uap10", UAP10)
    ET.register_namespace("rescap", RESCAP)
    namespaces = "uap rescap" + (" uap10" if variant == "modern" else "")
    package = ET.Element(q(FOUNDATION, "Package"), {"IgnorableNamespaces": namespaces})
    ET.SubElement(package, q(FOUNDATION, "Identity"), {
        "Name": IDENTITY_NAME, "Publisher": PUBLISHER, "Version": version,
        "ProcessorArchitecture": "x64"})
    properties = ET.SubElement(package, q(FOUNDATION, "Properties"))
    for key, value in (("DisplayName", "DMate"), ("PublisherDisplayName", "DMate"),
                       ("Description", "Discrete Mathematics Tutor"),
                       ("Logo", "Assets\\StoreLogo.png")):
        ET.SubElement(properties, q(FOUNDATION, key)).text = value
    resources = ET.SubElement(package, q(FOUNDATION, "Resources"))
    for language in ("en-us", "zh-cn"):
        ET.SubElement(resources, q(FOUNDATION, "Resource"), {"Language": language})
    dependencies = ET.SubElement(package, q(FOUNDATION, "Dependencies"))
    ET.SubElement(dependencies, q(FOUNDATION, "TargetDeviceFamily"), {
        "Name": "Windows.Desktop", "MinVersion": minimum,
        "MaxVersionTested": "10.0.26100.0"})
    applications = ET.SubElement(package, q(FOUNDATION, "Applications"))
    attributes = {"Id": "App", "Executable": "DMateLauncher.exe"}
    if variant == "modern":
        attributes[q(UAP10, "RuntimeBehavior")] = "packagedClassicApp"
        attributes[q(UAP10, "TrustLevel")] = "mediumIL"
    else:
        attributes["EntryPoint"] = "Windows.FullTrustApplication"
    application = ET.SubElement(applications, q(FOUNDATION, "Application"), attributes)
    ET.SubElement(application, q(UAP, "VisualElements"), {
        "DisplayName": "DMate", "Description": "Discrete Mathematics Tutor",
        "BackgroundColor": "#000000", "Square44x44Logo": "Assets\\Square44x44Logo.png",
        "Square150x150Logo": "Assets\\Square150x150Logo.png"})
    capabilities = ET.SubElement(package, q(FOUNDATION, "Capabilities"))
    ET.SubElement(capabilities, q(FOUNDATION, "Capability"), {"Name": "internetClient"})
    ET.SubElement(capabilities, q(RESCAP, "Capability"), {"Name": "runFullTrust"})
    ET.SubElement(capabilities, q(FOUNDATION, "DeviceCapability"), {"Name": "microphone"})
    ET.indent(package, space="  ")
    ET.ElementTree(package).write(directory / "AppxManifest.xml", encoding="utf-8", xml_declaration=True)


def create_assets(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, base in (("Square44x44Logo", 44), ("Square150x150Logo", 150), ("StoreLogo", 50)):
        draw_mark(base, min_stroke_px=1.0).save(directory / f"{name}.png", optimize=True)
        for scale in SCALES:
            pixels = math.ceil(base * scale / 100)
            draw_mark(pixels, min_stroke_px=1.0).save(
                directory / f"{name}.scale-{scale}.png", optimize=True)
    for pixels in TARGET_SIZES:
        draw_mark(pixels, min_stroke_px=1.0).save(
            directory / f"Square44x44Logo.targetsize-{pixels}.png", optimize=True)


def hardlink_or_copy(source: str, destination: str) -> str:
    try:
        os.link(source, destination)
        return destination
    except OSError:
        return shutil.copy2(source, destination)


def prepare(executable: Path, launcher: Path, runtime: Path, output: Path) -> None:
    executable = executable.resolve(strict=True)
    launcher = launcher.resolve(strict=True)
    runtime = runtime.resolve(strict=True)
    if not executable.is_file() or not launcher.is_file():
        raise ValueError("Executable and launcher must be regular files")
    if not runtime.is_dir() or not (runtime / "msedgewebview2.exe").is_file():
        raise ValueError("Runtime must be the folder containing msedgewebview2.exe")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory must be empty")
    output.mkdir(parents=True, exist_ok=True)
    for variant in VARIANTS:
        package = output / variant
        app = package / "App"
        app.mkdir(parents=True)
        shutil.copy2(executable, app / "dmate-desktop.exe")
        shutil.copy2(launcher, package / "DMateLauncher.exe")
        if variant == "modern":
            shutil.copytree(runtime, app / "WebView2")
            create_assets(package / "Assets")
        else:
            shutil.copytree(output / "modern" / "App" / "WebView2", app / "WebView2",
                            copy_function=hardlink_or_copy)
            shutil.copytree(output / "modern" / "Assets", package / "Assets",
                            copy_function=hardlink_or_copy)
        create_manifest(package, variant)
    print(json.dumps({"status": "prepared", "identity": IDENTITY_NAME,
                      "packages": {name: {"version": values[0], "min_version": values[1]}
                                   for name, values in VARIANTS.items()},
                      "runtime": "included", "output": str(output)}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.exe, args.launcher, args.runtime, args.output)


if __name__ == "__main__":
    main()
