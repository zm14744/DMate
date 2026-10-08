# API 说明

基础服务由 `app.py` 提供。本文只描述 DMate 产品运行接口，不包含安装包构建接口。

## 接口总览

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/` | 主页面 |
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
- 有参照题且未指定难度时，继承参照题难度；
- 独立泛化出题默认中等；
- 生成后再次分析实际难度：**未显式指定难度时不以估计差异拦截有效题目**；明确指定难度时最多额外重试一次，仍不匹配则可保留通过题目及知识点校验的有效题目，实际难度不保证与目标完全一致；
- 当有参照题时，生成题还需通过**课程大类 + 已识别核心知识点交集**检查。若知识点已明确且完全不相交，返回 502 并提示重新出题；识别不充分时不会仅凭规则断言不匹配。

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

`generated_answer` 只用于后续复测核验，不在初次出题正文直接展示。

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

普通 OCR、公式 OCR 与 Vision 具有故障隔离；部分链路失败时尽量返回仍可使用的识别结果。Vision 在同一次图片理解请求中判定 `image_kind`（`exercise` / `non_exercise` / `uncertain`）：明确的非题目图片返回 **HTTP 422** 和 `{"not_a_question": true, "error": "..."}`，不进入核对及解题；对不确定图片使用文本辅助判断，纯图论题仍可进入人工核对。类型判定依赖模型，不保证完全准确。

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
- 单次同步 JSON 最大 5 MiB；
- 正常写入要求 `baseRevision` 与云端当前版本一致；
- 冲突返回 HTTP 409，并附带云端数据和最新 `revision`；
- `force=true` 用于用户明确选择“用本设备覆盖云端”后的强制写入。

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
