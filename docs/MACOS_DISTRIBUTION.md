# macOS 构建、签名与公证

当前桌面端使用 Tauri v2，配置位于 `desktop/src-tauri/tauri.conf.json`：最低系统版本 10.15，默认加载远程 DMate 网站。`.github/workflows/build-desktop.yml` 构建 `universal-apple-darwin` DMG，同时安装 Apple Silicon 与 Intel Rust target。

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

## 构建与发布

1. 在 GitHub Actions 手动运行 **Build DMate Desktop**，或由桌面配置 / 图标相关路径的 main 分支更新触发。
2. 正式路径创建临时 Keychain，导入证书后执行 `cargo tauri build --target universal-apple-darwin --bundles dmg`。Tauri 完成应用签名与公证。
3. 工作流用 `codesign --verify`、`spctl --assess`、`xcrun stapler validate` 检查应用；对最终 DMG 再执行 `notarytool submit`、`stapler staple` 与 Gatekeeper 检查。
4. 全部成功才上传 `DMate-macos-SIGNED-NOTARIZED` Artifact。下载并核对实际产物后，再更新选定的对外发行渠道。

工作流仅生成 Artifact，不自动替换 GitHub Release、GitCode 或其他渠道的旧 DMG。源码存在签名流程也不能证明线上旧安装包已签名或取得公证票据；应依据该次构建日志和实际下载文件判断。

网页更新无需重新打包，但 Tauri 原生逻辑、可信来源或包元数据变更需要新构建。默认远程站点的 TLS、登录 Cookie 和模型数据流见[部署说明](DEPLOYMENT.md)与[数据与隐私](SECURITY_PRIVACY.md)。

参考：[Tauri macOS 签名](https://v2.tauri.app/distribute/sign/macos/) · [Apple 公证说明](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
