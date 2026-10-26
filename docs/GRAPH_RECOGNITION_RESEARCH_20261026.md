# 图论图片识别：研究依据与实现边界（2026-10-26）

> 本文保留研究来源及历史基线的采用记录。现行调用组织、工具接入和验收边界见 [DMATE_RECOGNITION_ARCHITECTURE.md](DMATE_RECOGNITION_ARCHITECTURE.md)，下文“两次视觉请求”等历史限制不代表当前架构。

## 目标和基线实现约束

这份记录支持 DMate 的真实图论图片识别重构。保留 PaddleOCR Small 文字识别、PP-DocLayoutV3 版面分析、Qwen3-VL-Plus 视觉识别和 DeepSeek 文字校正的分工。一次原图识别最多两次 Qwen 请求，不通过失败重试或反复识别挑选最佳答案。DeepSeek 不决定图的顶点、边、方向或重数。

上述调用次数描述本文对应的两轮基线。用户已进一步明确应用内插件与子智能体需求；
新设计将一次上传与内部调用次数分开，见 [DMate 工具与子智能体架构](DMATE_TOOL_AGENT_ARCHITECTURE_20261026.md)。
历史验收记录保持原样，新编排不能借用旧版测试结果声称已通过。

运行目标为 2 核 CPU、4 GB 内存。下文的可用性判断来自算法与依赖分析，不是该配置的实测性能保证。用户提供的原图、人工标准答案、模型原始响应均应保留在私有测试材料中，不随研究说明发布。

## 五类图像问题怎样处理

| 问题 | 输出的辅助证据 | 不应采取的做法 |
| --- | --- | --- |
| 颜色 | 原始 RGB、亮度对比、Lab 色差、HSV 彩色笔画候选 | 先统一灰度再永久丢掉彩色细线；将所有彩色区域当作边 |
| 透印 | 强墨迹、与强墨迹相连的弱笔画、剩余弱墨迹不确定层 | 根据浅灰阈值直接抹掉背面透印和正面浅线；声称单面图必然能分离两者 |
| 模糊 | 原图质量指标、梯度证据、有限锐化辅助图 | 用增强图中新增的线条确认原图不存在的边；把锐化叫作完整去模糊 |
| 分图 | 版面实例、子图候选、编号和留白证据、父子 ROI 与原图坐标映射 | 把一个版面 image/chart 框必然当作一幅数学图；裁图后丢失坐标 |
| 阴影 | 低频背景估计、照明归一化图、保留前景的墨迹证据 | 把阴影边界当作长边；去阴影时顺便去掉浅色笔画 |

原始图始终独立保留。预处理输出用于提出、定位和复核候选；最终边必须能回查原始像素。RGBA、LA 和带透明索引的图片先按实际透明度合成白底，不能直接 convert("RGB") 把透明底误当作黑色内容。EXIF 方向必须在坐标建立前统一。

## 研究来源与采用方式

以下 18 项是论文、作者仓库或官方文档。方法借鉴、实际依赖和未来实验项分别写明，避免把论文名称当作已部署能力。

| 编号 | 来源 | 可借鉴的机制 | 当前采用方式与限制 |
| --- | --- | --- | --- |
| 1 | [Optical Graph Recognition, JGAA 2013](https://jgaa.info/index.php/jgaa/article/view/paper303) | 预处理、分割、拓扑恢复、后处理；重点是边与顶点附着和交叉处处理 | CPU 方法借鉴。论文页面为 CC BY 4.0；未核实可直接作为 Python 依赖的官方实现 |
| 2 | [Optical Graph Edge Recognition, IVAPP 2018](https://www.scitepress.org/Papers/2018/65504/)；[全文](https://www.scitepress.org/publishedPapers/2018/65504/pdf/index.html) | 任意路由的边、密集交叉、实线与虚线处理 | 方法借鉴；没有把未核实许可的代码纳入项目 |
| 3 | [FlowExtract, APMS 2026 官方仓库](https://github.com/aixpert-rug/FlowExtract) | 图元检测与连通性分离；箭头归属与经典线追踪 | 借鉴边追踪，不额外安装 YOLO/EasyOCR。仓库代码 MIT，依赖许可另算。面向标准工业流程图，不能直接等同于弧线重边识别 |
| 4 | [VisAdj 论文](https://arxiv.org/abs/2608.21825)；[官方代码](https://github.com/Jiahao-Xie-86/VisAdj) | 高召回候选邻接选择；候选边之间的联合关系建模 | 只借鉴候选与冲突联合判断。官方包含 SAM 编码器、关系 Transformer 和训练流程；代码 MIT。没有部署该模型或复现其论文指标 |
| 5 | [Knossos and Ariadne 论文](https://arxiv.org/html/2610.04721v1)；[官方代码](https://github.com/bangwayne/knossos_Ariadne_Public) | 节点清单、按源分组的边提取、连接器几何分解 | 借鉴结构分解。代码 MIT，数据 CC BY 4.0，模型条款独立。原方法每组源节点单独调用，不能称为两调用方案 |
| 6 | [sknw](https://github.com/Image-Py/sknw) | 像素骨架转换为保存路径的 NetworkX 图；重边与闭环支持 | 可用的轻量候选依赖，BSD-3-Clause；依赖 NumPy、NetworkX、Numba。使用 multi=True/ring=True，原始轨迹阶段可用 full=False 保留实际附着位置 |
| 7 | [Skan 论文](https://pmc.ncbi.nlm.nih.gov/articles/PMC5816961/)；[官方代码](https://github.com/jni/skan) | 稀疏骨架图、路径与分支统计 | BSD-3-Clause，CPU 库。与 sknw 部分重叠，先借鉴稀疏表示和诊断，不要求同时引入两个库 |
| 8 | [scikit-image 骨架化文档](https://scikit-image.org/docs/stable/auto_examples/edges/plot_skeleton.html) | 保持像素连接性的细化；中轴与局部宽度 | 可用基础能力。骨架交叉点不是自动确认的数学顶点 |
| 9 | [Manuscript Bleed-through Removal via Hysteresis Thresholding, ICDAR 2009](https://scholars.duke.edu/publication/802371) | 阈值与墨迹再生长，处理透印和正面墨迹灰度重叠 | 借鉴为强弱墨迹分层；原手稿实验不能当作图论照片识别保证 |
| 10 | [Sauvola 局部二值化官方实现说明](https://scikit-image.org/docs/stable/auto_examples/segmentation/plot_niblack_sauvola.html) | 根据局部均值和标准差适应非均匀背景 | 可作辅助证据；不能由单一二值化决定浅线是否存在 |
| 11 | [Removing Shadows from Images of Documents, ACCV 2016 作者论文](https://web.ece.ucsb.edu/~psen/Papers/ACCV16_RemovingShadows.pdf) | 局部背景/文字颜色估计，形成匹配全局参考的增益图 | 借鉴 CPU 背景估计。近似均匀纸色假设不适用于所有彩色 PPT；未直接复制源码 |
| 12 | [Document Image Shadow Removal Guided by Color-Aware Background, CVPR 2023 官方代码](https://github.com/hyyh1314/BGShadowNet) | 颜色感知的背景估计与去阴影分开 | 仅借鉴机制；两阶段网络和较旧依赖未加入运行时，仓库页面未见明确代码许可证 |
| 13 | [OpenCV 色彩空间转换文档](https://docs.opencv.org/4.x/de/d25/imgproc_color_conversions.html) | RGB、HSV、Lab 的标准转换 | 沿用实际 OpenCV 依赖，支持亮度和颜色分离；转换本身不是图识别算法 |
| 14 | [L0-Regularized Intensity and Gradient Prior for Deblurring Text Images 作者项目](https://jspan.github.io/projects/text-deblurring/index.html) | 强度/梯度先验、模糊核估计、恢复伪影控制 | 研究参照。当前没有把迭代盲反卷积加入每图默认链路 |
| 15 | [DocRes, CVPR 2024 官方仓库](https://github.com/ZZZHANG-jx/DocRes)；[推理代码](https://github.com/ZZZHANG-jx/DocRes/blob/master/inference.py) | 背景图、Sobel 高频图、Sauvola 等任务提示与文档恢复分离 | MIT。借鉴确定性提示图，不加载 Restormer。当前官方代码有 CPU 回退，但未证明在 2 核 4 GB 上满足时延和内存目标 |
| 16 | [无参考模糊指标及原论文引用](https://scikit-image.org/docs/stable/auto_examples/filters/plot_blur_effect.html) | 通过再模糊的变化估计模糊强度 | 质量诊断参照；当前轻量实现记录 Laplacian/梯度指标，不能声称实现了此论文的完整指标 |
| 17 | [PP-DocLayoutV3 官方文档](https://paddlepaddle.github.io/PaddleX/latest/en/module_usage/tutorials/ocr_modules/layout_analysis.html) | 版面框、实例轮廓和阅读顺序，包含图、图表、正文、公式等 25 类 | 保留实际依赖；版面实例仍需数学子图细分。官方模型存储 126 MB 不等于进程内存；其 A100 时延不能冒充 2 核 CPU 时延 |
| 18 | [NetworkX MultiGraph](https://networkx.org/documentation/stable/reference/classes/multigraph.html) | 独立边 key、重边和自环；有向情况使用 MultiDiGraph | 沿用实际依赖做表示和检查；度数和、连通性等只能校验，不得反向编造缺失边 |

### 必须保留的研究边界

- FlowExtract 官方报告 Edge F1 为 66.7%、Edge Precision 为 85.5%，并明确面向人工补全的工作流，不能据此宣传自动全对。
- Ariadne 附录说明源节点目标组大小为 3；30 图效率切片中分阶段方案平均 5.23 次调用/图。DMate 将所有源节点装入一次第二阶段请求，只能称为借鉴其分解思想，不能称为复现。
- VisAdj 的训练模型、Ariadne 的适配器、DocRes 的恢复网络、BGShadowNet 的网络均没有因为被引用而成为生产依赖。
- sknw/Skan 是像素骨架工具，不理解题目顶点。交叉点、箭头尖端、字体笔画、短小噪声都可能成为骨架节点，需要独立的数学顶点附着与路径裁决。

## 两次视觉请求和本地处理的职责

1. 本地安全解码、EXIF 与透明度处理，建立原始坐标；分析颜色、阴影、弱墨迹、模糊质量；PaddleOCR/PP-DocLayoutV3 提供文字与版面证据。
2. 第一轮 Qwen 在原图上给出固定子图/顶点清单、位置和标签。任何结构草稿均只作候选。
3. 本地细化定位，逐条追踪像素链；分开像素交叉口与数学顶点，保留独立重边、自环、箭头与路径证据。
4. 第二轮 Qwen 在固定清单上按源顶点枚举全部独立边，审核候选并报告漏边及其原图路径；一个请求包含所有子图/源顶点，不逐节点增加调用。
5. 本地做稳定 ID 绑定、原图路径核对、方向/重数裁决、数学一致性检查和统一展示。失败或不完整不触发隐藏重试。DeepSeek 只校正文字。

## image_evidence 的接口和证据语义

独立模块 image_evidence.py 提供安全解码和图像证据层。DocumentEvidence 保留全尺寸 original、工作尺寸 working、辅助 normalized/sharpened、工作尺寸 ink_mask/strong_ink/uncertain_ink、work_size、scale_xy、quality 与 diagnostics。所有掩膜为 uint8，0 表示背景，255 表示候选墨迹。

strong_ink 表示显著局部对比或色差；ink_mask 加入与强证据连通的弱笔画；uncertain_ink 保存其余弱笔画，包括无法仅凭像素区分的浅色正面线和透印。整图只有弱墨迹时保留候选并明确标记低对比，不能静默清空。锐化辅助图不参与建立原图墨迹证据。归一化和掩膜都不能单独认证图结构正确。

为避免棋盘背景、纸张纹理或透印接触一处强笔画后通过连通性扩散到整页，弱连通分量相对强种子的面积受到限制；超出部分仍留在 uncertain_ink，不会从原图中擦除。该限制也可能使真实的很长浅线保留为不确定候选，因此调用方不能把 ink_mask 之外的像素一概判为无边。

默认输入上限 16,000,000 像素，工作图最长边不超过 1600；输入更大时明确拒绝，工作图缩放后提供显式尺寸和坐标比例。处理单张图时不加载额外视觉网络。

## 原图验收

53 张原图的掩膜检查只能发现图像处理副作用，不等于 53 张图结构识别通过。最终版本应冻结后每张原图仅执行一次真实识别，记录子图归属、顶点、边端点、方向、重数、自环、权值/边名、题干公式、弹窗展示和完整性状态。不能从多次运行中挑选最好结果，不把 HTTP 成功、单元测试通过或边数相同当作原图正确。

### 本模块已完成的验证

- 19 项针对性像素测试通过：RGBA/LA/索引透明、部分透明、EXIF、输入上限与缩放坐标、清洁原图保持、暗底亮线、饱和深蓝背景、四色细线、渐变阴影、弱墨迹保留、纯浅线、弱纹理连通扩散、并行线白缝和自环孔、模糊辅助不覆盖原图。
- 对私有清单内 53 张原图进行图层处理：0 解码/处理异常，0 空 ink_mask。没有读取人工标准答案来决定图层输出，也没有执行视觉模型识别。
- 本机将 OpenCV 设为 2 线程的这次串行检查，53 图共 4.589 秒，单图最高 0.615 秒，进程峰值 RSS 约 408 MiB。这是本环境单独预处理的观测，不是受限 2 核/4 GB 容器的整链验收。
- 视觉抽查暴露并修复了两种副作用：饱和深蓝背景在辅助归一化中残留黄色；棋盘格纹理因弱连通扩散被大面积升级为墨迹。修复后复查真实样本，原始图仍独立保留，细线和闭环未被形态学闭运算填合。
- 仍然可见的限制：照片中的桌面纹理、图书封面的装饰几何等是真实高对比像素，通用墨迹掩膜会保留它们。必须由版面/子图归属和结构复核排除，不应假装仅靠去阴影即可解决。弱透印与纸张噪声在 uncertain_ink 中可能较密集，不能直接当作边清单。
