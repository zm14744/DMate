# DMate macOS 签名与公证发布

此文档对应 `.github/workflows/build-desktop.yml` 和 Tauri v2。旧版 `tauri.conf.json` 中的 `signingIdentity: "-"` 仅为 ad-hoc 签名，不能通过 macOS Gatekeeper 的正式分发验证。**macOS 用户需要的正式版必须具有 Developer ID 签名与 Apple 公证。**

## 需要准备的 Apple 开发者凭据

Apple Developer Program 中的 **Developer ID Application** 证书应导出包含私钥的 `.p12`，并转为不带换行的 Base64。只将以下内容添加为 GitHub 仓库 Actions secrets，不要放在代码、PR、文档、日志或 Zeabur 环境变量里：

| GitHub Actions Secret | 含义 |
|---|---|
| `APPLE_CERTIFICATE` | Developer ID Application 的 p12 文件 Base64 |
| `APPLE_CERTIFICATE_PASSWORD` | 导出 p12 时设置的密码 |
| `APPLE_SIGNING_IDENTITY` | Keychain 中以 `Developer ID Application:` 开头的完整证书名 |
| `APPLE_ID` | Apple 开发者账号邮箱 |
| `APPLE_PASSWORD` | Apple 账号生成的**应用专用密码**，不是账户登录密码 |
| `APPLE_TEAM_ID` | 10 位 Apple Developer Team ID |

本仓库不持有这些证书或 Apple 凭据，不能自动替拥有者完成 Apple Developer 注册和公证。所有 6 个 Secret 填写齐全之后，构建工作流会创建临时 Keychain、导入证书，执行 `cargo tauri build --target universal-apple-darwin --bundles dmg`。Tauri 使用上述环境变量自动签名和公证，流水线随后分别使用 `codesign --verify`、`spctl --assess`、`xcrun stapler validate` 验证应用与 DMG。验证失败不会上传任何标称正式公证的安装包。

- 6 个 Secret **全部未设置**：仍能生成 `DMate-macos-UNSIGNED-TEST-ONLY` 测试用安装包，但是 Gatekeeper 仍可能警告，**不得作为无需手动放行的正式版宣传或替换 GitHub Release**。
- Secret **仅设置一部分**：macOS 构建直接失败，避免混淆。
- Secret **全部设置且验证通过**：生成 `DMate-macos-SIGNED-NOTARIZED`；发布前需要人工确认 Release、GitCode 和 itch.io 对应 DMG 已被替换，构建 Artifact 不会自动覆盖既有 Release。
- 如果 Apple 公证服务暂时不可用或拒绝包，将保留日志并失败；不使用 `xattr -d com.apple.quarantine` 等命令绕过用户设备上的安全检查。

可以从 GitHub → Settings → Secrets and variables → Actions 添加 Secrets。完成后在 Actions 页面手动运行 **Build DMate Desktop**，检查 macOS 构建记录和 DMG artifact。

**限制：**截至本次提交，没有验证苹果公证 Secret 已配置，也没有实际获得 Apple notarization ticket；已发布的旧 `DMate_1.0.0_universal.dmg` 不会因仓库配置改变而自动变成已签名版。

官方文档：
- https://v2.tauri.app/distribute/sign/macos/
- https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution
