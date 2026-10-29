# 部署与配置

## 运行方式

应用由 Flask 提供网页与 API，以 Linux 运行环境为基线；本地 worker 使用 `fcntl` 等系统能力，Windows 自托管应使用 WSL2 或 Linux 容器。Dockerfile 使用 `python:3.10-slim`，安装 `requirements.txt`（包含 `requirements-agents.txt`），并预下载本地文字 / 版面模型。Docker 构建和首次本地模型下载需要访问 Python 包源及 Paddle 官方模型源。

本地开发可按 [README](../README.md) 建立 Python 3.10 虚拟环境后运行 `python app.py`，默认监听 `0.0.0.0:5000`，`PORT` 可覆盖端口。Linux 系统依赖以 Dockerfile 的 `libgl1`、`libglib2.0-0`、`libgomp1`、`libsm6`、`libxext6`、`libxrender1` 为准。

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

邮箱注册、绑定及找回需要至少一个邮件通道：

- Brevo：`BREVO_API_KEY`、`BREVO_SENDER_EMAIL`，可选 `BREVO_SENDER_NAME`（默认 DMate）。发件人可回退 `SMTP_FROM_EMAIL` / `SMTP_FROM_NAME`。
- SMTP：`SMTP_HOST`（默认 `smtp.qq.com`）、`SMTP_PORT`（默认 465）、`SMTP_USERNAME`、`SMTP_PASSWORD`、`SMTP_FROM_EMAIL`（默认用户名）、`SMTP_FROM_NAME`（默认 DMate）、`SMTP_USE_SSL`（默认开启）。关闭 SSL 模式时使用 STARTTLS。

两者均配置时先用 Brevo，失败后使用 SMTP；仅配置 SMTP 时直接使用 SMTP。凭据属于服务端部署配置，不放进前端或安装包。

## 代理、容量与运行诊断

反向代理使用 HTTPS，上传请求体至少容纳应用允许的请求，超时应覆盖后端请求预算。只把真实可信代理网段填入逗号分隔的 `TRUSTED_PROXY_CIDRS`；未配置时限流使用直接连接地址，转发头不会被盲目信任。该配置不等于自动配置 Flask 的 HTTPS 代理识别。

当前关键容量为：单图 20,000,000 字节、总像素 33,177,600；全局请求体 22,524,288 字节；同步 `data` JSON 单独上限 12 MiB。普通聊天单条 6000 字符，最近最多 32 条，模型历史总预算 60,000 字符；经确认的图片内容另有结构与组合上限，超限时应拆分，不靠截断保存完整题意。

`GET /health` 返回进程版本、源码摘要和识别预算；`GET /ready` 返回本地阶段及所选识别路径状态。它们的 HTTP 200 不证明模型凭据、邮件、数据库或整条识题链可用；模型按需执行时，启动后的本地 OCR 尚未就绪也是可能状态。

图形确认登记默认放在临时目录的 SQLite；通过 `DMATE_GRAPH_CONFIRMATION_DB` 指向持久卷可避免容器重建丢失登记。登记过期或丢失后旧图片确认需重新建立，不影响 PostgreSQL 中的账号记录。回滚应用时一并考虑配置、数据库与确认存储的兼容性。

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
