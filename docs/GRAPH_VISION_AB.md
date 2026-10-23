# 私有原图视觉 A/B 测试

生产默认仍为 Qwen3-VL-Plus；配置 ZHIPU_API_KEY 不会改变默认模型。Provider 支持显式选择 glm-4.6v-flash、glm-4.6v 或 glm-5.3-flash，不自动切换。模型只用于用户已授权的对比运行。沿用 PP-DocLayoutV3、PP-OCRv6 Small、DeepSeek 与原有拓扑恢复算法。

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
# 限时混合复核实验（显式启用）

`scripts/benchmark_graph_hybrid.py` 对相同原图分别真实运行单 Qwen 与
Qwen 主识别、GLM 局部复核。两条件各自调用真实 NODE/EDGE，不回放或复用另一条件的
模型输出；版面缓存和独立人工真值相同，模型不读取真值。执行顺序逐图交替。

两条件保留生产大小的 155 秒、最多 7 次请求、Qwen 单次 45 秒预算。
`HybridReview` 仅在方向、平行候选、权值或线迹冲突出现时，最多**替换一次**原有
REVIEW 调用；候选总数最多 24，付费 `glm-4.6v` 关闭思考、限时 25 秒、零重试。
没有新增串行调用，也不会失败后再追加 Qwen 重试。其他阶段和后续复核继续 Qwen。
GLM 提交的新路径仍须通过原图墨迹与几何校验，不能绕过 RELATE。
没有环境变量自动切换，网站调用未启用该实验。

运行时需要两种密钥及 2 CPU / 4 GiB 受限容器。将原图、真值、输出目录保存在仓库外：

```sh
python -B scripts/benchmark_graph_hybrid.py \
  --manifest /private/ab-manifest.json --output /private/hybrid-run \
  --layout-cache /private/layout-cache --case-ids CASE1,CASE2
```

`--stop-after 2` 先执行预声明样本的前两张；之后同协议 `--resume` 继续，原结果不覆盖。
预设时间目标：全部尝试的平均模块耗时不超过单 Qwen 的 1.2 倍，同时检查最大耗时、
完成率和准确率；不能以失败或限流的快速返回宣称提速。记录每阶段原始响应、模型版本、
usage、请求错误、输入 SHA、全部预测边及仅 accepted 边的辅助评分。失败单列、不给漏边分。
本工具仅覆盖真实拓扑模块；完整 `/ocr`、文字校正与 Playwright 验收须另外执行。
小样本独立 NODE/EDGE 可能波动，不能把全部成绩差值直接归因于局部复核模型。

## GLM-5.3-Flash 独立模型适配

官方 `/api/paas/v4/models` 目录确认模型ID为 `glm-5.3-flash`，不是 `glm-5.3-flashx`
或付费 `glm-5.3`。真实原图请求表明该模型**始终思考**：关闭时返回400/1210，
提示使用low/high/max。已成功验证 `thinking.type=enabled`、`reasoning_effort=low`、
`do_sample=false`，原图base64图像输入及SSE响应。文档站在当前网络不可达，以上依据
官方模型目录和真实接口反馈，不冒称完整文档已读取。

新配置强制显式开启思考，默认effort低档，拒绝对旧GLM/Qwen误传该参数。
已通过真实教材照片验证GLM 5.3可在开启思考时使用response_format=json_object。
早期没有JSON模式时会在根JSON之后追加说明，严格解析失败；不截取内层对象伪装成功。
新协议使用GLM支持的JSON模式；Qwen思考开启的请求不照搬此字段。
不传Qwen专属enable_thinking/detail/stream_options，也不将开启思考标为关闭。
记录实际reasoning_chars、完整usage及返回模型；拒绝FlashX/付费版/无模型身份替代。
思考Token已包含在completion_tokens时不能再次加总。费用不得套用旧glm-4.6v单价，
未取得5.3 Flash可靠单价前只列真实用量，人民币费用标为未核实。

独立新适配 `glm53-native-v2` 复用已验证V2的观察ID、唯一像素线绑定和原图墨迹检查，
保留NODE→EDGE→TRACE→RELATE→REVIEW，不启用退步的V6圆点实验，也不混用Qwen答案。
先小批量验证，再以同一批原图和独立真值做raw/staged，思考模式单独分组：

```sh
python -B scripts/benchmark_graph_vision.py \
  --manifest /private/ab-manifest.json --output /private/glm53-on \
  --providers glm,qwen --glm-model glm-5.3-flash --glm-reasoning-effort low \
  --qwen-thinking-budget 1024 \
  --thinking on --experiments both --retries 0 --vision-timeout 155 --call-timeout 45 \
  --layout-cache /private/layout-cache --case-ids CASE1,CASE2
```

两者开启思考的成绩与Qwen生产关闭思考参考必须分列。GLM为low，Qwen为显式1024思考预算，
不声称内部推理计算量相同。Qwen预算字段仅在显式选择时发送，关闭思考的生产请求不变。
首轮默认Qwen思考预算曾返回只有reasoning、没有最终JSON；不从思考文本提取答案，保留该
失败，再单独验证显式1024预算下的原图NODE成功。两种协议的成绩不能混用；新协议从头
建立独立结果目录，费用包含失败。关闭GLM 5.3思考会在本地配置阶段报错，不发无效API请求。
生产默认、混合复核实验模型、其他学习功能及Zeabur部署均未更改。

最终实测源de5f758、30条件。与生产Qwen关闭思考的同4图中，GLM低档staged F1为73.4%，
Qwen73.2%，宏平均为67.2%/76.6%；均完成5/6图，平均76.728/68.948秒。
不能用另外5图的“均开启思考”82.6%/63.0%冒充与生产默认的同图提升。
详细分图、方向、独立重边、权值和失败见状态文档；原图与原始响应只放私有证据，不提交仓库。
参考为原图独立视觉读取，本轮逐边复核但未新增第三方人类标注。没有上线或自动混合。

该次实验之后新增失败处理：上游finish_reason=network_error明确记为upstream_network_error，
即便已有可解析片段也不评分；GLM SSE超时保留已收到的部分原文/已报告usage，仍判传输失败。
未知Token不填零，不把片段修成答案。原de5f758结果保持原始标签与缺失数据，不回填无法恢复的片段。
新代码hash不同，复现旧记录应使用其源快照，后续新实验必须用新输出目录，不能混合resume。

