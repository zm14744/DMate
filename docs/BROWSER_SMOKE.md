# DMate 线上浏览器测试（Playwright）

此测试运行**真实 Chromium 浏览器**访问 https://dmate.zeabur.app/ ，分别模拟桌面（1440×900）和手机（390×844）界面。

## 覆盖范围

- 首页能否正常打开（HTTP 状态、DMate 标题、文字输入框和发送按钮）
- 桌面端外观弹窗能否打开并关闭
- 手机端学习工具抽屉能否打开并关闭
- 两种设备中的知识图谱、错题本、学习回顾能否打开并关闭
- 知识图谱画布是否出现非“加载中”内容
- 实际截图、前端未捕获异常、本站 HTTP 5xx 请求和 Playwright 操作轨迹

**不进行 AI 提问、OCR 上传、账号注册或登录**，以避免调用收费接口或产生账号数据。浏览器测试不会验证数学推理或图形识别正确性。

## GitHub 上如何运行

在 **Actions → DMate Browser Smoke (Playwright) → Run workflow** 手动运行；修改 `tests/browser_smoke.py` 或工作流文件推送到 `main` 也会自动执行一次。浏览器测试不会触发构建安装包。

运行后在该次执行的 **Artifacts** 中下载 `dmate-playwright-browser-smoke`，其中包含：

- `report.json`：每步是否成功及前端 / 服务器错误
- `desktop-*.png` 和 `mobile-*.png`：真实浏览器截图
- `desktop-trace.zip` 和 `mobile-trace.zip`：可用 Playwright Trace Viewer 分析操作轨迹

需要本地运行时：

```bash
python -m pip install playwright==1.55.0
python -m playwright install chromium
python tests/browser_smoke.py
```

可使用 `DMATE_TEST_URL` 环境变量修改 HTTPS 测试地址。测试截图使用访客模式，主要用于排错和界面检查；应用商店发布前仍应检查截图是否清晰、是否真实对应最新部署版本。

**说明**：GitHub 提交成功不等于网站测试通过。需要查看该次 Actions 的执行状态和 `report.json`，才能判定线上网络、页面及交互是否正常。
