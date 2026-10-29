# API

接口由 `app.py` 提供，浏览器使用同源 Cookie 保持登录和图片任务身份。JSON 接口使用 `Content-Type: application/json`；文件上传使用 `multipart/form-data`。错误通常包含 `error`，部分接口另有 `code` 或 `error_code`，应结合 HTTP 状态判断。

## 接口索引

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/` | 主页面 |
| GET | `/web-version` | 当前 Web 源文件修订摘要 |
| POST | `/chat` | 教学对话、出题、确认图片后的解题 |
| POST | `/analyze-questions` | 批量分析题目知识点，可选语义复核 |
| POST | `/ocr`、`/ocr/cancel` | 登记或识别原图、申请取消 |
| GET | `/graph/session` | 初始化当前浏览器的图片任务身份 |
| POST | `/graph/text-region` | 文字选区 OCR |
| POST | `/graph/recognize-region` | 图形选区重识别 |
| POST | `/graph/figure-type` | 扫描选区的箭头、权值类型 |
| POST | `/graph/confirm` | 校验并确认编辑后的完整题目 |
| POST | `/graph/describe` | 已确认图形的可选外观描述 |
| POST | `/drawing/guide`、`/drawing/upload` | 画图指导、上传画板导出结果 |
| POST | `/notebook/analyze` | 解释选中概念或分析关联 |
| POST | `/voice/transcribe` | 录音转文字 |
| GET / POST | `/auth/*` | 账号与邮箱操作，见下表 |
| GET / PUT | `/sync` | 登录用户云同步 |
| GET | `/health`、`/ready` | Web 与识别运行状态 |

另提供 `/robots.txt`、`/sitemap.xml`、站点图标与 `/static/*`。`/service-worker.js` 仅用于注销历史 Service Worker。客户端安装包入口由页面配置提供，不是本服务的包构建接口。

## 通用限制

- 单张图片上限为 **20,000,000 字节**，一般图片解码像素总量上限为 `7680 × 4320`。绘图上传另外要求单帧 PNG，最多 24,000,000 像素。
- 请求体上限为图片上限加 2,000,000 字节选区数据及 512 KiB multipart 余量；文件本身仍单独核对。
- 常规限流按路由、登录会话用户 ID 或游客客户端 IP 计算，窗口为 60 秒：聊天 20 次，取消 45 次，图类型扫描 30 次，其他使用该限流器的路由一般为 10 次。账号操作另有限流和验证码发送限制。
- 只有配置可信代理地址后才使用转发地址识别客户端。限流、取消和活动识别容量均为进程内状态。

## `POST /chat`

普通请求：

```json
{
  "messages": [{"role": "user", "content": "解释等价关系，并举一个例子"}]
}
```

`messages` 必须是数组，仅接受 `user`、`assistant`，忽略空内容和其他角色，最多保留最近 32 条。普通单条消息最多 6000 字符；通过确认快照核验的图片请求单条最多 28000 字符。若消息只引用缺失的“上一题”条件，会返回 400 和 `missing_question_context: true`。

可选字段：

| 字段 | 含义 |
| --- | --- |
| `request_kind` | `exercise` 明确请求出题，`solution` 表示解题请求；具体是否显示答案与解析仍结合本轮文字要求判断 |
| `exercise_reference` | 出题参照对象，必须有非空 `question`；可有 `retest: true`、`difficulty`、最多 4 项 `core_points` |
| `solution_reference` | 已生成题的 `question` 与 `answer`，仅匹配当前题且本轮要求答案时使用 |
| `semantic_context` | `/graph/confirm` 返回的单图完整确认快照 |
| `semantic_contexts` | 1–4 份完整确认快照，按图片顺序提交；不能同时提交 `semantic_context` |

服务端重新分析参照题和生成题。普通出题目标默认中等，错题复测可继承原难度；显式难度偏离时最多额外生成一次，不保证估计难度完全一致。可识别的核心知识点、题干与答案完整性还会进行校验。

成功响应主要字段为 `reply`、`teaching`、`generated_exercise`。生成题另外返回 `generated_question`、`generated_teaching`、`generated_answer`；参考答案可以存在响应中而不展示在初次正文。图形解题可能附带相应结构和计算信息。客户端应保留服务端返回的确认对象，不自行重建或改写其摘要和题目锚点。

主要失败：400 参数或上下文不完整；409 图片确认失效或已修改；429 频率超限；502 上游输出或生成题校验失败；503 服务不可用。用户要求 `max` 思考强度时可返回说明与 `unsupported_effort: "max"`，不是使用该强度。

## `POST /analyze-questions`

```json
{
  "questions": [{"key": "q1", "text": "判断关系R是否自反、对称和传递"}],
  "semantic_fallback": false
}
```

最多处理前 80 项，每题分析前 6000 字符，返回 `results: [{key, teaching}]`。默认使用本地规则；只有显式设置 `semantic_fallback: true` 时才对符合条件的模糊分类尝试模型语义复核。

## `POST /ocr`

表单字段：`image`（也接受 `file`）、可选 `request_id`、`workflow`。请求 ID 应为 1–128 个 ASCII 字母、数字或 `._:-`；缺失或无效时服务端生成新 ID。需要取消或后续选区操作时，应先在客户端建立有效 ID 并保留返回值。

| `workflow` | 行为 |
| --- | --- |
| `auto_graph` | 当前网页自动识图，Qwen `qwen3.8-flash` 主读及按需局部复核 |
| `manual_graph` | 只验证和登记原图，返回空白手工草稿 |
| 不填 | 按后端 nextgen 与 pipeline 配置进入兼容流程，详见 [识别说明](RECOGNITION.md) |

自动识图响应示意：

```json
{
  "request_id": "scan-1",
  "source_sha256": "原图SHA256",
  "workflow_profile": "qwen_targeted",
  "recognition_status": "partial",
  "text": "原图题干",
  "document": {"body_text": "原图题干", "graphs": []},
  "graph_structures": [],
  "review": {"required": true, "reasons": ["有局部内容需要核对"]},
  "warning": "有局部内容需要核对"
}
```

还可返回 `diagnostics` 和服务端耗时。`complete`、`partial` 都是待核对草稿；状态完整不代表与原图逐项一致。手工响应包含 `manual_mode: true`、`recognition_status: "manual"`。各兼容流程返回字段有所不同。

文件缺失或无效返回 400，超限返回 413。同一浏览器同一活动任务重复识别返回 409；活动任务容量满或限流返回 429；自动识别无法生成草稿返回 503。当前自动和手工网页路径不使用旧路径的 `not_a_question` 判定，不能把兼容路径的 422 响应当作所有上传的统一行为。

## `POST /ocr/cancel`

```json
{"request_id": "scan-1"}
```

返回 `{"cancelled": true}` 表示当前浏览器的取消标记已登记。工作流在检查点响应取消；该响应不证明正在进行的上游模型请求已中止。对图形选区任务，应把其 `operation_id` 作为这里的 `request_id`。

## 原图选区接口

以下均为 multipart，请求携带原图 `image` 和已登记的 `request_id`；服务端核对原图摘要及当前浏览器身份，不匹配返回 409。

多边形均是方向校正后原图的归一化坐标，JSON 形式如 `[[0.1,0.1],[0.9,0.1],[0.9,0.5],[0.1,0.5]]`，3–64 个点。

| 路径 | 附加表单字段 | 主要返回 |
| --- | --- | --- |
| `/graph/text-region` | `polygon`；可选 `exclusions`，或改用 `regions` 数组 | `text`、`text_count`、状态及原图标识 |
| `/graph/recognize-region` | `polygon`；建议提供独立 `operation_id` | 图形草稿、选区来源信息、`operation_id` |
| `/graph/figure-type` | `polygon` | `directed`、`weighted`、状态和提示，不新增拓扑 |

`regions` 格式为 `[{"id":1,"order":0,"polygon":[...]}]`，编号和顺序必须各自唯一；一旦使用 `order`，每项都应提供。未提供顺序时按编号排序。批量文字选区响应另有逐区域结果与 `selection_mode: "numbered_regions"`。单选区可通过 `exclusions` 排除图形区域。文字接口只做所选像素的本地 OCR，图形选区接口使用自动识图后把坐标映射回原图。

## `GET /graph/session`

返回 `{"ready": true}` 并在需要时建立图片任务 Cookie。客户端先完成此请求再并发上传，可使同一批图片共享浏览器身份。

## `POST /graph/confirm`

```json
{
  "confirmed": true,
  "request_id": "scan-1",
  "source_sha256": "原图SHA256",
  "document": {
    "body_text": "求图中两个顶点的度数",
    "graphs": [{
      "id": "G1",
      "name": "G1",
      "vertices": [{"id": "v1", "label": "a"}, {"id": "v2", "label": "b"}],
      "edges": [{"id": "e1", "from": "v1", "to": "v2", "direction": "undirected"}]
    }]
  }
}
```

文档 JSON 最多 200,000 字节，题干最多 24000 字符，最多 64 幅图；每图最多 100 个顶点、300 条边。节点与边 ID 在各自图内唯一，子图 ID 在文档内唯一，端点必须存在。确认边方向只能是 `forward` 或 `undirected`；未知方向和未处理疑点会被拒绝。重边逐条列出。

节点 `label: null` 表示原本无名，临时显示编号使用 `display_label`。边 `weight` 表示权值，`edge_label` 表示独立边名。可选坐标和路径用于绘图；完整结构定义以 `graph_confirmation.DOCUMENT_SCHEMA` 和后续语义校验为准。

成功返回规范化 `document`、`drawing_document`、`semantic_context`、`confirmation_token`、文档摘要、修订号、原图标识及校验信息。调用 `/chat` 时原样携带 `semantic_context`；重新编辑后再次确认。服务器记录有效期默认 7 天，重新确认会替换旧令牌与修订号。`validation.image_accuracy_certified` 为 `false`：结构合法与用户确认不构成原图准确率认证。

## `POST /graph/describe`

请求含 `semantic_context` 和匹配的 `drawing_document`。只为已确认图形生成可选外观文字，不修改数学结构；内容改变返回 409，模型描述不可用时可返回 `status: "unavailable"` 与空描述。请求体最多 500,000 字节。

## 画板接口

`POST /drawing/guide` 接收 `{"document": 当前画图文档, "requirement": "本轮要求"}`。要求最多 2000 字符，文档最多 200,000 字节、16 幅图、总计 200 个顶点和 600 条边。允许空白或含未知项的草稿，返回 `ok`、`answer` 和 `document_digest`。它只提供文字指导，不修改或上传图形。

`POST /drawing/upload` 使用 multipart：`image` 为单帧 PNG，`document` 为完整结构 JSON 字符串，`request_id` 为新任务 ID。图片与结构通过校验后登记来源，返回 `ok`、原图摘要、请求 ID 与 `document`。这里不会重新读图或解题，后续仍需确认。

## `POST /notebook/analyze`

```json
{
  "action": "explain",
  "notes": [{"id": "note-1", "title": "等价关系", "content": "自反、对称、传递"}],
  "question": "举一个有限集合上的例子"
}
```

`action` 为 `explain` 或 `relations`，后者至少选 2 条；最多选 12 条。单条标题最多 160 字符、正文最多 6000 字符，所选标题与正文合计最多 24000 字符，补充问题最多 1000 字符。可带 `notes_digest` 核对来源，摘要不匹配返回 409。

返回 `ok`、`action`、`notes_digest`、`explanations`、`relations` 和 `summary`。解释逐条对应所选 ID；不会改写原笔记。未引用有效所选 ID 或输出不完整时返回 502。

## `POST /voice/transcribe`

multipart 字段为 `audio`。仅接受 16 kHz、单声道、PCM16 WAV，时长 0.15–60 秒，文件最多 10 MiB。默认模型 `qwen-audio-3.1-asr-flash`，配置见 [部署说明](DEPLOYMENT.md)。

成功返回 `ok`、`text`、`recognized`、模型和词库标识、音频时长及 `timings_ms`。空转写使用 `recognized: false`；文字只回填输入框，不自动调用聊天。错误可能为 400 格式问题、413 超限、429 繁忙、502 上游失败、503 配置缺失、504 超时。

## 账号接口

除 `/auth/me` 外均为 POST JSON。账号功能需要数据库与认证密钥，邮箱操作还需要邮件服务。

| 路径 | 主要字段与行为 |
| --- | --- |
| `/auth/me`（GET） | 返回 `configured`、`emailConfigured`、`authenticated`；登录时另有 `user`、恢复码和邮箱状态 |
| `/auth/email/send-code` | `purpose` 为 `register`、`reset`、`bind`，加 `email`；注册还需 `username`，绑定需已登录 |
| `/auth/register` | `username`、`password`、`email`、`emailCode`；成功登录并返回初始恢复码 |
| `/auth/login` | `identifier`（兼容 `username`）和 `password`，可使用用户名或邮箱 |
| `/auth/email/bind` | 当前 `password`、新 `email`、`emailCode`，需已登录 |
| `/auth/recovery-code` | 当前 `password`、`newRecoveryCode`，需已登录 |
| `/auth/recover-password-email` | `email`、`emailCode`、`newPassword`，重置成功后登录 |
| `/auth/recover-password` | `username`、`recoveryCode`、`newPassword`，重置成功后登录 |
| `/auth/logout` | 清除当前浏览器登录会话 |
| `/auth/delete-account` | 当前 `password`，需已登录；永久删除账号及关联云数据 |

用户名为 2–32 个允许字符；注册和新密码为 8–128 字符。登录兼容历史 6 位密码。自定义恢复码为 8–64 个字符，不含控制字符。验证码有效期 10 分钟、再次发送至少间隔 60 秒，另有小时发送数与错误次数限制。

常见状态：400 参数或验证码错误；401 未登录或凭据错误；409 名称、邮箱或状态冲突；429 频率超限；503 账号或邮件服务未配置。永久注销不会由服务器直接擦除所有设备的浏览器缓存，客户端清理行为见 [安全与隐私](SECURITY_PRIVACY.md)。

## `GET /sync` 与 `PUT /sync`

仅对当前登录用户开放。GET 默认返回 `ok`、`data`、`revision`、`updatedAt` 和各部分 `parts` 摘要。

| 查询参数 | 作用 |
| --- | --- |
| `revisionOnly=1` | 只读取版本号 |
| `manifestOnly=1` | 读取各部分哈希与字节数 |
| `parts=名称1,名称2` | 读取指定数据部分 |
| `expectedRevision=版本号` | 绑定读取版本，不匹配返回 409 |

PUT 示例：

```json
{"data": {"sessions": [], "learning": {}}, "baseRevision": 0}
```

`data` 必须是完整同步对象，编码后最多 12 MiB。服务端仅在当前 revision 等于 `baseRevision` 时更新并递增版本；冲突返回 409、当前云端数据与版本，客户端合并后重试。`force` 覆盖不受支持。服务端会为旧客户端保留其未携带的已存概念笔记字段。

## 运行状态

`GET /web-version` 返回 `revision`（源文件摘要，无法生成时为 `null`）。`GET /health` 返回 Web 状态、源文件摘要、识别预算和兼容 pipeline 标识。`GET /ready` 返回本地 OCR、阶段及兼容识别状态；它通常不以失败 HTTP 状态表示依赖未就绪。

这些接口不主动请求模型，不是远程凭据探测或图片准确率检查。网页 `auto_graph` 的实际模型与运行结果应根据其请求、`workflow_profile` 和识别诊断判断。
