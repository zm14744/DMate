# 离线保密底层与前端接入约定

## 交付状态

本次实现可直接调用的加密存储、自动密钥管理和原生密钥桥。没有新增锁屏、密码设置、导入导出按钮或备份流程。

`static/offline.html` 已加载 `offline-vault.js`，Service Worker 已预缓存它。**现有 `offline.js` 的业务读写尚未切换到新接口，旧数据也没有自动迁移。因此，仅合入本次改动不能宣称现有离线页面已经全部加密。** 后续前端工作须完成本文的存储替换和迁移验收。

底层本身不访问网络、不调用云端接口、不写 localStorage/sessionStorage、不要求用户记住或另存一个 DMate 密码。系统钥匙串如果已锁定，操作可能需要用户解锁现有系统账户；这与新增应用密码不同。

## 1. 每个平台实际得到什么保护

| 环境 | 密钥保管 | API 报告 | 能力边界 |
| --- | --- | --- | --- |
| Android 新版原生客户端 | AndroidKeyStore，原始 AES 密钥不返回 JavaScript | `android-keystore` / `os-keystore` | `hardwareBacked` 来自实际 KeyInfo；不预先承诺 TEE 或 StrongBox。API 35+ 要求设备处于解锁状态 |
| macOS 新版桌面客户端 | 系统 Keychain，通过固定服务名存取 | `desktop-keyring` / `os-keystore` | 密钥在原生侧使用，不返回网页；没有声称使用 Secure Enclave |
| Windows 新版桌面客户端 | Windows 系统凭据库 | `desktop-keyring` / `os-keystore` | 依赖当前 Windows 用户的系统保护，不声称 TPM 绑定 |
| Linux 新版桌面客户端 | 持久化 Secret Service | `desktop-keyring` / `os-keystore` | 没有服务、服务锁定或访问失败时明确报错；无明文文件或会话 keyring 降级 |
| Safari、iPhone/iPad 描述文件 Web Clip、普通浏览器 | IndexedDB 中的不可导出 Web Crypto `CryptoKey` | `webcrypto` / `browser-managed` | 数据以密文保存，但不能保证密钥与硬件绑定，也不能保证整份浏览器配置被复制后仍不可解密 |

`keyExportable: false` 表示本库没有返回原始密钥的接口，浏览器 AES key 的 `extractable` 为 `false`；它不意味着系统管理员、同权限进程或浏览器实现永远无法提取密钥。桌面凭据库可能随系统账户备份/恢复，故不把它宣传成严格的“只能这台设备使用”。

所有平台都需要承认使用时的边界：已经获得同源 JavaScript 执行权的代码，可以像正常应用一样调用解密；已解锁的设备、操作系统被控制和恶意更新也不在本模块的防护保证内。网页的 `/offline` 路径与同源在线页面不是独立安全域。若产品需要更强隔离，应在部署阶段使用单独 origin 或原生内置页面，并明确授权相应的新 origin，而非扩大为通配符。

## 2. 数据格式与防损坏设计

- AES-256-GCM；每次加密使用新的 96 位随机 IV，认证标签为 128 位。用户的图染色操作不参与密钥生成。
- 每个 vault 都有独立的随机密钥。原生密钥放在系统密钥服务中；浏览器密钥通过结构化克隆保存为 `CryptoKey`，不保存 Base64/JWK/原始 key。
- AAD 绑定格式版本、vault 名称及随机标识、密钥提供者、keyId、集合、记录 ID 和 revision。把笔记 A 的密文放到笔记 B 的位置不能正常解密。
- 加密的校验记录用于确认打开的密钥与数据库一致。缺失密钥、错误密钥和认证失败不会触发重建、覆盖或显示一个假空库。
- 首次打开时，在事务外生成候选密钥和校验密文，再在同一个 IndexedDB 事务中复查并建立元数据。两个窗口同时首次打开时只会选中一个候选；原生侧尽力清理落选的密钥。
- 每次写入必须提供 `expectedRevision`。事务内比较全部旧 revision，再原子写入整批；冲突返回 `CONFLICT`，不自动覆盖。
- Web Crypto/Blob/系统密钥操作都在 IndexedDB 事务外执行。只有事务完成事件才代表本次保存成功。
- `close()` 中止活跃事务，并使仍在进行的解密在交还结果前检查关闭状态。已交给调用者的对象、DOM、字符串或截图不会被本模块自动擦除。

数据库名为 `dmate-offline-vault-v1`，版本 1：

| Store | 内容 |
| --- | --- |
| `vaults` | keyPath `name`；格式、随机 vaultId/keyId、提供者、能力声明、加密校验记录；仅浏览器提供者包含 `CryptoKey` |
| `records` | keyPath `[vault, collection, id]`；revision、IV、认证密文；按 vault、集合建立结构性索引 |

**公开元数据**包括 vault 名称、集合名、记录 ID、记录数量、revision、密文长度和密钥提供者。应使用 `personal-v1`、`notes`、随机 UUID 等结构性标识；不能把笔记标题、邮箱、姓名或搜索词放进这些键。标题、正文、Blob MIME 类型、文件名和业务时间戳应放在加密的 `value` 内。

本版本不隐藏访问模式或数据长度，不防完整有效数据库的历史回滚，不保证防删除。IndexedDB、系统钥匙串和旧明文缓存的删除都不等于物理磁盘安全擦除。随机 IV 的碰撞概率不是数学上的零；该接口面向个人离线资料库，不应把单一密钥用于接近 `2^32` 次的大规模加密服务。

## 3. 前端调用

页面已经加载全局 `window.DMateOfflineVault`。模块初始化不打开数据库，也不会改变现有数据。

```js
const vault = await DMateOfflineVault.open({name: "personal-v1"});

// 原生桥存在时自动使用系统密钥；普通浏览器使用 Web Crypto。
console.log(vault.capabilities.keyProtection); // 仅能力信息，不含记录或密钥

const created = await vault.write("notes", "note-42", {
  title: "图论笔记",
  content: "我的推导……",
  updatedAt: Date.now()
}, {expectedRevision: null}); // null 表示必须尚不存在

const saved = await vault.read("notes", "note-42");
await vault.write("notes", "note-42", {
  ...saved.value,
  content: "修改后的推导……"
}, {expectedRevision: saved.revision});

const notes = await vault.list("notes");
// [{id, revision, value}, ...]；没有记录时为 []。

const current = await vault.read("notes", "note-42");
await vault.remove("notes", "note-42", {expectedRevision: current.revision});
vault.close();
```

如果调用方业务明确要求系统密钥保护，应直接要求该能力：

```js
const vault = await DMateOfflineVault.open({
  name: "personal-v1",
  requireProtection: "os-keystore"
});
```

这会在描述文件版/普通浏览器中报 `PROTECTION_UNAVAILABLE`，不会悄悄改成浏览器保护。默认调用会接受浏览器保护，但仍报告真实等级。识别为 `DMateAndroid/` 或 `DMateDesktop/` 的旧原生客户端如果没有桥，返回 `NATIVE_UNAVAILABLE`；必须更新客户端后再接入。现有 vault 的提供者发生变化时也不会自动降级或重加密。

### 数据类型、大小和命名

- 支持普通对象、数组、字符串、有限数值、布尔值、`null`、`undefined`，以及嵌套 `Blob`、`File`、`ArrayBuffer`、`Uint8Array`。
- 不支持循环引用、函数、访问器属性、自定义原型、Symbol、BigInt、Date/Map/Set 等额外类型；请先按业务约定转换。
- 每条记录经过编码后的明文上限 16 MiB；一批最多 128 个操作，总编码明文最多 32 MiB。
- vault 名称：1–128 位 ASCII，首字符为字母或数字，其余可用字母、数字、`_`、`.`、`-`。
- 集合名：1–64 位，首字符小写字母，其余小写字母、数字、`_`、`-`。
- 记录 ID：1–256 位 ASCII，首字符字母或数字，其余可用字母、数字、`_`、`.`、`:`、`-`。现有 ID 不符合时用稳定映射，不把敏感名称直接作为 ID。

### 原子业务更新

记录删除与删除标记等有关联的数据应在同一批次中保存：

```js
const note = await vault.read("notes", "note-42");
const deletions = await vault.read("settings", "note-deletions");
await vault.batch([
  {type: "delete", collection: "notes", id: "note-42",
    expectedRevision: note.revision},
  {type: "put", collection: "settings", id: "note-deletions",
    expectedRevision: deletions?.revision ?? null,
    value: {...(deletions?.value ?? {}), "note-42": Date.now()}}
]);
```

`CONFLICT` 后先重新读取，再由业务决定合并或提示冲突。不要把所有错误都当成“空数据”，也不要通过无条件覆盖绕开 revision。

### 关键错误码

| code | 调用方处理 |
| --- | --- |
| `CONFLICT` | 重读并处理并发修改 |
| `KEY_MISSING` | 保留数据库，不生成替代密钥，不重置资料库 |
| `AUTHENTICATION_FAILED` | 保留损坏/被改动的数据，停止读取该批内容 |
| `KEYSTORE_UNAVAILABLE` | 系统钥匙串不可用或锁定；允许稍后重试 |
| `NATIVE_UNAVAILABLE` | 当前原生客户端缺桥或桥不可用；更新客户端 |
| `PROTECTION_UNAVAILABLE` / `PROTECTION_MISMATCH` | 所需能力不存在或提供者不同；不要自动降级 |
| `QUOTA_EXCEEDED` / `STORAGE_FAILED` | 保存未完成；保留内存草稿并明确告知失败 |
| `CLOSED` | 句柄已关闭；切换上下文后重新打开 |
| `TOO_LARGE` / `UNSUPPORTED_VALUE` / `INVALID_ARGUMENT` | 按接口约定调整输入 |
| `BUSY` / `NATIVE_TIMEOUT` | 有界重试；不要因此写明文缓存 |

错误消息经过固定映射，不包含数据内容、文件名或原生系统异常详情。前端日志同样不要记录 `value`、整个请求或密钥元数据对象。

## 4. 原生实现位置与边界

Android 文件位于 `android/app/src/main/java/app/dmate/client/OfflineVault*.java`，使用 AndroidX WebMessage listener；Desktop 独立密码学 crate 位于 `desktop/src-tauri/offline-vault`，Tauri 接线位于 `src/offline_vault.rs`、`src/offline-vault.js` 和最小 capability 文件。

桥仅允许主页面的 `https://dmate.zeabur.app:443/offline` 和 `/static/offline.html`。它不是任意系统密钥读写接口，keyId 只允许 32 位小写十六进制，系统服务/alias 前缀固定。两端都不允许调用方指定加密 IV，不向 JS 返回原始 AES key，也不把 key 放进随数据库复制的普通文件。

Android 使用来源 origin、顶层 frame、当前 URL 与导航 generation 校验；回复通过原始 `JavaScriptReplyProxy`。桌面同时使用最小远程 ACL、原生 URL/窗口校验和初始化脚本闭包内的临时 token；跨源文档不加载进这个有解密回调的 WebView，外部 HTTP(S) 链接交系统浏览器打开。浏览器里的同源恶意代码仍与业务代码有同等访问能力。

原生操作协议是 `capabilities / create / encrypt / decrypt / delete`。`delete` 用于清理未入库候选密钥；普通前端应通过存储 API 管理记录，不能直接删已提交 vault 的 key。桌面锁文件只保存跨进程互斥状态，不含密钥或用户数据。

原生密钥丢失、清理应用数据、浏览器清理站点数据、系统钥匙串重置等可能使资料不可恢复。本次没有密码恢复、云端托管或导出副本；不要加入开发者万能密钥。若日后设计跨设备迁移，须单独设计密钥交付，不能直接把数据库复制成功当成迁移成功。

## 5. 后续 Codex 必须完成的持久化接入

此次没有删除、重写或隐式迁移用户的旧数据。以下是实际代码中的接入点，不是额外 UI 需求：

| 现有路径 | 后续替换要求 |
| --- | --- |
| `offline.js` 的 `openDb / transaction / put / all / remove` | 笔记、错题、练习、设置全部走 vault，保存 revision；删除与 tombstone 用 batch |
| `offline.js` 与 drawing-workspace 的绘图库 localStorage | 用加密记录保存图库；若图形组件要求同步缓存，只能用当前页面的内存适配器，异步保存成功后再确认 |
| `offline.js` 的 appearance localStorage 备份 | 外观及背景 Blob 统一走 vault，不能同时留一份明文 JSON/图片 |
| `DMateGuestSession` 中的离线 JSON 与 Blob key | 不把现有 Base64 secret 当作新密钥；明确游客资料生命周期，再使用对应的加密存储策略 |
| `offline-entry.js` 的 `dmate_offline_migration_v1` | 新交接不写明文 sessionStorage；既有交接槽迁移成功后清理 |
| 搜索索引、临时图片、草稿、错误日志 | 不把解密结果重新持久化到 localStorage、sessionStorage、Cache Storage 或遥测 |
| 账号/上下文切换 | 先关闭旧 vault，清空业务内存和 DOM，再打开新上下文；名称只是数据分组，不是访问认证 |

迁移必须先加密写入、成功提交并读回校验，再删除该范围旧明文；失败保留源数据。跨旧/新数据库不可能凭本接口获得一个全局事务，需可重复、可恢复的迁移标记。迁移期间应通过旧 IndexedDB 的版本升级/关闭协议阻止旧页面继续写明文，并处理旧 localStorage 路径。不能把复制一次后旧页面仍继续写入的状态视为迁移完成。

在线版原有数据与云同步属于另一条业务路径；这里不保证擦除在线副本。离线入口接入时也不得重新调用在线同步方法为 vault 自动备份。

## 6. 验证方法

```sh
node scripts/test_offline_vault_browser.cjs
python3 scripts/test_android_offline_vault.py
node scripts/test_desktop_offline_vault.cjs
cargo test --locked --manifest-path desktop/src-tauri/offline-vault/Cargo.toml
cargo check --locked --manifest-path desktop/src-tauri/Cargo.toml
```

浏览器脚本启动独立本地 HTTP 测试服务，使用真实 IndexedDB 和 Web Crypto；`DMATE_TEST_BROWSER` 可选 `chromium`、`firefox`、`webkit`，也可指定 `DMATE_BROWSER_EXECUTABLE`。测试包括并发建库、持久化重开、CAS 和整批失败、密文/IV/AAD 调换、丢钥不重建、关闭在途读取、嵌套 Blob、没有网络或 Web Storage 旁路、原生不可用不降级及大记录的原生桥格式。

Android JDK 测试执行生产协议/密码学实现，密钥提供者为内存模拟；桌面 Rust 单测也使用测试密钥提供者，JS 桥测试使用受控环境。它们不冒充真机硬件验证。真实 OS 凭据库往返测试明确标记 ignored，需在目标机器解锁密钥库后手动运行；Android 还需要真机/模拟器验证 KeyStore 与 WebView 生命周期。Playwright WebKit 也不等于已经在用户的 iPhone/iPad 上验收。

## 7. 一手依据

- [W3C Web Cryptography：密钥存储与安全边界](https://www.w3.org/TR/webcrypto-1/#security-considerations-authors)
- [W3C IndexedDB：事务生命周期](https://www.w3.org/TR/IndexedDB-3/#transaction-lifecycle)
- [W3C IndexedDB：同源目录不隔离](https://www.w3.org/TR/IndexedDB-3/#security-cross-directory)
- [NIST SP 800-38D：GCM 认证加密](https://csrc.nist.gov/pubs/sp/800/38/d/final)
- [Android Keystore](https://developer.android.com/privacy-and-security/keystore)
- [Android 的 unlockedDeviceRequired 版本限制](https://developer.android.com/reference/android/security/keystore/KeyGenParameterSpec.Builder#setUnlockedDeviceRequired(boolean))
- [Tauri capabilities](https://v2.tauri.app/security/capabilities/)
- [keyring 的平台实现与 features](https://docs.rs/keyring/3.6.3/keyring/)
