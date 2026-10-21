# 系统架构说明

## 1. 总体结构

DMate 当前可以划分为五个逻辑层：

1. **前端交互与题目状态层**：`templates/index.html` + `static/script.js`
2. **账号、会话与同步层**：Flask Session + PostgreSQL + 前端同步状态
3. **Flask 服务编排层**：`app.py`
4. **教学理解与知识组织层**：`teaching.py` + `knowledge_graph.json`
5. **模型、OCR 与外部服务层**：`ai.py` + `ocr.py` + DeepSeek + 可选鲁信通道 + Brevo/SMTP

```mermaid
flowchart LR
    U["用户"] --> F["前端交互层"]
    F -->|/chat| A["Flask app.py"]
    F -->|/ocr| A
    F -->|/auth/*| A
    F -->|/sync| A
    A --> T["teaching.py"]
    T --> KG["knowledge_graph.json"]
    A --> TXT["文本模型路由\n鲁信可选 → DeepSeek兜底"]
    A --> OCR["PaddleOCR"]
    A --> VIS["Qwen3-VL-235B-A22B-Thinking"]
    A --> DB["PostgreSQL\n账号 + 云同步"]
    A --> MAIL["Brevo API / SMTP\n邮箱验证码"]
```

## 2. 文本学习链路

```text
用户最新输入
→ 前端解析显式题目指代 / 当前题
→ 构造题目锚点与本轮唯一请求
→ POST /chat
→ app.py 清洗、限流、消息长度控制
→ teaching.py 分析教学模式、模块、知识点、题型、难度、难点与前置知识
→ ai.py 根据难度选择思考强度并选择文本提供方
→ 返回回答与 teaching 元数据
→ 前端 Markdown → DOMPurify → MathJax 渲染
→ 更新当前题、会话、学习状态与云同步状态
```

### 教学模式

- `hint`：提示引导
- `full_solution`：完整解析
- `concept`：概念讲解
- `exercise`：练习出题
- `check_answer`：答案诊断

文本题求解默认提示优先；完整解析由明确请求触发。

## 3. 题目难度与模型思考强度

`teaching.py` 对正式题目给出三档难度：

```text
简单 / 中等 / 困难
```

`ai.py` 根据 `teaching_context.difficulty` 选择：

```text
简单 → none
中等 → high
困难 → high
```

普通输出预算受 `DEEPSEEK_MAX_OUTPUT_TOKENS` 控制；`high` 推理（中等、困难共用）预算受 `MEDIUM_MAX_OUTPUT_TOKENS` 控制。当前代码不读取 `HARD_MAX_OUTPUT_TOKENS`，也不会向模型发送 `max`。出题生成默认先走非思考路径，和最终题目难度并非一一对应。

练习生成时，后端把“目标难度”和“生成后的实际难度”分开处理，必要时允许重生成一次。

## 4. 文本模型路由与熔断

文本回答代码支持：

```text
鲁信杯兼容接口（可选、优先）
        ↓ 失败 / 禁用 / 熔断
DeepSeek Chat Completions（兜底）
```

鲁信通道支持：

- `LUXIN_ENABLED` 总开关；
- `LUXIN_MODEL_ID` 显式模型 ID；
- 未配置模型 ID 时一次性 `/v1/models` 探测；
- 后台网络探测；
- 熔断冷却；
- 失败自动切换 DeepSeek。

Vision 不走该文本切换链，独立使用阿里云百炼 Qwen3-VL-235B-A22B-Thinking。

## 5. 上下文管理

后端：

```text
MAX_MESSAGES_PER_REQUEST = 32
MAX_MESSAGE_CHARS = 6000
```

AI 历史：

```text
MAX_HISTORY_MESSAGES = 32
MAX_HISTORY_CHARS = 60000
MAX_MESSAGE_CHARS = 6000
```

前端自然语言回退：

```text
FALLBACK_API_CONTEXT_MESSAGES = 12
```

前端优先使用明确题目对象和题目指纹，而不是机械提交完整聊天历史。只有显式题目状态不可用时才退回近期自然语言消息。

## 6. AI 生成题链路

```text
用户要求出题
→ 判断独立出题 / 参照题出题
→ request_kind="exercise"
→ 可选 exercise_reference.question
→ 后端重新分析参照题
→ 解析目标难度
→ 强制 exercise 教学模式
→ AI 生成题目 + 内部参考答案
→ 分离可见题干 / 隐藏答案
→ analyze_question(generated_question)
→ 校验参照题模块与可识别核心知识点是否匹配
→ 校验生成题实际难度
→ 未明确要求难度时不拦截有效题；明确难度不匹配时最多补充生成一次，仍偏离则保留已通过知识点校验的有效题（不保证难度完全匹配）
→ 前端登记为正式生成题
```

普通独立出题和同知识点参照出题未指定难度时以**中等**为目标；**错题本复测**通过独立 `retest` 标志继承已存的错题难度，缺失时后端分析原题。普通参照题出题在已识别核心知识点时至少要求一个知识点相交；**错题本结构化复测**如给出了 `retest_core_points`，则要求新题覆盖其中**全部**核心知识点（前端最多提取 4 项），否则拒绝该候选。这是启发式知识一致性检查，不能证明数学答案正确。

## 7. OCR + Vision 链路

OCR 模型：

- `PP-OCRv6_small_det`
- `PP-OCRv6_small_rec`
- `PP-FormulaNet_plus-S`
- CPU 推理
- 图片最长边 2200 px

流程：

```text
图片
→ /ocr（8 MiB）
→ EXIF方向处理 + 图像预处理
→ PaddleOCR文字
→ FormulaNet公式
→ Qwen3-VL-235B-A22B-Thinking 校对与图形结构解析
→ Vision 在原调用中标识 exercise / non_exercise / uncertain
→ 明确非题目返回 422、不进入 AI 解题；不确定和纯图题保留核对
→ corrected text + visual text
→ 手机端核对区独立滚动、底部操作固定，识别中隐藏图片入口
→ 前端组合为题目上下文
```

前端可通过 `/ocr/cancel` 撤销识别请求。普通 OCR、公式识别和 Vision 具有故障隔离，尽量保留仍可使用的部分结果。

## 8. 知识组织层

`knowledge_graph.json` 当前包含：

- 10 个模块
- 68 个节点
- 保留“RSA公钥密码”“矩阵树定理”等拓展知识点；本版新增“模逆与中国剩余定理”“图同构”“二部图”“拓扑排序”

`prerequisites` 表示建议学习前置 / 依赖关系，不表示严格逻辑蕴含。

`teaching.py` 可从图结构与常见题干识别图同构、二部图、拓扑排序，从模运算题识别模逆 / 中国剩余定理，也支持无显式“齐次”字样的公式型递推识别。明确题型信号优先落到选择、填空、证明、作图、构造、判断、计算等类型；无法区分时使用“一般题”。

`teaching.py` 主要输出：

- `category`
- `knowledge_points`
- `focus_points`
- `prerequisite_points`
- `knowledge_path`
- `question_type`
- `difficulty`
- `mode`
- `mode_label`

## 9. 账号与数据库结构

账号系统在未配置数据库时不会影响游客模式；配置后使用 PostgreSQL。

主要表：

```text
dm_users       账号、邮箱、密码哈希、恢复码哈希、auth_version
dm_user_data   云同步 JSONB、revision、updated_at
dm_email_codes 邮箱验证码摘要、用途、过期时间、错误次数、消费时间
```

密码和恢复码使用 Werkzeug `scrypt` 哈希；邮箱验证码不保存明文，使用 `AUTH_SECRET_KEY` 参与 HMAC-SHA256 摘要。

## 10. Session 与账号生命周期

服务器 Session Cookie：

- HttpOnly；
- SameSite=Lax；
- Secure 默认开启；
- `PERMANENT_SESSION_LIFETIME = 30 days`；
- 每次请求滚动续期。

`auth_version` 用于使旧 Session 失效；密码重置会提升版本并重新建立当前登录会话。

## 11. 游客、本机缓存与云同步

游客：

```text
会话 / 学习状态 / 外观
→ 只保留当前页面运行状态
→ 不写持久 localStorage
```

登录用户：

```text
前端状态
→ localStorage 本机缓存
→ collectCloudSnapshot()
→ PUT /sync
→ PostgreSQL JSONB
```

云快照包含：

- sessions
- learning
- appearance 参数

自定义背景图片 Blob 使用 IndexedDB，仅保存在当前设备，不进入云快照。

同步通过 `revision` 做乐观并发控制。冲突时后端返回 409 和云端最新数据，前端**按 ID 自动合并**并使用新修订号重试（至多尝试若干次）；发生会话分叉时保留另一设备的分支，避免静默丢消息。后端不允许 `force=true` 强制覆盖，也没有“覆盖云端/使用云端”的交互弹窗。

## 12. 错题闭环

```text
正式题目
→ 记为错题
→ 答案 / 解析 / 笔记
→ 完成订正
→ 保存 referenceQuestion
→ exercise_reference 结构化参照
→ 生成同核心知识点复测题
→ 保存 generatedQuestion + hidden generatedAnswer
→ 提交复测答案
→ 独立答案诊断
→ 更新复测统计
```

浏览器端错题上限 80 条。

## 13. 前端内容安全与数学渲染

```text
AI文本
→ 数学内容保护 / 整理
→ Marked
→ DOMPurify sanitize
→ 恢复数学片段
→ MathJax SVG
```

Marked 只负责 Markdown，不承担 HTML 安全过滤。

### 富文本、公式选择与知识图谱图片复制

- 渲染层使用 Marked、DOMPurify 与 MathJax；复制层为普通文字和公式混排内容分别生成 `text/plain` 与 `text/html`。公式在 HTML 里优先使用内嵌 SVG 图片，纯文本使用 LaTeX 回退，保证不支持富文本的环境也有可读结果。
- 页面支持正常文字选区、跨 MathJax 混合选区、公式字形级局部选中；统一高亮颜色，并在复制事件中按当前选择构建内容。输入框仍走浏览器原生复制，不应被富文本拦截。
- 复制按钮按场景限制：聊天只暴露完整题目的复制，错题本每题可复制，弹窗、控件与隐藏部分会在内容序列化时清理。
- 知识图谱复制以完整图形 PNG 为目标，支持 `image/png` 剪贴板时直接写入；不支持则尝试下载 PNG，不退化成纯文字替代。
- 复制功能存在浏览器权限、粘贴目标格式兼容边界；本实现不能保证所有目标编辑器可把 SVG 自动转回可编辑的原生数学公式。

## 14. PDF 导出

```text
错题 DOM
→ 等待 MathJax
→ 处理 SVG / 辅助 MathML
→ html2canvas
→ jsPDF
→ A4 PDF
```

MathJax 使用 `fontCache: 'none'`。

## 15. 服务运行结构

Gunicorn 记录配置：

```text
gunicorn -w 1 --threads 2 --timeout 300 -b 0.0.0.0:${PORT:-8080} app:app
```

进程内 60 秒限流：

- `/chat`：20 次 / 60 秒 / 客户端 IP；
- `/ocr`：10 次 / 60 秒 / 客户端 IP；
- 账号相关接口：按路由分别 20 次 / 60 秒 / 客户端 IP；
- 邮箱验证码另有 60 秒重发、8 次/小时和 6 次错误尝试限制。

## 16. 网页端与安装包的更新边界

- **服务器端**：修改并部署 `app.py` / `teaching.py` / `knowledge_graph.json` 后，新请求执行新的服务器逻辑；不需要重建原生客户端。
- **远程前端**：桌面 Tauri 的 `frontendDist` 与窗口 URL 均指向 `https://dmate.zeabur.app`；Android `DMATE_URL` / WebView 同样指向远程站点。部署 `templates/index.html` 与 `static/script.js` 后，刷新或重启客户端获取新页面（受网络与缓存影响）。
- **安装包自身**：Android 和桌面壳有代码、权限、版本、签名等变更时必须重新构建；目前没有安装包二进制自动升级组件。
- **iOS / iPadOS WebClip**：通过 `.mobileconfig` 将官网添加到主屏幕；它打开在线网页，不使用独立 Service Worker 缓存。

上述“随服务端生效”指部署成功之后的后续请求，不意味着尚未部署的本地修改会自动出现在用户设备上，也不是无条件实时推送到已打开的页面。

## 17. 多平台远程页面与发行渠道（2026-10-13）

```text
浏览器 / iOS WebClip
            │
Tauri (Windows NSIS / macOS DMG / Linux DEB、AppImage、Snap)
            │
Android WebView APK
            ▼
https://dmate.zeabur.app/  ← Zeabur + Flask + PostgreSQL / AI 服务
```

所有这些客户端**使用远程网页业务层**，并非每种系统都复制一套独立的 AI 后端。区别主要在窗口、安装器、分发方式、操作系统权限与文件/剪贴板行为：

- Windows / macOS / Linux：`desktop/src-tauri/tauri.conf.json` 使用 Tauri 2，产品版本 1.0.0；Github Actions 生成 NSIS、DMG、DEB/AppImage。
- Linux Snap：构建 Tauri DEB 再以 `core24`、GNOME 扩展、`strict` 沙盒封装为 AMD64 Snap，Store Revision 1 已发布 `stable`；Snap 包更新与网页内容更新是两条独立渠道。
- Android：`android/` 为 WebView 原生壳，有独立 debug APK Actions，正式签名与审核以实际渠道记录为准。
- iOS：`.mobileconfig` 提供 Apple WebClip 主屏幕入口；不是 IPA / 原生商店程序。

客户端没有自有 AI 推理核心，联网和 Zeabur / 运行时服务可用性是使用 AI 功能的必要条件；WebClip 只是官网快捷入口，不提供离线 AI 能力。

## 18. 网站可发现性与搜索引擎（2026-10-13）

首页 SEO/平台验证由 `templates/index.html` 承担（Description、H1、Alt、Bing/Baidu 校验标签）；Bing Site Scan/URL Inspection 与百度站点验证/手工提交属于外部索引流程，**不影响 Flask 业务路由、用户数据和模型选择**。旧子域名已经不能访问，应以 `https://dmate.zeabur.app/` 作为唯一公开入口。`robots.txt`、`sitemap.xml`、canonical 仍列为候选 SEO 改进，非当前已完成代码功能。

### 2026-10-14 可靠性修复

出题候选必须先过实际题面、隐藏答案、部分可精确计算的答案一致性、题目条件和参照知识点校验；这些失败依然阻断存题。**难度分类只是启发式标签**：复测继承原错题目标难度并允许一次纠偏，普通出题默认中等但不因第一次有效候选的分类偏差追加网络请求；纠偏后仍偏档时不再丢弃有效题，返回实际难度与偏差信息。这降低了“题目有效却因分类器不一致而反复失败”的风险。

OCR：首轮文本证据不足时，第二次文字识别仅对局部对比度作温和增强；第二轮失败保留首轮。公式识别只运行一次。文本 OCR 模型抛出非 `OCRError` 的异常时允许进入 Vision。图片类型 `non_exercise` 拦截增加明确数学问句保护，既保留教材图题，也不直接放行普通笔记。OpenCV 对弧线、交叉边、低清图可能不识别，人工核对流程仍保留。
