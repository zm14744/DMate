# DMate

DMate 是离散数学智能辅学应用，将文字提问、图片识题、图形绘制、AI 练习、错题订正、概念笔记和学习报告放在同一工作区。

网页版入口：<https://dmate.zeabur.app/>。Android WebView 和 Windows、macOS、Linux 的 Tauri 客户端打开同一远程网站，AI、识图、账号与同步需要联网。

## 能做什么

- **教学对话**：提示引导、完整解析、概念讲解、出题和答案诊断。解题默认先给提示，明确要求后再提供完整答案。
- **图片工作区**：每批最多 4 张，逐张识别与核对；支持文字框、图形框、自主选择来源，以及把多张图分成一道题。
- **独立绘图**：编辑顶点、边、箭头、权值、边名和布局，保留本机历史，导出 PNG，或上传当前结构后提问。
- **学习整理**：错题订正与同类复测、可搜索的概念笔记本、按现存记录生成的学习报告。
- **知识图谱**：10 个模块、68 个节点，展示相关知识和建议前置关系，不计算学生掌握度。
- **语音与外观**：语音先转为可编辑文字；支持跟随系统、白色、黑色、蓝色主题及背景、透明度设置。

发送文字前可用“题目：是 / 否”明确是否收录为题目；图片在“分组”中分别设置题目标记。游客的聊天、错题和笔记仅留在当前页面；登录后可缓存并云同步。独立绘图库始终只保存在当前浏览器，游客绘图也会持久保存。具体操作与存储区别见[使用指南](docs/USER_GUIDE.md)。

## 技术与模型

后端为 Python 3.10、Flask、Gunicorn；前端为原生 JavaScript，使用 MathJax 显示公式。账号与同步使用 PostgreSQL，邮件使用 Brevo 或 SMTP。

当前网页自动识图使用 **`qwen3.8-flash`**，按需对局部连线复核；文字框识别使用隔离的 PaddleOCR CPU worker。教学、出题、笔记和绘图指导使用 DeepSeek，默认文本模型 **`deepseek-flash`**。语音使用 **`qwen-audio-3.1-asr-flash`** 和配置的数学词库。服务端还保留其他显式识别路径，详见[识别流程](docs/RECOGNITION.md)。

识图结果需要对照原图核对，特别是箭头、交叉、重边、自环和权值。结构校验、用户确认和局部数学计算不能保证模型读图或所有解答正确。

## 本地启动

服务端以 Linux + Python 3.10 为运行基线，需要 Dockerfile 中列出的 OpenCV / Paddle 系统库。Windows 自托管请使用 WSL2 或 Linux 容器；多平台客户端只打开远程网站，不在本机运行这个服务端。依赖安装和模型包下载需要网络，不会在安装时发起付费模型请求。

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

默认访问 <http://localhost:5000/>。启动前在运行环境配置所需服务：

| 功能 | 环境变量 |
| --- | --- |
| 教学、出题、笔记分析、绘图指导 | `DEEPSEEK_API_KEY` |
| 网页自动识图、语音 | `DASHSCOPE_API_KEY`；服务地域或工作空间不同还需设置对应服务地址 |
| 账号、云同步 | `DATABASE_URL`、`AUTH_SECRET_KEY` |
| 邮箱注册与邮箱找回 | Brevo 或 SMTP 配置 |

无数据库和账号密钥时仍可打开游客工作区；未配置模型凭据的功能会报配置错误。HTTP 本地账号调试还需设置 `SESSION_COOKIE_SECURE=0`，生产环境保持 HTTPS 和默认安全 Cookie。完整配置、模型缓存及容器启动方法见[部署说明](docs/DEPLOYMENT.md)。

## 文档

[文档索引](docs/INDEX.md) · [使用指南](docs/USER_GUIDE.md) · [架构](docs/ARCHITECTURE.md) · [API](docs/API.md) · [数据与隐私](docs/SECURITY_PRIVACY.md) · [macOS 分发](docs/MACOS_DISTRIBUTION.md) · [参考资料](docs/REFERENCES.md)

本文描述仓库当前实现；运行环境、商店版本与已安装客户端可能与源码不同。
