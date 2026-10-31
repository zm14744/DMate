# API

接口由 `app.py` 提供，浏览器使用同源 Cookie 保持登录和图片任务身份。JSON 接口使用 `Content-Type: application/json`；文件上传使用 `multipart/form-data`。错误通常包含 `error`，部分接口另有 `code` 或 `error_code`，应结合 HTTP 状态判断。

本文描述当前仓库行为，面向前端维护和自托管集成。模型与服务配置见[部署说明](DEPLOYMENT.md)，普通用户操作见[使用指南](USER_GUIDE.md)。下文响应例子仅展示相关字段，不保证列出该路由所有诊断字段；示例中的摘要、令牌、题干和回复是占位说明，不能当作真实确认值使用。

## 请求方式与身份

- API 与网页默认同源；浏览器可使用 `fetch(path, {credentials: "same-origin"})`。仓库没有提供供第三方跨域网站使用的通用 CORS 接入或 Bearer Token 登录 API。
- 登录由 `dm_tutor_session` 签名 HttpOnly Cookie 表示，前端不读取登录令牌。图片任务另使用 `dm_graph_owner` HttpOnly Cookie，并与当前登录用户身份共同确定归属。
- 游客可以调用不要求账号的聊天、识图等功能，但仍受模型配置、容量和频率限制。`/sync`、邮箱绑定、恢复码设置、注销账号等有相应登录要求。
- `/chat`、识图、笔记分析、绘图指导、语音转写返回完整 JSON；这些路由不是 SSE 或 WebSocket 流式协议。页面上的等待和停止由客户端请求状态管理。
- multipart 请求由浏览器 `FormData` 或上传客户端生成 `Content-Type` 及 boundary；不要手工只填 `multipart/form-data` 而遗漏 boundary。
- 账号登录 / 退出后图片任务的身份范围会变化，其他浏览器或设备不能仅复制任务 ID 和令牌来复用原确认。

普通 JSON 调用示例：

```js
const response = await fetch("/chat", {
  method: "POST",
  credentials: "same-origin",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    messages: [{ role: "user", content: "解释等价关系，并举一个例子" }]
  })
});
const result = await response.json();
if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
// result.reply 是回答正文；teaching 是教学分析，不等同于正文。
```

调用模型接口会实际使用已配置的模型服务；这些示例不是静态健康检查。客户端应在提交后锁定相应任务，按一次响应完成状态更新，避免对同一输入自动循环重复 POST。

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

### 常见响应与重试

| HTTP 状态 | 典型含义 | 客户端处理 |
| --- | --- | --- |
| 200 | 路由已返回结果；仍可能是空转写、待核对草稿、已登记取消等业务状态 | 继续读取 `recognized`、`recognition_status`、`cancelled` 等字段 |
| 400 | JSON / 文件 / 结构字段或当前题目上下文不符合要求 | 修正输入，保留原草稿供编辑 |
| 401 | 未登录或账号凭据不正确 | 区分需要登录与账号错误，不清除本机学习数据来“重试” |
| 409 | 原图身份、确认版本或同步版本冲突 | 根据错误码重新核对图片，或读取云端合并 |
| 413 | 请求、文件、像素、文档或同步体超限 | 缩小文件或拆分内容；代理也可能先返回自身的 413 |
| 422 | 某些结构检查未通过，或兼容识别路径拒绝相应输入 | 查看该路由的 `code` / `issues`，不要将所有 422 都解释为“不是题目” |
| 429 | 频率限制或活动任务 / 专项服务容量已满 | 稍后由用户重试，不对同一任务立即并发补发 |
| 500 | 账号 / 同步等内部操作失败 | 保留本机数据并查看服务日志 |
| 502 / 503 / 504 | 上游输出失败、服务不可用或超时；具体依路由而定 | 展示路由错误，保留输入，避免假定原操作从未执行 |

错误字段并未统一为一种固定格式，例如确认接口可返回 `issues`，识别接口可能用 `error_code`，语音可返回 `provider_code`。不要只判断是否有 `ok: true`，部分成功接口并没有 `ok` 字段。生产代理也可能返回 HTML 错误页，客户端解析 JSON 失败时仍应保留 HTTP 状态及用户输入。

## `POST /chat`

普通请求：

```json
{
  "messages": [{"role": "user", "content": "解释等价关系，并举一个例子"}]
}
```

`messages` 必须是数组，仅接受 `user`、`assistant`，忽略空内容和其他角色，路由最多保留最近 64 条。普通单条消息最多 20,000 字符；模型历史另有 120,000 字符总预算，优先保留当前题、最新请求和最近交流。用户和 AI 消息分别计数，64 条不是 64 轮；丢弃旧上下文不会删除聊天存储。通过确认快照核验的图片请求单条仍为 28,000 字符。若消息只引用缺失的“上一题”条件，会返回 400 和 `missing_question_context: true`。

完整“当前指向题目 / 本轮唯一需要执行的用户请求”以及固定复测检查包装可在校验后使用 42,000 字符内部界限，题干与本轮文字分别不得超过 20,000 字符；不完整标记、超长子字段和任意普通长文本仍按 20,000 字符判断。此前端协议用于保留完整长题，不能简单把所有单条消息都放宽到 42,000。

历史按完整消息选择，不对当前题做前缀截断。提供方若明确报告 token 上下文容量不足，最多额外尝试一次移除旧历史；仍不足时返回明确提示，不能将 120,000 字符当作提供方保证的 token 容量。模型的输出长度配置独立于这些输入 / 历史边界。

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

普通回答结构示意：

```json
{
  "reply": "等价关系同时满足自反性、对称性和传递性……",
  "teaching": {"mode": "concept", "difficulty": "简单"},
  "generated_exercise": false
}
```

`teaching` 的字段由题目分析决定，不能把示例的模式和难度硬编码为所有请求的返回值。生成练习时 `generated_exercise` 为 `true` 且存在生成题目字段，客户端可将参考答案单独保存，用户明确查看答案后再展示。

上下文由调用方提供，后端不会按一个客户端会话 ID 从数据库自动拼回聊天历史。因此只发送“继续上一题”而不携带条件，可能触发 `missing_question_context`；改变题目后也不应沿用旧题的 `exercise_reference`、`solution_reference` 或图片确认。

网页“题目：是 / 否”与图片分组是前端学习记录策略，不是 `/chat` 的同名参数。题目是否收录、一个分组对应几张图，不应通过给普通消息添加未经后端定义的字段来实现。

## `POST /analyze-questions`

```json
{
  "questions": [{"key": "q1", "text": "判断关系R是否自反、对称和传递"}],
  "semantic_fallback": false
}
```

最多处理前 80 项，每题分析前 20,000 字符，返回 `results: [{key, teaching}]`。默认使用本地规则；只有显式设置 `semantic_fallback: true` 时才对符合条件的模糊分类尝试模型语义复核。

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

同源上传示例，`file` 是用户选择的 `File`：

```js
const identity = await fetch("/graph/session", { credentials: "same-origin" });
if (!identity.ok) throw new Error("无法初始化图片任务");

const form = new FormData();
form.append("image", file);
form.append("request_id", `scan-${crypto.randomUUID()}`);
form.append("workflow", "auto_graph");
const response = await fetch("/ocr", {
  method: "POST", credentials: "same-origin", body: form
});
const draft = await response.json();
if (!response.ok) throw new Error(draft.error || "识别未完成");
// 保存 request_id、source_sha256 和草稿，并先交给用户编辑核对。
```

初始化图片身份应在并发上传前完成。识别任务 ID 与原图字节绑定，重试同一来源可保留 ID，换图必须新建 ID；相同任务仍在运行时不能并发重复提交。文件摘要基于服务端收到的原始字节，后续选区必须再次提交同一原图，不能改传缩略图、截图或重新压缩后的文件。

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

选区不是显示器上的像素坐标。客户端先把指针坐标换算到校正方向后的原图，再按宽高归一化到 0–1；缩放和平移只改变显示，不应改变所选原图位置。`polygon`、`exclusions`、`regions` 在 multipart 中都传 JSON 字符串，不能直接把 JavaScript 数组转换为默认的逗号字符串。

`/graph/recognize-region` 的原图身份仍用 `request_id`，本次重识别的取消与容量跟踪用 `operation_id`。取消选区识别时向 `/ocr/cancel` 提交该 `operation_id`，不能用一次新的随机 ID。`/graph/figure-type` 只返回方向 / 权值判断，不自动补顶点、边、路线或完整题干；`unknown` 是未判断出，不能在数据层当作无向 / 无权。

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

### 确认结果中各字段的用途

| 字段 | 用途与使用约束 |
| --- | --- |
| `document` | 规范化数学语义内容，后续计算以其端点和边实例为依据 |
| `drawing_document` | 用于编辑 / 还原绘图的布局内容，与数学结构分开保留 |
| `source_sha256` | 本次原图原始字节 SHA256，不是可自行替换的文件名 |
| `request_id` | 已登记的原图任务 ID |
| `document_sha256` | 服务端规范化文档摘要 |
| `revision` | 本来源每次成功确认递增，旧修订不能替代新修订 |
| `confirmation_token` | 本次确认的随机令牌，应与完整确认对象一起保留 |
| `semantic_context` | 发送 `/chat` 的完整快照，内含题干锚点、身份、结构、摘要、修订和令牌 |
| `validation` | 结构校验和工具记录；不是对原图逐像素读准的认证 |

`confirmed: true` 必须是 JSON 布尔值，字符串 `"true"` 不等价。确认只对已登记原图执行校验与保存，不调用模型，不自动开始聊天。纯文字图片可使用空 `graphs`，但文档应包含有效题目文字；有图时端点、名称、方向和权值需按实际核对结果提交。

已确认单图发送示例：

```js
// confirmation 为本浏览器刚刚完成 /graph/confirm 的实际响应。
const context = confirmation.semantic_context;
const userRequirement = explicitUserInput.trim();
const content = userRequirement
  ? ["【当前指向题目】", context.question_text, "【当前指向题目结束】", "",
     "【本轮唯一需要执行的用户请求】", userRequirement, "【本轮请求结束】"].join("\n")
  : context.question_text;

const response = await fetch("/chat", {
  method: "POST", credentials: "same-origin",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    messages: [{ role: "user", content }],
    semantic_context: context
  })
});
```

`explicitUserInput` 只表示用户实际写入的额外要求，空白时不生成默认要求。不要只提交令牌、只提交边列表，或在快照内改题干后沿用旧摘要。`confirmation_stale` 需重新确认当前任务，`confirmation_changed` 需核对修改后的内容；`unknown_source_task` 则需要在当前身份重新建立原图任务。

上述内部标记用于把已确认题目与本轮操作分开；网页展示的用户消息可以将真实补充内容标为“【我的要求】”。两者都不能在空白时替用户生成要求，也不能因此改变 `semantic_context` 内的原始题干。

多图用 `semantic_contexts: [context1, context2, ...]`，每份都来自各自成功确认。消息题干按顺序采用 `【图片 1】\n` 加第一份 `question_text`、空行、`【图片 2】\n` 加第二份，以此类推。每次最多 4 份，不能重复同一来源，组合后的正文和结构也有上限；每张都未超限不等于组合后必然可发送。确认图片解题不能与生成新练习共用同一次确认请求。

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

### 账号调用顺序

1. 先读取 `/auth/me`，区分账号服务未配置、已配置但未登录、当前已登录。HTTP 200 和 `ok: true` 不代表 `authenticated: true`。
2. 注册前向 `/auth/email/send-code` 提交 `purpose: "register"`、用户名及邮箱，再由用户输入邮件验证码调用 `/auth/register`。
3. 注册、登录或找回成功后由响应 Cookie 建立会话。注册响应的一次性 `recoveryCode` 应立即交给用户保存，不能再从服务器读回明文。
4. 邮箱绑定使用 `purpose: "bind"` 的验证码，并提交当前密码；邮箱找回使用 `purpose: "reset"`，两者验证码不能互换。
5. 恢复码找回提交用户名和恢复码。修改密码后账号会话版本更新，旧版本签名会话失效。
6. `/auth/logout` 结束当前浏览器会话；`/auth/delete-account` 是永久删除操作，需要当前密码，含义不同。

登录与邮箱字段应原样作为 JSON 字符串提交，由服务器执行规范化；不要在客户端自己实现另一套大小写规则。错误响应不会返回数据库密码哈希或恢复码哈希。

## `GET /sync` 与 `PUT /sync`

仅对当前登录用户开放。GET 默认返回 `ok`、`data`、`revision`、`updatedAt` 和各部分 `parts` 摘要。

| 查询参数 | 作用 |
| --- | --- |
| `revisionOnly=1` | 只读取版本号 |
| `manifestOnly=1` | 读取各部分哈希与字节数 |
| `parts=sessions,learning,appearance` | 按需读取其中指定的数据部分 |
| `expectedRevision=版本号` | 绑定读取版本，不匹配返回 409 |

PUT 示例：

```json
{"data": {"sessions": [], "learning": {}}, "baseRevision": 0}
```

`data` 必须是完整同步对象，编码后最多 12 MiB。服务端仅在当前 revision 等于 `baseRevision` 时更新并递增版本；冲突返回 409、当前云端数据与版本，客户端合并后重试。`force` 覆盖不受支持。服务端会为旧客户端保留其未携带的已存概念笔记字段。

上例只是接口形状，真实前端同步对象还包括自身版本、会话及学习数据结构。不要把 `{sessions: [], learning: {}}` 当作“检查连接”的无副作用写请求，它会提交这些空内容。

版本冲突响应示意：

```json
{
  "ok": false,
  "conflict": true,
  "error": "云端数据已经被其他设备更新",
  "data": {},
  "revision": 7,
  "updatedAt": "2026-10-30T00:00:00+00:00",
  "parts": {}
}
```

其中 `data` 和 `parts` 应为服务端实际返回的云端内容，这里的空对象仅用于缩短示例。推荐读取流程为 revision → 同版本 manifest → 有变化的指定 parts；所有后续读取都绑定 `expectedRevision`。过程中收到 409 就重新开始版本读取，不能把不同 revision 的分段合成已完成快照。

`baseRevision` 必须是非负整数或可解析为非负整数的字符串，不接受布尔值、浮点数和非有限值；同步数据本身也不能包含 `NaN` / `Infinity`。PUT 成功只说明服务器已接受此快照，不会自动把独立绘图库、背景图片文件和进行中的图片任务转成云同步数据。

manifest 中 `sessions`、`learning`、`appearance` 各包含 `hash` 与 `bytes`；它们是服务端对对应部分序列化后的摘要与大小。读取分段时只支持这三个名称，不能通过任意键名查询其他用户数据或服务器配置。概念笔记由学习快照保存，并非另一个未列出的通用数据库查询接口。

## 运行状态

`GET /web-version` 返回 `revision`（源文件摘要，无法生成时为 `null`）。`GET /health` 返回 Web 状态、源文件摘要、识别预算和兼容 pipeline 标识。`GET /ready` 返回本地 OCR、阶段及兼容识别状态；它通常不以失败 HTTP 状态表示依赖未就绪。

这些接口不主动请求模型，不是远程凭据探测或图片准确率检查。网页 `auto_graph` 的实际模型与运行结果应根据其请求、`workflow_profile` 和识别诊断判断。
