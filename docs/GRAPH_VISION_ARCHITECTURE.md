# DMate 图论图形识别：像素证据 + 视觉复核架构（2026-10-22）

## 范围及保护原则

本改动只涉及离散数学图论图片识别，不更改账户、聊天、解题、知识图谱、客户端、下载或原有 OCR 文字处理逻辑。视觉模型固定使用原有的 `qwen3-vl-plus` 和既有 `DASHSCOPE_API_KEY`。不创建昂贵的图论题库 GitHub Actions。

## 当前工作流

```text
题目截图
 ├── 原有 OCR（PaddleOCR 识字/公式，原有文字模型链路保持不变）
 └── graph_recognition.py（原有多种 OpenCV 顶点/直线检测器）
        └── graph_line_tracer.py（新增）
             ├── RGB/HSV + 反色背景掩码
             ├── Guo–Hall thinning（opencv-contrib），无此接口时形态学骨架备用
             ├── 带切线连续性约束的线迹追踪（经过普通交叉不自动新增顶点）
             └── 高覆盖率直线边候选（中途存在真实顶点则阻止跨点合边）
                 ↓ 只产生未确认的 path evidence；绝不直接修改 confirmed_edges
        └── graph_structure.py（按图编号、顶点与采样路径建立有界证据）
               ↓ 图结构提示 + 初始 CV 证据 + 新增路径证据，最多 3000 字符新增证据
          Qwen3-VL-Plus（原有单次视觉请求）
               ↓ JSON 顶点/边表
          ai.py 现有严格图结构规范化
               ↓
          graph_validation.py（NetworkX 数据一致性审查）
               ↓
          app.py 现有图文核对与校验流程
```

## 几条必须遵守的约束

1. **几何证据不是数学真值**：一条线经过交叉点不自动产生顶点；模型也不能因为预期树、同构、完全图等答案去补边。
2. **路径是候选**：`line_path_evidence` 中的 `needs_review=true` 保留至 Qwen/人工确认，不进入原始 CV 确认边表。路径 `score` 是启发式线迹质量，不是校准后的真实概率。
3. **不同子图要分开**：所有路径依据原有 CV 节点集合的 `id` 独立生成，不通过连通分量直接拆分一张数学图。
4. **失败降级**：追踪模块导入失败、异常或没有结果，保留原图结构与原 Qwen 路线。没有 OpenCV 顶点时，本层不冒充能识别所有顶点。
5. **成本**：新增路径层不调用远程模型。Qwen 候选路径证据总长度默认不超过 3000 字符；保留原有的图片裁剪和费用日志。现有条件式独立视觉复核尚未全面重构，不能宣称所有请求只计费一次。
6. **回滚**：默认启用；若路径层与特定图发生兼容性问题，可临时设置 `GRAPH_PATH_EVIDENCE_ENABLED=false` 关闭新增路径层。该设置完全可选，不增加普通部署的必填环境变量。

## 本轮验证范围（非全面验收）

- 离线合成交叉线图片（浅底/深底）：两条交叉笔画沿原线路径追踪，不凭空产生中心节点。
- 使用用户 2026-10-21 提供的两张课件图进行少量离线候选路径检查；新模块能产生边连接候选，但仍会漏掉某些交叉/曲线边。
- **未执行付费 Qwen API、未运行高校大规模题库、未证明任何题库总体准确率。**

## 后续算法阶段

优先：像素级真实节点附近的入线/出线区分、自环检测、箭头尖端与反向追踪、曲线分叉路径搜索、子图切分；再结合对照标注的用户失败样本做节点/边 precision、recall、F1 和完整图一致率，最后再考虑学习型候选边分类器。

## 研究思路来源（借鉴算法，不复制项目代码）

- Optical Graph Recognition (JGAA 2013): https://jgaa.info/index.php/jgaa/article/view/paper303
- Optical Graph Edge Recognition (2018): https://www.scitepress.org/Papers/2018/65504/
- VisAdj (CIKM 2026): https://github.com/Jiahao-Xie-86/VisAdj
- FlowExtract: https://github.com/guille-gil/FlowExtract
- Diagram2Graph: https://github.com/Zackriya-Solutions/diagram2graph
- OpenCV ximgproc thinning: https://docs.opencv.org/4.x/df/d2d/group__ximgproc.html
- NetworkX graph classes: https://networkx.org/documentation/stable/reference/classes/index.html

## 2026-10-22 专项改进：边追踪与证据融合

- 扩展顶点外围路径扫描范围，避免裁掉外弧线或返回原顶点的自环。
- 对骨架路径加入保守的外部返回检测；普通圆点轮廓不能直接构成自环。
- 高覆盖率直线候选新增最长缺口检查，降低不连续线段被拼成边的风险。
- 同一端点对允许最多 3 条几何上明显不同的候选线迹；同笔画反向追踪去重，不把候选直接变成重边。
- `graph_structure.py` 按子图轮流分配有限的 Qwen 候选证据预算，优先提供尚未进入 OpenCV 确认边集的路线，保留 `path_variant`。
- 新增 `graph_evidence_fusion.py`：只有顶点归一化坐标能可靠匹配，且两种 OpenCV 像素检测器严格一致或蓝色空心多图像素检测足够可靠时，才对照 Qwen 返回的边集。分歧展示为待核对，不擅自改边。
- `app.py` 把上述分歧放进识别弹窗的图形描述，并继续保留现有原始边集及已有答题链路。

### 有界离线检查

仅使用本地构造的小型节点-线条图，不调用 Qwen API：无顶点交叉的两斜线、中心有真实顶点的四条边、带两对角线的四边形、折线弧线、返回同一顶点的外部自环、端点相同的直线加外弧线，以及中间存在大空隙的不连通线条。观察到的端点候选与这些用例的预期相符；平行线迹同端点保留两条。**这些检查不证明原课件 21 张失败图片全部通过，也不验证有向箭头端点和所有曲线类别。**

### 剩余事项

- 有向边箭头尖端检测和反向追踪仍需要专门算法；新模块没有声称已解决所有有向图。
- 学习式 VisAdj 候选边分类器尚未训练/部署；当前使用像素路径与候选排序的轻量实现。
- 复杂图像的 Qwen 实际 API 效果、Token 消耗及线上部署仍未验收。
- 不重新启用已经停用的高校题库测试工作流；仅进行小规模局部离线验证。
