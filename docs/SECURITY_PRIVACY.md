# 数据、安全与隐私说明

## 1. 游客模式与登录模式

DMate 当前明确区分两种数据状态。

### 游客模式

游客的聊天、学习记录、错题和外观设置不写入持久 `localStorage`。这些数据只属于当前运行中的页面状态，刷新、退出或重新打开后不保证保留。

游客自定义背景只保留为当前页面内存中的 Blob，不写入 IndexedDB。

### 登录模式

登录后前端允许使用本机缓存，并把以下云快照同步到 PostgreSQL：

```text
sessions
learning
appearance 参数
```

主要本地键：

```text
discrete_math_ai_sessions_v1
discrete_math_ai_learning_v1
discrete_math_ai_appearance_v1
discrete_math_ai_cloud_sync_v1
```

自定义背景图片使用 IndexedDB：

```text
discrete_math_ai_appearance_assets_v1
```

背景图片本体不进入云端快照，因此不同设备可以使用不同背景图。

## 2. PostgreSQL 服务端数据

主要表：

```text
dm_users
dm_user_data
dm_email_codes
```

`dm_users` 保存账号标识、已验证邮箱、密码哈希、恢复码哈希和 `auth_version`；`dm_user_data` 保存用户同步 JSONB 与 `revision`；`dm_email_codes` 保存邮箱验证码摘要、用途、过期时间、错误次数与消费时间。

单次 `/sync` JSON 上限为 5 MiB。

## 3. 密码、恢复码与验证码

- 密码使用 Werkzeug `generate_password_hash(..., method="scrypt")`；
- 恢复码同样使用 scrypt 哈希；
- 注册时的自动恢复码明文只返回一次；
- 邮箱验证码不保存明文，使用 `AUTH_SECRET_KEY` 参与 HMAC-SHA256 摘要；
- 邮箱验证码 10 分钟有效；
- 60 秒内不能重复发送；
- 同邮箱同用途每小时最多 8 次；
- 单个验证码最多允许 6 次错误尝试；
- 重置密码后 `auth_version` 增加，使其他旧 Session 失效。

## 4. Session Cookie

账号只使用服务器签名的 Session Cookie，前端 JavaScript 不保存登录 token。

当前配置：

```text
HttpOnly = true
SameSite = Lax
Secure = true（默认）
有效期 = 30 天
SESSION_REFRESH_EACH_REQUEST = true
```

生产环境应保持 HTTPS，并保持 `SESSION_COOKIE_SECURE` 开启。

## 5. 邮箱验证与账号枚举边界

注册、绑定 / 更换邮箱与邮箱重置密码使用 6 位验证码。

重置密码场景发送验证码时，如果邮箱不存在，接口仍返回统一成功外观，不直接告诉调用方“该邮箱是否注册”，降低简单账号枚举风险。

事务邮件默认：

```text
Brevo API
↓ 失败时
SMTP 备用
```

邮件服务会接触收件邮箱地址和验证码邮件内容，这是完成邮箱验证所必需的第三方数据流。

## 6. AI 与 OCR 数据流

### 文本对话

```text
前端
→ Flask /chat
→ teaching.py 本地规则分析
→ 当前文本提供方（可选鲁信 / DeepSeek兜底）
→ Flask
→ 前端
```

### 图片题

```text
图片
→ Flask /ocr
→ PaddleOCR CPU 推理
→ DeepSeek Vision（开启时）
→ Flask
→ 前端
```

因此，账号云同步与模型请求属于两类不同的数据流：学习状态可进入 PostgreSQL，模型输入会发送给运行时 AI 提供方。

## 7. API Key 与服务端密钥

以下敏感凭据仅从服务端环境变量读取，不写入前端 JavaScript：

- `DEEPSEEK_API_KEY`
- `LUXIN_API_KEY`
- `BREVO_API_KEY`
- SMTP 密码 / 授权码
- PostgreSQL 连接凭据
- `AUTH_SECRET_KEY`

## 8. HTML 内容安全

AI 文本显示链：

```text
Marked → DOMPurify → MathJax
```

Marked 用于 Markdown 解析；DOMPurify 负责进入 DOM 前的 HTML / MathML / SVG 清洗。

## 9. 请求与资源限制

### 聊天

- 32 条消息 / 请求；
- 6000 字符 / 单条；
- 20 次 / 60 秒 / 客户端 IP。

### 图片

- 8 MiB / 单张；
- OCR 最长边 2200 px；
- 10 次 / 60 秒 / 客户端 IP。

### 账号

账号相关接口按路由使用 20 次 / 60 秒 / 客户端 IP 的进程内限流；邮箱验证码另有更严格的重发、小时次数和错误次数限制。

## 10. 限流实现边界

当前限流记录使用 `defaultdict(deque)` 保存在 Python 进程内存中。客户端 IP 优先读取 `X-Forwarded-For` 第一地址，否则使用 `request.remote_addr`。

这套实现与当前 Gunicorn 单 worker 部署配合使用；若未来扩展到多 worker / 多实例，需要改用共享限流存储才能形成全局统一限制。

## 11. OCR 故障隔离

- PaddleOCR 普通文字属于基础识别能力；
- 公式模块异常时普通文字 OCR 仍可工作；
- DeepSeek Vision 异常时尽量保留 OCR 结果；
- `/ready` 暴露 Web / OCR 就绪状态，但不返回 API Key。

## 12. 注销账号

永久注销要求：

- 已登录；
- 再次输入当前密码；
- 删除 `dm_users`；
- 关联 `dm_user_data` 与验证码记录通过外键级联删除；
- 当前前端随后清空本机工作区并回到游客状态。

## 13. 学习画像边界

知识图谱用于课程知识组织、建议前置知识和学习路径展示，不存储虚构“掌握度”。学习回顾依据真实会话与错题事件生成，不输出没有数据依据的能力百分比。
