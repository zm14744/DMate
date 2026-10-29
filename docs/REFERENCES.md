# 参考资料与第三方来源

本页记录当前代码使用的主要项目、服务和知识内容来源。版本以 [Python 依赖](../requirements.txt)、[编排与工具依赖](../requirements-agents.txt)、前端加载地址及客户端构建文件为准；许可证说明见 [第三方清单](../THIRD_PARTY_LICENSES.md)。

## 知识内容

[knowledge_graph.json](../knowledge_graph.json) 的 `basis` 字段记录以下三项来源。项目据此整理课程术语、知识板块和建议学习顺序；这些来源不表示出版机构或高校认证了 DMate。

- [高等教育出版社《离散数学（第3版）》](https://xuanshu.hep.com.cn/front/book/findBookDetails?bookId=658daaba74ce561611bd9a4f)
- [MIT OpenCourseWare：Mathematics for Computer Science](https://ocw.mit.edu/courses/6-1200j-mathematics-for-computer-science-spring-2024/)
- [Kenneth H. Rosen：Discrete Mathematics and Its Applications](https://www.mheducation.com/highered/product/discrete-mathematics-and-its-applications-rosen.html)

图谱中的 `prerequisites` 是建议前置知识，不能当作严格的数学逻辑蕴含或学生掌握度测量。

## 后端、图像与数学工具

| 来源 | 代码中的用途 |
|---|---|
| [Flask](https://flask.palletsprojects.com/)、[Gunicorn](https://gunicorn.org/)、[Requests](https://requests.readthedocs.io/) | Web 服务、生产进程及 HTTP 请求 |
| [PostgreSQL](https://www.postgresql.org/docs/)、[Psycopg 3](https://www.psycopg.org/psycopg3/docs/) | 配置数据库后的账号、验证码和云同步 |
| [PaddlePaddle](https://github.com/PaddlePaddle/Paddle)、[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) | 本地版面、文字和公式识别；实际路由见 [识别说明](RECOGNITION.md) |
| [OpenCV](https://docs.opencv.org/)、[Pillow](https://pillow.readthedocs.io/)、[NumPy](https://numpy.org/doc/) | 图片解码、裁剪及像素几何处理 |
| [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview)、[LangChain Core](https://reference.langchain.com/python/langchain_core/)、[JSON Schema](https://python-jsonschema.readthedocs.io/) | 应用内工作流、工具消息与结构校验 |
| [NetworkX](https://networkx.org/documentation/stable/)、[SymPy](https://docs.sympy.org/) | 已确认图结构和受限数学输入的计算 |
| [sknw](https://github.com/Image-Py/sknw)、[Numba](https://numba.readthedocs.io/)、[llvmlite](https://llvmlite.readthedocs.io/) | 可选骨架路径候选工具；候选路径不直接作为最终数学边 |

## 外部服务

- [DeepSeek API](https://api-docs.deepseek.com/)：文本教学回答。
- [阿里云百炼 / Model Studio](https://www.alibabacloud.com/help/en/model-studio/)：Qwen 图像理解和语音转写。实际模型名及选择条件见 [架构](ARCHITECTURE.md) 和 [识别说明](RECOGNITION.md)。
- [智谱开放平台](https://docs.bigmodel.cn/)：代码保留的可选 GLM 图像提供方。
- [Brevo 事务邮件 API](https://developers.brevo.com/docs/send-a-transactional-email)：配置后发送邮箱验证码；代码也支持 SMTP。

这些模型与邮件服务按各提供方的 API 和服务条款运行，不随项目源码重新分发。

## 前端与客户端

- [MathJax](https://docs.mathjax.org/)、[Marked](https://marked.js.org/)、[DOMPurify](https://github.com/cure53/DOMPurify)：公式、Markdown 和 HTML 清理。
- [html2canvas](https://html2canvas.hertzen.com/)、[jsPDF](https://github.com/parallax/jsPDF)：页面内容和 PDF 导出。
- [Tauri 2](https://v2.tauri.app/)、[Android WebView](https://developer.android.com/develop/ui/views/layout/webapps/webview)、[Apple WebKit](https://developer.apple.com/documentation/webkit)、[Snapcraft](https://documentation.ubuntu.com/snapcraft/stable/)：客户端包装与平台集成，构建入口见 [部署说明](DEPLOYMENT.md)。
