# 私有原图视觉 A/B 测试

生产默认仍为 Qwen3-VL-Plus；配置 ZHIPU_API_KEY 不会改变默认模型。Provider 支持显式选择 glm-4.6v-flash 或 glm-4.6v；两者不能自动切换。付费模型只用于用户已授权的对比运行。沿用 PP-DocLayoutV3、PP-OCRv6 Small、DeepSeek 与原有拓扑恢复算法。

历史共享契约的正式付费对比可用 `scripts/benchmark_graph_vision.py --glm-model glm-4.6v --glm-adapter baseline --experiments staged --thinking off --retries 0` 复现。先2张原图验证，再扩大同一批样本；Flash结果保留作补充。同图的两种 Provider 共享原图、预处理版面结果、提示词、裁图规则、NODE→EDGE→TRACE→全局关系→复核和 NetworkX 检查，固定 155 秒/7 次调用，每次最多45秒，失败重试计入总调用预算。串行执行，交替模型先后顺序。关闭思考的结果不与开启思考混合。

运行时必须在总计2CPU/4GiB cgroup 内。通过环境变量注入 ZHIPU_API_KEY、DASHSCOPE_API_KEY；日志不含密钥。Qwen 使用自己的 enable_thinking、stream_options；GLM 使用 thinking.type、do_sample 和官方支持的图片编码。两者在关闭思考时均启用原生 response_format=json_object；付费GLM已用原图真实请求验证此参数。早期未启用此参数的结果单独保存，不与正式结果混合。HTTP成功与输出可解析率分别统计。保存实际请求、耗时、API返回Token及未报告用量的覆盖范围；失败请求Token不估算为零。

清单、用户图片、独立真值和输出必须在仓库外。清单每个 cases 条目包括 id、image、sha256、source_kind=conversation_original、ground_truth 和 ground_truth_independently_reviewed=true。真值格式为 graphs 列表及 reference_status=complete；标注必须独立读取原图，不能来自任一待测模型。无标签顶点使用原图归一化坐标匹配。截图不参与，原图按SHA去重。

输出包含 comparison.md/json、details.csv、per-image-errors.json、逐条件原始结果和实际请求记录。边集按独立边实例比较端点和方向，不合并平行边；严格整图匹配还检查权值、边名、线型及顶点。失败、429、超时、格式无效和预算耗尽单列；模型比较使用同图均可评分的配对子集，并同时报告全样本完成率。有效但不完整的结构输出仍评分，不因为难图而排除。

`--experiments raw` 可用于额外的直接视觉实验，但不代替第一阶段同流程测试。`--inventory-only`、Mock、单元测试及HTTP200均不能证明真实OCR准确率。真实成绩只能引用带原图SHA及原始响应的实际运行。

实际Token是API报告用量，并非人民币账单。没有可靠的当前单价或账单回执时，费用必须标记待核实，不编造金额。原始请求及用量可供账单复核。

若默认时限造成有效配对不足，可在另一输出目录使用 `--vision-timeout 300 --call-timeout 90` 对两模型做相同的补充测试。预算写入条件指纹；不得与155/45秒结果混合。生产默认仍为155/45秒、7次调用。解析器仅去除外围1至3个反引号后校验整个JSON对象，禁止提取截断对象的内部片段；旧格式失败不能回填成通过。

本轮实际数据、明确选型及尚未通过的项目见 [开发与测试记录](GRAPH_NEXTGEN_STATUS.md)。最终固定批次为源提交c77f7ea，六原图两模型各27次真实请求；不用模拟测试或早期成功样本替代最终成绩。

## GLM 单独适配复测

`--glm-adapter native`（新默认）仅对显式注入的 GLM Provider 使用 `glm-native-v2` 契约：简化 EDGE 提示，区分连接关系和坐标观察；按同批共享观察 ID 合并重复引用，保留不同 ID 的平行笔画；不完整坐标只有与唯一高置信 OpenCV 线迹双向唯一匹配时才补全。原坐标和补全来源保存在 evidence，端点、方向、权值不由适配器修改，原有交叉点与端点校验仍生效。GLM的REVIEW还可以为已有候选ID补交完整路径，只有端点/中间顶点检查及原图墨迹覆盖、连续空白段检查通过后才接收；不创建边，不凭visible=true认证路径。原坐标与接受/拒绝原因保留。Qwen 的提示、默认调用路径、时限和生产配置不变。

`--glm-adapter baseline` 保留旧共享契约，便于复现。配置和代码哈希进入条件指纹，旧结果不会被覆盖或冒充适配后的结果。原始视觉实验不启用适配。单独复测使用 `--providers glm --glm-model glm-4.6v --glm-adapter native --experiments staged --thinking off --retries 0 --vision-timeout 300 --call-timeout 90`，先小批量再扩到先前固定原图。参考结构不进入提示词，适配前后比较须核对原图、版面和真值哈希；GLM 专用提示与旧版已不同，因此不是重新进行等价提示词的双模型能力排名。

适配首轮 `glm-native-v1` 的候选边F1提升，但很多边没有完整路径而保持pending。V2针对这一已记录限制增加上述复核路径接收；两版真实结果分目录保留，不能混合挑选每图最优。主表沿用原评分（含pending预测边）；报告同时列出仅accepted边的辅助分数，避免将候选识别等同于证据已经验证。

V3 (`glm-native-v3`) 用包含path/style字段的完整GLM REVIEW主格式替换原先附加提示，精简重复观察上下文，保留箭头/像素冲突、原图尺寸和坐标系。像素圆点清单不足以整图对齐时，仅对距离≤0.06、双方最近且次近距离差≥0.02的独立现有顶点做局部锚定；保留未锚定ID，不增删顶点。Qwen仍使用原提示与整图锚定。V3复测必须放在新目录，除候选F1外报告path字段实际覆盖、墨迹验证命中、accepted覆盖和时限，不能用提示词修改本身证明适配成功。

V3两张原图小批量均出现嵌套REVIEW的JSON闭合错误，已保留为格式失败，未修补JSON后计通过。`glm-native-v4` 改用扁平decisions输出，每条明确graph_id，completed_graph_ids另列；只在完整JSON解析成功后按图分组，不猜测多图中缺失的graph_id。Qwen的旧格式及解析行为不变。V4必须另存新条件，不能回填V3失败。

V5 (`glm-native-v5`) 在坐标锚定不足或顶点近乎重叠时，增加一次有预算的NODE圆点ID选择：第一张仍为原图，第二张仅标注OpenCV圆点候选，GLM选择现有顶点对应的marker_id，坐标由真实像素候选取回。近重合候选先去重，文字圆圈不能自动成为顶点；每图须完整一一映射，不重用圆点、不增删顶点、不改标签，不完整映射保留原坐标并标记未解决。仍共用7次总调用上限，相应减少EDGE批次数量，不能突破资源或请求预算。V4的JSON及路径收益、教材退步均保留，V5独立复测。

V6 (`glm-native-v6`) 明确要求每个候选ID都有判定，重复笔画的额外ID须返回false，不能只列确认项；边的独立线迹与多边拼成的通路严格区分。单图预留复核在剩余预算内同时覆盖遗漏项和箭头冲突，不依据省略自动删除候选，预算用尽仍保留pending。多图判定继续以graph_id隔离，Qwen旧流程不改。V5中真实边全部验证但早期未核重复观察仍留在edges的案例单独保存，不能拿accepted分数替换候选分数冒充整图全对。

本轮V6的5张成功同图配对F1低于V2，故默认 `--glm-adapter native` 恢复为 `glm-native-v2`，新流程仅通过 `--glm-adapter experimental`（Python `glm_adapter='experimental'`）显式启用。`baseline`仍是旧共享契约，Qwen默认不变。六张历史响应的离线回放验证默认V2与6562c17的提示、输入图片SHA和输出逐项相同；这是兼容性机制检查，不是新增真实识别成绩。V6实测源提交为947864a，当时native指向V6；复现实验应检出该提交或使用experimental的新输出目录，不能用当前native覆盖旧指纹。
