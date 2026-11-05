# 部署与配置

本文面向自托管和维护人员，说明如何启动当前仓库、为不同功能补齐服务、保存运行数据，以及更新网页和客户端。日常操作见[使用指南](USER_GUIDE.md)，HTTP 字段见 [API](API.md)。

## 先确定需要哪些功能

应用不是必须连接所有外部服务才能打开。可以先启动网页，再按需要配置功能：

| 部署范围 | 需要准备 | 未准备时的表现 |
| --- | --- | --- |
| 打开页面、手工编辑画板、查看内置知识图谱 | Python 服务及静态资源 | 服务未启动时页面无法访问 |
| AI 教学、出题、错题分析、概念分析、绘图指导 | DeepSeek Key 和服务网络 | 相关 AI 请求返回配置或服务错误，不能因此判断画板或页面本身损坏 |
| 网页自动识图、选区图形重识别 | DashScope Key、可访问的视觉服务地址 | 自动扫描与图形选区重识别不能完成；独立画板仍可使用 |
| 文字框识别 | ONNX Runtime、PaddleOCR / PaddleX 依赖、已转换文字模型、可写缓存、足够的进程内存 | 选区 OCR 报初始化、缓存或资源错误；它不使用 DeepSeek Key |
| 语音转文字 | DashScope 语音权限、模型与词库、浏览器麦克风权限 | 不能录音或转写，文字输入仍可使用 |
| 注册、登录、云同步 | PostgreSQL、稳定的认证密钥 | 游客工作区可使用，账号操作不可用 |
| 邮箱注册、邮箱绑定、邮件找回 | 上述账号配置，加 Brevo 或 SMTP | 邮箱验证码无法发送；已有可用账号的其他登录方式不由邮件服务替代 |

识图与语音可使用同一个服务凭据，但仍需分别开通相应模型和词库权限。数据库不存储模型密钥；前端和客户端安装包也不应包含这些密钥。

## 运行方式

应用由 Flask 提供网页与 API，以 Linux 运行环境为基线；本地 worker 使用 `fcntl` 等系统能力，Windows 自托管应使用 WSL2 或 Linux 容器。Dockerfile 使用 `python:3.10-slim`，安装 `requirements.txt`（包含 `requirements-agents.txt`），预下载本地文字 / 版面模型，并在构建时将文字模型转换为 ONNX。Docker 构建和首次本地模型下载需要访问 Python 包源及 Paddle 官方模型源。

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
export DMATE_MODEL_CACHE_DIR="$PWD/.model-cache"
export PADDLE_PDX_CACHE_HOME="$DMATE_MODEL_CACHE_DIR/paddlex"
python scripts/prepare_ocr_model_cache.py --cache-dir "$DMATE_MODEL_CACHE_DIR"
python scripts/prepare_ocr_model_cache.py --cache-dir "$DMATE_MODEL_CACHE_DIR" --verify-only
python app.py
```

浏览器打开 `http://localhost:5000/`。示例占位值必须替换为自己的配置；不使用的服务可以不设置。文字识别需要在启动前成功完成模型准备；只运行 `pip install` 不会生成文字 ONNX 模型。不需要本地文字 / 版面识别时可跳过缓存命令，但相关接口届时不可用。配置在模块初始化时读取，项目没有在此之前自动加载 `.env` 的步骤，需由 shell、进程管理器或托管平台事先注入变量，不能仅创建文件就假设配置生效。

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

镜像构建除了安装依赖，还会预备 OCR 模型包、转换两个文字模型并检查缓存，再生成跨平台图标。模型准备先从 ModelScope 的官方 PaddlePaddle 仓库取得必需文件的提交版本、大小及 SHA256，按该版本下载并校验；失败后才使用 PaddleX 官方源作为后备。`PADDLE_PDX_MODEL_SOURCE`（当前默认 BOS）只影响 PaddleX 后备源的优先级，不改变 ModelScope 的首选顺序。下载与重试预算见[本地模型与缓存](#本地模型与缓存)。所有来源均无法提供完整模型时构建才会失败，后续 `--verify-only` 仍会严格检查模型文件、ONNX 导出和哈希清单。`scripts/generate_icons.py` 直接从脚本内的矢量路径生成图标，不再读取 Android 目录里的旧 PNG 作为源图；自定义构建上下文需保留生成脚本及 Pillow 依赖，输出目录由脚本创建。应用源码更新后重新构建镜像，正常情况下依赖和模型包层可复用缓存。

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

当前网页自动读图不先运行整图 OCR。自主框选的文字识别默认通过 ONNX Runtime CPU 执行 `PP-OCRv6_small_det`、`PP-OCRv6_small_rec`，复用 PaddleOCR / PaddleX 的预后处理。其他识别路径可使用 `PP-DocLayoutV3` 的 Paddle 版面推理和几何工具。worker 隔离运行，云端模型 API Key 不传入本地模型子进程。

主要版本固定为 PaddlePaddle 3.3.1、PaddleOCR 3.7.0、PaddleX 3.7.2、ONNX Runtime 1.23.2、Paddle2ONNX 2.1.0、ONNX 1.17.0。文字模型保留 FP32，不量化；导出为 ONNX opset 17。构建转换禁用导出器的可选优化工具，避免其自动安装额外依赖或改动 NumPy。ORT 使用自身图优化、`CPUExecutionProvider`、`intra_op_num_threads=2`、`inter_op_num_threads=1`、`execution_mode=sequential`。

Docker 构建运行 `scripts/prepare_ocr_model_cache.py`：下载三个官方 Paddle 包，校验原始包，为两个文字包导出 ONNX，再记录转换文件的模型身份和 SHA256。此步骤不对图片执行推理，也不请求云端模型。容器默认 `DMATE_MODEL_CACHE_DIR=/opt/dmate-model-cache`，其下使用 `paddlex` 目录；原包位于 `official_models/<模型名>/`，文字转换文件位于 `onnx_models/<模型名>/inference.onnx`，各目录保留对应的 `inference.yml` 及 `dmate-onnx-source.json` 来源哈希记录。清单为 `paddlex/dmate-model-manifest.json`。运行用户必须能写缓存及临时目录；已有 `PADDLE_PDX_CACHE_HOME` 配置也会优先参与缓存选择。

下载优先直接访问 ModelScope 上的官方 `PaddlePaddle/<模型名>` 仓库，只取 `inference.json`、`inference.pdiparams` 和 `inference.yml`，不下载 README 等附加文件。脚本从官方文件清单取得固定提交版本、文件大小及 SHA256，按该版本下载并逐文件校验；三个文件及模型身份全部通过后，才把暂存目录发布为可用缓存。失败时继续尝试 PaddleX 的其他官方源，不更换 OCR 模型、不跳过 ONNX 导出或最终清单核验。

官方文件清单最多尝试 3 次，每次总时限不超过 60 秒；每个文件最多尝试 3 次，每次默认总时限 300 秒，连接超时 8 秒、连续读取无数据超时 30 秒。超时或断开后保留同一提交版本的部分文件，下一次从断点继续；服务器不支持断点时重新写入该文件，最终仍须满足完整大小及 SHA256。`--download-timeout` 可调整每次文件下载及 PaddleX 后备源的时限（最多 600 秒），ONNX 导出同样使用该参数。已完整准备的缓存会复核后复用；整个 Docker 下载层失败后的重新构建仍可能需要重新下载，普通业务代码修改则可复用成功的模型构建层。

如果构建日志显示 BOS / Hugging Face 超时、AIStudio 返回 404，不能把它当作模型已经准备成功。新版首先请求实际的 ModelScope 文件地址，避免根域名仅 1 秒的连通探测误排除可用源；所有源失败仍会明确终止构建。SHA256 来源于 HTTPS 官方仓库清单，属于传输内容校验，不等同于独立发布者签名。

本地 Linux 可预备到可写目录：

```bash
export DMATE_MODEL_CACHE_DIR="$PWD/.model-cache"
export PADDLE_PDX_CACHE_HOME="$DMATE_MODEL_CACHE_DIR/paddlex"
python scripts/prepare_ocr_model_cache.py --cache-dir "$DMATE_MODEL_CACHE_DIR"
python scripts/prepare_ocr_model_cache.py --cache-dir "$DMATE_MODEL_CACHE_DIR" --verify-only
```

`--verify-only` 检查已有原包、ONNX 文件格式和清单，不下载、转换、执行文字识别，也不验证云模型凭据。缓存选择顺序为显式 `PADDLE_PDX_CACHE_HOME`、`DMATE_MODEL_CACHE_DIR/paddlex`、`XDG_CACHE_HOME/dmate/paddlex`、当前系统用户的临时缓存；目录需要能实际创建和写入子文件。只挂载空目录覆盖镜像内的缓存，会遮住预下载和转换内容，应先复制或重新准备所需模型包。

升级旧部署时，应更新依赖并重新构建镜像，或在启动前运行不带 `--verify-only` 的准备命令。原有 Paddle 缓存会先按旧清单核对，再补齐 ONNX 和升级清单；文件损坏或原包身份改变会失败，不会把改变后的文件直接重记为正常缓存。首次转换会产生额外构建耗时和内存占用，应在构建阶段完成。运行请求不导出模型；缺少 ONNX 文件或准备失败时，本地文字识别直接报错，不能只等待请求自行修好。

文字引擎设置：

| 变量 | 值与行为 |
| --- | --- |
| `DMATE_TEXT_OCR_ENGINE` | 默认 `onnxruntime`；`paddle_static` 显式回退到原 Paddle CPU 文字执行路径 |

修改该变量后需重启应用。原文字 Paddle 包保留在缓存内供回退使用；回退不会改换模型权重、视觉提供方或图形识别工作流。ONNX 初始化失败不会自动尝试 Paddle，避免把部署缺失隐去或在失败后叠加另一套模型的内存。先查看实际引擎、准备失败阶段和缓存状态，再处理依赖 / 缓存或显式回退。

本地推理在短生命周期子进程中运行，Web 进程不预加载 ONNX 或 Paddle 模型。版面与文字阶段由本地租约串行调度，不共驻一个 worker。文字仍为识别 batch 1、检测长边上限 1600，关闭文字方向分类和文档矫正；切换执行引擎没有放宽图片、并发和资源边界。worker 的 RSS 边界为 1600 MiB，并为容器其余部分预留 768 MiB；准入判断还考虑 cgroup 可用内存。它不是“给容器设置 1600 MiB 就足够”的资源承诺，Web、图像解码、并发请求和系统占用还需要空间。资源不足时先降低并发和图片复杂度，检查容器内存，再调整部署资源，避免通过增加 Web worker 放大内存占用。

本地比较在同权重、同前后处理、固定两个逻辑 CPU 下对五张图各做三轮：合计中位数从 5.24 秒降到 3.91 秒，峰值 RSS 约 1075 → 827 MiB，文字输出逐字一致。该环境不是线上 2 核 / 4 GB 服务器，未模拟 4 GB 内存限制，不含 HTTP、版面分析、增强重读或云端识图耗时。它支持评估执行效率，不能作为线上响应时间、容量或通用识别准确率的承诺。

### 文字质量处理与机器结果缓存

`ocr_text_preprocess.py` 的预处理版本为 `text-quality-v1`。每个选区先读原像素，再结合首遍置信度、数学符号风险和缩略质量图选择是否增加一遍辅助读取。清晰高置信文字不按字数或语言固定重读；低对比度使用局部对比度调整，阴影 / 亮度不均只作为恢复读取的线索并使用同一种温和局部对比度处理；深色底使用反转后对比度调整，轻度模糊使用温和锐化。每次只选一种，保持原尺寸与坐标，总计最多两遍，差异继续按原有保守规则进入待核对证据。该功能复用已有 OpenCV / NumPy，不增加模型或外部服务。

`ocr_text_cache.py` 缓存的是 `/graph/text-region` 的短期机器 OCR 结果，与上方的磁盘模型文件缓存不同。默认每个 Web 进程最多 64 条，序列化结果合计 8 MiB，有效期 600 秒；Python 对象、锁及解释器开销不包含在这 8 MiB 数据预算内。过期条目不再命中，在后续读写时清理；进程重启、重新部署或更换进程会清空，不需要数据卷、Redis 或数据库，也不跨进程共享。

只有完整非空、无失败和待核对信息的结果可以缓存，批量每一项也须合格。键包含身份、原图 SHA256、校验后的选区 / 排除范围、批量顺序与编号、实际引擎、模型清单和预处理版本；模型文件被替换或预处理版本更新后不沿用旧项。当前原图来源和身份校验先于查询，缓存命中不能绕过限流、输入校验或本次取消。请求仍上传原图以核对摘要；缓存只省去符合条件的重复推理，不加速首次扫描或省去上传耗时。

API 的 `force_recognition=1` 会清除当前匹配旧项并实际识别；`cache_hit` 布尔值用于区分命中和实际执行。取消前后的结果绑定当前操作，机器结果缓存不存 worker 完成回执、确认令牌或用户修改。该缓存不属于账号学习快照，也不恢复游客绘图；数据边界见[隐私说明](SECURITY_PRIVACY.md#服务端存储)。当前条目 / 容量 / 时间是代码内固定边界，不应通过增大 Web worker 数来假定有统一缓存或统一资源限制。

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

分项连接配置使用 PostgreSQL 驱动生成连接串，`PGPASSWORD` / `POSTGRES_PASSWORD` 的前后空格、引号和反斜杠会原样保留，不再拼接未转义的密码。未配置认证密钥的游客部署使用进程内随机 Cookie 签名密钥；它不启用账号功能，也不能替代生产环境稳定的 `AUTH_SECRET_KEY`。已配置账号系统的数据库临时故障返回可重试的 503，保留已有 Cookie 和前端账号缓存，不能把这类故障当成用户主动退出。

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

# 与上面的 location / 并列；SSE 不能等整段缓冲完再交给浏览器。
location = /chat {
    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_cache off;
    gzip off;
    proxy_connect_timeout 10s;
    proxy_read_timeout 310s;
    proxy_send_timeout 310s;
}
```

代理的 `24m` 只允许流量到达应用，应用仍执行更严格的文件和请求体上限。若需要应用正确识别代理后的 HTTPS，必须由可信的 WSGI / 平台接入层配置并验证；仅发送 `X-Forwarded-Proto` 不会在此应用中自动启用 `ProxyFix`。正式环境保留安全 Cookie；本机直接 HTTP 调试账号才设置 `SESSION_COOKIE_SECURE=0`。

`/chat` 在请求明确启用流式时发送 SSE，返回 `X-Accel-Buffering: no` 和 `Cache-Control: no-store, no-transform`。前面的独立 location 同时兼容原有 JSON 请求，不必新增域名或流式接口地址。若还有 CDN、网关、托管平台或压缩中间件，须让该 POST 响应及时透传，避免缓存、整段缓冲或压缩合并；应用返回这些头不证明所有上游平台都会遵守。没有修改代理权限时，应由部署者核对平台配置，本仓库的网页修改不会自动重写外部代理。

流式能力默认启用；需要暂时回退时设置 `DMATE_CHAT_STREAMING=0` 并重启应用。服务端会对同一请求返回原 JSON，新前端按响应类型处理，不会自动额外调用一次模型。此开关不修改模型选择、题目校验或已有聊天数据。

当前 `chat_streaming.py` 每进程限制最多 4 个流式工作任务，各有 64 个待发送事件的有界队列。配合默认单 worker、8 个 Gunicorn 线程，流式连接自身不会占满全部 8 个请求线程，可为同步、取消、账号及其他请求保留处理空间；这不是其他负载下的响应时间保证。已断开的受保护 JSON 模型请求可能仍在读取，直到它结束前仍占用同一个工作名额，防止快速断开重连产生无限后台任务。饱和时返回 JSON 429、`chat_stream_busy` 和 `Retry-After: 2`，不要靠客户端自动循环重发突破限额。多进程 / 副本不会共享该进程内信号量，不能仅增 worker 就认定全系统仍是 4 个任务。

等待中的 SSE 连接约每秒发送一次保活注释，以降低空闲断连并让服务器发现客户端离开；心跳不替代模型和后端的超时预算。停止时公开正文上游流会尝试关闭，受完整校验保护的 JSON 读取仍可能运行到原超时。不得把“客户端已断开”当成“提供方已停止生成或费用已撤回”。流式不更改云同步的修订号协议，也不会把临时片段写入已完成聊天记录。

应用另外设置整次 SSE 响应 300 秒上限；持续保活或持续收到片段不会延长此预算。到限返回 `chat_stream_timeout` / 504 终止事件并触发取消，工作名额仍等实际后台任务退出后归还。此应用层时限与代理的空闲读取超时不同，可避免上游无限保活占住请求。

当前关键容量为：单图 20,000,000 字节、总像素 33,177,600；全局请求体 22,524,288 字节；同步 `data` JSON 单独上限 12 MiB。普通文字单条 20,000 字符，历史最多 64 条消息、总计 120,000 字符。已确认图片单条仍为 28,000 字符；完整题干和追问 / 复测的内部包装另有校验，不等于放宽普通输入。

这些应用边界由 `chat_limits.py` 统一，前端同步普通输入和回退窗口。模型实际 token 窗口仍由配置的提供方与模型决定，不能仅凭字符数认定一定容纳；明确容量错误会触发最多一次只减旧完整消息的补救，必要上下文本身过大则提示拆分。此策略不自动更换模型，不提高回答输出预算，不改变图片大小、限流和云同步容量。

`GET /health` 返回进程版本、源码摘要和识别预算；`GET /ready` 返回本地阶段及所选识别路径状态。它们的 HTTP 200 不证明模型凭据、邮件、数据库或整条识题链可用；模型按需执行时，启动后的本地 OCR 尚未就绪也是可能状态。

图形确认登记默认放在临时目录的 SQLite；通过 `DMATE_GRAPH_CONFIRMATION_DB` 指向持久卷可避免容器重建丢失登记。登记过期或丢失后旧图片确认需重新建立，不影响 PostgreSQL 中的账号记录。回滚应用时一并考虑配置、数据库与确认存储的兼容性。

## 数据持久化与备份

| 数据 | 所在位置 | 部署维护方式 |
| --- | --- | --- |
| 账号、邮箱状态、密码 / 恢复码哈希、云同步 JSON | PostgreSQL | 使用数据库备份与恢复；恢复后关注同步 revision 和账号状态 |
| 图片任务与确认摘要 | `DMATE_GRAPH_CONFIRMATION_DB` 指定的 SQLite | 持久卷可保留有效确认；仅有摘要，不能恢复原图或题目全文 |
| 本地 OCR 原模型与 ONNX 转换文件 | 模型缓存目录及哈希清单 | 可从官方源重下并重新导出；保留完整目录可减少重复下载与转换 |
| 登录账号独立绘图历史 | 每台设备当前浏览器的 localStorage，按账号分区 | 不属于服务器备份，也不随 `/sync` 云同步 |
| 游客独立绘图 | 当前页面内存，不使用 localStorage 或 sessionStorage | 同页重开绘图可继续；刷新 / 关闭网页后清空，旧版游客持久图库不导入 |
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

下载安装弹窗可通过 `ANDROID_APK_URL`、`DESKTOP_WINDOWS_URL`、`DESKTOP_MACOS_URL`、`DESKTOP_LINUX_DEB_URL`、`DESKTOP_LINUX_APPIMAGE_URL` 配置下载地址。地址必须为没有用户凭据或片段的有效 HTTPS URL。按钮顺序保持 GitCode、GitHub：配置的 GitCode 地址或本项目 GitHub 发行版地址替换对应入口，其他自建镜像作为第三项“其他下载源”。未配置时使用 GitCode 文件直链与同一固定发行标签的 GitHub 地址。这些变量只配置下载安装弹窗，不替代安装后检查更新使用的 `static/client-updates.json` 清单。iOS 提供发行版已有的描述文件及备用源，不提供 PWA 安装。`/service-worker.js` 只用于清退旧 worker。

公式与富文本等前端依赖位于 `static/vendor/<组件-版本>/`，含 MathJax 本地按需资源、上游许可和完整性清单，镜像必须包含这些文件。版本化的第三方目录成功响应允许一年 immutable 缓存；业务 JS / CSS、未版本化资源清单和 `/web-version` 仍禁用旧缓存。升级第三方库应使用新版本目录，不能原地替换已长期缓存的文件。安装壳检查网页更新时会在忙碌期间延后重载；这不能更新 APK / Tauri 中的原生代码。

`static/client-updates.json` 独立控制安装后更新通知。保留实际包版本和发布状态，主源与 `fallbackUrls` 仅指向本仓库同发行版、同文件名的 GitCode / GitHub 地址；不能只改网页就把尚未发布的新原生包标成可更新。检测 GitCode 附件时使用 GET 或 Range GET，HEAD 返回值不能单独判断文件不存在。

### 图标生成与发布

图标生成的唯一输入是 `scripts/generate_icons.py` 内的几何路径；不要单独替换某个平台的 PNG 后期待其他平台自动一致。在仓库根目录先执行：

```bash
python -m pip install Pillow==11.3.0
python scripts/generate_icons.py
```

脚本输出网页 SVG / PNG / ICO、Tauri PNG / ICO / ICNS、Android 密度位图与 VectorDrawable。每种位图尺寸独立从路径绘制，小尺寸单独调整线宽；最大 PNG 和 macOS ICNS 图层为 1024 × 1024。Android 自适应图标前景处于 66dp 直径安全区域，普通 / 圆形资源在 API 26 及以上引用矢量前景，API 33 及以上增加单色主题前景。替换旧 `drawable-nodpi/dmate_foreground.png` 时会删除该文件，避免与同名矢量资源冲突。

当前网页通过带 `v49` 的新文件名和根路径版本参数取图，侧栏和手机顶部直接使用 SVG。浏览器特定的黑白标签图标选择保持独立于网页明暗主题；Safari 不通过失焦 / 聚焦事件反复更换图标。根路径 `/favicon.ico`、`/favicon-16.png`、`/favicon-32.png`、`/favicon-64.png`、Apple touch icon 继续有效。旧版本资源保留给历史缓存页面。

发布时分别处理：

- **服务端 / 网页**：Docker 构建会生成资源，新部署提供新图标地址。不要为换图清除用户学习数据或引入额外 Service Worker。
- **桌面与 Android**：对应构建工作流会先运行生成器；Tauri 配置包含 512 / 1024 PNG 及 ICO / ICNS，Android Gradle 使用新的启动器资源。Android debug / release 工作流仍需手动触发，签名与应用标识保持原配置。
- **Snap**：手动构建工作流从同次生成的 512 像素 PNG 写入 `snap/gui/dmate.png`；构建和 Snap Store 发布仍是独立步骤。
- **iOS Web Clip**：`python scripts/generate_ios_webclip.py` 默认生成 `dist/DMate-iPhone-iPad-fullscreen.mobileconfig`；内嵌 `dmate-app-v49-512.png`，与服务端 `/DMate.mobileconfig` 使用相同构建函数，原描述文件身份保持不变。公开 GitCode / GitHub 入口只有在发布工作流更新对应附件后才使用新图，用户已安装的 Web Clip 也需更新描述文件。

源码资源齐全和本地图像检查通过，不等于 APK / 桌面安装包编译、签名或真机验证已经完成。发布前仍应检查相应平台的构建产物；仅当新包真实发布后，才更新下载入口或 `static/client-updates.json` 的版本与状态。缓存图标未更新时先重新打开页面 / 应用、必要时重新创建系统快捷方式，不要删除账号存储来刷新图标。

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
