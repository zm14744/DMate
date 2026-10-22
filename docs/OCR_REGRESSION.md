# DMate 图片识别真实浏览器回归测试

入口脚本：`tests/ocr_regression.py`。使用 Playwright 的**真实浏览器上传**图片，完全走用户界面已有的 `#imageInput` → `/ocr` → `#ocrReviewDialog` 流程。

## 两种运行模式

- `mock`（默认）：拦截 `/ocr` 并返回固定 JSON，验证浏览器上传、核对页显示、原始结果抓取和拓扑比对代码；**不调用识别模型**，可安全用于持续集成。模拟测试通过不证明图形识别准确。
- `live`：不拦截网络请求，调用部署网站的**真实付费 OCR / 视觉模型链路**。保存后端返回的 `text`、`visual_text`、`graph_display_data`、`graph_structures`，以及显示层的文字、图谱内容与 MathJax 数量、截图、操作 Trace 和差异报告。

**默认只做 OCR，不进入 AI 解题。** 用 `--solve` 才会在 OCR 之后实际点击“开始”调用 `/chat`，每次最多 2 张图片。

## GitHub Actions

打开 **Actions → DMate OCR Regression (Playwright) → Run workflow**，选择 `mock` 或 `live`，每次最多 3 张（CLI 上限 20），可选 `strict` 模式。工作流保存报告至 Artifacts，失败时也保留截图。

对于 live，每次实际识别都会产生模型调用和网络流量；不设置定时触发。正式上线后的正常提交只运行不收费的浏览器基础测试，不会自动执行 live OCR。

## 报告结构

- `report.json`：HTTP 状态、运行耗时、可视核对窗口文本、数学公式 SVG 数量、每项对照结果。
- `*-ocr-response.json`：OCR 接口结构化结果，便于查看真正的边、方向、重边及 CV 候选。
- `*-ocr-review.png`：真实浏览器识别核对截图。
- `*-trace.zip`：Playwright Trace，方便分析具体操作、请求与页面状态。
- `fixtures/*.png`：实际送入模型的原始图像。

判断规则**不把截图“能打开”当作“图形识别正确”**。仅当 OCR 返回经审核允许显示的 `graph_display_data` 时，才能进行顶点、边方向、重边的严格结构比对；否则报告 `unverified`，不能当成准确识别。普通 `visual_text` 的关键短语只能作为弱检查。

自带三张程序原创生成的练习图：有向三角图、带两条平行边的无向图、简单无向三角图。其标准答案来自图像生成逻辑，和模型输出相互独立。加入现实教材截图时，应遵循资料版权并确保能够共享，不要把有敏感信息的用户图像公开到 GitHub 仓库或 Actions Artifacts。

## 本地调用

```bash
python -m pip install playwright==1.55.0 Pillow==11.3.0
python -m playwright install chromium
python tests/ocr_regression.py --mode mock --limit 3 --strict
python tests/ocr_regression.py --mode live --limit 1 --strict
# 仅在明确需要额外付费解题时：
python tests/ocr_regression.py --mode live --limit 1 --solve
```

可用 `--cases tests/fixtures/graph_ocr_cases.json` 传入用户自己的 JSON 清单；图片字段写文件实际路径，生成样例可以直接写 `directed.png` 等。把预期顶点、边、方向和重边个数写进 `expected.graph` 字段。如果服务器响应错误或超时，报告会明确标注，不会冒充通过。

说明：`--strict` 将 `failed` 或 `unverified` 拓扑比对视为失败。默认无 `--strict` 时，命令以接口可用性为准，仍在报告中分别标注 `operational_ok` 和 `semantic_status`。OCR 识别算法和 UI 业务代码均未因此改动。
