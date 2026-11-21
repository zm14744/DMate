# Microsoft Store 提交包

在 Actions 运行 **Build and Publish Microsoft Store Packages**。该工作流下载并核对当前公开的 Windows 1.0.2 安装包，提取实际程序，附带 Microsoft 官方 Fixed WebView2 x64 运行时，使用 Windows SDK 生成并验证两个包，再上传到 GitHub 发行集合 `v1.0.1`。

| 文件 | 商店包版本 | 最低 Windows 版本 | 内含程序 |
| --- | --- | --- | --- |
| `DMate_1.0.3.0.msixbundle` | 1.0.3.0 | Windows 10 build 19041 | DMate 1.0.2 x64 |
| `DMate_1.0.2.0.classic.appxbundle` | 1.0.2.0 | Windows 10 build 17763 | DMate 1.0.2 x64 |

两个商店版本号保持主包和后备包的顺序，二者包含相同的最新桌面程序。Identity 为 `DMate.DMate`，Publisher 为 `CN=F4B4F5DD-9B90-49AA-A3A9-C0B049718711`，PublisherDisplayName 为 `DMate`。提交时沿用现有 DMate 产品，仅选择 **Windows 10/11 Desktop** 设备类型。

工作流使用临时且 Publisher 匹配的自签证书签署提交包；Microsoft Store 审核后会重签。私钥和证书不放入发行版，这两个文件供 Partner Center 提交使用。普通用户仍使用原有 EXE 安装入口。工作流不登录 Partner Center，也不自动向微软提交。

## 验证范围

打包时为内层应用包和外层 bundle 显式使用上述商店版本；验证器读取两个实际 manifest，检查 Identity、Publisher、版本、x64 架构和内含 EXE 的 SHA256。文件名不能代替 bundle 版本核验。

报告中的 `package_integrity_passed` 只表示包结构、签名和文件完整性检查通过。随后，工作流在隔离的 GitHub-hosted Windows runner 中实际安装较低版本，再原位升级到较高版本；通过包的 AUMID 启动程序，检查程序窗口与内置 WebView2 至少连续存活 10 秒。只有安装、启动、升级以及测试清理全部成功，才将 `installation_test`、`upgrade_test` 写为 `passed`，保存可发布 artifact；发布器也会重新检查这些结果。运行环境不支持 Appx 安装或图形启动时会明确失败，不能自动跳过而继续发布。

测试只允许本仓库 `main` 的 GitHub-hosted runner；发现已有同名安装立即停止。只信任当前 bundle 中 Publisher 匹配的临时证书，只清理本次安装目录内新启动的进程、测试包和新增的证书，不运行宽泛的进程终止或用户数据清理。测试流程没有修改应用业务数据。

这一 smoke 仍不等于 Windows App Certification Kit（WACK）、断网业务使用、保密功能或真实用户数据迁移验证；报告相应字段保持 `not_run`，实际发行前还需执行这些检查。Partner Center 的身份、版本和审核结果以后台为准。

当前输入程序、版本、哈希、发行集合和文件名仍保持原样，工作流不会自动选择或发布最新桌面构建。更换具体安装包属于单独的发行准备工作。

## 上传中断后的重试

1. 在原始构建 run 的 **Summary** 确认安装启动 smoke 通过，且已保存 `DMate-Microsoft-Store-Packages` artifact，并记下该 run ID 与其完整 commit SHA。即使之后的 GitHub 上传失败，只要 artifact 已保存，仍可以重试。
2. 再次运行本工作流，将 `source_run_id` 和 `expected_head_sha` 填为上述值。重试会核对本仓库、同一工作流、`main`、手动触发、已结束的 run、commit SHA、artifact 来源及完整性。
3. 此模式直接复用原 artifact，跳过重新打包和自签。新生成的临时签名会改变 bundle 字节，不能用重新构建的同名文件充当原来的重试。

所有同名附件先下载并校验：字节一致则跳过，只补传缺失文件；任何同名不同内容都会停止，不删除、不覆盖历史包。报告与说明文件也遵守同一规则。原始 artifact 保留 14 天；过期后无法从该 run 重试，需另行准备发行，不能把新签名包覆盖到旧文件名。旧版 `passed` 报告未核验外层 bundle，不能当作新格式验证报告复用。

工作流与桌面 GitHub 发布共享 `dmate-github-release-assets` 并发组。发行说明仅更新 `DMATE-WINDOWS-STORE-BEGIN/END` 标记块；原有完全匹配的自动生成微软说明会收进该块，其他内容保留。重复执行不会反复追加同一个标记块。

## 本地检查

运行 `python scripts/test_windows_store_release.py` 可离线检查内外版本不一致、已上传附件冲突、部分上传重试、来源验证、必须通过安装 smoke 的发布条件和发行说明保留逻辑，不会调用真实发布接口。`scripts/test_windows_store_install.ps1` 必须由上述 Windows workflow 以 Windows PowerShell 执行；本地 Python 单测或 PowerShell 语法检查不会把实际安装结果标记为通过。
