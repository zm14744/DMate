# AI 辅助开发说明

## 项目研发方式

DMate 开发全过程使用 OpenAI ChatGPT GPT-5.6 Sol 进行人工智能辅助开发。

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
OpenAI ChatGPT GPT-5.6 Sol
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

因此，ChatGPT GPT-5.6 Sol 不属于 DMate 当前面向最终用户提供回答的运行时基础模型。

## 表述原则

项目材料采用“AI 辅助开发”表述，不使用“全部代码由项目负责人纯手工编写”的表述；运行时使用的 DeepSeek、PaddleOCR、Brevo、PostgreSQL/Psycopg 与可选第三方算力通道均明确作为第三方技术或服务说明。
