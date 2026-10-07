# DMate Desktop (Tauri)

本目录是 DMate 的 Windows / macOS / Linux 桌面客户端。前端直接加载 https://dmate.zeabur.app，不复制后端和网页业务代码。

## Windows 本地测试
1. 安装 Microsoft C++ Build Tools，并勾选“使用 C++ 的桌面开发”。
2. Windows 10/11 通常已经有 WebView2。
3. 安装 Rust：`winget install --id Rustlang.Rustup`。
4. 重开 PowerShell，执行：
   - `cargo install tauri-cli --version "^2" --locked`
   - `cd desktop`
   - `cargo tauri dev`
5. 生成安装程序：`cargo tauri build --bundles nsis`。

## Arch Linux
先安装 Tauri 官方依赖：
`sudo pacman -Syu`
`sudo pacman -S --needed webkit2gtk-4.1 base-devel curl wget file openssl appmenu-gtk-module libappindicator-gtk3 librsvg xdotool`
然后安装 Rust 和 Tauri CLI，执行：
`cargo tauri dev`
`cargo tauri build --bundles appimage`

## Ubuntu / Debian
安装 `libwebkit2gtk-4.1-dev build-essential curl wget file libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev`，再运行 Tauri。
发布时建议同时生成 `.deb` 和 AppImage。

## macOS
安装 Xcode Command Line Tools：`xcode-select --install`，再安装 Rust。
构建 DMG：`cargo tauri build --bundles dmg --target universal-apple-darwin`。
公开分发前建议使用 Apple Developer 证书签名并公证。
