# 实际上传路径的隔离验收

`scripts/verify_ocr_application_upload.py` 补充既有管线评测和弹窗重放：它让真实 Chromium 选择文件，经过页面现有上传事件、真实 Flask `/ocr` 路由、首个 HTTP 响应和现有核对弹窗，并读取真实 `/health`、`/ready`。它不直接调用弹窗来代替上传，不替换 `/ocr` 整体响应，不修改应用行为。

## 当前可以验证什么

`synthetic` 模式在新进程中导入应用，事先设置 `DMATE_GRAPH_NEXTGEN=1`，绑定 `127.0.0.1` 并启用 threaded server。环境采用允许清单，排除生产数据库、邮件、账号、代理和真实模型密钥；非秘密 sentinel 只用于通过配置检查。Requests、socket、数据库和邮件发送边界全部阻断并记录尝试，任何一次企图都会令契约验收失败。浏览器只访问该本地服务，外部脚本由已有且校验过摘要的公共 CDN 缓存提供，不下载替代库。

合成注入仅发生在 `ocr_runtime.run_worker`、`ai._request_qwen_completion` 和 `ai._request_text_completion`。真实图片解码、透明图白底合成、worker 编排、VisionProvider 构造和预算、两轮图结构管线、文本保护、Flask 状态传播、上传处理和 UI 保留运行。因此，输出中的 provider metrics 是由注入边界产生的合成观察，不能声称是真实模型发送。报告固定标明 `fixture_only=true`、实际 Qwen/DeepSeek 发送均为 `0`。

当前合成场景包括：

- 透明 PNG 正常上传，服务器收到的原始字节与选择文件一致，UI 使用真实首响应。
- 文字 worker 内存限制，`/ready` 不就绪，警告不能误称公式降级，部分结果可核对。
- Qwen 传输失败，HTTP 200 的失败 body 不被当成识别成功，错误在 UI 可见；本地文字就绪状态独立保留。
- 文字 worker 暂停时通过真实取消按钮调用 `/ocr/cancel`，文字完成后不进入视觉调用，不打开核对弹窗。
- 处理中和核对中再次选择文件，不增加 `/ocr`；核对取消或 Escape 不写入识别问题、不发送 `/chat`，控件释放。

取消视觉内部调用、限流、认证及部署容量等既有独立测试不由本 harness 重新认证。视觉阶段没有中断两轮调用的回调，所以这里也不声称视觉开始后的取消一定能节省第二次调用。

## 运行合成契约

使用仓库测试环境已安装的 Chromium 和预先校验的缓存，输出必须是仓库外尚不存在的新目录。每次失败观察也会保留，不覆盖旧响应。

```bash
python scripts/verify_ocr_application_upload.py \
  --mode synthetic \
  --browser /private/chromium/chrome \
  --cdn-cache /private/verified-public-js \
  --output /private/upload-contract-run-01
```

对应 pytest 测试统一读取 `DMATE_BROWSER_EXECUTABLE`、`DMATE_BROWSER_CDN_CACHE`、`DMATE_UPLOAD_INTEGRATION_OUTPUT`：

```bash
python -m pytest -q tests/test_ocr_upload_integration.py
```

浏览器配置缺失会明确 skip，不能计作浏览器通过。`application_contract_status=pass` 仅表示指定合成契约通过；顶层 `status` 仍为 `not_certified`，`application_status=not_certified`，`application_certified_passes=0`，`first_pass_certified_images=0`。命令退出码 `0` 的含义也是合成/观察契约检查通过，绝不是模型识别准确率通过。

## 后续真实测试服务入口

具备模型配置并明确获授权的隔离测试服务，可以使用同一个文件选择入口采集真实首次响应：

```bash
python scripts/verify_ocr_application_upload.py \
  --mode observed-http \
  --base-url http://127.0.0.1:5000 \
  --manifest /private/originals/manifest.json \
  --browser /private/chromium/chrome \
  --cdn-cache /private/verified-public-js \
  --output /private/actual-upload-observations-01
```

此模式不启动服务、不配置账号、不传入凭据，也不修改现有服务。必须由操作者明确指定已授权的本地测试实例；不接受生产域名、任意 IP、带凭据的 URL 或重定向。manifest 沿用首次识别基准的原图 ID、路径和 SHA-256 格式。每张图只实际选择一次，失败不会自动重试或挑选较好的结果，弹窗只观察并取消，不进入聊天或解题。

该入口保留服务返回的模型/transport 指标，但未经独立绑定的远端自报指标标记为 `server_reported_unverified`；`actual_model_sends=null` 表示无法独立证实，不能写成 0 或成功调用。浏览器源码快照也不能代替测试服务源码证明。因此 observed-http 目前仍是实际上传观察工具，完整应用认证始终为 0；需要再与可信服务来源、真实 transport 账本、原图人工金标以及目标部署环境验收共同核对。

## 私有证据

输出包括运行 ID、源码快照及是否变化、逐次请求/响应摘要、原始首次响应 bytes、浏览器呈现分项观察、健康状态和隔离审计。合成模式还保存服务器接收的文件摘要、请求 ID 和首响应摘要，可与浏览器捕获一一绑定。浏览器核对全部返回面板、顶点原文、边实例、方向、重数、自环、权值、边名、线型、题干和待核对提示，以及原图预览 byte digest、白底和只读状态。

本工具没有原图答案库，不读取人工 gold 作为识别输入。合成验证通过不代表用户的 53 张原图已识别正确；未调用真实 Qwen/DeepSeek 时，不会宣称真实端到端识别通过。
