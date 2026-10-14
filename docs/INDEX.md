# 文档索引

- [`../README.md`](../README.md)：DMate 总览、核心功能、账号同步与运行方式
- [`PROJECT_INFO.md`](PROJECT_INFO.md)：项目基本信息与产品定位
- [`ARCHITECTURE.md`](ARCHITECTURE.md)：教学、模型路由、账号、云同步与数据流
- [`API.md`](API.md)：HTTP 接口、账号接口与云同步接口
- [`KNOWLEDGE_GRAPH.md`](KNOWLEDGE_GRAPH.md)：10 模块 / 68 节点知识图谱
- [`DEPLOYMENT.md`](DEPLOYMENT.md)：Zeabur、PostgreSQL、Brevo/SMTP、更新机制与环境变量
- [`SECURITY_PRIVACY.md`](SECURITY_PRIVACY.md)：游客 / 登录数据、安全与第三方数据流
- [`AI_ASSISTED_DEVELOPMENT.md`](AI_ASSISTED_DEVELOPMENT.md)：GPT-5.6 Sol 辅助研发说明
- [`THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md)：直接依赖、前端库与主要外部服务
- [`TESTING.md`](TESTING.md)：175项自测默认状态、历史回归、2026-10-13 实际离线核验、未验证的端到端范围
- [`RELEASE_CHECKLIST.md`](RELEASE_CHECKLIST.md)：发布前的核心学习、OCR、账号同步、桌面/移动端、回滚核对清单
- [`REVIEW_20261013.md`](REVIEW_20261013.md)：说明文档与 175 项用例对照源码的审校与勘误
- [`REFERENCES.md`](REFERENCES.md)：权威资料与官方技术来源
- [`CHANGELOG.md`](../CHANGELOG.md)：主要代码调整记录


**当前进度（更新至 2026-10-14）**：**Microsoft Store 审核通过且 DMate 已正式上架**（开发者确认）；itch.io 已 Public；Snap Store `dmate` 1.0.0 / Revision 1 已在 Stable 正式发行；Bing 已可公开检索到 DMate。PWA Directory 仍排队、百度审核/待索引、Uptodown 已拒。具体状态以 [`../README.md`](../README.md) 的分发表与 [`PROJECT_INFO.md`](PROJECT_INFO.md) 为准。

最新功能说明：OCR 非题目拦截和移动端交互见 [`API.md`](API.md)、[`ARCHITECTURE.md`](ARCHITECTURE.md)；部署与远程网页更新见 [`DEPLOYMENT.md`](DEPLOYMENT.md)；离线测试与未完成验收范围见 [`TESTING.md`](TESTING.md)。

## 2026-10-13 文档增补导航

- **新一轮工作记录**：根目录 `CHANGELOG.md` 的“2026-10-09—2026-10-13”章节，包括 GitHub Actions、Snap Stable、iOS PWA、商店/搜索引擎进展与最新 API 消费快照。
- **用户功能/支持平台**：`../README.md` 的“下载、PWA 与商店分发”；功能说明仍以原有“核心功能”章节为准。
- **平台构建与认证**：`DEPLOYMENT.md` 的新增第 10—12 节；注意发布凭据只保存在 GitHub Actions Secret。
- **浏览器/原生壳架构**：`ARCHITECTURE.md` 的新增第 17—18 节；接口补充见 `API.md`。
- **个人测试与发行验证分离**：`TESTING.md` 的新增第 10—11 节；不把商店发布或站长验证算作产品功能测试。
- **安全与第三方版权**：`SECURITY_PRIVACY.md` 第 14 节及 `../THIRD_PARTY_LICENSES.md` 新增分发依赖说明。
- **投入成本快照**：`PROJECT_INFO.md`（2026-10-13 DeepSeek 累计消费 ¥103.65、余额 ¥16.34）；10/8 旧值保留为历史。
