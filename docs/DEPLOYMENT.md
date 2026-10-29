# 部署与配置

本文面向自托管和维护人员，说明如何启动当前仓库、为不同功能补齐服务、保存运行数据，以及更新网页和客户端。日常操作见[使用指南](USER_GUIDE.md)，HTTP 字段见 [API](API.md)。

## 先确定需要哪些功能

应用不是必须连接所有外部服务才能打开。可以先启动网页，再按需要配置功能：

| 部署范围 | 需要准备 | 未准备时的表现 |
| --- | --- | --- |
| 打开页面、手工编辑画板、查看内置知识图谱 | Python 服务及静态资源 | 服务未启动时页面无法访问 |
| AI 教学、出题、错题分析、概念分析、绘图指导 | DeepSeek Key 和服务网络 | 相关 AI 请求返回配置或服务错误，不能因此判断画板或页面本身损坏 |
| 网页自动识图、选区图形重识别 | DashScope Key、可访问的视觉服务地址 | 自动扫描与图形选区重识别不能完成；独立画板仍可使用 |
| 文字框识别 | Paddle 依赖、官方模型包、可写缓存、足够的进程内存 | 选区 OCR 报初始化、缓存或资源错误；它不使用 DeepSeek Key |
| 语音转文字 | DashScope 语音权限、模型与词库、浏览器麦克风权限 | 不能录音或转写，文字输入仍可使用 |
| 注册、登录、云同步 | PostgreSQL、稳定的认证密钥 | 游客工作区可使用，账号操作不可用 |
| 邮箱注册、邮箱绑定、邮件找回 | 上述账号配置，加 Brevo 或 SMTP | 邮箱验证码无法发送；已有可用账号的其他登录方式不由邮件服务替代 |

识图与语音可使用同一个服务凭据，但仍需分别开通相应模型和词库权限。数据库不存储模型密钥；前端和客户端安装包也不应包含这些密钥。

## 运行方式

应用由 Flask 提供网页与 API，以 Linux 运行环境为基线；本地 worker 使用 `fcntl` 等系统能力，Windows 自托管应使用 WSL2 或 Linux 容器。Dockerfile 使用 `python:3.10-slim`，安装 `requirements.txt`（包含 `requirements-agents.txt`），并预下载本地文字 / 版面模型。Docker 构建和首次本地模型下载需要访问 Python 包源及 Paddle 官方模型源。

本地开发可按 [README](../README.md) 建立 Python 3.10 虚拟环境后运行 `python app.py`，默认监听 `0.0.0.0:5000`，`PORT` 可覆盖端口。Linux 系统依赖以 Dockerfile 的 `libgl1`、`libglib2.0-0`、`libgomp1`、`libsm6`、`libxext6`、`libxrender1` 为准。

### Linux 本地启动

以下命令在仓库根目录执行。先确保系统已提供 Python 3.10 和 venv；Debian / Ubuntu 系统库示例如下，其他发行版安装对应包：

```bash
sudo apt-get update
sudo apt-get install -y libgl1 libglib2.0-0 libgomp1 libsm6 libxext6 libxrender1
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

然后只导出需要使用的配置，例如：

```bash
export DEEPSEEK_API_KEY='replace_with_your_key'
export DASHSCOPE_API_KEY='replace_with_your_key'
export DASHSCOPE_VISION_API_URL='https://your-authorized-host/compatible-mode/v1'
python app.py
```

浏览器打开 `http://localhost:5000/`。示例占位值必须替换为自己的配置；不使用的服务可以不设置。配置在模块初始化时读取，项目没有在此之前自动加载 `.env` 的步骤，需由 shell、进程管理器或托管平台事先注入变量，不能仅创建文件就假设配置生效。

`python app.py` 适合本地开发；对外运行使用 Gunicorn，并交给容器平台或进程管理器处理重启、日志及 HTTPS。非容器生产启动可使用：

```bash
gunicorn -w 1 --threads 8 --timeout 300 -b 127.0.0.1:8080 app:app
```

绑定 `127.0.0.1` 的示例供同机反向代理连接；容器通常绑定 `0.0.0.0`。修改 `PORT` 后，端口映射、代理目标与平台监听端口需一致。

### Docker 部署

容器构建与启动示例：

```bash
docker build -t dmate .
docker run --rm -p 8080:8080 --env-file /secure/path/dmate.env \
  -v dmate-state:/data \
  -e DMATE_GRAPH_CONFIRMATION_DB=/data/graph-confirmations.sqlite3 dmate
```

示例中的环境文件由部署者在仓库外准备，只在运行时注入。Dockerfile 默认启动：

```bash
gunicorn -w 1 --threads 8 --timeout 300 -b 0.0.0.0:${PORT:-8080} app:app
```

保持单 worker、多线程：上传准入、取消、限流及本地推理调度仍是进程内状态。直接增加 worker 或副本不能获得统一配额与取消行为；图形确认使用 SQLite 也不意味着这些其他状态已经共享。高内存的本地模型由调度器限制并发，视觉请求不持有本地模型租约。

环境文件使用 Docker `--env-file` 的 `KEY=value` 格式，不写 `export`，例如：

```dotenv
PORT=8080
DEEPSEEK_API_KEY=replace_with_your_deepseek_key
DASHSCOPE_API_KEY=replace_with_your_dashscope_key
DASHSCOPE_VISION_API_URL=https://your-authorized-host/compatible-mode/v1
DATABASE_URL=postgresql://dmate:replace_password@your-db-host:5432/dmate
AUTH_SECRET_KEY=replace_with_a_long_random_stable_secret
SESSION_COOKIE_SECURE=1
DMATE_GRAPH_CONFIRMATION_DB=/data/graph-confirmations.sqlite3
```

只需要游客模式时，数据库与认证配置可省略。不要把示例占位值用于正式服务。认证密钥可在自己的运行环境用 `python -c 'import secrets; print(secrets.token_hex(32))'` 生成一次，保存到平台 Secret 后持续复用。

镜像构建除了安装依赖，还会预备 OCR 模型包和生成跨平台图标；不是仅复制 Flask 文件。`scripts/generate_icons.py` 的源图位于 Android 资源目录，因此自定义构建上下文时应保留该图标输入，不能把整个 `android/` 目录一并排除。应用源码更新后重新构建镜像，正常情况下依赖和模型包层可复用缓存。

## 模型服务

| 变量 | 当前用途与默认值 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 教学、出题、答案诊断、笔记分析、绘图指导所需 |
| `DEEPSEEK_CHAT_MODEL` | 默认 `deepseek-flash`；文本地址固定为 `https://api.deepseek.com/chat/completions` |
| `DEEPSEEK_MAX_OUTPUT_TOKENS` | 默认 5000，限制在 2000–6000 |
| `MEDIUM_MAX_OUTPUT_TOKENS` | high 思考输出预算，默认 8000，上限 12000，且不小于普通预算 |
| `DASHSCOPE_API_KEY` | 网页自动识图和语音所需；兼容回退名 `DASHSCOPE_VISION_API_KEY` |
| `DASHSCOPE_VISION_API_URL` | 视觉地址，优先于 `QWEN_VISION_API_URL`、`DASHSCOPE_API_URL` |
| `ZHIPU_API_KEY` | 兼容识别路径中的可选 GLM 复核，当前网页 `auto_graph` 不使用 |

视觉地址未设置时使用仓库配置的北京工作空间：`https://ws-vh8am794i98a2gxt.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`。可填兼容 API 基址或完整 `/chat/completions` 地址；其他地域或工作空间应设置自身有权限的地址，不能只替换 Key 后假设可访问原工作空间。

当前网页上传显式发送 `workflow=auto_graph`：主读与按需局部复核均固定 `qwen3.8-flash`、开启思考，最多两次视觉调用，无其他提供商降级。无 `workflow` 的 `/ocr` 在默认 `DMATE_GRAPH_NEXTGEN=1`、`DMATE_GRAPH_PIPELINE=agent-tools` 下使用另一条兼容路径；`DMATE_GRAPH_PIPELINE=evidence-two-pass` 或 `DMATE_GRAPH_NEXTGEN=0` 选择其他后端路径。这些开关不能视为更换网页自动识图模型的配置，具体见[识别流程](RECOGNITION.md)。

兼容视觉配置还包括 `VISION_ANALYSIS_ENABLED`（默认开启）、`QWEN_VISION_ENABLE_THINKING`（默认关闭）、`QWEN_VISION_MAX_OUTPUT_TOKENS`（默认 6000，4096–6000）及 `QWEN_VISION_THINKING_BUDGET`。它们不覆盖网页 `auto_graph` 中显式固定的模型与思考参数。文本当前只使用 DeepSeek，已无 `LUXIN_*` 通道配置。

### 语音配置

语音默认复用上述 DashScope Key 与视觉地址的主机；`DMATE_ASR_API_URL` 可指定独立 HTTPS 主机，实际服务路径固定为 `/api/v1/services/aigc/multimodal-generation/generation`。

| 变量 | 默认值 |
| --- | --- |
| `DMATE_ASR_MODEL` | `qwen-audio-3.1-asr-flash` |
| `DMATE_ASR_VOCABULARY_ID` | `vocab-dmate-60d8d29883164a5a83fdfbb7f21772a9` |

应确保凭据、主机、模型和词库属于可访问的服务配置。语音每次只发起一次同步请求，不自动换模型、去掉词库或重试 POST；浏览器需 HTTPS 与麦克风授权。

## 本地模型与缓存

当前网页自动读图不先运行整图 OCR。自主框选的文字识别使用 `PP-OCRv6_small_det`、`PP-OCRv6_small_rec`；其他识别路径还可能使用 `PP-DocLayoutV3` 和几何工具。worker 隔离运行，Paddle API Key 不传入本地模型子进程。

Docker 构建运行 `scripts/prepare_ocr_model_cache.py` 下载这三个官方包并验证文件与清单，不初始化推理。容器默认 `DMATE_MODEL_CACHE_DIR=/opt/dmate-model-cache`，其下使用 `paddlex` 目录。运行用户必须能写缓存及临时目录；已有 `PADDLE_PDX_CACHE_HOME` 配置也会优先参与缓存选择。

本地 Linux 可预备到可写目录：

```bash
export DMATE_MODEL_CACHE_DIR="$PWD/.model-cache"
python scripts/prepare_ocr_model_cache.py --cache-dir "$DMATE_MODEL_CACHE_DIR"
python scripts/prepare_ocr_model_cache.py --cache-dir "$DMATE_MODEL_CACHE_DIR" --verify-only
```

`--verify-only` 检查包文件与清单，不执行文字识别，也不验证云模型凭据。缓存选择顺序为显式 `PADDLE_PDX_CACHE_HOME`、`DMATE_MODEL_CACHE_DIR/paddlex`、`XDG_CACHE_HOME/dmate/paddlex`、当前系统用户的临时缓存；目录需要能实际创建和写入子文件。只挂载空目录覆盖镜像内的缓存，会遮住预下载内容，应先复制或重新准备所需模型包。

本地推理在短生命周期子进程中运行，Web 进程不预加载 Paddle 模型。worker 的 RSS 边界为 1600 MiB，并为容器其余部分预留 768 MiB；准入判断还考虑 cgroup 可用内存。它不是“给容器设置 1600 MiB 就足够”的资源承诺，Web、图像解码、并发请求和系统占用还需要空间。资源不足时先降低并发和图片复杂度，检查容器内存，再调整部署资源，避免通过增加 Web worker 放大内存占用。

## 账号、数据库与邮件

账号功能需 PostgreSQL 驱动、数据库连接和稳定的签名密钥：

| 配置 | 说明 |
| --- | --- |
| `DATABASE_URL` | 首选 PostgreSQL DSN；也接受 `POSTGRES_CONNECTION_STRING`、`POSTGRES_URL` |
| `PGHOST`、`PGPORT`、`PGDATABASE`、`PGUSER`、`PGPASSWORD` | 未提供 DSN 时组合连接，端口默认 5432 |
| `POSTGRES_HOST`、`POSTGRES_PORT`、`POSTGRES_DATABASE`、`POSTGRES_USERNAME`、`POSTGRES_PASSWORD` | 上述分项的兼容名称 |
| `AUTH_SECRET_KEY` | Cookie 签名及验证码摘要所需；兼容 `SECRET_KEY`，重启 / 副本间保持稳定 |
| `SESSION_COOKIE_SECURE` | 默认开启；仅本地 HTTP 调试设为 `0` |

账号表在首次需要时创建并补列：`dm_users`、`dm_user_data`、`dm_email_codes`。数据库用户需相应建表和修改表权限；生产备份 PostgreSQL。未配置账号系统仍可使用游客页面，注册 / 登录 / 云同步不可用。

部署顺序建议为：创建 PostgreSQL 数据库与专用用户，配置连接及稳定认证密钥，再启动应用。数据库不由本仓库启动命令自动安装。DSN 中的特殊字符按 PostgreSQL URI 规则编码，托管数据库要求 TLS 时在 DSN 中附上平台要求的参数。`AUTH_SECRET_KEY` 改变会使既有签名会话失效，也影响仍在有效期内的验证码摘要，不能每次容器启动重新随机生成。

邮箱注册、绑定及找回需要至少一个邮件通道：

- Brevo：`BREVO_API_KEY`、`BREVO_SENDER_EMAIL`，可选 `BREVO_SENDER_NAME`（默认 DMate）。发件人可回退 `SMTP_FROM_EMAIL` / `SMTP_FROM_NAME`。
- SMTP：`SMTP_HOST`（默认 `smtp.qq.com`）、`SMTP_PORT`（默认 465）、`SMTP_USERNAME`、`SMTP_PASSWORD`、`SMTP_FROM_EMAIL`（默认用户名）、`SMTP_FROM_NAME`（默认 DMate）、`SMTP_USE_SSL`（默认开启）。关闭 SSL 模式时使用 STARTTLS。

两者均配置时先用 Brevo，失败后使用 SMTP；仅配置 SMTP 时直接使用 SMTP。凭据属于服务端部署配置，不放进前端或安装包。

发件邮箱还需满足邮件服务商的验证和授权要求。SMTP 密码通常是该服务要求的应用密码或授权码，不能假设普通邮箱登录密码可用。验证码有效期 10 分钟，重复发送至少间隔 60 秒，每用途 / 邮箱还有发送量及尝试次数限制；出现 429 时不要通过循环请求规避限制。

## 代理、容量与运行诊断

反向代理使用 HTTPS，上传请求体至少容纳应用允许的请求，超时应覆盖后端请求预算。只把真实可信代理网段填入逗号分隔的 `TRUSTED_PROXY_CIDRS`；未配置时限流使用直接连接地址，转发头不会被盲目信任。该配置不等于自动配置 Flask 的 HTTPS 代理识别。

Nginx 转发片段示例，放入已有 HTTPS `server` 中，证书及域名由部署环境配置：

```nginx
client_max_body_size 24m;

location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_connect_timeout 10s;
    proxy_read_timeout 310s;
    proxy_send_timeout 310s;
}
```

代理的 `24m` 只允许流量到达应用，应用仍执行更严格的文件和请求体上限。若需要应用正确识别代理后的 HTTPS，必须由可信的 WSGI / 平台接入层配置并验证；仅发送 `X-Forwarded-Proto` 不会在此应用中自动启用 `ProxyFix`。正式环境保留安全 Cookie；本机直接 HTTP 调试账号才设置 `SESSION_COOKIE_SECURE=0`。

当前关键容量为：单图 20,000,000 字节、总像素 33,177,600；全局请求体 22,524,288 字节；同步 `data` JSON 单独上限 12 MiB。普通聊天单条 6000 字符，最近最多 32 条，模型历史总预算 60,000 字符；经确认的图片内容另有结构与组合上限，超限时应拆分，不靠截断保存完整题意。

`GET /health` 返回进程版本、源码摘要和识别预算；`GET /ready` 返回本地阶段及所选识别路径状态。它们的 HTTP 200 不证明模型凭据、邮件、数据库或整条识题链可用；模型按需执行时，启动后的本地 OCR 尚未就绪也是可能状态。

图形确认登记默认放在临时目录的 SQLite；通过 `DMATE_GRAPH_CONFIRMATION_DB` 指向持久卷可避免容器重建丢失登记。登记过期或丢失后旧图片确认需重新建立，不影响 PostgreSQL 中的账号记录。回滚应用时一并考虑配置、数据库与确认存储的兼容性。

## 数据持久化与备份

| 数据 | 所在位置 | 部署维护方式 |
| --- | --- | --- |
| 账号、邮箱状态、密码 / 恢复码哈希、云同步 JSON | PostgreSQL | 使用数据库备份与恢复；恢复后关注同步 revision 和账号状态 |
| 图片任务与确认摘要 | `DMATE_GRAPH_CONFIRMATION_DB` 指定的 SQLite | 持久卷可保留有效确认；仅有摘要，不能恢复原图或题目全文 |
| 本地 OCR 模型包 | 模型缓存目录 | 可从官方源重建；保留可减少重复下载与启动等待 |
| 独立绘图历史 | 每台设备当前浏览器的 localStorage，按账号 / 游客分区 | 不属于服务器备份，也不随 `/sync` 云同步 |
| 自定义背景图片 | 当前浏览器 IndexedDB | 不在 PostgreSQL 和服务端确认库中 |
| 尚未发送的图片及其核对草稿 | 当前页面任务状态 | 刷新、关闭或切换环境前先完成发送；服务器摘要不能代替草稿备份 |

备份时不要只复制项目代码或容器镜像。数据库、部署 Secret、上传确认持久卷分别管理；Secret 不应跟随源码公开。升级数据库结构由应用按需补建，仓库没有可自动撤回所有结构变化的通用迁移命令。

## 排查常见问题

| 现象 | 先检查 | 处理方向 |
| --- | --- | --- |
| 页面可打开但 AI 回答失败 | DeepSeek Key、服务地址连通性和上游错误 | 在部署平台修正配置；页面能加载不代表远程模型可用 |
| 自动识图无草稿 | `DASHSCOPE_API_KEY`、实际工作空间地址、`workflow_profile` | 确认 Key 对该主机和 `qwen3.8-flash` 有权限；不要用兼容路径开关替代网页配置 |
| 文字框提示模型或资源失败 | 缓存写权限、包验证、本地 worker 日志、cgroup 内存 | 修复缓存和资源；无需改聊天模型 |
| 本地 HTTP 登录后仍是游客 | `SESSION_COOKIE_SECURE` 和浏览器是否保存 Cookie | 仅本地 HTTP 调试关闭 Secure；正式环境恢复 HTTPS 与安全 Cookie |
| 云同步返回 409 | 请求的 `baseRevision` 与云端 revision | 重新读取并合并；不要循环提交旧版本或尝试 `force` |
| 原图或已核对内容提示失效 | 当前浏览器 / 账号、任务 ID、SQLite 持久卷和有效期 | 在当前身份重新上传、核对并保存；不能跨设备复制令牌解决 |
| 代理返回 413 / 504 | 代理请求体 / 超时、平台硬上限、应用响应 | 分清代理错误与应用错误；调整代理仍不能突破应用上限 |
| 邮件不送达 | Brevo / SMTP 授权、发件人验证、垃圾邮件、频率限制 | 修正邮件服务；不要公开完整邮件配置或验证码 |
| 原生客户端没有更新 | 网页修订与 APK / 桌面壳版本是否混淆 | 网页代码由服务器更新；原生权限与桥接逻辑需重新构建并安装 |

排错先查看服务日志与对应 HTTP 状态。日志中不应公开 API Key、数据库 DSN、Cookie、恢复码和完整用户题目；向他人提供问题信息时保留错误码、路径和必要的非敏感配置名称即可。不要把远程模型、发邮件或真实账号操作作为每次启动时自动循环执行的探测。

## 网页与安装包

Tauri 配置位于 `desktop/src-tauri/tauri.conf.json`；Android 配置位于 `android/app/build.gradle`。两者默认加载 `https://dmate.zeabur.app/`。修改自托管地址时还需核对原生可信来源与权限设置，不能只替换一个链接。

| 工作流 | 产物 / 用途 |
| --- | --- |
| `.github/workflows/build-desktop.yml` | Windows NSIS、Linux DEB / AppImage、macOS universal DMG |
| `.github/workflows/build-android.yml` | 手动生成 debug APK |
| `.github/workflows/build-android-release.yml` | 手动生成签名 release APK Artifact，不自动覆盖 Release |
| `.github/workflows/build-snap.yml` | 构建 amd64 Snap |
| `.github/workflows/publish-snap.yml` | 使用发布凭据上传新构建或提升已有修订渠道 |

Android release 构建使用仓库 Secrets `DMATE_ANDROID_KEYSTORE_BASE64`、`DMATE_ANDROID_KEYSTORE_PASSWORD`、`DMATE_ANDROID_KEY_ALIAS`、`DMATE_ANDROID_KEY_PASSWORD`；Gradle 读取 `DMATE_KEYSTORE_PATH`、`DMATE_KEYSTORE_PASSWORD`、`DMATE_KEY_ALIAS`、`DMATE_KEY_PASSWORD`。Snap 发布使用 `SNAPCRAFT_STORE_CREDENTIALS`。macOS 见[签名与公证](MACOS_DISTRIBUTION.md)。构建 Artifact 与对外发布是两个步骤，旧下载文件不会因网页更新自动替换。

安装弹窗可通过 `ANDROID_APK_URL`、`DESKTOP_WINDOWS_URL`、`DESKTOP_MACOS_URL`、`DESKTOP_LINUX_DEB_URL`、`DESKTOP_LINUX_APPIMAGE_URL` 覆盖下载地址。网页不提供 PWA 或 iOS WebClip 安装；`/service-worker.js` 只用于清退旧 worker。主要静态资源禁用持久 HTTP 缓存，安装壳通过 `/web-version` 检查网页更新，忙碌时延后重载；这不能更新 APK / Tauri 中的原生代码。

### 本地构建客户端

桌面壳是 Rust / Tauri 2 工程，仓库没有单独的 npm 前端构建步骤。安装 Rust stable、Tauri CLI 2 和当前系统所需的 WebView / 打包依赖后，在 `desktop/` 执行：

```bash
cargo install tauri-cli --version '^2' --locked
cd desktop
cargo tauri build
```

产物位于 `desktop/src-tauri/target/` 下的平台 bundle 目录。Windows 目标为 NSIS，Linux 使用 DEB / AppImage，macOS 工作流同时安装 ARM64 与 x86_64 Rust target，生成 universal DMG。Linux 所需 WebKitGTK 等依赖以桌面工作流为准；macOS 正式分发需完整签名与公证配置，不能把未公证构建当作普通用户安装包。

Android 当前要求 Java 17、Android SDK 36 / build-tools 36.0.0，工作流使用 Gradle 9.6.0。仓库没有 Gradle wrapper，需提供相应 `gradle` 命令：

```bash
cd android
gradle assembleDebug
```

debug APK 位于 `android/app/build/outputs/apk/debug/app-debug.apk`。正式包在配置上述签名变量后执行 `gradle assembleRelease`，产物位于 `android/app/build/outputs/apk/release/`。不要混淆 debug 与 release 的应用 ID、签名和更新关系。

自托管更换网址时，除 Tauri 配置和 Android `DMATE_URL` 外，还需检查原生代码中的来源判断、允许导航、图片保存桥接和麦克风权限授权。网站可访问不表示新域名自动获得原生权限。构建产物上传到 Artifact、创建公开 Release、修改网页下载链接、用户安装更新，是不同的动作。
