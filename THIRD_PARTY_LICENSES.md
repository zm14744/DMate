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

## 客户端分发与商店新增依赖（2026-10-13）

| 技术 / 平台 | 用途 | 注意事项 |
|---|---|---|
| Tauri 2（Rust / 桌面 WebView） | Windows NSIS、macOS DMG、Linux DEB/AppImage；Snap 封装的原始桌面程序 | Tauri 及其 Rust crates 的许可、实际打包随附库和系统 WebView 依赖需在发布时按版本生成清单，**不能只凭本表覆盖全部间接依赖**。 |
| Snapcraft + `core24` + GNOME 扩展 | 封装与在 Snap Store 发布 Linux AMD64 版 | Snap Store 分发遵循服务条款；`libwebkit2gtk-4.1-0` 等运行时依赖需按实际构建核对版权信息。 |
| Android SDK / Android WebView | Android 原生 APK 包装 | Android SDK、嵌入/系统 WebView 的权利及发行条款按官方资料和最终打包清单核验。 |
| Apple Safari / WebKit PWA | iOS 主屏幕 Web App | 非 IPA；浏览器/系统行为不等于项目再分发 WebKit 二进制。 |
| PWAStore / Product Hunt / Uptodown / Microsoft Store | 展示与分发平台 | 提交/审核状态不改变项目源代码和第三方组件的许可证义务。 |

截至本次文档整理，不能仅凭 GitHub 仓库公开可读就声称 DMate 源代码具有某一特定开源许可；若要对外使用“open source project”字样，应先确认仓库已明确提供相应许可证。
