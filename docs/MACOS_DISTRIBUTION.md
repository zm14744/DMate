# macOS 构建、签名与公证

当前桌面端使用 Tauri v2，配置位于 `desktop/src-tauri/tauri.conf.json`：最低系统版本 10.15，默认加载远程 DMate 网站。`.github/workflows/build-desktop.yml` 构建 `universal-apple-darwin` DMG，同时安装 Apple Silicon 与 Intel Rust target。

## 先区分三种产物

| 产物 | 用途 | 可以据此判断什么 |
| --- | --- | --- |
| 本机或 ad-hoc 构建 | 开发者调试界面和原生逻辑 | 能生成应用，不代表满足普通用户分发要求 |
| Developer ID 签名应用 | 识别开发者并保护签名内容 | 有有效开发者签名，不等于已完成 Apple 公证 |
| 签名、公证并装订票据的 DMG | 面向用户分发 | 仍应检查本次日志和实际文件，不能由工作流存在推断旧包状态 |

DMG 是安装分发容器，里面的 `.app` 也要分别检查。当前工作流先让 Tauri 对应用签名和公证，再对最终 DMG 单独提交公证与装订票据，不只检查其中一层。

## 构建前准备

推荐使用仓库的 macOS GitHub Actions job，它与 Windows / Linux 构建共享入口、独立执行对应平台步骤。需要手动本机构建时，准备 macOS、Xcode 命令行工具、Rust 工具链和 Tauri 2 CLI；正式签名还需要有效 Apple Developer 账号、Developer ID Application 证书及其私钥。

应用窗口和远程地址来自 [Tauri 配置](../desktop/src-tauri/tauri.conf.json)，原生导航、权限和平台逻辑在 [main.rs](../desktop/src-tauri/src/main.rs)。更换自托管域名时应一起核对这些来源检查；只修改地址不能证明新站点获得相同原生能力。

## 配置发布凭据

将 Developer ID Application 证书连同私钥导出为 `.p12`，转换为 Base64 后存到 GitHub 仓库 Actions Secrets。工作流使用以下六项，均不能提交到代码或公开日志：

| Secret | 含义 |
| --- | --- |
| `APPLE_CERTIFICATE` | 包含私钥的 p12 文件 Base64 |
| `APPLE_CERTIFICATE_PASSWORD` | p12 导出密码 |
| `APPLE_SIGNING_IDENTITY` | 以 `Developer ID Application:` 开头的完整证书名称 |
| `APPLE_ID` | Apple 开发者账号邮箱 |
| `APPLE_PASSWORD` | Apple 应用专用密码 |
| `APPLE_TEAM_ID` | Apple Developer Team ID |

六项全部缺省时，工作流使用 ad-hoc 签名并生成 `DMate-macos-UNSIGNED-TEST-ONLY`；这类产物未公证，Gatekeeper 可能阻止打开。部分配置时直接失败。全部配置有效后才进入正式签名与公证路径。

`APPLE_PASSWORD` 是 Apple 应用专用密码，不是把常用登录密码写进构建文件。`APPLE_CERTIFICATE` 必须包含私钥，只导出公开证书不足以签名。证书过期、吊销、名称与导入身份不一致，或账号不属于相应 Team，都可能让正式流程失败。需要更换凭据时更新 Actions Secrets，不在代码或排障截图中暴露内容。

## 构建与发布

1. 在 GitHub Actions 手动运行 **Build DMate Desktop**，或由桌面配置 / 图标相关路径的 main 分支更新触发。
2. 正式路径创建临时 Keychain，导入证书后执行 `cargo tauri build --target universal-apple-darwin --bundles dmg`。Tauri 完成应用签名与公证。
3. 工作流用 `codesign --verify`、`spctl --assess`、`xcrun stapler validate` 检查应用；对最终 DMG 再执行 `notarytool submit`、`stapler staple` 与 Gatekeeper 检查。
4. 全部成功才上传 `DMate-macos-SIGNED-NOTARIZED` Artifact。下载并核对实际产物后，再更新选定的对外发行渠道。

工作流仅生成 Artifact，不自动替换 GitHub Release、GitCode 或其他渠道的旧 DMG。源码存在签名流程也不能证明线上旧安装包已签名或取得公证票据；应依据该次构建日志和实际下载文件判断。

### 本地 universal 构建命令

在已具备上述系统依赖的 macOS 上，从仓库根目录执行：

```bash
cargo install tauri-cli --version '^2' --locked
rustup target add aarch64-apple-darwin
rustup target add x86_64-apple-darwin
cd desktop
cargo tauri build --target universal-apple-darwin --bundles dmg
```

这组命令仅说明构建入口，不会自动安装发布证书或替你提供公证凭据。正式构建需按 Tauri 和 Apple 要求在本机配置签名身份及公证认证；公共发布更适合采用仓库已包含验证步骤的 Actions 路径。

universal 目标的产物目录通常为 `desktop/src-tauri/target/universal-apple-darwin/release/bundle/`，其中 `macos/` 为应用，`dmg/` 为磁盘映像。命令在 `desktop/` 内执行，查看输出时应留意相对路径。

### 下载与对外发布

1. 打开对应的 **Build DMate Desktop** 运行，确认 macOS job 使用了完整凭据，并完成正式检查。
2. 下载 `DMate-macos-SIGNED-NOTARIZED` Artifact；当前保留期为 7 天，需要及时归档到正式发布位置。
3. 对将要发布的实际 DMG 核对版本、文件名、签名和票据；不要与同一时期的测试产物混用。
4. 将核对后的 DMG 上传选定渠道，再修改相应下载入口。网页可通过 `DESKTOP_MACOS_URL` 指向实际发布文件。
5. 记录对应提交与构建来源。以后替换网站不能改变已下载 DMG 的签名或原生代码。

## 常见失败如何定位

| 现象 | 核查方向 |
| --- | --- |
| 工作流提示凭据不完整 | 六项 Secrets 是否全部配置，名称是否与工作流完全一致 |
| 找不到 signing identity | p12 是否含私钥，密码是否正确，完整证书名是否匹配 |
| 公证认证失败 | 应用专用密码、Apple ID、Team ID 和开发者账号状态 |
| 找不到预期 `.app` / `.dmg` | Tauri 构建是否已成功，目标与 bundle 类型是否匹配 |
| 签名通过但票据校验失败 | 是否完成相应应用 / DMG 公证及 stapler 步骤，是否在签名后改动了文件 |
| 用户下载的仍是旧版本 | 检查实际渠道文件与网页下载链接，Artifact 不自动覆盖公开下载 |
| 只有 `UNSIGNED-TEST-ONLY` | 该次没有完整 Apple 配置，不应把测试包当成正式已公证发行包 |

排障应以当前构建日志和实际产物为准。不要用关闭 Gatekeeper 或批量移除隔离属性代替修复发行包的签名与公证流程。

网页更新无需重新打包，但 Tauri 原生逻辑、可信来源或包元数据变更需要新构建。默认远程站点的 TLS、登录 Cookie 和模型数据流见[部署说明](DEPLOYMENT.md)与[数据与隐私](SECURITY_PRIVACY.md)。

参考：[Tauri macOS 签名](https://v2.tauri.app/distribute/sign/macos/) · [Apple 公证说明](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
