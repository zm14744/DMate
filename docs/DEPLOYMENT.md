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
- 截至 2026-10-08，DeepSeek API 后台显示 **累计消费 ¥101.96**、**充值余额 ¥8.03**。余额与累计支出是不同指标，也不直接等于整个项目的总投入或单用户成本。

## 2. Gunicorn

启动命令记录：

```text
gunicorn -w 1 --threads 2 --timeout 300 -b 0.0.0.0:${PORT:-8080} app:app
```

当前限流实现保存在单个 Python 进程内，因此当前 1 worker 配置与该实现保持一致；若未来增加多 worker，需要同步调整限流设计。

## 3. 核心环境变量

### AI

```text
DEEPSEEK_API_KEY
DEEPSEEK_CHAT_MODEL
DEEPSEEK_VISION_MODEL
VISION_ANALYSIS_ENABLED
DEEPSEEK_MAX_OUTPUT_TOKENS
MEDIUM_MAX_OUTPUT_TOKENS
HARD_MAX_OUTPUT_TOKENS
```

代码当前默认：

- `DEEPSEEK_CHAT_MODEL=deepseek-flash`
- `DEEPSEEK_VISION_MODEL=deepseek-flash`
- 普通 / 中等 / 困难的输出预算分别由三组 token 变量控制。

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

当前代码还读取 Android / 桌面客户端的下载 URL 环境变量。这些变量只影响下载入口，不影响 DMate 核心学习功能：

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
| `desktop/src-tauri/` 下的配置、Rust、权限、窗口及原生资源 | 重新构建并分发新的桌面安装包 | 需要安装新版安装包 |

**操作顺序**：提交变更 → Zeabur 部署完成 → 通过 `/health` 与 `/ready` 观察服务状态 → 在网页和已安装客户端各测试一轮重点功能。对本次产品能力变更，重点检查图同构、二部图、拓扑排序、模逆 / CRT、齐次与非齐次递推，以及同知识点出题是否偏题。本项目已有 175 项个人功能自测结果记录；部署新版时仍应针对本次实际改动复测 AI 出题、OCR、复制、账号同步与移动端交互，不能仅因既往记录为通过便视为新部署完成验收。

请注意：**工程目前没有启用 Tauri 自动更新器或 Android APK 自动更新机制**。远程网页与后端可以不重装而获得更新，不代表安装包的原生代码会自动升级。`static/service-worker.js` 仅服务于 iOS 主屏幕网页应用，在线时网络优先，网络失败时可能显示旧缓存。


### 2026-10-08 OCR 与移动端修复的部署检查

本轮网页端更新涉及 `app.py`、`ai.py`、`templates/index.html`、`static/script.js`。更新 Zeabur 并刷新/重开客户端后，Windows/Tauri 与 Android/WebView 远程网页壳可获得相应网页功能，不必重新生成 EXE/MSI/APK；**原生安装包文件本身不会自动升级**。验证 OCR 识别时入口隐藏且布局补位、手机核对按钮固定底部及内容滚动、明显非题目图返回 422、纯图题仍允许核对。刷新后若页面仍旧，检查浏览器/WebView 缓存及服务器部署版本。
