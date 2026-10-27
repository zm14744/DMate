# 部署说明

## 1. 当前部署形态

- 产品：DMate（离散数学智能辅学系统）
- Web 框架：Flask 3.1.2
- WSGI Server：Gunicorn 23.0.0
- 容器基础镜像记录：`python:3.10-slim`
- OCR：PaddlePaddle / PaddleOCR CPU 推理
- 账号与同步数据库：PostgreSQL + Psycopg 3
- 邮件：Brevo API 主通道 + SMTP 备用
- 当前部署平台：Zeabur
- 部署历程：Render → Zeabur
- 当前在线域名：https://dmate.zeabur.app
- 当前服务器记录：Tencent Seoul 2C 4GB
- 当前服务器费用记录：US$4/月；Zeabur **首次开通一次、续费一次、共两次付款**。若每次均按页面标价 US$4 收取，则两次名义费用约 US$8；最终金额请以两笔实际账单为准。
- **2026-10-13 新截图**：DeepSeek API 累计消费 **¥103.65**、充值余额 **¥16.34**；2026-10-08 的 ¥101.96 / ¥8.03 保留为历史快照，两个指标不能相减解释为“本轮总投入”，也不包括 Zeabur 等服务。

## 2. Gunicorn

启动命令记录：

```text
gunicorn -w 1 --threads 8 --timeout 300 -b 0.0.0.0:${PORT:-8080} app:app
```

当前限流实现保存在单个 Python 进程内，因此当前 1 worker 配置与该实现保持一致；若未来增加多 worker，需要同步调整限流设计。

四图识别需要 8 个 HTTP 线程承载并行上传以及取消、健康检查等请求；本地高内存推理由共享调度器串行执行。若平台覆盖 Docker 启动命令，请同步修改。当前识别与编辑确认流程见 [fast-editable-workflow.md](fast-editable-workflow.md)。

## 3. 核心环境变量

### AI

```text
DEEPSEEK_API_KEY
DEEPSEEK_CHAT_MODEL
DASHSCOPE_API_KEY
DASHSCOPE_VISION_API_URL
QWEN_VISION_MAX_OUTPUT_TOKENS
VISION_ANALYSIS_ENABLED
DEEPSEEK_MAX_OUTPUT_TOKENS
MEDIUM_MAX_OUTPUT_TOKENS
```

代码当前默认：

- `DEEPSEEK_CHAT_MODEL=deepseek-flash`（数学解题仍使用 DeepSeek / 可选鲁信路由）
- 图片视觉理解固定使用 `qwen3-vl-235b-a22b-thinking`，包括独立逐边复核；不使用 DeepSeek Vision 作为备用
- `DASHSCOPE_API_KEY` 必填，Zeabur 环境变量中设置，严禁写入 GitHub 或客户端
- `DASHSCOPE_VISION_API_URL` 可选，默认北京地域兼容接口 `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`；若使用其他地域，需填写对应地域 URL 并使用该地域的 Key
- `QWEN_VISION_MAX_OUTPUT_TOKENS=12000` 可选；包含思考 Token，较高上限会增加成本
- 缺少百炼 Key 时，视觉识别无法运行；仍保留 PaddleOCR 文字识别降级，但不悄悄调用 DeepSeek Vision。部署后需实际测试 /ocr
- 普通回复使用 `DEEPSEEK_MAX_OUTPUT_TOKENS`；`high` 思考（解题中的中等与困难共用）使用 `MEDIUM_MAX_OUTPUT_TOKENS`。本源码不使用 `HARD_MAX_OUTPUT_TOKENS` / `max` 档。

### 可选鲁信文本通道

```text
LUXIN_API_KEY
LUXIN_MODEL_ID
LUXIN_ENABLED
LUXIN_API_URL
LUXIN_MODELS_URL
LUXIN_CIRCUIT_BREAKER
LUXIN_CIRCUIT_COOLDOWN_SECONDS
LUXIN_PROBE_CONNECT_TIMEOUT
LUXIN_PROBE_READ_TIMEOUT
LUXIN_HEALTH_URL
```

未配置或不可用时自动使用 DeepSeek 文本兜底。

### PostgreSQL / 账号系统

优先使用：

```text
DATABASE_URL
```

也兼容：

```text
POSTGRES_CONNECTION_STRING
POSTGRES_URL
PGHOST / PGPORT / PGDATABASE / PGUSER / PGPASSWORD
POSTGRES_HOST / POSTGRES_PORT / POSTGRES_DATABASE / POSTGRES_USERNAME / POSTGRES_PASSWORD
```

账号系统密钥：

```text
AUTH_SECRET_KEY
```

`SECRET_KEY` 可作为兼容回退，但部署时建议明确设置 `AUTH_SECRET_KEY`。

Cookie：

```text
SESSION_COOKIE_SECURE
```

默认开启，生产环境应保持 HTTPS。

### 邮箱验证码

Brevo 主通道：

```text
BREVO_API_KEY
BREVO_SENDER_EMAIL
BREVO_SENDER_NAME
```

SMTP 备用：

```text
SMTP_HOST
SMTP_PORT
SMTP_USERNAME
SMTP_PASSWORD
SMTP_FROM_EMAIL
SMTP_FROM_NAME
SMTP_USE_SSL
```

代码默认 SMTP host 为 `smtp.qq.com`、端口为 `465`、SSL 开启；只有在 Brevo 调用失败且 SMTP 配置完整时才自动走备用通道。

### Web

```text
PORT
```

直接运行 `app.py` 默认 5000；容器启动记录默认 8080。

### 可选分发地址

安装弹窗默认使用 GitCode 的 `v1.0.1` 下载接口作为国内主链接，并保留 GitHub 对应安装包的独立下载直链作为海外备用。Microsoft Store、Snap Store 和 iPhone/iPad 描述文件仍保留。

以下环境变量只用于覆盖首选下载源，不影响 DMate 核心学习功能；若未填写，默认使用 GitCode。如果旧值仍是 `https://github.com/zm14744/DMate/releases/...`，前端会自动将其识别为 GitHub 备用链接，不会盖过 GitCode 主链接。

```text
ANDROID_APK_URL
DESKTOP_WINDOWS_URL
DESKTOP_MACOS_URL
DESKTOP_LINUX_DEB_URL
DESKTOP_LINUX_APPIMAGE_URL
```

## 4. 数据库初始化

账号表由 `app.py` 在首次需要账号功能时检查并创建 / 补列：

```text
dm_users
dm_user_data
dm_email_codes
```

已有旧账号表会通过 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 自动补齐邮箱、恢复码与 `auth_version` 字段，不要求手工执行单独迁移 SQL。

## 5. 本地运行

最低产品核心：

```bash
python -m pip install -r requirements.txt
export DEEPSEEK_API_KEY="your-key"
python app.py
```

若需要完整账号功能，还需提供 PostgreSQL DSN 与 `AUTH_SECRET_KEY`；若需要邮箱注册 / 重置，还需 Brevo 或 SMTP 配置。

Windows PowerShell 示例：

```powershell
$env:DEEPSEEK_API_KEY="your-key"
$env:DATABASE_URL="postgresql://..."
$env:AUTH_SECRET_KEY="your-long-secret"
python app.py
```

## 6. OCR 启动

`app.py` 启动后会在后台线程预热 OCR 模型。`/ready` 用于观察：

- OCR 模块是否可导入；
- OCR 模型是否完成预热；
- 公式识别是否正常或降级。

模型：

```text
PP-OCRv6_small_det
PP-OCRv6_small_rec
PP-FormulaNet_plus-S
```

## 7. 健康检查

```bash
curl https://dmate.zeabur.app/health
curl https://dmate.zeabur.app/ready
```

## 8. 关键静态检查

```bash
python -m py_compile ai.py app.py teaching.py ocr.py
node --check static/script.js
```

2026-10-08 当前代码执行上述语法检查通过；`knowledge_graph.json` 为 10 个模块分类、68 个节点。

## 9. 产品能力更新：是否需要重新生成安装包？

工程中 `desktop/src-tauri/tauri.conf.json` 的远程页面地址以及 `android/app/build.gradle` 的 `DMATE_URL` 均指向 `https://dmate.zeabur.app`。已安装的桌面 / Android 客户端因此加载服务器上的 DMate 网页，而不是携带完整本地网页与 Python 后端。

| 修改内容 | 发布操作 | 已安装客户端 |
|---|---|---|
| `app.py`、`teaching.py`、`knowledge_graph.json`、`ai.py`、`ocr.py` | 更新服务端代码并让 Zeabur 成功部署 / 重启应用 | 新请求使用新版能力，通常无需重新安装 |
| `static/script.js`、`templates/index.html`、网页样式 / 图标 | 更新 Zeabur 站点，客户端刷新或重新打开 | 从远程站点读取新版，可能受缓存影响 |
| `android/` 下的 Java、Manifest、Gradle、原生资源 | 重新构建、签名并分发 APK | 需要安装新版 APK |

**2026-10-28 兼容性修复：** 已恢复 GitHub Release 中原有的已签名 Android **1.0.1** APK，取消自动覆盖发布。旧安装版图片选择控件会由服务端 JavaScript 针对 1.0.1–1.0.4 WebView 使用单张文件选择（可连续上传，最多仍为四张），并监听 `input`/`change`，以避免部分系统文件多选无响应。旧版原生文件选择器若本身不能返回文件，该问题不能仅靠服务端脚本百分百消除；上线后必须真机检验。

| `desktop/src-tauri/` 下的配置、Rust、权限、窗口及原生资源 | 重新构建并分发新的桌面安装包 | 需要安装新版安装包 |

**操作顺序**：提交变更 → Zeabur 部署完成 → 通过 `/health` 与 `/ready` 观察服务状态 → 在网页和已安装客户端各测试一轮重点功能。对本次产品能力变更，重点检查图同构、二部图、拓扑排序、模逆 / CRT、齐次与非齐次递推，以及同知识点出题是否偏题。本项目已有 175 项个人功能自测结果记录；部署新版时仍应针对本次实际改动复测 AI 出题、OCR、复制、账号同步与移动端交互，不能仅因既往记录为通过便视为新部署完成验收。

请注意：**工程目前没有启用 Tauri 自动更新器或 Android APK 自动更新机制**。远程网页与后端可以不重装而获得更新，不代表安装包的原生代码会自动升级。iOS WebClip 打开的是在线官网，不提供独立离线缓存。


### 2026-10-08 OCR 与移动端修复的部署检查

本轮网页端更新涉及 `app.py`、`ai.py`、`templates/index.html`、`static/script.js`。更新 Zeabur 并刷新/重开客户端后，Windows/Tauri 与 Android/WebView 远程网页壳可获得相应网页功能，不必重新生成 EXE/MSI/APK；**原生安装包文件本身不会自动升级**。验证 OCR 识别时入口隐藏且布局补位、手机核对按钮固定底部及内容滚动、明显非题目图返回 422、纯图题仍允许核对。刷新后若页面仍旧，检查浏览器/WebView 缓存及服务器部署版本。

## 10. 2026-10-13 多平台分发与 GitHub Actions

当前仓库已有三个不同用途的 Actions 流程：

| 流程 | 路径 | 职责 |
|---|---|---|
| Build DMate Desktop | `.github/workflows/build-desktop.yml` | Windows `nsis`、Linux `deb,appimage`、macOS `universal-apple-darwin dmg`；生成构建 Artifact，不等于应用商店发布。 |
| Build DMate Android | `.github/workflows/build-android.yml` | 构建 Android **debug APK** Artifact；不等于已自动完成商店签名与正式发布。 |
| Build DMate Snap (GitHub) | `.github/workflows/build-snap.yml` | Ubuntu 24.04 Runner 构建 Tauri DEB，再由 Snapcraft 打包 `dmate_1.0.0_amd64.snap`。 |
| Publish DMate Snap to Snap Store | `.github/workflows/publish-snap.yml` | 使用 GitHub Secret 认证 Snap Store，已有修订选 `promote-existing`，全新构建才选 `upload-new-build`。 |

`snap/snapcraft.yaml`：`name: dmate`，`version: 1.0.0`，`base: core24`，`confinement: strict`，平台 **amd64**，GNOME 扩展并带 WebKitGTK 4.1 运行依赖。2026-10-13 的发布日志显示 Revision 1 已正式发布到 `stable`：`Released 'dmate' revision 1 to channels: 'stable'`。重复上传完全相同 Snap 曾在 Store 唯一性校验处失败，因此现有 revision 应直接 `snapcraft release` 而非二次上传。

安全约束：`SNAPCRAFT_STORE_CREDENTIALS` 只应放在 GitHub Actions Repository Secret，不可提交到仓库、放进 README 或公开日志；本机临时凭据使用后可删除。不能将 `workflow_dispatch` 的成功视为最新安装包一定上线，需要检查对应 Job 和 Store revision。

## 11. 多平台安装与分发（更新至 2026-10-19）

- **Windows**：使用 Tauri NSIS EXE；可通过 Microsoft Store、GitCode、GitHub Release 或 itch.io 获取。
- **macOS**：通用 DMG 的 CI 已区分开发测试版与正式公证版。只有设置六项 Apple Developer Secret 且签名/公证校验成功后才上传 `DMate-macos-SIGNED-NOTARIZED`；否则标记为 `DMate-macos-UNSIGNED-TEST-ONLY`。旧 GitHub Release / GitCode / itch.io DMG 不会被自动替换；详情见 [macOS 签名与公证](MACOS_DISTRIBUTION.md)。
- **Linux AMD64**：提供 DEB、AppImage 与 [Snap Store](https://snapcraft.io/dmate)。Snap 需要 `snapd`，并且只确认 AMD64 发行。
- **Android**：使用独立 WebView APK，通过 GitCode、GitHub Release 或 itch.io 分发。
- **iPhone / iPad**：目前没有独立安装包，直接通过浏览器访问官网。旧的 `/DMate.mobileconfig` WebClip 路由已移除。
- **网页安装流程**：Web App Manifest、Service Worker 注册、`/pwa/`、`/install`、PWA 安装说明和 iOS WebClip 安装入口均已移除。网页安装弹窗只展示平台安装包和应用商店链接；仅保留一次性清理旧版 Service Worker/缓存的兼容代码。

商店发布、安装包可下载、设备实机安装与搜索结果收录是不同状态，应分别记录；不要将构建成功或申请受理表述为所有设备已通过验收。

## 12. SEO 与部署验收

2026-10-13 首页增加更完整的 Meta Description、DMate H1、图标 Alt 及 Bing / 百度站点验证元标签；百度站点验证已通过并提交 `https://dmate.zeabur.app/`。**2026-10-14 更新：开发者已确认 Bing 公开搜索能够找到 DMate**，此前站长后台也显示过索引成功；Bing 可检索并不保证持续排名或所有地区关键词可见。**百度目前仍在审核/等待进一步收录反馈**，链接提交不等于正式索引成功。

部署后建议先在 Zeabur 确认新版容器 **Running / Ready**，再 `GET /health` 和 `GET /ready`，随后检查 `view-source:https://dmate.zeabur.app/` 中新 H1、验证标签是否实际生效。若源代码仍旧，优先排查 Zeabur 部署状态和浏览器 / WebView 缓存，不要仅凭 GitHub 提交成功即认为生产版本已更新。

截至本次文档整理，未确认项目已单独配置 `robots.txt`、`sitemap.xml` 或 canonical，**这三项属于待办而非已完成**。

## 13. 建议的最小发布与回滚核对流程（2026-10-13 文档补充）

1. **确认源版本**：记录 Git 提交 SHA、相关配置和数据库迁移范围；检查环境变量名称是否齐全，不在日志/截图中披露值。
2. **部署后端与网页**：等待 Zeabur 完成构建并显示运行中，再分别检查 `/health` 与 `/ready`。OCR 可能需要额外初始化时间。
3. **刷新远程客户端**：在桌面浏览器、Tauri、Android WebView 分别完全关闭并重开页面；对于缓存问题，先比较 HTTP 响应与实际脚本版本，不要通过删除服务来清除旧网址。
4. **冒烟验证核心学习链**：至少核验一个文字题、一个含图图片题、一个一般出题、一个“出题并给答案”、一个错题复测、多知识点复测，以及数学公式复制和图谱打开。
5. **账号状态检查**：注册或登录测试账号，在另一浏览器同步，触发一次冲突提示；确认退出后账号数据不混入游客会话。
6. **按构建类型分发**：仅 Web/后端改动无需重打远程网页壳；Android/桌面原生代码和包元数据变化必须重构并安装验证。Snap 上传和 `stable` 渠道提升应分开操作。
7. **失败时回滚**：回到已知正常的应用提交/镜像，确认 `/health`、`/ready` 和核心对话恢复。数据库 schema 改动需事先制定独立回滚方案；不可直接假设代码回滚等于数据回滚。

**通过标准**：静态检查通过只是进入发布验收的前置条件；不能替代在线 API、OCR 真机、客户端和账户/数据库端到端验证。测试记录与当前未验证清单见 [`TESTING.md`](TESTING.md) 与 [`RELEASE_CHECKLIST.md`](RELEASE_CHECKLIST.md)。


## 14. 恢复旧安装包，网页功能不再触发安装升级（2026-10-28）

此前临时上传的 Android 1.0.4 曾覆盖 GitHub `v1.0.1` 发行页中原有的 `DMate.apk`。已经从仓库的 `v1.0.1` 标签重新构建、使用原签名校验并恢复了发行文件，公开 Android 安装包恢复为 **1.0.1（versionCode 2）**。Windows、macOS、Linux 的原发行文件未改。

**目前不再提供新版安装包提醒和下载更新提示**：网页不加载 `static/client-update.js`，兼容用的 `static/client-updates.json` 标记 `published:false`；Android 正式构建工作流取消了推送触发和自动覆盖 Release，只能手动生成待验证的构建 Artifact，不会自动发布。新增的原生 APK 下载及请求安装通道已从当前源码清理，不申请 `REQUEST_INSTALL_PACKAGES` 权限。

网页安装弹窗恢复原先 Android 的 GitCode、GitHub APK 下载按钮、顺序及「选择 APK 下载源」说明；其他平台选项保持不变。服务端部署更新后，已安装 Android WebView / 桌面 Tauri 的**网页与后端功能**应通过在线版本检查和无缓存资源同步；**不能直接替换已安装程序中的旧 Android Java/Tauri Rust 原生代码**。若旧 ROM 的本机文件选择器回调失败，仍需要针对该设备进行原生修复并由用户安装对应构建；不能把静态 CI 通过当作实机验收。

## 15. 旧安装版自动同步最新版网页（不需要重新安装）

DMate 的 Android WebView 与电脑 Tauri 安装壳都以 Zeabur 远程地址为首页。旧版 Service Worker 曾通过 `/service-worker.js` 注册，2026-10-19 删除 PWA 时直接删除此脚本，导致某些旧设备的缓存注册在无法获取新 Worker 脚本时难以完成清理。

现在 **恢复旧路径的清退响应**，实际代码来自 `static/legacy-worker-retire.js`：仅 `skipWaiting`、删除 `dmate-pwa-*`、`dmate-ios-webapp-*`、`dmate-store-pwa-*` CacheStorage 缓存并 `unregister()`，不注册新 PWA、不缓存、不拦截任何 fetch。新网页自身已有老 Worker 清理，服务端关键 JS/CSS/JSON 改为 `no-store`，`/web-version` 提供进程启动时代码清单的 SHA-256，首页将 SHA 注入所有主要脚本/样式的 `?v=` 地址。安装版通过 `static/web-sync.js` 在启动、切回前台、页面恢复、网络恢复和定期检查此 SHA；发现新版且没有输入内容、未完成识图任务、活跃编辑器或其他工作时，自动跳转带版本参数的最新首页；用户正在操作时延后重载，以免丢失输入或识图草稿。没有 Service Worker 重新安装，没有清除登录 Cookie、IndexedDB 或 localStorage。

**能力边界**：这解决旧安装壳里网页代码及服务端图论识别功能的版本同步问题，不能把 Android APK 中旧的 `WebChromeClient.onShowFileChooser` 或 Tauri Rust 原生功能直接替换。若 WebView 系统图片选择器本身仍在系统层立即退出，新网页的真实 `<input type=file>` 点击修复可能有效，但仍需要该设备实测；旧 APK 的原生故障不能靠缓存机制无条件修复。
