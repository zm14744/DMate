# 私有原图视觉 A/B 测试

生产默认仍为 Qwen3-VL-Plus；配置 ZHIPU_API_KEY 不会改变默认模型。Provider 支持显式选择 glm-4.6v-flash 或 glm-4.6v；两者不能自动切换。付费模型只用于用户已授权的对比运行。沿用 PP-DocLayoutV3、PP-OCRv6 Small、DeepSeek 与原有拓扑恢复算法。

正式付费对比使用 `scripts/benchmark_graph_vision.py --glm-model glm-4.6v --experiments staged --thinking off --retries 0`。先2张原图验证，再扩大同一批样本；Flash结果保留作补充。同图的两种 Provider 共享原图、预处理版面结果、提示词、裁图规则、NODE→EDGE→TRACE→全局关系→复核和 NetworkX 检查，固定 155 秒/7 次调用，每次最多45秒，失败重试计入总调用预算。串行执行，交替模型先后顺序。关闭思考的结果不与开启思考混合。

运行时必须在总计2CPU/4GiB cgroup 内。通过环境变量注入 ZHIPU_API_KEY、DASHSCOPE_API_KEY；日志不含密钥。Qwen 使用自己的 enable_thinking、stream_options；GLM 使用 thinking.type、do_sample 和官方支持的图片编码。两者在关闭思考时均启用原生 response_format=json_object；付费GLM已用原图真实请求验证此参数。早期未启用此参数的结果单独保存，不与正式结果混合。HTTP成功与输出可解析率分别统计。保存实际请求、耗时、API返回Token及未报告用量的覆盖范围；失败请求Token不估算为零。

清单、用户图片、独立真值和输出必须在仓库外。清单每个 cases 条目包括 id、image、sha256、source_kind=conversation_original、ground_truth 和 ground_truth_independently_reviewed=true。真值格式为 graphs 列表及 reference_status=complete；标注必须独立读取原图，不能来自任一待测模型。无标签顶点使用原图归一化坐标匹配。截图不参与，原图按SHA去重。

输出包含 comparison.md/json、details.csv、per-image-errors.json、逐条件原始结果和实际请求记录。边集按独立边实例比较端点和方向，不合并平行边；严格整图匹配还检查权值、边名、线型及顶点。失败、429、超时、格式无效和预算耗尽单列；模型比较使用同图均可评分的配对子集，并同时报告全样本完成率。有效但不完整的结构输出仍评分，不因为难图而排除。

`--experiments raw` 可用于额外的直接视觉实验，但不代替第一阶段同流程测试。`--inventory-only`、Mock、单元测试及HTTP200均不能证明真实OCR准确率。真实成绩只能引用带原图SHA及原始响应的实际运行。

实际Token是API报告用量，并非人民币账单。没有可靠的当前单价或账单回执时，费用必须标记待核实，不编造金额。原始请求及用量可供账单复核。

若默认时限造成有效配对不足，可在另一输出目录使用 `--vision-timeout 300 --call-timeout 90` 对两模型做相同的补充测试。预算写入条件指纹；不得与155/45秒结果混合。生产默认仍为155/45秒、7次调用。解析器仅去除外围1至3个反引号后校验整个JSON对象，禁止提取截断对象的内部片段；旧格式失败不能回填成通过。

本轮实际数据、明确选型及尚未通过的项目见 [开发与测试记录](GRAPH_NEXTGEN_STATUS.md)。最终固定批次为源提交c77f7ea，六原图两模型各27次真实请求；不用模拟测试或早期成功样本替代最终成绩。
