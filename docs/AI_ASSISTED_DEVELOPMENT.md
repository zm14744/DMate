# AI 辅助开发说明

## 项目研发方式

DMate 开发过程中使用 OpenAI ChatGPT 辅助研发。2026-10-08 以前的研发记录以 GPT-5.6 Sol 为当时主要辅助模型；2026-10-09—10-13 的构建、发布、PWA 与 SEO 阶段继续使用 ChatGPT 辅助。此处按时间记录不同研发阶段，不把其中任何一个辅助模型误标为 DMate 的生产运行模型。

**近期开发与发布记录：2026-09-28—2026-10-13**。其中 9/28—10/8 为功能研发集中期（11 天），10/9—10/13 为客户端和商店发行、iOS PWA 与 SEO 集中推进期（5 天）。项目负责人持续进行需求调整、运行验证、部署/发布、审核进度核对；AI 辅助输出必须经人工确认。该时间段不是项目全部研发周期。

AI 辅助覆盖：

- 产品需求与交互方案讨论；
- 软件架构设计；
- Python / JavaScript / HTML / CSS 代码生成与修改建议；
- 账号、云同步、邮箱验证与故障恢复方案讨论；
- Bug 定位与故障排查；
- OCR、数学公式渲染、PDF 导出和上下文机制分析；
- 离散数学知识图谱初始结构设计；
- 数学知识内容校核与图谱修订；
- 测试用例与定向回归检查设计；
- 技术资料与说明文档整理。

## 项目负责人职责

项目负责人朱明负责：

- 定义项目目标与实际需求；
- 决定功能取舍和产品交互；
- 审阅、选择和整合 AI 生成或建议的代码；
- 运行项目并定位实际行为；
- 进行代码迭代和版本管理；
- 配置第三方服务与部署环境；
- 执行功能自测；
- 对最终系统结果进行审查。

## 研发辅助模型与生产运行能力的区分

### 研发过程

```text
OpenAI ChatGPT（GPT-5.6 Sol 为前期记录；近期继续使用 ChatGPT）
```

作用：辅助研发、审校、测试设计与文档整理。

### 系统生产运行

文本生成采用可切换运行链路：

```text
可选鲁信杯兼容文本接口
        ↓ 不可用 / 熔断
DeepSeek Chat Completions
```

DeepSeek 文本模型通过 `DEEPSEEK_CHAT_MODEL` 配置；代码默认值为 `deepseek-flash`。

图片结构理解：

```text
DeepSeek Vision
模型由 DEEPSEEK_VISION_MODEL 配置
代码默认值：deepseek-flash
```

OCR：

```text
PaddleOCR
PP-OCRv6_small_det
PP-OCRv6_small_rec
PP-FormulaNet_plus-S
```

事务邮件：

```text
Brevo API
↓ 失败时
SMTP 备用
```

账号和云同步数据：

```text
PostgreSQL + Psycopg 3
```

因此，ChatGPT 研发辅助模型不属于 DMate 当前面向最终用户提供回答的运行时基础模型；生产侧使用的仍是外部文本与图像理解服务。

## 表述原则

项目材料采用“AI 辅助开发”表述，不使用“全部代码由项目负责人纯手工编写”的表述；运行时使用的 DeepSeek、PaddleOCR、Brevo、PostgreSQL/Psycopg 与可选第三方算力通道均明确作为第三方技术或服务说明。

## 2026-10-09—13 新一轮 AI 辅助开发与产品化工作

- 协助检查和修改 GitHub Actions 的桌面/Snap 构建发布流程，尤其修正重复上传 Snap 的逻辑，将已有 Store 修订提升至 Stable；GitHub Store Secret 由项目负责人管理，不在对话或文档中展示。
- 协助区分 Linux DEB、AppImage、Snap 对不同发行版/架构的适用条件，并完善网站安装说明。
- 分析 iOS Safari 主屏幕 PWA 的 Manifest / Service Worker / Apple 图标元信息，梳理与 App Store IPA 的区别和第三方目录提交策略。
- 协助整理应用商店状态、Product Hunt 宣传文案、百度/Bing 验证流程，添加站点 meta 并修复 Description / H1 / Alt 等可确定的 SEO 问题。
- 软件自身的功能性是否正确仍以代码、部署日志与用户实际设备验收为准；工具输出和成功提交不等于人工验收完成。
