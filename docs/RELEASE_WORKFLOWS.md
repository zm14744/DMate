# 发行流程维护

本轮仅更新通用的校验、重试、权限适配和验收机制。现有安装包文件名、版本号、发行 tag、固定来源和产物哈希保持原样；准备新版安装包时再单独更新这些信息。

## 桌面 GitHub 发布

`Publish Verified Desktop Release to GitHub` 先下载并验证已经公开的附件，哈希相符则复用。所有附件已经发布时，不再要求旧 Actions artifact 仍然存在；缺少的附件仍必须来自脚本中固定且受信任的构建，不能从未知来源补齐。同名文件的字节不符会停止，不能覆盖旧文件。

桌面与 Microsoft Store 工作流共享发行写入并发组。各自只更新自己的发行说明标记块，保留其他平台和人工维护的说明。安装包发布、商店提交和网页部署仍是不同操作。

## Microsoft Store

参考 [Microsoft Store 提交包](WINDOWS_STORE.md)。重新上传应复用已经验证的原始 artifact；临时证书和时间戳可能使重新构建的包具有不同字节，不能把重新构建当作上传重试。

## Snap

1. 对准备发行的源码提交运行 `Build DMate Snap (GitHub)`，保存成功 run ID。构建必须包含包级安装与保密存储验收。
2. 首次上传选择 `upload-new-build`，填写该 run ID，先发布到 `edge` 或其他测试渠道。
3. 同一二进制升渠道时选择 `promote-existing`，填写 revision。升到 `stable` 时还必须填写原构建 run ID；工作流会核对商店 revision 的 SHA3-384 与该构建产物一致。
4. `stable` 要求源码的同一 commit 上，`Test offline workspace` 和 `Test offline confidentiality backend` 最新运行均成功，还要求源 Snap 构建实际通过包级验收。缺失、正在运行、失败和取消都不会被较早的成功记录覆盖。

某个测试工作流由于路径过滤未在该提交运行时，应对同一 commit 手动运行它；不能用其他提交的绿灯代替。旧构建没有包级验收记录时，应重新构建和验证，不能伪造 artifact 内的证明文件。旧包继续使用现有版本标记不影响 Snap revision 的机制，但正式原生功能升级仍应单独准备可辨认的新版本。

如果相同文件已经在其他渠道，上传步骤会给出 revision 并提示改用提升操作。目标渠道已经是相同文件则跳过，避免重复上传。

## 自动检查

`Test release workflow guards` 在 Linux 和 Windows 运行发行逻辑回归检查，覆盖上传中断恢复、旧缓存过期、错误产物来源、版本不匹配、同名文件冲突、说明保留和渠道提升校验；测试不会执行真实发布。Windows 同时检查打包脚本语法。

这些逻辑测试不能替代生成安装包后的操作系统验收，也不代表 Microsoft Store 认证已经通过。首次部署原生能力升级时，需要同时核对已安装旧客户端与网页的能力兼容性；网页刷新不能补齐缺少的原生桥接。
