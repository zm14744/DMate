# 第三方依赖、模型与服务说明

本文件是当前主要依赖的索引，不替代发行包中完整的版权声明、许可证和 NOTICE。实际 Python 版本约束见 [requirements.txt](requirements.txt) 与 [requirements-agents.txt](requirements-agents.txt)；客户端依赖以各自构建清单为准。

## Python 组件

| 组件 | 当前版本约束 | 主要许可证与来源 |
|---|---|---|
| Flask | 3.1.2 | [BSD-3-Clause](https://github.com/pallets/flask/blob/main/LICENSE.txt) |
| Requests | 2.32.5 | [Apache-2.0](https://github.com/psf/requests/blob/main/LICENSE) |
| Gunicorn | 23.0.0 | [MIT](https://github.com/benoitc/gunicorn/blob/master/LICENSE) |
| PaddlePaddle / PaddleOCR | 3.3.1 / 3.7.0 | [PaddlePaddle](https://github.com/PaddlePaddle/Paddle) 与 [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) 的 Apache-2.0；模型权重另按对应模型说明处理 |
| PaddleX | 3.7.2 | [Apache-2.0](https://github.com/PaddlePaddle/PaddleX/blob/release/3.7/LICENSE)，提供模型包和前后处理 |
| ONNX Runtime | 1.23.2 | [MIT](https://github.com/microsoft/onnxruntime/blob/v1.23.2/LICENSE)，用于本地文字 CPU 推理；随附第三方声明仍须保留 |
| ONNX | 1.17.0 | [Apache-2.0](https://github.com/onnx/onnx/blob/v1.17.0/LICENSE)，用于模型格式与检查 |
| Paddle2ONNX | 2.1.0 | [Apache-2.0](https://github.com/PaddlePaddle/Paddle2ONNX/blob/develop/LICENSE)，用于构建时转换同一套文字模型权重 |
| NumPy | 1.26.4 | [BSD-3-Clause](https://github.com/numpy/numpy/blob/main/LICENSE.txt) |
| OpenCV contrib | 4.10.0.84 | [OpenCV Apache-2.0](https://opencv.org/license/)；wheel 内其他组件另有随附许可 |
| Pillow | 11.3.0 | [MIT-CMU](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| Psycopg | >=3.2.0,<4.0 | [LGPL-3.0](https://github.com/psycopg/psycopg/blob/master/LICENSE.txt) |
| NetworkX | >=3.4,<4.0 | [BSD-3-Clause](https://github.com/networkx/networkx) |
| LangGraph / LangChain Core / LangSmith | requirements-agents.txt 中固定版本 | 各项目的 MIT 许可：[LangGraph](https://github.com/langchain-ai/langgraph)、[LangChain](https://github.com/langchain-ai/langchain)、[LangSmith SDK](https://github.com/langchain-ai/langsmith-sdk) |
| jsonschema 及规范/引用组件 | requirements-agents.txt 中固定版本 | [jsonschema](https://github.com/python-jsonschema/jsonschema) 等项目的 MIT 许可 |
| SymPy / mpmath | 1.14.0 / 1.3.0 | [SymPy](https://github.com/sympy/sympy) 与 [mpmath](https://github.com/mpmath/mpmath) 的 BSD 系列许可 |
| sknw / Numba / llvmlite | 0.15 / 0.61.2 / 0.44.0 | [sknw](https://github.com/Image-Py/sknw)、[Numba](https://github.com/numba/numba)、[llvmlite](https://github.com/numba/llvmlite) 的 BSD 系列许可 |

其他固定依赖及间接依赖同样受各自许可约束。分发时须根据实际安装和打包结果保留适用声明，不能只凭本表代替完整清单。

将 Paddle 官方权重转换为 ONNX 不改变权重来源或重新授权权重。镜像中保留的原模型与转换产物仍应按对应模型包的许可、模型说明及随附声明处理；执行引擎的 MIT / Apache-2.0 许可不能代替模型权重的许可。

## 网页直接加载的库

| 组件 | 当前版本 | 许可证与来源 |
|---|---|---|
| MathJax | 3.2.2 | [Apache-2.0](https://github.com/mathjax/MathJax) |
| Marked | 15.0.12 | [MIT](https://github.com/markedjs/marked) |
| DOMPurify | 3.2.6 | [Apache-2.0 或 MPL-2.0](https://github.com/cure53/DOMPurify) |
| html2canvas | 1.4.1 | [MIT](https://github.com/niklasvh/html2canvas) |
| jsPDF | 2.5.2 | [MIT](https://github.com/parallax/jsPDF) |

这些库当前从 jsDelivr 加载，服务可达性与缓存由浏览器和 CDN 决定。

## 模型与外部服务

- [DeepSeek](https://api-docs.deepseek.com/)：文本问答、讲解和相关文本任务；默认模型配置见 [部署说明](docs/DEPLOYMENT.md)。不承担当前网页图形识别。
- [阿里云百炼 / 通义千问](https://help.aliyun.com/zh/model-studio/)：当前图片图形识别和语音转写。自动图形识别使用 qwen3.8-flash，语音默认 qwen-audio-3.1-asr-flash；兼容视觉路径的配置与默认值见 [识别链路](docs/RECOGNITION.md)。远程模型按提供方服务条款使用，不随源码分发其权重。
- [智谱](https://open.bigmodel.cn/)：代码保留显式选择的兼容视觉适配器；仅配置密钥不会自动切换当前默认识别链路。
- [Brevo](https://developers.brevo.com/) 与 SMTP：账号邮箱验证码的发送通道，按部署配置启用。
- [PostgreSQL](https://www.postgresql.org/)：账号和用户云同步的数据存储服务。图形任务确认另用应用本地 SQLite，不应当作账号云数据库。

用户数据发送范围和保留方式见 [安全与隐私](docs/SECURITY_PRIVACY.md)。

## 客户端与分发

桌面端使用 [Tauri 2](https://tauri.app/) 和系统 WebView；Android 使用 Android SDK 与系统 WebView；Linux Snap 使用 Snapcraft、core24 和相应系统库。实际分发包中 Rust crates、系统库和工具链内容的许可应按构建产物核对。网站地址、商店链接或源码可读状态不等于对这些组件重新授权。

仓库当前没有声明覆盖 DMate 全部自有源码的整体开源许可证。本文件只说明第三方来源与义务，不授予项目自有代码的新许可。
