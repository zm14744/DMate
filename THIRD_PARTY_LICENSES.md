# 直接依赖与前端库许可证清单

本文件覆盖项目源代码中直接声明的 Python 依赖、`index.html` 中直接加载的前端库，以及运行时使用的主要外部服务。第三方项目著作权归相应权利人所有，许可证与服务条款以官方来源为准。

## Python 直接依赖

| 组件 | 项目使用版本 | 许可证 | 官方来源 |
|---|---:|---|---|
| Flask | 3.1.2 | BSD-3-Clause | https://flask.palletsprojects.com/en/stable/license/ |
| Requests | 2.32.5 | Apache-2.0 | https://github.com/psf/requests/blob/main/pyproject.toml |
| Gunicorn | 23.0.0 | MIT | https://github.com/benoitc/gunicorn/blob/master/LICENSE |
| PaddlePaddle | 3.3.1 | Apache-2.0 | https://github.com/PaddlePaddle/Paddle |
| PaddleOCR | 3.7.0 | Apache-2.0 | https://github.com/PaddlePaddle/PaddleOCR/blob/main/pyproject.toml |
| NumPy | 1.26.4 | BSD-3-Clause | https://github.com/numpy/numpy |
| OpenCV / opencv-contrib-python | 4.10.0.84 | Apache-2.0（OpenCV 4.5.0及以上） | https://opencv.org/license/ |
| Pillow | 11.3.0 | MIT-CMU | https://github.com/python-pillow/Pillow/blob/main/LICENSE |
| Psycopg 3 | `>=3.2.0,<4.0` | LGPL-3.0 | https://github.com/psycopg/psycopg/blob/master/LICENSE.txt |

## 前端直接加载库

| 组件 | 项目使用版本 | 许可证 | 官方来源 |
|---|---:|---|---|
| MathJax | 3.2.2 | Apache-2.0 | https://github.com/mathjax/MathJax |
| Marked | 15.0.12 | MIT | https://github.com/markedjs/marked/blob/master/package.json |
| DOMPurify | 3.2.6 | Apache-2.0 OR MPL-2.0 | https://github.com/cure53/DOMPurify |
| html2canvas | 1.4.1 | MIT | https://github.com/niklasvh/html2canvas/blob/master/package.json |
| jsPDF | 2.5.2 | MIT | https://github.com/parallax/jsPDF |

## 运行时第三方服务

### DeepSeek API

DMate 使用 DeepSeek Chat Completions 作为文本兜底与 Vision 运行服务。具体模型名由服务端环境变量控制，代码不把某个固定模型版本写死为产品自研能力。

- 文档：https://api-docs.deepseek.com/
- Chat Completions：https://api-docs.deepseek.com/api/create-chat-completion/

### 鲁信杯兼容文本接口（可选）

代码支持通过 OpenAI Chat Completions 兼容格式接入赛事算力，并提供模型发现、探测、熔断和 DeepSeek 自动兜底。该通道属于可选运行资源，不作为本项目重新分发的开源组件。

### Brevo Transactional Email

DMate 使用 Brevo API 作为邮箱验证码主发送通道，SMTP 可作为备用通道。Brevo 属于运行时外部服务，不随项目源码重新分发。

- 事务邮件 API：https://developers.brevo.com/docs/send-a-transactional-email

### PostgreSQL

账号和云同步使用 PostgreSQL 数据库；Python 连接层使用 Psycopg 3。数据库服务本身不随 DMate 源码重新分发。

- PostgreSQL：https://www.postgresql.org/
- Psycopg 3：https://www.psycopg.org/psycopg3/docs/

## 许可证处理方式

项目材料保留第三方框架、模型、服务与库的名称、版本和来源，不把第三方基础能力表述为项目自主研发成果。

分发第三方源代码或二进制内容时，应按对应许可证要求保留版权声明、许可证文本及 NOTICE 等适用内容。
