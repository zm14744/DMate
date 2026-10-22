# 私有原图视觉 A/B 测试

生产默认仍为 Qwen3-VL-Plus；配置 ZHIPU_API_KEY 不会改变默认模型。Provider 只添加 glm-4.6v-flash，不调用付费 glm-4.6v。沿用 PP-DocLayoutV3、PP-OCRv6 Small、DeepSeek 与原有拓扑恢复算法。

第一阶段使用 `scripts/benchmark_graph_vision.py --experiments staged --thinking off`。同图的两种 Provider 共享原图、预处理版面结果、提示词、裁图规则、NODE→EDGE→TRACE→全局关系→复核和 NetworkX 检查，固定 155 秒/7 次调用，每次最多45秒，失败重试计入总调用预算。串行执行，交替模型先后顺序。关闭思考的结果不与开启思考混合。

运行时必须在总计2CPU/4GiB cgroup 内。通过环境变量注入 ZHIPU_API_KEY、DASHSCOPE_API_KEY；日志不含密钥。Qwen 使用自己的 enable_thinking、stream_options；GLM 使用 thinking.type、do_sample 和官方支持的图片编码。保存实际请求、耗时、API返回Token及未报告用量的覆盖范围；失败请求Token不估算为零。

清单、用户图片、独立真值和输出必须在仓库外。清单每个 cases 条目包括 id、image、sha256、source_kind=conversation_original、ground_truth 和 ground_truth_independently_reviewed=true。真值格式为 graphs 列表及 reference_status=complete；标注必须独立读取原图，不能来自任一待测模型。无标签顶点使用原图归一化坐标匹配。截图不参与，原图按SHA去重。

输出包含 comparison.md/json、details.csv、per-image-errors.json、逐条件原始结果和实际请求记录。边集按独立边实例比较端点和方向，不合并平行边；严格整图匹配还检查权值、边名、线型及顶点。失败、429、超时、格式无效和预算耗尽单列；模型比较使用同图均可评分的配对子集，并同时报告全样本完成率。有效但不完整的结构输出仍评分，不因为难图而排除。

`--experiments raw` 可用于额外的直接视觉实验，但不代替第一阶段同流程测试。`--inventory-only`、Mock、单元测试及HTTP200均不能证明真实OCR准确率。真实成绩只能引用带原图SHA及原始响应的实际运行。
