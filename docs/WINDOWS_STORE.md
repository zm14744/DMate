# Microsoft Store 提交包

在 Actions 运行 **Build and Publish Microsoft Store Packages**。该工作流下载并核对当前公开的 Windows 1.0.2 安装包，提取实际程序，附带 Microsoft 官方 Fixed WebView2 x64 运行时，使用 Windows SDK 生成并验证两个包，再上传到 GitHub 发行集合 `v1.0.1`。

| 文件 | 商店包版本 | 最低 Windows 版本 | 内含程序 |
| --- | --- | --- | --- |
| `DMate_1.0.3.0.msixbundle` | 1.0.3.0 | Windows 10 build 19041 | DMate 1.0.2 x64 |
| `DMate_1.0.2.0.classic.appxbundle` | 1.0.2.0 | Windows 10 build 17763 | DMate 1.0.2 x64 |

两个商店版本号保持主包和后备包的顺序，二者包含相同的最新桌面程序。Identity 为 `DMate.DMate`，Publisher 为 `CN=F4B4F5DD-9B90-49AA-A3A9-C0B049718711`，PublisherDisplayName 为 `DMate`。提交时沿用现有 DMate 产品，仅选择 **Windows 10/11 Desktop** 设备类型。

工作流使用临时且 Publisher 匹配的自签证书签署提交包；Microsoft Store 审核后会重签。私钥和证书不放入发行版，这两个文件供 Partner Center 提交使用。普通用户仍使用原有 EXE 安装入口。工作流不登录 Partner Center，也不自动向微软提交。
