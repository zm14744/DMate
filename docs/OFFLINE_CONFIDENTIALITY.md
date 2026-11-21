# 离线保密存储与平台边界

## 交付状态

离线工作区已接入加密存储、自动密钥管理和原生密钥桥。错题、概念笔记、历史练习、设置、外观背景及绘图库通过 `static/offline-storage.js` 读写 `DMateOfflineVault`，绘图库使用异步保存接口。资料按当前设备的浏览器／WebView 存储空间长期保存，无需登录；登录、退出、断网、关闭页面或应用均不切换或清空这份资料。同一存储空间的新标签页共享资料，各标签页保留独立视图。

`static/offline.html` 已加载 vault、业务适配器和 ZIP 备份模块，Service Worker 将它们纳入离线应用外壳缓存。旧本机账号／游客 vault 向设备资料库迁移，原密文来源保留；迁移记录阻止已删除内容在重新打开时被旧来源反复加入。进入离线版直接打开本机工作区，不再自动复制当前在线账号资料；跨工作区或设备转移由用户选择 ZIP 导入。旧版已暂存在本机的交接包仍作兼容迁移。这里的保护范围是离线业务存储，不能据此声称整个浏览器配置或在线版数据都已加密。

网页版完成离线资源准备后，断网会自动转到 `/offline`。首次访问需要联网下载资源。新版 Android 与桌面客户端在构建时打包同一套学习资源，可在浏览器缓存为空时打开离线工作区。客户端仍使用原来的 HTTPS 地址和 `/offline` 路径，因此现有设备资料库及系统密钥可以继续使用。恢复网络后，可在离线工作区点击「在线版」返回。

当前交付是 `main` 中的源码接入，未发布新安装包。已安装的旧 Android/Desktop 1.0.2 客户端没有新桥，必须基于当前源码重建并安装客户端；仅更新远程网页不能补上原生桥。旧原生客户端会明确报 `NATIVE_UNAVAILABLE`，不退回浏览器密钥。

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
- `destroy()` 在核对 vault 身份后，用事务删除该 vault 的记录和元数据，再尽力删除对应原生密钥。当前设备工作区不会因登录退出或游客会话结束调用它。该底层接口不提供恢复功能，也不代表物理安全擦除。

数据库名为 `dmate-offline-vault-v1`，版本 1：

| Store | 内容 |
| --- | --- |
| `vaults` | keyPath `name`；格式、随机 vaultId/keyId、提供者、能力声明、加密校验记录；仅浏览器提供者包含 `CryptoKey` |
| `records` | keyPath `[vault, collection, id]`；revision、IV、认证密文；按 vault、集合建立结构性索引 |

**公开元数据**包括 vault 名称、集合名、记录 ID、记录数量、revision、密文长度和密钥提供者。应使用 `personal-v1`、`notes`、随机 UUID 等结构性标识；不能把笔记标题、邮箱、姓名或搜索词放进这些键。当前工作区使用固定结构性名称 `device-workspace-v1`，记录地址使用 SHA-256 映射；原始业务 ID、标题、正文、Blob MIME 类型、文件名和本机业务时间戳放在加密的 `value` 内。旧账号到随机 vault 名称的加密目录保留为迁移兼容数据。

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

原生操作协议是 `capabilities / create / encrypt / decrypt / delete`。`delete` 用于清理未入库候选密钥，以及在 `destroy()` 已提交删除 vault 后清理不再使用的密钥；普通前端应通过存储 API 管理记录，不能直接删已提交 vault 的 key。桌面锁文件只保存跨进程互斥状态，不含密钥或用户数据。

原生密钥丢失、清理应用数据、浏览器清理站点数据、系统钥匙串重置等可能使资料不可恢复。当前提供学习资料 ZIP 导入导出，不提供密码恢复、云端密钥托管或开发者万能密钥。ZIP 携带可移植的学习内容，不携带 vault 密钥；不能直接把数据库复制成功当成跨设备迁移成功。

## 5. 已接入的业务、迁移与交接

### 业务保存与上下文

工作区通过 `DMateOfflineStorage.open({scope:"device", isCurrent})` 打开 `device-workspace-v1`，提供 `get / all / put / remove / batch / close`。旧 `open({owner, isCurrent})` 与游客接口保留用于旧数据兼容。适配器为每个句柄保存读取到的 revision，并串行处理写入；删除笔记或错题及其删除墓碑使用同一批事务。并发页面修改返回冲突，不无条件覆盖。初始化或解密失败时工作区保持不可编辑，不展示假空库，也不写回旧明文存储。

`offline.js` 的外观及背景 Blob 保存到加密设置记录，不再维护明文离线外观备份。绘图组件通过 `persistence.initialGallery / save` 接收初始快照与异步保存函数，防抖更新、显式保存和确认操作等待保存结果；失败保留当前页面编辑并允许重试，不把尚未提交的内容显示为保存成功。返回在线版前等待笔记及绘图库保存。强制终止页面仍可能丢失尚未提交的编辑，不能将异步保存描述为关机事务。

设备工作区的有效性由自身生命周期决定。账号切换、退出及在线游客会话结束不会使它失效、销毁编辑器或清空资料；当前编辑与画板继续保留。每个设备及浏览器／WebView 存储空间各自独立，资料不因登录同一账号而跨设备自动同步。

### 无需账号的本机生命周期

未登录时与登录后使用同一设备 vault。刷新、关闭后重新打开、新标签页及新的原生启动会话都可读取此前成功提交的本机资料。页面选择、搜索等视图状态按标签页保存，业务内容共享。

设备资料不随游客会话结束清理，旧游客 vault 也作为迁移来源保留。在线版游客对话、图片草稿和在线画板仍执行各自原有的会话规则；这些规则不决定离线工作区的保存期限。

### 旧数据迁移

- 旧 `dmate-offline-workspace` 升级到版本 4，用版本升级/连接关闭协议阻止旧版 IndexedDB 写入；若被旧页面阻塞则提示关闭旧页面后重试。
- 版本屏障不能停用已经加载的旧页面中的 localStorage 写入逻辑，应关闭旧版页面。适配器在迁移锁内读取本机来源及目标，避免并发迁移覆盖资料。
- 旧本机账号与游客加密 vault 中的资料汇入同一设备资料库，原密文来源保留。相同业务内容合并，不同内容保留；旧分区的删除墓碑不会应用到另一份同 ID 内容。
- 迁移日志记录来源、记录及其 revision。未变化的来源不重复恢复，避免本机已删除内容在刷新时再次出现；变化的旧来源可再次检查。
- 旧明文离线库、旧离线图库、外观及背景经加密提交和核对后处理对应旧源；失败保留来源供重试，不承诺跨两个数据库的全局事务。在线原副本保持原样。
- 既有明文 `dmate_offline_migration_v1` 交接槽和已暂存在本机的加密交接包仅作一次兼容迁移；加密导入成功后才清理对应交接。新入口不再创建交接包。

### 旧短期交接的兼容读取

`offline-entry.js` 直接打开 `/offline` 并在后台准备应用资源，不要求登录、在线快照或云同步成功。在线 `DMateOfflineBridge` 仍供用户明确点击“导出数据”时读取对应模块内容。离线版通过 ZIP 导入这些内容，登录前后不会自动增添或替换本机资料。

原生桥仅授权离线路径，在线 `/` 页面不能使用原生 vault。因此 `static/offline-handoff.js` 是单独的短期运输层：**即使在原生客户端中，也使用浏览器管理的不可导出 AES-GCM 密钥，不具有目标 native vault 的 OS 密钥保护。** 它不是 native vault 失败时的业务存储回退，也没有扩大原生 ACL。

交接数据库为 `dmate-offline-handoff-v1`：元数据、JSON、Blob/File 内容按 4 MiB 分块认证加密，结构化克隆的 `CryptoKey` 与密文保存在 IndexedDB；sessionStorage 只保存随机 token。元数据绑定账号、`window.name` 标签页标识和 30 分钟有效期；总编码上限 128 MiB，最多 32 个待完成交接。过期交接不可读取，并在后续操作中尽力清理，不保证页面关闭时立即擦除。

离线目标通过 `read()` 读取但不删除交接，导入实际 vault 并成功提交后才 `ack()` 清除密文、密钥与 token；失败保留交接供有效期内重试。新版原生目标 vault 仍必须使用 OS 密钥，缺桥、缺钥或服务不可用时停止，不能将运输层当作已完成的业务保存。

**在线原副本、在线图库、原有账号同步和其他在线持久化不在本次离线保密范围内，不因进入离线版而删除，也不自动替换为 vault。** 离线修改不会自动回传或云备份；Cache Storage 只缓存应用与学习资源，不保存解密后的个人资料。

## 6. 验证方法

```sh
node scripts/test_offline_vault_browser.cjs
node scripts/test_offline_storage_browser.cjs
node scripts/test_offline_handoff_browser.cjs
python3 scripts/test_android_offline_vault.py
node scripts/test_desktop_offline_vault.cjs
cargo test --locked --manifest-path desktop/src-tauri/offline-vault/Cargo.toml
cargo check --locked --manifest-path desktop/src-tauri/Cargo.toml
```

上述 vault/storage/handoff 浏览器脚本各自启动本地 HTTP 测试服务，使用真实 IndexedDB 和 Web Crypto。vault 底层脚本的 `DMATE_TEST_BROWSER` 可选 `chromium`、`firefox`、`webkit`，也可指定 `DMATE_BROWSER_EXECUTABLE`；新增业务脚本默认使用 Chromium。测试包括并发建库、持久化重开、CAS 和整批失败、密文/IV/AAD 调换、丢钥不重建、关闭在途读取、嵌套 Blob、没有网络或 Web Storage 明文旁路、原生不可用不降级、设备资料迁移和登录独立性，以及旧交接包的账号/标签页/有效期及失败保留。

实际 UI 与绘图异步保存回归需要先启动本地 Flask 应用，再运行：

```sh
DMATE_TEST_BASE_URL=http://127.0.0.1:5000 node scripts/test_offline_vault_workspace_browser.cjs
DMATE_TEST_BASE_URL=http://127.0.0.1:5000 node scripts/test_drawing_async_persistence_browser.cjs
```

UI 回归检查真实离线编辑、重开恢复、旧资料迁移、二进制背景和持久化内容中没有私密正文旁路。绘图回归在桌面及移动视口模拟延迟提交、容量错误、确认等待、失败重试和图库重新挂载。接口采用本地 fixtures；这些测试不调用真实模型、OCR、登录或云同步 API。工作区 CI 固定 Ubuntu 24.04 以匹配当前 Playwright 版本，原生底层另有独立工作流。

Android JDK 测试执行生产协议/密码学实现，密钥提供者为内存模拟；桌面 Rust 单测也使用测试密钥提供者，JS 桥测试使用受控环境。它们不冒充真机硬件验证。真实 OS 凭据库往返测试明确标记 ignored，需在目标机器解锁密钥库后手动运行；Android 还需要真机/模拟器验证 KeyStore 与 WebView 生命周期。Playwright WebKit 也不等于已经在用户的 iPhone/iPad 上验收。

本次接入环境已运行 Android 协议/密码学测试与 Desktop JS 桥测试，但没有安装 Cargo，未在该环境执行 Rust/Tauri 编译；不能用 JS 通过替代目标平台构建、真实密钥库验证或新安装包验收。

## 7. 一手依据

- [W3C Web Cryptography：密钥存储与安全边界](https://www.w3.org/TR/webcrypto-1/#security-considerations-authors)
- [W3C IndexedDB：事务生命周期](https://www.w3.org/TR/IndexedDB-3/#transaction-lifecycle)
- [W3C IndexedDB：同源目录不隔离](https://www.w3.org/TR/IndexedDB-3/#security-cross-directory)
- [NIST SP 800-38D：GCM 认证加密](https://csrc.nist.gov/pubs/sp/800/38/d/final)
- [Android Keystore](https://developer.android.com/privacy-and-security/keystore)
- [Android 的 unlockedDeviceRequired 版本限制](https://developer.android.com/reference/android/security/keystore/KeyGenParameterSpec.Builder#setUnlockedDeviceRequired(boolean))
- [Tauri capabilities](https://v2.tauri.app/security/capabilities/)
- [keyring 的平台实现与 features](https://docs.rs/keyring/3.6.3/keyring/)
