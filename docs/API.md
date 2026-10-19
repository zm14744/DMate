# API 说明

基础服务由 `app.py` 提供。本文只描述 DMate 产品运行接口，不包含安装包构建接口。

## 接口总览

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/` | 主页面 |
| GET | `/DMate.mobileconfig` | iPhone / iPad WebClip 描述文件 |
| POST | `/chat` | AI 教学对话、题目锚定、难度控制与生成题登记 |
| POST | `/analyze-questions` | 批量规则化分析历史题目 |
| POST | `/ocr` | OCR + Vision 图片题理解 |
| POST | `/ocr/cancel` | 撤销图片识别请求 |
| GET | `/auth/me` | 当前账号状态 |
| POST | `/auth/email/send-code` | 发送注册 / 重置 / 绑定邮箱验证码 |
| POST | `/auth/register` | 邮箱验证注册 |
| POST | `/auth/login` | 用户名或邮箱登录 |
| POST | `/auth/email/bind` | 绑定或更换邮箱 |
| POST | `/auth/recovery-code` | 修改恢复码 |
| POST | `/auth/recover-password-email` | 邮箱验证码重置密码 |
| POST | `/auth/recover-password` | 恢复码重置密码 |
| POST | `/auth/logout` | 退出当前浏览器会话 |
| POST | `/auth/delete-account` | 永久注销账号 |
| GET / PUT | `/sync` | 云同步读取 / 写入 |
| GET | `/health` | Web 健康状态 |
| GET | `/ready` | Web / OCR 就绪状态 |

## GET `/`

返回 DMate 主页面，并注入知识图谱、平台识别状态及可选下载地址配置。

## iOS WebClip 描述文件

`GET /DMate.mobileconfig` 返回一个 Apple WebClip 配置描述文件，用于将 DMate 官网添加到 iPhone / iPad 主屏幕。它不安装 MDM、证书、VPN 或设备限制，也不提供原生 iOS IPA。其他平台通过首页安装弹窗获取对应安装包或商店入口。

`GET /` 向模板注入知识图谱、平台识别状态和可选下载地址配置。

## POST `/chat`

### 请求示例

```json
{
  "messages": [
    {"role": "user", "content": "给我一道和上一题同知识点的练习题"}
  ],
  "request_kind": "exercise",
  "exercise_reference": {
    "question": "上一道已定位题目的完整题干"
  }
}
```

`request_kind="exercise"` 表示前端明确声明本轮为出题请求；`exercise_reference` 仅在需要参照已有题生成同知识点题 / 复测题时使用。

### 输入规则

- `messages` 必须为数组；
- 有效角色为 `user`、`assistant`；
- 单次最多保留最近 32 条；
- 单条消息最多 6000 字符；
- 空内容忽略；
- `exercise_reference.question` 同样受 6000 字符限制；
- 后端不信任前端传入的知识分类，会重新分析参照题；
- 聊天限流：20 次 / 60 秒 / 客户端 IP。

### 出题难度规则

- 用户明确指定“简单 / 中等 / 困难”时，以明确要求为准；
- 普通参照题出题未指定难度时以中等为目标，不继承参照题难度；
- 独立泛化出题默认中等；**错题本复测默认继承已保存的原错题难度**（缺失时后端重估原题，仍无法确定才默认中等）。客户端通过 `exercise_reference` 提供 `retest: true`、`difficulty`（可空）和最多 4 项 `core_points`；不是复测的请求不应伪造 `retest`；
- 生成后再次分析实际难度：**未显式指定难度时不以估计差异拦截有效题目**；明确指定难度时最多额外重试一次，仍不匹配则可保留通过题目及知识点校验的有效题目，实际难度不保证与目标完全一致；
- 有普通参照题时，校验课程大类与已识别核心考点至少一个交集；**结构化错题复测**若携带 `retest_core_points`，则必须覆盖其中全部指定核心考点。若不符合返回生成失败提示；无法识别的知识点不能保证严格验证。

### 普通成功响应

```json
{
  "reply": "...",
  "teaching": {
    "mode": "concept",
    "mode_label": "概念讲解",
    "category": "图论",
    "difficulty": "简单"
  },
  "generated_exercise": false
}
```

### AI 生成题成功响应

```json
{
  "reply": "【题目】\n\n...",
  "teaching": {"mode": "exercise", "difficulty": "中等"},
  "generated_exercise": true,
  "generated_question": "...",
  "generated_teaching": {...},
  "generated_answer": "..."
}
```

`generated_answer` 是后端生成并保留的隐藏参考答案，供后续答案诊断、错题查看与复测使用；**普通出题**不在初次正文展示。但用户明确要求“出一道题并给出答案”时，正文可同时包含题目和答案；要求解析时还会额外尝试生成解题过程。模型答案仍需人工核对。

### 主要错误状态

- 400：请求格式、消息长度、参照题格式等错误；
- 429：频率超限；
- 500：服务编排或生成题登记异常；
- 502：模型返回空内容、生成题知识点偏离参照题等上游生成失败；**不再仅因难度估计不同返回 502**；
- 503：AI 服务不可用。

## POST `/analyze-questions`

批量使用 `teaching.py` 重新识别历史题目，不调用大模型。

```json
{
  "questions": [
    {"key": "q1", "text": "判断关系R是否自反、对称和传递"}
  ]
}
```

一次最多处理前 80 项；单题分析文本截取前 6000 字符。

## POST `/ocr`

`Content-Type: multipart/form-data`

上传字段支持 `image` 或 `file`，可附带 `request_id`。

限制：

- 文件必须非空；
- 单张图片最大 8 MiB；
- Flask 总请求上限约为 8 MiB + 512 KiB multipart 开销；
- OCR 限流：10 次 / 60 秒 / 客户端 IP。

成功响应示例：

```json
{
  "text": "校对后的题目文字或OCR文字",
  "visual_text": "图形结构说明",
  "text_count": 12,
  "formula_count": 2,
  "vision_used": true,
  "warning": null
}
```

普通 OCR、公式 OCR 与 Vision 具有故障隔离；部分链路失败时尽量返回仍可使用的识别结果。低对比度文字首轮证据不足时执行最多一次增强识别，初始化异常也转 Vision 兜底。若 OCR 已包含明确的数学题目问句，则不会仅因 Vision 返回 `non_exercise` 就抛弃题面；这不等于保证图形连接完全正确。Vision 在同一次图片理解请求中判定 `image_kind`（`exercise` / `non_exercise` / `uncertain`）：明确的非题目图片返回 **HTTP 422** 和 `{"not_a_question": true, "error": "..."}`，不进入核对及解题；对不确定图片使用文本辅助判断，纯图论题仍可进入人工核对。类型判定依赖模型，不保证完全准确。

## POST `/ocr/cancel`

```json
{"request_id": "前端生成的识别请求ID"}
```

用于撤销尚未完成的图片识别任务。成功返回：

```json
{"cancelled": true}
```

## 账号接口

### GET `/auth/me`

返回账号系统是否配置、邮箱服务是否配置、当前浏览器是否已登录，以及当前用户名 / 邮箱、恢复码与已验证邮箱状态。

### POST `/auth/email/send-code`

```json
{
  "purpose": "register",
  "email": "user@example.com",
  "username": "仅注册用途需要"
}
```

`purpose` 仅允许：

- `register`
- `reset`
- `bind`

验证码规则：6 位数字、10 分钟有效、60 秒重发间隔、同邮箱同用途每小时最多 8 次、最多 6 次错误尝试。

重置密码用途对不存在邮箱返回统一成功外观，不直接暴露账号是否存在。

### POST `/auth/register`

```json
{
  "username": "example",
  "email": "user@example.com",
  "password": "......",
  "emailCode": "123456"
}
```

规则：

- 用户名 2–32 个字符，只允许文字、数字、下划线、点、短横线；
- 密码 6–128 个字符；
- 邮箱全局唯一；
- 注册成功后自动登录；
- 成功响应会额外返回一次性明文 `recoveryCode`，数据库不保存其明文。

### POST `/auth/login`

```json
{
  "identifier": "用户名或邮箱",
  "password": "......"
}
```

登录成功后建立服务器签名的 Session Cookie。

### POST `/auth/email/bind`

已登录用户绑定或更换邮箱：

```json
{
  "password": "当前密码",
  "email": "new@example.com",
  "emailCode": "123456"
}
```

### POST `/auth/recovery-code`

已登录用户使用当前密码修改恢复码：

```json
{
  "password": "当前密码",
  "newRecoveryCode": "新的恢复码"
}
```

新恢复码长度要求为 8–64 个字符，不能含控制字符。

### POST `/auth/recover-password-email`

```json
{
  "email": "user@example.com",
  "emailCode": "123456",
  "newPassword": "新密码"
}
```

成功后自动登录，并提升 `auth_version`，使旧 Session 失效。

### POST `/auth/recover-password`

```json
{
  "username": "example",
  "recoveryCode": "恢复码",
  "newPassword": "新密码"
}
```

这是邮箱之外的备用重置路径，不会找回旧密码。成功后自动登录。

### POST `/auth/logout`

清除当前浏览器 Session。账号与云端学习数据不删除。

### POST `/auth/delete-account`

```json
{"password": "当前密码"}
```

要求已登录且再次验证当前密码。删除 `dm_users` 后，关联云数据与验证码记录通过外键级联清理。

## `/sync`

### GET `/sync`

返回：

```json
{
  "ok": true,
  "data": {...},
  "revision": 3,
  "updatedAt": "..."
}
```

### PUT `/sync`

```json
{
  "baseRevision": 3,
  "force": false,
  "data": {
    "schemaVersion": 1,
    "sessions": {...},
    "learning": {...},
    "appearance": {...}
  }
}
```

规则：

- 必须登录；
- `data` 必须为对象；
- `/sync` 内部 `data` JSON 限制为 **12 MiB**，但 Flask 全局 HTTP 请求限制 `MAX_CONTENT_LENGTH = 8.5 MiB` 更严格，**实际请求会先在约 8.5 MiB 处被拒绝**（JSON 包装开销使可用 `data` 更小）；不能宣称当前可完整上传 12 MiB；
- 正常写入要求 `baseRevision` 与云端当前版本一致；
- 冲突返回 HTTP 409，并附带云端数据和最新 `revision`；
- **`force=true` 当前被服务端拒绝（HTTP 400）**；不允许跳过版本检查强制覆盖，客户端收到 409 后应读取最新数据、合并并以新 `baseRevision` 重试。

自定义背景图片 Blob 不在 `/sync` 快照中。

## GET `/health`

```json
{"status": "ok"}
```

## GET `/ready`

```json
{
  "web": "正常",
  "ocr_available": true,
  "ocr_ready": true,
  "ocr_status": "已就绪"
}
```

`ocr_status` 也可以反映公式识别降级状态。

## 2026-10-14：复测难度及生成结果补充

`POST /chat` 的结构化错题复测参照字段示例：

```json
{
  "request_kind": "exercise",
  "exercise_reference": {
    "question": "原错题完整题面",
    "core_points": ["邻接矩阵", "欧拉图"],
    "retest": true,
    "difficulty": "困难"
  },
  "messages": [{"role": "user", "content": "请按原错题的考点生成一道复测题"}]
}
```

`difficulty` 只接受 `简单`、`中等`、`困难`；缺失时后端重新分析原题。`retest` 必须为布尔值 `true`，用于区别普通同知识点出题。通过题干完整性、答案有效性及参照考点校验的候选不会**仅因难度估计偏差**被直接退回 502；如果偏档，API 会返回 `exercise_generation_notice` 供客户端提示。对于复测/显式要求难度的情况，最多使用一次额外质量纠偏；未明确指定难度的普通出题不因此额外生成。分类是启发式而非数学正确性证明。
