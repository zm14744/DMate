# DMate community package submissions (2026-10-13)

This directory contains **ready-to-review submission source files**, not evidence that a third-party package catalog has accepted them. No additional user credentials are stored here.

## Official upstream release assets

GitHub release: https://github.com/zm14744/DMate/releases/tag/v1.0.1

| Binary | Advertised binary version | SHA-256 |
| --- | --- | --- |
| Windows NSIS `DMate_1.0.0_x64-setup.exe` | 1.0.0 | `740c98119cc4511d7f6f763287e2b80358f134dc602dd1eb3f384f287504727c` |
| Linux `DMate_1.0.0_amd64.deb` | 1.0.0 | `f08be966fd157465da68a0f76d316edec15199e6eac511616737c0fb6c92f307` |
| Linux `DMate_1.0.0_amd64.AppImage` | 1.0.0 | `25838e98c60d39007765de168006416142a1ba721613999a809f224fc5fac553` |

**Important:** the upstream release tag is `v1.0.1`, but the desktop installer filenames and Tauri product version are **1.0.0**. Package manifests intentionally use **1.0.0**, not the release tag number. Do not blindly raise PackageVersion to 1.0.1 without rebuilding/updating the desktop binaries.

## 1. WinGet

Files: `winget/manifests/z/zm14744/DMate/1.0.0/`.

Target: https://github.com/microsoft/winget-pkgs/tree/master/manifests

- WinGet community repository requires three YAML manifest files and a publicly reachable, stable installer URL with a verifiable SHA-256.
- Installer type is NSIS (`nullsoft`); confirm silent install behavior on an actual Windows machine before submitting.
- Repository currently does not contain a top-level software LICENSE. Per WinGet metadata guidance, use `License: Proprietary` when no formal license information is available; do not claim MIT/Apache/open-source without authorizing it.
- Submission requires a **fork of `microsoft/winget-pkgs`** and a PR from that fork. This repository only stages manifests, it does not publish to WinGet automatically.
- After acceptance, expected command: `winget install --id zm14744.DMate --exact`.

Official: https://github.com/microsoft/winget-pkgs/tree/master/doc

## 2. AppImageHub

File: `appimagehub/data/DMate`.

Target: https://github.com/AppImage/appimage.github.io/tree/master/data

- The catalog accepts one-line files referencing the GitHub release AppImage URL or the upstream repo hosting AppImages.
- Existing filename `DMate_1.0.0_amd64.AppImage` does **not** match the ideal `DMate-1.0.0-x86_64.AppImage` naming convention, so this submission points to the exact current binary, rather than relying on automatic discovery of future versions.
- AppImageHub CI checks download accessibility, desktop metadata, offline startup and compatibility with the oldest supported Ubuntu LTS. **DMate is a remote-site Tauri shell:** verify its offline error screen before assuming review will pass.
- Actual submission requires a **fork of `AppImage/appimage.github.io`** and a PR adding `data/DMate`. This file alone does not list the app.

Official: https://github.com/AppImage/appimage.github.io

## 3. AUR (Arch / Manjaro / Nyarch)

Files: `aur/dmate-bin/PKGBUILD` and `aur/dmate-bin/.SRCINFO`.

- Uses the official Debian release artifact with pinned hash. Only x86_64 is supplied; the PKGBUILD **does not** pretend the Windows binary or the AMD64 package supports ARM.
- Declares GTK / WebKitGTK runtime dependencies present in the Arch package repositories.
- `license=('unknown')` is used because the upstream repository currently has no verified software LICENSE. Decide and document the software license before broad third-party redistribution; if an SPDX license is added upstream, update PKGBUILD and .SRCINFO together.
- These files are a packaging **candidate** until `makepkg --printsrcinfo` and `makepkg -si` are tested on Arch/Nyarch. Confirm the DEB payload installs `/usr/bin/dmate-desktop` and a valid desktop launcher.
- AUR publication requires an account and registered SSH key. Use `git clone ssh://aur@aur.archlinux.org/dmate-bin.git`, copy the validated files, commit and push. Do not add binaries to the AUR Git repository.

Official: https://wiki.archlinux.org/title/AUR_submission_guidelines

## Status

- ✅ The existing upstream GitHub Release links and SHA-256 were verified from the GitHub Releases API.
- ✅ Manifest source files prepared inside this repository.
- ⏳ Independent local installation, WinGet manifest validation, AppImageHub CI and AUR package builds not yet completed.
- ⏳ WinGet / AppImageHub upstream PRs and AUR SSH publication not yet performed.

These files do not alter the running Flask app or trigger Snap Store publication.
